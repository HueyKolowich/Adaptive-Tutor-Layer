# Handler Service

File: `src/apps/handler/service.py`

## Purpose
The handler service is the orchestrator for a tutor response turn. It coordinates prompt selection, LLM generation, persistence, observability events, and embedding sync.

## Inputs
- `user_id`
- `conversation_id` (optional)
- `question_text`
- `trace_id` (optional)

## Core Flow
1. Enforce feedback gate (previous turn must have feedback).
2. Select prompt via `PromptService.select_system_prompt_with_trace`.
3. Emit bandit selection events.
4. Load conversation history via `HistoryService`.
5. Generate adaptive LLM response via `LLMService`.
6. Optionally run baseline shadow response in observability mode.
7. Persist turn via `HistoryService.append_turn`.
8. Emit `turn.persisted` event.
9. Attempt embedding sync for the turn; enqueue retry job on failure.
10. Link `PromptDecision` to persisted turn.

## Key Side Effects
- Writes `Turn` rows.
- Emits observability events to Redis stream.
- May enqueue `EmbeddingSyncJob` rows.

## Failure Modes
- `FeedbackRequiredError` if prior turn lacks feedback.
- Prompt selection and persistence errors surfaced upstream.
- Baseline branch can be strict or best-effort based on settings.
