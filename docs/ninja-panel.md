# Ninja Panel Engineering Guide

This document describes how the real-time Ninja Panel works today, where data comes from, and how to safely change behavior.

## What the panel is

The Ninja Panel is a **conversation-scoped real-time state machine view** for the adaptive tutor runtime.

- UI host: `panel-service` (Node/Express)
- Live transport: Server-Sent Events (SSE)
- Event bus: Redis Stream
- Producer: Django backend (`/api/tutor/respond`, `/api/turns/<id>/feedback` flows)

The panel must be opened with a conversation id:

- `http://localhost:3001/?conversation_id=<uuid>`
- Legacy route `http://localhost:8000/panel/?conversation_id=<uuid>` redirects to panel-service.

## Topology

### Services

- API service (Django): `src/`
- Panel service (Node): `panel-service/`
- Redis: stream buffer + replay source

### Key files

- Event contract/types:
  - `src/common/observability/events.py`
- Event publishing:
  - `src/common/observability/publisher.py`
- Tutor respond flow + event emission:
  - `src/apps/api/views.py`
  - `src/apps/handler/service.py`
- Feedback/qscore/bandit update flow + event emission:
  - `src/apps/ratings_service/service.py`
  - `src/apps/prompt_service/service.py`
- Panel backend (SSE + replay):
  - `panel-service/server.js`
- Panel frontend UI/state machine renderer:
  - `panel-service/public/index.html`
- Dev orchestration:
  - `docker-compose.yml`

## Event contract

All state events use this envelope:

- `event_id`
- `event_type`
- `occurred_at`
- `conversation_id`
- `user_id`
- `turn_id` (optional)
- `turn_index` (optional)
- `node`
- `edge` (`from`, `to`, optional)
- `payload`
- `trace_id`

Current `event_type` values:

1. `student.question_received`
2. `bandit.candidates_scored`
3. `bandit.prompt_selected`
4. `control.baseline_prompt_selected`
5. `llm.adaptive_started`
6. `llm.adaptive_completed`
7. `llm.baseline_started`
8. `llm.baseline_completed`
9. `turn.persisted`
10. `feedback.recorded`
11. `qscore.evaluated`
12. `bandit.reward_applied`
13. `bandit.arm_state_updated`
14. `pipeline.error`

## Backend flow: respond lifecycle

### 1) API request start

`TutorRespondView.post` emits:

- `student.question_received`

The view generates a `trace_id` and passes it to `TutorResponseHandler.generate_response`.

### 2) Prompt selection and bandit trace

`PromptService.select_system_prompt_with_trace` computes per-arm posterior and sampling diagnostics and logs a decision.

`TutorResponseHandler` emits:

- `bandit.candidates_scored` (contains per-arm `posterior_mu`, `posterior_lambda`, sampled theta, selected flag)
- `bandit.prompt_selected`

### 3) Adaptive + baseline LLM branches

Adaptive path always runs.

Baseline path runs in observability mode and uses `BASELINE_PROMPT_ID`.

`TutorResponseHandler` emits:

- `llm.adaptive_started`
- `llm.adaptive_completed`
- `control.baseline_prompt_selected`
- `llm.baseline_started`
- `llm.baseline_completed`
- `pipeline.error` (baseline failure)

Baseline output is stored in `Turn.metadata_json["baseline_shadow"]` (truncated excerpt + metrics). Baseline does **not** affect reward updates.

### 4) Turn persistence

After writing turn history:

- `turn.persisted`

## Backend flow: feedback lifecycle

`TurnFeedbackView.post` calls `RatingsService.record_feedback_and_evaluate`.

It emits:

- `feedback.recorded`
- `qscore.evaluated`
- `bandit.reward_applied`
- `bandit.arm_state_updated`

`bandit.arm_state_updated` payload now includes:

- `prompt_id`
- `eta`
- `nu`
- `effective_n`
- `posterior_mu`
- `posterior_lambda`

