from unittest.mock import patch

from django.test import TestCase

from apps.drift_detection_service.models import DriftRun
from apps.drift_detection_service.service import DriftDetectionService, DriftMetric
from apps.prompt_service.models import Prompt


class DriftDetectionServiceTests(TestCase):
    def test_run_cycle_for_user_without_data_completes(self):
        run = DriftDetectionService().run_cycle_for_user(user_id='learner-1')
        self.assertEqual(run.status, 'completed')
        self.assertFalse(run.ga_triggered)
        self.assertEqual(run.subject_user_id, 'learner-1')
        self.assertEqual(run.scope, 'user')

    def test_consecutive_high_cycles_trigger_ga_once_per_user(self):
        service = DriftDetectionService()
        Prompt.objects.create(
            text='Active manual prompt',
            is_active=True,
            status='active',
            origin='manual',
        )
        high = [
            DriftMetric('embedding_centroid_shift', 0.3, 0.18, True),
            DriftMetric('qscore_degradation', 0.2, 0.08, True),
            DriftMetric('feedback_deterioration', 0.0, 0.15, False),
        ]

        with patch.object(DriftDetectionService, 'compute_signals', return_value=high), patch(
            'apps.drift_detection_service.service.GAService.generate_variants',
            return_value=['v1', 'v2', 'v3'],
        ) as ga_mock:
            first = service.run_cycle_for_user(user_id='learner-1')
            second = service.run_cycle_for_user(user_id='learner-1')

        self.assertFalse(first.ga_triggered)
        self.assertTrue(second.ga_triggered)
        self.assertEqual(DriftRun.objects.filter(subject_user_id='learner-1', ga_triggered=True).count(), 1)
        self.assertEqual(ga_mock.call_count, 1)

    def test_high_cycles_are_isolated_by_user(self):
        service = DriftDetectionService()
        Prompt.objects.create(
            text='Active manual prompt',
            is_active=True,
            status='active',
            origin='manual',
        )
        high = [
            DriftMetric('embedding_centroid_shift', 0.3, 0.18, True),
            DriftMetric('qscore_degradation', 0.2, 0.08, True),
            DriftMetric('feedback_deterioration', 0.0, 0.15, False),
        ]

        with patch.object(DriftDetectionService, 'compute_signals', return_value=high), patch(
            'apps.drift_detection_service.service.GAService.generate_variants',
            return_value=['v1', 'v2', 'v3'],
        ):
            a1 = service.run_cycle_for_user(user_id='learner-a')
            b1 = service.run_cycle_for_user(user_id='learner-b')
            a2 = service.run_cycle_for_user(user_id='learner-a')

        self.assertFalse(a1.ga_triggered)
        self.assertFalse(b1.ga_triggered)
        self.assertTrue(a2.ga_triggered)
        self.assertEqual(DriftRun.objects.filter(subject_user_id='learner-a', ga_triggered=True).count(), 1)
        self.assertEqual(DriftRun.objects.filter(subject_user_id='learner-b', ga_triggered=True).count(), 0)
