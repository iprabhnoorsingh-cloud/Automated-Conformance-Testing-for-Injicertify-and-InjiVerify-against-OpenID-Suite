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

Implemented as of Milestone 3, scoped strictly to local, deterministic
execution — no real provider is called yet (see §5/§6 below, still NOT
IMPLEMENTED).

```
Test Run Configuration (M2)
        ↓
Orchestrator (M3): load config → build execution plan → run steps in order
        ↓
TestStepExecutor (pluggable)
        ├─ MockTestStepExecutor (M3, implemented — local, deterministic, no network)
        ├─ OpenID Foundation executor   (future — NOT IMPLEMENTED)
        └─ MOSIP API Test-Rig executor  (future — NOT IMPLEMENTED)
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
the seam future milestones plug real providers into. This milestone ships
only `MockTestStepExecutor`: deterministic, local, and network-free. It
reports a step FAILED if the step's id/display name contains the substring
"fail" (case-insensitive) — a test/demo convenience, not a real conformance
signal — and PASSED otherwise. An unexpected exception from any executor is
caught, logged server-side, and recorded as a FAILED step with a generic
message; it is never allowed to crash the request or leak internal details
to the client.

**Persistence.** Executions are stored via `ExecutionRepository`
(`backend/app/execution_repository.py`), mirroring the M2
`TestRunRepository` pattern: a JSON-file-backed implementation for this
milestone, isolated behind a Protocol so it can be replaced with a
database-backed implementation later without touching orchestration logic.
`GET /api/test-runs/{id}/execution` returns the most recent execution for
that run; re-executing a run creates a new Execution record rather than
mutating the previous one.

## 5. Future: OpenID Foundation integration (NOT IMPLEMENTED)

Integration with the OpenID Foundation conformance test suite to run
standard OpenID/OAuth conformance tests against MOSIP/Inji identity
components and retrieve structured results.

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
