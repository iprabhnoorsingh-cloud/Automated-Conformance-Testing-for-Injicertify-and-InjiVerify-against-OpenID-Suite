"""OpenID Foundation Conformance Suite executor.

Implements the M3 TestStepExecutor protocol (app/executors.py) by driving a
real Conformance Suite instance via OpenIDConformanceClient
(app/openid_client.py). Registered against provider "openid" in the
ExecutorRegistry (see app/dependencies.py) — the Orchestrator otherwise
treats it exactly like any other executor.

Plan/module relationship: one configured "openid" test suite creates one
Conformance Plan, which in turn produces one or more Test Modules. This
executor creates the plan once per step, then runs each configured (or
plan-resolved) module against it. All of that is reported as a single
StepResult for the step, with structured per-module details preserved
under `details["modules"]` — the M3 execution model doesn't need to grow a
sub-step concept for this.

State mapping (external Conformance Suite state -> internal ExecutionStatus
for this step):
    FINISHED    -> inspect the module's persisted result; PASSED only if it
                   explicitly reports a passing outcome, else FAILED.
    INTERRUPTED -> FAILED.
    (anything else, incl. our own wait timing out) -> FAILED, reported as
                   "did not reach a terminal state".
FINISHED is deliberately never assumed to mean PASSED — the actual test
result is read from GET /api/info/{module_id} defensively, since the exact
response shape isn't pinned down by this milestone's source contract. An
indeterminate result is always treated as FAILED, never fabricated as
PASSED.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.executors import ExecutionContext
from app.openid_client import (
    OpenIDConformanceAuthError,
    OpenIDConformanceBadRequestError,
    OpenIDConformanceClient,
    OpenIDConformanceConfigurationError,
    OpenIDConformanceConnectionError,
    OpenIDConformanceError,
    OpenIDConformanceNotFoundError,
    OpenIDConformanceResponseError,
    OpenIDConformanceServerError,
    OpenIDConformanceTimeoutError,
)
from app.orchestration import ExecutionStatus, Step, StepResult

logger = logging.getLogger(__name__)

_PASS_VALUES = {"passed", "pass", "success", "ok"}
_FAIL_VALUES = {"failed", "fail", "warning", "review", "error"}

_ERROR_TYPES = {
    OpenIDConformanceConfigurationError: "configuration_error",
    OpenIDConformanceAuthError: "authentication_failed",
    OpenIDConformanceBadRequestError: "bad_request",
    OpenIDConformanceNotFoundError: "not_found",
    OpenIDConformanceServerError: "conformance_suite_unavailable",
    OpenIDConformanceTimeoutError: "timeout",
    OpenIDConformanceConnectionError: "connection_failed",
    OpenIDConformanceResponseError: "malformed_response",
}


class OpenIDConformanceExecutor:
    def __init__(self, client: OpenIDConformanceClient, wait_timeout_ms: int = 60000):
        self._client = client
        self._wait_timeout_ms = wait_timeout_ms

    def execute(self, step: Step, context: ExecutionContext) -> StepResult:
        started_at = datetime.now(timezone.utc)
        suite_config = step.suite_config or {}
        openid_config = suite_config.get("openid_config")

        if not openid_config or not openid_config.get("plan_name"):
            return self._result(
                step,
                started_at,
                ExecutionStatus.FAILED,
                (
                    f"Step '{step.display_name}' has provider 'openid' but no "
                    "openid_config.plan_name configured. Real OpenID Foundation "
                    "test plan identifiers must be supplied explicitly — none "
                    "are invented automatically."
                ),
                {"provider": "openid", "error_type": "missing_openid_configuration"},
            )

        plan_name = openid_config["plan_name"]
        plan_configuration = openid_config.get("plan_configuration") or {}
        variant = openid_config.get("variant")
        explicit_modules = openid_config.get("modules")

        details: Dict[str, Any] = {"provider": "openid", "plan_name": plan_name}

        try:
            plan = self._client.create_plan(plan_name, plan_configuration)
            plan_id = plan["id"]
            details["plan_id"] = plan_id

            modules = explicit_modules or self._resolve_modules_from_plan(plan)
            if not modules:
                return self._result(
                    step,
                    started_at,
                    ExecutionStatus.FAILED,
                    (
                        f"No test modules resolved from plan '{plan_id}' and "
                        "none were explicitly configured (openid_config.modules)."
                    ),
                    {**details, "error_type": "no_modules_resolved"},
                )

            module_results: List[Dict[str, Any]] = []
            overall_status = ExecutionStatus.PASSED
            for module_name in modules:
                module_detail, module_status = self._run_module(
                    module_name, plan_id, variant
                )
                module_results.append(module_detail)
                if module_status != ExecutionStatus.PASSED:
                    overall_status = ExecutionStatus.FAILED

            details["modules"] = module_results
            message = (
                f"OpenID Conformance plan '{plan_name}' ({plan_id}): "
                f"{len(module_results)} module(s) executed, "
                f"overall {overall_status.value}."
            )
            return self._result(step, started_at, overall_status, message, details)

        except OpenIDConformanceError as exc:
            error_type = _ERROR_TYPES.get(type(exc), "conformance_suite_error")
            return self._result(
                step,
                started_at,
                ExecutionStatus.FAILED,
                str(exc),
                {**details, "error_type": error_type},
            )

    def _run_module(
        self, module_name: str, plan_id: str, variant: Optional[Dict[str, Any]]
    ) -> Tuple[Dict[str, Any], ExecutionStatus]:
        created = self._client.create_test_from_plan(module_name, plan_id, variant)
        module_id = created["id"]

        try:
            self._client.start_test(module_id)
        except (OpenIDConformanceNotFoundError, OpenIDConformanceBadRequestError):
            # Not every module requires an explicit start; the Conformance
            # Suite signals "not applicable" via 404/400 here for those.
            logger.debug(
                "start_test for module %s returned 404/400 — treating as "
                "'explicit start not required for this module'.",
                module_id,
            )

        wait_response = self._client.wait_for_state(
            module_id, states=["FINISHED", "INTERRUPTED"], timeout_ms=self._wait_timeout_ms
        )
        external_state = None
        if isinstance(wait_response, dict):
            external_state = wait_response.get("status") or wait_response.get("state")

        module_detail: Dict[str, Any] = {
            "module_id": module_id,
            "module_name": module_name,
            "external_state": external_state,
        }

        if external_state == "INTERRUPTED":
            module_detail["result"] = "FAILED"
            return module_detail, ExecutionStatus.FAILED

        if external_state != "FINISHED":
            module_detail["result"] = "UNKNOWN"
            module_detail["reason"] = (
                "Did not reach a terminal state within the configured wait "
                "timeout."
            )
            return module_detail, ExecutionStatus.FAILED

        info: Dict[str, Any] = {}
        try:
            info = self._client.get_test_info(module_id)
        except OpenIDConformanceError:
            logger.warning("Could not retrieve test info for module %s", module_id)

        result_value = self._extract_result(info)
        module_detail["result"] = result_value
        status = (
            ExecutionStatus.PASSED
            if result_value == "PASSED"
            else ExecutionStatus.FAILED
        )
        return module_detail, status

    @staticmethod
    def _resolve_modules_from_plan(plan: Dict[str, Any]) -> List[str]:
        modules = plan.get("modules")
        if not isinstance(modules, list):
            return []
        names = []
        for entry in modules:
            if isinstance(entry, dict) and isinstance(entry.get("testModule"), str):
                names.append(entry["testModule"])
        return names

    @staticmethod
    def _extract_result(info: Dict[str, Any]) -> str:
        candidate = None
        if isinstance(info, dict):
            for key in ("result", "status", "outcome"):
                value = info.get(key)
                if isinstance(value, str):
                    candidate = value
                    break
        if candidate is None:
            return "UNKNOWN"
        normalized = candidate.strip().lower()
        if normalized in _PASS_VALUES:
            return "PASSED"
        if normalized in _FAIL_VALUES:
            return "FAILED"
        return "UNKNOWN"

    @staticmethod
    def _result(
        step: Step,
        started_at: datetime,
        status: ExecutionStatus,
        message: str,
        details: Dict[str, Any],
    ) -> StepResult:
        return StepResult(
            step_id=step.step_id,
            status=status,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            message=message,
            details=details,
        )
