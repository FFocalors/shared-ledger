"""Fail-closed token admission for the isolated P2 LM Studio provider.

The optional SDK adapter runs in a short-lived helper process. The helper only
looks up already-loaded models and counts tokens; it has no load or inference
path. The parent owns artifact hashing and keeps its verified binding only in
memory for the lifetime of the checker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from threading import Event, Lock, Thread
from time import monotonic
from typing import BinaryIO, Callable, Literal, Protocol
from uuid import uuid4

if __package__:
    from .p2_local_endpoint import is_valid_local_http_origin, normalize_local_http_origin
    from .p2_format_repair import is_allowed_p2_message_sequence
else:
    # The checker deliberately launches this file by absolute path as a child
    # process. In that mode Python puts this file's directory at sys.path[0],
    # so this import resolves only the sibling helper from the same directory.
    from p2_local_endpoint import is_valid_local_http_origin, normalize_local_http_origin
    from p2_format_repair import is_allowed_p2_message_sequence


_COUNTER_SESSION_PROTOCOL = "p2-token-budget-session-v1"
_COUNTER_REQUEST_PROTOCOL = "p2-token-budget-v2-diagnostic"
_COUNTER_SESSION_INPUT_LIMIT = 1_000_000
_COUNTER_SESSION_OUTPUT_LIMIT = 4_096
_COUNTER_SESSION_CLEANUP_GRACE_SECONDS = 1.0


class P2TokenBudgetFailure(StrEnum):
    COUNTER_UNAVAILABLE = "counter_unavailable"
    COUNTER_TIMEOUT = "counter_timeout"
    ARTIFACT_BINDING_CHANGED = "artifact_binding_changed"
    MODEL_NOT_LOADED = "model_not_loaded"
    MODEL_KEY_MISMATCH = "model_key_mismatch"
    MODEL_PATH_MISMATCH = "model_path_mismatch"
    CONTEXT_MISMATCH = "context_mismatch"
    SERVER_BINDING_MISMATCH = "server_binding_mismatch"
    INPUT_BUDGET_EXCEEDED = "input_budget_exceeded"
    CONTEXT_BUDGET_EXCEEDED = "context_budget_exceeded"
    INVALID_COUNTER_RESPONSE = "invalid_counter_response"
    SESSION_NOT_PREPARED = "session_not_prepared"
    SESSION_CLOSED = "session_closed"


class P2CounterDiagnosticStage(StrEnum):
    """Closed stage labels for the private one-shot counter child response."""

    UNCLASSIFIED = "unclassified"
    REQUEST_VALIDATION = "request_validation"
    SDK_IMPORT = "sdk_import"
    SDK_CLIENT_OPEN = "sdk_client_open"
    TIMEOUT_SET = "timeout_set"
    LOOKUP_PRE = "lookup_pre"
    MESSAGE_POLICY = "message_policy"
    TYPED_HISTORY_BUILD = "typed_history_build"
    TYPED_HISTORY_SERIALIZE = "typed_history_serialize"
    CHAT_FROM_HISTORY = "chat_from_history"
    APPLY_PROMPT_TEMPLATE = "apply_prompt_template"
    COUNT_PROMPT_TOKENS = "count_prompt_tokens"
    COUNT_RESPONSE_FORMAT_TOKENS = "count_response_format_tokens"
    LOOKUP_POST = "lookup_post"
    IDENTITY_CHECK = "identity_check"
    CHILD_PROTOCOL = "child_protocol"


class P2CounterDiagnosticCategory(StrEnum):
    """Closed failure categories; never contains SDK exception text."""

    SDK_OPERATION_FAILED = "sdk_operation_failed"
    BINDING_REJECTED = "binding_rejected"
    POLICY_REJECTED = "policy_rejected"
    PROTOCOL_REJECTED = "protocol_rejected"
    DEADLINE = "deadline"


_COUNTER_PROGRESS_WRITER: Callable[[P2CounterDiagnosticStage], None] | None = None


class P2TokenBudgetError(RuntimeError):
    """Sanitized token admission failure; contains no prompt or SDK details."""

    def __init__(
        self,
        reason: str,
        *,
        diagnostic_stage: P2CounterDiagnosticStage | str | None = None,
        diagnostic_category: P2CounterDiagnosticCategory | str | None = None,
        sdk_exception_type: str | None = None,
        sdk_status_code: int | None = None,
    ) -> None:
        try:
            self.reason = P2TokenBudgetFailure(reason).value
        except (TypeError, ValueError):
            self.reason = P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE.value
        try:
            self.diagnostic_stage = (
                P2CounterDiagnosticStage(diagnostic_stage).value
                if diagnostic_stage is not None
                else None
            )
        except (TypeError, ValueError):
            self.diagnostic_stage = None
        try:
            self.diagnostic_category = (
                P2CounterDiagnosticCategory(diagnostic_category).value
                if diagnostic_category is not None
                else None
            )
        except (TypeError, ValueError):
            self.diagnostic_category = None
        self.sdk_exception_type = _safe_sdk_exception_type_name(sdk_exception_type)
        self.sdk_status_code = _safe_sdk_status_code(sdk_status_code)
        super().__init__(self.reason)


def _safe_sdk_exception_type_name(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 64 or not value.isascii():
        return None
    if not value[0].isalpha() or any(not (char.isalnum() or char == "_") for char in value):
        return None
    return value


def _safe_sdk_status_code(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
        return value
    return None


def _safe_sdk_exception_details(error: Exception) -> tuple[str | None, int | None]:
    error_type = _safe_sdk_exception_type_name(type(error).__name__)
    status_code = _safe_sdk_status_code(getattr(error, "status_code", None))
    return error_type, status_code


def _counter_diagnostic_category_for_reason(reason: str) -> P2CounterDiagnosticCategory:
    if reason in {
        P2TokenBudgetFailure.MODEL_NOT_LOADED,
        P2TokenBudgetFailure.MODEL_KEY_MISMATCH,
        P2TokenBudgetFailure.MODEL_PATH_MISMATCH,
        P2TokenBudgetFailure.CONTEXT_MISMATCH,
        P2TokenBudgetFailure.SERVER_BINDING_MISMATCH,
        P2TokenBudgetFailure.ARTIFACT_BINDING_CHANGED,
    }:
        return P2CounterDiagnosticCategory.BINDING_REJECTED
    if reason in {
        P2TokenBudgetFailure.INPUT_BUDGET_EXCEEDED,
        P2TokenBudgetFailure.CONTEXT_BUDGET_EXCEEDED,
    }:
        return P2CounterDiagnosticCategory.POLICY_REJECTED
    if reason in {
        P2TokenBudgetFailure.COUNTER_TIMEOUT,
    }:
        return P2CounterDiagnosticCategory.DEADLINE
    if reason == P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE:
        return P2CounterDiagnosticCategory.PROTOCOL_REJECTED
    return P2CounterDiagnosticCategory.SDK_OPERATION_FAILED


def _counter_stage_call(
    stage: P2CounterDiagnosticStage,
    operation: Callable[[], object],
) -> object:
    """Preserve a safe reason and one closed execution stage across helper IPC."""
    try:
        if _COUNTER_PROGRESS_WRITER is not None:
            _COUNTER_PROGRESS_WRITER(stage)
        return operation()
    except P2TokenBudgetError as exc:
        reason = exc.reason
        raise P2TokenBudgetError(
            reason,
            diagnostic_stage=exc.diagnostic_stage or stage,
            diagnostic_category=exc.diagnostic_category or _counter_diagnostic_category_for_reason(reason),
            sdk_exception_type=exc.sdk_exception_type,
            sdk_status_code=exc.sdk_status_code,
        ) from None
    except Exception as exc:
        sdk_exception_type, sdk_status_code = _safe_sdk_exception_details(exc)
        raise P2TokenBudgetError(
            P2TokenBudgetFailure.COUNTER_UNAVAILABLE,
            diagnostic_stage=stage,
            diagnostic_category=P2CounterDiagnosticCategory.SDK_OPERATION_FAILED,
            sdk_exception_type=sdk_exception_type,
            sdk_status_code=sdk_status_code,
        ) from None


@dataclass(frozen=True)
class P2ModelArtifactBinding:
    model_key: str
    artifact_path: Path
    lmstudio_model_path: str
    lmstudio_api_host: str
    artifact_sha256: str
    artifact_size_bytes: int
    expected_context_tokens: int = 8192

    def __post_init__(self) -> None:
        if not self.model_key or len(self.model_key) > 128:
            raise ValueError("model_key is invalid")
        path = Path(self.artifact_path)
        if not path.is_absolute():
            raise ValueError("artifact_path must be absolute")
        object.__setattr__(self, "artifact_path", path)
        if not self.lmstudio_model_path or len(self.lmstudio_model_path) > 512:
            raise ValueError("lmstudio_model_path is invalid")
        try:
            normalized_origin = normalize_local_http_origin(self.lmstudio_api_host)
        except (TypeError, ValueError, UnicodeError):
            raise ValueError("lmstudio_api_host must be an explicit local HTTP origin")
        object.__setattr__(self, "lmstudio_api_host", normalized_origin)
        if len(self.artifact_sha256) != 64 or any(
            char not in "0123456789abcdefABCDEF" for char in self.artifact_sha256
        ):
            raise ValueError("artifact_sha256 must be hexadecimal SHA-256")
        if (
            not isinstance(self.artifact_size_bytes, int)
            or isinstance(self.artifact_size_bytes, bool)
            or self.artifact_size_bytes <= 0
        ):
            raise ValueError("artifact_size_bytes must be positive")
        if (
            not isinstance(self.expected_context_tokens, int)
            or isinstance(self.expected_context_tokens, bool)
            or self.expected_context_tokens <= 0
        ):
            raise ValueError("expected_context_tokens must be positive")


@dataclass(frozen=True)
class P2TokenBudgetPolicy:
    actual_context_tokens: int = 8192
    max_input_tokens: int = 6144
    max_output_tokens: int = 768
    schema_safety_margin_tokens: int = 512
    sdk_call_timeout_seconds: float = 5.0
    artifact_hash_timeout_seconds: float = 5.0
    total_measurement_timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        for name in (
            "actual_context_tokens",
            "max_input_tokens",
            "max_output_tokens",
            "schema_safety_margin_tokens",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if self.actual_context_tokens < 1 or self.max_input_tokens < 1:
            raise ValueError("context and input budgets must be positive")
        if self.max_output_tokens < 1 or self.max_output_tokens > 1536:
            raise ValueError("max_output_tokens must be between 1 and 1536")
        for name in (
            "sdk_call_timeout_seconds",
            "artifact_hash_timeout_seconds",
            "total_measurement_timeout_seconds",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                or not 0.1 <= value <= 5.0
            ):
                raise ValueError(f"{name} must be finite and between 0.1 and 5 seconds")


@dataclass(frozen=True)
class P2ChatMessage:
    role: Literal["system", "user"]
    content: str

    def __post_init__(self) -> None:
        if self.role not in ("system", "user") or not isinstance(self.content, str):
            raise ValueError("invalid typed chat message")


@dataclass(frozen=True)
class P2ResponseFormat:
    """Exact compact provider response_format JSON counted as separate input."""

    payload_json: str

    def __post_init__(self) -> None:
        if not isinstance(self.payload_json, str) or not self.payload_json:
            raise ValueError("payload_json must be nonempty JSON")
        try:
            parsed = json.loads(self.payload_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            raise ValueError("payload_json must be valid JSON") from None
        if not isinstance(parsed, dict) or parsed.get("type") != "json_schema":
            raise ValueError("response format must be a JSON schema object")


@dataclass(frozen=True)
class P2TokenBudgetRequest:
    model_key: str
    api_host: str
    messages: tuple[P2ChatMessage, ...]
    response_format: P2ResponseFormat | None
    max_output_tokens: int

    def __post_init__(self) -> None:
        if not self.model_key or len(self.model_key) > 128:
            raise ValueError("model_key is invalid")
        try:
            normalized_origin = normalize_local_http_origin(self.api_host)
        except (TypeError, ValueError, UnicodeError):
            raise ValueError("api_host must be an explicit local HTTP origin")
        object.__setattr__(self, "api_host", normalized_origin)
        if not is_allowed_p2_message_sequence(self.messages):
            raise ValueError("P2 requests require the fixed system/user shape or a closed format-repair triplet")
        if (
            not isinstance(self.max_output_tokens, int)
            or isinstance(self.max_output_tokens, bool)
            or self.max_output_tokens < 1
        ):
            raise ValueError("max_output_tokens must be positive")


@dataclass(frozen=True)
class P2TokenBudgetMeasurement:
    model_key: str
    api_host: str
    artifact_path: str
    artifact_sha256: str
    actual_context_tokens: int
    prompt_tokens: int
    response_format_tokens: int
    safety_margin_tokens: int
    budgeted_input_tokens: int
    max_input_tokens: int
    requested_output_tokens: int
    max_output_tokens: int
    method: str = "lmstudio-sdk-1.5.0-applyPromptTemplate-countTokens-v1"
    artifact_hash_ms: int = 0
    total_measurement_ms: int = 0

    def __post_init__(self) -> None:
        numeric = (
            self.actual_context_tokens,
            self.prompt_tokens,
            self.response_format_tokens,
            self.safety_margin_tokens,
            self.budgeted_input_tokens,
            self.max_input_tokens,
            self.requested_output_tokens,
            self.max_output_tokens,
            self.artifact_hash_ms,
            self.total_measurement_ms,
        )
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in numeric):
            raise ValueError("measurement numeric fields must be nonnegative integers")
        if self.budgeted_input_tokens != (
            self.prompt_tokens + self.response_format_tokens + self.safety_margin_tokens
        ):
            raise ValueError("budgeted_input_tokens does not match counted components")
        if not self.model_key or not self.artifact_path:
            raise ValueError("measurement binding is incomplete")
        try:
            normalized_origin = normalize_local_http_origin(self.api_host)
        except (TypeError, ValueError, UnicodeError):
            raise ValueError("measurement binding is incomplete") from None
        object.__setattr__(self, "api_host", normalized_origin)


@dataclass(frozen=True)
class P2TokenBudgetSessionReadiness:
    """Nonsecret identity and timing returned by explicit SDK preparation."""

    candidate_id: str
    session_id: str
    sdk_version: str
    model_key: str
    api_host: str
    artifact_path: str
    artifact_sha256: str
    actual_context_tokens: int
    artifact_hash_ms: int
    sdk_prepare_ms: int

    def __post_init__(self) -> None:
        if not all((self.candidate_id, self.session_id, self.sdk_version, self.model_key)):
            raise ValueError("session readiness identity is incomplete")
        if not self.artifact_path:
            raise ValueError("session readiness binding is incomplete")
        try:
            normalized_origin = normalize_local_http_origin(self.api_host)
        except (TypeError, ValueError, UnicodeError):
            raise ValueError("session readiness binding is incomplete") from None
        object.__setattr__(self, "api_host", normalized_origin)
        if len(self.artifact_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in self.artifact_sha256
        ):
            raise ValueError("session readiness artifact digest is invalid")
        if self.actual_context_tokens < 1 or self.artifact_hash_ms < 0 or self.sdk_prepare_ms < 0:
            raise ValueError("session readiness numeric fields are invalid")


@dataclass
class _OwnedSDKSession:
    process: subprocess.Popen[bytes]
    candidate_id: str
    session_id: str
    binding_fingerprint: str
    epoch: int
    cleanup_lock: Lock = field(default_factory=Lock, repr=False, compare=False)
    cleanup_started: bool = field(default=False, repr=False, compare=False)
    cleanup_complete: bool = field(default=False, repr=False, compare=False)
    cleanup_deadline: float | None = field(default=None, repr=False, compare=False)


class P2TokenBudgetChecker(Protocol):
    def measure(self, request: P2TokenBudgetRequest) -> P2TokenBudgetMeasurement:
        """Return verified token counts or raise a sanitized fail-closed error."""


class LMStudioSDKTokenBudgetChecker:
    """Optional exact-model tokenizer counter; it never loads or generates."""

    def __init__(
        self,
        binding: P2ModelArtifactBinding,
        policy: P2TokenBudgetPolicy = P2TokenBudgetPolicy(),
        *,
        python_executable: str | Path | None = None,
        child_timeout_seconds: float = 5.0,
        candidate_id: str | None = None,
    ) -> None:
        if binding.expected_context_tokens != policy.actual_context_tokens:
            raise ValueError("artifact and budget context lengths must match")
        executable = Path(python_executable or sys.executable)
        if not executable.is_absolute():
            raise ValueError("python_executable must be absolute")
        if (
            not isinstance(child_timeout_seconds, (int, float))
            or isinstance(child_timeout_seconds, bool)
            or not math.isfinite(float(child_timeout_seconds))
            or not 0.1 <= child_timeout_seconds <= 5.0
        ):
            raise ValueError("child_timeout_seconds must be between 0.1 and 5 seconds")
        self.binding = binding
        self.policy = policy
        self._python_executable = executable
        self._child_timeout_seconds = float(child_timeout_seconds)
        if candidate_id is None:
            candidate_id = uuid4().hex
        if (
            not isinstance(candidate_id, str)
            or not candidate_id
            or len(candidate_id) > 128
            or any(char not in "0123456789abcdefABCDEF-_" for char in candidate_id)
        ):
            raise ValueError("candidate_id must be a bounded opaque identifier")
        self._candidate_id = candidate_id
        self._cache_lock = Lock()
        self._cached_stat: tuple[str, int, int, int] | None = None
        self._cached_sha256: str | None = None
        self._measurement_lock = Lock()
        self._sdk_prepare_lock = Lock()
        self._state_lock = Lock()
        self._session: _OwnedSDKSession | None = None
        self._session_epoch = 0
        self._session_request_id = 0
        self._session_required = False
        self._session_cleanup_failed = False
        self._closed = Event()

    @property
    def candidate_id(self) -> str:
        """Checker-lifetime candidate identity; callers cannot rebind it."""
        return self._candidate_id

    def measure(self, request: P2TokenBudgetRequest) -> P2TokenBudgetMeasurement:
        # Hash the selected artifact before starting the five-second SDK
        # measurement window. Model files can be large, so use the existing
        # bounded, local-only preparation path once for a cold checker. This
        # performs no SDK call or network operation; _verified_artifact below
        # still rechecks the cached file signature inside the measurement
        # window before binding the SDK result.
        if self._closed.is_set():
            raise P2TokenBudgetError(P2TokenBudgetFailure.SESSION_CLOSED)
        if request.model_key != self.binding.model_key:
            raise P2TokenBudgetError(P2TokenBudgetFailure.MODEL_KEY_MISMATCH)
        if request.api_host != self.binding.lmstudio_api_host:
            raise P2TokenBudgetError(P2TokenBudgetFailure.SERVER_BINDING_MISMATCH)
        if request.max_output_tokens > self.policy.max_output_tokens:
            raise P2TokenBudgetError(P2TokenBudgetFailure.CONTEXT_BUDGET_EXCEEDED)
        _acquire_state_lock_until(self._state_lock, monotonic() + 0.05)
        try:
            preflight_session = self._session
            preflight_session_required = self._session_required
        finally:
            self._state_lock.release()
        if preflight_session_required and preflight_session is None:
            raise P2TokenBudgetError(P2TokenBudgetFailure.SESSION_NOT_PREPARED)
        if preflight_session is None:
            self.prepare_artifact_binding(timeout_seconds=30.0)

        started = monotonic()
        deadline = started + self.policy.total_measurement_timeout_seconds
        remaining = deadline - monotonic()
        if remaining <= 0 or not self._measurement_lock.acquire(timeout=max(0.0, remaining)):
            raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_TIMEOUT)
        session: _OwnedSDKSession | None = None
        session_request_started = False
        try:
            if self._closed.is_set():
                raise P2TokenBudgetError(P2TokenBudgetFailure.SESSION_CLOSED)
            if request.model_key != self.binding.model_key:
                raise P2TokenBudgetError(P2TokenBudgetFailure.MODEL_KEY_MISMATCH)
            if request.api_host != self.binding.lmstudio_api_host:
                raise P2TokenBudgetError(P2TokenBudgetFailure.SERVER_BINDING_MISMATCH)
            if request.max_output_tokens > self.policy.max_output_tokens:
                raise P2TokenBudgetError(P2TokenBudgetFailure.CONTEXT_BUDGET_EXCEEDED)
            _acquire_state_lock_until(self._state_lock, deadline)
            try:
                session = self._session
                session_required = self._session_required
            finally:
                self._state_lock.release()
            if session_required and session is None:
                raise P2TokenBudgetError(P2TokenBudgetFailure.SESSION_NOT_PREPARED)
            file_signature, digest, hash_ms = self._verified_artifact(deadline=deadline)
            request_body = self._request_body(request)
            if session is None:
                payload = {
                    "protocol": _COUNTER_REQUEST_PROTOCOL,
                    "binding": self._binding_payload(digest),
                    "policy": self._policy_payload(),
                    "request": request_body,
                }
                stdin = _json_bytes(payload, limit=_COUNTER_SESSION_INPUT_LIMIT)
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_TIMEOUT)
                try:
                    returncode, stdout = _run_bounded_helper(
                        [str(self._python_executable), "-B", str(Path(__file__).resolve()), "--counter-child"],
                        stdin=stdin,
                        timeout=min(self._child_timeout_seconds, remaining),
                    )
                except _CounterHelperTimeout as exc:
                    raise P2TokenBudgetError(
                        P2TokenBudgetFailure.COUNTER_TIMEOUT,
                        diagnostic_stage=exc.diagnostic_stage,
                        diagnostic_category=(
                            P2CounterDiagnosticCategory.DEADLINE
                            if exc.diagnostic_stage is not None
                            else None
                        ),
                    ) from None
                except TimeoutError:
                    raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_TIMEOUT) from None
                except (OSError, ValueError):
                    raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_UNAVAILABLE) from None
                if monotonic() > deadline:
                    raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_TIMEOUT)
                if returncode != 0:
                    raise _safe_child_error(stdout)
                result = _parse_child_output(stdout)
            else:
                if session.process.poll() is not None:
                    self._invalidate_session(session, deadline=deadline)
                    raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_UNAVAILABLE)
                _acquire_state_lock_until(self._state_lock, deadline)
                try:
                    self._session_request_id += 1
                    request_id = self._session_request_id
                finally:
                    self._state_lock.release()
                payload = {
                    "protocol": _COUNTER_SESSION_PROTOCOL,
                    "operation": "measure",
                    "candidate_id": session.candidate_id,
                    "session_id": session.session_id,
                    "binding_fingerprint": session.binding_fingerprint,
                    "request_id": request_id,
                    "policy": self._policy_payload(),
                    "request": request_body,
                }
                session_request_started = True
                try:
                    stdout = _exchange_process_line(session.process, payload, deadline=deadline)
                    result = _parse_session_output(
                        stdout,
                        candidate_id=session.candidate_id,
                        session_id=session.session_id,
                        binding_fingerprint=session.binding_fingerprint,
                        request_id=request_id,
                    )
                    if monotonic() >= deadline:
                        raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_TIMEOUT)
                except TimeoutError:
                    raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_TIMEOUT) from None
                except P2TokenBudgetError:
                    raise
                except (OSError, ValueError, UnicodeError):
                    raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE) from None
                if self._closed.is_set() or not self._session_is_current(session, deadline=deadline):
                    self._invalidate_session(session, deadline=deadline)
                    raise P2TokenBudgetError(P2TokenBudgetFailure.SESSION_CLOSED)

            current_signature, current_digest, _ = self._verified_artifact(deadline=deadline)
            if current_signature != file_signature or current_digest != digest:
                raise P2TokenBudgetError(P2TokenBudgetFailure.ARTIFACT_BINDING_CHANGED)
            if result["model_key"] != self.binding.model_key:
                raise P2TokenBudgetError(P2TokenBudgetFailure.MODEL_KEY_MISMATCH)
            if result["api_host"] != self.binding.lmstudio_api_host:
                raise P2TokenBudgetError(P2TokenBudgetFailure.SERVER_BINDING_MISMATCH)
            if result["model_path"] != self.binding.lmstudio_model_path:
                raise P2TokenBudgetError(P2TokenBudgetFailure.MODEL_PATH_MISMATCH)
            if result["artifact_sha256"] != digest:
                raise P2TokenBudgetError(P2TokenBudgetFailure.ARTIFACT_BINDING_CHANGED)
            if result["actual_context_tokens"] != self.policy.actual_context_tokens:
                raise P2TokenBudgetError(P2TokenBudgetFailure.CONTEXT_MISMATCH)
            prompt_tokens = result["prompt_tokens"]
            response_format_tokens = result["response_format_tokens"]
            budgeted_input_tokens = (
                prompt_tokens + response_format_tokens + self.policy.schema_safety_margin_tokens
            )
            if budgeted_input_tokens > self.policy.max_input_tokens:
                raise P2TokenBudgetError(P2TokenBudgetFailure.INPUT_BUDGET_EXCEEDED)
            if budgeted_input_tokens + request.max_output_tokens > result["actual_context_tokens"]:
                raise P2TokenBudgetError(P2TokenBudgetFailure.CONTEXT_BUDGET_EXCEEDED)
            if monotonic() >= deadline:
                raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_TIMEOUT)
            _acquire_state_lock_until(self._state_lock, deadline)
            try:
                current = self._session
                if self._closed.is_set():
                    raise P2TokenBudgetError(P2TokenBudgetFailure.SESSION_CLOSED)
                if session is not None and (
                    current is None
                    or current.process is not session.process
                    or current.session_id != session.session_id
                    or current.epoch != session.epoch
                ):
                    raise P2TokenBudgetError(P2TokenBudgetFailure.SESSION_CLOSED)
                if session is None and (self._session_required or current is not None):
                    raise P2TokenBudgetError(P2TokenBudgetFailure.SESSION_NOT_PREPARED)
                return P2TokenBudgetMeasurement(
                    model_key=result["model_key"],
                    api_host=result["api_host"],
                    artifact_path=result["model_path"],
                    artifact_sha256=result["artifact_sha256"],
                    actual_context_tokens=result["actual_context_tokens"],
                    prompt_tokens=prompt_tokens,
                    response_format_tokens=response_format_tokens,
                    safety_margin_tokens=self.policy.schema_safety_margin_tokens,
                    budgeted_input_tokens=budgeted_input_tokens,
                    max_input_tokens=self.policy.max_input_tokens,
                    requested_output_tokens=request.max_output_tokens,
                    max_output_tokens=self.policy.max_output_tokens,
                    artifact_hash_ms=hash_ms,
                    total_measurement_ms=int((monotonic() - started) * 1000),
                )
            finally:
                self._state_lock.release()
        except P2TokenBudgetError as exc:
            if session is not None:
                if exc.reason == P2TokenBudgetFailure.ARTIFACT_BINDING_CHANGED:
                    self._invalidate_session(session, deadline=deadline)
                elif session_request_started and exc.reason not in {
                    P2TokenBudgetFailure.INPUT_BUDGET_EXCEEDED,
                    P2TokenBudgetFailure.CONTEXT_BUDGET_EXCEEDED,
                }:
                    self._invalidate_session(session, deadline=deadline)
            raise
        finally:
            self._measurement_lock.release()

    def _binding_payload(self, digest: str) -> dict[str, object]:
        return {
            "model_key": self.binding.model_key,
            "api_host": self.binding.lmstudio_api_host,
            "lmstudio_model_path": self.binding.lmstudio_model_path,
            "artifact_sha256": digest,
            "artifact_size_bytes": self.binding.artifact_size_bytes,
            "actual_context_tokens": self.policy.actual_context_tokens,
        }

    def _policy_payload(self) -> dict[str, object]:
        return {
            "max_input_tokens": self.policy.max_input_tokens,
            "max_output_tokens": self.policy.max_output_tokens,
            "schema_safety_margin_tokens": self.policy.schema_safety_margin_tokens,
            "sdk_call_timeout_seconds": self.policy.sdk_call_timeout_seconds,
        }

    @staticmethod
    def _request_body(request: P2TokenBudgetRequest) -> dict[str, object]:
        return {
            "model_key": request.model_key,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
            "response_format_json": (
                request.response_format.payload_json if request.response_format else None
            ),
            "max_output_tokens": request.max_output_tokens,
        }

    def verify_artifact_binding(self) -> tuple[str, int]:
        """Verify the artifact under the regular policy deadline; no SDK/network call."""
        started = monotonic()
        deadline = started + self.policy.artifact_hash_timeout_seconds
        _, digest, elapsed_ms = self._verified_artifact(deadline=deadline)
        if monotonic() > deadline:
            raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_TIMEOUT)
        return digest, elapsed_ms

    def prepare_artifact_binding(
        self,
        *,
        timeout_seconds: float = 30.0,
    ) -> tuple[str, int]:
        """Explicitly hash and cache the bound local artifact, without SDK/network I/O.

        This is an operator-invoked readiness step for large local model files.
        Its separate deadline does not change the regular five-second limits on
        ``verify_artifact_binding`` or ``measure``. Only a complete hash whose
        before/after file signatures and configured size/digest all match is
        admitted to this checker's in-memory cache.
        """
        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or not math.isfinite(float(timeout_seconds))
            or not 0.1 <= timeout_seconds <= 30.0
        ):
            raise ValueError("timeout_seconds must be finite and between 0.1 and 30 seconds")
        started = monotonic()
        deadline = started + float(timeout_seconds)
        _, digest, elapsed_ms = self._verified_artifact(deadline=deadline)
        if monotonic() >= deadline:
            raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_TIMEOUT)
        return digest, elapsed_ms

    def prepare_sdk_session(
        self,
        *,
        timeout_seconds: float = 15.0,
    ) -> P2TokenBudgetSessionReadiness:
        """Explicitly open one SDK helper bound to this checker and candidate.

        Local artifact hashing has its own explicit 30-second readiness bound.
        SDK import, explicit-origin client creation, and the initial fresh loaded
        model binding must finish within ``timeout_seconds`` (at most 15s).
        This method never autoloads a model and is never called by health or
        ordinary construction. A failed attempt leaves session mode required;
        callers must explicitly prepare again rather than falling back to the
        cold one-shot counter.
        """
        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or not math.isfinite(float(timeout_seconds))
            or not 0.1 <= timeout_seconds <= 15.0
        ):
            raise ValueError("timeout_seconds must be finite and between 0.1 and 15 seconds")
        if not self._state_lock.acquire(timeout=0.05):
            raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_TIMEOUT)
        try:
            self._session_required = True
            if self._closed.is_set():
                raise P2TokenBudgetError(P2TokenBudgetFailure.SESSION_CLOSED)
            if self._session_cleanup_failed:
                raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_UNAVAILABLE)
        finally:
            self._state_lock.release()
        digest, hash_ms = self.prepare_artifact_binding(timeout_seconds=30.0)
        sdk_started = monotonic()
        sdk_deadline = sdk_started + float(timeout_seconds)
        remaining = sdk_deadline - monotonic()
        if remaining <= 0 or not self._measurement_lock.acquire(timeout=max(0.0, remaining)):
            raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_TIMEOUT)
        owned: _OwnedSDKSession | None = None
        try:
            _acquire_state_lock_until(self._state_lock, sdk_deadline)
            try:
                if self._closed.is_set():
                    raise P2TokenBudgetError(P2TokenBudgetFailure.SESSION_CLOSED)
                if self._session_cleanup_failed:
                    raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_UNAVAILABLE)
            finally:
                self._state_lock.release()
            old = self._detach_session(deadline=sdk_deadline)
            if old is not None and not self._terminate_session(old):
                raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_UNAVAILABLE)
            if self._closed.is_set():
                raise P2TokenBudgetError(P2TokenBudgetFailure.SESSION_CLOSED)
            if monotonic() >= sdk_deadline:
                raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_TIMEOUT)
            session_id = uuid4().hex
            binding = self._binding_payload(digest)
            binding_fingerprint = hashlib.sha256(
                _json_bytes(
                    {"candidate_id": self.candidate_id, "binding": binding},
                    limit=_COUNTER_SESSION_INPUT_LIMIT,
                )
            ).hexdigest()
            bootstrap = {
                "protocol": _COUNTER_SESSION_PROTOCOL,
                "operation": "prepare",
                "candidate_id": self.candidate_id,
                "session_id": session_id,
                "request_id": 0,
                "binding_fingerprint": binding_fingerprint,
                "binding": binding,
                "policy": self._policy_payload(),
            }
            process = subprocess.Popen(
                self._session_helper_args(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                shell=False,
                bufsize=0,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            owned = _OwnedSDKSession(
                process=process,
                candidate_id=self.candidate_id,
                session_id=session_id,
                binding_fingerprint=binding_fingerprint,
                epoch=self._session_epoch + 1,
            )
            _acquire_state_lock_until(self._state_lock, sdk_deadline)
            try:
                if self._closed.is_set():
                    raise P2TokenBudgetError(P2TokenBudgetFailure.SESSION_CLOSED)
                self._session_epoch += 1
                owned = _OwnedSDKSession(
                    process=process,
                    candidate_id=self.candidate_id,
                    session_id=session_id,
                    binding_fingerprint=binding_fingerprint,
                    epoch=self._session_epoch,
                )
                self._session = owned
                self._session_request_id = 0
            finally:
                self._state_lock.release()
            if self._closed.is_set():
                raise P2TokenBudgetError(P2TokenBudgetFailure.SESSION_CLOSED)
            if monotonic() >= sdk_deadline:
                raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_TIMEOUT)
            stdout = _exchange_process_line(process, bootstrap, deadline=sdk_deadline)
            ready = _parse_session_ready(
                stdout,
                candidate_id=self.candidate_id,
                session_id=session_id,
                binding_fingerprint=binding_fingerprint,
            )
            current_signature, current_digest, _ = self._verified_artifact(deadline=sdk_deadline)
            if current_digest != digest or current_signature != self._cached_stat:
                raise P2TokenBudgetError(P2TokenBudgetFailure.ARTIFACT_BINDING_CHANGED)
            if ready["sdk_version"] != "1.5.0":
                raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_UNAVAILABLE)
            if process.poll() is not None or self._closed.is_set() or not self._session_is_current(owned, deadline=sdk_deadline):
                raise P2TokenBudgetError(P2TokenBudgetFailure.SESSION_CLOSED)
            if monotonic() >= sdk_deadline:
                raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_TIMEOUT)
            return P2TokenBudgetSessionReadiness(
                candidate_id=self.candidate_id,
                session_id=session_id,
                sdk_version=ready["sdk_version"],
                model_key=self.binding.model_key,
                api_host=self.binding.lmstudio_api_host,
                artifact_path=str(self.binding.artifact_path.resolve(strict=True)),
                artifact_sha256=digest,
                actual_context_tokens=self.policy.actual_context_tokens,
                artifact_hash_ms=hash_ms,
                sdk_prepare_ms=int((monotonic() - sdk_started) * 1000),
            )
        except TimeoutError:
            if owned is not None:
                self._invalidate_session(owned, deadline=sdk_deadline)
            raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_TIMEOUT) from None
        except P2TokenBudgetError as exc:
            if owned is not None:
                self._invalidate_session(owned, deadline=sdk_deadline)
            if exc.reason == P2TokenBudgetFailure.ARTIFACT_BINDING_CHANGED:
                raise
            raise
        except (OSError, ValueError, UnicodeError):
            if owned is not None:
                self._invalidate_session(owned, deadline=sdk_deadline)
            raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_UNAVAILABLE) from None
        finally:
            self._measurement_lock.release()

    def ensure_sdk_session(self, *, timeout_seconds: float = 15.0) -> None:
        """Prepare the exact loaded-model SDK session once before JIT counting.

        Cold SDK import and client setup are not part of the five-second token
        measurement window. The normal provider path calls this before
        ``measure``; subsequent calls reuse the same live, bound helper. A
        failed or later-dead prepared session stays fail-closed and is never
        silently rebuilt or downgraded to a one-shot child.
        """
        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or not math.isfinite(float(timeout_seconds))
            or not 0.1 <= timeout_seconds <= 15.0
        ):
            raise ValueError("timeout_seconds must be finite and between 0.1 and 15 seconds")
        if not self._sdk_prepare_lock.acquire(timeout=float(timeout_seconds)):
            raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_TIMEOUT)
        try:
            if self._closed.is_set():
                raise P2TokenBudgetError(P2TokenBudgetFailure.SESSION_CLOSED)
            if not self._state_lock.acquire(timeout=0.05):
                raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_TIMEOUT)
            try:
                session = self._session
                session_required = self._session_required
                cleanup_failed = self._session_cleanup_failed
            finally:
                self._state_lock.release()
            if cleanup_failed:
                raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_UNAVAILABLE)
            if session is not None:
                if session.process.poll() is not None:
                    self._invalidate_session(session)
                    raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_UNAVAILABLE)
                if not self._session_is_current(session, deadline=monotonic() + 0.05):
                    raise P2TokenBudgetError(P2TokenBudgetFailure.SESSION_CLOSED)
                return
            if session_required:
                raise P2TokenBudgetError(P2TokenBudgetFailure.SESSION_NOT_PREPARED)
            self.prepare_sdk_session(timeout_seconds=float(timeout_seconds))
        finally:
            self._sdk_prepare_lock.release()

    def _session_helper_args(self) -> list[str]:
        return [
            str(self._python_executable),
            "-B",
            str(Path(__file__).resolve()),
            "--counter-session-child",
        ]

    def _session_is_current(self, session: _OwnedSDKSession, *, deadline: float) -> bool:
        _acquire_state_lock_until(self._state_lock, deadline)
        try:
            current = self._session
            return (
                current is not None
                and current.process is session.process
                and current.candidate_id == session.candidate_id
                and current.session_id == session.session_id
                and current.binding_fingerprint == session.binding_fingerprint
                and current.epoch == session.epoch
            )
        finally:
            self._state_lock.release()

    def _detach_session(self, *, deadline: float) -> _OwnedSDKSession | None:
        _acquire_state_lock_until(self._state_lock, deadline)
        try:
            current = self._session
            self._session = None
            self._session_epoch += 1
            return current
        finally:
            self._state_lock.release()

    def _invalidate_session(self, session: _OwnedSDKSession, *, deadline: float | None = None) -> None:
        lock_wait = 0.05 if deadline is None else max(0.0, min(0.05, deadline - monotonic()))
        acquired = self._state_lock.acquire(timeout=lock_wait)
        if acquired:
            try:
                if self._session is not None and self._session.process is session.process:
                    self._session = None
                    self._session_epoch += 1
            finally:
                self._state_lock.release()
        self._terminate_session(session)

    def _terminate_session(
        self,
        session: _OwnedSDKSession,
    ) -> bool:
        """Give exactly one caller the bounded cleanup for this child/session."""
        if not session.cleanup_lock.acquire(blocking=False):
            return False
        try:
            if session.cleanup_started:
                return session.cleanup_complete
            session.cleanup_started = True
            session.cleanup_deadline = monotonic() + _COUNTER_SESSION_CLEANUP_GRACE_SECONDS
            threads = getattr(session.process, "_p2_pipe_threads", ())
            if not isinstance(threads, tuple) or any(not isinstance(item, Thread) for item in threads):
                threads = ()
            session.cleanup_complete = _terminate_owned_process(
                session.process,
                threads=threads,
                deadline=session.cleanup_deadline,
            )
            if (
                session.cleanup_complete
                and threads
                and getattr(session.process, "_p2_pipe_threads", None) is threads
            ):
                delattr(session.process, "_p2_pipe_threads")
            self._session_cleanup_failed = not session.cleanup_complete
            return session.cleanup_complete
        finally:
            session.cleanup_lock.release()

    def close(self) -> None:
        """Idempotently close this checker and kill only its SDK helper child."""
        if not self._state_lock.acquire(timeout=0.05):
            # The event prevents any not-yet-published preparation from being
            # admitted. If a session is already visible, terminate that exact
            # checker-owned process without waiting for the state lock.
            self._closed.set()
            session = self._session
            if session is not None:
                self._terminate_session(session)
            return
        try:
            self._closed.set()
            session = self._session
            self._session = None
            self._session_epoch += 1
        finally:
            self._state_lock.release()
        if session is not None:
            self._terminate_session(session)

    def _verified_artifact(
        self,
        *,
        deadline: float,
    ) -> tuple[tuple[str, int, int, int], str, int]:
        remaining = deadline - monotonic()
        if remaining <= 0 or not self._cache_lock.acquire(timeout=max(0.0, remaining)):
            raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_TIMEOUT)
        try:
            try:
                before = _stat_signature(self.binding.artifact_path)
            except OSError:
                raise P2TokenBudgetError(P2TokenBudgetFailure.ARTIFACT_BINDING_CHANGED) from None
            if before[1] != self.binding.artifact_size_bytes:
                raise P2TokenBudgetError(P2TokenBudgetFailure.ARTIFACT_BINDING_CHANGED)
            if self._cached_stat is not None:
                if before != self._cached_stat or self._cached_sha256 != self.binding.artifact_sha256.casefold():
                    raise P2TokenBudgetError(P2TokenBudgetFailure.ARTIFACT_BINDING_CHANGED)
                if monotonic() >= deadline:
                    raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_TIMEOUT)
                return before, self._cached_sha256, 0
            started = monotonic()
            digest = hashlib.sha256()
            try:
                with self.binding.artifact_path.open("rb") as file:
                    while chunk := file.read(1_048_576):
                        digest.update(chunk)
                        if monotonic() > deadline:
                            raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_TIMEOUT)
                after = _stat_signature(self.binding.artifact_path)
            except P2TokenBudgetError:
                raise
            except OSError:
                raise P2TokenBudgetError(P2TokenBudgetFailure.ARTIFACT_BINDING_CHANGED) from None
            if before != after:
                raise P2TokenBudgetError(P2TokenBudgetFailure.ARTIFACT_BINDING_CHANGED)
            if monotonic() >= deadline:
                raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_TIMEOUT)
            actual_hash = digest.hexdigest()
            if actual_hash != self.binding.artifact_sha256.casefold():
                raise P2TokenBudgetError(P2TokenBudgetFailure.ARTIFACT_BINDING_CHANGED)
            self._cached_stat = after
            self._cached_sha256 = actual_hash
            return after, actual_hash, int((monotonic() - started) * 1000)
        finally:
            self._cache_lock.release()


def _stat_signature(path: Path) -> tuple[str, int, int, int]:
    stat = path.stat()
    if not path.is_file():
        raise OSError("artifact is not a regular file")
    resolved = str(path.resolve(strict=True))
    return (resolved, stat.st_size, stat.st_mtime_ns, getattr(stat, "st_ino", 0))


def _acquire_state_lock_until(lock: Lock, deadline: float) -> None:
    """Bound checker-state synchronization by the caller's active deadline."""
    remaining = deadline - monotonic()
    if remaining <= 0 or not lock.acquire(timeout=remaining):
        raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_TIMEOUT)


