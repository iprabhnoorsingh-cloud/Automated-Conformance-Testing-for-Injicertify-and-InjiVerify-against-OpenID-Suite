"""Opt-in smoke test that runs a REAL Inji API Test-Rig JAR.

This NEVER runs as part of the normal `pytest` invocation. It requires:
- INJI_TEST_RIG_INTEGRATION=1
- INJI_CERTIFY_TEST_RIG_JAR / INJI_CERTIFY_TEST_RIG_WORKDIR (or the Verify
  equivalents) pointing at an actually-built api-test module — i.e. a real
  local clone of inji-certify or inji-verify, built with Maven per its own
  README (Java 21, Maven, apitest-commons, settings.xml).

Run explicitly with, e.g.:

    INJI_TEST_RIG_INTEGRATION=1 \\
    INJI_CERTIFY_TEST_RIG_JAR=/path/to/inji-certify/api-test/target/apitest-injicertify-*-jar-with-dependencies.jar \\
    INJI_CERTIFY_TEST_RIG_WORKDIR=/path/to/inji-certify/api-test/target \\
    pytest tests/test_inji_testrig_integration.py -q

This is a smoke test only — it proves the process actually launches, waits,
and produces a parseable report; it does not assert PASSED, since that
depends entirely on a real target Inji deployment being reachable.
"""

import os

import pytest

from app.executors import ExecutionContext
from app.inji_executors import CertifyApiTestRigExecutor, InjiTestRigSettings
from app.orchestration import Step

INTEGRATION_ENABLED = os.environ.get("INJI_TEST_RIG_INTEGRATION") == "1"

pytestmark = pytest.mark.skipif(
    not INTEGRATION_ENABLED,
    reason=(
        "Opt-in only: set INJI_TEST_RIG_INTEGRATION=1 and point "
        "INJI_CERTIFY_TEST_RIG_JAR/WORKDIR at a real built api-test module "
        "to run this against a real Inji Certify Test Rig."
    ),
)


def test_real_certify_test_rig_process_launches_and_produces_a_report():
    jar = os.environ.get("INJI_CERTIFY_TEST_RIG_JAR")
    workdir = os.environ.get("INJI_CERTIFY_TEST_RIG_WORKDIR")
    if not jar or not workdir:
        pytest.skip("INJI_CERTIFY_TEST_RIG_JAR / INJI_CERTIFY_TEST_RIG_WORKDIR not set")

    settings = InjiTestRigSettings(
        jar_path=jar,
        working_directory=workdir,
        java_executable=os.environ.get("INJI_TEST_RIG_JAVA", "java"),
        timeout_seconds=float(os.environ.get("INJI_TEST_RIG_TIMEOUT", "1800")),
    )
    executor = CertifyApiTestRigExecutor(settings)

    step = Step(
        step_id="integration:injicertify:mock",
        display_name="Inji Certify API Test Rig (live smoke)",
        provider="injicertify",
        component="inji-certify",
        order=0,
        suite_config={
            "provider": "injicertify",
            "suite_id": "mock",
            "display_name": "Inji Certify API Test Rig (live smoke)",
            "injicertify_config": {
                "test_level": "smoke",
                "env_user": os.environ.get("INJI_TEST_ENV_USER", "dev"),
                "env_endpoint": os.environ.get(
                    "INJI_TEST_ENV_ENDPOINT", "https://api-internal.dev.mosip.net"
                ),
                "use_case_to_execute": "mock",
            },
        },
    )
    context = ExecutionContext(
        test_run_id="integration", execution_id="integration", environment="staging"
    )

    result = executor.execute(step, context)

    # Only assert the process actually ran and produced evidence — not a
    # particular pass/fail outcome, which depends on the real environment.
    assert result.details.get("error_type") not in {
        "test_rig_not_configured",
        "jar_not_found",
        "invalid_working_directory",
        "process_start_failed",
    }
    assert "process_exit_code" in result.details
