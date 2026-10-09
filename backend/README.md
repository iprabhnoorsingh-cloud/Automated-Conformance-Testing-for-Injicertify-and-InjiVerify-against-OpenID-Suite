# Backend — MOSIP Conformance Center

FastAPI service for configuring test runs, orchestrating conformance evaluations, and serving execution reports.

## Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
export MCC_API_KEY="$(openssl rand -hex 32)"
uvicorn app.main:app --reload --port 8000
```

**Single-Worker Deployment Constraint:**
Run a **single** Uvicorn process only. Do not pass `--workers` > 1.
The system relies on in-process `threading.Condition` limits for bounded execution concurrency, an in-memory `asyncio.Queue` for background async workers, and process-local JSON persistence.

## Test

```bash
pytest
```

## Endpoints

- `GET /health` — health check (`{"status": "ok"}`); the only unauthenticated endpoint.
- `GET /api/test-runs` — test run configuration
- `POST /api/test-runs/{run_id}/execute` — synchronous M9 CI execution gate
- `POST /api/test-runs/{run_id}/execute-async` — background execution queue (M11-A)
- `GET /api/executions/{execution_id}` — execution status
- `GET /api/test-runs/{run_id}/executions` — execution history
- `GET /api/test-runs/{run_id}/report` — download evaluation report

All endpoints except `/health` require `Authorization: Bearer <MCC_API_KEY>`.

## Execution Model

The system supports both synchronous CI/CD execution and asynchronous background execution. Both models share a single global execution capacity to prevent test environment flooding.
If capacity or the async queue is full, the server returns HTTP 429.

At startup, any stale `QUEUED` or `RUNNING` executions from a previous aborted run are marked as `ERROR`.

## Configuration

Settings are read from environment variables prefixed with `MCC_` (see
`app/config.py`), e.g. `MCC_API_KEY`, `MCC_CORS_ORIGINS`, `MCC_MAX_ASYNC_QUEUE_SIZE`. No secrets are
hardcoded.
