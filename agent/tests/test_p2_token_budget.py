from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic
from typing import Any

import pytest

from app.p2_format_repair import P2_REPAIR_INSTRUCTIONS
from app.p2_token_budget import (
    LMStudioSDKTokenBudgetChecker,
    P2CounterDiagnosticCategory,
    P2CounterDiagnosticStage,
    P2ChatMessage,
    P2ModelArtifactBinding,
    P2ResponseFormat,
    P2TokenBudgetError,
    P2TokenBudgetFailure,
    P2TokenBudgetPolicy,
    P2TokenBudgetRequest,
    _measure_loaded_model,
    _measure_loaded_model_with_client,
    _run_bounded_helper,
    _safe_child_error,
    _sdk_chat_from_p2_messages,
)


MODEL_KEY = "fixture-loaded-model"
MODEL_PATH = "fixture/model.gguf"


def _fake_typed_lms_history(calls: list[object]) -> object:
    class FakeTextData:
        def __init__(self, *, text: str) -> None:
            self.text = text

        def to_dict(self) -> dict[str, str]:
            return {"type": "text", "text": self.text}

    class FakeSystemPrompt:
        def __init__(self, *, content: list[FakeTextData]) -> None:
            self.content = content

        def to_dict(self) -> dict[str, object]:
            return {"role": "system", "content": [part.to_dict() for part in self.content]}

    class FakeUserMessage:
        def __init__(self, *, content: list[FakeTextData]) -> None:
            self.content = content

        def to_dict(self) -> dict[str, object]:
            return {"role": "user", "content": [part.to_dict() for part in self.content]}

    class FakeChatHistoryData:
        def __init__(self, *, messages: list[object]) -> None:
            self.messages = messages

        def to_dict(self) -> dict[str, object]:
            return {"messages": [message.to_dict() for message in self.messages]}

    class FakeChat:
        def __init__(self, history: FakeChatHistoryData) -> None:
            self.history = history

        def to_dict(self) -> dict[str, object]:
            return self.history.to_dict()

        @classmethod
        def from_history(cls, history: FakeChatHistoryData) -> FakeChat:
            calls.append(("chat-from-history", history.to_dict()))
            return cls(history)

    return type("FakeTypedHistorySDK", (), {
        "TextData": FakeTextData,
        "SystemPrompt": FakeSystemPrompt,
        "UserMessage": FakeUserMessage,
        "ChatHistoryData": FakeChatHistoryData,
        "Chat": FakeChat,
    })()


