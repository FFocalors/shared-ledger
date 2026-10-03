"""Bounded OpenAI-compatible live provider adapter for explicitly authorized pilots."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ADAPTER_VERSION = "0.1.2"
USER_AGENT = "shared-ledger-teacher-generator/0.1.2"


class LiveProviderError(RuntimeError):
    def __init__(self, kind: str, message: str, *, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.retryable = retryable


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model: str
    api_key: str
    base_url: str
    temperature: float


def load_env(path: Path) -> ProviderConfig:
    """Load simple KEY=VALUE configuration without printing or logging values."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise LiveProviderError("config", "Invalid provider configuration line.")
        key, value = stripped.split("=", 1)
        key, value = key.strip(), value.strip()
        if key in values:
            raise LiveProviderError("config", "Duplicate provider configuration key.")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    required = ("TEACHER_PROVIDER", "TEACHER_MODEL", "TEACHER_API_KEY", "TEACHER_BASE_URL", "TEACHER_TEMPERATURE")
    if any(not values.get(key, "").strip() for key in required):
        raise LiveProviderError("config", "Required provider configuration is missing.")
    try:
        temperature = float(values["TEACHER_TEMPERATURE"])
    except ValueError as exc:
        raise LiveProviderError("config", "Temperature configuration is invalid.") from exc
    if not 0 <= temperature <= 2:
        raise LiveProviderError("config", "Temperature must be between 0 and 2.")
    if values["TEACHER_PROVIDER"].lower() not in {"opencode", "openai-compatible", "openai", "deepseek"}:
        raise LiveProviderError("config", "Provider does not have a supported compatible adapter.")
    return ProviderConfig(
        provider=values["TEACHER_PROVIDER"],
        model=values["TEACHER_MODEL"],
        api_key=values["TEACHER_API_KEY"],
        base_url=values["TEACHER_BASE_URL"].rstrip("/"),
        temperature=temperature,
    )


def _endpoint(config: ProviderConfig) -> str:
    # OpenCode Go documents chat-completions models at /zen/go/v1/chat/completions.
    # Other compatible providers can configure either a versioned base or full path.
    base = config.base_url.rstrip("/")
    lowered = base.lower()
    if lowered.endswith("/chat/completions"):
        return base
    if lowered.endswith("/zen/go"):
        return base + "/v1/chat/completions"
    if lowered.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def _redact(text: str, secret: str) -> str:
    return text.replace(secret, "[REDACTED]") if secret else text


def request_completion(config: ProviderConfig, request: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
    """Make one request and return sanitized transport metadata plus raw body."""
    payload = {
        "model": config.model,
        "messages": request["teacher_payload"]["messages"],
        "temperature": config.temperature,
        "response_format": {"type": "json_object"},
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        _endpoint(config),
        data=body,
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "x-opencode-session": request.get("local_trace", {}).get("opencode_session_id") or request.get("run_id", "teacher-generator-run"),
        },
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return {
                "http_status": response.status,
                "duration_seconds": round(time.monotonic() - started, 3),
                "raw_response": _redact(raw, config.api_key),
                "headers_recorded": False,
            }
    except urllib.error.HTTPError as exc:
        # Do not serialize the exception or request; it may contain private headers.
        raw = exc.read().decode("utf-8", errors="replace")
        status = int(exc.code)
        raise LiveProviderError(
            "http_error",
            _redact(raw[:2000], config.api_key),
            status=status,
            retryable=status in {408, 409, 425, 429} or status >= 500,
        ) from None
    except (TimeoutError, urllib.error.URLError) as exc:
        reason = getattr(exc, "reason", None)
        kind = "timeout" if isinstance(reason, TimeoutError) or isinstance(exc, TimeoutError) else "transport_error"
        raise LiveProviderError(kind, "Provider request failed before an HTTP response.", retryable=True) from None


def parse_completion(raw_response: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        envelope = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise LiveProviderError("provider_json_error", "Provider response was not valid JSON.") from exc
    if not isinstance(envelope, dict):
        raise LiveProviderError("provider_schema_error", "Provider response envelope was not an object.")
    if envelope.get("error"):
        # Keep only a bounded, key-redacted provider message in the local audit.
        err = envelope.get("error")
        if isinstance(err, dict):
            message = str(err.get("message", "Provider returned an error."))[:1000]
        else:
            message = "Provider returned an error."
        raise LiveProviderError("provider_error", message)
    choices = envelope.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise LiveProviderError("provider_schema_error", "Provider response has no completion choice.")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise LiveProviderError("provider_schema_error", "Provider completion content is not text.")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LiveProviderError("response_json_error", "Completion content was not valid JSON.") from exc
    usage = envelope.get("usage") if isinstance(envelope.get("usage"), dict) else {}
    return parsed, {
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "provider_cost": usage.get("cost", envelope.get("cost")),
    }
