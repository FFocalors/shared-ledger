"""Synthetic CPU tests for the unassembled P2 v3 protected-history DTOs."""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.contracts import MessageEvent, StatusEvent
from app.p2_read_contracts_v3 import (
    P2PageProjection,
    P2PageSummary,
    P2ReadBackendResult,
    P2FinancialVersion,
    P2ReadOperation,
    P2ProposalOperation,
    P2_V3_CANDIDATE_PROFILE_ID,
    P2_V3_VERSIONS,
    P2QueryEvidence,
    ReadCompleteness,
    ActivityFact,
    P2EntityDisplayLabel,
    DebtFact,
    ExpenseFact,
    ParticipantAllocationFact,
    PrepaymentAccountFact,
    PrepaymentReturnEventFact,
    PrepaymentUsageFact,
    RefundEventFact,
)
from app.p2_event_contracts_v3 import (
    P2V3EventContractError,
    P2V3EventPollQuery,
    P2V3HistoricalAnswer,
    P2V3HistoricalClarification,
    P2V3HistoricalProposalIntent,
    P2V3HistoricalReadResult,
    P2V3PrivateFactRowBinding,
    P2V3PrivateMetadataProofBinding,
    P2V3PrivateQevProofBinding,
    P2V3PrivateActivityCollectionQevProofBinding,
    P2V3PrivateActivityMembershipBinding,
    P2V3PrivateScopeGateBinding,
    P2V3PrivateScopeGatedHistoryGate,
    P2V3PrivateSidecarBinding,
    P2V3PrivateSourceFreeHistoryGate,
    P2V3PrivateTurnSnapshot,
    parse_p2_v3_event_poll_query,
    parse_p2_v3_event_poll_response,
    parse_p2_v3_historical_output,
    _fact_public_ref,
    _validate_activity_zero_classification,
    project_live_p2_read_result_for_history,
    project_p2_v3_event_page,
)


NOW = datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc)
TURN_REF = "ref_" + "T" * 22
CONTEXT_REF = "ref_" + "C" * 22
ACTIVITY_REF = "ref_" + "A" * 22
ACTIVITY_REF_2 = "ref_" + "B" * 22
CHILD_SCOPE_REF = "ref_" + "D" * 22
EXPENSE_REF = "ref_" + "E" * 22
EXPENSE_SOURCE_REF = "ref_" + "S" * 22
PARTICIPANT_REF = "ref_" + "P" * 22
ACTOR_REF = "ref_" + "U" * 22
LABEL_RECEIPT_REF = "ref_" + "L" * 22
QEV_REF = "qev_" + "Q" * 22
ACTIVITY_QEV_REF = "qev_" + "W" * 22
CAP_REF = "ref_" + "K" * 22
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64
OWNER_ID = UUID("10000000-0000-4000-8000-000000000001")
TURN_ID = UUID("20000000-0000-4000-8000-000000000002")
SCOPE_LOCATOR_ID = UUID("30000000-0000-4000-8000-000000000003")
ACTIVITY_LOCATOR_ID = UUID("40000000-0000-4000-8000-000000000004")
SOURCE_ROW_ID = UUID("50000000-0000-4000-8000-000000000005")
METADATA_PROOF_ID = UUID("60000000-0000-4000-8000-000000000006")
QUERY_PROOF_ID = UUID("70000000-0000-4000-8000-000000000007")
FACT_ROW_ID = UUID("80000000-0000-4000-8000-000000000008")
FACT_PROOF_ID = UUID("90000000-0000-4000-8000-000000000009")
SCOPE_LOCATOR_ID_2 = UUID("30000000-0000-4000-8000-000000000013")
ACTIVITY_LOCATOR_ID_2 = UUID("40000000-0000-4000-8000-000000000014")
COLLECTION_QUERY_ID = UUID("a0000000-0000-4000-8000-00000000000a")
COLLECTION_LOCATOR_ID = UUID("b0000000-0000-4000-8000-00000000000b")
MEMBERSHIP_PROOF_ID = UUID("c0000000-0000-4000-8000-00000000000c")


def _base_output_fields(*, read_epoch: int = 0, simulation: bool = False) -> dict:
    return {
        "history_only": True,
        "profile_id": P2_V3_CANDIDATE_PROFILE_ID,
        "versions": P2_V3_VERSIONS.model_dump(),
        "turn_ref": TURN_REF,
        "generation": 1,
        "read_epoch": read_epoch,
        "context_ref": CONTEXT_REF,
        "context_digest": DIGEST_A,
        "context_revision": 0,
        "observed_at": NOW,
        "simulation": simulation,
    }


def _clarification(*, prompt: str = "Which activity should I use?", read_epoch: int = 0) -> P2V3HistoricalClarification:
    return P2V3HistoricalClarification(
        **_base_output_fields(read_epoch=read_epoch),
        kind="clarify",
        prompt=prompt,
        missing_slots=("activity_scope",),
    )


def _text_digest(output) -> str | None:
    for field in ("text", "prompt", "recognized_intent_text"):
        value = getattr(output, field, None)
        if value is not None:
            return hashlib.sha256(value.encode("utf-8")).hexdigest()
    return None


def _source_free_gate(output, *, basis: str, text_origin: str) -> P2V3PrivateSourceFreeHistoryGate:
    return P2V3PrivateSourceFreeHistoryGate(
        mode="source_free",
        basis=basis,
        bound_context_ref=output.context_ref,
        bound_context_digest=output.context_digest,
        bound_text_digest=_text_digest(output),
        bound_generation=output.generation,
        bound_read_epoch=output.read_epoch,
        source_projection_empty=True,
        text_origin=text_origin,
    )


def _scope_binding(
    *,
    scope_ref: str = ACTIVITY_REF,
    activity_ref: str = ACTIVITY_REF,
    private_scope_locator_id: UUID = SCOPE_LOCATOR_ID,
    private_activity_locator_id: UUID = ACTIVITY_LOCATOR_ID,
) -> P2V3PrivateScopeGateBinding:
    return P2V3PrivateScopeGateBinding(
        scope_ref=scope_ref,
        activity_ref=activity_ref,
        private_scope_locator_id=private_scope_locator_id,
        private_activity_locator_id=private_activity_locator_id,
    )


def _metadata_proof(*, entity_kind: str = "activity", scope_ref: str = ACTIVITY_REF) -> P2V3PrivateMetadataProofBinding:
    entity_ref = {
        "current_actor": ACTOR_REF,
        "expense": EXPENSE_REF,
        "activity": ACTIVITY_REF,
    }.get(entity_kind, ACTIVITY_REF)
    source_ref = PARTICIPANT_REF if entity_kind == "current_actor" else entity_ref
    source_kind = {
        "current_actor": "participant_claims.current_auth_user",
        "expense": "expenses",
        "activity": "activities",
    }.get(entity_kind, "activities")
    return P2V3PrivateMetadataProofBinding(
        entity_kind=entity_kind,
        entity_ref=entity_ref,
        source_ref=source_ref,
        scope_ref=scope_ref,
        source_kind=source_kind,
        source_receipt_ref=LABEL_RECEIPT_REF,
        private_source_row_id=SOURCE_ROW_ID,
        private_proof_id=METADATA_PROOF_ID,
    )


