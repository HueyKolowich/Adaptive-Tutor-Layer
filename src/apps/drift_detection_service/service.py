from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import statistics
import uuid

from django.db import transaction
from django.utils import timezone

from apps.drift_detection_service.models import DriftRun, DriftSignal
from apps.embedding_service.models import TurnEmbeddingIndex
from apps.ga_service.service import GAService
from apps.history_service.models import Conversation
from apps.ratings_service.models import TurnEvaluation, TurnFeedback
from common.observability import publish_state_event


EMBEDDING_SHIFT_THRESHOLD = 0.18
EMBEDDING_MIN_SAMPLES = 20
EMBEDDING_RECENT_LIMIT = 120
EMBEDDING_BASELINE_LIMIT = 360
QSCORE_DROP_THRESHOLD = 0.08
QSCORE_WINDOW_SIZE = 30
FEEDBACK_DROP_THRESHOLD = 0.15
FEEDBACK_WINDOW_SIZE = 30
GA_COOLDOWN_HOURS = 24
ACTIVE_USER_LOOKBACK_DAYS = 14


@dataclass(frozen=True)
class DriftMetric:
    signal_type: str
    score: float
    threshold: float
    breached: bool


class DriftDetectionService:
    def run_sweep(self, now=None) -> list[DriftRun]:
        now = now or timezone.now()
        active_since = now - timedelta(days=ACTIVE_USER_LOOKBACK_DAYS)
        user_ids = list(
            Conversation.objects.filter(updated_at__gte=active_since)
            .exclude(user_id='')
            .values_list('user_id', flat=True)
            .distinct()
        )

        runs = []
        for user_id in user_ids:
            runs.append(self.run_cycle_for_user(user_id=user_id, now=now))
        return runs

    def run_cycle_for_user(self, user_id: str, now=None) -> DriftRun:
        now = now or timezone.now()
        run = DriftRun.objects.create(
            scope='user',
            subject_user_id=user_id,
            status='running',
            started_at=now,
        )

        try:
            recent_start = now - timedelta(days=3)
            baseline_start = now - timedelta(days=14)
            signals = self.compute_signals(
                user_id=user_id,
                window_recent=(recent_start, now),
                window_baseline=(baseline_start, recent_start),
            )

            breached_count = 0
            created = []
            for signal in signals:
                if signal.breached:
                    breached_count += 1
                severity = 'medium' if signal.breached else 'low'
                created.append(
                    DriftSignal.objects.create(
                        drift_run=run,
                        signal_type=signal.signal_type,
                        severity=severity,
                        score=signal.score,
                        threshold=signal.threshold,
                        scope='user',
                        subject_user_id=user_id,
                        metadata_json={'breached': signal.breached},
                    )
                )

            high_severity = breached_count >= 2
            breached_signals = [row for row in created if row.metadata_json.get('breached')]
            if high_severity:
                for row in breached_signals:
                    row.severity = 'high'
                    row.save(update_fields=['severity'])

            trigger_signal_id = breached_signals[0].id if breached_signals else None
            ga_triggered, parent_prompt_id, variants_generated = self._maybe_trigger_ga(
                run=run,
                user_id=user_id,
                high_severity=high_severity,
                drift_signal_id=trigger_signal_id,
            )
            run.status = 'completed'
            run.ga_triggered = ga_triggered
            run.metrics_json = {
                'breached_count': breached_count,
                'high_severity': high_severity,
                'signal_count': len(created),
                'subject_user_id': user_id,
                'parent_prompt_id': parent_prompt_id,
                'variants_generated': variants_generated,
            }
            run.finished_at = timezone.now()
            run.save(update_fields=['status', 'ga_triggered', 'metrics_json', 'finished_at'])

            trace_id = str(uuid.uuid4())
            for row in created:
                publish_state_event(
                    event_type='drift.signal_detected',
                    conversation_id=f'user:{user_id}',
                    user_id=user_id,
                    trace_id=trace_id,
                    node='drift',
                    edge={'from': 'qscore', 'to': 'drift'},
                    payload={
                        'drift_run_id': run.id,
                        'subject_user_id': user_id,
                        'signal_type': row.signal_type,
                        'severity': row.severity,
                        'score': row.score,
                        'threshold': row.threshold,
                        'breached': bool(row.metadata_json.get('breached')),
                    },
                )

            publish_state_event(
                event_type='drift.run_completed',
                conversation_id=f'user:{user_id}',
                user_id=user_id,
                trace_id=trace_id,
                node='drift',
                edge={'from': 'qscore', 'to': 'drift'},
                payload={
                    'drift_run_id': run.id,
                    'subject_user_id': user_id,
                    'high_severity': high_severity,
                    'ga_triggered': ga_triggered,
                    'breached_count': breached_count,
                },
            )
        except Exception as exc:
            run.status = 'failed'
            run.finished_at = timezone.now()
            run.metrics_json = {'error': str(exc)[:200], 'subject_user_id': user_id}
            run.save(update_fields=['status', 'finished_at', 'metrics_json'])
            raise

        return run

    def compute_signals(
        self,
        user_id: str,
        window_recent: tuple,
        window_baseline: tuple,
    ) -> list[DriftMetric]:
        return [
            self._embedding_centroid_shift(user_id, window_recent, window_baseline),
            self._qscore_degradation(user_id),
            self._feedback_deterioration(user_id),
        ]

    def _embedding_centroid_shift(self, user_id: str, window_recent: tuple, window_baseline: tuple) -> DriftMetric:
        recent = list(
            TurnEmbeddingIndex.objects.filter(
                document_type='question',
                metadata_json__user_id=user_id,
                created_at__gte=window_recent[0],
                created_at__lte=window_recent[1],
            )
            .order_by('-created_at')[:EMBEDDING_RECENT_LIMIT]
            .values_list('embedding_json', flat=True)
        )
        baseline = list(
            TurnEmbeddingIndex.objects.filter(
                document_type='question',
                metadata_json__user_id=user_id,
                created_at__gte=window_baseline[0],
                created_at__lt=window_baseline[1],
            )
            .order_by('-created_at')[:EMBEDDING_BASELINE_LIMIT]
            .values_list('embedding_json', flat=True)
        )

        if len(recent) < EMBEDDING_MIN_SAMPLES or len(baseline) < EMBEDDING_MIN_SAMPLES:
            return DriftMetric('embedding_centroid_shift', 0.0, EMBEDDING_SHIFT_THRESHOLD, False)

        recent_center = _centroid(recent)
        baseline_center = _centroid(baseline)
        distance = _cosine_distance(recent_center, baseline_center)
        return DriftMetric(
            'embedding_centroid_shift',
            distance,
            EMBEDDING_SHIFT_THRESHOLD,
            distance > EMBEDDING_SHIFT_THRESHOLD,
        )

    def _qscore_degradation(self, user_id: str) -> DriftMetric:
        total_needed = QSCORE_WINDOW_SIZE * 2
        rows = list(
            TurnEvaluation.objects.filter(turn__conversation__user_id=user_id)
            .order_by('-created_at')
            .values_list('q_total', flat=True)[:total_needed]
        )
        if len(rows) < total_needed:
            return DriftMetric('qscore_degradation', 0.0, QSCORE_DROP_THRESHOLD, False)

        recent = rows[:QSCORE_WINDOW_SIZE]
        baseline = rows[QSCORE_WINDOW_SIZE:total_needed]
        score = statistics.mean(baseline) - statistics.mean(recent)
        return DriftMetric('qscore_degradation', score, QSCORE_DROP_THRESHOLD, score >= QSCORE_DROP_THRESHOLD)

    def _feedback_deterioration(self, user_id: str) -> DriftMetric:
        total_needed = FEEDBACK_WINDOW_SIZE * 2
        rows = list(
            TurnFeedback.objects.filter(user_id=user_id)
            .order_by('-created_at')
            .values(
                'rating_correctness',
                'rating_helpfulness',
                'rating_clarity',
            )[:total_needed]
        )
        if len(rows) < total_needed:
            return DriftMetric('feedback_deterioration', 0.0, FEEDBACK_DROP_THRESHOLD, False)

        recent = rows[:FEEDBACK_WINDOW_SIZE]
        baseline = rows[FEEDBACK_WINDOW_SIZE:total_needed]

        recent_low = _low_ratio(recent)
        baseline_low = _low_ratio(baseline)
        delta = recent_low - baseline_low
        return DriftMetric('feedback_deterioration', delta, FEEDBACK_DROP_THRESHOLD, delta >= FEEDBACK_DROP_THRESHOLD)

    @transaction.atomic
    def _maybe_trigger_ga(
        self,
        run: DriftRun,
        user_id: str,
        high_severity: bool,
        drift_signal_id: int | None,
    ) -> tuple[bool, int | None, int]:
        if not high_severity:
            return False, None, 0

        previous = DriftRun.objects.filter(
            scope='user',
            subject_user_id=user_id,
            status='completed',
            id__lt=run.id,
        ).order_by('-started_at').first()
        if previous is None:
            return False, None, 0

        if not bool((previous.metrics_json or {}).get('high_severity')):
            return False, None, 0

        cooldown_cutoff = timezone.now() - timedelta(hours=GA_COOLDOWN_HOURS)
        recent_trigger = DriftRun.objects.filter(
            scope='user',
            subject_user_id=user_id,
            status='completed',
            ga_triggered=True,
            started_at__gte=cooldown_cutoff,
        ).exists()
        if recent_trigger:
            return False, None, 0

        ga_service = GAService()
        parent_prompt = ga_service.resolve_parent_prompt_for_user(subject_user_id=user_id)
        if parent_prompt is None:
            return False, None, 0

        candidates = ga_service.generate_variants(
            parent_prompt_id=parent_prompt.id,
            subject_user_id=user_id,
            drift_signal_id=drift_signal_id,
            k=3,
        )
        if not candidates:
            return False, parent_prompt.id, 0

        publish_state_event(
            event_type='drift.ga_triggered',
            conversation_id=f'user:{user_id}',
            user_id=user_id,
            trace_id=str(uuid.uuid4()),
            node='drift',
            edge={'from': 'drift', 'to': 'ga'},
            payload={
                'drift_run_id': run.id,
                'subject_user_id': user_id,
                'parent_prompt_id': parent_prompt.id,
                'variants_generated': len(candidates),
            },
        )
        return True, parent_prompt.id, len(candidates)


def _centroid(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    dim = len(vectors[0])
    out = [0.0] * dim
    for vec in vectors:
        for idx, value in enumerate(vec):
            out[idx] += float(value)
    return [value / len(vectors) for value in out]


def _cosine_distance(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    anorm = sum(x * x for x in a) ** 0.5
    bnorm = sum(y * y for y in b) ** 0.5
    if anorm == 0.0 or bnorm == 0.0:
        return 0.0
    cosine = max(min(dot / (anorm * bnorm), 1.0), -1.0)
    return 1.0 - cosine


def _low_ratio(rows: list[dict]) -> float:
    if not rows:
        return 0.0
    low = 0
    for row in rows:
        avg = (
            float(row['rating_correctness'])
            + float(row['rating_helpfulness'])
            + float(row['rating_clarity'])
        ) / 3.0
        if avg <= 2.0:
            low += 1
    return low / len(rows)
