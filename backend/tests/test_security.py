"""M10 security regression tests.

No real OpenID Conformance Suite / Inji test rig / external DNS is ever
contacted: processes are faked, and DNS resolution is injected.
"""

import socket
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import outbound
from app.auth import MIN_API_KEY_LENGTH
from app.concurrency import ExecutionCapacityError, ExecutionLimiter
from app.config import settings
from app.dependencies import (
    get_execution_repository,
    get_orchestrator,
    get_test_run_repository,
)
from app.executors import ExecutionContext, ExecutorRegistry, MockTestStepExecutor
from app.inji_executors import CertifyApiTestRigExecutor, InjiTestRigSettings
from app.inji_process import ProcessResult, sanitize_output
from app.json_execution_repository import JsonFileExecutionRepository
from app.json_repository import JsonFileTestRunRepository
from app.main import app
from app.orchestration import ExecutionStatus, Step, StepResult
from app.orchestrator import Orchestrator
from app.outbound import UnsafeDestinationError, validate_outbound_url
from app.redaction import REDACTED, redact_model
from app.report_generator import (
    build_conformance_report,
    render_markdown_report,
)
from tests.conftest import AUTH_HEADERS, TEST_API_KEY

PUBLIC = ["93.184.216.34"]


def _resolver(addresses):
    return lambda host, port: list(addresses)


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


class CapturingRunner:
    """Stands in for ProcessRunner: records what the executor passes to the
    Java process and returns canned (secret-bearing) output."""

    def __init__(self, stdout="", stderr=""):
        self.calls = []
        self._stdout, self._stderr = stdout, stderr

    def run(self, executable, args, cwd, env, timeout_seconds):
        self.calls.append({"args": args, "env": env})
        return ProcessResult(
            exit_code=0, stdout=self._stdout, stderr=self._stderr, timed_out=False
        )


@pytest.fixture
def repos(tmp_path):
    return (
        JsonFileTestRunRepository(tmp_path / "test_runs.json"),
        JsonFileExecutionRepository(tmp_path / "executions.json"),
    )


def _install(repos, registry, limiter=None):
    test_runs, executions = repos
    app.dependency_overrides[get_test_run_repository] = lambda: test_runs
    app.dependency_overrides[get_execution_repository] = lambda: executions
    app.dependency_overrides[get_orchestrator] = lambda: Orchestrator(
        test_runs, executions, registry, limiter=limiter
    )


@pytest.fixture
def anon_client(repos):
    """Client with NO credentials."""
    _install(repos, ExecutorRegistry({"mock": MockTestStepExecutor()}))
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def client(repos, tmp_path):
    """Authenticated client wired to a capturing fake Inji Certify rig."""
    jar = tmp_path / "rig.jar"
    jar.write_bytes(b"")
    runner = CapturingRunner(
        stdout="starting\npassword: hunter2-secret\nAuthorization: Bearer abc.def.ghi\n"
        "-----BEGIN PRIVATE KEY-----\nMIIEvQ\n-----END PRIVATE KEY-----\n"
    )
    executor = CertifyApiTestRigExecutor(
        InjiTestRigSettings(
            jar_path=str(jar),
            working_directory=str(tmp_path),
            java_executable="java",
            timeout_seconds=5,
        ),
        process_runner=runner,
    )
    _install(
        repos, ExecutorRegistry({"mock": MockTestStepExecutor(), "injicertify": executor})
    )
    with TestClient(app, headers=AUTH_HEADERS) as test_client:
        test_client.runner = runner
        yield test_client
    app.dependency_overrides.clear()


def _payload(suite):
    return {
        "run_name": "sec run",
        "environment": "development",
        "components": ["inji-certify"],
        "test_suites": [suite],
        "benchmark": {"minimum_pass_rate": 100, "critical_failures_allowed": 0},
    }


MOCK_SUITE = {"provider": "mock", "suite_id": "conformance-ok", "display_name": "ok"}


def _certify_suite(**overrides):
    config = {
        "env_user": "mosip-sensitive-user",
        "env_endpoint": "https://api-internal.dev.mosip.net",
        "inji_certify_base_url": "https://certify.example.test",
    }
    config.update(overrides)
    return {
        "provider": "injicertify",
        "suite_id": "certify",
        "display_name": "Certify",
        "injicertify_config": config,
    }


