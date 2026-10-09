import asyncio
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.async_runner import async_runner, cleanup_stale_executions
from app.orchestration import ExecutionStatus
from app.orchestrator import Orchestrator


def _payload(suite: dict) -> dict:
    return {
        "run_name": "Test Run",
        "environment": "development",
        "components": ["inji-certify"],
        "test_suites": [suite],
        "benchmark": {"minimum_pass_rate": 100, "critical_failures_allowed": 0},
    }

def _mock_suite() -> dict:
    return {
        "provider": "mock",
        "suite_id": "conformance-ok",
        "display_name": "mock ok",
    }


@pytest.fixture
def repos(tmp_path):
    from app.json_repository import JsonFileTestRunRepository
    from app.json_execution_repository import JsonFileExecutionRepository
    from app.dependencies import get_test_run_repository, get_execution_repository, get_orchestrator, get_executor_registry

    run_repo = JsonFileTestRunRepository(tmp_path / "test_runs.json")
    exec_repo = JsonFileExecutionRepository(tmp_path / "executions.json")
    exec_registry = get_executor_registry()

    app.dependency_overrides[get_test_run_repository] = lambda: run_repo
    app.dependency_overrides[get_execution_repository] = lambda: exec_repo
    app.dependency_overrides[get_orchestrator] = lambda: Orchestrator(
        test_run_repository=run_repo,
        execution_repository=exec_repo,
        executors=exec_registry,
    )
    yield run_repo, exec_repo
    app.dependency_overrides.clear()


@pytest.fixture
def auth_client():
    from app.config import settings
    from pydantic import SecretStr
    # For testing, ensure api_key is set
    settings.api_key = SecretStr("1234567890123456") # 16 chars
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer 1234567890123456"
        yield client

@pytest.fixture(autouse=True)
def _reset_runner():
    import threading
    async_runner._queue_semaphore = threading.Semaphore(async_runner.maxsize)
    # Only try to empty if it exists
    if async_runner.queue is not None:
        try:
            while not async_runner.queue.empty():
                async_runner.queue.get_nowait()
        except Exception:
            pass


def test_async_execution_lifecycle(auth_client, repos):
    from app.dependencies import get_executor_registry
    orch = Orchestrator(repos[0], repos[1], get_executor_registry())

    # Mock the background worker's dependency lookups
    with patch("app.async_runner.get_orchestrator", return_value=orch), \
         patch("app.async_runner.get_execution_repository", return_value=repos[1]), \
         patch("app.async_runner.get_test_run_repository", return_value=repos[0]):

        # Enqueue a test run
        payload = _payload(_mock_suite())
        run_resp = auth_client.post("/api/test-runs", json=payload)
        run_id = run_resp.json()["id"]

        # Test executing async
        resp = auth_client.post(f"/api/test-runs/{run_id}/execute-async")
        assert resp.status_code == 202
        exec_id = resp.json()["id"]
        assert resp.json()["status"] == "QUEUED"

        import time
        for _ in range(20):
            status_resp = auth_client.get(f"/api/executions/{exec_id}")
            if status_resp.json()["status"] in ("PASSED", "FAILED", "ERROR"):
                break
            time.sleep(0.1)

        assert status_resp.status_code == 200
        assert status_resp.json()["status"] == "PASSED"


def test_async_queue_full_returns_429(auth_client, repos):
    run_resp = auth_client.post("/api/test-runs", json=_payload(_mock_suite()))
    run_id = run_resp.json()["id"]

    # Stop worker task so it doesn't process them while we fill it
    if async_runner._worker_task:
        async_runner._worker_task.cancel()

    # Fill the queue (semaphore)
    max_size = async_runner.maxsize
    for _ in range(max_size):
        async_runner.try_reserve()

    # Queue full, request should fail
    resp = auth_client.post(f"/api/test-runs/{run_id}/execute-async")
    assert resp.status_code == 429
    assert "queue is full" in resp.json()["detail"]


def test_history_endpoint(auth_client, repos):
    run_resp = auth_client.post("/api/test-runs", json=_payload(_mock_suite()))
    run_id = run_resp.json()["id"]

    # Create 2 executions
    from app.dependencies import get_executor_registry
    orch = Orchestrator(repos[0], repos[1], get_executor_registry())
    exec1 = orch.plan_execution(run_id)
    exec2 = orch.plan_execution(run_id)
    orch.run_execution(exec1.id)
    orch.run_execution(exec2.id)

    # Get history
    resp = auth_client.get(f"/api/test-runs/{run_id}/executions")
    assert resp.status_code == 200
    history = resp.json()
    assert len(history) == 2
    # Newest first
    assert history[0]["id"] == exec2.id
    assert history[1]["id"] == exec1.id


