"""Test Run Configuration API.

These endpoints only create, read, and delete configuration. Nothing here
starts or simulates a test execution — POST /api/test-runs stores a
TestRunConfig with status CONFIGURED and nothing more.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_test_run_repository
from app.repository import TestRunRepository
from app.schemas import (
    TestRunConfig,
    TestRunCreateRequest,
    TestRunResponse,
    TestRunStatus,
)

router = APIRouter(prefix="/api/test-runs", tags=["test-runs"])


@router.post("", response_model=TestRunResponse, status_code=status.HTTP_201_CREATED)
def create_test_run(
    payload: TestRunCreateRequest,
    repo: TestRunRepository = Depends(get_test_run_repository),
) -> TestRunConfig:
    run = TestRunConfig(
        id=str(uuid.uuid4()),
        status=TestRunStatus.CONFIGURED,
        created_at=datetime.now(timezone.utc),
        **payload.model_dump(),
    )
    return repo.create(run)


@router.get("", response_model=list[TestRunResponse])
def list_test_runs(
    repo: TestRunRepository = Depends(get_test_run_repository),
) -> list[TestRunConfig]:
    return repo.list_all()


@router.get("/{run_id}", response_model=TestRunResponse)
def get_test_run(
    run_id: str,
    repo: TestRunRepository = Depends(get_test_run_repository),
) -> TestRunConfig:
    run = repo.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Test run not found")
    return run


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_test_run(
    run_id: str,
    repo: TestRunRepository = Depends(get_test_run_repository),
) -> None:
    deleted = repo.delete(run_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Test run not found")
