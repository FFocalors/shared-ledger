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


def _local_llm_probe() -> int:
    from .local_llm import LocalLLMError
    from .local_llm_v2 import run_probe_v2

    try:
        result = run_probe_v2()
    except LocalLLMError as error:
        print(f"LOCAL LLM PROBE V2: NOT READY ({error.category})")
        return 1
    print(f"Model: {result['model'] or '-'}")
    if result["error_category"]:
        print(f"Setup error: {result['error_category']}")
    for focus, entry in result["focus_results"].items():
        elapsed = "-" if entry["elapsed_seconds"] is None else f"{entry['elapsed_seconds']:.3f}s"
        print(f"{focus}: {entry['status']} | input={entry['input_characters']} chars | "
              f"prompt={entry['prompt_tokens']} completion={entry['completion_tokens']} | "
              f"elapsed={elapsed} | Loader={entry['loader_status']}")
        if entry["error_category"]:
            print(f"  {entry['error_category']}: {entry.get('loader_error') or entry.get('error_summary') or ''}")
    print(f"LOCAL LLM PROBE V2: {'READY' if result['ready'] else 'NOT READY'}")
    return 0 if result["ready"] else 1


def _generate_case(focus: str) -> int:
    from .generate_case import generate_case

    result = generate_case(focus)
    print(f"{focus}: {result['status']} | Loader={result['loader_result'] or '-'} "
          f"| repair_count={result['repair_count']}")
    print(f"Artifacts: {result['output_dir']}")
    if result["error_category"]:
        print(f"Error: {result['error_category']}")
    if result["loader_error"]:
        print(f"Loader: {result['loader_error']}")
    return 0 if result["status"] == "VALID" else 1


def _run_generated_case(focus: str) -> int:
    from .run_generated_case import run_generated_case

    result = run_generated_case(focus)
    print(f"{focus}: {result['status']} | run_id={result.get('run_id') or '-'} "
          f"| Loader={result.get('loader_result') or '-'} "
          f"| Runner={result.get('runner_result') or '-'} "
          f"| Judge={result.get('judge_verdict') or '-'}")
    print(f"Artifacts: {result['output_dir']}")
    if result.get("error_category"):
        print(f"Error: {result['error_category']}")
    return 0 if result["status"] == "COMPLETE" else 1


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
    commands.add_parser("local-llm-probe", help="probe LM Studio with three focused Scenario v1 generations")
    generate_parser = commands.add_parser(
        "generate-case", help="generate one raw case, compile it, and validate Scenario v1"
    )
    generate_parser.add_argument("--focus", choices=("expense_aa", "targeted_repayment", "prepayment_refund"),
                                 required=True)
    generated_run_parser = commands.add_parser(
        "run-generated-case", help="generate, compile, run locally, and judge one case"
    )
    generated_run_parser.add_argument(
        "--focus", choices=("expense_aa", "targeted_repayment", "prepayment_refund"), required=True
    )
    web_parser = commands.add_parser("web", help="launch local verification web dashboard")
    web_parser.add_argument("--host", default="127.0.0.1", help="host to bind (default: 127.0.0.1)")
    web_parser.add_argument("--port", type=int, default=8000, help="port to bind (default: 8000)")
    web_parser.add_argument("--no-browser", action="store_true", help="do not auto open browser")
    args = parser.parse_args(argv)

    if args.command == "web":
        from .web import start_server
        return start_server(host=args.host, port=args.port, open_browser=not args.no_browser)

    if args.command == "local-llm-probe":
        return _local_llm_probe()

    if args.command == "generate-case":
        return _generate_case(args.focus)

    if args.command == "run-generated-case":
        return _run_generated_case(args.focus)

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
