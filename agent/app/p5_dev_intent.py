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
from decimal import Decimal, InvalidOperation
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
_PRESENTATION_COMMANDS = {
    "改名": "title",
    "改图标": "icon",
    "改备注": "note",
}


def is_dev_delete_command(text: str) -> bool:
    return isinstance(text, str) and text.lstrip().startswith("删除")


def parse_dev_delete_command(text: str, titles: Sequence[str]) -> str | None:
    """The delete command has no value: the remainder must equal one title."""
    if not isinstance(text, str):
        return None
    stripped = text.lstrip()
    if not stripped.startswith("删除"):
        return None
    remainder = stripped[len("删除"):].strip()
    if not remainder:
        return None
    if remainder not in titles or titles.count(remainder) != 1:
        return None
    return remainder


def build_dev_delete_intent(
    *,
    expense_id: Any,
    source_turn_id: Any,
    activity_id: Any,
) -> tuple[c.ExpenseDeleteIntent, c.BoundExpenseReference]:
    intent = c.ExpenseDeleteIntent(
        kind="expense.delete", expense_ref=c.ExpenseRef.SELECTED,
    )
    binding = c.BoundExpenseReference(
        kind="expense", ref=c.ExpenseRef.SELECTED, entity_id=expense_id,
        source_turn_id=source_turn_id, scope_activity_id=activity_id,
    )
    return intent, binding


@dataclass(frozen=True, slots=True)
class DevUpdateCommand:
    title: str
    amount: str
    payer_name: str | None = None
    split_token: str | None = None
    unit_name: str | None = None


@dataclass(frozen=True, slots=True)
class DevPresentationCommand:
    kind: str  # "title" | "icon" | "note"
    target_title: str
    value: str


@dataclass(frozen=True, slots=True)
class DevRepaymentCommand:
    from_name: str
    to_name: str
    amount: str
    currency: str
    mode: str


@dataclass(frozen=True, slots=True)
class DevVoidCommand:
    from_name: str
    to_name: str
    amount: str
    currency: str
    reason: str


def is_dev_void_command(text: str) -> bool:
    return isinstance(text, str) and text.lstrip().startswith("作废")


def parse_dev_void_command(text: str) -> DevVoidCommand | None:
    """Parse `作废 <payer> <payee> <amount> <currency> [原因=<text>]`."""
    if not isinstance(text, str):
        return None
    stripped = text.lstrip()
    if not stripped.startswith("作废"):
        return None
    parts = stripped[len("作废"):].split(maxsplit=4)
    if len(parts) not in (4, 5):
        return None
    payer, payee, amount, currency = parts[:4]
    reason = "dev bridge void"
    if len(parts) == 5:
        tail = parts[4].strip()
        if not tail.startswith("原因="):
            return None
        reason = tail[len("原因="):].strip() or reason
    currency = currency.upper()
    if not payer or not payee or payer == payee:
        return None
    if not re.fullmatch(r"[A-Z]{3}", currency):
        return None
    try:
        value = Decimal(amount)
    except (InvalidOperation, TypeError):
        return None
    if not value.is_finite() or value <= 0:
        return None
    if not reason:
        return None
    return DevVoidCommand(
        from_name=payer, to_name=payee, amount=amount,
        currency=currency, reason=reason,
    )


@dataclass(frozen=True, slots=True)
class DevPrepaymentCommand:
    owner_name: str
    custodian_name: str
    amount: str
    currency: str


def is_dev_prepayment_command(text: str) -> bool:
    return isinstance(text, str) and text.lstrip().startswith("预存")


def is_dev_prepayment_return_command(text: str) -> bool:
    return isinstance(text, str) and text.lstrip().startswith("返还")


def parse_dev_prepayment_command(text: str) -> DevPrepaymentCommand | None:
    """Parse `预存 <owner> <custodian> <amount> <currency>`."""
    return _parse_prepayment_parts(text, "预存")


def parse_dev_prepayment_return_command(text: str) -> DevPrepaymentCommand | None:
    """Parse `返还 <owner> <custodian> <amount> <currency>`."""
    return _parse_prepayment_parts(text, "返还")


