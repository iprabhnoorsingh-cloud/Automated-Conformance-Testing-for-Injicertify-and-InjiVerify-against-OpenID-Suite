"""Opt-in smoke test against a REAL OpenID Foundation Conformance Suite
instance.

This NEVER runs as part of the normal `pytest` invocation — every test here
is skipped unless OPENID_CONFORMANCE_INTEGRATION=1 is set, and even then
requires OPENID_CONFORMANCE_BASE_URL to point at an instance you control
(never point this at the public certification.openid.net environment).

Run explicitly with, e.g.:

    OPENID_CONFORMANCE_INTEGRATION=1 \\
    OPENID_CONFORMANCE_BASE_URL=http://localhost:8443 \\
    pytest tests/test_openid_integration.py -q
"""

import os

import pytest

from app.openid_client import OpenIDConformanceClient

INTEGRATION_ENABLED = os.environ.get("OPENID_CONFORMANCE_INTEGRATION") == "1"
BASE_URL = os.environ.get("OPENID_CONFORMANCE_BASE_URL")

pytestmark = pytest.mark.skipif(
    not INTEGRATION_ENABLED,
    reason=(
        "Opt-in only: set OPENID_CONFORMANCE_INTEGRATION=1 (and point "
        "OPENID_CONFORMANCE_BASE_URL at an instance you control) to run "
        "this against a real Conformance Suite."
    ),
)


@pytest.fixture
def live_client():
    if not BASE_URL:
        pytest.skip("OPENID_CONFORMANCE_BASE_URL is not set")
    client = OpenIDConformanceClient(
        base_url=BASE_URL,
        api_token=os.environ.get("OPENID_CONFORMANCE_API_TOKEN"),
        verify_ssl=os.environ.get("OPENID_CONFORMANCE_VERIFY_SSL", "true").lower()
        != "false",
        timeout=float(os.environ.get("OPENID_CONFORMANCE_TIMEOUT", "30")),
    )
    yield client
    client.close()


def test_can_list_available_modules(live_client):
    modules = live_client.get_available_modules()
    assert modules is not None
