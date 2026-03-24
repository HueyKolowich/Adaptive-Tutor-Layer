# Simulation Harness (LLM Student)

## Purpose
Run a local demo harness that simulates a student with a separate local LLM and drives the full production-like API loop:
- `POST /api/tutor/respond`
- `POST /api/turns/<turn_id>/feedback`

This is intended for live Ninja Panel demos where you want to show personalization behavior over many turns.

## Prerequisites
- API stack running locally (`docker compose up -d --build`)
- API reachable at `http://127.0.0.1:8000`
- Ninja Panel reachable at `http://127.0.0.1:3001`
- Separate student LLM endpoint with OpenAI-compatible chat completions

## Local LLM Examples

### Ollama + OpenAI compatibility proxy
If you expose an OpenAI-compatible endpoint locally:
- URL: `http://127.0.0.1:11434/v1/chat/completions`
- Model example: `llama3.1:8b-instruct`

### Any OpenAI-compatible local runtime
Use your own endpoint and model name with:
- `--student-llm-url`
- `--student-model`

## One-Line Demo Run
```bash
.venv/bin/python scripts/run_student_sim_demo.py \
  --api-base http://127.0.0.1:8000 \
  --student-llm-url http://127.0.0.1:11434/v1/chat/completions \
  --student-model llama3.1:8b-instruct \
  --user-id demo-learner-01 \
  --persona socratic_novice \
  --turns 30 \
  --seed 42 \
  --temperature 0.2
```

## Personas
Defined in `scripts/student_profiles.json`:
- `socratic_novice` (default)
- `direct_pragmatic`
- `coach_preferring`

Each profile contains:
- `system_prompt`
- `question_style`
- `feedback_rubric` (with weights)
- `noise` (jitter probability and max delta)
- `target_topic`

## Runtime Behavior
- Student asks one generated question per turn.
- Tutor responds via real API.
- Student model grades tutor response into required v2 metrics:
  - `rating_perceived_progress`
  - `rating_clarity_understanding`
  - `rating_engagement_fit`
- Harness submits feedback and continues.
- Once `conversation_id` is known, harness prints panel URL:
  - `http://127.0.0.1:3001/?conversation_id=<id>`

## Expected Panel Signals (30 turns)
You should observe repeated lifecycle events:
- `student.question_received`
- `bandit.candidates_scored`
- `bandit.prompt_selected`
- `llm.*`
- `turn.persisted`
- `feedback.recorded`
- `qscore.evaluated`
- `bandit.reward_applied`
- `bandit.arm_state_updated`

Over enough turns, traffic/posterior should shift toward the prompt that best matches the persona rubric.

## Troubleshooting
- Invalid JSON from student model:
  - Harness performs one repair pass.
  - If repair fails, harness uses deterministic fallback values.
- API transient failures:
  - Harness retries with bounded exponential backoff.
- Feedback gate (`409 feedback_required`):
  - Harness auto-fetches prior turn from conversation history,
  - generates missing feedback,
  - submits it,
  - retries respond.
- Hard failure behavior:
  - Harness exits non-zero with an `ERROR:` message.

## Useful Flags
- `--persona`
- `--turns`
- `--seed`
- `--temperature`
- `--max-retries`
- `--timeout`
- `--sleep-ms`
- `--conversation-id`
