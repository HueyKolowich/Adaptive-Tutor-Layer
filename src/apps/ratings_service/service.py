from __future__ import annotations

import uuid

from django.db import transaction

from apps.history_service.models import Turn
from apps.ratings_service.models import Evaluator, TurnEvaluation, TurnFeedback
from common.errors import PersistenceError
from common.observability import publish_state_event
from apps.prompt_service.service import PromptService


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
        trace_id: str | None = None,
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

        trace_id = trace_id or str(uuid.uuid4())
        conversation_id = str(turn.conversation_id)
        turn_id = str(turn.id)

        feedback = TurnFeedback.objects.create(
            turn=turn,
            user_id=user_id,
            rating_correctness=rating_correctness,
            rating_helpfulness=rating_helpfulness,
            rating_clarity=rating_clarity,
            free_text=free_text,
        )

        publish_state_event(
            event_type='feedback.recorded',
            conversation_id=conversation_id,
            user_id=user_id,
            trace_id=trace_id,
            turn_id=turn_id,
            turn_index=turn.turn_index,
            node='adaptive',
            edge={'from': 'adaptive', 'to': 'qscore'},
            payload={
                'feedback_id': str(feedback.id),
                'rating_correctness': feedback.rating_correctness,
                'rating_helpfulness': feedback.rating_helpfulness,
                'rating_clarity': feedback.rating_clarity,
            },
        )

        evaluation = self.qscore_service.evaluate_turn(turn)

        if evaluation is not None:
            publish_state_event(
                event_type='qscore.evaluated',
                conversation_id=conversation_id,
                user_id=user_id,
                trace_id=trace_id,
                turn_id=turn_id,
                turn_index=turn.turn_index,
                node='qscore',
                edge={'from': 'adaptive', 'to': 'qscore'},
                payload={
                    'evaluator': evaluation.evaluator.name,
                    'q_total': evaluation.q_total,
                    'q_correctness': evaluation.q_correctness,
                    'q_helpfulness': evaluation.q_helpfulness,
                    'q_pedagogy': evaluation.q_pedagogy,
                },
            )

            updates = PromptService().apply_reward_for_turn_with_updates(turn)
            for update in updates:
                publish_state_event(
                    event_type='bandit.reward_applied',
                    conversation_id=conversation_id,
                    user_id=user_id,
                    trace_id=trace_id,
                    turn_id=turn_id,
                    turn_index=turn.turn_index,
                    node='qscore',
                    edge={'from': 'qscore', 'to': 'policies'},
                    payload={
                        'decision_id': update['decision_id'],
                        'prompt_id': update['prompt_id'],
                        'reward': update['reward'],
                    },
                )
                publish_state_event(
                    event_type='bandit.arm_state_updated',
                    conversation_id=conversation_id,
                    user_id=user_id,
                    trace_id=trace_id,
                    turn_id=turn_id,
                    turn_index=turn.turn_index,
                    node='bandit',
                    edge={'from': 'qscore', 'to': 'bandit'},
                    payload={
                        'prompt_id': update['prompt_id'],
                        'eta': update['eta'],
                        'nu': update['nu'],
                        'effective_n': update['effective_n'],
                        'model_version': update['model_version'],
                        'posterior_mu': update['posterior_mu'],
                        'posterior_lambda': update['posterior_lambda'],
                    },
                )

        return feedback, evaluation
