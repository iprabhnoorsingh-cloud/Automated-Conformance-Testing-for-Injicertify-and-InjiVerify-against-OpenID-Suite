from typing import Optional
import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_test_run_repository
from app.json_repository import JsonFileTestRunRepository
from app.main import app

VALID_PAYLOAD = {
    "run_name": "Nightly Inji Certify Check",
    "environment": "staging",
    "components": ["inji-certify"],
    "test_suites": [
        {
            "provider": "openid",
            "suite_id": "tbd-openid-suite",
            "display_name": "OpenID Conformance (placeholder)",
        }
    ],
    "benchmark": {
        "minimum_pass_rate": 95,
        "critical_failures_allowed": 0,
    },
    "metadata": {
        "notes": "Smoke test configuration",
        "created_by": "qa-team",
    },
}


@pytest.fixture
def client(tmp_path):
    repo = JsonFileTestRunRepository(tmp_path / "test_runs.json")
    app.dependency_overrides[get_test_run_repository] = lambda: repo
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _create(client, overrides: Optional[dict] = None):
    payload = {**VALID_PAYLOAD, **(overrides or {})}
    return client.post("/api/test-runs", json=payload)


# --- Validation ---------------------------------------------------------


def test_valid_configuration_is_accepted(client):
    response = _create(client)
    assert response.status_code == 201


def test_empty_run_name_rejected(client):
    response = _create(client, {"run_name": ""})
    assert response.status_code == 422


def test_missing_environment_rejected(client):
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "environment"}
    response = client.post("/api/test-runs", json=payload)
    assert response.status_code == 422


def test_empty_components_rejected(client):
    response = _create(client, {"components": []})
    assert response.status_code == 422


def test_unknown_component_rejected(client):
    response = _create(client, {"components": ["not-a-real-component"]})
    assert response.status_code == 422


def test_empty_test_suites_rejected(client):
    response = _create(client, {"test_suites": []})
    assert response.status_code == 422


def test_pass_rate_below_zero_rejected(client):
    response = _create(
        client,
        {"benchmark": {"minimum_pass_rate": -1, "critical_failures_allowed": 0}},
    )
    assert response.status_code == 422


def test_pass_rate_above_100_rejected(client):
    response = _create(
        client,
        {"benchmark": {"minimum_pass_rate": 101, "critical_failures_allowed": 0}},
    )
    assert response.status_code == 422


def test_negative_critical_failures_rejected(client):
    response = _create(
        client,
        {"benchmark": {"minimum_pass_rate": 95, "critical_failures_allowed": -1}},
    )
    assert response.status_code == 422


# --- CRUD ----------------------------------------------------------------


def test_create_test_run(client):
    response = _create(client)
    body = response.json()
    assert body["status"] == "CONFIGURED"
    assert body["run_name"] == VALID_PAYLOAD["run_name"]
    assert "id" in body
    assert "created_at" in body


def test_create_does_not_execute_anything(client):
    response = _create(client)
    body = response.json()
    # No result/execution fields should appear on a freshly configured run.
    assert body["status"] == "CONFIGURED"
    assert "result" not in body
    assert "pass_rate" not in body


def test_list_test_runs(client):
    _create(client)
    _create(client, {"run_name": "Second run"})
    response = client.get("/api/test-runs")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_get_test_run_by_id(client):
    created = _create(client).json()
    response = client.get(f"/api/test-runs/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_nonexistent_run_returns_404(client):
    response = client.get("/api/test-runs/does-not-exist")
    assert response.status_code == 404


def test_delete_test_run(client):
    created = _create(client).json()
    response = client.delete(f"/api/test-runs/{created['id']}")
    assert response.status_code == 204


def test_deleted_run_is_no_longer_retrievable(client):
    created = _create(client).json()
    client.delete(f"/api/test-runs/{created['id']}")
    response = client.get(f"/api/test-runs/{created['id']}")
    assert response.status_code == 404
