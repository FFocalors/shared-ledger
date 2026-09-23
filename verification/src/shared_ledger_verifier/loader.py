"""Load and validate hand-authored Scenario JSON v1 files."""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any, NoReturn
from uuid import UUID

from .models import (
    ActivitySpec,
    CreateExpense,
    CreatePrepayment,
    FifoRepayment,
    LinkedRefund,
    Operation,
    ReturnPrepayment,
    Scenario,
    TargetedRepayment,
    VoidTransfer,
)


class ScenarioValidationError(ValueError):
    """An input file is not a valid Scenario JSON v1 document."""


_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_MONEY = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_OPERATION_TYPES = {
    "create_expense",
    "targeted_repayment",
    "fifo_repayment",
    "create_prepayment",
    "return_prepayment",
    "linked_refund",
    "void_transfer",
}


def load_scenario(path: str | Path) -> Scenario:
    """Read a JSON file and return a fully validated Scenario.

    All money fields must be JSON strings. JSON fractional numbers are rejected
    at parse time so they can never be rounded through Python ``float``.
    """

    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise ScenarioValidationError(f"cannot read scenario {source}: {exc}") from exc

    try:
        document = json.loads(
            text,
            object_pairs_hook=_unique_object_pairs,
            parse_float=_reject_json_float,
            parse_constant=_reject_json_constant,
        )
    except ScenarioValidationError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise ScenarioValidationError(f"invalid JSON: {exc}") from exc

    return _parse_scenario(document)


def _parse_scenario(document: Any) -> Scenario:
    root = _object(document, "scenario")
    _keys(
        root,
        "scenario",
        required={"schema_version", "scenario_id", "description", "activity", "participants", "operations"},
        optional=set(),
    )

    version = root["schema_version"]
    if type(version) is not int or version != 1:
        _fail("scenario.schema_version", "must be integer 1")

    scenario_id = _identifier(root["scenario_id"], "scenario.scenario_id")
    description = _string(root["description"], "scenario.description", allow_empty=True)
    activity = _parse_activity(root["activity"])
    participants = _parse_participants(root["participants"])
    operations_value = _array(root["operations"], "scenario.operations")
    if not operations_value:
        _fail("scenario.operations", "must contain at least one operation")

    participant_set = set(participants)
    expense_refs: dict[str, tuple[Decimal, str]] = {}
    transfer_refs: set[str] = set()
    voided_transfer_refs: set[str] = set()
    operation_refs: set[str] = set()
    operations: list[Operation] = []

    for index, operation_value in enumerate(operations_value):
        location = f"scenario.operations[{index}]"
        operation = _parse_operation(
            operation_value,
            location,
            participant_set,
            activity.base_currency,
            expense_refs,
            transfer_refs,
            voided_transfer_refs,
            operation_refs,
        )
        operations.append(operation)

    return Scenario(
        schema_version=1,
        scenario_id=scenario_id,
        description=description,
        activity=activity,
        participants=participants,
        operations=tuple(operations),
    )


def _parse_activity(value: Any) -> ActivitySpec:
    location = "scenario.activity"
    activity = _object(value, location)
    _keys(
        activity,
        location,
        required={"type", "base_currency", "multi_currency_enabled"},
        optional=set(),
    )

    activity_type = _string(activity["type"], f"{location}.type")
    if activity_type not in {"normal", "large"}:
        _fail(f"{location}.type", 'must be "normal" or "large"')
    base_currency = _currency(activity["base_currency"], f"{location}.base_currency")
    multi_currency_enabled = activity["multi_currency_enabled"]
    if type(multi_currency_enabled) is not bool:
        _fail(f"{location}.multi_currency_enabled", "must be a boolean")
    return ActivitySpec(activity_type, base_currency, multi_currency_enabled)


def _parse_participants(value: Any) -> tuple[str, ...]:
    values = _array(value, "scenario.participants")
    if not values:
        _fail("scenario.participants", "must contain at least one participant")
    participants: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(values):
        participant = _identifier(raw, f"scenario.participants[{index}]")
        if participant in seen:
            _fail(f"scenario.participants[{index}]", f"duplicate participant ref {participant!r}")
        seen.add(participant)
        participants.append(participant)
    return tuple(participants)


