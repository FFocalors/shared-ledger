from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json

from jsonschema.validators import validator_for
import pytest
from pydantic import ValidationError

from agent.app import p2_read_contracts as c
from agent.app import p2_read_prompt as p


REF_ACTIVITY = "ref_" + "A" * 22
REF_EXPENSE = "ref_" + "C" * 22
REF_PARTICIPANT = "ref_" + "D" * 22
REF_QUERY = "ref_" + "G" * 22
REF_RESULT = "ref_" + "H" * 22
REF_CRITERIA = "ref_" + "I" * 22
REF_SOURCE = "ref_" + "J" * 22
REF_NEXT = "ref_" + "L" * 22
QEV = "qev_" + "M" * 22
DIGEST = "a" * 64
NOW = datetime(2026, 10, 14, 7, 0, tzinfo=timezone.utc)
INPUT_TEXT = "请查活动 00000000-0000-0000-0000-000000000123；保留 Café 原文。\n下一行不做规范化。"


def _context() -> c.P2ModelContext:
    scope = c.P2Scope(
        scope_kind="activity", scope_ref=REF_ACTIVITY,
        activity_ref=REF_ACTIVITY, ledger_unit_ref=None,
    )
    summary = c.P2PageSummary(
        pages_seen=1, has_more=True, truncated=True, source_query_complete=True,
        model_projection_complete=False, range_contiguous=True, stable_total_verified=True,
        source_version_fenced=True, unique_items_verified=True, expected_total=17,
    )
    evidence = c.P2QueryEvidence(
        profile_id=c.P2_CANDIDATE_PROFILE_ID, versions=c.P2_VERSIONS,
        query_evidence_ref=QEV, query_ref=REF_QUERY, result_ref=REF_RESULT,
        operation=c.P2ReadOperation.EXPENSES, criteria_ref=REF_CRITERIA,
        criteria_digest=DIGEST, normalized_criteria_digest=DIGEST,
        backend_criteria_stage="scope_only", source_kind="expenses", source_ref=REF_SOURCE,
        source_version="synthetic-expense-source-v1", observed_at=NOW, simulation=False,
        returned_count=17, matched_count=17, source_total=17, matched_total=17,
        page_count=1, query_zero_classification="nonzero", source_query_complete=True,
        model_projection_complete=False, matching_fact_refs=(REF_EXPENSE,),
        financial_versions=(c.P2FinancialVersion(activity_ref=REF_ACTIVITY, financial_version=42),),
        page=summary, query_digest=DIGEST, body_digest=DIGEST, projection_digest=DIGEST,
    )
    payer = c.ParticipantAllocationFact(
        participant_ref=REF_PARTICIPANT, role="payer", signed_original_amount="12.3400",
        original_currency="CNY", signed_base_amount="12.3", base_currency="CNY",
    )
    fact = c.ExpenseFact(
        fact_kind="expense", expense_ref=REF_EXPENSE, scope_ref=REF_ACTIVITY,
        occurred_at=NOW, signed_original_amount="12.3400", original_currency="CNY",
        signed_base_amount="12.3", base_currency="CNY", payer_split_lines=(payer,),
        expense_version=3, financial_version=42, query_evidence_ref=QEV,
    )
    return c.P2ModelContext(
        profile_id=c.P2_CANDIDATE_PROFILE_ID, versions=c.P2_VERSIONS,
        context_version="synthetic-context-v1", generation=2, input_text=INPUT_TEXT,
        trusted_intent=c.P2TrustedIntent(
            authority="server", classification="factual_business",
            requires_authoritative_evidence=True, source_input_seq=11,
            classifier_version="synthetic-classifier-v1",
        ),
        scope_authorization=c.P2ScopeAuthorization(
            status="verified", scope=scope, authorization_receipt_ref="auth_" + "N" * 22,
        ),
        guard=c.P2DecisionGuard(
            source_free_business_answer_allowed=False,
            allowed_decision_kinds=("answer", "clarify", "read"),
            allowed_read_operations=(c.P2ReadOperation.EXPENSES,),
            fresh_receipt_refs=(QEV,),
            proposal_clarification_required=None,
            allowed_proposal_operations=(),
        ),
        query_evidence=(evidence,),
        continuations=(c.P2ContinuationHint(
            query_evidence_ref=QEV, query_ref=REF_QUERY, next_page_ref=REF_NEXT,
        ),),
        facts=(fact,),
        recent_messages=(
            c.P2RecentMessage(seq=1, role="user", text=INPUT_TEXT, generation=2),
            c.P2RecentMessage(seq=2, role="assistant", text="我先核对这笔记录。", generation=2),
        ),
    )


