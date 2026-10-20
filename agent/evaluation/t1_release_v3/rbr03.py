"""RBR03: name clarification candidates by returned facts, not internal refs.

The root review found that the ambiguous presentation-update rows ask the user to
pick a candidate by a bare internal ``expense_ref``.  A user cannot act on that:
the clarification should distinguish the candidates with facts they were just
shown -- title, date, amount, currency, participants -- and the follow-up should
select on those facts.

This module is deliberately free of any protocol import so the isolated v2
generation process can use it as the gold validator for the converted rows.
"""
from __future__ import annotations

import re
from typing import Any

READ_STEP = 1
CLARIFY_STEP = 2
FOLLOWUP_STEP = 3
FINAL_STEP = 4

# Anything that leaks the internal reference into user-visible text.
INTERNAL_REF_PATTERN = re.compile(r"expense_ref\s*=")


class NaturalClarificationError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise NaturalClarificationError(message)


def validate_natural_clarification(record: dict[str, Any]) -> None:
    """Gold check for one natural-clarification presentation-update row."""
    expected = record["expected"]
    _require(expected["semantic"] == "propose", "natural clarification must end in a proposal")
    _require(
        expected["task_operation"] == "expense.presentation.update",
        "natural clarification applies to presentation updates only",
    )
    _require(record["case_type"] == "multi_turn", "ambiguous presentation rows are multi-turn")
    trace = record["trace"]
    _require(len(trace) == 5, "expected read, clarify, follow-up and final proposal steps")
    _require(trace[0]["kind"] == "model", "trace must start with the read decision")
    _require(trace[READ_STEP]["kind"] == "tool_result", "the read decision must be followed by its result")
    _require(trace[CLARIFY_STEP]["kind"] == "model", "the second model step must be the clarification")
    _require(trace[FOLLOWUP_STEP]["kind"] == "user_followup", "the clarification must be answered by the user")
    _require(trace[FINAL_STEP]["kind"] == "model", "the trace must end with the proposal")

    clarify = trace[CLARIFY_STEP]["target"]
    _require(clarify["kind"] == "clarify", "the second decision must be a clarification")
    prompt = clarify["prompt"]
    _require(not INTERNAL_REF_PATTERN.search(prompt), "clarification must not expose an internal reference")

    facts = trace[READ_STEP]["result"]["body"]["items"]
    _require(len(facts) >= 2, "an ambiguous presentation update needs at least two candidates")
    for fact in facts:
        # Every candidate must be distinguishable from the returned facts alone.
        _require(fact["title"] in prompt, "clarification must name each candidate by its title")
        _require(fact["occurred_at"][:10] in prompt, "clarification must show each candidate date")
        _require(
            f"{fact['original_amount']} {fact['original_currency']}" in prompt,
            "clarification must show each candidate amount and currency",
        )

    followup = trace[FOLLOWUP_STEP]["text"]
    _require(not INTERNAL_REF_PATTERN.search(followup), "follow-up must not select by internal reference")
    selected = [fact for fact in facts
                if fact["occurred_at"][:10] in followup
                and f"{fact['original_amount']} {fact['original_currency']}" in followup]
    _require(len(selected) == 1, "follow-up must select exactly one candidate by date and amount")

    final = trace[FINAL_STEP]["target"]
    _require(final["kind"] == "propose", "the final decision must be a proposal")
    _require(final["operation"] == "expense.presentation.update", "wrong final operation")
    fields = final["fields"]
    _require(
        fields["expense_ref"] == selected[0]["expense_ref"],
        "the proposal must target the candidate the user selected by its returned facts",
    )
    _require(
        set(fields) <= {"kind", "expense_ref", "title", "note", "icon_key"},
        "a presentation update may only change presentation fields",
    )
    _require(
        any(fields.get(key) not in (None, "") for key in ("title", "note", "icon_key")),
        "a presentation update must change at least one display field",
    )

    final_context = trace[FINAL_STEP]["context"]
    _require(final_context["input_text"] == followup, "final context input must be the user follow-up verbatim")
    _require(
        [item["text"] for item in final_context["recent_messages"]][-3:]
        == [trace[0]["context"]["input_text"], prompt, followup],
        "the clarification chain must be preserved in causal order",
    )


def audit_row(record: dict[str, Any]) -> dict[str, Any]:
    """Reviewer-facing summary of one natural clarification."""
    validate_natural_clarification(record)
    trace = record["trace"]
    facts = trace[READ_STEP]["result"]["body"]["items"]
    selected = [fact for fact in facts
                if fact["occurred_at"][:10] in trace[FOLLOWUP_STEP]["text"]
                and f"{fact['original_amount']} {fact['original_currency']}"
                in trace[FOLLOWUP_STEP]["text"]][0]
    return {
        "sample_id": record["sample_id"],
        "split": record["split"],
        "candidate_count": len(facts),
        "clarification_prompt": trace[CLARIFY_STEP]["target"]["prompt"],
        "followup": trace[FOLLOWUP_STEP]["text"],
        "selected_expense_ref": selected["expense_ref"],
        "exposes_internal_reference": bool(
            INTERNAL_REF_PATTERN.search(trace[CLARIFY_STEP]["target"]["prompt"])
            or INTERNAL_REF_PATTERN.search(trace[FOLLOWUP_STEP]["text"])
        ),
    }
