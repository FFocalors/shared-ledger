"""Build the release-v3 train-only review packet.

The root business review reads a 34-row train-only packet and the human receipt
is signed against that packet's identity.  This version therefore needs its own
packet: a new selection, new row and selection hashes, and a new pending
receipt.  No v2 selection, packet identity or receipt is reused.

The selection is deterministic and is required to contain, at minimum, every
row this version changed plus one of each boundary case, so a reviewer sees the
RBR fixes rather than an arbitrary sample.

Run from the repository root:

    agent/.venv/Scripts/python.exe -m agent.evaluation.t1_release_v3.packet
"""
from __future__ import annotations

import html
import json
import random
import sys
from pathlib import Path
from typing import Any

from . import hashing, profile

PACKET_ROWS = 34
SELECTION_SEED = 20261019
RECEIPT_SCHEMA = "t1-human-review-receipt-v3"
REQUIRED_COVERAGE = (
    "rbr01-query-evidence",
    "rbr03-natural-clarification",
    "rbr04-aa-tail",
    "boundary",
    "presentation",
    "financial-write",
    "read",
)


class PacketError(ValueError):
    pass


def _is_boundary(row: dict[str, Any]) -> bool:
    return row["scenario"].get("boundary_case") is not None


def _stratum(row: dict[str, Any]) -> str:
    if _is_boundary(row):
        return "boundary"
    if row["case_type"] == "multi_turn":
        return "clarification"
    operation = row["expected"]["task_operation"]
    if operation.startswith("read."):
        return "read"
    if operation == "expense.presentation.update":
        return "presentation"
    return "financial-write"


def _coverage(row: dict[str, Any]) -> set[str]:
    tags: set[str] = set()
    scenario = row["scenario"]
    if "query_evidence" in scenario:
        tags.add("rbr01-query-evidence")
    if scenario.get("interaction") == "clarify_ambiguous_expense_ref_then_continue":
        tags.add("rbr03-natural-clarification")
    if {"aa-tail", "small-multi"} & set(row["coverage_tags"]):
        tags.add("rbr04-aa-tail")
    if _is_boundary(row):
        tags.add("boundary")
    tags.add(_stratum(row))
    return tags


def select_rows(rows: list[dict[str, Any]], *, n: int = PACKET_ROWS,
                seed: int = SELECTION_SEED) -> list[dict[str, Any]]:
    """Pick a deterministic, coverage-complete train-only selection."""
    pool = sorted((row for row in rows if row["split"] == "train"),
                  key=lambda row: row["sample_id"])
    if len(pool) < n:
        raise PacketError("not enough train rows for the packet")

    chosen: list[dict[str, Any]] = []
    chosen_ids: set[str] = set()

    def take(row: dict[str, Any]) -> None:
        if row["sample_id"] not in chosen_ids and len(chosen) < n:
            chosen.append(row)
            chosen_ids.add(row["sample_id"])

    # Mandatory rows, in a stable order: one per boundary case, one per
    # operation, then a bounded sample of each RBR-changed shape.
    seen_cases: set[str] = set()
    for row in pool:
        case = row["scenario"].get("boundary_case")
        if case is not None and case not in seen_cases:
            seen_cases.add(case)
            take(row)
    seen_ops: set[str] = set()
    for row in pool:
        operation = row["expected"]["task_operation"]
        if operation not in seen_ops:
            seen_ops.add(operation)
            take(row)
    # RBR01 is the blocking fix, so every no-match row is included; the other
    # changed shapes are sampled.
    for tag, cap in (("rbr01-query-evidence", 3),
                     ("rbr03-natural-clarification", 2),
                     ("rbr04-aa-tail", 2)):
        taken = 0
        for row in pool:
            if taken >= cap:
                break
            if tag in _coverage(row) and row["sample_id"] not in chosen_ids:
                take(row)
                taken += 1

    # Fill the remainder round-robin across strata so the packet stays a
    # balanced sample rather than a pile of whichever shape came first.
    rng = random.Random(seed)
    by_stratum: dict[str, list[dict[str, Any]]] = {}
    for row in pool:
        if row["sample_id"] in chosen_ids:
            continue
        by_stratum.setdefault(_stratum(row), []).append(row)
    for bucket in by_stratum.values():
        rng.shuffle(bucket)
    order = sorted(by_stratum)
    while len(chosen) < n and any(by_stratum[name] for name in order):
        for name in order:
            if by_stratum[name] and len(chosen) < n:
                take(by_stratum[name].pop())

    covered: set[str] = set()
    for row in chosen:
        covered |= _coverage(row)
    missing = [name for name in REQUIRED_COVERAGE if name not in covered]
    if missing:
        raise PacketError(f"packet does not cover required strata: {missing}")
    return chosen


