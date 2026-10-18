from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest
from pydantic import ValidationError

from app import p2_read_contracts_v3 as c


NOW = datetime.now(timezone.utc)
VERSIONS = {
    "api": "3.0.0",
    "semantic": "2.1.0",
    "operations": "2.1.0",
    "trajectory": "2.0.0",
}


def ref(number: int) -> str:
    return "ref_" + f"{number:022d}"


def qev(number: int) -> str:
    return "qev_" + f"{number:022d}"


def authref(number: int) -> str:
    return "auth_" + f"{number:022d}"


def digest(letter: str = "a") -> str:
    return letter * 64


def scope_dto(*, activity: str | None = None, ledger_unit: str | None = None) -> c.P2Scope:
    activity = activity or ref(1)
    if ledger_unit is None:
        return c.P2Scope(
            scope_kind="activity", scope_ref=activity, activity_ref=activity, ledger_unit_ref=None
        )
    return c.P2Scope(
        scope_kind="ledger_unit", scope_ref=ledger_unit, activity_ref=activity, ledger_unit_ref=ledger_unit
    )


def label_dto(
    *, entity_ref: str, kind: str, scope_ref: str, source_kind: str, version: int = 8,
    updated_at: datetime | None = None, display_name: str = "张三 🧾"
) -> c.P2EntityDisplayLabel:
    is_activity = kind == "activity"
    return c.P2EntityDisplayLabel(
        entity_ref=entity_ref,
        entity_kind=kind,
        scope_ref=scope_ref,
        display_name=display_name,
        source_kind=source_kind,
        observed_at=NOW,
        scope_financial_version=version,
        source_financial_version=version if is_activity else None,
        source_row_updated_at=None if is_activity else (updated_at or NOW - timedelta(minutes=1)),
        source_receipt_ref=ref(900 + int(entity_ref[-2:])),
    )


def context_dto(
    *, classification: str = "factual_business", status: str = "verified",
    scope: c.P2Scope | None = None, kinds: tuple[str, ...] | None = None,
    operations: tuple[c.P2ReadOperation, ...] | None = None,
    source_free: bool = False, requires_evidence: bool = True,
    proposal_required: bool | None = None, proposals: tuple[c.P2ProposalOperation, ...] = (),
    actor: c.P2CurrentActorBinding | None = None,
    labels: tuple[c.P2EntityDisplayLabel, ...] = (),
    evidence: tuple[c.P2QueryEvidence, ...] = (), facts: tuple[c.P2Fact, ...] = (),
    fresh_refs: tuple[str, ...] = (), continuations: tuple[c.P2ContinuationHint, ...] = (),
    pending: tuple[c.P2PendingClarificationProjection, ...] = (),
) -> c.P2ModelContext:
    selected_scope = scope if scope is not None else (scope_dto() if status == "verified" else None)
    if kinds is None:
        if pending:
            kinds = ("clarify",)
        elif classification == "non_business":
            kinds = ("answer",)
        elif classification == "proposal_intent":
            kinds = ("propose",)
        else:
            kinds = ("read",)
    if operations is None:
        operations = (
            (c.P2ReadOperation.ACTIVITIES,) if status != "verified"
            else (c.P2ReadOperation.EXPENSES,)
        ) if "read" in kinds else ()
    return c.P2ModelContext(
        profile_id=c.P2_V3_CANDIDATE_PROFILE_ID,
        versions=c.P2_V3_VERSIONS,
        context_version="p2-context-v3-test",
        generation=3,
        input_text="我欠谁？🙂",
        trusted_intent=c.P2TrustedIntent(
            authority="server", classification=classification,
            requires_authoritative_evidence=requires_evidence, source_input_seq=5,
            classifier_version="test-policy-v1",
        ),
        scope_authorization=c.P2ScopeAuthorization(
            status=status,
            scope=selected_scope if status == "verified" else None,
            authorization_receipt_ref=authref(1) if status == "verified" else None,
        ),
        guard=c.P2DecisionGuard(
            source_free_business_answer_allowed=source_free,
            allowed_decision_kinds=kinds,
            allowed_read_operations=operations,
            fresh_receipt_refs=fresh_refs,
            proposal_clarification_required=proposal_required,
            allowed_proposal_operations=proposals,
        ),
        pending_clarifications=pending,
        query_evidence=evidence,
        continuations=continuations,
        facts=facts,
        recent_messages=(),
        current_actor=actor,
        source_labels=labels,
    )


def evidence_dto(
    *, operation: c.P2ReadOperation, evidence_ref: str, fact_ref: str,
    scope_ref: str | None = None, has_more: bool = False, index: int = 0,
    financial_versions: tuple[c.P2FinancialVersion, ...] | None = None,
    matching_fact_refs: tuple[str, ...] | None = None,
) -> c.P2QueryEvidence:
    complete = not has_more
    expected_total = 1
    return c.P2QueryEvidence(
        profile_id=c.P2_V3_CANDIDATE_PROFILE_ID,
        versions=c.P2_V3_VERSIONS,
        query_evidence_ref=evidence_ref,
        query_ref=ref(200 + index),
        result_ref=ref(300 + index),
        operation=operation,
        criteria_ref=ref(400 + index),
        criteria_digest=digest("b"),
        normalized_criteria_digest=digest("c"),
        backend_criteria_stage="scope_only",
        source_kind=operation.value.removeprefix("read."),
        source_ref=ref(500 + index),
        source_version="synthetic-source-v3",
        observed_at=NOW,
        simulation=True,
        returned_count=1,
        matched_count=1,
        source_total=1,
        matched_total=1,
        page_count=1,
        query_zero_classification="nonzero",
        source_query_complete=True,
        model_projection_complete=complete,
        matching_fact_refs=matching_fact_refs or (fact_ref,),
        financial_versions=(
            financial_versions
            if financial_versions is not None
            else (c.P2FinancialVersion(activity_ref=ref(1), financial_version=8),)
        ),
        page=c.P2PageSummary(
            pages_seen=1,
            has_more=has_more,
            truncated=False,
            source_query_complete=True,
            model_projection_complete=complete,
            range_contiguous=True,
            stable_total_verified=True,
            source_version_fenced=True,
            unique_items_verified=True,
            expected_total=expected_total,
        ),
        query_digest=digest("d"),
        body_digest=digest("e"),
        projection_digest=digest("f"),
    )


def grant_and_receipt(
    *, number: int, operation: c.P2ReadOperation, scope: c.P2Scope,
    criteria: str, expires: datetime | None = None,
) -> tuple[c.P2SourceAuthorizationGrant, c.P2FreshQueryEvidenceRef]:
    principal, owner = ref(700), ref(701)
    expiry = expires or NOW + timedelta(hours=1)
    grant = c.P2SourceAuthorizationGrant(
        principal_ref=principal,
        owner_turn_ref=owner,
        generation=3,
        source_input_seq=5,
        input_digest=digest("7"),
        operation=operation,
        scope=scope,
        criteria_digest=criteria,
        expires_at=expiry,
        grant_ref=ref(710 + number),
    )
    receipt = c.P2FreshQueryEvidenceRef(
        query_evidence_ref=qev(number),
        query_ref=ref(200 + number),
        principal_ref=principal,
        owner_turn_ref=owner,
        generation=3,
        source_input_seq=5,
        input_digest=digest("7"),
        operation=operation,
        scope_ref=scope.scope_ref,
        criteria_digest=criteria,
        observed_at=NOW,
        expires_at=expiry,
        next_page_ref=ref(800 + number) if number == 1 else None,
        page_index=0,
    )
    return grant, receipt


