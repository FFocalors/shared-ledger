from __future__ import annotations

from io import BytesIO
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from threading import Event, Thread, enumerate as enumerate_threads
from time import monotonic, sleep
from typing import Any

import pytest

from app.p2_token_budget import (
    LMStudioSDKTokenBudgetChecker,
    P2ChatMessage,
    P2ModelArtifactBinding,
    P2ResponseFormat,
    P2TokenBudgetError,
    P2TokenBudgetFailure,
    P2TokenBudgetPolicy,
    P2TokenBudgetRequest,
    _COUNTER_SESSION_PROTOCOL,
    _OwnedSDKSession,
    _json_bytes,
    _serve_counter_session,
    _validate_session_bootstrap,
    _validate_session_measure_command,
)


MODEL_KEY = "session-fixture-model"
MODEL_PATH = "fixture/session-model.gguf"
API_HOST = "http://127.0.0.1:1234"
ARTIFACT_HASH = hashlib.sha256(b"session-fixture-model-bytes").hexdigest()


class _TypedHistorySurface:
    """LM Studio SDK typed-history classes the token counter builds against.

    The counter constructs a typed ``ChatHistoryData``, checks its exact public
    serialization, and only then calls ``Chat.from_history``. A fake SDK that
    omits these classes fails that stage, and the session's generic error arm
    reports it as ``counter_unavailable`` rather than the real reason.
    """

    class TextData:
        def __init__(self, *, text: str) -> None:
            self.text = text

        def as_dict(self) -> dict[str, str]:
            return {"type": "text", "text": self.text}

    class _TypedMessage:
        role = ""

        def __init__(self, *, content: list["_TypedHistorySurface.TextData"]) -> None:
            self.content = content

        def as_dict(self) -> dict[str, object]:
            return {"role": self.role, "content": [item.as_dict() for item in self.content]}

    class SystemPrompt(_TypedMessage):
        role = "system"

    class UserMessage(_TypedMessage):
        role = "user"

    class ChatHistoryData:
        def __init__(self, *, messages: list["_TypedHistorySurface._TypedMessage"]) -> None:
            self.messages = messages

        def to_dict(self) -> dict[str, object]:
            return {"messages": [message.as_dict() for message in self.messages]}



def _binding_payload() -> dict[str, object]:
    return {
        "model_key": MODEL_KEY,
        "api_host": API_HOST,
        "lmstudio_model_path": MODEL_PATH,
        "artifact_sha256": ARTIFACT_HASH,
        "artifact_size_bytes": len(b"session-fixture-model-bytes"),
        "actual_context_tokens": 8192,
    }


def _policy_payload(*, timeout: float = 5.0) -> dict[str, object]:
    return {
        "max_input_tokens": 6144,
        "max_output_tokens": 768,
        "schema_safety_margin_tokens": 512,
        "sdk_call_timeout_seconds": timeout,
    }


def _request_body(*, prompt: str = "synthetic request") -> dict[str, object]:
    return {
        "model_key": MODEL_KEY,
        "messages": [
            {"role": "system", "content": "synthetic system"},
            {"role": "user", "content": prompt},
        ],
        "response_format_json": '{"type":"json_schema","json_schema":{"name":"fake","strict":true,"schema":{"type":"object"}}}',
        "max_output_tokens": 768,
    }


def _bootstrap() -> dict[str, object]:
    binding = _binding_payload()
    candidate_id = "a" * 64
    session_id = "b" * 32
    fingerprint = hashlib.sha256(
        _json_bytes({"candidate_id": candidate_id, "binding": binding}, limit=1_000_000)
    ).hexdigest()
    return {
        "protocol": _COUNTER_SESSION_PROTOCOL,
        "operation": "prepare",
        "candidate_id": candidate_id,
        "session_id": session_id,
        "request_id": 0,
        "binding_fingerprint": fingerprint,
        "binding": binding,
        "policy": _policy_payload(),
    }