def _row_view(row: dict[str, Any]) -> dict[str, Any]:
    models = [step for step in row["trace"] if step.get("kind") == "model"]
    tools = [step for step in row["trace"] if step.get("kind") == "tool_result"]
    return {
        "sample_id": row["sample_id"],
        "split": row["split"],
        "case_type": row["case_type"],
        "operation": row["expected"]["task_operation"],
        "semantic": row["expected"]["semantic"],
        "stratum": _stratum(row),
        "coverage": sorted(_coverage(row)),
        "user_request": models[0]["context"]["input_text"] if models else None,
        "final_input": models[-1]["context"]["input_text"] if models else None,
        "clarification": next(
            (step["target"]["prompt"] for step in models
             if step.get("target", {}).get("kind") == "clarify"), None,
        ),
        "user_followup": next(
            (step["text"] for step in row["trace"] if step.get("kind") == "user_followup"), None,
        ),
        "answer": next(
            (step["target"] for step in models
             if step.get("target", {}).get("kind") == "answer"), None,
        ),
        "proposal": next(
            (step["target"] for step in models
             if step.get("target", {}).get("kind") == "propose"), None,
        ),
        "query_evidence": row["scenario"].get("query_evidence"),
        "tool_result_items": sum(
            len(step.get("result", {}).get("body", {}).get("items", [])) for step in tools
        ),
        "row_sha256": hashing.sha256(row),
    }


