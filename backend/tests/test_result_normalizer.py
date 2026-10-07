"""Tests for app.result_normalizer (Milestone 6 — Unified Result Normalization).

All ``StepResult`` objects are built from the actual shapes that the four
executors produce — not invented ones.  The exact ``details`` structures are
verified from the executor source code and the existing M3–M5 unit tests:

mock (MockTestStepExecutor)
    details=None always.

openid (OpenIDConformanceExecutor)
    Success:   {"provider": "openid", "plan_name": "...", "plan_id": "...",
                "modules": [{"module_id": "...", "module_name": "...",
                             "external_state": "FINISHED", "result": "PASSED"|"FAILED"|"UNKNOWN"}]}
    Error:     above dict + "error_type": "<key>"

injicertify / injiverify (InjiApiTestRigExecutor subclasses)
    Report path: {"provider": "...", "test_rig": "...", "test_level": "...",
                  "process_exit_code": 0, "timed_out": False,
                  "tests_total": N, "tests_passed": N, "tests_failed": N,
                  "tests_skipped": N, "report_path": "...",
                  "report_file": "testng-results.xml", "failure_summary": [...]}
    Error path: above minus count/report keys + "error_type": "<key>"
                (timeout also adds "process_output_excerpt")
"""

from datetime import datetime, timezone
from typing import Optional

import pytest

