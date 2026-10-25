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
from typing import Any, Mapping, Sequence

from . import contracts as c


_COMMAND = re.compile(
    r"^\s*记账\s+(?P<title>.+?)\s+(?P<amount>\d{1,9}(?:\.\d{1,4})?)\s*(?P<rest>.*)$"
)
_DIRECTIVE = re.compile(r"(付款人|分摊|账本)\s*=\s*([^\s]+)")
_FOREIGN_MARKERS = ("USD", "美元", "$", "EUR", "欧元", "JPY", "日元")
_ALL_TOKENS = ("所有人", "全部", "全员")


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
