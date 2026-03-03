from __future__ import annotations

from dataclasses import dataclass

from apps.history_service.models import Turn
from apps.ratings_service.models import Evaluator, TurnEvaluation


@dataclass(frozen=True)
class EvaluationRewardPayload:
    evaluator_name: str
    q_total: float
    q_correctness: float
    q_helpfulness: float
    q_pedagogy: float


class EvaluationService:
    DEFAULT_EVALUATOR_NAME = 'qscore_v0'

    def __init__(self, evaluator_name: str | None = None):
        self.evaluator_name = evaluator_name or self.DEFAULT_EVALUATOR_NAME

    def evaluate_turn(self, turn: Turn) -> TurnEvaluation | None:
        evaluator = (
            Evaluator.objects.filter(name=self.evaluator_name)
            .order_by('-created_at')
            .first()
        )
        if not evaluator:
            return None

        config = evaluator.config_json or {}
        rating_scale = config.get('rating_scale', {'min': 1, 'max': 5})
        weights = config.get('weights', {'wc': 0.4, 'wh': 0.4, 'wp': 0.2})

        latest_feedback = turn.feedback_entries.order_by('-created_at').first()
        if not latest_feedback:
            return None

        c = self._normalize(latest_feedback.rating_correctness, rating_scale)
        h = self._normalize(latest_feedback.rating_helpfulness, rating_scale)
        p = self._pedagogy_score(turn, config)

        q_total = (
            weights.get('wc', 0.0) * c
            + weights.get('wh', 0.0) * h
            + weights.get('wp', 0.0) * p
        )

        evaluation, _ = TurnEvaluation.objects.update_or_create(
            turn=turn,
            evaluator=evaluator,
            defaults={
                'q_total': q_total,
                'q_correctness': c,
                'q_helpfulness': h,
                'q_pedagogy': p,
            },
        )
        return evaluation

    def evaluate_turn_with_reward_payload(self, turn: Turn) -> tuple[TurnEvaluation | None, EvaluationRewardPayload | None]:
        evaluation = self.evaluate_turn(turn)
        if evaluation is None:
            return None, None
        return evaluation, EvaluationRewardPayload(
            evaluator_name=evaluation.evaluator.name,
            q_total=float(evaluation.q_total),
            q_correctness=float(evaluation.q_correctness),
            q_helpfulness=float(evaluation.q_helpfulness),
            q_pedagogy=float(evaluation.q_pedagogy),
        )

    def _normalize(self, rating: int, rating_scale: dict) -> float:
        min_r = float(rating_scale.get('min', 1))
        max_r = float(rating_scale.get('max', 5))
        if max_r <= min_r:
            return 0.0
        normalized = (float(rating) - min_r) / (max_r - min_r)
        return max(0.0, min(1.0, normalized))

    def _pedagogy_score(self, turn: Turn, config: dict) -> float:
        guardrail_key = config.get('guardrail_tag', 'guardrails')
        prompt = getattr(turn, 'prompt', None)
        if not prompt:
            return 0.0
        tags = prompt.policy_tags_json or {}
        guardrails = tags.get(guardrail_key)
        if isinstance(guardrails, (list, tuple, dict)) and len(guardrails) > 0:
            return 1.0
        if isinstance(guardrails, str) and guardrails.strip():
            return 1.0
        return 0.0
