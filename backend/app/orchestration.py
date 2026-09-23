"""Execution domain models.

These represent an attempt to run a configured Test Run's test suites
against its configured components via the Orchestrator (see
app/orchestrator.py). Nothing here talks to a real OpenID Foundation or
MOSIP/Inji test-rig yet — see app/executors.py for the deterministic mock
executor used in this milestone.
"""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ExecutionStatus(str, Enum):
    """Lifecycle states shared by an Execution and its individual Steps."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Step(BaseModel):
    """One planned step in an execution plan: one configured test suite run
    against one configured component. `status` reflects this step's current
    state within one specific execution.
    """

    step_id: str
    display_name: str
    provider: str
    component: str
    order: int
    status: ExecutionStatus = ExecutionStatus.QUEUED


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
