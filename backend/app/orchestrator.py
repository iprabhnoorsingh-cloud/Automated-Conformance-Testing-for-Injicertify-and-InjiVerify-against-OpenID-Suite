"""Test Run Orchestrator.

Takes an existing CONFIGURED Test Run and executes its configured test
suites against its configured components as an ordered sequence of steps.
Each step is dispatched to a TestStepExecutor chosen by the step's
`provider` field via an ExecutorRegistry (see app/executors.py) — the
Orchestrator itself never branches on provider directly.

Execution is sequential and synchronous for this milestone — deterministic,
easy to debug, and a natural fit for the current local-only
MockTestStepExecutor and the (blocking-HTTP) OpenIDConformanceExecutor. The
domain model (Execution/Step/StepResult) does not assume synchronous
execution, so a future background/async execution model can replace how
`execute()` is invoked without changing what it produces.

A run's `status` field is only ever mutated here, via
TestRunRepository.update — the CRUD API (app/test_runs.py) never accepts a
client-supplied status.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import List

from app.components import ALLOWED_COMPONENTS
from app.execution_repository import ExecutionRepository
from app.executors import ExecutionContext, ExecutorRegistry, UnknownProviderError
from app.orchestration import Execution, ExecutionStatus, Step, StepResult
from app.repository import TestRunRepository
from app.schemas import TestRunConfig, TestRunStatus

logger = logging.getLogger(__name__)


class OrchestratorError(Exception):
    """Base class for expected, structured orchestration failures."""


class TestRunNotFoundError(OrchestratorError):
    def __init__(self, test_run_id: str):
        super().__init__(f"Test run not found: {test_run_id}")
        self.test_run_id = test_run_id


class EmptyExecutionPlanError(OrchestratorError):
    def __init__(self, test_run_id: str):
        super().__init__(f"No executable steps for test run: {test_run_id}")
        self.test_run_id = test_run_id


class ExecutionNotFoundError(OrchestratorError):
    def __init__(self, test_run_id: str):
        super().__init__(f"No execution found for test run: {test_run_id}")
        self.test_run_id = test_run_id


class Orchestrator:
    def __init__(
        self,
        test_run_repository: TestRunRepository,
        execution_repository: ExecutionRepository,
        executors: ExecutorRegistry,
    ):
        self._test_runs = test_run_repository
        self._executions = execution_repository
        self._executors = executors

    def execute(self, test_run_id: str) -> Execution:
        run = self._test_runs.get(test_run_id)
        if run is None:
            raise TestRunNotFoundError(test_run_id)

        steps = self._build_plan(run)
        if not steps:
            raise EmptyExecutionPlanError(test_run_id)

        execution = Execution(
            id=str(uuid.uuid4()),
            test_run_id=run.id,
            status=ExecutionStatus.QUEUED,
            started_at=datetime.now(timezone.utc),
            total_steps=len(steps),
            completed_steps=0,
            steps=steps,
            step_results=[],
        )
        self._executions.create(execution)

        run.status = TestRunStatus.QUEUED
        self._test_runs.update(run)

        execution.status = ExecutionStatus.RUNNING
        run.status = TestRunStatus.RUNNING
        self._executions.update(execution)
        self._test_runs.update(run)

        context = ExecutionContext(
            test_run_id=run.id,
            execution_id=execution.id,
            environment=run.environment.value,
        )

        overall_status = ExecutionStatus.PASSED
        for step in execution.steps:
            execution.current_step = step.step_id
            self._executions.update(execution)

            result = self._run_step_safely(step, context, test_run_id)

            step.status = result.status
            execution.step_results.append(result)
            execution.completed_steps += 1
            self._executions.update(execution)

            if result.status != ExecutionStatus.PASSED:
                overall_status = ExecutionStatus.FAILED
                break  # fail-fast: remaining steps stay QUEUED and unexecuted

        execution.current_step = None
        execution.status = overall_status
        execution.completed_at = datetime.now(timezone.utc)
        self._executions.update(execution)

        run.status = (
            TestRunStatus.PASSED
            if overall_status == ExecutionStatus.PASSED
            else TestRunStatus.FAILED
        )
        self._test_runs.update(run)

        return execution

    def get_latest_execution(self, test_run_id: str) -> Execution:
        run = self._test_runs.get(test_run_id)
        if run is None:
            raise TestRunNotFoundError(test_run_id)
        execution = self._executions.get_latest_for_run(test_run_id)
        if execution is None:
            raise ExecutionNotFoundError(test_run_id)
        return execution

    def _run_step_safely(
        self, step: Step, context: ExecutionContext, test_run_id: str
    ) -> StepResult:
        started_at = datetime.now(timezone.utc)
        try:
            executor = self._executors.resolve(step.provider)
        except UnknownProviderError as exc:
            return StepResult(
                step_id=step.step_id,
                status=ExecutionStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                message=str(exc),
                details={"error_type": "unknown_provider", "provider": step.provider},
            )

        try:
            return executor.execute(step, context)
        except Exception:
            logger.exception(
                "Unexpected error executing step %s for test run %s",
                step.step_id,
                test_run_id,
            )
            return StepResult(
                step_id=step.step_id,
                status=ExecutionStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                message="Step raised an unexpected error during execution.",
                details={"error_type": "internal_executor_error"},
            )

    @staticmethod
    def _build_plan(run: TestRunConfig) -> List[Step]:
        steps: List[Step] = []
        order = 0
        for component in run.components:
            component_label = ALLOWED_COMPONENTS.get(component, component)
            for suite in run.test_suites:
                steps.append(
                    Step(
                        step_id=f"{component}:{suite.provider}:{suite.suite_id}",
                        display_name=f"{suite.display_name} — {component_label}",
                        provider=suite.provider,
                        component=component,
                        order=order,
                        status=ExecutionStatus.QUEUED,
                        suite_config=suite.model_dump(),
                    )
                )
                order += 1
        return steps
