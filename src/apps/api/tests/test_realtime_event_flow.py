import json
from unittest.mock import patch

from django.test import TestCase

from apps.history_service.models import Conversation, Turn
from apps.prompt_service.models import Prompt, PromptDecision
from apps.ratings_service.models import Evaluator
from common.observability import publisher as publisher_module


class FakeRedis:
    def __init__(self):
        self.entries = []

    def xadd(self, stream, fields, maxlen=None, approximate=None):
        self.entries.append({'stream': stream, 'fields': fields})


def _events_from_fake(fake_redis: FakeRedis) -> list[dict]:
    return [json.loads(item['fields']['event']) for item in fake_redis.entries]


class RealtimeEventFlowTests(TestCase):
    def tearDown(self):
        publisher_module._publisher.cache_clear()

    def test_tutor_respond_emits_ordered_realtime_events(self):
        adaptive_prompt = Prompt.objects.create(text='ADAPTIVE prompt', is_active=True)
        baseline_prompt = Prompt.objects.create(text='BASELINE prompt', is_active=True)

        fake_redis = FakeRedis()

        def fake_generate(_self, system_prompt_text: str, history_turns: list, user_message: str) -> dict:
            role = 'baseline' if 'BASELINE' in system_prompt_text else 'adaptive'
            return {
                'assistant_text': f'{role} reply to {user_message}',
                'metadata': {
                    'model': 'fake-model',
                    'temperature': 0.7,
                    'max_tokens': 128,
                },
            }

        with self.settings(
            OBSERVABILITY_MODE=True,
            OBS_EVENTS_STRICT=True,
            OBS_REDIS_URL='redis://fake:6379/0',
            OBS_REDIS_STREAM_KEY='atl:state-events',
            OBS_REDIS_MAXLEN=2000,
            BASELINE_PROMPT_ID=baseline_prompt.id,
        ):
            publisher_module._publisher.cache_clear()
            with patch('common.observability.publisher._redis_from_url', return_value=fake_redis):
                with patch('apps.llm_service.service.LLMService.generate', autospec=True, side_effect=fake_generate):
                    resp = self.client.post(
                        '/api/tutor/respond',
                        data=json.dumps(
                            {
                                'user_id': 'learner-1',
                                'question_text': 'What is backprop?',
                            }
                        ),
                        content_type='application/json',
                    )

        self.assertEqual(resp.status_code, 200)
        events = _events_from_fake(fake_redis)
        event_types = [e['event_type'] for e in events]

        self.assertGreaterEqual(len(events), 9)
        self.assertEqual(event_types[0], 'student.question_received')
        self.assertIn('bandit.candidates_scored', event_types)
        self.assertIn('bandit.prompt_selected', event_types)
        self.assertIn('control.baseline_prompt_selected', event_types)
        self.assertIn('llm.adaptive_started', event_types)
        self.assertIn('llm.adaptive_completed', event_types)
        self.assertIn('llm.baseline_started', event_types)
        self.assertIn('llm.baseline_completed', event_types)
        self.assertEqual(event_types[-1], 'turn.persisted')

        trace_ids = {e['trace_id'] for e in events}
        self.assertEqual(len(trace_ids), 1)

        persisted = [e for e in events if e['event_type'] == 'turn.persisted'][-1]
        self.assertIsNotNone(persisted['turn_id'])
        self.assertIsNotNone(persisted['turn_index'])

        response_payload = resp.json()
        self.assertEqual(response_payload['turn_id'], persisted['turn_id'])
        self.assertEqual(response_payload['turn_index'], persisted['turn_index'])

    def test_feedback_lifecycle_emits_qscore_and_bandit_events(self):
        prompt = Prompt.objects.create(text='Prompt A', is_active=True)
        conversation = Conversation.objects.create(user_id='learner-1')
        turn = Turn.objects.create(
            conversation=conversation,
            turn_index=0,
            user_text='u',
            assistant_text='a',
            prompt=prompt,
        )
        PromptDecision.objects.create(
            learner_id='learner-1',
            conversation_id=conversation.id,
            turn=turn,
            prompt=prompt,
            turn_number=0,
            sampled_theta=0.3,
            model_version='pts_normal_v1',
        )
        Evaluator.objects.create(
            name='qscore_v0',
            version='0.1.0',
            config_json={
                'weights': {'wc': 0.4, 'wh': 0.4, 'wp': 0.2},
                'rating_scale': {'min': 1, 'max': 5},
                'guardrail_tag': 'guardrails',
            },
        )

        fake_redis = FakeRedis()

        with self.settings(
            OBSERVABILITY_MODE=True,
            OBS_EVENTS_STRICT=True,
            OBS_REDIS_URL='redis://fake:6379/0',
            OBS_REDIS_STREAM_KEY='atl:state-events',
            OBS_REDIS_MAXLEN=2000,
        ):
            publisher_module._publisher.cache_clear()
            with patch('common.observability.publisher._redis_from_url', return_value=fake_redis):
                resp = self.client.post(
                    f'/api/turns/{turn.id}/feedback',
                    data=json.dumps(
                        {
                            'user_id': 'learner-1',
                            'rating_correctness': 5,
                            'rating_helpfulness': 4,
                            'rating_clarity': 4,
                            'free_text': 'helpful',
                        }
                    ),
                    content_type='application/json',
                )

        self.assertEqual(resp.status_code, 201)
        events = _events_from_fake(fake_redis)
        event_types = [e['event_type'] for e in events]

        self.assertIn('feedback.recorded', event_types)
        self.assertIn('qscore.evaluated', event_types)
        self.assertIn('bandit.reward_applied', event_types)
        self.assertIn('bandit.arm_state_updated', event_types)

        decision = PromptDecision.objects.get(turn=turn)
        self.assertIsNotNone(decision.reward)
        self.assertGreaterEqual(decision.reward, 0.0)
        self.assertLessEqual(decision.reward, 1.0)
