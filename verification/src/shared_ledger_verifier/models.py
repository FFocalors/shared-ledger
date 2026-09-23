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


Operation: TypeAlias = (
    CreateExpense
    | LinkedRefund
    | TargetedRepayment
    | FifoRepayment
    | CreatePrepayment
    | ReturnPrepayment
    | VoidTransfer
)


@dataclass(frozen=True, slots=True)
class Scenario:
    schema_version: Literal[1]
    scenario_id: str
    description: str
    activity: ActivitySpec
    participants: tuple[str, ...]
    operations: tuple[Operation, ...]
