"""Explicitly convert a release candidate read row to the v1.1 canonical profile.

Three things change and nothing else:

* the model-visible input no longer carries a training-only "already read and
  consumed" hint (RBR02);
* a no-match answer stops being an uncited conversation turn and becomes the
  frozen trusted renderer's output, citing a typed query result (RBR01);
* the tool observation carries that typed query evidence.

Every value is either carried over verbatim from the v2 row or produced by
the frozen v1.1 package.  The v2 row itself is never written or mutated.
"""
from __future__ import annotations

import copy
import uuid
from decimal import Decimal
from typing import Any

from . import profile, v11_evidence
from .v11_evidence import EvidenceError

# The training-only hints that RBR02 removes.  Listed explicitly so a reviewer
# can see exactly which strings may never appear in a converted model input.
TRAINING_ONLY_HINTS = (
    " 已消费模拟工具回放结果，请按结果作答。",
    " 已读取并消费当前状态结果，再按明确参数生成草案。",
    " 已读取并消费当前模拟查询结果。",
)


class ConversionError(RuntimeError):
    pass


def strip_training_only_hints(text: str) -> str:
    result = text
    for hint in TRAINING_ONLY_HINTS:
        result = result.replace(hint, "")
    return result


def _activity_ref_enum(c: Any, value: str) -> Any:
    for member in c.ActivityRef:
        if member.value == value:
            return member
    raise ConversionError(f"unknown activity reference: {value}")


def _criteria_v11(c: Any, v11: Any, record: dict[str, Any], title_filter: str | None) -> Any:
    """Build the frozen v1.1 criteria for one read row.

    The v1.1 package carries its own copy of the v1 contracts, and its typed
    ports accept only those classes, so the criteria are built from ``v11.V1``.
    """
    v1 = v11.V1
    operation = record["scenario"]["operation"]
    raw = record["scenario"]["criteria"]
    if operation == "read.activities":
        return v1.ReadActivitiesCriteria(
            kind="activities",
            status=raw["status"],
            name_contains=raw["name_contains"],
        )
    if operation == "read.expenses":
        # The v2 row applied the title filter by hand after the read, which is
        # exactly the RBR01 defect: the filter was nowhere in the query.  The
        # v1.1 port carries it as a typed post-filter stage.
        return v11.ReadExpensesCriteria(
            kind="expenses",
            activity_ref=_activity_ref_enum(v1, raw["activity_ref"]),
            from_date=raw.get("from_date"),
            to_date=raw.get("to_date"),
            participant_ref=None,
            title_contains=title_filter,
        )
    if operation == "read.debts":
        return v1.ReadDebtsCriteria(
            kind="debts",
            activity_ref=_activity_ref_enum(v1, raw["activity_ref"]),
            participant_ref=None,
            currency=raw["currency"],
        )
    raise ConversionError(f"not a read row: {operation}")


def _reference_index(private_references: list[Any]) -> dict[tuple[str, str], uuid.UUID]:
    """(kind, ref token) -> persisted entity id, for the row's private bindings."""
    return {(item.kind, item.ref.value): item.entity_id for item in private_references}


def _evidence_references(v11: Any, result: Any, scope_activity_id: uuid.UUID,
                         private_references: list[Any], turn_id: uuid.UUID,
                         context_version: int) -> list[Any]:
    """Private per-fact evidence bindings for every row the backend returned.

    Each expense fact must bind to the entity id of its own persisted typed
    Expense reference, so the ids are looked up rather than invented.
    """
    index = _reference_index(private_references)
    built = []
    for fact in result.body.items:
        entity_id = index.get((fact.kind, fact.expense_ref.value))
        if entity_id is None:
            raise ConversionError(
                f"no persisted {fact.kind} reference for evidence {fact.evidence_ref.value}"
            )
        built.append(v11.V1.BoundExpenseEvidence(
            kind=fact.kind,
            evidence_ref=v11.V1.ExpenseEvidenceRef(fact.evidence_ref.value),
            entity_id=entity_id,
            scope_activity_id=scope_activity_id,
            source_result_id=result.result_id,
            source_turn_id=turn_id,
            context_version=context_version,
        ))
    return built


