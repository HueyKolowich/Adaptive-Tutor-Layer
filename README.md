# Adaptive Tutor Layer (Django API)

Minimal Django backend for the V0 tutoring flow.

## Feedback Requirement
- Users must submit feedback for the previous tutor response before sending the next question.
- Respond endpoint returns HTTP 409 with `code: feedback_required` when feedback is missing, including `last_turn_id` and `last_turn_index`.
- The sample app UI includes a Feedback tab/panel and shows an alert when blocked.

## Local dev (venv)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python src/manage.py makemigrations
.venv/bin/python src/manage.py migrate
.venv/bin/python src/manage.py runserver
```

Create an admin user:

```bash
.venv/bin/python src/manage.py createsuperuser
```

Add an active prompt (via the admin UI) by going to:

- http://127.0.0.1:8000/admin/

Simple UI (no build tools):

- http://127.0.0.1:8000/app/

## Docker (SQLite persistence)

Build the image:

```bash
docker build -t adaptive-tutor-api .
```

Run with a bind mount so `db.sqlite3` persists on your host:

```bash
docker run -p 8000:8000 \
  -v "$(pwd)/src/db.sqlite3:/app/src/db.sqlite3" \
  -e LLM_API_URL="https://api.x.ai/v1/chat/completions" \
  -e LLM_API_KEY="your-key-here" \
  -e LLM_TIMEOUT_SECONDS="15" \
  -e LLM_DEFAULT_MODEL="grok-4-1-fast-non-reasoning" \
  -e LLM_DEFAULT_TEMPERATURE="0.7" \
  -e LLM_DEFAULT_MAX_TOKENS="512" \
  adaptive-tutor-api
```

Note: The Docker image runs `python src/manage.py migrate --noinput` automatically on startup.

## API

`POST /api/tutor/respond`

```json
{
  "user_id": "user-123",
  "conversation_id": "optional-uuid",
  "question_text": "What is photosynthesis?"
}
```

Successful response (200):

```json
{
  "conversation_id": "uuid",
  "turn_id": "uuid",
  "turn_index": 0,
  "tutor_response": "..."
}
```

Feedback required (409):

```json
{
  "detail": "Feedback required before next turn.",
  "code": "feedback_required",
  "last_turn_id": "uuid",
  "last_turn_index": 0
}
```

`POST /api/turns/<turn_id>/feedback`

Body:

```json
{
  "user_id": "user-123",
  "rating_correctness": 5,
  "rating_helpfulness": 4,
  "rating_clarity": 4,
  "free_text": "optional"
}
```

### Quick Test (cURL)

```bash
# First turn (allowed)
curl -sS -X POST http://localhost:8000/api/tutor/respond \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user-123","question_text":"What is backpropagation?"}'

# Second turn without feedback (blocked)
curl -sS -X POST http://localhost:8000/api/tutor/respond \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user-123","conversation_id":"<copy from first>","question_text":"Explain gradients"}'

# Submit feedback
curl -sS -X POST http://localhost:8000/api/turns/<last_turn_id>/feedback \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user-123","rating_correctness":5,"rating_helpfulness":4,"rating_clarity":4,"free_text":"Good explanation."}'

# Next turn (allowed)
curl -sS -X POST http://localhost:8000/api/tutor/respond \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"user-123","conversation_id":"<same>","question_text":"Show an example"}'
```