def private_context(
    *, pairs: tuple[tuple[c.P2SourceAuthorizationGrant, c.P2FreshQueryEvidenceRef], ...] = (),
    classification: str = "factual_business", primary: int = 0,
    scope: c.P2Scope | None = None, scope_status: str | None = None,
    source_grant: c.P2SourceAuthorizationGrant | None = None,
    clarification: bool = False, target_resolved: bool = False,
    pending: tuple[c.P2PendingClarification, ...] = (),
) -> c.P2IntentContext:
    scope = scope or scope_dto()
    grant = source_grant or (pairs[primary][0] if pairs else None)
    selected_scope_status = scope_status or ("verified" if grant is not None else "absent")
    return c.P2IntentContext(
        profile_id=c.P2_V3_CANDIDATE_PROFILE_ID,
        versions=c.P2_V3_VERSIONS,
        classification=classification,
        principal_ref=ref(700),
        owner_turn_ref=ref(701),
        generation=3,
        source_input_seq=5,
        input_digest=digest("7"),
        scope_status=selected_scope_status,
        scope=scope if selected_scope_status == "verified" else None,
        source_authorization_grant=grant,
        fresh_receipt_refs=tuple(receipt for _, receipt in pairs),
        query_authorization_bindings=tuple(
            c.P2QueryAuthorizationBinding(query_evidence_ref=receipt.query_evidence_ref, receipt=receipt, grant=g)
            for g, receipt in pairs
        ),
        clarification_required=clarification or bool(pending),
        pending_clarifications=pending,
        proposal_target_resolved=target_resolved,
        classifier_source="server_policy" if classification != "ambiguous" else None,
        classifier_version="test-policy-v1" if classification != "ambiguous" else None,
    )


def pending_slot(
    slot: str, reason: str, operation: c.P2ReadOperation | c.P2ProposalOperation | None,
    *, generation: int = 3, source_input_seq: int = 5, input_digest: str | None = None,
) -> c.P2PendingClarification:
    return c.P2PendingClarification(
        slot=slot, reason=reason, generation=generation, source_input_seq=source_input_seq,
        input_digest=input_digest or digest("7"), operation=operation,
    )


def pending_projection(
    slot: str, reason: str, operation: c.P2ReadOperation | c.P2ProposalOperation | None,
) -> c.P2PendingClarificationProjection:
    return c.P2PendingClarificationProjection(slot=slot, reason=reason, operation=operation)


def expense_fact_dto(
    *, evidence_ref: str = qev(1), version: int = 8, scope_ref: str = ref(1),
    expense_ref: str = ref(21),
) -> c.ExpenseFact:
    return c.ExpenseFact(
        fact_kind="expense", expense_ref=expense_ref, title="早餐🍜", scope_ref=scope_ref,
        occurred_at=NOW, signed_original_amount="10.2500", original_currency="CNY",
        signed_base_amount="10.3", base_currency="CNY",
        payer_split_lines=(c.ParticipantAllocationFact(
            participant_ref=ref(22), role="payer", signed_original_amount="10.2500",
            original_currency="CNY", signed_base_amount="10.3", base_currency="CNY",
        ),),
        expense_version=2, financial_version=version, query_evidence_ref=evidence_ref,
    )


def test_v3_versions_and_all_seven_read_query_json_operations() -> None:
    assert c.P2_V3_VERSIONS.model_dump(mode="json") == VERSIONS
    scope = {
        "scope_kind": "activity", "scope_ref": ref(1),
        "activity_ref": ref(1), "ledger_unit_ref": None,
    }
    cases = [
        ("read.activities", {"kind": "activities", "status": "active", "name_contains": None}, None),
        ("read.expenses", {"kind": "expenses", "activity_ref": ref(1), "from_date": None, "to_date": None, "participant_ref": None, "title_contains": None}, scope),
        ("read.debts", {"kind": "debts", "activity_ref": ref(1), "participant_ref": None, "currency": None}, scope),
        ("read.refund_events", {"kind": "refund_events", "activity_ref": ref(1), "from_date": None, "to_date": None}, scope),
        ("read.prepayment_accounts", {"kind": "prepayment_accounts", "activity_ref": ref(1)}, scope),
        ("read.prepayment_usages", {"kind": "prepayment_usages", "activity_ref": ref(1), "expense_ref": None, "participant_ref": None}, scope),
        ("read.prepayment_return_events", {"kind": "prepayment_return_events", "activity_ref": ref(1), "from_date": None, "to_date": None}, scope),
    ]
    for operation, criteria, read_scope in cases:
        raw = json.dumps({
            "kind": "read", "message_type": "query_request", "profile_id": c.P2_V3_CANDIDATE_PROFILE_ID,
            "versions": VERSIONS, "operation": operation, "criteria": criteria, "scope": read_scope,
        }, separators=(",", ":")).encode()
        parsed = c.parse_p2_read_request(raw)
        assert isinstance(parsed, c.P2ReadQueryRequest)
        assert parsed.operation.value == operation
        assert parsed.profile_id == c.P2_V3_CANDIDATE_PROFILE_ID

    continuation = json.dumps({
        "kind": "read", "message_type": "continue_request", "profile_id": c.P2_V3_CANDIDATE_PROFILE_ID,
        "versions": VERSIONS, "query_ref": ref(9), "next_page_ref": ref(10),
    }).encode()
    assert isinstance(c.parse_p2_read_request(continuation), c.P2ReadContinueRequest)

    bad_scope_request = {
        "kind": "read", "message_type": "query_request", "profile_id": c.P2_V3_CANDIDATE_PROFILE_ID,
        "versions": VERSIONS, "operation": "read.expenses",
        "criteria": {"kind": "expenses", "activity_ref": ref(2), "from_date": None,
                     "to_date": None, "participant_ref": None, "title_contains": None},
        "scope": scope,
    }
    with pytest.raises(ValidationError, match="must match"):
        c.parse_p2_read_request(json.dumps(bad_scope_request).encode())


@pytest.mark.parametrize("tuple_value", [
    {"api": "2.1.0", "semantic": "2.0.0", "operations": "2.1.0", "trajectory": "2.0.0"},
    {"api": "3.0.0", "semantic": "2.1.0", "operations": "2.0.0", "trajectory": "2.0.0"},
])
def test_v2_or_mixed_protocol_tuple_is_rejected_on_json_wire(tuple_value: dict[str, str]) -> None:
    raw = json.dumps({
        "kind": "read", "message_type": "query_request", "profile_id": c.P2_V3_CANDIDATE_PROFILE_ID,
        "versions": tuple_value, "operation": "read.activities",
        "criteria": {"kind": "activities", "status": "active", "name_contains": None}, "scope": None,
    }).encode()
    with pytest.raises(ValidationError):
        c.parse_p2_read_request(raw)


def test_v3_rejects_v2_profile_extra_execution_key_duplicate_keys_and_nonfinite_json() -> None:
    body = {
        "kind": "read", "message_type": "query_request", "profile_id": c.P2_V3_CANDIDATE_PROFILE_ID,
        "versions": VERSIONS, "operation": "read.activities",
        "criteria": {"kind": "activities", "status": "active", "name_contains": None}, "scope": None,
    }
    for key, value in (("profile_id", "p2.read-paged-prepayment-refund.v2-candidate"),
                       ("execution_key_version", "legacy-1"), ("private_grant", "secret")):
        invalid = dict(body)
        invalid[key] = value
        with pytest.raises((ValidationError, ValueError)):
            c.parse_p2_read_request(json.dumps(invalid).encode())
    with pytest.raises(ValueError, match="duplicate"):
        c.parse_p2_read_request(b'{"kind":"read","kind":"read"}')
    with pytest.raises(ValueError):
        c.parse_p2_read_request(b'{"kind":"read","amount":NaN}')