def build(candidate_root: Path | None = None) -> dict[str, Any]:
    root = candidate_root or (profile.RUN_ROOT / "candidate-v3")
    rows: list[dict[str, Any]] = []
    for split in ("train", "validation"):
        path = root / f"{split}.jsonl"
        if not path.is_file():
            raise PacketError(f"candidate split is missing: {path}")
        rows += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    selected = [_row_view(row) for row in select_rows(rows)]

    selection_sha = hashing.sha256({
        "selection_seed": SELECTION_SEED,
        "selections": [{"sample_id": item["sample_id"], "row_sha256": item["row_sha256"]}
                       for item in selected],
    })
    markdown = _render_markdown(selected, selection_sha)
    html_body = _render_html(selected, selection_sha)
    packet_sha = hashing.sha256({
        "markdown_sha256": hashing.sha256(markdown),
        "html_sha256": hashing.sha256(html_body),
        "selection_sha256": selection_sha,
    })

    target = profile.REVIEW_ROOT / "human-review-v3"
    target.mkdir(parents=True, exist_ok=True)
    (target / "train-review-v3.md").write_bytes(markdown.encode("utf-8"))
    (target / "train-review-v3.html").write_bytes(html_body.encode("utf-8"))
    (target / "selection-hashes.json").write_bytes(
        (json.dumps({
            "selection_seed": SELECTION_SEED,
            "selection_sha256": selection_sha,
            "rows": [{"sample_id": item["sample_id"], "row_sha256": item["row_sha256"]}
                     for item in selected],
        }, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )

    receipt = {
        "schema": RECEIPT_SCHEMA,
        "status": "pending",
        "decision": None,
        "reviewer_kind": None,
        "reviewer_id": None,
        "evidence": None,
        "human_reviewed": False,
        "packet_sha256": packet_sha,
        "selection_sha256": selection_sha,
        "release_version": profile.RELEASE_VERSION,
        "profile": profile.V11_PROFILE,
        "selections": [
            {"sample_id": item["sample_id"], "split": item["split"],
             "row_sha256": item["row_sha256"], "stratum": item["stratum"]}
            for item in selected
        ],
        "training_eligible": False,
        "training_blockers": [
            "root_near_pair_adjudication_pending",
            "p2_baseline_calibration_pending",
            "t2_authorization_pending",
        ],
    }
    receipt_path = target / "pending-human-review-receipt.json"
    receipt_path.write_bytes(
        (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )

    manifest = {
        "format": "t1-release-v3-human-review-packet-manifest-v1",
        "release_version": profile.RELEASE_VERSION,
        "profile": profile.V11_PROFILE,
        "row_count": len(selected),
        "split": "train",
        "selection_seed": SELECTION_SEED,
        "packet_sha256": packet_sha,
        "selection_sha256": selection_sha,
        "receipt_status": "pending",
        "receipt_schema": RECEIPT_SCHEMA,
        "coverage": {
            name: sum(1 for item in selected if name in item["coverage"])
            for name in REQUIRED_COVERAGE
        },
        "files": [
            {"path": name, "sha256": hashing.sha256((target / name).read_bytes()),
             "bytes": (target / name).stat().st_size}
            for name in ("train-review-v3.md", "train-review-v3.html",
                         "selection-hashes.json", "pending-human-review-receipt.json")
        ],
    }
    manifest_path = target / "human-review-manifest.json"
    manifest_path.write_bytes(
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    return {"manifest": manifest, "target": str(target)}


def _render_markdown(selected: list[dict[str, Any]], selection_sha: str) -> str:
    lines = [
        "# T1 release-v3 train-only review packet",
        "",
        f"Rows: {len(selected)} (train only) | selection SHA-256: `{selection_sha}`",
        "",
        "This is a **pending** packet. It has no human receipt: review it, then sign the",
        "receipt to close the human-review gate. `training_eligible` stays false until it is",
        "signed and the other gates close.",
        "",
    ]
    for index, item in enumerate(selected, start=1):
        lines += [f"## {index}. {item['sample_id']}", ""]
        lines += [f"- stratum: {item['stratum']} | coverage: {', '.join(item['coverage'])}"]
        lines += [f"- case type: {item['case_type']} | operation: {item['operation']}"]
        lines += [f"- user request: {item['user_request']}"]
        if item["clarification"]:
            lines += [f"- clarification: {item['clarification']}"]
            lines += [f"- user follow-up: {item['user_followup']}"]
        if item["query_evidence"]:
            evidence = item["query_evidence"]
            lines += [
                f"- query evidence: {evidence['query_ref']} | {evidence['zero_class']} | "
                f"returned {evidence['returned_count']} | matched {evidence['matched_count']} | "
                f"complete {evidence['page_complete']}"
            ]
        if item["answer"]:
            lines += [f"- answer: {item['answer']['text']} | citations: {item['answer']['citations']}"]
        if item["proposal"]:
            lines += [f"- proposal: {json.dumps(item['proposal'], ensure_ascii=False)}"]
        lines += [f"- final input: {item['final_input']}"]
        lines += [f"- row SHA-256: `{item['row_sha256']}`", ""]
    return "\n".join(lines) + "\n"


def _render_html(selected: list[dict[str, Any]], selection_sha: str) -> str:
    def esc(value: Any) -> str:
        return html.escape(json.dumps(value, ensure_ascii=False) if not isinstance(value, str)
                           else value)

    parts = [
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>",
        "<title>T1 release-v3 train-only review packet</title></head><body>",
        "<h1>T1 release-v3 train-only review packet</h1>",
        f"<p>Rows: {len(selected)} (train only). Selection SHA-256: "
        f"<code>{selection_sha}</code></p>",
        "<p><strong>Pending.</strong> No human receipt yet; <code>training_eligible</code> "
        "stays false until this is signed and the other gates close.</p>",
    ]
    for index, item in enumerate(selected, start=1):
        anchor = html.escape(item["sample_id"])
        parts.append(f"<section id='{anchor}'><h2>{index}. {anchor}</h2><ul>")
        parts.append(f"<li>stratum: {esc(item['stratum'])} | coverage: "
                     f"{esc(', '.join(item['coverage']))}</li>")
        parts.append(f"<li>case type: {esc(item['case_type'])} | operation: "
                     f"{esc(item['operation'])}</li>")
        parts.append(f"<li>user request: {esc(item['user_request'])}</li>")
        if item["clarification"]:
            parts.append(f"<li>clarification: {esc(item['clarification'])}</li>")
            parts.append(f"<li>user follow-up: {esc(item['user_followup'])}</li>")
        if item["query_evidence"]:
            evidence = item["query_evidence"]
            parts.append(
                f"<li>query evidence: {esc(evidence['query_ref'])} | "
                f"{esc(evidence['zero_class'])} | returned {evidence['returned_count']} | "
                f"matched {evidence['matched_count']} | complete "
                f"{esc(evidence['page_complete'])}</li>"
            )
        if item["answer"]:
            parts.append(f"<li>answer: {esc(item['answer']['text'])} | citations: "
                         f"{esc(item['answer']['citations'])}</li>")
        if item["proposal"]:
            parts.append(f"<li>proposal: {esc(item['proposal'])}</li>")
        parts.append(f"<li>final input: {esc(item['final_input'])}</li>")
        parts.append(f"<li>row SHA-256: <code>{item['row_sha256']}</code></li>")
        parts.append("</ul></section>")
    parts.append("</body></html>")
    return "\n".join(parts) + "\n"


def validate_external_receipt(packet_manifest: dict[str, Any],
                              receipt: dict[str, Any]) -> dict[str, Any]:
    """The human-review gate.  Only a signed, human-authored receipt can pass."""
    for field in ("schema", "packet_sha256", "selection_sha256"):
        if receipt.get(field) != (
            RECEIPT_SCHEMA if field == "schema" else packet_manifest[field]
        ):
            raise PacketError(f"receipt {field} does not bind this packet")
    if receipt.get("status") == "pending":
        if receipt.get("human_reviewed") is not False or receipt.get("decision") is not None:
            raise PacketError("a pending receipt must not claim a review")
        return {"human_reviewed": False, "training_eligible": False,
                "training_blockers": receipt.get("training_blockers", [])}
    if not (
        receipt.get("status") == "approved"
        and receipt.get("human_reviewed") is True
        and receipt.get("decision") == "approved"
        and receipt.get("reviewer_kind") == "human"
        and isinstance(receipt.get("reviewer_id"), str) and receipt["reviewer_id"]
        and isinstance(receipt.get("evidence"), str) and receipt["evidence"]
    ):
        raise PacketError("an approved receipt needs a named human reviewer and evidence")
    return {
        "human_reviewed": True,
        "training_eligible": False,
        "training_blockers": [
            "root_near_pair_adjudication_pending",
            "p2_baseline_calibration_pending",
            "t2_authorization_pending",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    result = build()
    manifest = result["manifest"]
    print(f"packet rows {manifest['row_count']} | coverage {manifest['coverage']}")
    print(f"packet_sha256 {manifest['packet_sha256']}")
    print(f"selection_sha256 {manifest['selection_sha256']}")
    print(f"wrote {result['target']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
