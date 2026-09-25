"""Formal per-focus scenario shape contracts for the generated-case pipeline.

The Loader answers "is this a valid Scenario v1 document?".  It cannot answer
"does this scenario actually exercise the business behaviour its focus claims
to cover?".  This module owns that second question.

A focus contract is a predicate over a parsed :class:`~.models.Scenario`.  It
is deliberately expressed in terms of the scenario's *business shape* --
participants, payers, split method, operation order, operation kinds, and
exact Decimal arithmetic -- never in terms of wording.  Every contract is
decidable from the scenario alone, with no database access and no emulation of
server-side projection rules.

A scenario that passes the Loader but fails its focus contract is a
``FOCUS_MISMATCH``: a legal document that would be counted as coverage if the
contract were not enforced.  ``FOCUS_MISMATCH`` cases are still executed and
judged (they exercise real business logic) but they are excluded from every
coverage denominator.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Callable

from .models import (
    ArchiveActivity,
    CreateExpense,
    CreatePrepayment,
    CreateSubActivity,
    FifoRepayment,
    FinalSettlement,
    LinkedRefund,
    PreviewFinalSettlement,
    ReturnPrepayment,
    Scenario,
    TargetedRepayment,
    UnarchiveActivity,
    VoidTransfer,
)

# Focus tiers.  "smoke" focuses keep the historical three-focus E2E smoke
# contract; "coverage" focuses are the formal business-verification set.
SMOKE_TIER = "smoke"
COVERAGE_TIER = "coverage"

# Participant refs are supplied by the ScenarioPlan so the local model never has
# to invent names (invented names such as "Alice (Owner)" fail the Loader's ref
# pattern).  Six is the largest participant_count the plan space uses.
PARTICIPANT_NAMES: tuple[str, ...] = ("alice", "bob", "carol", "dave", "erin", "frank")

AMOUNT_PATTERNS = ("divisible", "non_divisible", "decimal", "large", "small")
EDGE_TAGS = (
    "rounding_residual",
    "partial_repayment",
    "multiple_creditors",
    "remaining_prepayment",
    "full_settlement",
    "fx_conversion",
    "cross_currency_settlement",
    "multi_hop_path",
    "plan_invalidated",
    "sub_activity_split",
    "refund_cap_boundary",
    "cumulative_refund",
    "cancel_archive",
)


class FocusDefinitionError(ValueError):
    """The requested focus is not part of the registry."""


@dataclass(frozen=True)
class FocusSpec:
    """Everything the pipeline needs to aim a generated case at one focus."""

    name: str
    tier: str
    title: str
    sections: tuple[int, ...]
    participants: tuple[int, int]
    payers: tuple[int, ...]
    amount_patterns: tuple[str, ...]
    operation_counts: tuple[int, ...]
    edge_tags: tuple[str, ...]
    goal: str
    contract: Callable[[Scenario], str | None]
    # Activity preconditions.  Most focuses run on a normal CNY-only activity;
    # multi_currency and large_activity need a different envelope.
    activity_types: tuple[str, ...] = ("normal",)
    base_currency: str = "CNY"
    multi_currency: bool = False
    # Base currency of the amounts the plan writes; differs for FX focuses.
    plan_currency: str = "CNY"
    # Fractional digits the plan's amounts use (4 is the loader limit for foreign amounts).
    plan_amount_scale: int = 1

    @property
    def is_smoke(self) -> bool:
        return self.tier == SMOKE_TIER


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------


def _expenses(scenario: Scenario) -> list[CreateExpense | LinkedRefund]:
    return [op for op in scenario.operations if isinstance(op, (CreateExpense, LinkedRefund))]


def _positive_payers(expense: CreateExpense | LinkedRefund) -> dict[str, Decimal]:
    return {name: amount for name, amount in expense.payments.items() if amount > 0}


def _net(expense: CreateExpense | LinkedRefund, participant: str) -> Decimal:
    """Original-currency net (split minus payment) for manual splits only.

    Returns ``None``-free arithmetic because AA expenses have no stored splits;
    callers must guard with ``expense.split_method == "manual"``.
    """
    splits = expense.splits or {}
    return splits.get(participant, Decimal(0)) - expense.payments.get(participant, Decimal(0))


def _aa_residual_exists(amount: Decimal, count: int) -> bool:
    """True when an equal 4-decimal split of ``amount`` over ``count`` cannot be exact."""
    if count <= 0:
        return False
    scaled = (abs(amount) * Decimal(10_000)).to_integral_value()
    return int(scaled) % count != 0


def _common(scenario: Scenario, spec: FocusSpec) -> str | None:
    if scenario.activity.type not in spec.activity_types:
        return f"expected activity type in {list(spec.activity_types)}"
    if scenario.activity.base_currency != spec.base_currency:
        return f"expected base currency {spec.base_currency}"
    if scenario.activity.multi_currency_enabled != spec.multi_currency:
        return f"expected multi_currency_enabled {spec.multi_currency}"
    low, high = spec.participants
    count = len(scenario.participants)
    if not low <= count <= high:
        return f"expected {low}-{high} participants, found {count}"
    return None


def _require(condition: bool, reason: str) -> str | None:
    return None if condition else reason


# --------------------------------------------------------------------------
# Contracts
# --------------------------------------------------------------------------


def _contract_expense_aa(scenario: Scenario, spec: FocusSpec) -> str | None:
    """Historical smoke contract: three participants, one all-participant AA expense."""
    if len(scenario.participants) != 3:
        return "expected 3 participants and one expense"
    if len(scenario.operations) != 1 or not isinstance(scenario.operations[0], CreateExpense):
        return "expected 3 participants and one expense"
    expense = scenario.operations[0]
    if (
        expense.split_method != "aa"
        or set(expense.aa_participants) != set(scenario.participants)
        or len(expense.payments) not in {2, 3}
        or any(amount <= 0 for amount in expense.payments.values())
    ):
        return "expected all-participant AA and 2-3 positive payers"
    return None


def _contract_targeted_repayment(scenario: Scenario, spec: FocusSpec) -> str | None:
    """Expense followed by a strictly partial repayment against that expense."""
    operations = scenario.operations
    if (
        len(operations) != 2
        or not isinstance(operations[0], CreateExpense)
        or not isinstance(operations[1], TargetedRepayment)
    ):
        return "expected expense followed by targeted repayment"
    expense, repayment = operations
    if repayment.target_expense_refs != (expense.ref,):
        return "repayment must reference the prior expense"
    if expense.split_method != "manual":
        return "expected a manual split so the repayable debt is determined"
    debtor_due = _net(expense, repayment.from_participant)
    creditor_due = -_net(expense, repayment.to_participant)
    if debtor_due <= 0 or creditor_due <= 0:
        return "repayment direction does not match the debt created by the expense"
    if not 0 < repayment.amount < min(debtor_due, creditor_due):
        return "repayment must be strictly partial against the selected debt"
    return None


def _contract_prepayment_refund(scenario: Scenario, spec: FocusSpec) -> str | None:
    """Historical smoke contract: prepayment, expense, linked refund, in order."""
    operations = scenario.operations
    if (
        len(operations) != 3
        or not isinstance(operations[0], CreatePrepayment)
        or not isinstance(operations[1], CreateExpense)
        or not isinstance(operations[2], LinkedRefund)
    ):
        return "expected prepayment, expense, linked refund in order"
    expense, refund = operations[1:]
    if refund.original_expense_ref != expense.ref or -refund.amount > expense.amount:
        return "refund must reference the preceding expense and stay within its amount"
    return None


def _contract_single_payer_aa(scenario: Scenario, spec: FocusSpec) -> str | None:
    """One payer, equal AA split across everyone: the AA baseline path."""
    if len(scenario.operations) != 1 or not isinstance(scenario.operations[0], CreateExpense):
        return "expected exactly one create_expense"
    expense = scenario.operations[0]
    if expense.split_method != "aa" or set(expense.aa_participants) != set(scenario.participants):
        return "expected all-participant AA"
    payers = _positive_payers(expense)
    if len(payers) != 1:
        return f"expected exactly 1 positive payer, found {len(payers)}"
    if next(iter(payers.values())) != expense.amount:
        return "the single payer must pay the whole expense amount"
    return None


def _contract_multi_payer_aa(scenario: Scenario, spec: FocusSpec) -> str | None:
    """Several payers plus at least one pure debtor: a real multi-payer topology."""
    expenses = [op for op in _expenses(scenario) if isinstance(op, CreateExpense) and op.amount > 0]
    if not expenses:
        return "expected at least one positive expense"
    expense = expenses[0]
    if expense.split_method != "aa" or set(expense.aa_participants) != set(scenario.participants):
        return "expected all-participant AA on the first expense"
    payers = _positive_payers(expense)
    if not 2 <= len(payers) <= 3:
        return f"expected 2-3 positive payers, found {len(payers)}"
    if any(amount >= expense.amount for amount in payers.values()):
        return "each payer must pay strictly less than the whole amount"
    if len(payers) >= len(scenario.participants):
        return "expected at least one participant who only owes, so debts fan out"
    return None


def _contract_aa_rounding(scenario: Scenario, spec: FocusSpec) -> str | None:
    """AA where an exact equal split is impossible, so the remainder is allocated."""
    expenses = [op for op in _expenses(scenario) if isinstance(op, CreateExpense) and op.amount > 0]
    if not expenses:
        return "expected at least one positive expense"
    expense = expenses[0]
    if expense.split_method != "aa" or set(expense.aa_participants) != set(scenario.participants):
        return "expected all-participant AA"
    count = len(expense.aa_participants)
    if not _aa_residual_exists(expense.amount, count):
        return (
            f"amount {expense.amount} divides exactly by {count}; "
            "expected an amount that leaves an AA rounding remainder"
        )
    return None


def _contract_manual_split(scenario: Scenario, spec: FocusSpec) -> str | None:
    """A caller-supplied split with at least two distinct bearers."""
    manual = [
        op
        for op in _expenses(scenario)
        if isinstance(op, CreateExpense) and op.split_method == "manual" and op.splits
    ]
    if not manual:
        return "expected at least one create_expense with split_method manual"
    splits = manual[0].splits
    if len(splits) < 2:
        return "expected at least two distinct split bearers"
    if len(set(splits.values())) < 2:
        return "expected the manual splits to differ between participants"
    return None


def _contract_fifo_repayment(scenario: Scenario, spec: FocusSpec) -> str | None:
    operations = scenario.operations
    if len(operations) != 2 or not isinstance(operations[0], CreateExpense):
        return "expected an expense followed by one fifo repayment"
    if not isinstance(operations[1], FifoRepayment):
        return "expected the repayment to use fifo mode"
    expense, repayment = operations
    if expense.split_method != "manual":
        return "expected a manual split so the repayable debt is determined"
    debtor_due = _net(expense, repayment.from_participant)
    creditor_due = -_net(expense, repayment.to_participant)
    if debtor_due <= 0 or creditor_due <= 0:
        return "repayment direction does not match the debt created by the expense"
    if not 0 < repayment.amount <= min(debtor_due, creditor_due):
        return "fifo repayment must be positive and within the outstanding debt"
    return None


def _contract_multiple_repayments(scenario: Scenario, spec: FocusSpec) -> str | None:
    operations = scenario.operations
    repayments = [op for op in operations if isinstance(op, (FifoRepayment, TargetedRepayment))]
    if not isinstance(operations[0], CreateExpense):
        return "expected the first operation to be an expense"
    if len(repayments) < 2:
        return f"expected at least 2 repayments, found {len(repayments)}"
    expense = operations[0]
    if expense.split_method != "manual":
        return "expected a manual split so the repayable debt is determined"
    owed = sum(
        (value for value in (_net(expense, name) for name in set(expense.splits) | set(expense.payments)) if value > 0),
        Decimal(0),
    )
    for repayment in repayments:
        if _net(expense, repayment.from_participant) <= 0 or -_net(expense, repayment.to_participant) <= 0:
            return "a repayment direction does not match the debt created by the expense"
    total = sum((op.amount for op in repayments), Decimal(0))
    if total <= 0 or total > owed:
        return f"repayments total {total} must be positive and within the {owed} debt"
    return None


def _prepayment_pairs(scenario: Scenario) -> list[tuple[str, str, Decimal]]:
    return [
        (op.owner_participant, op.custodian_participant, op.amount)
        for op in scenario.operations
        if isinstance(op, CreatePrepayment)
    ]


def _contract_prepayment_before_debt(scenario: Scenario, spec: FocusSpec) -> str | None:
    """Prepayment first, then an expense that makes the owner owe the custodian."""
    operations = scenario.operations
    if not isinstance(operations[0], CreatePrepayment):
        return "expected the prepayment to come first"
    if len(operations) < 2 or not isinstance(operations[1], CreateExpense):
        return "expected an expense after the prepayment"
    prepayment, expense = operations[0], operations[1]
    if expense.split_method != "manual":
        return "expected a manual split so the owner-to-custodian debt is determined"
    if _net(expense, prepayment.owner_participant) <= 0:
        return "the prepayment owner must end up owing on the later expense"
    if -_net(expense, prepayment.custodian_participant) <= 0:
        return "the prepayment custodian must end up being owed on the later expense"
    return None


def _contract_prepayment_after_debt(scenario: Scenario, spec: FocusSpec) -> str | None:
    """An expense first creates owner-to-custodian debt, then the prepayment settles it."""
    operations = scenario.operations
    if not isinstance(operations[0], CreateExpense):
        return "expected the expense to come first"
    if len(operations) < 2 or not isinstance(operations[1], CreatePrepayment):
        return "expected a prepayment after the expense"
    expense, prepayment = operations[0], operations[1]
    if expense.split_method != "manual":
        return "expected a manual split so the owner-to-custodian debt is determined"
    if _net(expense, prepayment.owner_participant) <= 0:
        return "the prepayment owner must already owe on the preceding expense"
    if -_net(expense, prepayment.custodian_participant) <= 0:
        return "the prepayment custodian must already be owed on the preceding expense"
    return None


def _contract_prepayment_return(scenario: Scenario, spec: FocusSpec) -> str | None:
    payments = _prepayment_pairs(scenario)
    returns = [
        op for op in scenario.operations if isinstance(op, ReturnPrepayment)
    ]
    if not payments:
        return "expected at least one create_prepayment"
    if not returns:
        return "expected at least one return_prepayment"
    by_pair: dict[tuple[str, str], Decimal] = {}
    for owner, custodian, amount in payments:
        by_pair[(owner, custodian)] = by_pair.get((owner, custodian), Decimal(0)) + amount
    returned: dict[tuple[str, str], Decimal] = {}
    for op in returns:
        key = (op.owner_participant, op.custodian_participant)
        if key not in by_pair:
            return "a return must match an earlier prepayment owner and custodian"
        returned[key] = returned.get(key, Decimal(0)) + op.amount
    for key, amount in returned.items():
        if amount > by_pair[key]:
            return "a return must not exceed the prepayment it draws on"
    return None


def _contract_linked_refund(scenario: Scenario, spec: FocusSpec) -> str | None:
    refunds = [op for op in scenario.operations if isinstance(op, LinkedRefund)]
    if not refunds:
        return "expected at least one linked_refund"
    refund = refunds[0]
    source = next(
        (
            op
            for op in scenario.operations
            if isinstance(op, CreateExpense) and op.ref == refund.original_expense_ref
        ),
        None,
    )
    if source is None or source.amount <= 0:
        return "a linked refund must reference an earlier positive expense"
    if -refund.amount > source.amount:
        return "a linked refund must stay within its source expense amount"
    payers = set(refund.payments)
    bearers = set(refund.splits or refund.aa_participants)
    if payers == bearers:
        return (
            "refund receiver and beneficiary must differ, otherwise the refund "
            "nets to zero and exercises no section 13 debt direction"
        )
    return None


def _contract_negative_expense(scenario: Scenario, spec: FocusSpec) -> str | None:
    if any(isinstance(op, LinkedRefund) for op in scenario.operations):
        return "a standalone negative expense must not be a linked refund"
    negatives = [
        op for op in scenario.operations if isinstance(op, CreateExpense) and op.amount < 0
    ]
    if not negatives:
        return "expected at least one unlinked negative expense"
    return None


def _contract_void_transfer(scenario: Scenario, spec: FocusSpec) -> str | None:
    voids = [op for op in scenario.operations if isinstance(op, VoidTransfer)]
    if not voids:
        return "expected at least one void_transfer"
    produced = {
        op.ref
        for op in scenario.operations
        if isinstance(op, (FifoRepayment, TargetedRepayment, CreatePrepayment, ReturnPrepayment))
    }
    for void in voids:
        if void.transfer_ref not in produced:
            return "a void must reference an earlier transfer-producing operation"
    return None


def _contract_mixed_flow(scenario: Scenario, spec: FocusSpec) -> str | None:
    operations = scenario.operations
    kinds = {op.type for op in operations}
    if len(operations) < 4:
        return f"expected at least 4 operations, found {len(operations)}"
    if len(kinds) < 3:
        return f"expected at least 3 distinct operation types, found {len(kinds)}"
    if not any(isinstance(op, CreatePrepayment) for op in operations):
        return "expected the flow to include a prepayment"
    if not any(isinstance(op, (LinkedRefund, TargetedRepayment, FifoRepayment)) for op in operations):
        return "expected the flow to include a refund or a repayment"
    return None


def _contract_multi_currency(scenario: Scenario, spec: FocusSpec) -> str | None:
    """A foreign-currency expense whose original and base amounts diverge."""
    foreign = [
        op
        for op in _expenses(scenario)
        if isinstance(op, CreateExpense) and op.amount > 0 and op.currency != spec.base_currency
    ]
    if not foreign:
        return f"expected a positive expense in a currency other than {spec.base_currency}"
    expense = foreign[0]
    if expense.split_method != "manual":
        return "expected a manual split so the foreign-currency debt direction is determined"
    creditors = [n for n in set(expense.splits) | set(expense.payments) if _net(expense, n) < 0]
    debtors = [n for n in set(expense.splits) | set(expense.payments) if _net(expense, n) > 0]
    if not creditors or not debtors:
        return "the foreign-currency expense must create a real cross-participant debt"
    return None


def _contract_final_settlement(scenario: Scenario, spec: FocusSpec) -> str | None:
    """Preview the server plan, execute an item of it, and keep the plan observable."""
    operations = scenario.operations
    executions = [op for op in operations if isinstance(op, FinalSettlement)]
    if not executions:
        return "expected at least one final_settlement execution"
    first_execution = operations.index(executions[0])
    if not any(isinstance(op, PreviewFinalSettlement) for op in operations[:first_execution]):
        return "expected a preview_final_settlement before the first execution"
    expenses = [op for op in _expenses(scenario) if isinstance(op, CreateExpense) and op.amount > 0]
    if len(expenses) < 2:
        return "expected at least two expenses so the final plan needs a path"
    debtors: set[str] = set()
    creditors: set[str] = set()
    for expense in expenses:
        if expense.split_method != "manual":
            return "expected manual splits so the settlement topology is determined"
        for name in set(expense.splits) | set(expense.payments):
            value = _net(expense, name)
            if value > 0:
                debtors.add(name)
            elif value < 0:
                creditors.add(name)
    if len(debtors) < 2 or len(creditors) < 2:
        return f"expected at least 2 debtors and 2 creditors, found {len(debtors)} and {len(creditors)}"
    return None


def _contract_large_activity(scenario: Scenario, spec: FocusSpec) -> str | None:
    """A large activity whose expenses live inside distinct sub-activities."""
    sub_refs = {op.ref for op in scenario.operations if isinstance(op, CreateSubActivity)}
    if len(sub_refs) < 2:
        return f"expected at least 2 sub-activities, found {len(sub_refs)}"
    used = {op.ledger_unit_ref for op in _expenses(scenario) if op.ledger_unit_ref}
    if len(used) < 2:
        return "expected expenses inside at least 2 different sub-activities"
    if not used <= sub_refs:
        return "every ledger_unit_ref must name an earlier create_sub_activity"
    return None


def _contract_refund_boundary(scenario: Scenario, spec: FocusSpec) -> str | None:
    """Linked refunds pushed towards their cumulative cap, but never past it."""
    refunds = [op for op in scenario.operations if isinstance(op, LinkedRefund)]
    if not refunds:
        return "expected at least one linked_refund"
    best = Decimal(0)
    for refund in refunds:
        source = next(
            (
                op
                for op in scenario.operations
                if isinstance(op, CreateExpense) and op.ref == refund.original_expense_ref
            ),
            None,
        )
        if source is None or source.amount <= 0:
            return "a linked refund must reference an earlier positive expense"
        total = sum(
            (
                -op.amount
                for op in refunds
                if op.original_expense_ref == refund.original_expense_ref
            ),
            Decimal(0),
        )
        if total > source.amount:
            return f"cumulative refunds {total} exceed the source amount {source.amount}"
        best = max(best, total / source.amount)
    if best < Decimal("0.9"):
        return f"expected refunds to reach at least 90% of their source amount, reached {best:.2f}"
    return None


def _contract_completion_archive(scenario: Scenario, spec: FocusSpec) -> str | None:
    """Either settle everything and archive, or archive unsettled and unarchive."""
    archives = [
        index for index, op in enumerate(scenario.operations) if isinstance(op, ArchiveActivity)
    ]
    if not archives:
        return "expected at least one archive_activity"
    first = archives[0]
    tail = scenario.operations[first + 1:]
    unarchived = [op for op in tail if isinstance(op, UnarchiveActivity)]
    if tail and not unarchived:
        return "nothing may follow archive_activity except unarchive_activity"

    debt = Decimal(0)
    repaid = Decimal(0)
    for operation in scenario.operations:
        if (
            isinstance(operation, CreateExpense)
            and operation.amount > 0
            and operation.split_method == "manual"
        ):
            for name in set(operation.splits) | set(operation.payments):
                value = _net(operation, name)
                if value > 0:
                    debt += value
        elif isinstance(operation, (FifoRepayment, TargetedRepayment)):
            repaid += operation.amount

    if unarchived:
        if debt > 0 and repaid >= debt:
            return "a cancelled archive must leave debt outstanding when it is archived"
    else:
        if first != len(scenario.operations) - 1:
            return "archive_activity must be the final operation"
        if debt <= 0 or repaid < debt:
            return f"expected the whole {debt} debt to be settled before archiving, repaid {repaid}"
    return None


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


def _spec(
    name: str,
    tier: str,
    title: str,
    sections: tuple[int, ...],
    participants: tuple[int, int],
    payers: tuple[int, ...],
    amount_patterns: tuple[str, ...],
    operation_counts: tuple[int, ...],
    edge_tags: tuple[str, ...],
    goal: str,
    contract: Callable[[Scenario, FocusSpec], str | None],
    *,
    activity_types: tuple[str, ...] = ("normal",),
    base_currency: str = "CNY",
    multi_currency: bool = False,
    plan_currency: str = "CNY",
    plan_amount_scale: int = 1,
) -> FocusSpec:
    """Build a spec whose stored contract also applies the shared preconditions."""
    placeholder = FocusSpec(
        name=name, tier=tier, title=title, sections=sections, participants=participants,
        payers=payers, amount_patterns=amount_patterns, operation_counts=operation_counts,
        edge_tags=edge_tags, goal=goal, contract=lambda scenario: None,
        activity_types=activity_types, base_currency=base_currency,
        multi_currency=multi_currency, plan_currency=plan_currency,
        plan_amount_scale=plan_amount_scale,
    )

    def bound(scenario: Scenario, _spec: FocusSpec = placeholder) -> str | None:
        return _common(scenario, _spec) or contract(scenario, _spec)

    return replace(placeholder, contract=bound)


_SPECS: dict[str, FocusSpec] = {}


def _register(spec: FocusSpec) -> FocusSpec:
    _SPECS[spec.name] = spec
    return spec


_register(_spec(
    "expense_aa", SMOKE_TIER, "AA 均摊消费（E2E smoke）", (5, 6, 7, 8), (3, 3), (2, 3),
    ("divisible", "decimal"), (1,), ("multiple_creditors",),
    "Three participants share one expense equally (AA) paid by two or three of them.",
    _contract_expense_aa,
))
_register(_spec(
    "targeted_repayment", SMOKE_TIER, "定向还款（E2E smoke）", (5, 6, 8, 9, 10, 11), (3, 5), (1,),
    ("divisible", "non_divisible", "decimal"), (2,), ("partial_repayment",),
    "One participant pays for another, then that debtor makes a strictly partial targeted repayment.",
    _contract_targeted_repayment,
))
_register(_spec(
    "prepayment_refund", SMOKE_TIER, "预付款与原路退款（E2E smoke）", (5, 6, 8, 9, 11, 12, 13, 16),
    (3, 4), (1,), ("divisible", "non_divisible", "decimal"), (3,),
    ("remaining_prepayment", "partial_repayment"),
    "A prepayment, then a shared expense, then a linked refund against that expense.",
    _contract_prepayment_refund,
))

# ---- formal coverage focuses -------------------------------------------------

_register(_spec(
    "single_payer_aa", COVERAGE_TIER, "单人付款 AA 均摊", (5, 6, 7, 8), (3, 5), (1,),
    ("divisible", "non_divisible", "decimal", "large", "small"), (1,),
    ("rounding_residual",),
    "Exactly one participant pays the whole bill; everyone splits it equally (AA).",
    _contract_single_payer_aa,
))
_register(_spec(
    "multi_payer_aa", COVERAGE_TIER, "多付款人 AA 均摊", (5, 6, 7, 8), (3, 5), (2, 3),
    ("non_divisible", "divisible", "decimal"), (1,),
    ("multiple_creditors", "rounding_residual"),
    "Two or three participants each pay part of one AA expense, leaving at least one pure debtor.",
    _contract_multi_payer_aa,
))
_register(_spec(
    "aa_rounding", COVERAGE_TIER, "AA 尾差分配", (5, 7, 8), (3, 3), (1, 2, 3),
    ("non_divisible",), (1,), ("rounding_residual", "multiple_creditors"),
    "An AA expense whose amount cannot be divided exactly, so the rounding remainder is allocated.",
    _contract_aa_rounding,
))
_register(_spec(
    "manual_split", COVERAGE_TIER, "手工分摊", (5, 6, 7, 8), (3, 5), (1, 2),
    ("divisible", "non_divisible", "decimal", "large", "small"), (1,),
    ("multiple_creditors",),
    "The caller states each participant's share explicitly instead of using AA.",
    _contract_manual_split,
))
_register(_spec(
    "fifo_repayment", COVERAGE_TIER, "FIFO 还款", (5, 6, 8, 9, 10, 11), (3, 5), (1,),
    ("divisible", "non_divisible", "decimal"), (2,), ("partial_repayment", "full_settlement"),
    "An expense creates a debt, then the debtor repays it by FIFO without naming a target expense.",
    _contract_fifo_repayment,
))
_register(_spec(
    "multiple_repayments", COVERAGE_TIER, "多次分批还款", (5, 8, 9, 10), (3, 5), (1,),
    ("divisible", "non_divisible", "decimal"), (3, 4),
    ("partial_repayment", "full_settlement"),
    "One debt is cleared by two or more separate instalment repayments.",
    _contract_multiple_repayments,
))
_register(_spec(
    "prepayment_before_debt", COVERAGE_TIER, "先预存后产生债务", (5, 8, 9, 12, 16), (3, 5), (1,),
    ("divisible", "non_divisible", "decimal"), (2,),
    ("remaining_prepayment",),
    "A prepayment is created first; a later expense makes the prepayment owner owe the custodian, "
    "so the account can be used against that debt.",
    _contract_prepayment_before_debt,
))
_register(_spec(
    "prepayment_after_debt", COVERAGE_TIER, "先有债务后预存清偿", (5, 8, 9, 12, 16), (3, 5), (1,),
    ("divisible", "non_divisible", "decimal"), (2,), ("full_settlement", "remaining_prepayment"),
    "An expense first makes one participant owe another; a later prepayment settles that existing debt.",
    _contract_prepayment_after_debt,
))
_register(_spec(
    "prepayment_return", COVERAGE_TIER, "预存返还", (5, 8, 11, 12, 16), (3, 5), (1,),
    ("divisible", "non_divisible", "decimal"), (2, 3), ("remaining_prepayment", "full_settlement"),
    "A prepayment is created and then partly or fully returned by the custodian to the owner.",
    _contract_prepayment_return,
))
_register(_spec(
    "linked_refund", COVERAGE_TIER, "关联退款", (5, 6, 8, 13, 16), (3, 5), (1, 2),
    ("divisible", "non_divisible", "decimal"), (2,), ("partial_repayment",),
    "A positive expense, then a negative linked refund whose receiver differs from its beneficiary.",
    _contract_linked_refund,
))
_register(_spec(
    "negative_expense", COVERAGE_TIER, "无关联负数调整", (5, 6, 8, 13), (3, 5), (1,),
    ("divisible", "non_divisible", "decimal"), (1,), ("multiple_creditors",),
    "A standalone negative expense that is not linked to any earlier expense.",
    _contract_negative_expense,
))
_register(_spec(
    "void_transfer", COVERAGE_TIER, "作废转账", (5, 8, 9, 11, 16, 17), (3, 5), (1,),
    ("divisible", "non_divisible", "decimal"), (3,), ("partial_repayment", "full_settlement"),
    "A real repayment is registered and then voided; history is kept but its current effect is removed.",
    _contract_void_transfer,
))
_register(_spec(
    "mixed_flow", COVERAGE_TIER, "混合流程", (5, 8, 9, 11, 12, 13, 16), (3, 5), (1, 2),
    ("divisible", "non_divisible", "decimal"), (4, 5),
    ("partial_repayment", "remaining_prepayment", "multiple_creditors"),
    "A longer flow that combines a prepayment with a refund or a repayment in one activity.",
    _contract_mixed_flow,
))

_register(_spec(
    "multi_currency", COVERAGE_TIER, "多币种原币/base 分离", (5, 7, 8, 15), (3, 5), (1,),
    ("divisible", "non_divisible", "decimal"), (2, 3),
    ("fx_conversion", "cross_currency_settlement"),
    "A foreign-currency expense whose original amount and base amount diverge through the "
    "server FX snapshot, then a repayment against the resulting foreign-currency debt.",
    _contract_multi_currency,
    base_currency="CNY", multi_currency=True, plan_currency="EUR", plan_amount_scale=2,
))
_register(_spec(
    "final_settlement", COVERAGE_TIER, "最终结算计划执行", (5, 8, 9, 14, 16), (4, 5), (1,),
    ("divisible", "non_divisible", "decimal"), (6, 7),
    ("multi_hop_path", "plan_invalidated", "partial_repayment"),
    "Several debts among three or more participants, a previewed final plan, and execution of "
    "one complete suggestion item, with an external payment in between.",
    _contract_final_settlement,
))
_register(_spec(
    "large_activity", COVERAGE_TIER, "大型活动与子活动", (2, 5, 6, 8, 12), (3, 5), (1,),
    ("divisible", "non_divisible", "decimal"), (5,),
    ("sub_activity_split", "remaining_prepayment"),
    "A large activity with several sub-activities: expenses booked inside different "
    "sub-activities against one shared member pool, and a large-activity prepayment.",
    _contract_large_activity,
    activity_types=("large",),
))
_register(_spec(
    "refund_boundary", COVERAGE_TIER, "退款上限边界", (5, 13, 16), (3, 4), (1,),
    ("divisible", "non_divisible", "decimal"), (3, 4), ("partial_repayment", "refund_cap_boundary", "cumulative_refund"),
    "Linked refunds that are partial, cumulative, and pushed to the source expense cap, "
    "including a refund after the original debt has been settled.",
    _contract_refund_boundary,
))
_register(_spec(
    "completion_archive", COVERAGE_TIER, "完成判定与归档", (5, 6, 8, 9, 12, 18), (3, 4), (1,),
    ("divisible", "non_divisible", "decimal"), (3, 4),
    ("full_settlement", "cancel_archive", "remaining_prepayment"),
    "Either settle every debt and archive the completed activity, or archive while debt or a "
    "prepayment balance remains and then cancel the archive.",
    _contract_completion_archive,
))

# ``targeted_repayment`` belongs to both tiers: it is the historical smoke focus
# and one of the formal coverage focuses.  Its contract above is the strict one.
_SPECS["targeted_repayment"] = replace(_SPECS["targeted_repayment"], tier=COVERAGE_TIER)

ALL_FOCUSES: tuple[str, ...] = tuple(_SPECS)
# The historical three-focus E2E smoke set.  ``targeted_repayment`` is also a
# formal coverage focus, so this list is named explicitly rather than derived.
SMOKE_FOCUSES: tuple[str, ...] = ("expense_aa", "targeted_repayment", "prepayment_refund")
COVERAGE_FOCUSES: tuple[str, ...] = tuple(n for n, s in _SPECS.items() if s.tier == COVERAGE_TIER)


def focus_spec(focus: str) -> FocusSpec:
    try:
        return _SPECS[focus]
    except KeyError:
        raise FocusDefinitionError(f"unsupported focus: {focus}") from None


def focus_sections(focus: str) -> tuple[int, ...]:
    return focus_spec(focus).sections


def check_focus(scenario: Scenario, focus: str) -> tuple[str, str | None]:
    """Return ``("FOCUS_VALID", None)`` or ``("FOCUS_MISMATCH", reason)``.

    ``reason`` names the business shape that is missing, never a model or
    transport failure.  It is safe to show to the Compiler repair step and to
    store in run artifacts.
    """
    spec = focus_spec(focus)
    reason = spec.contract(scenario)
    if reason is None:
        return "FOCUS_VALID", None
    return "FOCUS_MISMATCH", f"{spec.name}: {reason}"