def test_four_semantic_decision_shapes_are_reachable() -> None:
    payloads = [
        {"kind": "answer", "basis": "non_business_general", "text": "你好。", "citations": []},
        {"kind": "clarify", "prompt": "请问是哪一项？", "missing_slots": ["expense_target"]},
        {"kind": "propose", "operation": "expense.create", "recognized_intent_text": "记录一笔餐费"},
        {"kind": "read", "message_type": "query_request", "profile_id": c.P2_V3_CANDIDATE_PROFILE_ID,
         "versions": VERSIONS, "operation": "read.activities",
         "criteria": {"kind": "activities", "status": "active", "name_contains": None}, "scope": None},
    ]
    assert [c.parse_p2_decision_shape(json.dumps(item).encode()).kind for item in payloads] == [
        "answer", "clarify", "propose", "read"
    ]


def test_title_is_required_exact_unicode_and_bounded() -> None:
    valid = {
        "fact_kind": "expense", "expense_ref": ref(21), "title": " 早餐🍜 — café ",
        "scope_ref": ref(1), "occurred_at": NOW, "signed_original_amount": "10.2500",
        "original_currency": "CNY", "signed_base_amount": "10.3", "base_currency": "CNY",
        "payer_split_lines": ({"participant_ref": ref(22), "role": "payer", "signed_original_amount": "10.2500",
                              "original_currency": "CNY", "signed_base_amount": "10.3", "base_currency": "CNY"},),
        "expense_version": 2, "financial_version": 8, "query_evidence_ref": qev(1),
    }
    fact = c.ExpenseFact.model_validate(valid)
    assert fact.title == valid["title"]
    source_evidence = evidence_dto(
        operation=c.P2ReadOperation.EXPENSES, evidence_ref=qev(1), fact_ref=fact.expense_ref,
    )
    source_bound_context = context_dto(
        scope=scope_dto(), evidence=(source_evidence,), facts=(fact,), fresh_refs=(qev(1),),
    )
    assert c.parse_p2_model_context(source_bound_context).facts[0].title == fact.title
    wrong_scope_fact = fact.model_copy(update={"scope_ref": ref(999)})
    with pytest.raises(ValidationError, match="current authorized scope"):
        context_dto(scope=scope_dto(), evidence=(source_evidence,), facts=(wrong_scope_fact,), fresh_refs=(qev(1),))
    missing = dict(valid)
    del missing["title"]
    with pytest.raises(ValidationError):
        c.ExpenseFact.model_validate(missing)
    for title in (" " * 3, "x" * 201):
        with pytest.raises(ValidationError):
            c.ExpenseFact.model_validate({**valid, "title": title})


def test_verified_scope_rejects_missing_or_conflicting_financial_activity_fences() -> None:
    scope = scope_dto()
    missing_fence = evidence_dto(
        operation=c.P2ReadOperation.EXPENSES, evidence_ref=qev(30), fact_ref=ref(30),
        financial_versions=(),
    )
    with pytest.raises(ValidationError, match="financial query evidence"):
        context_dto(scope=scope, evidence=(missing_fence,))

    expense_label = label_dto(
        entity_ref=ref(1), kind="activity", scope_ref=ref(1), source_kind="activities", version=9,
    )
    participant_label = label_dto(
        entity_ref=ref(51), kind="participant", scope_ref=ref(1), source_kind="participants", version=9,
    )
    actor = c.P2CurrentActorBinding(
        actor_ref=ref(52), activity_ref=ref(1), participant_ref=ref(51),
        source_kind="participant_claims.current_auth_user", observed_at=NOW,
        scope_financial_version=9, source_receipt_ref=ref(903),
    )
    query_at_eight = evidence_dto(
        operation=c.P2ReadOperation.EXPENSES, evidence_ref=qev(31), fact_ref=ref(31),
    )
    with pytest.raises(ValidationError, match="financial-version fence"):
        context_dto(
            scope=scope, labels=(expense_label, participant_label), actor=actor,
            evidence=(query_at_eight,),
        )


def test_fact_financial_version_must_match_its_query_evidence_activity_fence() -> None:
    evidence = evidence_dto(
        operation=c.P2ReadOperation.EXPENSES, evidence_ref=qev(32), fact_ref=ref(32),
    )
    stale_fact = expense_fact_dto(evidence_ref=qev(32), version=9, expense_ref=ref(32))
    with pytest.raises(ValidationError, match="fact financial_version"):
        context_dto(scope=scope_dto(), evidence=(evidence,), facts=(stale_fact,), fresh_refs=(qev(32),))


def test_duplicate_query_evidence_refs_are_rejected() -> None:
    evidence = evidence_dto(
        operation=c.P2ReadOperation.EXPENSES, evidence_ref=qev(33), fact_ref=ref(33),
    )
    with pytest.raises(ValidationError, match="query evidence refs must be unique"):
        context_dto(evidence=(evidence, evidence))
    single = context_dto(evidence=(evidence,))
    bypassed = single.model_copy(update={"query_evidence": (evidence, evidence)})
    with pytest.raises(ValidationError, match="query evidence refs must be unique"):
        c.parse_p2_model_context(bypassed)


def test_no_scope_discovery_compares_financial_fences_per_activity() -> None:
    first = label_dto(
        entity_ref=ref(71), kind="activity", scope_ref=ref(71), source_kind="activities", version=8,
    )
    second = label_dto(
        entity_ref=ref(72), kind="activity", scope_ref=ref(72), source_kind="activities", version=11,
        display_name="第二个活动",
    )
    evidence = evidence_dto(
        operation=c.P2ReadOperation.ACTIVITIES, evidence_ref=qev(34), fact_ref=ref(71),
        financial_versions=(
            c.P2FinancialVersion(activity_ref=ref(71), financial_version=8),
            c.P2FinancialVersion(activity_ref=ref(72), financial_version=11),
        ),
        matching_fact_refs=(ref(71), ref(72)),
    )
    facts = (
        c.ActivityFact(
            fact_kind="activity", activity_ref=ref(71), activity_kind="trip", name="活动一",
            base_currency="CNY", status="active", observed_at=NOW, context_version="activity-v8",
            query_evidence_ref=qev(34),
        ),
        c.ActivityFact(
            fact_kind="activity", activity_ref=ref(72), activity_kind="trip", name="活动二",
            base_currency="USD", status="active", observed_at=NOW, context_version="activity-v11",
            query_evidence_ref=qev(34),
        ),
    )
    parsed = c.parse_p2_model_context(context_dto(
        status="absent", scope=None, labels=(first, second), evidence=(evidence,), facts=facts,
        kinds=("read",), operations=(c.P2ReadOperation.ACTIVITIES,), fresh_refs=(qev(34),),
    ))
    assert tuple(label.scope_financial_version for label in parsed.source_labels) == (8, 11)

    inconsistent = evidence.model_copy(update={
        "financial_versions": (
            c.P2FinancialVersion(activity_ref=ref(71), financial_version=9),
            c.P2FinancialVersion(activity_ref=ref(72), financial_version=11),
        ),
    })
    with pytest.raises(ValidationError, match="financial-version fence"):
        context_dto(
            status="absent", scope=None, labels=(first, second), evidence=(inconsistent,), facts=facts,
            kinds=("read",), operations=(c.P2ReadOperation.ACTIVITIES,), fresh_refs=(qev(34),),
        )


