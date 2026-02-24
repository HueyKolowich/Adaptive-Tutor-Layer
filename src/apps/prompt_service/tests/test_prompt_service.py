import uuid

from django.test import TestCase

from apps.history_service.models import Conversation, Turn
from apps.prompt_service.models import BanditUserArmState, Prompt, PromptDecision
from apps.prompt_service.service import PromptService
from apps.ratings_service.models import Evaluator, TurnEvaluation
from common.types import PromptContext


class PromptServiceSelectionTests(TestCase):
    def test_selection_logs_per_user_decision(self):
        prompt = Prompt.objects.create(text="Prompt A", is_active=True)
        service = PromptService()
        conversation_id = str(uuid.uuid4())

        result = service.select_system_prompt(
            PromptContext(user_id='learner-1', conversation_id=conversation_id)
        )

        self.assertEqual(result.prompt_id, prompt.id)
        decision = PromptDecision.objects.get()
        self.assertEqual(decision.learner_id, 'learner-1')
        self.assertEqual(str(decision.conversation_id), conversation_id)
        self.assertEqual(decision.turn_number, 0)
        self.assertIsNotNone(decision.sampled_theta)
        self.assertEqual(decision.model_version, 'pts_normal_v1')

    def test_selection_trace_includes_candidates_and_selected_prompt(self):
        Prompt.objects.create(text="Prompt A", is_active=True)
        Prompt.objects.create(text="Prompt B", is_active=True)
        service = PromptService()
        conversation_id = str(uuid.uuid4())

        result = service.select_system_prompt_with_trace(
            PromptContext(user_id='learner-1', conversation_id=conversation_id)
        )

        self.assertEqual(len(result.trace.candidates), 2)
        selected = [c for c in result.trace.candidates if c.selected]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].prompt_id, result.trace.selected_prompt_id)
        self.assertEqual(result.system_prompt.prompt_id, result.trace.selected_prompt_id)

    def test_streak_guardrail_uses_fallback_prompt(self):
        older_prompt = Prompt.objects.create(text="Older", is_active=True)
        fallback_prompt = Prompt.objects.create(text="Fallback", is_active=True)
        learner_id = 'learner-guardrail'
        conversation = Conversation.objects.create(user_id=learner_id)

        for idx in range(3):
            Turn.objects.create(
                conversation=conversation,
                turn_index=idx,
                user_text=f"u{idx}",
                assistant_text=f"a{idx}",
                prompt=older_prompt,
            )

        BanditUserArmState.objects.create(
            learner_id=learner_id,
            prompt=older_prompt,
            mu0=0.5,
            lambda0=4.0,
            eta=1000.0,
            nu=1000.0,
            sigma_r=0.2,
            alpha=1.0,
            gamma=0.998,
            model_version='pts_normal_v1',
        )
        BanditUserArmState.objects.create(
            learner_id=learner_id,
            prompt=fallback_prompt,
            mu0=0.5,
            lambda0=4.0,
            eta=0.0,
            nu=1000.0,
            sigma_r=0.2,
            alpha=1.0,
            gamma=0.998,
            model_version='pts_normal_v1',
        )

        service = PromptService()
        result = service.select_system_prompt(
            PromptContext(user_id=learner_id, conversation_id=str(conversation.id))
        )

        self.assertEqual(result.prompt_id, fallback_prompt.id)
        decision = PromptDecision.objects.latest('id')
        self.assertEqual(decision.prompt_id, fallback_prompt.id)


class PromptServiceUpdateTests(TestCase):
    def test_per_learner_states_are_isolated(self):
        prompt = Prompt.objects.create(text='Prompt', is_active=True)
        service = PromptService()

        service._apply_reward('learner-a', prompt, 0.9)
        service._apply_reward('learner-b', prompt, 0.1)

        a = BanditUserArmState.objects.get(learner_id='learner-a', prompt=prompt)
        b = BanditUserArmState.objects.get(learner_id='learner-b', prompt=prompt)
        self.assertNotEqual(a.eta, b.eta)
        self.assertNotEqual(a.learner_id, b.learner_id)

    def test_apply_reward_uses_discounted_eta_nu_and_clipping(self):
        prompt = Prompt.objects.create(text='Prompt', is_active=True)
        service = PromptService()

        service._apply_reward('learner-1', prompt, 1.4)
        state = BanditUserArmState.objects.get(learner_id='learner-1', prompt=prompt)
        self.assertAlmostEqual(state.eta, 25.0, places=6)
        self.assertAlmostEqual(state.nu, 25.0, places=6)
        self.assertAlmostEqual(state.effective_n, 1.0, places=6)

        service._apply_reward('learner-1', prompt, -0.5)
        state.refresh_from_db()
        self.assertAlmostEqual(state.eta, 24.95, places=6)
        self.assertAlmostEqual(state.nu, 49.95, places=6)
        self.assertAlmostEqual(state.effective_n, 1.998, places=6)

    def test_apply_reward_for_turn_is_idempotent_for_processed_decision(self):
        prompt = Prompt.objects.create(text='Prompt', is_active=True)
        conversation = Conversation.objects.create(user_id='learner-1')
        turn = Turn.objects.create(
            conversation=conversation,
            turn_index=0,
            user_text='u',
            assistant_text='a',
            prompt=prompt,
        )
        evaluator = Evaluator.objects.create(name='qscore_v0', version='0.1.0')
        TurnEvaluation.objects.create(
            turn=turn,
            evaluator=evaluator,
            q_total=0.7,
            q_correctness=0.7,
            q_helpfulness=0.7,
            q_pedagogy=0.7,
        )
        decision = PromptDecision.objects.create(
            learner_id='learner-1',
            conversation_id=conversation.id,
            turn=turn,
            prompt=prompt,
            turn_number=0,
            sampled_theta=0.2,
            model_version='pts_normal_v1',
        )

        service = PromptService()
        first = service.apply_reward_for_turn(turn)
        decision.refresh_from_db()
        state = BanditUserArmState.objects.get(learner_id='learner-1', prompt=prompt)
        eta_after_first = state.eta
        nu_after_first = state.nu

        second = service.apply_reward_for_turn(turn)
        decision.refresh_from_db()
        state.refresh_from_db()

        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertAlmostEqual(decision.reward, 0.7, places=6)
        self.assertAlmostEqual(state.eta, eta_after_first, places=6)
        self.assertAlmostEqual(state.nu, nu_after_first, places=6)
