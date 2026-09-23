"""FastAPI dependency providers.

Exposed as a function (not a bare module-level import) so tests can override
it via app.dependency_overrides to point at a temporary repository instead
of the real data file.
"""

from pathlib import Path

from app.config import settings
from app.execution_repository import ExecutionRepository
from app.executors import ExecutorRegistry, MockTestStepExecutor
from app.inji_executors import (
    CertifyApiTestRigExecutor,
    InjiTestRigSettings,
    VerifyApiTestRigExecutor,
)
from app.json_execution_repository import JsonFileExecutionRepository
from app.json_repository import JsonFileTestRunRepository
from app.openid_client import OpenIDConformanceClient
from app.openid_executor import OpenIDConformanceExecutor
from app.orchestrator import Orchestrator
from app.repository import TestRunRepository

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA_FILE = BASE_DIR / "data" / "test_runs.json"
DEFAULT_EXECUTIONS_FILE = BASE_DIR / "data" / "executions.json"

_repository = JsonFileTestRunRepository(DEFAULT_DATA_FILE)
_execution_repository = JsonFileExecutionRepository(DEFAULT_EXECUTIONS_FILE)

_openid_client = OpenIDConformanceClient(
    base_url=settings.openid_conformance_base_url,
    api_token=settings.openid_conformance_api_token,
    verify_ssl=settings.openid_conformance_verify_ssl,
    timeout=settings.openid_conformance_timeout,
)

_executor_registry = ExecutorRegistry(
    {
        "mock": MockTestStepExecutor(),
        "openid": OpenIDConformanceExecutor(
            client=_openid_client,
            wait_timeout_ms=int(settings.openid_conformance_wait_timeout * 1000),
        ),
        "injicertify": CertifyApiTestRigExecutor(
            InjiTestRigSettings(
                jar_path=settings.inji_certify_test_rig_jar,
                working_directory=settings.inji_certify_test_rig_workdir,
                java_executable=settings.inji_test_rig_java,
                timeout_seconds=settings.inji_test_rig_timeout_seconds,
            )
        ),
        "injiverify": VerifyApiTestRigExecutor(
            InjiTestRigSettings(
                jar_path=settings.inji_verify_test_rig_jar,
                working_directory=settings.inji_verify_test_rig_workdir,
                java_executable=settings.inji_test_rig_java,
                timeout_seconds=settings.inji_test_rig_timeout_seconds,
            )
        ),
    }
)


def get_test_run_repository() -> TestRunRepository:
    return _repository


def get_execution_repository() -> ExecutionRepository:
    return _execution_repository


def get_executor_registry() -> ExecutorRegistry:
    return _executor_registry


def get_orchestrator() -> Orchestrator:
    return Orchestrator(
        test_run_repository=get_test_run_repository(),
        execution_repository=get_execution_repository(),
        executors=get_executor_registry(),
    )