def converted_title_filter(record: dict[str, Any]) -> str | None:
    """The title filter the v2 row applied by hand, if any."""
    requested = record["scenario"].get("requested_values", {})
    return requested.get("title_contains")


def convert_write_row(*, v11: Any, record: dict[str, Any]) -> dict[str, Any]:
    """Carry a write/proposal row to the release-v3 profile.

    Only two things change: the model-visible inputs lose their training-only
    "already read and consumed" hint (RBR02), and every model context becomes a
    v1.1 context.  The proposal, the fixture and every amount stay byte-equal.
    """
    row = copy.deepcopy(record)
    for step in row["trace"]:
        if step["kind"] != "model":
            continue
        step["context"]["input_text"] = strip_training_only_hints(step["context"]["input_text"])
        step["context"].setdefault("intent_classification", "business")
    row["release_version"] = profile.RELEASE_VERSION
    row["generator_version"] = profile.GENERATOR_VERSION
    row["protocol_profile"] = profile.V11_PROFILE
    row["versions"] = {
        "api": profile.V11_API_VERSION,
        "semantic": profile.V11_SEMANTIC_VERSION,
        "operations": profile.V11_OPERATIONS_VERSION,
        "trajectory": profile.V11_TRAJECTORY_VERSION,
        "execution_key": profile.V11_EXECUTION_KEY_VERSION,
    }
    return row


