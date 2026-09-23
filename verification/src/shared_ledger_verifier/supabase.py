"""Small authenticated REST client for the local Supabase project."""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


class SupabaseConfigurationError(ValueError):
    """The runner is not pointed at a supported isolated local Supabase URL."""


class SupabaseApiError(RuntimeError):
    """An Auth or PostgREST request failed."""

    def __init__(self, status_code: int, code: str | None, message: str):
        self.status_code = status_code
        self.code = code
        self.message = _safe_error_text(message)
        super().__init__(self.message)


def verification_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_local_env(env_path: str | Path | None = None) -> None:
    """Load the small KEY=value file used by this package, without overriding env."""

    path = Path(env_path) if env_path else verification_root() / ".env"
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] in {"'", '"'} and value[-1:] == value[:1]:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def _validate_config(url: str, anon_key: str) -> tuple[str, str]:
    url = url.strip().rstrip("/")
    anon_key = anon_key.strip()
    try:
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError as exc:
        raise SupabaseConfigurationError("SUPABASE_URL is not a valid local URL") from exc

    if (
        parsed.scheme != "http"
        or hostname not in _LOCAL_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or port is None
    ):
        raise SupabaseConfigurationError(
            "SUPABASE_URL must be a local HTTP endpoint such as http://127.0.0.1:54321"
        )
    if not anon_key:
        raise SupabaseConfigurationError("SUPABASE_ANON_KEY is required")
    lowered = anon_key.lower()
    if "service_role" in lowered or lowered.startswith("sb_secret_"):
        raise SupabaseConfigurationError("SUPABASE_ANON_KEY must not be a service-role/secret key")
    # Legacy Supabase keys are JWTs. Reject a service_role JWT even if it was
    # accidentally placed in the anon-key environment variable.
    parts = anon_key.split(".")
    if len(parts) == 3:
        try:
            payload = parts[1] + "=" * (-len(parts[1]) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        except (ValueError, UnicodeError, json.JSONDecodeError):
            claims = {}
        if isinstance(claims, dict) and claims.get("role") == "service_role":
            raise SupabaseConfigurationError("SUPABASE_ANON_KEY must not contain a service-role JWT")
    return url, anon_key


def _safe_error_text(message: str) -> str:
    """Remove credentials if a proxy or server accidentally echoes them."""

    message = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer [redacted]", str(message))
    message = re.sub(r"\beyJ[A-Za-z0-9_-]{20,}(?:\.[A-Za-z0-9_-]+){1,2}", "[redacted token]", message)
    return message[:500]


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


class SupabaseRestClient:
    """Uses the anon key for Auth and the test user's JWT for every data request."""

    def __init__(self, url: str, anon_key: str, *, timeout: float = 30.0):
        self.url, self.anon_key = _validate_config(url, anon_key)
        self.timeout = timeout
        self.access_token: str | None = None
        self.user_id: str | None = None

    @classmethod
    def from_env(cls, env_path: str | Path | None = None) -> "SupabaseRestClient":
        load_local_env(env_path)
        url = os.environ.get("SUPABASE_URL", "")
        anon_key = os.environ.get("SUPABASE_ANON_KEY", "")
        return cls(url, anon_key)

    def create_test_user(self) -> str:
        """Create a fresh local email/password user using only the anon key."""

        email = f"verifier-{uuid.uuid4().hex}@example.invalid"
        password = secrets.token_urlsafe(32)
        headers = self._headers(use_user_token=False)
        signup = self._request(
            "/auth/v1/signup",
            method="POST",
            headers=headers,
            body={"email": email, "password": password},
        )
        token = signup.get("access_token") if isinstance(signup, dict) else None
        user = signup.get("user", {}) if isinstance(signup, dict) else {}
        if not token:
            # A local project normally disables email confirmations. Use the
            # normal password grant as a fallback when signup omits its session.
            session = self._request(
                "/auth/v1/token?grant_type=password",
                method="POST",
                headers=headers,
                body={"email": email, "password": password},
            )
            token = session.get("access_token") if isinstance(session, dict) else None
            user = session.get("user", {}) if isinstance(session, dict) else {}
        if not isinstance(token, str) or not token:
            raise SupabaseConfigurationError(
                "Local Supabase Auth did not issue a user session; disable email confirmation for local testing"
            )
        if not isinstance(user, dict) or not user.get("id"):
            raise SupabaseConfigurationError("Local Supabase Auth response omitted the test user id")
        self.access_token = token
        self.user_id = str(user["id"])
        return self.user_id

    def rpc(self, name: str, payload: Mapping[str, Any]) -> Any:
        if not _IDENTIFIER.fullmatch(name):
            raise ValueError("invalid RPC name")
        return self._request(
            f"/rest/v1/rpc/{name}",
            method="POST",
            headers=self._headers(use_user_token=True),
            body=dict(payload),
        )

    def select(
        self,
        table: str,
        *,
        filters: Mapping[str, str] | None = None,
        columns: str = "*",
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        if not _IDENTIFIER.fullmatch(table):
            raise ValueError("invalid table name")
        query: dict[str, str] = {"select": columns, "limit": str(limit)}
        for column, expression in (filters or {}).items():
            if not _IDENTIFIER.fullmatch(column):
                raise ValueError("invalid filter column")
            query[column] = expression
        result = self._request(
            f"/rest/v1/{table}?{urlencode(query)}",
            method="GET",
            headers=self._headers(use_user_token=True),
        )
        if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
            raise SupabaseApiError(200, "INVALID_RESPONSE", f"PostgREST select on {table} did not return rows")
        return result

    def close(self) -> None:
        # The local throwaway user's session is deliberately not written to disk
        # or logged. There is no need to invalidate it to complete this run.
        self.access_token = None

    def _headers(self, *, use_user_token: bool) -> dict[str, str]:
        bearer = self.access_token if use_user_token else self.anon_key
        if use_user_token and not bearer:
            raise SupabaseConfigurationError("No authenticated test user session is available")
        return {
            "apikey": self.anon_key,
            "Authorization": f"Bearer {bearer}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(
        self,
        path: str,
        *,
        method: str,
        headers: Mapping[str, str],
        body: Mapping[str, Any] | None = None,
    ) -> Any:
        request_body = None if body is None else json.dumps(body, default=_json_default).encode("utf-8")
        request = Request(
            f"{self.url}{path}",
            data=request_body,
            headers=dict(headers),
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                if not raw:
                    return None
                return json.loads(raw.decode("utf-8"), parse_float=Decimal)
        except HTTPError as exc:
            raw = exc.read()
            code: str | None = None
            message = f"HTTP {exc.code}"
            if raw:
                try:
                    detail = json.loads(raw.decode("utf-8"), parse_float=Decimal)
                    if isinstance(detail, dict):
                        raw_code = detail.get("code") or detail.get("error_code")
                        code = str(raw_code) if raw_code is not None else None
                        message = str(detail.get("message") or detail.get("msg") or detail.get("error_description") or message)
                except (UnicodeError, json.JSONDecodeError):
                    pass
            raise SupabaseApiError(exc.code, code, message) from None
        except (URLError, TimeoutError, OSError) as exc:
            # Do not include Request repr or headers: they contain the bearer JWT.
            reason = getattr(exc, "reason", None)
            message = str(reason) if reason is not None else type(exc).__name__
            raise SupabaseApiError(0, "NETWORK_ERROR", message) from None
