from unittest.mock import patch

from django.test import TestCase

from apps.history_service.models import Conversation, Turn
from apps.prompt_service.models import Prompt, PromptDecision
from apps.ratings_service.models import Evaluator
from apps.ratings_service.service import RatingsService


class RatingsEventsTests(TestCase):
    def test_record_feedback_emits_reward_and_arm_state_updates(self):
        prompt = Prompt.objects.create(
            text='Prompt A',
            is_active=True,
            policy_tags_json={'guardrails': ['check_understanding']},
        )
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
            sampled_theta=0.2,
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

        service = RatingsService()
        with patch('apps.ratings_service.service.publish_state_event') as publish_mock:
            feedback, evaluation = service.record_feedback_and_evaluate(
                turn_id=str(turn.id),
                user_id='learner-1',
                rating_correctness=5,
                rating_helpfulness=4,
                rating_clarity=4,
                free_text='helpful',
                trace_id='trace-1',
            )

        self.assertIsNotNone(feedback.id)
        self.assertIsNotNone(evaluation)

        event_types = [call.kwargs['event_type'] for call in publish_mock.mock_calls]
        self.assertIn('feedback.recorded', event_types)
        self.assertIn('qscore.evaluated', event_types)
        self.assertIn('bandit.reward_applied', event_types)
        self.assertIn('bandit.arm_state_updated', event_types)

        arm_update_calls = [
            call for call in publish_mock.mock_calls if call.kwargs['event_type'] == 'bandit.arm_state_updated'
        ]
        self.assertGreaterEqual(len(arm_update_calls), 1)
        payload = arm_update_calls[0].kwargs['payload']
        self.assertIn('eta', payload)
        self.assertIn('nu', payload)
        self.assertIn('effective_n', payload)
        self.assertIn('posterior_mu', payload)
        self.assertIn('posterior_lambda', payload)
