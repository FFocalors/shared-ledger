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

from ..coverage import compute_coverage, load_case_records
from ..duplicates import mark_duplicates, scenario_fingerprint
from ..focus_contract import ALL_FOCUSES, FocusDefinitionError, focus_spec
from ..fx_fixture import ensure_fx_fixture, requires_fx_fixture
from ..generate_case import _has_secret, _safe_error
from ..local_llm_v2 import FOCUS_SECTIONS
from ..pipeline import PipelineConfig, build_batch_plans, run_pipeline, summarise_pipeline
from ..run_generated_case import run_generated_case
from ..supabase import load_local_env, verification_root


# Bounded per-batch replay buffer, sized for the largest batch the UI allows
# (10 cases x 16 focus selections) with room for stage-progress events.
_EVENT_HISTORY_LIMIT = 20_000

FOCUS_META: dict[str, dict[str, str]] = {
    "expense_aa": {
        "title": "多人 AA 聚餐记账",
        "description": "大家平摊饭钱，由一人先付款，系统自动计算并记录谁欠谁多少钱",
    },
    "targeted_repayment": {
        "title": "还指定的一笔钱",
        "description": "明确指定清偿某一次消费产生的具体借款凭据",
    },
    "prepayment_refund": {
        "title": "预付款与原路退款",
        "description": "先存押金/预付款，后续用预付款核销消费，以及发生退款时原路返还",
    },
    "single_payer_aa": {
        "title": "单人付款 AA 均摊",
        "description": "一个人先垫付全部账单，其余人按 AA 均摊，产生一对多债务",
    },
    "multi_payer_aa": {
        "title": "多付款人 AA 均摊",
        "description": "两三个人各付一部分，AA 均摊后形成多债权人、多债务人的拓扑",
    },
    "aa_rounding": {
        "title": "AA 尾差分配",
        "description": "账单金额无法被人数整除，检验尾差按顺序逐个分配而非全压给最后一人",
    },
    "manual_split": {
        "title": "手工分摊",
        "description": "不按 AA，由调用方明确给出每个人承担的金额",
    },
    "fifo_repayment": {
        "title": "FIFO 还款",
        "description": "不指定具体账单，按先进先出自动选择清偿对象",
    },
    "multiple_repayments": {
        "title": "多次分批还款",
        "description": "同一笔债务用两到三次还款分批清偿",
    },
    "prepayment_before_debt": {
        "title": "先预存，后产生债务",
        "description": "先建立预存账户，之后产生的债务方向与账户一致，预存才真正被核销",
    },
    "prepayment_after_debt": {
        "title": "先有债务，后预存清偿",
        "description": "已有欠款时新预存先清偿欠款，剩余部分才进入预存账户",
    },
    "prepayment_return": {
        "title": "预存返还",
        "description": "保管人按账户币种把预存余额返还给所有者，不进入普通债务图",
    },
    "linked_refund": {
        "title": "关联退款",
        "description": "负数退款绑定原消费，且退款接收人与受益人不相同，形成新的债务方向",
    },
    "negative_expense": {
        "title": "无关联负数调整",
        "description": "不绑定任何原消费的负数账单，作为独立调整事实处理",
    },
    "void_transfer": {
        "title": "作废转账",
        "description": "真实还款登记后作废，保留历史但移除当前资金效果",
    },
    "mixed_flow": {
        "title": "混合流程",
        "description": "一个活动内组合预存、还款与退款的多步骤流程",
    },
}


