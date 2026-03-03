# Adaptive Tutor Layer: End-to-End Interaction and Function

## Goal
The Adaptive Tutor Layer continuously optimizes tutoring behavior per learner by closing two loops:
- online selection/update loop (per turn), and
- asynchronous drift/evolution loop (per learner).

## Per-Turn Runtime Loop
1. Student sends question (`user_id`, optional `conversation_id`).
2. Handler requests a prompt from Prompt Service for that learner.
3. Prompt Service samples from visible prompt arms:
   - global prompts (`owner_user_id IS NULL`), and
   - learner-private prompts (`owner_user_id = user_id`).
4. LLM Service generates adaptive response (and baseline shadow when observability mode is on).
5. History Service persists the turn.
6. Embedding Service indexes turn documents (`question`, `assistant`) and syncs to Chroma.
7. Student submits feedback.
8. Ratings + Evaluation pipeline computes Q-scores and persists `TurnEvaluation`.
9. Prompt Service applies reward to learner-arm posterior state.

## Per-Learner Adaptation Loop
1. Drift worker sweeps active learners (last 14 days of conversation activity), or runs targeted cycle for one user.
2. DriftDetectionService computes learner-scoped signals from that learner's data:
   - embedding centroid shift,
   - Q-score degradation,
   - feedback deterioration.
3. If trigger policy passes (consecutive high cycles + cooldown), DriftDetectionService triggers GA for that learner.
4. GAService selects parent prompt:
   - first choice: learner's top posterior arm,
   - fallback: latest global active manual prompt.
5. GAService generates prompt variants and publishes learner-private candidates (`owner_user_id = learner`).
6. Prompt Service begins sampling these candidates for that learner only under rollout gates.

## Data Plane
- SQLite (dev):
  - conversations, turns, feedback, evaluations
  - prompts + prompt ownership metadata
  - per-learner bandit state and prompt decisions
  - drift runs/signals and GA evolution runs/candidates
  - embedding index and sync retry jobs
- ChromaDB:
  - vector docs for question/assistant/feedback with metadata (`user_id`, `prompt_id`, etc.)

## Control Plane
- Internal API endpoints support targeted operations by `user_id`:
  - run drift cycle
  - list drift signals
  - trigger GA evolution
  - promote/retire prompt
- Drift worker command supports sweep mode and single-user mode.

## Observability
State transitions stream to Redis and feed Ninja Panel.
- Turn loop events remain conversation-scoped.
- Drift/GA lifecycle events are emitted with learner `user_id` and rendered in user-scoped panel mode (`?user_id=`).

## Dev Defaults
- Unauthenticated APIs/panel (development only).
- SQLite + persisted Chroma volume.
- Fail-open embedding sync with retry jobs.
