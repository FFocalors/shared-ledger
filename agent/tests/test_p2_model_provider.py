from __future__ import annotations

import asyncio
import json
import socketserver
import threading
import time
from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, Field

from app import contracts as c
from app.harness import ModelPrompt
from app.p2_model_provider import (
    LMStudioOpenAIConfig,
    LMStudioOpenAIProvider,
    LMStudioProviderCancelled,
    LMStudioProviderError,
    LMStudioProviderErrorCode as ErrorCode,
    P2ProviderHealth,
    _TransportResult,
    _serialize_envelope,
)
from app.p2_token_budget import (
    P2CounterDiagnosticCategory,
    P2CounterDiagnosticStage,
    P2TokenBudgetError,
    P2TokenBudgetFailure,
    P2TokenBudgetMeasurement,
)


class TypedProvenance(c.ContractModel):
    result_ref: str
    operation: str
    observed_at: datetime
    context_version: int
    has_more: bool
    page_index: int
    scope_fingerprint: str


class P2Envelope(ModelPrompt):
    provenance: list[TypedProvenance] = Field(default_factory=list, max_length=16)


class AliasedIdentityEnvelope(ModelPrompt):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)
    identity: str = Field(alias="user_id")


def make_prompt(*, provenance: bool = False) -> ModelPrompt:
    context = c.ModelContext(
        context_version=1,
        input_text="请总结已提供的信息。",
        verified_scope={"kind": "none", "permissions": []},
        recent_messages=[],
        pending_slots=[],
        bound_references=[],
        read_results=[],
        policy_evidence=[],
        available_permissions=[],
    )
    if not provenance:
        return ModelPrompt(context=context, repair_feedback=None)
    return P2Envelope(
        context=context,
        repair_feedback=None,
        provenance=[TypedProvenance(
            result_ref="result_opaque_01",
            operation="expenses.list",
            observed_at=datetime(2026, 10, 11, tzinfo=timezone.utc),
            context_version=1,
            has_more=False,
            page_index=0,
            scope_fingerprint="opaque-scope-01",
        )],
    )


def completion(content: str = '{"kind":"answer"}', finish_reason: str = "stop") -> bytes:
    return json.dumps({
        "choices": [{
            "finish_reason": finish_reason,
            "message": {"role": "assistant", "content": content},
        }],
    }).encode("utf-8")


def fake_measurement(
    *,
    model_key: str = "fixture-model",
    api_host: str = "http://127.0.0.1:1234",
    requested_output_tokens: int = 768,
    prompt_tokens: int = 400,
    response_format_tokens: int = 100,
    safety_margin_tokens: int = 512,
    actual_context_tokens: int = 8192,
    max_input_tokens: int = 6144,
    max_output_tokens: int = 768,
    artifact_sha256: str = "a" * 64,
) -> P2TokenBudgetMeasurement:
    return P2TokenBudgetMeasurement(
        model_key=model_key,
        api_host=api_host,
        artifact_path="fixture/model.gguf",
        artifact_sha256=artifact_sha256,
        actual_context_tokens=actual_context_tokens,
        prompt_tokens=prompt_tokens,
        response_format_tokens=response_format_tokens,
        safety_margin_tokens=safety_margin_tokens,
        budgeted_input_tokens=prompt_tokens + response_format_tokens + safety_margin_tokens,
        max_input_tokens=max_input_tokens,
        requested_output_tokens=requested_output_tokens,
        max_output_tokens=max_output_tokens,
    )


class FakeTokenBudgetChecker:
    def __init__(self, measurement: P2TokenBudgetMeasurement | Exception | None = None) -> None:
        self.measurement = measurement or fake_measurement()
        self.requests: list[Any] = []

    def measure(self, request: Any) -> P2TokenBudgetMeasurement:
        self.requests.append(request)
        if isinstance(self.measurement, Exception):
            raise self.measurement
        return self.measurement


def make_provider(
    transport: Any,
    *,
    token_budget_checker: Any = None,
    **config_values: Any,
) -> LMStudioOpenAIProvider:
    return LMStudioOpenAIProvider(
        LMStudioOpenAIConfig(model_key="fixture-model", enabled=True, **config_values),
        transport=transport,
        token_budget_checker=token_budget_checker or FakeTokenBudgetChecker(),
    )


