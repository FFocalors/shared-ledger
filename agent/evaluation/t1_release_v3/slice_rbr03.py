"""RBR03 slice: ambiguous clarifications name candidates by returned facts.

Run from the repository root:

    agent/.venv/Scripts/python.exe -m agent.evaluation.t1_release_v3.slice_rbr03

The root review flagged packet rows 19/20/26: the clarification asked the user to
choose an internal ``expense_ref``.  The converted rows list each candidate by
title, date, amount, currency and participants, and the follow-up selects on
those facts.  No expense data, amount or target changes.
"""
from __future__ import annotations

import json
import sys
from typing import Any

from . import rbr03

REPORT_NAME = "rbr03-slice-report.json"

# Family indices for ambiguous presentation updates, three per split.  Each has
# several same-title candidates with distinct dates and amounts.
RBR03_CASES: tuple[int, ...] = (
    16, 17, 9,          # train: packet rows 19, 20, 26
    36, 37, 29,         # validation
    56, 57, 49,         # sealed
)
WRITTEN_SPLITS = ("train", "validation")


def main(argv: list[str] | None = None) -> int:
    from . import bridge, convert, hashing, profile, runtime
    from . import snapshot as snapshot_module

    manifest = snapshot_module.verify_snapshot()

    generated = bridge.generate_rows([
        {
            "key": f"g{g}",
            "operation": "expense.presentation.update",
            "family_index": g,
            "clarification_policy": "returned_facts",
        }
        for g in RBR03_CASES
    ])

    _c, v11_package, data_signature, _simulator = runtime.baseline_modules()
    validator = runtime.make_v3_validator()

    rows: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    for g in RBR03_CASES:
        record = generated["rows"][f"g{g}"]
        # The row's own gold check runs before and after conversion.
        audit = rbr03.audit_row(record)
        row = convert.convert_write_row(v11=v11_package, record=record)
        row["scenario_signature_sha256"] = hashing.sha256(row["scenario"])
        row["normalized_scenario_signature_sha256"] = hashing.sha256(
            data_signature.scenario_projection(row["fixture_state"], row)
        )
        row["baseline_snapshot_manifest_sha256"] = manifest["snapshot_manifest_sha256"]
        rbr03.audit_row(row)

        errors = sorted(validator.iter_errors(row), key=lambda e: list(e.path))
        if errors:
            for error in errors[:5]:
                print("  SCHEMA:", "/".join(str(p) for p in error.path), error.message)
            raise SystemExit(f"converted row fails the release-v3 envelope: {row['sample_id']}")

        audit["source_family_index"] = g
        audits.append(audit)
        rows.append(row)
        print(f"  {audit['sample_id']}: {audit['candidate_count']} candidates, "
              f"selected {audit['selected_expense_ref']}")

    target = profile.RUN_ROOT / "conversion"
    target.mkdir(parents=True, exist_ok=True)
    written = [row for row in rows if row["split"] in WRITTEN_SPLITS]
    payload = "\n".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) for row in written
    ) + "\n"
    rows_path = target / "rbr03-converted-rows.jsonl"
    rows_path.write_bytes(payload.encode("utf-8"))

    sealed = [item for item in audits if item["split"] == "sealed"]
    report = {
        "format": "t1-release-v3-rbr03-slice-v1",
        "release_version": profile.RELEASE_VERSION,
        "profile": profile.V11_PROFILE,
        "versions": {
            "api": profile.V11_API_VERSION, "semantic": profile.V11_SEMANTIC_VERSION,
            "operations": profile.V11_OPERATIONS_VERSION,
            "trajectory": profile.V11_TRAJECTORY_VERSION,
            "execution_key": profile.V11_EXECUTION_KEY_VERSION,
        },
        "snapshot_manifest_sha256": manifest["snapshot_manifest_sha256"],
        "rows_file": rows_path.name,
        "rows_file_sha256": hashing.sha256(rows_path.read_bytes()),
        "row_count": len(written),
        "written_splits": list(WRITTEN_SPLITS),
        "sealed_generated_not_written": {
            "row_count": len(sealed),
            "sample_ids": [item["sample_id"] for item in sealed],
        },
        "cases": audits,
        "scope_note": (
            "Only the clarification wording and the user follow-up change. The proposal, its "
            "expense_ref, the amounts and the operation state are byte-equal to the v2 row. "
            "P2 baseline calibration of the candidate presentation remains a separate gate."
        ),
    }
    report_path = target / REPORT_NAME
    report_path.write_bytes(
        (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    print(f"wrote {report_path}")
    print(f"wrote {rows_path} ({len(written)} rows; sealed generated, not written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