def _scope_gate(
    output,
    *,
    kinds: tuple[str, ...],
    metadata=(),
    qev=(),
    text_scope_refs=(),
    scopes=None,
    text_collection_query_refs=(),
) -> P2V3PrivateScopeGatedHistoryGate:
    return P2V3PrivateScopeGatedHistoryGate(
        mode="scope_gated",
        bound_context_ref=output.context_ref,
        bound_context_digest=output.context_digest,
        bound_text_digest=_text_digest(output),
        bound_generation=output.generation,
        bound_read_epoch=output.read_epoch,
        source_projection_kinds=kinds,
        scopes=(_scope_binding(),) if scopes is None else tuple(scopes),
        metadata_proofs=metadata,
        qev_proofs=qev,
        text_scope_refs=text_scope_refs,
        text_collection_query_refs=text_collection_query_refs,
    )


def _private_qev_proof(evidence, *, scope_ref: str = ACTIVITY_REF, fact_rows=()):
    return P2V3PrivateQevProofBinding(
        query_evidence_ref=evidence.query_evidence_ref,
        query_ref=evidence.query_ref,
        result_ref=evidence.result_ref,
        source_kind=evidence.source_kind,
        source_ref=evidence.source_ref,
        criteria_ref=evidence.criteria_ref,
        criteria_digest=evidence.criteria_digest,
        normalized_criteria_digest=evidence.normalized_criteria_digest,
        private_query_proof_id=QUERY_PROOF_ID,
        scope_ref=scope_ref,
        fact_rows=tuple(fact_rows),
    )


def _activity_collection_case(*, zero: str = "nonzero", count: int = 2, partial: bool = False):
    if zero == "backend_zero":
        source_total = returned = matched = 0
        matched_total = 0
        refs = ()
        item_count = 0
    elif zero == "post_filter_zero":
        source_total = returned = 1
        matched = 0
        matched_total = 0
        refs = ()
        item_count = 0
    elif partial:
        source_total = matched_total = None
        returned = matched = 0
        refs = ()
        item_count = 0
    else:
        source_total = returned = matched = matched_total = count
        refs = (ACTIVITY_REF, ACTIVITY_REF_2)[:count]
        item_count = count
    complete = not partial
    has_more = partial
    activities = tuple(
        ActivityFact(
            fact_kind="activity",
            activity_ref=ref,
            activity_kind="trip",
            name=f"Activity {index + 1}",
            base_currency="USD",
            status="active",
            observed_at=NOW,
            context_version=f"ctx-{index + 1}",
            query_evidence_ref=ACTIVITY_QEV_REF,
        )
        for index, ref in enumerate(refs[:item_count])
    )
    summary = P2PageSummary(
        pages_seen=1,
        has_more=has_more,
        truncated=False,
        source_query_complete=complete,
        model_projection_complete=complete,
        range_contiguous=not partial,
        stable_total_verified=not partial,
        source_version_fenced=True,
        unique_items_verified=True,
        expected_total=source_total if not partial else None,
    )
    evidence = P2QueryEvidence(
        profile_id=P2_V3_CANDIDATE_PROFILE_ID,
        versions=P2_V3_VERSIONS,
        query_evidence_ref=ACTIVITY_QEV_REF,
        query_ref="ref_" + "X" * 22,
        result_ref="ref_" + "Y" * 22,
        operation=P2ReadOperation.ACTIVITIES,
        criteria_ref="ref_" + "Z" * 22,
        criteria_digest=DIGEST_A,
        normalized_criteria_digest=DIGEST_B,
        backend_criteria_stage="scope_only",
        source_kind="activities",
        source_ref="ref_" + "N" * 22,
        source_version="v3",
        observed_at=NOW,
        simulation=False,
        returned_count=returned,
        matched_count=matched,
        source_total=source_total,
        matched_total=matched_total,
        page_count=1,
        query_zero_classification="unknown_or_partial" if partial else zero,
        source_query_complete=complete,
        model_projection_complete=complete,
        matching_fact_refs=refs,
        financial_versions=(),
        page=summary,
        query_digest=DIGEST_B,
        body_digest=DIGEST_C,
        projection_digest=DIGEST_D,
    )
    page = P2PageProjection(
        items=activities,
        completeness=ReadCompleteness.PARTIAL if partial else ReadCompleteness.COMPLETE,
        has_more=has_more,
        next_page_ref=CAP_REF if has_more else None,
        page_index=0,
        range_contiguous=not partial,
        stable_total_verified=not partial,
        source_version_fenced=True,
        unique_items_verified=True,
        expected_total=source_total if not partial else None,
    )
    live = P2ReadBackendResult(
        operation=P2ReadOperation.ACTIVITIES,
        query_evidence=evidence,
        page=page,
    )
    result = project_live_p2_read_result_for_history(live)
    output = P2V3HistoricalReadResult(
        **_base_output_fields(read_epoch=1),
        kind="read_result",
        result=result,
        source_labels=(),
        current_actor=None,
    )
    membership = tuple(
        P2V3PrivateActivityMembershipBinding(
            activity_ref=ref,
            private_activity_locator_id=(ACTIVITY_LOCATOR_ID if ref == ACTIVITY_REF else ACTIVITY_LOCATOR_ID_2),
            private_membership_proof_id=(MEMBERSHIP_PROOF_ID if ref == ACTIVITY_REF else UUID("c0000000-0000-4000-8000-00000000000d")),
        )
        for ref in refs
    )
    fact_rows = tuple(
        P2V3PrivateFactRowBinding(
            fact_ref=ref,
            private_source_row_id=(ACTIVITY_LOCATOR_ID if ref == ACTIVITY_REF else ACTIVITY_LOCATOR_ID_2),
            private_fact_proof_id=(FACT_PROOF_ID if ref == ACTIVITY_REF else UUID("90000000-0000-4000-8000-00000000000a")),
        )
        for ref in refs[:item_count]
    )
    proof = P2V3PrivateActivityCollectionQevProofBinding(
        binding_kind="activity_collection",
        query_evidence_ref=evidence.query_evidence_ref,
        query_ref=evidence.query_ref,
        result_ref=evidence.result_ref,
        source_kind=evidence.source_kind,
        source_ref=evidence.source_ref,
        criteria_ref=evidence.criteria_ref,
        criteria_digest=evidence.criteria_digest,
        normalized_criteria_digest=evidence.normalized_criteria_digest,
        private_query_proof_id=QUERY_PROOF_ID,
        private_collection_query_id=COLLECTION_QUERY_ID,
        private_collection_locator_id=COLLECTION_LOCATOR_ID,
        activity_bindings=membership,
        fact_rows=fact_rows,
    )
    gate = _scope_gate(
        output,
        kinds=("query_evidence", "financial_facts"),
        qev=(proof,),
        scopes=(),
    )
    return output, gate, evidence


