from __future__ import annotations

import base64
import io
import json
import urllib.error
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent.app import auth
from agent.app.auth import AuthDependencyUnavailable, SupabaseAuthVerifier, Unauthenticated
from agent.app.settings import Settings
from pydantic import SecretStr, ValidationError


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _token(claim_overrides: dict[str, Any] | None = None) -> tuple[str, uuid.UUID]:
    user_id = uuid.uuid4()
    claims: dict[str, Any] = {
        "sub": str(user_id), "role": "authenticated", "aud": "authenticated",
        "is_anonymous": False, "exp": datetime.now(timezone.utc).timestamp() + 600,
        "iat": datetime.now(timezone.utc).timestamp(),
    }
    claims.update(claim_overrides or {})
    return _b64(b'{"alg":"ES256","kid":"local-test","typ":"JWT"}') + "." + _b64(
        json.dumps(claims, separators=(",", ":"), allow_nan=True).encode()
    ) + ".untrusted-signature", user_id


class _Response:
    status = 200

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.closed = False

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def read(self, maximum: int) -> bytes:
        return self.body[:maximum]

    def close(self) -> None:
        self.closed = True


class _Opener:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.request = None
        self.timeout = None

    def open(self, request: Any, *, timeout: float) -> _Response:
        self.request = request
        self.timeout = timeout
        if isinstance(self.result, BaseException):
            raise self.result
        return _Response(self.result)


def _valid_user(user_id: uuid.UUID, **changes: Any) -> bytes:
    user = {"id": str(user_id), "aud": "authenticated", "role": "authenticated",
            "is_anonymous": False, "banned_until": None, "deleted_at": None}
    user.update(changes)
    return json.dumps(user, separators=(",", ":")).encode()


def _mock_opener(monkeypatch: pytest.MonkeyPatch, result: Any) -> tuple[_Opener, list[Any]]:
    opener = _Opener(result)
    handlers: list[Any] = []
    def build(*items: Any) -> _Opener:
        handlers.extend(items)
        return opener
    monkeypatch.setattr(auth.urllib.request, "build_opener", build)
    return opener, handlers


def _verifier() -> SupabaseAuthVerifier:
    return SupabaseAuthVerifier("https://auth.example.test/auth/v1", SecretStr("sb_publishable_test"))


def test_remote_user_is_the_identity_authority_and_proxy_redirect_are_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    token, user_id = _token()
    opener, handlers = _mock_opener(monkeypatch, _valid_user(user_id))
    principal = _verifier().verify_bearer(token)
    assert principal.user_id == user_id
    assert len(handlers) == 2
    assert isinstance(handlers[0], auth.urllib.request.ProxyHandler)
    assert handlers[0].proxies == {}
    assert type(handlers[1]).__name__ == "_NoRedirect"
    assert opener.request.full_url == "https://auth.example.test/auth/v1/user"
    assert opener.request.get_method() == "GET"
    assert opener.request.get_header("Authorization") == "Bearer " + token
    assert opener.timeout == 3.0


@pytest.mark.parametrize("claims,user_change", [
    ({"role": "service_role"}, {}),
    ({"role": "anon"}, {}),
    ({"aud": "anon"}, {}),
    ({"is_anonymous": True}, {}),
    ({"exp": 1}, {}),
    ({"iat": float("inf")}, {}),
    ({"nbf": datetime.now(timezone.utc).timestamp() + 300}, {}),
    ({}, {"is_anonymous": True}),
    ({}, {"deleted_at": "2026-10-08T00:00:00Z"}),
    ({}, {"role": "service_role"}),
    ({}, {"aud": "anon"}),
    ({}, {"banned_until": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}),
])
def test_untrusted_or_ineligible_user_claims_are_rejected(monkeypatch: pytest.MonkeyPatch, claims: dict[str, Any], user_change: dict[str, Any]) -> None:
    token, user_id = _token(claims)
    _mock_opener(monkeypatch, _valid_user(user_id, **user_change))
    with pytest.raises(Unauthenticated):
        _verifier().verify_bearer(token)


