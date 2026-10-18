"""Synthetic CPU checks for the disabled P2 read-paged candidate contracts."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from agent.app import p2_read_contracts as c


REF_ACTIVITY = "ref_" + "A" * 22
REF_UNIT = "ref_" + "B" * 22
REF_EXPENSE = "ref_" + "C" * 22
REF_PARTICIPANT = "ref_" + "D" * 22
REF_ACCOUNT = "ref_" + "E" * 22
REF_DEBT = "ref_" + "F" * 22
REF_QUERY = "ref_" + "G" * 22
REF_RESULT = "ref_" + "H" * 22
REF_CRITERIA = "ref_" + "I" * 22
REF_SOURCE = "ref_" + "J" * 22
REF_GRANT = "ref_" + "K" * 22
REF_NEXT = "ref_" + "L" * 22
REF_TURN = "ref_" + "T" * 22
QEV = "qev_" + "M" * 22
DIGEST = "a" * 64
INPUT_DIGEST = "b" * 64
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def versions() -> dict[str, str]:
    return {"api": "2.1.0", "semantic": "2.0.0", "operations": "2.1.0", "trajectory": "2.0.0"}


def activity_scope() -> dict[str, str]:
    return {
        "scope_kind": "activity",
        "scope_ref": REF_ACTIVITY,
        "activity_ref": REF_ACTIVITY,
        "ledger_unit_ref": None,
    }


def ledger_unit_scope() -> dict[str, str]:
    return {
        "scope_kind": "ledger_unit",
        "scope_ref": REF_UNIT,
        "activity_ref": REF_ACTIVITY,
        "ledger_unit_ref": REF_UNIT,
    }


def query_payload(operation: c.P2ReadOperation, criteria: dict, *, scope: dict | None = None) -> dict:
    return {
        "kind": "read",
        "message_type": "query_request",
        "profile_id": c.P2_CANDIDATE_PROFILE_ID,
        "versions": versions(),
        "operation": operation,
        "criteria": criteria,
        "scope": scope,
    }


READ_CASES = [
    (c.P2ReadOperation.ACTIVITIES, {"kind": "activities", "status": "any"}, None),
    (c.P2ReadOperation.EXPENSES, {"kind": "expenses", "activity_ref": REF_ACTIVITY}, activity_scope()),
    (c.P2ReadOperation.DEBTS, {"kind": "debts", "activity_ref": REF_ACTIVITY}, activity_scope()),
    (c.P2ReadOperation.REFUND_EVENTS, {"kind": "refund_events", "activity_ref": REF_ACTIVITY}, activity_scope()),
    (
        c.P2ReadOperation.PREPAYMENT_ACCOUNTS,
        {"kind": "prepayment_accounts", "activity_ref": REF_ACTIVITY},
        activity_scope(),
    ),
    (
        c.P2ReadOperation.PREPAYMENT_USAGES,
        {"kind": "prepayment_usages", "activity_ref": REF_ACTIVITY, "expense_ref": REF_EXPENSE},
        activity_scope(),
    ),
    (
        c.P2ReadOperation.PREPAYMENT_RETURN_EVENTS,
        {"kind": "prepayment_return_events", "activity_ref": REF_ACTIVITY},
        activity_scope(),
    ),
]


def fresh_receipt(
    *,
    operation: c.P2ReadOperation = c.P2ReadOperation.EXPENSES,
    scope_ref: str | None = REF_ACTIVITY,
    query_ref: str = REF_QUERY,
    criteria_digest: str = DIGEST,
    next_page_ref: str | None = None,
    generation: int = 1,
    owner_turn_ref: str = REF_TURN,
    input_digest: str = INPUT_DIGEST,
) -> c.P2FreshQueryEvidenceRef:
    return c.P2FreshQueryEvidenceRef(
        query_evidence_ref=QEV,
        query_ref=query_ref,
        principal_ref=REF_PARTICIPANT,
        owner_turn_ref=owner_turn_ref,
        generation=generation,
        source_input_seq=7,
        input_digest=input_digest,
        operation=operation,
        scope_ref=scope_ref,
        criteria_digest=criteria_digest,
        observed_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=1),
        next_page_ref=next_page_ref,
    )


def source_grant(
    operation: c.P2ReadOperation,
    scope: c.P2Scope | None,
    criteria_digest: str = DIGEST,
    generation: int = 1,
) -> c.P2SourceAuthorizationGrant:
    return c.P2SourceAuthorizationGrant(
        principal_ref=REF_PARTICIPANT,
        owner_turn_ref=REF_TURN,
        generation=generation,
        source_input_seq=7,
        input_digest=INPUT_DIGEST,
        operation=operation,
        scope=scope,
        criteria_digest=criteria_digest,
        expires_at=NOW + timedelta(minutes=1),
        grant_ref=REF_GRANT,
    )


def intent_context(**fields) -> c.P2IntentContext:
    return c.P2IntentContext(
        principal_ref=REF_PARTICIPANT,
        owner_turn_ref=REF_TURN,
        generation=1,
        source_input_seq=7,
        input_digest=INPUT_DIGEST,
        **fields,
    )


@pytest.mark.parametrize("operation,criteria,scope", READ_CASES)
def test_all_seven_read_query_shapes(operation, criteria, scope):
    parsed = c.parse_p2_read_request(query_payload(operation, criteria, scope=scope))
    assert isinstance(parsed, c.P2ReadQueryRequest)
    assert parsed.operation == operation
    assert parsed.versions == c.P2_VERSIONS


def test_version_tuple_is_exact_and_has_no_execution_key():
    assert set(c.P2_VERSIONS.model_dump()) == {"api", "semantic", "operations", "trajectory"}
    bad = query_payload(c.P2ReadOperation.ACTIVITIES, {"kind": "activities"})
    bad["versions"]["api"] = "2.2.0"
    with pytest.raises(ValidationError):
        c.parse_p2_read_request(bad)
    with pytest.raises(ValidationError):
        c.parse_p2_read_request({**query_payload(c.P2ReadOperation.ACTIVITIES, {"kind": "activities"}), "execution_key": "x"})


def test_operation_criteria_scope_and_control_message_fail_closed():
    bad_pair = query_payload(c.P2ReadOperation.DEBTS, {"kind": "expenses", "activity_ref": REF_ACTIVITY}, scope=activity_scope())
    with pytest.raises(ValidationError):
        c.parse_p2_read_request(bad_pair)
    missing_scope = query_payload(
        c.P2ReadOperation.PREPAYMENT_ACCOUNTS,
        {"kind": "prepayment_accounts", "activity_ref": REF_ACTIVITY},
    )
    with pytest.raises(ValidationError):
        c.parse_p2_read_request(missing_scope)
    bad_scope = activity_scope()
    bad_scope["scope_ref"] = REF_UNIT
    with pytest.raises(ValidationError):
        c.parse_p2_read_request(
            query_payload(c.P2ReadOperation.EXPENSES, {"kind": "expenses", "activity_ref": REF_ACTIVITY}, scope=bad_scope)
        )
    bad_continue = {
        "kind": "read",
        "message_type": "continue_request",
        "profile_id": c.P2_CANDIDATE_PROFILE_ID,
        "versions": versions(),
        "query_ref": REF_QUERY,
        "next_page_ref": REF_NEXT,
        "operation": "read.continue",
    }
    with pytest.raises(ValidationError):
        c.parse_p2_read_request(bad_continue)


def test_json_wire_parser_preserves_unicode_and_exact_iso_dates():
    payload = query_payload(
        c.P2ReadOperation.EXPENSES,
        {"kind": "expenses", "activity_ref": REF_ACTIVITY, "from_date": "2026-10-01", "title_contains": "餐费—Café"},
        scope=activity_scope(),
    )
    parsed = c.parse_p2_read_request(json.dumps(payload, ensure_ascii=False))
    assert parsed.criteria.from_date == date(2026, 10, 1)
    assert parsed.criteria.title_contains == "餐费—Café"
    assert parsed.criteria.title_contains.encode("utf-8") != "餐费—Café".encode("utf-8")
    decoded = json.loads(json.dumps(payload, ensure_ascii=False))
    assert c.parse_p2_read_request(decoded).criteria.title_contains == "餐费—Café"


def test_json_wire_operation_string_parses_from_bytes_and_loaded_dict():
    payload = query_payload(
        c.P2ReadOperation.EXPENSES,
        {"kind": "expenses", "activity_ref": REF_ACTIVITY},
        scope=activity_scope(),
    )
    payload["operation"] = "read.expenses"
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    parsed_bytes = c.parse_p2_read_request(raw)
    parsed_dict = c.parse_p2_read_request(json.loads(raw))
    assert parsed_bytes.operation == c.P2ReadOperation.EXPENSES
    assert parsed_dict.operation == c.P2ReadOperation.EXPENSES


def test_ledger_unit_prepayment_usage_keeps_expense_hint_optional():
    child_discovery = query_payload(
        c.P2ReadOperation.PREPAYMENT_USAGES,
        {"kind": "prepayment_usages", "activity_ref": REF_ACTIVITY},
        scope=ledger_unit_scope(),
    )
    parsed_discovery = c.parse_p2_read_request(child_discovery)
    assert parsed_discovery.scope.scope_kind == "ledger_unit"
    assert parsed_discovery.criteria.expense_ref is None

    with_child = query_payload(
        c.P2ReadOperation.PREPAYMENT_USAGES,
        {"kind": "prepayment_usages", "activity_ref": REF_ACTIVITY, "expense_ref": REF_EXPENSE},
        scope=ledger_unit_scope(),
    )
    parsed = c.parse_p2_read_request(json.dumps(with_child))
    assert parsed.scope.scope_kind == "ledger_unit"
    assert parsed.criteria.expense_ref == REF_EXPENSE
    # Membership of the opaque Expense in this unit still requires source auth.


def test_source_precision_strict_int64_nullable_and_zero_base():
    assert c.parse_source_numeric_lexeme("9999999999999999.9999", precision=20, scale=4) == "9999999999999999.9999"
    assert c.parse_source_numeric_lexeme("9999999999999999999.9", precision=20, scale=1) == "9999999999999999999.9"
    assert c.parse_source_numeric_lexeme("9999999999.9999999999", precision=20, scale=10) == "9999999999.9999999999"
    assert c.parse_financial_version(c.MAX_FINANCIAL_VERSION) == c.MAX_FINANCIAL_VERSION
    for invalid in (True, 1.0, "1", -1, c.MAX_FINANCIAL_VERSION + 1):
        with pytest.raises(ValueError):
            c.parse_financial_version(invalid)
    for invalid in ("10000000000000000.00000", "1e3", 1.0, True):
        with pytest.raises(ValueError):
            c.parse_source_numeric_lexeme(invalid, precision=20, scale=4)
    assert c.parse_json_source_object('{"amount":1.2300,"financial_version":1}') == {
        "amount": "1.2300", "financial_version": 1,
    }
    with pytest.raises(ValueError):
        c.parse_json_source_object('{"amount":1,"amount":2}')


def test_expense_debt_source_parser_preserves_nulls_and_never_invents_row_version():
    legacy = c.parse_expense_debt_source_amounts({
        "amount": "0", "original_amount": None, "original_currency": None, "fx_rate": None,
    })
    assert legacy.amount == "0"
    assert legacy.original_amount is None and legacy.original_currency is None and legacy.fx_rate is None
    currency_only = c.parse_expense_debt_source_amounts({
        "amount": "1.2", "original_amount": None, "original_currency": "USD", "fx_rate": None,
    })
    assert currency_only.original_amount is None and currency_only.original_currency == "USD"
    assert not hasattr(currency_only, "financial_version")
    for bad in (
        {"amount": 0, "original_amount": None, "original_currency": None, "fx_rate": None},
        {"amount": "0", "original_amount": None, "original_currency": None},
        {"amount": "1.2", "original_amount": None, "original_currency": None, "fx_rate": "0"},
    ):
        with pytest.raises((ValueError, ValidationError)):
            c.parse_expense_debt_source_amounts(bad)
    with pytest.raises(ValueError):
        c.parse_expense_debt_source_amounts({
            "amount": "1.2", "original_amount": None, "original_currency": None, "fx_rate": None,
            "financial_version": 0,
        })

    debt = c.DebtFact(
        fact_kind="debt",
        debt_ref=REF_DEBT,
        scope_ref=REF_UNIT,
        activity_ref=REF_ACTIVITY,
        ledger_unit_ref=REF_UNIT,
        expense_ref=REF_EXPENSE,
        debtor_ref=REF_PARTICIPANT,
        creditor_ref=REF_UNIT,
        original_amount=None,
        original_currency=None,
        base_amount="0",
        base_currency="CNY",
        financial_version=0,
        query_evidence_ref=QEV,
    )
    assert debt.original_amount is None and debt.base_amount == "0"
    assert debt.debt_source_variant == c.P2_DEBT_SOURCE_VARIANT
    with pytest.raises(ValidationError):
        c.DebtFact.model_validate({**debt.model_dump(), "financial_version": True})
    with pytest.raises(ValidationError):
        c.DebtFact.model_validate({**debt.model_dump(), "unexpected": "no"})


def test_refund_sign_zero_base_and_public_lineage_only():
    base = {
        "fact_kind": "refund_event",
        "refund_ref": REF_EXPENSE,
        "scope_ref": REF_ACTIVITY,
        "signed_original_amount": "-0.0001",
        "original_currency": "CNY",
        "signed_base_amount": "0",
        "base_currency": "CNY",
        "occurred_at": NOW,
        "parent_expense_ref": REF_EXPENSE,
        "lineage_status": "verified_same_activity_parent",
        "lineage_basis": "public_parent_relationship",
        "refund_recipient_ref": None,
        "financial_version": 0,
        "query_evidence_ref": QEV,
    }
    assert c.RefundEventFact(**base).signed_base_amount == "0"
    with pytest.raises(ValidationError):
        c.RefundEventFact(**{**base, "lineage_basis": "private_immutable_marker"})
    with pytest.raises(ValidationError):
        c.RefundEventFact(**{**base, "signed_original_amount": "1"})
    with pytest.raises(ValidationError):
        c.RefundEventFact(**{**base, "signed_base_amount": "0.1"})
    unknown_parent = {**base, "parent_expense_ref": None, "lineage_status": "unverified", "lineage_basis": None}
    assert c.RefundEventFact(**unknown_parent).lineage_status == "unverified"


def test_activity_expense_and_return_fact_shapes_keep_direction_and_base_independent():
    activity = c.ActivityFact(
        fact_kind="activity", activity_ref=REF_ACTIVITY, activity_kind="group",
        name="Synthetic trip", base_currency="CNY", status="active", observed_at=NOW,
        context_version="activity-context-v1", query_evidence_ref=QEV,
    )
    assert activity.base_currency == "CNY"
    allocation = c.ParticipantAllocationFact(
        participant_ref=REF_PARTICIPANT, role="payer", signed_original_amount="1.2000",
        original_currency="USD", signed_base_amount="0", base_currency="CNY",
    )
    expense = c.ExpenseFact(
        fact_kind="expense", expense_ref=REF_EXPENSE, scope_ref=REF_UNIT, occurred_at=NOW,
        signed_original_amount="1.2000", original_currency="USD", signed_base_amount="0",
        base_currency="CNY", payer_split_lines=(allocation,), expense_version=1,
        financial_version=0, query_evidence_ref=QEV,
    )
    assert expense.signed_original_amount == "1.2000" and expense.signed_base_amount == "0"
    returned = c.PrepaymentReturnEventFact(
        fact_kind="prepayment_return_event", return_event_ref=REF_RESULT, activity_ref=REF_ACTIVITY,
        amount="1.0000", currency="CNY", occurred_at=NOW, from_ref=REF_ACCOUNT,
        from_role="custodian", to_ref=REF_PARTICIPANT, to_role="owner",
        transfer_component_match=False, financial_version=0, query_evidence_ref=QEV,
    )
    assert returned.from_role == "custodian" and returned.to_role == "owner"
    with pytest.raises(ValidationError):
        c.PrepaymentReturnEventFact.model_validate({**returned.model_dump(), "amount": "0"})


def test_candidate_context_uses_reviewed_guard_shape_and_keeps_safe_proposal_reachable():
    common = {
        "profile_id": c.P2_CANDIDATE_PROFILE_ID,
        "versions": versions(),
        "context_version": "ctx-synthetic-v1",
        "generation": 1,
        "input_text": "这笔账怎么分？",
        "scope_authorization": {"status": "absent", "scope": None, "authorization_receipt_ref": None},
        "query_evidence": [],
        "facts": [],
        "recent_messages": [],
    }
    ambiguous = {
        **common,
        "trusted_intent": {
            "authority": "server", "classification": "ambiguous",
            "requires_authoritative_evidence": True, "source_input_seq": 0,
            "classifier_version": "intent-synthetic-v1",
        },
        "guard": {
            "source_free_business_answer_allowed": False,
            "allowed_decision_kinds": ["clarify", "read"],
            "allowed_read_operations": ["read.activities"],
            "fresh_receipt_refs": [],
        },
    }
    assert c.P2ModelContext.model_validate_json(json.dumps(ambiguous)).trusted_intent.classification == "ambiguous"
    bad_ambiguous = json.loads(json.dumps(ambiguous))
    bad_ambiguous["guard"]["allowed_decision_kinds"] = ["answer", "read"]
    with pytest.raises(ValidationError):
        c.P2ModelContext.model_validate_json(json.dumps(bad_ambiguous))
    proposal = {
        **common,
        "trusted_intent": {
            "authority": "server", "classification": "proposal_intent",
            "requires_authoritative_evidence": False, "source_input_seq": 0,
            "classifier_version": "proposal-synthetic-v1",
        },
        "guard": {
            "source_free_business_answer_allowed": False,
            "allowed_decision_kinds": ["propose", "clarify"],
            "allowed_read_operations": [], "fresh_receipt_refs": [],
            "proposal_clarification_required": False,
            "allowed_proposal_operations": ["expense.update"],
        },
    }
    assert c.P2ModelContext.model_validate_json(json.dumps(proposal)).guard.allowed_proposal_operations == (
        c.P2ProposalOperation.EXPENSE_UPDATE,
    )


def test_unresolved_proposal_context_is_clarification_only_and_stays_source_guarded():
    common = {
        "profile_id": c.P2_CANDIDATE_PROFILE_ID,
        "versions": versions(),
        "context_version": "ctx-proposal-unresolved-v1",
        "generation": 1,
        "input_text": "把那笔消费改一下",
        "trusted_intent": {
            "authority": "server", "classification": "proposal_intent",
            "requires_authoritative_evidence": False, "source_input_seq": 3,
            "classifier_version": "proposal-synthetic-v1",
        },
        "scope_authorization": {"status": "unresolved", "scope": None, "authorization_receipt_ref": None},
        "query_evidence": [], "facts": [], "recent_messages": [],
        "guard": {
            "source_free_business_answer_allowed": False,
            "allowed_decision_kinds": ["clarify"],
            "allowed_read_operations": [],
            "fresh_receipt_refs": [],
            "proposal_clarification_required": True,
            "allowed_proposal_operations": [],
        },
    }
    parsed = c.P2ModelContext.model_validate_json(json.dumps(common, ensure_ascii=False))
    assert parsed.guard.allowed_decision_kinds == ("clarify",)
    assert parsed.guard.allowed_proposal_operations == ()

    injections = [
        {"guard": {"allowed_decision_kinds": ["propose", "clarify"], "allowed_proposal_operations": ["expense.update"]}},
        {"guard": {"allowed_decision_kinds": ["read", "clarify"], "allowed_read_operations": ["read.expenses"]}},
        {"guard": {"allowed_decision_kinds": ["answer", "clarify"]}},
        {"guard": {"allowed_proposal_operations": ["expense.update"]}},
        {"guard": {"source_free_business_answer_allowed": True}},
    ]
    for injection in injections:
        bad = json.loads(json.dumps(common, ensure_ascii=False))
        bad["guard"].update(injection["guard"])
        with pytest.raises(ValidationError):
            c.P2ModelContext.model_validate_json(json.dumps(bad, ensure_ascii=False))

    trusted = intent_context(
        classification="proposal_intent", scope_status="unresolved", proposal_target_resolved=False,
        clarification_required=True, classifier_source="server_policy", classifier_version="proposal-synthetic-v1",
    )
    clarify = {"kind": "clarify", "prompt": "是哪一笔消费？", "missing_slots": ["expense"]}
    assert c.parse_p2_decision(clarify, trusted).kind == "clarify"
    for forbidden in (
        {"kind": "propose", "operation": "expense.update", "recognized_intent_text": "改消费"},
        {"kind": "read", "message_type": "continue_request", "profile_id": c.P2_CANDIDATE_PROFILE_ID,
         "versions": versions(), "query_ref": REF_QUERY, "next_page_ref": REF_NEXT},
        {"kind": "answer", "basis": "non_business_general", "text": "已改", "citations": []},
    ):
        with pytest.raises(ValueError):
            c.parse_p2_decision(forbidden, trusted)


def test_query_evidence_backend_stage_and_page_are_bound_to_candidate():
    summary = c.P2PageSummary(
        pages_seen=1, has_more=False, truncated=False, source_query_complete=True,
        model_projection_complete=True, range_contiguous=True, stable_total_verified=True,
        source_version_fenced=True, unique_items_verified=True, expected_total=0,
    )
    evidence = c.P2QueryEvidence(
        profile_id=c.P2_CANDIDATE_PROFILE_ID, versions=c.P2_VERSIONS,
        query_evidence_ref=QEV, query_ref=REF_QUERY, result_ref=REF_RESULT,
        operation=c.P2ReadOperation.DEBTS, criteria_ref=REF_CRITERIA,
        criteria_digest=DIGEST, normalized_criteria_digest=DIGEST,
        backend_criteria_stage="scope_only", source_kind="debts", source_ref=REF_SOURCE,
        source_version="synthetic-v1", observed_at=NOW, simulation=False,
        returned_count=0, matched_count=0, source_total=0, matched_total=0,
        page_count=1, query_zero_classification="backend_zero", source_query_complete=True,
        model_projection_complete=True, matching_fact_refs=(), financial_versions=(), page=summary,
        query_digest=DIGEST, body_digest=DIGEST, projection_digest=DIGEST,
    )
    page = c.P2PageProjection[c.P2Fact](
        items=(), completeness=c.ReadCompleteness.COMPLETE, has_more=False,
        next_page_ref=None, page_index=0, range_contiguous=True,
        stable_total_verified=True, source_version_fenced=True, unique_items_verified=True,
        expected_total=0,
    )
    result = c.P2ReadBackendResult(operation=c.P2ReadOperation.DEBTS, query_evidence=evidence, page=page)
    assert result.query_evidence.backend_criteria_stage == "scope_only"
    with pytest.raises(ValidationError):
        c.P2QueryEvidence.model_validate({**evidence.model_dump(), "backend_criteria_stage": "server_filter"})


def test_source_completion_is_independent_from_model_page_completion():
    summary = c.P2PageSummary(
        pages_seen=1, has_more=True, truncated=True, source_query_complete=True,
        model_projection_complete=False, range_contiguous=True, stable_total_verified=True,
        source_version_fenced=True, unique_items_verified=True, expected_total=17,
    )
    assert summary.source_query_complete is True
    assert summary.model_projection_complete is False
    evidence = c.P2QueryEvidence(
        profile_id=c.P2_CANDIDATE_PROFILE_ID, versions=c.P2_VERSIONS,
        query_evidence_ref=QEV, query_ref=REF_QUERY, result_ref=REF_RESULT,
        operation=c.P2ReadOperation.DEBTS, criteria_ref=REF_CRITERIA,
        criteria_digest=DIGEST, normalized_criteria_digest=DIGEST,
        backend_criteria_stage="scope_only", source_kind="debts", source_ref=REF_SOURCE,
        source_version="synthetic-v1", observed_at=NOW, simulation=False,
        returned_count=17, matched_count=17, source_total=17, matched_total=17,
        page_count=1, query_zero_classification="nonzero", source_query_complete=True,
        model_projection_complete=False, matching_fact_refs=(), financial_versions=(), page=summary,
        query_digest=DIGEST, body_digest=DIGEST, projection_digest=DIGEST,
    )
    page = c.P2PageProjection[c.P2Fact](
        items=(), completeness=c.ModelProjectionCompleteness.PARTIAL, has_more=True,
        next_page_ref=REF_NEXT, page_index=0, range_contiguous=True,
        stable_total_verified=True, source_version_fenced=True, unique_items_verified=True,
        expected_total=17,
    )
    result = c.P2ReadBackendResult(operation=c.P2ReadOperation.DEBTS, query_evidence=evidence, page=page)
    assert result.query_evidence.source_query_complete is True
    assert result.page.completeness == c.ModelProjectionCompleteness.PARTIAL
    summary_without_more = summary.model_copy(update={"has_more": False, "truncated": False})
    evidence_without_more = evidence.model_copy(update={"page": summary_without_more})
    complete_page_without_more = page.model_copy(update={
        "completeness": c.ModelProjectionCompleteness.COMPLETE,
        "has_more": False,
        "next_page_ref": None,
    })
    with pytest.raises(ValidationError, match="model_projection_complete"):
        c.P2ReadBackendResult(
            operation=c.P2ReadOperation.DEBTS,
            query_evidence=evidence_without_more,
            page=complete_page_without_more,
        )


def test_model_context_facts_require_matching_operation_evidence():
    summary = c.P2PageSummary(
        pages_seen=1, has_more=False, truncated=False, source_query_complete=True,
        model_projection_complete=True, range_contiguous=True, stable_total_verified=True,
        source_version_fenced=True, unique_items_verified=True, expected_total=1,
    )
    evidence = c.P2QueryEvidence(
        profile_id=c.P2_CANDIDATE_PROFILE_ID, versions=c.P2_VERSIONS,
        query_evidence_ref=QEV, query_ref=REF_QUERY, result_ref=REF_RESULT,
        operation=c.P2ReadOperation.ACTIVITIES, criteria_ref=REF_CRITERIA,
        criteria_digest=DIGEST, normalized_criteria_digest=DIGEST,
        backend_criteria_stage="scope_only", source_kind="activities", source_ref=REF_SOURCE,
        source_version="synthetic-v1", observed_at=NOW, simulation=False,
        returned_count=1, matched_count=1, source_total=1, matched_total=1,
        page_count=1, query_zero_classification="nonzero", source_query_complete=True,
        model_projection_complete=True, matching_fact_refs=(REF_ACTIVITY,), financial_versions=(),
        page=summary, query_digest=DIGEST, body_digest=DIGEST, projection_digest=DIGEST,
    )
    fact = c.ActivityFact(
        fact_kind="activity", activity_ref=REF_ACTIVITY, activity_kind="group", name="Synthetic",
        base_currency="CNY", status="active", observed_at=NOW, context_version="ctx-v1",
        query_evidence_ref=QEV,
    )
    context = {
        "profile_id": c.P2_CANDIDATE_PROFILE_ID,
        "versions": versions(),
        "context_version": "ctx-v1",
        "generation": 1,
        "input_text": "活动有哪些？",
        "trusted_intent": {
            "authority": "server", "classification": "factual_business",
            "requires_authoritative_evidence": True, "source_input_seq": 0,
            "classifier_version": "classifier-v1",
        },
        "scope_authorization": {
            "status": "verified", "scope": activity_scope(), "authorization_receipt_ref": "auth_" + "N" * 22,
        },
        "guard": {
            "source_free_business_answer_allowed": False,
            "allowed_decision_kinds": ["answer", "clarify", "read"],
            "allowed_read_operations": ["read.activities"],
            "fresh_receipt_refs": [QEV],
        },
        "query_evidence": [evidence.model_dump(mode="json")],
        "facts": [fact.model_dump(mode="json")],
        "recent_messages": [],
    }
    parsed = c.P2ModelContext.model_validate_json(json.dumps(context, ensure_ascii=False))
    assert len(parsed.facts) == 1
    bad = json.loads(json.dumps(context, ensure_ascii=False))
    bad["query_evidence"][0]["matching_fact_refs"] = []
    with pytest.raises(ValidationError):
        c.P2ModelContext.model_validate_json(json.dumps(bad, ensure_ascii=False))


def _continuation_model_context_payload(*, has_more=True, continuations=(), read_allowed=True):
    page = c.P2PageSummary(
        pages_seen=1, has_more=has_more, truncated=has_more, source_query_complete=True,
        model_projection_complete=not has_more, range_contiguous=True, stable_total_verified=True,
        source_version_fenced=True, unique_items_verified=True, expected_total=1,
    )
    evidence = c.P2QueryEvidence(
        profile_id=c.P2_CANDIDATE_PROFILE_ID, versions=c.P2_VERSIONS,
        query_evidence_ref=QEV, query_ref=REF_QUERY, result_ref=REF_RESULT,
        operation=c.P2ReadOperation.EXPENSES, criteria_ref=REF_CRITERIA,
        criteria_digest=DIGEST, normalized_criteria_digest=DIGEST,
        backend_criteria_stage="scope_only", source_kind="expenses", source_ref=REF_SOURCE,
        source_version="synthetic-source-v1", observed_at=NOW, simulation=False,
        returned_count=1, matched_count=1, source_total=1, matched_total=1,
        page_count=1, query_zero_classification="nonzero", source_query_complete=True,
        model_projection_complete=not has_more, matching_fact_refs=(), financial_versions=(), page=page,
        query_digest=DIGEST, body_digest=DIGEST, projection_digest=DIGEST,
    )
    return {
        "profile_id": c.P2_CANDIDATE_PROFILE_ID,
        "versions": versions(),
        "context_version": "ctx-continuation-synthetic-v1",
        "generation": 1,
        "input_text": "继续查看下一页",
        "trusted_intent": {
            "authority": "server", "classification": "factual_business",
            "requires_authoritative_evidence": True, "source_input_seq": 7,
            "classifier_version": "synthetic-classifier-v1",
        },
        "scope_authorization": {
            "status": "verified", "scope": activity_scope(),
            "authorization_receipt_ref": "auth_" + "P" * 22,
        },
        "guard": {
            "source_free_business_answer_allowed": False,
            "allowed_decision_kinds": ["clarify", "read"] if read_allowed else ["clarify"],
            "allowed_read_operations": ["read.expenses"] if read_allowed else [],
            "fresh_receipt_refs": [QEV],
        },
        "query_evidence": [evidence.model_dump(mode="json")],
        "continuations": [item.model_dump(mode="json") if isinstance(item, c.P2ContinuationHint) else item for item in continuations],
        "facts": [],
        "recent_messages": [],
    }


def test_model_context_continuation_hints_are_public_fresh_and_page_bound():
    hint = c.P2ContinuationHint(
        query_evidence_ref=QEV, query_ref=REF_QUERY, next_page_ref=REF_NEXT,
    )
    payload = _continuation_model_context_payload(continuations=(hint,))
    parsed = c.P2ModelContext.model_validate_json(json.dumps(payload, ensure_ascii=False))
    assert parsed.continuations == (hint,)
    assert parsed.continuations[0].next_page_ref == REF_NEXT

    wrong_qev = _continuation_model_context_payload(continuations=(
        {"query_evidence_ref": "qev_" + "Z" * 22, "query_ref": REF_QUERY, "next_page_ref": REF_NEXT},
    ))
    with pytest.raises(ValidationError, match="fresh receipt ref"):
        c.P2ModelContext.model_validate_json(json.dumps(wrong_qev))

    wrong_query = _continuation_model_context_payload(continuations=(
        {"query_evidence_ref": QEV, "query_ref": REF_UNIT, "next_page_ref": REF_NEXT},
    ))
    with pytest.raises(ValidationError, match="query ref must match"):
        c.P2ModelContext.model_validate_json(json.dumps(wrong_query))

    not_fresh = _continuation_model_context_payload(continuations=(hint,))
    not_fresh["guard"]["fresh_receipt_refs"] = []
    with pytest.raises(ValidationError, match="fresh receipt ref"):
        c.P2ModelContext.model_validate_json(json.dumps(not_fresh))

    no_more = _continuation_model_context_payload(has_more=False, continuations=(hint,))
    with pytest.raises(ValidationError, match="another page"):
        c.P2ModelContext.model_validate_json(json.dumps(no_more))

    missing = _continuation_model_context_payload()
    with pytest.raises(ValidationError, match="requires a continuation hint"):
        c.P2ModelContext.model_validate_json(json.dumps(missing))

    duplicate = _continuation_model_context_payload(continuations=(hint, hint))
    with pytest.raises(ValidationError, match="must each be unique"):
        c.P2ModelContext.model_validate_json(json.dumps(duplicate))


def test_model_context_allows_partial_evidence_without_read_continuation_permission():
    payload = _continuation_model_context_payload(read_allowed=False)
    parsed = c.P2ModelContext.model_validate_json(json.dumps(payload, ensure_ascii=False))
    assert parsed.query_evidence[0].page.has_more is True
    assert parsed.continuations == ()


def test_prepayment_amount_source_domains_do_not_convert_or_fill():
    account = c.PrepaymentAccountFact(
        fact_kind="prepayment_account", account_ref=REF_ACCOUNT, activity_ref=REF_ACTIVITY,
        owner_ref=REF_PARTICIPANT, custodian_ref=REF_UNIT, balance="0.0000", currency="CNY",
        projection_updated_at=NOW, financial_version=0, query_evidence_ref=QEV,
    )
    assert account.balance == "0.0000"
    usage = c.PrepaymentUsageFact(
        fact_kind="prepayment_usage", usage_ref=REF_EXPENSE, account_ref=REF_ACCOUNT,
        expense_ref=REF_EXPENSE, debt_ref=REF_DEBT, activity_ref=REF_ACTIVITY,
        gross_amount="1.0000", amount="1.0000", prepayment_amount="1.0000",
        prepayment_currency="USD", debt_amount="1.0000", debt_currency="EUR",
        base_amount="0", base_currency="CNY", bill_fx_rate="1.1234567890",
        bill_occurred_at=NOW, financial_version=0, query_evidence_ref=QEV,
    )
    assert usage.prepayment_currency != usage.debt_currency and usage.base_amount == "0"
    with pytest.raises(ValidationError):
        c.PrepaymentUsageFact.model_validate({**usage.model_dump(), "base_currency": None})
    with pytest.raises(ValidationError):
        c.PrepaymentUsageFact.model_validate({**usage.model_dump(), "bill_fx_rate": "0"})
    with pytest.raises(ValidationError):
        c.PrepaymentUsageFact.model_validate({**usage.model_dump(), "preview": True})


def test_untrusted_ui_uuid_hints_are_separate_from_model_refs():
    hints = c.P2UntrustedUIResolutionHints(
        activity_ids=(UUID("00000000-0000-0000-0000-000000000001"),),
        expense_ids=(UUID("00000000-0000-0000-0000-000000000002"),),
    )
    assert hints.activity_ids and hints.expense_ids
    with pytest.raises(ValidationError):
        c.P2UntrustedUIResolutionHints(activity_ids=("00000000-0000-0000-0000-000000000001",))


def test_initial_reads_need_authorization_but_not_a_result_receipt():
    criteria = c.ActivityCriteria(kind="activities", status="active")
    grant = source_grant(c.P2ReadOperation.ACTIVITIES, None, c.p2_criteria_digest(criteria))
    context = intent_context(
        classification="ambiguous",
        scope_status="absent",
        source_authorization_grant=grant,
    )
    payload = {
        "kind": "read",
        "message_type": "query_request",
        "profile_id": c.P2_CANDIDATE_PROFILE_ID,
        "versions": versions(),
        "operation": "read.activities",
        "criteria": {"kind": "activities", "status": "active"},
    }
    assert isinstance(c.parse_p2_decision(json.dumps(payload), context), c.P2ReadQueryRequest)
    assert isinstance(c.parse_p2_decision(json.loads(json.dumps(payload)), context), c.P2ReadQueryRequest)
    no_grant_context = intent_context(classification="ambiguous", scope_status="absent")
    with pytest.raises(ValueError):
        c.parse_p2_decision(payload, no_grant_context)


def test_continuation_requires_private_next_page_query_scope_and_criteria_binding():
    criteria = c.ActivityCriteria(kind="activities", status="any")
    digest = c.p2_criteria_digest(criteria)
    grant = source_grant(c.P2ReadOperation.ACTIVITIES, None, digest)
    receipt = fresh_receipt(
        operation=c.P2ReadOperation.ACTIVITIES,
        scope_ref=None,
        criteria_digest=digest,
        next_page_ref=REF_NEXT,
    )
    context = intent_context(
        classification="ambiguous", scope_status="absent", source_authorization_grant=grant,
        fresh_receipt_refs=(receipt,),
    )
    continuation = {
        "kind": "read", "message_type": "continue_request",
        "profile_id": c.P2_CANDIDATE_PROFILE_ID, "versions": versions(),
        "query_ref": REF_QUERY, "next_page_ref": REF_NEXT,
    }
    assert isinstance(c.parse_p2_decision(continuation, context), c.P2ReadContinueRequest)
    with pytest.raises(ValueError):
        c.parse_p2_decision({**continuation, "next_page_ref": REF_UNIT}, context)
    forged_context = intent_context(
        classification="ambiguous", scope_status="absent", source_authorization_grant=grant,
        fresh_receipt_refs=(fresh_receipt(
            operation=c.P2ReadOperation.ACTIVITIES, scope_ref=None, criteria_digest=DIGEST,
            next_page_ref=REF_NEXT,
        ),),
    )
    with pytest.raises(ValueError):
        c.parse_p2_decision(continuation, forged_context)

    expired_grant = grant.model_copy(update={"expires_at": NOW - timedelta(seconds=1)})
    expired_context = intent_context(
        classification="ambiguous", scope_status="absent", source_authorization_grant=expired_grant,
        fresh_receipt_refs=(receipt,),
    )
    with pytest.raises(ValueError, match="source grant is expired"):
        c.parse_p2_decision(continuation, expired_context)
    cross_generation = fresh_receipt(
        operation=c.P2ReadOperation.ACTIVITIES, scope_ref=None, criteria_digest=digest,
        next_page_ref=REF_NEXT, generation=2,
    )
    with pytest.raises(ValidationError):
        intent_context(
            classification="ambiguous", scope_status="absent", source_authorization_grant=grant,
            fresh_receipt_refs=(cross_generation,),
        )


def test_context_default_deny_fresh_citations_and_authorized_discovery():
    answer = {"kind": "answer", "basis": "fresh_read_receipts", "text": "合成结果", "citations": [QEV]}
    receipt = fresh_receipt()
    for status in ("absent", "unresolved", "not_authorized"):
        context = intent_context(classification="ambiguous", scope_status=status, fresh_receipt_refs=(receipt,))
        with pytest.raises(ValueError):
            c.parse_p2_decision(answer, context)

    scope = c.P2Scope(**activity_scope())
    criteria = c.ExpenseCriteria(kind="expenses", activity_ref=REF_ACTIVITY)
    criteria_digest = c.p2_criteria_digest(criteria)
    grant = source_grant(c.P2ReadOperation.EXPENSES, scope, criteria_digest)
    scoped_receipt = fresh_receipt(criteria_digest=criteria_digest)
    verified = intent_context(
        classification="factual_business", scope_status="verified", scope=scope,
        source_authorization_grant=grant, fresh_receipt_refs=(scoped_receipt,),
        classifier_source="server_policy", classifier_version="intent-classifier-test-v1",
    )
    assert isinstance(c.parse_p2_decision(answer, verified), c.P2AnswerDecision)
    wrong_citation = {**answer, "citations": ["qev_" + "N" * 22]}
    with pytest.raises(ValueError):
        c.parse_p2_decision(wrong_citation, verified)

    discovery_criteria = c.ActivityCriteria(kind="activities", status="any")
    discovery_digest = c.p2_criteria_digest(discovery_criteria)
    discovery_grant = source_grant(
        c.P2ReadOperation.ACTIVITIES, None, discovery_digest
    )
    no_scope_receipt = fresh_receipt(
        operation=c.P2ReadOperation.ACTIVITIES, scope_ref=None, criteria_digest=discovery_digest
    )
    discovery_context = intent_context(
        classification="factual_business", scope_status="absent", source_authorization_grant=discovery_grant,
        fresh_receipt_refs=(no_scope_receipt,), classifier_source="server_policy", classifier_version="test-v1",
    )
    assert isinstance(c.parse_p2_decision({**answer, "citations": [QEV]}, discovery_context), c.P2AnswerDecision)


def test_proposal_only_branch_and_clarification_causality_surface():
    proposal_context = intent_context(
        classification="proposal_intent", scope_status="absent", proposal_target_resolved=True,
        classifier_source="server_policy", classifier_version="proposal-classifier-test-v1",
    )
    proposal = {
        "kind": "propose", "operation": "expense.update", "recognized_intent_text": "把午餐改为公司报销",
    }
    assert isinstance(c.parse_p2_decision(proposal, proposal_context), c.P2ProposalRecognition)
    with pytest.raises(ValueError):
        c.parse_p2_decision(
            {"kind": "answer", "basis": "non_business_general", "text": "回答", "citations": []},
            proposal_context,
        )
    with pytest.raises(ValidationError):
        c.P2ProposalRecognition.model_validate({**proposal, "confirmation_card": {}})
    unresolved = intent_context(
        classification="proposal_intent", scope_status="unresolved", proposal_target_resolved=False,
        clarification_required=True, classifier_source="server_policy", classifier_version="test-v1",
    )
    clarify = {"kind": "clarify", "prompt": "请确认这条消费：咖啡—東京？", "missing_slots": ["expense"]}
    assert c.parse_p2_decision(clarify, unresolved).prompt == "请确认这条消费：咖啡—東京？"
    with pytest.raises(ValueError):
        c.parse_p2_decision(proposal, unresolved)


def test_only_explicit_non_business_allows_source_free_general_answer():
    context = intent_context(
        classification="non_business", scope_status="absent",
        classifier_source="server_policy", classifier_version="nonbusiness-synthetic-v1",
    )
    decision = {
        "kind": "answer", "basis": "non_business_general", "text": "可以。", "citations": [],
    }
    assert isinstance(c.parse_p2_decision(decision, context), c.P2AnswerDecision)
    with pytest.raises(ValueError):
        c.parse_p2_decision({**decision, "basis": "fresh_read_receipts", "citations": [QEV]}, context)


def test_read_result_binds_fact_kind_evidence_and_page_limit():
    page = c.P2PageProjection[c.DebtFact](
        items=(), completeness=c.ReadCompleteness.COMPLETE, has_more=False, next_page_ref=None,
        page_index=0, range_contiguous=True, stable_total_verified=True,
        source_version_fenced=True, unique_items_verified=True, expected_total=0,
    )
    assert page.items == ()
    with pytest.raises(ValidationError):
        c.P2PageProjection[c.DebtFact](
            items=tuple({} for _ in range(17)), completeness="partial", has_more=True,
            next_page_ref=REF_NEXT, page_index=0, range_contiguous=True, stable_total_verified=False,
            source_version_fenced=True, unique_items_verified=True, expected_total=None,
        )


def test_shape_parser_uses_real_json_bytes_and_never_authorizes_first_read():
    payload = query_payload(
        c.P2ReadOperation.ACTIVITIES,
        {"kind": "activities", "status": "any"},
    )
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    parsed = c.parse_p2_decision_shape(raw)
    assert isinstance(parsed, c.P2ReadQueryRequest)
    assert parsed.operation == c.P2ReadOperation.ACTIVITIES

    # Shape parsing does not issue or authorize a source query. The trusted
    # entry point still requires a freshly minted grant for the exact criteria.
    context = intent_context(
        classification="factual_business", scope_status="absent",
        classifier_source="server_policy", classifier_version="shape-test-v1",
    )
    with pytest.raises(ValueError):
        c.parse_p2_decision(raw, context)

    with pytest.raises(ValueError, match="duplicate"):
        c.parse_p2_decision_shape(b'{"kind":"answer","kind":"answer"}')
    with pytest.raises(ValueError):
        c.parse_p2_decision_shape(b'{"kind":"answer","basis":"non_business_general","text":"ok","citations":[],"x":NaN}')
    with pytest.raises(ValueError):
        c.parse_p2_decision_shape(b'{"kind":"answer","basis":"non_business_general","text":"ok","citations":[],"x":1e999}')
    with pytest.raises(ValidationError):
        c.parse_p2_decision_shape({"kind": "unknown"})


def test_per_query_bindings_allow_same_scope_multiread_answer_and_reject_mismatches():
    scope = c.P2Scope(**activity_scope())
    expense_criteria = c.ExpenseCriteria(kind="expenses", activity_ref=REF_ACTIVITY)
    debt_criteria = c.DebtCriteria(kind="debts", activity_ref=REF_ACTIVITY)
    expense_digest = c.p2_criteria_digest(expense_criteria)
    debt_digest = c.p2_criteria_digest(debt_criteria)
    expense_grant = source_grant(c.P2ReadOperation.EXPENSES, scope, expense_digest)
    debt_grant = source_grant(c.P2ReadOperation.DEBTS, scope, debt_digest)
    expense_receipt = fresh_receipt(
        operation=c.P2ReadOperation.EXPENSES,
        query_ref=REF_QUERY,
        criteria_digest=expense_digest,
    )
    debt_receipt = c.P2FreshQueryEvidenceRef(
        query_evidence_ref="qev_" + "N" * 22,
        query_ref=REF_NEXT,
        principal_ref=REF_PARTICIPANT,
        owner_turn_ref=REF_TURN,
        generation=1,
        source_input_seq=7,
        input_digest=INPUT_DIGEST,
        operation=c.P2ReadOperation.DEBTS,
        scope_ref=REF_ACTIVITY,
        criteria_digest=debt_digest,
        observed_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=1),
    )
    bindings = (
        c.P2QueryAuthorizationBinding(
            query_evidence_ref=expense_receipt.query_evidence_ref,
            receipt=expense_receipt,
            grant=expense_grant,
        ),
        c.P2QueryAuthorizationBinding(
            query_evidence_ref=debt_receipt.query_evidence_ref,
            receipt=debt_receipt,
            grant=debt_grant,
        ),
    )
    context = intent_context(
        classification="factual_business",
        scope_status="verified",
        scope=scope,
        source_authorization_grant=expense_grant,
        fresh_receipt_refs=(expense_receipt, debt_receipt),
        query_authorization_bindings=bindings,
        classifier_source="server_policy",
        classifier_version="multi-query-test-v1",
    )
    answer = {
        "kind": "answer",
        "basis": "fresh_read_receipts",
        "text": "合成的消费和债务摘要",
        "citations": [expense_receipt.query_evidence_ref, debt_receipt.query_evidence_ref],
    }
    assert isinstance(c.parse_p2_decision(answer, context), c.P2AnswerDecision)

    # A valid answer may cite only the relevant subset of same-scope queries.
    expense_only = {**answer, "citations": [expense_receipt.query_evidence_ref]}
    assert isinstance(c.parse_p2_decision(expense_only, context), c.P2AnswerDecision)

    # A receipt can be present in context without a grant mapping, but it may
    # not be cited as if another query's grant authorized it.
    unbound_receipt = debt_receipt.model_copy(
        update={"query_evidence_ref": "qev_" + "O" * 22, "query_ref": "ref_" + "P" * 22}
    )
    context_with_unbound_receipt = context.model_copy(
        update={"fresh_receipt_refs": (expense_receipt, debt_receipt, unbound_receipt)}
    )
    with pytest.raises(ValueError, match="per-query authorization binding"):
        c.parse_p2_decision(
            {**answer, "citations": [unbound_receipt.query_evidence_ref]}, context_with_unbound_receipt
        )

    wrong_criteria_grant = source_grant(c.P2ReadOperation.DEBTS, scope, "c" * 64)
    with pytest.raises(ValidationError):
        c.P2QueryAuthorizationBinding(
            query_evidence_ref=debt_receipt.query_evidence_ref,
            receipt=debt_receipt,
            grant=wrong_criteria_grant,
        )
    wrong_operation_grant = source_grant(c.P2ReadOperation.EXPENSES, scope, debt_digest)
    with pytest.raises(ValidationError):
        c.P2QueryAuthorizationBinding(
            query_evidence_ref=debt_receipt.query_evidence_ref,
            receipt=debt_receipt,
            grant=wrong_operation_grant,
        )

    unit_scope = c.P2Scope(**ledger_unit_scope())
    cross_scope_grant = source_grant(c.P2ReadOperation.DEBTS, unit_scope, debt_digest)
    cross_scope_receipt = debt_receipt.model_copy(update={"scope_ref": REF_UNIT})
    cross_scope_binding = c.P2QueryAuthorizationBinding(
        query_evidence_ref=debt_receipt.query_evidence_ref,
        receipt=cross_scope_receipt,
        grant=cross_scope_grant,
    )
    with pytest.raises(ValidationError):
        intent_context(
            classification="factual_business", scope_status="verified", scope=scope,
            source_authorization_grant=expense_grant,
            fresh_receipt_refs=(expense_receipt, cross_scope_receipt),
            query_authorization_bindings=(bindings[0], cross_scope_binding),
            classifier_source="server_policy", classifier_version="cross-scope-test-v1",
        )
    with pytest.raises(ValidationError):
        intent_context(
            classification="factual_business", scope_status="verified", scope=scope,
            source_authorization_grant=expense_grant,
            fresh_receipt_refs=(expense_receipt, debt_receipt),
            query_authorization_bindings=(bindings[0], bindings[1], bindings[1]),
            classifier_source="server_policy", classifier_version="duplicate-binding-test-v1",
        )

    expired_grant = debt_grant.model_copy(update={"expires_at": NOW - timedelta(seconds=1)})
    expired_binding = c.P2QueryAuthorizationBinding(
        query_evidence_ref=debt_receipt.query_evidence_ref,
        receipt=debt_receipt,
        grant=expired_grant,
    )
    expired_context = context.model_copy(
        update={
            "query_authorization_bindings": (bindings[0], expired_binding),
        }
    )
    with pytest.raises(ValueError, match="expired"):
        c.parse_p2_decision(answer, expired_context)

    # Expired unused evidence and an expired unused primary grant do not
    # poison a debt-only answer; citing either expired expense capability does.
    expired_expense_receipt = expense_receipt.model_copy(
        update={"expires_at": NOW - timedelta(seconds=1)}
    )
    expired_expense_binding = c.P2QueryAuthorizationBinding(
        query_evidence_ref=expired_expense_receipt.query_evidence_ref,
        receipt=expired_expense_receipt,
        grant=expense_grant,
    )
    expired_unused_context = context.model_copy(
        update={
            "fresh_receipt_refs": (expired_expense_receipt, debt_receipt),
            "query_authorization_bindings": (expired_expense_binding, bindings[1]),
        }
    )
    debt_only = {**answer, "citations": [debt_receipt.query_evidence_ref]}
    assert isinstance(c.parse_p2_decision(debt_only, expired_unused_context), c.P2AnswerDecision)
    with pytest.raises(ValueError, match="receipt is expired"):
        c.parse_p2_decision(expense_only, expired_unused_context)

    expired_primary_grant = expense_grant.model_copy(
        update={"expires_at": NOW - timedelta(seconds=1)}
    )
    expired_primary_binding = c.P2QueryAuthorizationBinding(
        query_evidence_ref=expense_receipt.query_evidence_ref,
        receipt=expense_receipt,
        grant=expired_primary_grant,
    )
    expired_primary_context = context.model_copy(
        update={
            "source_authorization_grant": expired_primary_grant,
            "query_authorization_bindings": (expired_primary_binding, bindings[1]),
        }
    )
    assert isinstance(c.parse_p2_decision(debt_only, expired_primary_context), c.P2AnswerDecision)
    with pytest.raises(ValueError, match="expired"):
        c.parse_p2_decision(expense_only, expired_primary_context)

    # A typed copy cannot smuggle a mismatched operation/criteria grant through
    # the revalidation boundary.
    mismatched_grant = debt_grant.model_copy(update={"criteria_digest": expense_digest})
    mismatched_binding = bindings[1].model_copy(update={"grant": mismatched_grant})
    copied_binding_context = context.model_copy(
        update={"query_authorization_bindings": (bindings[0], mismatched_binding)}
    )
    with pytest.raises(ValueError, match="trusted P2 intent context failed revalidation"):
        c.parse_p2_decision(answer, copied_binding_context)


def test_strict_guard_revalidates_typed_copy_bypasses_and_duplicate_receipts():
    scope = c.P2Scope(**activity_scope())
    criteria = c.ExpenseCriteria(kind="expenses", activity_ref=REF_ACTIVITY)
    criteria_digest = c.p2_criteria_digest(criteria)
    grant = source_grant(c.P2ReadOperation.EXPENSES, scope, criteria_digest)
    receipt = fresh_receipt(criteria_digest=criteria_digest)
    context = intent_context(
        classification="factual_business", scope_status="verified", scope=scope,
        source_authorization_grant=grant, fresh_receipt_refs=(receipt,),
        classifier_source="server_policy", classifier_version="copy-test-v1",
    )
    decision = c.P2AnswerDecision(
        kind="answer", basis="fresh_read_receipts", text="当前有效的合成答案", citations=(QEV,)
    )
    expired_legacy_grant = grant.model_copy(update={"expires_at": NOW - timedelta(seconds=1)})
    expired_legacy_context = context.model_copy(
        update={"source_authorization_grant": expired_legacy_grant}
    )
    with pytest.raises(ValueError, match="expired"):
        c.parse_p2_decision(decision, expired_legacy_context)

    copied_decision = decision.model_copy(update={"citations": ("qev_" + "Z" * 22,)})
    with pytest.raises(ValueError):
        c.parse_p2_decision(copied_decision, context)

    copied_context = context.model_copy(update={"scope_status": "unresolved", "scope": scope})
    with pytest.raises(ValueError):
        c.parse_p2_decision(decision, copied_context)

    with pytest.raises(ValidationError):
        intent_context(
            classification="factual_business", scope_status="verified", scope=scope,
            source_authorization_grant=grant, fresh_receipt_refs=(receipt, receipt),
            classifier_source="server_policy", classifier_version="duplicate-test-v1",
        )