def _config() -> p.P2PromptBuildConfig:
    return p.P2PromptBuildConfig(model_id="synthetic-local-model")


def _body(prepared: p.P2PreparedRequest) -> dict:
    return json.loads(prepared.body_bytes)


def _walk_keys(value):
    if isinstance(value, dict):
        yield from value.keys()
        for child in value.values():
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def test_build_is_deterministic_and_preserves_typed_facts_unicode_and_page_state():
    context = _context()
    first = p.build_p2_request(context, config=_config())
    second = p.build_p2_request(context, config=_config())
    assert first.body_bytes == second.body_bytes
    assert first.request_sha256 == sha256(first.body_bytes).hexdigest()
    assert first.context_sha256 == second.context_sha256
    assert first.schema_sha256 == second.schema_sha256
    assert first.endpoint_url == "http://127.0.0.1:1234/v1/chat/completions"

    body = _body(first)
    assert body["model"] == "synthetic-local-model"
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 768
    assert body["n"] == 1
    assert body["stream"] is False
    assert "tools" not in body and "reasoning" not in body and "reasoning_effort" not in body


    assert body["messages"][0] == {"role": "system", "content": p.SYSTEM_INSTRUCTIONS}

    prefix, separator, encoded_context = body["messages"][1]["content"].partition("\n")
    assert separator == "\n" and "结构校验" in prefix
    visible = json.loads(encoded_context)
    assert visible["input_text"] == INPUT_TEXT
    assert visible["recent_messages"][0]["text"] == INPUT_TEXT
    assert visible["scope_authorization"]["scope"]["scope_ref"] == REF_ACTIVITY
    assert visible["facts"][0]["signed_original_amount"] == "12.3400"
    assert visible["facts"][0]["original_currency"] == "CNY"
    assert visible["facts"][0]["financial_version"] == 42
    assert visible["query_evidence"][0]["source_version"] == "synthetic-expense-source-v1"
    assert visible["query_evidence"][0]["observed_at"] == "2026-10-14T07:00:00Z"
    assert visible["query_evidence"][0]["page"]["source_query_complete"] is True
    assert visible["query_evidence"][0]["page"]["model_projection_complete"] is False
    assert visible["query_evidence"][0]["page"]["has_more"] is True
    assert visible["continuations"] == [{
        "query_evidence_ref": QEV, "query_ref": REF_QUERY, "next_page_ref": REF_NEXT,
    }]
    assert visible["profile_id"] == c.P2_CANDIDATE_PROFILE_ID
    assert not {"source_authorization_grant", "access_token", "private_intent_context"}.intersection(
        _walk_keys(visible)
    )
    # The UUID-like sequence remains ordinary user text; it is not promoted to a typed ref.
    assert visible["input_text"].count("00000000-0000-0000-0000-000000000123") == 1
    assert visible["facts"][0]["expense_ref"] == REF_EXPENSE


def test_configured_endpoint_is_strictly_bound_without_changing_body_bytes():
    context = _context()
    loopback = p.build_p2_request(context, config=_config())
    docker_config = p.P2PromptBuildConfig(
        model_id="synthetic-local-model",
        endpoint_url="HTTP://HOST.DOCKER.INTERNAL:1234/v1/chat/completions",
    )
    docker = p.build_p2_request(context, config=docker_config)

    assert docker.config.endpoint_url == "http://host.docker.internal:1234/v1/chat/completions"
    assert docker.endpoint_url == docker.config.endpoint_url
    assert docker.body_bytes == loopback.body_bytes
    assert docker.request_sha256 == loopback.request_sha256
    assert docker.prepared_fingerprint_sha256 != loopback.prepared_fingerprint_sha256
    assert docker.versions == loopback.versions == c.P2_VERSIONS

    endpoint_only_tamper = loopback.model_copy(update={
        "endpoint_url": docker.endpoint_url,
    })
    with pytest.raises(ValidationError):
        p.P2PreparedRequest.model_validate(
            endpoint_only_tamper.model_dump(mode="python", by_alias=True, exclude_none=False),
            strict=True,
        )

    endpoint_and_config_tamper = loopback.model_copy(update={
        "endpoint_url": docker.endpoint_url,
        "config": docker.config,
    })
    with pytest.raises(ValidationError, match="fingerprint"):
        p.P2PreparedRequest.model_validate(
            endpoint_and_config_tamper.model_dump(mode="python", by_alias=True, exclude_none=False),
            strict=True,
        )