def _safe_child_error(stdout: bytes) -> P2TokenBudgetError:
    try:
        payload, _ = _decode_counter_child_output(stdout)
    except (UnicodeError, ValueError, json.JSONDecodeError):
        return P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    expected = {
        "ok",
        "error",
        "diagnostic_stage",
        "diagnostic_category",
        "sdk_exception_type",
        "sdk_status_code",
    }
    if not isinstance(payload, dict) or set(payload) != expected or payload.get("ok") is not False:
        return P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    try:
        reason = P2TokenBudgetFailure(payload["error"])
        stage = P2CounterDiagnosticStage(payload["diagnostic_stage"])
        category = P2CounterDiagnosticCategory(payload["diagnostic_category"])
    except (TypeError, ValueError):
        return P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    exception_type = payload["sdk_exception_type"]
    status_code = payload["sdk_status_code"]
    if exception_type is not None and _safe_sdk_exception_type_name(exception_type) != exception_type:
        return P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    if status_code is not None and _safe_sdk_status_code(status_code) != status_code:
        return P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    if category is not P2CounterDiagnosticCategory.SDK_OPERATION_FAILED and (
        exception_type is not None or status_code is not None
    ):
        return P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    return P2TokenBudgetError(
        reason,
        diagnostic_stage=stage,
        diagnostic_category=category,
        sdk_exception_type=exception_type,
        sdk_status_code=status_code,
    )


