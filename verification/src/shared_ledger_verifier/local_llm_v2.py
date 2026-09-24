"""Focused, one-shot local Scenario JSON v1 probe; never executes scenarios."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .loader import ScenarioValidationError, load_scenario
from .local_llm import LocalLLMClient, LocalLLMError, _response_format
from .models import CreateExpense, CreatePrepayment, LinkedRefund, TargetedRepayment
from .runner import _business_logic_commit
from .supabase import verification_root


FOCUS_SECTIONS: dict[str, tuple[int, ...]] = {
    "expense_aa": (5, 6, 7, 8),
    "targeted_repayment": (5, 6, 8, 9, 10, 11),
    "prepayment_refund": (5, 6, 8, 9, 11, 12, 13, 16),
}
_HEADING = re.compile(r"^##[ \t]+(\d+)\.[ \t]+([^\r\n]+?)[ \t]*$", re.MULTILINE)
_REF = {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,63}$"}
_MONEY = {"type": "string", "pattern": "^-?(?:0|[1-9][0-9]*)(?:\\.[0-9])?$"}
_POSITIVE_MONEY = {"type": "string", "pattern": "^(?:0\\.[1-9]|[1-9][0-9]*(?:\\.[0-9])?)$"}
_NEGATIVE_MONEY = {"type": "string", "pattern": "^-(?:0\\.[1-9]|[1-9][0-9]*(?:\\.[0-9])?)$"}


def select_business_sections(document: str, focus: str) -> tuple[list[str], str]:
    """Select actual level-two Markdown sections by parsed section number."""
    if focus not in FOCUS_SECTIONS:
        raise LocalLLMError("INVALID_FOCUS")
    matches = list(_HEADING.finditer(document))
    found: dict[int, tuple[str, str]] = {}
    for index, match in enumerate(matches):
        number = int(match.group(1))
        if number in found:
            raise LocalLLMError("BUSINESS_LOGIC_SECTION_DUPLICATE")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(document)
        found[number] = (match.group(0), document[match.start():end].strip())
    if any(number not in found for number in FOCUS_SECTIONS[focus]):
        raise LocalLLMError("BUSINESS_LOGIC_SECTION_MISSING")
    selected = [found[number] for number in FOCUS_SECTIONS[focus]]
    return [heading for heading, _ in selected], "\n\n".join(body for _, body in selected)


def _schema(focus: str) -> dict[str, Any]:
    def variant(operation_type: str, fields: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "object", "additionalProperties": False,
            "properties": {"type": {"const": operation_type}, "ref": _REF, **fields},
            "required": ["type", "ref", *fields],
        }

    money_fields = {"amount": _POSITIVE_MONEY, "currency": {"const": "CNY"}}
    expense_fields = {
        "title": {"type": "string"}, **money_fields,
        "payments": {"type": "object", "minProperties": 1, "additionalProperties": _POSITIVE_MONEY},
    }
    manual = {**expense_fields, "split_method": {"const": "manual"},
              "splits": {"type": "object", "minProperties": 1, "additionalProperties": _POSITIVE_MONEY}}
    refund_fields = {
        **manual, "amount": _NEGATIVE_MONEY,
        "payments": {"type": "object", "minProperties": 1, "additionalProperties": _NEGATIVE_MONEY},
        "splits": {"type": "object", "minProperties": 1, "additionalProperties": _NEGATIVE_MONEY},
        "original_expense_ref": _REF,
    }
    variants = {
        "expense_aa": [variant("create_expense", {
            **expense_fields, "split_method": {"const": "aa"},
            "aa_participants": {"type": "array", "items": _REF, "minItems": 1},
        })],
        "targeted_repayment": [
            variant("create_expense", manual),
            variant("targeted_repayment", {
                **money_fields, "from_participant": _REF, "to_participant": _REF,
                "target_expense_refs": {"type": "array", "items": _REF, "minItems": 1},
            }),
        ],
        "prepayment_refund": [
            variant("create_prepayment", {
                **money_fields, "owner_participant": _REF, "custodian_participant": _REF,
            }),
            variant("create_expense", manual),
            variant("linked_refund", refund_fields),
        ],
    }[focus]
    operation = {"oneOf": variants}
    count = {"expense_aa": 1, "targeted_repayment": 2, "prepayment_refund": 3}[focus]
    return {
        "type": "object", "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "integer", "enum": [1]},
            "scenario_id": _REF, "description": {"type": "string"},
            "activity": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "type": {"type": "string", "enum": ["normal"]},
                    "base_currency": {"type": "string", "enum": ["CNY"]},
                    "multi_currency_enabled": {"type": "boolean", "enum": [False]},
                },
                "required": ["type", "base_currency", "multi_currency_enabled"],
            },
            "participants": {"type": "array", "items": _REF, "minItems": 3,
                             "maxItems": 3 if focus == "expense_aa" else 4},
            "operations": {"type": "array", "items": operation, "minItems": count, "maxItems": count},
        },
        "required": ["schema_version", "scenario_id", "description", "activity", "participants", "operations"],
    }


def _messages(focus: str, sections: str) -> list[dict[str, str]]:
    task = {
        "expense_aa": (
            "Use participants A, B, C. Exactly one create_expense in CNY, with two or three distinct "
            "positive payers whose payments sum to the amount. Use split_method aa and "
            "aa_participants [A, B, C]; omit splits. No repayment, refund, or prepayment."
        ),
        "targeted_repayment": (
            "Use three or four participants. Exactly two operations in this order: create_expense "
            "then targeted_repayment. A pays 100.0 CNY for B using manual splits; B repays A 40.0 "
            "CNY with target_expense_refs containing only the preceding expense ref. This is strictly "
            "partial repayment. Other participants may have no share."
        ),
        "prepayment_refund": (
            "Use three or four participants. Exactly three operations in this order: "
            "create_prepayment, create_expense, linked_refund. For example B may prepay A 50.0 CNY "
            "(B owner, A custodian), A then pays 120.0 CNY for an expense split B 60.0 and C 60.0; "
            "a later 30.0 CNY refund paid back to A and benefiting B references that earlier expense. "
            "Represent linked_refund amount, payments and manual splits as negative decimal strings. "
            "For create_prepayment use owner_participant and custodian_participant, not from/to. "
            "For linked_refund use original_expense_ref, not target_expense_refs."
        ),
    }[focus]
    common = (
        "Generate exactly one NEW Scenario JSON v1 object. Use the envelope schema_version=1, "
        "scenario_id, description, activity, participants, operations. Activity: type normal, "
        "base_currency CNY, multi_currency_enabled false. All monetary values must be JSON strings "
        "with at most one fractional digit for CNY. Use unique short refs. For each expense, "
        "payments must sum exactly to its signed amount; manual splits must also sum exactly. "
        "Use only fields needed for each operation. No UUID, SQL, JWT, financial_version, "
        "request_id, expected_result, Judge verdict, or database internal fields. Return JSON only.\n\n"
    )
    return [
        {"role": "system", "content": "Generate Shared Ledger Scenario JSON v1 using the supplied current BUSINESS_LOGIC.md sections as the only business-rule source. Output final JSON content only."},
        {"role": "user", "content": common + task + "\n\nRelevant BUSINESS_LOGIC.md sections:\n" + sections},
    ]


def _focus_error(scenario: Any, focus: str) -> str | None:
    if (scenario.activity.type != "normal" or scenario.activity.base_currency != "CNY"
            or scenario.activity.multi_currency_enabled or not 3 <= len(scenario.participants) <= 4):
        return "FOCUS_MISMATCH: expected normal CNY activity with 3-4 participants"
    operations = scenario.operations
    if focus == "expense_aa":
        if len(scenario.participants) != 3 or len(operations) != 1 or not isinstance(operations[0], CreateExpense):
            return "FOCUS_MISMATCH: expected 3 participants and one expense"
        expense = operations[0]
        if (expense.split_method != "aa" or set(expense.aa_participants) != set(scenario.participants)
                or len(expense.payments) not in {2, 3} or any(amount <= 0 for amount in expense.payments.values())):
            return "FOCUS_MISMATCH: expected all-participant AA and 2-3 positive payers"
    elif focus == "targeted_repayment":
        if (len(operations) != 2 or not isinstance(operations[0], CreateExpense)
                or not isinstance(operations[1], TargetedRepayment)):
            return "FOCUS_MISMATCH: expected expense followed by targeted repayment"
        expense, repayment = operations
        if repayment.target_expense_refs != (expense.ref,):
            return "FOCUS_MISMATCH: repayment must reference the prior expense"
        debtor_due = (expense.splits or {}).get(repayment.from_participant, 0) - expense.payments.get(repayment.from_participant, 0)
        creditor_due = expense.payments.get(repayment.to_participant, 0) - (expense.splits or {}).get(repayment.to_participant, 0)
        if not 0 < repayment.amount < min(debtor_due, creditor_due):
            return "FOCUS_MISMATCH: repayment must be strictly partial against the selected debt"
    else:
        if (len(operations) != 3 or not isinstance(operations[0], CreatePrepayment)
                or not isinstance(operations[1], CreateExpense) or not isinstance(operations[2], LinkedRefund)):
            return "FOCUS_MISMATCH: expected prepayment, expense, linked refund in order"
        expense, refund = operations[1:]
        if refund.original_expense_ref != expense.ref or -refund.amount > expense.amount:
            return "FOCUS_MISMATCH: refund must reference the preceding expense and stay within its amount"
    return None


def run_probe_v2(*, client: LocalLLMClient | None = None, output_dir: Path | None = None,
                 business_logic_path: Path | None = None) -> dict[str, Any]:
    client = client or LocalLLMClient.from_env()
    output_dir = output_dir or verification_root() / "local_llm_probe"
    business_logic_path = business_logic_path or verification_root().parent / "docs/backend/BUSINESS_LOGIC.md"
    output_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "probe_version": "2.1", "timestamp": datetime.now(timezone.utc).isoformat(),
        "base_url": client.base_url, "request_timeout_seconds": client.timeout,
        "model": None, "model_ids": [], "business_logic_commit": _business_logic_commit(),
        "focus_results": {}, "error_category": None, "ready": False,
    }

    def save() -> dict[str, Any]:
        result["ready"] = len(result["focus_results"]) == 3 and all(
            entry["status"] == "VALID" for entry in result["focus_results"].values()
        ) and result["error_category"] is None
        (output_dir / "probe_v2_1_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return result

    try:
        document = business_logic_path.read_text(encoding="utf-8")
        selected = {focus: select_business_sections(document, focus) for focus in FOCUS_SECTIONS}
        ids, status, elapsed = client.models()
        result["model_ids"] = ids
        result["models_request"] = {"http_status": status, "elapsed_seconds": elapsed}
        result["model"] = client.select_model(ids)
    except OSError:
        result["error_category"] = "BUSINESS_LOGIC_UNAVAILABLE"
        return save()
    except LocalLLMError as error:
        result["error_category"] = error.category
        return save()

    for focus, (headings, text) in selected.items():
        messages = _messages(focus, text)
        entry: dict[str, Any] = {
            "focus": focus, "business_logic_sections": headings,
            "business_logic_characters": len(text),
            "input_characters": sum(len(message["content"]) for message in messages),
            "prompt_tokens": None, "completion_tokens": None,
            "elapsed_seconds": None, "loader_status": None, "status": None,
            "error_category": None,
        }
        result["focus_results"][focus] = entry
        save()
        try:
            completion = client.complete(
                messages, max_tokens=1536,
                response_format=_response_format(f"shared_ledger_{focus}_v1", _schema(focus)),
            )
            entry.update(completion.usage)
            entry["elapsed_seconds"] = completion.elapsed_seconds
            path = output_dir / f"generated_v2_1_{focus}.json"
            path.write_text(completion.content, encoding="utf-8")
            entry["scenario_file"] = path.name
            try:
                scenario = load_scenario(path)
            except (ScenarioValidationError, ValueError) as error:
                entry.update(status="INVALID", loader_status="INVALID", error_category="LOADER_INVALID",
                             loader_error=str(error)[:240])
            else:
                entry["loader_status"] = "VALID"
                focus_error = _focus_error(scenario, focus)
                if focus_error:
                    entry.update(status="INVALID", error_category="FOCUS_MISMATCH", error_summary=focus_error)
                else:
                    entry["status"] = "VALID"
        except LocalLLMError as error:
            entry.update(status="TIMEOUT" if error.category == "TIMEOUT" else "API_ERROR",
                         error_category=error.category, elapsed_seconds=error.elapsed_seconds)
            entry.update(error.usage)
            if error.http_status is not None:
                entry["http_status"] = error.http_status
        save()
    return save()