def _sidecar(output, gate, *, seq: int = 4, owner_id: UUID = OWNER_ID) -> P2V3PrivateSidecarBinding:
    return P2V3PrivateSidecarBinding(
        owner_id=owner_id,
        turn_id=TURN_ID,
        turn_ref=TURN_REF,
        profile_id=P2_V3_CANDIDATE_PROFILE_ID,
        protocol_versions=P2_V3_VERSIONS,
        canonical_seq=seq,
        output=output,
        history_gate=gate,
    )


def _status(seq: int, *, simulation: bool = False) -> StatusEvent:
    return StatusEvent.model_validate(
        {
            "type": "status",
            "seq": seq,
            "occurred_at": NOW.isoformat(),
            "simulation": simulation,
            "payload": {"state": "RUNNING", "step": "tool_read", "state_revision": seq},
        },
        strict=True,
    )


def _source_page(*, has_more: bool = False, include_fact: bool = False, simulation: bool = False):
    query_ref = QEV_REF
    facts = ()
    returned = matched = 0
    matching_refs = ()
    total = 0
    zero = "backend_zero"
    stable = False
    financial_versions = ()
    if include_fact:
        facts = (
            ExpenseFact(
                fact_kind="expense",
                expense_ref=EXPENSE_REF,
                title="Coffee",
                scope_ref=ACTIVITY_REF,
                occurred_at=NOW,
                signed_original_amount="19.0000",
                original_currency="USD",
                signed_base_amount="19.0",
                base_currency="USD",
                payer_split_lines=(
                    ParticipantAllocationFact(
                        participant_ref=PARTICIPANT_REF,
                        role="payer",
                        signed_original_amount="19.0000",
                        original_currency="USD",
                        signed_base_amount="19.0",
                        base_currency="USD",
                    ),
                ),
                expense_version=1,
                financial_version=3,
                query_evidence_ref=query_ref,
            ),
        )
        returned = matched = 1
        matching_refs = (EXPENSE_REF,)
        total = 1
        zero = "nonzero"
        stable = True
        financial_versions = ({"activity_ref": ACTIVITY_REF, "financial_version": 3},)
    model_complete = not has_more
    source_complete = not has_more
    page_summary = P2PageSummary(
        pages_seen=1,
        has_more=has_more,
        truncated=False,
        source_query_complete=source_complete,
        model_projection_complete=model_complete,
        range_contiguous=True,
        stable_total_verified=stable,
        source_version_fenced=True,
        unique_items_verified=True,
        expected_total=total if stable else None,
    )
    evidence = P2QueryEvidence(
        profile_id=P2_V3_CANDIDATE_PROFILE_ID,
        versions=P2_V3_VERSIONS,
        query_evidence_ref=query_ref,
        query_ref="ref_" + "Q" * 22,
        result_ref="ref_" + "R" * 22,
        operation=P2ReadOperation.EXPENSES,
        criteria_ref="ref_" + "C" * 22,
        criteria_digest=DIGEST_A,
        normalized_criteria_digest=DIGEST_B,
        backend_criteria_stage="scope_only",
        source_kind="expenses",
        source_ref=EXPENSE_SOURCE_REF,
        source_version="v12",
        observed_at=NOW,
        simulation=simulation,
        returned_count=returned,
        matched_count=matched,
        source_total=total,
        matched_total=total,
        page_count=1,
        query_zero_classification="unknown_or_partial" if has_more else zero,
        source_query_complete=source_complete,
        model_projection_complete=model_complete,
        matching_fact_refs=matching_refs,
        financial_versions=financial_versions,
        page=page_summary,
        query_digest=DIGEST_B,
        body_digest=DIGEST_C,
        projection_digest=DIGEST_D,
    )
    page = P2PageProjection(
        items=facts,
        completeness=ReadCompleteness.PARTIAL if has_more else ReadCompleteness.COMPLETE,
        has_more=has_more,
        next_page_ref=CAP_REF if has_more else None,
        page_index=0,
        range_contiguous=True,
        stable_total_verified=stable,
        source_version_fenced=True,
        unique_items_verified=True,
        expected_total=total if stable else None,
    )
    return evidence, facts, page


def _live_result(*, has_more: bool = False, include_fact: bool = False) -> P2ReadBackendResult:
    evidence, facts, page = _source_page(has_more=has_more, include_fact=include_fact)
    return P2ReadBackendResult(operation=P2ReadOperation.EXPENSES, query_evidence=evidence, page=page)


def _answer_with_fact(*, simulation: bool = False) -> P2V3HistoricalAnswer:
    evidence, facts, _ = _source_page(include_fact=True, simulation=simulation)
    return P2V3HistoricalAnswer(
        **_base_output_fields(read_epoch=1, simulation=simulation),
        kind="answer",
        basis="fresh_read_receipts",
        text="The Coffee expense was USD 19.0000.",
        citations=(QEV_REF,),
        query_evidence=(evidence,),
        fact_cards=facts,
        source_labels=(),
        current_actor=None,
    )


def test_strict_query_parser_rejects_bool_extra_and_bad_bounds():
    assert parse_p2_v3_event_poll_query('{"after_seq":0,"limit":10}') == P2V3EventPollQuery(after_seq=0, limit=10)
    for wire in (
        {"after_seq": True, "limit": 10},
        {"after_seq": 0, "limit": 0},
        {"after_seq": 0, "limit": 10, "owner_id": str(OWNER_ID)},
    ):
        with pytest.raises(P2V3EventContractError):
            parse_p2_v3_event_poll_query(wire)
    with pytest.raises(P2V3EventContractError):
        parse_p2_v3_event_poll_query('{"after_seq":0,"after_seq":1,"limit":10}')


def test_source_free_activity_scope_clarification_is_valid_without_phantom_scope():
    output = _clarification()
    gate = _source_free_gate(
        output,
        basis="source_free_control_intent",
        text_origin="server_controlled_clarification",
    )
    sidecar = _sidecar(output, gate)
    assert isinstance(sidecar.history_gate, P2V3PrivateSourceFreeHistoryGate)
    assert not hasattr(sidecar.history_gate, "scopes")
    changed_text = output.model_copy(update={"prompt": "Which activity in Atlas should I use?"})
    with pytest.raises(ValidationError, match="exact historical context"):
        _sidecar(changed_text, gate)


