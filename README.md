# MOSIP Conformance Center

A conformance-testing orchestration platform for the MOSIP/Inji ecosystem.
It will orchestrate OpenID Foundation conformance tests and MOSIP/Inji API
test-rigs, normalize their results, apply configurable benchmark gates,
generate reports, and expose all of this through a web dashboard with
CI/CD integration.

See [docs/architecture.md](docs/architecture.md) for the full architecture
and a breakdown of what's implemented vs. planned.

## Current milestone

**Milestone 3 — Test Orchestrator.** Building on Milestone 2's Test Run
Configuration, this adds an orchestration engine that executes a
configured run's test suites against its configured components as an
ordered sequence of steps, via a pluggable executor. Only a deterministic,
local, network-free mock executor is implemented — no real OpenID
Foundation or MOSIP/Inji test-rig integration exists yet. See
[docs/architecture.md](docs/architecture.md) for the full execution
lifecycle and API.

Prior milestones:

- **Milestone 1 — Project Foundation.** Monorepo, minimal FastAPI backend
  (health/identity endpoints), minimal Next.js dashboard shell, CI.
- **Milestone 2 — Test Run Configuration.** CRUD API and UI for defining a
  Test Run's environment, components, test suites, and benchmark gate.
  Configuration only — no execution.

## Future milestones

- Real OpenID Foundation conformance test integration
- Real MOSIP/Inji API test-rig integration
- Configurable benchmark/gate evaluation against real results
- Report generation
- Full CI/CD-gated conformance runs

## Project structure

```
backend/    FastAPI service
frontend/   Next.js dashboard
config/     Shared configuration (future milestones)
reports/    Generated report output (gitignored, empty for now)
docs/       Architecture documentation
```

## Prerequisites

- Python 3.11+ (3.9+ works for this milestone)
- Node.js 20+
- npm

## Backend setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Frontend setup

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

## Running locally

1. Start the backend on port 8000 (see above).
2. Start the frontend on port 3000 (see above).
3. Open http://localhost:3000 — the dashboard's "System status" section
   shows the backend connection state.

## Health-check instructions

- Backend directly: `curl http://localhost:8000/health` → `{"status":"ok"}`
- Backend identity: `curl http://localhost:8000/` → `{"name": "...", "version": "..."}`
- Via frontend: the "Backend" indicator on the dashboard shows
  **Connected** or **Unavailable** based on the configured
  `NEXT_PUBLIC_API_URL`.

## Test Run Configuration & Execution

A **Test Run Configuration** captures what a future conformance run should
target: a run name, environment (`development`/`staging`/`production`),
one or more components (`inji-certify`, `inji-verify`), one or more test
suites (each a `provider`/`suite_id`/`display_name`/`version` — real OpenID
Foundation and MOSIP test-rig identifiers are not invented yet), a
benchmark (`minimum_pass_rate`, `critical_failures_allowed`), and optional
notes/metadata.

Status model: `CONFIGURED → QUEUED → RUNNING → PASSED`/`FAILED`
(`CANCELLED` reserved for later). A client can never set status directly —
only the orchestrator changes it, by executing a run.

API:

| Method | Path                              | Purpose                              |
| ------ | --------------------------------- | ------------------------------------- |
| POST   | `/api/test-runs`                  | Create a configuration (status `CONFIGURED`) |
| GET    | `/api/test-runs`                  | List all configurations               |
| GET    | `/api/test-runs/{id}`             | Get one configuration                 |
| DELETE | `/api/test-runs/{id}`             | Delete a configuration                |
| POST   | `/api/test-runs/{id}/execute`     | Execute a configured run (local mock only) |
| GET    | `/api/test-runs/{id}/execution`   | Get the latest execution for a run    |

Execution runs one step per (component × test suite) pair, sequentially, via
a deterministic local mock executor — **no real OpenID Foundation or
MOSIP/Inji test-rig is called.** See
[docs/architecture.md](docs/architecture.md) for the full execution
lifecycle and what's intentionally not implemented yet.
