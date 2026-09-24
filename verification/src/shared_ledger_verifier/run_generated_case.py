"""Run one generated Scenario through the isolated Runner and business Judge."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from .generate_case import _has_secret, _safe_error, generate_case
from .judge import judge_run
from .runner import run_scenario


_VERDICTS = {"PASS", "FAIL", "UNCERTAIN"}


def _save(path: Path, result: dict[str, Any]) -> dict[str, Any]:
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def _copy_artifact(source: Path, destination: Path) -> bool:
    if not source.is_file():
        return False
    try:
        shutil.copyfile(source, destination)
    except OSError:
        return False
    return True


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
) -> dict[str, Any]:
    """Generate, compile, validate, execute, and judge one fresh case.

    The existing generator does the only allowed Compiler repair. The Runner
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
    )
    case_dir = Path(generated["output_dir"])
    result: dict[str, Any] = {
        "status": "PENDING",
        "focus": focus,
        "run_id": None,
        "local_generator_model": generated.get("local_model"),
        "compiler_model": generated.get("compiler_model"),
        "judge_model": None,
        "business_logic_commit": generated.get("business_logic_commit"),
        "generator_latency_seconds": generated.get("generation_latency_seconds"),
        "compiler_latency_seconds": generated.get("compiler_latency_seconds"),
        "compiler_repair_count": generated.get("repair_count"),
        "loader_result": generated.get("loader_result"),
        "loader_error": generated.get("loader_error"),
        "runner_latency_seconds": None,
        "runner_result": None,
        "judge_latency_seconds": None,
        "judge_verdict": None,
        "error_category": generated.get("error_category"),
        "output_dir": str(case_dir),
        "run_dir": None,
    }
    result_path = case_dir / "result.json"
    if generated.get("status") != "VALID":
        result["status"] = (
            "COMPILER_INVALID" if generated.get("status") == "COMPILER_INVALID"
            else "GENERATION_ERROR"
        )
        if on_progress:
            on_progress("runner", "skipped", {"reason": "generation_failed"})
            on_progress("judge", "skipped", {"reason": "generation_failed"})
        return _save(result_path, result)

    execute = runner or run_scenario
    started = perf_counter()
    if on_progress:
        on_progress("runner", "running", {})
    try:
        run = execute(case_dir / "scenario.json", runs_dir=case_dir / "runs")
    except Exception:
        result.update(status="RUNNER_FAILED", runner_result="FAILED", error_category="RUNNER_EXCEPTION")
        result["runner_latency_seconds"] = round(perf_counter() - started, 3)
        if on_progress:
            on_progress("runner", "failed", {"error": "RUNNER_EXCEPTION"})
            on_progress("judge", "skipped", {"reason": "runner_exception"})
        return _save(result_path, result)
    result["runner_latency_seconds"] = round(perf_counter() - started, 3)
    result["runner_result"] = run.get("status")
    result["run_id"] = run.get("run_id")
    run_dir_value = run.get("run_dir")
    if run_dir_value:
        run_dir = Path(run_dir_value)
        result["run_dir"] = str(run_dir)
        artifacts_complete = all(
            _copy_artifact(run_dir / filename, case_dir / filename)
            for filename in ("operations.jsonl", "state_final.json")
        )
    else:
        run_dir = None
        artifacts_complete = False
    if run.get("status") != "EXECUTED":
        result.update(status="RUNNER_FAILED", error_category=_safe_error(
            str(run.get("error_code") or "RUNNER_FAILED")))
        if on_progress:
            on_progress("runner", "failed", {"error": run.get("error_code") or "RUNNER_FAILED"})
            on_progress("judge", "skipped", {"reason": "runner_failed"})
        return _save(result_path, result)
    if not artifacts_complete or run_dir is None:
        result.update(status="RUNNER_FAILED", error_category="RUNNER_ARTIFACT_MISSING")
        if on_progress:
            on_progress("runner", "failed", {"error": "RUNNER_ARTIFACT_MISSING"})
            on_progress("judge", "skipped", {"reason": "runner_artifact_missing"})
        return _save(result_path, result)

    if on_progress:
        on_progress("runner", "completed", {
            "latency": result["runner_latency_seconds"],
            "run_id": result["run_id"],
        })

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
        return _save(result_path, result)
    result["judge_latency_seconds"] = round(perf_counter() - started, 3)
    if not isinstance(judgment, dict) or _has_secret(judgment):
        judgment = {"verdict": "JUDGE_ERROR", "error_code": "FORBIDDEN_CONTENT"}
    result["judge_model"] = judgment.get("model")
    result["judge_verdict"] = judgment.get("verdict")
    # Judge normally persists this itself; also support injected offline Judges.
    _save(run_dir / "judge.json", judgment)
    _copy_artifact(run_dir / "judge.json", case_dir / "judge.json")
    if judgment.get("verdict") not in _VERDICTS:
        result.update(status="JUDGE_ERROR", error_category=_safe_error(
            str(judgment.get("error_code") or "INVALID_VERDICT")))
        if on_progress:
            on_progress("judge", "failed", {
                "verdict": judgment.get("verdict"),
                "error": result["error_category"],
            })
    else:
        result.update(status="COMPLETE", error_category=None)
        if on_progress:
            on_progress("judge", "completed", {
                "verdict": judgment.get("verdict"),
                "latency": result["judge_latency_seconds"],
            })
    return _save(result_path, result)