# --------------------------------------------------------------------------
# AUTH
# --------------------------------------------------------------------------

PROTECTED = [
    ("GET", "/"),
    ("GET", "/api/test-runs"),
    ("POST", "/api/test-runs"),
    ("GET", "/api/test-runs/x"),
    ("DELETE", "/api/test-runs/x"),
    ("POST", "/api/test-runs/x/execute"),
    ("GET", "/api/test-runs/x/execution"),
    ("GET", "/api/test-runs/x/report"),
    ("GET", "/openapi.json"),
    ("GET", "/no/such/path"),
]


@pytest.mark.parametrize("method,path", PROTECTED)
def test_missing_key_is_401(anon_client, method, path):
    response = anon_client.request(method, path)
    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


@pytest.mark.parametrize("method,path", PROTECTED)
def test_invalid_key_is_401(anon_client, method, path):
    response = anon_client.request(
        method, path, headers={"Authorization": "Bearer wrong-key-wrong-key-wrong"}
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "header",
    [
        TEST_API_KEY,  # no scheme
        f"Basic {TEST_API_KEY}",
        "Bearer",
        "Bearer ",
        f"Bearer {TEST_API_KEY}x",
        f"Bearer {TEST_API_KEY[:-1]}",
    ],
)
def test_malformed_or_near_miss_credentials_are_401(anon_client, header):
    response = anon_client.get("/api/test-runs", headers={"Authorization": header})
    assert response.status_code == 401


def test_valid_key_is_accepted(anon_client):
    response = anon_client.get("/api/test-runs", headers=AUTH_HEADERS)
    assert response.status_code == 200


def test_scheme_is_case_insensitive(anon_client):
    response = anon_client.get(
        "/api/test-runs", headers={"Authorization": f"bearer {TEST_API_KEY}"}
    )
    assert response.status_code == 200


def test_health_needs_no_key(anon_client):
    response = anon_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_401_does_not_reveal_whether_resource_exists(anon_client):
    created = anon_client.post(
        "/api/test-runs", json=_payload(MOCK_SUITE), headers=AUTH_HEADERS
    ).json()
    real = anon_client.get(f"/api/test-runs/{created['id']}")
    fake = anon_client.get("/api/test-runs/does-not-exist")
    assert real.status_code == fake.status_code == 401
    assert real.content == fake.content


def test_unauthenticated_execute_starts_nothing(anon_client, repos):
    created = anon_client.post(
        "/api/test-runs", json=_payload(MOCK_SUITE), headers=AUTH_HEADERS
    ).json()
    response = anon_client.post(f"/api/test-runs/{created['id']}/execute")
    assert response.status_code == 401
    assert repos[1].get_latest_for_run(created["id"]) is None