def test_json_and_mapping_inputs_use_the_same_strict_context_wire_validation():
    context = _context()
    dumped = context.model_dump(mode="json", by_alias=True, exclude_none=False)
    raw = json.dumps(dumped, ensure_ascii=False, separators=(",", ":"))
    expected = p.build_p2_request(context, config=_config()).body_bytes
    assert p.build_p2_request(raw, config=_config()).body_bytes == expected
    assert p.build_p2_request(raw.encode("utf-8"), config=_config()).body_bytes == expected
    assert p.build_p2_request(json.loads(raw), config=_config()).body_bytes == expected

    with pytest.raises(p.P2PromptInputError, match="duplicate JSON object key"):
        p.build_p2_request('{"profile_id":"first","profile_id":"second"}', config=_config())

    extra_private = dict(dumped)
    extra_private["source_authorization_grant"] = {"grant_ref": "private"}
    with pytest.raises(p.P2PromptInputError, match="strict P2ModelContext"):
        p.build_p2_request(extra_private, config=_config())

    wrong_versions = dict(dumped)
    wrong_versions["versions"] = dict(dumped["versions"], api="2.2.0")
    with pytest.raises(p.P2PromptInputError, match="strict P2ModelContext"):
        p.build_p2_request(wrong_versions, config=_config())

    wrong_typed_instance = context.model_copy(update={"input_text": ""})
    with pytest.raises(p.P2PromptInputError, match="strict P2ModelContext"):
        p.build_p2_request(wrong_typed_instance, config=_config())


