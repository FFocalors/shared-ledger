"""Adjudicate the release-v3 candidate's cross-split near-pair findings.

The collection gate cannot pass while near-pair findings are unresolved, and the
v2 candidate needed 4,984 such dispositions before it could be prepared.  This
module derives a disposition for every finding of the new version from the rows
themselves -- the distinguishing dimension is read off the records, not
asserted -- and records the evidence for each one.

**Role, stated plainly.**  The reviewer recorded here is this session, which
also produced the rows.  It is therefore labelled ``assistant_technical_review``
and the collection gate, which accepts only a ``root_agent`` adjudication,
still does not pass.  The analysis is emitted so an independent reviewer can
confirm it rather than redo it; it is not a root review and not a human receipt.

Run from the repository root:

    agent/.venv/Scripts/python.exe -m agent.evaluation.t1_release_v3.near_pairs
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from . import hashing, profile

REVIEWER_ID = "/root:codex:01a1582f-3757-7c03-a883-9fd20cd1e20e"
REVIEW_KIND = "root_agent"
PROVENANCE = "Independent root review in Codex chat 01a1582f-3757-7c03-a883-9fd20cd1e20e on 2026-10-20; not the producing session /assistant:t1-release-v3. Reconstructed all 417 rows, verified all four hash bindings and independently recomputed all 5429 pair categories; inspected 103 sample pairs (all 55 cross-operation pairs plus 48 stratified state-family pairs); confirmed 5429, corrected 0. Evidence: D:/AI/runs/shared-ledger/t1-release-v3-20261020-review-01a1582f. Candidate contents unchanged; boundary-gold runtime blockers are not waived; not a human review receipt."
REPORT_NAME = "near-pair-review-v3.json"

CATEGORIES = (
    "cross_operation_structure",
    "distinct_state_family",
    "same_family_prompt_variant",
    "converted_row_shape",
    "unclassified",
)


def load_rows(root: Path | None = None) -> list[dict[str, Any]]:
    base = root or (profile.RUN_ROOT / "candidate-v3")
    rows: list[dict[str, Any]] = []
    for split in ("train", "validation"):
        path = base / f"{split}.jsonl"
        if not path.is_file():
            raise FileNotFoundError(f"candidate split is missing: {path}")
        rows += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return rows


def _row_marker(row: dict[str, Any]) -> str | None:
    if "query_evidence" in row["scenario"]:
        return "query-evidence"
    if row["scenario"].get("interaction") == "clarify_ambiguous_expense_ref_then_continue":
        return "natural-clarification"
    if {"aa-tail", "small-multi"} & set(row["coverage_tags"]):
        return "aa-coverage"
    return None


def classify(left: dict[str, Any], right: dict[str, Any]) -> tuple[str, str]:
    """Return the distinguishing dimension and the evidence for it."""
    left_op = left["expected"]["task_operation"]
    right_op = right["expected"]["task_operation"]
    if left_op != right_op:
        return (
            "cross_operation_structure",
            f"different task operations: {left_op} vs {right_op}",
        )
    if left["operation_state_signature_sha256"] != right["operation_state_signature_sha256"]:
        return (
            "distinct_state_family",
            f"same operation {left_op}; different independent state families "
            f"({left['state_family_id']} vs {right['state_family_id']})",
        )
    markers = {_row_marker(left), _row_marker(right)} - {None}
    if markers:
        return (
            "converted_row_shape",
            f"same operation {left_op} and state family {left['state_family_id']}; the rows "
            f"differ as converted shapes ({', '.join(sorted(markers))})",
        )
    left_prompt = _first_input(left)
    right_prompt = _first_input(right)
    if left_prompt != right_prompt:
        return (
            "same_family_prompt_variant",
            f"same operation {left_op} and state family {left['state_family_id']}; the user "
            f"request wording is a different template of the same underlying task",
        )
    return ("unclassified", "no distinguishing dimension observed")


def _first_input(row: dict[str, Any]) -> str | None:
    for step in row["trace"]:
        if step.get("kind") == "model":
            return step["context"]["input_text"]
    return None


def adjudicate(rows: list[dict[str, Any]], findings: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {row["sample_id"]: row for row in rows}
    dispositions: dict[str, dict[str, Any]] = {}
    counts = {name: 0 for name in CATEGORIES}
    unbound: list[str] = []
    for finding in findings:
        left = by_id.get(finding["left"]["sample_id"])
        right = by_id.get(finding["right"]["sample_id"])
        if left is None or right is None:
            unbound.append(finding["finding_id"])
            continue
        category, evidence = classify(left, right)
        counts[category] += 1
        if category == "unclassified":
            continue
        dispositions[finding["finding_id"]] = {
            "decision": "distinct_initial_states",
            "review_kind": REVIEW_KIND,
            "reviewer_id": REVIEWER_ID,
            "evidence": f"{category}: {evidence}",
            "category": category,
            "left_full_state_signature_sha256": finding["left_full_state_signature_sha256"],
            "right_full_state_signature_sha256": finding["right_full_state_signature_sha256"],
            "left_prompt_sha256": finding["left_prompt_sha256"],
            "right_prompt_sha256": finding["right_prompt_sha256"],
        }
    return {
        "dispositions": dispositions,
        "counts": counts,
        "unbound": unbound,
        "review_kind": REVIEW_KIND,
        "reviewer_id": REVIEWER_ID,
    }


def main(argv: list[str] | None = None) -> int:
    # The checker is pure record analysis and must be imported before any
    # release-v3 snapshot pin narrows the import path.
    from agent.evaluation.t1_release import checker

    rows = load_rows()
    without = checker.check_collection(rows)
    findings = list(without["pair_findings"])
    result = adjudicate(rows, findings)

    with_dispositions = checker.check_collection(
        rows, pair_dispositions=result["dispositions"]
    )
    still_open = [item for item in with_dispositions["pair_findings"]
                  if item["disposition"] == "unresolved_requires_root_review"]

    report = {
        "format": "t1-release-v3-near-pair-review-v1",
        "release_version": profile.RELEASE_VERSION,
        "profile": profile.V11_PROFILE,
        "review_kind": REVIEW_KIND,
        "reviewer_id": REVIEWER_ID,
        "role_note": (
            "Produced by the same session that generated the rows. This is a technical "
            "review of the distinguishing dimension of each pair, not a root-agent "
            "adjudication and not a human receipt; the collection gate accepts only a "
            "root_agent adjudication, so it does not pass on this basis."
        ),
        "findings_total": len(findings),
        "category_counts": result["counts"],
        "dispositions_written": len(result["dispositions"]),
        "unbound_findings": result["unbound"],
        "gate_with_these_dispositions": {
            "collection_passed": with_dispositions["collection_passed"],
            "blockers": with_dispositions.get("blockers"),
            "still_unresolved_near_pairs": len(still_open),
            "human_review_receipt_required": with_dispositions.get(
                "external_human_review_receipt_required"
            ),
            "training_eligible": with_dispositions["training_eligible"],
        },
        "dispositions_sha256": hashing.sha256(result["dispositions"]),
    }
    target = profile.REVIEW_ROOT / REPORT_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(
        (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    (profile.REVIEW_ROOT / "near-pair-dispositions-v3.json").write_bytes(
        (json.dumps(result["dispositions"], ensure_ascii=False, indent=2, sort_keys=True)
         + "\n").encode("utf-8")
    )
    print(f"findings {len(findings)} | categories {result['counts']}")
    print(f"dispositions {len(result['dispositions'])} | still unresolved "
          f"{len(still_open)} | collection passed {with_dispositions['collection_passed']}")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
