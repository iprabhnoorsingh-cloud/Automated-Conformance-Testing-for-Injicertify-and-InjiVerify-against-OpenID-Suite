"""Tests for OpenIDConformanceExecutor against a fake OpenIDConformanceClient
double (not the real HTTP client — that contract is covered separately in
test_openid_client.py). This isolates "does the executor correctly drive
the plan/module/wait/result flow" from "does the HTTP client correctly
speak the REST protocol".
"""

from app.executors import ExecutionContext
from app.openid_client import (
    OpenIDConformanceConnectionError,
    OpenIDConformanceNotFoundError,
)
from app.openid_executor import OpenIDConformanceExecutor
from app.orchestration import ExecutionStatus, Step


class FakeOpenIDConformanceClient:
    def __init__(self):
        self.plan_response = {"id": "plan-1"}
        self.module_response = {"id": "module-1"}
        self.wait_response = {"status": "FINISHED"}
        self.info_response = {"result": "PASSED"}
        self.start_test_error = None
        self.create_plan_calls = []
        self.create_test_calls = []

    def create_plan(self, plan_name, configuration):
        self.create_plan_calls.append((plan_name, configuration))
        return self.plan_response

    def create_test_from_plan(self, test, plan_id, variant=None):
        self.create_test_calls.append((test, plan_id, variant))
        return self.module_response

    def start_test(self, module_id):
        if self.start_test_error is not None:
            raise self.start_test_error
        return {}

    def wait_for_state(self, module_id, states, timeout_ms):
        return self.wait_response

    def get_test_info(self, module_id):
        return self.info_response

    def get_test_log(self, module_id):
        return []

    def export_plan_results(self, plan_id):
        return {}


def make_step(suite_config):
    return Step(
        step_id="inji-certify:openid:oidcc-basic",
        display_name="OpenID Basic — Inji Certify",
        provider="openid",
        component="inji-certify",
        order=0,
        suite_config=suite_config,
    )


def make_context():
    return ExecutionContext(
        test_run_id="run-1", execution_id="exec-1", environment="staging"
    )


OPENID_CONFIG = {
    "plan_name": "oidcc-basic-certification-test-plan",
    "plan_configuration": {"alias": "test-alias"},
    "modules": ["oidcc-basic-module"],
}


def test_missing_openid_configuration_fails_without_calling_client():
    client = FakeOpenIDConformanceClient()
    executor = OpenIDConformanceExecutor(client)
    step = make_step({"provider": "openid", "suite_id": "x", "display_name": "X"})

    result = executor.execute(step, make_context())

    assert result.status == ExecutionStatus.FAILED
    assert result.details["error_type"] == "missing_openid_configuration"
    assert client.create_plan_calls == []


def test_missing_plan_name_fails():
    client = FakeOpenIDConformanceClient()
    executor = OpenIDConformanceExecutor(client)
    step = make_step({"openid_config": {"plan_configuration": {}}})

    result = executor.execute(step, make_context())

    assert result.status == ExecutionStatus.FAILED
    assert result.details["error_type"] == "missing_openid_configuration"


def test_successful_execution_produces_passed_result():
    client = FakeOpenIDConformanceClient()
    executor = OpenIDConformanceExecutor(client)
    step = make_step({"openid_config": OPENID_CONFIG})

    result = executor.execute(step, make_context())

    assert result.status == ExecutionStatus.PASSED
    assert result.details["plan_id"] == "plan-1"
    assert result.details["modules"][0]["module_id"] == "module-1"
    assert result.details["modules"][0]["result"] == "PASSED"
    assert client.create_plan_calls == [
        ("oidcc-basic-certification-test-plan", {"alias": "test-alias"})
    ]
    assert client.create_test_calls == [("oidcc-basic-module", "plan-1", None)]


def test_failed_test_result_produces_failed_step():
    client = FakeOpenIDConformanceClient()
    client.info_response = {"result": "FAILED"}
    executor = OpenIDConformanceExecutor(client)
    step = make_step({"openid_config": OPENID_CONFIG})

    result = executor.execute(step, make_context())

    assert result.status == ExecutionStatus.FAILED
    assert result.details["modules"][0]["result"] == "FAILED"


