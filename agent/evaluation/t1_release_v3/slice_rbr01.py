"""RBR01 vertical slice: convert the three no-match read rows to v1.1.

Run from the repository root:

    agent/.venv/Scripts/python.exe -m agent.evaluation.t1_release_v3.slice_rbr01

The three rows are the read.activities / read.expenses / read.debts no-match
rows that the root business review flagged (packet rows 21, 22 and 24).  Each
is regenerated with the frozen v2 generator, converted, and validated against
the release-v3 envelope and the frozen v1.1 harness.  Nothing in the frozen v2
candidate or its receipts is read back or modified.
"""
from __future__ import annotations

import hashlib
import json
import sys
import uuid
from pathlib import Path
from typing import Any

# The three no-match read rows: (operation, family index, packet row).
NO_MATCH_ROWS = (
    ("read.activities", 14, 21),
    ("read.expenses", 4, 22),
    ("read.debts", 0, 24),
)

REPORT_NAME = "rbr01-slice-report.json"
V2_CANDIDATE_TRAIN = Path(
    r"D:\AI\runs\shared-ledger\t1-release-v2-20261011\candidate-v2\train.jsonl"
)


def _frozen_v2_row(op: str, g: int) -> dict[str, Any]:
    """The byte-frozen v2 train row for one no-match read, for comparison only."""
    sample_id = f"t1-v2-train-{op.replace('.', '-')}-{g:03d}-read-empty"
    for line in V2_CANDIDATE_TRAIN.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["sample_id"] == sample_id:
            return row
    raise SystemExit(f"frozen v2 row is missing: {sample_id}")


def _strip_volatile(row: dict[str, Any]) -> dict[str, Any]:
    """Fields that legitimately differ because they name the new version."""
    copy = json.loads(json.dumps(row))
    for key in ("release_version", "generator_version", "protocol_profile", "versions",
                "scenario", "scenario_signature_sha256", "coverage_tags",
                "normalized_scenario_signature_sha256"):
        copy.pop(key, None)
    for step in copy.get("trace", []):
        step.pop("query", None)
    return copy


def main(argv: list[str] | None = None) -> int:
    from pydantic import TypeAdapter

    from . import bridge, convert, hashing, profile, runtime, v11_evidence
    from . import snapshot as snapshot_module

    manifest = snapshot_module.verify_snapshot()

    # --- stage 1: the frozen v2 generator, in its own process --------------
    # The v2 tooling pins the v1 baseline from the v2 snapshot and refuses to
    # run once the v1.1 package is loaded, so generation is isolated.
    generated = bridge.generate_rows([
        {
            "key": f"{op}:{g}",
            "operation": op,
            "family_index": g,
            "read_variant": "empty",
            "with_bindings": True,
        }
        for op, g, _packet_row in NO_MATCH_ROWS
    ])

    # --- stage 2: the pinned v1.1 profile ---------------------------------
    c, v11_package, data_signature, _simulator = runtime.baseline_modules()
    v11 = v11_evidence.api(v11_package)
    validator = runtime.make_v3_validator()
    namespace = uuid.UUID(generated["namespace"])
    bound_adapter = TypeAdapter(v11.V1.BoundReference)

    converted_rows = []
    report_rows = []
    for op, g, packet_row in NO_MATCH_ROWS:
        key = f"{op}:{g}"
        fresh = generated["rows"][key]
        private = generated["contexts"][key]
        frozen = _frozen_v2_row(op, g)
        if _strip_volatile(fresh) != _strip_volatile(frozen):
            raise SystemExit(
                f"the v2 generator no longer reproduces the frozen row for {op} g={g}; "
                "the conversion baseline is not stable"
            )

        sample_key = f"t1-release-v3-train-{op.replace('.', '-')}-{g:03d}"
        row = convert.convert_no_match_read_row(
            c=c,
            v11=v11,
            namespace=namespace,
            sample_key=sample_key,
            record=fresh,
            bound_references=[bound_adapter.validate_python(item) for item in private["bound"]],
            scope_activity_id=uuid.UUID(private["activity_ids"][0]),
            title_filter=convert.converted_title_filter(fresh),
            turn_id=uuid.UUID(private["turn"]),
        )
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

        answer = row["trace"][2]["target"]
        output = {
            "sample_id": row["sample_id"],
            "packet_row": packet_row,
            "operation": op,
            "zero_class": row["scenario"]["query_evidence"]["zero_class"],
            "returned_count": row["scenario"]["query_evidence"]["returned_count"],
            "citations": answer["citations"],
            "answer_text": answer["text"],
            "hint_removed": all(
                hint not in row["trace"][2]["context"]["input_text"]
                for hint in convert.TRAINING_ONLY_HINTS
            ),
            "row_sha256": hashing.sha256(row),
        }
        converted_rows.append(row)
        report_rows.append(output)
        print(f"  {output['sample_id']}: {output['zero_class']} "
              f"returned={output['returned_count']} citations={output['citations']}")

    target = profile.RUN_ROOT / "conversion"
    target.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) for row in converted_rows
    ) + "\n"
    rows_path = target / "rbr01-converted-rows.jsonl"
    # Written as bytes so the artifact hash does not depend on the platform's
    # newline translation.
    rows_path.write_bytes(payload.encode("utf-8"))

    report = {
        "format": "t1-release-v3-rbr01-slice-v1",
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
        "row_count": len(converted_rows),
        "v2_regeneration_reproduced_frozen_rows": True,
        "rows": report_rows,
        "rbr01_binding_fields": v11_evidence.RBR01_BINDING_FIELDS,
        "scope_note": (
            "This slice converts only the three no-match read rows. The remaining read rows, "
            "the write rows, RBR03 and RBR04 are not yet converted, and no candidate, freeze, "
            "packet or human receipt is produced by this step."
        ),
    }
    report_path = target / REPORT_NAME
    report_path.write_bytes(
        (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    print(f"wrote {report_path}")
    print(f"wrote {rows_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