@pytest.mark.parametrize("code,expected", [
    (400, Unauthenticated), (401, Unauthenticated), (403, Unauthenticated),
    (302, AuthDependencyUnavailable), (500, AuthDependencyUnavailable),
])
def test_remote_http_statuses_are_sanitized_and_http_errors_are_closed(monkeypatch: pytest.MonkeyPatch, code: int, expected: type[Exception]) -> None:
    token, _ = _token()
    error = urllib.error.HTTPError("https://auth.example.test/auth/v1/user", code, "private", {}, io.BytesIO(b"private"))
    opener, _ = _mock_opener(monkeypatch, error)
    with pytest.raises(expected) as captured:
        _verifier().verify_bearer(token)
    assert "private" not in str(captured.value)
    assert error.fp is None or error.fp.closed


@pytest.mark.parametrize("failure", [
    urllib.error.URLError("private endpoint"), TimeoutError("private timeout"), OSError("private socket"),
])
def test_network_failures_are_dependency_errors_not_invalid_identity(monkeypatch: pytest.MonkeyPatch, failure: BaseException) -> None:
    token, _ = _token()
    _mock_opener(monkeypatch, failure)
    with pytest.raises(AuthDependencyUnavailable) as captured:
        _verifier().verify_bearer(token)
    assert "private" not in str(captured.value)


@pytest.mark.parametrize("body", [
    pytest.param(b"{", id="truncated"),
    pytest.param(b"[]", id="array"),
    pytest.param(b'{"id":"a","id":"b"}', id="duplicate-key"),
    pytest.param(b'{"id":NaN}', id="nonfinite"),
    pytest.param(b"x" * (262_145), id="oversized"),
])
def test_malformed_or_oversized_auth_response_fails_closed(monkeypatch: pytest.MonkeyPatch, body: bytes) -> None:
    token, _ = _token()
    _mock_opener(monkeypatch, body)
    with pytest.raises(AuthDependencyUnavailable):
        _verifier().verify_bearer(token)


def test_remote_identity_must_match_verified_jwt_subject(monkeypatch: pytest.MonkeyPatch) -> None:
    token, _ = _token()
    _mock_opener(monkeypatch, _valid_user(uuid.uuid4()))
    with pytest.raises(Unauthenticated):
        _verifier().verify_bearer(token)


@pytest.mark.parametrize("overrides", [
    {"supabase_api_key": "sb_secret_not-for-users"},
    {"supabase_api_key": "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.signature"},
    {"supabase_auth_base_url": "http://auth.example.test", "allow_insecure_loopback_auth_http": True},
    {"supabase_auth_base_url": "https://user:pass@auth.example.test"},
    {"supabase_auth_base_url": "https://auth.example.test:99999"},
])
def test_settings_reject_privileged_keys_and_untrusted_auth_endpoints(tmp_path: Path, overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Settings(storage_path=tmp_path / "store.sqlite", **overrides)


def test_loopback_http_auth_requires_explicit_development_opt_in(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        Settings(storage_path=tmp_path / "store.sqlite", supabase_auth_base_url="http://127.0.0.1:54321")
    settings = Settings(storage_path=tmp_path / "store.sqlite", supabase_auth_base_url="http://127.0.0.1:54321",
                        allow_insecure_loopback_auth_http=True)
    assert settings.supabase_auth_base_url == "http://127.0.0.1:54321"


def test_env_example_parses_without_creating_storage_and_unconfigured_auth_keeps_health_available(tmp_path: Path) -> None:
    example = Path(__file__).resolve().parents[1] / ".env.example"
    settings = Settings(_env_file=example)
    assert settings.supabase_auth_base_url is None
    assert settings.supabase_api_key is None
    assert settings.cursor_signing_secret is None
    assert not settings.storage_path.exists()

    from agent.app.main import create_app

    with pytest.raises(ValidationError):
        Settings(_env_file=None, storage_path="")
    app_settings = Settings(storage_path=tmp_path / "health-only.sqlite3")
    with TestClient(create_app(app_settings)) as client:
        assert client.get("/health/live").status_code == 200
        unavailable = client.get("/v1/sessions", headers={"Authorization": "Bearer ignored"})
        assert unavailable.status_code == 503
        assert unavailable.json()["code"] == "dependency_unavailable"
