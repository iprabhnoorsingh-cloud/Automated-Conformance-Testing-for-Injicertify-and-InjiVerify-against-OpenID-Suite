# Backend — MOSIP Conformance Center

Minimal FastAPI service for Milestone 1 (project foundation). No conformance
execution logic exists yet — this only exposes health/identity endpoints.

## Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

## Test

```bash
pytest
```

## Endpoints

- `GET /` — service identification (`name`, `version`)
- `GET /health` — health check (`{"status": "ok"}`)

## Configuration

Settings are read from environment variables prefixed with `MCC_` (see
`app/config.py`), e.g. `MCC_CORS_ORIGINS`, `MCC_ENVIRONMENT`. No secrets are
hardcoded.
