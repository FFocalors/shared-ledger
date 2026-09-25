"""Small, dependency-free models for Scenario JSON v1.

Scenario values describe business actions and use participant/operation refs.
Money is represented by :class:`decimal.Decimal`; database identifiers and
RPC implementation details belong to the runner, not these models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, Mapping, TypeAlias


ActivityType: TypeAlias = Literal["normal", "large"]
SplitMethod: TypeAlias = Literal["manual", "aa"]


@dataclass(frozen=True, slots=True)
class ActivitySpec:
    type: ActivityType
    base_currency: str
    multi_currency_enabled: bool


@dataclass(frozen=True, slots=True)
class CreateExpense:
    ref: str
    title: str
    amount: Decimal
    currency: str
    payments: Mapping[str, Decimal]
    split_method: SplitMethod
    splits: Mapping[str, Decimal] | None = None
    aa_participants: tuple[str, ...] = ()
    # Optional sub-activity this expense belongs to; None means the root ledger unit.
    ledger_unit_ref: str | None = None
    type: Literal["create_expense"] = field(default="create_expense", init=False)


@dataclass(frozen=True, slots=True)
class LinkedRefund:
    ref: str
    original_expense_ref: str
    title: str
    amount: Decimal
    currency: str
    payments: Mapping[str, Decimal]
    split_method: SplitMethod
    splits: Mapping[str, Decimal] | None = None
    aa_participants: tuple[str, ...] = ()
    ledger_unit_ref: str | None = None
    type: Literal["linked_refund"] = field(default="linked_refund", init=False)


@dataclass(frozen=True, slots=True)
class TargetedRepayment:
    ref: str
    from_participant: str
    to_participant: str
    amount: Decimal
    currency: str
    target_expense_refs: tuple[str, ...]
    type: Literal["targeted_repayment"] = field(default="targeted_repayment", init=False)


@dataclass(frozen=True, slots=True)
class FifoRepayment:
    ref: str
    from_participant: str
    to_participant: str
    amount: Decimal
    currency: str
    type: Literal["fifo_repayment"] = field(default="fifo_repayment", init=False)


@dataclass(frozen=True, slots=True)
class CreatePrepayment:
    ref: str
    owner_participant: str
    custodian_participant: str
    amount: Decimal
    currency: str
    type: Literal["create_prepayment"] = field(default="create_prepayment", init=False)


@dataclass(frozen=True, slots=True)
class ReturnPrepayment:
    ref: str
    owner_participant: str
    custodian_participant: str
    amount: Decimal
    currency: str
    type: Literal["return_prepayment"] = field(default="return_prepayment", init=False)


@dataclass(frozen=True, slots=True)
class VoidTransfer:
    transfer_ref: str
    reason: str
    type: Literal["void_transfer"] = field(default="void_transfer", init=False)


@dataclass(frozen=True, slots=True)
class CreateSubActivity:
    """A sub-activity (LedgerUnit) of a large activity; holds its own expenses.

    ``create_sub_activity(activity_id, name)`` inherits the parent activity's
    type, base currency and multi-currency setting, so the scenario names only
    a ref and a display name.
    """

    ref: str
    name: str
    type: Literal["create_sub_activity"] = field(default="create_sub_activity", init=False)


FinalSettlementMode: TypeAlias = Literal["base_unified", "original_currency"]


@dataclass(frozen=True, slots=True)
class FinalSettlement:
    """One complete suggestion item from the server's current final plan.

    Section 14: the client executes a suggested item as-is; it never chooses a
    partial amount. The amount and currency therefore come from the server plan
    at execution time rather than from the scenario.
    """

    ref: str
    mode: FinalSettlementMode
    # Optional: omitted means "take the first item of the current server plan".
    from_participant: str | None = None
    to_participant: str | None = None
    type: Literal["final_settlement"] = field(default="final_settlement", init=False)


@dataclass(frozen=True, slots=True)
class PreviewFinalSettlement:
    """Read-only snapshot of the current final plan; changes no financial fact."""

    ref: str
    mode: FinalSettlementMode
    type: Literal["preview_final_settlement"] = field(default="preview_final_settlement", init=False)


@dataclass(frozen=True, slots=True)
class ArchiveActivity:
    ref: str
    type: Literal["archive_activity"] = field(default="archive_activity", init=False)


@dataclass(frozen=True, slots=True)
class UnarchiveActivity:
    ref: str
    type: Literal["unarchive_activity"] = field(default="unarchive_activity", init=False)


Operation: TypeAlias = (
    CreateExpense
    | LinkedRefund
    | TargetedRepayment
    | FifoRepayment
    | CreatePrepayment
    | ReturnPrepayment
    | VoidTransfer
    | CreateSubActivity
    | FinalSettlement
    | PreviewFinalSettlement
    | ArchiveActivity
    | UnarchiveActivity
)


@dataclass(frozen=True, slots=True)
class Scenario:
    schema_version: Literal[1]
    scenario_id: str
    description: str
    activity: ActivitySpec
    participants: tuple[str, ...]
    operations: tuple[Operation, ...]
