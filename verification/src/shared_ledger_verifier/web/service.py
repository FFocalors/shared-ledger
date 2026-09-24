"""Service layer for verification dashboard: artifact scanning, stats calculation, and workflow orchestration."""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Generator

from ..generate_case import _has_secret, _safe_error
from ..local_llm_v2 import FOCUS_SECTIONS
from ..run_generated_case import run_generated_case
from ..supabase import load_local_env, verification_root


def _parse_timestamp(name_or_str: str) -> tuple[str, str]:
    """Parse a timestamp into ISO format and user-friendly display string."""
    # Match YYYYMMDDTHHMMSS[fZ]
    match = re.search(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})", name_or_str)
    if match:
        y, m, d, hh, mm, ss = match.groups()
        iso = f"{y}-{m}-{d}T{hh}:{mm}:{ss}Z"
        display = f"{y}-{m}-{d} {hh}:{mm}:{ss}"
        return iso, display
    return "", name_or_str


def _read_json_safe(path: Path) -> Any | None:
    if not path.is_file():
        return None
    try:
        content = path.read_text(encoding="utf-8")
        parsed = json.loads(content)
        if _has_secret(parsed):
            return {"error": "Content contains sensitive credentials and is redacted"}
        return parsed
    except Exception:
        return None


def _read_jsonl_safe(path: Path) -> list[dict[str, Any]] | None:
    if not path.is_file():
        return None
    lines: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if not _has_secret(item):
                lines.append(item)
        return lines
    except Exception:
        return None


