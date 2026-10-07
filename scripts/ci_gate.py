#!/usr/bin/env python3
"""M9 CI gate for MOSIP Conformance Center.

Calls the existing synchronous ``POST /api/test-runs/{run_id}/execute``
endpoint, waits for the completed ``Execution`` response, and exits based
solely on the persisted M7 verdict (``benchmark_evaluation.status``).

This script is only a consumer of that verdict. It does not evaluate pass
rates, thresholds, or failures itself, and it is fail-closed: anything other
than an explicit ``PASSED`` verdict is a non-zero exit.

Exit codes:
    0  benchmark_evaluation.status == "PASSED"
    1  benchmark_evaluation.status == "FAILED" (gate failed)
    2  response unusable: not JSON / not an object / evaluation missing or
       malformed / status is neither PASSED nor FAILED
    3  backend returned an HTTP error (404, 409, 422, 5xx, ...)
    4  network failure or timeout
    5  invalid usage / configuration (e.g. bad base URL)

Standard library only, so it runs in CI without installing anything.
"""

import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional

EXIT_PASSED = 0
EXIT_GATE_FAILED = 1
EXIT_BAD_RESPONSE = 2
EXIT_HTTP_ERROR = 3
EXIT_NETWORK_ERROR = 4
EXIT_USAGE = 5

DEFAULT_BASE_URL = "http://localhost:8000"
# Real conformance runs can be long (Inji test-rig default timeout is 1800s
# per step), so the default is generous. Override with --timeout.
DEFAULT_TIMEOUT_SECONDS = 3600.0


def _error(message: str) -> None:
    print(f"ci_gate: ERROR: {message}", file=sys.stderr)


def _parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute a Test Run and gate on its persisted M7 benchmark verdict."
    )
    parser.add_argument("--run-id", required=True, help="ID of the Test Run to execute.")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("MCC_API_URL", DEFAULT_BASE_URL),
        help="Backend base URL (env: MCC_API_URL; default: %(default)s).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Seconds to wait for the synchronous execution (default: %(default)s).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)

    parsed = urllib.parse.urlparse(args.base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        _error(f"invalid base URL {args.base_url!r}; expected http(s)://host[:port]")
        return EXIT_USAGE
    if args.timeout <= 0:
        _error("--timeout must be greater than 0")
        return EXIT_USAGE

    url = (
        args.base_url.rstrip("/")
        + "/api/test-runs/"
        + urllib.parse.quote(args.run_id, safe="")
        + "/execute"
    )
    request = urllib.request.Request(url, data=b"", method="POST")
    print(f"ci_gate: executing test run {args.run_id} via POST {url}")

    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        _error(f"backend returned HTTP {exc.code} for test run {args.run_id}: {_detail(exc)}")
        return EXIT_HTTP_ERROR
    except (socket.timeout, TimeoutError):
        _error(f"timed out after {args.timeout:g}s waiting for test run {args.run_id}")
        return EXIT_NETWORK_ERROR
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            _error(f"timed out after {args.timeout:g}s waiting for test run {args.run_id}")
        else:
            _error(f"could not reach backend at {args.base_url}: {exc.reason}")
        return EXIT_NETWORK_ERROR
    except OSError as exc:
        _error(f"network error talking to {args.base_url}: {exc}")
        return EXIT_NETWORK_ERROR

    try:
        execution = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        _error("response was not valid JSON")
        return EXIT_BAD_RESPONSE
    if not isinstance(execution, dict):
        _error("response JSON was not an Execution object")
        return EXIT_BAD_RESPONSE

    evaluation = execution.get("benchmark_evaluation")
    if not isinstance(evaluation, dict):
        _error("response has no benchmark_evaluation; refusing to pass the gate")
        return EXIT_BAD_RESPONSE
    verdict = evaluation.get("status")

    execution_id = execution.get("id", "<unknown>")
    print(
        f"ci_gate: execution {execution_id} finished: "
        f"execution status={execution.get('status')}, benchmark status={verdict}, "
        f"pass rate={evaluation.get('pass_rate')}% "
        f"(minimum {evaluation.get('minimum_pass_rate')}%), "
        f"evidence_complete={evaluation.get('evidence_complete')}"
    )

    if verdict == "PASSED":
        print("ci_gate: PASSED")
        return EXIT_PASSED
    if verdict == "FAILED":
        for violation in evaluation.get("violations") or []:
            if isinstance(violation, dict):
                print(
                    f"ci_gate: violation {violation.get('code')}: {violation.get('message')}",
                    file=sys.stderr,
                )
        _error("benchmark gate FAILED")
        return EXIT_GATE_FAILED
    _error(f"unrecognized benchmark_evaluation.status {verdict!r}; refusing to pass the gate")
    return EXIT_BAD_RESPONSE


def _detail(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read())
        detail = payload.get("detail") if isinstance(payload, dict) else None
        return str(detail) if detail is not None else "(no detail)"
    except Exception:  # noqa: BLE001 - diagnostics only, never affects the verdict
        return "(no detail)"


if __name__ == "__main__":
    sys.exit(main())
