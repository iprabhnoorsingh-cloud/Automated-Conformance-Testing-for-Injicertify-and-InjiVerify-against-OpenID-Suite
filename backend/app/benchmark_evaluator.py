"""Pure, provider-neutral benchmark evaluation for Milestone 7.

The evaluator deliberately consumes only execution plan metadata, raw result
identifiers, and NormalizedStepResult fields. It never reads provider-specific
payloads, performs I/O, or mutates its inputs.
"""

from typing import List, Optional, Union

from app.orchestration import (
    BenchmarkEvaluation,
    BenchmarkStatus,
    BenchmarkViolation,
    Execution,
    ExecutionStatus,
)
from app.schemas import BenchmarkConfig


_FINAL_STATUSES = {ExecutionStatus.PASSED, ExecutionStatus.FAILED}


def evaluate_benchmark(
    config: BenchmarkConfig, execution: Execution
) -> BenchmarkEvaluation:
    """Evaluate global M7 gates for one execution.

    Pass rate is based on planned steps, not completed results. Any failed
    normalized step is one critical failure under M7's deliberately simple
    global semantics. Invalid or incomplete evidence fails closed.
    """
    violations: List[BenchmarkViolation] = []
    total_planned_steps = len(execution.steps)
    raw_results = execution.step_results
    normalized_results = execution.normalized_results

    raw_ids = [result.step_id for result in raw_results]
    normalized_ids = [result.step_id for result in normalized_results]
    planned_ids = [step.step_id for step in execution.steps]

    if total_planned_steps == 0:
        _add_violation(
            violations,
            "incomplete_normalized_evidence",
            "Execution has no planned steps; benchmark evidence is incomplete.",
            expected="at least one planned step",
            actual=0,
        )

    if len(raw_results) != len(normalized_results):
        _add_violation(
            violations,
            "incomplete_normalized_evidence",
            "Raw and normalized result counts differ.",
            expected=len(raw_results),
            actual=len(normalized_results),
        )

    if (
        len(set(raw_ids)) != len(raw_ids)
        or len(set(normalized_ids)) != len(normalized_ids)
        or set(raw_ids) != set(normalized_ids)
        or any(step_id not in planned_ids for step_id in normalized_ids)
    ):
        _add_violation(
            violations,
            "result_mapping_invalid",
            "Normalized results do not uniquely map to raw planned results.",
            step_ids=sorted(set(raw_ids).symmetric_difference(normalized_ids)),
        )

    missing_planned_ids = sorted(set(planned_ids).difference(normalized_ids))
    if missing_planned_ids:
        _add_violation(
            violations,
            "incomplete_normalized_evidence",
            "One or more planned steps have no normalized result.",
            expected=total_planned_steps,
            actual=len(set(planned_ids).intersection(normalized_ids)),
            step_ids=missing_planned_ids,
        )

    normalization_failed_ids = sorted(
        result.step_id
        for result in normalized_results
        if result.normalization_error is not None
        or result.error_type == "normalization_failed"
    )
    if normalization_failed_ids:
        _add_violation(
            violations,
            "normalization_failed",
            "One or more normalized results were recorded as normalization failures.",
            step_ids=normalization_failed_ids,
        )

    non_final_ids = sorted(
        result.step_id
        for result in normalized_results
        if result.status not in _FINAL_STATUSES
    )
    if non_final_ids:
        _add_violation(
            violations,
            "non_final_result",
            "One or more normalized results have a non-final or invalid status.",
            step_ids=non_final_ids,
        )

    passed_steps = sum(
        result.status == ExecutionStatus.PASSED for result in normalized_results
    )
    failed_steps = sum(
        result.status == ExecutionStatus.FAILED for result in normalized_results
    )
    pass_rate = (
        round((passed_steps / total_planned_steps) * 100, 3)
        if total_planned_steps
        else 0.0
    )

    if pass_rate < config.minimum_pass_rate:
        _add_violation(
            violations,
            "minimum_pass_rate_not_met",
            "Pass rate is below the configured minimum.",
            expected=config.minimum_pass_rate,
            actual=pass_rate,
        )

    if failed_steps > config.critical_failures_allowed:
        _add_violation(
            violations,
            "critical_failures_exceeded",
            "Failed normalized steps exceed the allowed critical failures.",
            expected=config.critical_failures_allowed,
            actual=failed_steps,
            step_ids=sorted(
                result.step_id
                for result in normalized_results
                if result.status == ExecutionStatus.FAILED
            ),
        )

    evidence_complete = not any(
        violation.code
        in {
            "incomplete_normalized_evidence",
            "normalization_failed",
            "non_final_result",
            "result_mapping_invalid",
        }
        for violation in violations
    )
    status = BenchmarkStatus.PASSED if not violations else BenchmarkStatus.FAILED
    return BenchmarkEvaluation(
        status=status,
        evidence_complete=evidence_complete,
        total_planned_steps=total_planned_steps,
        normalized_result_count=len(normalized_results),
        passed_steps=passed_steps,
        failed_steps=failed_steps,
        pass_rate=pass_rate,
        minimum_pass_rate=config.minimum_pass_rate,
        critical_failures_allowed=config.critical_failures_allowed,
        violations=violations,
    )


def _add_violation(
    violations: List[BenchmarkViolation],
    code: str,
    message: str,
    expected: Optional[Union[str, int, float, bool]] = None,
    actual: Optional[Union[str, int, float, bool]] = None,
    step_ids: Optional[List[str]] = None,
) -> None:
    """Append at most one violation for each stable M7 code."""
    if any(violation.code == code for violation in violations):
        return
    violations.append(
        BenchmarkViolation(
            code=code,
            message=message,
            expected=expected,
            actual=actual,
            step_ids=step_ids or None,
        )
    )
