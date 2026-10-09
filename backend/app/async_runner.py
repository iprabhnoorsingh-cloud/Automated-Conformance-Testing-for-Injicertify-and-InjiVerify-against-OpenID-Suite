import asyncio
import threading
import logging
from typing import Optional

from app.config import settings
from app.concurrency import execution_limiter
from app.dependencies import get_execution_repository, get_orchestrator, get_test_run_repository
from app.orchestrator import ExecutionNotFoundError
from app.orchestration import ExecutionStatus

logger = logging.getLogger(__name__)

class AsyncRunner:
    def __init__(self, maxsize: int = 20):
        # Initialize queue later when loop is available
        self.maxsize = maxsize
        self.queue: Optional[asyncio.Queue] = None
        self._worker_task: Optional[asyncio.Task] = None
        self._shutdown = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._queue_semaphore = threading.Semaphore(maxsize)

    def try_reserve(self) -> bool:
        if self._shutdown:
            return False
        return self._queue_semaphore.acquire(blocking=False)

    def release_reservation(self):
        self._queue_semaphore.release()

    def start(self):
        self._shutdown = False
        self._loop = asyncio.get_running_loop()
        self.queue = asyncio.Queue(maxsize=self.maxsize)
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("Async execution runner started")

    async def stop(self):
        self._shutdown = True
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        logger.info("Async execution runner stopped")

    def enqueue(self, execution_id: str) -> bool:
        if self._shutdown or not self.queue or not self._loop:
            self.release_reservation()
            return False

        def _put():
            self.queue.put_nowait(execution_id)

        self._loop.call_soon_threadsafe(_put)
        return True

    async def _worker_loop(self):
        while not self._shutdown:
            try:
                execution_id = await self.queue.get()
            except asyncio.CancelledError:
                break

            try:
                acquired = await asyncio.to_thread(execution_limiter.acquire, True)
                if not acquired:
                    continue

                try:
                    orchestrator = get_orchestrator()
                    await asyncio.to_thread(orchestrator.run_execution, execution_id)
                except ExecutionNotFoundError:
                    logger.warning("Queued execution %s not found, skipping", execution_id)
                except Exception:
                    logger.exception("Unexpected error in async execution %s", execution_id)
                    # We should mark it as ERROR here
                    try:
                        exec_repo = get_execution_repository()
                        execution = exec_repo.get(execution_id)
                        if execution:
                            execution.status = ExecutionStatus.ERROR
                            exec_repo.update(execution)
                            run_repo = get_test_run_repository()
                            run = run_repo.get(execution.test_run_id)
                            if run:
                                from app.schemas import TestRunStatus
                                run.status = TestRunStatus.FAILED
                                run_repo.update(run)
                    except Exception:
                        logger.exception("Failed to mark execution %s as ERROR", execution_id)
                finally:
                    execution_limiter.release()
            except asyncio.CancelledError:
                break
            finally:
                self.queue.task_done()
                self.release_reservation()

async_runner = AsyncRunner(settings.max_async_queue_size)


def cleanup_stale_executions():
    """M11-A: Handle restart/orphan cleanup."""
    executions = get_execution_repository()
    test_runs = get_test_run_repository()

    data = executions._read_all()
    for exec_data in data.values():
        status = exec_data.get("status")
        if status in (ExecutionStatus.QUEUED.value, ExecutionStatus.RUNNING.value):
            execution_id = exec_data["id"]
            execution = executions.get(execution_id)
            if execution:
                execution.status = ExecutionStatus.ERROR
                executions.update(execution)
                run = test_runs.get(execution.test_run_id)
                if run:
                    from app.schemas import TestRunStatus
                    run.status = TestRunStatus.FAILED
                    test_runs.update(run)
