"""P3a mock write path: deterministic effects and exactly-once application.

The agent must never invent a business effect. This module therefore derives the
mock effect *only* from the already-confirmed fixed command, with no clock, no
randomness and no client input, so re-deriving it after a restart yields the same
bytes. Durable application lives in the Store; this module is pure.

What it deliberately does not do: talk to a network, decide amounts, or merge
commands. The mock ledger records what the fixed command said, plus a per
activity financial-version increment that later previews bind to.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from . import contracts as c


class MockPreconditionConflict(RuntimeError):
    """The preview's bound ledger state no longer matches; the effect must not apply."""


class MockExecutionStateError(RuntimeError):
    """The stored proposal/execution cannot legally take this step."""


class MockWriteRefused(MockExecutionStateError):
    """A write refused before any effect, because authorization or lifecycle forbids it."""

    code = "mock_write_refused"


class MockPermissionDenied(MockWriteRefused):
    """The actor may not write to the proposed Activity."""

    code = "actor_not_permitted"


class MockActivityArchived(MockWriteRefused):
    """The Activity is archived, so a new write must not be applied."""

    code = "activity_archived"


@dataclass(frozen=True, slots=True)
class MockActivityAccess:
    """Who may write to one mock Activity, and whether it still accepts writes."""

    activity_id: uuid.UUID
    member_ids: frozenset[uuid.UUID]
    archived: bool = False


class MockActivityRoster:
    """Server-side permission and Activity lifecycle, as far as P3a can model them.

    The Mock has no membership table and no Activity rows, so a check that only
    read the fixture could never refuse. This roster makes the refusal explicit
    and mutable, and the Store consults it at both commit boundaries — dispatch
    and effect application — so a preview that was valid when rendered is
    re-checked before anything lands. An unknown Activity is treated exactly like
    one the actor may not touch: both refuse, and neither reveals which.
    """

    def __init__(self, activities: Iterable[MockActivityAccess] = ()) -> None:
        self._by_id = {item.activity_id: item for item in activities}

    def add(
        self,
        activity_id: uuid.UUID,
        member_ids: Iterable[uuid.UUID],
        *,
        archived: bool = False,
    ) -> MockActivityAccess:
        access = MockActivityAccess(activity_id, frozenset(member_ids), archived)
        self._by_id[activity_id] = access
        return access

    def archive(self, activity_id: uuid.UUID) -> None:
        current = self._require(activity_id)
        self._by_id[activity_id] = MockActivityAccess(
            activity_id, current.member_ids, archived=True,
        )

    def remove_member(self, activity_id: uuid.UUID, actor_id: uuid.UUID) -> None:
        current = self._require(activity_id)
        self._by_id[activity_id] = MockActivityAccess(
            activity_id, current.member_ids - {actor_id}, current.archived,
        )

    def _require(self, activity_id: uuid.UUID) -> MockActivityAccess:
        activity = self._by_id.get(activity_id)
        if activity is None:
            raise MockPermissionDenied("the actor may not write to this activity")
        return activity

    def require_writable(self, actor_id: uuid.UUID, activity_id: uuid.UUID) -> None:
        """Authorization first, then lifecycle; both refuse before any effect."""
        activity = self._by_id.get(activity_id)
        if activity is None or actor_id not in activity.member_ids:
            raise MockPermissionDenied("the actor may not write to this activity")
        if activity.archived:
            raise MockActivityArchived("the activity is archived; new writes are refused")

    def writable_guard(self, actor_id: uuid.UUID) -> Callable[[uuid.UUID], None]:
        """Bind one actor so the Store can re-check without knowing about rosters."""
        return lambda activity_id: self.require_writable(actor_id, activity_id)


@dataclass(frozen=True, slots=True)
class MockExpenseEffect:
    """The exact effect of one confirmed `expense.create` command."""

    operation: str
    activity_id: uuid.UUID
    ledger_unit_id: uuid.UUID
    title: str
    original_amount: str
    original_currency: str
    occurred_at: datetime | None
    payment_allocations: tuple[tuple[uuid.UUID, str], ...]
    split_mode: str
    split_participant_ids: tuple[uuid.UUID, ...]
    expected_financial_version: str
    command_sha256: str

    def as_payload(self) -> dict[str, Any]:
        """JSON-safe, order-stable projection stored in the mock ledger."""
        return {
            "operation": self.operation,
            "activity_id": str(self.activity_id),
            "ledger_unit_id": str(self.ledger_unit_id),
            "title": self.title,
            "original_amount": self.original_amount,
            "original_currency": self.original_currency,
            "occurred_at": (self.occurred_at or datetime.now(timezone.utc)).isoformat(),
            "payment_allocations": [
                [str(participant_id), amount]
                for participant_id, amount in self.payment_allocations
            ],
            "split": {
                "mode": self.split_mode,
                "participant_ids": [str(item) for item in self.split_participant_ids],
            },
            "expected_financial_version": self.expected_financial_version,
        }

    def next_financial_version(self) -> int:
        return int(self.expected_financial_version) + 1


def canonical_command_sha256(command: c.FixedExpenseCreateCommand) -> str:
    encoded = json.dumps(
        command.model_dump(mode="json", by_alias=True, exclude_none=False),
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def mock_effect_for_command(command: c.FixedExpenseCreateCommand) -> MockExpenseEffect:
    """Derive the one effect this command can have. Pure and repeatable."""
    if type(command) is not c.FixedExpenseCreateCommand:
        raise MockExecutionStateError("only a fixed expense-create command can be applied")
    if command.operation != "expense.create":
        raise MockExecutionStateError("the mock write path applies expense.create only")
    amount = Decimal(command.original_amount)
    if amount <= 0:
        raise MockExecutionStateError("the fixed command must carry a positive amount")
    if sum((Decimal(item.amount) for item in command.payment_allocations), Decimal("0")) != amount:
        raise MockExecutionStateError("payment allocations must sum to the command amount")
    split = command.split
    if split.mode == "equal":
        participants = tuple(split.participant_ids)
    else:  # pragma: no cover - the frozen command carries equal splits today
        raise MockExecutionStateError("unsupported split mode for the mock write path")
    if not participants:
        raise MockExecutionStateError("the fixed command must name split participants")
    return MockExpenseEffect(
        operation=command.operation,
        activity_id=command.activity_id,
        ledger_unit_id=command.ledger_unit_id,
        title=command.title,
        original_amount=command.original_amount,
        original_currency=command.original_currency,
        occurred_at=command.occurred_at,
        payment_allocations=tuple(
            (item.participant_id, item.amount) for item in command.payment_allocations
        ),
        split_mode=split.mode,
        split_participant_ids=participants,
        expected_financial_version=command.expected_financial_version,
        command_sha256=canonical_command_sha256(command),
    )


def require_matching_financial_version(
    preconditions: c.PreconditionSnapshot | None,
    current_financial_version: int,
) -> None:
    """A preview only holds while the ledger state it bound is unchanged."""
    if preconditions is None:
        raise MockPreconditionConflict("a confirmed backend proposal must carry preconditions")
    bound = preconditions.activity_financial_version
    if bound is None:
        raise MockPreconditionConflict("the preview did not bind a financial version")
    try:
        bound_value = int(bound)
    except (TypeError, ValueError):
        raise MockPreconditionConflict("the bound financial version is not an integer") from None
    if bound_value != current_financial_version:
        raise MockPreconditionConflict(
            "the activity financial version changed since the preview; the preview is stale"
        )
