"""Compile a raw business case into Scenario JSON v1 with DeepSeek.

This is separate from the verdict-producing Judge. It only sees the raw case,
the frozen business rules, and the public Scenario input contract; it never
receives execution results or database state. Validation and the single
permitted repair are controlled by the caller.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from .deepseek import DeepSeekClient
from .scenario_plan import ScenarioPlan, render_plan


class CompilerError(ValueError):
    """A compiler response cannot be used as a Scenario JSON v1 document."""

    def __init__(self, category: str, message: str, *, response_text: str | None = None):
        self.category = category
        self.response_text = response_text
        super().__init__(message)


@dataclass(frozen=True)
class CompilerResult:
    scenario: dict[str, Any]
    response_text: str
    model: str
    latency_seconds: float
    repair: bool


# This describes input syntax, not a second source of business rules. The
# loader remains the authority for semantic and cross-field validation.
SCENARIO_V1_CONTRACT = """\
Scenario JSON v1 is one JSON object with exactly: schema_version (integer 1),
scenario_id (short unique business ref), description (string), activity,
participants, operations. activity has exactly type (normal or large),
base_currency (uppercase 3-letter code), multi_currency_enabled (boolean).
participants is a nonempty array of unique short business refs. operations is
a nonempty array. Every monetary amount is a decimal JSON STRING; never a JSON
number. Base-currency amounts have at most one fractional digit; all amounts
have at most four. Every operation has only the fields listed for its type:

create_expense: type, ref, title, amount, currency, payments, split_method,
and either splits for manual or aa_participants for aa. amount is positive;
payments and manual splits are objects keyed by participant ref whose signed
amounts each sum EXACTLY to amount. AA omits splits and has a nonempty unique
aa_participants array. Each participant key/ref must be declared.

linked_refund: same expense fields plus original_expense_ref pointing to an
earlier positive create_expense. Its amount, payments, and manual splits are
negative and sum exactly. Its currency matches the original expense.

targeted_repayment: type, ref, from_participant, to_participant, amount,
currency, target_expense_refs (nonempty array pointing to earlier expenses in
the same currency). fifo_repayment: same fields except target_expense_refs.
Repayment amount is positive; payer and recipient differ.

create_prepayment and return_prepayment: type, ref, owner_participant,
custodian_participant, amount, currency. Amount is positive; owner and
custodian differ. void_transfer: type, transfer_ref, reason. transfer_ref
points to an earlier transfer-producing operation and is voided only once.

All operation refs are unique short business refs, not UUIDs. Preserve the
raw case's participant identities, currency, event order, and test intent.
Do not add expected_result, request_id, financial_version, SQL, JWT, database
IDs, verdicts, or any field not listed here. Output ONLY the Scenario object.
"""


_SYSTEM_PROMPT = (
    "You are the Shared Ledger Scenario Compiler. Convert one raw business "
    "test case into exactly one valid Scenario JSON v1 document. You do not "
    "judge expected results and cannot observe Runner or database state. "
    "Use the supplied BUSINESS_LOGIC.md as the only business-rule source. "
    "The Scenario contract defines syntax. Preserve the original test intent; "
    "only normalize field names, add missing titles and refs, resolve semantic "
    "references to earlier events, and repair arithmetic. Return JSON only, "
    "without Markdown or reasoning."
)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_float(_: str) -> Any:
    raise ValueError("JSON numbers with fractional parts are not allowed")


def parse_compiler_response(text: str) -> dict[str, Any]:
    """Parse the final content without silently rewriting model output."""

    if not isinstance(text, str) or not text.strip():
        raise CompilerError("EMPTY_RESPONSE", "Compiler returned empty content", response_text=text)
    try:
        document = json.loads(text, object_pairs_hook=_reject_duplicate_keys,
                              parse_float=_reject_float)
    except (json.JSONDecodeError, ValueError) as exc:
        raise CompilerError("INVALID_JSON", f"Compiler returned invalid JSON: {exc}", response_text=text) from None
    if not isinstance(document, dict):
        raise CompilerError("INVALID_ENVELOPE", "Compiler must return one JSON object", response_text=text)
    return document


def compile_once(
    raw_case: dict[str, Any],
    business_logic: str,
    *,
    prior_output: str | dict[str, Any] | None = None,
    loader_error: str | None = None,
    client: DeepSeekClient | None = None,
    smoke_currency: str | None = None,
    plan: ScenarioPlan | None = None,
) -> CompilerResult:
    """Make one Compiler request and parse its Scenario output.

    Pass both ``prior_output`` and ``loader_error`` for the caller's single
    repair attempt; ``loader_error`` carries whichever gate rejected the
    previous Scenario (the Loader or the focus contract). When ``plan`` is
    supplied its shape is authoritative and is restated to the model. This
    function does not call the Loader or retry.
    """

    if not isinstance(raw_case, dict):
        raise TypeError("raw_case must be a JSON object")
    if not isinstance(business_logic, str) or not business_logic.strip():
        raise ValueError("business_logic must contain the complete BUSINESS_LOGIC.md")
    if (prior_output is None) != (loader_error is None):
        raise ValueError("prior_output and loader_error must be supplied together")
    if smoke_currency is not None and raw_case.get("currency") != smoke_currency:
        raise ValueError("raw case currency does not match smoke focus")
    compiler_client = client or DeepSeekClient.from_env(max_retries=0)
    user_parts = [
        "Full BUSINESS_LOGIC.md:\n" + business_logic,
        "Scenario JSON v1 input contract:\n" + SCENARIO_V1_CONTRACT,
        "Raw business case:\n" + json.dumps(raw_case, ensure_ascii=False, indent=2),
    ]
    if plan is not None:
        user_parts.append(
            "This case was generated from a ScenarioPlan. The plan is authoritative: the "
            "compiled Scenario must use exactly its participants, amounts, split methods and "
            "operation order. Do not add, drop, reorder or re-amount anything.\n"
            + render_plan(plan)
        )
    if smoke_currency is not None:
        user_parts.append(
            f"This basic smoke focus is {smoke_currency}-only. Set activity.base_currency "
            f"to {smoke_currency}, multi_currency_enabled to false, and every monetary "
            f"operation currency to {smoke_currency}. Do not introduce FX currencies or rates."
        )
    repair = loader_error is not None
    if repair:
        rendered_prior = (
            prior_output if isinstance(prior_output, str)
            else json.dumps(prior_output, ensure_ascii=False, indent=2)
        )
        user_parts.append(
            "The previous Compiler output was rejected. Repair it once, preserving the raw "
            "case intent and the ScenarioPlan shape.\n"
            "Previous output:\n" + rendered_prior + "\n"
            "Rejection reason:\n" + loader_error
        )
    started = time.monotonic()
    response_text = compiler_client.complete(_SYSTEM_PROMPT, "\n\n".join(user_parts))
    latency = time.monotonic() - started
    scenario = parse_compiler_response(response_text)
    return CompilerResult(
        scenario=scenario,
        response_text=response_text,
        model=compiler_client.model,
        latency_seconds=latency,
        repair=repair,
    )
