# MOSIP Conformance Center

A conformance-testing orchestration platform for the MOSIP/Inji ecosystem.
It will orchestrate OpenID Foundation conformance tests and MOSIP/Inji API
test-rigs, normalize their results, apply configurable benchmark gates,
generate reports, and expose all of this through a web dashboard with
CI/CD integration.

See [docs/architecture.md](docs/architecture.md) for the full architecture
and a breakdown of what's implemented vs. planned.

## Current milestone

**Milestone 5 — Inji API Test-Rig integration.** Adds two real executors
(`provider: "injicertify"` / `"injiverify"`) that run the actual Inji
Certify / Inji Verify `api-test` Java module (REST Assured + TestNG,
Maven-built) as an external process — invoking its real JAR with the same
JVM arguments and environment-variable property overrides its own
`entrypoint.sh`/`ConfigManager` use, then parsing its real TestNG
`testng-results.xml` report. This does **not** build/deploy Inji Certify,
Inji Verify, or any MOSIP infrastructure, run OpenID conformance,
evaluate a benchmark gate, or generate a consolidated report. See
[docs/architecture.md](docs/architecture.md) §6 for the full source-verified
contract, subprocess control, and result parsing.

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
- **Milestone 4 — OpenID Foundation Conformance Suite integration.** Real
  executor (`provider: "openid"`) driving a Conformance Suite instance's
  REST API.

## CI/CD conformance gate (Milestone 9)

`scripts/ci_gate.py` executes a Test Run through the existing synchronous
`POST /api/test-runs/{id}/execute` endpoint and exits according to the
persisted M7 verdict (`benchmark_evaluation.status`) in the response. It
does not evaluate anything itself — M7 remains the source of truth — and it
is fail-closed: only an explicit `PASSED` verdict exits `0`.

```bash
python scripts/ci_gate.py --run-id <test-run-id> [--base-url http://localhost:8000] [--timeout 3600]
```

- `--run-id` (required): the Test Run to execute.
- `--base-url` or env `MCC_API_URL` (default `http://localhost:8000`).
- `--timeout`: seconds to wait for the synchronous run (default 3600).
- Standard library only. The API key is read from env `MCC_API_KEY` (never an
  argument) and sent as `Authorization: Bearer`; it is never printed.

| Exit | Meaning |
| ---- | ------- |
| 0 | `benchmark_evaluation.status == "PASSED"` |
| 1 | `FAILED` (gate failed; violations printed to stderr) |
| 2 | non-JSON/malformed response, missing evaluation, or unrecognized status |
| 3 | HTTP error from the backend (404, 409, 422, 5xx, ...) |
| 4 | network failure or timeout |
| 5 | invalid usage (bad base URL / timeout) |

Ordinary CI (`conformance-gate` job in `.github/workflows/ci.yml`) proves
the mechanism using only the deterministic `mock` provider: one passing run
(must exit 0) and one failing run (must exit 1). Real OpenID Conformance and
Inji test-rig integration tests remain opt-in and never run in CI.

## Security (Milestone 10)

**Authentication.** Every endpoint except `GET /health` requires
`Authorization: Bearer <MCC_API_KEY>`. Set `MCC_API_KEY` (at least 16
characters, e.g. `openssl rand -hex 32`) in the backend's environment; it is
never stored in Git. If it is unset or too short the API **fails closed**
(401 for everything but `/health`). The same variable is read by
`scripts/ci_gate.py`. In GitHub Actions the `conformance-gate` job generates a
throwaway key per run. **The bundled Next.js frontend does not send this key
yet**, so it cannot talk to an authenticated backend until a server-side
proxy / UI login is added.

**SSRF policy.** Destination URLs in a test run (Inji `env_endpoint` /
`*_base_url` fields and any URL inside an OpenID `plan_configuration`) must be
`http(s)`, carry no userinfo and resolve to public addresses only — no
loopback, private (RFC1918), link-local, CGNAT or IPv6 equivalents. Checked
at creation (HTTP 422) and again with DNS at execution time. This is **not
complete SSRF prevention**: the Inji Java test rigs and the OpenID Conformance
Suite make the real connections later, re-resolve DNS themselves and may
follow redirects, so DNS rebinding is not covered. Use network egress controls
around those processes. Targets on private networks are rejected by design.