def _parse_operation(
    value: Any,
    location: str,
    participants: set[str],
    base_currency: str,
    expense_refs: dict[str, tuple[Decimal, str]],
    transfer_refs: set[str],
    voided_transfer_refs: set[str],
    operation_refs: set[str],
) -> Operation:
    raw = _object(value, location)
    operation_type = _string(raw.get("type"), f"{location}.type")
    if operation_type not in _OPERATION_TYPES:
        _fail(f"{location}.type", f"unsupported operation type {operation_type!r}")

    if operation_type in {"create_expense", "linked_refund"}:
        return _parse_expense_operation(
            raw,
            location,
            operation_type,
            participants,
            base_currency,
            expense_refs,
            operation_refs,
        )

    if operation_type in {"targeted_repayment", "fifo_repayment"}:
        return _parse_repayment(
            raw,
            location,
            operation_type,
            participants,
            base_currency,
            expense_refs,
            transfer_refs,
            operation_refs,
        )

    if operation_type in {"create_prepayment", "return_prepayment"}:
        return _parse_prepayment(
            raw,
            location,
            operation_type,
            participants,
            base_currency,
            transfer_refs,
            operation_refs,
        )

    return _parse_void_transfer(raw, location, transfer_refs, voided_transfer_refs)


def _parse_expense_operation(
    raw: dict[str, Any],
    location: str,
    operation_type: str,
    participants: set[str],
    base_currency: str,
    expense_refs: dict[str, tuple[Decimal, str]],
    operation_refs: set[str],
) -> CreateExpense | LinkedRefund:
    required = {"type", "ref", "title", "amount", "currency", "payments"}
    if operation_type == "linked_refund":
        required.add("original_expense_ref")
    optional = {"split_method", "splits", "aa_participants"}
    _keys(raw, location, required=required, optional=optional)

    ref = _new_operation_ref(raw["ref"], f"{location}.ref", operation_refs)
    title = _string(raw["title"], f"{location}.title")
    amount = _money(raw["amount"], f"{location}.amount")
    if amount == 0:
        _fail(f"{location}.amount", "must be nonzero")
    currency = _currency(raw["currency"], f"{location}.currency")
    payments = _parse_amount_map(raw["payments"], f"{location}.payments", participants)
    if currency == base_currency:
        _require_scale(amount, 1, f"{location}.amount")
        for participant, payment in payments.items():
            _require_scale(payment, 1, f"{location}.payments.{participant}")
    _assert_amounts_match_total(payments, amount, f"{location}.payments", "payment")

    split_method = raw.get("split_method", "manual" if "splits" in raw else None)
    if split_method not in {"manual", "aa"}:
        _fail(f"{location}.split_method", 'must be "manual" or "aa"')
    if split_method == "manual":
        if "aa_participants" in raw:
            _fail(f"{location}.aa_participants", 'is only allowed when split_method is "aa"')
        if "splits" not in raw:
            _fail(f"{location}.splits", 'is required when split_method is "manual"')
        splits = _parse_amount_map(raw["splits"], f"{location}.splits", participants)
        if currency == base_currency:
            for participant, split in splits.items():
                _require_scale(split, 1, f"{location}.splits.{participant}")
        _assert_amounts_match_total(splits, amount, f"{location}.splits", "split")
        aa_participants: tuple[str, ...] = ()
    else:
        if "splits" in raw:
            _fail(f"{location}.splits", 'is not allowed when split_method is "aa"')
        if "aa_participants" not in raw:
            _fail(f"{location}.aa_participants", 'is required when split_method is "aa"')
        aa_participants = _parse_participant_refs(
            raw["aa_participants"], f"{location}.aa_participants", participants
        )
        splits = None

    original_expense_ref: str | None = None
    if operation_type == "linked_refund":
        original_expense_ref = _identifier(raw["original_expense_ref"], f"{location}.original_expense_ref")
        original = expense_refs.get(original_expense_ref)
        if original is None:
            _fail(f"{location}.original_expense_ref", "must reference an earlier expense")
        original_amount, original_currency = original
        if original_amount <= 0:
            _fail(f"{location}.original_expense_ref", "must reference an earlier positive expense")
        if currency != original_currency:
            _fail(f"{location}.currency", "must match the linked original expense currency")
        if amount >= 0:
            _fail(f"{location}.amount", "linked refund amount must be negative")

    expense_refs[ref] = (amount, currency)
    common = {
        "ref": ref,
        "title": title,
        "amount": amount,
        "currency": currency,
        "payments": MappingProxyType(payments),
        "split_method": split_method,
        "splits": MappingProxyType(splits) if splits is not None else None,
        "aa_participants": aa_participants,
    }
    if operation_type == "linked_refund":
        return LinkedRefund(original_expense_ref=original_expense_ref, **common)
    return CreateExpense(**common)


