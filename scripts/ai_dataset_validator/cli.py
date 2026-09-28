"""Command line interface for the Offline Dataset Validator."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from validator import DatasetValidator


def render(report, json_report: bool) -> str:
    if json_report:
        return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    rows = [
        "Validation Result",
        f"Scenarios: {report.statistics.get('scenarios', 0)}",
        f"Samples: {report.statistics.get('samples', 0)}",
        f"Families: {report.statistics.get('families', 0)}",
        f"Errors: {len(report.errors)}",
        f"Warnings: {len(report.warnings)}",
    ]
    for heading, issues in (("ERROR", report.errors), ("WARNING", report.warnings), ("INFO", report.info)):
        if issues:
            rows.extend(["", heading])
            for issue in issues:
                rows.append(f"{issue.record_id or '-'} {issue.json_path}: {issue.message} [{issue.file}; {issue.code}]")
    rows.extend(["", "SUMMARY", "PASS" if report.valid else "FAIL"])
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only offline validator for Shared Ledger Dataset v0.1.")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="Validate a scenario, sample, manifest, Dataset, or bundled examples.")
    validate.add_argument("kind", choices=("scenario", "sample", "manifest", "dataset", "examples"))
    validate.add_argument("path", nargs="?", help="JSON file or Dataset directory; examples defaults to repository examples.")
    validate.add_argument("--json-report", action="store_true", help="Print a machine-readable JSON report.")
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]
    validator = DatasetValidator(repo_root)
    try:
        if args.kind in {"dataset", "examples"}:
            path = Path(args.path).resolve() if args.path else repo_root / "docs/ai/dataset/examples"
            report = validator.load_dataset(path)
        else:
            if not args.path:
                parser.error(f"{args.kind} requires a JSON file path")
            report = validator.validate_file(args.kind, args.path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Validation input error: {exc}", file=sys.stderr)
        return 2
    print(render(report, args.json_report))
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