def attach_aa_base_amounts(
    row: dict[str, Any], *, base_currency_override: str | None = None,
    expense_index: int = 0,
) -> dict[str, Any]:
    """Write both AA allocation columns exactly as the backend persists them.

    Only used for designated coverage rows.  ``operation_state`` carries the
    ledger projection, so both columns are recomputed there:

    * ``splits[].amount`` -- original currency, 0.0001 quantum, first
      ``|remainder|`` participants in participant order move by one unit;
    * ``splits[].base_amount`` -- base currency, 0.1 quantum, the same first-N
      rule.  This is the persisted shape; the creation-time "last participant
      absorbs" intermediate is not what the database ends with.
    * ``payments[].base_amount`` -- base currency, 0.1 quantum, and payments
      keep the last-participant delta: the fair-allocation migration only
      redistributes splits.

    The participant order is the ledger unit's allowlist order, not the order
    the rows happen to be listed in.
    """
    from . import base_allocation

    state = row["operation_state"]
    allowlist = list(state["ledger_unit"]["participant_allowlist"])
    fx_snapshot = state["fx_snapshot"]
    base_currency = base_currency_override or fx_snapshot["base_currency"]
    if base_currency_override:
        state["multi_currency_enabled"] = True
        fx_snapshot["base_currency"] = base_currency
    quotes = {item["currency"]: Decimal(item["rate"]) for item in fx_snapshot["quotes"]}
    if allowlist and base_currency not in quotes:
        quotes[base_currency] = Decimal("1")
        fx_snapshot["quotes"] = sorted(
            [{"currency": name, "rate": f"{rate.quantize(Decimal('0.00000001')):.8f}"}
             for name, rate in quotes.items()],
            key=lambda item: item["currency"],
        )

    audited: list[dict[str, Any]] = []
    for index, expense in enumerate(state["expenses"]):
        if index != expense_index:
            continue
        participants = [ref for ref in allowlist if ref in expense["participant_refs"]]
        if len(participants) != len(expense["participant_refs"]):
            raise ConversionError("expense participants are outside the ledger allowlist")
        if not participants:
            raise ConversionError("expense has no participants to allocate")
        rate = Decimal("1") if expense["currency"] == base_currency else quotes.get(expense["currency"])
        if rate is None:
            raise ConversionError(f"no fx quote for {expense['currency']} to {base_currency}")

        original = base_allocation.original_allocations(expense["amount"], len(participants))
        by_ref = {item["participant_ref"]: Decimal(item["amount"]) for item in expense["splits"]}
        if sorted(by_ref) != sorted(participants):
            raise ConversionError("split participants differ from the expense participants")
        # The rows are listed in a rotated order; the rule is applied in
        # participant order, so re-emit both columns in that order.
        expense["splits"] = [
            {"participant_ref": ref, "amount": f"{amount:.4f}"}
            for ref, amount in zip(participants, original)
        ]

        base_total = base_allocation.expense_base_total(expense["amount"], rate)
        base = base_allocation.base_allocations(base_total, len(participants))
        for split, amount in zip(expense["splits"], base):
            split["base_amount"] = f"{amount:.1f}"
        expense["base_amount"] = f"{base_total:.1f}"

        # Payments keep the last-participant delta.
        if expense["payments"]:
            payment_rate = rate
            converted = [
                (item, base_allocation.expense_base_total(item["amount"], payment_rate))
                for item in expense["payments"]
            ]
            paid = sum((amount for _item, amount in converted), Decimal(0))
            ordered = sorted(
                converted,
                key=lambda pair: allowlist.index(pair[0]["participant_ref"]),
            )
            last_item, last_base = ordered[-1]
            for item, amount in converted:
                item["base_amount"] = f"{amount:.1f}"
            last_item["base_amount"] = f"{(last_base + (base_total - paid)):.1f}"
            if sum(Decimal(item["base_amount"]) for item in expense["payments"]) != base_total:
                raise ConversionError("payment base column does not conserve the expense base")

        if sum(Decimal(item["amount"]) for item in expense["splits"]) != Decimal(expense["amount"]):
            raise ConversionError("original split column does not conserve the expense amount")
        if sum(Decimal(item["base_amount"]) for item in expense["splits"]) != base_total:
            raise ConversionError("base split column does not conserve the expense base")
        if base_allocation.is_last_person_fallback(base, base_total):
            raise ConversionError("base column is the superseded last-person shape")

        audited.append({
            "expense_ref": expense["ref"],
            "original_amount": expense["amount"],
            "original_currency": expense["currency"],
            "base_currency": base_currency,
            "fx_rate": f"{rate:.8f}",
            "base_amount": f"{base_total:.1f}",
            "participants": participants,
            "original_shares": [item["amount"] for item in expense["splits"]],
            "base_shares": [item["base_amount"] for item in expense["splits"]],
            "original_has_tail": _has_tail(original),
            "base_has_tail": _has_tail(base),
            "payment_base_shares": [item.get("base_amount") for item in expense["payments"]],
        })
    return row, audited


def _has_tail(values: list[Decimal]) -> bool:
    return len(set(values)) > 1