def _parse_prepayment_parts(text: str, prefix: str) -> DevPrepaymentCommand | None:
    if not isinstance(text, str):
        return None
    stripped = text.lstrip()
    if not stripped.startswith(prefix):
        return None
    parts = stripped[len(prefix):].split()
    if len(parts) != 4:
        return None
    owner, custodian, amount, currency = parts
    currency = currency.upper()
    if not owner or not custodian or owner == custodian:
        return None
    if not re.fullmatch(r"[A-Z]{3}", currency):
        return None
    try:
        value = Decimal(amount)
    except (InvalidOperation, TypeError):
        return None
    if not value.is_finite() or value <= 0:
        return None
    return DevPrepaymentCommand(
        owner_name=owner, custodian_name=custodian,
        amount=amount, currency=currency,
    )


@dataclass(frozen=True, slots=True)
class DevFinalSettlementCommand:
    from_name: str
    to_name: str
    amount: str
    currency: str
    mode: str


def is_dev_final_settlement_command(text: str) -> bool:
    return isinstance(text, str) and text.lstrip().startswith("结算")


def parse_dev_final_settlement_command(
    text: str,
) -> DevFinalSettlementCommand | None:
    """Parse `结算 <payer> <payee> <amount> <currency> [模式=...]`.

    The command never names a plan item by id: only the server's current plan
    can decide whether this exact direction/amount/currency exists.
    """
    if not isinstance(text, str):
        return None
    stripped = text.lstrip()
    if not stripped.startswith("结算"):
        return None
    parts = stripped[len("结算"):].split(maxsplit=4)
    if len(parts) not in (4, 5):
        return None
    payer, payee, amount, currency = parts[:4]
    mode = "base_unified"
    if len(parts) == 5:
        tail = parts[4].strip()
        if not tail.startswith("模式="):
            return None
        mode = tail[len("模式="):].strip()
    currency = currency.upper()
    if not payer or not payee or payer == payee:
        return None
    if mode not in ("base_unified", "original_currency"):
        return None
    if not re.fullmatch(r"[A-Z]{3}", currency):
        return None
    try:
        value = Decimal(amount)
    except (InvalidOperation, TypeError):
        return None
    if not value.is_finite() or value <= 0:
        return None
    return DevFinalSettlementCommand(
        from_name=payer, to_name=payee, amount=amount,
        currency=currency, mode=mode,
    )


@dataclass(frozen=True, slots=True)
class DevRefundCommand:
    target_title: str
    amount: str
    receiver_name: str | None
    benefit_token: str | None


@dataclass(frozen=True, slots=True)
class DevNegativeAdjustmentCommand:
    title: str
    amount: str
    payer_name: str | None
    split_token: str | None


_REFUND_COMMAND = re.compile(
    r"^\s*退款\s+(?P<title>.+?)\s+(?P<amount>\d{1,9}(?:\.\d{1,4})?)\s*(?P<rest>.*)$"
)
_NEGATIVE_COMMAND = re.compile(
    r"^\s*负调整\s+(?P<title>.+?)\s+(?P<amount>\d{1,9}(?:\.\d{1,4})?)\s*(?P<rest>.*)$"
)
_REFUND_DIRECTIVE = re.compile(r"(收款人|受益)\s*=\s*([^\s]+)")


def is_dev_refund_command(text: str) -> bool:
    return isinstance(text, str) and text.lstrip().startswith("退款")


def is_dev_negative_adjustment_command(text: str) -> bool:
    return isinstance(text, str) and text.lstrip().startswith("负调整")


def is_dev_negative_amount_create(text: str) -> bool:
    """`记账` with a negative amount is refused, never reinterpreted."""
    if not isinstance(text, str):
        return False
    stripped = text.lstrip()
    if not stripped.startswith("记账"):
        return False
    return re.search(r"(?:^|\s)-\d", stripped) is not None


def parse_dev_refund_command(text: str) -> DevRefundCommand | None:
    """Parse `退款 <原单标题> <金额> [收款人=<名字>] [受益=<名字1>,<名字2>]`."""
    if not isinstance(text, str):
        return None
    match = _REFUND_COMMAND.match(text)
    if match is None:
        return None
    title = match.group("title").strip()
    amount = match.group("amount")
    rest = match.group("rest") or ""
    if not title or not amount or any(marker in rest for marker in _FOREIGN_MARKERS):
        return None
    directives = dict(_REFUND_DIRECTIVE.findall(rest))
    if _REFUND_DIRECTIVE.sub("", rest).strip():
        return None
    return DevRefundCommand(
        target_title=title,
        amount=amount,
        receiver_name=directives.get("收款人"),
        benefit_token=directives.get("受益"),
    )