def _run_direct_counter_entry(
    tmp_path: Path,
    *,
    flag: str,
    payload: bytes,
) -> tuple[subprocess.CompletedProcess[bytes], Path]:
    source = Path(__file__).resolve().parents[1] / "app" / "p2_token_budget.py"
    marker = tmp_path / "lmstudio-import-attempted.txt"
    blocker = tmp_path / "lmstudio.py"
    blocker.write_text(
        "from pathlib import Path\n"
        "import os\n"
        "Path(os.environ['P2_SDK_IMPORT_MARKER']).write_text('blocked', encoding='utf-8')\n"
        "raise RuntimeError('CPU test forbids SDK import')\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(tmp_path)
    env["P2_SDK_IMPORT_MARKER"] = str(marker)
    result = subprocess.run(
        [sys.executable, "-B", str(source), flag],
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=str(Path(__file__).resolve().parents[2]),
        timeout=5.0,
        check=False,
    )
    return result, marker


def test_direct_counter_child_entry_rejects_invalid_payload_before_sdk_import(tmp_path: Path) -> None:
    result, marker = _run_direct_counter_entry(
        tmp_path,
        flag="--counter-child",
        payload=b"{}",
    )

    assert result.returncode == 1
    assert json.loads(result.stdout) == {
        "ok": False,
        "error": "invalid_counter_response",
        "diagnostic_stage": "request_validation",
        "diagnostic_category": "protocol_rejected",
        "sdk_exception_type": None,
        "sdk_status_code": None,
    }
    assert result.stderr == b""
    assert not marker.exists()


def test_sdk_operation_failure_keeps_only_closed_stage_and_safe_exception_type() -> None:
    calls: list[object] = []
    typed_api = _fake_typed_lms_history(calls)

    class Model:
        identifier = MODEL_KEY

        def get_info(self) -> object:
            return type("Info", (), {
                "model_key": MODEL_KEY,
                "path": MODEL_PATH,
                "size_bytes": 16,
                "context_length": 8192,
            })()

        def get_context_length(self) -> int:
            return 8192

        def apply_prompt_template(self, _chat: object) -> str:
            class LMStudioServerError(Exception):
                status_code = 400

            raise LMStudioServerError("prompt-secret-canary")

        def count_tokens(self, _text: object) -> int:
            raise AssertionError("count_must_not_run_after_template_failure")

    model = Model()

    class Client:
        def list_loaded_models(self, namespace: str) -> list[object]:
            assert namespace == "llm"
            return [model]

    fake_lms = type("FakeLMStudio", (), {
        "TextData": typed_api.TextData,
        "SystemPrompt": typed_api.SystemPrompt,
        "UserMessage": typed_api.UserMessage,
        "ChatHistoryData": typed_api.ChatHistoryData,
        "Chat": typed_api.Chat,
    })()

    with pytest.raises(P2TokenBudgetError) as raised:
        _measure_loaded_model_with_client(
            fake_lms,
            Client(),
            {
                "model_key": MODEL_KEY,
                "api_host": "http://127.0.0.1:1234",
                "lmstudio_model_path": MODEL_PATH,
                "artifact_sha256": "a" * 64,
                "artifact_size_bytes": 16,
                "actual_context_tokens": 8192,
            },
            {"sdk_call_timeout_seconds": 5.0},
            {
                "messages": [{"role": "system", "content": "safe system"}, {"role": "user", "content": "safe user"}],
                "response_format_json": None,
            },
            set_api_timeout=False,
        )

    assert raised.value.reason == P2TokenBudgetFailure.COUNTER_UNAVAILABLE
    assert raised.value.diagnostic_stage == P2CounterDiagnosticStage.APPLY_PROMPT_TEMPLATE
    assert raised.value.diagnostic_category == P2CounterDiagnosticCategory.SDK_OPERATION_FAILED
    assert raised.value.sdk_exception_type == "LMStudioServerError"
    assert raised.value.sdk_status_code == 400
    assert "prompt-secret-canary" not in str(raised.value)
    assert "prompt-secret-canary" not in repr(raised.value)


def test_child_diagnostic_parser_fails_closed_on_unbounded_sdk_details() -> None:
    payload = {
        "ok": False,
        "error": P2TokenBudgetFailure.COUNTER_UNAVAILABLE.value,
        "diagnostic_stage": P2CounterDiagnosticStage.APPLY_PROMPT_TEMPLATE.value,
        "diagnostic_category": P2CounterDiagnosticCategory.SDK_OPERATION_FAILED.value,
        "sdk_exception_type": "SDKError-with-secret",
        "sdk_status_code": 400,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    error = _safe_child_error(encoded)
    assert error.reason == P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE
    assert error.diagnostic_stage is None
    assert error.sdk_exception_type is None


def test_direct_counter_session_entry_rejects_invalid_bootstrap_before_sdk_import(tmp_path: Path) -> None:
    result, marker = _run_direct_counter_entry(
        tmp_path,
        flag="--counter-session-child",
        payload=b"{}\n",
    )

    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr == b""
    assert not marker.exists()


def make_request(
    *,
    model_key: str = MODEL_KEY,
    api_host: str = "http://127.0.0.1:1234",
    max_output_tokens: int = 768,
    response_format: P2ResponseFormat | None = P2ResponseFormat(
        '{"type":"json_schema","json_schema":{"name":"fixture","strict":true,"schema":{"type":"object"}}}'
    ),
) -> P2TokenBudgetRequest:
    return P2TokenBudgetRequest(
        model_key=model_key,
        api_host=api_host,
        messages=(
            P2ChatMessage("system", "system fixture"),
            P2ChatMessage("user", "fixture prompt"),
        ),
        response_format=response_format,
        max_output_tokens=max_output_tokens,
    )


def make_checker(
    path: Path,
    *,
    expected_context: int = 8192,
    max_output: int = 768,
    artifact_hash_timeout: float = 5.0,
) -> LMStudioSDKTokenBudgetChecker:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    binding = P2ModelArtifactBinding(
        model_key=MODEL_KEY,
        artifact_path=path,
        lmstudio_model_path=MODEL_PATH,
        lmstudio_api_host="http://127.0.0.1:1234",
        artifact_sha256=digest,
        artifact_size_bytes=path.stat().st_size,
        expected_context_tokens=expected_context,
    )
    return LMStudioSDKTokenBudgetChecker(
        binding,
        P2TokenBudgetPolicy(
            actual_context_tokens=expected_context,
            max_input_tokens=6144,
            max_output_tokens=max_output,
            schema_safety_margin_tokens=512,
            sdk_call_timeout_seconds=5.0,
            artifact_hash_timeout_seconds=artifact_hash_timeout,
        ),
        python_executable=Path(sys.executable).resolve(),
        child_timeout_seconds=5.0,
    )


def child_result(
    *,
    model_key: str = MODEL_KEY,
    api_host: str = "http://127.0.0.1:1234",
    model_path: str = MODEL_PATH,
    artifact_sha256: str,
    context: int = 8192,
    prompt_tokens: int = 800,
    response_format_tokens: int = 400,
) -> subprocess.CompletedProcess[bytes]:
    stdout = json.dumps({
        "ok": True,
        "model_key": model_key,
        "api_host": api_host,
        "model_path": model_path,
        "artifact_sha256": artifact_sha256,
        "actual_context_tokens": context,
        "prompt_tokens": prompt_tokens,
        "response_format_tokens": response_format_tokens,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=b"")


def test_typed_counter_request_rejects_bad_message_boundary() -> None:
    with pytest.raises(ValueError):
        P2TokenBudgetRequest(
            model_key=MODEL_KEY,
            api_host="http://127.0.0.1:1234",
            messages=(P2ChatMessage("user", "missing system"),),
            response_format=None,
            max_output_tokens=768,
        )


def test_exact_binding_and_schema_budget_are_counted_conservatively(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "fixture.gguf"
    artifact.write_bytes(b"small-test-artifact-only")
    checker = make_checker(artifact)
    digest = checker.binding.artifact_sha256
    calls: list[dict[str, Any]] = []
    preparation_calls: list[float] = []
    prepare_artifact_binding = checker.prepare_artifact_binding

    def observed_prepare_artifact_binding(*, timeout_seconds: float = 30.0) -> tuple[str, int]:
        result = prepare_artifact_binding(timeout_seconds=timeout_seconds)
        preparation_calls.append(timeout_seconds)
        return result

    monkeypatch.setattr(checker, "prepare_artifact_binding", observed_prepare_artifact_binding)

    def fake_run(args: list[str], **kwargs: Any) -> tuple[int, bytes]:
        assert preparation_calls == [30.0]
        assert args[1] == "-B"
        assert args[-1] == "--counter-child"
        assert "shell" not in kwargs
        # measure() passes only the remaining portion of one total deadline.
        assert 0 < kwargs["timeout"] <= 5.0
        calls.append(json.loads(kwargs["stdin"].decode("utf-8")))
        return 0, child_result(artifact_sha256=digest).stdout

    monkeypatch.setattr("app.p2_token_budget._run_bounded_helper", fake_run)
    measurement = checker.measure(make_request())

    assert measurement.model_key == MODEL_KEY
    assert measurement.artifact_sha256 == digest
    assert measurement.actual_context_tokens == 8192
    assert measurement.prompt_tokens == 800
    assert measurement.response_format_tokens == 400
    assert measurement.safety_margin_tokens == 512
    assert measurement.budgeted_input_tokens == 1712
    assert measurement.max_input_tokens == 6144
    assert measurement.requested_output_tokens == 768
    assert measurement.total_measurement_ms >= measurement.artifact_hash_ms
    assert calls[0]["binding"]["artifact_sha256"] == digest
    assert calls[0]["binding"]["api_host"] == "http://127.0.0.1:1234"
    assert calls[0]["request"]["messages"][1]["content"] == "fixture prompt"
    assert calls[0]["request"]["response_format_json"] == make_request().response_format.payload_json
    assert preparation_calls == [30.0]


@pytest.mark.parametrize(
    ("child_overrides", "expected_reason"),
    [
        ({"model_key": "other-model"}, P2TokenBudgetFailure.MODEL_KEY_MISMATCH),
        ({"model_path": "other/path.gguf"}, P2TokenBudgetFailure.MODEL_PATH_MISMATCH),
        ({"context": 4096}, P2TokenBudgetFailure.CONTEXT_MISMATCH),
    ],
)
def test_loaded_model_key_path_and_context_mismatch_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    child_overrides: dict[str, Any],
    expected_reason: str,
) -> None:
    artifact = tmp_path / "fixture.gguf"
    artifact.write_bytes(b"test model bytes")
    checker = make_checker(artifact)
    digest = checker.binding.artifact_sha256
    monkeypatch.setattr(
        "app.p2_token_budget._run_bounded_helper",
        lambda *args, **kwargs: (0, child_result(artifact_sha256=digest, **child_overrides).stdout),
    )

    with pytest.raises(P2TokenBudgetError) as raised:
        checker.measure(make_request())
    assert raised.value.reason == expected_reason


def test_prompt_schema_and_output_caps_fail_closed_before_post(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "fixture.gguf"
    artifact.write_bytes(b"test model bytes")
    checker = make_checker(artifact)
    digest = checker.binding.artifact_sha256
    monkeypatch.setattr(
        "app.p2_token_budget._run_bounded_helper",
        lambda *args, **kwargs: (0, child_result(
            artifact_sha256=digest,
            prompt_tokens=6200,
            response_format_tokens=100,
        ).stdout),
    )
    with pytest.raises(P2TokenBudgetError) as input_error:
        checker.measure(make_request())
    assert input_error.value.reason == P2TokenBudgetFailure.INPUT_BUDGET_EXCEEDED

    with pytest.raises(P2TokenBudgetError) as output_error:
        checker.measure(make_request(max_output_tokens=1536))
    assert output_error.value.reason == P2TokenBudgetFailure.CONTEXT_BUDGET_EXCEEDED


def test_hash_is_cached_only_for_unchanged_stat_and_key_mismatch_never_spawns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "fixture.gguf"
    artifact.write_bytes(b"test model bytes")
    checker = make_checker(artifact)
    digest = checker.binding.artifact_sha256
    runs = 0

    def fake_run(*args: Any, **kwargs: Any) -> tuple[int, bytes]:
        nonlocal runs
        runs += 1
        return 0, child_result(artifact_sha256=digest).stdout

    monkeypatch.setattr("app.p2_token_budget._run_bounded_helper", fake_run)
    checker.measure(make_request())
    checker.measure(make_request())
    assert runs == 2

    with pytest.raises(P2TokenBudgetError) as key_error:
        checker.measure(make_request(model_key="changed-model"))
    assert key_error.value.reason == P2TokenBudgetFailure.MODEL_KEY_MISMATCH
    assert runs == 2

    artifact.write_bytes(b"mutated bytes")
    with pytest.raises(P2TokenBudgetError) as artifact_error:
        checker.measure(make_request())
    assert artifact_error.value.reason == P2TokenBudgetFailure.ARTIFACT_BINDING_CHANGED
    assert runs == 2


def test_counter_subprocess_timeout_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "fixture.gguf"
    artifact.write_bytes(b"test model bytes")
    checker = make_checker(artifact)

    def timeout(*args: Any, **kwargs: Any) -> None:
        assert 0 < kwargs["timeout"] <= 5.0
        raise TimeoutError()

    monkeypatch.setattr("app.p2_token_budget._run_bounded_helper", timeout)
    with pytest.raises(P2TokenBudgetError) as raised:
        checker.measure(make_request())
    assert raised.value.reason == P2TokenBudgetFailure.COUNTER_TIMEOUT


def test_helper_timeout_kills_only_its_child_and_caps_stdout() -> None:
    large_payload = b"x" * (512 * 1024)
    started = monotonic()
    with pytest.raises(TimeoutError):
        _run_bounded_helper(
            [str(Path(sys.executable).resolve()), "-B", "-c", "import time; time.sleep(10)"],
            stdin=large_payload,
            timeout=0.2,
        )
    # This tests the real helper process, not a mocked subprocess call: the
    # child never drains a payload larger than an ordinary Windows pipe.
    assert monotonic() - started < 2.0  # deadline plus the documented cleanup grace

    returncode, stdout = _run_bounded_helper(
        [
            str(Path(sys.executable).resolve()),
            "-B",
            "-c",
            "import sys; payload=sys.stdin.buffer.read(); sys.stdout.write(str(len(payload)))",
        ],
        stdin=large_payload,
        timeout=2.0,
    )
    assert returncode == 0
    assert stdout == str(len(large_payload)).encode("ascii")

    with pytest.raises(ValueError):
        _run_bounded_helper(
            [str(Path(sys.executable).resolve()), "-B", "-c", "print('x' * 5000)"],
            stdin=b"{}",
            timeout=2.0,
        )


def test_helper_timeout_reports_only_last_closed_progress_stage() -> None:
    progress = json.dumps(
        {"progress_stage": P2CounterDiagnosticStage.APPLY_PROMPT_TEMPLATE.value},
        sort_keys=True,
        separators=(",", ":"),
    )
    child = f"import sys,time; sys.stdout.write({progress!r}+'\\n'); sys.stdout.flush(); time.sleep(10)"
    with pytest.raises(TimeoutError) as raised:
        _run_bounded_helper(
            [str(Path(sys.executable).resolve()), "-B", "-c", child],
            stdin=b"{}",
            timeout=2.0,
        )
    assert getattr(raised.value, "diagnostic_stage", None) == P2CounterDiagnosticStage.APPLY_PROMPT_TEMPLATE


def test_sdk_counter_uses_only_loaded_handle_and_rechecks_binding_after_count() -> None:
    calls: list[object] = []
    prompt_inputs: list[object] = []
    model = type("Model", (), {
        "identifier": MODEL_KEY,
        "get_info": lambda self: type("Info", (), {
            "model_key": MODEL_KEY,
            "path": MODEL_PATH,
            "size_bytes": 16,
            "context_length": 8192,
        })(),
        "get_context_length": lambda self: 8192,
        "apply_prompt_template": lambda self, chat: (
            prompt_inputs.append(chat.to_dict()) or "template[fixture]"
        ),
        "count_tokens": lambda self, value: 10 if value == "template[fixture]" else 20,
    })()
    typed_api = _fake_typed_lms_history(calls)

    class FakeClient:
        def __init__(self, *, api_host: str) -> None:
            assert api_host == "127.0.0.1:1234"
            calls.append(("client", api_host))

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_args: object) -> None:
            calls.append("closed")

        def list_loaded_models(self, namespace: str) -> list[object]:
            assert namespace == "llm"
            calls.append("list-loaded")
            return [model]

    fake_lms = type("FakeLMStudio", (), {
        "TextData": typed_api.TextData,
        "SystemPrompt": typed_api.SystemPrompt,
        "UserMessage": typed_api.UserMessage,
        "ChatHistoryData": typed_api.ChatHistoryData,
        "Chat": typed_api.Chat,
        "Client": FakeClient,
        "set_sync_api_timeout": staticmethod(lambda timeout: calls.append(("timeout", timeout))),
    })()
    binding = {
        "model_key": MODEL_KEY,
        "api_host": "http://127.0.0.1:1234",
        "lmstudio_model_path": MODEL_PATH,
        "artifact_sha256": "a" * 64,
        "artifact_size_bytes": 16,
        "actual_context_tokens": 8192,
    }
    policy = {"sdk_call_timeout_seconds": 5.0}
    request = {
        "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        "response_format_json": '{"type":"json_schema"}',
    }

    result = _measure_loaded_model(fake_lms, binding, policy, request)

    assert result["prompt_tokens"] == 10
    assert result["response_format_tokens"] == 20
    assert calls.count("list-loaded") == 2
    assert sum(1 for call in calls if isinstance(call, tuple) and call[0] == "chat-from-history") == 1
    assert prompt_inputs == [{"messages": [
        {"role": "system", "content": [{"type": "text", "text": "s"}]},
        {"role": "user", "content": [{"type": "text", "text": "u"}]},
    ]}]
    assert ("timeout", 5.0) in calls
    assert not hasattr(fake_lms, "load")
    assert not hasattr(fake_lms, "llm")


def test_sdk_counter_bridges_closed_repair_messages_without_changing_request() -> None:
    calls: list[object] = []
    prompt_inputs: list[object] = []
    typed_api = _fake_typed_lms_history(calls)
    fake_lms = type("FakeLMStudio", (), {
        "TextData": typed_api.TextData,
        "SystemPrompt": typed_api.SystemPrompt,
        "UserMessage": typed_api.UserMessage,
        "ChatHistoryData": typed_api.ChatHistoryData,
        "Chat": typed_api.Chat,
    })()
    messages = [
        {"role": "system", "content": "système 🌿"},
        {"role": "system", "content": P2_REPAIR_INSTRUCTIONS["invalid_json_syntax"]},
        {"role": "user", "content": "原始输入：金额 42.10"},
    ]
    request = {"messages": messages, "response_format_json": None}
    before = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    binding = {
        "model_key": MODEL_KEY,
        "api_host": "http://127.0.0.1:1234",
        "lmstudio_model_path": MODEL_PATH,
        "artifact_sha256": "a" * 64,
        "artifact_size_bytes": 16,
        "actual_context_tokens": 8192,
    }
    policy = {"sdk_call_timeout_seconds": 5.0}

    class Model:
        identifier = MODEL_KEY

        def get_info(self) -> object:
            return type("Info", (), {
                "model_key": MODEL_KEY,
                "path": MODEL_PATH,
                "size_bytes": 16,
                "context_length": 8192,
            })()

        def get_context_length(self) -> int:
            return 8192

        def apply_prompt_template(self, chat: object) -> str:
            prompt_inputs.append(chat.to_dict())
            return "typed-repair-template"

        def count_tokens(self, text: str) -> int:
            assert text == "typed-repair-template"
            return 17

    model = Model()

    class Client:
        def __init__(self, *, api_host: str) -> None:
            assert api_host == "127.0.0.1:1234"

        def __enter__(self) -> Client:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def list_loaded_models(self, namespace: str) -> list[object]:
            assert namespace == "llm"
            calls.append("list-loaded")
            return [model]

    fake_lms.Client = Client
    fake_lms.set_sync_api_timeout = staticmethod(lambda _timeout: None)
    result = _measure_loaded_model(fake_lms, binding, policy, request)

    expected_history = {
        "messages": [
            {"role": "system", "content": [{"type": "text", "text": "système 🌿"}]},
            {"role": "system", "content": [{"type": "text", "text": P2_REPAIR_INSTRUCTIONS["invalid_json_syntax"]}]},
            {"role": "user", "content": [{"type": "text", "text": "原始输入：金额 42.10"}]},
        ],
    }
    assert calls == [
        "list-loaded",
        ("chat-from-history", {"messages": expected_history["messages"]}),
        "list-loaded",
    ]
    assert prompt_inputs == [expected_history]
    assert result["prompt_tokens"] == 17
    assert json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")) == before


@pytest.mark.parametrize(
    "messages",
    [
        [{"role": "developer", "content": "x"}, {"role": "user", "content": "y"}],
        [{"role": "system", "content": "x", "extra": True}, {"role": "user", "content": "y"}],
        [
            {"role": "system", "content": "x"},
            {"role": "system", "content": "unregistered repair text"},
            {"role": "user", "content": "y"},
        ],
    ],
)
def test_sdk_chat_bridge_rejects_unregistered_message_shapes_before_sdk_construction(
    messages: list[dict[str, object]],
) -> None:
    calls: list[object] = []
    typed_api = _fake_typed_lms_history(calls)

    with pytest.raises(P2TokenBudgetError) as raised:
        _sdk_chat_from_p2_messages(typed_api, messages)

    assert raised.value.reason == P2TokenBudgetFailure.INVALID_COUNTER_RESPONSE
    assert calls == []


def test_sdk_chat_bridge_fails_closed_when_public_typed_api_is_missing() -> None:
    class DictOnlyChat:
        @staticmethod
        def from_history(_history: object) -> object:
            raise AssertionError("must_not_fallback_to_dict_chat")

    fake_lms = type("IncompleteLMStudio", (), {"Chat": DictOnlyChat})()
    with pytest.raises(P2TokenBudgetError) as raised:
        _sdk_chat_from_p2_messages(
            fake_lms,
            [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        )
    assert raised.value.reason == P2TokenBudgetFailure.COUNTER_UNAVAILABLE


def test_sdk_counter_rejects_model_window_change_during_count() -> None:
    calls = 0
    sdk_calls: list[object] = []

    class Model:
        identifier = MODEL_KEY

        def get_info(self) -> object:
            return type("Info", (), {
                "model_key": MODEL_KEY,
                "path": MODEL_PATH,
                "size_bytes": 16,
                "context_length": 8192,
            })()

        def get_context_length(self) -> int:
            nonlocal calls
            calls += 1
            return 8192 if calls <= 1 else 4096

        def apply_prompt_template(self, chat: object) -> str:
            return "template"

        def count_tokens(self, text: str) -> int:
            return 10

    model = Model()

    class FakeClient:
        def __init__(self, *, api_host: str) -> None:
            pass

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def list_loaded_models(self, namespace: str) -> list[object]:
            return [model]

    typed_api = _fake_typed_lms_history(sdk_calls)
    fake_lms = type("FakeLMStudio", (), {
        "TextData": typed_api.TextData,
        "SystemPrompt": typed_api.SystemPrompt,
        "UserMessage": typed_api.UserMessage,
        "ChatHistoryData": typed_api.ChatHistoryData,
        "Client": FakeClient,
        "Chat": typed_api.Chat,
        "set_sync_api_timeout": staticmethod(lambda _timeout: None),
    })()

    with pytest.raises(P2TokenBudgetError) as raised:
        _measure_loaded_model(
            fake_lms,
            {
                "model_key": MODEL_KEY,
                "api_host": "http://127.0.0.1:1234",
                "lmstudio_model_path": MODEL_PATH,
                "artifact_sha256": "a" * 64,
                "artifact_size_bytes": 16,
                "actual_context_tokens": 8192,
            },
            {"sdk_call_timeout_seconds": 5.0},
            {
                "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
                "response_format_json": None,
            },
        )
    assert raised.value.reason == P2TokenBudgetFailure.CONTEXT_MISMATCH
    assert len([item for item in sdk_calls if isinstance(item, tuple) and item[0] == "chat-from-history"]) == 1


def test_diagnostic_output_cap_can_be_explicitly_raised_to_1536_without_changing_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "fixture.gguf"
    artifact.write_bytes(b"test model bytes")
    checker = make_checker(artifact, max_output=1536)
    digest = checker.binding.artifact_sha256
    monkeypatch.setattr(
        "app.p2_token_budget._run_bounded_helper",
        lambda *args, **kwargs: (0, child_result(
            artifact_sha256=digest,
            prompt_tokens=1000,
            response_format_tokens=500,
        ).stdout),
    )
    measurement = checker.measure(make_request(max_output_tokens=1536))
    assert measurement.max_output_tokens == 1536
    assert measurement.requested_output_tokens == 1536
    assert P2TokenBudgetPolicy().max_output_tokens == 768
