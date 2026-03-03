# Drift Detection Service (Per-User)

Files:
- `src/apps/drift_detection_service/service.py`
- `src/apps/drift_detection_service/models.py`
- `src/apps/drift_detection_service/management/commands/run_drift_cycle.py`

## Purpose
Runs asynchronous learner-scoped monitoring cycles and decides whether to trigger GA prompt evolution for that learner.

## Execution Modes
### `run_cycle_for_user(user_id, now=None)`
Runs one full drift cycle for a single learner.

### `run_sweep(now=None)`
Finds active learners (conversation activity in last 14 days) and runs `run_cycle_for_user` for each.

Worker command (`run_drift_cycle`) now defaults to sweep mode and supports `--user-id` for targeted runs.

## Signal Computation Scope
All signals are filtered to the target learner.

### 1) Embedding centroid shift
Source: `TurnEmbeddingIndex`
Filter:
- `document_type='question'`
- `metadata_json.user_id = <learner>`

Windows:
- recent: last 3 days (limit 120)
- baseline: prior 11 days (limit 360)

Threshold:
- breach if cosine distance `> 0.18`

Minimum samples (dev profile):
- at least 20 vectors in each window.

### 2) Q-score degradation
Source: `TurnEvaluation`
Filter:
- `turn.conversation.user_id = <learner>`

Windowing:
- latest 30 evaluations = recent
- previous 30 evaluations = baseline

Score:
- `mean(baseline) - mean(recent)`

Threshold:
- breach if `>= 0.08`

### 3) Feedback deterioration
Source: `TurnFeedback`
Filter:
- `TurnFeedback.user_id = <learner>`

Windowing:
- latest 30 = recent
- previous 30 = baseline

Low-rating ratio:
- row is low if avg(correctness, helpfulness, clarity) `<= 2.0`
- score = `recent_low_ratio - baseline_low_ratio`

Threshold:
- breach if `>= 0.15`

## Severity and GA Trigger Policy
Per signal:
- `medium` if breached, otherwise `low`.

Per run:
- high severity when 2+ signals breach in the same run.
- breached signals in high runs are upgraded to `high`.

GA trigger gates (all required):
1. current run is high severity,
2. previous completed run for same learner is also high severity,
3. no GA trigger for same learner in last 24h,
4. parent prompt resolution succeeds,
5. GA generates at least one candidate.

## Parent Prompt Rule
Drift delegates parent resolution to GA service:
1. learner's top posterior arm among visible active prompts,
2. fallback: latest global active manual prompt.

## Persistence
- `DriftRun`: includes `subject_user_id`, `scope='user'`, run-level summary, trigger flags.
- `DriftSignal`: includes `subject_user_id`, type, severity, score, threshold, metadata.

## Event Emission
Emits unchanged event types with learner scope in envelope:
- `drift.signal_detected`
- `drift.run_completed`
- `drift.ga_triggered`

Contract details:
- `user_id = subject_user_id`
- payload includes `subject_user_id`
- node/edge for panel graph:
  - `qscore -> drift`
  - `drift -> ga` (on trigger)

## Notes
This service is intentionally threshold-based and deterministic for development iteration. It provides the control boundary and lineage data required for later statistical and model-based drift methods.
