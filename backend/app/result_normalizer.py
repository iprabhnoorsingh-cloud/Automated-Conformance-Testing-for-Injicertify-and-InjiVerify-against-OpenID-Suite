"""Unified Result Normalizer (Milestone 6).

Converts a raw ``StepResult`` — as produced by any of the four executors
(``mock``, ``openid``, ``injicertify``, ``injiverify``) — into a
``NormalizedStepResult``: a stable, typed representation whose shape does
not depend on which provider produced the underlying data.

Design principles
-----------------
* **Read-only**: the normalizer never modifies a ``StepResult``, calls the
  network, or launches processes.
* **Preserve, don't destroy**: source-specific detail is moved into
  ``source_details`` rather than discarded so that M8 (reporting) can still
  surface it, and ``raw_result`` carries the original ``StepResult`` for any
  consumer that needs unfiltered access.
* **Safe by default**: any missing or unexpected field in ``details`` yields a
  reasonable default or ``None`` — never an exception.  The orchestrator must
  never crash because the normalizer encountered an unexpected value.
* **Status fidelity**: the existing ``ExecutionStatus`` vocabulary is reused
  exactly — no new status strings are introduced.  An unrecognised string
  is mapped to ``ExecutionStatus.FAILED`` (conservative, never fabricates a
  pass).
* **Typed**: every field has an explicit type annotation so M7 and M8 can
  consume ``NormalizedStepResult`` without defensive dict access.

Provider ``details`` contracts (verified from source + tests)
-------------------------------------------------------------
``mock``
    ``details`` is ``None`` — executor never sets it.

``openid`` (``OpenIDConformanceExecutor``)
    Success path:
        ``provider``, ``plan_name``, ``plan_id``,
        ``modules: list[{module_id, module_name, external_state, result}]``
    Error paths additionally carry ``error_type``.

``injicertify`` / ``injiverify`` (``InjiApiTestRigExecutor`` subclasses)
    Success path:
        ``provider``, ``test_rig``, ``test_level``,
        ``process_exit_code``, ``timed_out``,
        ``tests_total``, ``tests_passed``, ``tests_failed``, ``tests_skipped``,
        ``report_path``, ``report_file``, ``failure_summary: list[str]``
    Error paths may omit counts/report fields and carry ``error_type``.
    Timeout path additionally carries ``process_output_excerpt``.

Orchestrator-level failures (not from any executor)
    ``details`` carries ``error_type`` (e.g. ``unknown_provider``,
    ``internal_executor_error``); provider may be present.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.orchestration import ExecutionStatus, Step, StepResult


# ---------------------------------------------------------------------------
# Normalized sub-models
# ---------------------------------------------------------------------------


class OpenIDModuleResult(BaseModel):
    """One OpenID Conformance Suite test module's outcome within a step.

    Mirrors the per-entry shape stored in
    ``StepResult.details["modules"]`` by ``OpenIDConformanceExecutor``
    but typed.  A step may run multiple modules.
    """

    module_id: str
    module_name: str
    external_state: Optional[str] = None
    """Raw terminal state string from the Conformance Suite
    (``"FINISHED"``, ``"INTERRUPTED"``, or ``None`` if not reached)."""
    result: str
    """Conformance Suite result: ``"PASSED"``, ``"FAILED"``, or ``"UNKNOWN"``."""


class InjiTestCounts(BaseModel):
    """Aggregate test counts from one Inji API Test-Rig run."""

    total: int
    passed: int
    failed: int
    skipped: int
    failure_summary: List[str] = Field(default_factory=list)
    """Up to 20 failing test method names, as ``"ClassName.methodName"``."""


class NormalizedStepResult(BaseModel):
    """A stable, provider-independent representation of one step's outcome.

    Consumers (M7 benchmark engine, M8 report generator) should rely on
    fields at the top level.  Provider-specific detail is preserved in
    ``source_details`` and the original ``StepResult`` in ``raw_result``
    — those are evidence for auditing, not the primary contract.
    """

    # --- Identity ----------------------------------------------------------
    step_id: str
    """Opaque identifier: ``"{component}:{provider}:{suite_id}"``."""
    display_name: str
    """Human-readable step name."""
    provider: str
    """Executor provider: ``"mock"``, ``"openid"``, ``"injicertify"``,
    ``"injiverify"``, or an unknown string from an error path."""
    component: str
    """Component under test, e.g. ``"inji-certify"`` or ``"inji-verify"``."""
    suite_id: Optional[str] = None
    """Test suite identifier from the originating ``TestSuiteConfig``."""

    # --- Status ------------------------------------------------------------
    status: ExecutionStatus
    """Normalised outcome — one of the ``ExecutionStatus`` enum values.
    Unknown strings from ``details`` are mapped to ``FAILED``."""

    # --- Timing ------------------------------------------------------------
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    """Wall-clock duration derived from ``started_at``/``completed_at``.
    ``None`` when ``completed_at`` is absent."""

    # --- Human-readable summary --------------------------------------------
    message: str
    """Human-readable summary from the executor (preserved verbatim)."""
    error_type: Optional[str] = None
    """Structured error category from ``details["error_type"]``, or
    ``None`` on success."""
    normalization_error: Optional[str] = None
    """Normalizer failure class when this is a safe fallback record.
    ``None`` for normally normalized results."""
    provider_mismatch: Optional[str] = None
    """Diagnostic when provider-specific details disagree with the planned
    step's canonical provider. The details remain available in
    ``source_details`` but never control provider-specific parsing."""

    # --- Provider-specific counts (Inji Test-Rigs only) --------------------
    inji_test_counts: Optional[InjiTestCounts] = None
    """Populated only for ``injicertify``/``injiverify`` steps that produced
    a parsed TestNG report.  ``None`` for ``mock``, ``openid``, and any
    Inji error path where the report was not parsed."""

    # --- Provider-specific details (OpenID only) ---------------------------
    openid_plan_id: Optional[str] = None
    """Conformance Suite plan ID — populated only for ``openid`` steps."""
    openid_plan_name: Optional[str] = None
    """Conformance Suite plan name — populated only for ``openid`` steps."""
    openid_modules: Optional[List[OpenIDModuleResult]] = None
    """Per-module results — populated only for ``openid`` steps that
    reached the module-execution phase."""

    # --- Source preservation -----------------------------------------------
    source_details: Optional[Dict[str, Any]] = None
    """The original ``StepResult.details`` dict, preserved verbatim so that
    M8 can surface any provider-specific field without normalization loss."""
    raw_result: StepResult
    """The unmodified originating ``StepResult``, included as a non-lossy
    audit trail.  Serialized by Pydantic when the normalized result is
    stored or sent over the wire."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_step_result(step_result: StepResult, step: Step) -> NormalizedStepResult:
    """Return a ``NormalizedStepResult`` for one completed step.

    Args:
        step_result: The raw outcome produced by an executor.
        step:        The ``Step`` that was executed; carries identity
                     fields (component, provider, suite_id from
                     suite_config) that are not repeated on
                     ``StepResult``.

    Returns:
        A fully populated ``NormalizedStepResult``.  Never raises; any
        unexpected or missing field in ``step_result.details`` yields a
        safe default.
    """
    details: Dict[str, Any] = step_result.details or {}
    provider = step.provider

    duration = _compute_duration(step_result.started_at, step_result.completed_at)
    suite_id = _extract_suite_id(step)

    return NormalizedStepResult(
        # Identity
        step_id=step_result.step_id,
        display_name=step.display_name,
        provider=provider,
        component=step.component,
        suite_id=suite_id,
        # Status
        status=step_result.status,
        # Timing
        started_at=step_result.started_at,
        completed_at=step_result.completed_at,
        duration_seconds=duration,
        # Summary
        message=step_result.message,
        error_type=_safe_str(details.get("error_type")),
        provider_mismatch=_provider_mismatch(details, provider),
        # Provider-specific: Inji
        inji_test_counts=_extract_inji_counts(provider, details),
        # Provider-specific: OpenID
        openid_plan_id=_safe_str(details.get("plan_id")),
        openid_plan_name=_safe_str(details.get("plan_name")),
        openid_modules=_extract_openid_modules(provider, details),
        # Source preservation
        source_details=details if details else None,
        raw_result=step_result,
    )


