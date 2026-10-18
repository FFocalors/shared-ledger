from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from app import p2_read_contracts_v3 as c
from app.p2_read_prompt_v3 import build_p2_v3_request, p2_v3_decision_json_schema
from test_p2_read_prompt_provider_v3 import (
    ACTIVITY,
    NOW,
    QEV,
    _config,
    _expense_context_pair,
    _private_non_business,
    _public_non_business,
    ref,
)


def _reachable_definition_names(schema: dict[str, object]) -> set[str]:
    definitions = schema["$defs"]
    assert isinstance(definitions, dict)
    reachable: set[str] = set()

    def visit(node: object) -> None:
        if isinstance(node, dict):
            reference = node.get("$ref")
            if isinstance(reference, str) and reference.startswith("#/$defs/"):
                name = reference.removeprefix("#/$defs/")
                assert name in definitions
                if name not in reachable:
                    reachable.add(name)
                    visit(definitions[name])
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit({key: value for key, value in schema.items() if key != "$defs"})
    return reachable


def test_initial_activity_discovery_schema_contains_only_authorized_shapes() -> None:
    base_public = _public_non_business()
    public = base_public.model_copy(update={
        "input_text": "列出所有活动。",
        "trusted_intent": c.P2TrustedIntent(
            authority="server", classification="ambiguous", requires_authoritative_evidence=True,
            source_input_seq=5, classifier_version="fixture-policy-v1",
        ),
        "guard": c.P2DecisionGuard(
            source_free_business_answer_allowed=False,
            allowed_decision_kinds=("read",),
            allowed_read_operations=(c.P2ReadOperation.ACTIVITIES,),
            fresh_receipt_refs=(), proposal_clarification_required=None,
            allowed_proposal_operations=(),
        ),
    })
    private = _private_non_business().model_copy(update={"classification": "ambiguous"})

    prepared = build_p2_v3_request(public, private, config=_config())
    schema = json.loads(prepared.body_bytes)["response_format"]["json_schema"]["schema"]
    definitions = schema["$defs"]

    assert [item["$ref"] for item in schema["anyOf"]] == ["#/$defs/P2ReadQueryRequest"]
    assert definitions["P2ReadOperation"]["enum"] == ["read.activities"]
    assert definitions["P2ReadQueryRequest"]["properties"]["criteria"]["anyOf"] == [
        {"$ref": "#/$defs/ActivityCriteria"}
    ]
    assert definitions["P2ReadQueryRequest"]["properties"]["scope"]["anyOf"] == [
        {"type": "null"}
    ]
    assert set(definitions) == _reachable_definition_names(schema)
    assert "P2ReadContinueRequest" not in definitions
    assert "P2Scope" not in definitions

    # The context-free exporter remains the full public v3 decision schema.
    exported = p2_v3_decision_json_schema()
    assert len(exported["anyOf"]) == 5
    assert len(exported["$defs"]["P2ReadOperation"]["enum"]) == 7
    assert "P2ReadContinueRequest" in exported["$defs"]


def test_continuation_and_allowed_expense_query_remain_parseable() -> None:
    public, base_private = _expense_context_pair()
    evidence = public.query_evidence[0]
    paged_evidence = evidence.model_copy(update={
        "page": evidence.page.model_copy(update={
            "has_more": True,
            "model_projection_complete": False,
        }),
        "model_projection_complete": False,
    })
    next_page_ref = ref(91)
    public = public.model_copy(update={
        "guard": public.guard.model_copy(update={"fresh_receipt_refs": (QEV,)}),
        "query_evidence": (paged_evidence,),
        "continuations": (c.P2ContinuationHint(
            query_evidence_ref=QEV,
            query_ref=evidence.query_ref,
            next_page_ref=next_page_ref,
        ),),
    })

    criteria = c.ExpenseCriteria(
        kind="expenses", activity_ref=ACTIVITY, from_date=None, to_date=None,
        participant_ref=None, title_contains=None,
    )
    criteria_digest = c.p2_criteria_digest(criteria)
    expiry = datetime.now(timezone.utc) + timedelta(minutes=5)
    grant = c.P2SourceAuthorizationGrant(
        principal_ref=ref(700), owner_turn_ref=ref(701), generation=3, source_input_seq=5,
        input_digest="a" * 64, operation=c.P2ReadOperation.EXPENSES, scope=public.scope_authorization.scope,
        criteria_digest=criteria_digest, expires_at=expiry, grant_ref=ref(92),
    )
    receipt = c.P2FreshQueryEvidenceRef(
        query_evidence_ref=QEV, query_ref=evidence.query_ref,
        principal_ref=ref(700), owner_turn_ref=ref(701), generation=3, source_input_seq=5,
        input_digest="a" * 64, operation=c.P2ReadOperation.EXPENSES, scope_ref=ACTIVITY,
        criteria_digest=criteria_digest, observed_at=NOW, expires_at=expiry,
        next_page_ref=next_page_ref, page_index=0,
    )
    private = base_private.model_copy(update={
        "source_authorization_grant": grant,
        "fresh_receipt_refs": (receipt,),
    })

    prepared = build_p2_v3_request(public, private, config=_config())
    schema = json.loads(prepared.body_bytes)["response_format"]["json_schema"]["schema"]
    definitions = schema["$defs"]
    assert {item["$ref"] for item in schema["anyOf"]} == {
        "#/$defs/P2ReadQueryRequest", "#/$defs/P2ReadContinueRequest",
    }
    assert definitions["P2ReadOperation"]["enum"] == ["read.expenses"]
    assert definitions["P2ReadQueryRequest"]["properties"]["criteria"]["anyOf"] == [
        {"$ref": "#/$defs/ExpenseCriteria"}
    ]
    assert set(definitions) == _reachable_definition_names(schema)
    assert "query_ref" in definitions["P2ReadContinueRequest"]["properties"]
    assert "next_page_ref" in definitions["P2ReadContinueRequest"]["properties"]

    query = {
        "kind": "read", "message_type": "query_request",
        "profile_id": c.P2_V3_CANDIDATE_PROFILE_ID,
        "versions": c.P2_V3_VERSIONS.model_dump(mode="json"),
        "operation": "read.expenses",
        "criteria": criteria.model_dump(mode="json", exclude_none=False),
        "scope": public.scope_authorization.scope.model_dump(mode="json", exclude_none=False),
    }
    continuation = {
        "kind": "read", "message_type": "continue_request",
        "profile_id": c.P2_V3_CANDIDATE_PROFILE_ID,
        "versions": c.P2_V3_VERSIONS.model_dump(mode="json"),
        "query_ref": evidence.query_ref,
        "next_page_ref": next_page_ref,
    }
    assert isinstance(c.parse_p2_decision(json.dumps(query).encode(), private), c.P2ReadQueryRequest)
    assert isinstance(
        c.parse_p2_decision(json.dumps(continuation).encode(), private),
        c.P2ReadContinueRequest,
    )
