"""Canonical state-family projection for T1 leakage checks."""
from __future__ import annotations

import json
from typing import Any

from agent.evaluation.data_simulator import SyntheticFixture


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def fixture_projection(fixture_state: dict[str, Any]) -> dict[str, Any]:
    """Drop IDs, names, dates, amounts, and wording while retaining business state shape."""
    fixture = SyntheticFixture.model_validate(fixture_state)
    activity_index = {row.activity_ref.value: index for index, row in enumerate(fixture.activities)}
    participant_index: dict[str, int] = {}

    def participant(ref: Any) -> int:
        key = ref.value if hasattr(ref, "value") else str(ref)
        if key not in participant_index:
            participant_index[key] = len(participant_index)
        return participant_index[key]

    activities = [
        {"kind": row.activity_kind.value, "status": row.status.value, "currency": row.base_currency}
        for row in fixture.activities
    ]
    expenses = []
    for row in fixture.expenses:
        expenses.append({
            "activity": activity_index[row.activity_ref.value],
            "locked": row.financial_locked,
            "currency": row.original_currency,
            "participants": sorted(participant(ref) for ref in row.participant_refs),
        })
    debts = []
    for row in fixture.debts:
        debts.append({
            "activity": activity_index[row.activity_ref.value],
            "debtor": participant(row.debtor_ref),
            "creditor": participant(row.creditor_ref),
            "currency": row.currency,
        })

    return {"fixture": {"activities": activities, "expenses": expenses, "debts": debts}}


def scenario_projection(fixture_state: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """Keep task/trajectory shape separately; labels never make a fixture independent."""
    targets = []
    model_context_shapes = []
    tool_shapes = []
    followup_count = 0
    for step in record["trace"]:
        if step["kind"] == "tool_result":
            result = step["result"]
            tool_shapes.append({"operation": result["operation"], "body_kind": result["body"]["kind"], "result_count": len(result["body"]["items"])})
            continue
        if step["kind"] == "user_followup":
            followup_count += 1
            continue
        if step["kind"] != "model":
            continue
        target = step["target"]
        ctx = step["context"]
        reference_counts: dict[str, int] = {}
        for reference in ctx["bound_references"]:
            reference_counts[reference["kind"]] = reference_counts.get(reference["kind"], 0) + 1
        model_context_shapes.append({
            "scope": ctx["verified_scope"]["kind"],
            "reference_counts": reference_counts,
            "permission_count": len(ctx["available_permissions"]),
            "pending_slot_count": len(ctx["pending_slots"]),
            "read_result_shapes":[{"operation": result["operation"], "body_kind": result["body"]["kind"], "item_count": len(result["body"]["items"])} for result in ctx["read_results"]],
        })
        if target["kind"] == "read":
            criteria = target["criteria"]
            targets.append({
                "kind": "read",
                "operation": target["operation"],
                "criteria_kind": criteria["kind"],
                "filters": sorted(key for key, value in criteria.items() if key != "kind" and value is not None and value != "any"),
                "participant_filter": criteria.get("participant_ref") is not None,
                "currency_filter": criteria.get("currency") is not None,
                "date_filter": criteria.get("from_date") is not None or criteria.get("to_date") is not None,
                "name_filter": criteria.get("name_contains") is not None,
            })
        elif target["kind"] == "propose":
            fields = target["fields"]
            targets.append({
                "kind": "propose",
                "operation": target["operation"],
                "fields": sorted(key for key, value in fields.items() if key not in {"kind", "expense_ref", "ledger_unit_ref"} and value is not None),
                "payment_count": len(fields.get("payment_allocations") or []),
                "split_mode": fields.get("split", {}).get("mode") if isinstance(fields.get("split"), dict) else None,
                "split_count": len(fields.get("split", {}).get("participant_refs", fields.get("split", {}).get("allocations", []))) if isinstance(fields.get("split"), dict) else 0,
            })
        else:
            targets.append({"kind": target["kind"], "missing_slots": target.get("missing_slots", [])})

    return {
        "case_type": record["case_type"],
        "task_operation": record["expected"]["task_operation"],
        "targets": targets,
        "model_context_shapes": model_context_shapes,
        "tool_shapes": tool_shapes,
        "user_followup_count": followup_count,
        "policy_rules": sorted({p["rule"] for step in record["trace"] if step["kind"] == "model" for p in step["context"].get("policy_evidence", [])}),
        "scope_shape": sorted({step["context"]["verified_scope"]["kind"] for step in record["trace"] if step["kind"] == "model"}),
    }
