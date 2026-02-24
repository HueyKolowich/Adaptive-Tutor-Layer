from __future__ import annotations

import time
import uuid

from django.conf import settings

from apps.history_service.models import Turn
from apps.history_service.service import HistoryService
from apps.llm_service.service import LLMService
from apps.prompt_service.models import Prompt, PromptDecision
from apps.prompt_service.service import PromptService
from apps.ratings_service.models import TurnFeedback
from common.errors import FeedbackRequiredError, PromptDataError, PromptNotFoundError
from common.observability import publish_state_event
from common.types import PromptContext


def _excerpt(text: str, limit: int = 240) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + '…'


class TutorResponseHandler:
    def __init__(
        self,
        prompt_service: PromptService | None = None,
        history_service: HistoryService | None = None,
        llm_service: LLMService | None = None,
    ) -> None:
        self.prompt_service = prompt_service or PromptService()
        self.history_service = history_service or HistoryService()
        self.llm_service = llm_service or LLMService()

    def generate_response(
        self,
        user_id: str,
        conversation_id: str | None,
        question_text: str,
        trace_id: str | None = None,
    ) -> dict:
        if not conversation_id:
            conversation_id = str(uuid.uuid4())
        trace_id = trace_id or str(uuid.uuid4())

        # Enforce feedback required before selecting/serving the next prompt.
        last_turn = (
            Turn.objects.filter(conversation_id=conversation_id, conversation__user_id=user_id)
            .order_by('-turn_index')
            .first()
        )
        if last_turn is not None:
            has_feedback = TurnFeedback.objects.filter(turn=last_turn, user_id=user_id).exists()
            if not has_feedback:
                raise FeedbackRequiredError(
                    "Feedback required before next turn.",
                    last_turn_id=str(last_turn.id),
                    last_turn_index=last_turn.turn_index,
                )

        prompt_context = PromptContext(user_id=user_id, conversation_id=conversation_id)
        selection = self.prompt_service.select_system_prompt_with_trace(prompt_context)
        system_prompt = selection.system_prompt

        publish_state_event(
            event_type='bandit.candidates_scored',
            conversation_id=conversation_id,
            user_id=user_id,
            trace_id=trace_id,
            node='bandit',
            edge={'from': 'policies', 'to': 'bandit'},
            payload={
                'turn_number': selection.trace.turn_number,
                'candidates': [c.as_dict() for c in selection.trace.candidates],
            },
        )

        publish_state_event(
            event_type='bandit.prompt_selected',
            conversation_id=conversation_id,
            user_id=user_id,
            trace_id=trace_id,
            node='bandit',
            edge={'from': 'bandit', 'to': 'llm'},
            payload={
                'prompt_id': selection.trace.selected_prompt_id,
                'sampled_theta': selection.trace.selected_sampled_theta,
                'guardrail_applied': selection.trace.guardrail_applied,
            },
        )

        history = self.history_service.get_history(conversation_id, user_id)

        publish_state_event(
            event_type='llm.adaptive_started',
            conversation_id=conversation_id,
            user_id=user_id,
            trace_id=trace_id,
            node='llm',
            edge={'from': 'bandit', 'to': 'llm'},
            payload={'prompt_id': system_prompt.prompt_id},
        )

        adaptive_started = time.perf_counter()
        llm_response = self.llm_service.generate(
            system_prompt_text=system_prompt.text,
            history_turns=history,
            user_message=question_text,
        )
        adaptive_ms = round((time.perf_counter() - adaptive_started) * 1000, 2)

        adaptive_text = llm_response.get('assistant_text', '')
        adaptive_metadata = llm_response.get('metadata') or {}

        publish_state_event(
            event_type='llm.adaptive_completed',
            conversation_id=conversation_id,
            user_id=user_id,
            trace_id=trace_id,
            node='adaptive',
            edge={'from': 'llm', 'to': 'adaptive'},
            payload={
                'prompt_id': system_prompt.prompt_id,
                'assistant_excerpt': _excerpt(adaptive_text),
                'duration_ms': adaptive_ms,
                'model': adaptive_metadata.get('model'),
            },
        )

        baseline_shadow = None
        if settings.OBSERVABILITY_MODE:
            baseline_prompt_id = settings.BASELINE_PROMPT_ID
            if baseline_prompt_id is None:
                raise PromptDataError('BASELINE_PROMPT_ID is required when OBSERVABILITY_MODE is enabled.')

            baseline_prompt = Prompt.objects.filter(id=baseline_prompt_id, is_active=True).first()
            if baseline_prompt is None:
                raise PromptNotFoundError(f'Baseline prompt {baseline_prompt_id} not found or inactive.')

            publish_state_event(
                event_type='control.baseline_prompt_selected',
                conversation_id=conversation_id,
                user_id=user_id,
                trace_id=trace_id,
                node='static_policy',
                edge={'from': 'student', 'to': 'static_policy'},
                payload={'prompt_id': baseline_prompt.id},
            )

            publish_state_event(
                event_type='llm.baseline_started',
                conversation_id=conversation_id,
                user_id=user_id,
                trace_id=trace_id,
                node='llm',
                edge={'from': 'static_policy', 'to': 'llm'},
                payload={'prompt_id': baseline_prompt.id},
            )

            try:
                baseline_started = time.perf_counter()
                baseline_response = self.llm_service.generate(
                    system_prompt_text=baseline_prompt.text,
                    history_turns=history,
                    user_message=question_text,
                )
                baseline_ms = round((time.perf_counter() - baseline_started) * 1000, 2)
                baseline_text = baseline_response.get('assistant_text', '')
                baseline_metadata = baseline_response.get('metadata') or {}

                baseline_shadow = {
                    'status': 'ok',
                    'prompt_id': baseline_prompt.id,
                    'assistant_excerpt': baseline_text[:2048],
                    'assistant_length': len(baseline_text),
                    'duration_ms': baseline_ms,
                    'model': baseline_metadata.get('model'),
                }

                publish_state_event(
                    event_type='llm.baseline_completed',
                    conversation_id=conversation_id,
                    user_id=user_id,
                    trace_id=trace_id,
                    node='baseline',
                    edge={'from': 'llm', 'to': 'baseline'},
                    payload={
                        'prompt_id': baseline_prompt.id,
                        'assistant_excerpt': _excerpt(baseline_text),
                        'duration_ms': baseline_ms,
                        'model': baseline_metadata.get('model'),
                    },
                )
            except Exception as exc:
                publish_state_event(
                    event_type='pipeline.error',
                    conversation_id=conversation_id,
                    user_id=user_id,
                    trace_id=trace_id,
                    node='baseline',
                    edge={'from': 'llm', 'to': 'baseline'},
                    payload={
                        'stage': 'llm_baseline',
                        'error_type': type(exc).__name__,
                        'detail': _excerpt(str(exc), limit=180),
                    },
                )

                if settings.OBS_EVENTS_STRICT:
                    raise

                baseline_shadow = {
                    'status': 'error',
                    'prompt_id': baseline_prompt.id,
                    'error_type': type(exc).__name__,
                    'detail': _excerpt(str(exc), limit=180),
                }

        metadata = {**adaptive_metadata, 'prompt_id': system_prompt.prompt_id}
        if baseline_shadow is not None:
            metadata['baseline_shadow'] = baseline_shadow

        turn = self.history_service.append_turn(
            conversation_id=conversation_id,
            user_id=user_id,
            user_text=question_text,
            assistant_text=adaptive_text,
            metadata=metadata,
            prompt_id=system_prompt.prompt_id,
        )

        publish_state_event(
            event_type='turn.persisted',
            conversation_id=conversation_id,
            user_id=user_id,
            trace_id=trace_id,
            node='adaptive',
            edge={'from': 'llm', 'to': 'adaptive'},
            turn_id=str(turn.id),
            turn_index=turn.turn_index,
            payload={
                'prompt_id': system_prompt.prompt_id,
                'assistant_excerpt': _excerpt(adaptive_text),
                'baseline_status': (baseline_shadow or {}).get('status'),
            },
        )

        PromptDecision.objects.filter(
            learner_id=user_id,
            conversation_id=conversation_id,
            turn_number=turn.turn_index,
            turn__isnull=True,
        ).update(turn=turn)

        return {
            'conversation_id': conversation_id,
            'turn_id': str(turn.id),
            'turn_index': turn.turn_index,
            'tutor_response': adaptive_text,
        }