def test_schema_keeps_the_direct_four_semantic_and_seven_read_decision_union():
    prepared = p.build_p2_request(_context(), config=_config())
    body = _body(prepared)
    response_format = body["response_format"]
    assert response_format["type"] == "json_schema"
    json_schema = response_format["json_schema"]
    assert json_schema["strict"] is True
    assert json_schema["name"] == p.P2_DECISION_SCHEMA_NAME
    schema = json_schema["schema"]
    assert schema["type"] == "object"
    assert "properties" not in schema  # the decision remains the direct top-level union
    branch_refs = {branch["$ref"].rsplit("/", 1)[-1] for branch in schema["anyOf"]}
    assert branch_refs == {
        "P2AnswerDecision", "P2ClarifyDecision", "P2ReadQueryRequest",
        "P2ReadContinueRequest", "P2ProposalRecognition",
    }
    query = schema["$defs"]["P2ReadQueryRequest"]
    continuation = schema["$defs"]["P2ReadContinueRequest"]
    assert query["properties"]["message_type"]["const"] == "query_request"
    assert continuation["properties"]["message_type"]["const"] == "continue_request"
    criteria_union = query["properties"]["criteria"]
    criteria_kinds = {
        schema["$defs"][branch["$ref"].rsplit("/", 1)[-1]]["properties"]["kind"]["const"]
        for branch in criteria_union["anyOf"]
    }
    assert criteria_kinds == {
        "activities", "expenses", "debts", "refund_events", "prepayment_accounts",
        "prepayment_usages", "prepayment_return_events",
    }

    def assert_strict_objects(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            assert "oneOf" not in node and "discriminator" not in node
            for child in node.values():
                assert_strict_objects(child)
        elif isinstance(node, list):
            for child in node:
                assert_strict_objects(child)

    assert_strict_objects(schema)
    validator_for(schema).check_schema(schema)

    query_payload = {
        "kind": "read", "message_type": "query_request",
        "profile_id": c.P2_CANDIDATE_PROFILE_ID,
        "versions": c.P2_VERSIONS.model_dump(), "operation": "read.expenses",
        "criteria": {
            "kind": "expenses", "activity_ref": REF_ACTIVITY, "from_date": None,
            "to_date": None, "participant_ref": None, "title_contains": None,
        },
        "scope": {
            "scope_kind": "activity", "scope_ref": REF_ACTIVITY,
            "activity_ref": REF_ACTIVITY, "ledger_unit_ref": None,
        },
    }
    continue_payload = {
        "kind": "read", "message_type": "continue_request",
        "profile_id": c.P2_CANDIDATE_PROFILE_ID,
        "versions": c.P2_VERSIONS.model_dump(), "query_ref": REF_QUERY,
        "next_page_ref": REF_NEXT,
    }
    validator_for(schema)(schema).validate(query_payload)
    validator_for(schema)(schema).validate(continue_payload)


def test_exact_count_receipt_gates_dispatch_without_changing_request_bytes():
    prepared = p.build_p2_request(_context(), config=_config())
    receipt = p.P2ExactTokenCountReceipt(
        request_sha256=prepared.request_sha256, input_tokens=6144,
        counter_id="synthetic-exact-counter", counter_version="cpu-fake-v1", exact=True,
    )
    approval = p.require_exact_token_budget(prepared, receipt)
    assert approval.request_sha256 == prepared.request_sha256
    assert approval.input_tokens == 6144
    assert approval.output_reserve == 768 and approval.schema_margin == 512
    assert sha256(prepared.body_bytes).hexdigest() == prepared.request_sha256

    dispatched: list[bytes] = []

    def fake_dispatch(candidate, count_receipt):
        p.require_exact_token_budget(candidate, count_receipt)
        dispatched.append(candidate.body_bytes)

    too_large = receipt.model_copy(update={"input_tokens": 6145})
    with pytest.raises(p.P2RequestBudgetError, match="6144-token input budget"):
        fake_dispatch(prepared, too_large)
    with pytest.raises(p.P2RequestBudgetError, match="not bound"):
        fake_dispatch(prepared, receipt.model_copy(update={"request_sha256": "b" * 64}))
    with pytest.raises(p.P2RequestBudgetError, match="required before dispatch"):
        fake_dispatch(prepared, None)
    assert dispatched == []
    assert isinstance(prepared.body_bytes, bytes)
    assert sha256(prepared.body_bytes).hexdigest() == prepared.request_sha256

    with pytest.raises(ValidationError):
        p.P2ExactTokenCountReceipt.model_validate({
            "request_sha256": prepared.request_sha256, "input_tokens": True,
            "counter_id": "fake", "counter_version": "v1", "exact": True,
        })
    with pytest.raises(ValidationError):
        p.P2ExactTokenCountReceipt.model_validate({
            "request_sha256": prepared.request_sha256, "input_tokens": 1,
            "counter_id": "fake", "counter_version": "v1", "exact": False,
        })


def test_fixed_config_rejects_budget_drift_and_unknown_fields():
    with pytest.raises(ValidationError):
        p.P2PromptBuildConfig(model_id="synthetic-local-model", input_budget=4096)
    with pytest.raises(ValidationError):
        p.P2PromptBuildConfig(model_id="synthetic-local-model", fallback_model="backup")
    with pytest.raises(ValidationError):
        p.P2PromptBuildConfig(model_id="synthetic-local-model", client_profile="selected-by-user")


def test_model_copy_config_bypass_is_revalidated_before_request_build():
    config = _config().model_copy(update={"parallel_requests": 2, "temperature": 0.7})
    with pytest.raises(p.P2PromptInputError, match="strict P2PromptBuildConfig"):
        p.build_p2_request(_context(), config=config)


def test_model_copy_prepared_and_count_receipts_cannot_bypass_budget_checks():
    prepared = p.build_p2_request(_context(), config=_config())
    exact_receipt = p.P2ExactTokenCountReceipt(
        request_sha256=prepared.request_sha256, input_tokens=100,
        counter_id="synthetic-exact-counter", counter_version="cpu-fake-v1", exact=True,
    )

    body_bytes = prepared.body_bytes + b" "
    forged_prepared = prepared.model_copy(update={
        "body_bytes": body_bytes,
        "request_sha256": sha256(body_bytes).hexdigest(),
    })
    forged_count = exact_receipt.model_copy(update={"request_sha256": forged_prepared.request_sha256})
    with pytest.raises(p.P2RequestBudgetError, match="prepared request failed strict validation"):
        p.require_exact_token_budget(forged_prepared, forged_count)

    forged_config = _config().model_copy(update={"parallel_requests": 2, "temperature": 0.7})
    forged_prepared_config = prepared.model_copy(update={"config": forged_config})
    with pytest.raises(p.P2RequestBudgetError, match="prepared request failed strict validation"):
        p.require_exact_token_budget(forged_prepared_config, exact_receipt)

    false_exact = exact_receipt.model_copy(update={"exact": False})
    with pytest.raises(p.P2RequestBudgetError, match="counter receipt failed strict validation"):
        p.require_exact_token_budget(prepared, false_exact)
    for non_integer_count in (True, 100.0):
        forged_count = exact_receipt.model_copy(update={"input_tokens": non_integer_count})
        with pytest.raises(p.P2RequestBudgetError, match="counter receipt failed strict validation"):
            p.require_exact_token_budget(prepared, forged_count)
