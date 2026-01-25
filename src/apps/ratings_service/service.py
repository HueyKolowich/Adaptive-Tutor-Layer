from django.db import transaction

from apps.history_service.models import Turn
from apps.ratings_service.models import Evaluator, TurnEvaluation, TurnFeedback
from common.errors import PersistenceError


class QScoreService:
    DEFAULT_EVALUATOR_NAME = 'qscore_v0'
    DEFAULT_EVALUATOR_VERSION = '0.1.0'

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

        latest_feedback = (
            turn.feedback_entries.order_by('-created_at').first()
        )
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


class RatingsService:
    def __init__(self, qscore_service: QScoreService | None = None):
        self.qscore_service = qscore_service or QScoreService()

    @transaction.atomic
    def record_feedback_and_evaluate(
        self,
        turn_id: str,
        user_id: str,
        rating_correctness: int,
        rating_helpfulness: int,
        rating_clarity: int,
        free_text: str | None = None,
    ) -> tuple[TurnFeedback, TurnEvaluation | None]:
        turn = (
            Turn.objects.select_related('conversation', 'prompt')
            .filter(id=turn_id)
            .first()
        )
        if not turn:
            raise PersistenceError("Turn not found.")

        if turn.conversation.user_id != user_id:
            raise PersistenceError("User does not own this turn.")

        feedback = TurnFeedback.objects.create(
            turn=turn,
            user_id=user_id,
            rating_correctness=rating_correctness,
            rating_helpfulness=rating_helpfulness,
            rating_clarity=rating_clarity,
            free_text=free_text,
        )

        evaluation = self.qscore_service.evaluate_turn(turn)
        return feedback, evaluation