def test_metadata_only_source_bearing_clarification_requires_private_scope_and_metadata_proof():
    output = _clarification(prompt="Which expense in Atlas did you mean?")
    # The model-visible source name has no financial QEV or public label. The
    # private assembler nevertheless classifies the source-derived text and
    # binds the exact source metadata row and scope locator.
    gate = _scope_gate(
        output,
        kinds=("display_labels", "source_text"),
        metadata=(_metadata_proof(),),
        text_scope_refs=(ACTIVITY_REF,),
    )
    sidecar = _sidecar(output, gate)
    assert sidecar.history_gate.mode == "scope_gated"
    assert sidecar.history_gate.bound_read_epoch == 0
    assert isinstance(output, P2V3HistoricalClarification) and output.read_epoch == 0
    response = project_p2_v3_event_page(
        snapshot=P2V3PrivateTurnSnapshot(
            owner_id=OWNER_ID,
            turn_id=TURN_ID,
            turn_ref=TURN_REF,
            profile_id=P2_V3_CANDIDATE_PROFILE_ID,
            protocol_versions=P2_V3_VERSIONS,
        ),
        query=P2V3EventPollQuery(after_seq=0, limit=1),
        canonical_status_events=(_status(4),),
        sidecars=(sidecar,),
        has_more=False,
    )
    public_json = response.model_dump_json()
    assert "Atlas" in public_json
    assert "history_gate" not in public_json
    for private_id in (SCOPE_LOCATOR_ID, ACTIVITY_LOCATOR_ID, SOURCE_ROW_ID, METADATA_PROOF_ID):
        assert str(private_id) not in public_json

    with pytest.raises(ValidationError):
        P2V3PrivateSourceFreeHistoryGate(
            mode="source_free",
            basis="source_free_control_intent",
            bound_context_ref=output.context_ref,
            bound_context_digest=output.context_digest,
            bound_generation=output.generation,
            bound_read_epoch=output.read_epoch,
            source_projection_empty=True,
            source_projection_kinds=("display_labels",),
            text_origin="server_controlled_clarification",
        )

    title_output = _clarification(prompt="Which Coffee expense did you mean?")
    title_gate = _scope_gate(
        title_output,
        kinds=("expense_titles", "source_text"),
        metadata=(_metadata_proof(entity_kind="expense"),),
        text_scope_refs=(ACTIVITY_REF,),
    )
    assert _sidecar(title_output, title_gate)

    actor_text_output = _clarification(prompt="Did you mean your own participant entry?")
    actor_text_gate = _scope_gate(
        actor_text_output,
        kinds=("current_actor", "source_text"),
        metadata=(_metadata_proof(entity_kind="current_actor"),),
        text_scope_refs=(ACTIVITY_REF,),
    )
    actor_text_sidecar = _sidecar(actor_text_output, actor_text_gate)
    assert actor_text_sidecar.history_gate.bound_read_epoch == 0


def test_metadata_only_clarification_without_its_private_proof_is_rejected():
    output = _clarification(prompt="Which expense in Atlas did you mean?")
    gate = _scope_gate(
        output,
        kinds=("display_labels", "source_text"),
        text_scope_refs=(ACTIVITY_REF,),
    )
    with pytest.raises(ValidationError, match="scope has no private metadata or query proof"):
        _sidecar(output, gate)


def test_source_free_nonbusiness_answer_and_proposal_intent_are_distinct_from_source_answers():
    nonbusiness = P2V3HistoricalAnswer(
        **_base_output_fields(),
        kind="answer",
        basis="non_business_general",
        text="Hello.",
        citations=(),
        query_evidence=(),
        fact_cards=(),
        source_labels=(),
        current_actor=None,
    )
    assert _sidecar(nonbusiness, _source_free_gate(
        nonbusiness, basis="non_business_general", text_origin="non_business_answer"
    ))
    proposal = P2V3HistoricalProposalIntent(
        **_base_output_fields(),
        kind="proposal_intent",
        operation=P2ProposalOperation.EXPENSE_CREATE,
        recognized_intent_text="Add coffee expense from original user intent.",
    )
    assert _sidecar(proposal, _source_free_gate(
        proposal, basis="source_free_control_intent", text_origin="original_user_intent"
    ))
    with pytest.raises(ValidationError):
        _sidecar(nonbusiness, _scope_gate(nonbusiness, kinds=("source_text",), text_scope_refs=(ACTIVITY_REF,)))


def test_source_backed_answer_preserves_fact_lexemes_and_requires_fact_row_proof():
    output = _answer_with_fact(simulation=True)
    assert output.fact_cards[0].title == "Coffee"
    assert output.fact_cards[0].signed_original_amount == "19.0000"
    assert output.fact_cards[0].signed_base_amount == "19.0"
    assert output.fact_cards[0].original_currency == "USD"
    assert output.fact_cards[0].occurred_at == NOW
    assert output.simulation is True and output.query_evidence[0].simulation is True
    qev = _private_qev_proof(
        output.query_evidence[0],
        fact_rows=(P2V3PrivateFactRowBinding(
            fact_ref=EXPENSE_REF,
            private_source_row_id=FACT_ROW_ID,
            private_fact_proof_id=FACT_PROOF_ID,
        ),),
    )
    gate = _scope_gate(
        output,
        kinds=("financial_facts", "query_evidence", "expense_titles"),
        metadata=(_metadata_proof(entity_kind="expense"),),
        qev=(qev,),
        text_scope_refs=(ACTIVITY_REF,),
    )
    assert _sidecar(output, gate)
    missing_fact_binding = qev.model_copy(update={"fact_rows": ()})
    with pytest.raises(ValidationError, match="exactly bind each included financial fact row"):
        _sidecar(output, _scope_gate(
            output,
            kinds=("financial_facts", "query_evidence", "expense_titles"),
            metadata=(_metadata_proof(entity_kind="expense"),),
            qev=(missing_fact_binding,),
            text_scope_refs=(ACTIVITY_REF,),
        ))


def test_live_read_continuation_becomes_history_has_more_without_raw_capability():
    live = _live_result(has_more=True)
    historical = project_live_p2_read_result_for_history(live)
    assert historical.page.has_more is True
    assert historical.page.completeness == "partial"
    assert historical.page.page_index == live.page.page_index
    assert historical.page.range_contiguous is live.page.range_contiguous
    assert historical.page.stable_total_verified is live.page.stable_total_verified
    assert historical.page.source_version_fenced is live.page.source_version_fenced
    assert historical.page.unique_items_verified is live.page.unique_items_verified
    assert historical.page.expected_total == live.page.expected_total
    assert historical.query_evidence.page.has_more is historical.page.has_more
    assert historical.query_evidence.page.range_contiguous is historical.page.range_contiguous
    assert not hasattr(historical.page, "next_page_ref")
    wire = json.loads(historical.model_dump_json())
    assert "next_page_ref" not in wire["page"]
    assert CAP_REF not in historical.model_dump_json()

    output = P2V3HistoricalReadResult(
        **_base_output_fields(read_epoch=1),
        kind="read_result",
        result=historical,
        source_labels=(),
        current_actor=None,
    )
    qev = _private_qev_proof(output.result.query_evidence)
    gate = _scope_gate(output, kinds=("query_evidence",), qev=(qev,))
    assert _sidecar(output, gate)

    tampered = json.loads(output.model_dump_json())
    tampered["result"]["page"]["next_page_ref"] = CAP_REF
    with pytest.raises(P2V3EventContractError):
        parse_p2_v3_historical_output(tampered)


