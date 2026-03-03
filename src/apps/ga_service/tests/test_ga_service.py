from django.test import TestCase

from apps.ga_service.service import GAService
from apps.prompt_service.models import BanditUserArmState, Prompt


class GAServiceTests(TestCase):
    def test_generate_variants_creates_candidate_prompts(self):
        parent = Prompt.objects.create(text='Base prompt', is_active=True, status='active')

        rows = GAService().generate_variants(
            parent_prompt_id=parent.id,
            subject_user_id='learner-1',
            k=3,
        )

        self.assertEqual(len(rows), 3)
        created_prompts = Prompt.objects.filter(parent_prompt=parent).order_by('id')
        self.assertEqual(created_prompts.count(), 3)
        self.assertTrue(all(p.status == 'candidate' for p in created_prompts))
        self.assertTrue(all(abs(p.rollout_pct - 0.10) < 1e-9 for p in created_prompts))
        self.assertTrue(all(p.owner_user_id == 'learner-1' for p in created_prompts))

    def test_resolve_parent_prompt_for_user_uses_top_posterior(self):
        p_low = Prompt.objects.create(text='Low', is_active=True, status='active')
        p_high = Prompt.objects.create(text='High', is_active=True, status='active')
        Prompt.objects.create(
            text='Other user private',
            is_active=True,
            status='active',
            owner_user_id='learner-2',
            origin='ga',
        )

        BanditUserArmState.objects.create(
            learner_id='learner-1',
            prompt=p_low,
            mu0=0.5,
            lambda0=4.0,
            eta=1.0,
            nu=10.0,
            sigma_r=0.2,
            alpha=1.0,
            gamma=0.998,
            model_version='pts_normal_v1',
        )
        BanditUserArmState.objects.create(
            learner_id='learner-1',
            prompt=p_high,
            mu0=0.5,
            lambda0=4.0,
            eta=6.0,
            nu=10.0,
            sigma_r=0.2,
            alpha=1.0,
            gamma=0.998,
            model_version='pts_normal_v1',
        )

        parent = GAService().resolve_parent_prompt_for_user(subject_user_id='learner-1')
        self.assertIsNotNone(parent)
        self.assertEqual(parent.id, p_high.id)
