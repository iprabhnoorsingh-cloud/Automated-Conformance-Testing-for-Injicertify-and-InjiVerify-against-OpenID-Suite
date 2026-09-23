from datetime import datetime, timezone

import pytest

from app.json_execution_repository import JsonFileExecutionRepository
from app.json_repository import JsonFileTestRunRepository
from app.executors import ExecutorRegistry, MockTestStepExecutor
from app.orchestration import ExecutionStatus
from app.orchestrator import (
    EmptyExecutionPlanError,
    ExecutionNotFoundError,
    Orchestrator,
    TestRunNotFoundError,
)
from app.schemas import (
    BenchmarkConfig,
    Environment,
    TestRunConfig,
    TestRunStatus,
    TestSuiteConfig,
)


def _make_run(test_runs_repo, test_suites=None, components=None, run_id="run-1"):
    run = TestRunConfig(
        id=run_id,
        run_name="Orchestrator test run",
        environment=Environment.STAGING,
        components=components if components is not None else ["inji-certify"],
        test_suites=test_suites
        if test_suites is not None
        else [
            TestSuiteConfig(
                provider="openid",
                suite_id="suite-a",
                display_name="Suite A",
            )
        ],
        benchmark=BenchmarkConfig(minimum_pass_rate=95, critical_failures_allowed=0),
        metadata=None,
        status=TestRunStatus.CONFIGURED,
        created_at=datetime.now(timezone.utc),
    )
    return test_runs_repo.create(run)


class BrokenTestStepExecutor:
    """Test-only executor that always raises, to exercise the orchestrator's
    unexpected-exception handling path."""

    def execute(self, step, context):
        raise RuntimeError("boom")


@pytest.fixture
def orchestrator_parts(tmp_path):
    test_runs_repo = JsonFileTestRunRepository(tmp_path / "test_runs.json")
    executions_repo = JsonFileExecutionRepository(tmp_path / "executions.json")
    # These tests exercise the Orchestrator's own sequencing/persistence
    # logic, not any specific provider integration, so both provider
    # strings used by fixtures below ("openid", "mosip") are routed to the
    # same deterministic mock executor.
    mock_executor = MockTestStepExecutor()
    executors = ExecutorRegistry({"openid": mock_executor, "mosip": mock_executor})
    orchestrator = Orchestrator(test_runs_repo, executions_repo, executors)
    return test_runs_repo, executions_repo, orchestrator


def test_valid_run_executes_successfully(orchestrator_parts):
    test_runs_repo, _, orchestrator = orchestrator_parts
    run = _make_run(test_runs_repo)

    execution = orchestrator.execute(run.id)

    assert execution.status == ExecutionStatus.PASSED
    assert execution.total_steps == 1
    assert execution.completed_steps == 1


def test_execution_produces_ordered_steps(orchestrator_parts):
    test_runs_repo, _, orchestrator = orchestrator_parts
    suites = [
        TestSuiteConfig(provider="openid", suite_id="a", display_name="A"),
        TestSuiteConfig(provider="openid", suite_id="b", display_name="B"),
        TestSuiteConfig(provider="mosip", suite_id="c", display_name="C"),
    ]
    run = _make_run(test_runs_repo, test_suites=suites)

    execution = orchestrator.execute(run.id)

    assert [s.order for s in execution.steps] == [0, 1, 2]
    assert [s.provider for s in execution.steps] == ["openid", "openid", "mosip"]


def test_plan_covers_component_by_suite_combinations(orchestrator_parts):
    test_runs_repo, _, orchestrator = orchestrator_parts
    suites = [
        TestSuiteConfig(provider="openid", suite_id="a", display_name="A"),
    ]
    run = _make_run(
        test_runs_repo,
        test_suites=suites,
        components=["inji-certify", "inji-verify"],
    )

    execution = orchestrator.execute(run.id)

    assert execution.total_steps == 2
    assert {s.component for s in execution.steps} == {"inji-certify", "inji-verify"}


def test_step_results_are_persisted_and_retrievable(orchestrator_parts):
    test_runs_repo, executions_repo, orchestrator = orchestrator_parts
    run = _make_run(test_runs_repo)

    execution = orchestrator.execute(run.id)

    stored = executions_repo.get(execution.id)
    assert stored is not None
    assert len(stored.step_results) == 1
    assert stored.step_results[0].step_id == execution.steps[0].step_id


def test_failed_step_fails_execution_and_run(orchestrator_parts):
    test_runs_repo, _, orchestrator = orchestrator_parts
    suites = [
        TestSuiteConfig(provider="openid", suite_id="will-fail", display_name="Will Fail"),
    ]
    run = _make_run(test_runs_repo, test_suites=suites)

    execution = orchestrator.execute(run.id)

    assert execution.status == ExecutionStatus.FAILED
    assert execution.step_results[0].status == ExecutionStatus.FAILED

    updated_run = test_runs_repo.get(run.id)
    assert updated_run.status == TestRunStatus.FAILED


