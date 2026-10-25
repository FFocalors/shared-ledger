"""P5.0 device-acceptance bridge: a deterministic `记账` command.

This is deliberately not a product parser. It exists so the real write path can
be exercised on a physical device before the model profile is allowed to emit a
structured proposal. It is gated by `AGENT_P5_DEV_INTENT_ENABLED` (default off),
only runs with the non-v3 P2 profile, and only intercepts input that starts with
the documented command.

Syntax:

    记账 <标题> <金额> [付款人=<名字>] [分摊=<名字1>,<名字2>] [账本=<名字>]

Defaults: payer is the first active Participant, split is every active
Participant, ledger unit is the first active unit, currency is the Activity base
currency. `分摊=所有人` is accepted as the explicit "everyone" form.

Names come from the current server-resolved scope labels; the command never
accepts a client-supplied UUID. A name that matches zero or multiple entities
declines the bridge, so the normal model path runs instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from . import contracts as c


_COMMAND = re.compile(
    r"^\s*记账\s+(?P<title>.+?)\s+(?P<amount>\d{1,9}(?:\.\d{1,4})?)\s*(?P<rest>.*)$"
)
_UPDATE_COMMAND = re.compile(
    r"^\s*改账\s+(?P<title>.+?)\s+(?P<amount>\d{1,9}(?:\.\d{1,4})?)\s*(?P<rest>.*)$"
)
_DIRECTIVE = re.compile(r"(付款人|分摊|账本)\s*=\s*([^\s]+)")
_FOREIGN_MARKERS = ("USD", "美元", "$", "EUR", "欧元", "JPY", "日元")
_ALL_TOKENS = ("所有人", "全部", "全员")


@dataclass(frozen=True, slots=True)
class DevUpdateCommand:
    title: str
    amount: str
    payer_name: str | None = None
    split_token: str | None = None
    unit_name: str | None = None


def is_dev_update_command(text: str) -> bool:
    return isinstance(text, str) and text.lstrip().startswith("改账")


def has_foreign_currency_marker(text: str) -> bool:
    return isinstance(text, str) and any(marker in text for marker in _FOREIGN_MARKERS)


def parse_dev_expense_update(text: str) -> DevUpdateCommand | None:
    """Parse the documented update command; None means the bridge must refuse."""
    if not isinstance(text, str):
        return None
    match = _UPDATE_COMMAND.match(text)
    if match is None:
        return None
    title = match.group("title").strip()
    amount = match.group("amount")
    rest = match.group("rest") or ""
    if not title or not amount or any(marker in rest for marker in _FOREIGN_MARKERS):
        return None
    directives = dict(_DIRECTIVE.findall(rest))
    return DevUpdateCommand(
        title=title,
        amount=amount,
        payer_name=directives.get("付款人"),
        split_token=directives.get("分摊"),
        unit_name=directives.get("账本"),
    )



class DevIntentRefused(Exception):
    """The command is syntactically valid but cannot be bound safely."""


def build_dev_update_intent(
    cmd: DevUpdateCommand,
    references: Sequence[c.BoundReference],
    labels: Mapping[Any, Any],
    base_currency: str | None,
    *,
    expense_id: Any,
    source_turn_id: Any,
    activity_id: Any,
    current_payments: Sequence[tuple[Any, str]],
    current_split_method: str,
) -> tuple[c.ExpenseUpdateIntent, c.BoundExpenseReference]:
    """Bind the update command to the unique target Expense."""
    if not base_currency:
        raise DevIntentRefused("当前活动没有可用的基础币种。")
    participants = [
        item for item in references
        if isinstance(item, c.BoundParticipantReference)
        and item.scope_activity_id == activity_id
    ]
    if not participants:
        raise DevIntentRefused("当前活动没有可用参与人。")
    names = {
        _ref_key(label.ref): str(label.display_name)
        for label in labels.values()
        if getattr(label, "kind", None) == "participant"
    }
    if cmd.payer_name is not None:
        payer = _resolve(participants, names, cmd.payer_name)
        if payer is None:
            raise DevIntentRefused(f"找不到唯一匹配的付款人「{cmd.payer_name}」。")
        payments = [c.PaymentAllocation(participant_ref=payer.ref, amount=cmd.amount)]
    else:
        if len(current_payments) != 1:
            raise DevIntentRefused("这笔消费有多个付款人，请用 付款人=名字 指定。")
        payer_id = current_payments[0][0]
        payer = next(
            (item for item in participants if item.entity_id == payer_id), None,
        )
        if payer is None:
            raise DevIntentRefused("当前付款人不在活动范围内，无法改账。")
        payments = [c.PaymentAllocation(participant_ref=payer.ref, amount=cmd.amount)]
    split = None
    if cmd.split_token is not None:
        if cmd.split_token in _ALL_TOKENS:
            split_refs = participants
        else:
            split_refs = []
            for name in cmd.split_token.split(","):
                resolved = _resolve(participants, names, name)
                if resolved is None:
                    raise DevIntentRefused(f"找不到唯一匹配的分摊人「{name}」。")
                split_refs.append(resolved)
        if not split_refs or len({_ref_key(item.ref) for item in split_refs}) != len(split_refs):
            raise DevIntentRefused("分摊人重复或不合法。")
        split = c.EqualSplitIntent(
            mode="equal", participant_refs=[item.ref for item in split_refs],
        )
    elif current_split_method == "manual":
        raise DevIntentRefused("这笔消费是手动分摊，请用 分摊=名字1,名字2 指定。")
    try:
        intent = c.ExpenseUpdateIntent(
            kind="expense.update",
            expense_ref=c.ExpenseRef.SELECTED,
            title=None,
            original_amount=cmd.amount,
            original_currency=None,
            payment_allocations=payments,
            split=split,
            note=None,
            occurred_at=None,
        )
    except ValueError as exc:
        raise DevIntentRefused("改账金额或分摊不合法。") from exc
    binding = c.BoundExpenseReference(
        kind="expense", ref=c.ExpenseRef.SELECTED, entity_id=expense_id,
        source_turn_id=source_turn_id, scope_activity_id=activity_id,
    )
    return intent, binding


def parse_dev_expense_create(
    text: str,
    references: Sequence[c.BoundReference],
    labels: Mapping[Any, Any],
    base_currency: str | None,
) -> c.ExpenseCreateIntent | None:
    """Return a fully bound create intent, or None to decline the bridge."""
    if not isinstance(text, str) or not base_currency:
        return None
    match = _COMMAND.match(text)
    if match is None:
        return None
    title = match.group("title").strip()
    amount = match.group("amount")
    rest = match.group("rest") or ""
    if not title or not amount or any(marker in rest for marker in _FOREIGN_MARKERS):
        return None

    directives = dict(_DIRECTIVE.findall(rest))
    participants = [
        item for item in references if isinstance(item, c.BoundParticipantReference)
    ]
    units = [
        item for item in references if isinstance(item, c.BoundLedgerUnitReference)
    ]
    if not participants or not units:
        return None
    activity_id = units[0].scope_activity_id
    participants = [item for item in participants if item.scope_activity_id == activity_id]
    units = [item for item in units if item.scope_activity_id == activity_id]
    if not participants or not units:
        return None

    participant_names = {
        _ref_key(label.ref): str(label.display_name)
        for label in labels.values()
        if getattr(label, "kind", None) == "participant"
    }
    unit_names = {
        _ref_key(label.ref): str(label.display_name)
        for label in labels.values()
        if getattr(label, "kind", None) == "ledger_unit"
    }

    payer = (
        _resolve(participants, participant_names, directives["付款人"])
        if "付款人" in directives else participants[0]
    )
    if payer is None:
        return None

    if "分摊" in directives:
        token = directives["分摊"]
        if token in _ALL_TOKENS:
            split_refs = participants
        else:
            split_refs = []
            for name in token.split(","):
                resolved = _resolve(participants, participant_names, name)
                if resolved is None:
                    return None
                split_refs.append(resolved)
    else:
        split_refs = participants
    if not split_refs or len({_ref_key(item.ref) for item in split_refs}) != len(split_refs):
        return None

    unit = (
        _resolve(units, unit_names, directives["账本"])
        if "账本" in directives else units[0]
    )
    if unit is None:
        return None

    try:
        return c.ExpenseCreateIntent(
            kind="expense.create",
            ledger_unit_ref=unit.ref,
            title=title,
            original_amount=amount,
            original_currency=base_currency,
            payment_allocations=[
                c.PaymentAllocation(participant_ref=payer.ref, amount=amount),
            ],
            split=c.EqualSplitIntent(
                mode="equal",
                participant_refs=[item.ref for item in split_refs],
            ),
            occurred_at=None,
        )
    except ValueError:
        return None


def _resolve(items: Sequence[Any], names: Mapping[str, str], token: str) -> Any | None:
    exact = [item for item in items if names.get(_ref_key(item.ref)) == token]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None
    partial = [
        item for item in items
        if token and token in (names.get(_ref_key(item.ref)) or "")
    ]
    return partial[0] if len(partial) == 1 else None


def _ref_key(ref: Any) -> str:
    return getattr(ref, "value", str(ref))
