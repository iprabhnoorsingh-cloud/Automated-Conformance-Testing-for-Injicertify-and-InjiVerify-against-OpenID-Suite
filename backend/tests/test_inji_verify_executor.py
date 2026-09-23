"""Tests for VerifyApiTestRigExecutor — mirrors test_inji_certify_executor.py
but for the simpler Verify config surface (just injiVerifyBaseUrl beyond
the shared env.user/env.endpoint/env.testLevel)."""

import json
from pathlib import Path

import pytest

from app.executors import ExecutionContext
from app.inji_executors import InjiTestRigSettings, VerifyApiTestRigExecutor
from app.orchestration import ExecutionStatus, Step

FIXTURE_JAVA = str(Path(__file__).parent / "fixtures" / "fake_java_rig.py")

BASE_CONFIG = {
    "test_level": "smoke",
    "env_user": "dev",
    "env_endpoint": "https://api-internal.dev.mosip.net",
    "inji_verify_base_url": "https://injiverify.dev.mosip.net",
}


def make_step(injiverify_config):
    return Step(
        step_id="inji-verify:injiverify:smoke",
        display_name="Inji Verify API Test Rig",
        provider="injiverify",
        component="inji-verify",
        order=0,
        suite_config={
            "provider": "injiverify",
            "suite_id": "smoke",
            "display_name": "Inji Verify API Test Rig",
            "injiverify_config": injiverify_config,
        },
    )


def make_context():
    return ExecutionContext(test_run_id="run-1", execution_id="exec-1", environment="staging")


@pytest.fixture
def fake_jar(tmp_path):
    jar = tmp_path / "apitest-injiverify-0.18.2-jar-with-dependencies.jar"
    jar.touch()
    return jar


def make_executor(monkeypatch, tmp_path, scenario="pass", timeout=10, sleep_seconds=None):
    settings = InjiTestRigSettings(
        jar_path=str(tmp_path / "apitest-injiverify-*-jar-with-dependencies.jar"),
        working_directory=str(tmp_path),
        java_executable=FIXTURE_JAVA,
        timeout_seconds=timeout,
    )
    executor = VerifyApiTestRigExecutor(settings)

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
    assert result.details["process_exit_code"] == 0


def test_zero_exit_with_failing_report_is_still_failed(monkeypatch, tmp_path, fake_jar):
    executor, _ = make_executor(monkeypatch, tmp_path, scenario="fail")
    result = executor.execute(make_step(BASE_CONFIG), make_context())

    assert result.status == ExecutionStatus.FAILED
    assert result.details["process_exit_code"] == 0
    assert result.details["tests_failed"] == 1


def test_missing_configuration_never_starts_process(monkeypatch, tmp_path, fake_jar):
    executor, dump_path = make_executor(monkeypatch, tmp_path, scenario="pass")
    step = Step(
        step_id="inji-verify:injiverify:smoke",
        display_name="Inji Verify API Test Rig",
        provider="injiverify",
        component="inji-verify",
        order=0,
        suite_config={"provider": "injiverify", "suite_id": "smoke", "display_name": "x"},
    )
    result = executor.execute(step, make_context())

    assert result.status == ExecutionStatus.FAILED
    assert result.details["error_type"] == "missing_configuration"
    assert not dump_path.exists()


def test_missing_base_url_is_invalid_configuration(monkeypatch, tmp_path, fake_jar):
    # injiverify_config present, but without the one required Verify-specific
    # field. This exercises the field-level Pydantic requirement rather than
    # the block-level "missing_configuration" check.
    incomplete = {
        "test_level": "smoke",
        "env_user": "dev",
        "env_endpoint": "https://api-internal.dev.mosip.net",
        "inji_verify_base_url": "https://injiverify.dev.mosip.net",
    }
    # Simulate a legacy/corrupted stored record missing the required field
    # by constructing suite_config as a raw dict bypassing schema validation.
    step = Step(
        step_id="inji-verify:injiverify:smoke",
        display_name="Inji Verify API Test Rig",
        provider="injiverify",
        component="inji-verify",
        order=0,
        suite_config={
            "provider": "injiverify",
            "suite_id": "smoke",
            "display_name": "x",
            "injiverify_config": {**incomplete, "inji_verify_base_url": ""},
        },
    )
    executor, _ = make_executor(monkeypatch, tmp_path, scenario="pass")
    result = executor.execute(step, make_context())

    assert result.status == ExecutionStatus.FAILED
    assert result.details["error_type"] == "invalid_configuration"


def test_timeout_kills_process(monkeypatch, tmp_path, fake_jar):
    executor, _ = make_executor(
        monkeypatch, tmp_path, scenario="sleep", timeout=0.5, sleep_seconds=30
    )
    result = executor.execute(make_step(BASE_CONFIG), make_context())

    assert result.status == ExecutionStatus.FAILED
    assert result.details["error_type"] == "timeout"


def test_argument_construction_uses_injiverify_module(monkeypatch, tmp_path, fake_jar):
    executor, dump_path = make_executor(monkeypatch, tmp_path, scenario="pass")
    executor.execute(make_step(BASE_CONFIG), make_context())

    dumped = json.loads(dump_path.read_text())
    argv = dumped["argv"]
    assert "-Dmodules=injiverify" in argv
    assert argv[-1] == str(fake_jar)


def test_inji_verify_base_url_becomes_env_var(monkeypatch, tmp_path, fake_jar):
    executor, dump_path = make_executor(monkeypatch, tmp_path, scenario="pass")
    executor.execute(make_step(BASE_CONFIG), make_context())

    dumped = json.loads(dump_path.read_text())
    assert dumped["env"]["injiVerifyBaseUrl"] == "https://injiverify.dev.mosip.net"
    # Verify's config surface is deliberately narrow — no Certify-only keys
    # should ever leak into its environment.
    assert "injiCertifyBaseURL" not in dumped["env"]
    assert "useCaseToExecute" not in dumped["env"]


def test_smoke_and_regression_test_level(monkeypatch, tmp_path, fake_jar):
    config = {**BASE_CONFIG, "test_level": "smokeAndRegression"}
    executor, dump_path = make_executor(monkeypatch, tmp_path, scenario="pass")
    executor.execute(make_step(config), make_context())

    dumped = json.loads(dump_path.read_text())
    assert "-Denv.testLevel=smokeAndRegression" in dumped["argv"]


def test_jar_not_found_is_failed(monkeypatch, tmp_path):
    settings = InjiTestRigSettings(
        jar_path=str(tmp_path / "apitest-injiverify-*-jar-with-dependencies.jar"),
        working_directory=str(tmp_path),
        java_executable=FIXTURE_JAVA,
        timeout_seconds=10,
    )
    executor = VerifyApiTestRigExecutor(settings)
    result = executor.execute(make_step(BASE_CONFIG), make_context())

    assert result.status == ExecutionStatus.FAILED
    assert result.details["error_type"] == "jar_not_found"
