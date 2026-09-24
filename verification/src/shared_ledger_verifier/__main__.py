"""Command line entry point for scenario runs and saved-run judgments."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .runner import run_scenario


VERDICTS = ("PASS", "FAIL", "UNCERTAIN", "JUDGE_ERROR")


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


def _smoke_scenario_ids() -> set[str]:
    smoke_dir = Path(__file__).resolve().parents[2] / "scenarios" / "smoke"
    scenario_ids: set[str] = set()
    for path in smoke_dir.glob("*.json"):
        try:
            scenario = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        scenario_id = scenario.get("scenario_id") if isinstance(scenario, dict) else None
        if isinstance(scenario_id, str) and scenario_id:
            scenario_ids.add(scenario_id)
    return scenario_ids


def _recent_smoke_runs(runs_dir: Path) -> tuple[list[tuple[str, Path]], list[str]]:
    """Return the newest EXECUTED run for each configured Smoke scenario."""

    scenario_ids = _smoke_scenario_ids()
    candidates: list[tuple[int, str, Path]] = []
    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir():
            continue
        result_path = run_dir / "result.json"
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
            scenario = json.loads((run_dir / "scenario.json").read_text(encoding="utf-8"))
            completed_at = result_path.stat().st_mtime_ns
        except (OSError, json.JSONDecodeError):
            continue
        scenario_id = scenario.get("scenario_id") if isinstance(scenario, dict) else None
        if (
            isinstance(result, dict)
            and result.get("status") == "EXECUTED"
            and isinstance(scenario_id, str)
            and scenario_id in scenario_ids
        ):
            candidates.append((completed_at, scenario_id, run_dir))

    newest: dict[str, Path] = {}
    for _, scenario_id, run_dir in sorted(
        candidates,
        key=lambda item: (item[0], item[1], item[2].name),
        reverse=True,
    ):
        if scenario_id not in newest:
            newest[scenario_id] = run_dir

    selected = [(scenario_id, newest[scenario_id]) for scenario_id in sorted(newest)]
    missing = sorted(scenario_ids - newest.keys())
    return selected, missing


def _call_judge(run_dir: Path) -> dict[str, Any]:
    # Keep the runner usable independently while the Judge remains a separate step.
    from .judge import judge_run

    return judge_run(run_dir)


def _print_judge_error(result: dict[str, Any]) -> None:
    # Only fixed diagnostic fields; never provider exception text or bodies.
    details = [str(result[key]) for key in ("error_code", "error_kind", "http_status") if result.get(key) is not None]
    if details:
        print("  error: " + " / ".join(details), file=sys.stderr)


def _judge_one(run_dir: Path) -> int:
    if not run_dir.is_dir():
        print(f"run directory not found: {run_dir}", file=sys.stderr)
        return 2
    try:
        result = _call_judge(run_dir)
    except OSError as exc:
        print(f"could not judge run {run_dir}: {exc}", file=sys.stderr)
        return 1

    verdict = result.get("verdict", "JUDGE_ERROR")
    if verdict not in VERDICTS:
        verdict = "JUDGE_ERROR"
    print(f"{run_dir.name} {verdict}")
    if result.get("summary"):
        print(result["summary"])
    if verdict == "JUDGE_ERROR":
        _print_judge_error(result)
        return 1
    return 0


def _judge_all(runs_dir: Path) -> int:
    if not runs_dir.is_dir():
        print(f"runs directory not found: {runs_dir}", file=sys.stderr)
        return 2
    try:
        selected, missing = _recent_smoke_runs(runs_dir)
    except OSError as exc:
        print(f"could not read runs directory {runs_dir}: {exc}", file=sys.stderr)
        return 2
    expected_count = len(_smoke_scenario_ids())
    if not selected or missing:
        missing_text = ", ".join(missing) if missing else "no configured Smoke scenarios found"
        print(
            f"need {expected_count} distinct EXECUTED Smoke runs; "
            f"found {len(selected)}. Missing: {missing_text}",
            file=sys.stderr,
        )
        return 2

    counts = {verdict: 0 for verdict in VERDICTS}
    for scenario_id, run_dir in selected:
        try:
            result = _call_judge(run_dir)
        except OSError as exc:
            result = {"verdict": "JUDGE_ERROR", "error": str(exc)}
        verdict = result.get("verdict", "JUDGE_ERROR")
        if verdict not in counts:
            verdict = "JUDGE_ERROR"
        counts[verdict] += 1
        print(f"{scenario_id:<32} {verdict}")
        if verdict == "JUDGE_ERROR":
            _print_judge_error(result)

    print(", ".join(f"{verdict}: {counts[verdict]}" for verdict in VERDICTS))
    return 1 if counts["JUDGE_ERROR"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="shared-ledger-verifier")
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="run one scenario JSON file")
    run_parser.add_argument("scenario", type=Path)
    all_parser = commands.add_parser("run-all", help="run every scenario JSON file in a directory")
    all_parser.add_argument("directory", type=Path)
    judge_parser = commands.add_parser("judge", help="judge one completed run directory")
    judge_parser.add_argument("run_dir", type=Path)
    judge_all_parser = commands.add_parser(
        "judge-all", help="judge the newest EXECUTED run for each Smoke scenario"
    )
    judge_all_parser.add_argument("runs_dir", type=Path)
    args = parser.parse_args(argv)

    if args.command == "run":
        result = run_scenario(args.scenario, progress=_progress)
        return 0 if result["status"] == "EXECUTED" else 1

    if args.command == "run-all":
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

    if args.command == "judge":
        return _judge_one(args.run_dir)
    return _judge_all(args.runs_dir)


if __name__ == "__main__":
    raise SystemExit(main())