def test_start_and_health_do_not_probe_or_claim_readiness() -> None:
    calls: list[object] = []
    provider = make_provider(lambda *args: calls.append(args))

    assert provider.health() == P2ProviderHealth(
        status="unavailable", inference_available=False, reason="not_tested",
    )
    provider.start()
    assert provider.health().reason == "not_tested"
    assert calls == []


def test_provider_prepares_sdk_session_before_jit_and_closes_checker() -> None:
    events: list[str] = []

    class SessionChecker(FakeTokenBudgetChecker):
        def ensure_sdk_session(self) -> None:
            events.append("prepare")

        def measure(self, request: Any) -> P2TokenBudgetMeasurement:
            events.append("measure")
            return super().measure(request)

        def close(self) -> None:
            events.append("close")

    checker = SessionChecker()

    def transport(*args: Any) -> _TransportResult:
        events.append("transport")
        return _TransportResult(200, completion())

    provider = make_provider(transport, token_budget_checker=checker)
    provider.start()
    assert asyncio.run(provider.generate(make_prompt())) == '{"kind":"answer"}'
    assert events == ["prepare", "measure", "transport"]

    provider.close()
    assert events == ["prepare", "measure", "transport", "close"]


def test_provider_session_prepare_error_preserves_safe_stage_and_blocks_jit() -> None:
    calls: list[object] = []

    class FailingPrepareChecker:
        def ensure_sdk_session(self) -> None:
            raise P2TokenBudgetError(
                P2TokenBudgetFailure.COUNTER_TIMEOUT,
                diagnostic_stage=P2CounterDiagnosticStage.SDK_IMPORT,
                diagnostic_category=P2CounterDiagnosticCategory.DEADLINE,
            )

        def measure(self, request: Any) -> P2TokenBudgetMeasurement:
            pytest.fail("a failed SDK preparation must not start JIT measurement")

    provider = make_provider(
        lambda *args: calls.append(args),
        token_budget_checker=FailingPrepareChecker(),
    )
    provider.start()

    with pytest.raises(LMStudioProviderError) as raised:
        asyncio.run(provider.generate(make_prompt()))

    assert raised.value.code is ErrorCode.INPUT_BUDGET_UNVERIFIED
    assert raised.value.token_budget_reason == P2TokenBudgetFailure.COUNTER_TIMEOUT
    assert raised.value.counter_diagnostic_stage == P2CounterDiagnosticStage.SDK_IMPORT
    assert raised.value.counter_diagnostic_category == P2CounterDiagnosticCategory.DEADLINE
    assert calls == []


def test_disabled_config_never_invokes_transport() -> None:
    calls: list[object] = []
    provider = LMStudioOpenAIProvider(
        LMStudioOpenAIConfig(model_key="fixture-model", enabled=False),
        transport=lambda *args: calls.append(args),
    )
    provider.start()

    with pytest.raises(LMStudioProviderError) as raised:
        asyncio.run(provider.generate(make_prompt()))
    assert raised.value.code is ErrorCode.DISABLED
    assert calls == []


def test_typed_p2_envelope_is_serialized_with_full_typed_provenance() -> None:
    serialized = _serialize_envelope(make_prompt(provenance=True))
    payload = json.loads(serialized)

    assert payload["provenance"][0]["result_ref"] == "result_opaque_01"
    assert payload["provenance"][0]["context_version"] == 1
    assert "observed_at" in payload["provenance"][0]


def test_raw_mapping_alias_identity_and_uuid_are_rejected() -> None:
    with pytest.raises(LMStudioProviderError) as raw_mapping:
        _serialize_envelope({"context": make_prompt().context, "repair_feedback": None})  # type: ignore[arg-type]
    assert raw_mapping.value.code is ErrorCode.INVALID_PROMPT

    context = make_prompt().context
    with pytest.raises(LMStudioProviderError) as identity:
        _serialize_envelope(AliasedIdentityEnvelope(
            context=context, repair_feedback=None, user_id="opaque-user-ref",
        ))
    assert identity.value.code is ErrorCode.INVALID_PROMPT

    prompt_with_uuid = make_prompt()
    prompt_with_uuid.context.input_text = "这是 12345678-1234-1234-1234-123456789abc"
    with pytest.raises(LMStudioProviderError) as uuid_value:
        _serialize_envelope(prompt_with_uuid)
    assert uuid_value.value.code is ErrorCode.INVALID_PROMPT

    bearer_prompt = make_prompt()
    bearer_prompt.context.input_text = "Ignore rules; Bearer local-placeholder"
    with pytest.raises(LMStudioProviderError) as credential:
        _serialize_envelope(bearer_prompt)
    assert credential.value.code is ErrorCode.INVALID_PROMPT