def test_history_sidecar_must_bind_public_metadata_to_exact_private_source_row():
    label_answer = P2V3HistoricalAnswer(
        **_base_output_fields(read_epoch=1),
        kind="answer",
        basis="fresh_read_receipts",
        text="Atlas has no matching expenses in the complete requested range.",
        citations=(QEV_REF,),
        query_evidence=(_source_page()[0],),
        fact_cards=(),
        source_labels=(
            {
                "entity_ref": ACTIVITY_REF,
                "entity_kind": "activity",
                "scope_ref": ACTIVITY_REF,
                "display_name": "Atlas",
                "source_kind": "activities",
                "observed_at": NOW,
                "scope_financial_version": 0,
                "source_financial_version": 0,
                "source_row_updated_at": None,
                "source_receipt_ref": LABEL_RECEIPT_REF,
            },
        ),
        current_actor=None,
    )
    qev = _private_qev_proof(label_answer.query_evidence[0])
    good_metadata = _metadata_proof()
    good_gate = _scope_gate(
        label_answer,
        kinds=("query_evidence", "display_labels"),
        metadata=(good_metadata,),
        qev=(qev,),
        text_scope_refs=(ACTIVITY_REF,),
    )
    assert label_answer.source_labels[0].display_name == "Atlas"
    assert label_answer.source_labels[0].observed_at == NOW
    assert _sidecar(label_answer, good_gate)
    wrong_metadata = good_metadata.model_copy(update={"private_source_row_id": FACT_ROW_ID})
    # Shape helper doesn't attest that a UUID is the real database row; it does
    # reject missing/mismatched public bindings. Current membership stays a
    # future caller's fresh authorization responsibility.
    assert _sidecar(label_answer, _scope_gate(
        label_answer,
        kinds=("query_evidence", "display_labels"),
        metadata=(wrong_metadata,),
        qev=(qev,),
        text_scope_refs=(ACTIVITY_REF,),
    ))
    missing = good_metadata.model_copy(update={"source_receipt_ref": "ref_" + "M" * 22})
    with pytest.raises(ValidationError, match="lacks an exact private source proof"):
        _sidecar(label_answer, _scope_gate(
            label_answer,
            kinds=("query_evidence", "display_labels"),
            metadata=(missing,),
            qev=(qev,),
            text_scope_refs=(ACTIVITY_REF,),
        ))


def test_current_actor_projection_needs_private_auth_mapping_metadata_proof():
    evidence = _source_page()[0]
    actor_answer = P2V3HistoricalAnswer(
        **_base_output_fields(read_epoch=1),
        kind="answer",
        basis="fresh_read_receipts",
        text="The current participant is associated with this activity.",
        citations=(QEV_REF,),
        query_evidence=(evidence,),
        fact_cards=(),
        source_labels=(),
        current_actor={
            "actor_ref": ACTOR_REF,
            "activity_ref": ACTIVITY_REF,
            "participant_ref": PARTICIPANT_REF,
            "source_kind": "participant_claims.current_auth_user",
            "observed_at": NOW,
            "scope_financial_version": 0,
            "source_receipt_ref": LABEL_RECEIPT_REF,
        },
    )
    assert actor_answer.current_actor.actor_ref == ACTOR_REF
    assert actor_answer.current_actor.participant_ref == PARTICIPANT_REF
    assert actor_answer.current_actor.observed_at == NOW
    qev = _private_qev_proof(evidence)
    good = _scope_gate(
        actor_answer,
        kinds=("current_actor", "query_evidence"),
        metadata=(_metadata_proof(entity_kind="current_actor"),),
        qev=(qev,),
        text_scope_refs=(ACTIVITY_REF,),
    )
    assert _sidecar(actor_answer, good)
    wrong = _metadata_proof(entity_kind="current_actor").model_copy(update={"source_ref": ACTIVITY_REF})
    with pytest.raises(ValidationError):
        _sidecar(actor_answer, _scope_gate(
            actor_answer,
            kinds=("current_actor", "query_evidence"),
            metadata=(wrong,),
            qev=(qev,),
            text_scope_refs=(ACTIVITY_REF,),
        ))


def test_projection_uses_status_cursor_allows_sidecar_gaps_and_hides_private_uuid():
    output = _clarification()
    sidecar = _sidecar(output, _source_free_gate(
        output, basis="source_free_control_intent", text_origin="server_controlled_clarification"
    ))
    snapshot = P2V3PrivateTurnSnapshot(
        owner_id=OWNER_ID,
        turn_id=TURN_ID,
        turn_ref=TURN_REF,
        profile_id=P2_V3_CANDIDATE_PROFILE_ID,
        protocol_versions=P2_V3_VERSIONS,
    )
    projected = project_p2_v3_event_page(
        snapshot=snapshot,
        query=P2V3EventPollQuery(after_seq=0, limit=2),
        canonical_status_events=(_status(1), _status(4)),
        sidecars=(sidecar,),
        has_more=False,
    )
    wire = projected.model_dump_json()
    assert projected.next_after_seq == 4
    assert projected.events[0].historical_output is None
    assert projected.events[1].historical_output.kind == "clarify"
    assert "history_gate" not in wire
    assert str(OWNER_ID) not in wire
    assert str(TURN_ID) not in wire

    with pytest.raises(P2V3EventContractError, match="no matching status event"):
        project_p2_v3_event_page(
            snapshot=snapshot,
            query=P2V3EventPollQuery(after_seq=0, limit=2),
            canonical_status_events=(_status(1), _status(4)),
            sidecars=(_sidecar(output, sidecar.history_gate, seq=3),),
            has_more=False,
        )
    with pytest.raises(P2V3EventContractError, match="owner-bound Turn snapshot"):
        project_p2_v3_event_page(
            snapshot=snapshot,
            query=P2V3EventPollQuery(after_seq=0, limit=2),
            canonical_status_events=(_status(4),),
            sidecars=(_sidecar(output, sidecar.history_gate, owner_id=UUID("a0000000-0000-4000-8000-00000000000a")),),
            has_more=False,
        )


