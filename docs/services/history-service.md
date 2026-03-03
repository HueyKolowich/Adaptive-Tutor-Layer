# History Service

File: `src/apps/history_service/service.py`

## Purpose
Owns conversation/turn persistence and retrieval.

## Responsibilities
- Fetch ordered chat history for a `(conversation_id, user_id)` pair.
- Append a turn atomically while enforcing conversation ownership.
- Assign next `turn_index` consistently.

## Core Methods
- `get_history(conversation_id, user_id)`
- `append_turn(conversation_id, user_id, user_text, assistant_text, metadata, prompt_id)`

## Data Stored
- User/assistant text
- Prompt reference (`prompt_id`)
- Metadata JSON (including baseline shadow where enabled)