def _parse_repayment(
    raw: dict[str, Any],
    location: str,
    operation_type: str,
    participants: set[str],
    base_currency: str,
    expense_refs: dict[str, tuple[Decimal, str]],
    transfer_refs: set[str],
    operation_refs: set[str],
) -> TargetedRepayment | FifoRepayment:
    required = {"type", "ref", "from_participant", "to_participant", "amount", "currency"}
    if operation_type == "targeted_repayment":
        required.add("target_expense_refs")
    _keys(raw, location, required=required, optional=set())

    ref = _new_operation_ref(raw["ref"], f"{location}.ref", operation_refs)
    from_participant = _participant_ref(raw["from_participant"], f"{location}.from_participant", participants)
    to_participant = _participant_ref(raw["to_participant"], f"{location}.to_participant", participants)
    if from_participant == to_participant:
        _fail(location, "repayment participants must be different")
    amount = _positive_money(raw["amount"], f"{location}.amount")
    currency = _currency(raw["currency"], f"{location}.currency")
    if currency == base_currency:
        _require_scale(amount, 1, f"{location}.amount")
    transfer_refs.add(ref)

    if operation_type == "targeted_repayment":
        target_refs = _parse_reference_list(
            raw["target_expense_refs"], f"{location}.target_expense_refs", expense_refs
        )
        for index, target_ref in enumerate(target_refs):
            _, target_currency = expense_refs[target_ref]
            if target_currency != currency:
                _fail(
                    f"{location}.target_expense_refs[{index}]",
                    "target expense currency must match repayment currency",
                )
        return TargetedRepayment(ref, from_participant, to_participant, amount, currency, target_refs)
    return FifoRepayment(ref, from_participant, to_participant, amount, currency)


def _parse_prepayment(
    raw: dict[str, Any],
    location: str,
    operation_type: str,
    participants: set[str],
    base_currency: str,
    transfer_refs: set[str],
    operation_refs: set[str],
) -> CreatePrepayment | ReturnPrepayment:
    _keys(
        raw,
        location,
        required={"type", "ref", "owner_participant", "custodian_participant", "amount", "currency"},
        optional=set(),
    )
    ref = _new_operation_ref(raw["ref"], f"{location}.ref", operation_refs)
    owner = _participant_ref(raw["owner_participant"], f"{location}.owner_participant", participants)
    custodian = _participant_ref(
        raw["custodian_participant"], f"{location}.custodian_participant", participants
    )
    if owner == custodian:
        _fail(location, "owner and custodian must be different participants")
    amount = _positive_money(raw["amount"], f"{location}.amount")
    currency = _currency(raw["currency"], f"{location}.currency")
    if currency == base_currency:
        _require_scale(amount, 1, f"{location}.amount")
    transfer_refs.add(ref)
    if operation_type == "create_prepayment":
        return CreatePrepayment(ref, owner, custodian, amount, currency)
    return ReturnPrepayment(ref, owner, custodian, amount, currency)


def _parse_void_transfer(
    raw: dict[str, Any],
    location: str,
    transfer_refs: set[str],
    voided_transfer_refs: set[str],
) -> VoidTransfer:
    _keys(raw, location, required={"type", "transfer_ref", "reason"}, optional=set())
    transfer_ref = _identifier(raw["transfer_ref"], f"{location}.transfer_ref")
    if transfer_ref not in transfer_refs:
        _fail(f"{location}.transfer_ref", "must reference an earlier transfer-producing operation")
    if transfer_ref in voided_transfer_refs:
        _fail(f"{location}.transfer_ref", "transfer has already been voided in this scenario")
    reason = _string(raw["reason"], f"{location}.reason")
    voided_transfer_refs.add(transfer_ref)
    return VoidTransfer(transfer_ref, reason)


def _parse_amount_map(value: Any, location: str, participants: set[str]) -> dict[str, Decimal]:
    raw = _object(value, location)
    if not raw:
        _fail(location, "must contain at least one participant amount")
    amounts: dict[str, Decimal] = {}
    for participant, amount_value in raw.items():
        participant_ref = _participant_ref(participant, f"{location} key", participants)
        amount = _money(amount_value, f"{location}.{participant_ref}")
        if amount == 0:
            _fail(f"{location}.{participant_ref}", "must be nonzero")
        amounts[participant_ref] = amount
    return amounts