class VerificationScanner:
    """Scans generated cases and smoke runs from disk."""

    def __init__(self, root_dir: Path | None = None) -> None:
        self.root_dir = root_dir or verification_root()
        self.generated_cases_dir = self.root_dir / "local_llm_probe" / "generated_cases"
        self.runs_dir = self.root_dir / "runs"

    def scan_cases(self) -> list[dict[str, Any]]:
        load_local_env()
        cases: list[dict[str, Any]] = []
        known_run_ids: set[str] = set()

        # 1. Scan generated cases
        if self.generated_cases_dir.is_dir():
            for entry in sorted(self.generated_cases_dir.iterdir(), key=lambda p: p.name, reverse=True):
                if not entry.is_dir() or entry.name.startswith("."):
                    continue
                case_summary = self._parse_generated_case(entry)
                if case_summary:
                    cases.append(case_summary)
                    if case_summary.get("run_id"):
                        known_run_ids.add(case_summary["run_id"])

        # 2. Scan standalone smoke runs
        if self.runs_dir.is_dir():
            for entry in sorted(self.runs_dir.iterdir(), key=lambda p: p.name, reverse=True):
                if not entry.is_dir() or entry.name.startswith("."):
                    continue
                # If this run was already incorporated in a generated case, skip or record as smoke
                if entry.name in known_run_ids:
                    continue
                smoke_summary = self._parse_smoke_run(entry)
                if smoke_summary:
                    cases.append(smoke_summary)

        # Sort all by timestamp descending
        cases.sort(key=lambda c: c.get("timestamp") or "", reverse=True)
        return cases

    def _parse_generated_case(self, case_dir: Path) -> dict[str, Any] | None:
        result_path = case_dir / "result.json"
        result_data = _read_json_safe(result_path) or {}

        iso_time, display_time = _parse_timestamp(case_dir.name)
        if not iso_time and result_path.is_file():
            mtime = datetime.fromtimestamp(result_path.stat().st_mtime, tz=timezone.utc)
            iso_time = mtime.strftime("%Y-%m-%dT%H:%M:%SZ")
            display_time = mtime.strftime("%Y-%m-%d %H:%M:%S")

        run_id = result_data.get("run_id")
        focus = result_data.get("focus") or "unknown"
        status = result_data.get("status") or "UNKNOWN"
        loader_result = result_data.get("loader_result")
        runner_result = result_data.get("runner_result")
        judge_verdict = result_data.get("judge_verdict")

        # Check if judge.json exists independently
        judge_path = case_dir / "judge.json"
        judge_data = _read_json_safe(judge_path) if judge_path.is_file() else None
        if judge_data and not judge_verdict:
            judge_verdict = judge_data.get("verdict")

        # Latencies
        gen_lat = result_data.get("generator_latency_seconds") or result_data.get("generation_latency_seconds")
        comp_lat = result_data.get("compiler_latency_seconds")
        run_lat = result_data.get("runner_latency_seconds")
        judge_lat = result_data.get("judge_latency_seconds")

        valid_lats = [l for l in (gen_lat, comp_lat, run_lat, judge_lat) if l is not None]
        total_lat = round(sum(valid_lats), 3) if valid_lats else None

        # Normalized overall result & filter status
        if judge_verdict in ("PASS", "FAIL", "UNCERTAIN"):
            overall_result = judge_verdict
            filter_status = judge_verdict
        elif judge_verdict == "JUDGE_ERROR" or status == "JUDGE_ERROR":
            overall_result = "JUDGE_ERROR"
            filter_status = "ERROR"
        elif runner_result == "FAILED" or status == "RUNNER_FAILED":
            overall_result = "RUNNER_FAILED"
            filter_status = "ERROR"
        elif loader_result == "INVALID" or status == "COMPILER_INVALID":
            overall_result = "COMPILER_INVALID"
            filter_status = "ERROR"
        elif status in ("RAW_CASE_ERROR", "GENERATION_ERROR"):
            overall_result = "GENERATION_ERROR"
            filter_status = "ERROR"
        elif runner_result == "EXECUTED":
            overall_result = "EXECUTED"
            filter_status = "EXECUTED"
        elif status == "VALID":
            overall_result = "LOADER_VALID"
            filter_status = "LOADER_VALID"
        else:
            overall_result = status
            filter_status = "ERROR" if "ERROR" in status or "FAILED" in status else "OTHER"

        return {
            "id": case_dir.name,
            "source_type": "generated",
            "run_id": run_id,
            "focus": focus,
            "timestamp": iso_time,
            "time_display": display_time,
            "status": status,
            "overall_result": overall_result,
            "filter_status": filter_status,
            "loader_result": loader_result,
            "runner_result": runner_result,
            "judge_verdict": judge_verdict,
            "latencies": {
                "generator": gen_lat,
                "compiler": comp_lat,
                "runner": run_lat,
                "judge": judge_lat,
                "total": total_lat,
            },
            "error_category": result_data.get("error_category"),
            "loader_error": result_data.get("loader_error"),
            "models": {
                "generator": result_data.get("local_generator_model") or result_data.get("local_model"),
                "compiler": result_data.get("compiler_model"),
                "judge": result_data.get("judge_model") or (judge_data.get("model") if judge_data else None),
            },
            "has_artifacts": {
                "raw_case": (case_dir / "raw_case.json").is_file(),
                "compiler_result": (case_dir / "compiler_result.json").is_file(),
                "scenario": (case_dir / "scenario.json").is_file(),
                "operations": (case_dir / "operations.jsonl").is_file(),
                "state_final": (case_dir / "state_final.json").is_file(),
                "judge": (case_dir / "judge.json").is_file(),
                "result": result_path.is_file(),
            },
            "dir_path": str(case_dir),
        }

    def _parse_smoke_run(self, run_dir: Path) -> dict[str, Any] | None:
        result_path = run_dir / "result.json"
        result_data = _read_json_safe(result_path) or {}

        iso_time, display_time = _parse_timestamp(run_dir.name)
        if not iso_time and result_data.get("started_at"):
            iso_time, display_time = _parse_timestamp(result_data["started_at"])

        run_id = result_data.get("run_id") or run_dir.name
        focus = result_data.get("scenario_id") or "smoke"
        status = result_data.get("status") or "UNKNOWN"
        runner_result = status

        judge_path = run_dir / "judge.json"
        judge_data = _read_json_safe(judge_path) if judge_path.is_file() else None
        judge_verdict = judge_data.get("verdict") if judge_data else None

        # Compute duration if started_at and completed_at exist
        total_lat = None
        started_at = result_data.get("started_at")
        completed_at = result_data.get("completed_at")
        if started_at and completed_at:
            try:
                t1 = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                t2 = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
                total_lat = round((t2 - t1).total_seconds(), 3)
            except Exception:
                pass

        if judge_verdict in ("PASS", "FAIL", "UNCERTAIN"):
            overall_result = judge_verdict
            filter_status = judge_verdict
        elif judge_verdict == "JUDGE_ERROR":
            overall_result = "JUDGE_ERROR"
            filter_status = "ERROR"
        elif runner_result == "FAILED":
            overall_result = "RUNNER_FAILED"
            filter_status = "ERROR"
        elif runner_result == "EXECUTED":
            overall_result = "EXECUTED"
            filter_status = "EXECUTED"
        else:
            overall_result = status
            filter_status = "ERROR" if "FAILED" in status else "OTHER"

        return {
            "id": run_dir.name,
            "source_type": "smoke",
            "run_id": run_id,
            "focus": focus,
            "timestamp": iso_time,
            "time_display": display_time,
            "status": status,
            "overall_result": overall_result,
            "filter_status": filter_status,
            "loader_result": "VALID" if runner_result == "EXECUTED" else None,
            "runner_result": runner_result,
            "judge_verdict": judge_verdict,
            "latencies": {
                "generator": None,
                "compiler": None,
                "runner": total_lat,
                "judge": None,
                "total": total_lat,
            },
            "error_category": result_data.get("error_code"),
            "loader_error": None,
            "models": {
                "generator": None,
                "compiler": None,
                "judge": judge_data.get("model") if judge_data else None,
            },
            "has_artifacts": {
                "raw_case": False,
                "compiler_result": False,
                "scenario": (run_dir / "scenario.json").is_file(),
                "operations": (run_dir / "operations.jsonl").is_file(),
                "state_final": (run_dir / "state_final.json").is_file(),
                "judge": (run_dir / "judge.json").is_file(),
                "result": result_path.is_file(),
            },
            "dir_path": str(run_dir),
        }

    def get_dashboard_stats(self) -> dict[str, Any]:
        cases = self.scan_cases()
        total_cases = len(cases)

        pass_count = sum(1 for c in cases if c["filter_status"] == "PASS")
        fail_count = sum(1 for c in cases if c["filter_status"] == "FAIL")
        uncertain_count = sum(1 for c in cases if c["filter_status"] == "UNCERTAIN")
        error_count = sum(1 for c in cases if c["filter_status"] == "ERROR")

        # Loader stats
        loader_valid_cases = sum(1 for c in cases if c.get("loader_result") == "VALID")
        loader_tested_cases = sum(1 for c in cases if c.get("loader_result") in ("VALID", "INVALID"))
        loader_valid_rate = round(loader_valid_cases / loader_tested_cases * 100, 1) if loader_tested_cases else 100.0

        # Runner stats
        runner_executed_cases = sum(1 for c in cases if c.get("runner_result") == "EXECUTED")
        runner_tested_cases = sum(1 for c in cases if c.get("runner_result") in ("EXECUTED", "FAILED"))
        runner_exec_rate = round(runner_executed_cases / runner_tested_cases * 100, 1) if runner_tested_cases else 100.0

        # Latencies
        gen_lats = [c["latencies"]["generator"] for c in cases if c["latencies"].get("generator") is not None]
        comp_lats = [c["latencies"]["compiler"] for c in cases if c["latencies"].get("compiler") is not None]
        run_lats = [c["latencies"]["runner"] for c in cases if c["latencies"].get("runner") is not None]
        judge_lats = [c["latencies"]["judge"] for c in cases if c["latencies"].get("judge") is not None]
        total_lats = [c["latencies"]["total"] for c in cases if c["latencies"].get("total") is not None]

        def _avg(lst: list[float]) -> float | None:
            return round(sum(lst) / len(lst), 2) if lst else None

        average_latencies = {
            "generator": _avg(gen_lats),
            "compiler": _avg(comp_lats),
            "runner": _avg(run_lats),
            "judge": _avg(judge_lats),
            "total": _avg(total_lats),
        }

        # Focus breakdown
        focus_map: dict[str, dict[str, Any]] = {}
        for c in cases:
            f = c.get("focus") or "other"
            if f not in focus_map:
                focus_map[f] = {
                    "focus": f,
                    "total": 0,
                    "pass": 0,
                    "fail": 0,
                    "uncertain": 0,
                    "error": 0,
                    "executed": 0,
                }
            entry = focus_map[f]
            entry["total"] += 1
            if c["filter_status"] == "PASS":
                entry["pass"] += 1
            elif c["filter_status"] == "FAIL":
                entry["fail"] += 1
            elif c["filter_status"] == "UNCERTAIN":
                entry["uncertain"] += 1
            elif c["filter_status"] == "ERROR":
                entry["error"] += 1
            if c.get("runner_result") == "EXECUTED":
                entry["executed"] += 1

        focus_stats = []
        for f, data in sorted(focus_map.items(), key=lambda item: item[1]["total"], reverse=True):
            rated_total = data["pass"] + data["fail"] + data["uncertain"] + data["error"]
            data["pass_rate"] = round(data["pass"] / rated_total * 100, 1) if rated_total else 0.0
            focus_stats.append(data)

        return {
            "total_cases": total_cases,
            "verdicts": {
                "PASS": pass_count,
                "FAIL": fail_count,
                "UNCERTAIN": uncertain_count,
                "ERROR": error_count,
            },
            "loader_stats": {
                "valid": loader_valid_cases,
                "tested": loader_tested_cases,
                "valid_rate": loader_valid_rate,
            },
            "runner_stats": {
                "executed": runner_executed_cases,
                "tested": runner_tested_cases,
                "execution_rate": runner_exec_rate,
            },
            "average_latencies": average_latencies,
            "focus_stats": focus_stats,
            "recent_cases": cases[:5],
        }

    def get_issue_queue(self) -> list[dict[str, Any]]:
        """Filter and detail all problematic cases for review."""
        cases = self.scan_cases()
        issues: list[dict[str, Any]] = []

        for c in cases:
            overall = c.get("overall_result")
            status = c.get("status")
            runner = c.get("runner_result")
            judge = c.get("judge_verdict")

            is_issue = (
                judge in ("FAIL", "UNCERTAIN", "JUDGE_ERROR")
                or overall in ("FAIL", "UNCERTAIN", "COMPILER_INVALID", "RUNNER_FAILED", "JUDGE_ERROR", "GENERATION_ERROR")
                or runner == "FAILED"
                or c.get("loader_result") == "INVALID"
            )
            if not is_issue:
                continue

            # Classify issue type and level
            if judge == "FAIL" or overall == "FAIL":
                issue_type = "FAIL"
                severity = "high"
            elif judge == "UNCERTAIN" or overall == "UNCERTAIN":
                issue_type = "UNCERTAIN"
                severity = "medium"
            elif overall == "COMPILER_INVALID" or c.get("loader_result") == "INVALID":
                issue_type = "COMPILER_INVALID"
                severity = "high"
            elif overall == "RUNNER_FAILED" or runner == "FAILED":
                issue_type = "RUNNER_FAILED"
                severity = "high"
            elif overall == "JUDGE_ERROR" or judge == "JUDGE_ERROR":
                issue_type = "JUDGE_ERROR"
                severity = "high"
            else:
                issue_type = status or "ERROR"
                severity = "medium"

            # Fetch extra error summary if possible
            dir_path = Path(c["dir_path"])
            summary = c.get("error_category") or c.get("loader_error")
            differences: list[str] = []

            judge_file = dir_path / "judge.json"
            if judge_file.is_file():
                judge_data = _read_json_safe(judge_file) or {}
                if judge_data.get("summary"):
                    summary = judge_data["summary"]
                if judge_data.get("differences"):
                    differences = judge_data["differences"]

            issues.append({
                "id": c["id"],
                "run_id": c.get("run_id"),
                "focus": c.get("focus"),
                "issue_type": issue_type,
                "severity": severity,
                "timestamp": c.get("timestamp"),
                "time_display": c.get("time_display"),
                "summary": summary,
                "differences": differences,
                "loader_error": c.get("loader_error"),
                "models": c.get("models"),
                "latencies": c.get("latencies"),
            })

        return issues

    def get_case_detail(self, case_id: str) -> dict[str, Any] | None:
        """Fetch all 6 core verification artifacts plus metadata for a case."""
        target_dir: Path | None = None

        # Check in generated_cases
        candidate_gen = self.generated_cases_dir / case_id
        if candidate_gen.is_dir():
            target_dir = candidate_gen
        else:
            # Check in runs
            candidate_run = self.runs_dir / case_id
            if candidate_run.is_dir():
                target_dir = candidate_run
            else:
                # Also search by run_id if case_id was a run_id
                for c in self.scan_cases():
                    if c.get("run_id") == case_id or c.get("id") == case_id:
                        target_dir = Path(c["dir_path"])
                        break

        if not target_dir or not target_dir.is_dir():
            return None

        # Read artifacts
        raw_case = _read_json_safe(target_dir / "raw_case.json")
        compiler_result = _read_json_safe(target_dir / "compiler_result.json")
        scenario = _read_json_safe(target_dir / "scenario.json")
        operations = _read_jsonl_safe(target_dir / "operations.jsonl")
        state_final = _read_json_safe(target_dir / "state_final.json")
        judge = _read_json_safe(target_dir / "judge.json")
        result = _read_json_safe(target_dir / "result.json")

        iso_time, display_time = _parse_timestamp(target_dir.name)

        return {
            "id": target_dir.name,
            "case_id": target_dir.name,
            "time_display": display_time,
            "timestamp": iso_time,
            "artifacts": {
                "raw_case": raw_case,
                "compiler_result": compiler_result,
                "scenario": scenario,
                "operations": operations,
                "state_final": state_final,
                "judge": judge,
                "result": result,
            },
        }