def test_orphan_cleanup(auth_client, repos):
    run_resp = auth_client.post("/api/test-runs", json=_payload(_mock_suite()))
    run_id = run_resp.json()["id"]

    from app.dependencies import get_executor_registry
    orch = Orchestrator(repos[0], repos[1], get_executor_registry())
    exec_queued = orch.plan_execution(run_id)

    exec_running = orch.plan_execution(run_id)
    # forcefully set to RUNNING
    exec_running.status = ExecutionStatus.RUNNING
    repos[1].update(exec_running)

    with patch("app.async_runner.get_execution_repository", return_value=repos[1]), \
         patch("app.async_runner.get_test_run_repository", return_value=repos[0]):
        # Run cleanup
        cleanup_stale_executions()

    # Verify they were changed to ERROR
    assert repos[1].get(exec_queued.id).status == ExecutionStatus.ERROR
    assert repos[1].get(exec_running.id).status == ExecutionStatus.ERROR


def test_concurrent_enqueue(auth_client, repos):
    # Test that concurrent requests properly respect the queue capacity limit
    run_resp = auth_client.post("/api/test-runs", json=_payload(_mock_suite()))
    run_id = run_resp.json()["id"]

    # Stop worker to ensure items stay in queue
    if async_runner._worker_task:
        async_runner._worker_task.cancel()

    import threading
    results = []

    def enqueue_req():
        resp = auth_client.post(f"/api/test-runs/{run_id}/execute-async")
        results.append(resp.status_code)

    threads = []
    # Send max_size + 5 concurrent requests
    total_requests = async_runner.maxsize + 5
    for _ in range(total_requests):
        t = threading.Thread(target=enqueue_req)
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    successes = results.count(202)
    failures = results.count(429)

    assert successes == async_runner.maxsize
    assert failures == 5

    # Verify no orphaned QUEUED executions
    executions = repos[1]._read_all().values()
    queued_count = sum(1 for e in executions if e["status"] == "QUEUED")
    assert queued_count == async_runner.maxsize


def test_shared_concurrency_sync_and_async(auth_client, repos):
    # Test that M9 synchronous requests and M11-A async workers share the same ExecutionLimiter
    from app.concurrency import execution_limiter

    run_resp = auth_client.post("/api/test-runs", json=_payload(_mock_suite()))
    run_id = run_resp.json()["id"]

    from app.dependencies import get_executor_registry
    orch = Orchestrator(repos[0], repos[1], get_executor_registry())

    with patch("app.async_runner.get_orchestrator", return_value=orch), \
         patch("app.async_runner.get_execution_repository", return_value=repos[1]), \
         patch("app.async_runner.get_test_run_repository", return_value=repos[0]):

        # Acquire all concurrency slots directly
        acquired_locks = []
        for _ in range(execution_limiter._capacity):
            assert execution_limiter.try_acquire() is True
            acquired_locks.append(True)

        # Now synchronous M9 should fail with 429
        sync_resp = auth_client.post(f"/api/test-runs/{run_id}/execute")
        assert sync_resp.status_code == 429

        # Now enqueue an async job - it should be accepted (202) because queue has space
        async_resp = auth_client.post(f"/api/test-runs/{run_id}/execute-async")
        assert async_resp.status_code == 202
        exec_id = async_resp.json()["id"]

        # But it shouldn't execute because it's waiting on capacity!
        import time
        time.sleep(0.1)
        status_resp = auth_client.get(f"/api/executions/{exec_id}")
        assert status_resp.json()["status"] == "QUEUED"

        # Now release ONE concurrency slot
        execution_limiter.release()

        # The background worker should immediately acquire it and start execution
        for _ in range(20):
            status_resp = auth_client.get(f"/api/executions/{exec_id}")
            if status_resp.json()["status"] in ("PASSED", "FAILED", "ERROR"):
                break
            time.sleep(0.1)

        assert status_resp.json()["status"] == "PASSED"

        # Release remaining locks to keep environment clean
        for _ in range(len(acquired_locks) - 1):
            execution_limiter.release()
