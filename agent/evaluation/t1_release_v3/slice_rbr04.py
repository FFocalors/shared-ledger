"""RBR04 slice: AA minor-unit tail and multi-person small-amount coverage.

Run from the repository root:

    agent/.venv/Scripts/python.exe -m agent.evaluation.t1_release_v3.slice_rbr04

Each case reuses an existing in-split state family, so no family-count floor
changes; only the user-authored amount does.  Every case is checked for exact
amount conservation and for a real, deterministic allocation tail.

Train and validation bodies are written; sealed is generated and validated in
memory only, because sealed must be written last under its own one-shot receipt
in the full preparation.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from . import rbr04

REPORT_NAME = "rbr04-slice-report.json"


def main(argv: list[str] | None = None) -> int:
    from . import bridge, convert, hashing, profile, runtime
    from . import snapshot as snapshot_module

    manifest = snapshot_module.verify_snapshot()

    # --- stage 1: the frozen v2 generator, in its own process --------------
    generated = bridge.generate_rows([
        {
            "key": f"{split_name}:{g}:{tag}",
            "operation": "expense.create",
            "family_index": g,
            "amount_override": amount,
            "variant_tag": tag,
        }
        for split_name, g, _participants, tag, amount in rbr04.RBR04_CASES
    ])

    # --- stage 2: the pinned v1.1 profile ---------------------------------
    c, v11_package, data_signature, _simulator = runtime.baseline_modules()
    validator = runtime.make_v3_validator()

    rows: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    for split_name, g, participants, tag, amount in rbr04.RBR04_CASES:
        record = generated["rows"][f"{split_name}:{g}:{tag}"]
        if record["split"] != split_name:
            raise SystemExit(
                f"family {g} belongs to split {record['split']}, not {split_name}"
            )
        row = convert.convert_write_row(v11=v11_package, record=record)
        row["scenario_signature_sha256"] = hashing.sha256(row["scenario"])
        row["normalized_scenario_signature_sha256"] = hashing.sha256(
            data_signature.scenario_projection(row["fixture_state"], row)
        )
        row["baseline_snapshot_manifest_sha256"] = manifest["snapshot_manifest_sha256"]

        errors = sorted(validator.iter_errors(row), key=lambda e: list(e.path))
        if errors:
            for error in errors[:5]:
                print("  SCHEMA:", "/".join(str(p) for p in error.path), error.message)
            raise SystemExit(f"converted row fails the release-v3 envelope: {row['sample_id']}")

        audit = rbr04.audit_case(row, expected_participants=participants, expected_amount=amount)
        audit["tag"] = tag
        audit["source_family_index"] = g
        # Every model-visible input must be free of the training-only hint.
        audit["hint_removed"] = all(
            hint not in step["context"]["input_text"]
            for step in row["trace"] if step["kind"] == "model"
            for hint in convert.TRAINING_ONLY_HINTS
        )
        audits.append(audit)
        rows.append(row)
        print(f"  {audit['sample_id']}: {amount} {audit['currency']} over "
              f"{participants} -> first {audit['tail']['first_share']} / "
              f"last {audit['tail']['last_share']} (conserved)")

    target = profile.RUN_ROOT / "conversion"
    target.mkdir(parents=True, exist_ok=True)
    written = [row for row in rows if row["split"] in rbr04.WRITTEN_SPLITS]
    payload = "\n".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) for row in written
    ) + "\n"
    rows_path = target / "rbr04-converted-rows.jsonl"
    rows_path.write_bytes(payload.encode("utf-8"))

    sealed = [up for up in audits if up["split"] == "sealed"]
    report = {
        "format": "t1-release-v3-rbr04-slice-v1",
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
        "rows_file_sha256": hashlib.sha256(rows_path.read_bytes()).hexdigest(),
        "row_count": len(written),
        "written_splits": list(rbr04.WRITTEN_SPLITS),
        "sealed_generated_not_written": {
            "row_count": len(sealed),
            "sample_ids": [item["sample_id"] for item in sealed],
        },
        "cases": audits,
        "scope_note": (
            "Coverage only: no existing row was changed and no allocation rule was altered. "
            "The AA tail is produced by the allocator that is already in force, at its own "
            "0.0001 quantum. Whether the candidate should instead allocate at the backend's "
            "documented 0.1 minimum unit is a separate semantics decision and is not made here."
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
