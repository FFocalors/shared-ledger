"""Small standard-library client for DeepSeek chat completions."""

from __future__ import annotations

import json
import math
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .supabase import load_local_env


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"
_CHAT_COMPLETIONS_PATH = "/chat/completions"
_DEFAULT_TIMEOUT = 30.0
_DEFAULT_OPENCODE_GO_TIMEOUT = 120.0
_DEFAULT_MAX_RETRIES = 2
_OPENCODE_GO_HOST = "opencode.ai"
_USER_AGENT = "shared-ledger-verifier/0.2"


class DeepSeekConfigurationError(ValueError):
    """DeepSeek client configuration is missing or invalid."""


class DeepSeekApiError(RuntimeError):
    """A DeepSeek request failed; messages intentionally omit response bodies."""

    def __init__(self, message: str, *, status_code: int | None = None, error_kind: str = "network"):
        self.error_kind = error_kind if error_kind in {"timeout", "network", "http", "invalid_response"} else "network"
        self.status_code = status_code if type(status_code) is int and 100 <= status_code <= 599 else None
        super().__init__(message)


@dataclass(frozen=True)
class TransportResponse:
    """Minimal response shape accepted from an injected test transport."""

    status_code: int
    body: bytes


Transport = Callable[[Request, float], TransportResponse]


def _urlopen_transport(request: Request, timeout: float) -> TransportResponse:
    try:
        with urlopen(request, timeout=timeout) as response:
            return TransportResponse(response.status, response.read())
    except HTTPError as error:
        # HTTPError is also a response. Keep its body in memory for parity with
        # the normal response path, but never expose or log it in exceptions.
        return TransportResponse(error.code, error.read())


def _normalize_base_url(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise DeepSeekConfigurationError("DEEPSEEK_BASE_URL is not a valid URL") from exc

    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise DeepSeekConfigurationError(
            "DEEPSEEK_BASE_URL must be an HTTP(S) base URL without credentials, query, or fragment"
        )
    return value


class DeepSeekClient:
    """Minimal synchronous client for the non-streaming Chat Completions API."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        transport: Transport | None = None,
    ):
        key = api_key.strip()
        if not key:
            raise DeepSeekConfigurationError("DEEPSEEK_API_KEY is required")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise DeepSeekConfigurationError("timeout must be a positive finite number")
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or not 0 <= max_retries <= 5:
            raise DeepSeekConfigurationError("max_retries must be an integer between 0 and 5")
        if not model.strip():
            raise DeepSeekConfigurationError("DEEPSEEK_MODEL must not be empty")

        self._api_key = key
        self.base_url = _normalize_base_url(base_url)
        self.model = model.strip()
        self.timeout = float(timeout)
        self.max_retries = max_retries
        self._transport = transport or _urlopen_transport
        self._opencode_go_endpoint_path = self._get_opencode_go_endpoint_path(self.base_url)
        self._opencode_go_session = (
            f"ses_{uuid.uuid4().hex}" if self._opencode_go_endpoint_path is not None else None
        )

    @staticmethod
    def _get_opencode_go_endpoint_path(base_url: str) -> str | None:
        parsed = urlsplit(base_url)
        if parsed.hostname == _OPENCODE_GO_HOST:
            path = parsed.path.rstrip("/")
            if path == "/zen/go":
                return "/v1/chat/completions"
            if path == "/zen/go/v1":
                return "/chat/completions"
        return None

    @classmethod
    def from_env(
        cls,
        env_path: str | Path | None = None,
        *,
        timeout: float | None = None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        transport: Transport | None = None,
    ) -> "DeepSeekClient":
        """Build a client from DEEPSEEK_* variables and the verifier .env file."""

        load_local_env(env_path)
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        base_url = os.environ.get("DEEPSEEK_BASE_URL", "").strip() or DEFAULT_BASE_URL
        model = os.environ.get("DEEPSEEK_MODEL", "").strip() or DEFAULT_MODEL
        configured_timeout = os.environ.get("DEEPSEEK_TIMEOUT_SECONDS", "").strip()
        if timeout is None and configured_timeout:
            try:
                timeout = float(configured_timeout)
            except ValueError:
                raise DeepSeekConfigurationError("DEEPSEEK_TIMEOUT_SECONDS must be a positive finite number") from None
        if timeout is None:
            base_url = _normalize_base_url(base_url)
            timeout = (
                _DEFAULT_OPENCODE_GO_TIMEOUT
                if cls._get_opencode_go_endpoint_path(base_url) is not None
                else _DEFAULT_TIMEOUT
            )
        return cls(
            api_key,
            base_url=base_url,
            model=model,
            timeout=timeout,
            max_retries=max_retries,
            transport=transport,
        )

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Return the assistant message content for the supplied prompts."""

        if not isinstance(system_prompt, str) or not isinstance(user_prompt, str):
            raise TypeError("system_prompt and user_prompt must be strings")

        request_body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._opencode_go_session is not None:
            headers["User-Agent"] = _USER_AGENT
            headers["x-opencode-session"] = self._opencode_go_session

        request = Request(
            f"{self.base_url}{self._opencode_go_endpoint_path or _CHAT_COMPLETIONS_PATH}",
            data=request_body,
            headers=headers,
            method="POST",
        )

        for attempt in range(self.max_retries + 1):
            try:
                response = self._transport(request, self.timeout)
            except (URLError, TimeoutError, OSError) as error:
                if attempt < self.max_retries:
                    time.sleep(min(0.2 * (2**attempt), 1.0))
                    continue
                kind = "timeout" if isinstance(error, TimeoutError) or (isinstance(error, URLError) and isinstance(error.reason, TimeoutError)) else "network"
                raise DeepSeekApiError("DeepSeek network request failed", error_kind=kind) from None

            if response.status_code < 200 or response.status_code >= 300:
                retryable = response.status_code == 429 or 500 <= response.status_code <= 599
                if retryable and attempt < self.max_retries:
                    time.sleep(min(0.2 * (2**attempt), 1.0))
                    continue
                raise DeepSeekApiError(
                    f"DeepSeek HTTP request failed with status {response.status_code}",
                    status_code=response.status_code,
                    error_kind="http",
                )

            return self._extract_content(response.body)

        # The loop always returns or raises. Keep an explicit fallback for type checkers.
        raise DeepSeekApiError("DeepSeek request failed")

    @staticmethod
    def _extract_content(body: bytes) -> str:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            raise DeepSeekApiError("DeepSeek returned an invalid JSON response", error_kind="invalid_response") from None

        try:
            content = payload["choices"][0]["message"]["content"]
        except (TypeError, KeyError, IndexError):
            raise DeepSeekApiError("DeepSeek response omitted message content", error_kind="invalid_response") from None
        if not isinstance(content, str):
            raise DeepSeekApiError("DeepSeek response omitted message content", error_kind="invalid_response")
        return content
