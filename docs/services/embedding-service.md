# Embedding Service

Files:
- `src/apps/embedding_service/service.py`
- `src/apps/embedding_service/models.py`

## Purpose
Creates vector documents for turns/feedback and syncs them to ChromaDB with DB-backed retry.

## Document Types
- `question`
- `assistant`
- `feedback`

## Stored Metadata
- `conversation_id`
- `user_id`
- `prompt_id`
- `turn_id`
- timestamps

## Sync Model
- Primary index table: `TurnEmbeddingIndex`
- Retry queue: `EmbeddingSyncJob` (`pending`, `running`, `failed`, `done`)

## Main Methods
- `embed_turn(turn_id)`
- `embed_feedback(feedback_id)`
- `query_window(start_at, end_at, filters)`
- `process_pending_jobs(limit)`

## Notes
Current embedding vector generation is deterministic hash-based for local/dev consistency.
