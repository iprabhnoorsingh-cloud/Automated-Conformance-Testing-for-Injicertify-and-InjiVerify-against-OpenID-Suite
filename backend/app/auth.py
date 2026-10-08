"""M10: centralized API-key authentication.

Implemented as one ASGI-level middleware (not per-router dependencies) so
that every route — including any added in the future, and unknown paths —
is protected by default, and the only exemption is the explicit
`GET /health` liveness probe.

Clients send `Authorization: Bearer <MCC_API_KEY>`. The key comes only from
the environment (settings.api_key); it is never hardcoded, logged, or
echoed. The check is fail-closed: if no (or a too-short) key is configured,
every protected request is rejected rather than silently allowed.

All failures return the same generic 401 whether the credential was
missing, malformed, or wrong, and authentication runs before routing
reaches any handler, so a 401 reveals nothing about whether a resource
exists.
"""

import hmac
import logging
from typing import Awaitable, Callable, Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from app.config import settings

logger = logging.getLogger(__name__)

MIN_API_KEY_LENGTH = 16

# (method, path) pairs reachable without credentials. Exact match only.
_PUBLIC_ENDPOINTS = frozenset({("GET", "/health")})


def configured_api_key() -> Optional[bytes]:
    """The usable configured key, or None if unset/too short (fail closed)."""
    secret = settings.api_key
    if secret is None:
        return None
    value = secret.get_secret_value()
    if len(value) < MIN_API_KEY_LENGTH:
        return None
    return value.encode("utf-8")


def _presented_key(authorization: Optional[str]) -> Optional[bytes]:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip().encode("utf-8")


def is_authorized(authorization: Optional[str]) -> bool:
    expected = configured_api_key()
    presented = _presented_key(authorization)
    if expected is None or presented is None:
        return False
    return hmac.compare_digest(presented, expected)


def warn_if_unconfigured() -> None:
    if configured_api_key() is None:
        logger.warning(
            "MCC_API_KEY is not set or is shorter than %d characters: every "
            "API request except GET /health will be rejected with 401.",
            MIN_API_KEY_LENGTH,
        )


async def api_key_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    if (request.method, request.url.path) in _PUBLIC_ENDPOINTS:
        return await call_next(request)
    if not is_authorized(request.headers.get("authorization")):
        return JSONResponse(
            status_code=401,
            content={"detail": "Not authenticated"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await call_next(request)