def focus_catalog() -> list[dict[str, Any]]:
    """Describe every registered focus for the console's focus picker."""
    catalog: list[dict[str, Any]] = []
    for name in ALL_FOCUSES:
        spec = focus_spec(name)
        meta = FOCUS_META.get(name)
        catalog.append({
            "id": name,
            "name": f"{meta['title']} ({name})" if meta else f"{spec.title} ({name})",
            "desc": meta["description"] if meta else spec.goal,
            "tier": spec.tier,
            "goal": spec.goal,
            "participants": list(spec.participants),
            "payers": list(spec.payers),
            "amount_patterns": list(spec.amount_patterns),
            "operation_counts": list(spec.operation_counts),
            "edge_tags": list(spec.edge_tags),
        })
    return catalog


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

        # 1. Scan generated cases, oldest first so duplicate marking can keep the
        #    earliest case as the canonical one.
        generated: list[dict[str, Any]] = []
        if self.generated_cases_dir.is_dir():
            for entry in sorted(self.generated_cases_dir.iterdir(), key=lambda p: p.name):
                if not entry.is_dir() or entry.name.startswith("."):
                    continue
                case_summary = self._parse_generated_case(entry)
                if case_summary:
                    generated.append(case_summary)
                    if case_summary.get("run_id"):
                        known_run_ids.add(case_summary["run_id"])
        duplicates = mark_duplicates(generated, key="scenario_fingerprint", id_key="id")
        for case_summary in generated:
            canonical = duplicates.get(case_summary["id"])
            case_summary["duplicate"] = canonical is not None
            case_summary["duplicate_of"] = canonical
            case_summary["unique_valid"] = (
                case_summary.get("focus_status") == "FOCUS_VALID"
                and case_summary.get("loader_result") == "VALID"
                and case_summary.get("runner_result") is not None
                and canonical is None
            )
            if canonical is not None:
                case_summary["coverage_status"] = "DUPLICATE"
            elif case_summary.get("focus_status") == "FOCUS_MISMATCH":
                case_summary["coverage_status"] = "FOCUS_MISMATCH"
            elif case_summary["unique_valid"]:
                case_summary["coverage_status"] = "UNIQUE_VALID"
            else:
                case_summary["coverage_status"] = "NOT_VALID"
            cases.append(case_summary)

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

        # Fingerprint: prefer the value recorded at generation time, but derive it
        # for cases produced before the coverage framework so the case list and
        # /api/coverage always agree.
        fingerprint = result_data.get("scenario_fingerprint")
        if not fingerprint:
            fingerprint = scenario_fingerprint(_read_json_safe(case_dir / "scenario.json"))

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
            "focus_result": result_data.get("focus_result"),
            "focus_status": result_data.get("focus_result") or "UNKNOWN",
            "focus_error": result_data.get("focus_error"),
            "plan_seed": result_data.get("plan_seed"),
            "plan_fingerprint": result_data.get("plan_fingerprint"),
            "scenario_fingerprint": fingerprint,
            "duplicate": False,
            "duplicate_of": None,
            "unique_valid": False,
            "coverage_status": "NOT_VALID",
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
            "focus_result": None,
            "focus_status": "UNKNOWN",
            "focus_error": None,
            "plan_seed": None,
            "plan_fingerprint": None,
            "scenario_fingerprint": None,
            "duplicate": False,
            "duplicate_of": None,
            "unique_valid": False,
            "coverage_status": "NOT_VALID",
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

    def get_coverage_report(self) -> dict[str, Any]:
        """Coverage counters over every generated case on disk.

        ``unique_valid_count`` is the only denominator a pass rate may use: a
        focus-mismatched case and a structural repeat of an earlier case are not
        coverage, however green the pipeline looks.
        """
        summary = compute_coverage(load_case_records(self.generated_cases_dir))
        summary.pop("cases", None)
        return summary

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
            "coverage": self.get_coverage_report(),
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
                or c.get("focus_status") == "FOCUS_MISMATCH"
                or c.get("duplicate") is True
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
            elif c.get("focus_status") == "FOCUS_MISMATCH":
                # A legal scenario that does not exercise its declared focus:
                # it is not coverage, so it needs a decision, not a rerun.
                issue_type = "FOCUS_MISMATCH"
                severity = "medium"
            elif c.get("duplicate") is True:
                issue_type = "DUPLICATE_CASE"
                severity = "low"
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
            summary = (
                c.get("focus_error")
                or c.get("error_category")
                or c.get("loader_error")
            )
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
                "focus_status": c.get("focus_status"),
                "focus_error": c.get("focus_error"),
                "duplicate_of": c.get("duplicate_of"),
                "plan_seed": c.get("plan_seed"),
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

    def get_live_execution(self, orchestrator: WorkflowOrchestrator | None = None) -> dict[str, Any]:
        """Detect any actively running case (whether started via UI or externally by Claude Code)."""
        now = datetime.now(timezone.utc)
        latest_completed: dict[str, Any] | None = None
        active_case: dict[str, Any] | None = None

        # 1. Check orchestrator active batches
        if orchestrator:
            with orchestrator.lock:
                for b_id, b_data in orchestrator.active_batches.items():
                    if b_data.get("status") == "running":
                        focus = b_data.get("focus") or "unknown"
                        focus_info = FOCUS_META.get(focus, {"title": focus, "description": ""})
                        stage = b_data.get("current_stage") or "generator"
                        stage_map = {
                            "generator": ("步骤 1/5：Qwen 正在构思生活记账故事...", "AI 正在生成日常消费故事与分账意图"),
                            "compiler": ("步骤 2/5：DeepSeek 正在转译标准记账指令...", "将故事翻译为系统结构化测试场景"),
                            "loader": ("步骤 3/5：Scenario 格式体检与合规校验...", "核对数据结构与金额精度规范"),
                            "runner": ("步骤 4/5：正在本地 Supabase 真实执行记账...", "调用真实 RPC 记录账单与债务"),
                            "judge": ("步骤 5/5：DeepSeek 业务法官正在查账与审计...", "根据业务规则手册核对账面是否正确"),
                        }
                        st_title, st_desc = stage_map.get(stage, ("执行中...", ""))
                        active_case = {
                            "is_active": True,
                            "source": "web_ui",
                            "batch_id": b_id,
                            "case_id": f"批次进度: 第 {b_data.get('current_index', 1)} / {b_data.get('total_count', 1)} 案",
                            "focus": focus,
                            "focus_title": focus_info["title"],
                            "focus_desc": focus_info["description"],
                            "stage": stage,
                            "stage_name": st_title,
                            "stage_desc": st_desc,
                            "age_seconds": 0.0,
                            "stages": {
                                s: ("completed" if b_data.get("current_stage") not in (s, None) else ("running" if b_data.get("current_stage") == s else "waiting"))
                                for s in ("generator", "compiler", "loader", "runner", "judge")
                            }
                        }
                        break

        # 2. Check disk for external runs (e.g. Claude Code or CLI runs)
        if self.generated_cases_dir.is_dir():
            candidates = sorted(
                self.generated_cases_dir.iterdir(),
                key=lambda p: p.stat().st_mtime if p.is_dir() else 0,
                reverse=True,
            )
            for entry in candidates[:15]:
                if not entry.is_dir() or entry.name.startswith("."):
                    continue

                mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
                age_seconds = (now - mtime).total_seconds()

                result_path = entry / "result.json"
                result_data = _read_json_safe(result_path) or {}
                status = result_data.get("status")
                judge_file = entry / "judge.json"

                is_complete = bool(judge_file.is_file() or (status and status not in ("PENDING", None)))

                # Record the latest completed case
                if is_complete and not latest_completed:
                    latest_completed = self._parse_generated_case(entry)

                # An active case: age_seconds <= 180 and not completed yet
                if not is_complete and age_seconds <= 180 and not active_case:
                    has_raw = (entry / "raw_case.json").is_file()
                    has_scenario = (entry / "scenario.json").is_file()
                    has_operations = (entry / "operations.jsonl").is_file()

                    focus = result_data.get("focus")
                    if not focus:
                        for f_key in ("targeted_repayment", "prepayment_refund", "expense_aa"):
                            if f_key in entry.name:
                                focus = f_key
                                break
                    focus = focus or "unknown"
                    focus_info = FOCUS_META.get(focus, {"title": focus, "description": ""})

                    if not has_raw:
                        stage = "generator"
                        stage_name = "步骤 1/5：Qwen 正在构思生活记账故事..."
                        stage_desc = "AI 模型正在模拟真实的日常消费对话与参与者分账意图"
                    elif not has_scenario:
                        stage = "compiler"
                        stage_name = "步骤 2/5：DeepSeek 正在转译标准记账指令..."
                        stage_desc = "将自然语言故事转译为系统结构化 Scenario v1 测试用例"
                    elif not has_operations:
                        stage = "runner"
                        stage_name = "步骤 3/4：正在本地 Supabase 数据库真实执行..."
                        stage_desc = "调用系统 RPC 创建活动、添加成员、真实记录账单与债务结转"
                    else:
                        stage = "judge"
                        stage_name = "步骤 5/5：DeepSeek 业务法官正在查账与审计..."
                        stage_desc = "对照《业务规则手册》，逐项核对记账前后账面余额与债务结清状态"

                    active_case = {
                        "is_active": True,
                        "source": "claude_code_or_cli",
                        "case_id": entry.name,
                        "focus": focus,
                        "focus_title": focus_info["title"],
                        "focus_desc": focus_info["description"],
                        "stage": stage,
                        "stage_name": stage_name,
                        "stage_desc": stage_desc,
                        "age_seconds": round(age_seconds, 1),
                        "stages": {
                            "generator": "completed" if has_raw else ("running" if stage == "generator" else "waiting"),
                            "compiler": "completed" if has_scenario else ("running" if stage == "compiler" else "waiting"),
                            "loader": "completed" if has_scenario else ("running" if stage == "compiler" else "waiting"),
                            "runner": "completed" if has_operations else ("running" if stage == "runner" else "waiting"),
                            "judge": "running" if stage == "judge" else "waiting",
                        },
                    }

        return {
            "has_active_run": active_case is not None,
            "active_case": active_case,
            "latest_completed": latest_completed,
            "server_time": now.isoformat(),
        }