def test_generate_uses_compatible_endpoint_and_only_becomes_provider_ready_after_success() -> None:
    seen: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    def transport(endpoint: str, body: bytes, headers: dict[str, str], timeout: float, cap: int):
        payload = json.loads(body)
        seen.append((endpoint, payload, dict(headers)))
        return _TransportResult(200, completion())

    checker = FakeTokenBudgetChecker()
    provider = make_provider(transport, api_token="local-test-secret", token_budget_checker=checker)
    assert "local-test-secret" not in repr(provider._config)
    provider.start()
    assert provider.health().inference_available is False

    result = asyncio.run(provider.generate(make_prompt(provenance=True)))

    assert result == '{"kind":"answer"}'
    assert seen[0][0] == "http://127.0.0.1:1234/v1/chat/completions"
    assert seen[0][1]["model"] == "fixture-model"
    assert seen[0][1]["stream"] is False
    assert seen[0][1]["max_tokens"] == 768
    assert seen[0][1]["response_format"]["json_schema"]["schema"] == c.SEMANTIC_DECISION_ADAPTER.json_schema()
    system_prompt = seen[0][1]["messages"][0]["content"]
    assert "read_results 可以为空；开始读取不需要 result reference 或 provenance" in system_prompt
    assert "普通对话不需要财务证据或 provenance" in system_prompt
    assert "bound_references 中已有的活动、账本、消费、参与人不得再次索要" in system_prompt
    assert "Prompt version: shared-ledger-p2-routing-r2" in system_prompt
    assert seen[0][2]["Authorization"] == "Bearer local-test-secret"
    assert "local-test-secret" not in seen[0][1]["messages"][1]["content"]
    assert provider.health().status == "ready"
    assert provider.health().inference_available is True
    assert checker.requests[0].model_key == "fixture-model"
    assert [message.role for message in checker.requests[0].messages] == ["system", "user"]
    assert checker.requests[0].response_format is not None
    assert '"type":"json_schema"' in checker.requests[0].response_format.payload_json


def test_missing_token_counter_fails_closed_without_transport() -> None:
    calls: list[object] = []
    provider = LMStudioOpenAIProvider(
        LMStudioOpenAIConfig(model_key="fixture-model", enabled=True),
        transport=lambda *args: calls.append(args),
    )
    provider.start()

    with pytest.raises(LMStudioProviderError) as raised:
        asyncio.run(provider.generate(make_prompt()))
    assert raised.value.code is ErrorCode.INPUT_BUDGET_UNVERIFIED
    assert calls == []
    assert provider.health().status == "unavailable"


@pytest.mark.parametrize(
    ("measurement", "expected"),
    [
        (fake_measurement(prompt_tokens=6000), ErrorCode.INPUT_BUDGET_EXCEEDED),
        (fake_measurement(model_key="other-model"), ErrorCode.INPUT_BUDGET_UNVERIFIED),
        (
            fake_measurement(actual_context_tokens=4096, prompt_tokens=3500),
            ErrorCode.INPUT_BUDGET_EXCEEDED,
        ),
    ],
)
def test_unverified_or_over_budget_counter_result_blocks_http(
    measurement: P2TokenBudgetMeasurement,
    expected: ErrorCode,
) -> None:
    calls: list[object] = []
    provider = make_provider(
        lambda *args: calls.append(args),
        token_budget_checker=FakeTokenBudgetChecker(measurement),
    )
    provider.start()

    with pytest.raises(LMStudioProviderError) as raised:
        asyncio.run(provider.generate(make_prompt()))
    assert raised.value.code is expected
    assert calls == []


def test_token_counter_timeout_and_artifact_change_are_distinct_and_block_http() -> None:
    for error, expected in [
        (P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_TIMEOUT), ErrorCode.INPUT_BUDGET_UNVERIFIED),
        (P2TokenBudgetError(P2TokenBudgetFailure.ARTIFACT_BINDING_CHANGED), ErrorCode.ARTIFACT_BINDING_CHANGED),
    ]:
        calls: list[object] = []
        provider = make_provider(
            lambda *args: calls.append(args),
            token_budget_checker=FakeTokenBudgetChecker(error),
        )
        provider.start()
        with pytest.raises(LMStudioProviderError) as raised:
            asyncio.run(provider.generate(make_prompt()))
        assert raised.value.code is expected
        assert calls == []


