from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from agent.app import p2_read_contracts as c
from agent.app.p2_model_provider import (
    LMStudioOpenAIConfig,
    LMStudioOpenAIProvider,
    LMStudioProviderError,
    LMStudioProviderErrorCode as ErrorCode,
    _TransportResult,
)
from agent.app.p2_read_prompt import (
    P2_ENDPOINT_URL,
    P2PromptBuildConfig,
    P2PromptInputError,
    P2RepairFeedback,
    build_p2_request,
)
from agent.app.p2_read_provider import P2ReadProvider
from agent.app.p2_token_budget import (
    P2ChatMessage,
    P2ResponseFormat,
    P2TokenBudgetMeasurement,
    P2TokenBudgetRequest,
    _parse_child_output,
)
from agent.app.p2_format_repair import P2_REPAIR_INSTRUCTIONS, is_allowed_p2_message_sequence


MODEL = "repair-cpu-model"
REF_PRINCIPAL = "ref_" + "A" * 22
REF_TURN = "ref_" + "B" * 22


def make_context() -> c.P2ModelContext:
    return c.P2ModelContext(
        profile_id=c.P2_CANDIDATE_PROFILE_ID,
        versions=c.P2_VERSIONS,
        context_version="repair-cpu-context-v1",
        generation=1,
        input_text="列出允许的候选操作。",
        trusted_intent=c.P2TrustedIntent(
            authority="server",
            classification="non_business",
            requires_authoritative_evidence=False,
            source_input_seq=0,
            classifier_version="repair-cpu-v1",
        ),
        scope_authorization=c.P2ScopeAuthorization(
            status="absent", scope=None, authorization_receipt_ref=None,
        ),
        guard=c.P2DecisionGuard(
            source_free_business_answer_allowed=True,
            allowed_decision_kinds=("answer", "clarify"),
            allowed_read_operations=(),
            fresh_receipt_refs=(),
            proposal_clarification_required=None,
            allowed_proposal_operations=(),
        ),
        query_evidence=(),
        continuations=(),
        facts=(),
        recent_messages=(),
    )


def make_intent_context() -> c.P2IntentContext:
    return c.P2IntentContext(
        classification="non_business",
        principal_ref=REF_PRINCIPAL,
        owner_turn_ref=REF_TURN,
        generation=1,
        source_input_seq=0,
        input_digest="c" * 64,
        scope_status="absent",
        classifier_source="server_policy",
        classifier_version="repair-cpu-v1",
    )


def completion(content: str) -> bytes:
    return json.dumps({"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": content}}]}).encode()


class FakeCounter:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def measure(self, request: Any) -> P2TokenBudgetMeasurement:
        self.requests.append(request)
        return P2TokenBudgetMeasurement(
            model_key=request.model_key,
            api_host=request.api_host,
            artifact_path="cpu-fake.gguf",
            artifact_sha256="d" * 64,
            actual_context_tokens=8192,
            prompt_tokens=500,
            response_format_tokens=100,
            safety_margin_tokens=512,
            budgeted_input_tokens=1112,
            max_input_tokens=6144,
            requested_output_tokens=request.max_output_tokens,
            max_output_tokens=768,
        )


def make_provider(transport: Any, checker: FakeCounter) -> P2ReadProvider:
    base = LMStudioOpenAIProvider(
        LMStudioOpenAIConfig(
            model_key=MODEL,
            enabled=True,
            endpoint_url=P2_ENDPOINT_URL,
            temperature=0.0,
            max_output_tokens=768,
            max_concurrency=1,
        ),
        transport=transport,
        token_budget_checker=checker,
    )
    candidate = P2ReadProvider(base)
    candidate.start()
    return candidate


def feedback(code: str = "invalid_json_syntax") -> P2RepairFeedback:
    return P2RepairFeedback(error_code=code, instruction_id="p2_format_repair_v1")


