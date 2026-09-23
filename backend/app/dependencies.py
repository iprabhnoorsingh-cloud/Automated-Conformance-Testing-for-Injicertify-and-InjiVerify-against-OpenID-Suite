"""FastAPI dependency providers.

Exposed as a function (not a bare module-level import) so tests can override
it via app.dependency_overrides to point at a temporary repository instead
of the real data file.
"""

from pathlib import Path

from app.execution_repository import ExecutionRepository
from app.executors import MockTestStepExecutor
from app.json_execution_repository import JsonFileExecutionRepository
from app.json_repository import JsonFileTestRunRepository
from app.orchestrator import Orchestrator
from app.repository import TestRunRepository

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_FILE = BASE_DIR / "data" / "test_runs.json"
DEFAULT_EXECUTIONS_FILE = BASE_DIR / "data" / "executions.json"

_repository = JsonFileTestRunRepository(DEFAULT_DATA_FILE)
_execution_repository = JsonFileExecutionRepository(DEFAULT_EXECUTIONS_FILE)
_executor = MockTestStepExecutor()


def get_test_run_repository() -> TestRunRepository:
    return _repository


def get_execution_repository() -> ExecutionRepository:
    return _execution_repository


def get_orchestrator() -> Orchestrator:
    return Orchestrator(
        test_run_repository=get_test_run_repository(),
        execution_repository=get_execution_repository(),
        executor=_executor,
    )