def test_unconfigured_server_key_fails_closed(anon_client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", None)
    response = anon_client.get("/api/test-runs", headers=AUTH_HEADERS)
    assert response.status_code == 401
    # even an empty bearer cannot match "no key"
    assert (
        anon_client.get("/api/test-runs", headers={"Authorization": "Bearer x"}).status_code
        == 401
    )


def test_too_short_server_key_fails_closed(anon_client, monkeypatch):
    short = "a" * (MIN_API_KEY_LENGTH - 1)
    monkeypatch.setattr(settings, "api_key", SecretStr(short))
    response = anon_client.get(
        "/api/test-runs", headers={"Authorization": f"Bearer {short}"}
    )
    assert response.status_code == 401


def test_health_still_open_when_key_unconfigured(anon_client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", None)
    assert anon_client.get("/health").status_code == 200


def test_cors_preflight_is_not_blocked_by_auth(anon_client):
    response = anon_client.options(
        "/api/test-runs",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 200


def test_api_key_never_appears_in_settings_repr_or_responses(anon_client):
    assert TEST_API_KEY not in repr(settings)
    assert TEST_API_KEY not in str(settings.model_dump())
    body = anon_client.get("/api/test-runs").text
    assert TEST_API_KEY not in body


# --------------------------------------------------------------------------
# SSRF
# --------------------------------------------------------------------------

UNSAFE = [
    "http://127.0.0.1",
    "http://127.0.0.1:8080/x",
    "https://localhost",
    "http://LOCALHOST.:80",
    "http://foo.localhost",
    "http://169.254.169.254/latest/meta-data",
    "http://metadata.google.internal",
    "http://0.0.0.0",
    "http://10.0.0.5",
    "http://10.255.255.255",
    "http://172.16.0.1",
    "http://172.31.255.255",
    "http://192.168.1.10",
    "http://100.64.0.1",
    "http://[::1]",
    "http://[::1]:8080",
    "http://[::]",
    "http://[fe80::1]",
    "http://[fc00::1]",
    "http://[fd12:3456::1]",
    "http://[::ffff:127.0.0.1]",
    "http://[::ffff:10.0.0.1]",
    "http://[64:ff9b::7f00:1]",
    "http://[2002:7f00:1::]",
    # unusual numeric spellings of loopback / link-local
    "http://2130706433",
    "http://0x7f000001",
    "http://0x7f.0.0.1",
    "http://017700000001",
    "http://127.1",
    "http://2852039166",
    # structural attacks
    "http://user:pass@example.com",
    "http://example.com@127.0.0.1",
    "http://127.0.0.1#@example.com",
    "ftp://example.com",
    "file:///etc/passwd",
    "gopher://example.com",
    "javascript:alert(1)",
    "http://example.com:0",
    "http://example.com:99999",
    "http://exa mple.com",
    "http://example.com\\@127.0.0.1",
    "http://[fe80::1%25eth0]",
    "",
    "   ",
]


@pytest.mark.parametrize("url", UNSAFE)
def test_unsafe_destinations_rejected_without_dns(url):
    with pytest.raises(UnsafeDestinationError):
        validate_outbound_url(url, resolve=False)


@pytest.mark.parametrize("url", UNSAFE)
def test_unsafe_destinations_rejected_with_dns(url):
    with pytest.raises(UnsafeDestinationError):
        validate_outbound_url(url, resolve=True, resolver=_resolver(PUBLIC))


@pytest.mark.parametrize(
    "url",
    [
        "https://api-internal.dev.mosip.net",
        "http://example.com:8080/path?q=1",
        "https://93.184.216.34",
        "https://[2606:2800:220:1:248:1893:25c8:1946]",
        "api-internal.dev.mosip.net",  # bare host (Inji env.endpoint style)
        "HTTPS://Example.COM/",
    ],
)
def test_legitimate_destinations_allowed(url):
    validate_outbound_url(url, resolve=True, resolver=_resolver(PUBLIC))


@pytest.mark.parametrize(
    "resolved",
    [
        ["127.0.0.1"],
        ["10.0.0.1"],
        ["169.254.169.254"],
        ["::1"],
        ["fc00::1"],
        ["fe80::1"],
        ["93.184.216.34", "10.0.0.1"],  # one bad answer poisons the set
        [],
    ],
)
def test_hostname_resolving_to_non_public_address_is_rejected(resolved):
    with pytest.raises(UnsafeDestinationError):
        validate_outbound_url(
            "https://attacker.example", resolve=True, resolver=_resolver(resolved)
        )


def test_unresolvable_hostname_fails_closed():
    def boom(host, port):
        raise socket.gaierror("nope")

    with pytest.raises(UnsafeDestinationError):
        validate_outbound_url("https://nx.example", resolve=True, resolver=boom)


def test_error_message_never_echoes_url_or_credentials():
    with pytest.raises(UnsafeDestinationError) as info:
        validate_outbound_url("http://admin:s3cret@10.0.0.1", resolve=False)
    assert "s3cret" not in str(info.value)
    assert "10.0.0.1" not in str(info.value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("env_endpoint", "http://127.0.0.1"),
        ("env_endpoint", "https://localhost"),
        ("inji_certify_base_url", "http://169.254.169.254"),
        ("esignet_base_url", "http://10.1.2.3"),
        ("sunbird_base_url", "http://172.16.0.9"),
        ("mosip_components_base_urls", "a=https://ok.example$b=http://192.168.0.1"),
        ("inji_certify_base_url", "http://[::1]"),
    ],
)
def test_api_rejects_unsafe_certify_fields_with_422(client, field, value):
    response = client.post("/api/test-runs", json=_payload(_certify_suite(**{field: value})))
    assert response.status_code == 422
    assert field in response.text


def test_api_rejects_unsafe_verify_url(client):
    suite = {
        "provider": "injiverify",
        "suite_id": "v",
        "display_name": "V",
        "injiverify_config": {
            "env_user": "u",
            "env_endpoint": "https://api-internal.dev.mosip.net",
            "inji_verify_base_url": "http://127.0.0.1:3000",
        },
    }
    assert client.post("/api/test-runs", json=_payload(suite)).status_code == 422


@pytest.mark.parametrize(
    "plan_configuration",
    [
        {"server": {"discoveryUrl": "http://169.254.169.254/x"}},
        {"credential_issuer_url": "http://localhost:8080"},
        {"nested": [{"jwks_uri": "https://10.0.0.1/jwks"}]},
        {"callback": "file:///etc/passwd"},
    ],
)
def test_api_rejects_unsafe_urls_inside_openid_plan_configuration(client, plan_configuration):
    suite = {
        "provider": "openid",
        "suite_id": "o",
        "display_name": "O",
        "openid_config": {"plan_name": "plan", "plan_configuration": plan_configuration},
    }
    assert client.post("/api/test-runs", json=_payload(suite)).status_code == 422


def test_api_accepts_safe_destinations(client):
    suite = _certify_suite(
        mosip_components_base_urls="a=https://ok.example$b=https://ok2.example"
    )
    assert client.post("/api/test-runs", json=_payload(suite)).status_code == 201
    openid = {
        "provider": "openid",
        "suite_id": "o",
        "display_name": "O",
        "openid_config": {
            "plan_name": "plan",
            "plan_configuration": {"server": {"discoveryUrl": "https://issuer.example/.well-known"}},
        },
    }
    assert client.post("/api/test-runs", json=_payload(openid)).status_code == 201


def test_execution_time_dns_check_blocks_rebinding_style_run(client, monkeypatch):
    """A run that was valid when created but whose host now resolves to a
    private address is stopped before the (fake) Java process starts."""
    created = client.post("/api/test-runs", json=_payload(_certify_suite()))
    assert created.status_code == 201
    monkeypatch.setattr(outbound, "_default_resolver", lambda h, p: ["10.9.9.9"])

    response = client.post(f"/api/test-runs/{created.json()['id']}/execute")

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "FAILED"
    assert body["benchmark_evaluation"]["status"] == "FAILED"
    assert body["step_results"][0]["details"]["error_type"] == "unsafe_destination"
    assert client.runner.calls == []  # the rig was never launched
    assert "10.9.9.9" not in response.text


# --------------------------------------------------------------------------
# DoS: bounded concurrency
# --------------------------------------------------------------------------


def _orchestrator(repos, limiter):
    test_runs, executions = repos
    return Orchestrator(
        test_runs,
        executions,
        ExecutorRegistry({"mock": MockTestStepExecutor()}),
        limiter=limiter,
    )


def _mock_run(repos, suite_id="conformance-ok"):
    from app.schemas import TestRunConfig, TestRunCreateRequest, TestRunStatus

    request = TestRunCreateRequest(**_payload({**MOCK_SUITE, "suite_id": suite_id}))
    run = TestRunConfig(
        id=f"run-{suite_id}",
        status=TestRunStatus.CONFIGURED,
        created_at=datetime.now(timezone.utc),
        **request.model_dump(),
    )
    repos[0].create(run)
    return run.id


def test_execution_allowed_when_capacity_available(repos):
    limiter = ExecutionLimiter(1)
    execution = _orchestrator(repos, limiter).execute(_mock_run(repos))
    assert execution.status == ExecutionStatus.PASSED


def test_execution_rejected_when_capacity_exhausted(repos):
    limiter = ExecutionLimiter(1)
    assert limiter.try_acquire()  # someone else holds the only slot
    run_id = _mock_run(repos)

    with pytest.raises(ExecutionCapacityError):
        _orchestrator(repos, limiter).execute(run_id)

    assert repos[1].get_latest_for_run(run_id) is None  # nothing started
    assert limiter.in_use == 1  # rejection did not steal/leak a slot


def test_capacity_released_after_success(repos):
    limiter = ExecutionLimiter(1)
    orchestrator = _orchestrator(repos, limiter)
    run_id = _mock_run(repos)
    orchestrator.execute(run_id)
    assert limiter.in_use == 0
    orchestrator.execute(run_id)  # a second run is admitted
    assert limiter.in_use == 0


def test_capacity_released_after_failed_step(repos):
    limiter = ExecutionLimiter(1)
    orchestrator = _orchestrator(repos, limiter)
    run_id = _mock_run(repos, "conformance-fail")
    assert orchestrator.execute(run_id).status == ExecutionStatus.FAILED
    assert limiter.in_use == 0


def test_capacity_released_after_unexpected_exception(repos):
    limiter = ExecutionLimiter(1)
    orchestrator = _orchestrator(repos, limiter)
    run_id = _mock_run(repos)

    def explode(execution):
        raise RuntimeError("disk full")

    orchestrator._executions.update = explode  # repository failure mid-run
    with pytest.raises(RuntimeError):
        orchestrator.execute(run_id)
    assert limiter.in_use == 0


def test_unknown_run_does_not_consume_capacity(repos):
    limiter = ExecutionLimiter(1)
    from app.orchestrator import TestRunNotFoundError

    with pytest.raises(TestRunNotFoundError):
        _orchestrator(repos, limiter).execute("missing")
    assert limiter.in_use == 0


def test_execute_endpoint_returns_429_when_exhausted_then_recovers(repos):
    limiter = ExecutionLimiter(1)
    _install(repos, ExecutorRegistry({"mock": MockTestStepExecutor()}), limiter=limiter)
    with TestClient(app, headers=AUTH_HEADERS) as client:
        run_id = client.post("/api/test-runs", json=_payload(MOCK_SUITE)).json()["id"]
        assert limiter.try_acquire()
        blocked = client.post(f"/api/test-runs/{run_id}/execute")
        assert blocked.status_code == 429
        assert "Retry-After" in blocked.headers
        assert client.get(f"/api/test-runs/{run_id}/execution").status_code == 404
        limiter.release()
        ok = client.post(f"/api/test-runs/{run_id}/execute")
        assert ok.status_code == 201  # synchronous contract unchanged
        assert ok.json()["benchmark_evaluation"]["status"] == "PASSED"
    app.dependency_overrides.clear()


def test_limiter_rejects_invalid_capacity_and_ignores_extra_release():
    with pytest.raises(ValueError):
        ExecutionLimiter(0)
    limiter = ExecutionLimiter(1)
    limiter.release()
    assert limiter.in_use == 0
    assert limiter.try_acquire() and not limiter.try_acquire()


# --------------------------------------------------------------------------
# SECRETS
# --------------------------------------------------------------------------

SECRET_VALUES = ["mosip-sensitive-user", "hunter2-secret", "abc.def.ghi", "MIIEvQ"]


def test_credentials_not_in_test_run_responses(client):
    created = client.post("/api/test-runs", json=_payload(_certify_suite()))
    assert created.status_code == 201
    run_id = created.json()["id"]

    for response in (
        created,
        client.get(f"/api/test-runs/{run_id}"),
        client.get("/api/test-runs"),
    ):
        assert "mosip-sensitive-user" not in response.text
        assert REDACTED in response.text


def test_credentials_stay_available_internally_for_execution(client, repos):
    run_id = client.post("/api/test-runs", json=_payload(_certify_suite())).json()["id"]

    # Persistence still holds the real value (execution needs it) ...
    stored = repos[0].get(run_id)
    assert stored.test_suites[0].injicertify_config.env_user == "mosip-sensitive-user"

    client.post(f"/api/test-runs/{run_id}/execute")

    # ... and the rig process actually received it.
    assert "-Denv.user=mosip-sensitive-user" in client.runner.calls[0]["args"]


def test_credentials_and_evidence_secrets_not_in_execution_responses(client):
    run_id = client.post("/api/test-runs", json=_payload(_certify_suite())).json()["id"]
    executed = client.post(f"/api/test-runs/{run_id}/execute")
    latest = client.get(f"/api/test-runs/{run_id}/execution")

    for response in (executed, latest):
        assert response.status_code in (200, 201)
        for secret in SECRET_VALUES:
            assert secret not in response.text, secret
    assert "process_output_excerpt" in executed.text  # evidence kept, secrets scrubbed


def test_credentials_not_in_json_or_markdown_report(client):
    run_id = client.post("/api/test-runs", json=_payload(_certify_suite())).json()["id"]
    client.post(f"/api/test-runs/{run_id}/execute")

    for fmt in ("json", "markdown"):
        response = client.get(f"/api/test-runs/{run_id}/report", params={"format": fmt})
        assert response.status_code == 200
        for secret in SECRET_VALUES:
            assert secret not in response.text, (fmt, secret)


def test_openid_plan_configuration_secrets_redacted_but_kept_for_execution(client, repos):
    suite = {
        "provider": "openid",
        "suite_id": "o",
        "display_name": "O",
        "openid_config": {
            "plan_name": "plan",
            "plan_configuration": {
                "client": {"client_id": "public-id", "client_secret": "s3cr3t-value"},
                "resource": {"access_token": "tok-123", "password": "pw-456"},
                "private_key": "-----BEGIN PRIVATE KEY-----\nAAA\n-----END PRIVATE KEY-----",
                "note": "-----BEGIN RSA PRIVATE KEY-----\nBBB\n-----END RSA PRIVATE KEY-----",
                "jwks": {"keys": [{"kty": "RSA", "d": "private-exponent"}]},
            },
        },
    }
    created = client.post("/api/test-runs", json=_payload(suite))
    assert created.status_code == 201
    for secret in ("s3cr3t-value", "tok-123", "pw-456", "AAA", "BBB", "private-exponent"):
        assert secret not in created.text, secret
    assert "public-id" in created.text  # non-secret content preserved

    stored = repos[0].get(created.json()["id"])
    cfg = stored.test_suites[0].openid_config.plan_configuration
    assert cfg["client"]["client_secret"] == "s3cr3t-value"  # still real internally


def test_redact_model_does_not_mutate_original(repos):
    run_id = _mock_run(repos)
    run = repos[0].get(run_id)
    run.test_suites[0].injicertify_config = None
    copy = redact_model(run)
    assert copy is not run


def test_sanitize_output_still_redacts_subprocess_secrets():
    text = sanitize_output("Authorization: Bearer abc\npassword=hunter2\nclient_secret: x")
    assert "abc" not in text and "hunter2" not in text
    assert "client_secret: [REDACTED]" in text
    assert '"client_secret": "[REDACTED]' in sanitize_output('{"client_secret": "zzz"}')


def test_executor_error_messages_do_not_contain_credentials(client):
    # report_not_found path embeds process output; secrets must be scrubbed
    run_id = client.post("/api/test-runs", json=_payload(_certify_suite())).json()["id"]
    body = client.post(f"/api/test-runs/{run_id}/execute").text
    assert "hunter2-secret" not in body


# --------------------------------------------------------------------------
# REPORT / Markdown safety
# --------------------------------------------------------------------------


def _report_for(run_name="r", message="m", step_id="s1", suite_id="suite", violation="v"):
    from app.orchestration import BenchmarkEvaluation, BenchmarkStatus, BenchmarkViolation, Execution
    from app.result_normalizer import NormalizedStepResult
    from app.schemas import (
        BenchmarkConfig,
        Environment,
        TestRunConfig,
        TestRunStatus,
        TestSuiteConfig,
    )

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    raw = StepResult(
        step_id=step_id, status=ExecutionStatus.FAILED, started_at=now, message=message
    )
    normalized = NormalizedStepResult(
        step_id=step_id,
        display_name="d",
        provider="mock",
        component="inji-certify",
        suite_id=suite_id,
        status=ExecutionStatus.FAILED,
        started_at=now,
        message=message,
        error_type=message,
        raw_result=raw,
    )
    execution = Execution(
        id="exec-1",
        test_run_id="run-1",
        status=ExecutionStatus.FAILED,
        started_at=now,
        total_steps=1,
        completed_steps=1,
        steps=[
            Step(
                step_id=step_id,
                display_name="d",
                provider="mock",
                component="inji-certify",
                order=0,
            )
        ],
        step_results=[raw],
        normalized_results=[normalized],
        benchmark_evaluation=BenchmarkEvaluation(
            status=BenchmarkStatus.FAILED,
            evidence_complete=True,
            total_planned_steps=1,
            normalized_result_count=1,
            passed_steps=0,
            failed_steps=1,
            pass_rate=0,
            minimum_pass_rate=100,
            critical_failures_allowed=0,
            violations=[
                BenchmarkViolation(
                    code="X", message=violation, expected="a", actual=violation, step_ids=[step_id]
                )
            ],
        ),
    )
    run = TestRunConfig(
        id="run-1",
        run_name=run_name,
        environment=Environment.DEVELOPMENT,
        components=["inji-certify"],
        test_suites=[TestSuiteConfig(provider="mock", suite_id="s", display_name="S")],
        benchmark=BenchmarkConfig(minimum_pass_rate=100, critical_failures_allowed=0),
        status=TestRunStatus.FAILED,
        created_at=now,
    )
    return render_markdown_report(build_conformance_report(run, execution))


def _lines(markdown):
    return markdown.split("\n")


def test_markdown_newline_injection_cannot_create_new_blocks():
    evil = "ok\n# INJECTED HEADING\n- injected item\r\n| a | b |\u2028## more"
    for kwargs in (
        {"run_name": evil},
        {"message": evil},
        {"step_id": evil},
        {"suite_id": evil},
        {"violation": evil},
    ):
        markdown = _report_for(**kwargs)
        for line in _lines(markdown):
            assert not line.startswith("# INJECTED")
            assert not line.startswith("- injected")
            assert not line.startswith("## more")
        headings = [l for l in _lines(markdown) if l.startswith("#")]
        assert headings[0] == "# Conformance Report"
        assert all(h.startswith("## ") or h == "# Conformance Report" for h in headings)
        assert "INJECTED HEADING" in markdown  # content preserved, just inert


def test_markdown_pipes_cannot_add_table_columns():
    markdown = _report_for(message="a | b | c", violation="x|y")
    rows = [l for l in _lines(markdown) if l.startswith("| s1 |")]
    assert rows
    # split on unescaped pipes only
    import re

    for row in rows:
        cells = re.split(r"(?<!\\)\|", row)
        assert len(cells) == 12  # leading "" + 10 columns + trailing ""
    assert "a \\| b \\| c" in markdown


def test_markdown_backslash_cannot_cancel_pipe_escape():
    import re

    markdown = _report_for(message="evil\\| x")
    row = next(l for l in _lines(markdown) if l.startswith("| s1 |"))
    # the attacker's backslash is itself escaped, so the pipe stays escaped
    assert "evil\\\\\\| x" in row
    assert len(re.split(r"(?<!\\)(?:\\\\)*\|", row)) >= 1


def test_markdown_backticks_cannot_break_code_spans():
    markdown = _report_for(run_name="x` injected `y", step_id="a`b")
    summary = next(l for l in _lines(markdown) if l.startswith("- Test run:"))
    assert summary.count("`") == 4  # exactly our two code spans
    assert "x' injected 'y" in summary
    cell_row = next(l for l in _lines(markdown) if l.startswith("| a"))
    assert "a\\`b" in cell_row


def test_markdown_legitimate_content_preserved():
    markdown = _report_for(run_name="Release 1.2 (staging)", message="12/12 passed")
    assert "Release 1.2 (staging)" in markdown
    assert "12/12 passed" in markdown


def test_markdown_control_characters_removed():
    markdown = _report_for(message="a\x00b\x07c\x1bd")
    assert "\x00" not in markdown and "\x07" not in markdown and "\x1b" not in markdown
    assert "abcd" in markdown


# --------------------------------------------------------------------------
# Regression: command-injection protections still hold
# --------------------------------------------------------------------------


def test_shell_metacharacters_stay_inert_argv_elements(tmp_path):
    jar = tmp_path / "rig.jar"
    jar.write_bytes(b"")
    runner = CapturingRunner()
    executor = CertifyApiTestRigExecutor(
        InjiTestRigSettings(str(jar), str(tmp_path), "java", 5), process_runner=runner
    )
    step = Step(
        step_id="s",
        display_name="d",
        provider="injicertify",
        component="inji-certify",
        order=0,
        suite_config={
            "injicertify_config": {
                "env_user": "u; rm -rf / #$(id)",
                "env_endpoint": "https://api-internal.dev.mosip.net",
            }
        },
    )
    executor.execute(step, ExecutionContext(test_run_id="r", execution_id="e", environment="development"))
    args = runner.calls[0]["args"]
    assert "-Denv.user=u; rm -rf / #$(id)" in args  # a single literal argument
    assert all(isinstance(a, str) for a in args)