def _parse_child_output(stdout: bytes) -> dict[str, int | str]:
    try:
        payload, _ = _decode_counter_child_output(stdout)
    except (UnicodeError, ValueError, json.JSONDecodeError):
        raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE) from None
    expected = {
        "ok",
        "model_key",
        "api_host",
        "model_path",
        "artifact_sha256",
        "actual_context_tokens",
        "prompt_tokens",
        "response_format_tokens",
    }
    if isinstance(payload, dict) and payload.get("ok") is False:
        raise _safe_child_error(stdout)
    if not isinstance(payload, dict) or set(payload) != expected or payload.get("ok") is not True:
        raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    for name in ("model_key", "api_host", "model_path", "artifact_sha256"):
        if not isinstance(payload[name], str):
            raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    for name in ("actual_context_tokens", "prompt_tokens", "response_format_tokens"):
        value = payload[name]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    return payload


def _decode_counter_child_output(
    stdout: bytes,
) -> tuple[dict[str, object], P2CounterDiagnosticStage | None]:
    """Decode strict private progress records followed by one final JSON result."""
    lines = stdout.decode("utf-8", errors="strict").splitlines()
    if not lines:
        raise ValueError("counter child output is empty")
    for line in lines[:-1]:
        event = json.loads(line)
        if not isinstance(event, dict) or set(event) != {"progress_stage"}:
            raise ValueError("counter child progress event is invalid")
        P2CounterDiagnosticStage(event["progress_stage"])
    final = json.loads(lines[-1])
    if not isinstance(final, dict):
        raise ValueError("counter child result is not an object")
    progress_stage = None
    if len(lines) > 1:
        last_event = json.loads(lines[-2])
        progress_stage = P2CounterDiagnosticStage(last_event["progress_stage"])
    return final, progress_stage


