"""Independent operation-state and request-derived gold checks for release v2.

Gold is parsed from user-authored request text and model-visible read facts.  The
scenario is treated as redundant metadata; it never supplies the expected answer.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from .signatures import operation_state_signature, sha256


class GoldGuardError(ValueError):
    pass


OPS = {
    "read.activities",
    "read.expenses",
    "read.debts",
    "expense.create",
    "expense.update",
    "expense.presentation.update",
}

_PERMISSION = {
    "read.activities": "read.activities",
    "read.expenses": "read.expenses",
    "read.debts": "read.debts",
    "expense.create": "propose.expense.create",
    "expense.update": "propose.expense.update",
    "expense.presentation.update": "propose.expense.presentation.update",
}
_WRITE_OPS = {"expense.create", "expense.update", "expense.presentation.update"}
_POSITIVE_CASE_TYPES = {"supported_operation", "grounded_answer", "clarification", "multi_turn"}
_BOUNDARY_CASE_TYPES = {
    "locked_financial_update", "ordinary_prepayment", "permission_denial", "prompt_injection",
}
_DECIMAL = re.compile(r"^(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,4})?$")
_REF = r"(?:activity|ledger_unit|expense|participant)_(?:selected|[0-9]{1,2})"
_EXPENSE_REF = r"expense_(?:selected|[0-9]{1,2})"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _decimal(value: Any, *, positive: bool = False, nonzero: bool = False) -> Decimal:
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
        raise GoldGuardError("amount must be a bounded decimal string with at most four fractional digits")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise GoldGuardError("amount is not a decimal string") from exc
    if not amount.is_finite() or (positive and amount <= 0) or (nonzero and amount == 0):
        raise GoldGuardError("amount is outside the permitted nonzero range")
    return amount


def _money(value: str) -> Decimal:
    return _decimal(value, positive=True)


def _parse_allocation_text(value: str, label: str) -> list[dict[str, str]]:
    if not value:
        raise GoldGuardError(f"{label} request list is empty")
    rows: list[dict[str, str]] = []
    for item in value.split(","):
        match = re.fullmatch(rf"({_REF})=({_DECIMAL.pattern[1:-1]})", item)
        if not match:
            raise GoldGuardError(f"{label} request list is malformed")
        rows.append({"participant_ref": match.group(1), "amount": match.group(2)})
    _allocation_map(rows, label)
    return rows


def _parse_reference_text(value: str, label: str) -> list[str]:
    refs = value.split(",") if value else []
    if not refs or any(not re.fullmatch(r"participant_(?:selected|[0-9]{1,2})", ref) for ref in refs):
        raise GoldGuardError(f"{label} request list is malformed")
    if len(refs) != len(set(refs)):
        raise GoldGuardError(f"{label} request list repeats a participant")
    return refs


def _allocation_map(rows: Any, label: str) -> dict[str, Decimal]:
    if not isinstance(rows, list) or not rows:
        raise GoldGuardError(f"{label} allocations must be nonempty")
    result: dict[str, Decimal] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"participant_ref", "amount"}:
            raise GoldGuardError(f"{label} allocation has an invalid shape")
        ref = row["participant_ref"]
        if not isinstance(ref, str) or not re.fullmatch(r"participant_(?:selected|[0-9]{1,2})", ref):
            raise GoldGuardError(f"{label} allocation has an invalid participant reference")
        if ref in result:
            raise GoldGuardError(f"{label} allocations repeat a participant")
        result[ref] = _money(row["amount"])
    return result


def _sum_allocations(rows: list[dict[str, Any]]) -> Decimal:
    return sum(_allocation_map(rows, "allocation").values(), Decimal("0"))


def _same_allocations(left: Any, right: Any, label: str) -> bool:
    return _allocation_map(left, label) == _allocation_map(right, label)


def _equal_allocations(amount: Decimal, refs: list[str]) -> list[dict[str, str]]:
    if not refs or len(refs) != len(set(refs)):
        raise GoldGuardError("equal split requires unique participants")
    # Expense original-currency allocations retain four decimal places.  This
    # evenly shares the smallest representable units while keeping conservation.
    units_decimal = amount * Decimal("10000")
    if units_decimal != units_decimal.to_integral_value():
        raise GoldGuardError("equal split amount exceeds the supported four-decimal precision")
    units = int(units_decimal)
    base, remainder = divmod(units, len(refs))
    if base <= 0:
        raise GoldGuardError("equal split must give every participant a positive allocation")
    result = []
    for index, ref in enumerate(refs):
        share = base + (1 if index < remainder else 0)
        result.append({"participant_ref": ref, "amount": f"{Decimal(share) / Decimal(10000):.4f}"})
    return result


def _split_allocations(split: Any, amount: Decimal, label: str) -> tuple[list[str], list[dict[str, str]]]:
    if not isinstance(split, dict) or split.get("mode") not in {"equal", "manual"}:
        raise GoldGuardError(f"{label} split mode is unsupported")
    if split["mode"] == "manual":
        rows = split.get("allocations")
        amounts = _allocation_map(rows, f"{label} split")
        if sum(amounts.values(), Decimal("0")) != amount:
            raise GoldGuardError(f"{label} manual split does not conserve the expense amount")
        return list(amounts), rows
    refs = split.get("participant_refs")
    if not isinstance(refs, list) or not refs or len(refs) != len(set(refs)):
        raise GoldGuardError(f"{label} equal split requires unique participants")
    rows = _equal_allocations(amount, refs)
    if _sum_allocations(rows) != amount:
        raise GoldGuardError(f"{label} equal split does not conserve the expense amount")
    return refs, rows


def _model_steps(record: dict[str, Any]) -> list[dict[str, Any]]:
    steps = [step for step in record.get("trace", []) if step.get("kind") == "model"]
    if not steps:
        raise GoldGuardError("record has no model step")
    return steps


def _context_refs(context: dict[str, Any]) -> dict[str, set[str]]:
    result = {"activity": set(), "ledger_unit": set(), "expense": set(), "participant": set()}
    for item in context.get("bound_references", []):
        kind, ref = item.get("kind"), item.get("ref")
        if kind in result and isinstance(ref, str):
            result[kind].add(ref)
    return result


def _current_activity(state: dict[str, Any]) -> dict[str, Any]:
    current = [row for row in state.get("activities", []) if row.get("role") == "current"]
    if len(current) != 1:
        raise GoldGuardError("operation state must have exactly one current activity anchor")
    return current[0]


def _operation_state_eligible(state: dict[str, Any], operation: str) -> None:
    current = _current_activity(state)
    if not current.get("visible", False) or current.get("status") == "deleted":
        raise GoldGuardError("current activity is not visible to the authenticated actor")
    if operation in _WRITE_OPS and current.get("status") != "active":
        raise GoldGuardError("archived or deleted activities are read-only")
    required = _PERMISSION[operation]
    permissions = set(current.get("permissions", []))
    if required not in permissions:
        raise GoldGuardError(f"operation state does not grant {required}")

    participant_rows = state.get("participants", [])
    participants = {row.get("ref"): row for row in participant_rows if isinstance(row, dict)}
    member_refs = current.get("member_allowlist", [])
    if not member_refs or len(member_refs) != len(set(member_refs)):
        raise GoldGuardError("current activity member scope is empty or duplicated")
    if any(ref not in participants or not participants[ref].get("active") for ref in member_refs):
        raise GoldGuardError("current activity member scope contains an inactive or unknown participant")
    # ActivityMember is a User-level grant.  ParticipantClaim is independent,
    # so there may be zero Participant rows with role=current_user.
    actor = state.get("actor")
    if not isinstance(actor, dict) or (
        actor.get("authenticated") is not True
        or actor.get("activity_member") is not True
        or actor.get("activity_member_active") is not True
        or actor.get("activity_ref") != current.get("ref")
        or set(actor.get("permissions", [])) != set(current.get("permissions", []))
        or required not in actor.get("permissions", [])
    ):
        raise GoldGuardError("actor is not an authenticated current-activity member with this permission")

    if operation in {"expense.create", "expense.update"}:
        unit = state.get("ledger_unit", {})
        if not unit.get("active"):
            raise GoldGuardError("financial write requires an active ledger unit")
        if unit.get("activity_ref") != current.get("ref"):
            raise GoldGuardError("ledger unit does not belong to the current activity")
        allowed = unit.get("participant_allowlist", [])
        if not allowed or len(allowed) != len(set(allowed)):
            raise GoldGuardError("ledger-unit member scope is empty or duplicated")
        if any(ref not in participants or not participants[ref].get("active") for ref in allowed):
            raise GoldGuardError("ledger-unit scope contains an inactive or unknown participant")
        if not set(allowed).issubset(set(member_refs)):
            raise GoldGuardError("ledger-unit participant is outside its parent activity")
        role = unit.get("role")
        parent_ref = unit.get("parent_ref")
        parent_role = unit.get("parent_role")
        if role in {"normal_root", "large_root"}:
            expected_kind = "normal" if role == "normal_root" else "large"
            if current.get("kind") != expected_kind:
                raise GoldGuardError("root ledger-unit role does not match the current activity kind")
            if parent_ref is not None or parent_role is not None or unit.get("parent_active") is not True:
                raise GoldGuardError("root ledger unit has an invalid parent binding")
            if set(allowed) != set(member_refs):
                raise GoldGuardError("root unit must use the full current activity member scope")
        elif role == "large_child":
            if current.get("kind") != "large":
                raise GoldGuardError("a child ledger unit requires a large activity")
            if (not re.fullmatch(r"ledger_unit_(?:selected|[0-9]{1,2})", str(parent_ref))
                    or parent_role != "large_root" or unit.get("parent_active") is not True):
                raise GoldGuardError("large child ledger unit must have an active large-root parent")
        elif role == "legacy_unscoped":
            # Pre-migration large child activities have a parent binding but
            # retain the historical whole-activity participant scope.
            if current.get("kind") != "large":
                raise GoldGuardError("legacy unscoped unit must belong to a large activity")
            if (not re.fullmatch(r"ledger_unit_(?:selected|[0-9]{1,2})", str(parent_ref))
                    or parent_role != "large_root" or unit.get("parent_active") is not True):
                raise GoldGuardError("legacy unit must have an active large-root parent")
            if set(allowed) != set(member_refs):
                raise GoldGuardError("legacy unscoped unit must use the full activity member scope")
        else:
            raise GoldGuardError("ledger-unit role is missing or unsupported")


def _state_fixture_projection(record: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    state = record["operation_state"]
    activities_by_ref = {row["ref"]: row for row in state.get("activities", [])}
    expected_activities = [{
        "activity_ref": row["ref"], "name": row["name"], "activity_kind": row["kind"],
        "base_currency": row["base_currency"], "status": row["status"],
    } for row in state.get("activities", [])
        if row.get("visible") and row.get("status") in {"active", "archived"}
        and row.get("status") in state.get("visible_statuses", [])]

    expected_expenses = []
    for row in state.get("expenses", []):
        activity = activities_by_ref.get(row.get("activity_ref"))
        if not activity or not activity.get("visible") or activity.get("status") not in {"active", "archived"}:
            continue
        expected_expenses.append({
            "activity_ref": row["activity_ref"], "expense_ref": row["ref"], "title": row["title"],
            "original_amount": row["amount"], "original_currency": row["currency"],
            "occurred_at": row["occurred_at"], "participant_refs": row["participant_refs"],
            "financial_locked": row["locked"], "expense_version": row.get("expense_version"),
        })

    expected_debts = []
    for row in state.get("debts", []):
        activity = activities_by_ref.get(row.get("activity_ref"))
        if not activity or not activity.get("visible") or activity.get("status") not in {"active", "archived"}:
            continue
        expected_debts.append({
            "activity_ref": row["activity_ref"], "debtor_ref": row["debtor_ref"],
            "creditor_ref": row["creditor_ref"], "amount": row["amount"], "currency": row["currency"],
        })
    return {"activities": expected_activities, "expenses": expected_expenses, "debts": expected_debts}


def _validate_state_fixture_binding(record: dict[str, Any]) -> None:
    state, fixture = record["operation_state"], record["fixture_state"]
    projection = _state_fixture_projection(record)
    for key in ("activities", "expenses", "debts"):
        if fixture.get(key) != projection[key]:
            raise GoldGuardError(f"fixture {key} differ from the accessible operation-state facts")

    activities = {row["ref"]: row for row in state["activities"]}
    people = {row["ref"]: row for row in state["participants"]}
    for row in state.get("expenses", []):
        if row["activity_ref"] not in activities:
            raise GoldGuardError("expense snapshot has an unknown activity")
        activity = activities[row["activity_ref"]]
        members = set(activity.get("member_allowlist", []))
        refs = row.get("participant_refs", [])
        if not refs or len(refs) != len(set(refs)) or not set(refs).issubset(members):
            raise GoldGuardError("expense snapshot participant scope is invalid")
        if any(ref not in people or not people[ref].get("active") for ref in refs):
            raise GoldGuardError("expense snapshot uses an inactive or unknown participant")
        amount = _money(row["amount"])
        for group in ("payments", "splits"):
            amounts = _allocation_map(row.get(group), f"snapshot {group}")
            if not set(amounts).issubset(members) or sum(amounts.values(), Decimal("0")) != amount:
                raise GoldGuardError(f"snapshot {group} do not conserve the visible expense amount")

    for row in state.get("debts", []):
        if row["debtor_ref"] == row["creditor_ref"]:
            raise GoldGuardError("debt snapshot cannot owe a participant to themself")
        if row["debtor_ref"] not in people or row["creditor_ref"] not in people:
            raise GoldGuardError("debt snapshot refers to an unknown participant")
        if not people[row["debtor_ref"]].get("active") or not people[row["creditor_ref"]].get("active"):
            raise GoldGuardError("debt snapshot refers to an inactive participant")
        if row["debtor_ref"] not in activities[row["activity_ref"]].get("member_allowlist", []) \
                or row["creditor_ref"] not in activities[row["activity_ref"]].get("member_allowlist", []):
            raise GoldGuardError("debt snapshot crosses its activity participant scope")
        _money(row["amount"])

    if record.get("fixture_state_sha256") != sha256(fixture):
        raise GoldGuardError("fixture-state signature mismatch")


def _user_texts(context: dict[str, Any]) -> list[str]:
    texts = []
    input_text = context.get("input_text")
    if isinstance(input_text, str) and input_text:
        texts.append(input_text)
    texts.extend(
        item["text"] for item in context.get("recent_messages", [])
        if isinstance(item, dict) and item.get("role") == "user" and isinstance(item.get("text"), str)
    )
    if not texts:
        raise GoldGuardError("model context contains no user-authored request text")
    return texts


def _matches(pattern: str, texts: list[str], label: str, *, group: int | tuple[int, ...] = 1) -> list[Any]:
    found: list[Any] = []
    for text in texts:
        for match in re.finditer(pattern, text, flags=re.DOTALL):
            found.append(match.group(group) if isinstance(group, int) else tuple(match.group(i) for i in group))
    return found


def _one(pattern: str, texts: list[str], label: str, *, required: bool = True,
         group: int | tuple[int, ...] = 1) -> Any:
    found = _matches(pattern, texts, label, group=group)
    distinct = {_json(value) for value in found}
    if not distinct:
        if required:
            raise GoldGuardError(f"user request does not state {label}")
        return None
    if len(distinct) != 1:
        raise GoldGuardError(f"user request contains conflicting values for {label}")
    return found[0]


def _quoted(texts: list[str], pattern: str, label: str, *, required: bool = True) -> str | None:
    value = _one(pattern, texts, label, required=required)
    return value


def _parse_split(text: str) -> tuple[dict[str, Any], str]:
    match = re.fullmatch(r"(equal|manual):([^\]]*)", text)
    if not match:
        raise GoldGuardError("user request split is malformed")
    mode, value = match.groups()
    if mode == "equal":
        refs = _parse_reference_text(value, "equal split")
        return {"mode": "equal", "participant_refs": refs}, f"分摊[equal:{value}]"
    rows = _parse_allocation_text(value, "manual split")
    return {"mode": "manual", "allocations": rows}, f"分摊[manual:{value}]"


def _parse_request(operation: str, context: dict[str, Any]) -> dict[str, Any]:
    texts = _user_texts(context)
    joined = "\n".join(texts)
    if operation == "read.activities":
        status = _one(r"(?:^|[；;，,\s])status=([a-z]+)", texts, "activity status")
        if status not in {"active", "archived", "any"}:
            raise GoldGuardError("user request activity status is unsupported")
        name = _one(r"name_contains=([^；;，,。\s]+)", texts, "activity name filter")
        name_filter = None if name == "无" else name
        return {"criteria": {"kind": "activities", "status": status, "name_contains": name_filter},
                "metadata": {"status": status, "name_contains": name}}

    if operation == "read.expenses":
        activity = _one(rf"读取活动ref=({_REF})(?:的费用|账下费用)", texts, "expense-read activity")
        date_ranges = _matches(
            r"日期从([0-9]{4}-[0-9]{2}-[0-9]{2})到([0-9]{4}-[0-9]{2}-[0-9]{2})",
            texts, "expense-read date range", group=(1, 2),
        )
        if len({_json(item) for item in date_ranges}) > 1:
            raise GoldGuardError("user request contains conflicting expense-read date ranges")
        start, end = date_ranges[0] if date_ranges else (None, None)
        if start is not None and _one(
            r"全部日期", texts, "all-date marker", required=False, group=0,
        ) is not None:
            raise GoldGuardError("expense-read request conflicts between a date range and all dates")
        if start is None and _one(
            r"日期从|日期范围", texts, "partial date filter", required=False, group=0,
        ) is not None:
            raise GoldGuardError("expense-read date range is incomplete")
        participant = _one(
            r"participant_ref=(participant_(?:selected|[0-9]{1,2})|全部参与人)",
            texts, "expense-read participant", required=False,
        )
        all_participants = _one(
            r"全部参与人", texts, "all-participants marker", required=False, group=0,
        )
        if participant == "全部参与人":
            participant = None
        elif participant is None:
            participant = None
        elif all_participants is not None:
            raise GoldGuardError("expense-read request conflicts between a member and all participants")
        title_contains = _one(
            r"title_contains=([^；;，,。\s]+)", texts, "expense title post-filter", required=False,
        )
        if title_contains is not None and not title_contains.strip():
            raise GoldGuardError("expense title post-filter cannot be empty")
        metadata: dict[str, Any] = {}
        if start is not None:
            metadata.update({"from_date": start, "to_date": end})
        elif _one(r"全部日期", texts, "all-date marker", required=False, group=0) is not None:
            metadata["date_scope"] = "all"
        if participant is not None:
            metadata["participant_ref"] = participant
        elif all_participants is not None:
            metadata["participant_scope"] = "all"
        if title_contains is not None:
            metadata["title_contains"] = title_contains
        return {
            "criteria": {"kind": "expenses", "activity_ref": activity, "from_date": start,
                         "to_date": end, "participant_ref": participant},
            "metadata": metadata,
            "post_filter": {"title_contains": title_contains},
        }

    if operation == "read.debts":
        activity = _one(rf"读取活动ref=({_REF})的债务", texts, "debt-read activity")
        currency_text = _one(r"currency=([A-Z]{3}|全部币种)", texts, "debt-read currency")
        participant_text = _one(rf"participant_ref=({_REF}|全部成员)", texts, "debt-read participant")
        return {
            "criteria": {"kind": "debts", "activity_ref": activity,
                         "participant_ref": None if participant_text == "全部成员" else participant_text,
                         "currency": None if currency_text == "全部币种" else currency_text},
            "metadata": {"currency": currency_text, "participant_ref": participant_text},
        }

    if operation == "expense.create":
        title = _quoted(texts, r"新增费用标题[“\"]([^”\"]+)[”\"]", "create title")
        ledger_unit = _one(rf"ledger_unit_ref=({_REF})", texts, "create ledger unit")
        split_text = _one(r"分摊\[(equal|manual):([^\]\r\n]*)\]", texts, "create split", group=(1, 2))
        amount_matches = _matches(
            r"金额(?:补充为)?\s*([0-9]+(?:\.[0-9]{1,4})?)\s+([A-Z]{3})",
            texts, "create amount and currency", group=(1, 2),
        )
        if len({_json(item) for item in amount_matches}) > 1:
            raise GoldGuardError("create request contains conflicting amount or currency values")
        missing_total = _one(
            r"总金额待确认，请勿根据付款人与分摊推定总金额", texts,
            "missing-total clarification marker", group=0, required=False,
        ) is not None
        if missing_total:
            users = [item["text"] for item in context.get("recent_messages", [])
                     if isinstance(item, dict) and item.get("role") == "user"
                     and isinstance(item.get("text"), str)]
            initial = users[0] if users else texts[0]
            if re.search(r"金额(?:补充为)?\s*[0-9]+(?:\.[0-9]{1,4})?\s+[A-Z]{3}", initial):
                raise GoldGuardError("missing-total create request disclosed an amount in its initial turn")
            followup_texts = [item.get("text") for item in context.get("recent_messages", [])
                              if isinstance(item, dict) and item.get("role") == "user"
                              and re.fullmatch(
                                  r"\s*金额补充为[0-9]+(?:\.[0-9]{1,4})?\s+[A-Z]{3}[。.!！]?\s*",
                                  item.get("text", "") if isinstance(item.get("text"), str) else "",
                              )]
            if len(followup_texts) != 1 or not re.fullmatch(
                r"\s*金额补充为[0-9]+(?:\.[0-9]{1,4})?\s+[A-Z]{3}[。.!！]?\s*",
                followup_texts[0] if isinstance(followup_texts[0], str) else "",
            ):
                raise GoldGuardError("missing-total create requires one exact amount follow-up")
            unique_amounts = {_json(item): item for item in amount_matches}
            if len(unique_amounts) != 1:
                raise GoldGuardError("missing-total create follow-up must provide exactly one amount")
            amount, currency = next(iter(unique_amounts.values()))
            payer_text = _one(r"付款人\[([^\]\r\n]*)\]", texts, "single create payer")
            payer_refs = _parse_reference_text(payer_text, "create payer")
            if len(payer_refs) != 1:
                raise GoldGuardError("missing-total create requires exactly one explicitly named payer")
            if split_text[0] != "equal":
                raise GoldGuardError("missing-total clarification supports an explicit equal split only")
            split, rendered_split = _parse_split(f"{split_text[0]}:{split_text[1]}")
            metadata = {
                "title": title, "amount": amount, "currency": currency,
                "ledger_unit_ref": ledger_unit,
                "payment_allocations": f"付款[{payer_refs[0]}={amount}]",
                "split": rendered_split,
            }
            expected = {"kind": operation, "ledger_unit_ref": ledger_unit, "title": title,
                        "original_amount": amount, "original_currency": currency,
                        "payment_payer_refs": payer_refs, "split": split}
            return {"fields": expected, "metadata": metadata,
                    "interaction": "clarify_only_missing_amount_then_continue"}
        if not amount_matches:
            raise GoldGuardError("create request does not state an amount")
        amount, currency = amount_matches[0]
        payment_text = _one(r"付款\[([^\]\r\n]*)\]", texts, "create payment allocations")
        occurred = _one(
            r"(?:发生于|日期[=:：])([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.+-]+Z?)",
            texts, "create occurrence time", required=False,
        )
        payments = _parse_allocation_text(payment_text, "payment")
        split, rendered_split = _parse_split(":".join(split_text))
        expected = {"kind": operation, "ledger_unit_ref": ledger_unit, "title": title,
                    "original_amount": amount, "original_currency": currency,
                    "payment_allocations": payments, "split": split}
        if occurred is not None:
            expected["occurred_at"] = occurred
        metadata = {"title": title, "amount": amount, "currency": currency, "ledger_unit_ref": ledger_unit,
                    "payment_allocations": f"付款[{payment_text}]", "split": rendered_split}
        return {"fields": expected, "metadata": metadata}

    if operation == "expense.update":
        expense_ref = _one(rf"更正费用ref=({_REF})", texts, "update expense reference")
        amount_text = _one(r"新额\s*([0-9]+(?:\.[0-9]{1,4})?)(?:\s+([A-Z]{3}))?", texts,
                           "new expense amount", required=False, group=(1, 2))
        currency = _one(r"新币种[=:]([A-Z]{3})", texts, "new expense currency", required=False)
        if amount_text:
            amount_text, amount_currency = amount_text
            currency = amount_currency or currency
        else:
            amount_text = None
        payment_text = _one(r"付款\[([^\]\r\n]*)\]", texts, "updated payment allocations", required=False)
        split_text = _one(r"分摊\[(equal|manual):([^\]\r\n]*)\]", texts,
                          "updated split", required=False, group=(1, 2))
        title = _quoted(texts, r"(?:修改)?标题[“\"]([^”\"]+)[”\"]", "updated title", required=False)
        note = _quoted(texts, r"(?:修改)?备注[“\"]([^”\"]*)[”\"]", "updated note", required=False)
        occurred = _one(r"发生于([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.+-]+Z?)", texts,
                        "updated occurrence time", required=False)
        expected: dict[str, Any] = {"kind": operation, "expense_ref": expense_ref}
        metadata: dict[str, Any] = {"expense_ref": expense_ref}
        if amount_text is not None:
            expected["original_amount"] = amount_text
            metadata["original_amount"] = amount_text
        if currency is not None:
            expected["original_currency"] = currency
            metadata["original_currency"] = currency
        if payment_text is not None:
            payments = _parse_allocation_text(payment_text, "updated payment")
            expected["payment_allocations"] = payments
            metadata["payment_allocations"] = f"付款[{payment_text}]"
        if split_text is not None:
            split, rendered_split = _parse_split(":".join(split_text))
            expected["split"] = split
            metadata["split"] = rendered_split
        for key, value in (("title", title), ("note", note), ("occurred_at", occurred)):
            if value is not None:
                expected[key] = value
                metadata[key] = value
        return {"fields": expected, "metadata": metadata}

    if operation == "expense.presentation.update":
        # Direct references support one-turn work.  Ambiguous multi-turn work
        # obtains its explicit expense_ref in a user follow-up.  The query title
        # and requested display fields always come from user-authored text.
        query_title = _quoted(
            texts, r"(?:把)?标题为[“\"]([^”\"]+)[”\"](?:的那笔)?费用", "presentation query title",
            required=False,
        )
        ref_pattern = rf"(?:已锁定费用ref|展示费用ref|expense_ref)=({_EXPENSE_REF})"
        ref_followup_pattern = rf"\s*expense_ref=({_EXPENSE_REF})\s*[。.!！]?\s*"
        followup_texts = [text for text in texts if re.fullmatch(ref_followup_pattern, text)]
        initial_texts = [text for text in texts if not re.fullmatch(ref_followup_pattern, text)]
        initial_expense_ref = _one(
            ref_pattern, initial_texts, "presentation expense reference", required=False,
        )
        followup_expense_ref = _one(
            rf"expense_ref=({_EXPENSE_REF})", followup_texts, "presentation expense follow-up reference",
            required=False,
        )
        if initial_expense_ref is not None and followup_expense_ref is not None:
            raise GoldGuardError("presentation request cannot both specify an expense and ask for a follow-up selection")
        title = _quoted(
            texts, r"(?:展示改为title=|title=|标题[=:：]?)[“\"]([^”\"]+)[”\"]",
            "presentation title", required=False,
        )
        note = _quoted(texts, r"(?:note=|备注[=：:])[“\"]([^”\"]*)[”\"]", "presentation note", required=False)
        icon = _one(r"icon_key=([a-z0-9_]+)", texts, "presentation icon", required=False)
        expected = {"kind": operation}
        metadata: dict[str, Any] = {}
        if query_title is not None:
            metadata["query_title"] = query_title
        if initial_expense_ref is not None:
            metadata["expense_ref"] = initial_expense_ref
        expense_ref = initial_expense_ref or followup_expense_ref
        if expense_ref is not None:
            expected["expense_ref"] = expense_ref
        for key, value in (("title", title), ("note", note), ("icon_key", icon)):
            if value is not None:
                expected[key] = value
                metadata[key] = value
        return {"fields": expected, "metadata": metadata,
                "selection": {"initial_expense_ref": initial_expense_ref,
                              "followup_expense_ref": followup_expense_ref}}

    raise GoldGuardError(f"no request parser for operation {operation}")


def _validate_scenario_request(scenario: dict[str, Any], parsed: dict[str, Any], operation: str) -> None:
    if scenario.get("operation") != operation:
        raise GoldGuardError("scenario operation differs from the task operation")
    metadata = scenario.get("requested_values", {})
    for key, expected in parsed.get("metadata", {}).items():
        if metadata.get(key) != expected:
            raise GoldGuardError(f"scenario metadata {key} differs from the user request")
    # Required user-visible values are checked against the parsed request, and
    # scenario duplicates cannot silently replace or add request intent.
    if set(metadata) != set(parsed.get("metadata", {})):
        raise GoldGuardError("scenario requested-value keys differ from the explicit request")


def _validate_target_matches_request(fields: dict[str, Any], parsed: dict[str, Any]) -> None:
    expected = parsed["fields"]
    for key, value in expected.items():
        if key in {"original_amount"}:
            if _decimal(fields.get(key), nonzero=True) != _decimal(value, nonzero=True):
                raise GoldGuardError(f"gold field {key} differs from the explicit user request")
        elif key == "payment_allocations":
            if not _same_allocations(fields.get(key), value, "requested payment"):
                raise GoldGuardError("gold payment allocations differ from the explicit user request")
        elif key == "split":
            split = fields.get(key)
            if not isinstance(split, dict) or split.get("mode") != value.get("mode"):
                raise GoldGuardError("gold split mode differs from the explicit user request")
            if value["mode"] == "equal":
                if split.get("participant_refs") != value.get("participant_refs"):
                    raise GoldGuardError("gold equal-split participants differ from the explicit user request")
            elif not _same_allocations(split.get("allocations"), value.get("allocations"), "requested split"):
                raise GoldGuardError("gold manual split differs from the explicit user request")
        elif key == "payment_payer_refs":
            requested = value
            actual = list(_allocation_map(fields.get("payment_allocations"), "requested payer set"))
            if set(actual) != set(requested) or len(actual) != len(requested):
                raise GoldGuardError("gold payment bearers differ from the explicitly requested payer")
        elif fields.get(key) != value:
            raise GoldGuardError(f"gold field {key} differs from the explicit user request")

    for key, value in fields.items():
        if key in {"kind", "expense_ref", "ledger_unit_ref"} \
                or (key == "payment_allocations" and "payment_payer_refs" in expected):
            continue
        if key not in expected and value is not None:
            raise GoldGuardError(f"gold field {key} is not explicit in the user request")


def _tool_trace(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    tools = [step for step in record.get("trace", []) if step.get("kind") == "tool_result"]
    if len(tools) != 1:
        raise GoldGuardError("a T1 operation must contain exactly one deterministic read result")
    step = tools[0]
    if step.get("producer") != "deterministic_synthetic_fixture":
        raise GoldGuardError("read result producer is not the deterministic fixture simulator")
    if step.get("fixture_state") != record.get("fixture_state"):
        raise GoldGuardError("tool replay fixture differs from the record fixture")

    from .runtime import SNAPSHOT_AGENT, baseline_modules
    _, _, _, simulator, _ = baseline_modules()
    if step.get("simulator_version") != simulator.SIMULATOR_VERSION:
        raise GoldGuardError("read result uses an unsupported simulator version")
    simulator_path = SNAPSHOT_AGENT / "evaluation" / "data_simulator.py"
    if step.get("simulator_sha256") != hashlib.sha256(simulator_path.read_bytes()).hexdigest():
        raise GoldGuardError("read result simulator hash differs from the frozen source")
    request = step.get("request")
    if not isinstance(request, dict):
        raise GoldGuardError("read result request is missing")
    try:
        expected = simulator.simulate_read(
            record["fixture_state"], request,
            observed_at=step["observed_at"], context_version=step["context_version"],
            replay_key=step["replay_key"],
        ).model_dump(mode="json")
    except Exception as exc:
        raise GoldGuardError("read result request cannot be replayed from the fixture") from exc
    if _json(expected) != _json(step.get("result")):
        raise GoldGuardError("deterministic tool body differs from a fresh fixture replay")
    return step, expected


def _model_read_result(result: dict[str, Any]) -> dict[str, Any]:
    return {key: result[key] for key in ("result_ref", "operation", "observed_at", "context_version", "simulation", "body")}


def _validate_read_consumption(record: dict[str, Any], tool: dict[str, Any], result: dict[str, Any]) -> None:
    read_model = _model_read_result(result)
    model_steps = _model_steps(record)
    for step in model_steps:
        context = step.get("context", {})
        rows = context.get("read_results", [])
        if rows:
            if len(rows) != 1 or _json(rows[0]) != _json(read_model):
                raise GoldGuardError("model context consumed a result different from deterministic replay")
    final_rows = model_steps[-1].get("context", {}).get("read_results", [])
    if len(final_rows) != 1 or _json(final_rows[0]) != _json(read_model):
        raise GoldGuardError("final model decision did not consume the deterministic read result")
    trace = record["trace"]
    tool_index = trace.index(tool)
    preceding_models = [step for step in trace[:tool_index] if step.get("kind") == "model"]
    if not preceding_models or _json(preceding_models[-1].get("target")) != _json(tool.get("request")):
        raise GoldGuardError("tool request differs from the preceding model read decision")
    if result.get("operation") != tool.get("request", {}).get("operation"):
        raise GoldGuardError("read result operation differs from the request")


def _read_body(context: dict[str, Any], operation: str) -> list[dict[str, Any]]:
    results = context.get("read_results", [])
    if len(results) != 1 or results[0].get("operation") != operation:
        raise GoldGuardError("the final model call must consume the matching current read result")
    return results[0].get("body", {}).get("items", [])


def _visible_current_activity(context: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    current = _current_activity(state)
    facts = _read_body(context, "read.activities")
    matches = [row for row in facts if row.get("activity_ref") == current["ref"]]
    if len(matches) != 1 or matches[0].get("status") != "active":
        raise GoldGuardError("create context does not expose its active current activity fact")
    return matches[0]


def _validate_create(record: dict[str, Any], target: dict[str, Any], context: dict[str, Any], parsed: dict[str, Any]) -> None:
    state = record["operation_state"]
    fields = target.get("fields", {})
    if parsed.get("interaction") == "clarify_only_missing_amount_then_continue":
        _validate_missing_total_create_trajectory(record, parsed)
    _validate_target_matches_request(fields, parsed)
    if fields.get("kind") != "expense.create":
        raise GoldGuardError("create gold has a different operation")
    unit = state["ledger_unit"]
    if fields.get("ledger_unit_ref") != unit.get("ref"):
        raise GoldGuardError("create gold targets the wrong ledger unit")
    refs = _context_refs(context)
    if fields["ledger_unit_ref"] not in refs["ledger_unit"]:
        raise GoldGuardError("create ledger unit is not bound in this model context")
    current = _current_activity(state)
    if current["ref"] not in refs["activity"]:
        raise GoldGuardError("current activity anchor is not present in the model context")
    visible_activity = _visible_current_activity(context, state)
    if visible_activity.get("base_currency") != current.get("base_currency"):
        raise GoldGuardError("current activity fact differs from the operation-state base currency")
    if unit.get("currency") != visible_activity.get("base_currency"):
        raise GoldGuardError("create ledger unit currency differs from the visible activity base currency")

    participants = {row["ref"]: row for row in state["participants"]}
    allowed = set(unit["participant_allowlist"])
    payers = fields.get("payment_allocations")
    split = fields.get("split")
    amount = _money(fields.get("original_amount"))
    payer_map = _allocation_map(payers, "create payment")
    if "payment_payer_refs" in parsed["fields"]:
        if set(payer_map) != set(parsed["fields"]["payment_payer_refs"]) or len(payer_map) != 1:
            raise GoldGuardError("missing-total create payment must use its one explicitly requested payer")
    split_refs, split_rows = _split_allocations(split, amount, "create")
    all_refs = set(payer_map) | set(split_refs)
    if not all_refs.issubset(allowed):
        raise GoldGuardError("payer or split bearer is outside the ledger-unit participant scope")
    if any(not participants[ref].get("active") for ref in all_refs):
        raise GoldGuardError("payer or split bearer is inactive")
    if not all_refs.issubset(refs["participant"]):
        raise GoldGuardError("payer or split bearer lacks a typed current-turn binding")
    if refs["participant"] != allowed:
        raise GoldGuardError("model participant references differ from the active ledger-unit scope")
    if sum(payer_map.values(), Decimal("0")) != amount:
        raise GoldGuardError("create payments do not conserve the expense amount")
    if _sum_allocations(split_rows) != amount:
        raise GoldGuardError("create split does not conserve the expense amount")
    if fields.get("original_currency") != visible_activity["base_currency"]:
        raise GoldGuardError("new create lacks model-visible server FX evidence for a non-base currency")


def _validate_missing_total_create_trajectory(record: dict[str, Any], parsed: dict[str, Any]) -> None:
    scenario = record.get("scenario", {})
    if (scenario.get("interaction") != "clarify_only_missing_amount_then_continue"
            or scenario.get("request_completed_across_turns") is not True):
        raise GoldGuardError("missing-total create scenario does not describe a completed clarification")
    model_steps = _model_steps(record)
    clarifications = [step for step in model_steps if step.get("target", {}).get("kind") == "clarify"]
    followups = [step for step in record.get("trace", []) if step.get("kind") == "user_followup"]
    if len(clarifications) != 1 or len(followups) != 1:
        raise GoldGuardError("missing-total create needs exactly one clarification and one amount follow-up")
    missing = clarifications[0].get("target", {}).get("missing_slots")
    if missing != ["original_amount"]:
        raise GoldGuardError("create clarification must ask only for the missing total amount")
    prompt = clarifications[0].get("target", {}).get("prompt")
    if not isinstance(prompt, str) or "总金额" not in prompt:
        raise GoldGuardError("create clarification does not ask for the requested total amount")
    initial_context = model_steps[0].get("context", {})
    initial = initial_context.get("input_text")
    if not isinstance(initial, str) or "总金额待确认，请勿根据付款人与分摊推定总金额" not in initial:
        raise GoldGuardError("initial create request lacks an explicit no-inference instruction")
    if re.search(r"金额(?:补充为)?\s*[0-9]+(?:\.[0-9]{1,4})?\s+[A-Z]{3}", initial):
        raise GoldGuardError("initial create request already discloses the supposedly missing amount")
    expected_followup = f"金额补充为{parsed['fields']['original_amount']} {parsed['fields']['original_currency']}。"
    if followups[0].get("text") != expected_followup:
        raise GoldGuardError("amount follow-up differs from the user-derived missing amount")


def _expense_fact_for(context: dict[str, Any], expense_ref: str) -> dict[str, Any]:
    facts = _read_body(context, "read.expenses")
    matches = [row for row in facts if row.get("expense_ref") == expense_ref]
    if len(matches) != 1:
        raise GoldGuardError("target expense is absent or ambiguous in the consumed ExpenseFact set")
    return matches[0]


def _require_current_activity_expense_read(record: dict[str, Any], current: dict[str, Any]) -> None:
    tool, _ = _tool_trace(record)
    request = tool.get("request", {})
    criteria = request.get("criteria", {})
    if request.get("operation") != "read.expenses" or criteria.get("activity_ref") != current.get("ref"):
        raise GoldGuardError("consumed ExpenseFact result is not scoped to the current activity")


def _check_visible_expense_fact(expense: dict[str, Any], fact: dict[str, Any]) -> None:
    expected = {
        "expense_ref": expense["ref"], "title": expense["title"],
        "original_amount": expense["amount"], "original_currency": expense["currency"],
        "occurred_at": expense["occurred_at"], "participant_refs": expense["participant_refs"],
        "financial_locked": expense["locked"], "expense_version": expense["expense_version"],
    }
    for key, value in expected.items():
        if fact.get(key) != value:
            raise GoldGuardError(f"visible ExpenseFact differs from current {key}")


def _validate_update(record: dict[str, Any], target: dict[str, Any], context: dict[str, Any], parsed: dict[str, Any]) -> None:
    fields = target.get("fields", {})
    _validate_target_matches_request(fields, parsed)
    if fields.get("kind") != "expense.update":
        raise GoldGuardError("financial update gold has a different operation")
    state = record["operation_state"]
    current = _current_activity(state)
    expense_ref = fields.get("expense_ref")
    refs = _context_refs(context)
    matched = [row for row in state.get("expenses", []) if row.get("ref") == expense_ref]
    if len(matched) != 1 or expense_ref not in refs["expense"]:
        raise GoldGuardError("target expense is missing, ambiguous, or not bound in this model context")
    expense = matched[0]
    if expense.get("activity_ref") != current["ref"] or not expense.get("target_allowed"):
        raise GoldGuardError("target expense is outside the authorized current activity scope")
    unit = state.get("ledger_unit", {})
    if expense.get("ledger_unit_ref") != unit.get("ref"):
        raise GoldGuardError("target expense is not bound to the current ledger-unit scope")
    fact = _expense_fact_for(context, expense_ref)
    _check_visible_expense_fact(expense, fact)
    _require_current_activity_expense_read(record, current)
    if expense.get("locked"):
        raise GoldGuardError("financially locked expense cannot receive a financial update")

    old_amount = _money(expense["amount"])
    old_currency = expense["currency"]
    resulting_amount = _money(fields["original_amount"]) if fields.get("original_amount") is not None else old_amount
    resulting_currency = fields.get("original_currency") or old_currency
    if not re.fullmatch(r"[A-Z]{3}", resulting_currency):
        raise GoldGuardError("updated expense currency is invalid")
    if resulting_amount != old_amount and resulting_currency != current["base_currency"]:
        raise GoldGuardError("changed foreign-currency amount lacks visible server FX snapshot evidence")
    if fields.get("original_currency") is not None and resulting_currency != old_currency \
            and resulting_currency != current["base_currency"]:
        raise GoldGuardError("changing to a non-base currency lacks visible server FX snapshot evidence")

    participants = {row["ref"]: row for row in state["participants"]}
    allowed = set(unit.get("participant_allowlist", []))
    if not set(expense.get("participant_refs", [])) or not set(expense["participant_refs"]).issubset(allowed):
        raise GoldGuardError("target expense participants are outside its ledger-unit scope")
    if fields.get("payment_allocations") is None:
        merged_payments = expense["payments"]
    else:
        merged_payments = fields["payment_allocations"]
    if fields.get("split") is None:
        merged_splits = expense["splits"]
        split_refs = [row["participant_ref"] for row in merged_splits]
    else:
        split_refs, merged_splits = _split_allocations(fields["split"], resulting_amount, "updated")
    payer_map = _allocation_map(merged_payments, "merged update payment")
    if set(payer_map) - allowed or set(split_refs) - allowed:
        raise GoldGuardError("stored update allocations are outside the target ledger-unit participant scope")
    if any(ref not in participants or not participants[ref].get("active") for ref in set(payer_map) | set(split_refs)):
        raise GoldGuardError("updated payer or split bearer is inactive")
    if not (set(payer_map) | set(split_refs)).issubset(refs["participant"]):
        raise GoldGuardError("updated participant lacks a typed current-turn binding")
    if sum(payer_map.values(), Decimal("0")) != resulting_amount:
        raise GoldGuardError("merged update payments do not conserve the resulting expense amount")
    if _sum_allocations(merged_splits) != resulting_amount:
        raise GoldGuardError("merged update splits do not conserve the resulting expense amount")

    changed = False
    if fields.get("original_amount") is not None:
        changed |= _decimal(fields["original_amount"], nonzero=True) != old_amount
    if fields.get("original_currency") is not None:
        changed |= resulting_currency != old_currency
    if fields.get("payment_allocations") is not None:
        changed |= not _same_allocations(fields["payment_allocations"], expense["payments"], "old payment")
    if fields.get("split") is not None:
        changed |= not _same_allocations(merged_splits, expense["splits"], "old split")
    if not changed:
        raise GoldGuardError("financial update changes no financial value")


def _presentation_candidate_token(fact: dict[str, Any]) -> str:
    ref = fact.get("expense_ref")
    currency = fact.get("original_currency")
    participants = fact.get("participant_refs")
    locked = fact.get("financial_locked")
    if not isinstance(ref, str) or not re.fullmatch(_EXPENSE_REF, ref):
        raise GoldGuardError("visible presentation candidate has an invalid expense reference")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        raise GoldGuardError("visible presentation candidate has an invalid currency")
    if not isinstance(participants, list) or any(
        not isinstance(item, str) or not re.fullmatch(r"participant_(?:selected|[0-9]{1,2})", item)
        for item in participants
    ) or len(participants) != len(set(participants)):
        raise GoldGuardError("visible presentation candidate has invalid participant references")
    if not isinstance(locked, bool):
        raise GoldGuardError("visible presentation candidate has no typed financial-lock fact")
    participant_text = ",".join(participants) if participants else "-"
    return f"{ref}|{currency}|{participant_text}|{'是' if locked else '否'}"


def _validate_presentation_clarification(
    step: dict[str, Any], query_title: str, candidates: list[dict[str, Any]],
) -> None:
    prompt = step.get("target", {}).get("prompt")
    match = re.fullmatch(
        r"请求标题=“([^”]+)”；候选\(ref\|currency\|participant_refs\|financial_locked\)="
        r"(.+)；请回复其中一个expense_ref。",
        prompt if isinstance(prompt, str) else "",
    )
    if not match or match.group(1) != query_title:
        raise GoldGuardError("presentation clarification must expose the requested title and typed candidate facts")
    # The candidate separator is a full-width comma; ASCII commas remain part
    # of a comma-separated participant_refs value.
    tokens = match.group(2).split("，")
    parsed: dict[str, str] = {}
    for token in tokens:
        candidate = re.fullmatch(
            rf"({_EXPENSE_REF})\|([A-Z]{{3}})\|((?:participant_(?:selected|[0-9]{{1,2}})(?:,participant_(?:selected|[0-9]{{1,2}}))*)|-?)\|(是|否)",
            token,
        )
        if not candidate:
            raise GoldGuardError("presentation clarification contains a malformed candidate fact")
        ref = candidate.group(1)
        if ref in parsed:
            raise GoldGuardError("presentation clarification repeats a candidate reference")
        parsed[ref] = token
    expected = {row["expense_ref"]: _presentation_candidate_token(row) for row in candidates}
    if parsed != expected:
        raise GoldGuardError("presentation clarification candidate facts are incomplete, substituted, or invented")


def _check_presentation_selection(record: dict[str, Any], context: dict[str, Any], expense_ref: Any,
                                  parsed: dict[str, Any]) -> dict[str, Any]:
    facts = _read_body(context, "read.expenses")
    if not facts:
        raise GoldGuardError("presentation update has no visible ExpenseFact to select")
    query_title = parsed["metadata"].get("query_title")
    initial_ref = parsed.get("selection", {}).get("initial_expense_ref")
    followup_ref = parsed.get("selection", {}).get("followup_expense_ref")
    clarifications = [
        step for step in record["trace"]
        if step.get("kind") == "model" and step.get("target", {}).get("kind") == "clarify"
    ]
    followups = [step.get("text", "") for step in record["trace"] if step.get("kind") == "user_followup"]
    if query_title is not None:
        title_candidates = [row for row in facts if row.get("title") == query_title]
        if not title_candidates:
            raise GoldGuardError("presentation query title has no matching visible ExpenseFact")
    else:
        title_candidates = []

    if initial_ref is not None:
        if clarifications or followups or followup_ref is not None:
            raise GoldGuardError("an explicitly selected presentation expense must not ask for a follow-up")
        if expense_ref != initial_ref:
            raise GoldGuardError("presentation target differs from the explicit initial expense reference")
        if query_title is not None and not any(row.get("expense_ref") == expense_ref for row in title_candidates):
            raise GoldGuardError("explicit presentation expense does not match the requested title")
    elif query_title is not None and len(title_candidates) == 1:
        if clarifications or followups or followup_ref is not None:
            raise GoldGuardError("a unique visible title match must be proposed without a false clarification")
        if expense_ref != title_candidates[0].get("expense_ref"):
            raise GoldGuardError("presentation proposal did not bind the unique visible title match")
    elif query_title is not None and len(title_candidates) > 1:
        if len(clarifications) != 1 or followup_ref is None or len(followups) != 1:
            raise GoldGuardError("ambiguous title match requires one clarification and one explicit follow-up")
        missing = clarifications[0]["target"].get("missing_slots", [])
        if missing != ["expense_ref"]:
            raise GoldGuardError("presentation clarification must ask only for the ambiguous expense reference")
        clarify_context = clarifications[0].get("context", {})
        clarify_facts = _read_body(clarify_context, "read.expenses")
        clarify_candidates = [row for row in clarify_facts if row.get("title") == query_title]
        if {row.get("expense_ref") for row in clarify_candidates} != {
            row.get("expense_ref") for row in title_candidates
        } or len(clarify_candidates) != len(title_candidates):
            raise GoldGuardError("clarification context does not expose every requested-title candidate")
        _validate_presentation_clarification(clarifications[0], query_title, title_candidates)
        followup_match = re.fullmatch(rf"\s*expense_ref=({_EXPENSE_REF})\s*[。.!！]?\s*", followups[0])
        if not followup_match or followup_match.group(1) != followup_ref:
            raise GoldGuardError("presentation follow-up trace differs from its user-authored reference")
        if expense_ref != followup_ref:
            raise GoldGuardError("presentation target differs from the user's clarified expense reference")
        if not any(row.get("expense_ref") == expense_ref for row in title_candidates):
            raise GoldGuardError("clarified expense is not one of the visible same-title candidates")
    else:
        if clarifications or followups or followup_ref is not None:
            raise GoldGuardError("presentation clarification requires a title-only ambiguous request")
        if initial_ref is None or expense_ref != initial_ref:
            raise GoldGuardError("presentation update has no explicit expense reference or unique title match")

    matches = [row for row in facts if row.get("expense_ref") == expense_ref]
    if len(matches) != 1:
        raise GoldGuardError("selected presentation expense is absent or ambiguous in visible facts")
    return matches[0]


def _validate_presentation(record: dict[str, Any], target: dict[str, Any], context: dict[str, Any],
                           parsed: dict[str, Any]) -> None:
    fields = target.get("fields", {})
    _validate_target_matches_request(fields, parsed)
    if fields.get("kind") != "expense.presentation.update":
        raise GoldGuardError("presentation update gold has a different operation")
    expense_ref = fields.get("expense_ref")
    clarification_exists = any(
        step.get("kind") == "model" and step.get("target", {}).get("kind") == "clarify"
        for step in record["trace"]
    )
    scenario = record.get("scenario", {})
    if clarification_exists:
        if scenario.get("interaction") != "clarify_ambiguous_expense_ref_then_continue" \
                or scenario.get("request_completed_across_turns") is not True:
            raise GoldGuardError("ambiguous presentation gold lacks its multi-turn interaction declaration")
    elif parsed["metadata"].get("query_title") is not None \
            and parsed.get("selection", {}).get("initial_expense_ref") is None:
        if scenario.get("interaction") != "unique_title_match_direct_proposal" \
                or scenario.get("request_completed_across_turns") is not False:
            raise GoldGuardError("unique-title presentation lacks its direct-proposal interaction declaration")
    elif scenario.get("interaction") in {
        "clarify_ambiguous_expense_ref_then_continue", "unique_title_match_direct_proposal",
    } or scenario.get("request_completed_across_turns") is True:
        raise GoldGuardError("presentation scenario declares an interaction that is absent from the request trace")
    if not clarification_exists and parsed["fields"].get("expense_ref") != expense_ref:
        if parsed["metadata"].get("query_title") is None:
            raise GoldGuardError("single-turn presentation target is not stated in the user request")
    selected_fact = _check_presentation_selection(record, context, expense_ref, parsed)
    state = record["operation_state"]
    current = _current_activity(state)
    _require_current_activity_expense_read(record, current)
    refs = _context_refs(context)
    if expense_ref not in refs["expense"]:
        raise GoldGuardError("selected presentation expense is not bound in this model context")
    matching = [row for row in state.get("expenses", []) if row.get("ref") == expense_ref]
    if len(matching) != 1 or not matching[0].get("target_allowed"):
        raise GoldGuardError("presentation target is outside the current activity scope")
    expense = matching[0]
    _check_visible_expense_fact(expense, selected_fact)
    # Financial locks do not block presentation edits; only a visible, current,
    # editable target and a live activity are required.
    for key in ("title", "note", "icon_key"):
        if key in fields and fields[key] is not None \
                and (not isinstance(fields[key], str) or not fields[key].strip()):
            raise GoldGuardError(f"presentation field {key} must be nonempty when supplied")
    if not any(fields.get(key) not in (None, "") for key in ("title", "note", "icon_key")):
        raise GoldGuardError("presentation update changes no nonempty display field")


def _read_answer(
    record: dict[str, Any], context: dict[str, Any], result: dict[str, Any], parsed: dict[str, Any],
) -> None:
    operation = result["operation"]
    items = result["body"]["items"]
    post_filter = parsed.get("post_filter", {})
    title_contains = post_filter.get("title_contains") if isinstance(post_filter, dict) else None
    if title_contains is not None:
        if operation != "read.expenses" or not isinstance(title_contains, str) or not title_contains:
            raise GoldGuardError("title post-filter is unsupported or malformed")
        items = [row for row in items if title_contains in row.get("title", "")]
    answer = _model_steps(record)[-1].get("target", {})
    if answer.get("kind") != "answer":
        raise GoldGuardError("read operation does not end with an answer")
    expected_citations = [row["evidence_ref"] for row in items]
    if answer.get("citations") != expected_citations:
        raise GoldGuardError("answer citations are missing, substituted, or out of order")
    if not items:
        expected_text = "按你给出的筛选条件，模拟查询没有匹配记录。"
        if answer.get("basis") != "conversation" or answer.get("text") != expected_text:
            raise GoldGuardError("empty-result answer differs from the grounded no-match response")
        return
    if answer.get("basis") != "grounded":
        raise GoldGuardError("nonempty read results require a grounded answer")
    if operation == "read.activities":
        lines = [f"{row['name']}（{row['activity_kind']}，{row['status']}）" for row in items]
    elif operation == "read.expenses":
        lines = [f"{row['title']}：{row['original_amount']} {row['original_currency']}" for row in items]
    elif operation == "read.debts":
        lines = [f"{row['debtor_ref']}→{row['creditor_ref']}：{row['amount']} {row['currency']}" for row in items]
    else:
        raise GoldGuardError("unsupported read result body")
    expected_text = f"模拟查询得到{len(lines)}项：" + "；".join(lines) + "。"
    if answer.get("text") != expected_text:
        raise GoldGuardError("answer facts differ from the visible result amount, currency, direction, or object")


def _validate_read(record: dict[str, Any], target: dict[str, Any], context: dict[str, Any], parsed: dict[str, Any],
                   tool: dict[str, Any], result: dict[str, Any]) -> None:
    if target.get("kind") != "read" or target.get("operation") != record["expected"]["task_operation"]:
        raise GoldGuardError("selected read operation differs from the task operation")
    if target.get("criteria") != parsed["criteria"]:
        raise GoldGuardError("read criteria differ from the user-authored request")
    scenario = record["scenario"]
    _validate_scenario_request(scenario, parsed, record["expected"]["task_operation"])
    if scenario.get("criteria") != parsed["criteria"]:
        raise GoldGuardError("scenario criteria differ from the user-authored request")
    refs = _context_refs(context)
    criteria = parsed["criteria"]
    if record["expected"]["task_operation"] != "read.activities":
        current = _current_activity(record["operation_state"])
        if criteria.get("activity_ref") != current["ref"] or current["ref"] not in refs["activity"]:
            raise GoldGuardError("read criteria cross or lack the authorized current activity scope")
        if current["status"] == "deleted" or not current.get("visible"):
            raise GoldGuardError("expense and debt reads require a visible current activity")
    if criteria.get("participant_ref") and criteria["participant_ref"] not in refs["participant"]:
        raise GoldGuardError("read participant filter is not bound in this model context")
    if tool.get("request") != target:
        raise GoldGuardError("tool read request differs from the user-derived read decision")
    _read_answer(record, context, result, parsed)


def _validate_write(record: dict[str, Any], target: dict[str, Any], context: dict[str, Any],
                    parsed: dict[str, Any]) -> None:
    operation = record["expected"]["task_operation"]
    scenario = record["scenario"]
    _validate_scenario_request(scenario, parsed, operation)
    fields = target.get("fields", {})
    if scenario.get("target") is not None and scenario["target"] != fields:
        raise GoldGuardError("scenario target duplicate differs from the selected model decision")
    if target.get("kind") != "propose" or target.get("operation") != operation:
        raise GoldGuardError("selected proposal operation differs from the task operation")
    unit = record["operation_state"].get("ledger_unit", {})
    parent_ref = unit.get("parent_ref")
    if parent_ref is not None and parent_ref not in _context_refs(context)["ledger_unit"]:
        raise GoldGuardError("child ledger unit parent is not bound in the current model context")
    if operation == "expense.create":
        _validate_create(record, target, context, parsed)
    elif operation == "expense.update":
        _validate_update(record, target, context, parsed)
    elif operation == "expense.presentation.update":
        _validate_presentation(record, target, context, parsed)
    else:
        raise GoldGuardError("unsupported write operation")


def validate_operation_gold(record: dict[str, Any]) -> None:
    if not isinstance(record, dict):
        raise GoldGuardError("gold record must be a mapping")
    tags = record.get("coverage_tags", [])
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise GoldGuardError("gold record coverage tags are malformed")
    boundary_tags = [tag for tag in tags if tag.startswith("boundary_")]
    if boundary_tags:
        if len(boundary_tags) != 1:
            raise GoldGuardError("gold record must carry exactly one boundary coverage tag")
        try:
            from .boundary import validate_boundary_gold
            result = validate_boundary_gold(record)
        except Exception as exc:
            raise GoldGuardError("independent boundary gold validation failed") from exc
        expected_case = boundary_tags[0][len("boundary_"):]
        if not isinstance(result, dict) or result.get("valid") is not True \
                or result.get("case_id") != expected_case \
                or not isinstance(result.get("derived_semantic"), str) \
                or not result["derived_semantic"].strip() \
                or not isinstance(result.get("reason_codes"), list) \
                or not result["reason_codes"] \
                or any(not isinstance(code, str) or not code.strip() for code in result["reason_codes"]) \
                or not isinstance(result.get("source_facts_sha256"), str) \
                or not re.fullmatch(r"[0-9a-f]{64}", result["source_facts_sha256"]):
            raise GoldGuardError("independent boundary gold returned an invalid or mismatched result")
        return

    case_type = record.get("case_type")
    if case_type in _BOUNDARY_CASE_TYPES:
        raise GoldGuardError("boundary case type is missing its independently validated boundary tag")
    if case_type not in _POSITIVE_CASE_TYPES:
        raise GoldGuardError("unknown or unsupported gold case type")
    operation = record.get("expected", {}).get("task_operation")
    if operation not in OPS:
        raise GoldGuardError("unknown or unsupported gold task operation")
    state = record.get("operation_state")
    _operation_state_eligible(state, operation)
    _validate_state_fixture_binding(record)
    steps = _model_steps(record)
    selected = steps[0] if operation.startswith("read.") else steps[-1]
    context, target = selected.get("context", {}), selected.get("target", {})
    parsed = _parse_request(operation, context)
    tool, replayed = _tool_trace(record)
    _validate_read_consumption(record, tool, replayed)

    current = _current_activity(state)
    required = _PERMISSION[operation]
    if required not in context.get("available_permissions", []):
        raise GoldGuardError(f"model context does not expose {required}")
    verified = context.get("verified_scope", {})
    if verified.get("kind") != "activity" or verified.get("activity_ref") != current.get("ref"):
        raise GoldGuardError("model context verified scope differs from the current activity")
    if required not in verified.get("permissions", []):
        raise GoldGuardError(f"verified activity scope does not grant {required}")

    if operation.startswith("read."):
        answer_context = steps[-1].get("context", {})
        if required not in answer_context.get("available_permissions", []):
            raise GoldGuardError("final answer context does not expose the read permission")
        answer_scope = answer_context.get("verified_scope", {})
        if answer_scope.get("kind") != "activity" or answer_scope.get("activity_ref") != current.get("ref") \
                or required not in answer_scope.get("permissions", []):
            raise GoldGuardError("final answer context verified scope differs from the authorized read scope")

    if operation.startswith("read."):
        _validate_read(record, target, context, parsed, tool, replayed)
    else:
        if not context.get("read_results"):
            raise GoldGuardError("write proposal must consume a current model-visible state read")
        expected_read = "read.activities" if operation == "expense.create" else "read.expenses"
        if context["read_results"][-1].get("operation") != expected_read:
            raise GoldGuardError("write proposal consumed the wrong current read result")
        _validate_write(record, target, context, parsed)

    if record.get("operation_state_signature_sha256") != operation_state_signature(state, operation):
        raise GoldGuardError("operation-state signature mismatch")
    if record.get("scenario_signature_sha256") != sha256(record["scenario"]):
        raise GoldGuardError("scenario signature mismatch")
