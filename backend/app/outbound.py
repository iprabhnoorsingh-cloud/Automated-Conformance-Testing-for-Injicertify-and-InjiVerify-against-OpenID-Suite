"""M10: outbound-destination (SSRF) policy for user-supplied URLs.

Test-run configuration lets a caller name hosts that the conformance
tooling will contact (Inji test-rig `env_endpoint` / `*_base_url` fields and
any URL inside an OpenID plan configuration). This module decides whether
such a destination is acceptable.

Policy
------
* Schemes: only `http` and `https` (what the OpenID/Inji integrations use).
* No userinfo (`user:pass@host`), no whitespace/control characters, no
  backslashes, valid port only.
* The host must be a public address. Rejected: loopback, RFC1918 private,
  link-local (incl. 169.254.169.254 metadata), CGNAT, unspecified,
  multicast, reserved and other non-global ranges, for IPv4 and IPv6 —
  including IPv4-mapped / NAT64 / 6to4 / Teredo IPv6 forms and unusual
  IPv4 spellings (`2130706433`, `0x7f.1`, `017700000001`, `127.1`).
* Names such as `localhost`, `*.localhost`, `*.local`, `*.internal` are
  rejected without DNS.
* With `resolve=True` the hostname is resolved and EVERY returned address
  must be public (an unresolvable host is rejected: fail closed).

Limitations (also documented in docs/architecture.md)
-----------------------------------------------------
This is a check at one moment in time. The actual connections are made
later by external processes this application does not control (the Inji
Java test rigs and the OpenID Conformance Suite). They resolve DNS again
and may follow redirects themselves, so DNS rebinding (a name that resolves
to a public address now and a private one later) and redirects to internal
hosts are NOT prevented here. Complete SSRF prevention requires network
egress controls (firewall / network namespace) around those processes.
"""

import ipaddress
import re
import socket
from typing import Any, Callable, Iterator, List, Optional, Tuple
from urllib.parse import urlsplit

ALLOWED_SCHEMES = frozenset({"http", "https"})

# Suite-config field names whose values are destinations. A bare host
# (no scheme) is accepted for these and treated as https.
URL_FIELD_NAMES = frozenset(
    {
        "env_endpoint",
        "esignet_base_url",
        "inji_certify_base_url",
        "mosip_components_base_urls",
        "sunbird_base_url",
        "inji_verify_base_url",
    }
)

_BLOCKED_HOSTNAMES = frozenset({"localhost"})
_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".localdomain")

# Any `scheme://...` token inside free text (multi-URL fields, plan config).
_URL_IN_TEXT = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://[^\s$,;|\"'<>]+")
_NUMERIC_IPV4_SPELLING = re.compile(
    r"^(0[xX][0-9a-fA-F]+|\d+)(\.(0[xX][0-9a-fA-F]+|\d+)){0,3}$"
)
_UNSAFE_CHARS = re.compile(r"[\x00-\x20\x7f\\]")

Resolver = Callable[[str, Optional[int]], List[str]]


class UnsafeDestinationError(ValueError):
    """A destination was rejected. Messages never contain the URL itself
    (it could carry credentials); they carry only a reason."""


def _default_resolver(host: str, port: Optional[int]) -> List[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({info[4][0].split("%")[0] for info in infos})


def _embedded_ipv4(ip: ipaddress.IPv6Address) -> List[ipaddress.IPv4Address]:
    found: List[ipaddress.IPv4Address] = []
    if ip.ipv4_mapped is not None:
        found.append(ip.ipv4_mapped)
    if ip.sixtofour is not None:
        found.append(ip.sixtofour)
    if ip.teredo is not None:
        found.extend(ip.teredo)
    if ip in ipaddress.ip_network("64:ff9b::/96"):  # NAT64
        found.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return found


def _is_public(ip: Any) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        if not all(_is_public(v4) for v4 in _embedded_ipv4(ip)):
            return False
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_unspecified
        or ip.is_multicast
        or ip.is_reserved
        or (isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local)
    ):
        return False
    return bool(ip.is_global)