**Concurrency.** At most `MCC_MAX_CONCURRENT_EXECUTIONS` (default 2)
executions run at once per process; further `POST .../execute` calls get HTTP
429 and start nothing. Execution is still synchronous.

**Secrets.** Credentials (`env_user`, anything named like a
secret/password/token/credential/private key/API key/JWKS, PEM private keys)
are redacted in every API response and report; the stored JSON files keep the
real values because executions need them, so protect `backend/data/`.
Credentials passed as `-Denv.user=...` are visible in the OS process list of
the host running the Java test rig (upstream contract).

**Deployment constraint — single worker only.** Persistence is JSON files
guarded by an in-process lock, and the concurrency limiter is in-process.
Run exactly one Uvicorn process: **never use `--workers` > 1**, never run
multiple replicas against the same `backend/data/`. Multi-process deployment
needs a persistence redesign first.

## Future milestones

- Automated Inji Certify / Inji Verify lifecycle management (build/deploy)
- Unified result normalization across OpenID and Inji Test-Rig evidence
- Configurable benchmark/gate evaluation against real results
- Report generation

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
export MCC_API_KEY="$(openssl rand -hex 32)"   # required; all endpoints except /health reject requests without it
uvicorn app.main:app --reload --port 8000        # single worker only (see Security)
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
  See [docs/architecture.md](docs/architecture.md) §5.
- `"injicertify"` / `"injiverify"` — the real Inji Certify / Inji Verify
  API Test-Rig, run as an external Java process. Requires
  `injicertify_config` / `injiverify_config`: `test_level`
  (`smoke`/`smokeAndRegression`), `env_user`, `env_endpoint`, and
  (Certify only) `use_case_to_execute` plus optional
  eSignet/injiCertify/mosip-components/sunbird overrides; (Verify only)
  the required `inji_verify_base_url`. See
  [docs/architecture.md](docs/architecture.md) §6.
- Every `*_config` above is optional at configuration time — a suite can
  be saved without one — but required to *execute*; a mismatch fails with
  a clear `missing_configuration`/`missing_openid_configuration` error
  rather than a fabricated result. Any other provider string is accepted
  at configuration time but fails execution with a structured
  `unknown_provider` error.

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
Each step's `provider` determines its executor — `"mock"` never touches
the network; `"openid"` drives a real Conformance Suite instance;
`"injicertify"`/`"injiverify"` launch the real Inji API Test-Rig JAR as a
subprocess. See [docs/architecture.md](docs/architecture.md) for the full
execution lifecycle and what's intentionally not implemented yet.

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

### Inji API Test-Rig environment variables

See `backend/.env.example`. Set `INJI_CERTIFY_TEST_RIG_JAR` /
`INJI_CERTIFY_TEST_RIG_WORKDIR` (and/or the `_VERIFY_` equivalents) to a
locally built `api-test` JAR/directory — clone `inji-certify`/`inji-verify`
and run `mvn clean install` per that repo's own README first; this project
does not build or fetch that JAR for you. `INJI_TEST_RIG_JAVA` (default
`java`) and `INJI_TEST_RIG_TIMEOUT` (default 1800s) are also configurable.
Without a configured JAR/working directory, executing an
`"injicertify"`/`"injiverify"` suite fails clearly with
`test_rig_not_configured` rather than silently doing nothing.

To run the opt-in live smoke test against a real built JAR:

```bash
INJI_TEST_RIG_INTEGRATION=1 \
INJI_CERTIFY_TEST_RIG_JAR=/path/to/inji-certify/api-test/target/apitest-injicertify-*-jar-with-dependencies.jar \
INJI_CERTIFY_TEST_RIG_WORKDIR=/path/to/inji-certify/api-test/target \
pytest tests/test_inji_testrig_integration.py -q
```

This never runs as part of the normal `pytest` suite or CI.
