from __future__ import annotations

import json
import re
import asyncio

from app import contracts as c
from app.p2_harness import P2Harness
from app.p2_model_provider import (
    LMStudioOpenAIConfig,
    LMStudioOpenAIProvider,
    LMStudioProviderError,
    LMStudioProviderErrorCode,
    _TransportResult,
    _build_request,
)
from app.p2_prompt_policy import P2_PROMPT_VERSION, P2_SYSTEM_INSTRUCTIONS
from app.p2_token_budget import (
    P2TokenBudgetError,
    P2TokenBudgetFailure,
    P2TokenBudgetMeasurement,
)


def _measurement() -> P2TokenBudgetMeasurement:
    return P2TokenBudgetMeasurement(
        model_key="fixture-model",
        api_host="http://127.0.0.1:1234",
        artifact_path="fixture.gguf",
        artifact_sha256="a" * 64,
        actual_context_tokens=8192,
        prompt_tokens=100,
        response_format_tokens=3753,
        safety_margin_tokens=512,
        budgeted_input_tokens=4365,
        max_input_tokens=6144,
        requested_output_tokens=768,
        max_output_tokens=768,
        total_measurement_ms=1,
        artifact_hash_ms=0,
    )


def _typed_p2_prompt() -> c.ModelContext:
    return c.ModelContext(
        context_version=1,
        input_text="请解释普通对话和账本查询有什么区别。",
        verified_scope={"kind": "none", "permissions": []},
        recent_messages=[],
        pending_slots=[],
        bound_references=[],
        read_results=[],
        policy_evidence=[],
        available_permissions=[],
    )


def test_r2_policy_is_bounded_and_names_schema_routing_families() -> None:
    assert P2_PROMPT_VERSION == "shared-ledger-p2-routing-r2"
    for family in ("conversation", "grounded", "read.activities", "read.expenses", "read.debts", "propose", "clarify"):
        assert family in P2_SYSTEM_INSTRUCTIONS
    assert len(P2_SYSTEM_INSTRUCTIONS.encode("utf-8")) <= 4096


def test_r2_policy_has_no_fixture_ids_or_concrete_financial_examples() -> None:
    assert re.search(
        r"(?i)(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![0-9a-f])",
        P2_SYSTEM_INSTRUCTIONS,
    ) is None
    assert not re.search(r"(?<!\d)\d+\.\d{2}(?!\d)", P2_SYSTEM_INSTRUCTIONS)
    assert "Bearer " not in P2_SYSTEM_INSTRUCTIONS
    assert "read_result_" not in P2_SYSTEM_INSTRUCTIONS
    assert "expense_" not in P2_SYSTEM_INSTRUCTIONS


def test_provider_request_uses_r2_without_changing_schema_or_transport_defaults() -> None:
    config = LMStudioOpenAIConfig(model_key="fixture-model", enabled=True)
    request = json.loads(_build_request(config, b'{"context":{}}'))

    assert config.prompt_version == P2_PROMPT_VERSION
    assert config.endpoint_url == "http://127.0.0.1:1234/v1/chat/completions"
    assert config.temperature == 0
    assert config.max_output_tokens == 768
    assert config.max_concurrency == 1
    assert request["messages"][0]["content"].startswith(P2_SYSTEM_INSTRUCTIONS)
    assert request["messages"][0]["content"].endswith(
        f"Provider version: {config.provider_version}\nPrompt version: {P2_PROMPT_VERSION}"
    )
    assert request["response_format"]["json_schema"]["schema"] == c.SEMANTIC_DECISION_ADAPTER.json_schema()
    assert request["max_tokens"] == 768
    assert request["stream"] is False


def test_typed_harness_envelope_is_the_exact_counted_input_before_http() -> None:
    context = _typed_p2_prompt()
    prompt = P2Harness.build_envelope(context)
    counted = []
    transported = []

    class RecordingChecker:
        def measure(self, request):
            counted.append(request)
            return _measurement()

    def transport(endpoint, body, headers, timeout, cap):
        transported.append((endpoint, json.loads(body)))
        return _TransportResult(200, json.dumps({
            "choices": [{
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "{}"},
            }],
        }).encode())

    provider = LMStudioOpenAIProvider(
        LMStudioOpenAIConfig(model_key="fixture-model", enabled=True),
        transport=transport,
        token_budget_checker=RecordingChecker(),
    )
    provider.start()
    asyncio.run(provider.generate(prompt))

    assert len(counted) == len(transported) == 1
    counted_user = json.loads(
        counted[0].messages[1].content.split(" (JSON data):\n", 1)[1]
    )
    posted = transported[0][1]
    assert counted[0].messages[0].content.startswith(P2_SYSTEM_INSTRUCTIONS)
    assert counted[0].messages[1].content == posted["messages"][1]["content"]
    assert counted_user["context"]["input_text"] == context.input_text
    assert counted_user["provenance"] == []
    assert counted_user["expense_supplements"] == []
    assert posted["response_format"]["json_schema"]["schema"] == c.SEMANTIC_DECISION_ADAPTER.json_schema()


def test_typed_envelope_budget_failure_blocks_http_dispatch() -> None:
    transported = []

    class FailingChecker:
        def measure(self, request):
            raise P2TokenBudgetError(P2TokenBudgetFailure.COUNTER_TIMEOUT)

    provider = LMStudioOpenAIProvider(
        LMStudioOpenAIConfig(model_key="fixture-model", enabled=True),
        transport=lambda *args: transported.append(args),
        token_budget_checker=FailingChecker(),
    )
    provider.start()

    try:
        asyncio.run(provider.generate(P2Harness.build_envelope(_typed_p2_prompt())))
    except LMStudioProviderError as error:
        assert error.code is LMStudioProviderErrorCode.INPUT_BUDGET_UNVERIFIED
    else:
        raise AssertionError("budget failure unexpectedly allowed provider output")
    assert transported == []