def _parse_ip_literal(host: str) -> Optional[Any]:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    if _NUMERIC_IPV4_SPELLING.match(host):
        try:
            return ipaddress.IPv4Address(socket.inet_aton(host))
        except OSError:
            raise UnsafeDestinationError("host is a malformed numeric address")
    return None


def validate_outbound_url(
    value: str,
    *,
    resolve: bool = True,
    resolver: Optional[Resolver] = None,
    allow_bare_host: bool = True,
) -> None:
    """Raise UnsafeDestinationError unless `value` is an acceptable
    destination. See the module docstring for the policy."""
    if not isinstance(value, str) or not value.strip():
        raise UnsafeDestinationError("destination is empty")
    text = value.strip()
    if _UNSAFE_CHARS.search(text):
        raise UnsafeDestinationError("destination contains whitespace/control characters")

    if "://" not in text:
        if not allow_bare_host:
            raise UnsafeDestinationError("destination has no scheme")
        text = "https://" + text

    try:
        parts = urlsplit(text)
        port = parts.port
        hostname = parts.hostname
    except ValueError:
        raise UnsafeDestinationError("destination is not a valid URL")

    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeDestinationError("scheme is not allowed (only http/https)")
    if "@" in parts.netloc:
        raise UnsafeDestinationError("userinfo in the URL is not allowed")
    if port == 0:
        raise UnsafeDestinationError("port is not valid")
    if not hostname:
        raise UnsafeDestinationError("destination has no host")
    if "%" in hostname:
        raise UnsafeDestinationError("host contains an invalid character")

    host = hostname.rstrip(".").lower()
    if not host:
        raise UnsafeDestinationError("destination has no host")

    literal = _parse_ip_literal(host)
    if literal is not None:
        if not _is_public(literal):
            raise UnsafeDestinationError("destination address is not publicly routable")
        return

    if host in _BLOCKED_HOSTNAMES or host.endswith(_BLOCKED_HOST_SUFFIXES):
        raise UnsafeDestinationError("destination host name is internal/local")
    try:
        host.encode("idna")
    except UnicodeError:
        raise UnsafeDestinationError("host name is not valid")

    if not resolve:
        return

    lookup = resolver or _default_resolver
    try:
        addresses = lookup(host, port)
    except OSError:
        raise UnsafeDestinationError("host name could not be resolved")
    if not addresses:
        raise UnsafeDestinationError("host name could not be resolved")
    for address in addresses:
        try:
            resolved = ipaddress.ip_address(address)
        except ValueError:
            raise UnsafeDestinationError("host resolved to an invalid address")
        if not _is_public(resolved):
            raise UnsafeDestinationError("host resolves to a non-public address")


def iter_outbound_urls(config: Any, location: str = "") -> Iterator[Tuple[str, str]]:
    """Yield (location, candidate) for every destination in a suite config.

    Known URL fields are always treated as destinations; any other string
    anywhere in the structure (e.g. inside an OpenID plan_configuration) is
    treated as one when it contains a `scheme://` token.
    """
    if isinstance(config, dict):
        for key, value in config.items():
            where = f"{location}.{key}" if location else str(key)
            if key in URL_FIELD_NAMES and isinstance(value, str):
                matches = _URL_IN_TEXT.findall(value)
                for match in matches:
                    yield where, match
                if not matches and value.strip():
                    yield where, value
            else:
                yield from iter_outbound_urls(value, where)
    elif isinstance(config, (list, tuple)):
        for index, item in enumerate(config):
            yield from iter_outbound_urls(item, f"{location}[{index}]")
    elif isinstance(config, str):
        for match in _URL_IN_TEXT.findall(config):
            yield location, match


def validate_suite_config_urls(
    suite_config: Any,
    *,
    resolve: bool,
    resolver: Optional[Resolver] = None,
) -> None:
    """Validate every destination in one suite config; the raised message
    names the offending field and reason, never the URL value."""
    for location, candidate in iter_outbound_urls(suite_config):
        try:
            validate_outbound_url(candidate, resolve=resolve, resolver=resolver)
        except UnsafeDestinationError as exc:
            raise UnsafeDestinationError(f"{location}: {exc}") from None

