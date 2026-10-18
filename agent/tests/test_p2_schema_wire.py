from __future__ import annotations

import asyncio
import copy
import json
from datetime import datetime, timezone
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError

from app import contracts as c
from app.harness import ModelPrompt
from app.p2_harness import P2PromptEnvelope
from app.p2_model_provider import (
    LMStudioOpenAIConfig,
    LMStudioOpenAIProvider,
    _TransportResult,
    _build_request,
)
from app.p2_schema_wire import (
    P2SchemaWireSelection,
    P2_SCHEMA_PROMPT_VERSION,
    P2_SCHEMA_PROVIDER_VERSION,
    P2_SCHEMA_RENDERER_VERSION,
    P2_WIRE_CONFIG_VERSION,
    render_p2_wire_schema,
)
from app.p2_token_budget import P2TokenBudgetMeasurement


def selection() -> P2SchemaWireSelection:
    return P2SchemaWireSelection()


def selected_config(**overrides: Any) -> LMStudioOpenAIConfig:
    values: dict[str, Any] = {
        "model_key": "synthetic-model",
        "enabled": True,
        "provider_version": P2_SCHEMA_PROVIDER_VERSION,
        "prompt_version": P2_SCHEMA_PROMPT_VERSION,
        "schema_wire_selection": selection(),
    }
    values.update(overrides)
    return LMStudioOpenAIConfig(**values)


def semantic_fixtures() -> tuple[dict[str, Any], ...]:
    """Fresh synthetic positives: all semantic branches and each operation."""

    return (
        {"kind": "answer", "basis": "conversation", "text": "synthetic answer", "citations": []},
        {"kind": "clarify", "prompt": "synthetic clarification", "missing_slots": ["title"]},
        {
            "kind": "read",
            "operation": "read.activities",
            "criteria": {"kind": "activities", "status": "active", "name_contains": None},
        },
        {
            "kind": "read",
            "operation": "read.expenses",
            "criteria": {"kind": "expenses", "activity_ref": "activity_1", "participant_ref": None},
        },
        {
            "kind": "read",
            "operation": "read.debts",
            "criteria": {"kind": "debts", "activity_ref": "activity_1", "currency": "USD"},
        },
        {
            "kind": "propose",
            "operation": "expense.create",
            "fields": {
                "kind": "expense.create",
                "ledger_unit_ref": "ledger_unit_1",
                "title": "synthetic lunch",
                "original_amount": "12.50",
                "original_currency": "USD",
                "payment_allocations": [{"participant_ref": "participant_1", "amount": "12.50"}],
                "split": {"mode": "equal", "participant_refs": ["participant_1"]},
            },
        },
        {
            "kind": "propose",
            "operation": "expense.update",
            "fields": {"kind": "expense.update", "expense_ref": "expense_1", "title": "synthetic edit"},
        },
        {
            "kind": "propose",
            "operation": "expense.presentation.update",
            "fields": {
                "kind": "expense.presentation.update",
                "expense_ref": "expense_1",
                "icon_key": "synthetic_icon",
            },
        },
    )


def schema_negative_fixtures() -> tuple[dict[str, Any], ...]:
    """Synthetic cases rejected by JSON Schema (required, closed, enum, ref, bounds, union)."""

    return (
        {"kind": "answer", "basis": "conversation", "text": "missing citations"},
        {"kind": "answer", "basis": "conversation", "text": "extra", "citations": [], "surprise": True},
        {"kind": "answer", "basis": "unknown", "text": "wrong enum", "citations": []},
        {
            "kind": "propose",
            "operation": "expense.create",
            "fields": {
                "kind": "expense.create",
                "ledger_unit_ref": "ledger_unit_1",
                "title": "bad currency pattern",
                "original_amount": "10.00",
                "original_currency": "US",
                "payment_allocations": [{"participant_ref": "participant_1", "amount": "10.00"}],
                "split": {"mode": "equal", "participant_refs": ["participant_1"]},
            },
        },
        {
            "kind": "propose",
            "operation": "expense.create",
            "fields": {
                "kind": "expense.create",
                "ledger_unit_ref": "ledger_unit_1",
                "title": "x" * 121,
                "original_amount": "10.00",
                "original_currency": "USD",
                "payment_allocations": [{"participant_ref": "participant_1", "amount": "10.00"}],
                "split": {"mode": "equal", "participant_refs": ["participant_1"]},
            },
        },
        {
            "kind": "propose",
            "operation": "expense.create",
            "fields": {
                "kind": "expense.create",
                "ledger_unit_ref": "ledger_unit_1",
                "title": "bad amount pattern",
                "original_amount": "01.00",
                "original_currency": "USD",
                "payment_allocations": [{"participant_ref": "participant_1", "amount": "01.00"}],
                "split": {"mode": "equal", "participant_refs": ["participant_1"]},
            },
        },
        {
            "kind": "propose",
            "operation": "expense.create",
            "fields": {
                "kind": "expense.create",
                "ledger_unit_ref": "ledger_unit_1",
                "title": "bad reference",
                "original_amount": "10.00",
                "original_currency": "USD",
                "payment_allocations": [{"participant_ref": "participant_unknown", "amount": "10.00"}],
                "split": {"mode": "equal", "participant_refs": ["participant_1"]},
            },
        },
        {"kind": "not-a-branch", "payload": {}},
    )