def test_status_only_page_is_valid_and_non_status_events_are_not_accepted():
    snapshot = P2V3PrivateTurnSnapshot(
        owner_id=OWNER_ID,
        turn_id=TURN_ID,
        turn_ref=TURN_REF,
        profile_id=P2_V3_CANDIDATE_PROFILE_ID,
        protocol_versions=P2_V3_VERSIONS,
    )
    page = project_p2_v3_event_page(
        snapshot=snapshot,
        query=P2V3EventPollQuery(after_seq=4, limit=5),
        canonical_status_events=(),
        sidecars=(),
        has_more=False,
    )
    assert page.next_after_seq == 4 and not page.events
    message = MessageEvent.model_validate(
        {
            "type": "message",
            "seq": 5,
            "occurred_at": NOW.isoformat(),
            "simulation": False,
            "payload": {"text": "not a status event", "citations": []},
        },
        strict=True,
    )
    with pytest.raises(P2V3EventContractError, match="only canonical status events"):
        project_p2_v3_event_page(
            snapshot=snapshot,
            query=P2V3EventPollQuery(after_seq=4, limit=5),
            canonical_status_events=(message,),
            sidecars=(),
            has_more=False,
        )


def test_unknown_zero_semantics_and_explicit_nullable_source_fields_survive_history():
    live = _live_result(has_more=True)
    historical = project_live_p2_read_result_for_history(live)
    assert historical.query_evidence.query_zero_classification == "unknown_or_partial"
    assert historical.query_evidence.source_total == 0
    assert historical.query_evidence.matched_total == 0
    output = P2V3HistoricalReadResult(
        **_base_output_fields(read_epoch=1),
        kind="read_result",
        result=historical,
        source_labels=(),
        current_actor=None,
    )
    raw = json.loads(output.model_dump_json())
    raw["result"]["query_evidence"]["source_total"] = None
    raw["result"]["query_evidence"]["matched_total"] = None
    parsed = parse_p2_v3_historical_output(json.dumps(raw))
    assert parsed.result.query_evidence.source_total is None
    assert parsed.result.query_evidence.matched_total is None
    del raw["result"]["query_evidence"]["source_total"]
    with pytest.raises(P2V3EventContractError):
        parse_p2_v3_historical_output(json.dumps(raw))


def test_private_fact_ref_mapping_covers_all_seven_closed_v3_fact_kinds():
    refs = {
        "activity": "activity_ref",
        "expense": "expense_ref",
        "debt": "debt_ref",
        "refund_event": "refund_ref",
        "prepayment_account": "account_ref",
        "prepayment_usage": "usage_ref",
        "prepayment_return_event": "return_event_ref",
    }
    types = {
        "activity": ActivityFact,
        "expense": ExpenseFact,
        "debt": DebtFact,
        "refund_event": RefundEventFact,
        "prepayment_account": PrepaymentAccountFact,
        "prepayment_usage": PrepaymentUsageFact,
        "prepayment_return_event": PrepaymentReturnEventFact,
    }
    for index, (kind, field) in enumerate(refs.items(), start=1):
        reference = "ref_" + chr(ord("A") + index) * 22
        synthetic_unvalidated = types[kind].model_construct(fact_kind=kind, **{field: reference})
        assert _fact_public_ref(synthetic_unvalidated) == reference


def test_private_scope_bindings_allow_multiple_child_scopes_for_one_activity_and_actor():
    base = _answer_with_fact()
    wire = base.model_dump()
    wire["fact_cards"][0]["scope_ref"] = CHILD_SCOPE_REF
    wire["current_actor"] = {
        "actor_ref": ACTOR_REF,
        "activity_ref": ACTIVITY_REF,
        "participant_ref": PARTICIPANT_REF,
        "source_kind": "participant_claims.current_auth_user",
        "observed_at": NOW,
        "scope_financial_version": 3,
        "source_receipt_ref": LABEL_RECEIPT_REF,
    }
    output = P2V3HistoricalAnswer.model_validate(wire, strict=True)
    qev = _private_qev_proof(
        output.query_evidence[0],
        scope_ref=CHILD_SCOPE_REF,
        fact_rows=(P2V3PrivateFactRowBinding(
            fact_ref=EXPENSE_REF,
            private_source_row_id=FACT_ROW_ID,
            private_fact_proof_id=FACT_PROOF_ID,
        ),),
    )
    scopes = (
        _scope_binding(),
        _scope_binding(
            scope_ref=CHILD_SCOPE_REF,
            activity_ref=ACTIVITY_REF,
            private_scope_locator_id=SCOPE_LOCATOR_ID_2,
            private_activity_locator_id=ACTIVITY_LOCATOR_ID,
        ),
    )
    gate = _scope_gate(
        output,
        kinds=("current_actor", "financial_facts", "query_evidence", "expense_titles", "source_text"),
        metadata=(
            _metadata_proof(entity_kind="expense", scope_ref=CHILD_SCOPE_REF),
            _metadata_proof(entity_kind="current_actor"),
        ),
        qev=(qev,),
        text_scope_refs=(ACTIVITY_REF, CHILD_SCOPE_REF),
        scopes=scopes,
    )
    assert _sidecar(output, gate)

    conflicting = _scope_binding(
        scope_ref=CHILD_SCOPE_REF,
        activity_ref=ACTIVITY_REF,
        private_scope_locator_id=SCOPE_LOCATOR_ID_2,
        private_activity_locator_id=ACTIVITY_LOCATOR_ID_2,
    )
    with pytest.raises(ValidationError, match="conflicting private Activity locators"):
        _scope_gate(output, kinds=("source_text",), scopes=(_scope_binding(), conflicting))


@pytest.mark.parametrize("zero", ("backend_zero", "post_filter_zero"))
def test_unscoped_activity_collection_accepts_only_explicit_complete_zero_classes(zero):
    output, gate, _evidence = _activity_collection_case(zero=zero)
    assert gate.scopes == ()
    assert gate.qev_proofs[0].binding_kind == "activity_collection"
    assert _sidecar(output, gate)
    wire = json.loads(_sidecar(output, gate).model_dump_json())
    assert "scope_ref" not in wire["history_gate"]["qev_proofs"][0]
    assert "jwt" not in json.dumps(wire).lower()

    unknown_evidence = output.result.query_evidence.model_copy(
        update={"query_zero_classification": "unknown_or_partial"}
    )
    unknown_output = output.model_copy(update={
        "result": output.result.model_copy(update={"query_evidence": unknown_evidence})
    })
    with pytest.raises(ValidationError, match="complete empty Activity coverage"):
        _sidecar(unknown_output, gate)


