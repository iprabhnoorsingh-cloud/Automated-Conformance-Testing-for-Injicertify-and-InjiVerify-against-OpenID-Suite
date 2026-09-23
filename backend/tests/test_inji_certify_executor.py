"""Tests for CertifyApiTestRigExecutor, end-to-end against the real
subprocess layer but with tests/fixtures/fake_java_rig.py standing in for
`java` — no real JVM, Maven, or Inji Test-Rig JAR required. This exercises
real argv/env construction, real process launch, real report discovery and
parsing.
"""

import json
from pathlib import Path

import pytest

from app.executors import ExecutionContext
from app.inji_executors import CertifyApiTestRigExecutor, InjiTestRigSettings
from app.orchestration import ExecutionStatus, Step

FIXTURE_JAVA = str(Path(__file__).parent / "fixtures" / "fake_java_rig.py")

BASE_CONFIG = {
    "test_level": "smoke",
    "env_user": "dev",
    "env_endpoint": "https://api-internal.dev.mosip.net",
    "use_case_to_execute": "mock",
}


def make_step(injicertify_config):
    return Step(
        step_id="inji-certify:injicertify:smoke",
        display_name="Inji Certify API Test Rig",
        provider="injicertify",
        component="inji-certify",
        order=0,
        suite_config={
            "provider": "injicertify",
            "suite_id": "smoke",
            "display_name": "Inji Certify API Test Rig",
            "injicertify_config": injicertify_config,
        },
    )


def make_context():
    return ExecutionContext(test_run_id="run-1", execution_id="exec-1", environment="staging")


@pytest.fixture
def fake_jar(tmp_path):
    jar = tmp_path / "apitest-injicertify-0.14.0-jar-with-dependencies.jar"
    jar.touch()
    return jar


def make_executor(monkeypatch, tmp_path, scenario="pass", timeout=10, sleep_seconds=None):
    settings = InjiTestRigSettings(
        jar_path=str(tmp_path / "apitest-injicertify-*-jar-with-dependencies.jar"),
        working_directory=str(tmp_path),
        java_executable=FIXTURE_JAVA,
        timeout_seconds=timeout,
    )
    executor = CertifyApiTestRigExecutor(settings)

    # monkeypatch (not raw os.environ mutation) so these never leak into
    # other tests regardless of pass/fail.
    monkeypatch.setenv("FAKE_RIG_SCENARIO", scenario)
    dump_path = tmp_path / "dump.json"
    monkeypatch.setenv("FAKE_RIG_DUMP_PATH", str(dump_path))
    if sleep_seconds is not None:
        monkeypatch.setenv("FAKE_RIG_SLEEP_SECONDS", str(sleep_seconds))
    return executor, dump_path


def test_successful_run_produces_passed(monkeypatch, tmp_path, fake_jar):
    executor, _ = make_executor(monkeypatch, tmp_path, scenario="pass")
    result = executor.execute(make_step(BASE_CONFIG), make_context())

    assert result.status == ExecutionStatus.PASSED
    assert result.details["tests_total"] == 2
    assert result.details["tests_passed"] == 2
    assert result.details["process_exit_code"] == 0


def test_zero_exit_with_failing_report_is_still_failed(monkeypatch, tmp_path, fake_jar):
    # Proves exit code is never trusted over the parsed report — the real
    # InjiTestRunner always exits 0 regardless of test outcome.
    executor, _ = make_executor(monkeypatch, tmp_path, scenario="fail")
    result = executor.execute(make_step(BASE_CONFIG), make_context())

    assert result.status == ExecutionStatus.FAILED
    assert result.details["process_exit_code"] == 0
    assert result.details["tests_failed"] == 1
    assert result.details["failure_summary"] == ["c.Test.testA"]


def test_nonzero_exit_without_report_is_failed(monkeypatch, tmp_path, fake_jar):
    executor, _ = make_executor(monkeypatch, tmp_path, scenario="crash")
    result = executor.execute(make_step(BASE_CONFIG), make_context())

    assert result.status == ExecutionStatus.FAILED
    assert result.details["process_exit_code"] == 1
    assert result.details["error_type"] == "report_not_found"


def test_missing_report_after_clean_exit_is_failed(monkeypatch, tmp_path, fake_jar):
    executor, _ = make_executor(monkeypatch, tmp_path, scenario="no_report")
    result = executor.execute(make_step(BASE_CONFIG), make_context())

    assert result.status == ExecutionStatus.FAILED
    assert result.details["process_exit_code"] == 0
    assert result.details["error_type"] == "report_not_found"


def test_malformed_report_is_failed(monkeypatch, tmp_path, fake_jar):
    executor, _ = make_executor(monkeypatch, tmp_path, scenario="malformed_report")
    result = executor.execute(make_step(BASE_CONFIG), make_context())

    assert result.status == ExecutionStatus.FAILED
    assert result.details["error_type"] == "malformed_report"


def test_timeout_kills_process_and_reports_timeout(monkeypatch, tmp_path, fake_jar):
    executor, _ = make_executor(
        monkeypatch, tmp_path, scenario="sleep", timeout=0.5, sleep_seconds=30
    )
    result = executor.execute(make_step(BASE_CONFIG), make_context())

    assert result.status == ExecutionStatus.FAILED
    assert result.details["error_type"] == "timeout"
    assert result.details["timed_out"] is True