def normalization_failure_result(
    step_result: StepResult, step: Step, error: Exception
) -> NormalizedStepResult:
    """Return a lossless, failed fallback when normalizing unexpectedly fails.

    This function deliberately relies only on the already-validated Step and
    StepResult models.  It preserves execution cardinality and makes the
    failure visible to downstream consumers instead of silently omitting a
    result.
    """
    details = step_result.details or {}
    return NormalizedStepResult(
        step_id=step_result.step_id,
        display_name=step.display_name,
        provider=step.provider,
        component=step.component,
        suite_id=_extract_suite_id(step),
        status=ExecutionStatus.FAILED,
        started_at=step_result.started_at,
        completed_at=step_result.completed_at,
        duration_seconds=_compute_duration(
            step_result.started_at, step_result.completed_at
        ),
        message="Result normalization failed; see normalization_error.",
        error_type="normalization_failed",
        normalization_error=type(error).__name__,
        provider_mismatch=_provider_mismatch(details, step.provider),
        source_details=details if details else None,
        raw_result=step_result,
    )


def normalize_execution_results(
    step_results: List[StepResult],
    steps: List[Step],
) -> List[NormalizedStepResult]:
    """Normalize all step results from one ``Execution`` in order.

    ``step_results`` and ``steps`` need not be in the same order; they are
    matched by ``step_id``.  Steps that have no corresponding result (e.g.
    they were never reached because of fail-fast) are silently skipped —
    only executed steps have a ``StepResult``.

    Args:
        step_results: ``Execution.step_results`` list.
        steps:        ``Execution.steps`` list (the plan).

    Returns:
        Normalized results in the same order as ``step_results``.
    """
    step_index: Dict[str, Step] = {s.step_id: s for s in steps}
    normalized: List[NormalizedStepResult] = []
    for sr in step_results:
        matched_step = step_index.get(sr.step_id)
        if matched_step is None:
            # Defensive: a result with no matching plan step should not
            # crash M7/M8.  Synthesize a minimal Step from what we know.
            matched_step = _synthesize_step(sr)
        normalized.append(normalize_step_result(sr, matched_step))
    return normalized


