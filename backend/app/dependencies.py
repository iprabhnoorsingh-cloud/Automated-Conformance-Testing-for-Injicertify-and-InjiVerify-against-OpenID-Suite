"""FastAPI dependency providers.

Exposed as a function (not a bare module-level import) so tests can override
it via app.dependency_overrides to point at a temporary repository instead
of the real data file.
"""

from pathlib import Path

from app.json_repository import JsonFileTestRunRepository
from app.repository import TestRunRepository

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_FILE = BASE_DIR / "data" / "test_runs.json"

_repository = JsonFileTestRunRepository(DEFAULT_DATA_FILE)


def get_test_run_repository() -> TestRunRepository:
    return _repository
