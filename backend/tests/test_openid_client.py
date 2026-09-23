"""Tests for OpenIDConformanceClient against a mocked HTTP transport.

These never touch a real network or certification.openid.net — httpx's
built-in MockTransport intercepts every request and returns a canned
response, so the suite stays fully offline and deterministic.
"""

import json

import httpx
import pytest

from app.openid_client import (
    OpenIDConformanceAuthError,
    OpenIDConformanceBadRequestError,
    OpenIDConformanceClient,
    OpenIDConformanceConfigurationError,
    OpenIDConformanceConnectionError,
    OpenIDConformanceNotFoundError,
    OpenIDConformanceResponseError,
    OpenIDConformanceServerError,
    OpenIDConformanceTimeoutError,
)

BASE_URL = "https://conformance.example.test"


def make_client(handler, **kwargs):
    transport = httpx.MockTransport(handler)
    return OpenIDConformanceClient(
        base_url=BASE_URL, transport=transport, timeout=1.0, **kwargs
    )


def json_response(status_code, payload):
    return httpx.Response(status_code, json=payload)


# --- individual API methods ------------------------------------------------


def test_get_available_modules():
    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/api/runner/available"
        return json_response(200, {"oidcc-basic-certification-test-plan": {}})

    client = make_client(handler)
    result = client.get_available_modules()
    assert "oidcc-basic-certification-test-plan" in result


def test_create_plan_sends_query_param_and_json_body():
    captured = {}

    def handler(request):
        captured["query"] = dict(request.url.params)
        captured["body"] = json.loads(request.content)
        return json_response(201, {"id": "plan-123"})

    client = make_client(handler)
    result = client.create_plan("oidcc-basic-certification-test-plan", {"foo": "bar"})

    assert result["id"] == "plan-123"
    assert captured["query"]["planName"] == "oidcc-basic-certification-test-plan"
    assert captured["body"] == {"foo": "bar"}


def test_create_plan_missing_id_raises_response_error():
    def handler(request):
        return json_response(201, {"no_id_here": True})

    client = make_client(handler)
    with pytest.raises(OpenIDConformanceResponseError):
        client.create_plan("some-plan", {})


def test_create_test_from_plan_sends_test_and_plan_params():
    captured = {}

    def handler(request):
        captured["query"] = dict(request.url.params)
        return json_response(201, {"id": "module-456"})

    client = make_client(handler)
    result = client.create_test_from_plan("some-module", "plan-123")

    assert result["id"] == "module-456"
    assert captured["query"]["test"] == "some-module"
    assert captured["query"]["plan"] == "plan-123"
    assert "variant" not in captured["query"]


def test_create_test_from_plan_encodes_variant_as_json():
    captured = {}

    def handler(request):
        captured["query"] = dict(request.url.params)
        return json_response(201, {"id": "module-456"})

    client = make_client(handler)
    client.create_test_from_plan("some-module", "plan-123", variant={"client_auth_type": "private_key_jwt"})

    assert json.loads(captured["query"]["variant"]) == {
        "client_auth_type": "private_key_jwt"
    }


def test_start_test():
    def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/api/runner/module-456"
        return json_response(200, {"ok": True})

    client = make_client(handler)
    result = client.start_test("module-456")
    assert result == {"ok": True}


def test_wait_for_state_sends_states_and_timeout():
    captured = {}

    def handler(request):
        captured["query"] = dict(request.url.params)
        return json_response(200, {"status": "FINISHED"})

    client = make_client(handler)
    result = client.wait_for_state("module-456", states=["FINISHED", "INTERRUPTED"], timeout_ms=5000)

    assert result["status"] == "FINISHED"
    assert captured["query"]["states"] == "FINISHED,INTERRUPTED"
    assert captured["query"]["timeoutMs"] == "5000"


def test_get_test_info():
    def handler(request):
        assert request.url.path == "/api/info/module-456"
        return json_response(200, {"result": "PASSED"})

    client = make_client(handler)
    assert client.get_test_info("module-456")["result"] == "PASSED"


def test_get_test_log():
    def handler(request):
        assert request.url.path == "/api/log/module-456"
        return json_response(200, [{"msg": "did a thing"}])

    client = make_client(handler)
    result = client.get_test_log("module-456")
    assert result == [{"msg": "did a thing"}]


def test_export_plan_results():
    def handler(request):
        assert request.url.path == "/api/plan/plan-123/export"
        return json_response(200, {"plan": "plan-123", "results": []})

    client = make_client(handler)
    result = client.export_plan_results("plan-123")
    assert result["plan"] == "plan-123"