def _command(bootstrap: dict[str, object], *, request_id: object = 1) -> dict[str, object]:
    return {
        "protocol": _COUNTER_SESSION_PROTOCOL,
        "operation": "measure",
        "candidate_id": bootstrap["candidate_id"],
        "session_id": bootstrap["session_id"],
        "binding_fingerprint": bootstrap["binding_fingerprint"],
        "request_id": request_id,
        "policy": _policy_payload(),
        "request": _request_body(),
    }


def _checker(artifact: Path, *, total_timeout: float = 5.0) -> LMStudioSDKTokenBudgetChecker:
    payload = b"session-fixture-model-bytes"
    artifact.write_bytes(payload)
    return LMStudioSDKTokenBudgetChecker(
        P2ModelArtifactBinding(
            model_key=MODEL_KEY,
            artifact_path=artifact,
            lmstudio_model_path=MODEL_PATH,
            lmstudio_api_host=API_HOST,
            artifact_sha256=hashlib.sha256(payload).hexdigest(),
            artifact_size_bytes=len(payload),
        ),
        P2TokenBudgetPolicy(total_measurement_timeout_seconds=total_timeout),
        python_executable=Path(sys.executable).resolve(),
    )


def _request(*, user_content: str = "synthetic request") -> P2TokenBudgetRequest:
    return P2TokenBudgetRequest(
        model_key=MODEL_KEY,
        api_host=API_HOST,
        messages=(P2ChatMessage("system", "synthetic system"), P2ChatMessage("user", user_content)),
        response_format=P2ResponseFormat(
            '{"type":"json_schema","json_schema":{"name":"fake","strict":true,"schema":{"type":"object"}}}'
        ),
        max_output_tokens=768,
    )


def _install_fake_helper(checker: LMStudioSDKTokenBudgetChecker, tmp_path: Path, mode: str = "success") -> Path:
    helper = tmp_path / f"fake_session_{mode}.py"
    script = r'''
import json, sys, time
mode = MODE
marker = MARKER
def emit(value):
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()
bootstrap = json.loads(sys.stdin.buffer.readline(1000001))
if mode == "late_ready":
    time.sleep(1.0)
emit({"protocol": bootstrap["protocol"], "operation": "ready", "candidate_id": bootstrap["candidate_id"], "session_id": BOOT_SESSION, "binding_fingerprint": bootstrap["binding_fingerprint"], "ok": True, "sdk_version": "1.5.0"})
while True:
    if mode == "stall_measure":
        time.sleep(10)
    line = sys.stdin.buffer.readline(1000001)
    if not line:
        break
    command = json.loads(line)
    if marker:
        open(marker, "w", encoding="ascii").write("started")
    if mode == "late_result":
        time.sleep(10)
    if mode == "helper_exit":
        sys.exit(7)
    request_id = command["request_id"]
    if mode == "bool_request_id":
        request_id = True
    measurement = {"ok": True, "model_key": bootstrap["binding"]["model_key"], "api_host": bootstrap["binding"]["api_host"], "model_path": bootstrap["binding"]["lmstudio_model_path"], "artifact_sha256": bootstrap["binding"]["artifact_sha256"], "actual_context_tokens": bootstrap["binding"]["actual_context_tokens"], "prompt_tokens": 20, "response_format_tokens": 10}
    response = {"protocol": bootstrap["protocol"], "operation": "result", "candidate_id": bootstrap["candidate_id"], "session_id": bootstrap["session_id"], "binding_fingerprint": bootstrap["binding_fingerprint"], "request_id": request_id, "ok": True, "measurement": measurement}
    if mode == "oversized_result":
        response["padding"] = "x" * 5000
    emit(response)
'''
    script = script.replace("MODE", repr(mode)).replace("MARKER", repr(str(tmp_path / "measure-started.flag") if mode in {"stall_measure", "success", "bool_request_id", "late_result", "helper_exit", "oversized_result"} else ""))
    # Late-ready mode also needs the session echo to remain exact. Other modes
    # use the bootstrap session ID, so only the deliberate bad-handshake test
    # overrides this placeholder by emitting a stale value in its own script.
    session_expression = '"stale-session-id"' if mode == "bad_ready" else 'bootstrap["session_id"]'
    script = script.replace("BOOT_SESSION", session_expression)
    helper.write_text(script, encoding="utf-8")
    checker._session_helper_args = lambda: [str(Path(sys.executable).resolve()), "-B", str(helper)]  # type: ignore[method-assign]
    return helper