def _assert_amounts_match_total(
    values: dict[str, Decimal], total: Decimal, location: str, label: str
) -> None:
    for participant, value in values.items():
        if (value > 0) != (total > 0):
            _fail(f"{location}.{participant}", f"{label} sign must match expense amount")
    if sum(values.values(), Decimal(0)) != total:
        _fail(location, f"{label} amounts must sum exactly to expense amount")


def _parse_participant_refs(value: Any, location: str, participants: set[str]) -> tuple[str, ...]:
    values = _array(value, location)
    if not values:
        _fail(location, "must contain at least one participant ref")
    result: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(values):
        participant = _participant_ref(raw, f"{location}[{index}]", participants)
        if participant in seen:
            _fail(f"{location}[{index}]", f"duplicate participant ref {participant!r}")
        seen.add(participant)
        result.append(participant)
    return tuple(result)


def _parse_reference_list(
    value: Any, location: str, references: dict[str, tuple[Decimal, str]]
) -> tuple[str, ...]:
    values = _array(value, location)
    if not values:
        _fail(location, "must contain at least one expense ref")
    result: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(values):
        reference = _identifier(raw, f"{location}[{index}]")
        if reference in seen:
            _fail(f"{location}[{index}]", f"duplicate expense ref {reference!r}")
        if reference not in references:
            _fail(f"{location}[{index}]", "must reference an earlier expense")
        seen.add(reference)
        result.append(reference)
    return tuple(result)


def _positive_money(value: Any, location: str) -> Decimal:
    amount = _money(value, location)
    if amount <= 0:
        _fail(location, "must be greater than zero")
    return amount


def _require_scale(amount: Decimal, maximum: int, location: str) -> None:
    scale = max(0, -amount.as_tuple().exponent)
    if scale > maximum:
        _fail(location, f"supports at most {maximum} fractional digit(s) in the base currency")


def _money(value: Any, location: str) -> Decimal:
    if not isinstance(value, str) or not _MONEY.fullmatch(value):
        _fail(location, "must be a decimal string (for example, \"100.0\")")
    try:
        amount = Decimal(value)
    except InvalidOperation:
        _fail(location, "is not a valid decimal amount")
    if not amount.is_finite():
        _fail(location, "must be finite")
    scale = max(0, -amount.as_tuple().exponent)
    if scale > 4:
        _fail(location, "supports at most 4 fractional digits")
    return amount


def _currency(value: Any, location: str) -> str:
    currency = _string(value, location)
    if not _CURRENCY.fullmatch(currency):
        _fail(location, "must be a three-letter uppercase currency code")
    return currency


def _participant_ref(value: Any, location: str, participants: set[str]) -> str:
    reference = _identifier(value, location)
    if reference not in participants:
        _fail(location, f"unknown participant ref {reference!r}")
    return reference


def _new_operation_ref(value: Any, location: str, seen: set[str]) -> str:
    reference = _identifier(value, location)
    if reference in seen:
        _fail(location, f"duplicate operation ref {reference!r}")
    seen.add(reference)
    return reference


def _identifier(value: Any, location: str) -> str:
    identifier = _string(value, location)
    if not _IDENTIFIER.fullmatch(identifier):
        _fail(location, "must be a short ref using letters, numbers, underscores, or hyphens")
    try:
        UUID(identifier)
    except ValueError:
        return identifier
    _fail(location, "must be a business ref, not a UUID")


def _string(value: Any, location: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        _fail(location, "must be a string")
    if not allow_empty and not value.strip():
        _fail(location, "must not be empty")
    return value


def _object(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(location, "must be a JSON object")
    return value


def _array(value: Any, location: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(location, "must be a JSON array")
    return value


def _keys(
    value: dict[str, Any],
    location: str,
    *,
    required: set[str],
    optional: set[str],
) -> None:
    missing = required - value.keys()
    if missing:
        _fail(location, f"missing required field(s): {', '.join(sorted(missing))}")
    unexpected = value.keys() - required - optional
    if unexpected:
        _fail(location, f"unknown field(s): {', '.join(sorted(unexpected))}")


def _unique_object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ScenarioValidationError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _reject_json_float(value: str) -> NoReturn:
    raise ScenarioValidationError(
        f"JSON fractional number {value!r} is not allowed; encode money as a decimal string"
    )


def _reject_json_constant(value: str) -> NoReturn:
    raise ScenarioValidationError(f"non-standard JSON number {value!r} is not allowed")


def _fail(location: str, message: str) -> NoReturn:
    raise ScenarioValidationError(f"{location}: {message}")
