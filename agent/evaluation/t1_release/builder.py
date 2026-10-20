"""Deterministic synthetic T1 v2 candidate builder; bodies go only to D:."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .goldguard import validate_operation_gold
from .runtime import SNAPSHOT_AGENT, SNAPSHOT_MANIFEST_SHA256, baseline_modules, make_v2_validator
from .signatures import operation_state_signature, sha256


RUN_ROOT = Path(r"D:\AI\runs\shared-ledger\t1-release-v2-20261011")
DATA_ROOT = RUN_ROOT / "data"
REVIEW_ROOT = RUN_ROOT / "human-review"
NAMESPACE = uuid.UUID("3a916a32-8053-5e7a-9d17-ddf56f61a76a")
SPLITS = ("train", "validation", "sealed")
OPERATIONS = (
    "read.activities", "read.expenses", "read.debts",
    "expense.create", "expense.update", "expense.presentation.update",
)
CURRENCIES = ("USD", "CNY", "EUR", "JPY", "CAD")
EXPENSE_TITLE_PLACES = (
    "春日", "海岸", "山间", "星河", "松林", "古城", "云端", "湖畔",
    "北岸", "南站", "林谷", "石桥", "海湾", "雪岭", "花园",
)
EXPENSE_TITLE_TYPES = ("团餐", "客房", "车票", "景区票")
CAPABILITY = {
    "read.activities": ["CAP01"], "read.expenses": ["CAP01"], "read.debts": ["CAP01"],
    "expense.create": ["CAP07"], "expense.update": ["CAP08"],
    "expense.presentation.update": ["CAP08"],
}
PERMISSION = {
    "read.activities": "read.activities", "read.expenses": "read.expenses",
    "read.debts": "read.debts", "expense.create": "propose.expense.create",
    "expense.update": "propose.expense.update",
    "expense.presentation.update": "propose.expense.presentation.update",
}
PRE_READ_PERMISSION = {
    "expense.create": "read.activities",
    "expense.update": "read.expenses",
    "expense.presentation.update": "read.expenses",
}
def _unit_role_for(g: int) -> str:
    group = (g % 20) // 4
    if group % 2:
        return "large_child" if group == 3 else "large_root"
    return "legacy_unscoped" if group == 2 else "normal_root"


def _debt_edge_count(g: int) -> int:
    node_count = 3 + ((g % 15) % 5)
    topology = (g % 15) // 5
    return node_count if topology == 1 else node_count - 1


def _catalogue_currency(op: str, g: int) -> str:
    if op in {"read.activities", "read.expenses", "read.debts", "expense.presentation.update"}:
        return CURRENCIES[(g // 15) % 4]
    return CURRENCIES[(g // 12) % len(CURRENCIES)]


def _presentation_catalogue_row(index: int) -> tuple[int, int]:
    if not 0 <= index < 60:
        raise ValueError("presentation family index must select one of 60 bounded catalogue rows")
    # The approved catalogue is 1..15 same-title candidates crossed with four
    # historical ExpenseFact currencies.  Lock is factual context, not a family
    # axis for a display-only proposal.
    candidate_count = 1 + (index % 15)
    return candidate_count, candidate_count if index % 2 else 0


def _expense_title(index: int) -> str:
    bounded = index % (len(EXPENSE_TITLE_PLACES) * len(EXPENSE_TITLE_TYPES))
    place = EXPENSE_TITLE_PLACES[bounded % len(EXPENSE_TITLE_PLACES)]
    category = EXPENSE_TITLE_TYPES[bounded // len(EXPENSE_TITLE_PLACES)]
    return f"{place}{category}费"


def _split_for(op: str, g: int) -> str:
    """Assign content clusters to splits while preserving a 20-row floor."""
    if op == "read.activities":
        # Each five-row name cohort stays in one split; four cohorts form 20 rows.
        return SPLITS[(g // 5) // 4]
    if op == "read.expenses":
        # Each of the three complete-query phrasings is a 20-row lexical
        # cluster. Keep each wording cluster in one split.
        place_group = (g % 15) // 5
        return SPLITS[place_group]
    if op == "read.debts":
        # Currency and requested graph-shape focus are real read dimensions.
        currency_group = g // 15
        topology_group = (g % 15) // 5
        return SPLITS[(currency_group + topology_group) % 3]
    return SPLITS[g // 20]


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _even_allocations(amount: str, refs: list[str]) -> list[dict[str, str]]:
    precision = 4
    quantum = Decimal("0.0001")
    units = int((Decimal(amount) / quantum).quantize(Decimal("1")))
    if units < len(refs):
        raise ValueError("amount is too small for strictly positive allocations")
    base, rem = divmod(units, len(refs))
    rows = []
    for index, ref in enumerate(refs):
        value = Decimal(base + (1 if index < rem else 0)) * quantum
        rows.append({"participant_ref": ref, "amount": f"{value:.{precision}f}"})
    return rows


def _binding_map(op: str, g: int, *, activity_count: int, participant_count: int, expense_count: int):
    c, _, _, _, _ = baseline_modules()
    turn = uuid.uuid5(NAMESPACE, f"{op}:{g}:turn")
    activity_ids = [uuid.uuid5(NAMESPACE, f"{op}:{g}:activity:{i}") for i in range(activity_count)]
    unit_id = uuid.uuid5(NAMESPACE, f"{op}:{g}:ledger-unit")
    unit_role = "large_root" if op == "read.debts" else _unit_role_for(g)
    # A migrated legacy unit is a large sub-activity unit too: bind it to an
    # active large-root parent just like an explicitly selected child unit.
    parent_unit_id = (
        uuid.uuid5(NAMESPACE, f"{op}:{g}:parent-ledger-unit")
        if unit_role in {"large_child", "legacy_unscoped"} else None
    )
    expense_ids = [uuid.uuid5(NAMESPACE, f"{op}:{g}:expense:{i}") for i in range(expense_count)]
    participant_ids = [uuid.uuid5(NAMESPACE, f"{op}:{g}:participant:{i}") for i in range(participant_count)]

    def candidate(kind, entity_id, scope):
        return c.ResolvedEntityCandidate(kind=kind, entity_id=entity_id, scope_activity_id=scope)

    anchor = candidate(c.UiEntityType.ACTIVITY, activity_ids[0], activity_ids[0])
    bound = [c.bind_selected_reference([], anchor, source_turn_id=turn)]
    rest = [candidate(c.UiEntityType.ACTIVITY, eid, eid) for eid in activity_ids[1:]]
    rest.append(candidate(c.UiEntityType.LEDGER_UNIT, unit_id, activity_ids[0]))
    if parent_unit_id is not None:
        rest.append(candidate(c.UiEntityType.LEDGER_UNIT, parent_unit_id, activity_ids[0]))
    rest.extend(candidate(c.UiEntityType.EXPENSE, eid, activity_ids[0]) for eid in expense_ids)
    rest.extend(candidate(c.UiEntityType.PARTICIPANT, pid, activity_ids[0]) for pid in participant_ids)
    bound = c.bind_stable_references(bound, rest, source_turn_id=turn)
    refs = {(item.kind, item.entity_id): item.ref.value for item in bound}
    return {
        "turn": turn, "activity_ids": activity_ids, "unit_id": unit_id, "expense_ids": expense_ids,
        "participant_ids": participant_ids, "bound": bound, "refs": refs,
        "activity_refs": [refs[("activity", item)] for item in activity_ids],
        "unit_ref": refs[("ledger_unit", unit_id)],
        "parent_unit_ref": refs[("ledger_unit", parent_unit_id)] if parent_unit_id is not None else None,
        "expense_refs": [refs[("expense", item)] for item in expense_ids],
        "participant_refs": [refs[("participant", item)] for item in participant_ids],
    }


def _activity(g: int, ref: str, role: str, *, status: str, kind: str, currency: str,
              permissions: list[str], member_allowlist: list[str], visible: bool = True) -> dict[str, Any]:
    labels = ("春日", "海岸", "山间", "星河", "松林", "古城", "云端", "湖畔")
    return {
        "ref": ref, "role": role, "name": f"{labels[g % len(labels)]}协作账本{g % 9}",
        "status": status, "kind": kind, "base_currency": currency,
        "visible": visible, "permissions": list(permissions), "member_allowlist": list(member_allowlist),
    }


def _make_state(op: str, g: int, ids: dict[str, Any],
                state_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    c, _, _, _, _ = baseline_modules()
    participants_refs = ids["participant_refs"]
    count = len(participants_refs)
    unit_role = "large_root" if op == "read.debts" else _unit_role_for(g)
    kind = "large" if unit_role in {"large_root", "large_child", "legacy_unscoped"} else "normal"
    currency = _catalogue_currency(op, g)
    member_count = (
        count if op in {"expense.create", "expense.update", "expense.presentation.update", "read.debts"}
        else max(1, count - (g % 3))
    )
    member_allowlist = participants_refs[:member_count]
    read_activity_group = g // 16
    activity_count = len(ids["activity_refs"])
    activities = []
    for idx, ref in enumerate(ids["activity_refs"]):
        if op == "read.activities":
            status = "archived" if (read_activity_group + idx) % 3 == 0 else "active"
            # Keep the current Activity compatible with its bound ledger unit;
            # visible non-current activities still vary independently below.
            kind_value = kind if idx == 0 else ("large" if (read_activity_group + idx) % 2 else "normal")
        else:
            status = "active" if idx == 0 else ("archived" if idx % 2 else "active")
            kind_value = kind if idx == 0 else ("large" if (g + idx) % 2 else "normal")
        if idx == 0 and op != "read.activities":
            status = "active"
        activity_permissions = sorted({PERMISSION[op], *([PRE_READ_PERMISSION[op]] if op in PRE_READ_PERMISSION else [])})
        activities.append(_activity(
            g + idx, ref, "current" if idx == 0 else f"visible_{idx}",
            status=status, kind=kind_value,
            currency=currency if idx == 0 else CURRENCIES[(g + idx) % len(CURRENCIES)],
            permissions=activity_permissions,
            member_allowlist=member_allowlist,
            visible=True,
        ))
    if op == "read.activities":
        cohort = f"{_expense_title((g // 5) * 5)}协作组"
        for activity in activities:
            activity["name"] = f"{cohort}·{activity['name']}"
    people = []
    for idx, ref in enumerate(participants_refs):
        role = "owner" if idx == 1 else (
               ("child" if kind == "large" and idx == count - 1 else "member"))
        people.append({
            "ref": ref, "role": role, "active": True,
        })
    # Positive create examples bind only an actually available ledger unit and
    # explicitly name every participant used by the request.
    allow_count = max(1, member_count - 1) if unit_role == "large_child" else member_count
    allowlist = participants_refs[:allow_count]
    state: dict[str, Any] = {
        "activities": activities,
        "participants": people,
        "actor": {"authenticated": True, "activity_member": True,
                  "activity_member_active": True, "activity_ref": ids["activity_refs"][0],
                  "permissions": list(activities[0]["permissions"])},
        "ledger_unit": {"ref": ids["unit_ref"], "activity_ref": ids["activity_refs"][0],
                        "role": unit_role, "parent_ref": ids["parent_unit_ref"],
                        "parent_role": "large_root" if ids["parent_unit_ref"] is not None else None,
                        "parent_active": True,
                        "currency": currency, "active": True,
                        "participant_allowlist": allowlist},
        "expenses": [],
        "debts": [],
        "visible_statuses": ["active", "archived"],
        "multi_currency_enabled": False,
        "fx_snapshot": {"source": "synthetic_state_fixture",
                        "snapshot_ref": f"fx_snapshot_{g:03d}", "base_currency": currency,
                        "quotes": []},
    }
    fx_base_units = {"USD": Decimal("1"), "CNY": Decimal("7.10"), "EUR": Decimal("0.92"),
                     "JPY": Decimal("149"), "CAD": Decimal("1.36")}
    quote_currencies = (currency,)
    for quote_currency in quote_currencies:
        rate = fx_base_units[quote_currency] / fx_base_units[currency]
        state["fx_snapshot"]["quotes"].append({
            "currency": quote_currency, "rate": f"{rate.quantize(Decimal('0.00000001')):.8f}",
        })
    if state_overrides and state_overrides.get("expense_currency"):
        # A release profile may model an expense denominated away from the
        # activity base currency, which is what makes the base column carry its
        # own rounding.  The stated rate is the one the fixture is read with.
        foreign = state_overrides["expense_currency"]
        rate = Decimal(state_overrides.get("fx_rate") or "1")
        state["multi_currency_enabled"] = True
        state["fx_snapshot"]["quotes"] = [{
            "currency": foreign, "rate": f"{rate.quantize(Decimal('0.00000001')):.8f}",
        }]
    if op in {"read.expenses", "expense.update", "expense.presentation.update"}:
        expense_count = len(ids["expense_refs"])
        presentation_locked_count = (
            _presentation_catalogue_row(g)[1] if op == "expense.presentation.update" else 0
        )
        for index, ref in enumerate(ids["expense_refs"]):
            unit_count = len(allowlist)
            if op == "expense.update":
                people_count = unit_count
                used_people = allowlist
            elif op == "expense.presentation.update":
                people_count = 1
                used_people = allowlist[(g + index) % unit_count:] + allowlist[:(g + index) % unit_count]
            else:
                people_count = min(unit_count, 2 + ((g + index) % max(1, unit_count - 1)))
                used_people = allowlist[(g + index) % unit_count:] + allowlist[:(g + index) % unit_count]
            expense_people = used_people[:people_count]
            amount = f"{Decimal(75 + 3 * g + index):.2f}"
            expense_currency = currency
            if state_overrides:
                # A release profile may pin the participant count, the amount
                # and the denomination of a designated expense so that a
                # specific allocation rule can be exercised.
                if state_overrides.get("split_participant_count") is not None:
                    people_count = int(state_overrides["split_participant_count"])
                    if people_count < 1 or people_count > len(used_people):
                        raise ValueError("split participant count is outside the allowlist")
                    expense_people = used_people[:people_count]
                amounts = state_overrides.get("expense_amounts") or []
                if index < len(amounts):
                    amount = amounts[index]
                if state_overrides.get("expense_currency"):
                    expense_currency = state_overrides["expense_currency"]
            payments = _even_allocations(amount, expense_people[:1 if (g + index) % 2 == 0 else min(2, len(expense_people))])
            splits = _even_allocations(amount, expense_people[:max(1, len(expense_people))])
            state["expenses"].append({
                "ref": ref, "activity_ref": ids["activity_refs"][0],
                "ledger_unit_ref": ids["unit_ref"],
                "title": _expense_title(g if op == "expense.presentation.update" else g + index),
                "amount": amount, "currency": expense_currency, "occurred_at": f"2026-10-{1 + ((g + index) % 20):02d}T09:30:00Z",
                "locked": index < presentation_locked_count if op == "expense.presentation.update" else False,
                "participant_refs": expense_people,
                "payments": payments, "splits": splits, "target_allowed": True,
                "is_target": index == 0 and op == "expense.update",
                "expense_version": str(1 + (g % 8)),
            })
    if op == "read.debts":
        # Three graph topologies crossed with five node counts and four colors
        # produce sixty distinct bounded graph families.
        debt_people = member_allowlist
        debt_count = len(debt_people)
        local_index = g % 15
        shape = local_index // 5
        if shape == 0:  # directed path
            pairs = [(index, index + 1) for index in range(debt_count - 1)]
        elif shape == 1:  # directed cycle
            pairs = [(index, (index + 1) % debt_count) for index in range(debt_count)]
        else:  # directed star into one center
            pairs = [(index, 0) for index in range(1, debt_count)]
        for index, (debtor_index, creditor_index) in enumerate(pairs):
            debt = {
                "activity_ref": ids["activity_refs"][0],
                "debtor_ref": debt_people[debtor_index], "creditor_ref": debt_people[creditor_index],
                "amount": f"{Decimal(8 + ((g + index) % 80)):.2f}",
                "currency": currency,
            }
            state["debts"].append(debt)
            expense_ref = ids["expense_refs"][index]
            amount = debt["amount"]
            state["expenses"].append({
                "ref": expense_ref,
                "activity_ref": ids["activity_refs"][0],
                "ledger_unit_ref": ids["unit_ref"],
                "title": f"{_expense_title(g + index)}债务结算费用",
                "amount": amount,
                "currency": debt["currency"],
                "occurred_at": f"2026-10-{1 + ((g + index) % 20):02d}T09:30:00Z",
                "locked": False,
                "participant_refs": [debt["debtor_ref"], debt["creditor_ref"]],
                "payments": [{"participant_ref": debt["creditor_ref"], "amount": amount}],
                "splits": [{"participant_ref": debt["debtor_ref"], "amount": amount}],
                "target_allowed": True,
                "is_target": False,
                "expense_version": "1",
            })
    return state


def _fixture_from_state(op: str, g: int, state: dict[str, Any]) -> dict[str, Any]:
    activities = [{
        "activity_ref": row["ref"], "name": row["name"], "activity_kind": row["kind"],
        "base_currency": row["base_currency"], "status": row["status"],
    } for row in state["activities"]]
    expenses = [{
        "activity_ref": row["activity_ref"], "expense_ref": row["ref"], "title": row["title"],
        "original_amount": row["amount"], "original_currency": row["currency"],
        "occurred_at": row["occurred_at"], "participant_refs": row["participant_refs"],
        "financial_locked": row["locked"], "expense_version": row["expense_version"],
    } for row in state["expenses"]]
    debts = [{
        "activity_ref": row["activity_ref"], "debtor_ref": row["debtor_ref"],
        "creditor_ref": row["creditor_ref"], "amount": row["amount"], "currency": row["currency"],
    } for row in state["debts"]]
    return {"activities": activities, "expenses": expenses, "debts": debts}


def _model_context(c, ids, text: str, op: str, *, results=None, policy_rows=None,
                   activity_permissions=None, participant_allowlist=None):
    names = [{
        "read.activities": "READ_ACTIVITIES", "read.expenses": "READ_EXPENSES",
        "read.debts": "READ_DEBTS", "expense.create": "PROPOSE_EXPENSE_CREATE",
        "expense.update": "PROPOSE_EXPENSE_UPDATE",
        "expense.presentation.update": "PROPOSE_EXPENSE_PRESENTATION_UPDATE",
    }[op]]
    if op in PRE_READ_PERMISSION:
        names.append({
            "read.activities": "READ_ACTIVITIES", "read.expenses": "READ_EXPENSES",
        }[PRE_READ_PERMISSION[op]])
    if activity_permissions is None:
        permissions = [getattr(c.HarnessPermission, name) for name in names]
    else:
        enum_names = {value: name for name, value in ((name, getattr(c.HarnessPermission, name).value)
                      for name in c.HarnessPermission.__members__)}
        permissions = [getattr(c.HarnessPermission, enum_names[name]) for name in activity_permissions]
    bound = ids["bound"]
    if participant_allowlist is not None:
        allowed = set(participant_allowlist)
        bound = [item for item in bound if item.kind != "participant" or item.ref.value in allowed]
    return c.ModelContext(
        context_version=1, input_text=text,
        verified_scope=c.ModelActivityScope(kind="activity", activity_ref=ids["activity_refs"][0], permissions=permissions),
        recent_messages=[], pending_slots=[], bound_references=c.model_reference_tokens(bound),
        read_results=list(results or []), policy_evidence=list(policy_rows or []), available_permissions=permissions,
    )


def _prompt(split: str, g: int, detail: str) -> str:
    # Details are operation-specific requests with concrete, user-visible task facts.
    # Do not add split-keyed phrasing or padding to alter prompt similarity.
    del split, g
    return detail


def _read_row(op: str, split: str, g: int, ids: dict[str, Any], state: dict[str, Any],
              fixture: dict[str, Any], now: datetime, *, variant: str = "full"):
    c, _, _, simulator, _ = baseline_modules()
    if variant not in {"full", "empty", "narrow"}:
        raise ValueError(f"unsupported read row variant: {variant}")
    activity_ref = ids["activity_refs"][0]
    if op == "read.activities":
        status = "any"
        name_filter = f"{_expense_title((g // 5) * 5)}协作组"
        if variant == "empty":
            name_filter = "不存在的协作活动标记"
        elif variant == "narrow":
            name_filter = state["activities"][0]["name"]
        criteria = c.ReadActivitiesCriteria(kind="activities", status=status, name_contains=name_filter)
        if variant == "empty":
            detail = (f"请查找名称带有“{name_filter}”标记的协作活动，并列出名称、类别与当前状态；"
                      f"status={status}；name_contains={name_filter}。")
        elif variant == "narrow":
            detail = (f"请只盘点名为“{name_filter}”的活动，列出名称、类别与当前状态；"
                      f"status={status}；name_contains={name_filter}。")
        else:
            detail = (f"请盘点名称带有“{name_filter}”标记的协作活动，列出各活动名称、类别与当前状态；"
                      f"status={status}；name_contains={name_filter}。")
        requested = {"status": status, "name_contains": name_filter}
    elif op == "read.expenses":
        from_date = to_date = selected_person = None
        title_filter = None
        if variant == "narrow":
            title_filter = state["expenses"][0]["title"]
        elif variant == "empty":
            title_filter = "不存在的费用标题T1"
        criteria = c.ReadExpensesCriteria(
            kind="expenses", activity_ref=activity_ref, from_date=from_date, to_date=to_date,
            participant_ref=selected_person,
        )
        place_group = (g % 15) // 5
        if variant == "empty":
            detail = (f"请查找标题包含“{title_filter}”的费用，并列出金额和币种；"
                      f"读取活动ref={activity_ref}的费用；全部日期；全部参与人；"
                      f"title_contains={title_filter}。")
        elif variant == "narrow":
            detail = (f"请核对标题含“{title_filter}”的费用，列出金额和币种；"
                      f"读取活动ref={activity_ref}的费用；全部日期；全部参与人；"
                      f"title_contains={title_filter}。")
        elif place_group == 0:
            detail = ("请列出该活动全部费用明细的标题、金额和币种，供我核账；"
                      f"读取活动ref={activity_ref}的费用；全部日期；全部参与人。")
        elif place_group == 1:
            detail = ("麻烦核对活动账下每笔支出，完整列出标题、金额与币种；"
                      f"读取活动ref={activity_ref}的费用；日期选全部日期；参与人范围为全部参与人。")
        else:
            detail = ("我需要活动的完整开销清单，请按可见明细逐条给出标题、金额和币种；"
                      f"读取活动ref={activity_ref}账下费用，时间不设限（全部日期），成员不设限（全部参与人）。")
        requested = {"date_scope": "all", "participant_scope": "all"}
        if title_filter is not None:
            requested["title_contains"] = title_filter
    else:
        debts = state["debts"]
        currency = debts[0]["currency"]
        person_ref = None
        if variant == "narrow":
            person_ref = state["participants"][0]["ref"]
        elif variant == "empty":
            currency = "CAD"
        criteria = c.ReadDebtsCriteria(
            kind="debts", activity_ref=activity_ref, participant_ref=person_ref, currency=currency,
        )
        topology = (g % 15) // 5
        focus = ("成员间逐段相连的欠款关系" if topology == 0 else
                 "成员间形成闭环的债务往来" if topology == 1 else
                 "由共同中心成员连接的债务关系")
        if variant == "empty":
            detail = ("请查找该活动中全部CAD欠款，核对每条债务方向与金额；"
                      f"读取活动ref={activity_ref}的债务；currency={currency}；participant_ref=全部成员。")
        elif variant == "narrow":
            detail = (f"请只查参与人ref={person_ref}关联的{currency}债务，并保留方向与金额；"
                      f"读取活动ref={activity_ref}的债务；currency={currency}；participant_ref={person_ref}。")
        else:
            detail = (f"请核对{focus}的完整{currency}明细，保留每条债务方向与金额；"
                      f"读取活动ref={activity_ref}的债务；currency={currency}；participant_ref=全部成员。")
        requested = {"currency": currency,
                     "participant_ref": person_ref if person_ref is not None else "全部成员"}
    decision = c.ReadDecision(kind="read", operation=op, criteria=criteria)
    prompt = _prompt(split, g, detail)
    current_permissions = state["activities"][0]["permissions"]
    first_context = _model_context(
        c, ids, prompt, op, activity_permissions=current_permissions,
        participant_allowlist=state["activities"][0]["member_allowlist"],
    )
    replay_key = f"t1-release-v2-{split}-{op.replace('.', '-')}-{g:03d}-read"
    result = simulator.simulate_read(fixture, decision, observed_at=now, context_version=1, replay_key=replay_key)
    simulator_path = SNAPSHOT_AGENT / "evaluation/data_simulator.py"
    tool = {
        "kind": "tool_result", "producer": "deterministic_synthetic_fixture", "fixture_state": fixture,
        "request": decision.model_dump(mode="json"), "observed_at": _iso(now), "context_version": 1,
        "replay_key": replay_key, "simulator_version": simulator.SIMULATOR_VERSION,
        "simulator_sha256": _file_sha(simulator_path), "result": result.model_dump(mode="json"),
    }
    facts = result.body.items
    answer_facts = facts
    if op == "read.expenses" and title_filter is not None:
        answer_facts = [item for item in facts if title_filter in item.title]
    if not answer_facts:
        answer = c.AnswerDecision(kind="answer", basis="conversation",
                                  text="按你给出的筛选条件，模拟查询没有匹配记录。", citations=[])
    else:
        if result.body.kind == "activities":
            lines = [f"{x.name}（{x.activity_kind.value}，{x.status.value}）" for x in answer_facts]
        elif result.body.kind == "expenses":
            lines = [f"{x.title}：{x.original_amount} {x.original_currency}" for x in answer_facts]
        else:
            lines = [f"{x.debtor_ref.value}→{x.creditor_ref.value}：{x.amount} {x.currency}" for x in answer_facts]
        citations = [x.evidence_ref for x in answer_facts]
        answer = c.AnswerDecision(kind="answer", basis="grounded",
                                  text=f"模拟查询得到{len(lines)}项：" + "；".join(lines) + "。",
                                  citations=citations)
    model_result = c.ModelReadResult(
        result_ref=result.result_ref, operation=result.operation, observed_at=result.observed_at,
        context_version=result.context_version, simulation=result.simulation, body=result.body,
    )
    second_context = _model_context(
        c, ids, prompt + " 已消费模拟工具回放结果，请按结果作答。", op,
        results=[model_result], activity_permissions=current_permissions,
        participant_allowlist=state["activities"][0]["member_allowlist"],
    )
    trace = [
        {"kind": "model", "context": first_context.model_dump(mode="json"), "target": decision.model_dump(mode="json")},
        tool,
        {"kind": "model", "context": second_context.model_dump(mode="json"), "target": answer.model_dump(mode="json")},
    ]
    scenario = {
        "operation": op, "criteria": decision.criteria.model_dump(mode="json"),
        "requested_values": requested,
        "result_origin": "deterministic_synthetic_fixture",
        "empty_result_citation_gap": not bool(answer_facts),
    }
    return prompt, trace, scenario

def _create_row(c, split_name: str, g: int, ids, state, amount_override=None):
    allowed = state["ledger_unit"]["participant_allowlist"]
    if amount_override is not None:
        # A release profile may pin the amount so that equal splitting leaves a
        # deterministic minor-unit tail.  The same value feeds the user request
        # and the proposal, so the two cannot disagree.
        amount_value = Decimal(amount_override)
    else:
        amount_value = Decimal("0.01") if g == 12 else Decimal(25 * max(1, len(allowed)))
    amount = f"{amount_value:.2f}"
    title = _expense_title(g)
    base_currency = state["ledger_unit"]["currency"]
    currency = base_currency
    if g == 12:
        payer_refs = [allowed[0]]
        split_refs = allowed[:3]
        split_intent = c.ManualSplitIntent(
            mode="manual", allocations=[c.ManualSplitAllocation(**item)
                                        for item in _even_allocations(amount, split_refs)])
    elif g % 7 == 0:
        payer_refs = [allowed[0]]
        split_refs = [allowed[0]]
        split_intent = c.EqualSplitIntent(mode="equal", participant_refs=split_refs)
    else:
        payer_refs = allowed[:1] if g % 3 == 0 else allowed[:2]
        payer_rows = _even_allocations(amount, payer_refs)
        if g % 2:
            split_refs = allowed
            split_intent = c.EqualSplitIntent(mode="equal", participant_refs=split_refs)
        else:
            split_refs = allowed
            split_intent = c.ManualSplitIntent(
                mode="manual", allocations=[c.ManualSplitAllocation(**item) for item in _even_allocations(amount, split_refs)])
    payments = _even_allocations(amount, payer_refs)
    fields = c.ExpenseCreateIntent(
        kind="expense.create", ledger_unit_ref=ids["unit_ref"], title=title,
        original_amount=amount, original_currency=currency,
        payment_allocations=[c.PaymentAllocation(**item) for item in payments], split=split_intent,
    )
    decision = c.ProposeDecision(kind="propose", operation="expense.create", fields=fields)
    payment_text = ",".join(f"{x['participant_ref']}={x['amount']}" for x in payments)
    split_text = (",".join(f"{x.participant_ref.value}={x.amount}" for x in fields.split.allocations)
                  if fields.split.mode == "manual" else ",".join(x.value for x in fields.split.participant_refs))
    split_kind = fields.split.mode
    detail = (f"按给定付款与分摊安排草拟费用“{title}”；新增费用标题“{title}”，"
              f"金额{amount} {currency}；付款[{payment_text}]；"
              f"分摊[{split_kind}:{split_text}]；ledger_unit_ref={ids['unit_ref']}。")
    prompt = _prompt(split_name, g, detail)
    target = decision.model_dump(mode="json")
    requested_values = {
        "title": title, "amount": amount, "currency": currency, "ledger_unit_ref": ids["unit_ref"],
        "payment_allocations": f"付款[{payment_text}]",
        "split": f"分摊[{split_kind}:{split_text}]",
    }
    return prompt, decision, {
        "operation": "expense.create", "target": target["fields"],
        "requested_values": requested_values,
        "request_relationship": "payment_and_split_are_explicit",
    }


def _update_row(c, op: str, split_name: str, g: int, ids, state):
    expense = state["expenses"][0]
    new_amount = f"{Decimal(expense['amount']) + Decimal(20 + (g % 13)):.2f}"
    new_currency = state["activities"][0]["base_currency"]
    refs = expense["participant_refs"]
    payments = _even_allocations(new_amount, refs[:1 if g % 2 == 0 else min(2, len(refs))])
    splits = _even_allocations(new_amount, refs)
    fields = c.ExpenseUpdateIntent(
        kind="expense.update", expense_ref=expense["ref"], original_amount=new_amount,
        original_currency=new_currency,
        payment_allocations=[c.PaymentAllocation(**item) for item in payments],
        split=c.ManualSplitIntent(mode="manual", allocations=[c.ManualSplitAllocation(**item) for item in splits]),
    )
    decision = c.ProposeDecision(kind="propose", operation=op, fields=fields)
    old_amount, old_currency = expense["amount"], expense["currency"]
    pay_text = ",".join(f"{x['participant_ref']}={x['amount']}" for x in payments)
    split_text = ",".join(f"{x['participant_ref']}={x['amount']}" for x in splits)
    detail = (f"调整费用名称“{expense['title']}”对应的账目；更正费用ref={expense['ref']}："
              f"原额{old_amount} {old_currency}；"
              f"新额{new_amount} {new_currency}；付款[{pay_text}]；分摊[manual:{split_text}]。")
    prompt = _prompt(split_name, g, detail)
    target = decision.model_dump(mode="json")
    requested_values = {
        "expense_ref": expense["ref"], "original_amount": new_amount, "original_currency": new_currency,
        "payment_allocations": f"付款[{pay_text}]", "split": f"分摊[manual:{split_text}]",
    }
    return prompt, decision, {
        "operation": op, "target": target["fields"], "requested_values": requested_values,
        "request_relationship": "financial_update_explicit_and_conserved",
    }


def _presentation_row(c, split: str, g: int, ids, state):
    """Return the ambiguous initial request and final proposal; caller builds turns."""
    icon = ("receipt", "meal", "ticket", "transport", "lodging")[g % 5]
    title = _expense_title(g + len(EXPENSE_TITLE_PLACES))
    query_title = state["expenses"][0]["title"]
    selected = state["expenses"][g % len(state["expenses"])]
    fields = c.ExpensePresentationUpdateIntent(
        kind="expense.presentation.update", expense_ref=selected["ref"],
        title=title, icon_key=icon,
    )
    decision = c.ProposeDecision(kind="propose", operation="expense.presentation.update", fields=fields)
    detail = (f"把标题为“{query_title}”的那笔费用展示改为title=“{title}”；"
              f"icon_key={icon}；仅调整卡片展示字段。")
    prompt = _prompt(split, g, detail)
    return prompt, decision, {
        "operation": "expense.presentation.update",
        "target": decision.model_dump(mode="json")["fields"],
        "requested_values": {"query_title": query_title, "title": title, "icon_key": icon},
        "request_relationship": "presentation_fields_only",
        "interaction": (
            "clarify_ambiguous_expense_ref_then_continue"
            if len(state["expenses"]) > 1 else "unique_title_match_direct_proposal"
        ),
        "request_completed_across_turns": len(state["expenses"]) > 1,
    }


def _proposal_prelude(c, op: str, prompt: str, ids, state, fixture, now, sample_key):
    """A read decision/result makes initial activity or expense facts model-visible."""
    _, _, _, simulator, _ = baseline_modules()
    if op == "expense.create":
        read_op = "read.activities"
        request = c.ReadDecision(
            kind="read", operation=read_op,
            criteria=c.ReadActivitiesCriteria(kind="activities", status="any"),
        )
    else:
        read_op = "read.expenses"
        request = c.ReadDecision(
            kind="read", operation=read_op,
            criteria=c.ReadExpensesCriteria(kind="expenses", activity_ref=ids["activity_refs"][0]),
        )
    now_text = _iso(now)
    current_permissions = state["activities"][0]["permissions"]
    participant_scope = state["ledger_unit"]["participant_allowlist"]
    first_context = _model_context(
        c, ids, prompt, op, activity_permissions=current_permissions,
        participant_allowlist=participant_scope,
    )
    result = simulator.simulate_read(fixture, request, observed_at=now_text,
                                     context_version=1, replay_key=sample_key + "-initial-read")
    tool = {
        "kind": "tool_result", "producer": "deterministic_synthetic_fixture",
        "fixture_state": fixture, "request": request.model_dump(mode="json"),
        "observed_at": now_text, "context_version": 1,
        "replay_key": sample_key + "-initial-read",
        "simulator_version": simulator.SIMULATOR_VERSION,
        "simulator_sha256": _file_sha(SNAPSHOT_AGENT / "evaluation/data_simulator.py"),
        "result": result.model_dump(mode="json"),
    }
    model_result = c.ModelReadResult(
        result_ref=result.result_ref, operation=result.operation, observed_at=result.observed_at,
        context_version=result.context_version, simulation=result.simulation, body=result.body,
    )
    final_context = _model_context(
        c, ids, prompt + " 已读取并消费当前状态结果，再按明确参数生成草案。",
        op, results=[model_result], activity_permissions=current_permissions,
        participant_allowlist=participant_scope,
    )
    return [
        {"kind": "model", "context": first_context.model_dump(mode="json"),
         "target": request.model_dump(mode="json")},
        tool,
    ], final_context


def _make_record(op: str, g: int, *, read_variant: str = "full",
                 amount_override: str | None = None, variant_tag: str = "",
                 clarification_policy: str = "expense_ref",
                 gold_validator=None,
                 state_overrides: dict[str, Any] | None = None,
                 participant_count_override: int | None = None) -> dict[str, Any]:
    c, _, signature, simulator, validator_module = baseline_modules()
    if read_variant != "full" and op not in {"read.activities", "read.expenses", "read.debts"}:
        raise ValueError("read variants are supported only for read operations")
    if amount_override is not None and op != "expense.create":
        raise ValueError("an explicit amount override is supported only for expense.create")
    if variant_tag and "/" in variant_tag:
        raise ValueError("variant tag must be a plain label")
    if clarification_policy not in {"expense_ref", "returned_facts"}:
        raise ValueError("unsupported clarification policy")
    if clarification_policy != "expense_ref" and op != "expense.presentation.update":
        raise ValueError("the returned-facts clarification policy applies to presentation updates")
    split = _split_for(op, g)
    row_idx = g % 20
    if op in {"expense.create", "expense.update"}:
        eligible_count = 1 + (g % 12)
        base_people = eligible_count + int(_unit_role_for(g) == "large_child")
    elif op == "read.debts":
        base_people = 3 + ((g % 15) % 5)
    else:
        base_people = 2
    if participant_count_override is not None:
        # A release profile may widen the participant set so a designated
        # allocation can be exercised at a specific headcount.
        if participant_count_override < 1:
            raise ValueError("participant count override must be positive")
        base_people = int(participant_count_override)
    activity_count = 1 + (g % 15) if op == "read.activities" else 1
    expense_count = (
        1 + (g % 15) if op == "read.expenses" else
        1 if op == "expense.update" else
        _debt_edge_count(g) if op == "read.debts" else
        _presentation_catalogue_row(g)[0] if op == "expense.presentation.update" else 0
    )
    ids = _binding_map(op, g, activity_count=activity_count, participant_count=base_people,
                       expense_count=expense_count)
    state = _make_state(op, g, ids, state_overrides=state_overrides)
    fixture = _fixture_from_state(op, g, state)
    now = datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(days=g)
    if op.startswith("read."):
        prompt, trace, scenario = _read_row(
            op, split, g, ids, state, fixture, now, variant=read_variant,
        )
        semantic, operation, task_operation, must_complete = "answer", None, op, True
    else:
        if op == "expense.create":
            prompt, decision, scenario = _create_row(
                c, split, g, ids, state, amount_override=amount_override,
            )
        elif op == "expense.update":
            prompt, decision, scenario = _update_row(c, op, split, g, ids, state)
        else:
            prompt, decision, scenario = _presentation_row(c, split, g, ids, state)
        sample_key = f"t1-release-v2-{split}-{op.replace('.', '-')}-{g:03d}"
        prelude, replayed_context = _proposal_prelude(
            c, op, prompt, ids, state, fixture, now, sample_key,
        )
        if op == "expense.presentation.update":
            raw_target = decision.model_dump(mode="json")["fields"]
            if len(state["expenses"]) > 1:
                read_rows = replayed_context.read_results[0].body.items
                candidates = [
                    item.model_dump(mode="json") for item in read_rows
                    if item.title == scenario["requested_values"]["query_title"]
                ]
                if len(candidates) != len(state["expenses"]) or len(candidates) < 2:
                    raise ValueError("presentation ambiguity candidates do not match replayed facts")
                if clarification_policy == "expense_ref":
                    candidate_text = "，".join(
                        "|".join((
                            item["expense_ref"], item["original_currency"],
                            ",".join(item["participant_refs"]),
                            "是" if item["financial_locked"] else "否",
                        ))
                        for item in candidates
                    )
                    clarification_prompt = (
                        f"请求标题=“{scenario['requested_values']['query_title']}”；"
                        f"候选(ref|currency|participant_refs|financial_locked)={candidate_text}；"
                        "请回复其中一个expense_ref。"
                    )
                    followup = f"expense_ref={raw_target['expense_ref']}。"
                else:
                    # RBR03: name each candidate by the facts the user can see,
                    # never by the internal reference.
                    def describe(item):
                        return (
                            f"“{item['title']}”（日期 {item['occurred_at'][:10]}，"
                            f"金额 {item['original_amount']} {item['original_currency']}，"
                            f"参与人 {','.join(item['participant_refs'])}）"
                        )

                    candidate_text = "；".join(describe(item) for item in candidates)
                    clarification_prompt = (
                        f"有 {len(candidates)} 笔同名费用：{candidate_text}。"
                        "请用日期或金额说明要修改哪一笔。"
                    )
                    selected = next(
                        (item for item in candidates
                         if item["expense_ref"] == raw_target["expense_ref"]),
                        None,
                    )
                    if selected is None:
                        raise ValueError("presentation target is not among the returned candidates")
                    if any(
                        item is not selected
                        and item["occurred_at"] == selected["occurred_at"]
                        and item["original_amount"] == selected["original_amount"]
                        for item in candidates
                    ):
                        raise ValueError("returned facts do not uniquely identify the selected candidate")
                    followup = (
                        f"改日期 {selected['occurred_at'][:10]}、"
                        f"金额 {selected['original_amount']} {selected['original_currency']} 的那一笔。"
                    )
                clarification = c.ClarifyDecision(
                    kind="clarify", prompt=clarification_prompt,
                    missing_slots=[c.ClarificationSlot.EXPENSE],
                )
                followup_step = {"kind": "user_followup", "text": followup}
                final_context = c.ModelContext(
                    context_version=replayed_context.context_version,
                    input_text=followup,
                    verified_scope=replayed_context.verified_scope,
                    recent_messages=[
                        c.PriorMessage(role="user", text=prompt),
                        c.PriorMessage(role="assistant", text=clarification.prompt),
                        c.PriorMessage(role="user", text=followup),
                    ],
                    pending_slots=[],
                    bound_references=replayed_context.bound_references,
                    read_results=replayed_context.read_results,
                    policy_evidence=replayed_context.policy_evidence,
                    available_permissions=replayed_context.available_permissions,
                )
                trace = prelude + [
                    {"kind": "model", "context": replayed_context.model_dump(mode="json"),
                     "target": clarification.model_dump(mode="json")},
                    followup_step,
                    {"kind": "model", "context": final_context.model_dump(mode="json"),
                     "target": decision.model_dump(mode="json")},
                ]
            else:
                final_context = replayed_context
                trace = prelude + [{"kind": "model", "context": final_context.model_dump(mode="json"),
                                    "target": decision.model_dump(mode="json")}]
        else:
            final_context = replayed_context
            trace = prelude + [{"kind": "model", "context": final_context.model_dump(mode="json"),
                                "target": decision.model_dump(mode="json")}]
        semantic, operation, task_operation, must_complete = "propose", op, op, True

    variant_suffix = f"-read-{read_variant}" if read_variant != "full" else ""
    tag_suffix = f"-{variant_tag}" if variant_tag else ""
    sid = f"t1-v2-{split}-{op.replace('.', '-')}-{g:03d}{variant_suffix}{tag_suffix}"
    family = f"state-family-t1-v2-{split}-{op.replace('.', '-')}-{g:03d}"
    record = {
        "schema_version": "shared-ledger-agent-t1-sample-v1",
        "sample_id": sid, "state_family_id": family, "split": split,
        "case_type": (
            "multi_turn" if op == "expense.presentation.update" and len(state["expenses"]) > 1
            else "supported_operation"
        ),
        "capability_ids": CAPABILITY[op],
        "expected": {
            "supported_in_v1": True, "semantic": semantic, "operation": operation,
            "task_operation": task_operation, "must_complete": must_complete,
        },
        "trace": trace, "data_origin": "synthetic", "replay_status": "simulated",
        "protocol_fingerprint_sha256": _file_sha(SNAPSHOT_AGENT / "dataset_contracts/t1/protocol-fingerprint.json"),
        "fixture_state": fixture, "fixture_state_sha256": hashlib.sha256(signature.canonical_json(fixture)).hexdigest(),
        "business_source_revision": "3f938ee6114b763e6cd3dbd10792a78c691eb526",
        "generator_version": "t1-synth-2.0.0", "teacher_candidate_id": None,
        "review": {
            "status": "auto_validated", "reviewer_kind": "agent", "reviewer_id": "t1-release-v2-checker",
            "independent_root_review": "pending", "human_review_pending": True, "training_eligible": False,
            "review_note": "Synthetic candidate. Automated checks are not human review; pending independent review.",
        },
        "normalized_state_signature_sha256": "0" * 64,
        "normalized_scenario_signature_sha256": "0" * 64,
        "coverage_tags": ["synthetic-positive", op.replace(".", "-"), f"family-{row_idx:02d}"]
                          + ([f"read-{read_variant}"] if read_variant != "full" else [])
                          + ([variant_tag] if variant_tag else []),
        "release_version": "t1-release-v2",
        "operation_state": state,
        "scenario": scenario,
        "operation_state_signature_sha256": operation_state_signature(state, op),
        "scenario_signature_sha256": sha256(scenario),
        "canonicalization_version": "operation-graph-v2",
        "baseline_snapshot_manifest_sha256": SNAPSHOT_MANIFEST_SHA256,
    }
    record["normalized_state_signature_sha256"] = hashlib.sha256(
        signature.canonical_json(signature.fixture_projection(fixture))
    ).hexdigest()
    record["normalized_scenario_signature_sha256"] = hashlib.sha256(
        signature.canonical_json(signature.scenario_projection(fixture, record))
    ).hexdigest()
    (gold_validator or validate_operation_gold)(record)
    validator = make_v2_validator()
    validator_module.validate_record(record, validator)
    return record


def _multiturn_create_record(g: int) -> dict[str, Any]:
    c, _, signature, _, validator_module = baseline_modules()
    split = SPLITS[g // 20]
    # Reuse the same initial-state catalogue family as the one-turn create row.
    # This adds a dialogue variant without introducing a second state family.
    people_count = 1 + (g % 12) + int(_unit_role_for(g) == "large_child")
    ids = _binding_map("expense.create", g, activity_count=1,
                       participant_count=people_count, expense_count=0)
    state = _make_state("expense.create", g, ids)
    fixture = _fixture_from_state("expense.create", g, state)
    _, seed_decision, scenario = _create_row(c, split, g, ids, state)
    seed_fields = seed_decision.fields
    allowed = state["ledger_unit"]["participant_allowlist"]
    payer_ref = allowed[0]
    split_refs = list(allowed)
    amount = seed_fields.original_amount
    currency = seed_fields.original_currency
    title = seed_fields.title
    fields = c.ExpenseCreateIntent(
        kind="expense.create", ledger_unit_ref=ids["unit_ref"], title=title,
        original_amount=amount, original_currency=currency,
        payment_allocations=[c.PaymentAllocation(participant_ref=payer_ref, amount=amount)],
        split=c.EqualSplitIntent(mode="equal", participant_refs=split_refs),
    )
    decision = c.ProposeDecision(kind="propose", operation="expense.create", fields=fields)
    payment_text = f"付款[{payer_ref}={amount}]"
    split_text = "分摊[equal:" + ",".join(split_refs) + "]"
    initial_detail = (
        f"新增费用标题“{title}”；ledger_unit_ref={ids['unit_ref']}；"
        f"付款人[{payer_ref}]；{split_text}；"
        "总金额待确认，请勿根据付款人与分摊推定总金额。"
    )
    initial_prompt = _prompt(split, g, initial_detail)
    now = datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(days=g)
    sample_key = f"t1-release-v2-{split}-expense-create-multiturn-{g:03d}"
    prelude, clarified_context = _proposal_prelude(
        c, "expense.create", initial_prompt, ids, state, fixture, now, sample_key,
    )
    clarification = c.ClarifyDecision(
        kind="clarify", prompt="请提供费用总金额；付款人和分摊方式不能推出总金额。",
        missing_slots=[c.ClarificationSlot.AMOUNT],
    )
    followup = f"金额补充为{amount} {currency}。"
    clarify_step = {
        "kind": "model", "context": clarified_context.model_dump(mode="json"),
        "target": clarification.model_dump(mode="json"),
    }
    followup_step = {"kind": "user_followup", "text": followup}
    final_context = c.ModelContext(
        context_version=clarified_context.context_version,
        input_text=followup,
        verified_scope=clarified_context.verified_scope,
        recent_messages=[
            c.PriorMessage(role="user", text=initial_prompt),
            c.PriorMessage(role="assistant", text=clarification.prompt),
            c.PriorMessage(role="user", text=followup),
        ],
        pending_slots=[],
        bound_references=clarified_context.bound_references,
        read_results=clarified_context.read_results,
        policy_evidence=clarified_context.policy_evidence,
        available_permissions=clarified_context.available_permissions,
    )
    trace = prelude + [clarify_step, followup_step, {
        "kind": "model", "context": final_context.model_dump(mode="json"),
        "target": decision.model_dump(mode="json"),
    }]
    scenario.update({
        "requested_values": {
            "title": title, "amount": amount, "currency": currency,
            "ledger_unit_ref": ids["unit_ref"],
            "payment_allocations": payment_text, "split": split_text,
        },
        "interaction": "clarify_only_missing_amount_then_continue",
        "request_completed_across_turns": True,
    })
    # Keep the duplicated scenario target aligned with the final proposal after
    # clarification, rather than with the seed's one-turn create proposal.
    scenario["target"] = decision.model_dump(mode="json")["fields"]
    sid = f"t1-v2-{split}-expense-create-multiturn-{g:03d}"
    record = {
        "schema_version": "shared-ledger-agent-t1-sample-v1",
        "sample_id": sid, "state_family_id": f"state-family-t1-v2-{split}-expense-create-{g:03d}",
        "split": split, "case_type": "multi_turn", "capability_ids": ["CAP07"],
        "expected": {"supported_in_v1": True, "semantic": "propose", "operation": "expense.create",
                     "task_operation": "expense.create", "must_complete": True},
        "trace": trace, "data_origin": "synthetic", "replay_status": "simulated",
        "protocol_fingerprint_sha256": _file_sha(SNAPSHOT_AGENT / "dataset_contracts/t1/protocol-fingerprint.json"),
        "fixture_state": fixture,
        "fixture_state_sha256": hashlib.sha256(signature.canonical_json(fixture)).hexdigest(),
        "business_source_revision": "3f938ee6114b763e6cd3dbd10792a78c691eb526",
        "generator_version": "t1-synth-2.0.0", "teacher_candidate_id": None,
        "review": {
            "status": "auto_validated", "reviewer_kind": "agent", "reviewer_id": "t1-release-v2-checker",
            "independent_root_review": "pending", "human_review_pending": True, "training_eligible": False,
            "review_note": "Synthetic multi-turn candidate; amount alone was missing. Human review pending.",
        },
        "normalized_state_signature_sha256": "0" * 64,
        "normalized_scenario_signature_sha256": "0" * 64,
        "coverage_tags": ["synthetic-positive", "expense-create", "clarify-then-carry", "proposal-only"],
        "release_version": "t1-release-v2", "operation_state": state, "scenario": scenario,
        "operation_state_signature_sha256": operation_state_signature(state, "expense.create"),
        "scenario_signature_sha256": sha256(scenario),
        "canonicalization_version": "operation-graph-v2",
        "baseline_snapshot_manifest_sha256": SNAPSHOT_MANIFEST_SHA256,
    }
    record["normalized_state_signature_sha256"] = hashlib.sha256(
        signature.canonical_json(signature.fixture_projection(fixture))
    ).hexdigest()
    record["normalized_scenario_signature_sha256"] = hashlib.sha256(
        signature.canonical_json(signature.scenario_projection(fixture, record))
    ).hexdigest()
    validate_operation_gold(record)
    validator_module.validate_record(record, make_v2_validator())
    return record


def generate_candidate_records() -> dict[str, list[dict[str, Any]]]:
    """Build records in memory and independently validate each before any file write."""
    result = {split: [] for split in SPLITS}
    for op in OPERATIONS:
        for g in range(60):
            record = _make_record(op, g)
            result[record["split"]].append(record)
    # One focused multi-turn case per split exercises exactly-one-slot clarification
    # and exact field carry into the final proposal. It is additional to the 20 unique
    # state families per operation floor, not counted as a new family.
    for g in (1, 22, 41):
        row = _multiturn_create_record(g)
        result[row["split"]].append(row)
    # Empty and narrow read examples reuse an existing in-split family state.
    # They exercise answer/citation behavior without increasing the positive
    # family floor for any operation.
    read_extra_sources = {
        "read.activities": 14,
        "read.expenses": 4,
        "read.debts": 0,
    }
    for op, g in read_extra_sources.items():
        for variant in ("empty", "narrow"):
            row = _make_record(op, g, read_variant=variant)
            result[row["split"]].append(row)
    return result

