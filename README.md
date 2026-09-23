# MOSIP Conformance Center

A conformance-testing orchestration platform for the MOSIP/Inji ecosystem.
It will orchestrate OpenID Foundation conformance tests and MOSIP/Inji API
test-rigs, normalize their results, apply configurable benchmark gates,
generate reports, and expose all of this through a web dashboard with
CI/CD integration.

See [docs/architecture.md](docs/architecture.md) for the full architecture
and a breakdown of what's implemented vs. planned.

## Current milestone

**Milestone 4 — OpenID Foundation Conformance Suite integration.** Adds a
real executor (`provider: "openid"`) that drives an OpenID Foundation
Conformance Suite instance's REST API — creating a plan, running its test
module(s), waiting for a terminal state, and recording the actual result.
This does **not** start/deploy Inji Certify, Inji Verify, or the
Conformance Suite itself, and does not yet feed the MOSIP/Inji API
Test-Rig, evaluate a benchmark gate, or generate a report. See
[docs/architecture.md](docs/architecture.md) §5 for the full API flow,
state mapping, and configuration.

Prior milestones:

- **Milestone 1 — Project Foundation.** Monorepo, minimal FastAPI backend
  (health/identity endpoints), minimal Next.js dashboard shell, CI.
- **Milestone 2 — Test Run Configuration.** CRUD API and UI for defining a
  Test Run's environment, components, test suites, and benchmark gate.
  Configuration only — no execution.
- **Milestone 3 — Test Orchestrator.** Orchestration engine that executes a
  configured run's test suites as an ordered sequence of steps, via a
  pluggable executor. Introduced the local, deterministic mock executor
  (`provider: "mock"`).

## Future milestones

- MOSIP/Inji API Test-Rig integration
- Automated Inji Certify / Inji Verify lifecycle management
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

A **Test Run Configuration** captures what a conformance run should target:
a run name, environment (`development`/`staging`/`production`), one or more
components (`inji-certify`, `inji-verify`), one or more test suites (each a
`provider`/`suite_id`/`display_name`/`version`, plus `openid_config` when
`provider` is `"openid"` — see below), a benchmark
(`minimum_pass_rate`, `critical_failures_allowed`), and optional
notes/metadata.

**Test suite providers:**
- `"mock"` — local, deterministic, no network (demo/testing).
- `"openid"` — a real OpenID Foundation Conformance Suite instance.
  Requires `openid_config.plan_name` (a real plan name for your own
  Conformance Suite instance — never invented); optional
  `plan_configuration` (JSON body for the plan), `variant`, and `modules`.
  A suite can be saved without `openid_config`, but executing it then fails
  with a clear `missing_openid_configuration` error rather than a
  fabricated result. See [docs/architecture.md](docs/architecture.md) §5.
- MOSIP/Inji API Test-Rig identifiers are not invented yet (later
  milestone) — any other provider string is accepted at configuration time
  but fails execution with a structured `unknown_provider` error.

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

Execution runs one step per (component × test suite) pair, sequentially.
Each step's `provider` determines its executor — `"mock"` never touches the
network; `"openid"` drives a real Conformance Suite instance (see
`OPENID_CONFORMANCE_BASE_URL` in `backend/.env.example`). **No MOSIP/Inji
API Test-Rig is called yet.** See [docs/architecture.md](docs/architecture.md)
for the full execution lifecycle and what's intentionally not implemented
yet.

### OpenID Conformance Suite environment variables

See `backend/.env.example`. At minimum, set `OPENID_CONFORMANCE_BASE_URL`
to a local/staging Conformance Suite instance you control before executing
any `"openid"`-provider suite — never point this at the public
certification environment by default. Without it configured, executing
such a suite fails with a clear configuration error rather than silently
doing nothing.

To run the opt-in live integration smoke test against a real instance:

```bash
OPENID_CONFORMANCE_INTEGRATION=1 \
OPENID_CONFORMANCE_BASE_URL=http://localhost:8443 \
pytest tests/test_openid_integration.py -q
```

This never runs as part of the normal `pytest` suite or CI.
