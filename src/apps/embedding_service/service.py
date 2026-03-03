from __future__ import annotations

import hashlib
import json
import logging
from urllib import error as urlerror
from urllib import request as urlrequest

from django.conf import settings
from django.db import transaction

from apps.embedding_service.models import EmbeddingSyncJob, TurnEmbeddingIndex
from apps.history_service.models import Turn
from apps.ratings_service.models import TurnFeedback


logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self) -> None:
        self.base_url = f"http://{settings.CHROMA_HOST}:{settings.CHROMA_PORT}"
        self.collection_name = settings.CHROMA_COLLECTION_TURNS
        self.embedding_model_version = settings.EMBEDDING_MODEL_VERSION
        self._collection_id: str | None = None

    def embed_turn(self, turn_id: str) -> list[TurnEmbeddingIndex]:
        turn = Turn.objects.select_related('conversation').filter(id=turn_id).first()
        if turn is None:
            return []

        docs = [
            self._build_turn_doc(turn, 'question', turn.user_text),
            self._build_turn_doc(turn, 'assistant', turn.assistant_text),
        ]
        return self._upsert_docs(docs)

    def embed_feedback(self, feedback_id: str) -> TurnEmbeddingIndex | None:
        feedback = TurnFeedback.objects.select_related('turn__conversation').filter(id=feedback_id).first()
        if feedback is None:
            return None

        free_text = (feedback.free_text or '').strip()
        if not free_text:
            free_text = (
                f"ratings correctness={feedback.rating_correctness} "
                f"helpfulness={feedback.rating_helpfulness} clarity={feedback.rating_clarity}"
            )

        doc = self._build_feedback_doc(feedback, free_text)
        rows = self._upsert_docs([doc])
        return rows[0] if rows else None

    def query_window(self, start_at, end_at, filters: dict | None = None) -> list[dict]:
        query = TurnEmbeddingIndex.objects.filter(created_at__gte=start_at, created_at__lte=end_at)
        filters = filters or {}
        for key, value in filters.items():
            if key == 'document_type':
                query = query.filter(document_type=value)
            elif key == 'user_id':
                query = query.filter(metadata_json__user_id=value)
            elif key == 'prompt_id':
                query = query.filter(metadata_json__prompt_id=value)

        return [
            {
                'vector_id': row.vector_id,
                'document_type': row.document_type,
                'embedding_json': row.embedding_json,
                'metadata_json': row.metadata_json,
            }
            for row in query.order_by('created_at')
        ]

    def process_pending_jobs(self, limit: int = 50) -> int:
        processed = 0
        jobs = EmbeddingSyncJob.objects.filter(status='pending').order_by('created_at')[:limit]
        for job in jobs:
            with transaction.atomic():
                job = EmbeddingSyncJob.objects.select_for_update().get(id=job.id)
                if job.status != 'pending':
                    continue
                job.status = 'running'
                job.attempts += 1
                job.save(update_fields=['status', 'attempts', 'updated_at'])

            try:
                if job.turn_id:
                    self.embed_turn(str(job.turn_id))
                elif job.feedback_id:
                    self.embed_feedback(str(job.feedback_id))
                job.status = 'done'
                job.last_error = None
                processed += 1
            except Exception as exc:  # pragma: no cover - protective path
                job.status = 'failed'
                job.last_error = str(exc)[:500]

            job.save(update_fields=['status', 'last_error', 'updated_at'])
        return processed

    def enqueue_turn_job(self, turn_id: str, payload: dict | None = None) -> EmbeddingSyncJob:
        return EmbeddingSyncJob.objects.create(turn_id=turn_id, payload_json=payload or {}, status='pending')

    def enqueue_feedback_job(self, feedback_id: str, payload: dict | None = None) -> EmbeddingSyncJob:
        return EmbeddingSyncJob.objects.create(feedback_id=feedback_id, payload_json=payload or {}, status='pending')

    def _build_turn_doc(self, turn: Turn, doc_type: str, text: str) -> dict:
        vector_id = f"turn:{turn.id}:{doc_type}"
        metadata = {
            'conversation_id': str(turn.conversation_id),
            'user_id': turn.conversation.user_id,
            'turn_id': str(turn.id),
            'turn_index': turn.turn_index,
            'prompt_id': turn.prompt_id,
            'document_type': doc_type,
            'created_at': turn.created_at.isoformat(),
        }
        return {
            'vector_id': vector_id,
            'turn_id': str(turn.id),
            'feedback_id': None,
            'document_type': doc_type,
            'text': text,
            'metadata': metadata,
        }

    def _build_feedback_doc(self, feedback: TurnFeedback, text: str) -> dict:
        vector_id = f"feedback:{feedback.id}:feedback"
        turn = feedback.turn
        metadata = {
            'conversation_id': str(turn.conversation_id),
            'user_id': feedback.user_id,
            'turn_id': str(turn.id),
            'prompt_id': turn.prompt_id,
            'feedback_id': str(feedback.id),
            'document_type': 'feedback',
            'created_at': feedback.created_at.isoformat(),
        }
        return {
            'vector_id': vector_id,
            'turn_id': str(turn.id),
            'feedback_id': str(feedback.id),
            'document_type': 'feedback',
            'text': text,
            'metadata': metadata,
        }

    def _upsert_docs(self, docs: list[dict]) -> list[TurnEmbeddingIndex]:
        if not docs:
            return []

        rows = []
        for doc in docs:
            embedding = self._text_to_embedding(doc['text'])
            row, _ = TurnEmbeddingIndex.objects.update_or_create(
                vector_id=doc['vector_id'],
                defaults={
                    'turn_id': doc['turn_id'],
                    'feedback_id': doc['feedback_id'],
                    'document_type': doc['document_type'],
                    'embedding_model_version': self.embedding_model_version,
                    'embedding_json': embedding,
                    'metadata_json': doc['metadata'],
                },
            )
            rows.append(row)

        try:
            self._chroma_upsert(docs, rows)
        except Exception as exc:
            logger.warning('Chroma upsert failed; continuing with DB embeddings only: %s', exc)
            raise

        return rows

    def _chroma_upsert(self, docs: list[dict], rows: list[TurnEmbeddingIndex]) -> None:
        collection_id = self._get_or_create_collection_id()
        payload = {
            'ids': [doc['vector_id'] for doc in docs],
            'documents': [doc['text'] for doc in docs],
            'metadatas': [doc['metadata'] for doc in docs],
            'embeddings': [row.embedding_json for row in rows],
        }
        self._request('POST', f"/api/v1/collections/{collection_id}/upsert", payload)

    def _get_or_create_collection_id(self) -> str:
        if self._collection_id:
            return self._collection_id

        payload = self._request('GET', '/api/v1/collections')
        existing_id = self._find_collection_id(payload, self.collection_name)
        if existing_id:
            self._collection_id = existing_id
            return existing_id

        created = self._request('POST', '/api/v1/collections', {'name': self.collection_name})
        created_id = self._extract_collection_id(created)
        if created_id:
            self._collection_id = created_id
            return created_id

        # Fallback read if create payload shape does not contain id.
        payload = self._request('GET', '/api/v1/collections')
        existing_id = self._find_collection_id(payload, self.collection_name)
        if existing_id:
            self._collection_id = existing_id
            return existing_id

        raise RuntimeError(f"Could not resolve Chroma collection id for '{self.collection_name}'")

    def _find_collection_id(self, payload: object, name: str) -> str | None:
        for row in self._extract_collections(payload):
            if row.get('name') == name and row.get('id'):
                return str(row['id'])
        return None

    def _extract_collections(self, payload: object) -> list[dict]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            collections = payload.get('collections')
            if isinstance(collections, list):
                return [item for item in collections if isinstance(item, dict)]
        return []

    def _extract_collection_id(self, payload: object) -> str | None:
        if isinstance(payload, dict) and payload.get('id'):
            return str(payload['id'])
        return None

    def _request(self, method: str, path: str, payload: dict | None = None) -> object:
        body = None
        headers = {'Accept': 'application/json'}
        if payload is not None:
            body = json.dumps(payload).encode('utf-8')
            headers['Content-Type'] = 'application/json'

        req = urlrequest.Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers=headers,
        )
        try:
            with urlrequest.urlopen(req, timeout=4) as resp:
                raw = resp.read().decode('utf-8')
                return json.loads(raw) if raw else {}
        except urlerror.HTTPError as exc:
            detail = exc.read().decode('utf-8') if exc.fp else ''
            raise RuntimeError(f"Chroma error {exc.code}: {detail}") from exc

    def _text_to_embedding(self, text: str, dim: int = 64) -> list[float]:
        if not text:
            text = ' '
        values = []
        for idx in range(dim):
            digest = hashlib.sha256(f"{idx}:{text}".encode('utf-8')).digest()
            raw = int.from_bytes(digest[:4], 'big')
            values.append((raw / 2**32) * 2.0 - 1.0)
        return values
