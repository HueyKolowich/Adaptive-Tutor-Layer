# API Service

Files:
- `src/apps/api/views.py`
- `src/apps/api/urls.py`

## Purpose
HTTP entrypoint for tutor interaction flows plus internal drift/GA operations.

## Public Endpoints
- `POST /api/tutor/respond`
- `POST /api/turns/<turn_id>/feedback`
- `GET /api/conversations?user_id=<learner>`
- `GET /api/conversations/<conversation_id>/history?user_id=<learner>`

## Internal Endpoints (Per-User)
- `POST /api/internal/drift/run`
  - body: `{"user_id": "learner-1"}`
- `GET /api/internal/drift/signals?user_id=learner-1`
- `POST /api/internal/ga/evolve`
  - body: `{"user_id": "learner-1", "parent_prompt_id": 12, "k": 3}`
  - `parent_prompt_id` optional; service resolves parent when omitted.
- `POST /api/internal/prompts/<id>/promote`
  - body must include `user_id`; rejects owner mismatch.
- `POST /api/internal/prompts/<id>/retire`
  - body must include `user_id`; rejects owner mismatch.

## Contract Notes
- Public tutor/feedback/history remain learner-scoped through provided `user_id`.
- Internal adaptation endpoints are explicitly learner-targeted; global drift/GA control is removed.
- Prompt promotion does not globalize learner-owned GA prompts.

## Observability
The API emits lifecycle events and preserves event names:
- drift: `drift.signal_detected`, `drift.run_completed`, `drift.ga_triggered`
- ga: `ga.variants_generated`, `ga.prompt_promoted`
