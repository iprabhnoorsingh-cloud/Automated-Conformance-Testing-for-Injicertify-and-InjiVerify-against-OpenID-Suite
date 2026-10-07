"""Execution domain models.

These represent an attempt to run a configured Test Run's test suites
against its configured components via the Orchestrator (see
app/orchestrator.py).

Milestone 6 added ``Execution.normalized_results``: each step result
passed through ``app.result_normalizer.normalize_step_result`` is
appended here so M7 (benchmark) and M8 (reporting) can consume a
provider-independent representation without re-parsing raw details.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Dict, List, Optional, Union

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    # Imported only for type-checking; at runtime result_normalizer imports
    # from this module (orchestration), so we must not create a circular
    # runtime import.  Pydantic resolves the forward reference lazily.
    from app.result_normalizer import NormalizedStepResult


class ExecutionStatus(str, Enum):
    """Lifecycle states shared by an Execution and its individual Steps."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class BenchmarkStatus(str, Enum):
    """Final verdict of the M7 benchmark gate, separate from execution state."""

    PASSED = "PASSED"
    FAILED = "FAILED"


class BenchmarkViolation(BaseModel):
    """One stable, machine-readable reason a benchmark gate did not pass."""

    code: str
    message: str
    expected: Optional[Union[str, int, float, bool]] = None
    actual: Optional[Union[str, int, float, bool]] = None
    step_ids: Optional[List[str]] = None


class BenchmarkEvaluation(BaseModel):
    """Persisted, provider-neutral M7 gate evidence for one Execution."""

    status: BenchmarkStatus
    evidence_complete: bool
    total_planned_steps: int
    normalized_result_count: int
    passed_steps: int
    failed_steps: int
    pass_rate: float
    minimum_pass_rate: float
    critical_failures_allowed: int
    violations: List[BenchmarkViolation] = Field(default_factory=list)


class Step(BaseModel):
    """One planned step in an execution plan: one configured test suite run
    against one configured component. `status` reflects this step's current
    state within one specific execution.

    `suite_config` carries the originating TestSuiteConfig (as a dict) so a
    provider-specific executor (e.g. OpenIDConformanceExecutor) can read its
    own configuration (plan name, plan configuration JSON, etc.) without
    Step itself needing provider-specific typed fields.
    """

    step_id: str
    display_name: str
    provider: str
    component: str
    order: int
    status: ExecutionStatus = ExecutionStatus.QUEUED
    suite_config: Optional[Dict] = None


class StepResult(BaseModel):
    """The recorded outcome of actually running one Step."""

    step_id: str
    status: ExecutionStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    message: str
    details: Optional[Dict] = None


class Execution(BaseModel):
    """A single attempt to execute a Test Run's configured test suites."""

    id: str
    test_run_id: str
    status: ExecutionStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    current_step: Optional[str] = None
    total_steps: int
    completed_steps: int = 0
    steps: List[Step]
    step_results: List[StepResult] = Field(default_factory=list)
    normalized_results: List["NormalizedStepResult"] = Field(
        default_factory=list,
        description=(
            "M6: provider-independent normalized form of each StepResult, "
            "produced by app.result_normalizer.normalize_step_result. "
            "Empty until the orchestrator populates it after each step."
        ),
    )
    benchmark_evaluation: Optional[BenchmarkEvaluation] = Field(
        default=None,
        description=(
            "M7: provider-neutral benchmark verdict calculated from the "
            "execution plan and normalized results after execution completes."
        ),
    )