def _json_bytes(payload: dict[str, object], *, limit: int) -> bytes:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > limit:
        raise ValueError("counter helper message exceeds its bound")
    return encoded


def _parse_session_ready(
    stdout: bytes,
    *,
    candidate_id: str,
    session_id: str,
    binding_fingerprint: str,
) -> dict[str, str]:
    try:
        payload = json.loads(stdout.decode("utf-8", errors="strict"))
    except (UnicodeError, ValueError, json.JSONDecodeError):
        raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE) from None
    expected = {
        "protocol",
        "operation",
        "candidate_id",
        "session_id",
        "binding_fingerprint",
        "ok",
        "sdk_version",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != expected
        or payload.get("protocol") != _COUNTER_SESSION_PROTOCOL
        or payload.get("operation") != "ready"
        or payload.get("ok") is not True
        or payload.get("candidate_id") != candidate_id
        or payload.get("session_id") != session_id
        or payload.get("binding_fingerprint") != binding_fingerprint
        or payload.get("sdk_version") != "1.5.0"
    ):
        raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    return {"sdk_version": payload["sdk_version"]}


def _parse_session_output(
    stdout: bytes,
    *,
    candidate_id: str,
    session_id: str,
    binding_fingerprint: str,
    request_id: int,
) -> dict[str, int | str]:
    try:
        payload = json.loads(stdout.decode("utf-8", errors="strict"))
    except (UnicodeError, ValueError, json.JSONDecodeError):
        raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE) from None
    common = {
        "protocol",
        "operation",
        "candidate_id",
        "session_id",
        "binding_fingerprint",
        "request_id",
        "ok",
    }
    if (
        not isinstance(payload, dict)
        or payload.get("protocol") != _COUNTER_SESSION_PROTOCOL
        or payload.get("operation") != "result"
        or payload.get("candidate_id") != candidate_id
        or payload.get("session_id") != session_id
        or payload.get("binding_fingerprint") != binding_fingerprint
        or not isinstance(payload.get("request_id"), int)
        or isinstance(payload.get("request_id"), bool)
        or payload.get("request_id") != request_id
        or not isinstance(payload.get("ok"), bool)
    ):
        raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    if payload["ok"] is False:
        if set(payload) != common | {"error"}:
            raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
        reason = payload.get("error")
        allowed = {item.value for item in P2TokenBudgetFailure}
        if not isinstance(reason, str) or reason not in allowed:
            raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
        raise P2TokenBudgetError(reason)
    if set(payload) != common | {"measurement"} or not isinstance(payload["measurement"], dict):
        raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    encoded = _json_bytes(payload["measurement"], limit=_COUNTER_SESSION_OUTPUT_LIMIT)
    return _parse_child_output(encoded)


