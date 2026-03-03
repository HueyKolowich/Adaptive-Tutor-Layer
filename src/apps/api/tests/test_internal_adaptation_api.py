import json
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.drift_detection_service.models import DriftRun, DriftSignal
from apps.prompt_service.models import Prompt


class InternalAdaptationApiTests(TestCase):
    def test_drift_run_requires_user_id(self):
        resp = self.client.post('/api/internal/drift/run', data=json.dumps({}), content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_drift_signals_require_user_id(self):
        resp = self.client.get('/api/internal/drift/signals')
        self.assertEqual(resp.status_code, 400)

    def test_drift_signals_are_filtered_by_user(self):
        now = timezone.now()
        run_a = DriftRun.objects.create(
            scope='user',
            subject_user_id='learner-a',
            status='completed',
            started_at=now,
            finished_at=now,
        )
        run_b = DriftRun.objects.create(
            scope='user',
            subject_user_id='learner-b',
            status='completed',
            started_at=now,
            finished_at=now,
        )
        DriftSignal.objects.create(
            drift_run=run_a,
            signal_type='qscore_degradation',
            severity='medium',
            score=0.2,
            threshold=0.08,
            scope='user',
            subject_user_id='learner-a',
        )
        DriftSignal.objects.create(
            drift_run=run_b,
            signal_type='feedback_deterioration',
            severity='low',
            score=0.01,
            threshold=0.15,
            scope='user',
            subject_user_id='learner-b',
        )

        resp = self.client.get('/api/internal/drift/signals?user_id=learner-a')
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()['signals']
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]['subject_user_id'], 'learner-a')

    def test_ga_evolve_requires_user_id(self):
        resp = self.client.post('/api/internal/ga/evolve', data=json.dumps({}), content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    @patch('apps.api.views.GAService.generate_variants', return_value=[])
    def test_ga_evolve_accepts_optional_parent_prompt(self, ga_mock):
        resp = self.client.post(
            '/api/internal/ga/evolve',
            data=json.dumps({'user_id': 'learner-1'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        ga_mock.assert_called_once_with(
            parent_prompt_id=None,
            subject_user_id='learner-1',
            drift_signal_id=None,
            k=3,
        )

    def test_prompt_lifecycle_rejects_owner_mismatch(self):
        prompt = Prompt.objects.create(
            text='Private prompt',
            is_active=True,
            status='candidate',
            owner_user_id='learner-2',
            origin='ga',
            rollout_pct=0.1,
        )
        resp = self.client.post(
            f'/api/internal/prompts/{prompt.id}/promote',
            data=json.dumps({'user_id': 'learner-1'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_prompt_lifecycle_promote_keeps_owner(self):
        prompt = Prompt.objects.create(
            text='Private prompt',
            is_active=True,
            status='candidate',
            owner_user_id='learner-1',
            origin='ga',
            rollout_pct=0.1,
        )
        resp = self.client.post(
            f'/api/internal/prompts/{prompt.id}/promote',
            data=json.dumps({'user_id': 'learner-1'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        prompt.refresh_from_db()
        self.assertEqual(prompt.status, 'active')
        self.assertEqual(prompt.owner_user_id, 'learner-1')
