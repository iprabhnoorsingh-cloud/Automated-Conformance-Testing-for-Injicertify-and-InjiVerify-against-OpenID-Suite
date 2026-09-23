# Architecture

## 1. Purpose

MOSIP Conformance Center is a conformance-testing orchestration platform for
the MOSIP/Inji ecosystem. It will eventually run OpenID Foundation
conformance suites and MOSIP/Inji API test-rigs, normalize their results into
a common format, apply configurable benchmark gates, generate reports, and
expose all of this through a web dashboard and CI/CD integration.

This document describes both what exists today (Milestone 1) and what is
planned for later milestones. Anything listed under "Future" below is
**NOT IMPLEMENTED**.

## 2. Frontend responsibility

A Next.js (TypeScript, Tailwind) dashboard with a navigation shell
(Dashboard, Test Runs, Environments, Reports) and a live backend health
indicator. "Test Runs" is implemented: creating, listing, viewing, deleting,
and executing a Test Run Configuration. Dashboard/Environments/Reports
remain placeholders. In later milestones the dashboard will also visualize
benchmark results and generated reports.

## 3. Backend responsibility

A FastAPI service exposing:

- `GET /health`, `GET /` — service identification and health checking.
- `POST/GET/DELETE /api/test-runs[/{id}]` — Test Run Configuration CRUD
  (Milestone 2). Creates and manages configuration only; never executes
  anything.
- `POST /api/test-runs/{id}/execute`, `GET /api/test-runs/{id}/execution` —
  triggers and observes orchestrated execution of a configured Test Run
  (Milestone 3; see §4).

Configuration is environment-variable-based (see `app/config.py`).

## 4. Orchestrator

Introduced in Milestone 3; Milestone 4 adds a second, real executor
alongside the local mock (see §5). Benchmark evaluation, reporting, and
MOSIP API Test-Rig integration (§6-§9) remain NOT IMPLEMENTED.

```
Test Run Configuration (M2)
        ↓
Orchestrator (M3): load config → build execution plan → run steps in order
        ↓
ExecutorRegistry (M4): resolves a step's executor by its `provider` field
        ├─ "mock"   → MockTestStepExecutor   (M3, local, deterministic, no network)
        └─ "openid" → OpenIDConformanceExecutor (M4, real Conformance Suite REST API)
                            ↓
                      OpenIDConformanceClient → Conformance Suite instance
                            (future) MOSIP API Test-Rig executor  — NOT IMPLEMENTED
        ↓
Result Normalizer (future — NOT IMPLEMENTED)
        ↓
Benchmark Engine (future — NOT IMPLEMENTED)
```

**Execution plan.** One step is planned per (component × test suite) pair
from the Test Run's configuration — e.g. 2 components × 1 suite = 2 steps.
Steps execute sequentially, in a fixed order, within a single synchronous
API call (`POST /api/test-runs/{id}/execute`). Sequential execution is
intentional for this milestone: it's deterministic, easy to debug, and a
natural fit for a local mock executor. The domain model doesn't assume
synchronous execution, so a background/async execution model can replace
how `execute()` is invoked later without changing what it produces.

**Execution lifecycle.** An `Execution` moves through
`QUEUED → RUNNING → PASSED` or `FAILED`. The first step to fail stops the
run (fail-fast) — later steps stay `QUEUED` and are never attempted. The
owning Test Run's own `status` field mirrors this
(`CONFIGURED → QUEUED → RUNNING → PASSED`/`FAILED`), and is only ever
written by the Orchestrator — the configuration API never accepts a
client-supplied status.

**Executor abstraction.** `TestStepExecutor` (`backend/app/executors.py`) is
the seam providers plug into; `ExecutorRegistry` (same file) is the single
place that maps a step's `provider` string to a concrete executor, so the
Orchestrator itself never branches on provider — adding a provider means
registering one more entry (see `app/dependencies.py`), not editing
orchestration logic. An unregistered provider fails just that step with a
structured `unknown_provider` result rather than crashing the whole
execution. `MockTestStepExecutor` (provider `"mock"`) remains exactly as
introduced in M3: deterministic, local, and network-free, reporting a step
FAILED if its id/display name contains "fail" (case-insensitive) and
PASSED otherwise — a test/demo convenience, not a real conformance signal.
An unexpected exception from any executor is caught, logged server-side,
and recorded as a FAILED step with a generic message; it is never allowed
to crash the request or leak internal details to the client.

**Persistence.** Executions are stored via `ExecutionRepository`
(`backend/app/execution_repository.py`), mirroring the M2
`TestRunRepository` pattern: a JSON-file-backed implementation for this
milestone, isolated behind a Protocol so it can be replaced with a
database-backed implementation later without touching orchestration logic.
`GET /api/test-runs/{id}/execution` returns the most recent execution for
that run; re-executing a run creates a new Execution record rather than
mutating the previous one.

