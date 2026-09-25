"""Command line entry point for scenario runs and saved-run judgments."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .focus_contract import ALL_FOCUSES
from .runner import run_scenario


VERDICTS = ("PASS", "FAIL", "UNCERTAIN", "JUDGE_ERROR")
FOCUS_CHOICES = tuple(ALL_FOCUSES)


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


def _generate_case(focus: str, seed: int | None = None) -> int:
    from .generate_case import generate_case

    result = generate_case(focus, seed=seed)
    print(f"{focus}: {result['status']} | Loader={result['loader_result'] or '-'} "
          f"| Focus={result['focus_result'] or '-'} | repair_count={result['repair_count']}"
          + (f" | seed={result['plan_seed']}" if result.get("plan_seed") is not None else ""))
    print(f"Artifacts: {result['output_dir']}")
    if result["error_category"]:
        print(f"Error: {result['error_category']}")
    if result["focus_error"]:
        print(f"Focus: {result['focus_error']}")
    if result["loader_error"]:
        print(f"Loader: {result['loader_error']}")
    return 0 if result["status"] == "VALID" else 1


def _run_generated_case(focus: str, seed: int | None = None) -> int:
    from .run_generated_case import run_generated_case

    result = run_generated_case(focus, seed=seed)
    print(f"{focus}: {result['status']} | run_id={result.get('run_id') or '-'} "
          f"| Loader={result.get('loader_result') or '-'} "
          f"| Focus={result.get('focus_result') or '-'} "
          f"| Runner={result.get('runner_result') or '-'} "
          f"| Judge={result.get('judge_verdict') or '-'}")
    print(f"Artifacts: {result['output_dir']}")
    if result.get("focus_error"):
        print(f"Focus: {result['focus_error']}")
    if result.get("error_category"):
        print(f"Error: {result['error_category']}")
    return 0 if result["status"] == "COMPLETE" else 1


def _fx_fixture() -> int:
    from .fx_fixture import ensure_fx_fixture

    try:
        status = ensure_fx_fixture()
    except Exception as exc:
        print(f"FX fixture failed: {exc}", file=sys.stderr)
        return 1
    print(f"local FX fixture: {status['present_pairs']}/{status['expected_pairs']} pairs "
          f"({status['note']})")
    for rate in status["rates"]:
        print(f"  {rate}")
    return 0 if status["ready"] else 1


def _coverage_run(
    focuses: list[str],
    per_focus: int,
    seed_base: int,
    *,
    sequential: bool = False,
) -> int:
    """Run a coverage batch: one ScenarioPlan-driven case per (focus, seed).

    Plans are all generated up front, then executed by the parallel pipeline
    unless ``--sequential`` is given.
    """
    import json
    from datetime import datetime, timezone

    from .coverage import compute_coverage, load_case_records
    from .focus_contract import ALL_FOCUSES, COVERAGE_FOCUSES
    from .fx_fixture import ensure_fx_fixture, requires_fx_fixture
    from .pipeline import PipelineConfig, build_batch_plans, run_pipeline, summarise_pipeline
    from .run_generated_case import run_generated_case
    from .supabase import verification_root

    selected = focuses or list(COVERAGE_FOCUSES)
    unknown = [focus for focus in selected if focus not in ALL_FOCUSES]
    if unknown:
        print(f"unsupported focus: {', '.join(unknown)}", file=sys.stderr)
        return 2

    plans = build_batch_plans(selected, per_focus=per_focus, seed_base=seed_base)
    print(f"planned {len(plans)} cases across {len(selected)} focuses "
          f"(seeds {seed_base}..{seed_base + len(plans) - 1})")

    if any(requires_fx_fixture(plan.focus) for plan in plans):
        try:
            status = ensure_fx_fixture()
        except Exception as exc:
            print(f"could not prepare the local FX fixture: {exc}", file=sys.stderr)
            return 2
        print(f"local FX fixture ready: {status['present_pairs']}/{status['expected_pairs']} pairs "
              f"({status['note']})")

    case_ids: list[str] = []
    pipeline_summary = None

    if sequential:
        for plan in plans:
            result = run_generated_case(plan.focus, plan=plan)
            case_ids.append(Path(result["output_dir"]).name)
            print(
                f"{plan.focus:24s} seed={plan.seed:<4d} {result['status']:<15s} "
                f"focus={result.get('focus_result') or '-':<14s} "
                f"runner={result.get('runner_result') or '-':<9s} "
                f"judge={result.get('judge_verdict') or '-'}"
            )
            sys.stdout.flush()
    else:
        def report_progress(event: dict) -> None:
            if event.get("stage") == "coverage":
                return
            print(f"  [{event.get('case_id', '?')[:24]}] {event.get('stage')}: "
                  f"{event.get('status')}", flush=True)

        def report_done(result: dict) -> None:
            case_ids.append(Path(result["output_dir"]).name)
            print(
                f"{result.get('focus'):24s} seed={result.get('plan_seed')!s:<4s} "
                f"{result.get('status'):<15s} "
                f"focus={result.get('focus_result') or '-':<14s} "
                f"runner={result.get('runner_result') or '-':<9s} "
                f"judge={result.get('judge_verdict') or '-'}",
                flush=True,
            )

        payload = run_pipeline(
            plans,
            config=PipelineConfig.from_env(),
            on_progress=report_progress,
            on_case_done=report_done,
        )
        pipeline_summary = summarise_pipeline(payload)
        if payload.get("generator_clamped"):
            print("note: LOCAL_GENERATOR_WORKERS was clamped to 1 (single local prediction)")

    records = load_case_records(
        verification_root() / "local_llm_probe" / "generated_cases", case_ids=case_ids
    )
    summary = compute_coverage(records)
    report_dir = verification_root() / "local_llm_probe" / "coverage_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = report_dir / f"coverage_{stamp}.json"
    report_path.write_text(
        json.dumps(
            {"case_ids": case_ids, "summary": summary, "pipeline": pipeline_summary},
            ensure_ascii=False, indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    verdicts = summary["judge_verdicts"]
    print()
    print(f"generated={summary['generated_count']} "
          f"focus_valid={summary['focus_valid_count']} "
          f"focus_mismatch={summary['focus_mismatch_count']} "
          f"duplicate={summary['duplicate_count']} "
          f"unique_valid={summary['unique_valid_count']} "
          f"distinct_scenarios={summary['distinct_scenarios']}")
    print(f"loader_valid={summary['loader_valid_count']} "
          f"runner_executed={summary['runner_executed_count']} "
          f"repairs={summary['compiler_repair_count']}")
    print("judge: " + ", ".join(f"{key}={value}" for key, value in verdicts.items())
          + f" | pass_rate={summary['pass_rate']}")
    if pipeline_summary is not None:
        elapsed = pipeline_summary["elapsed_seconds"]
        print(f"pipeline: {pipeline_summary['cases']} cases in {elapsed:.0f}s "
              f"({pipeline_summary['cases_per_hour']} cases/hour) "
              f"| queue_max={pipeline_summary['queue_max']} "
              f"| deepseek_timeouts={pipeline_summary['deepseek_timeouts']}")
        if pipeline_summary["worker_failures"]:
            for failure in pipeline_summary["worker_failures"]:
                print(f"  worker failure: {failure}")
        print(f"workers: {pipeline_summary['config']}")
    flagged = [
        case for case in summary["cases"]
        if case["judge_verdict"] in ("FAIL", "UNCERTAIN", "JUDGE_ERROR")
        or case["focus_status"] == "FOCUS_MISMATCH"
    ]
    if flagged:
        print("needs review:")
        for case in flagged:
            print(f"  {case['case_id']} [{case['focus']}] judge={case['judge_verdict']} "
                  f"focus={case['focus_status']} {case['focus_error'] or ''}")
    print(f"report: {report_path}")
    return 0 if summary["focus_mismatch_count"] == 0 else 1


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
    generate_parser.add_argument("--focus", choices=sorted(FOCUS_CHOICES), required=True)
    generate_parser.add_argument(
        "--seed", type=int, default=None,
        help="ScenarioPlan seed; omit to generate without a plan",
    )
    generated_run_parser = commands.add_parser(
        "run-generated-case", help="generate, compile, run locally, and judge one case"
    )
    generated_run_parser.add_argument("--focus", choices=sorted(FOCUS_CHOICES), required=True)
    generated_run_parser.add_argument(
        "--seed", type=int, default=None,
        help="ScenarioPlan seed; omit to generate without a plan",
    )
    coverage_parser = commands.add_parser(
        "coverage-run",
        help="run a ScenarioPlan-driven coverage batch and report unique valid coverage",
    )
    coverage_parser.add_argument(
        "--focus", action="append", default=[], choices=sorted(FOCUS_CHOICES),
        help="focus to include; repeatable. Defaults to every formal coverage focus.",
    )
    coverage_parser.add_argument(
        "--per-focus", type=int, default=3, help="cases per focus (default 3)",
    )
    coverage_parser.add_argument(
        "--seed-base", type=int, default=1, help="first ScenarioPlan seed (default 1)",
    )
    coverage_parser.add_argument(
        "--sequential", action="store_true",
        help="run cases one at a time instead of the parallel pipeline",
    )
    commands.add_parser(
        "fx-fixture",
        help="write the deterministic local FX rates the multi_currency focus needs",
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
        return _generate_case(args.focus, args.seed)

    if args.command == "run-generated-case":
        return _run_generated_case(args.focus, args.seed)

    if args.command == "coverage-run":
        return _coverage_run(
            args.focus, args.per_focus, args.seed_base, sequential=args.sequential
        )

    if args.command == "fx-fixture":
        return _fx_fixture()

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
