"""Tests for scripts/ci_gate.py (M9 CI gate).

HTTP is mocked at ``urllib.request.urlopen``; no real server or external
conformance system is contacted. The end-to-end tests route the script's
request into the real FastAPI app (mock provider) to prove that both PASSED
and FAILED verdicts come from the real M7 evaluation.
"""

import importlib.util
import io
import json
import socket
import urllib.error
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.dependencies import (
    get_execution_repository,
    get_orchestrator,
    get_test_run_repository,
)
from app.executors import ExecutorRegistry, MockTestStepExecutor
from app.json_execution_repository import JsonFileExecutionRepository
from app.json_repository import JsonFileTestRunRepository
from app.main import app
from app.orchestrator import Orchestrator
from tests.conftest import AUTH_HEADERS, TEST_API_KEY

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ci_gate.py"
_spec = importlib.util.spec_from_file_location("ci_gate", SCRIPT)
ci_gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ci_gate)

ARGS = ["--run-id", "run-1", "--base-url", "http://backend.test"]


class FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch_urlopen(monkeypatch, behavior):
    calls = []

    def fake(request, timeout=None):
        calls.append((request, timeout))
        return behavior(request)

    monkeypatch.setattr(ci_gate.urllib.request, "urlopen", fake)
    return calls


def _execution(status="PASSED", **evaluation):
    return {
        "id": "exec-1",
        "status": "PASSED",
        "benchmark_evaluation": {
            "status": status,
            "evidence_complete": True,
            "pass_rate": 100,
            "minimum_pass_rate": 95,
            **evaluation,
        },
    }


def _respond_json(payload):
    return lambda request: FakeResponse(json.dumps(payload).encode())


def _http_error(code, body=b'{"detail": "boom"}'):
    def raise_it(request):
        raise urllib.error.HTTPError(
            request.full_url, code, "err", {}, io.BytesIO(body)
        )

    return raise_it


def test_passed_exits_zero_and_posts_to_execute(monkeypatch, capsys):
    calls = _patch_urlopen(monkeypatch, _respond_json(_execution("PASSED")))

    assert ci_gate.main(ARGS) == 0

    request, timeout = calls[0]
    assert request.get_method() == "POST"
    assert request.full_url == "http://backend.test/api/test-runs/run-1/execute"
    assert timeout == ci_gate.DEFAULT_TIMEOUT_SECONDS
    assert "PASSED" in capsys.readouterr().out


def test_failed_exits_non_zero(monkeypatch, capsys):
    _patch_urlopen(
        monkeypatch,
        _respond_json(
            _execution(
                "FAILED",
                violations=[{"code": "pass_rate_below_minimum", "message": "too low"}],
            )
        ),
    )

    assert ci_gate.main(ARGS) == ci_gate.EXIT_GATE_FAILED
    err = capsys.readouterr().err
    assert "benchmark gate FAILED" in err
    assert "pass_rate_below_minimum" in err


@pytest.mark.parametrize(
    "payload",
    [
        {"id": "exec-1", "status": "PASSED"},
        {"id": "exec-1", "benchmark_evaluation": None},
        {"id": "exec-1", "benchmark_evaluation": "PASSED"},
        {"id": "exec-1", "benchmark_evaluation": {}},
        _execution("passed"),
        _execution("UNKNOWN"),
        [],
        "PASSED",
    ],
)
def test_missing_or_unrecognized_evaluation_fails_closed(monkeypatch, payload):
    _patch_urlopen(monkeypatch, _respond_json(payload))

    assert ci_gate.main(ARGS) == ci_gate.EXIT_BAD_RESPONSE


@pytest.mark.parametrize("body", [b"not json", b"", b"\xff\xfe"])
def test_malformed_json_fails_closed(monkeypatch, body):
    _patch_urlopen(monkeypatch, lambda request: FakeResponse(body))

    assert ci_gate.main(ARGS) == ci_gate.EXIT_BAD_RESPONSE


@pytest.mark.parametrize("code", [404, 409, 422, 400, 500, 502, 503])
def test_http_errors_fail_closed(monkeypatch, capsys, code):
    _patch_urlopen(monkeypatch, _http_error(code))

    assert ci_gate.main(ARGS) == ci_gate.EXIT_HTTP_ERROR
    assert f"HTTP {code}" in capsys.readouterr().err


def test_http_error_with_non_json_body_still_fails(monkeypatch):
    _patch_urlopen(monkeypatch, _http_error(500, b"<html>oops</html>"))

    assert ci_gate.main(ARGS) == ci_gate.EXIT_HTTP_ERROR


def test_network_failure_fails_closed(monkeypatch, capsys):
    def refuse(request):
        raise urllib.error.URLError(ConnectionRefusedError("refused"))

    _patch_urlopen(monkeypatch, refuse)

    assert ci_gate.main(ARGS) == ci_gate.EXIT_NETWORK_ERROR
    assert "could not reach backend" in capsys.readouterr().err


