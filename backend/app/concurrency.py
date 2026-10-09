"""M10: bounded execution concurrency.

One process-wide, non-blocking capacity gate. It lives behind
`Orchestrator.execute`, so every way of starting an execution shares it and
cannot bypass it. Acquisition never waits: when capacity is exhausted the
caller is told immediately (HTTP 429) instead of queueing work, which would
keep request threads pinned. Execution itself stays synchronous.

Process-local by design — consistent with the documented single-worker
deployment constraint (see docs/architecture.md, "Deployment constraint").
"""

import threading

from app.config import settings


class ExecutionCapacityError(Exception):
    """All execution slots are in use."""


class ExecutionLimiter:
    def __init__(self, capacity: int):
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._capacity = capacity
        self._in_use = 0
        self._cond = threading.Condition(threading.Lock())

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def in_use(self) -> int:
        with self._cond:
            return self._in_use

    def acquire(self, blocking: bool = True) -> bool:
        with self._cond:
            if not blocking:
                if self._in_use >= self._capacity:
                    return False
                self._in_use += 1
                return True

            while self._in_use >= self._capacity:
                self._cond.wait()
            self._in_use += 1
            return True

    def try_acquire(self) -> bool:
        return self.acquire(blocking=False)

    def release(self) -> None:
        with self._cond:
            if self._in_use > 0:
                self._in_use -= 1
                self._cond.notify(1)


execution_limiter = ExecutionLimiter(settings.max_concurrent_executions)