def schema_pair() -> tuple[dict[str, Any], dict[str, Any]]:
    canonical = c.SEMANTIC_DECISION_ADAPTER.json_schema()
    original = copy.deepcopy(canonical)
    projected = render_p2_wire_schema(
        canonical,
        selection(),
        provider_version=P2_SCHEMA_PROVIDER_VERSION,
        prompt_version=P2_SCHEMA_PROMPT_VERSION,
    )
    assert canonical == original
    return canonical, projected


def test_title_projection_preserves_schema_structure_and_json_schema_decisions() -> None:
    canonical, projected = schema_pair()
    Draft202012Validator.check_schema(canonical)
    Draft202012Validator.check_schema(projected)
    canonical_validator = Draft202012Validator(canonical)
    projected_validator = Draft202012Validator(projected)

    positives = semantic_fixtures()
    negatives = schema_negative_fixtures()
    assert len(positives) == 8
    assert len(negatives) == 8
    for fixture in (*positives, *negatives):
        assert canonical_validator.is_valid(fixture) == projected_validator.is_valid(fixture)
    assert all(canonical_validator.is_valid(item) for item in positives)
    assert all(not canonical_validator.is_valid(item) for item in negatives)

    assert canonical["$defs"].keys() == projected["$defs"].keys()
    assert all("$ref" in str(value) for value in (
        projected["$defs"]["ExpenseCreateIntent"],
        projected["$defs"]["ProposeDecision"],
    ))
    # Validate references, including nested intent refs, through both schemas.
    for fixture in positives:
        assert projected_validator.is_valid(fixture)

    adapter: TypeAdapter[Any] = c.SEMANTIC_DECISION_ADAPTER
    for fixture in positives:
        adapter.validate_python(fixture)
    for fixture in negatives:
        with pytest.raises(ValidationError):
            adapter.validate_python(fixture)


def test_pydantic_cross_field_negative_is_distinct_from_schema_parity() -> None:
    canonical, projected = schema_pair()
    fixture = {
        "kind": "read",
        "operation": "read.activities",
        "criteria": {"kind": "debts", "activity_ref": "activity_1"},
    }
    assert Draft202012Validator(canonical).is_valid(fixture)
    assert Draft202012Validator(projected).is_valid(fixture)
    with pytest.raises(ValidationError):
        c.SEMANTIC_DECISION_ADAPTER.validate_python(fixture)


def test_title_keys_unknown_payload_and_non_schema_wrapper_are_preserved() -> None:
    schema = {
        "title": "root schema title",
        "type": "object",
        "$defs": {
            "title": {
                "title": "definition annotation",
                "type": "object",
                "properties": {"title": {"title": "business field annotation", "type": "string"}},
            },
        },
        "properties": {
            "title": {"title": "expense title annotation", "type": "string"},
        },
        "default": {"title": "default payload data"},
        "x-private-extension": {"title": "unknown extension payload"},
        "custom-unknown-keyword": {"title": "unknown keyword payload"},
    }
    wrapper = {
        "title": "response format wrapper title",
        "name": "synthetic-wrapper",
        "schema": schema,
    }
    original = copy.deepcopy(wrapper)
    projected = render_p2_wire_schema(
        wrapper["schema"],
        selection(),
        provider_version=P2_SCHEMA_PROVIDER_VERSION,
        prompt_version=P2_SCHEMA_PROMPT_VERSION,
    )
    projected_wrapper = {**wrapper, "schema": projected}

    assert wrapper == original
    assert projected_wrapper["title"] == "response format wrapper title"
    assert "title" not in projected
    assert "title" in projected["$defs"]
    assert "title" not in projected["$defs"]["title"]
    assert "title" in projected["$defs"]["title"]["properties"]
    assert "title" not in projected["$defs"]["title"]["properties"]["title"]
    assert "title" in projected["properties"]
    assert "title" not in projected["properties"]["title"]
    assert projected["default"] == {"title": "default payload data"}
    assert projected["x-private-extension"] == {"title": "unknown extension payload"}
    assert projected["custom-unknown-keyword"] == {"title": "unknown keyword payload"}