def convert_no_match_read_row(
    *,
    c: Any,
    v11: Any,
    namespace: uuid.UUID,
    sample_key: str,
    record: dict[str, Any],
    bound_references: list[Any],
    scope_activity_id: uuid.UUID | None,
    title_filter: str | None,
    turn_id: uuid.UUID,
) -> dict[str, Any]:
    """Return the release-v3 form of one no-match read row."""
    if record["expected"]["semantic"] != "answer":
        raise ConversionError("only answer rows are converted by this path")
    trace = record["trace"]
    if len(trace) != 3 or trace[0]["kind"] != "model" or trace[1]["kind"] != "tool_result" \
            or trace[2]["kind"] != "model":
        raise ConversionError("unexpected read trace shape")

    row = copy.deepcopy(record)
    tool_step = row["trace"][1]
    final_step = row["trace"][2]

    # Reconstruct the replayed result with the v1.1 package's own classes: the
    # frozen ports accept only those, and the JSON is identical either way.
    result = v11.V1.ToolReadResult.model_validate(tool_step["result"])
    criteria = _criteria_v11(c, v11, row, title_filter)
    if criteria.kind != result.body.kind:
        raise ConversionError("converted criteria kind differs from the replayed body kind")
    operation = row["scenario"]["operation"]

    # The frozen v1.1 profile models a global activity listing as a query with
    # no selected backend scope, and a context without a verified activity
    # scope may not carry entity references at all.  Expense and debt queries
    # keep the selected activity scope and its references.
    global_activity_query = criteria.kind == "activities"
    query_scope = None if global_activity_query else scope_activity_id
    # The row's final context exposes only the references its member allowlist
    # admits; the private whitelist must project exactly those.
    visible = {(item["kind"], item["ref"]) for item in final_step["context"]["bound_references"]}
    private_references = (
        [] if global_activity_query
        else [item for item in bound_references if (item.kind, item.ref.value) in visible]
    )
    if not global_activity_query and len(private_references) != len(visible):
        raise ConversionError("private reference whitelist does not project the visible tokens")

    evidence = v11_evidence.build_no_match_evidence(
        c=c,
        v11=v11,
        namespace=namespace,
        sample_key=sample_key,
        operation=operation,
        criteria=criteria,
        result=result,
        scope_activity_id=query_scope,
        observed_at=result.observed_at,
        bound_references=private_references,
        turn_id=turn_id,
        bound_evidence_references=_evidence_references(
            v11, result, query_scope, private_references,
            turn_id, result.context_version,
        ) if query_scope is not None else [],
        row_entity_ids={
            fact.evidence_ref.value: _reference_index(private_references)[(fact.kind, fact.expense_ref.value)]
            for fact in result.body.items
        } if query_scope is not None else {},
    )

    context_payload = dict(final_step["context"])
    context_payload["input_text"] = strip_training_only_hints(context_payload["input_text"])
    if context_payload["input_text"] != row["trace"][0]["context"]["input_text"]:
        raise ConversionError("converted context must carry the original user request verbatim")
    context_payload["intent_classification"] = "business"
    if global_activity_query:
        context_payload["verified_scope"] = {
            "kind": "none",
            "permissions": list(context_payload["verified_scope"]["permissions"]),
        }
        context_payload["bound_references"] = []
    context_payload["query_observations"] = [evidence["observation"].model_dump(mode="json")]
    context_payload["read_results"] = [evidence["model_result"].model_dump(mode="json")]
    context = v11.ModelContext.model_validate(context_payload)

    answer = v11_evidence.render_no_match_answer(v11=v11, context=context, evidence=evidence)
    if answer.basis != "grounded" or [item.value for item in answer.citations] != [v11_evidence.QUERY_REF]:
        raise ConversionError("trusted renderer did not produce a query-citing grounded answer")

    # Every model-visible context of the converted row is a v1.1 context.
    for step in row["trace"]:
        if step["kind"] == "model":
            step["context"]["input_text"] = strip_training_only_hints(step["context"]["input_text"])
            step["context"].setdefault("intent_classification", "business")

    final_step["context"] = context.model_dump(mode="json")
    final_step["target"] = answer.model_dump(mode="json")
    tool_step["query"] = evidence["observation"].model_dump(mode="json")
    # The tool request is left exactly as the frozen simulator consumed it. The
    # typed post-filter lives on the query observation, not on the backend
    # request, and the frozen v1 simulator rejects the v1.1-only expense field.

    row["scenario"] = dict(row["scenario"])
    row["scenario"]["empty_result_citation_gap"] = False
    row["scenario"]["query_evidence"] = v11_evidence.summary(evidence)
    row["release_version"] = profile.RELEASE_VERSION
    row["generator_version"] = profile.GENERATOR_VERSION
    row["protocol_profile"] = profile.V11_PROFILE
    row["versions"] = {
        "api": profile.V11_API_VERSION,
        "semantic": profile.V11_SEMANTIC_VERSION,
        "operations": profile.V11_OPERATIONS_VERSION,
        "trajectory": profile.V11_TRAJECTORY_VERSION,
        "execution_key": profile.V11_EXECUTION_KEY_VERSION,
    }
    tags = [tag for tag in row["coverage_tags"] if tag != "empty-result-citation-gap"]
    tags.append("query-evidence-bound")
    tags.append("rbr01")
    row["coverage_tags"] = sorted(set(tags))
    return row
