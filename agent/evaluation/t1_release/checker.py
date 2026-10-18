"""In-memory collection integrity gate for T1 release v2.

The checker deliberately accepts records rather than paths.  It never opens a
dataset and recomputes every signature from ``operation_state`` and the first
model prompt in ``trace``; producer-supplied family IDs and signature hashes
are not used to establish independence.
"""
from __future__ import annotations

import copy
import re
from collections import defaultdict
from typing import Any, Mapping, Sequence

from .signatures import (
    _canonical_graph,
    _current_activity,
    canonical_json,
    normalize_prompt,
    operation_state_signature,
    prompt_similarity,
    sha256,
)


OPERATIONS = (
    "read.activities",
    "read.expenses",
    "read.debts",
    "expense.create",
    "expense.update",
    "expense.presentation.update",
)
SPLITS = ("train", "validation", "sealed")
TRAIN_MIN_FAMILIES = 20
EVAL_MIN_FAMILIES = 20
NEAR_SEQUENCE_THRESHOLD = 0.82
NEAR_CHAR3_JACCARD_THRESHOLD = 0.72

_TASK_PERMISSIONS = {
    "read.activities",
    "read.expenses",
    "read.debts",
    "propose.expense.create",
    "propose.expense.update",
    "propose.expense.presentation.update",
}


def _task_neutral_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """Copy a state while removing task labels that are not initial-state facts."""
    result = copy.deepcopy(dict(state))
    for activity in result.get("activities", []):
        if isinstance(activity, dict):
            activity["permissions"] = [
                value for value in activity.get("permissions", [])
                if value not in _TASK_PERMISSIONS
            ]
    actor = result.get("actor")
    if isinstance(actor, dict):
        actor["permissions"] = [
            value for value in actor.get("permissions", [])
            if value not in _TASK_PERMISSIONS
        ]
    # This is a request-to-target designation, not a property of the initial
    # ledger.  The expense itself is still represented through read-visible
    # facts in the combined projection.
    for expense in result.get("expenses", []):
        if isinstance(expense, dict):
            expense.pop("is_target", None)
    return result


def _common_permission_facts(state: Mapping[str, Any]) -> dict[str, Any]:
    current = _current_activity(dict(state))
    current_ref = current.get("ref")
    actor = state.get("actor", {})
    actor = actor if isinstance(actor, dict) else {}
    other_activity_permissions = []
    for row in state.get("activities", []):
        if not isinstance(row, dict):
            continue
        values = sorted(
            value for value in row.get("permissions", [])
            if isinstance(value, str) and value not in _TASK_PERMISSIONS
        )
        other_activity_permissions.append((row.get("ref") == current_ref, values))
    return {
        "actor": {
            "authenticated": actor.get("authenticated") is True,
            "activity_member": actor.get("activity_member") is True,
            "activity_member_active": actor.get("activity_member_active") is True,
            "bound_to_current_activity": actor.get("activity_ref") == current_ref,
            "other_permissions": sorted(
                value for value in actor.get("permissions", [])
                if isinstance(value, str) and value not in _TASK_PERMISSIONS
            ),
        },
        "activity_other_permissions": sorted(other_activity_permissions, key=canonical_json),
        "readable_activity_status_filter": sorted(
            status for status in set(state.get("visible_statuses", ["active", "archived"]))
            if status in {"active", "archived"}
        ),
    }


