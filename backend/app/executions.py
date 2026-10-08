"""Test run execution API.

These endpoints trigger and observe execution of an already-configured Test
Run via the Orchestrator. They never create or directly mutate test run
configuration — only the Orchestrator (via TestRunRepository.update) is
allowed to change a run's status.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.concurrency import ExecutionCapacityError
from app.dependencies import get_orchestrator
from app.orchestration import Execution
from app.orchestrator import (
    EmptyExecutionPlanError,
    ExecutionNotFoundError,
    Orchestrator,
    TestRunNotFoundError,
)
from app.redaction import redact_model

router = APIRouter(prefix="/api/test-runs", tags=["executions"])


@router.post(
    "/{run_id}/execute", response_model=Execution, status_code=status.HTTP_201_CREATED
)
def execute_test_run(
    run_id: str,
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> Execution:
    try:
        return redact_model(orchestrator.execute(run_id))
    except TestRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EmptyExecutionPlanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ExecutionCapacityError as exc:
        # M10: bounded concurrency — nothing was started.
        raise HTTPException(
            status_code=429,
            detail="Execution capacity exhausted; retry later.",
            headers={"Retry-After": "30"},
        ) from exc


@router.get("/{run_id}/execution", response_model=Execution)
def get_latest_execution(
    run_id: str,
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> Execution:
    try:
        return redact_model(orchestrator.get_latest_execution(run_id))
    except TestRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ExecutionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