def test_fake_sdk_session_keeps_one_client_and_freshly_binds_before_and_after_each_count() -> None:
    bootstrap = _bootstrap()
    first = _command(bootstrap, request_id=1)
    second = _command(bootstrap, request_id=2)
    reader = BytesIO(
        _json_bytes(first, limit=1_000_000) + b"\n"
        + _json_bytes(second, limit=1_000_000) + b"\n"
    )
    writer = BytesIO()
    calls: list[str] = []

    class Model:
        identifier = MODEL_KEY

        def get_info(self) -> object:
            return type("Info", (), {
                "model_key": MODEL_KEY,
                "path": MODEL_PATH,
                "size_bytes": len(b"session-fixture-model-bytes"),
                "context_length": 8192,
            })()

        def get_context_length(self) -> int:
            return 8192

        def apply_prompt_template(self, chat: object) -> str:
            calls.append("template")
            return "fake-template"

        def count_tokens(self, prompt: str) -> int:
            calls.append("count")
            return 10 if prompt == "fake-template" else 20

    model = Model()

    class FakeClient:
        def __init__(self, *, api_host: str) -> None:
            assert api_host == "127.0.0.1:1234"
            calls.append("client")

        def __enter__(self) -> FakeClient:
            calls.append("enter")
            return self

        def __exit__(self, *_args: object) -> None:
            calls.append("exit")

        def list_loaded_models(self, namespace: str) -> list[object]:
            assert namespace == "llm"
            calls.append("list")
            return [model]

    class FakeLMStudio(_TypedHistorySurface):
        Client = FakeClient
        Chat = type("Chat", (), {"from_history": staticmethod(lambda _history: object())})

        @staticmethod
        def set_sync_api_timeout(value: float) -> None:
            assert 0 < value <= 5.0

    assert _serve_counter_session(FakeLMStudio, bootstrap, "1.5.0", reader, writer) == 0
    responses = [json.loads(line) for line in writer.getvalue().splitlines()]
    assert [item["operation"] for item in responses] == ["ready", "result", "result"]
    assert [item["request_id"] for item in responses[1:]] == [1, 2]
    assert all(item["measurement"]["prompt_tokens"] == 10 for item in responses[1:])
    assert calls.count("client") == 1
    assert calls.count("list") == 5  # one prepare lookup and two for each count
    assert calls.count("template") == 2
    assert calls.count("count") == 4  # prompt plus schema on each measurement
    assert calls.count("exit") == 1
    assert not hasattr(FakeLMStudio, "llm")
    assert not hasattr(FakeLMStudio, "load")


