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
- `GET /api/test-runs/{id}/report?format=json|markdown` — projects the latest
  persisted execution into a read-only M8 conformance report (see §8).

`scripts/ci_gate.py` (Milestone 9, see §9) is a client of the execute
endpoint, not a backend component.

Configuration is environment-variable-based (see `app/config.py`).

## 4. Orchestrator

Introduced in Milestone 3; Milestone 4 added the OpenID executor;
Milestone 5 added the Inji Certify/Verify Test-Rig executors;
Milestone 6 added result normalization (see §6.5). Benchmark
evaluation was added in Milestone 7 (see §7). Unified reporting and
CI/CD integration (§9) remains NOT IMPLEMENTED.

```
Test Run Configuration (M2)
        ↓
Orchestrator (M3): load config → build execution plan → run steps in order
        ↓
ExecutorRegistry (M4): resolves a step's executor by its `provider` field
        ├─ "mock"        → MockTestStepExecutor      (M3, local, deterministic, no network)
        ├─ "openid"      → OpenIDConformanceExecutor  (M4, real Conformance Suite REST API)
        │                       ↓
        │                 OpenIDConformanceClient → Conformance Suite instance
        ├─ "injicertify" → CertifyApiTestRigExecutor  (M5, real Inji Certify api-test JAR)
        └─ "injiverify"  → VerifyApiTestRigExecutor   (M5, real Inji Verify api-test JAR)
                                ↓
                          InjiApiTestRigExecutor → external `java -jar` process → TestNG report
        ↓ (StepResult produced by executor)
normalize_step_result()  (M6, backend/app/result_normalizer.py)
        ↓ (NormalizedStepResult appended to Execution.normalized_results)
evaluate_benchmark()  (M7, backend/app/benchmark_evaluator.py)
        ↓ (BenchmarkEvaluation stored on Execution.benchmark_evaluation)
build_conformance_report()  (M8, backend/app/report_generator.py)
        ↓ (on-demand JSON or Markdown representation; no persisted artifact)
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

## 6. Inji API Test-Rig integration (Milestone 5)

Providers `"injicertify"`/`"injiverify"` run the actual Inji Certify /
Inji Verify `api-test` Java module (REST Assured + TestNG, built with
Maven) as an **external process**, not an invented REST API — see
`backend/app/inji_executors.py` (`InjiApiTestRigExecutor` and its
`CertifyApiTestRigExecutor`/`VerifyApiTestRigExecutor` subclasses),
`backend/app/inji_process.py` (subprocess control), and
`backend/app/inji_report.py` (TestNG report parsing).

**Why an external process, not a REST client.** Unlike the OpenID
Foundation Conformance Suite (M4), the Inji API Test-Rigs are not
themselves a network service with a REST API to call — they *are* the
test client, built as a shaded JAR (`apitest-<module>-<version>-jar-with-dependencies.jar`)
you run with `java -jar`. The only faithful integration is to invoke that
JAR as a subprocess and read what it produces, exactly as its own
Dockerfile/`entrypoint.sh` do.

**Source-verified facts this was built against** (from the actual
`inji-certify`/`inji-verify` repos, not invented):
- `api-test/entrypoint.sh`: `java -jar -Dmodules="$MODULES" -Denv.user="$ENV_USER" -Denv.endpoint="$ENV_ENDPOINT" -Denv.testLevel="$ENV_TESTLEVEL" apitest-<module>-*-jar-with-dependencies.jar`.
  `-D` flags between `-jar` and the jar path is unusual-looking but was
  confirmed to work with a real JVM before relying on it.
- `InjiTestRunner.java` (both repos) calls `runner.setOutputDirectory("testng-report")`
  on a plain `org.testng.TestNG` with default listeners enabled — so
  `testng-report/testng-results.xml` is **TestNG's own standard XML
  reporter output**, not a MOSIP-specific format. That's why
  `TestRigResultParser` parses it with stdlib `xml.etree.ElementTree`
  against TestNG's public, stable schema rather than a bespoke one.
- `InjiTestRunner.main()` calls `System.exit(0)` **unconditionally** at
  the end, regardless of whether TestNG reported failures. The process
  exit code therefore never determines pass/fail here — only the parsed
  report does (see §9 of the M5 task and "Result determination" below).
- `apitest-commons`' `ConfigManager.getValueForKeyAddToPropertiesMap()`
  checks `System.getenv(<exact property name>)` before falling back to
  its bundled properties file, for every property including
  `injiCertifyBaseURL`, `eSignetbaseurl`, `mosip_components_base_urls`,
  `useCaseToExecute`, `sunBirdBaseURL`, and (generically) `injiVerifyBaseUrl`.
  This is why per-run configuration is passed as **OS environment
  variables** to the child process, not by editing the test rig's
  properties file — that file gets deleted and re-extracted fresh from the
  JAR's own bundled resources on every single run
  (`ExtractResource.removeOldMosipTestTestResource()` +
  `extractCommonResourceFromJar()`), so a pre-written override file would
  simply be wiped before the JAR ever reads it.

**M5 boundary — what this milestone does NOT do:**
- Does not build, deploy, or manage Inji Certify, Inji Verify, Keycloak,
  Postgres, or any other MOSIP infrastructure the test rig itself talks
  to. You point the executor at an already-built `api-test` JAR/working
  directory (`mvn clean install` per that repo's own README) and an
  already-reachable target environment.
- Does not run OpenID Foundation conformance (M4) or evaluate a benchmark
  gate/generate a consolidated report (later milestones) — this produces
  one `StepResult` per suite with normalized TestNG counts, nothing more.
- Does not invent JAR filenames, report schemas, or MOSIP property names —
  every one above was verified from the actual source. Where the source
  didn't pin something down precisely (e.g. whether the report lands
  directly under the working directory or nested under a `target/`
  subfolder), the code stays deliberately configurable/defensive (see
  "Report discovery" below) rather than guessing.

**Configuration.** Two typed, provider-specific suite configs
(`backend/app/schemas.py`), both requiring `test_level`
(`smoke`/`smokeAndRegression` — the only two the source documents),
`env_user`, `env_endpoint`:
- `InjiCertifyTestRigConfig` — plus `use_case_to_execute` (one of
  `mosipid`/`mock`/`sunbird`/`landregistry`/`mdl`/`mdocvp`/`preauthcode`,
  all documented by the Certify `api-test` README) and optional
  `esignet_base_url`, `inji_certify_base_url`,
  `mosip_components_base_urls`, `esignet_actuator_property_section`,
  `use_pre_configured_otp`, `sunbird_base_url`.
- `InjiVerifyTestRigConfig` — plus the one Verify-specific field its
  README documents, `inji_verify_base_url`. No additional Verify fields
  are invented.

As with M4's `openid_config`, these are optional at the configuration
layer (a suite can be saved without one) but required to *execute*: a
`provider: "injicertify"` suite with no `injicertify_config` fails clearly
with `missing_configuration` rather than fabricating values.

Deployment-level settings (`backend/.env.example`, `app/config.py` — no
default paths, since these are inherently machine-specific):

| Variable | Purpose | Default |
| --- | --- | --- |
| `INJI_CERTIFY_TEST_RIG_JAR` | Path/glob to the built Certify JAR | none (must be set to execute) |
| `INJI_CERTIFY_TEST_RIG_WORKDIR` | Directory to run `java` from | none |
| `INJI_VERIFY_TEST_RIG_JAR` | Path/glob to the built Verify JAR | none |
| `INJI_VERIFY_TEST_RIG_WORKDIR` | Directory to run `java` from | none |
| `INJI_TEST_RIG_JAVA` | `java` executable | `java` (resolved via `PATH`) |
| `INJI_TEST_RIG_TIMEOUT` | Subprocess timeout (seconds) | `1800` (these can be slow real runs) |
| `INJI_TEST_RIG_INTEGRATION` | `1` to opt into the live smoke test | unset (offline) |

The JAR path may contain a `*` (e.g. `apitest-injicertify-*-jar-with-dependencies.jar`),
resolved via a bounded glob against the working directory at execution
time — mirroring the actual `entrypoint.sh`'s own use of a shell glob for
the same reason (the version number changes per release). An unconfigured
or unresolvable JAR/working directory fails with a distinct, structured
`error_type` (`test_rig_not_configured`, `jar_not_found`,
`invalid_working_directory`) rather than a confusing crash.

**Subprocess control** (`ProcessRunner` in `app/inji_process.py`): always
an explicit executable + argument list via `subprocess.Popen` — never a
shell string, so no configuration or suite value can inject additional
shell commands. Runs in its own process group (`start_new_session=True`)
so a timeout can reliably `SIGKILL` the whole group, not just the
top-level process, avoiding an orphaned child. stdout/stderr are captured
and passed through `sanitize_output()` (regex-redacts
`Authorization`/`password`/`secret`/`token`/`cookie`-shaped substrings)
before ever being persisted, and only a short excerpt is kept — only when
there's no report to explain the failure (a timeout or a clean exit with
no report at all); a normal run's evidence comes entirely from the parsed
report, never raw logs.

**Result determination — exit code is never trusted alone.** Because
`InjiTestRunner` always exits 0, this executor's status logic is, in
order: (1) timeout → `FAILED`; (2) no `testng-report/testng-results.xml`
found → `FAILED` (`report_not_found`), regardless of exit code; (3) report
found but unparseable → `FAILED` (`malformed_report`); (4) report parsed →
`PASSED` only if `tests_failed == 0 and tests_passed > 0` — an all-skipped
or zero-test report is deliberately never `PASSED`, since nothing was
actually verified.

**Report discovery.** `locate_report()` looks directly under the
configured working directory first, then falls back to a bounded
`working_directory.glob("**/testng-report/testng-results.xml")` search —
bounded to that directory's own subtree only, never escaping upward or
following an absolute path, since the exact nesting (directly under the
working directory vs. under a `target/` build subfolder) wasn't fully
pinned down by the source.

**Result parsing.** `TestRigResultParser` reads TestNG's standard
`<testng-results total="" passed="" failed="" skipped="">` root plus
`<test-method status="FAIL">` entries for a bounded (20-entry) failure
summary, using stdlib `xml.etree.ElementTree` — no XML parsing dependency
was needed. A missing file, malformed XML, or a root missing its count
attributes are each a distinct, explicit error, never a fabricated result.

**Normalized StepResult mapping** (`details`, kept as compact metadata —
never a raw dump of the report or process output): `provider`, `test_rig`,
`test_level`, `process_exit_code`, `timed_out`, `tests_total`,
`tests_passed`, `tests_failed`, `tests_skipped`, `report_path`,
`report_file`, `failure_summary` (bounded list of `Class.method` names).
No execution ID is invented — the report doesn't expose one, so only this
project's own `step_id`/`execution_id` are used, and they're never
conflated with an external identifier.

**Testing without Java/Maven/a real JAR.** `tests/test_inji_process.py`
uses the real Python interpreter as a throwaway "external process" to
exercise real subprocess timeout/kill/output-capture mechanics.
`tests/test_inji_report.py` covers TestNG-schema parsing with representative
fixtures (all-passing, mixed, all-skipped, zero-tests, multiple suites,
malformed, missing). `tests/test_inji_certify_executor.py` and
`test_inji_verify_executor.py` run the real subprocess/report-discovery
path end-to-end against `tests/fixtures/fake_java_rig.py` — a small script
that stands in for `java` (invoked directly via its shebang, so it
receives the exact same argv/env a real JVM would) and can simulate every
scenario (pass, fail, crash, timeout, malformed/missing report) without
Java, Maven, or a real Inji deployment. `tests/test_inji_testrig_integration.py`
is a real-JAR smoke test, skipped unless `INJI_TEST_RIG_INTEGRATION=1` is
set — it never runs in the normal `pytest` invocation or in CI.

**Relationship to M4, M5, and M6.** M4 (OpenID) and M5 (Inji Test-Rigs)
are deliberately separate `TestStepExecutor` implementations producing
provider-specific `StepResult.details` — they are not merged into one
result format at the executor level. M6's result normalizer (§6.5) reads
both shapes and produces a common `NormalizedStepResult` from them.

## 6.5. Result Normalization (Milestone 6)

Implemented in `backend/app/result_normalizer.py`. Converts a raw
`StepResult` from any of the four executors into a `NormalizedStepResult`:
a stable, typed, provider-independent representation that M7 (benchmark
evaluation) and M8 (report generation) consume without provider-specific
parsing or branching on
provider-specific dict shapes.

**Integration point.** `normalize_step_result(result, step)` is called by
the Orchestrator immediately after each step's `StepResult` is appended to
`Execution.step_results`. The resulting `NormalizedStepResult` is appended
to `Execution.normalized_results` (a new field added to the `Execution`
domain model in `orchestration.py`). If the normalizer raises unexpectedly,
the exception is caught, a warning is logged, and the orchestration
continues — the normalizer can never crash a test run.

**Public API:**

| Function | Purpose |
|---|---|
| `normalize_step_result(result, step)` | Normalize one `StepResult` |
| `normalize_execution_results(step_results, steps)` | Normalize all results from one `Execution` |

**`NormalizedStepResult` fields** (all typed; consumers use these, not raw dicts):

| Field | Type | Description |
|---|---|---|
| `step_id` | `str` | Opaque step identifier |
| `display_name` | `str` | Human-readable step name |
| `provider` | `str` | Executor provider (`"mock"`, `"openid"`, `"injicertify"`, `"injiverify"`) |
| `component` | `str` | Component under test (`"inji-certify"`, `"inji-verify"`) |
| `suite_id` | `Optional[str]` | Test suite identifier from `TestSuiteConfig` |
| `status` | `ExecutionStatus` | Step outcome (same vocabulary as M3) |
| `started_at` | `datetime` | Step start time |
| `completed_at` | `Optional[datetime]` | Step end time |
| `duration_seconds` | `Optional[float]` | Wall-clock duration |
| `message` | `str` | Human-readable executor summary (verbatim) |
| `error_type` | `Optional[str]` | Structured error category (`"missing_configuration"`, `"timeout"`, etc.) |
| `normalization_error` | `Optional[str]` | Exception class when normalization itself failed and a safe fallback record was stored |
| `provider_mismatch` | `Optional[str]` | Diagnostic if raw details disagree with the step's canonical provider |
| `inji_test_counts` | `Optional[InjiTestCounts]` | TestNG counts — populated only for Inji providers that produced a parsed report |
| `openid_plan_id` | `Optional[str]` | Conformance Suite plan ID — `openid` only |
| `openid_plan_name` | `Optional[str]` | Conformance Suite plan name — `openid` only |
| `openid_modules` | `Optional[List[OpenIDModuleResult]]` | Per-module results — `openid` only |
| `source_details` | `Optional[Dict]` | Original `StepResult.details` dict, preserved verbatim |
| `raw_result` | `StepResult` | Unmodified originating `StepResult` |

**`InjiTestCounts` fields:** `total`, `passed`, `failed`, `skipped` (int),
`failure_summary` (list of up to 20 failing method names as
`"ClassName.methodName"`).

**`OpenIDModuleResult` fields:** `module_id`, `module_name` (str),
`external_state` (Optional[str] — raw Conformance Suite state), `result`
(str — `"PASSED"`, `"FAILED"`, or `"UNKNOWN"`).

**Design invariants:**
- Never calls the network, launches processes, evaluates benchmarks, or
  generates reports — purely a data transformation.
- `inji_test_counts` is `None` on any Inji error path where the TestNG
  report was not parsed (all four count keys must be present in details).
- `openid_modules` is `None` on OpenID error paths before the plan phase.
- Any missing or malformed field in `details` yields `None` or a safe
  default — never raises.
- `step.provider` is canonical. A conflicting `details["provider"]` is
  preserved in `source_details` and recorded in `provider_mismatch`, but
  never changes provider-specific parsing.
- Every stored `StepResult` has exactly one corresponding normalized result.
  An unexpected normalizer exception produces a `FAILED` fallback with
  `error_type="normalization_failed"`, its exception class in
  `normalization_error`, and the unmodified `raw_result`.
- `source_details` and `raw_result` are preserved verbatim so no
  source-specific information is lost.
- Normalization is deterministic: same inputs always produce equal outputs.

## 7. Benchmark / Gate Evaluation (Milestone 7)

Implemented in `backend/app/benchmark_evaluator.py`. M7 is a pure,
deterministic, provider-neutral gate evaluator. It consumes only the
execution plan, normalized step results, and the existing global
`BenchmarkConfig`; it never inspects raw provider details, OpenID module
payloads, or TestNG details, and performs no I/O.

**Scope.** Evaluation is at the normalized **step** level. There are no
component-, suite-, or provider-specific thresholds; required/forbidden
individual tests, minimum pass counts, and rule combinators remain outside
M7's intentionally small scope.

**Gate rules.** The existing configuration fields apply globally to the
whole Test Run, with all conditions required:

- `pass_rate >= minimum_pass_rate`
- `failed_steps <= critical_failures_allowed`
- evidence is complete

For M7, every normalized step whose status is `FAILED` counts as one
critical failure. Pass rate is `passed_steps / total_planned_steps * 100`;
the denominator is planned steps, not completed steps. Therefore, steps
left unexecuted by M3's fail-fast behavior reduce the pass rate.

**Evidence safety.** M7 fails closed and records machine-readable
`BenchmarkViolation` evidence if raw/normalized cardinality or ID mapping
is invalid, a planned step lacks a normalized result, normalization failed,
or a normalized status is non-final/unknown. It never produces a successful
gate from partial evidence.

**Persistence/API.** Each final `Execution` stores a separate
`benchmark_evaluation` (`BenchmarkEvaluation`) with its own `PASSED`/`FAILED`
verdict, evidence counts, configured thresholds, calculated pass rate, and
violations. This does not change `Execution.status`, which remains the
execution lifecycle/result state. Existing `POST /api/test-runs/{id}/execute`
and `GET /api/test-runs/{id}/execution` responses expose the persisted
evaluation.

## 8. Report Generation (Milestone 8)

Implemented in `backend/app/report_generator.py` and exposed by
`GET /api/test-runs/{id}/report?format=json|markdown`. M8 is a read-only
presentation layer over persisted `TestRunConfig`, `Execution`, normalized
step results, and the persisted M7 `BenchmarkEvaluation`; it never executes
tests, parses raw provider payloads, or re-evaluates a benchmark.

**Formats.** JSON is the canonical typed `ConformanceReport` format.
`format=markdown` returns a deterministic, downloadable `text/markdown`
artifact. Both are generated on demand from persisted source-of-truth data;
M8 creates no report database records and does not use the ignored
`reports/` directory. There is deliberately no wall-clock `generated_at`
field, so repeated generation from the same persisted execution is stable.

**Content.** Reports contain the run/execution summary, copied M7 gate
evidence and violations, ordered normalized step projections, and
display-only component/suite/provider breakdowns. Step projections include
normalized OpenID metadata and Inji TestNG counts where present, but exclude
`raw_result` and `source_details`.

**M7 authority.** The report copies the persisted M7 verdict without
changing or recalculating its values. Incomplete normalized evidence and a
failed benchmark still generate a report so their evidence remains visible;
an execution lacking `benchmark_evaluation` returns HTTP 409 instead of
silently re-evaluating M7. A Reports frontend page remains deferred.

## 9. CI/CD-Gated Conformance Runs (Milestone 9)

Implemented in `scripts/ci_gate.py`. M9 adds no backend endpoint, model,
persistence, or background execution. The script is a thin standard-library
HTTP client:

```
CI → scripts/ci_gate.py → POST /api/test-runs/{id}/execute (synchronous)
   → completed Execution JSON → benchmark_evaluation.status
   → PASSED: exit 0 · otherwise non-zero