def test_known_schema_keywords_are_projected_without_touching_refs_or_other_values() -> None:
    schema = {
        "title": "root",
        "$ref": "#/$defs/target",
        "$defs": {"target": {"title": "target", "type": "string"}},
        "properties": {"a": {"title": "prop", "type": "string"}},
        "patternProperties": {"^b$": {"title": "pattern", "type": "number"}},
        "dependentSchemas": {"a": {"title": "dependent", "required": ["b"]}},
        "allOf": [{"title": "all", "type": "object"}],
        "anyOf": [{"title": "any", "type": "string"}],
        "oneOf": [{"title": "one", "type": "integer"}],
        "prefixItems": [{"title": "prefix", "type": "string"}],
        "items": [{"title": "tuple item", "type": "number"}],
        "contains": {"title": "contains", "type": "string"},
        "propertyNames": {"title": "property names", "type": "string"},
        "additionalProperties": {"title": "additional", "type": "boolean"},
        "not": {"title": "not", "type": "null"},
        "if": {"title": "if", "type": "string"},
        "then": {"title": "then", "minLength": 1},
        "else": {"title": "else", "maxLength": 4},
        "dependencies": {
            "schemaDependency": {"title": "dependency schema", "type": "object"},
            "propertyDependency": ["other"],
        },
        "required": ["a"],
        "pattern": "^keep$",
        "minimum": 2,
    }
    projected = render_p2_wire_schema(
        schema,
        selection(),
        provider_version=P2_SCHEMA_PROVIDER_VERSION,
        prompt_version=P2_SCHEMA_PROMPT_VERSION,
    )
    assert projected["$ref"] == schema["$ref"]
    assert projected["required"] == schema["required"]
    assert projected["pattern"] == schema["pattern"]
    assert projected["minimum"] == schema["minimum"]
    assert projected["dependencies"]["propertyDependency"] == ["other"]
    assert "title" not in projected["dependencies"]["schemaDependency"]
    assert "title" not in projected["properties"]["a"]
    assert "title" not in projected["items"][0]


@pytest.mark.parametrize(
    "bad_selection",
    [
        P2SchemaWireSelection(wire_config_version="future"),  # type: ignore[arg-type]
        P2SchemaWireSelection(envelope_kind="p1_model_prompt"),  # type: ignore[arg-type]
        P2SchemaWireSelection(renderer_version="future-renderer"),  # type: ignore[arg-type]
        object(),
    ],
)
def test_invalid_selected_tuple_fails_closed(bad_selection: object) -> None:
    with pytest.raises(ValueError):
        selected_config(schema_wire_selection=bad_selection)