def _exchange_process_line(
    process: subprocess.Popen[bytes],
    payload: dict[str, object],
    *,
    deadline: float,
) -> bytes:
    """Exchange one bounded JSON line with one owned, single-flight child."""
    if process.poll() is not None or process.stdin is None or process.stdout is None:
        raise OSError("counter session child is unavailable")
    message = _json_bytes(payload, limit=_COUNTER_SESSION_INPUT_LIMIT) + b"\n"
    output: list[bytes] = []
    writer_error: list[BaseException] = []
    reader_error: list[BaseException] = []
    writer_done = Event()
    reader_done = Event()

    def write_message() -> None:
        try:
            remaining = memoryview(message)
            while remaining:
                count = process.stdin.write(remaining)
                if count is None or count <= 0:
                    raise OSError("counter session input pipe closed")
                remaining = remaining[count:]
            process.stdin.flush()
        except BaseException as exc:
            writer_error.append(exc)
        finally:
            writer_done.set()

    def read_message() -> None:
        try:
            raw = process.stdout.readline(_COUNTER_SESSION_OUTPUT_LIMIT + 1)
            if len(raw) > _COUNTER_SESSION_OUTPUT_LIMIT:
                raise ValueError("counter session response exceeds its bound")
            if not raw.endswith(b"\n"):
                raise ValueError("counter session response is not one complete line")
            output.append(raw[:-1])
        except BaseException as exc:
            reader_error.append(exc)
        finally:
            reader_done.set()

    writer = Thread(target=write_message, name="p2-token-session-input", daemon=True)
    reader = Thread(target=read_message, name="p2-token-session-output", daemon=True)
    pipe_threads = (writer, reader)
    # The session cleanup owner needs these exact threads if the exchange
    # fails while either pipe operation is blocked.
    setattr(process, "_p2_pipe_threads", pipe_threads)
    failure: BaseException | None = None
    try:
        writer.start()
        reader.start()
        while not (writer_done.is_set() and reader_done.is_set()):
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise TimeoutError()
            if process.poll() is not None and not reader_done.is_set():
                # Give the reader one short opportunity to observe EOF.
                reader_done.wait(min(0.01, remaining))
            else:
                reader_done.wait(min(0.01, remaining))
        if writer_error:
            raise OSError("counter session input failed") from writer_error[0]
        if reader_error:
            raise ValueError("counter session output failed") from reader_error[0]
        if monotonic() >= deadline or len(output) != 1:
            raise TimeoutError()
        if getattr(process, "_p2_pipe_threads", None) is pipe_threads:
            delattr(process, "_p2_pipe_threads")
        return output[0]
    except BaseException as exc:
        failure = exc
    if isinstance(failure, TimeoutError):
        raise failure
    if isinstance(failure, (OSError, ValueError)):
        raise failure
    raise OSError("counter session exchange failed") from failure


