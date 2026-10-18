"""Supabase Auth verification and safe identity extraction for P1-04."""

from __future__ import annotations

import base64
import binascii
import json
import math
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

from pydantic import SecretStr

from .ports import Principal
from .settings import Settings


class Unauthenticated(RuntimeError):
    """A missing, malformed, expired, revoked, anonymous or privileged token."""


class AuthDependencyUnavailable(RuntimeError):
    """Auth is not configured or its trusted verification endpoint is unavailable."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise ValueError("non-standard JSON number")


def _decode_validated_claims(token: str) -> dict[str, Any]:
    """Decode claims only after Auth `/user` has cryptographically verified the token.

    This is deliberately not a local JWT verifier. Supabase Auth validates the
    signature according to its current signing configuration (HS256 or asymmetric)
    before this function reads claims for application policy checks.
    """
    parts = token.split(".")
    if len(parts) != 3 or not parts[1] or len(parts[1]) > 16_384:
        raise Unauthenticated("invalid bearer token") from None
    try:
        encoded = parts[1].encode("ascii")
        payload = base64.urlsafe_b64decode(encoded + b"=" * (-len(encoded) % 4))
        claims = json.loads(payload, object_pairs_hook=_unique_json_object, parse_constant=_reject_json_constant)
    except (UnicodeError, ValueError, binascii.Error, json.JSONDecodeError):
        raise Unauthenticated("invalid bearer token") from None
    if not isinstance(claims, dict):
        raise Unauthenticated("invalid bearer token") from None
    return claims


def _claim_audience_is_authenticated(value: object) -> bool:
    # Supabase's Auth user access token uses the exact `authenticated` audience.
    # In particular, `anon` is a valid Postgres role but is not a signed-in user.
    return value == "authenticated"


class SupabaseAuthVerifier:
    """Validate a Bearer token by asking the configured Supabase Auth `/user` API.

    Endpoint configuration is fixed at construction. Requests do not honor ambient
    HTTP(S)_PROXY settings and do not follow redirects, so a token cannot be sent to a
    redirect target or to a process-wide proxy by accident.
    """

    _MAX_RESPONSE_BYTES = 262_144
    _MAX_TOKEN_BYTES = 16_384

    def __init__(
        self,
        auth_base_url: str | None,
        api_key: SecretStr | None,
        *,
        timeout_seconds: float = 3.0,
    ) -> None:
        self._api_key = api_key
        self._timeout = max(0.1, min(timeout_seconds, 10.0))
        self._user_url: str | None = None
        if auth_base_url:
            parsed = urlsplit(auth_base_url)
            path = parsed.path.rstrip("/")
            if path in ("", "/"):
                path = "/auth/v1"
            self._user_url = parsed._replace(path=path + "/user", query="", fragment="").geturl()

    @classmethod
    def from_settings(cls, settings: Settings) -> "SupabaseAuthVerifier":
        return cls(settings.supabase_auth_base_url, settings.supabase_api_key)

    @property
    def configured(self) -> bool:
        return bool(self._user_url and self._api_key and self._api_key.get_secret_value())

    def verify_bearer(self, access_token: str) -> Principal:
        if not self.configured:
            raise AuthDependencyUnavailable("Supabase Auth is not configured") from None
        if not isinstance(access_token, str) or not access_token or len(access_token.encode("utf-8", "ignore")) > self._MAX_TOKEN_BYTES:
            raise Unauthenticated("invalid bearer token") from None
        if any(ord(char) < 33 or ord(char) == 127 for char in access_token):
            raise Unauthenticated("invalid bearer token") from None
        assert self._user_url is not None
        assert self._api_key is not None

        request = urllib.request.Request(
            self._user_url,
            method="GET",
            headers={
                "Accept": "application/json",
                "apikey": self._api_key.get_secret_value(),
                "Authorization": "Bearer " + access_token,
            },
        )
        # ProxyHandler({}) is intentional. This request contains a user's access
        # token and must go only to the configured, validated Supabase endpoint.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        try:
            with opener.open(request, timeout=self._timeout) as response:
                status = int(response.status)
                if status != 200:
                    raise AuthDependencyUnavailable("Auth verification service returned an unexpected response") from None
                raw = response.read(self._MAX_RESPONSE_BYTES + 1)
                if len(raw) > self._MAX_RESPONSE_BYTES:
                    raise AuthDependencyUnavailable("Auth verification service returned an oversized response") from None
        except urllib.error.HTTPError as exc:
            # Never include an upstream body or URL in errors; they can contain
            # credential material and are not part of the client contract.
            code = exc.code
            try:
                exc.close()
            except Exception:
                pass
            if code in (400, 401, 403):
                raise Unauthenticated("invalid bearer token") from None
            raise AuthDependencyUnavailable("Auth verification service is unavailable") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise AuthDependencyUnavailable("Auth verification service is unavailable") from None
        except AuthDependencyUnavailable:
            raise

        try:
            user = json.loads(raw, object_pairs_hook=_unique_json_object, parse_constant=_reject_json_constant)
        except (UnicodeError, ValueError, json.JSONDecodeError):
            raise AuthDependencyUnavailable("Auth verification service returned malformed JSON") from None
        if not isinstance(user, dict):
            raise AuthDependencyUnavailable("Auth verification service returned malformed user data") from None

        # The HTTP Auth API has now verified the signature and live user record.
        # Claims are inspected only after that server-side validation succeeds.
        claims = _decode_validated_claims(access_token)
        try:
            user_id = uuid.UUID(user.get("id"))
            subject = uuid.UUID(claims.get("sub"))
        except (TypeError, ValueError, AttributeError):
            raise Unauthenticated("invalid bearer token") from None
        if user_id != subject:
            raise Unauthenticated("invalid bearer token") from None
        if user.get("role") != "authenticated" or not _claim_audience_is_authenticated(user.get("aud")):
            raise Unauthenticated("signed-in user required") from None
        if user.get("is_anonymous") is True:
            raise Unauthenticated("permanent signed-in user required") from None
        if user.get("deleted_at") not in (None, ""):
            raise Unauthenticated("user is not allowed to sign in") from None
        if claims.get("role") != "authenticated" or not _claim_audience_is_authenticated(claims.get("aud")):
            raise Unauthenticated("signed-in user required") from None
        if claims.get("is_anonymous") is not False:
            raise Unauthenticated("permanent signed-in user required") from None
        self._validate_times(claims)
        self._validate_ban(user)
        expires_at = datetime.fromtimestamp(float(claims["exp"]), timezone.utc)
        return Principal(user_id=user_id, expires_at=expires_at)

    @staticmethod
    def _validate_times(claims: dict[str, Any]) -> None:
        now = time.time()
        expires = claims.get("exp")
        issued = claims.get("iat")
        not_before = claims.get("nbf")
        if (
            isinstance(expires, bool)
            or not isinstance(expires, (int, float))
            or isinstance(issued, bool)
            or not isinstance(issued, (int, float))
            or not math.isfinite(expires)
            or not math.isfinite(issued)
            or expires <= now
            or issued > now + 60
            or (not_before is not None and (
                isinstance(not_before, bool) or not isinstance(not_before, (int, float))
                or not math.isfinite(not_before) or not_before > now
            ))
        ):
            raise Unauthenticated("invalid bearer token") from None

    @staticmethod
    def _validate_ban(user: dict[str, Any]) -> None:
        banned_until = user.get("banned_until")
        if banned_until in (None, ""):
            return
        if not isinstance(banned_until, str):
            raise AuthDependencyUnavailable("Auth verification service returned malformed user data") from None
        try:
            parsed = datetime.fromisoformat(banned_until.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("timezone required")
        except ValueError:
            raise AuthDependencyUnavailable("Auth verification service returned malformed user data") from None
        if parsed.astimezone(timezone.utc) > datetime.now(timezone.utc):
            raise Unauthenticated("user is not allowed to sign in") from None
