from __future__ import annotations

import uuid

from django.db import transaction

from apps.embedding_service.service import EmbeddingService
from apps.evaluation_service.service import EvaluationService
from apps.history_service.models import Turn
from apps.ratings_service.models import TurnEvaluation, TurnFeedback
from common.errors import PersistenceError
from common.observability import publish_state_event
from apps.prompt_service.service import PromptService


class QScoreService:
    def __init__(self, evaluator_name: str | None = None):
        self.evaluation_service = EvaluationService(evaluator_name=evaluator_name)

    def evaluate_turn(self, turn: Turn) -> TurnEvaluation | None:
        return self.evaluation_service.evaluate_turn(turn)


class RatingsService:
    def __init__(self, qscore_service: QScoreService | None = None):
        self.qscore_service = qscore_service or QScoreService()
        self.embedding_service = EmbeddingService()

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
        try:
            self.embedding_service.embed_feedback(str(feedback.id))
        except Exception:
            self.embedding_service.enqueue_feedback_job(
                str(feedback.id),
                payload={'reason': 'feedback_post_persist'},
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
