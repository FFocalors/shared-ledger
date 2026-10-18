from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import Field

from app import contracts as c
from app.harness import ModelPrompt
from app.p2_model_provider import (
    LMStudioOpenAIConfig,
    LMStudioOpenAIProvider,
    LMStudioProviderError,
    LMStudioProviderErrorCode as ErrorCode,
    LMStudioTransportObservation,
    _TransportResult,
    _build_request,
    _serialize_envelope,
)
from app.p2_token_budget import P2TokenBudgetMeasurement


class P2Envelope(ModelPrompt):
    provenance: list[dict[str, Any]] = Field(default_factory=list, max_length=16)


def _prompt() -> ModelPrompt:
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
    return ModelPrompt(context=context, repair_feedback=None)


def _completion(content: str = '{"kind":"answer"}', finish_reason: str = "stop") -> bytes:
    return json.dumps({
        "choices": [{
            "finish_reason": finish_reason,
            "message": {"role": "assistant", "content": content},
        }],
    }).encode("utf-8")


def _measurement(*, model_key: str = "hook-fixture-model") -> P2TokenBudgetMeasurement:
    prompt_tokens = 100
    response_format_tokens = 20
    safety_margin_tokens = 512
    return P2TokenBudgetMeasurement(
        model_key=model_key,
        api_host="http://127.0.0.1:1234",
        artifact_path="fixture/model.gguf",
        artifact_sha256="a" * 64,
        actual_context_tokens=8192,
        prompt_tokens=prompt_tokens,
        response_format_tokens=response_format_tokens,
        safety_margin_tokens=safety_margin_tokens,
        budgeted_input_tokens=prompt_tokens + response_format_tokens + safety_margin_tokens,
        max_input_tokens=6144,
        requested_output_tokens=768,
        max_output_tokens=768,
    )


class FakeChecker:
    def __init__(
        self,
        measurement: P2TokenBudgetMeasurement | Exception | None = None,
        *,
        ordered_events: list[str] | None = None,
    ) -> None:
        self.measurement = measurement or _measurement()
        self.requests: list[Any] = []
        self.events: list[str] = []
        self.ordered_events = ordered_events

    def measure(self, request: Any) -> P2TokenBudgetMeasurement:
        self.events.append("counter")
        if self.ordered_events is not None:
            self.ordered_events.append("counter")
        self.requests.append(request)
        if isinstance(self.measurement, Exception):
            raise self.measurement
        return self.measurement


def _provider(
    transport: Any,
    checker: FakeChecker,
) -> LMStudioOpenAIProvider:
    provider = LMStudioOpenAIProvider(
        LMStudioOpenAIConfig(model_key="hook-fixture-model", enabled=True),
        transport=transport,
        token_budget_checker=checker,
    )
    provider.start()
    return provider


def _body(provider: LMStudioOpenAIProvider) -> bytes:
    envelope = _serialize_envelope(_prompt())
    return _build_request(provider._config, envelope, None)


def test_dispatch_hook_brackets_exact_count_body_and_one_transport() -> None:
    events: list[str] = []
    checker = FakeChecker(ordered_events=events)
    transport_seen: list[bytes] = []
    observations: list[LMStudioTransportObservation] = []

    def transport(_url: str, body: bytes, *_args: Any) -> _TransportResult:
        events.append("transport")
        transport_seen.append(body)
        return _TransportResult(200, _completion())

    provider = _provider(transport, checker)
    body = _body(provider)

    def before_dispatch(body_sha256: str, measurement: P2TokenBudgetMeasurement) -> None:
        events.append("before_dispatch")
        assert body_sha256 == hashlib.sha256(body).hexdigest()
        assert measurement is checker.measurement

    def observe(response: LMStudioTransportObservation) -> None:
        events.append("observer")
        observations.append(response)

    # The internal hooks exercise the same bound-body method used by the public
    # provider path; neither hook rebuilds or substitutes the serialized body.
    result = asyncio.run(provider._generate_bound_body(
        body,
        expected_body_sha256=hashlib.sha256(body).hexdigest(),
        before_dispatch=before_dispatch,
        on_transport_result=observe,
    ))

    assert result == '{"kind":"answer"}'
    assert events == ["counter", "before_dispatch", "transport", "observer"]
    assert checker.events == ["counter"]
    assert len(checker.requests) == len(transport_seen) == 1
    assert transport_seen[0] == body
    payload = json.loads(body)
    assert [{"role": m.role, "content": m.content} for m in checker.requests[0].messages] == payload["messages"]
    assert observations == [LMStudioTransportObservation(
        status=200,
        body_bytes=len(_completion()),
        body_sha256=hashlib.sha256(_completion()).hexdigest(),
        observed_at=observations[0].observed_at,
    )]
    assert observations[0].observed_at is not None
    assert observations[0].observed_at.tzinfo is timezone.utc
    assert {field for field in observations[0].__dataclass_fields__} == {
        "status", "body_bytes", "body_sha256", "observed_at",
    }
    with pytest.raises((AttributeError, TypeError)):
        observations[0].status = 500  # type: ignore[misc]
    provider.close()


