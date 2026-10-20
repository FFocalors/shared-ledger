"""Generate candidate rows with the frozen v2 generator, in an isolated process.

The v2 generator and the v1.1 conversion each pin a different frozen baseline
and each refuses to run once the other's package is loaded.  Rather than weaken
either pin, the generation stage runs in its own process and hands back JSON.

Usage (from the repository root):

    agent/.venv/Scripts/python.exe -m agent.evaluation.t1_release_v3.generate_v2_rows --spec SPEC --out OUT
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def build(spec: dict) -> dict:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from agent.evaluation.t1_release import builder as v2_builder

    from . import rbr03

    namespace = str(v2_builder.NAMESPACE)
    rows: dict[str, dict] = {}
    contexts: dict[str, dict] = {}
    for index, request in enumerate(spec["rows"]):
        key = request.get("key") or f"row-{index:03d}"
        if request.get("kind") == "boundary":
            from agent.evaluation.t1_release import boundary as v2_boundary

            for record in v2_boundary.build_boundary_records():
                rows[f"{record['sample_id']}"] = record
            continue

        if request.get("kind") == "multiturn_create":
            rows[key] = v2_builder._multiturn_create_record(int(request["family_index"]))
            continue

        op = request["operation"]
        g = int(request["family_index"])
        policy = request.get("clarification_policy", "expense_ref")
        # A natural-clarification row cannot satisfy the v2 gold parser, which
        # requires an `expense_ref=` follow-up; the row carries its own gold
        # check instead.
        gold_validator = (
            rbr03.validate_natural_clarification if policy == "returned_facts" else None
        )
        record = v2_builder._make_record(
            op, g,
            read_variant=request.get("read_variant", "full"),
            amount_override=request.get("amount_override"),
            variant_tag=request.get("variant_tag", ""),
            clarification_policy=policy,
            gold_validator=gold_validator,
            state_overrides=request.get("state_overrides"),
            participant_count_override=request.get("participant_count_override"),
        )
        rows[key] = record

        if request.get("with_bindings"):
            if op not in {"read.activities", "read.expenses", "read.debts"}:
                raise SystemExit("private bindings are only produced for read rows")
            activity_count = 1 + (g % 15) if op == "read.activities" else 1
            base_people = 3 + ((g % 15) % 5) if op == "read.debts" else 2
            expense_count = (
                1 + (g % 15) if op == "read.expenses"
                else v2_builder._debt_edge_count(g) if op == "read.debts" else 0
            )
            ids = v2_builder._binding_map(
                op, g, activity_count=activity_count,
                participant_count=base_people, expense_count=expense_count,
            )
            contexts[key] = {
                "bound": [item.model_dump(mode="json") for item in ids["bound"]],
                "turn": str(ids["turn"]),
                "activity_ids": [str(item) for item in ids["activity_ids"]],
            }
    return {
        "rows": rows,
        "contexts": contexts,
        "namespace": namespace,
        "generator_version": "t1-synth-2.0.0",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="generate rows with the frozen v2 generator")
    parser.add_argument("--spec", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    payload = build(spec)
    Path(args.out).write_bytes(
        (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