```

**M7 authority.** The script only reads the persisted M7 verdict returned in
the execute response; it never recomputes pass rates, thresholds, or
failures. It consumes its own request's response, so it cannot read a stale
or concurrent execution.

**Fail-closed.** Exit `0` only for an explicit `PASSED`. Exit `1`: `FAILED`.
Exit `2`: malformed/non-JSON response, missing `benchmark_evaluation`, or
unrecognized status. Exit `3`: any HTTP error (404/409/422/5xx). Exit `4`:
network failure or timeout. Exit `5`: invalid usage. Configuration: `--run-id`
(required), `--base-url`/`MCC_API_URL`, `--timeout` (default 3600s).

**CI.** The `conformance-gate` job in `.github/workflows/ci.yml` starts the
backend, creates deterministic `mock`-provider runs, requires the passing run
to exit `0` and the failing run to exit `1`. Ordinary CI never invokes the
OpenID Conformance Suite or Inji test-rigs; those integration tests remain
opt-in.

**Deliberately not included.** Async/background execution, polling, an
`execution_id` lookup, a gate endpoint, API authentication, webhooks or
notifications. A long run depends on the HTTP client timeout (`--timeout`)
and on any proxy in between not cutting the connection; a dropped
connection fails the gate (exit 4). The API has no authentication, so the
backend should only be reachable from trusted networks.