def test_financial_source_lexemes_keep_domain_precision_and_nullability() -> None:
    assert c.parse_source_numeric_lexeme("9999999999999999.9999", precision=20, scale=4)
    assert c.parse_source_numeric_lexeme("9999999999999999999.9", precision=20, scale=1)
    with pytest.raises(ValueError):
        c.parse_source_numeric_lexeme("10000000000000000.0000", precision=20, scale=4)
    with pytest.raises(ValueError):
        c.parse_source_numeric_lexeme("10000000000000000000.0", precision=20, scale=1)
    assert c.parse_financial_version(2**63 - 1) == 2**63 - 1
    for invalid in (True, 1.0, "1", 2**63):
        with pytest.raises(ValueError):
            c.parse_financial_version(invalid)
    debt = c.DebtFact(
        fact_kind="debt", debt_ref=ref(31), scope_ref=ref(1), activity_ref=ref(1),
        ledger_unit_ref=ref(32), expense_ref=ref(33), debtor_ref=ref(34), creditor_ref=ref(35),
        original_amount=None, original_currency=None, base_amount="0", base_currency="CNY",
        financial_version=8, query_evidence_ref=qev(2),
    )
    assert debt.original_amount is None and debt.base_amount == "0"
    with pytest.raises(ValidationError):
        c.DebtFact.model_validate({**debt.model_dump(), "financial_version": True})


def test_source_amount_parsers_preserve_nullable_original_and_fx_lexemes() -> None:
    parsed = c.parse_expense_debt_source_amounts({
        "amount": "0", "original_amount": None, "original_currency": None, "fx_rate": "1.1234567890"
    })
    assert parsed.amount == "0" and parsed.original_amount is None
    assert parsed.fx_rate == "1.1234567890"
    with pytest.raises(ValueError):
        c.parse_expense_debt_source_amounts({
            "amount": "0", "original_amount": None, "original_currency": None, "fx_rate": "1.12345678901"
        })


def test_refund_sign_and_zero_base_are_preserved_without_conversion() -> None:
    common = {
        "fact_kind": "refund_event", "refund_ref": ref(41), "scope_ref": ref(1),
        "signed_original_amount": "-2.0000", "original_currency": "USD",
        "signed_base_amount": "0", "base_currency": "CNY", "occurred_at": NOW,
        "parent_expense_ref": None, "lineage_status": "parent_unavailable", "lineage_basis": None,
        "refund_recipient_ref": ref(42), "financial_version": 8, "query_evidence_ref": qev(3),
    }
    assert c.RefundEventFact.model_validate(common).signed_base_amount == "0"
    for change in ({"signed_original_amount": "2.0000"}, {"signed_original_amount": "0"}, {"signed_base_amount": "0.1"}):
        with pytest.raises(ValidationError):
            c.RefundEventFact.model_validate({**common, **change})


def test_actor_and_labels_bind_unicode_identity_to_one_verified_scope() -> None:
    scope = scope_dto()
    activity_label = label_dto(entity_ref=ref(1), kind="activity", scope_ref=ref(1), source_kind="activities", display_name="春日🪴")
    participant_label = label_dto(entity_ref=ref(51), kind="participant", scope_ref=ref(1), source_kind="participants", display_name="我 — 张三")
    actor = c.P2CurrentActorBinding(
        actor_ref=ref(52), activity_ref=ref(1), participant_ref=ref(51),
        source_kind="participant_claims.current_auth_user", observed_at=NOW,
        scope_financial_version=8, source_receipt_ref=ref(903),
    )
    context = context_dto(scope=scope, actor=actor, labels=(activity_label, participant_label))
    parsed = c.parse_p2_model_context(context.model_dump_json())
    assert parsed.current_actor == actor
    assert parsed.source_labels[0].display_name == "春日🪴"
    assert parsed.source_labels[1].display_name == "我 — 张三"

    bad_actor = actor.model_copy(update={"activity_ref": ref(999)})
    with pytest.raises(ValidationError):
        context_dto(scope=scope, actor=bad_actor, labels=(activity_label, participant_label))
    unmatched = actor.model_copy(update={"participant_ref": ref(777)})
    with pytest.raises(ValidationError):
        context_dto(scope=scope, actor=unmatched, labels=(activity_label, participant_label))


