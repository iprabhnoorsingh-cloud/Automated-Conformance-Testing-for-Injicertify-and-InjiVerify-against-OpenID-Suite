"""Test-step executor abstraction.

TestStepExecutor is the seam later milestones use to plug in real OpenID
Foundation and MOSIP/Inji test-rig integrations (M4/M5). This milestone only
ships MockTestStepExecutor: a deterministic, local, network-free
implementation used to exercise the orchestration engine end-to-end.
"""

from datetime import datetime, timezone
from typing import Protocol

from pydantic import BaseModel

from app.orchestration import ExecutionStatus, Step, StepResult


class ExecutionContext(BaseModel):
    """Everything a step executor needs to run one step.

    Deliberately minimal for this milestone — real providers will need
    richer context (environment endpoints, credential references, etc.)
    once they're integrated.
    """

    test_run_id: str
    execution_id: str
    environment: str


class TestStepExecutor(Protocol):
    def execute(self, step: Step, context: ExecutionContext) -> StepResult: ...


class MockTestStepExecutor:
    """Deterministic local executor — never calls the network and never
    requires a real OpenID/MOSIP system.

    Determinism rule (so tests and the demo UI can hit both paths on
    demand): a step whose `step_id` or `display_name` contains the
    substring "fail" (case-insensitive) is reported FAILED; every other
    step is reported PASSED. This is a test/demo convenience, not a real
    conformance signal.
    """

    FAIL_MARKER = "fail"

    def execute(self, step: Step, context: ExecutionContext) -> StepResult:
        started_at = datetime.now(timezone.utc)
        should_fail = (
            self.FAIL_MARKER in step.step_id.lower()
            or self.FAIL_MARKER in step.display_name.lower()
        )
        completed_at = datetime.now(timezone.utc)

        if should_fail:
            return StepResult(
                step_id=step.step_id,
                status=ExecutionStatus.FAILED,
                started_at=started_at,
                completed_at=completed_at,
                message=(
                    f"Mock executor: step '{step.display_name}' deterministically "
                    "failed (step id/display name contains 'fail')."
                ),
            )
        return StepResult(
            step_id=step.step_id,
            status=ExecutionStatus.PASSED,
            started_at=started_at,
            completed_at=completed_at,
            message=f"Mock executor: step '{step.display_name}' completed successfully.",
        )