@pytest.mark.parametrize(
    "override",
    [
        {"provider_version": "mixed-provider"},
        {"prompt_version": "mixed-prompt"},
    ],
)
def test_mixed_selected_provider_or_prompt_version_fails_closed(override: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        selected_config(**override)


def test_canonical_default_keeps_custom_labels_and_private_builder_default() -> None:
    config = LMStudioOpenAIConfig(
        model_key="synthetic-model",
        provider_version="custom-canonical-provider-v9",
        prompt_version="custom-canonical-prompt-v7",
    )
    body = _build_request(config, b"{}")
    request = json.loads(body)
    assert request["response_format"]["json_schema"]["schema"] == c.SEMANTIC_DECISION_ADAPTER.json_schema()
    assert "Provider version: custom-canonical-provider-v9" in request["messages"][0]["content"]
    assert "Prompt version: custom-canonical-prompt-v7" in request["messages"][0]["content"]
    assert P2_WIRE_CONFIG_VERSION == "p2-wire-config-v2"
    assert P2_SCHEMA_RENDERER_VERSION == "p2-json-schema-title-strip-v1"


def test_new_optional_config_field_preserves_existing_positional_api_token_slot() -> None:
    config = LMStudioOpenAIConfig(
        "synthetic-model",
        True,
        "http://127.0.0.1:1234/v1/chat/completions",
        "custom-provider",
        "custom-prompt",
        0.0,
        768,
        30.0,
        49_152,
        65_536,
        32_768,
        16_384,
        1,
        True,
        "local-synthetic-token",
    )
    assert config.api_token == "local-synthetic-token"
    assert config.schema_wire_selection is None


def _synthetic_context() -> c.ModelContext:
    return c.ModelContext(
        context_version=1,
        input_text="synthetic P2 input",
        verified_scope={"kind": "none", "permissions": []},
        recent_messages=[],
        pending_slots=[],
        bound_references=[],
        read_results=[],
        policy_evidence=[],
        available_permissions=[],
    )


def _synthetic_p2_envelope() -> P2PromptEnvelope:
    return P2PromptEnvelope(
        context=_synthetic_context(),
        repair_feedback=None,
        provenance=[],
        reference_labels=[],
        expense_supplements=[],
    )


def _synthetic_completion() -> bytes:
    return json.dumps({
        "choices": [{
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": '{"kind":"answer"}'},
        }],
    }).encode("utf-8")


class _RecordingChecker:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    def measure(self, request: Any) -> P2TokenBudgetMeasurement:
        self.requests.append(request)
        return P2TokenBudgetMeasurement(
            model_key=request.model_key,
            api_host=request.api_host,
            artifact_path="synthetic/model.gguf",
            artifact_sha256="a" * 64,
            actual_context_tokens=8192,
            prompt_tokens=400,
            response_format_tokens=100,
            safety_margin_tokens=512,
            budgeted_input_tokens=1012,
            max_input_tokens=6144,
            requested_output_tokens=request.max_output_tokens,
            max_output_tokens=768,
        )


def test_only_actual_p2_envelope_uses_projection_and_budget_matches_dispatched_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.p2_model_provider as provider_module

    checker = _RecordingChecker()
    dispatched: list[bytes] = []
    real_builder = provider_module._build_request
    builds: list[tuple[type[object], P2SchemaWireSelection | None]] = []

    def counted_builder(
        config: LMStudioOpenAIConfig,
        envelope: bytes,
        schema_wire_selection: P2SchemaWireSelection | None = None,
    ) -> bytes:
        builds.append((type(envelope), schema_wire_selection))  # envelope is serialized bytes here
        return real_builder(config, envelope, schema_wire_selection)

    def transport(endpoint: str, body: bytes, headers: dict[str, str], timeout: float, cap: int) -> _TransportResult:
        dispatched.append(body)
        return _TransportResult(200, _synthetic_completion())

    monkeypatch.setattr(provider_module, "_build_request", counted_builder)
    provider = LMStudioOpenAIProvider(
        selected_config(),
        transport=transport,
        token_budget_checker=checker,
    )
    provider.start()
    asyncio.run(provider.generate(_synthetic_p2_envelope()))
    # Even with the selected P2 tuple configured, the base P1 ModelPrompt uses
    # the canonical response schema.
    asyncio.run(provider.generate(ModelPrompt(context=_synthetic_context(), repair_feedback=None)))

    assert len(builds) == 2
    assert builds[0][1] == selection()
    assert builds[1][1] is None
    assert len(dispatched) == len(checker.requests) == 2
    canonical_schema = c.SEMANTIC_DECISION_ADAPTER.json_schema()
    first_schema = json.loads(dispatched[0])["response_format"]["json_schema"]["schema"]
    second_schema = json.loads(dispatched[1])["response_format"]["json_schema"]["schema"]
    assert first_schema != canonical_schema
    assert second_schema == canonical_schema

    for body, budget_request in zip(dispatched, checker.requests, strict=True):
        wire_response_format = json.loads(body)["response_format"]
        exact_compact_response_format = json.dumps(
            wire_response_format,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        assert budget_request.response_format is not None
        assert budget_request.response_format.payload_json == exact_compact_response_format


def test_selected_tuple_versions_are_independent_from_canonical_prompt_default() -> None:
    assert LMStudioOpenAIConfig(model_key="synthetic-model").prompt_version == "shared-ledger-p2-routing-r2"
    configured = selected_config()
    assert configured.prompt_version == P2_SCHEMA_PROMPT_VERSION
    assert configured.provider_version == P2_SCHEMA_PROVIDER_VERSION
    # The source instruction string is not version-specific prose; selection
    # changes candidate identity only.
    from app.p2_prompt_policy import P2_SYSTEM_INSTRUCTIONS

    assert isinstance(P2_SYSTEM_INSTRUCTIONS, str) and P2_SYSTEM_INSTRUCTIONS
