import uuid
from unittest.mock import patch

from django.test import TestCase

from apps.handler.service import TutorResponseHandler
from apps.prompt_service.models import Prompt
from apps.prompt_service.service import (
    PromptCandidateTrace,
    PromptSelectionResult,
    PromptSelectionTrace,
)
from common.types import SystemPrompt


class FakePromptService:
    def __init__(self, prompt_id: int, text: str):
        self.prompt_id = prompt_id
        self.text = text

    def select_system_prompt_with_trace(self, context):
        return PromptSelectionResult(
            system_prompt=SystemPrompt(prompt_id=self.prompt_id, text=self.text),
            trace=PromptSelectionTrace(
                turn_number=0,
                selected_prompt_id=self.prompt_id,
                selected_sampled_theta=0.42,
                guardrail_applied=False,
                candidates=[
                    PromptCandidateTrace(
                        prompt_id=self.prompt_id,
                        sampled_theta=0.42,
                        posterior_mu=0.5,
                        posterior_lambda=4.0,
                        selected=True,
                    )
                ],
            ),
        )


class FakeLLMService:
    def generate(self, system_prompt_text: str, history_turns: list, user_message: str) -> dict:
        if 'BASELINE' in system_prompt_text:
            return {
                'assistant_text': 'B' * 2600,
                'metadata': {'model': 'fake-llm'},
            }
        return {
            'assistant_text': f'adaptive: {user_message}',
            'metadata': {'model': 'fake-llm'},
        }


class BrokenBaselineLLMService(FakeLLMService):
    def generate(self, system_prompt_text: str, history_turns: list, user_message: str) -> dict:
        if 'BASELINE' in system_prompt_text:
            raise RuntimeError('baseline failed')
        return super().generate(system_prompt_text, history_turns, user_message)


class HandlerBaselineShadowTests(TestCase):
    def test_baseline_shadow_is_persisted_with_excerpt_limit(self):
        adaptive_prompt = Prompt.objects.create(text='ADAPTIVE prompt', is_active=True)
        baseline_prompt = Prompt.objects.create(text='BASELINE prompt', is_active=True)

        handler = TutorResponseHandler(
            prompt_service=FakePromptService(adaptive_prompt.id, adaptive_prompt.text),
            llm_service=FakeLLMService(),
        )

        with self.settings(
            OBSERVABILITY_MODE=True,
            OBS_EVENTS_STRICT=True,
            BASELINE_PROMPT_ID=baseline_prompt.id,
        ):
            with patch('apps.handler.service.publish_state_event'):
                result = handler.generate_response(
                    user_id='learner-1',
                    conversation_id=str(uuid.uuid4()),
                    question_text='Question?',
                    trace_id='trace-1',
                )

        self.assertEqual(result['turn_index'], 0)

        from apps.history_service.models import Turn

        turn = Turn.objects.get(id=result['turn_id'])
        baseline_shadow = turn.metadata_json.get('baseline_shadow')
        self.assertEqual(baseline_shadow['status'], 'ok')
        self.assertEqual(baseline_shadow['prompt_id'], baseline_prompt.id)
        self.assertEqual(len(baseline_shadow['assistant_excerpt']), 2048)
        self.assertEqual(baseline_shadow['assistant_length'], 2600)

    def test_baseline_failure_raises_in_strict_observability_mode(self):
        adaptive_prompt = Prompt.objects.create(text='ADAPTIVE prompt', is_active=True)
        baseline_prompt = Prompt.objects.create(text='BASELINE prompt', is_active=True)

        handler = TutorResponseHandler(
            prompt_service=FakePromptService(adaptive_prompt.id, adaptive_prompt.text),
            llm_service=BrokenBaselineLLMService(),
        )

        with self.settings(
            OBSERVABILITY_MODE=True,
            OBS_EVENTS_STRICT=True,
            BASELINE_PROMPT_ID=baseline_prompt.id,
        ):
            with patch('apps.handler.service.publish_state_event'):
                with self.assertRaises(RuntimeError):
                    handler.generate_response(
                        user_id='learner-1',
                        conversation_id=str(uuid.uuid4()),
                        question_text='Question?',
                        trace_id='trace-1',
                    )