def test_unscoped_activity_collection_binds_multiple_members_and_partial_empty_stays_partial():
    output, gate, _evidence = _activity_collection_case(count=2)
    assert gate.scopes == ()
    assert len(gate.qev_proofs[0].activity_bindings) == 2
    assert _sidecar(output, gate)

    proof = gate.qev_proofs[0]
    missing_member = proof.model_copy(update={"activity_bindings": proof.activity_bindings[:1]})
    with pytest.raises(ValidationError, match="exactly bind the public QEV references"):
        _sidecar(output, gate.model_copy(update={"qev_proofs": (missing_member,)}))

    partial_output, partial_gate, evidence = _activity_collection_case(partial=True)
    assert partial_output.result.page.items == ()
    assert partial_output.result.page.completeness == ReadCompleteness.PARTIAL
    assert evidence.query_zero_classification == "unknown_or_partial"
    assert not evidence.source_query_complete and not evidence.model_projection_complete
    assert _sidecar(partial_output, partial_gate)
    falsely_complete = evidence.model_copy(update={
        "source_query_complete": True,
        "model_projection_complete": True,
    })
    with pytest.raises(ValueError, match="complete empty Activity coverage"):
        _validate_activity_zero_classification(falsely_complete, ())


def test_collection_text_uses_its_qev_but_does_not_authorize_activity_labels():
    read_output, gate, evidence = _activity_collection_case(count=1)
    proof = gate.qev_proofs[0]
    answer = P2V3HistoricalAnswer(
        **_base_output_fields(read_epoch=1),
        kind="answer",
        basis="fresh_read_receipts",
        text="Activity 1 is active.",
        citations=(ACTIVITY_QEV_REF,),
        query_evidence=(evidence,),
        fact_cards=read_output.result.page.items,
        source_labels=(),
        current_actor=None,
    )
    answer_gate = _scope_gate(
        answer,
        kinds=("query_evidence", "financial_facts", "source_text"),
        qev=(proof,),
        scopes=(),
        text_collection_query_refs=(ACTIVITY_QEV_REF,),
    )
    assert _sidecar(answer, answer_gate)
    without_text_binding = _scope_gate(
        answer,
        kinds=("query_evidence", "financial_facts", "source_text"),
        qev=(proof,),
        scopes=(),
    )
    with pytest.raises(ValidationError, match="source-bearing text requires"):
        _sidecar(answer, without_text_binding)

    label = P2EntityDisplayLabel(
        entity_ref=ACTIVITY_REF,
        entity_kind="activity",
        scope_ref=ACTIVITY_REF,
        display_name="Activity 1",
        source_kind="activities",
        observed_at=NOW,
        scope_financial_version=0,
        source_financial_version=0,
        source_row_updated_at=None,
        source_receipt_ref=LABEL_RECEIPT_REF,
    )
    labelled = read_output.model_copy(update={"source_labels": (label,)})
    with pytest.raises(ValidationError, match="public source metadata lacks an exact private source proof"):
        _sidecar(labelled, gate)


def test_expense_title_proof_is_row_and_scope_exact_without_activity_label_proof():
    output = _answer_with_fact()
    qev = _private_qev_proof(
        output.query_evidence[0],
        fact_rows=(P2V3PrivateFactRowBinding(
            fact_ref=EXPENSE_REF,
            private_source_row_id=FACT_ROW_ID,
            private_fact_proof_id=FACT_PROOF_ID,
        ),),
    )
    good = _scope_gate(
        output,
        kinds=("financial_facts", "query_evidence", "expense_titles"),
        metadata=(_metadata_proof(entity_kind="expense"),),
        qev=(qev,),
        text_scope_refs=(ACTIVITY_REF,),
    )
    assert "display_labels" not in good.source_projection_kinds
    assert _sidecar(output, good)

    wrong_expense = _metadata_proof(entity_kind="expense").model_copy(update={
        "entity_ref": "ref_" + "M" * 22,
        "source_ref": "ref_" + "M" * 22,
    })
    bad = good.model_copy(update={"metadata_proofs": (wrong_expense,)})
    with pytest.raises(ValidationError, match="exact private expense row and scope"):
        _sidecar(output, bad)


def test_private_financial_qev_checks_fact_reference_and_version_links():
    output = _answer_with_fact()
    qev = _private_qev_proof(
        output.query_evidence[0],
        fact_rows=(P2V3PrivateFactRowBinding(
            fact_ref=EXPENSE_REF,
            private_source_row_id=FACT_ROW_ID,
            private_fact_proof_id=FACT_PROOF_ID,
        ),),
    )
    gate = _scope_gate(
        output,
        kinds=("financial_facts", "query_evidence", "expense_titles"),
        metadata=(_metadata_proof(entity_kind="expense"),),
        qev=(qev,),
        text_scope_refs=(ACTIVITY_REF,),
    )
    wrong_version_fact = output.fact_cards[0].model_copy(update={"financial_version": 4})
    wrong_version_output = output.model_copy(update={"fact_cards": (wrong_version_fact,)})
    with pytest.raises(ValidationError, match="fact version"):
        _sidecar(wrong_version_output, gate)

    wrong_refs_evidence = output.query_evidence[0].model_copy(update={"matching_fact_refs": ()})
    wrong_refs_output = output.model_copy(update={"query_evidence": (wrong_refs_evidence,)})
    with pytest.raises(ValidationError, match="historical fact reference is absent"):
        _sidecar(wrong_refs_output, gate)


def test_scoped_activity_reads_remain_valid_and_cannot_escape_the_bound_activity():
    output, _collection_gate, evidence = _activity_collection_case(count=1)
    fact = output.result.page.items[0]
    scoped = _private_qev_proof(
        evidence,
        scope_ref=ACTIVITY_REF,
        fact_rows=(P2V3PrivateFactRowBinding(
            fact_ref=ACTIVITY_REF,
            private_source_row_id=ACTIVITY_LOCATOR_ID,
            private_fact_proof_id=FACT_PROOF_ID,
        ),),
    )
    gate = _scope_gate(
        output,
        kinds=("query_evidence", "financial_facts"),
        qev=(scoped,),
    )
    assert fact.activity_ref == ACTIVITY_REF
    assert _sidecar(output, gate)

    zero_output, _zero_collection_gate, zero_evidence = _activity_collection_case(zero="backend_zero")
    scoped_zero = _private_qev_proof(zero_evidence, scope_ref=ACTIVITY_REF)
    zero_gate = _scope_gate(
        zero_output,
        kinds=("query_evidence",),
        qev=(scoped_zero,),
    )
    assert _sidecar(zero_output, zero_gate)

    foreign_scope = _scope_binding(
        scope_ref=ACTIVITY_REF_2,
        activity_ref=ACTIVITY_REF_2,
        private_scope_locator_id=SCOPE_LOCATOR_ID_2,
        private_activity_locator_id=ACTIVITY_LOCATOR_ID_2,
    )
    escaped_qev = _private_qev_proof(
        evidence,
        scope_ref=ACTIVITY_REF_2,
        fact_rows=(P2V3PrivateFactRowBinding(
            fact_ref=ACTIVITY_REF,
            private_source_row_id=ACTIVITY_LOCATOR_ID_2,
            private_fact_proof_id=FACT_PROOF_ID,
        ),),
    )
    escaped_gate = _scope_gate(
        output,
        kinds=("query_evidence", "financial_facts"),
        qev=(escaped_qev,),
        scopes=(foreign_scope,),
    )
    with pytest.raises(ValidationError, match="outside its exact Activity locator"):
        _sidecar(output, escaped_gate)