## 5. OpenID Foundation Conformance Suite integration (Milestone 4)

Provider `"openid"` drives a real [OpenID Foundation Conformance
Suite](https://gitlab.com/openid/conformance-suite) instance over its REST
API — see `backend/app/openid_client.py` (`OpenIDConformanceClient`) and
`backend/app/openid_executor.py` (`OpenIDConformanceExecutor`).

**M4 boundary — what this milestone does NOT do:**
- Does not start/deploy Inji Certify, Inji Verify, or the Conformance Suite
  itself. You point `OPENID_CONFORMANCE_BASE_URL` at an instance you
  already run (local or staging — never the public certification
  environment by default).
- Does not feed results into the MOSIP/Inji API Test-Rig, evaluate a
  benchmark gate against results, generate a report, or run in CI. Those
  are later milestones; this one only produces a `StepResult` the
  orchestrator already knows how to store and surface.
- Does not invent OpenID test-plan IDs, module IDs, issuer/verifier URLs,
  or client registration values. All of that comes from
  `TestSuiteConfig.openid_config`, supplied by whoever configures the test
  run (see below) — this is exactly where a real Inji Certify OpenID4VCI
  issuer endpoint or Inji Verify OpenID4VP verifier endpoint is supplied,
  once those are available to test against. Today, configuring a suite
  with `provider: "openid"` and no `openid_config` is accepted at
  configuration time (M2 doesn't force OpenID-specific fields onto every
  suite) but fails clearly at execution time with a
  `missing_openid_configuration` error — never a fabricated result.

**Configuration.** A test suite's `openid_config`
(`backend/app/schemas.py: OpenIDSuiteConfig`) carries:
- `plan_name` (required to execute) — a real Conformance Suite plan name.
- `plan_configuration` — arbitrary JSON sent verbatim as the body of
  `POST /api/plan`; this is where target endpoints/credentials for the
  system under test belong.
- `variant` — optional JSON, forwarded to `POST /api/runner` as
  `variant=<json>`.
- `modules` — optional explicit module names; if omitted, the executor
  reads them from the created plan's own `modules` array.

Environment variables (see `backend/.env.example`, `app/config.py`):

| Variable | Purpose | Default |
| --- | --- | --- |
| `OPENID_CONFORMANCE_BASE_URL` | Conformance Suite base URL | none (must be set to execute) |
| `OPENID_CONFORMANCE_API_TOKEN` | Optional bearer token | none (no auth header sent) |
| `OPENID_CONFORMANCE_VERIFY_SSL` | Verify TLS certs | `true` |
| `OPENID_CONFORMANCE_TIMEOUT` | Per-request timeout (seconds) | `30` |
| `OPENID_CONFORMANCE_WAIT_TIMEOUT` | `wait-state` long-poll timeout (seconds) | `60` |
| `OPENID_CONFORMANCE_INTEGRATION` | `1` to opt into the live smoke test | unset (offline) |

These use their literal upstream names (no `MCC_` prefix) via Pydantic
`validation_alias`, since they mirror env vars the OIDF ecosystem's own
tooling already uses. None of these are ever logged; a missing/invalid
base URL raises a clear configuration error rather than a confusing HTTP
failure.

**API flow** (`OpenIDConformanceClient` methods, called by
`OpenIDConformanceExecutor.execute()` in this order):

1. `create_plan(plan_name, plan_configuration)` → `POST /api/plan?planName=...`
   (body = `plan_configuration`), expects HTTP 201 with an `id`.
2. Modules to run = `openid_config.modules` if given, else parsed from the
   plan response's own `modules[].testModule` list.
3. For each module: `create_test_from_plan(module, plan_id, variant)` →
   `POST /api/runner?test=...&plan=...[&variant=<json>]`, expects 201 with
   an `id`.
4. `start_test(module_id)` → `POST /api/runner/{module_id}`. Not every
   module requires this; a 404/400 here is treated as "not required" and
   execution continues.
5. `wait_for_state(module_id, states=["FINISHED","INTERRUPTED"], timeout_ms)`
   → `GET /api/runner/{module_id}/wait-state?states=...&timeoutMs=...`
   (long-polls server-side; the client's own request timeout is set
   comfortably above `timeoutMs` so it doesn't fire first).
6. On `FINISHED`: `get_test_info(module_id)` → `GET /api/info/{module_id}`,
   parsed defensively for a `result`/`status`/`outcome` string.
7. `get_test_log(module_id)` (`GET /api/log/{module_id}`) and
   `export_plan_results(plan_id)` (`GET /api/plan/{plan_id}/export`) are
   implemented on the client and available for future use; this
   milestone's executor doesn't call them as part of the per-step flow
   (keeps the stored StepResult compact — see "Result extraction" below).
8. `get_available_modules()` (`GET /api/runner/available`) is implemented
   for future module-discovery UI; not called by the executor today.

**Plan vs. module.** One configured `"openid"` suite creates exactly one
Conformance Plan and then runs one or more Test Modules against it — the
two are never collapsed into each other. All modules for a step share the
step's single `plan_id`; each module gets its own `module_id`,
`external_state`, and `result`, preserved under
`StepResult.details["modules"]`.

**State mapping.** External Conformance Suite states are never assumed to
equal our internal ones:

| External | Internal (per module) |
| --- | --- |
| `FINISHED` | Inspect `get_test_info()`'s result field; `PASSED` only on an explicit passing value, else `FAILED` |
| `INTERRUPTED` | `FAILED` |
| anything else (incl. our own wait timing out before a terminal state) | `FAILED`, reported as "did not reach a terminal state" |

`FINISHED` is deliberately never treated as `PASSED` by itself — an
indeterminate or unrecognized result value is always `FAILED`, never
fabricated as a pass. A step with multiple modules is `PASSED` only if
every module passed.

**Timeout/retry behavior.** Retries are opt-in per HTTP call
(`retryable=True`) and only ever applied to transient failures (5xx,
timeout, connection error) — 400/401 and other validation failures are
never retried. `create_plan` and `create_test_from_plan` are never
retryable at all: a network failure after the server already created the
resource must not silently become a duplicate plan/module. Backoff between
retries is small and capped at 2 retries (3 attempts total).

**Result extraction.** `StepResult.details` for an `"openid"` step holds
metadata, not raw payloads: `provider`, `plan_name`, `plan_id`, and per
module `module_id`, `module_name`, `external_state`, `result` (and
`error_type` on failure). No log URL is manufactured — `module_id` is the
retrievable reference (`get_test_log`), since the Conformance Suite's own
log page path isn't part of this milestone's confirmed contract.

**Security.** SSRF exposure is limited by construction:
`OPENID_CONFORMANCE_BASE_URL` is an operator-set environment variable, not
something any API caller can influence — a test run's `plan_configuration`
JSON becomes the *body* sent to that fixed, already-configured host, it
never redirects the client to a different one. The base URL is still
validated as a well-formed `http(s)` URL before use. TLS verification is
on by default (`OPENID_CONFORMANCE_VERIFY_SSL=true`); disabling it is an
explicit, documented opt-out for local/dev use, never the default. The
bearer token (if any) is attached as an `Authorization` header and never
logged; a 401 is surfaced as a distinct, structured `authentication_failed`
error.

**Testing without a live server.** `tests/test_openid_client.py` mocks the
HTTP layer with `httpx.MockTransport` (ships with httpx — no extra
dependency) to verify the REST contract offline. `tests/test_openid_executor.py`
exercises the plan/module/state-mapping logic against a fake client
double. `tests/test_openid_integration.py` is a real-server smoke test,
skipped unless `OPENID_CONFORMANCE_INTEGRATION=1` is set — it never runs in
the normal `pytest` invocation or in CI.

**Sync HTTP, by design.** The M3 orchestration engine
(`Orchestrator.execute`, `TestStepExecutor.execute`, the FastAPI route
handlers) is entirely synchronous. Rather than introduce async through that
whole call chain for this one integration, `OpenIDConformanceClient` uses a
blocking `httpx.Client`. FastAPI runs sync `def` route handlers in a
thread pool, so this doesn't block the event loop; revisit if/when
execution moves to a background task model.

## 6. Future: MOSIP API Test-Rig integration (NOT IMPLEMENTED)

Integration with MOSIP/Inji-specific API test-rigs to exercise
implementation-specific behavior not covered by generic OpenID conformance
suites.

## 7. Future: Benchmark engine (NOT IMPLEMENTED)

A configurable rules engine that evaluates normalized test results against
pass/fail benchmarks/gates (e.g. required test coverage, required passing
tests) to produce a conformance verdict.

## 8. Future: Reporting system (NOT IMPLEMENTED)

Generation of human-readable and machine-readable conformance reports from
normalized results and benchmark evaluations, surfaced in the dashboard and
as downloadable artifacts.

## 9. Future: CI/CD integration (NOT IMPLEMENTED)

Hooks to trigger conformance runs from CI/CD pipelines and to gate merges or
releases on conformance benchmark results. The current `.github/workflows/ci.yml`
only builds/tests this repository's own code — it does not run conformance
suites.