from app.orchestration import ExecutionStatus, Step, StepResult
from app.result_normalizer import (
    InjiTestCounts,
    NormalizedStepResult,
    OpenIDModuleResult,
    normalization_failure_result,
    normalize_execution_results,
    normalize_step_result,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_LATER = datetime(2026, 1, 1, 12, 0, 5, tzinfo=timezone.utc)  # 5 seconds later


def _step(
    step_id: str = "inji-certify:mock:smoke",
    display_name: str = "Smoke Suite — Inji Certify",
    provider: str = "mock",
    component: str = "inji-certify",
    suite_config: Optional[dict] = None,
) -> Step:
    return Step(
        step_id=step_id,
        display_name=display_name,
        provider=provider,
        component=component,
        order=0,
        suite_config=suite_config or {
            "provider": provider,
            "suite_id": "smoke",
            "display_name": display_name,
        },
    )


def _result(
    step_id: str = "inji-certify:mock:smoke",
    status: ExecutionStatus = ExecutionStatus.PASSED,
    message: str = "ok",
    details: Optional[dict] = None,
    completed_at=_LATER,
) -> StepResult:
    return StepResult(
        step_id=step_id,
        status=status,
        started_at=_NOW,
        completed_at=completed_at,
        message=message,
        details=details,
    )


# ---------------------------------------------------------------------------
# 1. Mock executor — success
# ---------------------------------------------------------------------------


def test_mock_passed_normalization():
    """Mock executor always sets details=None; normalizer handles that safely."""
    step = _step(provider="mock")
    sr = _result(status=ExecutionStatus.PASSED, details=None)

    n = normalize_step_result(sr, step)

    assert isinstance(n, NormalizedStepResult)
    assert n.status == ExecutionStatus.PASSED
    assert n.provider == "mock"
    assert n.component == "inji-certify"
    assert n.suite_id == "smoke"
    assert n.display_name == "Smoke Suite — Inji Certify"
    assert n.inji_test_counts is None
    assert n.openid_modules is None
    assert n.openid_plan_id is None
    assert n.error_type is None
    assert n.source_details is None


def test_mock_failed_normalization():
    """Mock FAILED step (contains 'fail' in id) normalizes correctly."""
    step = _step(
        step_id="inji-certify:mock:will-fail",
        display_name="Will Fail Suite",
        provider="mock",
    )
    sr = _result(
        step_id="inji-certify:mock:will-fail",
        status=ExecutionStatus.FAILED,
        message="Mock executor: step 'Will Fail Suite' deterministically failed.",
        details=None,
    )

    n = normalize_step_result(sr, step)

    assert n.status == ExecutionStatus.FAILED
    assert n.error_type is None   # mock never sets error_type
    assert n.inji_test_counts is None


# ---------------------------------------------------------------------------
# 2. OpenID executor — success
# ---------------------------------------------------------------------------


_OPENID_SUCCESS_DETAILS = {
    "provider": "openid",
    "plan_name": "oidcc-basic-certification-test-plan",
    "plan_id": "plan-abc123",
    "modules": [
        {
            "module_id": "module-xyz",
            "module_name": "oidcc-basic-module",
            "external_state": "FINISHED",
            "result": "PASSED",
        }
    ],
}


def test_openid_passed_normalization():
    step = _step(
        step_id="inji-certify:openid:oidcc-basic",
        display_name="OpenID Basic — Inji Certify",
        provider="openid",
        suite_config={
            "provider": "openid",
            "suite_id": "oidcc-basic",
            "display_name": "OpenID Basic — Inji Certify",
        },
    )
    sr = _result(
        step_id="inji-certify:openid:oidcc-basic",
        status=ExecutionStatus.PASSED,
        message="OpenID Conformance plan 'oidcc-basic-certification-test-plan' (plan-abc123): 1 module(s) executed, overall PASSED.",
        details=_OPENID_SUCCESS_DETAILS,
    )

    n = normalize_step_result(sr, step)

    assert n.status == ExecutionStatus.PASSED
    assert n.provider == "openid"
    assert n.openid_plan_id == "plan-abc123"
    assert n.openid_plan_name == "oidcc-basic-certification-test-plan"
    assert n.openid_modules is not None
    assert len(n.openid_modules) == 1
    mod = n.openid_modules[0]
    assert isinstance(mod, OpenIDModuleResult)
    assert mod.module_id == "module-xyz"
    assert mod.module_name == "oidcc-basic-module"
    assert mod.external_state == "FINISHED"
    assert mod.result == "PASSED"
    assert n.inji_test_counts is None
    assert n.error_type is None


# ---------------------------------------------------------------------------
# 3. OpenID executor — failure
# ---------------------------------------------------------------------------


def test_openid_failed_module_result():
    details = {
        "provider": "openid",
        "plan_name": "oidcc-basic-certification-test-plan",
        "plan_id": "plan-abc123",
        "modules": [
            {
                "module_id": "module-xyz",
                "module_name": "oidcc-basic-module",
                "external_state": "FINISHED",
                "result": "FAILED",
            }
        ],
    }
    step = _step(
        step_id="inji-certify:openid:oidcc-basic",
        provider="openid",
    )
    sr = _result(step_id="inji-certify:openid:oidcc-basic", status=ExecutionStatus.FAILED, details=details)

    n = normalize_step_result(sr, step)

    assert n.status == ExecutionStatus.FAILED
    assert n.openid_modules[0].result == "FAILED"
    assert n.error_type is None  # module failure ≠ configuration error


def test_openid_missing_config_error():
    details = {
        "provider": "openid",
        "error_type": "missing_openid_configuration",
    }
    step = _step(
        step_id="inji-certify:openid:no-config",
        provider="openid",
    )
    sr = _result(step_id="inji-certify:openid:no-config", status=ExecutionStatus.FAILED, details=details)

    n = normalize_step_result(sr, step)

    assert n.status == ExecutionStatus.FAILED
    assert n.error_type == "missing_openid_configuration"
    assert n.openid_plan_id is None
    assert n.openid_modules is None  # never reached the plan phase


def test_openid_interrupted_state_normalizes():
    details = {
        "provider": "openid",
        "plan_name": "oidcc-basic-certification-test-plan",
        "plan_id": "plan-abc123",
        "modules": [
            {
                "module_id": "module-xyz",
                "module_name": "oidcc-basic-module",
                "external_state": "INTERRUPTED",
                "result": "FAILED",
            }
        ],
    }
    step = _step(step_id="inji-certify:openid:oidcc-basic", provider="openid")
    sr = _result(step_id="inji-certify:openid:oidcc-basic", status=ExecutionStatus.FAILED, details=details)

    n = normalize_step_result(sr, step)

    assert n.status == ExecutionStatus.FAILED
    assert n.openid_modules[0].external_state == "INTERRUPTED"


def test_openid_connection_error_type():
    details = {"provider": "openid", "error_type": "connection_failed"}
    step = _step(step_id="inji-certify:openid:x", provider="openid")
    sr = _result(step_id="inji-certify:openid:x", status=ExecutionStatus.FAILED, details=details)

    n = normalize_step_result(sr, step)

    assert n.error_type == "connection_failed"
    assert n.openid_modules is None


# ---------------------------------------------------------------------------
# 4. Inji Certify executor — success
# ---------------------------------------------------------------------------


_CERTIFY_SUCCESS_DETAILS = {
    "provider": "injicertify",
    "test_rig": "injicertify-api-test-rig",
    "test_level": "smoke",
    "process_exit_code": 0,
    "timed_out": False,
    "tests_total": 2,
    "tests_passed": 2,
    "tests_failed": 0,
    "tests_skipped": 0,
    "report_path": "/tmp/workdir/testng-report/testng-results.xml",
    "report_file": "testng-results.xml",
    "failure_summary": [],
}


def test_inji_certify_passed_normalization():
    step = _step(
        step_id="inji-certify:injicertify:smoke",
        display_name="Inji Certify API Test Rig",
        provider="injicertify",
        suite_config={
            "provider": "injicertify",
            "suite_id": "smoke",
            "display_name": "Inji Certify API Test Rig",
        },
    )
    sr = _result(
        step_id="inji-certify:injicertify:smoke",
        status=ExecutionStatus.PASSED,
        message="injicertify test rig: 2/2 passed, 0 failed, 0 skipped.",
        details=_CERTIFY_SUCCESS_DETAILS,
    )

    n = normalize_step_result(sr, step)

    assert n.status == ExecutionStatus.PASSED
    assert n.provider == "injicertify"
    assert n.component == "inji-certify"
    assert n.suite_id == "smoke"
    assert n.inji_test_counts is not None
    assert isinstance(n.inji_test_counts, InjiTestCounts)
    assert n.inji_test_counts.total == 2
    assert n.inji_test_counts.passed == 2
    assert n.inji_test_counts.failed == 0
    assert n.inji_test_counts.skipped == 0
    assert n.inji_test_counts.failure_summary == []
    assert n.openid_plan_id is None
    assert n.openid_modules is None
    assert n.error_type is None


# ---------------------------------------------------------------------------
# 5. Inji Certify executor — failure (failing report)
# ---------------------------------------------------------------------------


def test_inji_certify_failed_normalization():
    details = {
        **_CERTIFY_SUCCESS_DETAILS,
        "tests_passed": 1,
        "tests_failed": 1,
        "failure_summary": ["c.Test.testA"],
    }
    step = _step(step_id="inji-certify:injicertify:smoke", provider="injicertify")
    sr = _result(
        step_id="inji-certify:injicertify:smoke",
        status=ExecutionStatus.FAILED,
        message="injicertify test rig: 1/2 passed, 1 failed, 0 skipped.",
        details=details,
    )

    n = normalize_step_result(sr, step)

    assert n.status == ExecutionStatus.FAILED
    assert n.inji_test_counts is not None
    assert n.inji_test_counts.failed == 1
    assert n.inji_test_counts.failure_summary == ["c.Test.testA"]
    assert n.error_type is None  # it's a test failure, not a configuration error


# ---------------------------------------------------------------------------
# 6. Inji Verify executor — success
# ---------------------------------------------------------------------------


_VERIFY_SUCCESS_DETAILS = {
    "provider": "injiverify",
    "test_rig": "injiverify-api-test-rig",
    "test_level": "smoke",
    "process_exit_code": 0,
    "timed_out": False,
    "tests_total": 2,
    "tests_passed": 2,
    "tests_failed": 0,
    "tests_skipped": 0,
    "report_path": "/tmp/workdir/testng-report/testng-results.xml",
    "report_file": "testng-results.xml",
    "failure_summary": [],
}


def test_inji_verify_passed_normalization():
    step = _step(
        step_id="inji-verify:injiverify:smoke",
        display_name="Inji Verify API Test Rig",
        provider="injiverify",
        component="inji-verify",
        suite_config={
            "provider": "injiverify",
            "suite_id": "smoke",
            "display_name": "Inji Verify API Test Rig",
        },
    )
    sr = _result(
        step_id="inji-verify:injiverify:smoke",
        status=ExecutionStatus.PASSED,
        message="injiverify test rig: 2/2 passed, 0 failed, 0 skipped.",
        details=_VERIFY_SUCCESS_DETAILS,
    )

    n = normalize_step_result(sr, step)

    assert n.status == ExecutionStatus.PASSED
    assert n.provider == "injiverify"
    assert n.component == "inji-verify"
    assert n.inji_test_counts is not None
    assert n.inji_test_counts.total == 2
    assert n.inji_test_counts.passed == 2


# ---------------------------------------------------------------------------
# 7. Inji Verify executor — failure
# ---------------------------------------------------------------------------


def test_inji_verify_failed_normalization():
    details = {
        **_VERIFY_SUCCESS_DETAILS,
        "tests_passed": 1,
        "tests_failed": 1,
        "failure_summary": ["com.example.VerifyTest.testCredential"],
    }
    step = _step(
        step_id="inji-verify:injiverify:smoke",
        provider="injiverify",
        component="inji-verify",
    )
    sr = _result(
        step_id="inji-verify:injiverify:smoke",
        status=ExecutionStatus.FAILED,
        details=details,
    )

    n = normalize_step_result(sr, step)

    assert n.status == ExecutionStatus.FAILED
    assert n.inji_test_counts.failed == 1
    assert n.inji_test_counts.failure_summary == ["com.example.VerifyTest.testCredential"]


# ---------------------------------------------------------------------------
# 8. Missing optional details (error paths that don't populate all keys)
# ---------------------------------------------------------------------------


def test_inji_certify_report_not_found_error_path():
    """When the report is not found, count keys are absent — inji_test_counts is None."""
    details = {
        "provider": "injicertify",
        "test_rig": "injicertify-api-test-rig",
        "test_level": "smoke",
        "process_exit_code": 0,
        "timed_out": False,
        "error_type": "report_not_found",
        "process_output_excerpt": "... (stdout excerpt) ...",
    }
    step = _step(step_id="inji-certify:injicertify:smoke", provider="injicertify")
    sr = _result(step_id="inji-certify:injicertify:smoke", status=ExecutionStatus.FAILED, details=details)

    n = normalize_step_result(sr, step)

    assert n.status == ExecutionStatus.FAILED
    assert n.error_type == "report_not_found"
    assert n.inji_test_counts is None  # no count keys present


def test_inji_certify_timeout_error_path():
    """Timeout path: timed_out=True, no count keys, has process_output_excerpt."""
    details = {
        "provider": "injicertify",
        "test_rig": "injicertify-api-test-rig",
        "test_level": "smoke",
        "process_exit_code": None,
        "timed_out": True,
        "error_type": "timeout",
        "process_output_excerpt": "... last 4000 chars ...",
    }
    step = _step(step_id="inji-certify:injicertify:smoke", provider="injicertify")
    sr = _result(step_id="inji-certify:injicertify:smoke", status=ExecutionStatus.FAILED, details=details)

    n = normalize_step_result(sr, step)

    assert n.status == ExecutionStatus.FAILED
    assert n.error_type == "timeout"
    assert n.inji_test_counts is None
    # source_details must preserve the process_output_excerpt
    assert n.source_details is not None
    assert "process_output_excerpt" in n.source_details


# ---------------------------------------------------------------------------
# 9. Partial details (only some keys present)
# ---------------------------------------------------------------------------


def test_partial_openid_details_no_modules_key():
    """OpenID error path before plan_id is obtained: no plan_id, no modules."""
    details = {
        "provider": "openid",
        "error_type": "no_modules_resolved",
        "plan_name": "some-plan",
        "plan_id": "plan-123",
    }
    step = _step(provider="openid")
    sr = _result(status=ExecutionStatus.FAILED, details=details)

    n = normalize_step_result(sr, step)

    assert n.openid_plan_id == "plan-123"
    assert n.openid_modules is None  # key absent from details
    assert n.error_type == "no_modules_resolved"


def test_openid_modules_list_with_malformed_entries_skipped():
    """Malformed entries in modules list are silently skipped, valid ones kept."""
    details = {
        "provider": "openid",
        "plan_name": "some-plan",
        "plan_id": "plan-123",
        "modules": [
            "not-a-dict",  # malformed — skipped
            {
                "module_id": "m1",
                "module_name": "mod-a",
                "external_state": "FINISHED",
                "result": "PASSED",
            },
        ],
    }
    step = _step(provider="openid")
    sr = _result(status=ExecutionStatus.PASSED, details=details)

    n = normalize_step_result(sr, step)

    assert n.openid_modules is not None
    assert len(n.openid_modules) == 1
    assert n.openid_modules[0].module_id == "m1"


# ---------------------------------------------------------------------------
# 10. Unknown / unrecognised status values
# ---------------------------------------------------------------------------


def test_unknown_provider_error_result():
    """Orchestrator-level unknown_provider error (no real executor ran)."""
    details = {
        "error_type": "unknown_provider",
        "provider": "does-not-exist",
    }
    step = _step(
        step_id="inji-certify:does-not-exist:x",
        provider="does-not-exist",
    )
    sr = _result(
        step_id="inji-certify:does-not-exist:x",
        status=ExecutionStatus.FAILED,
        details=details,
    )

    n = normalize_step_result(sr, step)

    assert n.status == ExecutionStatus.FAILED
    assert n.error_type == "unknown_provider"
    assert n.provider == "does-not-exist"
    assert n.inji_test_counts is None
    assert n.openid_modules is None


def test_queued_status_preserved():
    """A step that never ran is QUEUED — status is preserved verbatim."""
    step = _step(provider="mock")
    sr = _result(status=ExecutionStatus.QUEUED, details=None, completed_at=None)

    n = normalize_step_result(sr, step)

    assert n.status == ExecutionStatus.QUEUED
    assert n.duration_seconds is None  # no completed_at


# ---------------------------------------------------------------------------
# 11. Empty / null details
# ---------------------------------------------------------------------------


def test_empty_dict_details():
    """details={} (e.g. from internal_executor_error path) handled safely."""
    step = _step(provider="mock")
    sr = _result(status=ExecutionStatus.FAILED, details={})

    n = normalize_step_result(sr, step)

    assert n.status == ExecutionStatus.FAILED
    assert n.error_type is None
    assert n.inji_test_counts is None
    assert n.openid_modules is None
    assert n.source_details is None  # empty dict treated as absent


def test_none_details():
    """details=None is identical to details={}."""
    step = _step(provider="mock")
    sr = _result(status=ExecutionStatus.PASSED, details=None)

    n = normalize_step_result(sr, step)

    assert n.source_details is None
    assert n.error_type is None


# ---------------------------------------------------------------------------
# 12. Preservation of source-specific metadata
# ---------------------------------------------------------------------------


def test_source_details_preserves_all_original_keys():
    """Every key in the original details dict must appear in source_details."""
    step = _step(provider="injicertify")
    sr = _result(
        status=ExecutionStatus.PASSED,
        details=_CERTIFY_SUCCESS_DETAILS,
    )

    n = normalize_step_result(sr, step)

    assert n.source_details is not None
    for key in _CERTIFY_SUCCESS_DETAILS:
        assert key in n.source_details, f"source_details missing key: {key}"


def test_source_details_preserves_process_output_excerpt():
    """Timeout results include process_output_excerpt — preserved in source_details."""
    details = {
        "provider": "injicertify",
        "test_rig": "injicertify-api-test-rig",
        "test_level": "smoke",
        "process_exit_code": None,
        "timed_out": True,
        "error_type": "timeout",
        "process_output_excerpt": "Timeout output here",
    }
    step = _step(provider="injicertify")
    sr = _result(status=ExecutionStatus.FAILED, details=details)

    n = normalize_step_result(sr, step)

    assert n.source_details["process_output_excerpt"] == "Timeout output here"


def test_openid_source_details_preserves_modules():
    """OpenID module list is accessible from source_details as well as openid_modules."""
    step = _step(provider="openid")
    sr = _result(status=ExecutionStatus.PASSED, details=_OPENID_SUCCESS_DETAILS)

    n = normalize_step_result(sr, step)

    # Typed access
    assert n.openid_modules[0].module_id == "module-xyz"
    # Raw access via source_details
    assert n.source_details["modules"][0]["module_id"] == "module-xyz"


# ---------------------------------------------------------------------------
# 13. Deterministic normalization (same input → same output, twice)
# ---------------------------------------------------------------------------


def test_normalization_is_deterministic():
    """Calling normalize_step_result twice with the same inputs returns
    equivalent results — no randomness, no mutable state."""
    step = _step(provider="injicertify")
    sr = _result(status=ExecutionStatus.PASSED, details=_CERTIFY_SUCCESS_DETAILS)

    n1 = normalize_step_result(sr, step)
    n2 = normalize_step_result(sr, step)

    assert n1.model_dump() == n2.model_dump()


# ---------------------------------------------------------------------------
# 14. Timing / duration computation
# ---------------------------------------------------------------------------


def test_duration_computed_from_timestamps():
    step = _step()
    sr = _result(completed_at=_LATER)  # 5 seconds after _NOW

    n = normalize_step_result(sr, step)

    assert n.duration_seconds == 5.0


def test_duration_none_when_no_completed_at():
    step = _step()
    sr = _result(completed_at=None)

    n = normalize_step_result(sr, step)

    assert n.duration_seconds is None


# ---------------------------------------------------------------------------
# 15. Suite ID extraction from suite_config
# ---------------------------------------------------------------------------


def test_suite_id_extracted_from_suite_config():
    step = _step(
        suite_config={
            "provider": "mock",
            "suite_id": "my-suite-123",
            "display_name": "My Suite",
        }
    )
    sr = _result()

    n = normalize_step_result(sr, step)

    assert n.suite_id == "my-suite-123"


def test_suite_id_none_when_suite_config_absent():
    step = Step(
        step_id="inji-certify:mock:smoke",
        display_name="Smoke",
        provider="mock",
        component="inji-certify",
        order=0,
        suite_config=None,
    )
    sr = _result()

    n = normalize_step_result(sr, step)

    assert n.suite_id is None


# ---------------------------------------------------------------------------
# 16. normalize_execution_results — batch normalization
# ---------------------------------------------------------------------------


def test_normalize_execution_results_matches_by_step_id():
    """normalize_execution_results correctly matches results to steps by step_id."""
    steps = [
        _step(
            step_id="inji-certify:mock:a",
            display_name="Suite A",
            provider="mock",
        ),
        _step(
            step_id="inji-certify:mock:b",
            display_name="Suite B",
            provider="mock",
        ),
    ]
    step_results = [
        _result(step_id="inji-certify:mock:a", status=ExecutionStatus.PASSED),
        _result(step_id="inji-certify:mock:b", status=ExecutionStatus.FAILED),
    ]

    normalized = normalize_execution_results(step_results, steps)

    assert len(normalized) == 2
    assert normalized[0].step_id == "inji-certify:mock:a"
    assert normalized[0].status == ExecutionStatus.PASSED
    assert normalized[0].display_name == "Suite A"
    assert normalized[1].step_id == "inji-certify:mock:b"
    assert normalized[1].status == ExecutionStatus.FAILED


def test_normalize_execution_results_only_executed_steps():
    """Steps never reached (fail-fast) produce no StepResult, so they are absent
    from the normalized list — not padded with placeholder entries."""
    steps = [
        _step(step_id="inji-certify:mock:a", provider="mock"),
        _step(step_id="inji-certify:mock:b", provider="mock"),
    ]
    step_results = [
        _result(step_id="inji-certify:mock:a", status=ExecutionStatus.FAILED),
        # step b never executed
    ]

    normalized = normalize_execution_results(step_results, steps)

    assert len(normalized) == 1
    assert normalized[0].step_id == "inji-certify:mock:a"


def test_normalize_execution_results_no_crash_on_unmatched_result():
    """A result with no matching plan step falls back to _synthesize_step —
    never raises."""
    steps: list = []
    step_results = [_result(step_id="orphan:mock:x", status=ExecutionStatus.FAILED)]

    normalized = normalize_execution_results(step_results, steps)

    assert len(normalized) == 1
    assert normalized[0].step_id == "orphan:mock:x"


# ---------------------------------------------------------------------------
# 17. Inji multiple skipped tests (skipped ≠ passed)
# ---------------------------------------------------------------------------


def test_inji_all_skipped_report_is_not_a_pass_in_counts():
    """All-skipped TestNG output: passed=0, failed=0, skipped=N.
    The normalizer faithfully records what the report says.
    (The actual pass/fail decision was made by the executor before this runs.)
    """
    details = {
        "provider": "injicertify",
        "test_rig": "injicertify-api-test-rig",
        "test_level": "smoke",
        "process_exit_code": 0,
        "timed_out": False,
        "tests_total": 5,
        "tests_passed": 0,
        "tests_failed": 0,
        "tests_skipped": 5,
        "report_path": "/tmp/testng-results.xml",
        "report_file": "testng-results.xml",
        "failure_summary": [],
    }
    step = _step(provider="injicertify")
    sr = _result(status=ExecutionStatus.FAILED, details=details)

    n = normalize_step_result(sr, step)

    assert n.inji_test_counts is not None
    assert n.inji_test_counts.passed == 0
    assert n.inji_test_counts.skipped == 5
    assert n.inji_test_counts.failed == 0


# ---------------------------------------------------------------------------
# 18. OpenID multi-module step
# ---------------------------------------------------------------------------


def test_openid_multi_module_step_all_modules_normalized():
    details = {
        "provider": "openid",
        "plan_name": "oidcc-full-plan",
        "plan_id": "plan-multi",
        "modules": [
            {"module_id": "m1", "module_name": "mod-a", "external_state": "FINISHED", "result": "PASSED"},
            {"module_id": "m2", "module_name": "mod-b", "external_state": "FINISHED", "result": "FAILED"},
            {"module_id": "m3", "module_name": "mod-c", "external_state": "INTERRUPTED", "result": "FAILED"},
        ],
    }
    step = _step(provider="openid")
    sr = _result(status=ExecutionStatus.FAILED, details=details)

    n = normalize_step_result(sr, step)

    assert n.openid_modules is not None
    assert len(n.openid_modules) == 3
    assert n.openid_modules[0].result == "PASSED"
    assert n.openid_modules[1].result == "FAILED"
    assert n.openid_modules[2].external_state == "INTERRUPTED"


# ---------------------------------------------------------------------------
# 19. Inji missing_configuration error path (no process ran)
# ---------------------------------------------------------------------------


def test_inji_missing_configuration_error_path():
    """missing_configuration error: process was never started, no count keys."""
    details = {
        "provider": "injicertify",
        "error_type": "missing_configuration",
    }
    step = _step(provider="injicertify")
    sr = _result(status=ExecutionStatus.FAILED, details=details)

    n = normalize_step_result(sr, step)

    assert n.status == ExecutionStatus.FAILED
    assert n.error_type == "missing_configuration"
    assert n.inji_test_counts is None


# ---------------------------------------------------------------------------
# 20. Provider sourced from step (not details) when details lacks 'provider'
# ---------------------------------------------------------------------------


def test_provider_falls_back_to_step_provider():
    """When details has no 'provider' key (e.g. mock), step.provider is used."""
    step = _step(provider="mock")
    sr = _result(details=None)   # mock never sets details

    n = normalize_step_result(sr, step)

    assert n.provider == "mock"


def test_provider_from_details_overrides_step_when_present():
    """Matching provider details do not change the step's canonical provider."""
    step = _step(provider="openid")
    # details.provider matches step.provider — confirm it's used
    sr = _result(details={"provider": "openid", "error_type": "connection_failed"})

    n = normalize_step_result(sr, step)

    assert n.provider == "openid"


def test_conflicting_details_provider_does_not_change_openid_parsing():
    step = _step(provider="openid")
    details = {
        **_OPENID_SUCCESS_DETAILS,
        "provider": "injicertify",
    }

    n = normalize_step_result(_result(details=details), step)

    assert n.provider == "openid"
    assert n.openid_plan_id == "plan-abc123"
    assert n.openid_modules is not None
    assert n.inji_test_counts is None
    assert n.provider_mismatch is not None
    assert n.source_details["provider"] == "injicertify"


def test_conflicting_details_provider_does_not_change_inji_parsing():
    step = _step(provider="injicertify")
    details = {**_CERTIFY_SUCCESS_DETAILS, "provider": "openid"}

    n = normalize_step_result(_result(details=details), step)

    assert n.provider == "injicertify"
    assert n.inji_test_counts is not None
    assert n.openid_modules is None
    assert n.provider_mismatch is not None


def test_normalization_failure_result_preserves_raw_result_and_identity():
    step = _step(provider="mock")
    raw = _result(status=ExecutionStatus.PASSED)

    fallback = normalization_failure_result(raw, step, RuntimeError("boom"))

    assert fallback.status == ExecutionStatus.FAILED
    assert fallback.error_type == "normalization_failed"
    assert fallback.normalization_error == "RuntimeError"
    assert fallback.step_id == raw.step_id
    assert fallback.provider == step.provider
    assert fallback.raw_result == raw