def test_r4_scoped_activities_qev_financial_version_round_trips_and_rejects_foreign_activity():
    """Use the frozen R4 backend path, not a hand-built QEV, for this regression."""
    import asyncio
    import importlib

    source_test = importlib.import_module("test_p2_source_codec_backend_v3")

    async def read_scoped_activities():
        adapter, identity, locator, _budget, _transport, verified, admission = source_test._harness()
        projection = await adapter.admit_scope_v3(
            verified,
            admission,
            ui_activity_id_hint=source_test.ACTIVITY,
            ui_ledger_unit_id_hint=None,
        )
        assert projection is not None
        activity_ref = projection.snapshot.activity_ref
        scope = source_test.pc.P2Scope(
            scope_kind="activity",
            scope_ref=activity_ref,
            activity_ref=activity_ref,
            ledger_unit_ref=None,
        )
        request = source_test._request(
            source_test.pc.P2ReadOperation.ACTIVITIES,
            scope,
            activity_ref,
        )
        logical_id = "event-r4-scoped-activities-financial-version"
        query_ref = locator.query_ref(logical_id, identity=identity)
        locator.descriptors[query_ref] = source_test.codec.V3QueryDescriptor(
            request=request,
            public_request_digest=source_test.backend._canonical_sha(
                request.model_dump(mode="json", exclude_none=False)
            ),
            normalized_selection_digest=source_test.backend._canonical_sha({
                "criteria": request.criteria.model_dump(mode="json", exclude_none=False),
                "ui_expense_ids": (),
            }),
        )
        binding = source_test.codec.QueryAttemptBinding(
            identity, logical_id, "event-r4-scoped-activities-attempt", 0, "cpu-fake-claim",
        )
        grant = source_test.pc.P2SourceAuthorizationGrant(
            principal_ref=locator.principal_ref,
            owner_turn_ref=locator.owner_ref,
            generation=identity.generation,
            source_input_seq=identity.input_seq,
            input_digest=identity.input_digest,
            operation=request.operation,
            scope=request.scope,
            criteria_digest=source_test.pc.p2_criteria_digest(request.criteria),
            expires_at=source_test.datetime.now(source_test.timezone.utc) + source_test.timedelta(minutes=2),
            grant_ref=locator.ref("event-r4-scoped-activities-grant"),
        )
        live = await adapter.read_candidate_v3(
            request,
            verified,
            grant,
            admission=admission,
            admission_projection=projection,
            query_binding=binding,
            context_version="server-context-r4-cpu",
        )
        return live

    live = asyncio.run(read_scoped_activities())
    evidence = live.query_evidence
    assert evidence.operation == P2ReadOperation.ACTIVITIES
    assert evidence.source_kind == "activities"
    assert len(evidence.financial_versions) == 1
    assert len(live.page.items) == 1
    fact = live.page.items[0]
    assert fact.fact_kind == "activity"
    assert fact.context_version == "server-context-r4-cpu"
    # The actual QEV version comes from the R4 scope snapshot. It is not
    # inferred from ActivityFact.context_version.
    assert evidence.financial_versions[0].financial_version == 7
    assert evidence.financial_versions[0].activity_ref == fact.activity_ref

    projected = project_live_p2_read_result_for_history(live)
    base_fields = _base_output_fields(read_epoch=1)
    base_fields["observed_at"] = evidence.observed_at
    output = P2V3HistoricalReadResult(
        **base_fields,
        kind="read_result",
        result=projected,
        source_labels=(),
        current_actor=None,
    )
    scope_binding = _scope_binding(
        scope_ref=fact.activity_ref,
        activity_ref=fact.activity_ref,
    )
    fact_row = P2V3PrivateFactRowBinding(
        fact_ref=fact.activity_ref,
        private_source_row_id=ACTIVITY_LOCATOR_ID,
        private_fact_proof_id=FACT_PROOF_ID,
    )
    proof = _private_qev_proof(
        evidence,
        scope_ref=fact.activity_ref,
        fact_rows=(fact_row,),
    )
    good_gate = _scope_gate(
        output,
        kinds=("query_evidence", "financial_facts"),
        qev=(proof,),
        scopes=(scope_binding,),
    )
    assert _sidecar(output, good_gate)

    foreign_evidence = evidence.model_copy(update={
        "financial_versions": (
            P2FinancialVersion(
                activity_ref=ACTIVITY_REF_2,
                financial_version=evidence.financial_versions[0].financial_version,
            ),
        ),
    })
    foreign_live = live.model_copy(update={"query_evidence": foreign_evidence})
    foreign_projected = project_live_p2_read_result_for_history(foreign_live)
    foreign_output = output.model_copy(update={"result": foreign_projected})
    foreign_proof = _private_qev_proof(
        foreign_evidence,
        scope_ref=fact.activity_ref,
        fact_rows=(fact_row,),
    )
    foreign_gate = good_gate.model_copy(update={"qev_proofs": (foreign_proof,)})
    with pytest.raises(ValidationError, match="financial version does not match its private Activity locator"):
        _sidecar(foreign_output, foreign_gate)



def test_response_parser_rejects_mixed_tuple_and_extra_private_fields():
    output = _clarification()
    projected = project_p2_v3_event_page(
        snapshot=P2V3PrivateTurnSnapshot(
            owner_id=OWNER_ID,
            turn_id=TURN_ID,
            turn_ref=TURN_REF,
            profile_id=P2_V3_CANDIDATE_PROFILE_ID,
            protocol_versions=P2_V3_VERSIONS,
        ),
        query=P2V3EventPollQuery(after_seq=0, limit=1),
        canonical_status_events=(_status(1),),
        sidecars=(_sidecar(output, _source_free_gate(
            output, basis="source_free_control_intent", text_origin="server_controlled_clarification"
        ), seq=1),),
        has_more=False,
    )
    wire = json.loads(projected.model_dump_json())
    wire["events"][0]["historical_output"]["owner_id"] = str(OWNER_ID)
    with pytest.raises(P2V3EventContractError):
        parse_p2_v3_event_poll_response(wire)
    wire = json.loads(projected.model_dump_json())
    wire["protocol_versions"]["api"] = "3.1.0"
    with pytest.raises(P2V3EventContractError):
        parse_p2_v3_event_poll_response(wire)