def test_missing_configuration_never_starts_process(monkeypatch, tmp_path, fake_jar):
    executor, dump_path = make_executor(monkeypatch, tmp_path, scenario="pass")
    step = Step(
        step_id="inji-certify:injicertify:smoke",
        display_name="Inji Certify API Test Rig",
        provider="injicertify",
        component="inji-certify",
        order=0,
        suite_config={"provider": "injicertify", "suite_id": "smoke", "display_name": "x"},
    )
    result = executor.execute(step, make_context())

    assert result.status == ExecutionStatus.FAILED
    assert result.details["error_type"] == "missing_configuration"
    assert not dump_path.exists()  # process never launched


def test_jar_not_found_is_failed(monkeypatch, tmp_path):
    settings = InjiTestRigSettings(
        jar_path=str(tmp_path / "apitest-injicertify-*-jar-with-dependencies.jar"),
        working_directory=str(tmp_path),
        java_executable=FIXTURE_JAVA,
        timeout_seconds=10,
    )
    executor = CertifyApiTestRigExecutor(settings)
    result = executor.execute(make_step(BASE_CONFIG), make_context())

    assert result.status == ExecutionStatus.FAILED
    assert result.details["error_type"] == "jar_not_found"


def test_invalid_working_directory_is_failed(monkeypatch, tmp_path):
    settings = InjiTestRigSettings(
        jar_path=str(tmp_path / "some.jar"),
        working_directory=str(tmp_path / "does-not-exist"),
        java_executable=FIXTURE_JAVA,
        timeout_seconds=10,
    )
    executor = CertifyApiTestRigExecutor(settings)
    result = executor.execute(make_step(BASE_CONFIG), make_context())

    assert result.status == ExecutionStatus.FAILED
    assert result.details["error_type"] == "invalid_working_directory"


def test_not_configured_deployment_is_failed(monkeypatch, tmp_path):
    settings = InjiTestRigSettings(
        jar_path=None,
        working_directory=None,
        java_executable=FIXTURE_JAVA,
        timeout_seconds=10,
    )
    executor = CertifyApiTestRigExecutor(settings)
    result = executor.execute(make_step(BASE_CONFIG), make_context())

    assert result.status == ExecutionStatus.FAILED
    assert result.details["error_type"] == "test_rig_not_configured"


def test_argument_construction_matches_upstream_entrypoint(monkeypatch, tmp_path, fake_jar):
    executor, dump_path = make_executor(monkeypatch, tmp_path, scenario="pass")
    executor.execute(make_step(BASE_CONFIG), make_context())

    dumped = json.loads(dump_path.read_text())
    argv = dumped["argv"]
    assert argv[0] == "-jar"
    assert "-Dmodules=injicertify" in argv
    assert "-Denv.user=dev" in argv
    assert "-Denv.endpoint=https://api-internal.dev.mosip.net" in argv
    assert "-Denv.testLevel=smoke" in argv
    assert argv[-1] == str(fake_jar)


def test_use_case_and_extra_properties_become_env_vars(monkeypatch, tmp_path, fake_jar):
    config = {
        **BASE_CONFIG,
        "use_case_to_execute": "sunbird",
        "esignet_base_url": "https://esignet.example.test",
        "inji_certify_base_url": "https://injicertify.example.test",
        "mosip_components_base_urls": "auditmanager=api.example.test",
        "esignet_actuator_property_section": "esignet",
        "use_pre_configured_otp": True,
        "sunbird_base_url": "https://sunbird.example.test",
    }
    executor, dump_path = make_executor(monkeypatch, tmp_path, scenario="pass")
    executor.execute(make_step(config), make_context())

    dumped = json.loads(dump_path.read_text())
    env = dumped["env"]
    assert env["useCaseToExecute"] == "sunbird"
    assert env["eSignetbaseurl"] == "https://esignet.example.test"
    assert env["injiCertifyBaseURL"] == "https://injicertify.example.test"
    assert env["mosip_components_base_urls"] == "auditmanager=api.example.test"
    assert env["esignetActuatorPropertySection"] == "esignet"
    assert env["usePreConfiguredOtp"] == "true"
    assert env["sunBirdBaseURL"] == "https://sunbird.example.test"


def test_smoke_and_regression_test_level_is_passed_through(monkeypatch, tmp_path, fake_jar):
    config = {**BASE_CONFIG, "test_level": "smokeAndRegression"}
    executor, dump_path = make_executor(monkeypatch, tmp_path, scenario="pass")
    executor.execute(make_step(config), make_context())

    dumped = json.loads(dump_path.read_text())
    assert "-Denv.testLevel=smokeAndRegression" in dumped["argv"]


def test_timeout_result_never_includes_raw_process_output_fields(monkeypatch, tmp_path, fake_jar):
    # process_output_excerpt (already sanitized — see test_inji_process.py)
    # is the only output-derived field ever persisted; raw stdout/stderr
    # are never stored verbatim.
    executor, _ = make_executor(
        monkeypatch, tmp_path, scenario="sleep", timeout=0.5, sleep_seconds=30
    )
    result = executor.execute(make_step(BASE_CONFIG), make_context())
    assert "stdout" not in result.details
    assert "stderr" not in result.details
    assert "process_output_excerpt" in result.details
