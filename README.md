# Adaptive Tutor Layer (Django API)

Adaptive Tutor backend with modular services for prompt optimization, feedback-driven evaluation, embedding sync, drift detection, and GA prompt evolution.

## Services Implemented

- `handler`: request orchestration
- `prompt_service`: contextual bandit prompt selection + reward updates
- `history_service`: turn persistence
- `llm_service`: upstream model wrapper
- `ratings_service`: feedback ingestion and reward orchestration
- `evaluation_service`: Q-score computation/persistence
- `embedding_service`: turn/feedback embedding sync + retry queue
- `drift_detection_service`: periodic drift analysis and GA trigger policy
- `ga_service`: prompt variant generation/publish workflow

## Local Dev (venv)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python src/manage.py migrate
.venv/bin/python src/manage.py runserver
```

## Environment Variables

Core:

- `SQLITE_DB_PATH` (optional, defaults to `src/db.sqlite3`)
- `LLM_API_URL`, `LLM_API_KEY`, `LLM_TIMEOUT_SECONDS`
- `LLM_DEFAULT_MODEL`, `LLM_DEFAULT_TEMPERATURE`, `LLM_DEFAULT_MAX_TOKENS`

Observability:

- `OBSERVABILITY_MODE`, `OBS_EVENTS_STRICT`
- `OBS_REDIS_URL`, `OBS_REDIS_STREAM_KEY`, `OBS_REDIS_MAXLEN`
- `NINJA_PANEL_URL`, `BASELINE_PROMPT_ID`

Embeddings/Drift:

- `CHROMA_HOST`, `CHROMA_PORT`, `CHROMA_COLLECTION_TURNS`
- `EMBEDDING_MODEL_VERSION`

## Docker Compose (API + SQLite + Chroma + Redis + Panel + Drift Worker)

```bash
docker compose up --build -d
```

You can still view logs in daemon mode:

```bash
# all services
docker compose logs -f

# one service
docker compose logs -f api
docker compose logs -f drift-worker
docker compose logs -f chromadb
```

Useful lifecycle commands:

```bash
# stop services (keep containers)
docker compose stop

# stop + remove containers/network (keep volumes)
docker compose down
```

Services:

- API: http://127.0.0.1:8000
- Panel: http://127.0.0.1:3001/?conversation_id=<uuid>
- SQLite DB file: `src/db.sqlite3` (bind-mounted into API and drift worker)
- ChromaDB: `localhost:8001` (persisted via Docker volume `chroma_data`)
- Redis: `localhost:6379`
- Drift worker: background loop every 300s

## Documentation

- Service docs index: `docs/services/service-index.md`
- System interaction overview: `docs/architecture/adaptive-tutor-layer-overview.md`

## Cleanup Helpers

Reset runtime data while preserving default prompts and current users:

```bash
./scripts/clean_dev_db.py
```

Useful options:

- Dry run: `./scripts/clean_dev_db.py --dry-run`
- Also delete users: `./scripts/clean_dev_db.py --drop-users`
- Keep specific prompts: `./scripts/clean_dev_db.py --keep-prompt-id 1 --keep-prompt-id 2`
- Keep all prompts: `./scripts/clean_dev_db.py --keep-all-prompts`
- Skip Chroma cleanup: `./scripts/clean_dev_db.py --no-chroma-clean`
- Target a specific Chroma URL: `./scripts/clean_dev_db.py --chroma-url http://localhost:8001`

## Tutor API (Dev Mode, No Auth)

`POST /api/tutor/respond`

Body:

```json
{
  "user_id": "learner-1",
  "conversation_id": "optional-uuid",
  "question_text": "What is photosynthesis?"
}
```

## Internal API

- `POST /api/internal/drift/run`
- `GET /api/internal/drift/signals`
- `POST /api/internal/ga/evolve`
- `POST /api/internal/prompts/<id>/promote`
- `POST /api/internal/prompts/<id>/retire`

## Drift Worker

Run one cycle:

```bash
.venv/bin/python src/manage.py run_drift_cycle
```

Run loop:

```bash
.venv/bin/python src/manage.py run_drift_cycle --loop --interval 300
```
