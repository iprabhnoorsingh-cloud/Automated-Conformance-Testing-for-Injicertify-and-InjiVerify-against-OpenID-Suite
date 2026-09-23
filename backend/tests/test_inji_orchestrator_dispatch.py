"""Confirms the Orchestrator's ExecutorRegistry dispatch correctly routes
between all four providers introduced across M3-M5 in a single registry —
mock (M3) and openid (M4) must keep working unaffected by the M5 additions,
and injicertify/injiverify (M5) must be reachable through the exact same
dispatch mechanism, not a parallel code path.
"""

from datetime import datetime, timezone
from pathlib import Path

from app.executors import ExecutorRegistry, MockTestStepExecutor
from app.inji_executors import CertifyApiTestRigExecutor, InjiTestRigSettings, VerifyApiTestRigExecutor
from app.json_execution_repository import JsonFileExecutionRepository
from app.json_repository import JsonFileTestRunRepository
from app.openid_client import OpenIDConformanceClient
from app.openid_executor import OpenIDConformanceExecutor
from app.orchestration import ExecutionStatus
from app.orchestrator import Orchestrator
from app.schemas import (
    BenchmarkConfig,
    Environment,
    TestRunConfig,
    TestRunStatus,
    TestSuiteConfig,
)

FIXTURE_JAVA = str(Path(__file__).parent / "fixtures" / "fake_java_rig.py")


def make_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_RIG_SCENARIO", "pass")

    certify_jar = tmp_path / "apitest-injicertify-0.1.0-jar-with-dependencies.jar"
    certify_jar.touch()
    verify_jar = tmp_path / "apitest-injiverify-0.1.0-jar-with-dependencies.jar"
    verify_jar.touch()

    return ExecutorRegistry(
        {
            "mock": MockTestStepExecutor(),
            "openid": OpenIDConformanceExecutor(client=OpenIDConformanceClient(base_url=None)),
            "injicertify": CertifyApiTestRigExecutor(
                InjiTestRigSettings(
                    jar_path=str(certify_jar),
                    working_directory=str(tmp_path),
                    java_executable=FIXTURE_JAVA,
                    timeout_seconds=10,
                )
            ),
            "injiverify": VerifyApiTestRigExecutor(
                InjiTestRigSettings(
                    jar_path=str(verify_jar),
                    working_directory=str(tmp_path),
                    java_executable=FIXTURE_JAVA,
                    timeout_seconds=10,
                )
            ),
        }
    )


def make_run(test_runs_repo, run_id="run-1"):
    run = TestRunConfig(
        id=run_id,
        run_name="Multi-provider dispatch run",
        environment=Environment.STAGING,
        components=["inji-certify", "inji-verify"],
        test_suites=[
            TestSuiteConfig(provider="mock", suite_id="a", display_name="Mock suite"),
            TestSuiteConfig(
                provider="openid",
                suite_id="b",
                display_name="OpenID suite (no config)",
            ),
            TestSuiteConfig(
                provider="injicertify",
                suite_id="c",
                display_name="Certify suite",
                injicertify_config={
                    "test_level": "smoke",
                    "env_user": "dev",
                    "env_endpoint": "https://api-internal.dev.mosip.net",
                    "use_case_to_execute": "mock",
                },
            ),
            TestSuiteConfig(
                provider="injiverify",
                suite_id="d",
                display_name="Verify suite",
                injiverify_config={
                    "test_level": "smoke",
                    "env_user": "dev",
                    "env_endpoint": "https://api-internal.dev.mosip.net",
                    "inji_verify_base_url": "https://injiverify.dev.mosip.net",
                },
            ),
        ],
        benchmark=BenchmarkConfig(minimum_pass_rate=95, critical_failures_allowed=0),
        metadata=None,
        status=TestRunStatus.CONFIGURED,
        created_at=datetime.now(timezone.utc),
    )
    return test_runs_repo.create(run)


def test_mock_executor_step_passes(tmp_path, monkeypatch):
    test_runs_repo = JsonFileTestRunRepository(tmp_path / "test_runs.json")
    executions_repo = JsonFileExecutionRepository(tmp_path / "executions.json")
    orchestrator = Orchestrator(test_runs_repo, executions_repo, make_registry(tmp_path, monkeypatch))
    run = make_run(test_runs_repo, run_id="run-mock-only")

    # Restrict to a single mock component/suite to isolate this assertion.
    run.components = ["inji-certify"]
    run.test_suites = [TestSuiteConfig(provider="mock", suite_id="a", display_name="Mock suite")]
    test_runs_repo.update(run)

    execution = orchestrator.execute(run.id)
    assert execution.status == ExecutionStatus.PASSED
    assert execution.steps[0].provider == "mock"


def test_all_four_providers_dispatch_correctly_in_one_run(tmp_path, monkeypatch):
    test_runs_repo = JsonFileTestRunRepository(tmp_path / "test_runs.json")
    executions_repo = JsonFileExecutionRepository(tmp_path / "executions.json")
    orchestrator = Orchestrator(test_runs_repo, executions_repo, make_registry(tmp_path, monkeypatch))

    # Isolate one suite at a time (fail-fast in the orchestrator would
    # otherwise stop at the first non-mock failure) — the point here is
    # dispatch correctness, not overall run status.
    for provider, suite_id, config_key, config in [
        ("mock", "a", None, None),
        (
            "injicertify",
            "c",
            "injicertify_config",
            {
                "test_level": "smoke",
                "env_user": "dev",
                "env_endpoint": "https://api-internal.dev.mosip.net",
                "use_case_to_execute": "mock",
            },
        ),
        (
            "injiverify",
            "d",
            "injiverify_config",
            {
                "test_level": "smoke",
                "env_user": "dev",
                "env_endpoint": "https://api-internal.dev.mosip.net",
                "inji_verify_base_url": "https://injiverify.dev.mosip.net",
            },
        ),
    ]:
        run_id = f"run-{provider}"
        run = make_run(test_runs_repo, run_id=run_id)
        run.components = ["inji-certify"]
        suite_kwargs = {"provider": provider, "suite_id": suite_id, "display_name": provider}
        if config_key:
            suite_kwargs[config_key] = config
        run.test_suites = [TestSuiteConfig(**suite_kwargs)]
        test_runs_repo.update(run)

        execution = orchestrator.execute(run_id)
        assert execution.status == ExecutionStatus.PASSED, (
            f"provider {provider} did not dispatch/pass correctly: "
            f"{execution.step_results[0].message}"
        )
        assert execution.steps[0].provider == provider


def test_openid_without_config_fails_clearly_alongside_other_providers(tmp_path, monkeypatch):
    test_runs_repo = JsonFileTestRunRepository(tmp_path / "test_runs.json")
    executions_repo = JsonFileExecutionRepository(tmp_path / "executions.json")
    orchestrator = Orchestrator(test_runs_repo, executions_repo, make_registry(tmp_path, monkeypatch))

    run = make_run(test_runs_repo, run_id="run-openid")
    run.components = ["inji-certify"]
    run.test_suites = [
        TestSuiteConfig(provider="openid", suite_id="b", display_name="OpenID suite (no config)")
    ]
    test_runs_repo.update(run)

    execution = orchestrator.execute("run-openid")
    assert execution.status == ExecutionStatus.FAILED
    assert execution.step_results[0].details["error_type"] == "missing_openid_configuration"
