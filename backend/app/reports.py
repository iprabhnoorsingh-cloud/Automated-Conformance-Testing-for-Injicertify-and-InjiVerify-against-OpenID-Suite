"""Read-only M8 conformance report API."""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.dependencies import get_execution_repository, get_test_run_repository
from app.execution_repository import ExecutionRepository
from app.report_generator import ConformanceReport, build_conformance_report, render_markdown_report
from app.repository import TestRunRepository


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/test-runs", tags=["reports"])


@router.get("/{run_id}/report", response_model=ConformanceReport)
def get_report(
    run_id: str,
    format: Literal["json", "markdown"] = Query(default="json"),
    test_runs: TestRunRepository = Depends(get_test_run_repository),
    executions: ExecutionRepository = Depends(get_execution_repository),
):
    try:
        test_run = test_runs.get(run_id)
        if test_run is None:
            raise HTTPException(status_code=404, detail="Test run not found")
        execution = executions.get_latest_for_run(run_id)
        if execution is None:
            raise HTTPException(status_code=404, detail="No execution found for test run")
        if execution.benchmark_evaluation is None:
            raise HTTPException(
                status_code=409,
                detail="Execution has no benchmark evaluation; report cannot be generated.",
            )
        report = build_conformance_report(test_run, execution)
        if format == "markdown":
            return Response(
                content=render_markdown_report(report),
                media_type="text/markdown",
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="conformance-report-{execution.id}.md"'
                    )
                },
            )
        return report
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Could not generate conformance report for test run %s", run_id)
        raise HTTPException(status_code=500, detail="Could not generate conformance report") from exc
