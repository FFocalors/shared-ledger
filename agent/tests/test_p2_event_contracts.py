"""CPU-only tests for the disabled P2 event sidecar candidate."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from agent.app import contracts as canonical
from agent.app import p2_event_contracts as events
from agent.app import p2_read_contracts as p2


NOW = datetime.now(timezone.utc).replace(microsecond=0)
REF_A = "ref_" + "A" * 22
REF_B = "ref_" + "B" * 22
REF_C = "ref_" + "C" * 22
REF_D = "ref_" + "D" * 22
REF_E = "ref_" + "E" * 22
REF_F = "ref_" + "F" * 22
REF_G = "ref_" + "G" * 22
REF_H = "ref_" + "H" * 22
REF_I = "ref_" + "I" * 22
REF_J = "ref_" + "J" * 22
REF_K = "ref_" + "K" * 22
DIGEST = "a" * 64


def make_fact(operation: p2.P2ReadOperation, qev: str) -> p2.P2Fact:
    if operation == p2.P2ReadOperation.ACTIVITIES:
        return p2.ActivityFact(
            fact_kind="activity", activity_ref=REF_A, activity_kind="trip", name="合成东京行程",
            base_currency="JPY", status="active", observed_at=NOW, context_version="fv:5",
            query_evidence_ref=qev,
        )
    if operation == p2.P2ReadOperation.EXPENSES:
        line = p2.ParticipantAllocationFact(
            participant_ref=REF_B, role="payer", signed_original_amount="-12.3400",
            original_currency="EUR", signed_base_amount="-19.0", base_currency="USD",
        )
        return p2.ExpenseFact(
            fact_kind="expense", expense_ref=REF_C, scope_ref=REF_A, occurred_at=NOW,
            signed_original_amount="-12.3400", original_currency="EUR", signed_base_amount="-19.0",
            base_currency="USD", payer_split_lines=(line,), expense_version=3, financial_version=7,
            query_evidence_ref=qev,
        )
    if operation == p2.P2ReadOperation.DEBTS:
        return p2.DebtFact(
            fact_kind="debt", debt_ref=REF_D, scope_ref=REF_A, activity_ref=REF_A,
            ledger_unit_ref=REF_E, expense_ref=REF_C, debtor_ref=REF_B, creditor_ref=REF_F,
            original_amount=None, original_currency=None, base_amount="0.0", base_currency="USD",
            financial_version=7, query_evidence_ref=qev,
        )
    if operation == p2.P2ReadOperation.REFUND_EVENTS:
        return p2.RefundEventFact(
            fact_kind="refund_event", refund_ref=REF_G, scope_ref=REF_A,
            signed_original_amount="-2.5000", original_currency="EUR", signed_base_amount="0.0",
            base_currency="USD", occurred_at=NOW, parent_expense_ref=None,
            lineage_status="parent_unavailable", lineage_basis=None, refund_recipient_ref=None,
            financial_version=7, query_evidence_ref=qev,
        )
    if operation == p2.P2ReadOperation.PREPAYMENT_ACCOUNTS:
        return p2.PrepaymentAccountFact(
            fact_kind="prepayment_account", account_ref=REF_H, activity_ref=REF_A,
            owner_ref=REF_B, custodian_ref=REF_F, balance="12.3400", currency="CNY",
            projection_updated_at=NOW, financial_version=7, query_evidence_ref=qev,
        )
    if operation == p2.P2ReadOperation.PREPAYMENT_USAGES:
        return p2.PrepaymentUsageFact(
            fact_kind="prepayment_usage", usage_ref=REF_I, account_ref=REF_H, expense_ref=REF_C,
            debt_ref=REF_D, activity_ref=REF_A, gross_amount="3.0000", amount="2.0000",
            prepayment_amount="1.0000", prepayment_currency="CNY", debt_amount="1.0000",
            debt_currency="EUR", base_amount="0.0", base_currency="USD", bill_fx_rate="1.2345678901",
            bill_occurred_at=NOW, financial_version=7, query_evidence_ref=qev,
        )
    if operation == p2.P2ReadOperation.PREPAYMENT_RETURN_EVENTS:
        return p2.PrepaymentReturnEventFact(
            fact_kind="prepayment_return_event", return_event_ref=REF_J, activity_ref=REF_A,
            amount="2.0000", currency="CNY", occurred_at=NOW, from_ref=REF_B, from_role="custodian",
            to_ref=REF_F, to_role="owner", transfer_component_match=True, financial_version=7,
            query_evidence_ref=qev,
        )
    raise AssertionError(operation)


def fact_ref(fact: p2.P2Fact) -> str:
    field = {
        "activity": "activity_ref", "expense": "expense_ref", "debt": "debt_ref",
        "refund_event": "refund_ref", "prepayment_account": "account_ref",
        "prepayment_usage": "usage_ref", "prepayment_return_event": "return_event_ref",
    }[fact.fact_kind]
    return getattr(fact, field)


def make_result(
    operation: p2.P2ReadOperation,
    *,
    fact: p2.P2Fact | None = None,
    source_complete: bool = True,
    model_complete: bool = True,
    returned: int | None = None,
    matched: int | None = None,
    zero_kind: str | None = None,
    truncated: bool = False,
) -> p2.P2ReadBackendResult:
    qev = "qev_" + chr(ord("L") + list(p2.P2ReadOperation).index(operation)) * 22
    source_ref = "ref_" + chr(ord("S") + list(p2.P2ReadOperation).index(operation)) * 22
    items = () if fact is None else (fact,)
    if returned is None:
        returned = len(items)
    if matched is None:
        matched = len(items)
    if zero_kind is None:
        zero_kind = "nonzero" if matched else "backend_zero" if returned == 0 else "post_filter_zero"
    stable = source_complete and model_complete and not truncated
    has_more = False
    expected = returned if stable else None
    source_total = returned if stable else None
    matched_total = matched if stable else None
    page_summary = p2.P2PageSummary(
        pages_seen=1, has_more=has_more, truncated=truncated,
        source_query_complete=source_complete, model_projection_complete=model_complete,
        range_contiguous=stable, stable_total_verified=stable, source_version_fenced=stable,
        unique_items_verified=stable, expected_total=expected,
    )
    operation_kind = operation.value.removeprefix("read.")
    evidence = p2.P2QueryEvidence(
        profile_id=p2.P2_CANDIDATE_PROFILE_ID,
        versions=p2.P2_VERSIONS,
        query_evidence_ref=qev,
        query_ref=REF_K,
        result_ref=REF_J,
        operation=operation,
        criteria_ref=REF_I,
        criteria_digest=DIGEST,
        normalized_criteria_digest="b" * 64,
        backend_criteria_stage="scope_only",
        source_kind=operation_kind,
        source_ref=source_ref,
        source_version="synthetic-source-v1",
        observed_at=NOW - timedelta(seconds=2),
        simulation=False,
        returned_count=returned,
        matched_count=matched,
        source_total=source_total,
        matched_total=matched_total,
        page_count=1,
        query_zero_classification=zero_kind,
        source_query_complete=source_complete,
        model_projection_complete=model_complete,
        matching_fact_refs=tuple(fact_ref(item) for item in items),
        financial_versions=(p2.P2FinancialVersion(activity_ref=REF_A, financial_version=7),),
        page=page_summary,
        query_digest="c" * 64,
        body_digest="d" * 64,
        projection_digest="e" * 64,
    )
    page = p2.P2PageProjection[p2.P2Fact](
        items=items,
        completeness=p2.ModelProjectionCompleteness.COMPLETE if model_complete else p2.ModelProjectionCompleteness.PARTIAL,
        has_more=False,
        next_page_ref=None,
        page_index=0,
        range_contiguous=stable,
        stable_total_verified=stable,
        source_version_fenced=stable,
        unique_items_verified=stable,
        expected_total=expected,
    )
    return p2.P2ReadBackendResult(operation=operation, query_evidence=evidence, page=page)


def with_total_metadata(result, *, source_total, matched_total, stable, expected):
    evidence = result.query_evidence
    summary = evidence.page.model_copy(
        update={"stable_total_verified": stable, "expected_total": expected}
    )
    projection = result.page.model_copy(
        update={"stable_total_verified": stable, "expected_total": expected}
    )
    updated_evidence = evidence.model_copy(
        update={"source_total": source_total, "matched_total": matched_total, "page": summary}
    )
    return result.model_copy(update={"query_evidence": updated_evidence, "page": projection})


@pytest.mark.parametrize("operation", list(p2.P2ReadOperation))
def test_all_seven_fact_variants_project_as_bound_cards(operation):
    qev = "qev_" + chr(ord("L") + list(p2.P2ReadOperation).index(operation)) * 22
    fact = make_fact(operation, qev)
    result = make_result(operation, fact=fact)
    observation, cards = events.project_p2_backend_result(result)
    assert observation.query_evidence_ref == qev
    assert observation.result_state == events.P2EventResultState.COMPLETE_NONEMPTY
    assert len(cards) == 1
    assert cards[0].query_evidence_ref == qev
    assert cards[0].fact == fact
    if isinstance(fact, p2.DebtFact):
        assert fact.original_amount is None and fact.base_amount == "0.0"
    if isinstance(fact, p2.RefundEventFact):
        assert fact.signed_original_amount == "-2.5000" and fact.signed_base_amount == "0.0"
    if isinstance(fact, p2.ExpenseFact):
        assert fact.signed_original_amount == "-12.3400" and fact.signed_base_amount == "-19.0"


def test_zero_partial_and_source_complete_model_partial_are_distinct():
    zero = make_result(p2.P2ReadOperation.ACTIVITIES)
    empty_observation, empty_cards = events.project_p2_backend_result(zero)
    assert empty_observation.result_state == events.P2EventResultState.COMPLETE_EMPTY
    assert empty_cards == ()

    partial_zero = make_result(
        p2.P2ReadOperation.ACTIVITIES, source_complete=False, model_complete=False,
        zero_kind="unknown_or_partial",
    )
    partial_observation, partial_cards = events.project_p2_backend_result(partial_zero)
    assert partial_observation.result_state == events.P2EventResultState.PARTIAL_OR_UNKNOWN
    assert partial_observation.matched_count == 0 and partial_cards == ()

    capped = make_result(
        p2.P2ReadOperation.ACTIVITIES, source_complete=True, model_complete=False,
        returned=17, matched=17, zero_kind="nonzero", truncated=True,
    )
    capped_observation, capped_cards = events.project_p2_backend_result(capped)
    assert capped_observation.source_query_complete is True
    assert capped_observation.model_projection_complete is False
    assert capped_observation.result_state == events.P2EventResultState.PARTIAL_OR_UNKNOWN
    assert capped_cards == ()


def test_unknown_zero_classification_is_always_partial():
    # This is a valid typed backend result: evidence explicitly says the zero
    # classification is unknown even though every coverage flag is true.
    unknown_zero = make_result(
        p2.P2ReadOperation.ACTIVITIES,
        source_complete=True,
        model_complete=True,
        returned=0,
        matched=0,
        zero_kind="unknown_or_partial",
    )
    assert unknown_zero.query_evidence.query_zero_classification == "unknown_or_partial"
    unknown_observation, unknown_cards = events.project_p2_backend_result(unknown_zero)
    assert unknown_observation.result_state == events.P2EventResultState.PARTIAL_OR_UNKNOWN
    assert unknown_cards == ()


def test_known_matched_total_does_not_require_unknown_source_total_stability():
    # The server's total is unknown, while the fully projected filtered match
    # total is exactly zero. A stable source total is not required in this case.
    post_filter_zero = make_result(
        p2.P2ReadOperation.ACTIVITIES,
        source_complete=True,
        model_complete=True,
        returned=3,
        matched=0,
        zero_kind="post_filter_zero",
    )
    matched_total_only = with_total_metadata(
        post_filter_zero, source_total=None, matched_total=0, stable=False, expected=None
    )
    matched_only_observation, _ = events.project_p2_backend_result(matched_total_only)
    assert matched_only_observation.source_total is None
    assert matched_only_observation.matched_total == 0
    assert matched_only_observation.result_state == events.P2EventResultState.COMPLETE_EMPTY

    # When a source total is present, the same complete-looking result stays
    # partial until that source total is stable.
    known_source_zero = make_result(
        p2.P2ReadOperation.ACTIVITIES,
        source_complete=True,
        model_complete=True,
        returned=0,
        matched=0,
        zero_kind="backend_zero",
    )
    known_source_unstable = with_total_metadata(
        known_source_zero, source_total=0, matched_total=0, stable=False, expected=None
    )
    unstable_observation, _ = events.project_p2_backend_result(known_source_unstable)
    assert unstable_observation.result_state == events.P2EventResultState.PARTIAL_OR_UNKNOWN


def test_answer_projection_binds_cards_and_observations_without_private_source_fields():
    results = tuple(
        make_result(operation, fact=make_fact(operation, "qev_" + chr(ord("L") + i) * 22))
        for i, operation in enumerate(p2.P2ReadOperation)
    )
    decision = p2.P2AnswerDecision(
        kind="answer", basis="fresh_read_receipts", text="合成的七类来源事实摘要",
        citations=tuple(result.query_evidence.query_evidence_ref for result in results),
    )
    output = events.build_p2_answer_output(decision, results)
    assert len(output.observations) == 7
    assert len(output.fact_cards) == 7
    serialized = output.model_dump(mode="json")
    rendered = str(serialized)
    assert "source_ref" not in rendered and "query_ref" not in rendered and "result_ref" not in rendered
    assert "criteria_digest" not in rendered and "next_page_ref" not in rendered
    assert "raw_body_hash" not in rendered and "current" not in rendered and "is_fresh" not in rendered
    assert "observed_at" in rendered and "source_version" in rendered
    assert {card.fact.fact_kind for card in output.fact_cards} == {
        "activity", "expense", "debt", "refund_event", "prepayment_account",
        "prepayment_usage", "prepayment_return_event",
    }

    # Projection is driven only by the cited result subset. Uncited accepted
    # results stay out of both observations and cards.
    selected = results[1]
    subset_decision = decision.model_copy(
        update={"citations": (selected.query_evidence.query_evidence_ref,)}
    )
    subset_output = events.build_p2_answer_output(subset_decision, (selected,))
    assert tuple(obs.query_evidence_ref for obs in subset_output.observations) == (
        selected.query_evidence.query_evidence_ref,
    )
    assert subset_output.fact_cards
    assert {card.query_evidence_ref for card in subset_output.fact_cards} == {
        selected.query_evidence.query_evidence_ref,
    }
    with pytest.raises(ValueError, match="exactly match answer citations"):
        events.build_p2_answer_output(subset_decision, results)


def test_candidate_response_cursor_status_sidecar_and_typed_copy_guard():
    now = NOW
    turn = canonical.TurnPublicStatus(
        turn_id=str(uuid4()), session_id=str(uuid4()), state=canonical.TurnState.RUNNING,
        step=canonical.TurnStep.MODEL_DECISION, state_revision=2, execution_assigned=False,
        context_version=4,
    )
    event = canonical.StatusEvent(
        type="status", seq=4, occurred_at=now, simulation=False,
        payload=canonical.StatusEventPayload(
            state=canonical.TurnState.RUNNING, step=canonical.TurnStep.MODEL_DECISION,
            state_revision=2,
        ),
    )
    clarification = events.P2ClarificationOutput(
        kind="clarify", prompt="請選擇哪一筆費用", missing_slots=("expense",)
    )
    projected = events.P2ProjectedEvent(seq=4, created_at=now, event=event, candidate_output=clarification)
    response = events.P2EventPollResponse(
        versions=p2.P2_VERSIONS, turn=turn, after_seq=3, events=(projected,), next_after_seq=4, has_more=False,
    )
    assert response.api_version == canonical.API_VERSION
    assert response.next_after_seq == 4

    with pytest.raises(ValidationError):
        events.P2EventPollResponse(
            versions=p2.P2_VERSIONS.model_copy(update={"api": "9.0.0"}), turn=turn,
            after_seq=3, events=(projected,), next_after_seq=4, has_more=False,
        )
    bad_event = event.model_copy(update={"seq": 9})
    with pytest.raises(ValidationError):
        events.P2ProjectedEvent(seq=4, created_at=now, event=bad_event)

    good_debt = make_fact(p2.P2ReadOperation.DEBTS, "qev_" + "L" * 22)
    bypassed_debt = good_debt.model_copy(update={"financial_version": -1})
    with pytest.raises(ValidationError):
        events.P2FactCard(query_evidence_ref=good_debt.query_evidence_ref, fact=bypassed_debt)


def test_candidate_output_rejects_private_fields_and_inconsistent_citations():
    with pytest.raises(ValidationError):
        events.P2ClarificationOutput(
            kind="clarify", prompt="請確認", missing_slots=("expense",), next_page_ref=REF_K
        )
    with pytest.raises(ValidationError):
        events.P2ProposalRecognitionOutput(
            kind="propose", operation="expense.update", recognized_intent_text="改金额",
            preview_card={"x": 1},
        )
    with pytest.raises(ValidationError):
        events.P2AnswerOutput(
            kind="answer", basis="fresh_read_receipts", text="摘要",
            citations=("qev_" + "L" * 22,), observations=(), fact_cards=(),
        )
    source_free = events.P2AnswerOutput(
        kind="answer", basis="non_business_general", text="一般说明", citations=(), observations=(), fact_cards=()
    )
    assert source_free.citations == ()


def test_event_timestamp_sequence_cursor_and_schema_versions_are_strict():
    turn = canonical.TurnPublicStatus(
        turn_id=str(uuid4()), session_id=str(uuid4()), state=canonical.TurnState.RUNNING,
        step=canonical.TurnStep.MODEL_DECISION, state_revision=1, execution_assigned=False,
        context_version=1,
    )
    event = canonical.StatusEvent(
        type="status", seq=2, occurred_at=NOW, simulation=False,
        payload=canonical.StatusEventPayload(
            state=canonical.TurnState.RUNNING, step=canonical.TurnStep.MODEL_DECISION, state_revision=1,
        ),
    )
    row = events.P2ProjectedEvent(seq=2, created_at=NOW, event=event)
    with pytest.raises(ValidationError):
        events.P2EventPollResponse(
            versions=p2.P2_VERSIONS, turn=turn, after_seq=2, events=(row,), next_after_seq=2, has_more=False,
        )
    with pytest.raises(ValidationError):
        events.P2EventPollResponse(
            versions=p2.P2_VERSIONS, turn=turn, after_seq=1, events=(), next_after_seq=1, has_more=True,
        )
    schemas = events.event_projection_json_schemas()
    assert set(schemas) == {"P2EventPollQuery", "P2EventPollResponse", "P2CandidateOutput"}
    assert "api_version" in schemas["P2EventPollResponse"]["properties"]
    assert "execution_key_version" not in str(schemas)