# ---------------------------------------------------------------------------
# Internal helpers — all pure functions, no I/O, no side effects
# ---------------------------------------------------------------------------


def _provider_mismatch(details: Dict[str, Any], provider: str) -> Optional[str]:
    """Describe, but never trust, a conflicting provider in raw details."""
    raw = details.get("provider")
    if isinstance(raw, str) and raw and raw != provider:
        return f"details provider {raw!r} does not match step provider {provider!r}"
    return None


def _extract_suite_id(step: Step) -> Optional[str]:
    """Suite ID from step.suite_config if available."""
    config = step.suite_config
    if not isinstance(config, dict):
        return None
    raw = config.get("suite_id")
    return str(raw) if raw is not None else None


def _compute_duration(
    started_at: datetime, completed_at: Optional[datetime]
) -> Optional[float]:
    if completed_at is None:
        return None
    try:
        delta: timedelta = completed_at - started_at
        return round(delta.total_seconds(), 3)
    except (TypeError, OverflowError):
        return None


def _safe_str(value: Any) -> Optional[str]:
    """Return the value as a string, or None if falsy/non-string."""
    if value is None:
        return None
    s = str(value)
    return s if s else None


_INJI_PROVIDERS = {"injicertify", "injiverify"}


def _extract_inji_counts(
    provider: str, details: Dict[str, Any]
) -> Optional[InjiTestCounts]:
    """Return test counts only for Inji providers that produced a parsed report.

    Returns ``None`` for any other provider, and for Inji error paths where
    the report was not reached (those paths do not have the count keys).
    """
    if provider not in _INJI_PROVIDERS:
        return None

    # All four count keys must be present; if any is missing the report was
    # not parsed (e.g. error_type == "report_not_found" / "timeout" / etc.).
    required = ("tests_total", "tests_passed", "tests_failed", "tests_skipped")
    if not all(k in details for k in required):
        return None

    try:
        total = int(details["tests_total"])
        passed = int(details["tests_passed"])
        failed = int(details["tests_failed"])
        skipped = int(details["tests_skipped"])
    except (TypeError, ValueError):
        return None

    raw_summary = details.get("failure_summary")
    summary: List[str] = (
        [str(s) for s in raw_summary if isinstance(s, str)]
        if isinstance(raw_summary, list)
        else []
    )

    return InjiTestCounts(
        total=total,
        passed=passed,
        failed=failed,
        skipped=skipped,
        failure_summary=summary,
    )


def _extract_openid_modules(
    provider: str, details: Dict[str, Any]
) -> Optional[List[OpenIDModuleResult]]:
    """Return typed per-module results only for the ``openid`` provider.

    Returns ``None`` for any other provider, and for OpenID error paths
    where ``plan_id`` was never obtained (the ``modules`` key is absent).
    """
    if provider != "openid":
        return None

    raw_modules = details.get("modules")
    if not isinstance(raw_modules, list):
        return None

    results: List[OpenIDModuleResult] = []
    for entry in raw_modules:
        if not isinstance(entry, dict):
            continue
        module_id = _safe_str(entry.get("module_id")) or ""
        module_name = _safe_str(entry.get("module_name")) or ""
        external_state = _safe_str(entry.get("external_state"))
        result = _safe_str(entry.get("result")) or "UNKNOWN"
        results.append(
            OpenIDModuleResult(
                module_id=module_id,
                module_name=module_name,
                external_state=external_state,
                result=result,
            )
        )
    return results if results else None


def _synthesize_step(step_result: StepResult) -> Step:
    """Create a minimal ``Step`` from a ``StepResult`` when the plan is
    unavailable.  Used only as a fallback in ``normalize_execution_results``
    to avoid crashing if a result has no matching plan entry.
    """
    details = step_result.details or {}
    provider = _safe_str(details.get("provider")) or "unknown"
    return Step(
        step_id=step_result.step_id,
        display_name=step_result.step_id,
        provider=provider,
        component="unknown",
        order=0,
    )


# ---------------------------------------------------------------------------
# Resolve forward reference in Execution.normalized_results
#
# ``orchestration.Execution`` declares its ``normalized_results`` field
# using a forward-reference string (``"NormalizedStepResult"``) to avoid a
# circular import at module load time (orchestration ← result_normalizer is
# the import chain; the reverse would be circular).  Pydantic v2 requires
# ``model_rebuild()`` to be called once the referenced class is defined so
# that the model's JSON schema and validators become fully operational.
#
# This must run *after* ``NormalizedStepResult`` is defined above and after
# ``orchestration`` is imported.  Importing ``Execution`` here (rather than
# at the top of the file) is safe because orchestration.py does NOT import
# from result_normalizer at runtime — only inside ``if TYPE_CHECKING``.
# ---------------------------------------------------------------------------
from app.orchestration import Execution as _Execution  # noqa: E402 — intentional late import

_Execution.model_rebuild()
