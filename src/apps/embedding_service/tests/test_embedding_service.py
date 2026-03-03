from unittest.mock import patch

from django.test import TestCase

from apps.embedding_service.models import EmbeddingSyncJob, TurnEmbeddingIndex
from apps.embedding_service.service import EmbeddingService
from apps.history_service.models import Conversation, Turn
from apps.ratings_service.models import TurnFeedback


class EmbeddingServiceTests(TestCase):
    @staticmethod
    def _fake_chroma_request(method: str, path: str, payload: dict | None = None):
        if method == 'GET' and path == '/api/v1/collections':
            return [{'id': '11111111-1111-1111-1111-111111111111', 'name': 'atl_turns'}]
        if method == 'POST' and path.startswith('/api/v1/collections/') and path.endswith('/upsert'):
            return {}
        if method == 'POST' and path == '/api/v1/collections':
            return {'id': '11111111-1111-1111-1111-111111111111', 'name': 'atl_turns'}
        return {}

    def test_embed_turn_and_feedback_create_index_rows(self):
        conversation = Conversation.objects.create(user_id='learner-1')
        turn = Turn.objects.create(
            conversation=conversation,
            turn_index=0,
            user_text='What is backprop?',
            assistant_text='Chain rule over layers.',
        )
        feedback = TurnFeedback.objects.create(
            turn=turn,
            user_id='learner-1',
            rating_correctness=5,
            rating_helpfulness=4,
            rating_clarity=4,
            free_text='Helpful answer',
        )

        service = EmbeddingService()
        with patch.object(EmbeddingService, '_request', side_effect=self._fake_chroma_request):
            rows = service.embed_turn(str(turn.id))
            row = service.embed_feedback(str(feedback.id))

        self.assertEqual(len(rows), 2)
        self.assertIsNotNone(row)
        self.assertEqual(TurnEmbeddingIndex.objects.count(), 3)

    def test_enqueue_jobs_and_process(self):
        conversation = Conversation.objects.create(user_id='learner-1')
        turn = Turn.objects.create(
            conversation=conversation,
            turn_index=0,
            user_text='u',
            assistant_text='a',
        )
        service = EmbeddingService()
        service.enqueue_turn_job(str(turn.id), payload={'source': 'test'})

        with patch.object(EmbeddingService, '_request', side_effect=self._fake_chroma_request):
            processed = service.process_pending_jobs(limit=10)

        self.assertEqual(processed, 1)
        job = EmbeddingSyncJob.objects.get()
        self.assertEqual(job.status, 'done')