@pytest.mark.parametrize(
    "exc",
    [
        socket.timeout("timed out"),
        TimeoutError("timed out"),
        urllib.error.URLError(socket.timeout("timed out")),
    ],
)
def test_timeout_fails_closed(monkeypatch, capsys, exc):
    def raise_it(request):
        raise exc

    _patch_urlopen(monkeypatch, raise_it)

    assert ci_gate.main(ARGS + ["--timeout", "5"]) == ci_gate.EXIT_NETWORK_ERROR
    assert "timed out after 5s" in capsys.readouterr().err


def test_base_url_from_environment_and_invalid_usage(monkeypatch):
    monkeypatch.setenv("MCC_API_URL", "http://from-env.test/")
    calls = _patch_urlopen(monkeypatch, _respond_json(_execution("PASSED")))

    assert ci_gate.main(["--run-id", "run-1"]) == 0
    assert calls[0][0].full_url == "http://from-env.test/api/test-runs/run-1/execute"
    assert ci_gate.main(["--run-id", "r", "--base-url", "not-a-url"]) == ci_gate.EXIT_USAGE
    assert ci_gate.main(ARGS + ["--timeout", "0"]) == ci_gate.EXIT_USAGE
    with pytest.raises(SystemExit):
        ci_gate.main([])


# --- end to end against the real app + mock provider -----------------------


@pytest.fixture
def live_gate(tmp_path, monkeypatch):
    test_runs = JsonFileTestRunRepository(tmp_path / "test_runs.json")
    executions = JsonFileExecutionRepository(tmp_path / "executions.json")
    registry = ExecutorRegistry({"mock": MockTestStepExecutor()})
    app.dependency_overrides[get_test_run_repository] = lambda: test_runs
    app.dependency_overrides[get_execution_repository] = lambda: executions
    app.dependency_overrides[get_orchestrator] = lambda: Orchestrator(
        test_runs, executions, registry
    )
    with TestClient(app) as client:

        def route_to_app(request, timeout=None):
            path = request.full_url.replace("http://backend.test", "")
            # Forward exactly what ci_gate.py sent: the client itself holds
            # no credentials, so this proves the script authenticates.
            auth = request.get_header("Authorization")
            resp = client.post(path, headers={"Authorization": auth} if auth else {})
            if resp.status_code >= 400:
                raise urllib.error.HTTPError(
                    request.full_url, resp.status_code, "err", {}, io.BytesIO(resp.content)
                )
            return FakeResponse(resp.content)

        monkeypatch.setattr(ci_gate.urllib.request, "urlopen", route_to_app)
        yield client
    app.dependency_overrides.clear()


def _create_run(client, suite_id):
    response = client.post(
        "/api/test-runs",
        headers=AUTH_HEADERS,
        json={
            "run_name": f"ci gate {suite_id}",
            "environment": "development",
            "components": ["inji-certify"],
            "test_suites": [
                {"provider": "mock", "suite_id": suite_id, "display_name": suite_id}
            ],
            "benchmark": {"minimum_pass_rate": 100, "critical_failures_allowed": 0},
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_end_to_end_mock_passed_run_exits_zero(live_gate, monkeypatch):
    monkeypatch.setenv("MCC_API_KEY", TEST_API_KEY)
    run_id = _create_run(live_gate, "conformance-ok")

    assert ci_gate.main(["--run-id", run_id, "--base-url", "http://backend.test"]) == 0


def test_end_to_end_mock_failing_run_exits_non_zero(live_gate, monkeypatch):
    monkeypatch.setenv("MCC_API_KEY", TEST_API_KEY)
    run_id = _create_run(live_gate, "conformance-fail")

    code = ci_gate.main(["--run-id", run_id, "--base-url", "http://backend.test"])

    assert code == ci_gate.EXIT_GATE_FAILED


def test_end_to_end_unknown_run_exits_non_zero(live_gate, monkeypatch):
    monkeypatch.setenv("MCC_API_KEY", TEST_API_KEY)
    code = ci_gate.main(["--run-id", "missing", "--base-url", "http://backend.test"])

    assert code == ci_gate.EXIT_HTTP_ERROR


# --- M10: authentication ----------------------------------------------------


def test_sends_bearer_key_from_environment(monkeypatch):
    monkeypatch.setenv("MCC_API_KEY", TEST_API_KEY)
    calls = _patch_urlopen(monkeypatch, _respond_json(_execution("PASSED")))

    assert ci_gate.main(ARGS) == 0
    assert calls[0][0].get_header("Authorization") == f"Bearer {TEST_API_KEY}"


def test_without_key_backend_401_is_exit_http_error(live_gate, monkeypatch):
    monkeypatch.delenv("MCC_API_KEY", raising=False)
    run_id = _create_run(live_gate, "conformance-ok")

    code = ci_gate.main(["--run-id", run_id, "--base-url", "http://backend.test"])

    assert code == ci_gate.EXIT_HTTP_ERROR
