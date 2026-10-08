"""Shared test configuration.

* M10 auth: every test runs with a known API key configured, and test
  clients that talk to the real app send it (see TEST_API_KEY /
  AUTH_HEADERS). The security tests in test_security.py additionally prove
  the unauthenticated/invalid paths are rejected.
* M10 SSRF: tests must never perform real DNS lookups. Non-IP hostnames
  resolve to a fixed public documentation address by default; IP literals
  and internal names are still checked for real (they never reach the
  resolver), and test_security.py injects its own resolvers for the
  resolution-based cases.
"""

import pytest
from pydantic import SecretStr

from app import outbound
from app.config import settings

TEST_API_KEY = "test-api-key-0123456789abcdef"
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_API_KEY}"}


@pytest.fixture(autouse=True)
def _api_key_configured(monkeypatch):
    monkeypatch.setattr(settings, "api_key", SecretStr(TEST_API_KEY))


@pytest.fixture(autouse=True)
def _hermetic_dns(monkeypatch):
    monkeypatch.setattr(
        outbound, "_default_resolver", lambda host, port: ["93.184.216.34"]
    )

