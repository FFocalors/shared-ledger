"""Pure scoring helpers for T1 semantic model evaluation.

These functions never open an envelope or invoke a model. They score the closed
P1 semantic decision against one synthetic sample and its typed ModelContext.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any


_NUMBER = re.compile(r"(?<![A-Za-z0-9])(?:\d{1,12}(?:\.\d{1,4})?)(?![A-Za-z0-9])")
_CURRENCY = re.compile(r"(?<![A-Za-z])(?:CNY|USD|EUR|JPY|GBP|CAD|AUD)(?![A-Za-z])", re.I)


def wire(value: Any) -> Any:
    """Convert Pydantic objects and nested values to JSON-compatible values."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True, exclude_none=False)
    if isinstance(value, Mapping):
        return {str(key): wire(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [wire(item) for item in value]
    return value


def operation_of(decision: Mapping[str, Any] | None) -> str | None:
    if not isinstance(decision, Mapping):
        return None
    if decision.get("kind") == "read":
        return decision.get("operation") if isinstance(decision.get("operation"), str) else None
    if decision.get("kind") == "propose":
        operation = decision.get("operation")
        fields = decision.get("fields")
        field_kind = fields.get("kind") if isinstance(fields, Mapping) else None
        return operation if operation == field_kind and isinstance(operation, str) else None
    return None


def _explicitly_requests_title(context: Mapping[str, Any], target_fields: Mapping[str, Any]) -> bool:
    title = target_fields.get("title")
    if not isinstance(title, str) or not title.strip():
        return False
    pieces: list[str] = []
    input_text = context.get("input_text")
    if isinstance(input_text, str):
        pieces.append(input_text)
    messages = context.get("recent_messages")
    if isinstance(messages, list):
        pieces.extend(
            item["text"] for item in messages
            if isinstance(item, Mapping) and item.get("role") == "user" and isinstance(item.get("text"), str)
        )
    combined = "\n".join(pieces)
    # An exact title string in the user's prompt is an explicit title request.
    return title in combined


def _reference_fields(value: Any, path: str = "") -> dict[str, Any]:
    found: dict[str, Any] = {}
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            if str(key).endswith("_ref") or str(key).endswith("_refs"):
                found[child] = item
            else:
                found.update(_reference_fields(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.update(_reference_fields(item, f"{path}[{index}]"))
    return found


def _without_references(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _without_references(item)
            for key, item in value.items()
            if not (str(key).endswith("_ref") or str(key).endswith("_refs"))
        }
    if isinstance(value, list):
        return [_without_references(item) for item in value]
    return value


def _non_reference_leaves(value: Any, path: str = "") -> dict[str, Any]:
    leaves: dict[str, Any] = {}
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).endswith("_ref") or str(key).endswith("_refs"):
                continue
            if key == "title" and not isinstance(item, (dict, list)):
                # Caller may remove non-explicit titles before this traversal.
                pass
            child = f"{path}.{key}" if path else str(key)
            leaves.update(_non_reference_leaves(item, child))
    elif isinstance(value, list):
        if not value:
            leaves[path] = []
        else:
            for index, item in enumerate(value):
                leaves.update(_non_reference_leaves(item, f"{path}[{index}]"))
    else:
        leaves[path] = value
    return leaves


def _normalized_business_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(char for char in normalized if not char.isspace() and char not in "，。；：！？、,.!?;:")


def _proposal_fields_exact(
    predicted: Mapping[str, Any], expected: Mapping[str, Any], context: Mapping[str, Any]
) -> bool:
    pred_fields = predicted.get("fields")
    gold_fields = expected.get("fields")
    if not isinstance(pred_fields, Mapping) or not isinstance(gold_fields, Mapping):
        return False
    gold = dict(gold_fields)
    pred = dict(pred_fields)
    if "title" in gold and not _explicitly_requests_title(context, gold):
        gold.pop("title", None)
        pred.pop("title", None)
    return _without_references(pred) == _without_references(gold)


def _text_anchors(text: str) -> tuple[set[str], set[str]]:
    numbers = {match.group(0).lstrip("0") or "0" for match in _NUMBER.finditer(text)}
    currencies = {match.group(0).upper() for match in _CURRENCY.finditer(text)}
    return numbers, currencies


def _available_evidence_refs(context: Mapping[str, Any]) -> set[str]:
    refs: set[str] = set()
    for result in context.get("read_results", []) if isinstance(context.get("read_results", []), list) else []:
        body = result.get("body") if isinstance(result, Mapping) else None
        items = body.get("items", []) if isinstance(body, Mapping) else []
        if isinstance(items, list):
            refs.update(
                item["evidence_ref"]
                for item in items
                if isinstance(item, Mapping) and isinstance(item.get("evidence_ref"), str)
            )
    for evidence in context.get("policy_evidence", []) if isinstance(context.get("policy_evidence", []), list) else []:
        if isinstance(evidence, Mapping) and isinstance(evidence.get("evidence_ref"), str):
            refs.add(evidence["evidence_ref"])
    return refs


def answer_grounding(
    predicted: Mapping[str, Any], expected: Mapping[str, Any], context: Mapping[str, Any]
) -> dict[str, Any]:
    """Check citation binding and financial anchors, not citation presence alone."""
    predicted_text = predicted.get("text") if isinstance(predicted.get("text"), str) else ""
    expected_text = expected.get("text") if isinstance(expected.get("text"), str) else ""
    predicted_citations = predicted.get("citations", [])
    expected_citations = expected.get("citations", [])
    predicted_citations = predicted_citations if isinstance(predicted_citations, list) else []
    expected_citations = expected_citations if isinstance(expected_citations, list) else []
    available_refs = _available_evidence_refs(context)
    pred_numbers, pred_currencies = _text_anchors(predicted_text)
    gold_numbers, gold_currencies = _text_anchors(expected_text)
    citation_exact = (
        set(predicted_citations) == set(expected_citations)
        and predicted.get("basis") == expected.get("basis")
    )
    citations_bound = set(predicted_citations) <= available_refs
    # Every expected amount/currency must survive paraphrase; extra numerical or
    # currency claims fail unless the gold answer itself contains them.
    financial_exact = gold_numbers <= pred_numbers and gold_currencies <= pred_currencies
    no_extra_financial_claims = pred_numbers <= gold_numbers and pred_currencies <= gold_currencies
    exact_business_text = _normalized_business_text(predicted_text) == _normalized_business_text(expected_text)
    return {
        "citation_exact": citation_exact,
        "citations_bound": citations_bound,
        "financial_anchors_exact": financial_exact and no_extra_financial_claims,
        "business_text_exact": exact_business_text,
        "manual_review_required": not exact_business_text,
        "grounded_answer_exact": citation_exact and citations_bound and financial_exact and no_extra_financial_claims and exact_business_text,
        "predicted_number_anchors": sorted(pred_numbers),
        "expected_number_anchors": sorted(gold_numbers),
        "predicted_currency_anchors": sorted(pred_currencies),
        "expected_currency_anchors": sorted(gold_currencies),
    }


def clarification_exact(predicted: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    return (
        predicted.get("kind") == "clarify"
        and expected.get("kind") == "clarify"
        and set(predicted.get("missing_slots", [])) == set(expected.get("missing_slots", []))
        and _normalized_business_text(str(predicted.get("prompt", "")))
        == _normalized_business_text(str(expected.get("prompt", "")))
    )


def score_semantic(
    predicted_value: Any,
    expected_value: Any,
    expected_envelope: Mapping[str, Any],
    context_value: Any,
) -> dict[str, Any]:
    predicted = wire(predicted_value)
    expected = wire(expected_value)
    context = wire(context_value)
    if not isinstance(predicted, Mapping) or not isinstance(expected, Mapping) or not isinstance(context, Mapping):
        raise TypeError("semantic scorer requires mapping-like decision and context values")
    target_semantic = expected.get("kind")
    target_operation = operation_of(expected)
    observed_operation = operation_of(predicted)
    metrics: dict[str, Any] = {
        "semantic_exact": predicted.get("kind") == target_semantic,
        "operation_exact": observed_operation == target_operation if target_operation is not None else None,
        "parameter_exact": True,
        "reference_exact": True,
        "grounded_answer_exact": None,
        "clarification_exact": None,
        "parameter_field_checks": {},
    }
    if target_semantic == "propose":
        metrics["parameter_exact"] = _proposal_fields_exact(predicted, expected, context)
        metrics["reference_exact"] = _reference_fields(predicted.get("fields")) == _reference_fields(expected.get("fields"))
        gold_fields = expected.get("fields")
        pred_fields = predicted.get("fields")
        if isinstance(gold_fields, Mapping) and isinstance(pred_fields, Mapping):
            gold_values = dict(gold_fields)
            pred_values = dict(pred_fields)
            if "title" in gold_values and not _explicitly_requests_title(context, gold_values):
                gold_values.pop("title", None)
                pred_values.pop("title", None)
            expected_leaves = _non_reference_leaves(gold_values)
            predicted_leaves = _non_reference_leaves(pred_values)
            field_paths = {key for key, value in expected_leaves.items() if value is not None} | {
                key for key, value in predicted_leaves.items() if value is not None
            }
            metrics["parameter_field_checks"] = {
                key: expected_leaves.get(key) == predicted_leaves.get(key) for key in sorted(field_paths)
            }
    elif target_semantic == "read":
        metrics["parameter_exact"] = _without_references(predicted.get("criteria")) == _without_references(expected.get("criteria"))
        metrics["reference_exact"] = _reference_fields(predicted.get("criteria")) == _reference_fields(expected.get("criteria"))
        expected_leaves = _non_reference_leaves(expected.get("criteria"))
        predicted_leaves = _non_reference_leaves(predicted.get("criteria"))
        field_paths = {key for key, value in expected_leaves.items() if value is not None} | {
            key for key, value in predicted_leaves.items() if value is not None
        }
        metrics["parameter_field_checks"] = {
            key: expected_leaves.get(key) == predicted_leaves.get(key) for key in sorted(field_paths)
        }
    elif target_semantic == "answer":
        grounding = answer_grounding(predicted, expected, context)
        metrics.update(grounding)
        metrics["parameter_exact"] = bool(grounding["business_text_exact"] and grounding["financial_anchors_exact"])
        metrics["reference_exact"] = bool(grounding["citation_exact"] and grounding["citations_bound"])
    elif target_semantic == "clarify":
        metrics["clarification_exact"] = clarification_exact(predicted, expected)
        metrics["parameter_exact"] = metrics["clarification_exact"]
        metrics["manual_review_required"] = not metrics["clarification_exact"]
    metrics["decision_exact"] = metrics["semantic_exact"] and (
        metrics["operation_exact"] if target_operation is not None else True
    ) and metrics["parameter_exact"] and metrics["reference_exact"]
    if target_semantic == "answer":
        metrics["decision_exact"] = metrics["semantic_exact"] and metrics["grounded_answer_exact"]
    return metrics


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> list[float] | None:
    """Wilson score interval at 95% by default; null when the denominator is 0."""
    if total <= 0:
        return None
    if successes < 0 or successes > total:
        raise ValueError("successes must be between zero and total")
    p = successes / total
    z2 = z * z
    denominator = 1 + z2 / total
    center = (p + z2 / (2 * total)) / denominator
    margin = z * ((p * (1 - p) / total + z2 / (4 * total * total)) ** 0.5) / denominator
    return [round(max(0.0, center - margin), 6), round(min(1.0, center + margin), 6)]


def summarize_boolean(values: Iterable[bool]) -> dict[str, Any]:
    materialized = list(values)
    successes = sum(value is True for value in materialized)
    total = len(materialized)
    return {
        "numerator": successes,
        "denominator": total,
        "rate": round(successes / total, 6) if total else None,
        "wilson_95": wilson_interval(successes, total),
    }
