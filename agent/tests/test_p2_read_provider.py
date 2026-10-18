from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

import pytest

from agent.app import p2_read_contracts as c
from agent.app.p2_model_provider import (
    LMStudioOpenAIConfig,
    LMStudioOpenAIProvider,
    LMStudioProviderCancelled,
    LMStudioProviderError,
    LMStudioProviderErrorCode as ErrorCode,
    _TransportResult,
)
from agent.app.p2_read_prompt import P2_ENDPOINT_URL, P2PromptBuildConfig, build_p2_request
from agent.app.p2_read_provider import P2ReadProvider
from agent.app.p2_token_budget import P2TokenBudgetMeasurement


MODEL = "fixture-local-model"
REF_PRINCIPAL = "ref_" + "A" * 22
REF_TURN = "ref_" + "B" * 22


def make_context() -> c.P2ModelContext:
    return c.P2ModelContext(
        profile_id=c.P2_CANDIDATE_PROFILE_ID,
        versions=c.P2_VERSIONS,
        context_version="provider-cpu-context-v1",
        generation=1,
        input_text="用一句话说明今天的天气常识。",
        trusted_intent=c.P2TrustedIntent(
            authority="server",
            classification="non_business",
            requires_authoritative_evidence=False,
            source_input_seq=0,
            classifier_version="cpu-fixture-v1",
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
        classifier_version="cpu-fixture-v1",
    )


def completion(content: str) -> bytes:
    return json.dumps({
        "choices": [{
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": content},
        }],
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class FakeCounter:
    def __init__(self, *, input_tokens: int = 600, block: bool = False) -> None:
        self.input_tokens = input_tokens
        self.requests: list[Any] = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.block = block

    def measure(self, request: Any) -> P2TokenBudgetMeasurement:
        self.requests.append(request)
        self.started.set()
        if self.block and not self.release.wait(5):
            raise TimeoutError("CPU fixture counter was not released")
        return P2TokenBudgetMeasurement(
            model_key=request.model_key,
            api_host=request.api_host,
            artifact_path="fixture/model.gguf",
            artifact_sha256="d" * 64,
            actual_context_tokens=8192,
            prompt_tokens=self.input_tokens,
            response_format_tokens=100,
            safety_margin_tokens=512,
            budgeted_input_tokens=self.input_tokens + 100 + 512,
            max_input_tokens=6144,
            requested_output_tokens=request.max_output_tokens,
            max_output_tokens=768,
        )


def make_provider(
    transport: Any,
    *,
    checker: FakeCounter | None = None,
    enabled: bool = True,
    endpoint_url: str = P2_ENDPOINT_URL,
) -> P2ReadProvider:
    legacy = LMStudioOpenAIProvider(
        LMStudioOpenAIConfig(
            model_key=MODEL,
            enabled=enabled,
            endpoint_url=endpoint_url,
            temperature=0.0,
            max_output_tokens=768,
            max_concurrency=1,
        ),
        transport=transport,
        token_budget_checker=checker,
    )
    candidate = P2ReadProvider(legacy)
    candidate.start()
    return candidate


def prepared(endpoint_url: str = P2_ENDPOINT_URL):
    context = make_context()
    request = build_p2_request(
        context,
        config=P2PromptBuildConfig(model_id=MODEL, endpoint_url=endpoint_url),
    )
    return context, request


def test_exact_body_flows_through_counter_http_and_candidate_parser() -> None:
    content = json.dumps({
        "kind": "answer", "basis": "non_business_general",
        "text": "CPU fake response.", "citations": [],
    }, ensure_ascii=False, separators=(",", ":"))
    posted: list[tuple[str, bytes]] = []
    checker = FakeCounter()

    def fake_transport(url: str, body: bytes, headers: Any, timeout: float, max_bytes: int):
        posted.append((url, body))
        return _TransportResult(200, completion(content))

    context, request = prepared()
    provider = make_provider(fake_transport, checker=checker)
    raw = asyncio.run(provider.generate(context, request))
    decision = c.parse_p2_decision(raw, make_intent_context())

    assert decision.kind == "answer"
    assert decision.text == "CPU fake response."
    assert len(checker.requests) == 1
    assert len(posted) == 1
    url, body = posted[0]
    counter_request = checker.requests[0]
    payload = json.loads(body)
    assert url == P2_ENDPOINT_URL
    assert body == request.body_bytes
    assert counter_request.model_key == payload["model"] == MODEL
    assert counter_request.max_output_tokens == payload["max_tokens"] == 768
    assert [
        {"role": item.role, "content": item.content}
        for item in counter_request.messages
    ] == payload["messages"]
    assert json.loads(counter_request.response_format.payload_json) == payload["response_format"]


def test_docker_host_endpoint_uses_same_normalized_origin_and_exact_prepared_body() -> None:
    endpoint = "http://host.docker.internal:1234/v1/chat/completions"
    content = json.dumps({
        "kind": "answer", "basis": "non_business_general",
        "text": "CPU fake response.", "citations": [],
    }, ensure_ascii=False, separators=(",", ":"))
    posted: list[tuple[str, bytes]] = []
    checker = FakeCounter()

    def fake_transport(url: str, body: bytes, headers: Any, timeout: float, max_bytes: int):
        posted.append((url, body))
        return _TransportResult(200, completion(content))

    context, request = prepared(endpoint)
    provider = make_provider(fake_transport, checker=checker, endpoint_url=endpoint)
    raw = asyncio.run(provider.generate(context, request))
    decision = c.parse_p2_decision(raw, make_intent_context())

    assert decision.kind == "answer"
    assert len(checker.requests) == 1
    assert posted == [(endpoint, request.body_bytes)]
    counted = checker.requests[0]
    body = json.loads(request.body_bytes)
    assert counted.api_host == "http://host.docker.internal:1234"
    assert counted.model_key == body["model"] == MODEL
    assert counted.max_output_tokens == body["max_tokens"] == 768
    assert [{"role": item.role, "content": item.content} for item in counted.messages] == body["messages"]
    assert json.loads(counted.response_format.payload_json) == body["response_format"]


def test_endpoint_or_model_mismatch_fails_before_counter_and_dispatch() -> None:
    endpoint = "http://host.docker.internal:1234/v1/chat/completions"
    context, request = prepared(endpoint)
    checker = FakeCounter()
    dispatches: list[bytes] = []
    provider = make_provider(
        lambda _url, body, *_args: (dispatches.append(body) or _TransportResult(200, completion("{}"))),
        checker=checker,
    )

    with pytest.raises(LMStudioProviderError) as endpoint_mismatch:
        asyncio.run(provider.generate(context, request))
    assert endpoint_mismatch.value.code is ErrorCode.INVALID_PROMPT
    assert checker.requests == []
    assert dispatches == []

    wrong_model_request = build_p2_request(
        context,
        config=P2PromptBuildConfig(model_id="other-model", endpoint_url=P2_ENDPOINT_URL),
    )
    with pytest.raises(LMStudioProviderError) as model_mismatch:
        asyncio.run(provider.generate(context, wrong_model_request))
    assert model_mismatch.value.code is ErrorCode.INVALID_PROMPT
    assert checker.requests == []
    assert dispatches == []


def test_tampered_prepared_or_context_fails_before_counter_and_dispatch() -> None:
    dispatches: list[bytes] = []
    checker = FakeCounter()
    provider = make_provider(
        lambda _url, body, *_args: (dispatches.append(body) or _TransportResult(200, completion("{}"))),
        checker=checker,
    )
    context, request = prepared()
    tampered_request = request.model_copy(update={"request_sha256": "e" * 64})
    with pytest.raises(LMStudioProviderError) as bad_hash:
        asyncio.run(provider.generate(context, tampered_request))
    assert bad_hash.value.code is ErrorCode.INVALID_PROMPT

    altered_context = context.model_copy(update={"input_text": "替换后的上下文。"})
    with pytest.raises(LMStudioProviderError) as mismatch:
        asyncio.run(provider.generate(altered_context, request))
    assert mismatch.value.code is ErrorCode.INVALID_PROMPT
    assert checker.requests == []
    assert dispatches == []


def test_budget_refusal_and_missing_counter_never_dispatch() -> None:
    context, request = prepared()
    dispatches: list[bytes] = []
    too_large = FakeCounter(input_tokens=6000)
    provider = make_provider(
        lambda _url, body, *_args: (dispatches.append(body) or _TransportResult(200, completion("{}"))),
        checker=too_large,
    )
    with pytest.raises(LMStudioProviderError) as over_budget:
        asyncio.run(provider.generate(context, request))
    assert over_budget.value.code is ErrorCode.INPUT_BUDGET_EXCEEDED
    assert len(too_large.requests) == 1
    assert dispatches == []

    no_counter = make_provider(
        lambda _url, body, *_args: (dispatches.append(body) or _TransportResult(200, completion("{}"))),
    )
    with pytest.raises(LMStudioProviderError) as unverified:
        asyncio.run(no_counter.generate(context, request))
    assert unverified.value.code is ErrorCode.INPUT_BUDGET_UNVERIFIED
    assert dispatches == []


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (_TransportResult(429, b"{}"), ErrorCode.HTTP_BUSY),
        (ConnectionError("fixture offline"), ErrorCode.OFFLINE),
    ],
)
def test_busy_and_offline_errors_are_classified_without_retry(result: Any, expected: ErrorCode) -> None:
    calls: list[bytes] = []
    checker = FakeCounter()

    def transport(_url: str, body: bytes, *_args: Any):
        calls.append(body)
        if isinstance(result, BaseException):
            raise result
        return result

    context, request = prepared()
    provider = make_provider(transport, checker=checker)
    with pytest.raises(LMStudioProviderError) as raised:
        asyncio.run(provider.generate(context, request))
    assert raised.value.code is expected
    assert len(calls) == 1
    assert len(checker.requests) == 1


def test_close_while_counter_is_busy_prevents_late_http_dispatch() -> None:
    checker = FakeCounter(block=True)
    calls: list[bytes] = []
    provider = make_provider(
        lambda _url, body, *_args: (calls.append(body) or _TransportResult(200, completion("{}"))),
        checker=checker,
    )
    context, request = prepared()

    async def scenario() -> None:
        task = asyncio.create_task(provider.generate(context, request))
        assert await asyncio.to_thread(checker.started.wait, 2)
        provider.close()
        checker.release.set()
        with pytest.raises(LMStudioProviderError) as closed:
            await task
        assert closed.value.code is ErrorCode.CLOSED

    asyncio.run(scenario())
    assert len(checker.requests) == 1
    assert calls == []


def test_cancel_during_counter_drains_worker_before_return_and_never_dispatches() -> None:
    checker = FakeCounter(block=True)
    calls: list[bytes] = []
    provider = make_provider(
        lambda _url, body, *_args: (calls.append(body) or _TransportResult(200, completion("{}"))),
        checker=checker,
    )
    context, request = prepared()

    async def scenario() -> None:
        task = asyncio.create_task(provider.generate(context, request))
        assert await asyncio.to_thread(checker.started.wait, 2)
        task.cancel()
        checker.release.set()
        with pytest.raises(LMStudioProviderCancelled):
            await task

    asyncio.run(scenario())
    assert len(checker.requests) == 1
    assert calls == []


def test_candidate_accepts_localhost_and_rejects_non_candidate_wire_configuration() -> None:
    localhost_provider = LMStudioOpenAIProvider(
        LMStudioOpenAIConfig(model_key=MODEL, endpoint_url="http://localhost:1234/v1/chat/completions"),
        transport=lambda *_args: _TransportResult(200, completion("{}")),
        token_budget_checker=FakeCounter(),
    )
    candidate = P2ReadProvider(localhost_provider)
    assert candidate._endpoint_url == "http://localhost:1234/v1/chat/completions"

    provider = LMStudioOpenAIProvider(
        LMStudioOpenAIConfig(
            model_key=MODEL,
            endpoint_url="http://localhost:1234/v1/chat/completions",
            max_output_tokens=512,
        ),
        transport=lambda *_args: _TransportResult(200, completion("{}")),
        token_budget_checker=FakeCounter(),
    )
    with pytest.raises(ValueError, match="local P2 candidate wire profile"):
        P2ReadProvider(provider)