def parse_dev_negative_adjustment_command(
    text: str,
) -> DevNegativeAdjustmentCommand | None:
    """Parse `负调整 <标题> <金额> [付款人=<名字>] [分摊=<名字1>,<名字2>]`."""
    if not isinstance(text, str):
        return None
    match = _NEGATIVE_COMMAND.match(text)
    if match is None:
        return None
    title = match.group("title").strip()
    amount = match.group("amount")
    rest = match.group("rest") or ""
    if not title or not amount or any(marker in rest for marker in _FOREIGN_MARKERS):
        return None
    directives = dict(_DIRECTIVE.findall(rest))
    return DevNegativeAdjustmentCommand(
        title=title,
        amount=amount,
        payer_name=directives.get("付款人"),
        split_token=directives.get("分摊"),
    )


def _dev_participants(
    references: Sequence[c.BoundReference], activity_id: Any,
) -> list[c.BoundParticipantReference]:
    return [
        item for item in references
        if isinstance(item, c.BoundParticipantReference)
        and item.scope_activity_id == activity_id
    ]


def _dev_participant_names(labels: Mapping[Any, Any]) -> dict[str, str]:
    return {
        _ref_key(label.ref): str(label.display_name)
        for label in labels.values()
        if getattr(label, "kind", None) == "participant"
    }


def _dev_split_refs(
    token: str | None,
    participants: Sequence[c.BoundParticipantReference],
    names: Mapping[str, str],
) -> list[Any]:
    if token is None or token in _ALL_TOKENS:
        return [item.ref for item in participants]
    resolved: list[Any] = []
    for name in token.split(","):
        item = _resolve(participants, names, name)
        if item is None:
            raise DevIntentRefused(f"找不到唯一匹配的分摊人「{name}」。")
        resolved.append(item.ref)
    return resolved


def build_dev_refund_intent(
    cmd: DevRefundCommand,
    references: Sequence[c.BoundReference],
    labels: Mapping[Any, Any],
    *,
    expense_id: Any,
    source_turn_id: Any,
    activity_id: Any,
) -> tuple[c.ExpenseRefundIntent, c.BoundExpenseReference]:
    """Bind a refund to its original; receiver/beneficiary are chosen here."""
    participants = _dev_participants(references, activity_id)
    if not participants:
        raise DevIntentRefused("当前活动没有可用参与人。")
    names = _dev_participant_names(labels)
    if cmd.receiver_name is not None:
        receiver = _resolve(participants, names, cmd.receiver_name)
        if receiver is None:
            raise DevIntentRefused(f"找不到唯一匹配的收款人「{cmd.receiver_name}」。")
    else:
        receiver = participants[0]
    try:
        intent = c.ExpenseRefundIntent(
            kind="expense.refund",
            original_expense_ref=c.ExpenseRef.SELECTED,
            title=f"退款-{cmd.target_title}",
            original_amount=cmd.amount,
            payment_allocations=[
                c.PaymentAllocation(participant_ref=receiver.ref, amount=cmd.amount),
            ],
            split=c.EqualSplitIntent(
                mode="equal",
                participant_refs=_dev_split_refs(cmd.benefit_token, participants, names),
            ),
            occurred_at=None,
        )
    except ValueError as exc:
        raise DevIntentRefused("退款金额或受益人集合不合法。") from exc
    binding = c.BoundExpenseReference(
        kind="expense", ref=c.ExpenseRef.SELECTED, entity_id=expense_id,
        source_turn_id=source_turn_id, scope_activity_id=activity_id,
    )
    return intent, binding


def build_dev_negative_adjustment_intent(
    cmd: DevNegativeAdjustmentCommand,
    references: Sequence[c.BoundReference],
    labels: Mapping[Any, Any],
    base_currency: str | None,
    *,
    activity_id: Any,
) -> c.NegativeAdjustmentIntent:
    """Build the explicit unlinked negative Expense intent."""
    if not base_currency:
        raise DevIntentRefused("当前活动没有可用的基础币种。")
    participants = _dev_participants(references, activity_id)
    units = [
        item for item in references
        if isinstance(item, c.BoundLedgerUnitReference)
        and item.scope_activity_id == activity_id
    ]
    if not participants or not units:
        raise DevIntentRefused("当前活动没有可用参与人或账本单元。")
    names = _dev_participant_names(labels)
    if cmd.payer_name is not None:
        payer = _resolve(participants, names, cmd.payer_name)
        if payer is None:
            raise DevIntentRefused(f"找不到唯一匹配的付款人「{cmd.payer_name}」。")
    else:
        payer = participants[0]
    try:
        return c.NegativeAdjustmentIntent(
            kind="expense.negative_adjustment",
            ledger_unit_ref=units[0].ref,
            title=cmd.title,
            original_amount=cmd.amount,
            original_currency=base_currency,
            payment_allocations=[
                c.PaymentAllocation(participant_ref=payer.ref, amount=cmd.amount),
            ],
            split=c.EqualSplitIntent(
                mode="equal",
                participant_refs=_dev_split_refs(cmd.split_token, participants, names),
            ),
            occurred_at=None,
        )
    except ValueError as exc:
        raise DevIntentRefused("负调整金额或分摊集合不合法。") from exc


