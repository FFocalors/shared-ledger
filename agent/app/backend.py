"""P1-05 adapters. Mock facts are deterministic and always explicitly simulated."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from . import contracts as c
from . import mock_fixtures
from .ports import CapabilityUnavailable, ComponentHealth, Principal


class UnimplementedBackendAdapter:
    """Closed production adapter until a separately reviewed live-read phase."""

    def start(self) -> None:
        pass

    def health(self) -> ComponentHealth:
        return ComponentHealth(status="not_implemented", available=False)

    async def read(self, owner_user_id: uuid.UUID, turn_id: uuid.UUID, context: Any, decision: Any) -> Any:
        raise CapabilityUnavailable("live business reads are not installed")

    def close(self) -> None:
        pass


class MockBackendAdapter:
    """A fixed fixture source; it never contacts Supabase or writes business state."""

    _RESULT_BY_OPERATION = {
        c.ReadOperation.ACTIVITIES: 0,
        c.ReadOperation.EXPENSES: 1,
        c.ReadOperation.DEBTS: 2,
    }

    def start(self) -> None:
        pass

    def health(self) -> ComponentHealth:
        return ComponentHealth(status="simulation", available=True)

    async def read(self, owner_user_id: uuid.UUID, turn_id: uuid.UUID, context: c.ModelContext,
                   decision: c.ReadDecision) -> c.ToolReadResult:
        if decision.operation not in self._RESULT_BY_OPERATION:
            raise CapabilityUnavailable("read operation is outside the frozen simulation allowlist")
        bound = mock_fixtures.references(turn_id)
        fixture = mock_fixtures.tool_results(bound)[self._RESULT_BY_OPERATION[decision.operation]]
        now = datetime.now(timezone.utc)
        body = fixture.body
        items = []
        for fact in body.items:
            updates: dict[str, Any] = {"observed_at": now, "context_version": context.context_version}
            if isinstance(fact, c.ExpenseFact):
                # The source produces the data, while the Harness allocates stable evidence refs.
                updates["financial_locked"] = False
            items.append(fact.model_copy(update=updates))
        body = body.model_copy(update={"items": items})
        result_id = uuid.uuid5(uuid.NAMESPACE_URL, f"mock-read:{owner_user_id}:{turn_id}:{decision.operation}:{now.isoformat()}")
        return c.ToolReadResult(
            result_id=result_id,
            result_ref=c.ReadResultRef.R01,
            operation=decision.operation,
            observed_at=now,
            context_version=context.context_version,
            simulation=True,
            body=body,
        )

    def close(self) -> None:
        pass


class MockScopeAuthorizer:
    """Accept only the one server-defined demonstration Activity identity."""

    def authorize(self, principal: Principal, activity_ids: frozenset[uuid.UUID], *, action: str) -> None:
        if not activity_ids:
            return
        if activity_ids != frozenset({mock_fixtures.ACTIVITY_ID}):
            from .ports import ScopeDenied
            raise ScopeDenied("scope is outside the deterministic mock fixture")


def build_simulation_proposal(
    owner_user_id: uuid.UUID,
    session_id: uuid.UUID,
    turn_id: uuid.UUID,
    intent: c.WriteIntent,
    policy_version: str,
    *,
    proposal_id: uuid.UUID | None = None,
    revision: int = 1,
    expires_at: datetime | None = None,
) -> c.ProposalRecord:
    """Build a preview-only proposal using the frozen, visibly simulated fixture."""
    now = datetime.now(timezone.utc)
    preview = _simulation_preview(intent, now)
    return c.ProposalRecord(
        proposal_id=proposal_id or uuid.uuid4(),
        owner_user_id=owner_user_id,
        session_id=session_id,
        turn_id=turn_id,
        revision=revision,
        operation=intent.kind,
        mode="simulation",
        status=c.ProposalStatus.PENDING,
        intent=intent,
        canonical_command=None,
        preview=preview,
        preconditions=None,
        command_digest=None,
        confirmation_nonce=None,
        policy_version=policy_version,
        expires_at=expires_at or now.replace(microsecond=0) + timedelta(minutes=10),
        execution=None,
        request_receipts=[],
    )


def _simulation_preview(intent: c.WriteIntent, now: datetime) -> c.ExpensePreview:
    """Create a typed preview from the exact simulated intent parameters."""
    refs = mock_fixtures.references()
    by_ref = {item.ref: item.entity_id for item in refs}
    before = None if isinstance(intent, c.ExpenseCreateIntent) else mock_fixtures._expense_snapshot()
    if before is None:
        assert isinstance(intent, c.ExpenseCreateIntent)
        amount = intent.original_amount
        payments = [c.CanonicalPayment(participant_id=by_ref[item.participant_ref], amount=item.amount)
                    for item in intent.payment_allocations]
        if isinstance(intent.split, c.EqualSplitIntent):
            split: c.CanonicalSplit = c.CanonicalEqualSplit(
                mode="equal", participant_ids=[by_ref[item] for item in intent.split.participant_refs]
            )
        else:
            split = c.CanonicalManualSplit(
                mode="manual", allocations=[c.CanonicalPayment(
                    participant_id=by_ref[item.participant_ref], amount=item.amount
                ) for item in intent.split.allocations]
            )
        after = c.ExpenseSnapshot(
            ledger_unit_id=by_ref[intent.ledger_unit_ref], title=intent.title,
            original_amount=amount, original_currency=intent.original_currency,
            base_amount=amount, payment_allocations=payments, split=split,
            occurred_at=intent.occurred_at, note=intent.note, expense_version="1", financial_locked=False,
        )
        summary = f"模拟新增消费 {intent.title} {amount} {intent.original_currency}"
    else:
        if before.financial_locked and isinstance(intent, c.ExpenseUpdateIntent):
            raise CapabilityUnavailable("the simulated Expense is financially locked")
        updates: dict[str, Any] = {}
        if isinstance(intent, c.ExpenseUpdateIntent):
            for key in ("title", "original_amount", "original_currency", "note", "occurred_at"):
                value = getattr(intent, key)
                if value is not None:
                    updates[key] = value
            if intent.original_amount is not None:
                updates["base_amount"] = intent.original_amount
            if intent.payment_allocations is not None:
                updates["payment_allocations"] = [c.CanonicalPayment(
                    participant_id=by_ref[item.participant_ref], amount=item.amount
                ) for item in intent.payment_allocations]
            if intent.split is not None:
                if isinstance(intent.split, c.EqualSplitIntent):
                    updates["split"] = c.CanonicalEqualSplit(
                        mode="equal", participant_ids=[by_ref[item] for item in intent.split.participant_refs]
                    )
                else:
                    updates["split"] = c.CanonicalManualSplit(
                        mode="manual", allocations=[c.CanonicalPayment(
                            participant_id=by_ref[item.participant_ref], amount=item.amount
                        ) for item in intent.split.allocations]
                    )
            summary = f"模拟修改消费 {intent.original_amount or before.original_amount} {intent.original_currency or before.original_currency}"
        else:
            for key in ("title", "note", "icon_key"):
                value = getattr(intent, key)
                if value is not None:
                    updates[key] = value
            summary = "模拟修改消费显示信息"
        updates["expense_version"] = str(int(before.expense_version) + 1)
        # The fixture is already a validated typed snapshot. model_copy keeps
        # nested CanonicalPayment/Split instances typed instead of routing them
        # through frozen JSON-wire validation as arbitrary Python objects.
        after = before.model_copy(update=updates)

    changes: list[c.ExpenseFieldChange] = []
    change_types = {
        "title": c.ExpenseTitleChange,
        "original_amount": c.ExpenseAmountChange,
        "base_amount": c.ExpenseAmountChange,
        "original_currency": c.ExpenseCurrencyChange,
        "ledger_unit_id": c.ExpenseLedgerUnitChange,
        "payment_allocations": c.ExpensePaymentsChange,
        "split": c.ExpenseSplitChange,
        "occurred_at": c.ExpenseOccurredAtChange,
        "note": c.ExpenseNoteChange,
        "icon_key": c.ExpenseIconChange,
        "fx_snapshot": c.ExpenseFxChange,
    }
    tracked = tuple(change_types)
    for field in tracked:
        after_value = getattr(after, field)
        before_value = getattr(before, field) if before is not None else None
        changed = before is None and after_value is not None or before is not None and before_value != after_value
        if changed:
            changes.append(change_types[field](field=field, before=before_value, after=after_value))
    return c.ExpensePreview(
        kind="expense", summary=summary, before=before, after=after, changes=changes,
        activity_financial_version="0", generated_at=now, simulation=True,
    )
