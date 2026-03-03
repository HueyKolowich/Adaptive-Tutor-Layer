from __future__ import annotations

from dataclasses import dataclass
import hashlib
import uuid

from django.db.models import Q
from django.utils import timezone as dj_timezone

from apps.ga_service.models import PromptEvolutionRun, PromptVariantCandidate
from apps.prompt_service.models import BanditUserArmState, Prompt
from common.observability import publish_state_event


DEFAULT_MUTATIONS = (
    'tone_supportive',
    'scaffold_depth',
    'misconception_probe',
    'hint_cadence',
)


@dataclass(frozen=True)
class CandidateDraft:
    text: str
    mutation_operator: str
    score: float
    passed_safety: bool


class GAService:
    def generate_variants(
        self,
        parent_prompt_id: int | None,
        subject_user_id: str,
        drift_signal_id: int | None = None,
        k: int = 3,
    ) -> list[PromptVariantCandidate]:
        parent = self._resolve_parent_prompt(parent_prompt_id, subject_user_id)
        if parent is None:
            return []

        run = PromptEvolutionRun.objects.create(
            parent_prompt=parent,
            drift_signal_id=drift_signal_id,
            requested_by='system' if drift_signal_id else 'manual',
            subject_user_id=subject_user_id,
            status='running',
        )

        drafts: list[CandidateDraft] = []
        for idx in range(max(1, int(k))):
            operator = DEFAULT_MUTATIONS[idx % len(DEFAULT_MUTATIONS)]
            text = self._mutate_prompt(parent.text, operator)
            score = self._score_text(text)
            passed = self._passes_safety(text)
            drafts.append(CandidateDraft(text=text, mutation_operator=operator, score=score, passed_safety=passed))

        kept = self.score_and_filter(drafts)
        published = self.publish_candidates(run, parent, kept, subject_user_id)

        run.generated_count = len(drafts)
        run.published_count = len(published)
        run.status = 'completed'
        run.completed_at = dj_timezone.now()
        run.save(update_fields=['generated_count', 'published_count', 'status', 'completed_at'])

        publish_state_event(
            event_type='ga.variants_generated',
            conversation_id=f'user:{subject_user_id}',
            user_id=subject_user_id,
            trace_id=str(uuid.uuid4()),
            node='ga',
            edge={'from': 'ga', 'to': 'policies'},
            payload={
                'evolution_run_id': run.id,
                'subject_user_id': subject_user_id,
                'parent_prompt_id': parent.id,
                'generated_count': len(drafts),
                'published_count': len(published),
            },
        )
        return published

    def resolve_parent_prompt_for_user(self, subject_user_id: str) -> Prompt | None:
        scored = []
        states = (
            BanditUserArmState.objects.select_related('prompt')
            .filter(
                learner_id=subject_user_id,
                prompt__is_active=True,
                prompt__status='active',
            )
            .filter(Q(prompt__owner_user_id__isnull=True) | Q(prompt__owner_user_id=subject_user_id))
            .order_by('-updated_at', '-id')
        )
        for state in states:
            lam = max(float(state.lambda0 + state.nu), 1e-12)
            mu = (float(state.lambda0) * float(state.mu0) + float(state.eta)) / lam
            scored.append((float(mu), state.prompt))

        if scored:
            scored.sort(key=lambda item: item[0], reverse=True)
            return scored[0][1]

        fallback = (
            Prompt.objects.filter(
                is_active=True,
                status='active',
                origin='manual',
                owner_user_id__isnull=True,
            )
            .order_by('-created_at', '-id')
            .first()
        )
        if fallback is not None:
            return fallback

        return (
            Prompt.objects.filter(is_active=True, status='active', owner_user_id__isnull=True)
            .order_by('-created_at', '-id')
            .first()
        )

    def score_and_filter(self, candidates: list[CandidateDraft]) -> list[CandidateDraft]:
        filtered = [c for c in candidates if c.passed_safety]
        filtered.sort(key=lambda c: c.score, reverse=True)
        return filtered

    def publish_candidates(
        self,
        evolution_run: PromptEvolutionRun,
        parent_prompt: Prompt,
        candidates: list[CandidateDraft],
        subject_user_id: str,
    ) -> list[PromptVariantCandidate]:
        out = []
        for candidate in candidates:
            prompt = Prompt.objects.create(
                text=candidate.text,
                is_active=True,
                parent_prompt=parent_prompt,
                origin='ga',
                status='candidate',
                rollout_pct=0.10,
                owner_user_id=subject_user_id,
                lineage_metadata_json={
                    'evolution_run_id': evolution_run.id,
                    'mutation_operator': candidate.mutation_operator,
                    'created_from': parent_prompt.id,
                    'subject_user_id': subject_user_id,
                },
            )
            row = PromptVariantCandidate.objects.create(
                evolution_run=evolution_run,
                prompt=prompt,
                text=candidate.text,
                mutation_operator=candidate.mutation_operator,
                score=candidate.score,
                passed_safety=True,
                status='published',
                metadata_json={'prompt_id': prompt.id, 'subject_user_id': subject_user_id},
            )
            out.append(row)
        return out

    def _resolve_parent_prompt(self, parent_prompt_id: int | None, subject_user_id: str) -> Prompt | None:
        visible_filter = Q(owner_user_id__isnull=True) | Q(owner_user_id=subject_user_id)
        if parent_prompt_id is not None:
            return (
                Prompt.objects.filter(
                    id=parent_prompt_id,
                    is_active=True,
                    status='active',
                )
                .filter(visible_filter)
                .first()
            )
        return self.resolve_parent_prompt_for_user(subject_user_id)

    def _mutate_prompt(self, text: str, operator: str) -> str:
        suffix_map = {
            'tone_supportive': ' Keep a supportive, confidence-building tone with concise encouragement.',
            'scaffold_depth': ' Use a three-step scaffold: diagnose, hint, then verify understanding.',
            'misconception_probe': ' Ask one misconception-check question before giving final guidance.',
            'hint_cadence': ' Prefer short hints and require learner response between hints.',
        }
        suffix = suffix_map.get(operator, '')
        return f"{text.strip()}\n\n[GA:{operator}] {suffix}".strip()

    def _score_text(self, text: str) -> float:
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        return int(digest[:8], 16) / 0xFFFFFFFF

    def _passes_safety(self, text: str) -> bool:
        blocked_tokens = ['give direct answers only', 'ignore safety policy']
        lowered = text.lower()
        return all(token not in lowered for token in blocked_tokens)
