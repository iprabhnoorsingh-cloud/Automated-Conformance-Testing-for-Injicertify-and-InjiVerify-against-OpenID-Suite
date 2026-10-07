"""Unit tests for the pure, provider-neutral M7 benchmark evaluator."""

from datetime import datetime, timezone

import pytest

from app.benchmark_evaluator import evaluate_benchmark
from app.orchestration import Execution, ExecutionStatus, Step, StepResult
from app.result_normalizer import NormalizedStepResult
from app.schemas import BenchmarkConfig


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _step(index: int, provider: str = "mock") -> Step:
    return Step(
        step_id=f"inji-certify:{provider}:suite-{index}",
        display_name=f"Suite {index}",
        provider=provider,
        component="inji-certify",
        order=index,
        suite_config={"suite_id": f"suite-{index}"},
    )


def _normalized(step: Step, status: ExecutionStatus = ExecutionStatus.PASSED, **kwargs):
    raw = StepResult(
        step_id=step.step_id,
        status=status,
        started_at=NOW,
        completed_at=NOW,
        message="raw",
    )
    return NormalizedStepResult(
        step_id=step.step_id,
        display_name=step.display_name,
        provider=step.provider,
        component=step.component,
        suite_id=f"suite-{step.order}",
        status=status,
        started_at=NOW,
        completed_at=NOW,
        duration_seconds=0,
        message="normalized",
        raw_result=raw,
        **kwargs,
    )


def _execution(statuses, providers=None) -> Execution:
    providers = providers or ["mock"] * len(statuses)
    steps = [_step(i, providers[i]) for i in range(len(statuses))]
    normalized = [_normalized(step, status) for step, status in zip(steps, statuses)]
    return Execution(
        id="execution-1",
        test_run_id="run-1",
        status=ExecutionStatus.PASSED,
        started_at=NOW,
        completed_at=NOW,
        total_steps=len(steps),
        completed_steps=len(steps),
        steps=steps,
        step_results=[result.raw_result for result in normalized],
        normalized_results=normalized,
    )


def _config(minimum_pass_rate=100, critical_failures_allowed=0):
    return BenchmarkConfig(
        minimum_pass_rate=minimum_pass_rate,
        critical_failures_allowed=critical_failures_allowed,
    )


def _codes(evaluation):
    return {violation.code for violation in evaluation.violations}


def test_all_passed_passes_gate():
    evaluation = evaluate_benchmark(_config(), _execution([ExecutionStatus.PASSED] * 3))

    assert evaluation.status.value == "PASSED"
    assert evaluation.evidence_complete is True
    assert evaluation.pass_rate == 100
    assert evaluation.violations == []


@pytest.mark.parametrize("allowed", [1, 2])
def test_failed_steps_within_or_at_threshold_pass_when_rate_allows(allowed):
    evaluation = evaluate_benchmark(
        _config(minimum_pass_rate=50, critical_failures_allowed=allowed),
        _execution([ExecutionStatus.PASSED, ExecutionStatus.FAILED]),
    )

    assert evaluation.status.value == "PASSED"
    assert evaluation.failed_steps == 1


def test_failed_steps_above_threshold_fail():
    evaluation = evaluate_benchmark(
        _config(minimum_pass_rate=0, critical_failures_allowed=0),
        _execution([ExecutionStatus.FAILED]),
    )

    assert evaluation.status.value == "FAILED"
    assert "critical_failures_exceeded" in _codes(evaluation)


@pytest.mark.parametrize(
    ("minimum", "expected_status"),
    [(50, "PASSED"), (50.1, "FAILED"), (40, "PASSED"), (0, "PASSED"), (100, "FAILED")],
)
def test_pass_rate_threshold_boundaries(minimum, expected_status):
    evaluation = evaluate_benchmark(
        _config(minimum_pass_rate=minimum, critical_failures_allowed=1),
        _execution([ExecutionStatus.PASSED, ExecutionStatus.FAILED]),
    )

    assert evaluation.pass_rate == 50
    assert evaluation.status.value == expected_status
    assert ("minimum_pass_rate_not_met" in _codes(evaluation)) == (expected_status == "FAILED")


def test_zero_planned_steps_fails_closed_deterministically():
    execution = _execution([])

    evaluation = evaluate_benchmark(_config(minimum_pass_rate=0), execution)

    assert evaluation.status.value == "FAILED"
    assert evaluation.evidence_complete is False
    assert evaluation.pass_rate == 0
    assert "incomplete_normalized_evidence" in _codes(evaluation)


def test_fail_fast_uses_planned_steps_as_denominator():
    execution = _execution([ExecutionStatus.PASSED] * 2 + [ExecutionStatus.PASSED] * 3)
    execution.step_results = execution.step_results[:2]
    execution.normalized_results = execution.normalized_results[:2]
    execution.completed_steps = 2

    evaluation = evaluate_benchmark(_config(minimum_pass_rate=50), execution)

    assert evaluation.pass_rate == 40
    assert evaluation.status.value == "FAILED"
    assert evaluation.evidence_complete is False
    assert "incomplete_normalized_evidence" in _codes(evaluation)


def test_missing_normalized_result_fails_closed():
    execution = _execution([ExecutionStatus.PASSED, ExecutionStatus.PASSED])
    execution.normalized_results.pop()

    evaluation = evaluate_benchmark(_config(minimum_pass_rate=0), execution)

    assert evaluation.evidence_complete is False
    assert "incomplete_normalized_evidence" in _codes(evaluation)


def test_duplicate_or_mismatched_mapping_fails_closed():
    execution = _execution([ExecutionStatus.PASSED, ExecutionStatus.PASSED])
    execution.normalized_results[1].step_id = execution.normalized_results[0].step_id

    evaluation = evaluate_benchmark(_config(minimum_pass_rate=0), execution)

    assert evaluation.evidence_complete is False
    assert "result_mapping_invalid" in _codes(evaluation)


def test_normalization_failure_fails_closed():
    execution = _execution([ExecutionStatus.FAILED])
    execution.normalized_results[0].error_type = "normalization_failed"
    execution.normalized_results[0].normalization_error = "RuntimeError"

    evaluation = evaluate_benchmark(_config(minimum_pass_rate=0, critical_failures_allowed=1), execution)

    assert evaluation.evidence_complete is False
    assert "normalization_failed" in _codes(evaluation)


@pytest.mark.parametrize("status", [ExecutionStatus.QUEUED, ExecutionStatus.RUNNING, ExecutionStatus.CANCELLED])
def test_non_final_status_fails_closed(status):
    execution = _execution([ExecutionStatus.PASSED])
    execution.normalized_results[0].status = status

    evaluation = evaluate_benchmark(_config(minimum_pass_rate=0), execution)

    assert evaluation.evidence_complete is False
    assert "non_final_result" in _codes(evaluation)


def test_unknown_status_fails_closed():
    execution = _execution([ExecutionStatus.PASSED])
    execution.normalized_results[0].status = "UNKNOWN"

    evaluation = evaluate_benchmark(_config(minimum_pass_rate=0), execution)

    assert evaluation.evidence_complete is False
    assert "non_final_result" in _codes(evaluation)


@pytest.mark.parametrize("provider", ["mock", "openid", "injicertify", "injiverify"])
def test_evaluation_is_provider_neutral(provider):
    evaluation = evaluate_benchmark(
        _config(), _execution([ExecutionStatus.PASSED], providers=[provider])
    )

    assert evaluation.status.value == "PASSED"
    assert evaluation.passed_steps == 1