def test_dispatch_hook_waits_for_successful_validated_counter() -> None:
    calls: list[bytes] = []
    hook_calls: list[str] = []
    checker = FakeChecker(_measurement(model_key="different-model"))
    provider = _provider(
        lambda _url, body, *_args: calls.append(body) or _TransportResult(200, _completion()),
        checker,
    )
    body = _body(provider)

    with pytest.raises(LMStudioProviderError) as raised:
        asyncio.run(provider._generate_bound_body(
            body,
            before_dispatch=lambda digest, _measurement: hook_calls.append(digest),
        ))
    assert raised.value.code is ErrorCode.INPUT_BUDGET_UNVERIFIED
    assert len(checker.requests) == 1
    assert hook_calls == []
    assert calls == []
    provider.close()


def test_bad_expected_body_hash_rejects_before_counter_hook_or_transport() -> None:
    calls: list[bytes] = []
    hook_calls: list[str] = []
    checker = FakeChecker()
    provider = _provider(
        lambda _url, body, *_args: calls.append(body) or _TransportResult(200, _completion()),
        checker,
    )
    body = _body(provider)

    with pytest.raises(LMStudioProviderError) as raised:
        asyncio.run(provider._generate_bound_body(
            body,
            expected_body_sha256="0" * 64,
            before_dispatch=lambda digest, _measurement: hook_calls.append(digest),
        ))
    assert raised.value.code is ErrorCode.INVALID_PROMPT
    assert checker.requests == []
    assert hook_calls == []
    assert calls == []
    provider.close()


def test_close_during_count_prevents_dispatch_hook_and_http() -> None:
    entered = threading.Event()
    release = threading.Event()
    hook_calls: list[str] = []
    transport_calls: list[bytes] = []

    class BlockingChecker:
        def measure(self, _request: Any) -> P2TokenBudgetMeasurement:
            entered.set()
            if not release.wait(2):
                raise TimeoutError()
            return _measurement()

    provider = _provider(
        lambda _url, body, *_args: transport_calls.append(body) or _TransportResult(200, _completion()),
        FakeChecker(),
    )
    provider._token_budget_checker = BlockingChecker()
    body = _body(provider)

    async def exercise() -> None:
        task = asyncio.create_task(provider._generate_bound_body(
            body,
            before_dispatch=lambda digest, _measurement: hook_calls.append(digest),
        ))
        assert await asyncio.to_thread(entered.wait, 1)
        provider.close()
        release.set()
        with pytest.raises(LMStudioProviderError) as raised:
            await asyncio.wait_for(task, 2)
        assert raised.value.code is ErrorCode.CLOSED

    asyncio.run(exercise())
    assert hook_calls == []
    assert transport_calls == []


def test_disabled_provider_does_not_count_hook_or_dispatch() -> None:
    checker = FakeChecker()
    calls: list[bytes] = []
    hook_calls: list[str] = []
    provider = LMStudioOpenAIProvider(
        LMStudioOpenAIConfig(model_key="hook-fixture-model", enabled=False),
        transport=lambda _url, body, *_args: calls.append(body) or _TransportResult(200, _completion()),
        token_budget_checker=checker,
    )
    provider.start()
    body = _body(provider)

    with pytest.raises(LMStudioProviderError) as raised:
        asyncio.run(provider._generate_bound_body(
            body,
            before_dispatch=lambda digest, _measurement: hook_calls.append(digest),
        ))
    assert raised.value.code is ErrorCode.DISABLED
    assert checker.requests == []
    assert hook_calls == []
    assert calls == []
    provider.close()


