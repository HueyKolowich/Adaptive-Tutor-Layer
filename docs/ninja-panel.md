# Ninja Panel Engineering Guide

## Scope Modes
Ninja Panel supports two stream scopes:
- conversation mode: `/?conversation_id=<uuid>`
- user mode: `/?user_id=<learner-id>`

Use user mode to visualize per-learner drift/GA lifecycle events.

## Services and Files
- Event contract: `src/common/observability/events.py`
- Event publishing: `src/common/observability/publisher.py`
- Panel backend SSE: `panel-service/server.js`
- Panel frontend graph/UI: `panel-service/public/index.html`

## SSE Endpoint
`GET /events` accepts either `conversation_id` or `user_id`.

Filtering behavior:
- if `user_id` is provided, events are filtered by `event.user_id`.
- else, events are filtered by `event.conversation_id`.

Replay and live tail both use the same filter mode.

## Event Types Used by Panel
Core tutor loop:
- `student.question_received`
- `bandit.candidates_scored`
- `bandit.prompt_selected`
- `llm.*`
- `turn.persisted`
- `feedback.recorded`
- `qscore.evaluated`
- `bandit.reward_applied`
- `bandit.arm_state_updated`

Per-learner adaptation loop:
- `drift.signal_detected`
- `drift.run_completed`
- `drift.ga_triggered`
- `ga.variants_generated`
- `ga.prompt_promoted`

## State Machine Graph
Panel now includes two adaptation nodes:
- `drift`
- `ga`

Additional edges:
- `qscore -> drift`
- `drift -> ga`
- `ga -> policies`

These are highlighted through event `edge` payloads.

## Rendering Notes
- Conversation mode remains primary for turn-by-turn tutoring flows.
- User mode aggregates adaptation events across that learner's conversations.
- Drift/GA cards in UI display run id, severity/breach status, parent prompt, generated/published counts, and promotion status.

## Operational Checks
1. Start stack: `docker compose up -d --build`
2. Open panel:
   - conversation: `http://localhost:3001/?conversation_id=<uuid>`
   - user: `http://localhost:3001/?user_id=<learner-id>`
3. Trigger adaptation:
   - run drift cycle for learner via API or command
   - verify drift/ga nodes activate in user mode.

## Known Constraints
- Panel transport remains unauthenticated for dev.
- Replay window is bounded by `PANEL_REPLAY_LIMIT`.
- User mode can include mixed conversation events for that learner.