def _terminate_owned_process(
    process: subprocess.Popen[bytes],
    *,
    threads: tuple[Thread, ...] = (),
    deadline: float | None = None,
) -> bool:
    """Kill and reap only this checker-owned helper with one bounded grace."""
    cleanup_deadline = (
        min(deadline, monotonic() + _COUNTER_SESSION_CLEANUP_GRACE_SECONDS)
        if deadline is not None
        else monotonic() + _COUNTER_SESSION_CLEANUP_GRACE_SECONDS
    )
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=max(0.0, cleanup_deadline - monotonic()))
    except (subprocess.TimeoutExpired, OSError):
        pass
    for stream in (process.stdin, process.stdout):
        if stream is not None:
            try:
                stream.close()
            except (OSError, ValueError):
                pass
    for thread in threads:
        if thread.ident is None:
            continue
        remaining = cleanup_deadline - monotonic()
        if remaining <= 0:
            break
        thread.join(timeout=remaining)
    return process.poll() is not None and all(not thread.is_alive() for thread in threads)


class _CounterHelperTimeout(TimeoutError):
    def __init__(self, diagnostic_stage: P2CounterDiagnosticStage | None) -> None:
        self.diagnostic_stage = diagnostic_stage
        super().__init__("counter helper deadline expired")


def _last_counter_progress_stage(output: bytes) -> P2CounterDiagnosticStage | None:
    try:
        text = output.decode("utf-8", errors="strict")
    except UnicodeError:
        return None
    last: P2CounterDiagnosticStage | None = None
    for line in text.splitlines():
        try:
            event = json.loads(line)
            if isinstance(event, dict) and set(event) == {"progress_stage"}:
                last = P2CounterDiagnosticStage(event["progress_stage"])
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return last


def _run_bounded_helper(args: list[str], *, stdin: bytes, timeout: float) -> tuple[int, bytes]:
    """Run only our SDK helper, with bounded pipes and discarded stderr.

    The five-second deadline covers normal process/pipe work. If it expires,
    cleanup may take one additional second while this owned child and its pipe
    threads terminate; callers must not describe timeout cleanup as a hard
    five-second wall-clock bound.
    """
    output_limit = 4096
    input_limit = 1_000_000
    if len(stdin) > input_limit:
        raise ValueError("counter helper input exceeds its bound")
    deadline = monotonic() + timeout
    process = subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        shell=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if process.stdin is None or process.stdout is None:
        process.kill()
        process.wait()
        raise OSError("counter helper pipes unavailable")
    output = bytearray()
    overflow = Event()
    reader_failed = Event()
    writer_failed = Event()

    def read_bounded_output() -> None:
        try:
            read_chunk = getattr(process.stdout, "read1", process.stdout.read)
            while len(output) <= output_limit:
                chunk = read_chunk(min(1024, output_limit + 1 - len(output)))
                if not chunk:
                    return
                output.extend(chunk)
                if len(output) > output_limit:
                    overflow.set()
                    try:
                        process.kill()
                    except OSError:
                        pass
                    return
        except OSError:
            reader_failed.set()

    def write_bounded_input() -> None:
        try:
            process.stdin.write(stdin)
            process.stdin.close()
        except (OSError, ValueError):
            writer_failed.set()

    reader = Thread(target=read_bounded_output, name="p2-token-counter-output", daemon=True)
    reader.start()
    writer = Thread(target=write_bounded_input, name="p2-token-counter-input", daemon=True)
    writer.start()
    timed_out = False
    returncode: int | None = None
    failure: BaseException | None = None
    result_data: tuple[int, bytes] | None = None
    try:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(args, timeout)
        returncode = process.wait(timeout=remaining)
        remaining = deadline - monotonic()
        if remaining > 0:
            writer.join(timeout=remaining)
        remaining = deadline - monotonic()
        if remaining > 0:
            reader.join(timeout=remaining)
        if writer.is_alive() or reader.is_alive():
            raise subprocess.TimeoutExpired(args, timeout)
        if overflow.is_set() or reader_failed.is_set():
            raise ValueError("counter helper output invalid")
        if writer_failed.is_set() and returncode == 0:
            raise ValueError("counter helper input was not accepted")
        result_data = (returncode, bytes(output))
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        failure = exc
    except BaseException as exc:
        failure = exc
    finally:
        # Kill only the child created above. Killing it closes the read end of
        # stdin and releases a writer blocked on a full Windows pipe.
        cleanup_deadline = monotonic() + 1.0
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
        try:
            process.wait(timeout=max(0.0, cleanup_deadline - monotonic()))
        except subprocess.TimeoutExpired:
            pass
        for thread in (writer, reader):
            remaining = cleanup_deadline - monotonic()
            if remaining <= 0:
                break
            thread.join(timeout=remaining)
        if writer.is_alive() or reader.is_alive():
            if failure is None:
                failure = OSError("counter helper pipe thread did not stop")
        try:
            process.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            process.stdout.close()
        except (OSError, ValueError):
            pass
    if timed_out:
        raise _CounterHelperTimeout(_last_counter_progress_stage(bytes(output))) from None
    if failure is not None:
        raise failure
    if returncode is None:
        raise OSError("counter helper returned no process status")
    if result_data is None:
        raise OSError("counter helper result was not collected")
    return result_data


