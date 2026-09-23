import pytest
from fastapi.testclient import TestClient

from app.dependencies import (
    get_execution_repository,
    get_orchestrator,
    get_test_run_repository,
)
from app.executors import MockTestStepExecutor
from app.json_execution_repository import JsonFileExecutionRepository
from app.json_repository import JsonFileTestRunRepository
from app.main import app
from app.orchestrator import Orchestrator

BASE_PAYLOAD = {
    "run_name": "Execution API test run",
    "environment": "staging",
    "components": ["inji-certify"],
    "test_suites": [
        {
            "provider": "openid",
            "suite_id": "tbd-openid-suite",
            "display_name": "OpenID Conformance (placeholder)",
        }
    ],
    "benchmark": {"minimum_pass_rate": 95, "critical_failures_allowed": 0},
}


@pytest.fixture
def client(tmp_path):
    test_runs_repo = JsonFileTestRunRepository(tmp_path / "test_runs.json")
    executions_repo = JsonFileExecutionRepository(tmp_path / "executions.json")
    executor = MockTestStepExecutor()

    app.dependency_overrides[get_test_run_repository] = lambda: test_runs_repo
    app.dependency_overrides[get_execution_repository] = lambda: executions_repo
    app.dependency_overrides[get_orchestrator] = lambda: Orchestrator(
        test_runs_repo, executions_repo, executor
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _create_run(client, test_suites=None):
    payload = {**BASE_PAYLOAD}
    if test_suites is not None:
        payload["test_suites"] = test_suites
    response = client.post("/api/test-runs", json=payload)
    assert response.status_code == 201
    return response.json()


def test_post_test_runs_still_does_not_execute(client):
    run = _create_run(client)
    assert run["status"] == "CONFIGURED"
    response = client.get(f"/api/test-runs/{run['id']}/execution")
    assert response.status_code == 404


def test_execute_valid_run_returns_passed(client):
    run = _create_run(client)
    response = client.post(f"/api/test-runs/{run['id']}/execute")
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "PASSED"
    assert body["test_run_id"] == run["id"]
    assert body["total_steps"] == 1
    assert body["completed_steps"] == 1
    assert len(body["step_results"]) == 1


def test_execute_updates_run_status_to_passed(client):
    run = _create_run(client)
    client.post(f"/api/test-runs/{run['id']}/execute")
    updated = client.get(f"/api/test-runs/{run['id']}").json()
    assert updated["status"] == "PASSED"


def test_execute_failed_step_marks_execution_and_run_failed(client):
    run = _create_run(
        client,
        test_suites=[
            {"provider": "openid", "suite_id": "will-fail", "display_name": "Will Fail"}
        ],
    )
    response = client.post(f"/api/test-runs/{run['id']}/execute")
    body = response.json()
    assert body["status"] == "FAILED"

    updated = client.get(f"/api/test-runs/{run['id']}").json()
    assert updated["status"] == "FAILED"


def test_execute_nonexistent_run_returns_404(client):
    response = client.post("/api/test-runs/does-not-exist/execute")
    assert response.status_code == 404


def test_get_execution_returns_latest(client):
    run = _create_run(client)
    first = client.post(f"/api/test-runs/{run['id']}/execute").json()
    second = client.post(f"/api/test-runs/{run['id']}/execute").json()

    latest = client.get(f"/api/test-runs/{run['id']}/execution").json()
    assert latest["id"] == second["id"]
    assert latest["id"] != first["id"]


def test_get_execution_for_nonexistent_run_returns_404(client):
    response = client.get("/api/test-runs/does-not-exist/execution")
    assert response.status_code == 404


def test_client_supplied_status_is_ignored_on_create(client):
    payload = {**BASE_PAYLOAD, "status": "PASSED"}
    response = client.post("/api/test-runs", json=payload)
    assert response.status_code == 201
    assert response.json()["status"] == "CONFIGURED"


def test_existing_m2_crud_still_works(client):
    run = _create_run(client)
    assert client.get("/api/test-runs").status_code == 200
    assert client.get(f"/api/test-runs/{run['id']}").status_code == 200
    assert client.delete(f"/api/test-runs/{run['id']}").status_code == 204
    assert client.get(f"/api/test-runs/{run['id']}").status_code == 404
