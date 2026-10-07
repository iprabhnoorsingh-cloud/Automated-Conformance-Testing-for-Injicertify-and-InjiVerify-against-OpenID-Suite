from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.dependencies import (
    get_execution_repository,
    get_orchestrator,
    get_test_run_repository,
)
from app.execution_repository import ExecutionRepository
from app.executors import ExecutorRegistry, MockTestStepExecutor
from app.json_execution_repository import JsonFileExecutionRepository
from app.json_repository import JsonFileTestRunRepository
from app.main import app
from app.orchestration import BenchmarkEvaluation, BenchmarkStatus, Execution, ExecutionStatus
from app.orchestrator import Orchestrator


PAYLOAD = {
    "run_name": "M8 API report run",
    "environment": "staging",
    "components": ["inji-certify"],
    "test_suites": [{"provider": "mock", "suite_id": "suite", "display_name": "Suite"}],
    "benchmark": {"minimum_pass_rate": 95, "critical_failures_allowed": 0},
}


@pytest.fixture
def report_client(tmp_path):
    test_runs = JsonFileTestRunRepository(tmp_path / "test_runs.json")
    executions = JsonFileExecutionRepository(tmp_path / "executions.json")
    registry = ExecutorRegistry({"mock": MockTestStepExecutor()})
    app.dependency_overrides[get_test_run_repository] = lambda: test_runs
    app.dependency_overrides[get_execution_repository] = lambda: executions
    app.dependency_overrides[get_orchestrator] = lambda: Orchestrator(
        test_runs, executions, registry
    )
    with TestClient(app) as client:
        yield client, test_runs, executions
    app.dependency_overrides.clear()


def _create_run(client):
    response = client.post("/api/test-runs", json=PAYLOAD)
    assert response.status_code == 201
    return response.json()


def test_report_json_default_explicit_and_markdown(report_client):
    client, _, _ = report_client
    run = _create_run(client)
    client.post(f"/api/test-runs/{run['id']}/execute")

    default = client.get(f"/api/test-runs/{run['id']}/report")
    explicit = client.get(f"/api/test-runs/{run['id']}/report?format=json")
    markdown = client.get(f"/api/test-runs/{run['id']}/report?format=markdown")

    assert default.status_code == explicit.status_code == 200
    assert default.json() == explicit.json()
    assert default.json()["benchmark"]["status"] == "PASSED"
    assert markdown.status_code == 200
    assert markdown.headers["content-type"].startswith("text/markdown")
    assert "attachment; filename=\"conformance-report-" in markdown.headers["content-disposition"]
    assert markdown.text.startswith("# Conformance Report\n")


def test_report_missing_run_and_execution(report_client):
    client, _, _ = report_client
    assert client.get("/api/test-runs/missing/report").status_code == 404
    run = _create_run(client)
    assert client.get(f"/api/test-runs/{run['id']}/report").status_code == 404


def test_report_missing_benchmark_evaluation_is_conflict(report_client):
    client, _, executions = report_client
    run = _create_run(client)
    executions.create(
        Execution(
            id="legacy-execution",
            test_run_id=run["id"],
            status=ExecutionStatus.PASSED,
            started_at=datetime.now(timezone.utc),
            total_steps=0,
            steps=[],
        )
    )

    assert client.get(f"/api/test-runs/{run['id']}/report").status_code == 409


def test_report_rejects_unsupported_format(report_client):
    client, _, _ = report_client
    run = _create_run(client)
    assert client.get(f"/api/test-runs/{run['id']}/report?format=pdf").status_code == 422


def test_failed_and_incomplete_benchmark_reports_still_generate(report_client):
    client, _, executions = report_client
    run = _create_run(client)
    executions.create(
        Execution(
            id="incomplete-execution",
            test_run_id=run["id"],
            status=ExecutionStatus.FAILED,
            started_at=datetime.now(timezone.utc),
            total_steps=2,
            steps=[],
            benchmark_evaluation=BenchmarkEvaluation(
                status=BenchmarkStatus.FAILED,
                evidence_complete=False,
                total_planned_steps=2,
                normalized_result_count=0,
                passed_steps=0,
                failed_steps=0,
                pass_rate=0,
                minimum_pass_rate=95,
                critical_failures_allowed=0,
            ),
        )
    )

    response = client.get(f"/api/test-runs/{run['id']}/report")

    assert response.status_code == 200
    assert response.json()["benchmark"]["status"] == "FAILED"
    assert response.json()["benchmark"]["evidence_complete"] is False


def _file_bytes(tmp_path):
    return {p.name: p.read_bytes() for p in sorted(tmp_path.iterdir())}


def test_report_json_and_markdown_are_byte_deterministic(report_client):
    client, _, _ = report_client
    run = _create_run(client)
    client.post(f"/api/test-runs/{run['id']}/execute")
    url = f"/api/test-runs/{run['id']}/report"

    assert client.get(url + "?format=json").content == client.get(url + "?format=json").content
    first = client.get(url + "?format=markdown")
    assert first.content == client.get(url + "?format=markdown").content
    assert first.text.endswith("\n")


def test_report_matches_persisted_m7_evaluation(report_client):
    client, _, executions = report_client
    run = _create_run(client)
    execution = client.post(f"/api/test-runs/{run['id']}/execute").json()
    persisted = executions.get(execution["id"]).benchmark_evaluation

    body = client.get(f"/api/test-runs/{run['id']}/report").json()
    markdown = client.get(f"/api/test-runs/{run['id']}/report?format=markdown").text

    assert body["benchmark"] == persisted.model_dump(mode="json")
    assert body["summary"]["benchmark_status"] == persisted.status.value
    assert body["summary"]["pass_rate"] == persisted.pass_rate
    assert f"Benchmark status: `{persisted.status.value}`" in markdown


def test_report_is_read_only_and_not_persisted(report_client, tmp_path):
    client, test_runs, executions = report_client
    run = _create_run(client)
    client.post(f"/api/test-runs/{run['id']}/execute")
    run_before = test_runs.get(run["id"]).model_dump_json()
    exec_before = executions.get_latest_for_run(run["id"]).model_dump_json()
    files_before = _file_bytes(tmp_path)

    for fmt in ("json", "markdown", "json"):
        assert client.get(f"/api/test-runs/{run['id']}/report?format={fmt}").status_code == 200

    assert test_runs.get(run["id"]).model_dump_json() == run_before
    assert executions.get_latest_for_run(run["id"]).model_dump_json() == exec_before
    assert _file_bytes(tmp_path) == files_before


def test_report_for_in_progress_execution_is_conflict(report_client):
    client, _, executions = report_client
    run = _create_run(client)
    executions.create(
        Execution(
            id="running-execution",
            test_run_id=run["id"],
            status=ExecutionStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
            total_steps=1,
            steps=[],
        )
    )

    assert client.get(f"/api/test-runs/{run['id']}/report").status_code == 409