def test_dispatch_hook_failure_is_sanitized_and_never_dispatches_or_retries() -> None:
    calls: list[bytes] = []
    commits: list[str] = []
    checker = FakeChecker()
    provider = _provider(
        lambda _url, body, *_args: calls.append(body) or _TransportResult(200, _completion()),
        checker,
    )
    body = _body(provider)

    def commit_then_raise(body_sha256: str, _measurement: P2TokenBudgetMeasurement) -> None:
        commits.append(body_sha256)
        raise RuntimeError("sensitive-store-detail")

    with pytest.raises(LMStudioProviderError) as raised:
        asyncio.run(provider._generate_bound_body(
            body,
            before_dispatch=commit_then_raise,
        ))

    assert raised.value.code is ErrorCode.DISPATCH_HOOK_REJECTED
    assert str(raised.value) == ErrorCode.DISPATCH_HOOK_REJECTED.value
    assert "sensitive-store-detail" not in str(raised.value)
    assert len(commits) == 1
    assert commits[0] == hashlib.sha256(body).hexdigest()
    assert calls == []

    # The provider itself does not refund or retry a possibly committed Store
    # marker. It only releases its local gate; the caller must read durable state.
    assert asyncio.run(provider.generate(_prompt())) == '{"kind":"answer"}'
    assert len(calls) == 1
    provider.close()


def test_async_dispatch_hook_is_rejected_without_creating_an_http_worker() -> None:
    calls: list[bytes] = []
    checker = FakeChecker()
    provider = _provider(
        lambda _url, body, *_args: calls.append(body) or _TransportResult(200, _completion()),
        checker,
    )
    body = _body(provider)

    async def accidental_async_hook(_sha: str, _measurement: P2TokenBudgetMeasurement) -> None:
        return None

    with pytest.raises(LMStudioProviderError) as raised:
        asyncio.run(provider._generate_bound_body(body, before_dispatch=accidental_async_hook))
    assert raised.value.code is ErrorCode.DISPATCH_HOOK_REJECTED
    assert calls == []
    provider.close()


def test_dispatch_commit_then_worker_creation_failure_stays_unknown_and_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bytes] = []
    commits: list[str] = []
    checker = FakeChecker()
    provider = _provider(
        lambda _url, body, *_args: calls.append(body) or _TransportResult(200, _completion()),
        checker,
    )
    body = _body(provider)
    original_create_task = asyncio.create_task

    def fail_only_http_task(coro: Any, *, name: str | None = None):
        if name == "p2-lmstudio-openai-http":
            raise RuntimeError("private-event-loop-detail")
        return original_create_task(coro, name=name)

    monkeypatch.setattr("app.p2_model_provider.asyncio.create_task", fail_only_http_task)
    with pytest.raises(LMStudioProviderError) as raised:
        asyncio.run(provider._generate_bound_body(
            body,
            before_dispatch=lambda digest, _measurement: commits.append(digest),
        ))

    assert raised.value.code is ErrorCode.DISPATCH_WORKER_FAILED
    assert str(raised.value) == ErrorCode.DISPATCH_WORKER_FAILED.value
    assert "private-event-loop-detail" not in str(raised.value)
    assert commits == [hashlib.sha256(body).hexdigest()]
    assert calls == []
    provider.close()


def test_post_dispatch_cancel_drains_same_worker_before_successor_hook_or_http() -> None:
    transport_started = threading.Event()
    release_transport = threading.Event()
    attempts: list[bytes] = []
    checker = FakeChecker()
    provider = _provider(
        lambda _url, body, *_args: _blocking_transport(
            body, attempts, transport_started, release_transport,
        ),
        checker,
    )
    first_body = _body(provider)
    committed: list[str] = []
    second_started = asyncio.Event()
    second_body = first_body

    def before_dispatch(body_sha256: str, _measurement: P2TokenBudgetMeasurement) -> None:
        committed.append(body_sha256)

    async def exercise() -> None:
        first = asyncio.create_task(provider._generate_bound_body(
            first_body,
            before_dispatch=before_dispatch,
        ))
        assert await asyncio.to_thread(transport_started.wait, 1)
        first.cancel()
        await asyncio.sleep(0)
        assert not first.done()

        async def run_second() -> str:
            second_started.set()
            return await provider._generate_bound_body(
                second_body,
                before_dispatch=before_dispatch,
            )

        second = asyncio.create_task(run_second())
        await second_started.wait()
        assert not second.done()
        assert checker.requests == [checker.requests[0]]
        assert len(committed) == 1
        assert len(attempts) == 1

        release_transport.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(first, 2)
        assert await asyncio.wait_for(second, 2) == '{"kind":"answer"}'

    try:
        asyncio.run(exercise())
    finally:
        release_transport.set()
        provider.close()

    assert len(checker.requests) == 2
    assert len(committed) == 2
    assert committed == [hashlib.sha256(first_body).hexdigest()] * 2
    assert attempts == [first_body, second_body]