@dataclass(frozen=True, slots=True)
class DevActivityCreateCommand:
    name: str
    activity_type: str
    currency: str


@dataclass(frozen=True, slots=True)
class DevActivityJoinCommand:
    join_code: str


@dataclass(frozen=True, slots=True)
class DevParticipantCommand:
    name: str


_ACTIVITY_CREATE = re.compile(
    r"^\s*建活动\s+(?P<name>.+?)\s+(?P<type>普通|大型)\s+(?P<currency>[A-Za-z]{3})\s*$"
)
_ACTIVITY_JOIN = re.compile(r"^\s*加入活动\s+(?P<code>[0-9]{8})\s*$")
_PARTICIPANT_ADD = re.compile(r"^\s*加参与人\s+(?P<name>.+?)\s*$")
_PARTICIPANT_DELETE = re.compile(r"^\s*删参与人\s+(?P<name>.+?)\s*$")


def is_dev_activity_create_command(text: str) -> bool:
    return isinstance(text, str) and text.lstrip().startswith("建活动")


def is_dev_activity_join_command(text: str) -> bool:
    return isinstance(text, str) and text.lstrip().startswith("加入活动")


def is_dev_participant_create_command(text: str) -> bool:
    return isinstance(text, str) and text.lstrip().startswith("加参与人")


def is_dev_participant_delete_command(text: str) -> bool:
    return isinstance(text, str) and text.lstrip().startswith("删参与人")


def parse_dev_activity_create_command(text: str) -> DevActivityCreateCommand | None:
    """Parse `建活动 <名称> <普通|大型> <币种>`."""
    if not isinstance(text, str):
        return None
    match = _ACTIVITY_CREATE.match(text)
    if match is None:
        return None
    name = match.group("name").strip()
    if not name:
        return None
    return DevActivityCreateCommand(
        name=name,
        activity_type="large" if match.group("type") == "大型" else "normal",
        currency=match.group("currency").upper(),
    )


def parse_dev_activity_join_command(text: str) -> DevActivityJoinCommand | None:
    if not isinstance(text, str):
        return None
    match = _ACTIVITY_JOIN.match(text)
    if match is None:
        return None
    return DevActivityJoinCommand(join_code=match.group("code"))


def parse_dev_participant_create_command(text: str) -> DevParticipantCommand | None:
    if not isinstance(text, str):
        return None
    match = _PARTICIPANT_ADD.match(text)
    if match is None:
        return None
    name = match.group("name").strip()
    return DevParticipantCommand(name=name) if name else None


def parse_dev_participant_delete_command(text: str) -> DevParticipantCommand | None:
    if not isinstance(text, str):
        return None
    match = _PARTICIPANT_DELETE.match(text)
    if match is None:
        return None
    name = match.group("name").strip()
    return DevParticipantCommand(name=name) if name else None


def build_dev_activity_create_intent(
    cmd: DevActivityCreateCommand,
) -> c.ActivityCreateIntent:
    try:
        return c.ActivityCreateIntent(
            kind="activity.create",
            name=cmd.name,
            activity_type=cmd.activity_type,
            base_currency=cmd.currency,
            multi_currency_enabled=False,
        )
    except ValueError as exc:
        raise DevIntentRefused("活动名称、类型或币种不合法。") from exc


def build_dev_activity_join_intent(cmd: DevActivityJoinCommand) -> c.ActivityJoinIntent:
    try:
        return c.ActivityJoinIntent(kind="activity.join", join_code=cmd.join_code)
    except ValueError as exc:
        raise DevIntentRefused("加入码必须是 8 位数字。") from exc