def _counter_child() -> int:
    """Private stdin/stdout helper entry point. Never emits raw SDK exceptions."""
    global _COUNTER_PROGRESS_WRITER
    try:
        payload = json.loads(sys.stdin.buffer.read(2_000_000).decode("utf-8", errors="strict"))
        if not isinstance(payload, dict) or payload.get("protocol") != _COUNTER_REQUEST_PROTOCOL:
            raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
        binding = payload["binding"]
        policy = payload["policy"]
        request = payload["request"]
        if not all(isinstance(item, dict) for item in (binding, policy, request)):
            raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
        if request.get("model_key") != binding.get("model_key"):
            raise P2TokenBudgetError(P2TokenBudgetFailure.MODEL_KEY_MISMATCH)
        if request.get("max_output_tokens", 0) > policy.get("max_output_tokens", 0):
            raise P2TokenBudgetError(P2TokenBudgetFailure.CONTEXT_BUDGET_EXCEEDED)
        messages_data = request.get("messages")
        if not isinstance(messages_data, list):
            raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
        if any(
            not isinstance(message, dict)
            or set(message) != {"role", "content"}
            or message.get("role") not in {"system", "user"}
            or not isinstance(message.get("content"), str)
            for message in messages_data
        ):
            raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
        if not is_allowed_p2_message_sequence(messages_data):
            raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
        response_format = request.get("response_format_json")
        if response_format is not None and not isinstance(response_format, str):
            raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
        for name in (
            "model_key",
            "api_host",
            "lmstudio_model_path",
            "artifact_sha256",
            "artifact_size_bytes",
            "actual_context_tokens",
        ):
            if name not in binding:
                raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)

        previous_progress_writer = _COUNTER_PROGRESS_WRITER

        def write_progress(stage: P2CounterDiagnosticStage) -> None:
            event = json.dumps(
                {"progress_stage": stage.value},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8") + b"\n"
            sys.stdout.buffer.write(event)
            sys.stdout.buffer.flush()

        _COUNTER_PROGRESS_WRITER = write_progress
        try:
            def import_lmstudio() -> object:
                import lmstudio as lms
                return lms

            lms = _counter_stage_call(P2CounterDiagnosticStage.SDK_IMPORT, import_lmstudio)
            output = _measure_loaded_model(lms, binding, policy, request)
        finally:
            _COUNTER_PROGRESS_WRITER = previous_progress_writer
        sys.stdout.buffer.write(json.dumps(output, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")
        return 0
    except P2TokenBudgetError as exc:
        reason = exc.reason
        output = {
            "ok": False,
            "error": reason,
            "diagnostic_stage": exc.diagnostic_stage or P2CounterDiagnosticStage.REQUEST_VALIDATION.value,
            "diagnostic_category": exc.diagnostic_category or _counter_diagnostic_category_for_reason(reason).value,
            "sdk_exception_type": exc.sdk_exception_type,
            "sdk_status_code": exc.sdk_status_code,
        }
    except Exception:
        output = {
            "ok": False,
            "error": P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE.value,
            "diagnostic_stage": P2CounterDiagnosticStage.CHILD_PROTOCOL.value,
            "diagnostic_category": P2CounterDiagnosticCategory.PROTOCOL_REJECTED.value,
            "sdk_exception_type": None,
            "sdk_status_code": None,
        }
    sys.stdout.buffer.write(json.dumps(output, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return 1


def _counter_session_child() -> int:
    """Persistent, explicitly prepared SDK child; token counts only, no load API."""
    try:
        bootstrap_line = sys.stdin.buffer.readline(_COUNTER_SESSION_INPUT_LIMIT + 1)
        if len(bootstrap_line) > _COUNTER_SESSION_INPUT_LIMIT or not bootstrap_line.endswith(b"\n"):
            return 2
        bootstrap = json.loads(bootstrap_line[:-1].decode("utf-8", errors="strict"))
        # Reject malformed bootstrap data before importing the optional SDK.
        # This preserves the sanitized EOF/exit-2 contract for invalid starts.
        _validate_session_bootstrap(bootstrap)
        import importlib.metadata
        import lmstudio as lms

        sdk_version = importlib.metadata.version("lmstudio")
        return _serve_counter_session(lms, bootstrap, sdk_version, sys.stdin.buffer, sys.stdout.buffer)
    except Exception:
        # Bootstrap failures are intentionally silent. The parent sees EOF and
        # reports a sanitized unavailable/protocol failure.
        return 2


def _serve_counter_session(
    lms: object,
    bootstrap: object,
    sdk_version: str,
    reader: BinaryIO,
    writer: BinaryIO,
) -> int:
    candidate_id, session_id, binding_fingerprint, binding, policy = _validate_session_bootstrap(bootstrap)
    if sdk_version != "1.5.0":
        return 2
    lms.set_sync_api_timeout(float(policy["sdk_call_timeout_seconds"]))
    with lms.Client(api_host=_sdk_api_host(str(binding["api_host"]))) as client:
        _lookup_bound_model(client, binding)
        _write_session_message(
            writer,
            {
                "protocol": _COUNTER_SESSION_PROTOCOL,
                "operation": "ready",
                "candidate_id": candidate_id,
                "session_id": session_id,
                "binding_fingerprint": binding_fingerprint,
                "ok": True,
                "sdk_version": sdk_version,
            },
        )
        last_request_id = 0
        while True:
            line = reader.readline(_COUNTER_SESSION_INPUT_LIMIT + 1)
            if not line:
                return 0
            if len(line) > _COUNTER_SESSION_INPUT_LIMIT or not line.endswith(b"\n"):
                return 2
            command = json.loads(line[:-1].decode("utf-8", errors="strict"))
            request_id, request_policy, request = _validate_session_measure_command(
                command,
                candidate_id=candidate_id,
                session_id=session_id,
                binding_fingerprint=binding_fingerprint,
                last_request_id=last_request_id,
                model_key=str(binding["model_key"]),
            )
            last_request_id = request_id
            try:
                measurement = _measure_loaded_model_with_client(lms, client, binding, request_policy, request)
                response = {
                    "protocol": _COUNTER_SESSION_PROTOCOL,
                    "operation": "result",
                    "candidate_id": candidate_id,
                    "session_id": session_id,
                    "binding_fingerprint": binding_fingerprint,
                    "request_id": request_id,
                    "ok": True,
                    "measurement": measurement,
                }
            except P2TokenBudgetError as exc:
                response = {
                    "protocol": _COUNTER_SESSION_PROTOCOL,
                    "operation": "result",
                    "candidate_id": candidate_id,
                    "session_id": session_id,
                    "binding_fingerprint": binding_fingerprint,
                    "request_id": request_id,
                    "ok": False,
                    "error": exc.reason,
                }
            except Exception:
                response = {
                    "protocol": _COUNTER_SESSION_PROTOCOL,
                    "operation": "result",
                    "candidate_id": candidate_id,
                    "session_id": session_id,
                    "binding_fingerprint": binding_fingerprint,
                    "request_id": request_id,
                    "ok": False,
                    "error": P2TokenBudgetFailure.COUNTER_UNAVAILABLE,
                }
            _write_session_message(writer, response)


def _validate_session_bootstrap(
    payload: object,
) -> tuple[str, str, str, dict[str, object], dict[str, object]]:
    expected = {
        "protocol", "operation", "candidate_id", "session_id", "request_id",
        "binding_fingerprint", "binding", "policy",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    if (
        payload.get("protocol") != _COUNTER_SESSION_PROTOCOL
        or payload.get("operation") != "prepare"
        or not isinstance(payload.get("request_id"), int)
        or isinstance(payload.get("request_id"), bool)
        or payload.get("request_id") != 0
        or not isinstance(payload.get("candidate_id"), str)
        or not isinstance(payload.get("session_id"), str)
        or not isinstance(payload.get("binding_fingerprint"), str)
        or not isinstance(payload.get("binding"), dict)
        or not isinstance(payload.get("policy"), dict)
    ):
        raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    candidate_id = payload["candidate_id"]
    session_id = payload["session_id"]
    binding_fingerprint = payload["binding_fingerprint"]
    binding = payload["binding"]
    policy = payload["policy"]
    if not candidate_id or len(candidate_id) > 128 or not session_id or len(session_id) > 128:
        raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    if set(binding) != {
        "model_key", "api_host", "lmstudio_model_path", "artifact_sha256",
        "artifact_size_bytes", "actual_context_tokens",
    }:
        raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    if set(policy) != {
        "max_input_tokens", "max_output_tokens", "schema_safety_margin_tokens", "sdk_call_timeout_seconds",
    }:
        raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    _validate_session_policy(policy)
    expected_fingerprint = hashlib.sha256(
        _json_bytes({"candidate_id": candidate_id, "binding": binding}, limit=_COUNTER_SESSION_INPUT_LIMIT)
    ).hexdigest()
    if binding_fingerprint != expected_fingerprint:
        raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    if (
        not isinstance(binding["model_key"], str)
        or not _is_valid_api_host(binding["api_host"])
        or not isinstance(binding["lmstudio_model_path"], str)
        or not binding["lmstudio_model_path"]
        or not isinstance(binding["artifact_sha256"], str)
        or len(binding["artifact_sha256"]) != 64
        or not isinstance(binding["artifact_size_bytes"], int)
        or isinstance(binding["artifact_size_bytes"], bool)
        or not isinstance(binding["actual_context_tokens"], int)
        or isinstance(binding["actual_context_tokens"], bool)
        or binding["actual_context_tokens"] < 1
    ):
        raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    return candidate_id, session_id, binding_fingerprint, binding, policy


def _validate_session_measure_command(
    payload: object,
    *,
    candidate_id: str,
    session_id: str,
    binding_fingerprint: str,
    last_request_id: int,
    model_key: str,
) -> tuple[int, dict[str, object], dict[str, object]]:
    expected = {
        "protocol", "operation", "candidate_id", "session_id", "binding_fingerprint",
        "request_id", "policy", "request",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    request_id = payload.get("request_id")
    policy = payload.get("policy")
    request = payload.get("request")
    if (
        payload.get("protocol") != _COUNTER_SESSION_PROTOCOL
        or payload.get("operation") != "measure"
        or payload.get("candidate_id") != candidate_id
        or payload.get("session_id") != session_id
        or payload.get("binding_fingerprint") != binding_fingerprint
        or not isinstance(request_id, int)
        or isinstance(request_id, bool)
        or request_id != last_request_id + 1
        or not isinstance(policy, dict)
        or not isinstance(request, dict)
        or set(policy) != {
            "max_input_tokens", "max_output_tokens", "schema_safety_margin_tokens", "sdk_call_timeout_seconds",
        }
        or set(request) != {"model_key", "messages", "response_format_json", "max_output_tokens"}
        or request.get("model_key") != model_key
    ):
        raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    _validate_session_policy(policy)
    messages = request.get("messages")
    if (
        not isinstance(messages, list)
        or any(
            not isinstance(message, dict)
            or set(message) != {"role", "content"}
            or not isinstance(message.get("content"), str)
            for message in messages
        )
        or not is_allowed_p2_message_sequence(messages)
    ):
        raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    response_format = request.get("response_format_json")
    if response_format is not None:
        try:
            P2ResponseFormat(response_format)
        except (TypeError, ValueError):
            raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE) from None
    output_tokens = request.get("max_output_tokens")
    if (
        not isinstance(output_tokens, int)
        or isinstance(output_tokens, bool)
        or output_tokens < 1
        or output_tokens > policy["max_output_tokens"]
    ):
        raise P2TokenBudgetError(P2TokenBudgetFailure.CONTEXT_BUDGET_EXCEEDED)
    return request_id, policy, request


def _validate_session_policy(policy: dict[str, object]) -> None:
    for name in ("max_input_tokens", "max_output_tokens", "schema_safety_margin_tokens"):
        value = policy.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
    timeout = policy.get("sdk_call_timeout_seconds")
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or not math.isfinite(float(timeout))
        or not 0.1 <= float(timeout) <= 5.0
    ):
        raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)


def _write_session_message(writer: BinaryIO, payload: dict[str, object]) -> None:
    encoded = _json_bytes(payload, limit=_COUNTER_SESSION_OUTPUT_LIMIT) + b"\n"
    remaining = memoryview(encoded)
    while remaining:
        written = writer.write(remaining)
        if written is None or written <= 0:
            raise OSError("counter session output pipe closed")
        remaining = remaining[written:]
    writer.flush()


def _lookup_bound_model(client: object, binding: dict[str, object]) -> tuple[object, str, int]:
    """Fresh loaded-handle lookup only; deliberately contains no load/JIT path."""
    try:
        handles = client.list_loaded_models("llm")
        matching = [handle for handle in handles if getattr(handle, "identifier", None) == binding["model_key"]]
        if not matching:
            raise P2TokenBudgetError(P2TokenBudgetFailure.MODEL_NOT_LOADED)
        if len(matching) != 1:
            raise P2TokenBudgetError(P2TokenBudgetFailure.MODEL_KEY_MISMATCH)
        model = matching[0]
        info = model.get_info()
        if getattr(info, "model_key", None) != binding["model_key"]:
            raise P2TokenBudgetError(P2TokenBudgetFailure.MODEL_KEY_MISMATCH)
        model_path = getattr(info, "path", None)
        if model_path != binding["lmstudio_model_path"]:
            raise P2TokenBudgetError(P2TokenBudgetFailure.MODEL_PATH_MISMATCH)
        if getattr(info, "size_bytes", None) != binding["artifact_size_bytes"]:
            raise P2TokenBudgetError(P2TokenBudgetFailure.ARTIFACT_BINDING_CHANGED)
        actual_context = model.get_context_length()
        if (
            actual_context != binding["actual_context_tokens"]
            or getattr(info, "context_length", None) != actual_context
        ):
            raise P2TokenBudgetError(P2TokenBudgetFailure.CONTEXT_MISMATCH)
        return model, model_path, actual_context
    except P2TokenBudgetError:
        raise
    except Exception as exc:
        sdk_exception_type, sdk_status_code = _safe_sdk_exception_details(exc)
        raise P2TokenBudgetError(
            P2TokenBudgetFailure.COUNTER_UNAVAILABLE,
            sdk_exception_type=sdk_exception_type,
            sdk_status_code=sdk_status_code,
        ) from None


def _is_valid_api_host(value: object) -> bool:
    return is_valid_local_http_origin(value)


def _sdk_api_host(origin: str) -> str:
    """Convert the provider's HTTP origin to LM Studio SDK authority syntax."""
    try:
        normalized_origin = normalize_local_http_origin(origin)
    except (TypeError, ValueError, UnicodeError):
        raise P2TokenBudgetError(P2TokenBudgetFailure.SERVER_BINDING_MISMATCH)
    return normalized_origin.removeprefix("http://")


def _sdk_chat_from_p2_messages(lms: object, messages: object) -> object:
    """Build the SDK chat from the exact closed P2 text-message sequence.

    P2's repair request intentionally contains two consecutive system messages.
    LM Studio SDK 1.5.0 rejects that shape when it is passed as a plain dict,
    but its public typed-history API preserves it. Keep the wire/request data
    unchanged and fail closed if the public typed API cannot represent it
    exactly.
    """
    if type(messages) not in (list, tuple) or any(
        type(message) is not dict
        or set(message) != {"role", "content"}
        or type(message.get("role")) is not str
        or type(message.get("content")) is not str
        for message in messages
    ):
        raise P2TokenBudgetError(
            P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE,
            diagnostic_stage=P2CounterDiagnosticStage.MESSAGE_POLICY,
            diagnostic_category=P2CounterDiagnosticCategory.POLICY_REJECTED,
        )
    if not is_allowed_p2_message_sequence(messages):
        raise P2TokenBudgetError(
            P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE,
            diagnostic_stage=P2CounterDiagnosticStage.MESSAGE_POLICY,
            diagnostic_category=P2CounterDiagnosticCategory.POLICY_REJECTED,
        )

    text_data_type, system_prompt_type, user_message_type, history_type, chat_type = _counter_stage_call(
        P2CounterDiagnosticStage.TYPED_HISTORY_BUILD,
        lambda: (
            getattr(lms, "TextData"),
            getattr(lms, "SystemPrompt"),
            getattr(lms, "UserMessage"),
            getattr(lms, "ChatHistoryData"),
            getattr(lms, "Chat"),
        ),
    )

    def build_history() -> tuple[object, list[dict[str, object]]]:
        typed_messages = []
        expected_messages = []
        for message in messages:
            role = message["role"]
            text_data = text_data_type(text=message["content"])
            if role == "system":
                typed_message = system_prompt_type(content=[text_data])
            elif role == "user":
                typed_message = user_message_type(content=[text_data])
            else:  # is_allowed_p2_message_sequence should make this unreachable.
                raise P2TokenBudgetError(P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE)
            typed_messages.append(typed_message)
            expected_messages.append({
                "role": role,
                "content": [{"type": "text", "text": message["content"]}],
            })
        return history_type(messages=typed_messages), expected_messages

    history, expected_messages = _counter_stage_call(
        P2CounterDiagnosticStage.TYPED_HISTORY_BUILD,
        build_history,
    )
    # Check the public typed serialization before passing it to Chat. This
    # rejects SDK drift that adds, drops, reorders, or changes message data.
    serialized_history = _counter_stage_call(
        P2CounterDiagnosticStage.TYPED_HISTORY_SERIALIZE,
        history.to_dict,
    )
    if (
        type(serialized_history) is not dict
        or set(serialized_history) != {"messages"}
        or serialized_history.get("messages") != expected_messages
    ):
        raise P2TokenBudgetError(
            P2TokenBudgetFailure.COUNTER_UNAVAILABLE,
            diagnostic_stage=P2CounterDiagnosticStage.TYPED_HISTORY_SERIALIZE,
            diagnostic_category=P2CounterDiagnosticCategory.PROTOCOL_REJECTED,
        )
    return _counter_stage_call(
        P2CounterDiagnosticStage.CHAT_FROM_HISTORY,
        lambda: chat_type.from_history(history),
    )


def _measure_loaded_model(
    lms: object,
    binding: dict[str, object],
    policy: dict[str, object],
    request: dict[str, object],
) -> dict[str, object]:
    """Count through an explicit API host and two fresh loaded-handle lookups."""

    def use_client() -> dict[str, object]:
        with lms.Client(api_host=_sdk_api_host(str(binding["api_host"]))) as client:
            return _measure_loaded_model_with_client(
                lms,
                client,
                binding,
                policy,
                request,
                set_api_timeout=False,
            )

    _counter_stage_call(
        P2CounterDiagnosticStage.TIMEOUT_SET,
        lambda: lms.set_sync_api_timeout(float(policy["sdk_call_timeout_seconds"])),
    )
    return _counter_stage_call(P2CounterDiagnosticStage.SDK_CLIENT_OPEN, use_client)


def _measure_loaded_model_with_client(
    lms: object,
    client: object,
    binding: dict[str, object],
    policy: dict[str, object],
    request: dict[str, object],
    *,
    set_api_timeout: bool = True,
) -> dict[str, object]:
    """Count using a prepared client, retaining fresh binding checks on both sides."""
    if set_api_timeout:
        _counter_stage_call(
            P2CounterDiagnosticStage.TIMEOUT_SET,
            lambda: lms.set_sync_api_timeout(float(policy["sdk_call_timeout_seconds"])),
        )
    model, model_path, actual_context = _counter_stage_call(
        P2CounterDiagnosticStage.LOOKUP_PRE,
        lambda: _lookup_bound_model(client, binding),
    )
    chat = _sdk_chat_from_p2_messages(lms, request["messages"])
    formatted_prompt = _counter_stage_call(
        P2CounterDiagnosticStage.APPLY_PROMPT_TEMPLATE,
        lambda: model.apply_prompt_template(chat),
    )
    prompt_tokens = _counter_stage_call(
        P2CounterDiagnosticStage.COUNT_PROMPT_TOKENS,
        lambda: model.count_tokens(formatted_prompt),
    )
    response_format = request.get("response_format_json")
    response_format_tokens = (
        _counter_stage_call(
            P2CounterDiagnosticStage.COUNT_RESPONSE_FORMAT_TOKENS,
            lambda: model.count_tokens(response_format),
        )
        if response_format
        else 0
    )
    after_model, after_path, after_context = _counter_stage_call(
        P2CounterDiagnosticStage.LOOKUP_POST,
        lambda: _lookup_bound_model(client, binding),
    )

    def validate_identity() -> None:
        if after_path != model_path or after_context != actual_context:
            raise P2TokenBudgetError(P2TokenBudgetFailure.ARTIFACT_BINDING_CHANGED)
        if getattr(after_model, "identifier", None) != getattr(model, "identifier", None):
            raise P2TokenBudgetError(P2TokenBudgetFailure.MODEL_KEY_MISMATCH)

    _counter_stage_call(P2CounterDiagnosticStage.IDENTITY_CHECK, validate_identity)
    return {
        "ok": True,
        "model_key": binding["model_key"],
        "api_host": binding["api_host"],
        "model_path": model_path,
        "artifact_sha256": binding["artifact_sha256"],
        "actual_context_tokens": actual_context,
        "prompt_tokens": prompt_tokens,
        "response_format_tokens": response_format_tokens,
    }


if __name__ == "__main__" and len(sys.argv) == 2 and sys.argv[1] == "--counter-child":
    raise SystemExit(_counter_child())
if __name__ == "__main__" and len(sys.argv) == 2 and sys.argv[1] == "--counter-session-child":
    raise SystemExit(_counter_session_child())
