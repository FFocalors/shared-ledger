"""P2 LM Studio adapter for the OpenAI-compatible chat endpoint.

Production assembly is opt-in and fail-closed: it starts disabled and requires
an explicit artifact-bound token budget checker before any HTTP dispatch. The
Harness remains authoritative for semantic validation and bounded repair.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
import hashlib
import http.client
import inspect
import json
import math
import re
import socket
import threading
from time import monotonic
from typing import Any, Callable, Literal, Protocol
from urllib.parse import urlsplit
import uuid

from pydantic import BaseModel

from . import contracts as c
from .p2_harness import P2PromptEnvelope
from .p2_schema_wire import (
    P2SchemaWireSelection,
    P2_SCHEMA_PROMPT_VERSION,
    P2_SCHEMA_PROVIDER_VERSION,
    render_p2_wire_schema,
    validate_p2_schema_wire_selection,
)
from .p2_token_budget import (
    P2CounterDiagnosticCategory,
    P2CounterDiagnosticStage,
    P2TokenBudgetChecker,
    P2TokenBudgetError,
    P2TokenBudgetFailure,
    P2TokenBudgetMeasurement,
    P2TokenBudgetRequest,
    P2ChatMessage,
    P2ResponseFormat,
)
from .p2_prompt_policy import P2_PROMPT_VERSION, P2_SYSTEM_INSTRUCTIONS
from .p2_local_endpoint import parse_local_p2_endpoint


class LMStudioProviderErrorCode(str, Enum):
    DISABLED = "disabled"
    CLOSED = "closed"
    INVALID_PROMPT = "invalid_prompt"
    INPUT_OVERSIZE = "input_oversize"
    INPUT_BUDGET_UNVERIFIED = "input_budget_unverified"
    INPUT_BUDGET_EXCEEDED = "input_budget_exceeded"
    ARTIFACT_BINDING_CHANGED = "artifact_binding_changed"
    OVERSIZE = "oversize"
    EMPTY_CONTENT = "empty_content"
    LENGTH = "length"
    JSON_ERROR = "json_error"
    PARSER_ERROR = "parser_error"
    HTTP_BUSY = "http_busy"
    HTTP_ERROR = "http_error"
    DISPATCH_HOOK_REJECTED = "dispatch_hook_rejected"
    DISPATCH_WORKER_FAILED = "dispatch_worker_failed"
    TRANSPORT_OBSERVER_FAILED = "transport_observer_failed"
    OFFLINE = "offline"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class LMStudioProviderError(RuntimeError):
    """Sanitized provider failure; never includes prompt, response, URL, or token."""

    def __init__(
        self,
        code: LMStudioProviderErrorCode,
        *,
        http_status: int | None = None,
        token_budget_reason: str | None = None,
        counter_diagnostic_stage: str | None = None,
        counter_diagnostic_category: str | None = None,
        counter_sdk_exception_type: str | None = None,
        counter_sdk_status_code: int | None = None,
    ) -> None:
        self.code = code
        self.http_status = http_status
        try:
            self.token_budget_reason = P2TokenBudgetFailure(token_budget_reason).value if token_budget_reason else None
        except (TypeError, ValueError):
            self.token_budget_reason = None
        try:
            self.counter_diagnostic_stage = (
                P2CounterDiagnosticStage(counter_diagnostic_stage).value
                if counter_diagnostic_stage
                else None
            )
        except (TypeError, ValueError):
            self.counter_diagnostic_stage = None
        try:
            self.counter_diagnostic_category = (
                P2CounterDiagnosticCategory(counter_diagnostic_category).value
                if counter_diagnostic_category
                else None
            )
        except (TypeError, ValueError):
            self.counter_diagnostic_category = None
        if (
            isinstance(counter_sdk_exception_type, str)
            and counter_sdk_exception_type.isascii()
            and 1 <= len(counter_sdk_exception_type) <= 64
            and counter_sdk_exception_type[0].isalpha()
            and all(char.isalnum() or char == "_" for char in counter_sdk_exception_type)
        ):
            self.counter_sdk_exception_type = counter_sdk_exception_type
        else:
            self.counter_sdk_exception_type = None
        self.counter_sdk_status_code = (
            counter_sdk_status_code
            if isinstance(counter_sdk_status_code, int)
            and not isinstance(counter_sdk_status_code, bool)
            and 100 <= counter_sdk_status_code <= 599
            else None
        )
        super().__init__(code.value)


class LMStudioProviderCancelled(asyncio.CancelledError):
    """Cancellation is reported only after the underlying request has ended."""

    code = LMStudioProviderErrorCode.CANCELLED

    def __init__(self) -> None:
        super().__init__(LMStudioProviderErrorCode.CANCELLED.value)


@dataclass(frozen=True)
class P2ProviderHealth:
    """Internal provider health, separate from the frozen P1/OpenAPI health type."""

    status: Literal["disabled", "unavailable", "ready"]
    inference_available: bool
    reason: Literal["disabled", "not_tested", "last_call_failed", "last_call_succeeded", "closed"]
    last_success_at: datetime | None = None


@dataclass(frozen=True)
class LMStudioOpenAIConfig:
    """Explicit local endpoint and bounded request settings.

    api_token is held in memory only and hidden from repr. Input is bounded in
    UTF-8 bytes because this adapter deliberately does not guess token counts.
    max_output_tokens is sent to LM Studio as the server-side generation cap.
    """

    model_key: str
    enabled: bool = False
    endpoint_url: str = "http://127.0.0.1:1234/v1/chat/completions"
    provider_version: str = "p2-lmstudio-openai-v1"
    prompt_version: str = P2_PROMPT_VERSION
    temperature: float = 0.0
    max_output_tokens: int = 768
    request_timeout_seconds: float = 30.0
    max_prompt_bytes: int = 49_152
    max_request_bytes: int = 65_536
    max_response_bytes: int = 32_768
    max_content_bytes: int = 16_384
    max_concurrency: int = 1
    structured_output: bool = True
    api_token: str | None = field(default=None, repr=False)
    schema_wire_selection: P2SchemaWireSelection | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.model_key, str) or not self.model_key or len(self.model_key) > 128:
            raise ValueError("model_key must be a nonempty string of at most 128 characters")
        if any(ord(char) < 32 or ord(char) == 127 for char in self.model_key):
            raise ValueError("model_key contains control characters")
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be boolean")
        if not isinstance(self.provider_version, str) or not self.provider_version.strip() or len(self.provider_version) > 96:
            raise ValueError("provider_version is invalid")
        if not isinstance(self.prompt_version, str) or not self.prompt_version.strip() or len(self.prompt_version) > 96:
            raise ValueError("prompt_version is invalid")
        if not isinstance(self.temperature, (int, float)) or isinstance(self.temperature, bool):
            raise ValueError("temperature must be numeric")
        if not math.isfinite(float(self.temperature)) or not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be finite and between 0 and 2")
        self._bounded_int("max_output_tokens", self.max_output_tokens, 1, 32_768)
        self._bounded_int("max_prompt_bytes", self.max_prompt_bytes, 256, 1_048_576)
        self._bounded_int("max_request_bytes", self.max_request_bytes, 512, 1_048_576)
        self._bounded_int("max_response_bytes", self.max_response_bytes, 256, 1_048_576)
        self._bounded_int("max_content_bytes", self.max_content_bytes, 1, 16_384)
        self._bounded_int("max_concurrency", self.max_concurrency, 1, 1)
        if self.max_prompt_bytes > self.max_request_bytes:
            raise ValueError("max_prompt_bytes cannot exceed max_request_bytes")
        if self.max_content_bytes > self.max_response_bytes:
            raise ValueError("max_content_bytes cannot exceed max_response_bytes")
        if (
            not isinstance(self.request_timeout_seconds, (int, float))
            or isinstance(self.request_timeout_seconds, bool)
            or not math.isfinite(float(self.request_timeout_seconds))
            or not 0.1 <= self.request_timeout_seconds <= 300
        ):
            raise ValueError("request_timeout_seconds must be finite and between 0.1 and 300")
        if self.api_token is not None and (
            not isinstance(self.api_token, str)
            or not self.api_token
            or any(ord(char) < 32 or ord(char) == 127 for char in self.api_token)
        ):
            raise ValueError("api_token is invalid")
        if not isinstance(self.structured_output, bool):
            raise ValueError("structured_output must be boolean")
        if self.schema_wire_selection is not None:
            validate_p2_schema_wire_selection(
                self.schema_wire_selection,
                provider_version=self.provider_version,
                prompt_version=self.prompt_version,
            )

        self._validate_local_endpoint(self.endpoint_url)

    @staticmethod
    def _bounded_int(name: str, value: object, minimum: int, maximum: int) -> None:
        if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
            raise ValueError(f"{name} must be an integer between {minimum} and {maximum}")

    @staticmethod
    def _validate_local_endpoint(value: str) -> None:
        try:
            parse_local_p2_endpoint(value)
        except (TypeError, UnicodeError, ValueError):
            raise ValueError("endpoint_url must be a local HTTP /v1/chat/completions URL") from None


class PromptEnvelope(Protocol):
    """Structural input shared by P1 ModelPrompt and typed P2 prompt envelopes."""

    context: c.ModelContext
    repair_feedback: str | None


@dataclass(frozen=True)
class _TransportResult:
    status: int
    body: bytes


@dataclass(frozen=True)
class LMStudioTransportObservation:
    """Safe metadata about one bounded HTTP response, without response content."""

    status: int
    body_bytes: int
    body_sha256: str
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if type(self.status) is not int or not 100 <= self.status <= 599:
            raise ValueError("status must be an HTTP status integer")
        if type(self.body_bytes) is not int or self.body_bytes < 0:
            raise ValueError("body_bytes must be a nonnegative integer")
        if (
            type(self.body_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", self.body_sha256, flags=re.ASCII) is None
        ):
            raise ValueError("body_sha256 must be a lowercase SHA-256 digest")
        if self.observed_at is not None and (
            not isinstance(self.observed_at, datetime)
            or self.observed_at.tzinfo is None
            or self.observed_at.utcoffset() is None
        ):
            raise ValueError("observed_at must be timezone-aware")


class _ProviderHookRejected(Exception):
    """Internal sentinel; callback exception details never escape this module."""


def _invoke_provider_hook(callback: Callable[..., Any], *args: Any) -> None:
    """Invoke a bounded synchronous observer and reject accidental async hooks."""
    try:
        result = callback(*args)
    except (Exception, asyncio.CancelledError):
        raise _ProviderHookRejected() from None
    if inspect.isawaitable(result):
        close = getattr(result, "close", None)
        cancel = getattr(result, "cancel", None)
        try:
            if callable(close):
                close()
            elif callable(cancel):
                cancel()
        except Exception:
            pass
        raise _ProviderHookRejected() from None
    if result is not None:
        raise _ProviderHookRejected() from None


Transport = Callable[[str, bytes, Mapping[str, str], float, int], _TransportResult | tuple[int, bytes]]


_UUID_LITERAL = re.compile(
    r"(?i)(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![0-9a-f])"
)
_CREDENTIAL_LITERAL = re.compile(
    r"(?i)(?:\bbearer\s+\S+|\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})"
)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError("non-standard JSON constant")


def _validate_prompt_node(value: Any, field_name: str = "") -> None:
    normalized = field_name.casefold().replace("-", "_")
    forbidden = (
        "access_token",
        "auth_token",
        "token",
        "authorization",
        "bearer",
        "credential",
        "secret",
        "user",
        "user_id",
        "actor_id",
        "turn_id",
        "session_id",
        "activity_id",
        "expense_id",
    )
    if any(name in normalized for name in forbidden):
        raise LMStudioProviderError(LMStudioProviderErrorCode.INVALID_PROMPT)
    if isinstance(value, uuid.UUID):
        raise LMStudioProviderError(LMStudioProviderErrorCode.INVALID_PROMPT)
    if isinstance(value, str):
        if _UUID_LITERAL.search(value) or _CREDENTIAL_LITERAL.search(value):
            raise LMStudioProviderError(LMStudioProviderErrorCode.INVALID_PROMPT)
        return
    if value is None or isinstance(value, (bool, int, float, Decimal, datetime, date, Enum)):
        return
    if isinstance(value, BaseModel):
        if value.model_extra:
            raise LMStudioProviderError(LMStudioProviderErrorCode.INVALID_PROMPT)
        for name, model_field in type(value).model_fields.items():
            _validate_prompt_node(getattr(value, name), name)
            for alias in (model_field.alias, model_field.serialization_alias):
                if alias is not None:
                    _validate_prompt_node(None, alias)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _validate_prompt_node(item, field_name)
        return
    if isinstance(value, Mapping):
        # Typed Pydantic fields are accepted; raw mappings can smuggle credentials.
        raise LMStudioProviderError(LMStudioProviderErrorCode.INVALID_PROMPT)
    raise LMStudioProviderError(LMStudioProviderErrorCode.INVALID_PROMPT)


def _serialize_envelope(prompt: PromptEnvelope) -> bytes:
    if not isinstance(prompt, BaseModel):
        raise LMStudioProviderError(LMStudioProviderErrorCode.INVALID_PROMPT)
    context = getattr(prompt, "context", None)
    repair_feedback = getattr(prompt, "repair_feedback", None)
    if not isinstance(context, c.ModelContext) or (
        repair_feedback is not None and not isinstance(repair_feedback, str)
    ):
        raise LMStudioProviderError(LMStudioProviderErrorCode.INVALID_PROMPT)
    if repair_feedback is not None and len(repair_feedback.encode("utf-8", "ignore")) > 256:
        raise LMStudioProviderError(LMStudioProviderErrorCode.INVALID_PROMPT)
    try:
        _validate_prompt_node(prompt)
        payload = prompt.model_dump(mode="json", by_alias=True, exclude_none=False)
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return serialized.encode("utf-8")
    except LMStudioProviderError:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise LMStudioProviderError(LMStudioProviderErrorCode.INVALID_PROMPT) from None


def _build_request(
    config: LMStudioOpenAIConfig,
    envelope: bytes,
    schema_wire_selection: P2SchemaWireSelection | None = None,
) -> bytes:
    if len(envelope) > config.max_prompt_bytes:
        raise LMStudioProviderError(LMStudioProviderErrorCode.INPUT_OVERSIZE)
    try:
        context_payload = envelope.decode("utf-8")
        messages = [
            {
                "role": "system",
                "content": (
                    P2_SYSTEM_INSTRUCTIONS
                    + "\nProvider version: "
                    + config.provider_version
                    + "\nPrompt version: "
                    + config.prompt_version
                ),
            },
            {
                "role": "user",
                "content": "Harness-constructed typed envelope (JSON data):\n" + context_payload,
            },
        ]
        request: dict[str, Any] = {
            "model": config.model_key,
            "messages": messages,
            "temperature": float(config.temperature),
            "max_tokens": config.max_output_tokens,
            "stream": False,
        }
        if config.structured_output:
            schema: object = c.SEMANTIC_DECISION_ADAPTER.json_schema()
            if schema_wire_selection is not None:
                schema = render_p2_wire_schema(
                    schema,
                    schema_wire_selection,
                    provider_version=config.provider_version,
                    prompt_version=config.prompt_version,
                )
            request["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "shared_ledger_semantic_decision_v1",
                    "strict": True,
                    "schema": schema,
                },
            }
        body = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except LMStudioProviderError:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise LMStudioProviderError(LMStudioProviderErrorCode.INVALID_PROMPT) from None
    if len(body) > config.max_request_bytes:
        raise LMStudioProviderError(LMStudioProviderErrorCode.INPUT_OVERSIZE)
    return body


def _parse_completion(body: bytes, *, max_content_bytes: int) -> str:
    try:
        raw = body.decode("utf-8", errors="strict")
        document = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError):
        raise LMStudioProviderError(LMStudioProviderErrorCode.JSON_ERROR) from None
    if not isinstance(document, dict):
        raise LMStudioProviderError(LMStudioProviderErrorCode.PARSER_ERROR)
    choices = document.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise LMStudioProviderError(LMStudioProviderErrorCode.PARSER_ERROR)
    choice = choices[0]
    finish_reason = choice.get("finish_reason")
    if finish_reason == "length":
        raise LMStudioProviderError(LMStudioProviderErrorCode.LENGTH)
    if finish_reason != "stop":
        raise LMStudioProviderError(LMStudioProviderErrorCode.PARSER_ERROR)
    message = choice.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise LMStudioProviderError(LMStudioProviderErrorCode.PARSER_ERROR)
    content = message.get("content")
    if content is None or not isinstance(content, str) or not content.strip():
        raise LMStudioProviderError(LMStudioProviderErrorCode.EMPTY_CONTENT)
    if len(content.encode("utf-8")) > max_content_bytes:
        raise LMStudioProviderError(LMStudioProviderErrorCode.OVERSIZE)
    return content


def _http_post(
    endpoint_url: str,
    body: bytes,
    headers: Mapping[str, str],
    timeout_seconds: float,
    max_response_bytes: int,
) -> _TransportResult:
    """Perform one bounded HTTP POST without urllib redirect handling."""

    parsed = urlsplit(endpoint_url)
    host = parsed.hostname
    if host is None:
        raise ValueError("invalid endpoint")
    port = parsed.port or 80
    connection = http.client.HTTPConnection(host, port=port, timeout=timeout_seconds)
    deadline = monotonic() + timeout_seconds
    deadline_expired = threading.Event()
    request_socket: socket.socket | None = None

    def expire_request() -> None:
        deadline_expired.set()
        active_socket = request_socket or connection.sock
        if active_socket is not None:
            try:
                active_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                active_socket.close()
            except OSError:
                pass
        connection.close()

    deadline_timer = threading.Timer(timeout_seconds, expire_request)
    deadline_timer.daemon = True
    deadline_timer.start()
    try:
        connection.request("POST", parsed.path, body=body, headers=dict(headers))
        request_socket = connection.sock
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError()
        if connection.sock is not None:
            connection.sock.settimeout(remaining)
        response = connection.getresponse()
        if deadline_expired.is_set() or monotonic() >= deadline:
            raise TimeoutError()
        status = response.status
        if status != 200:
            return _TransportResult(status=status, body=b"")
        content_length = response.getheader("Content-Length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                raise http.client.HTTPException("invalid content length") from None
            if declared_length < 0:
                raise http.client.HTTPException("invalid content length")
            if declared_length > max_response_bytes:
                raise _ResponseTooLarge()
        chunks: list[bytes] = []
        total = 0
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError()
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            read = getattr(response, "read1", response.read)
            chunk = read(min(8192, max_response_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_response_bytes:
                raise _ResponseTooLarge()
        if deadline_expired.is_set() or monotonic() >= deadline:
            raise TimeoutError()
        return _TransportResult(status=status, body=b"".join(chunks))
    except _ResponseTooLarge:
        raise
    except (socket.timeout, TimeoutError):
        raise
    except http.client.IncompleteRead:
        if deadline_expired.is_set():
            raise TimeoutError() from None
        raise ConnectionError() from None
    except (http.client.HTTPException, OSError):
        if deadline_expired.is_set():
            raise TimeoutError() from None
        raise
    except Exception:
        if deadline_expired.is_set():
            raise TimeoutError() from None
        raise
    finally:
        deadline_timer.cancel()
        connection.close()


class _ResponseTooLarge(RuntimeError):
    pass


class LMStudioOpenAIProvider:
    """Single-endpoint provider with a per-instance concurrency gate."""

    def __init__(
        self,
        config: LMStudioOpenAIConfig,
        *,
        transport: Transport | None = None,
        token_budget_checker: P2TokenBudgetChecker | None = None,
    ) -> None:
        self._config = config
        self._transport = transport or _http_post
        self._token_budget_checker = token_budget_checker
        self._gate = asyncio.Semaphore(config.max_concurrency)
        self._state_lock = threading.Lock()
        self._started = False
        self._closed = False
        self._last_failure = False
        self._last_success_at: datetime | None = None

    def start(self) -> None:
        """Mark the adapter active; performs no network, catalog, or model operation."""
        with self._state_lock:
            self._started = True
            self._closed = False
            self._last_failure = False
            self._last_success_at = None

    def health(self) -> P2ProviderHealth:
        """Return local state only; never probes the endpoint or model catalog."""
        with self._state_lock:
            if not self._config.enabled:
                return P2ProviderHealth(
                    status="disabled", inference_available=False, reason="disabled",
                )
            if self._closed:
                return P2ProviderHealth(
                    status="unavailable", inference_available=False, reason="closed",
                )
            if self._last_failure:
                return P2ProviderHealth(
                    status="unavailable", inference_available=False, reason="last_call_failed",
                )
            if self._last_success_at is not None:
                return P2ProviderHealth(
                    status="ready", inference_available=True,
                    reason="last_call_succeeded", last_success_at=self._last_success_at,
                )
            return P2ProviderHealth(
                status="unavailable", inference_available=False, reason="not_tested",
            )

    def close(self) -> None:
        with self._state_lock:
            self._closed = True
            self._started = False
            checker = self._token_budget_checker
        close_checker = getattr(checker, "close", None)
        if callable(close_checker):
            close_checker()

    async def prepare(self) -> None:
        """Prepare the optional exact-model counter before a Runtime turn.

        This is a read-only readiness step: it hashes the configured artifact
        and verifies the already-loaded model through the SDK helper. It never
        loads a model, counts tokens, or sends a chat request.
        """
        self._ensure_available()
        await self._prepare_token_counter_session()
        self._ensure_available()

    async def _prepare_token_counter_session(self) -> None:
        checker = self._token_budget_checker
        ensure_sdk_session = getattr(checker, "ensure_sdk_session", None)
        if not callable(ensure_sdk_session):
            return
        preparation_worker = asyncio.create_task(
            asyncio.to_thread(ensure_sdk_session),
            name="p2-lmstudio-token-counter-prepare",
        )
        try:
            await asyncio.shield(preparation_worker)
        except asyncio.CancelledError:
            await self._drain_worker(preparation_worker)
            self._mark_failure()
            raise LMStudioProviderCancelled() from None
        except P2TokenBudgetError as exc:
            self._mark_failure()
            raise _provider_budget_error(exc) from None
        except BaseException:
            self._mark_failure()
            raise LMStudioProviderError(LMStudioProviderErrorCode.INPUT_BUDGET_UNVERIFIED) from None

    async def generate(self, prompt: PromptEnvelope) -> str:
        self._ensure_available()
        envelope = _serialize_envelope(prompt)
        schema_wire_selection = (
            self._config.schema_wire_selection
            if isinstance(prompt, P2PromptEnvelope)
            else None
        )
        body = _build_request(self._config, envelope, schema_wire_selection)
        return await self._generate_bound_body(body, initial_state_checked=True)

    def _ensure_available(self) -> None:
        with self._state_lock:
            if not self._config.enabled:
                raise LMStudioProviderError(LMStudioProviderErrorCode.DISABLED)
            if self._closed or not self._started:
                self._last_failure = True
                raise LMStudioProviderError(LMStudioProviderErrorCode.CLOSED)

    async def _generate_bound_body(
        self,
        body: bytes,
        *,
        expected_body_sha256: str | None = None,
        initial_state_checked: bool = False,
        native_candidate_wire: bool = False,
        before_dispatch: Callable[[str, P2TokenBudgetMeasurement], None] | None = None,
        on_transport_result: Callable[[LMStudioTransportObservation], None] | None = None,
    ) -> str:
        """Run the shared bounded counter/HTTP/parser path for already built bytes.

        The candidate read provider revalidates its prepared object before calling
        this internal seam. The token-counter request is always reconstructed
        from the exact body passed to the HTTP transport below.
        """
        if not initial_state_checked:
            self._ensure_available()
        if type(body) is not bytes:
            self._mark_failure()
            raise LMStudioProviderError(LMStudioProviderErrorCode.INVALID_PROMPT)
        if expected_body_sha256 is not None and (
            not isinstance(expected_body_sha256, str)
            or hashlib.sha256(body).hexdigest() != expected_body_sha256
        ):
            self._mark_failure()
            raise LMStudioProviderError(LMStudioProviderErrorCode.INVALID_PROMPT)
        if len(body) > self._config.max_request_bytes:
            self._mark_failure()
            raise LMStudioProviderError(LMStudioProviderErrorCode.INPUT_OVERSIZE)
        if type(native_candidate_wire) is not bool:
            self._mark_failure()
            raise LMStudioProviderError(LMStudioProviderErrorCode.INVALID_PROMPT)
        if before_dispatch is not None and not callable(before_dispatch):
            self._mark_failure()
            raise LMStudioProviderError(LMStudioProviderErrorCode.DISPATCH_HOOK_REJECTED)
        if on_transport_result is not None and not callable(on_transport_result):
            self._mark_failure()
            raise LMStudioProviderError(LMStudioProviderErrorCode.TRANSPORT_OBSERVER_FAILED)
        if native_candidate_wire:
            try:
                budget_request = _native_candidate_token_budget_request(self._config, body)
                dispatch_endpoint = _native_candidate_endpoint(self._config.endpoint_url)
            except LMStudioProviderError:
                self._mark_failure()
                raise
            except (TypeError, ValueError, UnicodeError):
                self._mark_failure()
                raise LMStudioProviderError(LMStudioProviderErrorCode.INVALID_PROMPT) from None
            content_parser = _parse_native_candidate_response
            timeout_seconds = self._config.request_timeout_seconds
            thread_name = "p2-lmstudio-native-candidate-http"
        else:
            budget_request = _token_budget_request(self._config, body)
            dispatch_endpoint = self._config.endpoint_url
            content_parser = _parse_completion
            # An explicitly enabled native candidate may allow a longer timeout
            # for its own wire, while the compatibility transport stays capped
            # at its reviewed 30-second limit.
            timeout_seconds = min(float(self._config.request_timeout_seconds), 30.0)
            thread_name = "p2-lmstudio-openai-http"
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Connection": "close",
        }
        if self._config.api_token is not None:
            headers["Authorization"] = "Bearer " + self._config.api_token

        try:
            await self._gate.acquire()
        except asyncio.CancelledError:
            self._mark_failure()
            raise LMStudioProviderCancelled() from None
        try:
            with self._state_lock:
                if not self._config.enabled:
                    self._last_failure = True
                    raise LMStudioProviderError(LMStudioProviderErrorCode.DISABLED)
                if self._closed or not self._started:
                    self._last_failure = True
                    raise LMStudioProviderError(LMStudioProviderErrorCode.CLOSED)
            if self._token_budget_checker is None:
                self._mark_failure()
                raise LMStudioProviderError(LMStudioProviderErrorCode.INPUT_BUDGET_UNVERIFIED)
            # The exact SDK/client readiness is a bounded read-only preparation
            # phase, separate from the unchanged five-second JIT count. It is
            # lazy so provider construction/start/health remain local-only, and
            # the checker reuses one current helper for later requests.
            await self._prepare_token_counter_session()
            checker_worker = asyncio.create_task(
                asyncio.to_thread(self._token_budget_checker.measure, budget_request),
                name="p2-lmstudio-token-budget-check",
            )
            try:
                measurement = await asyncio.shield(checker_worker)
            except asyncio.CancelledError:
                await self._drain_worker(checker_worker)
                self._mark_failure()
                raise LMStudioProviderCancelled() from None
            except P2TokenBudgetError as exc:
                self._mark_failure()
                raise _provider_budget_error(exc) from None
            except BaseException:
                self._mark_failure()
                raise LMStudioProviderError(LMStudioProviderErrorCode.INPUT_BUDGET_UNVERIFIED) from None
            try:
                _validate_budget_measurement(measurement, self._config, budget_request)
            except P2TokenBudgetError as exc:
                self._mark_failure()
                raise _provider_budget_error(exc) from None
            hook_rejected = False
            worker_creation_failed = False
            with self._state_lock:
                if not self._config.enabled:
                    self._last_failure = True
                    raise LMStudioProviderError(LMStudioProviderErrorCode.DISABLED)
                if self._closed or not self._started:
                    self._last_failure = True
                    raise LMStudioProviderError(LMStudioProviderErrorCode.CLOSED)
                if before_dispatch is not None:
                    actual_body_sha256 = hashlib.sha256(body).hexdigest()
                    try:
                        _invoke_provider_hook(before_dispatch, actual_body_sha256, measurement)
                    except _ProviderHookRejected:
                        hook_rejected = True
                # Creating the worker while holding the state lock defines the
                # dispatch boundary: a close before this point prevents I/O.
                if not hook_rejected:
                    http_call = asyncio.to_thread(
                        self._transport,
                        dispatch_endpoint,
                        body,
                        headers,
                        timeout_seconds,
                        self._config.max_response_bytes,
                    )
                    try:
                        worker = asyncio.create_task(
                            http_call,
                            name=thread_name,
                        )
                    except (Exception, asyncio.CancelledError):
                        if before_dispatch is None:
                            http_call.close()
                            raise
                        http_call.close()
                        worker_creation_failed = True
            if hook_rejected:
                self._mark_failure()
                raise LMStudioProviderError(
                    LMStudioProviderErrorCode.DISPATCH_HOOK_REJECTED,
                ) from None
            if worker_creation_failed:
                self._mark_failure()
                raise LMStudioProviderError(
                    LMStudioProviderErrorCode.DISPATCH_WORKER_FAILED,
                ) from None
            try:
                result = await asyncio.shield(worker)
            except asyncio.CancelledError:
                await self._drain_worker(worker)
                self._mark_failure()
                raise LMStudioProviderCancelled() from None
            except BaseException as exc:
                self._raise_transport_error(exc)
            if isinstance(result, tuple):
                result = _TransportResult(status=result[0], body=result[1])
            if not isinstance(result, _TransportResult) or not isinstance(result.body, bytes):
                self._mark_failure()
                raise LMStudioProviderError(LMStudioProviderErrorCode.PARSER_ERROR)
            if len(result.body) > self._config.max_response_bytes:
                self._mark_failure()
                raise LMStudioProviderError(LMStudioProviderErrorCode.OVERSIZE)
            if on_transport_result is not None:
                if type(result.status) is not int or not 100 <= result.status <= 599:
                    self._mark_failure()
                    raise LMStudioProviderError(LMStudioProviderErrorCode.PARSER_ERROR)
                observation = LMStudioTransportObservation(
                    status=result.status,
                    body_bytes=len(result.body),
                    body_sha256=hashlib.sha256(result.body).hexdigest(),
                    observed_at=datetime.now(timezone.utc),
                )
                try:
                    _invoke_provider_hook(on_transport_result, observation)
                except _ProviderHookRejected:
                    self._mark_failure()
                    raise LMStudioProviderError(
                        LMStudioProviderErrorCode.TRANSPORT_OBSERVER_FAILED,
                    ) from None
            if result.status in (408, 504):
                self._mark_failure()
                raise LMStudioProviderError(
                    LMStudioProviderErrorCode.TIMEOUT, http_status=result.status,
                )
            if result.status in (409, 423, 429, 503):
                self._mark_failure()
                raise LMStudioProviderError(
                    LMStudioProviderErrorCode.HTTP_BUSY, http_status=result.status,
                )
            if result.status != 200:
                self._mark_failure()
                raise LMStudioProviderError(
                    LMStudioProviderErrorCode.HTTP_ERROR, http_status=result.status,
                )
            try:
                content = content_parser(
                    result.body, max_content_bytes=self._config.max_content_bytes,
                )
            except LMStudioProviderError:
                self._mark_failure()
                raise
            self._mark_success()
            return content
        finally:
            self._gate.release()

    @staticmethod
    async def _drain_worker(worker: asyncio.Task[Any]) -> None:
        """Ignore repeated caller cancellation until the actual thread has returned."""
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except BaseException:
                break
        if worker.done():
            try:
                worker.result()
            except BaseException:
                pass

    def _raise_transport_error(self, exc: BaseException) -> None:
        self._mark_failure()
        if isinstance(exc, (socket.timeout, TimeoutError)):
            raise LMStudioProviderError(LMStudioProviderErrorCode.TIMEOUT) from None
        if isinstance(exc, _ResponseTooLarge):
            raise LMStudioProviderError(LMStudioProviderErrorCode.OVERSIZE) from None
        if isinstance(exc, http.client.HTTPException):
            raise LMStudioProviderError(LMStudioProviderErrorCode.PARSER_ERROR) from None
        if isinstance(exc, (ConnectionError, OSError)):
            raise LMStudioProviderError(LMStudioProviderErrorCode.OFFLINE) from None
        raise LMStudioProviderError(LMStudioProviderErrorCode.HTTP_ERROR) from None

    def _mark_failure(self) -> None:
        with self._state_lock:
            self._last_failure = True

    def _mark_success(self) -> None:
        with self._state_lock:
            self._last_failure = False
            self._last_success_at = datetime.now(timezone.utc)


def _token_budget_request(config: LMStudioOpenAIConfig, body: bytes) -> P2TokenBudgetRequest:
    """Convert only this provider's own serialized request into typed counter input."""
    try:
        payload = json.loads(body.decode("utf-8", errors="strict"))
        if type(payload) is not dict:
            raise ValueError("provider body must be a JSON object")
        if payload.get("model") != config.model_key or payload.get("max_tokens") != config.max_output_tokens:
            raise ValueError("provider body model or output cap does not match the server config")
        raw_messages = payload["messages"]
        if not isinstance(raw_messages, list):
            raise ValueError("invalid provider messages")
        messages = tuple(
            P2ChatMessage(role=item["role"], content=item["content"])
            for item in raw_messages
        )
        raw_response_format = payload.get("response_format")
        response_format = None
        if raw_response_format is not None:
            response_format = P2ResponseFormat(
                payload_json=json.dumps(
                    raw_response_format,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
            )
        api_host = parse_local_p2_endpoint(config.endpoint_url).origin
        return P2TokenBudgetRequest(
            model_key=config.model_key,
            api_host=api_host,
            messages=messages,
            response_format=response_format,
            max_output_tokens=config.max_output_tokens,
        )
    except LMStudioProviderError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        raise LMStudioProviderError(LMStudioProviderErrorCode.INVALID_PROMPT) from None


def _native_candidate_endpoint(endpoint_url: str) -> str:
    """Derive the one supported native candidate path from the pinned local origin."""
    endpoint = parse_local_p2_endpoint(endpoint_url)
    return endpoint.origin + "/api/v1/chat"


def _native_candidate_token_budget_request(
    config: LMStudioOpenAIConfig,
    body: bytes,
) -> P2TokenBudgetRequest:
    """Rebuild counter messages from the exact native body sent over HTTP."""
    expected_keys = {
        "model", "input", "system_prompt", "stream", "temperature",
        "max_output_tokens", "reasoning", "context_length", "store",
    }
    try:
        payload = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        if (
            type(payload) is not dict
            or frozenset(payload) != expected_keys
            or json.dumps(
                payload, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False,
            ).encode("utf-8") != body
        ):
            raise ValueError("native candidate body is not the exact supported JSON shape")
        if (
            payload["model"] != config.model_key
            or type(payload["input"]) is not str
            or type(payload["system_prompt"]) is not str
            or payload["stream"] is not False
            or type(payload["temperature"]) not in (int, float)
            or isinstance(payload["temperature"], bool)
            or float(payload["temperature"]) != float(config.temperature)
            or type(payload["max_output_tokens"]) is not int
            or payload["max_output_tokens"] != config.max_output_tokens
            or payload["reasoning"] != "off"
            or type(payload["context_length"]) is not int
            or payload["context_length"] != 8192
            or payload["store"] is not False
        ):
            raise ValueError("native candidate body differs from selected server policy")
        if len((payload["system_prompt"] + payload["input"]).encode("utf-8")) > config.max_prompt_bytes:
            raise LMStudioProviderError(LMStudioProviderErrorCode.INPUT_OVERSIZE)
        return P2TokenBudgetRequest(
            model_key=config.model_key,
            api_host=parse_local_p2_endpoint(config.endpoint_url).origin,
            messages=(
                P2ChatMessage(role="system", content=payload["system_prompt"]),
                P2ChatMessage(role="user", content=payload["input"]),
            ),
            response_format=None,
            max_output_tokens=config.max_output_tokens,
        )
    except LMStudioProviderError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        raise LMStudioProviderError(LMStudioProviderErrorCode.INVALID_PROMPT) from None


def _parse_native_candidate_response(body: bytes, *, max_content_bytes: int) -> str:
    """Extract exactly one native ``output[type=message].content`` string."""
    try:
        document = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError):
        raise LMStudioProviderError(LMStudioProviderErrorCode.JSON_ERROR) from None
    if type(document) is not dict or type(document.get("output")) is not list:
        raise LMStudioProviderError(LMStudioProviderErrorCode.PARSER_ERROR)
    messages = [
        item for item in document["output"]
        if type(item) is dict and item.get("type") == "message"
    ]
    if len(messages) != 1 or type(messages[0].get("content")) is not str:
        raise LMStudioProviderError(LMStudioProviderErrorCode.PARSER_ERROR)
    content = messages[0]["content"]
    if not content.strip():
        raise LMStudioProviderError(LMStudioProviderErrorCode.EMPTY_CONTENT)
    if len(content.encode("utf-8")) > max_content_bytes:
        raise LMStudioProviderError(LMStudioProviderErrorCode.OVERSIZE)
    return content


