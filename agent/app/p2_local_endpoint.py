"""Strict local endpoint parsing shared by the P2 provider and token checker.

This policy intentionally recognizes only local loopback addresses and the one
explicit Docker Desktop host alias already supported by the legacy provider.
It performs no DNS lookup, proxy selection, redirect handling, or fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
from urllib.parse import urlsplit


P2_CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
_DECIMAL_PORT = re.compile(r"^[0-9]+$")


@dataclass(frozen=True)
class LocalP2Endpoint:
    """Canonical identity derived from one validated completion URL."""

    endpoint_url: str
    origin: str
    sdk_authority: str
    hostname: str
    port: int


def parse_local_p2_endpoint(value: object) -> LocalP2Endpoint:
    """Validate and canonicalize the exact local OpenAI chat endpoint.

    Omitted HTTP ports mean 80. Host case and IPv6 text are canonicalized, but
    different host identities such as localhost, 127.0.0.1, and
    host.docker.internal are never substituted for one another.
    """
    parsed, hostname, port = _parse_local_http_url(
        value,
        allowed_paths={P2_CHAT_COMPLETIONS_PATH},
        require_explicit_port=False,
    )
    authority_host = f"[{hostname}]" if ":" in hostname else hostname
    sdk_authority = f"{authority_host}:{port}"
    origin = f"http://{sdk_authority}"
    return LocalP2Endpoint(
        endpoint_url=f"{origin}{P2_CHAT_COMPLETIONS_PATH}",
        origin=origin,
        sdk_authority=sdk_authority,
        hostname=hostname,
        port=port,
    )


def normalize_local_p2_endpoint(value: object) -> str:
    """Return a canonical full endpoint URL or raise ``ValueError``."""
    return parse_local_p2_endpoint(value).endpoint_url


def normalize_local_http_origin(value: object) -> str:
    """Return one canonical local HTTP origin with an explicit valid port."""
    _, hostname, port = _parse_local_http_url(
        value,
        allowed_paths={"", "/"},
        require_explicit_port=True,
    )
    authority_host = f"[{hostname}]" if ":" in hostname else hostname
    return f"http://{authority_host}:{port}"


def is_valid_local_http_origin(value: object) -> bool:
    try:
        normalize_local_http_origin(value)
        return True
    except (TypeError, ValueError, UnicodeError):
        return False


def _parse_local_http_url(
    value: object,
    *,
    allowed_paths: set[str],
    require_explicit_port: bool,
) -> tuple[object, str, int]:
    if type(value) is not str or not value or len(value) > 2048:
        raise ValueError("local endpoint is invalid")
    if value != value.strip() or any(
        char.isspace() or ord(char) < 32 or ord(char) == 127 or char in "\\%"
        for char in value
    ):
        raise ValueError("local endpoint contains an invalid character")
    # urlsplit represents a trailing '?' or '#' as an empty query/fragment.
    if "?" in value or "#" in value:
        raise ValueError("local endpoint cannot include query or fragment delimiters")

    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme.casefold() != "http"
            or not parsed.netloc
            or parsed.path not in allowed_paths
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or "@" in parsed.netloc
            or "%" in parsed.netloc
        ):
            raise ValueError("local endpoint has an unsupported URL shape")

        hostname_value = parsed.hostname
        if not hostname_value or "%" in hostname_value:
            # The percent test rejects scoped/zone IPv6 and encoded hostnames.
            raise ValueError("local endpoint host is invalid")
        hostname_value = hostname_value.casefold()
        if hostname_value in {"localhost", "host.docker.internal"}:
            hostname = hostname_value
        else:
            address = ipaddress.ip_address(hostname_value)
            if not address.is_loopback:
                raise ValueError("local endpoint must use a loopback IP literal")
            hostname = address.compressed.casefold()

        raw_port = _raw_port(parsed.netloc, hostname)
        if raw_port is None:
            if require_explicit_port:
                raise ValueError("origin port must be explicit")
            port = 80
        else:
            if not _DECIMAL_PORT.fullmatch(raw_port):
                raise ValueError("local endpoint port must be decimal")
            port = int(raw_port, 10)
            if not 1 <= port <= 65535 or raw_port != str(port):
                raise ValueError("local endpoint port is out of range or noncanonical")

        # Accessing parsed.port also rejects values outside Python's URL range.
        if parsed.port is not None and parsed.port != port:
            raise ValueError("local endpoint port parse mismatch")
        return parsed, hostname, port
    except (UnicodeError, ValueError) as exc:
        if str(exc).startswith("local endpoint") or str(exc).startswith("origin port"):
            raise
        raise ValueError("local endpoint is not an allowed local HTTP URL") from None


def _raw_port(netloc: str, hostname: str) -> str | None:
    if ":" in hostname:
        if not netloc.startswith("["):
            raise ValueError("IPv6 endpoint must use brackets")
        closing = netloc.find("]")
        if closing < 0:
            raise ValueError("IPv6 endpoint bracket is not closed")
        raw_host = netloc[1:closing]
        suffix = netloc[closing + 1:]
        try:
            parsed_host = ipaddress.ip_address(raw_host)
        except ValueError:
            raise ValueError("IPv6 endpoint literal is invalid") from None
        if parsed_host.version != 6 or parsed_host.compressed.casefold() != hostname:
            raise ValueError("IPv6 endpoint literal is noncanonical or invalid")
        if not suffix:
            return None
        if not suffix.startswith(":") or suffix.count(":") != 1:
            raise ValueError("IPv6 endpoint authority is malformed")
        raw_port = suffix[1:]
        if not raw_port:
            raise ValueError("local endpoint has an empty port")
        return raw_port

    if netloc.count(":") > 1:
        raise ValueError("local endpoint authority has ambiguous colons")
    if ":" not in netloc:
        if netloc.casefold() != hostname:
            raise ValueError("local endpoint authority host does not match")
        return None
    raw_host, raw_port = netloc.rsplit(":", 1)
    if raw_host.casefold() != hostname:
        raise ValueError("local endpoint authority host does not match")
    if not raw_port:
        raise ValueError("local endpoint has an empty port")
    return raw_port
