"""Build the release-v3 candidate: every row, all four RBR fixes, fresh gates.

Run from the repository root:

    agent/.venv/Scripts/python.exe -m agent.evaluation.t1_release_v3.build_candidate

What this does, in order:

1. freeze the sources this preparation depends on (its own manifest, no v2 receipt);
2. generate every row with the frozen v2 generator, in an isolated process;
3. convert each row to the frozen offline v1.1 profile, applying RBR01, RBR02,
   RBR03 and RBR04 where they apply and carrying every other row over unchanged;
4. validate every row against the release-v3 envelope and its own semantic check;
5. re-run the collection gate: schema, per-row gold, family floors, leakage and
   near-pair analysis;
6. write train and validation, and hold sealed.

Sealed is generated and validated in memory but **not written**: under the v2
discipline it is written last under a one-shot root receipt, and the near-pair
findings this version produces have not been adjudicated by root yet.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from . import profile, rbr03, rbr04

# The collection checker and the signature helpers are pure record analysis and
# must be imported before the release-v3 snapshot pin narrows the import path.
from agent.evaluation.t1_release import checker, signatures as v2_signatures

READ_OPS = ("read.activities", "read.expenses", "read.debts")
PRESENTATION = "expense.presentation.update"
# Family indices whose presentation catalogue holds exactly one expense.
SINGLE_CANDIDATE = (0, 15, 30, 45)
REPORT_NAME = "candidate-report.json"
# key -> (tag, base-currency override)
BASE_CASE_INDEX = {
    f"base:{split}:{g}:{tag}": (tag, base_currency)
    for split, g, tag, _amount, _participants, _currency, _fx, base_currency
    in rbr04.BASE_AA_CASES
}


def _unit_role(g: int) -> str:
    """Mirror of the generator's ledger-unit role selection."""
    group = (g % 20) // 4
    if group % 2:
        return "large_child" if group == 3 else "large_root"
    return "legacy_unscoped" if group == 2 else "normal_root"


def is_ambiguous_presentation(g: int) -> bool:
    return g not in SINGLE_CANDIDATE


def generation_requests() -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for op in profile.OPERATIONS:
        for g in range(60):
            request: dict[str, Any] = {
                "key": f"{op}:{g}", "operation": op, "family_index": g,
            }
            if op in READ_OPS:
                request["with_bindings"] = True
            if op == PRESENTATION and is_ambiguous_presentation(g):
                request["clarification_policy"] = "returned_facts"
            requests.append(request)
    for g in (1, 22, 41):
        requests.append({"key": f"multiturn:{g}", "kind": "multiturn_create", "family_index": g})
    for op, g in {"read.activities": 14, "read.expenses": 4, "read.debts": 0}.items():
        for variant in ("empty", "narrow"):
            requests.append({
                "key": f"{op}:{g}:{variant}", "operation": op, "family_index": g,
                "read_variant": variant, "with_bindings": True,
            })
    for _split, g, _participants, tag, amount in rbr04.RBR04_CASES:
        requests.append({
            "key": f"rbr04:{g}:{tag}", "operation": "expense.create", "family_index": g,
            "amount_override": amount, "variant_tag": tag,
        })
    for split, g, tag, amount, participants, currency, fx_rate, base_currency \
            in rbr04.BASE_AA_CASES:
        requests.append({
            "key": f"base:{split}:{g}:{tag}",
            "operation": "read.expenses",
            "family_index": g,
            "variant_tag": tag,
            # read.expenses trims the allowlist by g % 3, and a large-child
            # unit reserves one further participant, so the bound count is
            # widened to leave exactly this split headcount.
            "participant_count_override": (
                participants + (g % 3) + (1 if _unit_role(g) == "large_child" else 0)
            ),
            "state_overrides": {
                "expense_amounts": [amount],
                "split_participant_count": participants,
                **({"expense_currency": currency, "fx_rate": fx_rate} if currency else {}),
            },
        })
    requests.append({"key": "boundary", "kind": "boundary"})
    return requests


