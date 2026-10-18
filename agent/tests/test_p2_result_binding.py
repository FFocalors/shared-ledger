from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app import contracts as c
from app.p2_backend import (
    P2ActivityDTO,
    P2BackendReadResult,
    P2DebtDTO,
    P2ExpenseDTO,
    P2PaymentDTO,
    P2ResolvedScope,
    P2SplitDTO,
)
from app.p2_harness import P2ReferenceLabel
from app.p2_runtime import P2Runtime, _P2TerminalFailure, _TurnP2State
from app.store import TurnAggregate, TurnCheckpoint


OWNER_ID = uuid.UUID("10000000-0000-4000-8000-000000000001")
TURN_ID = uuid.UUID("80000000-0000-4000-8000-000000000001")
SESSION_ID = uuid.UUID("90000000-0000-4000-8000-000000000001")
ACTIVITY_ID = uuid.UUID("20000000-0000-4000-8000-000000000001")
UNIT_ID = uuid.UUID("30000000-0000-4000-8000-000000000001")
P1_ID = uuid.UUID("40000000-0000-4000-8000-000000000001")
P2_ID = uuid.UUID("40000000-0000-4000-8000-000000000002")
P3_ID = uuid.UUID("40000000-0000-4000-8000-000000000003")
EXPENSE_ID = uuid.UUID("50000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 10, 11, 3, 0, tzinfo=timezone.utc)


def activity(*, activity_id: uuid.UUID = ACTIVITY_ID, version: int = 7, base_currency: str = "USD") -> P2ActivityDTO:
    return P2ActivityDTO(
        activity_id=activity_id, name="Trip", activity_type="normal",
        base_currency=base_currency, multi_currency_enabled=True,
        is_deleted=False, archived_at=None, financial_version=version,
    )


def make_aggregate(*, turn_id: uuid.UUID = TURN_ID) -> TurnAggregate:
    turn = c.TurnStateSnapshot(
        turn_id=turn_id, session_id=SESSION_ID, owner_user_id=OWNER_ID,
        state=c.TurnState.RUNNING, step=c.TurnStep.TOOL_READ,
        state_revision=1, context_version=1,
    )
    record = c.TurnRecord(
        turn=turn, client_request_id=uuid.uuid4(), request_payload_hash="a" * 64,
        original_text="查询可信记录", ui_context_snapshot=None,
        bound_references=[
            c.BoundActivityReference(
                kind="activity", ref=c.ActivityRef.A01, entity_id=ACTIVITY_ID,
                source_turn_id=turn_id, scope_activity_id=ACTIVITY_ID,
            ),
        ],
        bound_evidence_references=[], bound_read_results=[], request_receipts=[],
    )
    checkpoint = TurnCheckpoint(
        accepted_inputs=[], model_context=None, last_decision=None,
        last_clarification=None, resume_step=None, read_results=[],
        persisted_policy_evidence=[], generation=1,
    )
    return TurnAggregate(
        record=record, checkpoint=checkpoint, queue_order=1,
        checkpoint_revision=1, claim_token="claim-test", claim_until=None,
    )


def state(*, scope_activity: P2ActivityDTO | None = None, activity_id: uuid.UUID = ACTIVITY_ID) -> _TurnP2State:
    labels = {
        ref: P2ReferenceLabel(kind="participant", ref=ref, display_name=f"participant-{ref.value}")
        for ref in c.ParticipantRef
        if ref.value in {"participant_1", "participant_2", "participant_3", "participant_4"}
    }
    return _TurnP2State(
        resolved_scope=P2ResolvedScope(
            mode="activity", activity=scope_activity or activity(activity_id=activity_id),
            participants=(), ledger_units=(), child_scopes=(), observed_at=NOW,
        ),
        scope_activity_id=activity_id,
        scope_fingerprint="f" * 64,
        labels=labels,
    )


def decision(operation: c.ReadOperation) -> c.ReadDecision:
    criterion_kind = "debts" if operation == c.ReadOperation.DEBTS else "expenses"
    operation_value = "read.debts" if operation == c.ReadOperation.DEBTS else "read.expenses"
    return c.ReadDecision.model_validate({
        "kind": "read", "operation": operation_value,
        "criteria": {"kind": criterion_kind, "activity_ref": "activity_1"},
    })


def expense(
    *,
    expense_id: uuid.UUID = EXPENSE_ID,
    activity_id: uuid.UUID = ACTIVITY_ID,
    amount: str = "10.00",
    currency: str = "EUR",
    payment_participant: uuid.UUID = P1_ID,
    split_participant: uuid.UUID = P2_ID,
) -> P2ExpenseDTO:
    return P2ExpenseDTO(
        expense_id=expense_id, activity_id=activity_id, ledger_unit_id=UNIT_ID,
        title="Dinner", original_amount=Decimal(amount), original_currency=currency,
        fx_rate=Decimal("1.25"), base_amount=Decimal("12.50"),
        occurred_at=NOW, original_expense_id=None, expense_version=2,
        is_deleted=False, financial_locked=False,
        payments=(P2PaymentDTO(
            payment_id=uuid.uuid4(), expense_id=expense_id,
            participant_id=payment_participant, amount=Decimal("6.00"),
            base_amount=Decimal("7.50"),
        ),),
        splits=(P2SplitDTO(
            split_id=uuid.uuid4(), expense_id=expense_id,
            participant_id=split_participant, amount=Decimal("4.00"),
            base_amount=Decimal("5.00"),
        ),),
    )


def raw_expenses(
    items: tuple[P2ExpenseDTO, ...], *, activity_id: uuid.UUID = ACTIVITY_ID,
    version: int = 7,
) -> P2BackendReadResult:
    return P2BackendReadResult(
        operation=c.ReadOperation.EXPENSES, observed_at=NOW,
        source="supabase_postgrest", expenses=items,
        financial_versions={activity_id: version}, complete=True,
    )


def bind(
    raw: P2BackendReadResult,
    *, aggregate: TurnAggregate | None = None,
    turn_state: _TurnP2State | None = None,
) -> tuple[object, ...]:
    current_aggregate = aggregate or make_aggregate()
    current_state = turn_state or state()
    # The mapper and provenance builder are pure with respect to runtime services.
    return P2Runtime._bind_p2_read_result(
        object.__new__(P2Runtime), current_aggregate, raw,
        decision(raw.operation), current_state,
    )


def test_debt_rows_with_shared_debtor_have_distinct_evidence() -> None:
    raw = P2BackendReadResult(
        operation=c.ReadOperation.DEBTS, observed_at=NOW,
        source="supabase_postgrest", financial_versions={ACTIVITY_ID: 7},
        debts=(
            P2DebtDTO(P1_ID, P2_ID, "USD", Decimal("2"), Decimal("2"), Decimal("2"), 7),
            P2DebtDTO(P1_ID, P3_ID, "USD", Decimal("3"), Decimal("3"), Decimal("3"), 7),
            P2DebtDTO(P1_ID, P2_ID, "EUR", Decimal("4"), Decimal("5"), Decimal("5"), 7),
        ),
    )

    result, references, evidence, _, _, _ = bind(raw)

    facts = result.body.items
    assert len(facts) == 3
    assert len({fact.evidence_ref for fact in facts}) == 3
    assert len({item.entity_id for item in evidence}) == 3
    assert all(fact.debtor_ref == c.ParticipantRef.P01 for fact in facts)
    assert [fact.creditor_ref for fact in facts] == [c.ParticipantRef.P02, c.ParticipantRef.P03, c.ParticipantRef.P02]
    row_ids = {item.entity_id for item in evidence}
    assert row_ids == {
        P2Runtime._debt_evidence_entity_id(TURN_ID, ACTIVITY_ID, item) for item in raw.debts
    }
    assert len({(item.kind, item.entity_id) for item in references}) == len(references)


def test_negative_refund_is_rejected_without_absolute_value_or_fact_mapping() -> None:
    raw = raw_expenses((expense(amount="-10.00"),))

    with pytest.raises(_P2TerminalFailure, match="refund or non-positive"):
        bind(raw)


def test_payment_and_split_lines_preserve_role_original_and_base_amounts() -> None:
    raw = raw_expenses((expense(),))

    result, _, _, _, supplements, _ = bind(raw)

    assert result.body.items[0].original_amount == "10.00"
    supplement = supplements[0]
    payer = supplement.payments[0]
    split = supplement.splits[0]
    assert (payer.role, payer.amount, payer.currency, payer.base_amount, payer.base_currency) == (
        "payer", "6.00", "EUR", "7.50", "USD",
    )
    assert (split.role, split.amount, split.currency, split.base_amount, split.base_currency) == (
        "split_participant", "4.00", "EUR", "5.00", "USD",
    )


def test_same_uuid_in_activity_and_participant_kinds_uses_distinct_typed_refs() -> None:
    shared_id = ACTIVITY_ID
    aggregate = make_aggregate()
    # Rebind the existing activity to the test's same UUID used by a payer.
    raw = raw_expenses((expense(
        activity_id=shared_id, payment_participant=shared_id,
    ),))
    turn_state = state(activity_id=shared_id)

    result, references, _, _, supplements, _ = bind(raw, aggregate=aggregate, turn_state=turn_state)

    activity_binding = next(item for item in references if item.kind == "activity")
    participant_binding = next(
        item for item in references if item.kind == "participant" and item.entity_id == shared_id
    )
    assert activity_binding.entity_id == participant_binding.entity_id == shared_id
    assert activity_binding.ref == c.ActivityRef.A01
    assert participant_binding.ref == c.ParticipantRef.P01
    assert result.body.items[0].participant_refs == [c.ParticipantRef.P01, c.ParticipantRef.P02]
    assert supplements[0].payments[0].participant_ref == c.ParticipantRef.P01


def test_financial_version_zero_is_valid_and_scope_version_drift_fails_closed() -> None:
    zero_scope = state(scope_activity=activity(version=0))
    zero_raw = P2BackendReadResult(
        operation=c.ReadOperation.DEBTS, observed_at=NOW,
        source="supabase_postgrest", financial_versions={ACTIVITY_ID: 0}, debts=(),
    )
    result, _, _, _, supplements, provenance = bind(zero_raw, turn_state=zero_scope)
    assert result.body.items == []
    assert supplements == []
    assert provenance.financial_versions[0].financial_version == 0

    drifted_debt = P2BackendReadResult(
        operation=c.ReadOperation.DEBTS, observed_at=NOW,
        source="supabase_postgrest", financial_versions={ACTIVITY_ID: 8},
        debts=(P2DebtDTO(P1_ID, P2_ID, "USD", Decimal("1"), Decimal("1"), Decimal("1"), 8),),
    )
    with pytest.raises(_P2TerminalFailure, match="activity changed during scope resolution"):
        bind(drifted_debt, turn_state=state(scope_activity=activity(version=7)))


def test_base_currency_is_taken_from_verified_scope_and_not_model_or_expense_currency() -> None:
    turn_state = state(scope_activity=activity(version=7, base_currency="CAD"))
    raw = raw_expenses((expense(currency="EUR"),))

    _, _, _, _, supplements, provenance = bind(raw, turn_state=turn_state)

    assert supplements[0].original_currency == "EUR"
    assert supplements[0].base_currency == "CAD"
    assert supplements[0].payments[0].base_currency == "CAD"
    assert provenance.financial_versions[0].base_currency == "CAD"
