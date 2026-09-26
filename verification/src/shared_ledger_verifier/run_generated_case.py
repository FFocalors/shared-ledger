"""Run one generated Scenario through the isolated Runner and business Judge.

Like the generation stage, the work is split so the parallel pipeline can treat
execution and judging as separate stages: :func:`stage_execute` runs the
scenario against loopback Supabase, and :func:`stage_judge` asks the business
Judge for a verdict.  :func:`run_generated_case` remains the sequential wrapper.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from .generate_case import CaseRun, _has_secret, _safe_error, generate_case, result_template
from .judge import judge_run
from .runner import run_scenario
from .scenario_plan import ScenarioPlan


_VERDICTS = {"PASS", "FAIL", "UNCERTAIN"}
# A scenario that satisfies the Loader but not its focus contract is still worth
# executing -- it exercises real business logic -- but it is not coverage.
_EXECUTABLE = {"VALID", "FOCUS_MISMATCH"}


def _copy_artifact(source: Path, destination: Path) -> bool:
    if not source.is_file():
        return False
    try:
        shutil.copyfile(source, destination)
    except OSError:
        return False
    return True


def stage_execute(
    run: CaseRun,
    *,
    runner: Callable[..., dict[str, Any]] | None = None,
    on_progress: Callable[[str, str, dict[str, Any]], None] | None = None,
) -> CaseRun:
    """Execute the compiled scenario against loopback Supabase."""
    result = run.result
    if result.get("status") not in _EXECUTABLE or result.get("loader_result") != "VALID":
        # `loader_result` is asserted as well: a scenario the Loader rejected
        # must never reach the database, whatever status an earlier stage left.
        if result.get("status") in _EXECUTABLE:
            result["status"] = "COMPILER_INVALID"
            result["error_category"] = result.get("error_category") or "LOADER_INVALID"
            run.save()
        if on_progress:
            on_progress("runner", "skipped", {"reason": "generation_failed"})
        return run
    if result.get("status") == "FOCUS_MISMATCH" and on_progress:
        on_progress("coverage", "excluded", {"reason": "FOCUS_MISMATCH"})

    execute = runner or run_scenario
    started = perf_counter()
    if on_progress:
        on_progress("runner", "running", {})
    try:
        outcome = execute(run.output_dir / "scenario.json", runs_dir=run.output_dir / "runs")
    except Exception:
        result.update(status="RUNNER_FAILED", runner_result="FAILED",
                      error_category="RUNNER_EXCEPTION")
        result["runner_latency_seconds"] = round(perf_counter() - started, 3)
        if on_progress:
            on_progress("runner", "failed", {"error": "RUNNER_EXCEPTION"})
        run.save()
        return run
    result["runner_latency_seconds"] = round(perf_counter() - started, 3)
    result["runner_result"] = outcome.get("status")
    result["run_id"] = outcome.get("run_id")
    run_dir_value = outcome.get("run_dir")
    if run_dir_value:
        run_dir = Path(run_dir_value)
        result["run_dir"] = str(run_dir)
        artifacts_complete = all(
            _copy_artifact(run_dir / filename, run.output_dir / filename)
            for filename in ("operations.jsonl", "state_final.json")
        )
    else:
        run_dir = None
        artifacts_complete = False
    if outcome.get("status") != "EXECUTED":
        result.update(status="RUNNER_FAILED", error_category=_safe_error(
            str(outcome.get("error_code") or "RUNNER_FAILED")))
        if on_progress:
            on_progress("runner", "failed", {"error": outcome.get("error_code") or "RUNNER_FAILED"})
        run.save()
        return run
    if not artifacts_complete or run_dir is None:
        result.update(status="RUNNER_FAILED", error_category="RUNNER_ARTIFACT_MISSING")
        if on_progress:
            on_progress("runner", "failed", {"error": "RUNNER_ARTIFACT_MISSING"})
        run.save()
        return run
    result["status"] = "EXECUTED"
    if on_progress:
        on_progress("runner", "completed", {
            "latency": result["runner_latency_seconds"], "run_id": result["run_id"],
        })
    run.save()
    return run


def stage_judge(
    run: CaseRun,
    *,
    judge: Callable[..., dict[str, Any]] | None = None,
    judge_client: Any = None,
    on_progress: Callable[[str, str, dict[str, Any]], None] | None = None,
) -> CaseRun:
    """Ask the business Judge for a verdict on the executed run."""
    result = run.result
    run_dir_value = result.get("run_dir")
    if result.get("status") != "EXECUTED" or not run_dir_value:
        if on_progress:
            on_progress("judge", "skipped", {"reason": "runner_failed"})
        return run
    run_dir = Path(run_dir_value)
    adjudicate = judge or judge_run
    started = perf_counter()
    if on_progress:
        on_progress("judge", "running", {})
    try:
        judgment = adjudicate(run_dir, client=judge_client)
    except Exception:
        result.update(status="JUDGE_ERROR", error_category="JUDGE_EXCEPTION")
        result["judge_latency_seconds"] = round(perf_counter() - started, 3)
        if on_progress:
            on_progress("judge", "failed", {"error": "JUDGE_EXCEPTION"})
        run.save()
        return run
    result["judge_latency_seconds"] = round(perf_counter() - started, 3)
    if not isinstance(judgment, dict) or _has_secret(judgment):
        judgment = {"verdict": "JUDGE_ERROR", "error_code": "FORBIDDEN_CONTENT"}
    result["judge_model"] = judgment.get("model")
    result["judge_verdict"] = judgment.get("verdict")
    # Judge normally persists this itself; also support injected offline Judges.
    (run_dir / "judge.json").write_text(
        __import__("json").dumps(judgment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _copy_artifact(run_dir / "judge.json", run.output_dir / "judge.json")
    if judgment.get("verdict") not in _VERDICTS:
        result.update(status="JUDGE_ERROR", error_category=_safe_error(
            str(judgment.get("error_code") or "INVALID_VERDICT")))
        if on_progress:
            on_progress("judge", "failed", {
                "verdict": judgment.get("verdict"), "error": result["error_category"],
            })
    else:
        result["status"] = "COMPLETE"
        if result.get("focus_result") != "FOCUS_MISMATCH":
            result["error_category"] = None
        if on_progress:
            on_progress("judge", "completed", {
                "verdict": judgment.get("verdict"),
                "latency": result["judge_latency_seconds"],
                "focus_result": result.get("focus_result"),
            })
    run.save()
    return run


def run_generated_case(
    focus: str,
    *,
    local_client: Any = None,
    compiler_client: Any = None,
    judge_client: Any = None,
    output_dir: Path | None = None,
    business_logic_path: Path | None = None,
    runner: Callable[..., dict[str, Any]] | None = None,
    judge: Callable[..., dict[str, Any]] | None = None,
    on_progress: Callable[[str, str, dict[str, Any]], None] | None = None,
    plan: ScenarioPlan | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Generate, compile, validate, execute, and judge one fresh case.

    The existing generator does the only allowed Compiler repair.  The Runner
    creates a fresh test identity and activity; its local-only URL validation
    remains the sole database connection policy. Failures never trigger an E2E
    retry, and a failed Runner is never sent to the Judge.
    """
    generated = generate_case(
        focus,
        local_client=local_client,
        compiler_client=compiler_client,
        output_dir=output_dir,
        business_logic_path=business_logic_path,
        on_progress=on_progress,
        plan=plan,
        seed=seed,
    )
    merged = result_template(focus, plan, output_dir=Path(generated["output_dir"]))
    merged.update({key: value for key, value in generated.items() if value is not None or key in merged})
    merged["compiler_repair_count"] = generated.get("repair_count", merged["compiler_repair_count"])
    # `local_model` is the generation-stage name; the result record keeps both.
    if generated.get("local_model") and not generated.get("local_generator_model"):
        merged["local_generator_model"] = generated["local_model"]
    run = CaseRun(focus=focus, output_dir=Path(generated["output_dir"]), result=merged, plan=plan)
    stage_execute(run, runner=runner, on_progress=on_progress)
    stage_judge(run, judge=judge, judge_client=judge_client, on_progress=on_progress)
    # Preserve the historical status vocabulary for sequential callers: the
    # pipeline reads the finer-grained status, the one-case CLI does not.
    status = run.result.get("status")
    if status == "EXECUTED":
        run.result["status"] = "JUDGE_ERROR"
        if run.result.get("error_category") is None:
            run.result["error_category"] = "INVALID_VERDICT"
    elif status in ("COMPILER_ERROR", "RAW_CASE_ERROR", "ERROR"):
        run.result["status"] = "GENERATION_ERROR"
    run.save()
    return run.result
