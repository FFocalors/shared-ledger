from __future__ import annotations

import pytest

from agent.app.p2_local_endpoint import (
    is_valid_local_http_origin,
    normalize_local_http_origin,
    normalize_local_p2_endpoint,
    parse_local_p2_endpoint,
)


@pytest.mark.parametrize(
    ("value", "endpoint_url", "origin", "sdk_authority"),
    [
        (
            "http://127.0.0.1:1234/v1/chat/completions",
            "http://127.0.0.1:1234/v1/chat/completions",
            "http://127.0.0.1:1234",
            "127.0.0.1:1234",
        ),
        (
            "HTTP://LOCALHOST:1234/v1/chat/completions",
            "http://localhost:1234/v1/chat/completions",
            "http://localhost:1234",
            "localhost:1234",
        ),
        (
            "http://HOST.DOCKER.INTERNAL:1234/v1/chat/completions",
            "http://host.docker.internal:1234/v1/chat/completions",
            "http://host.docker.internal:1234",
            "host.docker.internal:1234",
        ),
        (
            "http://[0:0:0:0:0:0:0:1]:1234/v1/chat/completions",
            "http://[::1]:1234/v1/chat/completions",
            "http://[::1]:1234",
            "[::1]:1234",
        ),
        (
            "http://127.0.0.1/v1/chat/completions",
            "http://127.0.0.1:80/v1/chat/completions",
            "http://127.0.0.1:80",
            "127.0.0.1:80",
        ),
    ],
)
def test_allowed_endpoints_have_one_canonical_endpoint_origin_and_sdk_authority(
    value: str,
    endpoint_url: str,
    origin: str,
    sdk_authority: str,
) -> None:
    parsed = parse_local_p2_endpoint(value)
    assert parsed.endpoint_url == endpoint_url
    assert parsed.origin == origin
    assert parsed.sdk_authority == sdk_authority
    assert normalize_local_p2_endpoint(value) == endpoint_url
    assert normalize_local_http_origin(origin) == origin


def test_default_port_and_host_identity_rules_are_explicit() -> None:
    assert normalize_local_p2_endpoint("http://localhost/v1/chat/completions") == (
        "http://localhost:80/v1/chat/completions"
    )
    assert normalize_local_http_origin("http://LOCALHOST:80/") == "http://localhost:80"
    assert normalize_local_p2_endpoint("http://localhost:1234/v1/chat/completions") != (
        normalize_local_p2_endpoint("http://127.0.0.1:1234/v1/chat/completions")
    )
    assert normalize_local_p2_endpoint("http://127.0.0.1:1234/v1/chat/completions") != (
        normalize_local_p2_endpoint("http://host.docker.internal:1234/v1/chat/completions")
    )
    assert normalize_local_p2_endpoint("http://localhost/v1/chat/completions") == (
        normalize_local_p2_endpoint("http://localhost:80/v1/chat/completions")
    )


@pytest.mark.parametrize(
    "value",
    [
        "",
        " https://127.0.0.1:1234/v1/chat/completions",
        "https://127.0.0.1:1234/v1/chat/completions",
        "http://lmstudio:1234/v1/chat/completions",
        "http://example.com/v1/chat/completions",
        "http://192.168.1.4:1234/v1/chat/completions",
        "http://10.0.0.2:1234/v1/chat/completions",
        "http://8.8.8.8:1234/v1/chat/completions",
        "http://localhost.:1234/v1/chat/completions",
        "http://localhost:1234.evil/v1/chat/completions",
        "http://user@localhost:1234/v1/chat/completions",
        "http://user:password@localhost:1234/v1/chat/completions",
        "http://localhost:1234/v1/chat/completions?x=1",
        "http://localhost:1234/v1/chat/completions?",
        "http://localhost:1234/v1/chat/completions#fragment",
        "http://localhost:1234/v1/chat/completions#",
        "http://localhost:1234/v1/models",
        "http://localhost:1234/v1/chat/completions/",
        "http://localhost:1234:/v1/chat/completions",
        "http://localhost:0/v1/chat/completions",
        "http://localhost:65536/v1/chat/completions",
        "http://localhost:abc/v1/chat/completions",
        "http://localhost:01234/v1/chat/completions",
        "http://[fe80::1%25eth0]:1234/v1/chat/completions",
        "http://[::ffff:127.0.0.1]:1234/v1/chat/completions",
        "http://::1:1234/v1/chat/completions",
        "http://[::1/v1/chat/completions",
        "http://localhost%2e:1234/v1/chat/completions",
        "http://localhost\\@127.0.0.1:1234/v1/chat/completions",
        "http://local host:1234/v1/chat/completions",
    ],
)
def test_malformed_or_nonlocal_completion_urls_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_local_p2_endpoint(value)


@pytest.mark.parametrize(
    "value",
    [
        "http://localhost",
        "http://localhost:",
        "http://localhost:0",
        "http://localhost:65536",
        "http://localhost:01234",
        "http://lmstudio:1234",
        "http://192.168.1.4:1234",
        "https://localhost:1234",
        "http://localhost:1234/v1/chat/completions",
        "http://localhost:1234/?",
        "http://localhost:1234/#",
    ],
)
def test_checker_requires_explicit_clean_local_origin(value: str) -> None:
    assert not is_valid_local_http_origin(value)


def test_checker_origin_canonicalizes_case_and_optional_single_slash() -> None:
    assert is_valid_local_http_origin("HTTP://HOST.DOCKER.INTERNAL:1234/")
    assert normalize_local_http_origin("HTTP://HOST.DOCKER.INTERNAL:1234/") == (
        "http://host.docker.internal:1234"
    )