def build_dev_participant_create_intent(
    cmd: DevParticipantCommand, activity_id: Any,
) -> c.ParticipantCreateIntent:
    try:
        return c.ParticipantCreateIntent(
            kind="participant.create", activity_id=activity_id, name=cmd.name,
        )
    except ValueError as exc:
        raise DevIntentRefused("参与人名称不合法。") from exc


def build_dev_participant_delete_intent(
    cmd: DevParticipantCommand, activity_id: Any, participant_id: Any,
) -> c.ParticipantDeleteIntent:
    return c.ParticipantDeleteIntent(
        kind="participant.delete",
        activity_id=activity_id,
        participant_id=participant_id,
    )


def is_dev_repayment_command(text: str) -> bool:
    return isinstance(text, str) and text.lstrip().startswith("还款")


def parse_dev_repayment_command(text: str) -> DevRepaymentCommand | None:
    """Parse `还款 <payer> <payee> <amount> <currency> [FIFO|TARGETED]`.

    Participant names are single tokens. A name containing a space is declined
    rather than guessed; the dev bridge is intentionally strict.
    """
    if not isinstance(text, str):
        return None
    stripped = text.lstrip()
    if not stripped.startswith("还款"):
        return None
    parts = stripped[len("还款"):].split()
    if len(parts) not in (4, 5):
        return None
    payer, payee, amount, currency = parts[:4]
    mode = (parts[4] if len(parts) == 5 else "FIFO").upper()
    currency = currency.upper()
    if not payer or not payee or payer == payee:
        return None
    if mode not in ("FIFO", "TARGETED"):
        return None
    if not re.fullmatch(r"[A-Z]{3}", currency):
        return None
    try:
        value = Decimal(amount)
    except (InvalidOperation, TypeError):
        return None
    if not value.is_finite() or value <= 0:
        return None
    return DevRepaymentCommand(
        from_name=payer, to_name=payee, amount=amount,
        currency=currency, mode=mode,
    )


def is_dev_presentation_command(text: str) -> bool:
    if not isinstance(text, str):
        return False
    stripped = text.lstrip()
    return any(stripped.startswith(key) for key in _PRESENTATION_COMMANDS)


def parse_dev_presentation_command(
    text: str, titles: Sequence[str],
) -> DevPresentationCommand | None:
    """Resolve the target title by longest unique prefix.

    The target title may contain spaces, so the split is not "first token".
    A title that matches more than one Expense, or a remainder that matches
    more than one title, declines the bridge.
    """
    if not isinstance(text, str):
        return None
    stripped = text.lstrip()
    command = next(
        (key for key in _PRESENTATION_COMMANDS if stripped.startswith(key)), None,
    )
    if command is None:
        return None
    remainder = stripped[len(command):].strip()
    if not remainder:
        return None
    candidates: list[tuple[str, str]] = []
    for title in sorted(set(titles)):
        if titles.count(title) != 1:
            continue
        if remainder == title:
            return None
        if remainder.startswith(title + " "):
            candidates.append((title, remainder[len(title):].strip()))
    if len(candidates) != 1:
        return None
    target_title, value = candidates[0]
    if not value:
        return None
    return DevPresentationCommand(
        kind=_PRESENTATION_COMMANDS[command],
        target_title=target_title,
        value=value,
    )


def build_dev_presentation_intent(
    cmd: DevPresentationCommand,
    *,
    expense_id: Any,
    source_turn_id: Any,
    activity_id: Any,
) -> tuple[c.ExpensePresentationUpdateIntent, c.BoundExpenseReference]:
    from .p5_write import SUPPORTED_ICON_KEYS

    if cmd.kind == "icon" and cmd.value not in SUPPORTED_ICON_KEYS:
        raise DevIntentRefused("图标不在支持列表：money/dining/shopping/transport/hotel/ticket/fuel/entertainment/medical/gift/grocery/flight。")
    try:
        intent = c.ExpensePresentationUpdateIntent(
            kind="expense.presentation.update",
            expense_ref=c.ExpenseRef.SELECTED,
            title=cmd.value if cmd.kind == "title" else None,
            note=cmd.value if cmd.kind == "note" else None,
            icon_key=cmd.value if cmd.kind == "icon" else None,
        )
    except ValueError as exc:
        raise DevIntentRefused("展示字段不合法。") from exc
    binding = c.BoundExpenseReference(
        kind="expense", ref=c.ExpenseRef.SELECTED, entity_id=expense_id,
        source_turn_id=source_turn_id, scope_activity_id=activity_id,
    )
    return intent, binding



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