# --- authentication ----------------------------------------------------


def test_bearer_token_is_sent_when_configured():
    captured = {}

    def handler(request):
        captured["auth"] = request.headers.get("authorization")
        return json_response(200, {})

    transport = httpx.MockTransport(handler)
    client = OpenIDConformanceClient(
        base_url=BASE_URL, api_token="secret-token-value", transport=transport
    )
    client.get_available_modules()

    assert captured["auth"] == "Bearer secret-token-value"


def test_no_authorization_header_when_no_token_configured():
    captured = {}

    def handler(request):
        captured["auth"] = request.headers.get("authorization")
        return json_response(200, {})

    client = make_client(handler)
    client.get_available_modules()

    assert captured["auth"] is None


# --- error handling ------------------------------------------------------


def test_http_401_raises_auth_error():
    def handler(request):
        return httpx.Response(401, json={"error": "unauthorized"})

    client = make_client(handler)
    with pytest.raises(OpenIDConformanceAuthError):
        client.get_available_modules()


def test_http_404_raises_not_found_error():
    def handler(request):
        return httpx.Response(404, json={"error": "not found"})

    client = make_client(handler)
    with pytest.raises(OpenIDConformanceNotFoundError):
        client.get_test_info("missing-module")


def test_http_400_raises_bad_request_error():
    def handler(request):
        return httpx.Response(400, json={"error": "bad config"})

    client = make_client(handler)
    with pytest.raises(OpenIDConformanceBadRequestError):
        client.create_plan("bad-plan", {})


def test_http_5xx_raises_server_error():
    def handler(request):
        return httpx.Response(503, text="service unavailable")

    client = make_client(handler)
    with pytest.raises(OpenIDConformanceServerError):
        client.get_available_modules()


def test_timeout_raises_timeout_error():
    def handler(request):
        raise httpx.TimeoutException("timed out", request=request)

    client = make_client(handler)
    with pytest.raises(OpenIDConformanceTimeoutError):
        client.get_available_modules()


def test_connection_failure_raises_connection_error():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    client = make_client(handler)
    with pytest.raises(OpenIDConformanceConnectionError):
        client.get_available_modules()


def test_malformed_json_raises_response_error():
    def handler(request):
        return httpx.Response(200, text="not json{{{")

    client = make_client(handler)
    with pytest.raises(OpenIDConformanceResponseError):
        client.get_available_modules()


def test_no_base_url_raises_configuration_error():
    transport = httpx.MockTransport(lambda request: json_response(200, {}))
    client = OpenIDConformanceClient(base_url=None, transport=transport)
    with pytest.raises(OpenIDConformanceConfigurationError):
        client.get_available_modules()


def test_invalid_base_url_raises_configuration_error():
    transport = httpx.MockTransport(lambda request: json_response(200, {}))
    client = OpenIDConformanceClient(base_url="not-a-valid-url", transport=transport)
    with pytest.raises(OpenIDConformanceConfigurationError):
        client.get_available_modules()


# --- retry behavior ------------------------------------------------------


def test_retryable_get_retries_on_server_error_then_succeeds():
    attempts = {"count": 0}

    def handler(request):
        attempts["count"] += 1
        if attempts["count"] < 3:
            return httpx.Response(503, text="unavailable")
        return json_response(200, {"ok": True})

    client = make_client(handler)
    result = client.get_available_modules()

    assert result == {"ok": True}
    assert attempts["count"] == 3


def test_retryable_get_gives_up_after_max_retries():
    attempts = {"count": 0}

    def handler(request):
        attempts["count"] += 1
        return httpx.Response(503, text="unavailable")

    client = make_client(handler)
    with pytest.raises(OpenIDConformanceServerError):
        client.get_available_modules()

    # 1 initial attempt + 2 retries = 3 total.
    assert attempts["count"] == 3


def test_create_plan_is_never_retried_on_server_error():
    attempts = {"count": 0}

    def handler(request):
        attempts["count"] += 1
        return httpx.Response(503, text="unavailable")

    client = make_client(handler)
    with pytest.raises(OpenIDConformanceServerError):
        client.create_plan("some-plan", {})

    # Resource-creating calls must never be retried automatically.
    assert attempts["count"] == 1


def test_400_is_never_retried_even_on_retryable_call():
    attempts = {"count": 0}

    def handler(request):
        attempts["count"] += 1
        return httpx.Response(400, json={"error": "bad"})

    client = make_client(handler)
    with pytest.raises(OpenIDConformanceBadRequestError):
        client.get_available_modules()

    assert attempts["count"] == 1