class WorkflowOrchestrator:
    """Manages background batch runs and streams progress events."""

    def __init__(self, scanner: VerificationScanner) -> None:
        self.scanner = scanner
        self.active_batches: dict[str, dict[str, Any]] = {}
        self.event_subscribers: dict[str, list[asyncio.Queue]] = {}
        # Replay buffer: a browser attaches its EventSource only after the run
        # request returns, so the first events of a batch would otherwise be
        # lost. Keep a bounded history per batch and hand it to late subscribers.
        self.event_history: dict[str, list[dict[str, Any]]] = {}
        self.lock = threading.Lock()

    def get_batch(self, batch_id: str) -> dict[str, Any] | None:
        with self.lock:
            batch = self.active_batches.get(batch_id)
            return dict(batch) if batch else None

    def create_batch(self, focuses: list[str], count: int, seed: int | None = None) -> str:
        """Create a batch of ``count`` ScenarioPlan cases for each requested focus."""
        selected = [focus for focus in focuses if focus]
        if not selected:
            raise ValueError("At least one focus is required")
        unknown = [focus for focus in selected if focus not in ALL_FOCUSES]
        if unknown:
            raise ValueError(
                f"Unsupported focus: {', '.join(unknown)}. Supported: {list(ALL_FOCUSES)}"
            )
        if count < 1 or count > 10:
            raise ValueError("Count must be between 1 and 10")

        base_seed = seed if isinstance(seed, int) else 1
        tasks: list[dict[str, Any]] = []
        for focus in selected:
            for offset in range(count):
                tasks.append({"focus": focus, "seed": base_seed + len(tasks)})

        batch_id = f"batch_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
        with self.lock:
            self.active_batches[batch_id] = {
                "batch_id": batch_id,
                "focus": selected[0] if len(selected) == 1 else "multi",
                "focuses": selected,
                "focus_counts": {focus: count for focus in selected},
                "tasks": tasks,
                "seed_base": base_seed,
                "total_count": len(tasks),
                "current_index": 0,
                "status": "pending",
                "completed_cases": [],
                "current_stage": None,
                "current_focus": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self.event_subscribers[batch_id] = []
        return batch_id

    def subscribe(self, batch_id: str) -> asyncio.Queue:
        """Return a queue pre-filled with the batch's events so far."""
        queue: asyncio.Queue = asyncio.Queue()
        with self.lock:
            if batch_id in self.event_subscribers:
                self.event_subscribers[batch_id].append(queue)
                for payload in self.event_history.get(batch_id, []):
                    queue.put_nowait(payload)
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
            history = self.event_history.setdefault(batch_id, [])
            if len(history) < _EVENT_HISTORY_LIMIT:
                history.append(payload)
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
            focuses = list(batch["focuses"])
            per_focus = batch["focus_counts"][focuses[0]]
            seed_base = batch["seed_base"]

        try:
            plans = build_batch_plans(focuses, per_focus=per_focus, seed_base=seed_base)
        except (FocusDefinitionError, ValueError) as exc:
            with self.lock:
                batch["status"] = "failed"
                batch["error"] = _safe_error(exc)
            self._broadcast_event(batch_id, "batch_failed", {"error": _safe_error(exc)})
            return

        with self.lock:
            batch["total_count"] = len(plans)

        fx_ready = None
        if any(requires_fx_fixture(plan.focus) for plan in plans):
            try:
                fixture = ensure_fx_fixture()
                fx_ready = fixture["ready"]
            except Exception:
                fx_ready = False

        config, clamped = PipelineConfig.from_env().resolved()
        self._broadcast_event(batch_id, "batch_started", {
            "focus": batch["focus"],
            "focuses": focuses,
            "total_count": len(plans),
            "seed_base": seed_base,
            "pipeline": {
                **{key: value for key, value in vars(config).items()},
                "generator_clamped": clamped,
                "fx_fixture_ready": fx_ready,
            },
        })

        seen: set[str] = set()

        def index_of(seed: Any) -> int:
            try:
                return int(seed) - seed_base + 1
            except (TypeError, ValueError):
                return 0

        def on_progress(event: dict[str, Any]) -> None:
            case_id = str(event.get("case_id") or "")
            stage = str(event.get("stage") or "")
            with self.lock:
                batch["current_stage"] = stage
                batch["current_focus"] = event.get("focus")
                batch["in_flight"] = len(seen)
            if case_id and case_id not in seen:
                # The pipeline has no single "current case"; a case is started
                # when its first event arrives, and cases overlap by design.
                seen.add(case_id)
                self._broadcast_event(batch_id, "case_started", {
                    "case_index": index_of(event.get("plan_seed")),
                    "total_count": len(plans),
                    "focus": event.get("focus"),
                    "seed": event.get("plan_seed"),
                    "case_id": case_id,
                })
            self._broadcast_event(batch_id, "stage_progress", {
                "case_index": index_of(event.get("plan_seed")),
                "total_count": len(plans),
                "case_id": case_id,
                "focus": event.get("focus"),
                "seed": event.get("plan_seed"),
                "stage": stage,
                "status": event.get("status"),
                "details": event.get("details") or {},
            })

        def on_case_done(result: dict[str, Any]) -> None:
            case_id = Path(result["output_dir"]).name if result.get("output_dir") else None
            with self.lock:
                batch["completed_cases"].append(result)
            self._broadcast_event(batch_id, "case_completed", {
                "case_index": index_of(result.get("plan_seed")),
                "total_count": len(plans),
                "case_id": case_id,
                "focus": result.get("focus"),
                "seed": result.get("plan_seed"),
                "result": {
                    "status": result.get("status"),
                    "run_id": result.get("run_id"),
                    "judge_verdict": result.get("judge_verdict"),
                    "runner_result": result.get("runner_result"),
                    "loader_result": result.get("loader_result"),
                    "focus_result": result.get("focus_result"),
                    "plan_seed": result.get("plan_seed"),
                },
            })

        failure: str | None = None
        pipeline_summary: dict[str, Any] | None = None
        try:
            payload = run_pipeline(
                plans,
                config=config,
                on_progress=on_progress,
                on_case_done=on_case_done,
            )
            pipeline_summary = summarise_pipeline(payload)
        except Exception as exc:
            failure = _safe_error(exc)

        with self.lock:
            batch["status"] = "failed" if failure else "completed"
            if failure:
                batch["error"] = failure
            batch["coverage"] = None
            batch["pipeline"] = pipeline_summary
            case_ids = [
                Path(item["output_dir"]).name
                for item in batch["completed_cases"] if item.get("output_dir")
            ]
        if failure is None:
            try:
                summary = compute_coverage(
                    load_case_records(self.scanner.generated_cases_dir, case_ids=case_ids)
                )
                summary.pop("cases", None)
                with self.lock:
                    batch["coverage"] = summary
            except Exception:
                pass
        if failure:
            self._broadcast_event(batch_id, "batch_failed", {"error": failure})
            return
        with self.lock:
            coverage = batch["coverage"]
        self._broadcast_event(batch_id, "batch_completed", {
            "total_count": len(plans),
            "completed_count": len(case_ids),
            "coverage": coverage,
            "pipeline": pipeline_summary,
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
