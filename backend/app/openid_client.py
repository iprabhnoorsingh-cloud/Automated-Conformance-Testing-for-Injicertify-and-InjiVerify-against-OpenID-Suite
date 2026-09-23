"""HTTP client for the OpenID Foundation Conformance Suite REST API.

This client only knows how to call the REST API surface described in
docs/architecture.md (mirroring the Foundation's own upstream CI helper
script's REST usage) — it has no opinion about which test plan/module to
run for a given Test Run; that's OpenIDConformanceExecutor's job (see
app/openid_executor.py).

Talks to whatever `OPENID_CONFORMANCE_BASE_URL` points at — a local or
staging conformance-suite instance you control. Never assume this is the
public certification.openid.net environment.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


class OpenIDConformanceError(Exception):
    """Base class for OpenID Conformance Suite client errors."""


class OpenIDConformanceConfigurationError(OpenIDConformanceError):
    """Raised when the client itself is not configured correctly (e.g. no
    base URL) — never retried."""


class OpenIDConformanceAuthError(OpenIDConformanceError):
    """Raised on HTTP 401 — never retried."""


class OpenIDConformanceBadRequestError(OpenIDConformanceError):
    """Raised on HTTP 400 — a client/configuration error, never retried."""


class OpenIDConformanceNotFoundError(OpenIDConformanceError):
    """Raised on HTTP 404 — never retried."""


class OpenIDConformanceServerError(OpenIDConformanceError):
    """Raised on HTTP 5xx. Transient — may be retried by callers that pass
    retryable=True."""


class OpenIDConformanceTimeoutError(OpenIDConformanceError):
    """Raised when a request (or a wait-state long-poll) exceeds its
    timeout. Transient — may be retried."""


class OpenIDConformanceConnectionError(OpenIDConformanceError):
    """Raised when the conformance suite cannot be reached at all.
    Transient — may be retried."""


class OpenIDConformanceResponseError(OpenIDConformanceError):
    """Raised when a response can't be parsed as expected: malformed JSON,
    an unexpected (non-error) status code, or a missing required field."""


_TRANSIENT_ERRORS = (
    OpenIDConformanceServerError,
    OpenIDConformanceTimeoutError,
    OpenIDConformanceConnectionError,
)


class OpenIDConformanceClient:
    """Typed wrapper around the Conformance Suite's REST API.

    Retries are opt-in per call (`retryable=True`) and only ever applied to
    transient failures (5xx / timeout / connection error) — never to 400/401
    or other validation failures. Callers must not mark a resource-creating
    call (create_plan, create_test_from_plan) as retryable: a network
    failure after the server has already created the resource must not
    silently become a duplicate plan/module on retry.
    """

    def __init__(
        self,
        base_url: Optional[str],
        api_token: Optional[str] = None,
        verify_ssl: bool = True,
        timeout: float = 30.0,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self._base_url = base_url.rstrip("/") if base_url else None
        self._api_token = api_token
        self._timeout = timeout
        self._http = httpx.Client(
            verify=verify_ssl, timeout=timeout, transport=transport
        )

    def close(self) -> None:
        self._http.close()

    # --- internals ---------------------------------------------------

    def _build_url(self, path: str) -> str:
        if not self._base_url:
            raise OpenIDConformanceConfigurationError(
                "OPENID_CONFORMANCE_BASE_URL is not configured. Point this "
                "at a conformance-suite instance you control (local or "
                "staging) — see docs/architecture.md."
            )
        parsed = urlparse(self._base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise OpenIDConformanceConfigurationError(
                f"OPENID_CONFORMANCE_BASE_URL is not a valid http(s) URL: "
                f"{self._base_url!r}"
            )
        return f"{self._base_url}{path}"

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._api_token:
            headers["Authorization"] = f"Bearer {self._api_token}"
        return headers

    def _handle_response(
        self, response: httpx.Response, method: str, path: str, exact_status: Optional[int]
    ) -> Any:
        if response.status_code == 400:
            raise OpenIDConformanceBadRequestError(
                f"Bad request for {method} {path} (HTTP 400)"
            )
        if response.status_code == 401:
            raise OpenIDConformanceAuthError(
                f"Authentication failed for {method} {path} (HTTP 401)"
            )
        if response.status_code == 404:
            raise OpenIDConformanceNotFoundError(
                f"Not found: {method} {path} (HTTP 404)"
            )
        if response.status_code >= 500:
            raise OpenIDConformanceServerError(
                f"Conformance suite server error for {method} {path}: "
                f"HTTP {response.status_code}"
            )
        if exact_status is not None:
            if response.status_code != exact_status:
                raise OpenIDConformanceResponseError(
                    f"Unexpected status {response.status_code} for {method} "
                    f"{path} (expected {exact_status})"
                )
        elif not (200 <= response.status_code < 300):
            raise OpenIDConformanceResponseError(
                f"Unexpected status {response.status_code} for {method} {path}"
            )

        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise OpenIDConformanceResponseError(
                f"Malformed JSON response from {method} {path}"
            ) from exc

    def _do_request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]],
        json_body: Optional[Any],
        exact_status: Optional[int],
        timeout: Optional[float],
    ) -> Any:
        url = self._build_url(path)
        try:
            response = self._http.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=self._headers(),
                timeout=timeout if timeout is not None else self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise OpenIDConformanceTimeoutError(
                f"Timed out calling {method} {path}"
            ) from exc
        except httpx.ConnectError as exc:
            raise OpenIDConformanceConnectionError(
                f"Could not connect to conformance suite for {method} {path}"
            ) from exc
        except httpx.HTTPError as exc:
            raise OpenIDConformanceConnectionError(
                f"HTTP error calling {method} {path}: {type(exc).__name__}"
            ) from exc

        return self._handle_response(response, method, path, exact_status)

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Any] = None,
        exact_status: Optional[int] = None,
        timeout: Optional[float] = None,
        retryable: bool = False,
        max_retries: int = 2,
    ) -> Any:
        attempt = 0
        while True:
            try:
                return self._do_request(
                    method, path, params, json_body, exact_status, timeout
                )
            except _TRANSIENT_ERRORS:
                if not retryable or attempt >= max_retries:
                    raise
                backoff = 0.05 * (2**attempt)
                logger.warning(
                    "Transient error calling %s %s, retrying (attempt %d/%d)",
                    method,
                    path,
                    attempt + 1,
                    max_retries,
                )
                time.sleep(backoff)
                attempt += 1

    # --- public API surface ------------------------------------------

    def get_available_modules(self) -> Any:
        return self._request("GET", "/api/runner/available", retryable=True)

    def create_plan(
        self, plan_name: str, configuration: Dict[str, Any]
    ) -> Dict[str, Any]:
        # Never retryable: a retry after a dropped connection could create a
        # second plan on the server without us knowing the first succeeded.
        result = self._request(
            "POST",
            "/api/plan",
            params={"planName": plan_name},
            json_body=configuration,
            exact_status=201,
        )
        if not isinstance(result, dict) or "id" not in result:
            raise OpenIDConformanceResponseError(
                "create_plan response did not contain an 'id'"
            )
        return result

    def create_test_from_plan(
        self,
        test: str,
        plan_id: str,
        variant: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        # Never retryable, for the same reason as create_plan.
        params: Dict[str, Any] = {"test": test, "plan": plan_id}
        if variant is not None:
            params["variant"] = json.dumps(variant)
        result = self._request(
            "POST", "/api/runner", params=params, exact_status=201
        )
        if not isinstance(result, dict) or "id" not in result:
            raise OpenIDConformanceResponseError(
                "create_test_from_plan response did not contain an 'id'"
            )
        return result

    def start_test(self, module_id: str) -> Any:
        # Not marked retryable: whether starting an already-started module
        # is safe to repeat isn't guaranteed by the documented contract, so
        # we're conservative here even though it's less risky than the
        # plan/module creation calls.
        return self._request("POST", f"/api/runner/{module_id}")

    def wait_for_state(
        self, module_id: str, states: List[str], timeout_ms: int
    ) -> Dict[str, Any]:
        # The server long-polls for up to timeout_ms itself, so our own
        # request timeout must exceed that or we'll time out first.
        request_timeout = max(self._timeout, (timeout_ms / 1000.0) + 5.0)
        return self._request(
            "GET",
            f"/api/runner/{module_id}/wait-state",
            params={"states": ",".join(states), "timeoutMs": timeout_ms},
            timeout=request_timeout,
            retryable=True,
        )

    def get_test_info(self, module_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/api/info/{module_id}", retryable=True)

    def get_test_log(self, module_id: str) -> Any:
        return self._request("GET", f"/api/log/{module_id}", retryable=True)

    def export_plan_results(self, plan_id: str) -> Any:
        return self._request(
            "GET", f"/api/plan/{plan_id}/export", retryable=True
        )