This allows immediate in-place UI updates without waiting for another question.

## Panel-service behavior

`panel-service/server.js` exposes:

- `GET /` static panel UI
- `GET /events?conversation_id=<uuid>` SSE stream
- `GET /health`

SSE behavior:

1. Requires `conversation_id`.
2. Replays last N matching events from Redis Stream (default 100).
3. Tails new stream entries and forwards only matching `conversation_id`.
4. Sends keepalive comments every ~15s.

## Frontend state model

The panel frontend is a React app in `panel-service/public/index.html`.

### Core behavior

- Maintains graph node/edge UI state.
- Applies incoming events through `applyEvent(prev, evt)`.
- Uses per-event node/edge hot windows to animate activity.

### Distribution panel (posterior cards)

Source of truth is `snapshot.policies.candidates`.

Population paths:

- `bandit.candidates_scored`: full candidate list (normal per-turn update)
- `bandit.arm_state_updated`: targeted in-place update for affected arm (`posterior_mu`, `posterior_lambda`)

Card math:

- `mu` displayed from `posterior_mu`
- `lambda` displayed from `posterior_lambda`
- `sigma = 1 / sqrt(lambda)`
- sampled theta shown directly from event payload

Plot details:

- Domain is `[0, 1]`.
- x-position for mean and sampled-theta markers is mapped directly to that domain.
- SVG uses `preserveAspectRatio="none"` to keep marker and axis alignment.

## Configuration and env vars

Django settings:

- `OBSERVABILITY_MODE`
- `OBS_EVENTS_STRICT`
- `OBS_REDIS_URL`
- `OBS_REDIS_STREAM_KEY`
- `OBS_REDIS_MAXLEN`
- `NINJA_PANEL_URL`
- `BASELINE_PROMPT_ID`

Panel-service env vars:

- `OBS_REDIS_URL` (or `REDIS_URL` fallback)
- `OBS_REDIS_STREAM_KEY`
- `PANEL_REPLAY_LIMIT`

Compose defaults are defined in `docker-compose.yml`.

## Error handling model

Publisher behavior:

- In strict mode (`OBS_EVENTS_STRICT=true` with observability enabled), event publish failures raise and can fail the request.
- In non-strict mode, failures are logged and dropped.

Pipeline errors emit `pipeline.error` events with compact stage/error metadata.

## How to extend safely

### Add a new backend state transition

1. Add event type to `STATE_EVENT_TYPES` in `src/common/observability/events.py`.
2. Emit with `publish_state_event(...)` at the exact lifecycle point.
3. Update `applyEvent(...)` in panel UI.
4. Add or update tests under:
   - `src/apps/api/tests/`
   - `src/apps/ratings_service/tests/`
   - `src/apps/prompt_service/tests/`

### Add a new node/edge in diagram

1. Update `layout.nodes` and `layout.edges` in `panel-service/public/index.html`.
2. Add rendering logic in `Node` for the new node id.
3. Emit events with matching `node` and `edge` ids from backend.

### Change posterior visualization

- Keep `posterior_mu` and `posterior_lambda` as the canonical inputs.
- If you change plot scaling, validate marker alignment against the 0.00/1.00 axis labels.

## Tests and verification

Recommended checks:

```bash
.venv/bin/python src/manage.py test apps.api.tests apps.handler.tests apps.prompt_service.tests apps.ratings_service.tests
node --check panel-service/server.js
docker compose config
```

Manual smoke test:

1. `docker compose up --build`
2. Open panel with a live conversation id.
3. Send a tutor turn, then submit feedback.
4. Confirm `μ/λ/σ` update immediately after feedback (`bandit.arm_state_updated`) before next user turn.

## Known constraints

- Panel is conversation-scoped by design in v1.
- No auth on panel/SSE in v1 (dev-focused).
- Baseline is shadow-only and not used for bandit reward.
- Event replay is limited (default 100) for fast startup.
