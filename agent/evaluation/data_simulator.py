"""Pure deterministic T1 read simulator over explicit synthetic fixture rows."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from pydantic import Field

from agent.app import contracts as c

SIMULATOR_VERSION = "t1-synthetic-read-1.0.0"
SIMULATOR_NAMESPACE = uuid.UUID("7ca4da9c-35f8-5bfb-a5be-9fe57efb04d7")


class FixtureActivity(c.ContractModel):
    activity_ref: c.ActivityRef
    name: c.TitleText
    activity_kind: c.ActivityKind
    base_currency: c.CurrencyCode
    status: c.ActivityStatus


class FixtureExpense(c.ContractModel):
    activity_ref: c.ActivityRef
    expense_ref: c.ExpenseRef
    title: c.TitleText
    original_amount: c.MoneyString
    original_currency: c.CurrencyCode
    occurred_at: c.WireDateTime
    participant_refs: list[c.ParticipantRef] = Field(min_length=1, max_length=32)
    financial_locked: bool
    expense_version: c.ExpenseVersion


class FixtureDebt(c.ContractModel):
    activity_ref: c.ActivityRef
    debtor_ref: c.ParticipantRef
    creditor_ref: c.ParticipantRef
    amount: c.MoneyString
    currency: c.CurrencyCode


class SyntheticFixture(c.ContractModel):
    activities: list[FixtureActivity] = Field(max_length=16)
    expenses: list[FixtureExpense] = Field(max_length=16)
    debts: list[FixtureDebt] = Field(max_length=16)


def _aware_datetime(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("simulator timestamp must be timezone-aware")
    return value


def _date(value: datetime) -> date:
    return value.date()


def simulate_read(
    fixture_state: dict[str, Any] | SyntheticFixture,
    request: dict[str, Any] | c.ReadDecision,
    *,
    observed_at: datetime | str,
    context_version: int,
    replay_key: str,
) -> c.ToolReadResult:
    """Recompute a simulation result from fixture facts and the exact read criteria."""
    fixture = fixture_state if isinstance(fixture_state, SyntheticFixture) else SyntheticFixture.model_validate(fixture_state)
    decision = request if isinstance(request, c.ReadDecision) else c.ReadDecision.model_validate(request)
    now = _aware_datetime(observed_at)
    if context_version < 1:
        raise ValueError("context_version must be positive")
    if not replay_key:
        raise ValueError("replay_key is required")
    result_id = uuid.uuid5(SIMULATOR_NAMESPACE, f"{replay_key}:{decision.operation.value}")
    evidence_no = 1

    if decision.operation == c.ReadOperation.ACTIVITIES:
        criteria = decision.criteria
        assert isinstance(criteria, c.ReadActivitiesCriteria)
        rows = [
            row for row in fixture.activities
            if criteria.status == "any" or row.status.value == criteria.status
        ]
        if criteria.name_contains:
            needle = criteria.name_contains.casefold()
            rows = [row for row in rows if needle in row.name.casefold()]
        facts = []
        for row in rows:
            facts.append(c.ActivityFact(
                kind="activity",
                evidence_ref=getattr(c.ActivityEvidenceRef, f"F{evidence_no:02d}"),
                activity_ref=row.activity_ref,
                name=row.name,
                activity_kind=row.activity_kind,
                base_currency=row.base_currency,
                status=row.status,
                observed_at=now,
                context_version=context_version,
            ))
            evidence_no += 1
        body: c.ReadResultBody = c.ActivityListResult(kind="activities", items=facts)
    elif decision.operation == c.ReadOperation.EXPENSES:
        criteria = decision.criteria
        assert isinstance(criteria, c.ReadExpensesCriteria)
        rows = [row for row in fixture.expenses if row.activity_ref == criteria.activity_ref]
        if criteria.from_date:
            rows = [row for row in rows if _date(row.occurred_at) >= criteria.from_date]
        if criteria.to_date:
            rows = [row for row in rows if _date(row.occurred_at) <= criteria.to_date]
        if criteria.participant_ref:
            rows = [row for row in rows if criteria.participant_ref in row.participant_refs]
        facts = []
        for row in rows:
            facts.append(c.ExpenseFact(
                kind="expense",
                evidence_ref=getattr(c.ExpenseEvidenceRef, f"F{evidence_no:02d}"),
                expense_ref=row.expense_ref,
                title=row.title,
                original_amount=row.original_amount,
                original_currency=row.original_currency,
                occurred_at=row.occurred_at,
                participant_refs=row.participant_refs,
                financial_locked=row.financial_locked,
                expense_version=row.expense_version,
                observed_at=now,
                context_version=context_version,
            ))
            evidence_no += 1
        body = c.ExpenseListResult(kind="expenses", items=facts)
    else:
        criteria = decision.criteria
        assert isinstance(criteria, c.ReadDebtsCriteria)
        rows = [row for row in fixture.debts if row.activity_ref == criteria.activity_ref]
        if criteria.participant_ref:
            rows = [row for row in rows if criteria.participant_ref in (row.debtor_ref, row.creditor_ref)]
        if criteria.currency:
            rows = [row for row in rows if row.currency == criteria.currency]
        facts = []
        for row in rows:
            facts.append(c.DebtFact(
                kind="debt",
                evidence_ref=getattr(c.DebtEvidenceRef, f"F{evidence_no:02d}"),
                debtor_ref=row.debtor_ref,
                creditor_ref=row.creditor_ref,
                amount=row.amount,
                currency=row.currency,
                observed_at=now,
                context_version=context_version,
            ))
            evidence_no += 1
        body = c.DebtListResult(kind="debts", items=facts)

    return c.ToolReadResult(
        result_id=result_id,
        result_ref=c.ReadResultRef.R01,
        operation=decision.operation,
        observed_at=now,
        context_version=context_version,
        simulation=True,
        body=body,
    )