def _blocking_transport(
    body: bytes,
    attempts: list[bytes],
    started: threading.Event,
    release: threading.Event,
) -> _TransportResult:
    attempts.append(body)
    if len(attempts) == 1:
        started.set()
        if not release.wait(2):
            raise TimeoutError()
    return _TransportResult(200, _completion())


@pytest.mark.parametrize(
    ("status", "response", "expected_code"),
    [
        (429, b"{}", ErrorCode.HTTP_BUSY),
        (200, _completion("", "stop"), ErrorCode.EMPTY_CONTENT),
        (200, _completion("ignored", "length"), ErrorCode.LENGTH),
    ],
)
def test_observer_receives_safe_result_metadata_before_http_or_completion_failure(
    status: int,
    response: bytes,
    expected_code: ErrorCode,
) -> None:
    seen: list[LMStudioTransportObservation] = []
    provider = _provider(
        lambda *_args: _TransportResult(status, response),
        FakeChecker(),
    )
    body = _body(provider)

    with pytest.raises(LMStudioProviderError) as raised:
        asyncio.run(provider._generate_bound_body(
            body,
            on_transport_result=seen.append,
        ))

    assert raised.value.code is expected_code
    assert len(seen) == 1
    assert seen[0].status == status
    assert seen[0].body_bytes == len(response)
    assert seen[0].body_sha256 == hashlib.sha256(response).hexdigest()
    assert not hasattr(seen[0], "body")
    provider.close()


def test_oversized_response_is_rejected_before_safe_observer() -> None:
    seen: list[LMStudioTransportObservation] = []
    provider = _provider(
        lambda *_args: _TransportResult(200, b"x" * 40_000),
        FakeChecker(),
    )
    body = _body(provider)

    with pytest.raises(LMStudioProviderError) as raised:
        asyncio.run(provider._generate_bound_body(
            body,
            on_transport_result=seen.append,
        ))
    assert raised.value.code is ErrorCode.OVERSIZE
    assert seen == []
    provider.close()


def test_observer_failure_is_sanitized_and_never_returns_completion() -> None:
    provider = _provider(
        lambda *_args: _TransportResult(200, _completion()),
        FakeChecker(),
    )
    body = _body(provider)

    def fail_observer(_observation: LMStudioTransportObservation) -> None:
        raise RuntimeError("private-response-detail")

    with pytest.raises(LMStudioProviderError) as raised:
        asyncio.run(provider._generate_bound_body(body, on_transport_result=fail_observer))
    assert raised.value.code is ErrorCode.TRANSPORT_OBSERVER_FAILED
    assert str(raised.value) == ErrorCode.TRANSPORT_OBSERVER_FAILED.value
    assert "private-response-detail" not in str(raised.value)
    provider.close()


def test_transport_observation_rejects_untyped_or_naive_values() -> None:
    digest = hashlib.sha256(b"body").hexdigest()
    with pytest.raises(ValueError):
        LMStudioTransportObservation(status=True, body_bytes=4, body_sha256=digest)
    with pytest.raises(ValueError):
        LMStudioTransportObservation(status=200, body_bytes=True, body_sha256=digest)
    with pytest.raises(ValueError):
        LMStudioTransportObservation(status=200, body_bytes=4, body_sha256="A" * 64)
    with pytest.raises(ValueError):
        LMStudioTransportObservation(
            status=200, body_bytes=4, body_sha256=digest,
            observed_at=datetime(2026, 10, 14),
        )