def is_no_match_read(record: dict[str, Any]) -> bool:
    return bool(record["scenario"].get("empty_result_citation_gap"))


def build_rows(generated: dict[str, Any], *, c: Any, v11: Any, v11_package: Any,
               data_signature: Any, namespace: Any, manifest_sha: str,
               protocol_sha: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from pydantic import TypeAdapter

    from . import convert, hashing, v11_evidence

    bound_adapter = TypeAdapter(v11.V1.BoundReference)
    rows: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []

    for key, record in generated["rows"].items():
        scenario = record["scenario"]
        operation = record["expected"]["task_operation"]
        note: dict[str, Any] = {"source_key": key, "operation": operation, "rbr_items": []}

        if isinstance(scenario, dict) and scenario.get("empty_result_citation_gap") is True:
            private = generated["contexts"][key]
            row = convert.convert_no_match_read_row(
                c=c, v11=v11, namespace=namespace,
                sample_key=f"t1-release-v3-{record['split']}-{key.replace(':', '-')}",
                record=record,
                bound_references=[bound_adapter.validate_python(item) for item in private["bound"]],
                scope_activity_id=_uuid(private["activity_ids"][0]),
                title_filter=convert.converted_title_filter(record),
                turn_id=_uuid(private["turn"]),
            )
            note["rbr_items"].extend([profile.RBR01_QUERY_EVIDENCE, profile.RBR02_NO_CONSUMED_HINT])
            note["zero_class"] = row["scenario"]["query_evidence"]["zero_class"]
        else:
            row = convert.convert_write_row(v11=v11_package, record=record)
            if _hint_present(record):
                note["rbr_items"].append(profile.RBR02_NO_CONSUMED_HINT)
            if scenario.get("interaction") == "clarify_ambiguous_expense_ref_then_continue":
                rbr03.validate_natural_clarification(row)
                note["rbr_items"].append(profile.RBR03_NATURAL_CLARIFICATION)
            if _variant_tag(record) in {"aa-tail", "small-multi"}:
                note["rbr_items"].append(profile.RBR04_AA_TAIL_COVERAGE)
            if key in BASE_CASE_INDEX:
                tag, base_currency = BASE_CASE_INDEX[key]
                row, audits = convert.attach_aa_base_amounts(
                    row, base_currency_override=base_currency,
                )
                _check_base_expectation(tag, audits)
                note["rbr_items"].append(profile.RBR04_AA_TAIL_COVERAGE)
                note["base_aa"] = audits
                note["base_share_detail"] = {
                    "source_key": key,
                    "sample_id": row["sample_id"],
                    "audit": audits,
                }

        row = _finalize(row, data_signature=data_signature, manifest_sha=manifest_sha,
                        protocol_sha=protocol_sha)
        rows.append(row)
        note["sample_id"] = row["sample_id"]
        note["split"] = row["split"]
        notes.append(note)

    return rows, notes


def _uuid(value: str):
    import uuid

    return uuid.UUID(value)


def _hint_present(record: dict[str, Any]) -> bool:
    from . import convert

    return any(
        hint in step["context"]["input_text"]
        for step in record["trace"] if step["kind"] == "model"
        for hint in convert.TRAINING_ONLY_HINTS
    )


def _variant_tag(record: dict[str, Any]) -> str:
    tags = record.get("coverage_tags", [])
    for tag in ("aa-tail", "small-multi"):
        if tag in tags:
            return tag
    return ""


def _check_base_expectation(tag: str, audits: list[dict[str, Any]]) -> None:
    """The case must produce exactly the two-column shape B2 asks for."""
    expected = rbr04.BASE_AA_EXPECTATIONS[tag]
    if len(audits) != 1:
        raise SystemExit(f"base case {tag} did not allocate exactly one expense")
    audit = audits[0]
    if audit["original_shares"] != expected["original_shares"]:
        raise SystemExit(
            f"base case {tag}: original column {audit['original_shares']} != "
            f"{expected['original_shares']}"
        )
    if audit["base_shares"] != expected["base_shares"]:
        raise SystemExit(
            f"base case {tag}: base column {audit['base_shares']} != {expected['base_shares']}"
        )
    if audit["original_has_tail"] != expected["original_has_tail"] or \
            audit["base_has_tail"] != expected["base_has_tail"]:
        raise SystemExit(f"base case {tag}: tail presence differs from the declared case")


def _finalize(row: dict[str, Any], *, data_signature: Any, manifest_sha: str,
              protocol_sha: str) -> dict[str, Any]:
    from . import hashing, profile as profile_module

    row["scenario_signature_sha256"] = hashing.sha256(row["scenario"])
    # A base-coverage row rewrites its ledger projection, so the operation-state
    # signature is recomputed from the row that is actually written.  Boundary
    # rows may have no task operation; their signature was computed at build.
    operation = row["expected"]["task_operation"]
    if operation is not None:
        row["operation_state_signature_sha256"] = v2_signatures.operation_state_signature(
            row["operation_state"], operation,
        )
    row["normalized_scenario_signature_sha256"] = hashing.sha256(
        data_signature.scenario_projection(row["fixture_state"], row)
    )
    row["baseline_snapshot_manifest_sha256"] = manifest_sha
    row["protocol_fingerprint_sha256"] = protocol_sha
    row["release_version"] = profile_module.RELEASE_VERSION
    row["generator_version"] = profile_module.GENERATOR_VERSION
    row["protocol_profile"] = profile_module.V11_PROFILE
    row["versions"] = {
        "api": profile_module.V11_API_VERSION,
        "semantic": profile_module.V11_SEMANTIC_VERSION,
        "operations": profile_module.V11_OPERATIONS_VERSION,
        "trajectory": profile_module.V11_TRAJECTORY_VERSION,
        "execution_key": profile_module.V11_EXECUTION_KEY_VERSION,
    }
    row["review"]["reviewer_id"] = "t1-release-v3-checker"
    row["review"]["review_note"] = (
        "Synthetic release-v3 candidate converted to the frozen offline protocol v1.1.0 "
        "profile. Automated checks are not human review; pending independent review."
    )
    return row


def main(argv: list[str] | None = None) -> int:
    from . import bridge, freeze, hashing, runtime
    from . import snapshot as snapshot_module

    # The collection checker is pure record analysis (it imports only the
    # signature helpers), and it must be imported *before* the release-v3 pin
    # narrows `agent.__path__` to the snapshot, where the v2 tooling does not
    # exist.  It is imported at module scope above for the same reason.

    manifest = snapshot_module.verify_snapshot()

    # --- 1. fresh source freeze -------------------------------------------
    source_manifest = freeze.freeze_source_manifest()
    freeze.write_source_manifest(source_manifest)
    freeze.verify_source_manifest(source_manifest)

    # --- 2. generate every row in the isolated v2 process ------------------
    generated = bridge.generate_rows(generation_requests())

    # --- 3. convert ---------------------------------------------------------
    c, v11_package, data_signature, _simulator = runtime.baseline_modules()
    from . import v11_evidence

    v11 = v11_evidence.api(v11_package)
    import uuid

    rows, notes = build_rows(
        generated, c=c, v11=v11, v11_package=v11_package,
        data_signature=data_signature,
        namespace=uuid.UUID(generated["namespace"]),
        manifest_sha=manifest["snapshot_manifest_sha256"],
        protocol_sha=freeze._sha256_file(
            freeze.AGENT_DIR / profile.V11_MANIFEST_RELATIVE
        ),
    )

    # --- 4. per-row validation ---------------------------------------------
    validator = runtime.make_v3_validator()
    failures: list[dict[str, Any]] = []
    for row in rows:
        errors = sorted(validator.iter_errors(row), key=lambda e: list(e.path))
        if errors:
            failures.append({
                "sample_id": row["sample_id"],
                "errors": ["/".join(str(p) for p in e.path) + ": " + e.message for e in errors[:3]],
            })
            continue
        hint = _hint_present(row)
        if hint:
            failures.append({"sample_id": row["sample_id"], "errors": ["training-only hint survived"]})
    if failures:
        for item in failures[:10]:
            print("  FAIL", item["sample_id"], item["errors"])
        raise SystemExit(f"{len(failures)} rows failed release-v3 validation")

    # --- 4b. deterministic replay -----------------------------------------
    # Every converted tool observation must still re-derive byte-for-byte from
    # its own fixture through the frozen simulator.
    simulator = _simulator
    replayed = 0
    replay_failures: list[dict[str, Any]] = []
    for row in rows:
        for step in row["trace"]:
            if step.get("kind") != "tool_result":
                continue
            replayed += 1
            try:
                again = simulator.simulate_read(
                    step["fixture_state"], step["request"],
                    observed_at=step["observed_at"], context_version=step["context_version"],
                    replay_key=step["replay_key"],
                ).model_dump(mode="json")
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                replay_failures.append({"sample_id": row["sample_id"],
                                        "error": f"{type(exc).__name__}: {exc}"})
                continue
            if again != step["result"]:
                replay_failures.append({"sample_id": row["sample_id"], "error": "result differs"})
    if replay_failures:
        for item in replay_failures[:10]:
            print("  REPLAY FAIL", item["sample_id"], item["error"])
        raise SystemExit(f"{len(replay_failures)} tool observations failed deterministic replay")

    # --- 5. collection gate -------------------------------------------------
    gate = checker.check_collection(rows)

    # 5b. Near-pair analysis over every row, sealed included.  Each finding is
    # classified by the dimension that actually distinguishes its two rows.  The
    # reviewer recorded is this session, so the collection gate -- which accepts
    # only a root_agent adjudication -- still does not pass on it; the analysis
    # exists so an independent reviewer can confirm and re-issue it.
    from . import near_pairs

    review = near_pairs.adjudicate(rows, list(gate.get("pair_findings", [])))
    gated = checker.check_collection(rows, pair_dispositions=review["dispositions"])
    near_review = {
        "format": "t1-release-v3-near-pair-review-v1",
        "release_version": profile.RELEASE_VERSION,
        "profile": profile.V11_PROFILE,
        "review_kind": near_pairs.REVIEW_KIND,
        "reviewer_id": near_pairs.REVIEWER_ID,
        "provenance": near_pairs.PROVENANCE,
        "role_note": (
            "A technical review produced by the session that generated the rows. It is not "
            "a root_agent adjudication and not a human receipt, so the collection gate does "
            "not pass on it; an independent reviewer must re-issue the same decisions in the "
            "root role."
        ),
        "findings_total": len(gate.get("pair_findings", [])),
        "category_counts": review["counts"],
        "dispositions_written": len(review["dispositions"]),
        "unbound_findings": review["unbound"],
        "gate_if_reissued_by_root": {
            "collection_passed": gated["collection_passed"],
            "still_unresolved": sum(
                1 for item in gated["pair_findings"]
                if item["disposition"] == "unresolved_requires_root_review"
            ),
            "human_review_receipt_required": gated.get("external_human_review_receipt_required"),
            "training_eligible": gated["training_eligible"],
        },
        "dispositions_sha256": hashing.sha256(review["dispositions"]),
    }
    (profile.REVIEW_ROOT / near_pairs.REPORT_NAME).write_bytes(
        (json.dumps(near_review, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        .encode("utf-8")
    )
    (profile.REVIEW_ROOT / "near-pair-dispositions-v3.json").write_bytes(
        (json.dumps(review["dispositions"], ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        .encode("utf-8")
    )

    # --- 6. write -----------------------------------------------------------
    target = profile.RUN_ROOT / "candidate-v3"
    target.mkdir(parents=True, exist_ok=True)
    payload_sha: dict[str, str] = {}
    row_counts: dict[str, int] = {}
    for split in profile.SPLITS:
        split_rows = [row for row in rows if row["split"] == split]
        row_counts[split] = len(split_rows)
        if split == "sealed":
            # Held: sealed is written last under its own one-shot root receipt.
            continue
        payload = "\n".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) for row in split_rows
        ) + "\n"
        path = target / f"{split}.jsonl"
        path.write_bytes(payload.encode("utf-8"))
        payload_sha[split] = hashing.sha256(path.read_bytes())

    freeze.verify_source_manifest(source_manifest)

    report = {
        "format": "t1-release-v3-candidate-report-v1",
        "release_version": profile.RELEASE_VERSION,
        "profile": profile.V11_PROFILE,
        "versions": {
            "api": profile.V11_API_VERSION, "semantic": profile.V11_SEMANTIC_VERSION,
            "operations": profile.V11_OPERATIONS_VERSION,
            "trajectory": profile.V11_TRAJECTORY_VERSION,
            "execution_key": profile.V11_EXECUTION_KEY_VERSION,
        },
        "source_manifest_sha256": source_manifest["source_manifest_sha256"],
        "snapshot_manifest_sha256": manifest["snapshot_manifest_sha256"],
        "row_count": len(rows),
        "row_counts": row_counts,
        "payload_sha256": payload_sha,
        "sealed_written": False,
        "sealed_hold_reason": (
            "sealed is written last under its own one-shot receipt; the near-pair findings "
            "of this version have not been adjudicated by root"
        ),
        "rbr_items_applied": {
            item: sum(1 for note in notes if item in note["rbr_items"])
            for item in profile.ACTIVE_RBR_ITEMS
        },
        "aa_quantum_ruling": rbr04.QUANTUM_RULING,
        "base_aa_cases": [
            {"source_key": note["source_key"], **note["base_aa"][0]}
            for note in notes if note.get("base_aa")
        ],
        "near_pair_review": near_review,
        "validation": {
            "rows_validated": len(rows),
            "failures": 0,
            "tool_observations_replayed": replayed,
            "replay_failures": 0,
        },
        "collection_gate": {
            "collection_passed": gate.get("collection_passed"),
            # check_collection reports these under ``blocking_issues``; the
            # earlier ``blockers`` key never existed and always read as empty.
            "blocking_issues": gate.get("blocking_issues"),
            "blocking_issue_count": len(gate.get("blocking_issues") or []),
            "near_pair_findings": len(gate.get("pair_findings", [])),
            "operation_family_counts": gate.get("operation_family_counts"),
            "training_eligible": gate.get("training_eligible"),
        },
        "external_gates_pending": [
            "root adjudication of this version's near-pair findings",
            "new train-only review packet and a genuine human review receipt",
            "P2 baseline calibration",
            "explicit T2 authorization",
        ],
        "scope_note": (
            "This is a prepared candidate version, not an admitted dataset: training_eligible "
            "stays false until the external gates above are closed."
        ),
    }
    report_path = profile.REVIEW_ROOT / REPORT_NAME
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(
        (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    print(f"rows {len(rows)} | counts {row_counts}")
    print(f"rbr applied {report['rbr_items_applied']}")
    print(f"base cases {len(report['base_aa_cases'])} | near pairs "
          f"{report['near_pair_review']['findings_total']} "
          f"{report['near_pair_review']['category_counts']}")
    print(f"collection passed: {report['collection_gate']['collection_passed']} | "
          f"near-pair findings: {report['collection_gate']['near_pair_findings']} | "
          f"blocking issues: {report['collection_gate']['blocking_issue_count']}")
    print(f"wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
