"""Command line entry point for local scenario runs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .runner import run_scenario


def _progress(event: dict[str, object]) -> None:
    kind = event.get("kind")
    scenario_id = event.get("scenario_id", "scenario")
    if kind == "operation":
        print(
            f"[{scenario_id}] step {event.get('step')}/{event.get('count')} "
            f"{event.get('operation')}: {event.get('status')}"
        )
    elif kind == "scenario" and event.get("status") != "loaded":
        print(
            f"[{scenario_id}] {event.get('status')} - result: {event.get('run_dir')}"
        )
        if event.get("error_code"):
            print(f"  {event.get('error_code')}: {event.get('error_message')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="shared-ledger-verifier")
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="run one scenario JSON file")
    run_parser.add_argument("scenario", type=Path)
    all_parser = commands.add_parser("run-all", help="run every scenario JSON file in a directory")
    all_parser.add_argument("directory", type=Path)
    args = parser.parse_args(argv)

    if args.command == "run":
        result = run_scenario(args.scenario, progress=_progress)
        return 0 if result["status"] == "EXECUTED" else 1

    if not args.directory.is_dir():
        print(f"scenario directory not found: {args.directory}", file=sys.stderr)
        return 2
    scenarios = sorted(args.directory.glob("*.json"))
    if not scenarios:
        print(f"no scenario JSON files in: {args.directory}", file=sys.stderr)
        return 2
    results = [run_scenario(path, progress=_progress) for path in scenarios]
    succeeded = sum(result["status"] == "EXECUTED" for result in results)
    print(f"run-all: {succeeded}/{len(results)} scenarios executed")
    return 0 if succeeded == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