def test_label_source_kind_version_timestamps_duplicates_and_bounds_are_strict() -> None:
    with pytest.raises(ValidationError):
        label_dto(entity_ref=ref(61), kind="participant", scope_ref=ref(1), source_kind="activities")
    with pytest.raises(ValidationError):
        label_dto(entity_ref=ref(62), kind="participant", scope_ref=ref(1), source_kind="participants", updated_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        label_dto(entity_ref=ref(63), kind="activity", scope_ref=ref(1), source_kind="activities", version=True)
    scope = scope_dto()
    label = label_dto(entity_ref=ref(64), kind="participant", scope_ref=ref(1), source_kind="participants")
    with pytest.raises(ValidationError):
        context_dto(scope=scope, labels=(label, label))
    with pytest.raises(ValidationError):
        c.P2EntityDisplayLabel.model_validate({
            **label.model_dump(), "display_name": "x" * 201,
        })
    with pytest.raises(ValidationError):
        c.P2CurrentActorBinding(
            actor_ref=ref(65), activity_ref=ref(1), participant_ref=ref(66),
            source_kind="participant_claims.current_auth_user", observed_at=NOW,
            scope_financial_version=True, source_receipt_ref=ref(67),
        )
    excessive = tuple(
        label_dto(entity_ref=ref(1000 + index), kind="participant", scope_ref=ref(1), source_kind="participants")
        for index in range(129)
    )
    with pytest.raises(ValidationError):
        context_dto(scope=scope, labels=excessive)


def test_unscoped_discovery_allows_only_self_scoped_activity_labels() -> None:
    activity = label_dto(entity_ref=ref(71), kind="activity", scope_ref=ref(71), source_kind="activities")
    context = context_dto(status="absent", scope=None, labels=(activity,), kinds=("read",),
                          operations=(c.P2ReadOperation.ACTIVITIES,))
    assert c.parse_p2_model_context(context).source_labels == (activity,)
    another_activity = label_dto(
        entity_ref=ref(72), kind="activity", scope_ref=ref(72), source_kind="activities", version=11,
        display_name="第二个活动",
    )
    multi_activity = context_dto(
        status="absent", scope=None, labels=(activity, another_activity), kinds=("read",),
        operations=(c.P2ReadOperation.ACTIVITIES,),
    )
    assert tuple(label.scope_financial_version for label in multi_activity.source_labels) == (8, 11)
    participant = label_dto(entity_ref=ref(72), kind="participant", scope_ref=ref(71), source_kind="participants")
    with pytest.raises(ValidationError):
        context_dto(status="absent", scope=None, labels=(participant,), kinds=("read",),
                    operations=(c.P2ReadOperation.ACTIVITIES,))
    with pytest.raises(ValidationError):
        context_dto(status="unresolved", scope=None, labels=(activity,), kinds=("read",),
                    operations=(c.P2ReadOperation.ACTIVITIES,))
    financial_evidence = evidence_dto(
        operation=c.P2ReadOperation.EXPENSES, evidence_ref=qev(88), fact_ref=ref(88),
    )
    with pytest.raises(ValidationError, match="financial query evidence"):
        context_dto(status="absent", scope=None, evidence=(financial_evidence,),
                    kinds=("read",), operations=(c.P2ReadOperation.ACTIVITIES,))


def test_context_versions_construct_bypass_and_unknown_secret_fields_are_revalidated() -> None:
    valid = context_dto()
    bad_copy = valid.model_copy(update={
        "versions": c.P2V3ProtocolVersions.model_construct(
            api="3.0.0", semantic="2.1.0", operations="2.0.0", trajectory="2.0.0"
        )
    })
    with pytest.raises(ValidationError):
        c.parse_p2_model_context(bad_copy)
    raw = valid.model_dump_json()
    duplicate = raw[:-1] + ',"generation":99}'
    with pytest.raises(ValueError, match="duplicate"):
        c.parse_p2_model_context(duplicate)
    with pytest.raises(ValidationError):
        c.parse_p2_model_context({**valid.model_dump(mode="json"), "access_token": "not-for-context"})
    with pytest.raises(ValidationError):
        c.P2CurrentActorBinding(
            actor_ref="550e8400-e29b-41d4-a716-446655440000", activity_ref=ref(1),
            participant_ref=ref(2), source_kind="participant_claims.current_auth_user",
            observed_at=NOW, scope_financial_version=8, source_receipt_ref=ref(9),
        )


def test_four_context_semantic_branches_keep_read_clarify_and_recognition_reachable() -> None:
    nonbusiness = context_dto(
        classification="non_business", status="absent", scope=None,
        kinds=("answer",), operations=(), source_free=True, requires_evidence=False,
    )
    ambiguous = context_dto(
        classification="ambiguous", status="unresolved", scope=None,
        kinds=("read",), operations=(c.P2ReadOperation.ACTIVITIES,), source_free=False,
    )
    proposal = context_dto(
        classification="proposal_intent", status="verified", scope=scope_dto(),
        kinds=("propose",), operations=(), source_free=False, requires_evidence=False,
        proposal_required=False, proposals=(c.P2ProposalOperation.EXPENSE_CREATE,),
    )
    unresolved_proposal = context_dto(
        classification="proposal_intent", status="verified", scope=scope_dto(),
        kinds=("clarify",), operations=(), source_free=False, requires_evidence=False,
        proposal_required=True, proposals=(),
        pending=(pending_projection("proposal_target", "required_target_missing", c.P2ProposalOperation.EXPENSE_CREATE),),
    )
    assert [nonbusiness.trusted_intent.classification, ambiguous.trusted_intent.classification,
            proposal.trusted_intent.classification, unresolved_proposal.trusted_intent.classification] == [
        "non_business", "ambiguous", "proposal_intent", "proposal_intent"
    ]
    assert isinstance(c.parse_p2_decision(
        {"kind": "answer", "basis": "non_business_general", "text": "你好。", "citations": []},
        private_context(classification="non_business"),
    ), c.P2AnswerDecision)
    with pytest.raises(ValidationError, match="authoritative evidence"):
        context_dto(classification="factual_business", source_free=True)
    with pytest.raises(ValidationError, match="ambiguous context"):
        context_dto(classification="ambiguous", kinds=("answer", "read"), source_free=False)
    with pytest.raises(ValidationError, match="cannot enable reads or answers"):
        context_dto(classification="proposal_intent", kinds=("propose", "answer"),
                    requires_evidence=False, proposal_required=False,
                    proposals=(c.P2ProposalOperation.EXPENSE_CREATE,))



def test_public_pending_projection_is_exact_safe_and_order_independent() -> None:
    private_pending = (
        pending_slot("expense_target", "ambiguous_user_reference", c.P2ReadOperation.EXPENSES),
        pending_slot("participant_target", "required_target_missing", c.P2ReadOperation.EXPENSES),
    )
    public_pending = tuple(
        pending_projection(item.slot, item.reason, item.operation)
        for item in reversed(private_pending)
    )
    public = context_dto(
        classification="factual_business", status="absent", scope=None,
        kinds=("clarify",), operations=(), pending=public_pending,
    )
    private = private_context(classification="factual_business", pending=private_pending)
    validated = c.validate_p2_clarification_projection(public, private)
    assert validated.input_text == "我欠谁？🙂"
    assert tuple(item.slot for item in validated.pending_clarifications) == (
        "participant_target", "expense_target",
    )
    assert set(validated.pending_clarifications[0].model_dump()) == {"slot", "reason", "operation"}
    assert not hasattr(validated.pending_clarifications[0], "input_digest")
    assert not hasattr(validated.pending_clarifications[0], "generation")


def test_public_pending_projection_rejects_slot_reason_operation_and_private_binding_drift() -> None:
    pending = pending_slot("expense_target", "ambiguous_user_reference", c.P2ReadOperation.EXPENSES)
    public = context_dto(
        classification="factual_business", status="absent", scope=None,
        kinds=("clarify",), operations=(),
        pending=(pending_projection(pending.slot, pending.reason, pending.operation),),
    )
    private = private_context(classification="factual_business", pending=(pending,))
    assert c.validate_p2_clarification_projection(public, private) is not None

    for replacement in (
        pending_projection("participant_target", "ambiguous_user_reference", c.P2ReadOperation.EXPENSES),
        pending_projection("expense_target", "source_label_unavailable", c.P2ReadOperation.EXPENSES),
        pending_projection("expense_target", "ambiguous_user_reference", c.P2ReadOperation.DEBTS),
    ):
        changed = public.model_copy(update={"pending_clarifications": (replacement,)})
        with pytest.raises(ValueError):
            c.validate_p2_clarification_projection(changed, private)

    changed_generation = public.model_copy(update={"generation": 4})
    with pytest.raises(ValueError, match="generation"):
        c.validate_p2_clarification_projection(changed_generation, private)
    changed_sequence_intent = public.trusted_intent.model_copy(update={"source_input_seq": 6})
    changed_sequence = public.model_copy(update={"trusted_intent": changed_sequence_intent})
    with pytest.raises(ValueError, match="input sequence"):
        c.validate_p2_clarification_projection(changed_sequence, private)

    no_pending_public = context_dto(
        classification="factual_business", status="absent", scope=None,
        kinds=("read",), operations=(c.P2ReadOperation.ACTIVITIES,),
    )
    no_pending_private = private_context(classification="factual_business")
    with pytest.raises(ValueError, match="generation"):
        c.validate_p2_clarification_projection(
            no_pending_public, no_pending_private.model_copy(update={"generation": 4}),
        )
    with pytest.raises(ValueError, match="input sequence"):
        c.validate_p2_clarification_projection(
            no_pending_public, no_pending_private.model_copy(update={"source_input_seq": 6}),
        )
    bad_classification = no_pending_public.trusted_intent.model_copy(update={"classification": "ambiguous"})
    with pytest.raises(ValueError, match="classification"):
        c.validate_p2_clarification_projection(
            no_pending_public.model_copy(update={"trusted_intent": bad_classification}),
            no_pending_private,
        )
    bad_classifier_version = no_pending_public.trusted_intent.model_copy(update={"classifier_version": "stale-policy"})
    with pytest.raises(ValueError, match="classifier version"):
        c.validate_p2_clarification_projection(
            no_pending_public.model_copy(update={"trusted_intent": bad_classifier_version}),
            no_pending_private,
        )

    forged_projection = c.P2PendingClarificationProjection.model_construct(
        slot="expense_ref", reason="ambiguous_user_reference",
        operation=c.P2ReadOperation.EXPENSES,
    )
    forged_public = public.model_copy(update={"pending_clarifications": (forged_projection,)})
    with pytest.raises(ValueError, match="strict revalidation"):
        c.validate_p2_clarification_projection(forged_public, private)

    stale_pending = pending_slot(
        "expense_target", "ambiguous_user_reference", c.P2ReadOperation.EXPENSES, generation=2,
    )
    private_payload = private.model_dump()
    private_payload["versions"] = private.versions
    private_payload["pending_clarifications"] = (stale_pending,)
    forged_private = c.P2IntentContext.model_construct(**private_payload)
    with pytest.raises(ValueError, match="strict revalidation"):
        c.validate_p2_clarification_projection(public, forged_private)


def test_public_pending_projection_shape_and_guard_reachability() -> None:
    missing_scope = pending_projection("activity_scope", "missing_required_scope", None)
    ambiguous_object = pending_projection(
        "expense_target", "ambiguous_user_reference", c.P2ReadOperation.EXPENSES,
    )
    proposal_amount = pending_projection(
        "proposal_amount", "required_target_missing", c.P2ProposalOperation.EXPENSE_CREATE,
    )
    missing_scope_context = context_dto(
        classification="ambiguous", status="unresolved", scope=None,
        kinds=("clarify",), operations=(), pending=(missing_scope,),
    )
    assert missing_scope_context.pending_clarifications == (missing_scope,)
    assert c.validate_p2_clarification_projection(
        missing_scope_context,
        private_context(
            classification="ambiguous", scope_status="unresolved",
            pending=(pending_slot("activity_scope", "missing_required_scope", None),),
        ),
    )
    ambiguous_object_context = context_dto(
        classification="factual_business", status="absent", scope=None,
        kinds=("clarify",), operations=(), pending=(ambiguous_object,),
    )
    assert ambiguous_object_context.pending_clarifications == (ambiguous_object,)
    assert c.validate_p2_clarification_projection(
        ambiguous_object_context,
        private_context(
            classification="factual_business",
            pending=(pending_slot("expense_target", "ambiguous_user_reference", c.P2ReadOperation.EXPENSES),),
        ),
    )
    proposal_pending = context_dto(
        classification="proposal_intent", status="absent", scope=None,
        kinds=("clarify",), operations=(), requires_evidence=False,
        proposal_required=True, pending=(proposal_amount,),
    )
    private_proposal_pending = private_context(
        classification="proposal_intent", target_resolved=True,
        pending=(pending_slot("proposal_amount", "required_target_missing", c.P2ProposalOperation.EXPENSE_CREATE),),
    )
    assert c.validate_p2_clarification_projection(proposal_pending, private_proposal_pending)

    # A resolved full expense read does not need an expense_ref or a fabricated clarify branch.
    full_expense = context_dto(
        classification="factual_business", status="verified", scope=scope_dto(),
        kinds=("read",), operations=(c.P2ReadOperation.EXPENSES,), pending=(),
    )
    assert "clarify" not in full_expense.guard.allowed_decision_kinds
    assert full_expense.guard.allowed_read_operations == (c.P2ReadOperation.EXPENSES,)

    resolved_proposal = context_dto(
        classification="proposal_intent", status="verified", scope=scope_dto(),
        kinds=("propose",), operations=(), requires_evidence=False,
        proposal_required=False, proposals=(c.P2ProposalOperation.EXPENSE_CREATE,), pending=(),
    )
    assert resolved_proposal.guard.allowed_decision_kinds == ("propose",)
    nonbusiness = context_dto(
        classification="non_business", status="absent", scope=None,
        kinds=("answer",), operations=(), source_free=True, requires_evidence=False, pending=(),
    )
    assert nonbusiness.guard.allowed_decision_kinds == ("answer",)

    with pytest.raises(ValidationError, match="only allowed decision kind"):
        context_dto(
            classification="ambiguous", status="unresolved", scope=None,
            kinds=("clarify", "read"), operations=(c.P2ReadOperation.ACTIVITIES,),
            pending=(missing_scope,),
        )
    with pytest.raises(ValidationError, match="without a current pending slot"):
        context_dto(
            classification="ambiguous", status="unresolved", scope=None,
            kinds=("clarify",), operations=(), pending=(),
        )
    with pytest.raises(ValidationError):
        context_dto(
            classification="non_business", status="absent", scope=None,
            kinds=("clarify",), operations=(), source_free=False, requires_evidence=False,
            pending=(missing_scope,),
        )
    with pytest.raises(ValidationError):
        context_dto(
            classification="proposal_intent", status="verified", scope=scope_dto(),
            kinds=("propose", "clarify"), operations=(), requires_evidence=False,
            proposal_required=False, proposals=(c.P2ProposalOperation.EXPENSE_CREATE,), pending=(),
        )


def test_pending_clarification_classification_cannot_mix_read_and_proposal_slots() -> None:
    read_pending = pending_slot(
        "expense_target", "ambiguous_user_reference", c.P2ReadOperation.EXPENSES,
    )
    public_read_pending = pending_projection(
        "expense_target", "ambiguous_user_reference", c.P2ReadOperation.EXPENSES,
    )
    with pytest.raises(ValidationError, match="proposal intent cannot carry a read-operation"):
        private_context(
            classification="proposal_intent", target_resolved=True,
            pending=(read_pending,),
        )
    with pytest.raises(ValidationError, match="proposal intent cannot carry a read-operation"):
        context_dto(
            classification="proposal_intent", status="verified", scope=scope_dto(),
            kinds=("clarify",), operations=(), requires_evidence=False,
            proposal_required=True, pending=(public_read_pending,),
        )

    proposal_pending = pending_slot(
        "proposal_amount", "required_target_missing", c.P2ProposalOperation.EXPENSE_CREATE,
    )
    public_proposal_pending = pending_projection(
        "proposal_amount", "required_target_missing", c.P2ProposalOperation.EXPENSE_CREATE,
    )
    for classification in ("factual_business", "ambiguous"):
        with pytest.raises(ValidationError, match="cannot carry proposal-specific"):
            private_context(classification=classification, pending=(proposal_pending,))
        with pytest.raises(ValidationError, match="cannot carry proposal-specific"):
            context_dto(
                classification=classification, status="absent", scope=None,
                kinds=("clarify",), operations=(), pending=(public_proposal_pending,),
            )

    # A scope slot without an operation is the sole shared proposal/read slot;
    # it does not smuggle a read operation into proposal classification.
    activity_scope = pending_slot("activity_scope", "missing_required_scope", None)
    public_scope = pending_projection("activity_scope", "missing_required_scope", None)
    private_scope = private_context(
        classification="proposal_intent", scope_status="verified", clarification=True,
        target_resolved=True, pending=(activity_scope,),
    )
    public_scope_context = context_dto(
        classification="proposal_intent", status="verified", scope=scope_dto(),
        kinds=("clarify",), operations=(), requires_evidence=False,
        proposal_required=True, pending=(public_scope,),
    )
    assert c.validate_p2_clarification_projection(public_scope_context, private_scope)

    forged_public_payload = dict(public_scope_context.__dict__)
    forged_public_payload["pending_clarifications"] = (public_read_pending,)
    forged_public = c.P2ModelContext.model_construct(**forged_public_payload)
    with pytest.raises(ValueError, match="strict revalidation"):
        c.validate_p2_clarification_projection(forged_public, private_scope)

    forged_private_payload = dict(private_scope.__dict__)
    forged_private_payload["pending_clarifications"] = (read_pending,)
    forged_private = c.P2IntentContext.model_construct(**forged_private_payload)
    with pytest.raises(ValueError, match="strict revalidation"):
        c.validate_p2_clarification_projection(public_scope_context, forged_private)


def test_verified_scope_metadata_bootstrap_is_not_a_financial_read_grant() -> None:
    scope = scope_dto()
    public = context_dto(
        classification="factual_business", status="verified", scope=scope,
        kinds=("read",), operations=(c.P2ReadOperation.EXPENSES,),
    )
    metadata_only = private_context(
        classification="factual_business", scope=scope, scope_status="verified",
    )
    assert metadata_only.source_authorization_grant is None
    assert c.validate_p2_clarification_projection(public, metadata_only) == public

    criteria = c.ExpenseCriteria(kind="expenses", activity_ref=scope.activity_ref)
    request = {
        "kind": "read", "message_type": "query_request",
        "profile_id": c.P2_V3_CANDIDATE_PROFILE_ID,
        "versions": VERSIONS, "operation": "read.expenses",
        "criteria": criteria.model_dump(mode="json"),
        "scope": scope.model_dump(mode="json"),
    }
    with pytest.raises(ValueError, match="fresh source-authorized grant"):
        c.parse_p2_decision(request, metadata_only)
    answer = {
        "kind": "answer", "basis": "fresh_read_receipts", "text": "旧摘要不能证明当前事实。",
        "citations": [qev(560)],
    }
    with pytest.raises(ValueError, match="source grant and fresh query evidence"):
        c.parse_p2_decision(answer, metadata_only)

    _, stale_shape_receipt = grant_and_receipt(
        number=560, operation=c.P2ReadOperation.EXPENSES, scope=scope,
        criteria=c.p2_criteria_digest(criteria),
    )
    forged_metadata_with_receipt = metadata_only.model_copy(update={
        "fresh_receipt_refs": (stale_shape_receipt,),
    })
    with pytest.raises(ValidationError, match="pre-read metadata context"):
        c.P2IntentContext.model_validate_json(forged_metadata_with_receipt.model_dump_json(), strict=True)

    grant = c.P2SourceAuthorizationGrant(
        principal_ref=ref(700), owner_turn_ref=ref(701), generation=3, source_input_seq=5,
        input_digest=digest("7"), operation=c.P2ReadOperation.EXPENSES, scope=scope,
        criteria_digest=c.p2_criteria_digest(criteria), expires_at=NOW + timedelta(hours=1),
        grant_ref=ref(760),
    )
    authorized_for_query = private_context(
        classification="factual_business", scope=scope, scope_status="verified",
        source_grant=grant,
    )
    assert c.validate_p2_clarification_projection(public, authorized_for_query) == public
    assert isinstance(c.parse_p2_decision(request, authorized_for_query), c.P2ReadQueryRequest)


def test_public_pending_projection_is_required_bounded_and_rejects_private_fields() -> None:
    valid = context_dto()
    raw = valid.model_dump(mode="json")
    missing = dict(raw)
    missing.pop("pending_clarifications")
    with pytest.raises(ValidationError):
        c.parse_p2_model_context(missing)

    activity_scope = pending_projection("activity_scope", "missing_required_scope", None)
    with pytest.raises(ValidationError):
        context_dto(
            classification="ambiguous", status="unresolved", scope=None,
            kinds=("clarify",), operations=(), pending=(activity_scope, activity_scope),
        )
    too_many = tuple(activity_scope for _ in range(17))
    with pytest.raises(ValidationError):
        context_dto(
            classification="ambiguous", status="unresolved", scope=None,
            kinds=("clarify",), operations=(), pending=too_many,
        )

    secret = dict(raw)
    secret["pending_clarifications"] = [{
        "slot": "activity_scope", "reason": "missing_required_scope", "operation": None,
        "owner_turn_ref": ref(700),
    }]
    with pytest.raises(ValidationError):
        c.parse_p2_model_context(secret)


def test_proposal_recognition_requires_private_resolved_target_and_never_executes() -> None:
    decision = {"kind": "propose", "operation": "expense.create", "recognized_intent_text": "记一笔咖啡"}
    unresolved = private_context(
        classification="proposal_intent", clarification=True, target_resolved=False,
        pending=(pending_slot("proposal_target", "required_target_missing", c.P2ProposalOperation.EXPENSE_CREATE),),
    )
    with pytest.raises(ValueError, match="clarification"):
        c.parse_p2_decision(decision, unresolved)
    resolved = private_context(classification="proposal_intent", target_resolved=True)
    assert isinstance(c.parse_p2_decision(decision, resolved), c.P2ProposalRecognition)


def test_clarification_requires_current_server_pending_slot_and_allows_only_its_subset() -> None:
    pending = (
        pending_slot("expense_target", "ambiguous_user_reference", c.P2ReadOperation.EXPENSES),
        pending_slot("participant_target", "ambiguous_user_reference", c.P2ReadOperation.EXPENSES),
    )
    context = private_context(classification="factual_business", pending=pending)
    valid = {
        "kind": "clarify", "prompt": "你指哪一笔？", "missing_slots": ["expense_target"]
    }
    assert isinstance(c.parse_p2_decision(valid, context), c.P2ClarifyDecision)
    assert c.parse_p2_decision(valid, context).prompt == "你指哪一笔？"
    fabricated = {**valid, "missing_slots": ["return_target"]}
    with pytest.raises(ValueError, match="currently pending"):
        c.parse_p2_decision(fabricated, context)
    arbitrary = {**valid, "missing_slots": ["expense_ref"]}
    with pytest.raises(ValidationError):
        c.parse_p2_decision(arbitrary, context)
    duplicate = {**valid, "missing_slots": ["expense_target", "expense_target"]}
    with pytest.raises(ValidationError):
        c.parse_p2_decision(duplicate, context)

    resolved_context = private_context(classification="factual_business")
    with pytest.raises(ValueError, match="pending slots"):
        c.parse_p2_decision(valid, resolved_context)


def test_resolved_expense_read_does_not_require_optional_expense_target() -> None:
    scope = scope_dto()
    criteria = c.ExpenseCriteria(kind="expenses", activity_ref=ref(1))
    criteria_digest = c.p2_criteria_digest(criteria)
    # This required source grant binds the actual criteria. ExpenseCriteria has no
    # mandatory expense_ref; it remains an optional/absent filter for a full read.
    grant = c.P2SourceAuthorizationGrant(
        principal_ref=ref(700), owner_turn_ref=ref(701), generation=3, source_input_seq=5,
        input_digest=digest("7"), operation=c.P2ReadOperation.EXPENSES, scope=scope,
        criteria_digest=criteria_digest, expires_at=NOW + timedelta(hours=1), grant_ref=ref(712),
    )
    trusted = c.P2IntentContext(
        profile_id=c.P2_V3_CANDIDATE_PROFILE_ID,
        versions=c.P2_V3_VERSIONS,
        classification="factual_business", principal_ref=ref(700), owner_turn_ref=ref(701),
        generation=3, source_input_seq=5, input_digest=digest("7"), scope_status="verified",
        scope=scope, source_authorization_grant=grant,
        classifier_source="server_policy", classifier_version="test-policy-v1",
    )
    request = {
        "kind": "read", "message_type": "query_request", "profile_id": c.P2_V3_CANDIDATE_PROFILE_ID,
        "versions": VERSIONS, "operation": "read.expenses", "criteria": criteria.model_dump(mode="json"),
        "scope": scope.model_dump(mode="json"),
    }
    parsed = c.parse_p2_decision(request, trusted)
    assert isinstance(parsed, c.P2ReadQueryRequest)
    assert parsed.criteria.title_contains is None

    fabricated = {
        "kind": "clarify", "prompt": "请提供 expense_ref。", "missing_slots": ["expense_target"]
    }
    with pytest.raises(ValueError, match="pending slots"):
        c.parse_p2_decision(fabricated, trusted)


def test_pending_clarification_is_bound_to_current_input_and_operation() -> None:
    with pytest.raises(ValidationError, match="does not apply"):
        pending_slot("currency", "ambiguous_user_reference", c.P2ReadOperation.EXPENSES)
    with pytest.raises(ValidationError, match="proposal operation"):
        pending_slot("proposal_target", "required_target_missing", c.P2ReadOperation.EXPENSES)
    stale = pending_slot(
        "expense_target", "ambiguous_user_reference", c.P2ReadOperation.EXPENSES,
        input_digest=digest("8"),
    )
    with pytest.raises(ValidationError, match="current input"):
        private_context(classification="factual_business", pending=(stale,))
    proposal_slot = pending_slot(
        "proposal_amount", "required_target_missing", c.P2ProposalOperation.EXPENSE_CREATE,
    )
    proposal_context = private_context(
        classification="proposal_intent", target_resolved=True, pending=(proposal_slot,),
    )
    assert c.parse_p2_decision(
        {"kind": "clarify", "prompt": "请问金额是多少？", "missing_slots": ["proposal_amount"]},
        proposal_context,
    ).kind == "clarify"


def test_factual_answer_needs_private_per_qev_binding_not_metadata_receipt() -> None:
    scope = scope_dto()
    criteria = digest("1")
    grant, receipt = grant_and_receipt(number=1, operation=c.P2ReadOperation.EXPENSES, scope=scope, criteria=criteria)
    private = private_context(pairs=((grant, receipt),))
    answer = {"kind": "answer", "basis": "fresh_read_receipts", "text": "有一项早餐。", "citations": [qev(1)]}
    assert isinstance(c.parse_p2_decision(answer, private), c.P2AnswerDecision)

    label = label_dto(entity_ref=ref(81), kind="participant", scope_ref=ref(1), source_kind="participants")
    actor = c.P2CurrentActorBinding(
        actor_ref=ref(82), activity_ref=ref(1), participant_ref=ref(81),
        source_kind="participant_claims.current_auth_user", observed_at=NOW,
        scope_financial_version=8, source_receipt_ref=label.source_receipt_ref,
    )
    metadata_bootstrap = context_dto(scope=scope, actor=actor, labels=(label,))
    assert c.parse_p2_model_context(metadata_bootstrap).query_evidence == ()
    no_query = private_context(pairs=())
    with pytest.raises(ValueError, match="source grant and fresh query evidence"):
        c.parse_p2_decision(answer, no_query)

    no_bindings = private.model_copy(update={"query_authorization_bindings": ()})
    with pytest.raises(ValueError, match="per-query authorization binding"):
        c.parse_p2_decision(answer, no_bindings)


def test_cited_subset_is_authorized_per_qev_and_uncited_binding_is_not_required() -> None:
    scope = scope_dto()
    pair1 = grant_and_receipt(
        number=1, operation=c.P2ReadOperation.EXPENSES, scope=scope, criteria=digest("1"),
        expires=NOW - timedelta(seconds=1),
    )
    pair2 = grant_and_receipt(number=2, operation=c.P2ReadOperation.DEBTS, scope=scope, criteria=digest("2"))
    context = private_context(pairs=(pair1, pair2))
    answer = {"kind": "answer", "basis": "fresh_read_receipts", "text": "债务已核对。", "citations": [qev(2)]}
    assert isinstance(c.parse_p2_decision(answer, context), c.P2AnswerDecision)
    unbound = context.model_copy(update={"query_authorization_bindings": context.query_authorization_bindings[:1]})
    with pytest.raises(ValueError, match="lacks a per-query"):
        c.parse_p2_decision(answer, unbound)


def test_private_intent_guard_is_bound_to_the_v3_tuple_and_revalidates_copy_bypass() -> None:
    scope = scope_dto()
    pair = grant_and_receipt(number=7, operation=c.P2ReadOperation.EXPENSES, scope=scope, criteria=digest("a"))
    trusted = private_context(pairs=(pair,))
    bad_versions = c.P2V3ProtocolVersions.model_construct(
        api="2.1.0", semantic="2.0.0", operations="2.1.0", trajectory="2.0.0"
    )
    bypassed = trusted.model_copy(update={"versions": bad_versions})
    answer = {"kind": "answer", "basis": "fresh_read_receipts", "text": "结果。", "citations": [qev(7)]}
    with pytest.raises(ValueError, match="failed revalidation"):
        c.parse_p2_decision(answer, bypassed)


def test_expired_cited_grant_and_cross_scope_binding_fail_closed() -> None:
    scope = scope_dto()
    expired_pair = grant_and_receipt(
        number=3, operation=c.P2ReadOperation.EXPENSES, scope=scope,
        criteria=digest("3"), expires=NOW - timedelta(seconds=1),
    )
    expired_context = private_context(pairs=(expired_pair,))
    answer = {"kind": "answer", "basis": "fresh_read_receipts", "text": "结果。", "citations": [qev(3)]}
    with pytest.raises(ValueError, match="expired"):
        c.parse_p2_decision(answer, expired_context)

    foreign_scope = scope_dto(activity=ref(90))
    foreign_pair = grant_and_receipt(number=4, operation=c.P2ReadOperation.DEBTS, scope=foreign_scope, criteria=digest("4"))
    with pytest.raises(ValidationError, match="scope"):
        private_context(pairs=(expired_pair if False else grant_and_receipt(number=5, operation=c.P2ReadOperation.EXPENSES, scope=scope, criteria=digest("5")), foreign_pair))


def test_stale_generation_input_and_continuation_do_not_reuse_prior_authority() -> None:
    scope = scope_dto()
    pair = grant_and_receipt(number=1, operation=c.P2ReadOperation.EXPENSES, scope=scope, criteria=digest("a"))
    stale = pair[1].model_copy(update={"generation": 2})
    with pytest.raises(ValidationError):
        private_context(pairs=((pair[0], stale),))

    expired_pair = grant_and_receipt(
        number=1, operation=c.P2ReadOperation.EXPENSES, scope=scope,
        criteria=digest("a"), expires=NOW - timedelta(seconds=1),
    )
    continuation = {
        "kind": "read", "message_type": "continue_request", "profile_id": c.P2_V3_CANDIDATE_PROFILE_ID,
        "versions": VERSIONS, "query_ref": expired_pair[1].query_ref,
        "next_page_ref": expired_pair[1].next_page_ref,
    }
    expired_context = private_context(pairs=(expired_pair,))
    with pytest.raises(ValueError, match="expired"):
        c.parse_p2_decision(continuation, expired_context)
    wrong = dict(continuation)
    wrong["query_ref"] = ref(999)
    valid_pair = grant_and_receipt(number=1, operation=c.P2ReadOperation.EXPENSES, scope=scope, criteria=digest("a"))
    with pytest.raises(ValueError, match="prior query receipt"):
        c.parse_p2_decision(wrong, private_context(pairs=(valid_pair,)))


def test_v3_schema_bundle_is_isolated_and_required_title_is_explicit() -> None:
    schemas = c.export_p2_v3_json_schemas()
    assert set(schemas) == {
        "protocol_versions", "read_request", "model_context", "decision", "query_evidence", "fact",
        "current_actor", "entity_display_label",
    }
    assert schemas["model_context"]["properties"]["profile_id"]["const"] == c.P2_V3_CANDIDATE_PROFILE_ID
    assert "pending_clarifications" in schemas["model_context"]["required"]
    pending_def = schemas["model_context"]["$defs"]["P2PendingClarificationProjection"]
    assert set(pending_def["properties"]) == {"slot", "reason", "operation"}
    assert {"slot", "reason"} <= set(pending_def["required"])
    version_properties = schemas["protocol_versions"]["properties"]
    assert {name: schema["const"] for name, schema in version_properties.items()} == VERSIONS
    expense_schema = schemas["fact"]["$defs"]["ExpenseFact"]
    assert "title" in expense_schema["required"]
    assert expense_schema["properties"]["title"]["maxLength"] == 200
    assert "execution_key_version" not in schemas["protocol_versions"]["properties"]

