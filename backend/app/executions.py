"""Test run execution API.

These endpoints trigger and observe execution of an already-configured Test
Run via the Orchestrator. They never create or directly mutate test run
configuration — only the Orchestrator (via TestRunRepository.update) is
allowed to change a run's status.
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status

from app.concurrency import ExecutionCapacityError
from app.dependencies import get_orchestrator, get_execution_repository, get_test_run_repository
from app.execution_repository import ExecutionRepository
from app.repository import TestRunRepository
from app.orchestration import Execution
from app.orchestrator import (
    EmptyExecutionPlanError,
    ExecutionNotFoundError,
    Orchestrator,
    TestRunNotFoundError,
)
from app.redaction import redact_model
from app.async_runner import async_runner

router = APIRouter(tags=["executions"])


@router.post(
    "/api/test-runs/{run_id}/execute", response_model=Execution, status_code=status.HTTP_201_CREATED
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


@router.post(
    "/api/test-runs/{run_id}/execute-async", response_model=Execution, status_code=status.HTTP_202_ACCEPTED
)
def execute_test_run_async(
    run_id: str,
    orchestrator: Orchestrator = Depends(get_orchestrator),
) -> Execution:
    if not async_runner.try_reserve():
        raise HTTPException(
            status_code=429,
            detail="Async execution queue is full; retry later.",
            headers={"Retry-After": "30"},
        )

    try:
        # Plan the execution synchronously (persists as QUEUED)
        execution = orchestrator.plan_execution(run_id)

        # Enqueue the job. We already reserved capacity.
        if not async_runner.enqueue(execution.id):
            # Should only happen if shutdown/uninitialized
            raise HTTPException(
                status_code=503,
                detail="Async execution system unavailable.",
            )

        return redact_model(execution)
    except TestRunNotFoundError as exc:
        async_runner.release_reservation()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EmptyExecutionPlanError as exc:
        async_runner.release_reservation()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        async_runner.release_reservation()
        raise


@router.get("/api/test-runs/{run_id}/execution", response_model=Execution)
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


@router.get("/api/executions/{execution_id}", response_model=Execution)
def get_execution_by_id(
    execution_id: str,
    executions: ExecutionRepository = Depends(get_execution_repository),
) -> Execution:
    execution = executions.get(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    return redact_model(execution)


@router.get("/api/test-runs/{run_id}/executions", response_model=List[Execution])
def list_executions_for_run(
    run_id: str,
    executions: ExecutionRepository = Depends(get_execution_repository),
    test_runs: TestRunRepository = Depends(get_test_run_repository),
) -> List[Execution]:
    # At current project scale, scanning the existing JSON repository is acceptable.
    # Order by started_at descending (newest first). Use execution id for deterministic secondary sort.
    # Check if run exists?
    if not test_runs.get(run_id):
        raise HTTPException(status_code=404, detail="Test run not found")

    data = executions._read_all()
    results = [
        Execution.model_validate(v)
        for v in data.values()
        if v.get("test_run_id") == run_id
    ]
    # newest first
    results.sort(key=lambda x: (x.started_at, x.id), reverse=True)
    return [redact_model(r) for r in results]