def _common_relationship_graph(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Canonicalize effective membership and ledger relationships without IDs.

    Names, amounts, dates, version values, unit role labels, row order, FX data,
    and target/request markers do not enter the graph.  Participant identity is
    anonymous; only active status and its relationship to the current unit,
    activities, expenses, and debts can distinguish it.
    """
    vertices: list[tuple[Any, ...]] = []
    indices: dict[tuple[str, str], int] = {}
    edges: list[tuple[int, int, str]] = []

    def ensure(kind: str, ref: Any, label: tuple[Any, ...]) -> int:
        key = (kind, str(ref))
        if key not in indices:
            indices[key] = len(vertices)
            vertices.append(label)
        return indices[key]

    def edge(left: int, right: int, label: str, *, bidirectional: bool = False) -> None:
        edges.append((left, right, label))
        if bidirectional:
            edges.append((right, left, label))

    participants: dict[str, int] = {}
    for row in state.get("participants", []):
        if not isinstance(row, dict) or row.get("ref") is None:
            continue
        ref = str(row["ref"])
        participants[ref] = ensure("participant", ref, ("participant", row.get("active") is True))

    current = _current_activity(dict(state))
    current_ref = current.get("ref")
    visible_statuses = set(state.get("visible_statuses", ["active", "archived"]))
    activity_indices: dict[str, int] = {}
    activities = [row for row in state.get("activities", []) if isinstance(row, dict)]
    for row in activities:
        ref = row.get("ref")
        if ref is None:
            continue
        visible_fact = bool(row.get("visible") and row.get("status") in {"active", "archived"}
                            and row.get("status") in visible_statuses)
        if not visible_fact and ref != current_ref:
            continue
        label = (
            "activity", ref == current_ref, row.get("kind"), row.get("status"),
            row.get("base_currency"), row.get("visible") is True,
        )
        activity_indices[str(ref)] = ensure("activity", ref, label)

    for row in activities:
        activity_ref = row.get("ref")
        activity_index = activity_indices.get(str(activity_ref))
        if activity_index is None:
            continue
        for participant_ref in row.get("member_allowlist", []):
            participant_index = participants.get(str(participant_ref))
            if participant_index is not None:
                edge(activity_index, participant_index, "activity_member", bidirectional=True)

    unit = state.get("ledger_unit", {})
    unit_index = None
    if isinstance(unit, dict) and unit:
        unit_index = ensure("unit", "current", (
            "unit", unit.get("active") is True,
            unit.get("parent_active", True) is True,
            unit.get("currency"),
            unit.get("activity_ref") == current_ref,
            unit.get("parent_ref") is not None,
        ))
        bound_activity = activity_indices.get(str(unit.get("activity_ref")))
        if bound_activity is not None:
            edge(unit_index, bound_activity, "unit_activity", bidirectional=True)

        # Only the intersection can supply a legal create choice.  Anonymous
        # participant identities are distinguished only by their other edges.
        current_members = set(current.get("member_allowlist", []))
        unit_allowed = set(unit.get("participant_allowlist", []))
        for ref in unit_allowed & current_members:
            participant_index = participants.get(str(ref))
            if participant_index is not None and state.get("participants"):
                participant_row = next(
                    (row for row in state["participants"]
                     if isinstance(row, dict) and str(row.get("ref")) == str(ref)),
                    None,
                )
                if participant_row is not None and participant_row.get("active") is True:
                    edge(unit_index, participant_index, "effective_unit_member", bidirectional=True)

    # Expenses visible to a read/presentation operation.  is_target is ignored;
    # amount and descriptive text are excluded, but the same-title partition is
    # represented anonymously because it controls real selection ambiguity.
    anchor_readable = bool(
        current.get("visible") and current.get("status") in {"active", "archived"}
    )
    expense_rows = [
        (index, expense) for index, expense in enumerate(state.get("expenses", []))
        if isinstance(expense, dict)
        and anchor_readable
        and expense.get("activity_ref") == current_ref
        and expense.get("target_allowed", True) is True
    ]
    title_groups: dict[bytes, list[int]] = defaultdict(list)
    for index, expense in expense_rows:
        title = expense.get("title")
        if isinstance(title, str) and title:
            title_groups[canonical_json(title)].append(index)
    title_group_size = {
        index: len(members)
        for members in title_groups.values()
        for index in members
    }
    for index, expense in expense_rows:
        ref = expense.get("ref", f"anonymous-expense-{index}")
        group_size = title_group_size.get(index, 0)
        title_kind = "title_singleton" if group_size == 1 else (
            "title_repeated" if group_size > 1 else "title_absent"
        )
        expense_index = ensure("expense", ref, (
            "expense", expense.get("currency"), expense.get("locked") is True,
            bool(unit and expense.get("ledger_unit_ref") == unit.get("ref")), title_kind,
        ))
        title = expense.get("title")
        activity_index = activity_indices.get(str(current_ref))
        if activity_index is not None:
            edge(expense_index, activity_index, "expense_activity", bidirectional=True)
        if unit_index is not None and unit and expense.get("ledger_unit_ref") == unit.get("ref"):
            edge(expense_index, unit_index, "expense_current_unit", bidirectional=True)
        for participant_ref in expense.get("participant_refs", []):
            participant_index = participants.get(str(participant_ref))
            if participant_index is None:
                participant_index = ensure(
                    "participant", participant_ref, ("participant", "unresolved_reference")
                )
            edge(expense_index, participant_index, "expense_participant", bidirectional=True)
    expense_index_by_source = {
        index: indices[("expense", str(expense.get("ref", f"anonymous-expense-{index}")))]
        for index, expense in expense_rows
    }
    for title_key, source_indices in title_groups.items():
        if len(source_indices) < 2:
            continue
        title_group_index = ensure("title_group", title_key.hex(), ("title_group",))
        for source_index in source_indices:
            expense_index = expense_index_by_source[source_index]
            edge(expense_index, title_group_index, "same_title", bidirectional=True)

    # Debt topology is operation-visible only through the current readable
    # activity.  Currency labels are visible; numeric balances are not families.
    if anchor_readable:
        for debt in state.get("debts", []):
            if not isinstance(debt, dict) or debt.get("activity_ref") != current_ref:
                continue
            debtor = participants.get(str(debt.get("debtor_ref")))
            if debtor is None:
                debtor = ensure("participant", debt.get("debtor_ref"), ("participant", "unresolved_reference"))
            creditor = participants.get(str(debt.get("creditor_ref")))
            if creditor is None:
                creditor = ensure("participant", debt.get("creditor_ref"), ("participant", "unresolved_reference"))
            edge(debtor, creditor, f"debt:{debt.get('currency')}")

    return _canonical_graph(vertices, edges)


def initial_state_signature(state: Mapping[str, Any]) -> str:
    """Return the operation-independent canonical signature of an initial state."""
    if not isinstance(state, Mapping):
        raise TypeError("operation_state must be a mapping")
    neutral = _task_neutral_state(state)
    return sha256({
        "relationship_graph": _common_relationship_graph(neutral),
        "common_authorization": _common_permission_facts(neutral),
    })


def _initial_prompt(record: Mapping[str, Any]) -> str:
    trace = record.get("trace")
    if not isinstance(trace, list):
        raise ValueError("trace must be a list")
    for item in trace:
        if not isinstance(item, Mapping) or item.get("kind") != "model":
            continue
        context = item.get("context")
        if isinstance(context, Mapping) and isinstance(context.get("input_text"), str):
            return context["input_text"]
    raise ValueError("trace has no model input_text")


def _normalized_prompt_for_check(prompt: str) -> str:
    # The existing v2 normalizer handles participants, activities, expenses,
    # dates, numbers and whitespace.  Add only the stable typed unit reference
    # forms used by the builder; business names/titles remain because there is
    # no safe way to distinguish a name from an instruction word.
    text = re.sub(
        r"\bledger_unit_(?:selected|[0-9]{1,3})\b",
        "<ledger_unit>", prompt, flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\bledger_unit_ref\s*[:=]\s*[A-Za-z0-9_-]+",
        "ledger_unit_ref=<ledger_unit>", text, flags=re.IGNORECASE,
    )
    return normalize_prompt(text)


def _pair_id(kind: str, left: Mapping[str, Any], right: Mapping[str, Any]) -> str:
    """Bind pair IDs to recomputed state and prompt evidence, not row claims."""
    members = [{
        "sample_id": item["sample_id"],
        "operation": item["operation"],
        "split": item["split"],
        "operation_signature": item["operation_signature"],
        "full_state_signature": item["full_state_signature"],
        "normalized_prompt_sha256": item["normalized_prompt_sha256"],
    } for item in (left, right)]
    members.sort(key=lambda item: item["sample_id"])
    return sha256({"kind": kind, "members": members})[:24]


def _explicit_root_near_review(
    review: Any, *, left: Mapping[str, Any], right: Mapping[str, Any]
) -> bool:
    """Accept only an explicit root-agent adjudication bound to current evidence."""
    if not isinstance(review, Mapping):
        return False
    required_bindings = {
        "left_full_state_signature_sha256": left["full_state_signature"],
        "right_full_state_signature_sha256": right["full_state_signature"],
        "left_prompt_sha256": left["normalized_prompt_sha256"],
        "right_prompt_sha256": right["normalized_prompt_sha256"],
    }
    return (
        review.get("decision") == "distinct_initial_states"
        and review.get("review_kind") == "root_agent"
        and isinstance(review.get("reviewer_id"), str)
        and bool(review["reviewer_id"].strip())
        and isinstance(review.get("evidence"), str)
        and bool(review["evidence"].strip())
        and all(review.get(key) == value for key, value in required_bindings.items())
        and left["full_state_signature"] != right["full_state_signature"]
    )


def check_collection(
    rows: Sequence[Mapping[str, Any]],
    *,
    pair_dispositions: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Recompute and gate an in-memory collection of T1 v2 records.

    ``rows`` must be the records already held by the caller.  No path, bundle,
    database, or stored split is accepted or opened.  Returns summary counts,
    blockers, independently computed signatures and all cross-split pair
    findings.  Prompt bodies are intentionally never returned.  Optional
    near-pair dispositions must be explicit root-agent technical reviews bound
    to current state and prompt hashes. They cannot waive exact duplicates,
    state leaks, or the separate external human-review receipt for training.
    """
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
        raise TypeError("rows must be an in-memory sequence of record mappings")

    prepared: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    seen_ids: dict[str, int] = {}
    family_sets: dict[str, dict[str, set[str]]] = {
        operation: {split: set() for split in SPLITS} for operation in OPERATIONS
    }
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            blockers.append({"kind": "invalid_record", "row_index": index,
                             "detail": "record is not a mapping"})
            continue
        sample_id = row.get("sample_id", row.get("id"))
        if not isinstance(sample_id, str) or not sample_id.strip():
            sample_id = f"<missing-sample-id:{index}>"
            blockers.append({"kind": "missing_sample_id", "row_index": index})
        if sample_id in seen_ids:
            blockers.append({
                "kind": "duplicate_sample_id", "sample_id": sample_id,
                "first_row_index": seen_ids[sample_id], "row_index": index,
            })
        else:
            seen_ids[sample_id] = index

        split = row.get("split")
        if split not in SPLITS:
            blockers.append({"kind": "invalid_split", "sample_id": sample_id,
                             "split": split if isinstance(split, (str, int, float, bool)) else None})
            continue
        expected = row.get("expected")
        operation = expected.get("task_operation") if isinstance(expected, Mapping) else None
        tags = row.get("coverage_tags", [])
        boundary_tags = [tag for tag in tags if isinstance(tag, str) and tag.startswith("boundary_")] \
            if isinstance(tags, list) else []
        boundary_verified = False
        boundary_case = None
        if boundary_tags:
            if len(boundary_tags) != 1:
                blockers.append({"kind": "invalid_boundary_tag_count", "sample_id": sample_id,
                                 "count": len(boundary_tags)})
            else:
                try:
                    from .boundary import validate_boundary_gold
                    boundary_result = validate_boundary_gold(row)
                    boundary_case = boundary_result.get("case_id")
                    boundary_verified = boundary_result.get("valid") is True
                except Exception as exc:
                    blockers.append({"kind": "invalid_boundary_gold", "sample_id": sample_id,
                                     "detail": type(exc).__name__})
            if not boundary_verified and len(boundary_tags) == 1 and not any(
                item.get("kind") == "invalid_boundary_gold" and item.get("sample_id") == sample_id
                for item in blockers
            ):
                blockers.append({"kind": "invalid_boundary_gold", "sample_id": sample_id,
                                 "detail": "boundary validator did not return valid true"})
        elif not isinstance(tags, list):
            blockers.append({"kind": "invalid_coverage_tags", "sample_id": sample_id})

        if operation not in OPERATIONS and not boundary_verified:
            blockers.append({"kind": "invalid_operation", "sample_id": sample_id,
                             "operation": operation if isinstance(operation, str) else None})
        state = row.get("operation_state")
        if not isinstance(state, Mapping):
            blockers.append({"kind": "missing_operation_state", "sample_id": sample_id})
            continue
        try:
            operation_signature = (
                operation_state_signature(state, operation) if operation in OPERATIONS else None
            )
            full_state_signature = initial_state_signature(state)
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            blockers.append({"kind": "invalid_operation_state", "sample_id": sample_id,
                             "detail": type(exc).__name__})
            continue

        # Producer metadata is checked for integrity when present, but never
        # supplies the signature used for counts or pairwise isolation.
        supplied = row.get("operation_state_signature_sha256")
        if operation_signature is not None and supplied is not None and supplied != operation_signature:
            blockers.append({"kind": "operation_signature_metadata_mismatch",
                             "sample_id": sample_id,
                             "computed_signature": operation_signature})

        if boundary_verified:
            # Verified boundary cases are globally scanned below, but they are
            # never positive task-family evidence, including supported reads.
            pass
        elif operation in OPERATIONS:
            supported = isinstance(expected, Mapping) and expected.get("supported_in_v1") is True
            must_complete = isinstance(expected, Mapping) and expected.get("must_complete") is True
            case_type = row.get("case_type")
            if case_type not in {"supported_operation", "multi_turn"}:
                blockers.append({
                    "kind": "unverified_case_type", "sample_id": sample_id,
                    "detail": "only independently gold-guarded positive case types may count toward the family floor",
                })
            elif not supported or not must_complete:
                blockers.append({
                    "kind": "unverified_nonpositive_record", "sample_id": sample_id,
                    "detail": "non-positive rows require an independently validated boundary tag",
                })
            else:
                family_sets[operation][split].add(operation_signature)

        try:
            prompt = _initial_prompt(row)
            normalized = _normalized_prompt_for_check(prompt)
        except (TypeError, ValueError) as exc:
            blockers.append({"kind": "invalid_prompt_source", "sample_id": sample_id,
                             "detail": str(exc)})
            continue

        prepared.append({
            "sample_id": sample_id,
            "operation": operation,
            "split": split,
            "operation_signature": operation_signature,
            "full_state_signature": full_state_signature,
            "normalized_prompt": normalized,
            "normalized_prompt_sha256": sha256(normalized),
            "is_boundary": boundary_verified,
            "boundary_case_id": boundary_case,
        })

    family_counts: dict[str, dict[str, int]] = {}
    for operation in OPERATIONS:
        family_counts[operation] = {}
        for split in SPLITS:
            count = len(family_sets[operation][split])
            family_counts[operation][split] = count
            if split == "train" and count < TRAIN_MIN_FAMILIES:
                blockers.append({
                    "kind": "insufficient_independent_families", "operation": operation,
                    "split": split, "actual": count, "minimum": TRAIN_MIN_FAMILIES,
                })
            if split in {"validation", "sealed"} and count < EVAL_MIN_FAMILIES:
                blockers.append({
                    "kind": "insufficient_independent_families", "operation": operation,
                    "split": split, "actual": count, "minimum": EVAL_MIN_FAMILIES,
                })

    findings: list[dict[str, Any]] = []
    pair_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in prepared:
        if item["operation_signature"] is not None:
            pair_groups[("operation", item["operation_signature"])].append(item)
        pair_groups[("full_state", item["full_state_signature"])].append(item)

    for (scope, signature), members in sorted(pair_groups.items()):
        by_split: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in members:
            by_split[item["split"]].append(item)
        for left_split_index, left_split in enumerate(SPLITS):
            for right_split in SPLITS[left_split_index + 1:]:
                for left in by_split.get(left_split, []):
                    for right in by_split.get(right_split, []):
                        if scope == "operation" and left["operation"] != right["operation"]:
                            continue
                        finding_kind = (
                            "operation_state_leakage" if scope == "operation"
                            else "full_initial_state_leakage"
                        )
                        pair_key = _pair_id(finding_kind, left, right)
                        findings.append({
                            "finding_id": pair_key,
                            "kind": finding_kind,
                            "scope": scope,
                            "left": {"sample_id": left["sample_id"], "operation": left["operation"],
                                     "split": left["split"]},
                            "right": {"sample_id": right["sample_id"], "operation": right["operation"],
                                      "split": right["split"]},
                            "signature_sha256": signature,
                            "disposition": "blocking_leakage",
                        })

    # Prompt pairs are compared across every operation. Exact normalized text
    # is a hard leak; near candidates remain unresolved until explicitly
    # dispositioned by the root technical reviewer. Row review metadata is not
    # used to resolve a pair.
    split_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in prepared:
        split_groups[item["split"]].append(item)
    for left_split_index, left_split in enumerate(SPLITS):
        for right_split in SPLITS[left_split_index + 1:]:
            for left in split_groups.get(left_split, []):
                for right in split_groups.get(right_split, []):
                    left_prompt = left["normalized_prompt"]
                    right_prompt = right["normalized_prompt"]
                    exact = left_prompt == right_prompt
                    if exact:
                        seq, jac = 1.0, 1.0
                    else:
                        # Use the same fixed normalizer and metrics exported by
                        # signatures.py; normalized typed refs are idempotent.
                        seq, jac = prompt_similarity(left_prompt, right_prompt)
                    near = seq >= NEAR_SEQUENCE_THRESHOLD or jac >= NEAR_CHAR3_JACCARD_THRESHOLD
                    if not exact and not near:
                        continue
                    kind = "exact_prompt_duplicate" if exact else "near_prompt_candidate"
                    finding_id = _pair_id(kind, left, right)
                    disposition = "blocking_exact_duplicate" if exact else "unresolved_requires_root_review"
                    if not exact and _explicit_root_near_review(
                        (pair_dispositions or {}).get(finding_id), left=left, right=right
                    ):
                        disposition = "reviewed_distinct_by_root_agent"
                    findings.append({
                        "finding_id": finding_id,
                        "kind": kind,
                        "left": {"sample_id": left["sample_id"], "operation": left["operation"],
                                 "split": left["split"]},
                        "right": {"sample_id": right["sample_id"], "operation": right["operation"],
                                  "split": right["split"]},
                        "left_prompt_sha256": left["normalized_prompt_sha256"],
                        "right_prompt_sha256": right["normalized_prompt_sha256"],
                        "left_full_state_signature_sha256": left["full_state_signature"],
                        "right_full_state_signature_sha256": right["full_state_signature"],
                            "left_operation_signature_sha256": left["operation_signature"],
                            "right_operation_signature_sha256": right["operation_signature"],
                        "sequence_matcher_ratio": round(seq, 6),
                        "char3gram_jaccard": round(jac, 6),
                        "disposition": disposition,
                    })

    findings.sort(key=lambda item: (item["kind"], item["finding_id"]))
    pair_blockers = [item for item in findings if item["disposition"] in {
        "blocking_leakage", "blocking_exact_duplicate",
    }]
    blockers.extend({
        "kind": "cross_split_pair_finding",
        "finding_id": item["finding_id"],
        "finding_kind": item["kind"],
        "disposition": item["disposition"],
    } for item in pair_blockers)

    preparation_eligible = not blockers
    training_blockers = ["external_human_review_receipt_required"]
    if not preparation_eligible:
        training_blockers.append("collection_preparation_blocked")
    if any(item["disposition"] == "unresolved_requires_root_review" for item in findings):
        training_blockers.append("unresolved_near_prompt_pairs")
    return {
        "checker_version": "t1-collection-gate-v2",
        "rows_seen": len(rows),
        "rows_checked": len(prepared),
        "operation_family_counts": family_counts,
        "verified_boundary_rows": sum(item["is_boundary"] for item in prepared),
        "boundary_case_counts": {
            case: sum(item["is_boundary"] and item["boundary_case_id"] == case for item in prepared)
            for case in sorted({item["boundary_case_id"] for item in prepared if item["is_boundary"]})
        },
        "boundary_rows_excluded_from_positive_family_floor": sum(item["is_boundary"] for item in prepared),
        "pair_findings": findings,
        "pair_finding_count": len(findings),
        "unresolved_pair_count": sum(
            item["disposition"] == "unresolved_requires_root_review" for item in findings
        ),
        "blocking_pair_count": sum(
            item["disposition"] in {"blocking_leakage", "blocking_exact_duplicate"}
            for item in findings
        ),
        "blocking_issues": blockers,
        "preparation_eligible": preparation_eligible,
        "collection_passed": preparation_eligible,
        # The checker has no trusted human-review receipt input. Even a row's
        # self-reported review fields cannot make training eligible.
        "training_eligible": False,
        "training_admission": False,
        "training_blockers": training_blockers,
        "external_human_review_receipt_required": True,
        "human_review_metadata_is_trusted": False,
        "row_review_claims_pending": sum(
            1 for row in rows if isinstance(row, Mapping)
            and isinstance(row.get("review"), Mapping)
            and row["review"].get("human_review_pending") is True
        ),
        "human_review_policy": "row review metadata does not establish human review; an external receipt bound to the manifest and reviewed sample IDs is required",
        "thresholds": {
            "near_sequence_matcher_min": NEAR_SEQUENCE_THRESHOLD,
            "near_char3gram_jaccard_min": NEAR_CHAR3_JACCARD_THRESHOLD,
        },
    }


__all__ = ["OPERATIONS", "SPLITS", "initial_state_signature", "check_collection"]