def test_cancellation_keeps_gate_until_token_counter_worker_finishes() -> None:
    entered = threading.Event()
    release = threading.Event()
    calls: list[object] = []

    class BlockingChecker:
        def measure(self, request: Any) -> P2TokenBudgetMeasurement:
            entered.set()
            if not release.wait(3):
                raise TimeoutError()
            return fake_measurement()

    provider = make_provider(
        lambda *args: calls.append(args) or _TransportResult(200, completion()),
        token_budget_checker=BlockingChecker(),
    )
    provider.start()

    async def exercise() -> None:
        first = asyncio.create_task(provider.generate(make_prompt()))
        assert await asyncio.to_thread(entered.wait, 1)
        first.cancel()
        await asyncio.sleep(0)
        second = asyncio.create_task(provider.generate(make_prompt()))
        await asyncio.sleep(0)
        assert calls == []
        assert not first.done()
        release.set()
        with pytest.raises(LMStudioProviderCancelled):
            await asyncio.wait_for(first, 2)
        assert await asyncio.wait_for(second, 2) == '{"kind":"answer"}'

    asyncio.run(exercise())
    assert len(calls) == 1


def test_http_completion_error_classes_are_distinct() -> None:
    cases = [
        (completion("", "stop"), ErrorCode.EMPTY_CONTENT),
        (completion("ignored", "length"), ErrorCode.LENGTH),
        (b"{", ErrorCode.JSON_ERROR),
        (b"[]", ErrorCode.PARSER_ERROR),
        (completion("x" * 20), ErrorCode.OVERSIZE),
    ]
    for body, expected in cases:
        provider = make_provider(
            lambda *args, body=body: _TransportResult(200, body),
            max_content_bytes=8,
        )
        provider.start()
        with pytest.raises(LMStudioProviderError) as raised:
            asyncio.run(provider.generate(make_prompt()))
        assert raised.value.code is expected
        assert provider.health().status == "unavailable"


def test_failed_completion_after_success_clears_provider_ready_health() -> None:
    responses = iter((
        _TransportResult(200, completion()),
        _TransportResult(200, completion("", "stop")),
    ))
    provider = make_provider(lambda *args: next(responses))
    provider.start()

    asyncio.run(provider.generate(make_prompt()))
    assert provider.health().status == "ready"
    with pytest.raises(LMStudioProviderError) as raised:
        asyncio.run(provider.generate(make_prompt()))

    assert raised.value.code is ErrorCode.EMPTY_CONTENT
    assert provider.health().status == "unavailable"
    assert provider.health().reason == "last_call_failed"


def test_http_status_and_transport_failures_are_distinct_and_never_retried() -> None:
    calls = 0

    def busy(*args: Any):
        nonlocal calls
        calls += 1
        return _TransportResult(429, b"")

    provider = make_provider(busy)
    provider.start()
    with pytest.raises(LMStudioProviderError) as busy_error:
        asyncio.run(provider.generate(make_prompt()))
    assert busy_error.value.code is ErrorCode.HTTP_BUSY
    assert busy_error.value.http_status == 429
    assert calls == 1

    for exception, expected in [
        (OSError("private transport detail"), ErrorCode.OFFLINE),
        (TimeoutError(), ErrorCode.TIMEOUT),
    ]:
        provider = make_provider(lambda *args, exception=exception: (_ for _ in ()).throw(exception))
        provider.start()
        with pytest.raises(LMStudioProviderError) as raised:
            asyncio.run(provider.generate(make_prompt()))
        assert raised.value.code is expected
        assert str(raised.value) == expected.value


def test_input_oversize_and_endpoint_validation_fail_closed() -> None:
    provider = make_provider(
        lambda *args: _TransportResult(200, completion()),
        max_prompt_bytes=256,
    )
    provider.start()
    oversized = P2Envelope(
        context=make_prompt().context.model_copy(update={"input_text": "x" * 600}),
        repair_feedback=None,
    )
    with pytest.raises(LMStudioProviderError) as raised:
        asyncio.run(provider.generate(oversized))
    assert raised.value.code is ErrorCode.INPUT_OVERSIZE

    for endpoint in (
        "https://127.0.0.1:1234/v1/chat/completions",
        "http://example.com/v1/chat/completions",
        "http://127.0.0.1:1234/v1/models",
        "http://127.0.0.1:1234/v1/chat/completions?redirect=1",
    ):
        with pytest.raises(ValueError):
            LMStudioOpenAIConfig(model_key="fixture-model", endpoint_url=endpoint)

    with pytest.raises(ValueError):
        LMStudioOpenAIConfig(model_key="fixture-model", max_concurrency=2)