def _validate_budget_measurement(
    measurement: object,
    config: LMStudioOpenAIConfig,
    request: P2TokenBudgetRequest,
) -> None:
    if not isinstance(measurement, P2TokenBudgetMeasurement):
        raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    if measurement.model_key != config.model_key:
        raise P2TokenBudgetError(P2TokenBudgetFailure.MODEL_KEY_MISMATCH)
    if measurement.api_host != request.api_host:
        raise P2TokenBudgetError(P2TokenBudgetFailure.SERVER_BINDING_MISMATCH)
    if request.response_format is not None and measurement.response_format_tokens < 1:
        raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    if measurement.safety_margin_tokens < 512:
        raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    if measurement.requested_output_tokens != config.max_output_tokens:
        raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    if measurement.requested_output_tokens > measurement.max_output_tokens:
        raise P2TokenBudgetError(P2TokenBudgetFailure.CONTEXT_BUDGET_EXCEEDED)
    if measurement.budgeted_input_tokens > measurement.max_input_tokens:
        raise P2TokenBudgetError(P2TokenBudgetFailure.INPUT_BUDGET_EXCEEDED)
    if (
        measurement.actual_context_tokens < 1
        or measurement.budgeted_input_tokens + measurement.requested_output_tokens
        > measurement.actual_context_tokens
    ):
        raise P2TokenBudgetError(P2TokenBudgetFailure.CONTEXT_BUDGET_EXCEEDED)
    if len(measurement.artifact_sha256) != 64 or any(
        char not in "0123456789abcdefABCDEF" for char in measurement.artifact_sha256
    ):
        raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)


def _provider_budget_error(error: P2TokenBudgetError) -> LMStudioProviderError:
    if error.reason in {
        P2TokenBudgetFailure.INPUT_BUDGET_EXCEEDED,
        P2TokenBudgetFailure.CONTEXT_BUDGET_EXCEEDED,
    }:
        code = LMStudioProviderErrorCode.INPUT_BUDGET_EXCEEDED
    elif error.reason == P2TokenBudgetFailure.ARTIFACT_BINDING_CHANGED:
        code = LMStudioProviderErrorCode.ARTIFACT_BINDING_CHANGED
    else:
        code = LMStudioProviderErrorCode.INPUT_BUDGET_UNVERIFIED
    return LMStudioProviderError(
        code,
        token_budget_reason=error.reason,
        counter_diagnostic_stage=error.diagnostic_stage,
        counter_diagnostic_category=error.diagnostic_category,
        counter_sdk_exception_type=error.sdk_exception_type,
        counter_sdk_status_code=error.sdk_status_code,
    )
