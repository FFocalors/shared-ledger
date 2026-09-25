"""Coverage statistics for generated batches.

The dashboard and the batch reports must answer a different question from "how
many cases ran": *how much distinct business behaviour was actually verified?*
A run of 30 cases that all encode one scenario has a coverage of one, however
green the pipeline looks.

These counters make that explicit.  ``unique_valid_count`` -- focus-contract
valid, Loader valid, and not a structural repeat of an earlier case -- is the
only denominator any pass rate may use.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .duplicates import mark_duplicates, raw_case_fingerprint, scenario_fingerprint

_VERDICTS = ("PASS", "FAIL", "UNCERTAIN", "JUDGE_ERROR")


@dataclass(frozen=True)
class CaseRecord:
    """One generated case reduced to the fields coverage cares about."""

    case_id: str
    focus: str
    timestamp: str
    status: str
    focus_result: str | None
    focus_error: str | None
    loader_result: str | None
    runner_result: str | None
    judge_verdict: str | None
    error_category: str | None
    compiler_repair_count: int
    scenario_fingerprint: str | None
    raw_case_fingerprint: str | None
    plan_seed: int | None
    plan_fingerprint: str | None
    generator_latency_seconds: float | None = None
    compiler_latency_seconds: float | None = None
    runner_latency_seconds: float | None = None
    judge_latency_seconds: float | None = None
    duplicate_of: str | None = None

    @property
    def is_focus_valid(self) -> bool:
        return self.focus_result == "FOCUS_VALID"

    @property
    def is_duplicate(self) -> bool:
        return self.duplicate_of is not None

    @property
    def was_executed(self) -> bool:
        """True once the Runner was attempted, whether it succeeded or failed.

        A case that was only generated (``generate-case``) produced no evidence,
        so it must not enter the coverage denominator; a case whose Runner failed
        must stay in it, because that is a real verification failure.
        """
        return self.runner_result is not None

    @property
    def is_unique_valid(self) -> bool:
        return (
            self.is_focus_valid
            and self.loader_result == "VALID"
            and not self.is_duplicate
            and self.was_executed
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self) | {
            "is_focus_valid": self.is_focus_valid,
            "is_duplicate": self.is_duplicate,
            "was_executed": self.was_executed,
            "is_unique_valid": self.is_unique_valid,
        }


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def load_case_record(case_dir: Path) -> CaseRecord | None:
    """Build a :class:`CaseRecord` from one generated-case directory.

    Fingerprints are read from ``result.json`` when present and recomputed from
    the saved artefacts otherwise, so cases generated before the coverage
    framework still fold into the same statistics.
    """
    result = _read_json(case_dir / "result.json")
    if not isinstance(result, dict):
        return None
    scenario = _read_json(case_dir / "scenario.json")
    raw_case = _read_json(case_dir / "raw_case.json")
    focus = str(result.get("focus") or "unknown")
    return CaseRecord(
        case_id=case_dir.name,
        focus=focus,
        timestamp=str(result.get("started_at") or case_dir.name),
        status=str(result.get("status") or "UNKNOWN"),
        focus_result=result.get("focus_result"),
        focus_error=result.get("focus_error"),
        loader_result=result.get("loader_result"),
        runner_result=result.get("runner_result"),
        judge_verdict=result.get("judge_verdict"),
        error_category=result.get("error_category"),
        compiler_repair_count=int(result.get("compiler_repair_count") or 0),
        scenario_fingerprint=result.get("scenario_fingerprint") or scenario_fingerprint(scenario),
        raw_case_fingerprint=result.get("raw_case_fingerprint") or raw_case_fingerprint(raw_case),
        plan_seed=result.get("plan_seed") if isinstance(result.get("plan_seed"), int) else None,
        plan_fingerprint=result.get("plan_fingerprint"),
        generator_latency_seconds=_number(result.get("generator_latency_seconds")),
        compiler_latency_seconds=_number(result.get("compiler_latency_seconds")),
        runner_latency_seconds=_number(result.get("runner_latency_seconds")),
        judge_latency_seconds=_number(result.get("judge_latency_seconds")),
    )


def load_case_records(root: Path, *, case_ids: Iterable[str] | None = None) -> list[CaseRecord]:
    """Load records for every generated case under ``root``, oldest first."""
    wanted = set(case_ids) if case_ids is not None else None
    records: list[CaseRecord] = []
    if not root.is_dir():
        return records
    for entry in sorted(root.iterdir(), key=lambda path: path.name):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if wanted is not None and entry.name not in wanted:
            continue
        record = load_case_record(entry)
        if record is not None:
            records.append(record)
    return records


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def compute_coverage(records: list[CaseRecord]) -> dict[str, Any]:
    """Aggregate coverage counters over an ordered list of cases."""
    duplicates = mark_duplicates([record.as_dict() for record in records])
    marked = [
        CaseRecord(**{**asdict(record), "duplicate_of": duplicates.get(record.case_id)})
        for record in records
    ]

    unique_valid = [record for record in marked if record.is_unique_valid]
    verdicts = {verdict: 0 for verdict in _VERDICTS}
    for record in unique_valid:
        if record.judge_verdict in verdicts:
            verdicts[record.judge_verdict] += 1
    passes = verdicts["PASS"]

    latencies = {
        "generator": _average([r.generator_latency_seconds for r in marked if r.generator_latency_seconds]),
        "compiler": _average([r.compiler_latency_seconds for r in marked if r.compiler_latency_seconds]),
        "runner": _average([r.runner_latency_seconds for r in marked if r.runner_latency_seconds is not None]),
        "judge": _average([r.judge_latency_seconds for r in marked if r.judge_latency_seconds is not None]),
    }

    by_focus: dict[str, dict[str, Any]] = {}
    for record in marked:
        entry = by_focus.setdefault(record.focus, {
            "focus": record.focus,
            "generated_count": 0,
            "focus_valid_count": 0,
            "focus_mismatch_count": 0,
            "duplicate_count": 0,
            "unique_valid_count": 0,
            "distinct_scenarios": 0,
            "loader_valid_count": 0,
            "runner_executed_count": 0,
            "runner_failed_count": 0,
            "compiler_repair_count": 0,
            **{verdict.lower(): 0 for verdict in _VERDICTS},
        })
        entry["generated_count"] += 1
        if record.is_focus_valid:
            entry["focus_valid_count"] += 1
        if record.focus_result == "FOCUS_MISMATCH":
            entry["focus_mismatch_count"] += 1
        if record.is_duplicate:
            entry["duplicate_count"] += 1
        if record.is_unique_valid:
            entry["unique_valid_count"] += 1
            if record.judge_verdict in _VERDICTS:
                entry[record.judge_verdict.lower()] += 1
        if record.loader_result == "VALID":
            entry["loader_valid_count"] += 1
        if record.runner_result == "EXECUTED":
            entry["runner_executed_count"] += 1
        if record.runner_result == "FAILED":
            entry["runner_failed_count"] += 1
        entry["compiler_repair_count"] += record.compiler_repair_count

    for focus, entry in by_focus.items():
        entry["distinct_scenarios"] = len({
            record.scenario_fingerprint
            for record in unique_valid
            if record.focus == focus and record.scenario_fingerprint
        })
        entry["pass_rate"] = (
            round(entry["pass"] / entry["unique_valid_count"] * 100, 1)
            if entry["unique_valid_count"] else None
        )
        entry["duplicate_rate"] = (
            round(entry["duplicate_count"] / entry["focus_valid_count"] * 100, 1)
            if entry["focus_valid_count"] else None
        )

    return {
        "generated_count": len(marked),
        "focus_valid_count": sum(1 for r in marked if r.is_focus_valid),
        "focus_mismatch_count": sum(1 for r in marked if r.focus_result == "FOCUS_MISMATCH"),
        "duplicate_count": sum(1 for r in marked if r.is_duplicate),
        "unique_valid_count": len(unique_valid),
        "distinct_scenarios": len({
            record.scenario_fingerprint for record in unique_valid if record.scenario_fingerprint
        }),
        "compiler_repair_count": sum(record.compiler_repair_count for record in marked),
        "loader_valid_count": sum(1 for r in marked if r.loader_result == "VALID"),
        "loader_invalid_count": sum(1 for r in marked if r.loader_result == "INVALID"),
        "runner_executed_count": sum(1 for r in marked if r.runner_result == "EXECUTED"),
        "runner_failed_count": sum(1 for r in marked if r.runner_result == "FAILED"),
        "judge_verdicts": verdicts,
        "pass_rate": round(passes / len(unique_valid) * 100, 1) if unique_valid else None,
        "coverage_rate": (
            round(len(unique_valid) / len(marked) * 100, 1) if marked else None
        ),
        "average_latencies": latencies,
        "focus_breakdown": sorted(by_focus.values(), key=lambda item: item["focus"]),
        "cases": [record.as_dict() for record in marked],
    }


__all__ = ["CaseRecord", "compute_coverage", "load_case_record", "load_case_records"]