class WorkflowOrchestrator:
    """Manages background batch runs and streams progress events."""

    def __init__(self, scanner: VerificationScanner) -> None:
        self.scanner = scanner
        self.active_batches: dict[str, dict[str, Any]] = {}
        self.event_subscribers: dict[str, list[asyncio.Queue]] = {}
        self.lock = threading.Lock()

    def create_batch(self, focus: str, count: int) -> str:
        if focus not in FOCUS_SECTIONS:
            raise ValueError(f"Unsupported focus: {focus}. Supported: {list(FOCUS_SECTIONS.keys())}")
        if count < 1 or count > 10:
            raise ValueError("Count must be between 1 and 10")

        batch_id = f"batch_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
        with self.lock:
            self.active_batches[batch_id] = {
                "batch_id": batch_id,
                "focus": focus,
                "total_count": count,
                "current_index": 0,
                "status": "pending",
                "completed_cases": [],
                "current_stage": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self.event_subscribers[batch_id] = []
        return batch_id

    def subscribe(self, batch_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        with self.lock:
            if batch_id in self.event_subscribers:
                self.event_subscribers[batch_id].append(queue)
        return queue

    def unsubscribe(self, batch_id: str, queue: asyncio.Queue) -> None:
        with self.lock:
            if batch_id in self.event_subscribers:
                try:
                    self.event_subscribers[batch_id].remove(queue)
                except ValueError:
                    pass

    def _broadcast_event(self, batch_id: str, event_type: str, data: dict[str, Any]) -> None:
        payload = {"batch_id": batch_id, "event": event_type, "data": data}
        with self.lock:
            queues = list(self.event_subscribers.get(batch_id, []))
        for q in queues:
            try:
                q.put_nowait(payload)
            except Exception:
                pass

    def run_batch_in_background(self, batch_id: str) -> None:
        thread = threading.Thread(target=self._execute_batch, args=(batch_id,), daemon=True)
        thread.start()

    def _execute_batch(self, batch_id: str) -> None:
        with self.lock:
            batch = self.active_batches.get(batch_id)
            if not batch:
                return
            batch["status"] = "running"

        focus = batch["focus"]
        total_count = batch["total_count"]
        self._broadcast_event(batch_id, "batch_started", {
            "focus": focus,
            "total_count": total_count,
        })

        for case_idx in range(1, total_count + 1):
            with self.lock:
                batch["current_index"] = case_idx

            self._broadcast_event(batch_id, "case_started", {
                "case_index": case_idx,
                "total_count": total_count,
                "focus": focus,
            })

            def on_progress(stage: str, status: str, details: dict[str, Any]) -> None:
                with self.lock:
                    batch["current_stage"] = stage
                self._broadcast_event(batch_id, "stage_progress", {
                    "case_index": case_idx,
                    "total_count": total_count,
                    "stage": stage,
                    "status": status,
                    "details": details,
                })

            try:
                result = run_generated_case(focus, on_progress=on_progress)
                case_id = Path(result["output_dir"]).name if result.get("output_dir") else None
                with self.lock:
                    batch["completed_cases"].append(result)
                self._broadcast_event(batch_id, "case_completed", {
                    "case_index": case_idx,
                    "total_count": total_count,
                    "case_id": case_id,
                    "result": {
                        "status": result.get("status"),
                        "run_id": result.get("run_id"),
                        "judge_verdict": result.get("judge_verdict"),
                        "runner_result": result.get("runner_result"),
                        "loader_result": result.get("loader_result"),
                    },
                })
            except Exception as exc:
                safe_err = _safe_error(exc)
                self._broadcast_event(batch_id, "case_failed", {
                    "case_index": case_idx,
                    "total_count": total_count,
                    "error": safe_err,
                })

        with self.lock:
            batch["status"] = "completed"
        self._broadcast_event(batch_id, "batch_completed", {
            "total_count": total_count,
            "completed_count": len(batch["completed_cases"]),
        })

    def get_batch_status(self, batch_id: str) -> dict[str, Any] | None:
        with self.lock:
            batch = self.active_batches.get(batch_id)
            if not batch:
                return None
            return dict(batch)


# Singleton instances
scanner_instance = VerificationScanner()
orchestrator_instance = WorkflowOrchestrator(scanner_instance)