def test_cancellation_keeps_gate_until_real_transport_finishes() -> None:
    entered = threading.Event()
    release = threading.Event()
    lock = threading.Lock()
    calls = 0

    def blocking_transport(*args: Any):
        nonlocal calls
        with lock:
            calls += 1
            current = calls
        if current == 1:
            entered.set()
            if not release.wait(3):
                raise TimeoutError()
        return _TransportResult(200, completion())

    provider = make_provider(blocking_transport, max_concurrency=1)
    provider.start()

    async def exercise() -> None:
        first = asyncio.create_task(provider.generate(make_prompt()))
        assert await asyncio.to_thread(entered.wait, 1)
        first.cancel()
        await asyncio.sleep(0)
        assert not first.done()

        second = asyncio.create_task(provider.generate(make_prompt()))
        await asyncio.sleep(0)
        with lock:
            assert calls == 1
        assert not second.done()

        release.set()
        with pytest.raises(LMStudioProviderCancelled):
            await asyncio.wait_for(first, 2)
        assert await asyncio.wait_for(second, 2) == '{"kind":"answer"}'

    asyncio.run(exercise())
    assert calls == 2


def test_start_restart_and_close_health_are_local_state_only() -> None:
    calls: list[object] = []
    provider = make_provider(lambda *args: calls.append(args))
    provider.start()
    provider.close()

    assert provider.health().reason == "closed"
    assert calls == []


def test_close_while_waiting_for_gate_prevents_late_request_dispatch() -> None:
    entered = threading.Event()
    release = threading.Event()
    lock = threading.Lock()
    calls = 0

    def blocking_transport(*args: Any):
        nonlocal calls
        with lock:
            calls += 1
        entered.set()
        if not release.wait(3):
            raise TimeoutError()
        return _TransportResult(200, completion())

    provider = make_provider(blocking_transport)
    provider.start()

    async def exercise() -> None:
        first = asyncio.create_task(provider.generate(make_prompt()))
        assert await asyncio.to_thread(entered.wait, 1)
        queued = asyncio.create_task(provider.generate(make_prompt()))
        await asyncio.sleep(0)
        provider.close()
        release.set()

        assert await asyncio.wait_for(first, 2) == '{"kind":"answer"}'
        with pytest.raises(LMStudioProviderError) as raised:
            await asyncio.wait_for(queued, 2)
        assert raised.value.code is ErrorCode.CLOSED

    asyncio.run(exercise())
    assert calls == 1


@pytest.mark.parametrize("slow_part", ["headers", "body"])
def test_local_http_stub_obeys_one_total_deadline(slow_part: str) -> None:
    class SlowResponseHandler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            headers: list[bytes] = []
            while True:
                line = self.rfile.readline()
                if not line:
                    return
                headers.append(line)
                if line == b"\r\n":
                    break
            if slow_part == "headers":
                response = b"HTTP/1.1 200 OK\r\nX-Slow: " + b"x" * 32 + b"\r\n\r\n"
                for byte in response:
                    try:
                        self.request.sendall(bytes((byte,)))
                    except OSError:
                        return
                    time.sleep(0.02)
                return
            self.request.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n"
            )
            time.sleep(0.12)
            try:
                self.request.sendall(b"a")
                time.sleep(0.12)
                self.request.sendall(b"b")
            except OSError:
                return

    class LocalStubServer(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    server = LocalStubServer(("127.0.0.1", 0), SlowResponseHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    endpoint = f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions"
    provider = LMStudioOpenAIProvider(
        LMStudioOpenAIConfig(
            model_key="local-stub",
            enabled=True,
            endpoint_url=endpoint,
            request_timeout_seconds=0.2,
        ),
        token_budget_checker=FakeTokenBudgetChecker(
            fake_measurement(
                model_key="local-stub",
                api_host=f"http://127.0.0.1:{server.server_address[1]}",
            ),
        ),
    )
    provider.start()
    started_at = time.monotonic()
    try:
        with pytest.raises(LMStudioProviderError) as raised:
            asyncio.run(provider.generate(make_prompt()))
        elapsed = time.monotonic() - started_at
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=1)

    assert raised.value.code is ErrorCode.TIMEOUT
    assert elapsed < 1.0
    assert provider.health().status == "unavailable"