def test_failure_stops_remaining_steps(orchestrator_parts):
    test_runs_repo, _, orchestrator = orchestrator_parts
    suites = [
        TestSuiteConfig(provider="openid", suite_id="will-fail", display_name="Will Fail"),
        TestSuiteConfig(provider="openid", suite_id="never-runs", display_name="Never Runs"),
    ]
    run = _make_run(test_runs_repo, test_suites=suites)

    execution = orchestrator.execute(run.id)

    assert execution.completed_steps == 1
    assert len(execution.step_results) == 1
    assert execution.steps[1].status == ExecutionStatus.QUEUED


def test_unexpected_executor_exception_is_handled(tmp_path):
    test_runs_repo = JsonFileTestRunRepository(tmp_path / "test_runs.json")
    executions_repo = JsonFileExecutionRepository(tmp_path / "executions.json")
    executors = ExecutorRegistry({"openid": BrokenTestStepExecutor()})
    orchestrator = Orchestrator(test_runs_repo, executions_repo, executors)
    run = _make_run(test_runs_repo)

    execution = orchestrator.execute(run.id)

    assert execution.status == ExecutionStatus.FAILED
    assert execution.step_results[0].status == ExecutionStatus.FAILED
    assert "unexpected error" in execution.step_results[0].message.lower()
    # The raw exception text must never leak to the recorded result.
    assert "boom" not in execution.step_results[0].message


def test_nonexistent_test_run_raises(orchestrator_parts):
    _, _, orchestrator = orchestrator_parts
    with pytest.raises(TestRunNotFoundError):
        orchestrator.execute("does-not-exist")


class _InMemoryTestRunRepository:
    """Minimal in-memory stub used only to hand the orchestrator a
    TestRunConfig built via model_construct(), bypassing both Pydantic
    validation and the JSON repository's own re-validation on read (which
    would otherwise reject an empty test_suites list before the
    orchestrator's own guard is ever reached)."""

    def __init__(self):
        self._runs = {}

    def create(self, run):
        self._runs[run.id] = run
        return run

    def update(self, run):
        self._runs[run.id] = run
        return run

    def list_all(self):
        return list(self._runs.values())

    def get(self, run_id):
        return self._runs.get(run_id)

    def delete(self, run_id):
        return self._runs.pop(run_id, None) is not None


def test_empty_execution_plan_is_rejected(tmp_path):
    # TestRunBase normally forbids an empty test_suites list at construction
    # time, and the JSON repository re-validates on every read, so an empty
    # plan cannot reach the orchestrator through the real persistence path.
    # This test simulates a corrupted/legacy record via an in-memory stub
    # repository to confirm the orchestrator's own guard still refuses to
    # build and run an empty plan, as defense in depth.
    test_runs_repo = _InMemoryTestRunRepository()
    executions_repo = JsonFileExecutionRepository(tmp_path / "executions.json")
    executors = ExecutorRegistry({"openid": MockTestStepExecutor()})
    orchestrator = Orchestrator(test_runs_repo, executions_repo, executors)

    bad_run = TestRunConfig.model_construct(
        id="bad-run",
        run_name="Corrupted",
        environment=Environment.STAGING,
        components=["inji-certify"],
        test_suites=[],
        benchmark=BenchmarkConfig(minimum_pass_rate=95, critical_failures_allowed=0),
        metadata=None,
        status=TestRunStatus.CONFIGURED,
        created_at=datetime.now(timezone.utc),
    )
    test_runs_repo.create(bad_run)

    with pytest.raises(EmptyExecutionPlanError):
        orchestrator.execute("bad-run")


def test_get_latest_execution_returns_most_recent(orchestrator_parts):
    test_runs_repo, _, orchestrator = orchestrator_parts
    run = _make_run(test_runs_repo)

    first = orchestrator.execute(run.id)
    second = orchestrator.execute(run.id)

    latest = orchestrator.get_latest_execution(run.id)
    assert latest.id == second.id
    assert latest.id != first.id


def test_get_latest_execution_without_prior_execution_raises(orchestrator_parts):
    test_runs_repo, _, orchestrator = orchestrator_parts
    run = _make_run(test_runs_repo)

    with pytest.raises(ExecutionNotFoundError):
        orchestrator.get_latest_execution(run.id)


def test_get_latest_execution_for_nonexistent_run_raises(orchestrator_parts):
    _, _, orchestrator = orchestrator_parts
    with pytest.raises(TestRunNotFoundError):
        orchestrator.get_latest_execution("does-not-exist")


def test_unregistered_provider_fails_step_without_crashing(tmp_path):
    test_runs_repo = JsonFileTestRunRepository(tmp_path / "test_runs.json")
    executions_repo = JsonFileExecutionRepository(tmp_path / "executions.json")
    # No "unregistered-provider" entry registered.
    executors = ExecutorRegistry({"openid": MockTestStepExecutor()})
    orchestrator = Orchestrator(test_runs_repo, executions_repo, executors)

    suites = [
        TestSuiteConfig(
            provider="unregistered-provider", suite_id="a", display_name="A"
        )
    ]
    run = _make_run(test_runs_repo, test_suites=suites)

    execution = orchestrator.execute(run.id)

    assert execution.status == ExecutionStatus.FAILED
    assert execution.step_results[0].details["error_type"] == "unknown_provider"
