"""Persistence abstraction for Executions.

Mirrors app/repository.py's TestRunRepository: the Orchestrator depends only
on this Protocol, so JsonFileExecutionRepository can be swapped for a
database-backed implementation later without touching orchestration logic.
"""

from typing import Optional, Protocol

from app.orchestration import Execution


class ExecutionRepository(Protocol):
    def create(self, execution: Execution) -> Execution: ...

    def update(self, execution: Execution) -> Execution: ...

    def get(self, execution_id: str) -> Optional[Execution]: ...

    def get_latest_for_run(self, test_run_id: str) -> Optional[Execution]: ...
