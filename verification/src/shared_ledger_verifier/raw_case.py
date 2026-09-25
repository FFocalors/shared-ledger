"""Generate a lightweight business case with the local model; no Scenario execution."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from .focus_contract import ALL_FOCUSES, FocusDefinitionError, focus_spec
from .local_llm import LocalLLMClient, LocalLLMError, _response_format
from .local_llm_v2 import FOCUS_SECTIONS, select_business_sections
from .scenario_plan import ScenarioPlan, render_plan
from .supabase import verification_root


EVENT_TYPES = (
    "expense", "fifo_repayment", "targeted_repayment", "prepayment",
    "prepayment_return", "linked_refund", "void_transfer",
)
SMOKE_CNY_FOCUSES = frozenset({"expense_aa", "targeted_repayment", "prepayment_refund"})
# Every registered focus runs on a CNY-only activity, so the raw-case currency is
# pinned for all of them; unregistered focus names keep the schema unconstrained.
CNY_ONLY_FOCUSES = frozenset(ALL_FOCUSES)
KNOWN_FOCUSES = frozenset(ALL_FOCUSES) | frozenset(FOCUS_SECTIONS)

# The intentionally small contract leaves accounting normalization to the Compiler.
# Each event is a plain-language business intent, not a Scenario JSON v1 operation.
RAW_CASE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "theme": {"type": "string"},
        "participants": {"type": "array", "items": {"type": "string"}, "minItems": 2},
        "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
        "events": {
            "type": "array", "minItems": 1,
            "items": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "type": {"type": "string", "enum": list(EVENT_TYPES)},
                    "intent": {"type": "string"},
                },
                "required": ["type", "intent"],
            },
        },
    },
    "required": ["theme", "participants", "currency", "events"],
}


class RawCaseError(ValueError):
    """A local response is not a usable raw business case."""

    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


_FORBIDDEN = re.compile(
    r"\b(?:SQL|JWT|request_id|financial_version|expected_result|judge\s+verdict)\b"
    r"|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RawCaseError("DUPLICATE_FIELD")
        result[key] = value
    return result


def parse_raw_case(content: str, *, required_currency: str | None = None) -> dict[str, Any]:
    """Parse only the deliberately small raw-case envelope and event vocabulary."""
    try:
        raw = json.loads(content, object_pairs_hook=_unique_pairs)
    except RawCaseError:
        raise
    except (TypeError, json.JSONDecodeError, ValueError):
        raise RawCaseError("INVALID_JSON") from None
    if not isinstance(raw, dict) or set(raw) != {"theme", "participants", "currency", "events"}:
        raise RawCaseError("INVALID_RAW_CASE")
    if (not isinstance(raw["theme"], str) or not raw["theme"].strip()
            or not isinstance(raw["currency"], str)
            or not re.fullmatch(r"[A-Z]{3}", raw["currency"])):
        raise RawCaseError("INVALID_RAW_CASE")
    participants = raw["participants"]
    if (not isinstance(participants, list) or len(participants) < 2
            or any(not isinstance(name, str) or not name.strip() for name in participants)
            or len(set(participants)) != len(participants)):
        raise RawCaseError("INVALID_RAW_CASE")
    events = raw["events"]
    if not isinstance(events, list) or not events:
        raise RawCaseError("INVALID_RAW_CASE")
    for event in events:
        if (not isinstance(event, dict) or set(event) != {"type", "intent"}
                or event["type"] not in EVENT_TYPES
                or not isinstance(event["intent"], str) or not event["intent"].strip()):
            raise RawCaseError("INVALID_RAW_CASE")
    if _FORBIDDEN.search(content):
        raise RawCaseError("FORBIDDEN_CONTENT")
    if required_currency is not None and raw["currency"] != required_currency:
        raise RawCaseError("CURRENCY_MISMATCH")
    return raw


def _schema_for_focus(focus: str) -> dict[str, Any]:
    schema = deepcopy(RAW_CASE_SCHEMA)
    if focus in CNY_ONLY_FOCUSES:
        schema["properties"]["currency"] = {"type": "string", "const": "CNY"}
    return schema


def _guidance(focus: str) -> str:
    """Bespoke guidance for the historical smoke focuses, else the registry goal."""
    bespoke = {
        "expense_aa": (
            "Use a normal CNY activity with A, B, C. Describe one shared expense, "
            "two or three payers, and an equal AA share for all three. No repayment, "
            "prepayment, or refund."
        ),
        "targeted_repayment": (
            "Use a CNY-only activity with three or four participants. First describe an expense paid by one person "
            "for another; then a strictly partial repayment directed at that previous "
            "expense. Make debtor, creditor, amount, and semantic reference explicit."
        ),
        "prepayment_refund": (
            "Use a CNY-only activity with three or four participants. Describe, in order, a prepayment by an owner "
            "to a custodian, a later shared expense, then a partial refund linked to that "
            "previous expense. State who receives the refund and who benefits."
        ),
    }
    if focus in bespoke:
        return bespoke[focus]
    return focus_spec(focus).goal


def _messages(focus: str, sections: str, plan: ScenarioPlan | None = None) -> list[dict[str, str]]:
    if plan is not None:
        task = (
            "Encode this fixed ScenarioPlan as a raw business case. The plan is authoritative: "
            "use exactly the participants, amounts, payers and operation order it states, and do "
            "not invent, drop, or reorder any of them.\n\n" + render_plan(plan)
        )
    else:
        task = _guidance(focus)
    return [
        {"role": "system", "content": (
            "Create one original raw business test case using the supplied BUSINESS_LOGIC.md "
            "sections as the sole rule source. Output only a JSON raw_case with theme, "
            "participants, currency, events. Each event has type and a concise natural-language "
            "intent including useful amounts and actors. This is not Scenario JSON v1. "
            "Do not generate SQL, UUID, JWT, request_id, financial_version, expected_result, "
            "Judge verdict, or database internal fields."
        )},
        {"role": "user", "content": (
            task + " Express amounts in the intent as clear decimal currency amounts; "
            "do not worry about exact payment/split conservation, titles, refs, or Loader field "
            "names. Use ordinary semantic references such as 'previous expense' where useful. "
            "Generate exactly one case.\n\nRelevant BUSINESS_LOGIC.md sections:\n" + sections
        )},
    ]


def generate_raw_case(
    focus: str, *, client: LocalLLMClient | None = None,
    business_logic_path: Path | None = None,
    plan: ScenarioPlan | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Generate once; return raw case and non-secret provenance/performance metadata.

    Raises ``RawCaseError`` for malformed model output and ``LocalLLMError`` for
    unavailable source/model or API errors. It never retries or writes files.
    """
    if focus not in KNOWN_FOCUSES:
        raise RawCaseError("INVALID_FOCUS")
    if plan is not None and plan.focus != focus:
        raise RawCaseError("PLAN_FOCUS_MISMATCH")
    client = client or LocalLLMClient.from_env()
    path = business_logic_path or verification_root().parent / "docs/backend/BUSINESS_LOGIC.md"
    try:
        document = path.read_text(encoding="utf-8")
    except OSError:
        raise LocalLLMError("BUSINESS_LOGIC_UNAVAILABLE") from None
    headings, sections = select_business_sections(document, focus)
    if not client.model:
        ids, _, _ = client.models()
        client.select_model(ids)
    messages = _messages(focus, sections, plan)
    completion = client.complete(
        messages,
        max_tokens=1024,
        response_format=_response_format("shared_ledger_raw_case_v1", _schema_for_focus(focus)),
    )
    raw = parse_raw_case(
        completion.content,
        required_currency="CNY" if focus in CNY_ONLY_FOCUSES else None,
    )
    return raw, {
        "focus": focus,
        "plan_seed": plan.seed if plan is not None else None,
        "plan_fingerprint": plan.fingerprint() if plan is not None else None,
        "local_model": client.model,
        "business_logic_sections": headings,
        "business_logic_characters": len(sections),
        "input_characters": sum(len(message["content"]) for message in messages),
        "generation_latency_seconds": completion.elapsed_seconds,
        "prompt_tokens": completion.usage.get("prompt_tokens"),
        "completion_tokens": completion.usage.get("completion_tokens"),
    }