def test_feedback_dto_is_closed_and_revalidates_model_construct_or_copy_bypasses() -> None:
    with pytest.raises(Exception):
        P2RepairFeedback.model_validate(
            {"error_code": "arbitrary_model_error", "instruction_id": "p2_format_repair_v1"},
            strict=True,
        )
    with pytest.raises(Exception):
        P2RepairFeedback(error_code="invalid_json_syntax", instruction_id="other")

    copied_bypass = feedback().model_copy(update={"error_code": "include raw output: secret"})
    with pytest.raises(P2PromptInputError, match="repair feedback"):
        build_p2_request(
            make_context(), config=P2PromptBuildConfig(model_id=MODEL), repair_feedback=copied_bypass
        )

    constructed_bypass = P2RepairFeedback.model_construct(
        error_code="unsafe", instruction_id="p2_format_repair_v1"
    )
    with pytest.raises(P2PromptInputError, match="repair feedback"):
        build_p2_request(
            make_context(), config=P2PromptBuildConfig(model_id=MODEL), repair_feedback=constructed_bypass
        )


def test_no_feedback_is_two_messages_and_repair_changes_prepared_identity_only() -> None:
    context = make_context()
    config = P2PromptBuildConfig(model_id=MODEL)
    normal = build_p2_request(context, config=config)
    repaired = build_p2_request(context, config=config, repair_feedback=feedback())
    changed_code = build_p2_request(
        context, config=config, repair_feedback=feedback("invalid_strict_decision_schema")
    )
    normal_body = json.loads(normal.body_bytes)
    repair_body = json.loads(repaired.body_bytes)

    assert len(normal_body["messages"]) == 2
    assert len(repair_body["messages"]) == 3
    assert normal_body["messages"][0] == repair_body["messages"][0]
    assert normal_body["messages"][1] == repair_body["messages"][2]
    assert repair_body["messages"][1]["role"] == "system"
    assert repair_body["messages"][1]["content"] != normal_body["messages"][0]["content"]
    assert repaired.repair_feedback == feedback()
    assert repaired.repair_feedback_sha256 == sha256(
        json.dumps(feedback().model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert repaired.request_sha256 != normal.request_sha256
    assert repaired.prepared_fingerprint_sha256 != normal.prepared_fingerprint_sha256
    assert changed_code.request_sha256 != repaired.request_sha256
    assert changed_code.prepared_fingerprint_sha256 != repaired.prepared_fingerprint_sha256
    assert sha256(normal.body_bytes).hexdigest() == normal.request_sha256
    assert normal.request_sha256 == "6611de455f8898fe4e5e77ecb61af5a94f1ccb0914dc46fdf19fff2dd7c38dd0"


def test_provider_counts_and_posts_exact_repaired_body_once() -> None:
    posted: list[tuple[str, bytes]] = []
    checker = FakeCounter()

    def transport(url: str, body: bytes, *_args: Any) -> _TransportResult:
        posted.append((url, body))
        response = json.dumps({
            "kind": "answer", "basis": "non_business_general",
            "text": "CPU fake answer.", "citations": [],
        }, separators=(",", ":"))
        return _TransportResult(200, completion(response))

    context = make_context()
    fix = feedback("invalid_strict_decision_schema")
    prepared = build_p2_request(context, config=P2PromptBuildConfig(model_id=MODEL), repair_feedback=fix)
    provider = make_provider(transport, checker)
    raw = asyncio.run(provider.generate(context, prepared, repair_feedback=fix))
    decision = c.parse_p2_decision(raw, make_intent_context())

    assert decision.kind == "answer"
    assert len(checker.requests) == 1
    assert len(posted) == 1
    url, body = posted[0]
    assert url == P2_ENDPOINT_URL
    assert body == prepared.body_bytes
    assert sha256(body).hexdigest() == prepared.request_sha256
    payload = json.loads(body)
    counted = checker.requests[0]
    assert counted.model_key == payload["model"] == MODEL
    assert [{"role": item.role, "content": item.content} for item in counted.messages] == payload["messages"]
    assert json.loads(counted.response_format.payload_json) == payload["response_format"]


@pytest.mark.parametrize("mismatch", ["missing", "different", "prepared-none", "tampered-feedback-hash", "nested-bypass"])
def test_feedback_mismatch_fails_before_count_or_http(mismatch: str) -> None:
    posted: list[bytes] = []
    checker = FakeCounter()
    provider = make_provider(
        lambda _url, body, *_args: (posted.append(body) or _TransportResult(200, completion("{}"))),
        checker,
    )
    context = make_context()
    syntax = feedback("invalid_json_syntax")
    schema = feedback("invalid_strict_decision_schema")
    repair_prepared = build_p2_request(context, config=P2PromptBuildConfig(model_id=MODEL), repair_feedback=syntax)
    supplied: P2RepairFeedback | None = syntax

    if mismatch == "missing":
        supplied = None
    elif mismatch == "different":
        supplied = schema
    elif mismatch == "prepared-none":
        repair_prepared = build_p2_request(context, config=P2PromptBuildConfig(model_id=MODEL))
    elif mismatch == "tampered-feedback-hash":
        repair_prepared = repair_prepared.model_copy(update={"repair_feedback_sha256": "f" * 64})
    elif mismatch == "nested-bypass":
        bad_feedback = syntax.model_copy(update={"error_code": "raw output: unsafe"})
        repair_prepared = repair_prepared.model_copy(update={"repair_feedback": bad_feedback})

    with pytest.raises(LMStudioProviderError) as raised:
        asyncio.run(provider.generate(context, repair_prepared, repair_feedback=supplied))
    assert raised.value.code is ErrorCode.INVALID_PROMPT
    assert checker.requests == []
    assert posted == []


_COUNTER_SCRIPT = Path(__file__).parents[1] / "app" / "p2_token_budget.py"


def _messages(variant: str) -> list[dict[str, str]]:
    good_system = {"role": "system", "content": "server system prompt"}
    good_user = {"role": "user", "content": "validated context"}
    repair_text = next(iter(P2_REPAIR_INSTRUCTIONS.values()))
    repair = {"role": "system", "content": repair_text}
    if variant == "legacy":
        return [good_system, good_user]
    if variant == "repair":
        return [good_system, repair, good_user]
    if variant == "wrong-role":
        return [good_system, {"role": "assistant", "content": repair_text}, good_user]
    if variant == "wrong-order":
        return [good_system, good_user, repair]
    if variant == "unknown-middle":
        return [good_system, {"role": "system", "content": "model supplied arbitrary feedback"}, good_user]
    if variant == "extra-fourth":
        return [good_system, repair, good_user, good_user]
    if variant == "malformed-message":
        return [good_system, {"role": "system", "content": repair_text, "extra": "x"}, good_user]
    raise AssertionError(variant)


def _typed_request(messages: list[dict[str, str]]) -> P2TokenBudgetRequest:
    return P2TokenBudgetRequest(
        model_key="fixture-key",
        api_host="http://127.0.0.1:1234",
        messages=tuple(P2ChatMessage(role=item["role"], content=item["content"]) for item in messages),
        response_format=P2ResponseFormat('{"type":"json_schema"}'),
        max_output_tokens=768,
    )


def test_typed_counter_request_accepts_only_legacy_pair_or_closed_repair_triplet() -> None:
    assert _typed_request(_messages("legacy")).messages[0].role == "system"
    assert len(_typed_request(_messages("repair")).messages) == 3
    with pytest.raises(ValueError, match="invalid typed chat message"):
        _typed_request(_messages("wrong-role"))
    for variant in ("wrong-order", "unknown-middle", "extra-fourth"):
        with pytest.raises(ValueError, match="closed format-repair"):
            _typed_request(_messages(variant))
    malformed = _messages("repair")
    malformed[1] = {"role": "system", "content": next(iter(P2_REPAIR_INSTRUCTIONS.values())) + " extra"}
    assert not is_allowed_p2_message_sequence(malformed)


def _write_fake_sdk(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "lmstudio-1.5.0.dist-info").mkdir(exist_ok=True)
    (directory / "lmstudio-1.5.0.dist-info" / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: lmstudio\nVersion: 1.5.0\n\n", encoding="utf-8"
    )
    (directory / "lmstudio.py").write_text(
        '''import json, os
from types import SimpleNamespace

def _record(event, value=None):
    path = os.environ.get("P2_FAKE_SDK_RECORD")
    if path:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": event, "value": value}, sort_keys=True) + "\\n")

_record("import")

def set_sync_api_timeout(value):
    _record("timeout", value)

class TextData:
    def __init__(self, *, text):
        self.text = text
    def to_dict(self):
        return {"type": "text", "text": self.text}

class SystemPrompt:
    def __init__(self, *, content):
        self.content = content
    def to_dict(self):
        return {"role": "system", "content": [part.to_dict() for part in self.content]}

class UserMessage:
    def __init__(self, *, content):
        self.content = content
    def to_dict(self):
        return {"role": "user", "content": [part.to_dict() for part in self.content]}

class ChatHistoryData:
    def __init__(self, *, messages):
        self.messages = messages
    def to_dict(self):
        return {"messages": [message.to_dict() for message in self.messages]}

class Chat:
    @staticmethod
    def from_history(history):
        payload = history.to_dict()
        _record("history", payload)
        return payload

class Model:
    identifier = "fixture-key"
    def get_info(self):
        return SimpleNamespace(model_key="fixture-key", path="fixture/model.gguf", size_bytes=4096, context_length=8192)
    def get_context_length(self):
        return 8192
    def apply_prompt_template(self, chat):
        _record("template", chat)
        return json.dumps(chat, ensure_ascii=False)
    def count_tokens(self, value):
        _record("count", {"type": type(value).__name__, "length": len(value)})
        return 123

class Client:
    def __init__(self, api_host=None):
        self.api_host = api_host
        self.model = Model()
        _record("client", api_host)
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return False
    def list_loaded_models(self, _kind):
        return [self.model]
''',
        encoding="utf-8",
    )
    return directory


def _counter_env(fake_sdk: Path, record: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(fake_sdk)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["P2_FAKE_SDK_RECORD"] = str(record)
    return env


def _binding() -> dict[str, Any]:
    return {
        "model_key": "fixture-key",
        "api_host": "http://127.0.0.1:1234",
        "lmstudio_model_path": "fixture/model.gguf",
        "artifact_sha256": "a" * 64,
        "artifact_size_bytes": 4096,
        "actual_context_tokens": 8192,
    }


def _policy() -> dict[str, Any]:
    return {
        "max_input_tokens": 6144,
        "max_output_tokens": 768,
        "schema_safety_margin_tokens": 512,
        "sdk_call_timeout_seconds": 5.0,
    }


def _request(messages: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "model_key": "fixture-key",
        "api_host": "http://127.0.0.1:1234",
        "lmstudio_model_path": "fixture/model.gguf",
        "artifact_sha256": "a" * 64,
        "artifact_size_bytes": 4096,
        "actual_context_tokens": 8192,
        "messages": messages,
        "response_format_json": '{"type":"json_schema"}',
        "max_output_tokens": 768,
    }


def _run_direct(tmp_path: Path, payload: object) -> tuple[subprocess.CompletedProcess[bytes], Path]:
    fake_sdk = _write_fake_sdk(tmp_path / "fake-sdk")
    record = tmp_path / "sdk-record.jsonl"
    completed = subprocess.run(
        [sys.executable, "-B", str(_COUNTER_SCRIPT), "--counter-child"],
        input=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        capture_output=True,
        cwd=str(_COUNTER_SCRIPT.parent),
        env=_counter_env(fake_sdk, record),
        timeout=10,
        check=False,
    )
    return completed, record


def _direct_payload(messages: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "protocol": "p2-token-budget-v2-diagnostic",
        "binding": _binding(),
        "policy": _policy(),
        "request": _request(messages),
    }


def test_actual_counter_child_entry_rejects_invalid_shapes_before_fake_sdk_import(tmp_path: Path) -> None:
    for variant in ("wrong-role", "wrong-order", "unknown-middle", "extra-fourth", "malformed-message"):
        completed, record = _run_direct(tmp_path / variant, _direct_payload(_messages(variant)))
        assert completed.returncode == 1
        assert json.loads(completed.stdout) == {
            "error": "invalid_counter_response",
            "ok": False,
            "diagnostic_stage": "request_validation",
            "diagnostic_category": "protocol_rejected",
            "sdk_exception_type": None,
            "sdk_status_code": None,
        }
        assert completed.stderr == b""
        assert not record.exists(), f"fake SDK imported for invalid input: {variant}"


def test_actual_counter_child_counts_legacy_and_closed_repair_bodies_with_fake_sdk(tmp_path: Path) -> None:
    for variant, count in (("legacy", 2), ("repair", 3)):
        completed, record = _run_direct(tmp_path / variant, _direct_payload(_messages(variant)))
        assert completed.returncode == 0, completed.stdout.decode(errors="replace")
        result = _parse_child_output(completed.stdout)
        assert result["ok"] is True
        assert result["prompt_tokens"] == 123
        events = [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines()]
        history = next(event["value"] for event in events if event["event"] == "history")
        assert len(history["messages"]) == count
        assert [item["role"] for item in history["messages"]] == ( ["system", "user"] if count == 2 else ["system", "system", "user"] )


def _session_bootstrap() -> dict[str, Any]:
    candidate_id = "cpu-repair-candidate"
    binding = _binding()
    fingerprint = sha256(json.dumps({"candidate_id": candidate_id, "binding": binding}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "protocol": "p2-token-budget-session-v1",
        "operation": "prepare",
        "candidate_id": candidate_id,
        "session_id": "cpu-repair-session",
        "request_id": 0,
        "binding_fingerprint": fingerprint,
        "binding": binding,
        "policy": _policy(),
    }


def _session_command(messages: list[dict[str, str]]) -> dict[str, Any]:
    bootstrap = _session_bootstrap()
    return {
        "protocol": "p2-token-budget-session-v1",
        "operation": "measure",
        "candidate_id": bootstrap["candidate_id"],
        "session_id": bootstrap["session_id"],
        "binding_fingerprint": bootstrap["binding_fingerprint"],
        "request_id": 1,
        "policy": _policy(),
        "request": {
            "model_key": "fixture-key",
            "messages": messages,
            "response_format_json": '{"type":"json_schema"}',
            "max_output_tokens": 768,
        },
    }


def _run_session(tmp_path: Path, bootstrap: object, command: object | None = None) -> tuple[subprocess.CompletedProcess[bytes], Path]:
    fake_sdk = _write_fake_sdk(tmp_path / "fake-sdk")
    record = tmp_path / "sdk-record.jsonl"
    data = json.dumps(bootstrap, separators=(",", ":")).encode() + b"\n"
    if command is not None:
        data += json.dumps(command, separators=(",", ":")).encode() + b"\n"
    completed = subprocess.run(
        [sys.executable, "-B", str(_COUNTER_SCRIPT), "--counter-session-child"],
        input=data,
        capture_output=True,
        cwd=str(_COUNTER_SCRIPT.parent),
        env=_counter_env(fake_sdk, record),
        timeout=10,
        check=False,
    )
    return completed, record


def test_actual_session_child_keeps_invalid_bootstrap_pre_sdk_sanitized_refusal(tmp_path: Path) -> None:
    completed, record = _run_session(tmp_path, {})
    assert completed.returncode == 2
    assert completed.stdout == b""
    assert completed.stderr == b""
    assert not record.exists()


def test_actual_session_child_validates_measure_shapes_and_counts_exact_legacy_or_repair_messages(tmp_path: Path) -> None:
    for variant, count in (("legacy", 2), ("repair", 3)):
        completed, record = _run_session(
            tmp_path / variant, _session_bootstrap(), _session_command(_messages(variant))
        )
        assert completed.returncode == 0, completed.stdout.decode(errors="replace")
        events = [json.loads(line) for line in completed.stdout.decode().splitlines()]
        assert [event["operation"] for event in events] == ["ready", "result"]
        assert events[1]["ok"] is True
        logs = [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines()]
        history = next(event["value"] for event in logs if event["event"] == "history")
        assert len(history["messages"]) == count


def test_actual_session_measure_validator_rejects_invalid_repair_shapes_before_count(tmp_path: Path) -> None:
    for variant in ("wrong-role", "wrong-order", "unknown-middle", "extra-fourth", "malformed-message"):
        completed, record = _run_session(
            tmp_path / variant, _session_bootstrap(), _session_command(_messages(variant))
        )
        assert completed.returncode == 2
        events = [json.loads(line) for line in completed.stdout.decode().splitlines()]
        assert [event["operation"] for event in events] == ["ready"]
        assert record.exists()  # SDK is imported only after the valid session bootstrap.
        assert not any(json.loads(line)["event"] == "history" for line in record.read_text(encoding="utf-8").splitlines())