def test_session_ids_are_checker_bound_and_failed_prepare_never_falls_back_to_cold_helper(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "artifact.gguf"
    checker = _checker(artifact)
    other = _checker(tmp_path / "other.gguf")
    assert checker.candidate_id != other.candidate_id
    with pytest.raises(AttributeError):
        checker.candidate_id = "changed"  # type: ignore[misc]

    _install_fake_helper(checker, tmp_path, "bad_ready")
    # Change only the test helper's ready session ID, producing a stale reply.
    helper = tmp_path / "fake_session_bad_ready.py"
    cold_calls: list[str] = []
    checker._session_helper_args = lambda: [str(Path(sys.executable).resolve()), "-B", str(helper)]  # type: ignore[method-assign]
    with pytest.raises(P2TokenBudgetError) as prepare_error:
        checker.prepare_sdk_session(timeout_seconds=2.0)
    assert prepare_error.value.reason == P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE

    def cold_counter(*_args: Any, **_kwargs: Any) -> tuple[int, bytes]:
        cold_calls.append("cold")
        return 1, b"{}"

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("app.p2_token_budget._run_bounded_helper", cold_counter)
    try:
        with pytest.raises(P2TokenBudgetError) as measure_error:
            checker.measure(_request())
    finally:
        monkeypatch.undo()
    assert measure_error.value.reason == P2TokenBudgetFailure.SESSION_NOT_PREPARED
    assert cold_calls == []
    checker.close()


def test_close_during_late_ready_invalidates_and_kills_only_owned_helper(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.gguf"
    checker = _checker(artifact)
    _install_fake_helper(checker, tmp_path, "late_ready")
    outcomes: list[object] = []

    def prepare() -> None:
        try:
            outcomes.append(checker.prepare_sdk_session(timeout_seconds=2.0))
        except P2TokenBudgetError as exc:
            outcomes.append(exc.reason)

    thread = Thread(target=prepare, daemon=True)
    thread.start()
    started = monotonic()
    session = None
    while monotonic() - started < 1.0:
        session = checker._session
        if session is not None:
            break
        sleep(0.01)
    assert session is not None
    checker.close()
    checker.close()
    thread.join(timeout=1.5)
    assert not thread.is_alive()
    assert outcomes and outcomes[0] in {
        P2TokenBudgetFailure.SESSION_CLOSED,
        P2TokenBudgetFailure.COUNTER_UNAVAILABLE,
        P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE,
    }
    assert session.process.poll() is not None
    with pytest.raises(P2TokenBudgetError) as closed_error:
        checker.measure(_request())
    assert closed_error.value.reason == P2TokenBudgetFailure.SESSION_CLOSED


def test_session_rejects_bool_request_id_and_closes_session(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.gguf"
    checker = _checker(artifact)
    _install_fake_helper(checker, tmp_path, "bool_request_id")
    checker.prepare_sdk_session(timeout_seconds=2.0)
    owned = checker._session
    assert owned is not None
    with pytest.raises(P2TokenBudgetError) as raised:
        checker.measure(_request())
    assert raised.value.reason == P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE
    assert checker._session is None
    assert owned.process.poll() is not None

    bootstrap = _bootstrap()
    with pytest.raises(P2TokenBudgetError) as child_validation:
        _validate_session_measure_command(
            _command(bootstrap, request_id=True),
            candidate_id=str(bootstrap["candidate_id"]),
            session_id=str(bootstrap["session_id"]),
            binding_fingerprint=str(bootstrap["binding_fingerprint"]),
            last_request_id=0,
            model_key=MODEL_KEY,
        )
    assert child_validation.value.reason == P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE
    checker.close()


@pytest.mark.parametrize("invalid_id", [False, True])
def test_bootstrap_request_id_requires_an_integer_zero_not_a_boolean(invalid_id: bool) -> None:
    bootstrap = _bootstrap()
    bootstrap["request_id"] = invalid_id
    with pytest.raises(P2TokenBudgetError) as raised:
        _validate_session_bootstrap(bootstrap)
    assert raised.value.reason == P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE


def test_close_during_late_result_kills_child_and_joins_pipe_threads(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.gguf"
    checker = _checker(artifact, total_timeout=3.0)
    _install_fake_helper(checker, tmp_path, "late_result")
    checker.prepare_sdk_session(timeout_seconds=2.0)
    owned = checker._session
    assert owned is not None
    marker = tmp_path / "measure-started.flag"
    outcomes: list[object] = []

    def measure() -> None:
        try:
            outcomes.append(checker.measure(_request()))
        except P2TokenBudgetError as exc:
            outcomes.append(exc.reason)

    thread = Thread(target=measure, daemon=True)
    thread.start()
    started = monotonic()
    while monotonic() - started < 1.0 and not marker.exists():
        sleep(0.005)
    assert marker.exists()
    checker.close()
    thread.join(timeout=1.5)
    assert not thread.is_alive()
    assert outcomes and outcomes[0] in {
        P2TokenBudgetFailure.SESSION_CLOSED,
        P2TokenBudgetFailure.COUNTER_UNAVAILABLE,
        P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE,
    }
    assert not hasattr(owned.process, "_p2_pipe_threads")
    assert owned.process.poll() is not None
    assert not [
        item for item in enumerate_threads()
        if item.name in {"p2-token-session-input", "p2-token-session-output"} and item.is_alive()
    ]


def test_measure_timeout_gets_one_cleanup_grace_and_reaps_pipe_threads(tmp_path: Path) -> None:
    artifact = tmp_path / "stall.gguf"
    checker = _checker(artifact, total_timeout=0.15)
    _install_fake_helper(checker, tmp_path, "stall_measure")
    checker.prepare_sdk_session(timeout_seconds=2.0)
    owned = checker._session
    assert owned is not None
    started = monotonic()
    with pytest.raises(P2TokenBudgetError) as raised:
        checker.measure(_request())
    elapsed = monotonic() - started
    assert raised.value.reason == P2TokenBudgetFailure.COUNTER_TIMEOUT
    assert elapsed <= 1.3  # 150ms call deadline plus one shared cleanup grace
    assert owned.process.poll() is not None
    assert not hasattr(owned.process, "_p2_pipe_threads")
    assert not [
        item for item in enumerate_threads()
        if item.name in {"p2-token-session-input", "p2-token-session-output"} and item.is_alive()
    ]


def test_delayed_reap_cleanup_is_one_shot_with_one_absolute_grace(tmp_path: Path) -> None:
    class DelayedProcess:
        def __init__(self) -> None:
            self.returncode: int | None = None
            self.stdin = None
            self.stdout = None
            self.kill_calls = 0
            self.wait_calls = 0

        def poll(self) -> int | None:
            return self.returncode

        def kill(self) -> None:
            self.kill_calls += 1

        def wait(self, timeout: float | None = None) -> int:
            self.wait_calls += 1
            sleep(min(0.08, timeout if timeout is not None else 0.08))
            self.returncode = -9
            return self.returncode

    process = DelayedProcess()
    checker = _checker(tmp_path / "artifact.gguf")
    session = _OwnedSDKSession(
        process=process,  # type: ignore[arg-type]
        candidate_id="candidate",
        session_id="session",
        binding_fingerprint="binding",
        epoch=1,
    )
    started = monotonic()
    first = checker._terminate_session(session)
    elapsed_first = monotonic() - started
    original_deadline = session.cleanup_deadline
    second = checker._terminate_session(session)
    elapsed_second = monotonic() - started
    assert first is True and second is True
    assert 0.06 <= elapsed_first < 0.5
    assert elapsed_second - elapsed_first < 0.02
    assert process.kill_calls == 1
    assert process.wait_calls == 1
    assert session.cleanup_deadline == original_deadline


def test_incomplete_cleanup_blocks_a_new_sdk_session(tmp_path: Path) -> None:
    class UnreapableProcess:
        stdin = None
        stdout = None

        def poll(self) -> None:
            return None

        def kill(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            raise subprocess.TimeoutExpired("fake-owned-child", timeout)

    checker = _checker(tmp_path / "artifact.gguf")
    session = _OwnedSDKSession(
        process=UnreapableProcess(),  # type: ignore[arg-type]
        candidate_id=checker.candidate_id,
        session_id="session",
        binding_fingerprint="binding",
        epoch=1,
    )
    assert checker._terminate_session(session) is False
    assert checker._session_cleanup_failed is True
    spawn_calls: list[str] = []
    checker._session_helper_args = lambda: spawn_calls.append("spawn") or []  # type: ignore[method-assign]
    with pytest.raises(P2TokenBudgetError) as raised:
        checker.prepare_sdk_session(timeout_seconds=1.0)
    assert raised.value.reason == P2TokenBudgetFailure.COUNTER_UNAVAILABLE
    assert spawn_calls == []


@pytest.mark.parametrize("mode", ["helper_exit", "oversized_result"])
def test_bad_or_oversized_session_result_cleans_child_and_pipe_threads(
    tmp_path: Path,
    mode: str,
) -> None:
    artifact = tmp_path / f"{mode}.gguf"
    checker = _checker(artifact)
    _install_fake_helper(checker, tmp_path, mode)
    checker.prepare_sdk_session(timeout_seconds=2.0)
    owned = checker._session
    assert owned is not None
    with pytest.raises(P2TokenBudgetError) as raised:
        checker.measure(_request())
    assert raised.value.reason in {
        P2TokenBudgetFailure.COUNTER_UNAVAILABLE,
        P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE,
    }
    assert checker._session is None
    assert owned.process.poll() is not None
    assert not hasattr(owned.process, "_p2_pipe_threads")
    assert not [
        item for item in enumerate_threads()
        if item.name in {"p2-token-session-input", "p2-token-session-output"} and item.is_alive()
    ]


@pytest.mark.parametrize(
    ("failure_field", "failure_value", "expected_error", "count_expected"),
    [
        ("path", "other/session.gguf", P2TokenBudgetFailure.MODEL_PATH_MISMATCH, False),
        ("context", 4096, P2TokenBudgetFailure.CONTEXT_MISMATCH, False),
        ("path_after_count", "other/session.gguf", P2TokenBudgetFailure.MODEL_PATH_MISMATCH, True),
        ("context_after_count", 4096, P2TokenBudgetFailure.CONTEXT_MISMATCH, True),
    ],
)
def test_fake_sdk_rejects_path_or_context_change_before_admitting_counts(
    failure_field: str,
    failure_value: object,
    expected_error: str,
    count_expected: bool,
) -> None:
    bootstrap = _bootstrap()
    command = _command(bootstrap, request_id=1)
    reader = BytesIO(_json_bytes(command, limit=1_000_000) + b"\n")
    writer = BytesIO()
    calls: list[str] = []

    class Model:
        identifier = MODEL_KEY

        def __init__(self) -> None:
            self.lookup_count = 0
            self.path = MODEL_PATH
            self.context = 8192

        def get_info(self) -> object:
            self.lookup_count += 1
            if failure_field in {"path", "context"} and self.lookup_count == 2:
                self._apply_mismatch()
            if failure_field.endswith("_after_count") and "count" in calls:
                self._apply_mismatch()
            return type("Info", (), {
                "model_key": MODEL_KEY,
                "path": self.path,
                "size_bytes": len(b"session-fixture-model-bytes"),
                "context_length": self.context,
            })()

        def _apply_mismatch(self) -> None:
            if failure_field.startswith("path"):
                self.path = str(failure_value)
            else:
                self.context = int(failure_value)

        def get_context_length(self) -> int:
            return self.context

        def apply_prompt_template(self, _chat: object) -> str:
            return "fake-template"

        def count_tokens(self, _value: str) -> int:
            calls.append("count")
            return 10

    model = Model()

    class FakeClient:
        def __init__(self, *, api_host: str) -> None:
            assert api_host == "127.0.0.1:1234"

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def list_loaded_models(self, namespace: str) -> list[object]:
            assert namespace == "llm"
            return [model]

    class FakeLMStudio(_TypedHistorySurface):
        Client = FakeClient
        Chat = type("Chat", (), {"from_history": staticmethod(lambda _history: object())})

        @staticmethod
        def set_sync_api_timeout(_value: float) -> None:
            return None

    assert _serve_counter_session(FakeLMStudio, bootstrap, "1.5.0", reader, writer) == 0
    messages = [json.loads(line) for line in writer.getvalue().splitlines()]
    result = messages[-1]
    assert result["operation"] == "result"
    assert result["ok"] is False
    assert result["error"] == expected_error
    assert "measurement" not in result
    assert ("count" in calls) is count_expected


def test_prepared_artifact_change_fails_closed_without_cold_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "artifact.gguf"
    checker = _checker(artifact)
    _install_fake_helper(checker, tmp_path, "success")
    checker.prepare_sdk_session(timeout_seconds=2.0)
    owned = checker._session
    assert owned is not None
    artifact.write_bytes(b"X" * len(b"session-fixture-model-bytes"))
    cold_calls: list[str] = []

    def cold_counter(*_args: Any, **_kwargs: Any) -> tuple[int, bytes]:
        cold_calls.append("cold")
        return 0, b"{}"

    monkeypatch.setattr("app.p2_token_budget._run_bounded_helper", cold_counter)
    with pytest.raises(P2TokenBudgetError) as raised:
        checker.measure(_request())
    assert raised.value.reason == P2TokenBudgetFailure.ARTIFACT_BINDING_CHANGED
    assert cold_calls == []
    assert checker._session is None
    assert owned.process.poll() is not None
    checker.close()
    assert owned.process.poll() is not None


def test_checker_state_lock_waits_are_bounded_for_measure_and_close(tmp_path: Path) -> None:
    checker = _checker(tmp_path / "artifact.gguf", total_timeout=0.12)
    checker._state_lock.acquire()
    outcome: list[str] = []

    def call_measure() -> None:
        try:
            checker.measure(_request())
        except P2TokenBudgetError as exc:
            outcome.append(exc.reason)

    thread = Thread(target=call_measure, daemon=True)
    started = monotonic()
    thread.start()
    thread.join(timeout=0.5)
    measure_elapsed = monotonic() - started
    assert not thread.is_alive()
    assert outcome == [P2TokenBudgetFailure.COUNTER_TIMEOUT]
    assert measure_elapsed < 0.4

    close_started = monotonic()
    checker.close()
    assert monotonic() - close_started < 0.2
    checker._state_lock.release()


def test_singleflight_wait_uses_the_five_second_measurement_deadline(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.gguf"
    checker = _checker(artifact, total_timeout=0.15)
    entered = Event()
    checker._measurement_lock.acquire()
    outcome: list[str] = []

    def call_measure() -> None:
        entered.set()
        try:
            checker.measure(_request())
        except P2TokenBudgetError as exc:
            outcome.append(exc.reason)

    thread = Thread(target=call_measure, daemon=True)
    thread.start()
    assert entered.wait(0.5)
    sleep(0.2)
    checker._measurement_lock.release()
    thread.join(timeout=1.0)
    assert not thread.is_alive()
    assert outcome == [P2TokenBudgetFailure.COUNTER_TIMEOUT]
    checker.close()


def test_prepare_rechecks_failed_cleanup_after_waiting_for_measurement_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = _checker(tmp_path / "artifact.gguf")
    gate = checker._measurement_lock
    gate.acquire()
    waiting = Event()
    outcomes: list[object] = []
    spawn_calls: list[object] = []

    class ObservedGate:
        def acquire(self, *, timeout: float) -> bool:
            waiting.set()
            return gate.acquire(timeout=timeout)

        def release(self) -> None:
            gate.release()

    class UnreapableProcess:
        stdin = None
        stdout = None

        def poll(self) -> None:
            return None

        def kill(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            raise subprocess.TimeoutExpired("fake-owned-child", timeout)

    def forbidden_spawn(*args: object, **kwargs: object) -> None:
        spawn_calls.append((args, kwargs))
        raise AssertionError("failed cleanup must prevent another helper")

    checker._measurement_lock = ObservedGate()  # type: ignore[assignment]
    monkeypatch.setattr(
        checker, "prepare_artifact_binding", lambda **_kwargs: (ARTIFACT_HASH, 0),
    )
    monkeypatch.setattr("app.p2_token_budget.subprocess.Popen", forbidden_spawn)

    def prepare() -> None:
        try:
            outcomes.append(checker.prepare_sdk_session(timeout_seconds=5.0))
        except P2TokenBudgetError as exc:
            outcomes.append(exc.reason)
        except Exception as exc:
            outcomes.append(exc)

    thread = Thread(target=prepare, daemon=True)
    thread.start()
    try:
        # This signal occurs after the first cleanup check and artifact phase.
        assert waiting.wait(2.0)
        session = _OwnedSDKSession(
            process=UnreapableProcess(),  # type: ignore[arg-type]
            candidate_id=checker.candidate_id,
            session_id="failed-cleanup-during-gate-wait",
            binding_fingerprint="binding",
            epoch=1,
        )
        assert checker._terminate_session(session) is False
        assert checker._session_cleanup_failed is True
    finally:
        gate.release()
        thread.join(timeout=5.5)
        checker.close()

    assert not thread.is_alive()
    assert outcomes == [P2TokenBudgetFailure.COUNTER_UNAVAILABLE]
    assert spawn_calls == []