def test_interrupted_state_maps_to_failed():
    client = FakeOpenIDConformanceClient()
    client.wait_response = {"status": "INTERRUPTED"}
    executor = OpenIDConformanceExecutor(client)
    step = make_step({"openid_config": OPENID_CONFIG})

    result = executor.execute(step, make_context())

    assert result.status == ExecutionStatus.FAILED
    assert result.details["modules"][0]["result"] == "FAILED"
    assert result.details["modules"][0]["external_state"] == "INTERRUPTED"


def test_non_terminal_wait_state_is_treated_as_failure_not_fabricated_pass():
    client = FakeOpenIDConformanceClient()
    client.wait_response = {"status": "WAITING"}
    executor = OpenIDConformanceExecutor(client)
    step = make_step({"openid_config": OPENID_CONFIG})

    result = executor.execute(step, make_context())

    assert result.status == ExecutionStatus.FAILED
    assert result.details["modules"][0]["result"] == "UNKNOWN"


def test_unrecognized_result_value_never_fabricates_pass():
    client = FakeOpenIDConformanceClient()
    client.info_response = {"result": "REVIEW"}
    executor = OpenIDConformanceExecutor(client)
    step = make_step({"openid_config": OPENID_CONFIG})

    result = executor.execute(step, make_context())

    assert result.status == ExecutionStatus.FAILED
    assert result.details["modules"][0]["result"] == "FAILED"


def test_start_test_404_is_tolerated_as_not_required():
    client = FakeOpenIDConformanceClient()
    client.start_test_error = OpenIDConformanceNotFoundError("no start needed")
    executor = OpenIDConformanceExecutor(client)
    step = make_step({"openid_config": OPENID_CONFIG})

    result = executor.execute(step, make_context())

    assert result.status == ExecutionStatus.PASSED


def test_connection_error_produces_structured_failure_not_a_crash():
    client = FakeOpenIDConformanceClient()

    def raise_connection_error(plan_name, configuration):
        raise OpenIDConformanceConnectionError("could not connect")

    client.create_plan = raise_connection_error
    executor = OpenIDConformanceExecutor(client)
    step = make_step({"openid_config": OPENID_CONFIG})

    result = executor.execute(step, make_context())

    assert result.status == ExecutionStatus.FAILED
    assert result.details["error_type"] == "connection_failed"


def test_no_modules_resolved_fails_with_clear_error():
    client = FakeOpenIDConformanceClient()
    client.plan_response = {"id": "plan-1"}  # no "modules" key at all
    executor = OpenIDConformanceExecutor(client)
    step = make_step(
        {
            "openid_config": {
                "plan_name": "oidcc-basic-certification-test-plan",
                "plan_configuration": {},
                # no explicit "modules" either
            }
        }
    )

    result = executor.execute(step, make_context())

    assert result.status == ExecutionStatus.FAILED
    assert result.details["error_type"] == "no_modules_resolved"


def test_modules_resolved_from_plan_response_when_not_explicit():
    client = FakeOpenIDConformanceClient()
    client.plan_response = {
        "id": "plan-1",
        "modules": [{"testModule": "resolved-module-a"}],
    }
    executor = OpenIDConformanceExecutor(client)
    step = make_step(
        {
            "openid_config": {
                "plan_name": "oidcc-basic-certification-test-plan",
                "plan_configuration": {},
            }
        }
    )

    result = executor.execute(step, make_context())

    assert result.status == ExecutionStatus.PASSED
    assert client.create_test_calls[0][0] == "resolved-module-a"


def test_no_fabricated_ids_details_only_reflect_client_responses():
    client = FakeOpenIDConformanceClient()
    client.plan_response = {"id": "real-plan-id-from-server"}
    client.module_response = {"id": "real-module-id-from-server"}
    executor = OpenIDConformanceExecutor(client)
    step = make_step({"openid_config": OPENID_CONFIG})

    result = executor.execute(step, make_context())

    assert result.details["plan_id"] == "real-plan-id-from-server"
    assert result.details["modules"][0]["module_id"] == "real-module-id-from-server"


def test_mock_executor_still_works_independent_of_openid_executor():
    from app.executors import MockTestStepExecutor

    mock_step = Step(
        step_id="inji-certify:mock:demo",
        display_name="Demo suite",
        provider="mock",
        component="inji-certify",
        order=0,
    )
    result = MockTestStepExecutor().execute(mock_step, make_context())
    assert result.status == ExecutionStatus.PASSED
