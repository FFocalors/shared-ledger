"""Repeatable synthetic examples for the offline T1 query-evidence protocol."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from . import v1_contracts as v1
from .contracts import (
    ActivityPostFilter,
    AnswerDecision,
    ModelContext,
    NegotiatedVersions,
    QueryEvidenceObservation,
    QueryEvidenceRef,
    QueryPageMetadata,
    QuerySource,
    ReadCriteriaV11,
    ReadDecision,
    ReadExpensesCriteria,
    backend_criteria_for,
    body_digest,
    calculate_query_digest,
    canonical_hash,
    exact_hash,
    normalized_criteria,
    post_filter_for,
)
from .harness import (
    BoundQueryEvidence,
    CurrentQueryState,
    FinancialVersionFence,
    PageReceipt,
    TrustedSourceSnapshot,
    bind_trusted_query,
    make_query_observation,
    row_identity_digest,
    validate_context_bindings,
)

FIXTURE_OBSERVED_AT = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
FIXTURE_SOURCE_VERSION = "synthetic-source-v1"
FIXTURE_GENERATION = 1
FIXTURE_REVISION = 1
FIXTURE_FRESHNESS_EPOCH = 1


@dataclass(frozen=True)
class SyntheticQueryExample:
    name: str
    context: ModelContext
    actual_result: v1.ToolReadResult
    binding: BoundQueryEvidence
    owner_id: uuid.UUID
    turn_id: uuid.UUID
    scope_activity_id: Optional[uuid.UUID]
    bound_references: list[v1.BoundReference]
    bound_evidence_references: list[v1.BoundEvidenceReference]
    bound_read_results: list[v1.BoundReadResultReference]

    def validate(self):
        current = CurrentQueryState(
            query_ref=self.binding.query_ref,
            result_id=self.binding.result_id,
            owner_id=self.owner_id,
            source_turn_id=self.turn_id,
            generation=self.binding.generation,
            expected_revision=self.binding.expected_revision,
            freshness_epoch=self.binding.freshness_epoch,
            current_generation=self.binding.generation,
            current_revision=self.binding.expected_revision,
            current_freshness_epoch=self.binding.freshness_epoch,
            status="current",
            scope_activity_id=self.binding.scope_activity_id,
            context_version=self.binding.context_version,
            source=self.binding.source,
            source_version=self.binding.source_version,
            source_fingerprint=self.binding.source_fingerprint,
            source_snapshot_fingerprint=self.binding.source_snapshot_fingerprint,
            observed_at=self.binding.observed_at,
            query_digest=self.binding.query_digest,
            body_digest=self.binding.body_digest,
        )
        return validate_context_bindings(
            self.context,
            current_owner_id=self.owner_id,
            current_turn_id=self.turn_id,
            generation=self.binding.generation,
            expected_revision=self.binding.expected_revision,
            freshness_epoch=self.binding.freshness_epoch,
            current_context_version=self.context.context_version,
            current_query_states=[current],
            trusted_tool_results=[self.actual_result],
            bound_queries=[self.binding],
            bound_references=self.bound_references,
            bound_evidence_references=self.bound_evidence_references,
            bound_read_results=self.bound_read_results,
        )


def _id(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.UUID("c23f5c6a-d1c5-5d9f-bc97-e2fc3bb7cf54"), name)


def _page_meta(*, count: int, expected: int, partial: bool = False) -> QueryPageMetadata:
    return QueryPageMetadata(
        pages_seen=1,
        expected_total=expected,
        has_more=partial,
        truncated=partial,
        complete=not partial,
        range_contiguous=True,
        stable_total_verified=True,
        source_version_fenced=True,
        unique_items_verified=True,
    )


def make_synthetic_example(
    kind: str,
    *,
    title_contains: Optional[str] = None,
    partial: bool = False,
    titles: Optional[list[str]] = None,
    fixture_key: Optional[str] = None,
    query_ref_override: Optional[QueryEvidenceRef] = None,
    result_ref_override: Optional[v1.ReadResultRef] = None,
    context_version: int = 1,
    observed_at: datetime = FIXTURE_OBSERVED_AT,
    source_version: str = FIXTURE_SOURCE_VERSION,
    expected_revision: int = FIXTURE_REVISION,
    owner_id_override: Optional[uuid.UUID] = None,
    turn_id_override: Optional[uuid.UUID] = None,
    activity_id_override: Optional[uuid.UUID] = None,
    participant_id_override: Optional[uuid.UUID] = None,
    expense_ref_offset: int = 0,
    participant_ref: Optional[v1.ParticipantRef] = None,
) -> SyntheticQueryExample:
    """Build one trusted offline query fixture without loading old release-v2 receipts."""
    if kind not in {"empty_activities", "empty_cad_debts", "expenses_postfilter_empty"}:
        raise ValueError("unknown synthetic query example")
    if partial and kind != "expenses_postfilter_empty":
        raise ValueError("the partial fixture is a five-row expense query")
    suffix = fixture_key or kind + ("_partial" if partial else "")
    owner_id = owner_id_override or _id(suffix + ":owner")
    turn_id = turn_id_override or _id(suffix + ":turn")
    result_id = _id(suffix + ":result")
    permissions: list[v1.HarnessPermission]
    references: list[v1.BoundReference] = []
    evidence: list[v1.BoundEvidenceReference] = []
    scope_activity_id: Optional[uuid.UUID] = None
    facts: list[object] = []

    if kind == "empty_activities":
        operation = v1.ReadOperation.ACTIVITIES
        criteria: ReadCriteriaV11 = v1.ReadActivitiesCriteria(
            kind="activities", status="active", name_contains=None
        )
        verified_scope = v1.ModelNoActivityScope(
            kind="none", permissions=[v1.HarnessPermission.READ_ACTIVITIES]
        )
        permissions = [v1.HarnessPermission.READ_ACTIVITIES]
        body = v1.ActivityListResult(kind="activities", items=[])
        input_text = "List active activities."
        query_ref = QueryEvidenceRef.Q01
    elif kind == "empty_cad_debts":
        operation = v1.ReadOperation.DEBTS
        activity_id = activity_id_override or _id(suffix + ":activity")
        scope_activity_id = activity_id
        criteria = v1.ReadDebtsCriteria(
            kind="debts", activity_ref=v1.ActivityRef.A01, participant_ref=None, currency="CAD"
        )
        verified_scope = v1.ModelActivityScope(
            kind="activity",
            activity_ref=v1.ActivityRef.A01,
            permissions=[v1.HarnessPermission.READ_DEBTS],
        )
        permissions = [v1.HarnessPermission.READ_DEBTS]
        references.append(v1.BoundActivityReference(
            kind="activity",
            ref=v1.ActivityRef.A01,
            entity_id=activity_id,
            source_turn_id=turn_id,
            scope_activity_id=activity_id,
        ))
        body = v1.DebtListResult(kind="debts", items=[])
        input_text = "Are there any debts in CAD?"
        query_ref = QueryEvidenceRef.Q02
    else:
        operation = v1.ReadOperation.EXPENSES
        activity_id = activity_id_override or _id(suffix + ":activity")
        scope_activity_id = activity_id
        criteria = ReadExpensesCriteria(
            kind="expenses",
            activity_ref=v1.ActivityRef.A01,
            from_date=None,
            to_date=None,
            participant_ref=participant_ref,
            title_contains=title_contains if title_contains is not None else "rail",
        )
        verified_scope = v1.ModelActivityScope(
            kind="activity",
            activity_ref=v1.ActivityRef.A01,
            permissions=[v1.HarnessPermission.READ_EXPENSES],
        )
        permissions = [v1.HarnessPermission.READ_EXPENSES]
        references.append(v1.BoundActivityReference(
            kind="activity",
            ref=v1.ActivityRef.A01,
            entity_id=activity_id,
            source_turn_id=turn_id,
            scope_activity_id=activity_id,
        ))
        all_titles = titles or ["Cafe 1", "Cafe 2", "Cafe 3", "Cafe 4", "Cafe 5"]
        selected_titles = all_titles[:1] if partial else all_titles
        participant_id = participant_id_override or _id(suffix + ":participant_1")
        references.append(v1.BoundParticipantReference(
            kind="participant",
            ref=v1.ParticipantRef.P01,
            entity_id=participant_id,
            source_turn_id=turn_id,
            scope_activity_id=activity_id,
        ))
        for index, title in enumerate(selected_titles, start=1):
            expense_id = _id(f"{suffix}:expense_{index}")
            facts.append(v1.ExpenseFact(
                kind="expense",
                evidence_ref=list(v1.ExpenseEvidenceRef)[index - 1 + expense_ref_offset],
                expense_ref=list(v1.ExpenseRef)[index + expense_ref_offset],
                title=title,
                original_amount=f"{index}.00",
                original_currency="CAD",
                occurred_at=observed_at,
                participant_refs=[v1.ParticipantRef.P01],
                financial_locked=True,
                expense_version=str(index),
                observed_at=observed_at,
                context_version=context_version,
            ))
            references.append(v1.BoundExpenseReference(
                kind="expense",
                ref=list(v1.ExpenseRef)[index + expense_ref_offset],
                entity_id=expense_id,
                source_turn_id=turn_id,
                scope_activity_id=activity_id,
            ))
            evidence.append(v1.BoundExpenseEvidence(
                kind="expense",
                evidence_ref=list(v1.ExpenseEvidenceRef)[index - 1 + expense_ref_offset],
                entity_id=expense_id,
                scope_activity_id=activity_id,
                source_result_id=result_id,
                source_turn_id=turn_id,
                context_version=context_version,
            ))
        body = v1.ExpenseListResult(kind="expenses", items=facts)
        input_text = f'Find expenses whose title contains "{criteria.title_contains}".'
        query_ref = QueryEvidenceRef.Q03

    actual = v1.ToolReadResult(
        result_id=result_id,
        result_ref=result_ref_override or v1.ReadResultRef.R01,
        operation=operation,
        observed_at=observed_at,
        context_version=context_version,
        simulation=True,
        body=body,
    )
    if criteria.kind == "activities":
        financial_versions: list[FinancialVersionFence] = []
        membership_snapshot_id = _id(suffix + ":membership_snapshot")
    else:
        financial_versions = [FinancialVersionFence(
            activity_ref=criteria.activity_ref,
            private_activity_id=scope_activity_id,
            financial_version="1",
        )]
        membership_snapshot_id = None
    source_snapshot = TrustedSourceSnapshot(
        snapshot_id=_id(suffix + ":snapshot"),
        source_version=source_version,
        observed_at=observed_at,
        scope_activity_id=scope_activity_id,
        financial_versions=financial_versions,
        membership_snapshot_id=membership_snapshot_id,
    )
    source_snapshot_fingerprint = exact_hash(source_snapshot)
    source_fingerprint = source_snapshot_fingerprint
    page = _page_meta(count=len(actual.body.items), expected=5 if partial else len(actual.body.items), partial=partial)
    item_digests = [canonical_hash(fact) for fact in actual.body.items]
    evidence_by_ref = {entry.evidence_ref: entry.entity_id for entry in evidence}
    row_digests = [row_identity_digest(fact.kind, evidence_by_ref[fact.evidence_ref]) for fact in actual.body.items]
    cursor = canonical_hash({"cursor": suffix, "next": True}) if partial else None
    scope_fingerprint = canonical_hash({"scope_activity_id": str(scope_activity_id) if scope_activity_id else None})
    page_receipts = [PageReceipt(
        page_index=0,
        offset=0,
        item_digests=item_digests,
        row_identity_digests=row_digests,
        source_version=source_version,
        snapshot_fingerprint=source_snapshot_fingerprint,
        scope_fingerprint=scope_fingerprint,
        range_start=0,
        range_end_exclusive=len(item_digests),
        total_count=5 if partial else len(actual.body.items),
        cursor_in_digest=None,
        cursor_out_digest=cursor,
    )]
    binding = bind_trusted_query(
        query_ref=query_ref_override or query_ref,
        owner_id=owner_id,
        turn_id=turn_id,
        generation=FIXTURE_GENERATION,
        expected_revision=expected_revision,
        freshness_epoch=FIXTURE_FRESHNESS_EPOCH,
        scope_activity_id=scope_activity_id,
        result=actual,
        criteria=criteria,
        context_version=context_version,
        source=QuerySource.SYNTHETIC_SIMULATION,
        source_version=source_version,
        source_fingerprint=source_fingerprint,
        source_snapshot=source_snapshot,
        page=page,
        page_receipts=page_receipts,
    )
    observation = make_query_observation(binding, actual)
    model_result = v1.ModelReadResult(
        result_ref=actual.result_ref,
        operation=actual.operation,
        observed_at=actual.observed_at,
        context_version=actual.context_version,
        simulation=actual.simulation,
        body=actual.body,
    )
    context = ModelContext(
        context_version=context_version,
        intent_classification="business",
        input_text=input_text,
        verified_scope=verified_scope,
        recent_messages=[],
        pending_slots=[],
        bound_references=v1.model_reference_tokens(references),
        read_results=[model_result],
        policy_evidence=[],
        available_permissions=permissions,
        query_observations=[observation],
    )
    bound_read = v1.BoundReadResultReference(
        result_ref=actual.result_ref,
        result_id=actual.result_id,
        source_turn_id=turn_id,
        operation=actual.operation,
        observed_at=actual.observed_at,
        context_version=actual.context_version,
    )
    return SyntheticQueryExample(
        name=kind + ("_partial" if partial else ""),
        context=context,
        actual_result=actual,
        binding=binding,
        owner_id=owner_id,
        turn_id=turn_id,
        scope_activity_id=scope_activity_id,
        bound_references=references,
        bound_evidence_references=evidence,
        bound_read_results=[bound_read],
    )


def build_three_complete_examples() -> list[SyntheticQueryExample]:
    return [
        make_synthetic_example("empty_activities"),
        make_synthetic_example("empty_cad_debts"),
        make_synthetic_example("expenses_postfilter_empty"),
    ]


def build_two_turn_clarify_propose_trace():
    """A synthetic causal example: preserve initial title/payer/split across one resume."""
    from .trajectory import (
        ModelDecisionStep,
        T1TrajectoryV11,
        ToolObservationStep,
        UserClarificationStep,
        UserInputStep,
    )

    initial = "Add Lunch to Dinner, paid by Alice, and split equally with Alice and Jo."
    clarification = "50 USD."
    owner_id, turn_id, activity_id = _id("resume:owner"), _id("resume:turn"), _id("resume:activity")
    criteria = ReadExpensesCriteria(
        kind="expenses", activity_ref=v1.ActivityRef.A01, from_date=None, to_date=None, participant_ref=None
    )
    permissions = [v1.HarnessPermission.READ_EXPENSES, v1.HarnessPermission.PROPOSE_EXPENSE_CREATE]
    scope = v1.ModelActivityScope(kind="activity", activity_ref=v1.ActivityRef.A01, permissions=permissions)
    references: list[v1.BoundReference] = [
        v1.BoundActivityReference(
            kind="activity", ref=v1.ActivityRef.A01, entity_id=activity_id,
            source_turn_id=turn_id, scope_activity_id=activity_id,
        ),
        v1.BoundLedgerUnitReference(
            kind="ledger_unit", ref=v1.LedgerUnitRef.U01, entity_id=_id("resume:ledger"),
            source_turn_id=turn_id, scope_activity_id=activity_id,
        ),
        v1.BoundParticipantReference(
            kind="participant", ref=v1.ParticipantRef.P01, entity_id=_id("resume:alice"),
            source_turn_id=turn_id, scope_activity_id=activity_id,
        ),
        v1.BoundParticipantReference(
            kind="participant", ref=v1.ParticipantRef.P02, entity_id=_id("resume:jo"),
            source_turn_id=turn_id, scope_activity_id=activity_id,
        ),
    ]
    model_refs = v1.model_reference_tokens(references)
    observed_at = datetime(2026, 10, 12, 10, tzinfo=timezone.utc)
    result = v1.ToolReadResult(
        result_id=_id("resume:read-result"),
        result_ref=v1.ReadResultRef.R01,
        operation=v1.ReadOperation.EXPENSES,
        observed_at=observed_at,
        context_version=1,
        simulation=True,
        body=v1.ExpenseListResult(kind="expenses", items=[]),
    )
    page = QueryPageMetadata(
        pages_seen=1, expected_total=0, has_more=False, truncated=False, complete=True,
        range_contiguous=True, stable_total_verified=True, source_version_fenced=True,
        unique_items_verified=True,
    )
    source_version = "synthetic-resume-source-v1"
    query = QueryEvidenceObservation(
        query_ref=QueryEvidenceRef.Q01,
        result_ref=result.result_ref,
        operation=result.operation,
        criteria=criteria,
        normalized_criteria=normalized_criteria(result.operation, criteria),
        backend_criteria=backend_criteria_for(criteria),
        post_filter=post_filter_for(criteria),
        context_version=1,
        source=QuerySource.SYNTHETIC_SIMULATION,
        source_version=source_version,
        observed_at=observed_at,
        simulation=True,
        returned_count=0,
        matched_count=0,
        matching_fact_citations=[],
        page=page,
        query_digest=calculate_query_digest(
            operation=result.operation, criteria=criteria,
            backend_criteria=backend_criteria_for(criteria), post_filter=post_filter_for(criteria),
            scope_activity_id=activity_id, context_version=1, schema_version="1.1.0",
            source=QuerySource.SYNTHETIC_SIMULATION, source_version=source_version,
        ),
        body_digest=body_digest(result.body),
    )
    visible_result = v1.ModelReadResult(
        result_ref=result.result_ref, operation=result.operation, observed_at=result.observed_at,
        context_version=result.context_version, simulation=True, body=result.body,
    )
    base = dict(
        context_version=1, intent_classification="business", verified_scope=scope,
        pending_slots=[], bound_references=model_refs,
        policy_evidence=[], available_permissions=permissions,
    )
    context_before_read = ModelContext(
        input_text=initial, recent_messages=[], read_results=[], query_observations=[], **base,
    )
    context_after_read = ModelContext(
        input_text=initial, recent_messages=[], read_results=[visible_result],
        query_observations=[query], **base,
    )
    context_after_resume = ModelContext(
        input_text=clarification,
        recent_messages=[v1.PriorMessage(role="user", text=initial)],
        read_results=[visible_result], query_observations=[query], **base,
    )
    decision_read = ReadDecision(kind="read", operation=v1.ReadOperation.EXPENSES, criteria=criteria)
    decision_clarify = v1.ClarifyDecision(
        kind="clarify", prompt="What amount and currency should I use?",
        missing_slots=[v1.ClarificationSlot.AMOUNT, v1.ClarificationSlot.CURRENCY],
    )
    proposal_fields = v1.ExpenseCreateIntent(
        kind="expense.create", ledger_unit_ref=v1.LedgerUnitRef.U01, title="Lunch",
        original_amount="50.00", original_currency="USD",
        payment_allocations=[v1.PaymentAllocation(participant_ref=v1.ParticipantRef.P01, amount="50.00")],
        split=v1.EqualSplitIntent(mode="equal", participant_refs=[v1.ParticipantRef.P01, v1.ParticipantRef.P02]),
    )
    proposal = v1.ProposeDecision(kind="propose", operation="expense.create", fields=proposal_fields)
    return T1TrajectoryV11(
        trajectory_version="1.1.0",
        versions=NegotiatedVersions(
            api_version="1.0.0", semantic_version="1.1.0", operations_version="1.1.0",
            trajectory_version="1.1.0", execution_key_version="1",
        ),
        scenario="synthetic-resume-preserves-original-fields",
        original_input_text=initial,
        recent_messages=[],
        initial_generation=1,
        synthetic_private_turn_id=turn_id,
        synthetic_private_bound_references=references,
        steps=[
            UserInputStep(kind="user_input", seq=0, text=initial),
            ModelDecisionStep(kind="model_decision", seq=1, context=context_before_read, decision=decision_read),
            ToolObservationStep(kind="tool_observation", seq=2, query=query, result=visible_result),
            ModelDecisionStep(kind="model_decision", seq=3, context=context_after_read, decision=decision_clarify),
            UserClarificationStep(
                kind="user_clarification", seq=4, text=clarification, responds_to_seq=3, generation=2,
            ),
            ModelDecisionStep(kind="model_decision", seq=5, context=context_after_resume, decision=proposal),
        ],
    )


def build_participant_filtered_read_trace():
    """Synthetic causal read with a private same-Turn participant sidecar."""
    from .trajectory import ModelDecisionStep, T1TrajectoryV11, ToolObservationStep, UserInputStep
    from .harness import render_query_answer

    example = make_synthetic_example(
        "expenses_postfilter_empty",
        title_contains="Cafe",
        titles=["Cafe 1", "Cafe 2"],
        participant_ref=v1.ParticipantRef.P01,
        fixture_key="participant-read-trace",
    )
    text = "Find Cafe expenses for Alice."
    before_payload = example.context.model_dump(mode="python")
    before_payload.update(input_text=text, read_results=[], query_observations=[])
    before = ModelContext.model_validate(before_payload)
    after_payload = example.context.model_dump(mode="python")
    after_payload.update(input_text=text)
    after = ModelContext.model_validate(after_payload)
    decision_read = ReadDecision(kind="read", operation=v1.ReadOperation.EXPENSES, criteria=example.binding.criteria)
    validated = example.validate()
    answer = render_query_answer(validated, expected_context=example.context)
    decision_answer = AnswerDecision(
        kind="answer", basis="grounded", text=answer.text, citations=answer.citations,
    )
    return T1TrajectoryV11(
        trajectory_version="1.1.0",
        versions=NegotiatedVersions(
            api_version="1.0.0", semantic_version="1.1.0", operations_version="1.1.0",
            trajectory_version="1.1.0", execution_key_version="1",
        ),
        scenario="synthetic-participant-filtered-read",
        original_input_text=text,
        recent_messages=[],
        initial_generation=1,
        synthetic_private_turn_id=example.turn_id,
        synthetic_private_bound_references=example.bound_references,
        steps=[
            UserInputStep(kind="user_input", seq=0, text=text),
            ModelDecisionStep(kind="model_decision", seq=1, context=before, decision=decision_read),
            ToolObservationStep(
                kind="tool_observation", seq=2,
                query=example.context.query_observations[0], result=example.context.read_results[0],
            ),
            ModelDecisionStep(kind="model_decision", seq=3, context=after, decision=decision_answer),
        ],
    )
