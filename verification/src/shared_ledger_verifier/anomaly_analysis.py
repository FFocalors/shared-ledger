"""Second-stage analysis of a batch's anomaly pool with DeepSeek.

A 500-case batch produces a long tail of Judge FAIL / UNCERTAIN and Runner
FAILED cases. Handing that raw list to Codex would be useless: most entries are
the same problem repeated, some are Judge over-reach, and a few are real. This
module turns the pool into a small set of classified candidates:

1. :func:`load_anomalies` collects each anomalous case with its full artefacts.
2. :func:`anomaly_index` builds the compact table DeepSeek clusters on.
3. :func:`cluster_anomalies` asks DeepSeek to group them by suspected root cause.
4. :func:`classify_cluster` gives DeepSeek the representative case's complete
   artefacts and asks for a classification, severity and expected/actual.
5. :func:`reproduce_case` re-executes one saved scenario to test stability.

Nothing here changes business behaviour: it reads artefacts and reports.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from .deepseek import DeepSeekApiError, DeepSeekClient
from .judge import _clean_json, judge_run
from .runner import run_scenario

# Classification vocabulary required by the mass-verification brief.
CLASSIFICATIONS = (
    "BUSINESS_BUG",
    "BAD_SCENARIO",
    "JUDGE_FALSE_POSITIVE",
    "ENVIRONMENT",
    "WORKFLOW",
    "UNKNOWN",
)
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE")
_ANOMALOUS_VERDICTS = {"FAIL", "UNCERTAIN", "JUDGE_ERROR"}

# Artefact excerpts are capped so one huge state cannot dominate a prompt.
_MAX_JSON_CHARS = 24_000
_MAX_OPERATIONS = 60


@dataclass
class AnomalyRecord:
    """One anomalous case with everything the analysis needs."""

    case_id: str
    focus: str
    seed: int | None
    status: str
    judge_verdict: str | None
    runner_result: str | None
    error_category: str | None
    judge_summary: str | None
    differences: list[str]
    plan: dict[str, Any] = field(default_factory=dict)
    raw_case: dict[str, Any] = field(default_factory=dict)
    scenario: dict[str, Any] = field(default_factory=dict)
    operations: list[dict[str, Any]] = field(default_factory=list)
    state_final: dict[str, Any] = field(default_factory=dict)
    judge: dict[str, Any] = field(default_factory=dict)
    failed_operations: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_anomalous(self) -> bool:
        return (
            self.judge_verdict in _ANOMALOUS_VERDICTS
            or self.runner_result == "FAILED"
            or self.status in ("JUDGE_ERROR", "RUNNER_FAILED")
        )

    def signature(self) -> str:
        """A cheap local grouping key; DeepSeek does the real clustering."""
        if self.runner_result == "FAILED":
            failed = ",".join(
                f"{op.get('operation')}:{op.get('error_code')}" for op in self.failed_operations
            ) or "unknown"
            return f"RUNNER_FAILED|{self.focus}|{failed}"
        verdict = self.judge_verdict or "UNKNOWN"
        first = (self.differences or [""])[0]
        # Keep only the leading field path so wording shifts do not split a group.
        theme = re.sub(r"[0-9]+(?:\.[0-9]+)?", "<n>", first.lower())[:90]
        return f"{verdict}|{self.focus}|{theme}"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self) | {"signature": self.signature()}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    except (OSError, ValueError):
        return rows
    return rows


def _clip(value: Any, limit: int = _MAX_JSON_CHARS) -> Any:
    rendered = json.dumps(value, ensure_ascii=False)
    if len(rendered) <= limit:
        return value
    return {"_truncated": rendered[:limit] + " ...(truncated)"}


def load_anomalies(
    case_ids: Iterable[str], cases_dir: Path, *, include_all: bool = False
) -> list[AnomalyRecord]:
    """Collect the anomalous cases from a finished batch (or every case)."""
    records: list[AnomalyRecord] = []
    for case_id in case_ids:
        directory = cases_dir / case_id
        result = _read_json(directory / "result.json")
        if not isinstance(result, dict):
            continue
        judge = _read_json(directory / "judge.json") or {}
        operations = _read_jsonl(directory / "operations.jsonl")
        record = AnomalyRecord(
            case_id=case_id,
            focus=str(result.get("focus") or "unknown"),
            seed=result.get("plan_seed") if isinstance(result.get("plan_seed"), int) else None,
            status=str(result.get("status") or "UNKNOWN"),
            judge_verdict=result.get("judge_verdict"),
            runner_result=result.get("runner_result"),
            error_category=result.get("error_category"),
            judge_summary=judge.get("summary") if isinstance(judge, dict) else None,
            differences=list(judge.get("differences") or []) if isinstance(judge, dict) else [],
            plan=_read_json(directory / "plan.json") or {},
            raw_case=_read_json(directory / "raw_case.json") or {},
            scenario=_read_json(directory / "scenario.json") or {},
            operations=operations,
            state_final=_read_json(directory / "state_final.json") or {},
            judge=judge if isinstance(judge, dict) else {},
            failed_operations=[op for op in operations if op.get("status") == "failed"],
        )
        if include_all or record.is_anomalous:
            records.append(record)
    return records


def anomaly_index(records: Sequence[AnomalyRecord]) -> dict[str, Any]:
    """The compact table DeepSeek clusters on, plus the occurrence statistics."""
    by_signature: dict[str, list[str]] = {}
    for record in records:
        by_signature.setdefault(record.signature(), []).append(record.case_id)
    return {
        "total_anomalies": len(records),
        "by_focus": {
            focus: sum(1 for r in records if r.focus == focus)
            for focus in sorted({r.focus for r in records})
        },
        "by_verdict": {
            verdict: sum(1 for r in records if (r.judge_verdict or r.status) == verdict)
            for verdict in sorted({(r.judge_verdict or r.status) for r in records})
        },
        "local_signature_groups": [
            {
                "signature": signature,
                "occurrence_count": len(ids),
                "case_ids": ids[:20],
            }
            for signature, ids in sorted(by_signature.items(), key=lambda item: -len(item[1]))
        ],
        "entries": [
            {
                "case_id": record.case_id,
                "focus": record.focus,
                "seed": record.seed,
                "verdict": record.judge_verdict or record.status,
                "runner": record.runner_result,
                "error_category": record.error_category,
                "summary": (record.judge_summary or "")[:400],
                "differences": [d[:300] for d in record.differences[:5]],
                "failed_operations": [
                    {
                        "step": op.get("step"),
                        "operation": op.get("operation"),
                        "error_code": op.get("error_code"),
                        "error_message": str(op.get("error_message"))[:200],
                    }
                    for op in record.failed_operations
                ],
            }
            for record in records
        ],
    }


def evidence_bundle(record: AnomalyRecord) -> dict[str, Any]:
    """Everything the brief requires for one representative case."""
    return _clean_json({
        "case_id": record.case_id,
        "focus": record.focus,
        "plan_seed": record.seed,
        "runner_result": record.runner_result,
        "judge_verdict": record.judge_verdict,
        "error_category": record.error_category,
        "scenario_plan": record.plan,
        "raw_case": record.raw_case,
        "scenario": _clip(record.scenario),
        "operations": _clip(record.operations[:_MAX_OPERATIONS]),
        "state_final": _clip(record.state_final),
        "judge": _clip(record.judge),
    })


_CLUSTER_SYSTEM = """You are the Shared Ledger anomaly triage analyst.
You receive the anomaly pool of one verification batch: every Judge FAIL /
UNCERTAIN and every Runner failure, with the occurrence statistics the batch
computed locally.

Group the anomalies by SUSPECTED ROOT CAUSE, not by wording. Two cases belong to
the same cluster when a single underlying defect (or a single class of Judge
over-reach, or a single workflow bug) would explain both.

Rules:
- Prefer few, well-supported clusters over many singletons.
- A cluster may contain only one case, but say so explicitly.
- Do not decide yet whether a cluster is a real bug; only name the suspected
  root cause and the evidence that ties the members together.
- Never invent case ids. Use only ids present in the input.

Return exactly one JSON object with a "clusters" array; each element has:
  cluster_id (short stable slug), suspected_root_area (one line),
  affected_focus (focus name or "multiple"), member_case_ids (array),
  occurrence_count (integer), shared_evidence (array of short strings),
  why_one_cause (one sentence).
"""

_CLASSIFY_SYSTEM = """You are the Shared Ledger anomaly triage analyst deciding what a
cluster of anomalies means. You receive one representative case in full: the
ScenarioPlan, the raw business case, the compiled Scenario, the RPC trace, the
final database projections and the Judge's verdict with its differences.

Decide, from BUSINESS_LOGIC.md rules and the observed state:
1. real: is the anomaly a genuine deviation from the rules?
2. classification: exactly one of BUSINESS_BUG, BAD_SCENARIO,
   JUDGE_FALSE_POSITIVE, ENVIRONMENT, WORKFLOW, UNKNOWN.
   - BUSINESS_BUG: the database/projection contradicts a documented rule.
   - BAD_SCENARIO: the generated scenario itself is unreasonable, degenerate or
     asks for something the rules never promise.
   - JUDGE_FALSE_POSITIVE: the state is actually correct per the rules; the
     Judge misread it or applied an undocumented expectation.
   - ENVIRONMENT: transport, timeout, HTTP or provider failure.
   - WORKFLOW: the verification harness misbehaved (runner bug, missing fixture).
   - UNKNOWN: the supplied evidence does not settle it.
3. severity: only for BUSINESS_BUG; one of CRITICAL, HIGH, MEDIUM, LOW
   (NONE otherwise).
   CRITICAL = money invented or destroyed, wrong debt direction, an original
   funding fact rewritten, or a real Transfer/Prepayment altered.
   HIGH = core Settlement / Refund / Prepayment / Final Settlement logic wrong.
   MEDIUM = completed / archive / projection / status outcome wrong.
   LOW = minor logic that does not touch funding facts.
4. confidence: 0..1, and stable_reproduction: true/false/none.
5. expected_behavior / actual_behavior: concrete, with numbers.
6. suspected_root_area: the smallest code or rule area that would explain it.

Return exactly one JSON object with keys: real, classification, severity,
confidence, stable_reproduction, expected_behavior, actual_behavior,
suspected_root_area, reasoning.
"""


@dataclass
class ClusterVerdict:
    cluster_id: str
    suspected_root_area: str
    affected_focus: str
    member_case_ids: list[str]
    occurrence_count: int
    shared_evidence: list[str]
    why_one_cause: str
    real: bool | None = None
    classification: str | None = None
    severity: str | None = None
    confidence: float | None = None
    stable_reproduction: Any = None
    expected_behavior: str | None = None
    actual_behavior: str | None = None
    reasoning: str | None = None
    representative_case_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in the response")
    return json.loads(cleaned[start:end + 1])


def cluster_anomalies(
    index: dict[str, Any],
    *,
    client: DeepSeekClient,
    max_entries: int = 200,
) -> list[ClusterVerdict]:
    """Ask DeepSeek to group the anomaly pool by suspected root cause."""
    payload = dict(index)
    entries = payload.get("entries") or []
    if len(entries) > max_entries:
        payload["entries"] = entries[:max_entries]
        payload["entries_truncated_from"] = len(entries)
    response = client.complete(
        _CLUSTER_SYSTEM,
        "Anomaly pool:\n" + json.dumps(payload, ensure_ascii=False, indent=1),
    )
    parsed = _parse_json_object(response)
    valid_ids = {entry["case_id"] for entry in entries}
    clusters: list[ClusterVerdict] = []
    for raw in parsed.get("clusters") or []:
        members = [cid for cid in (raw.get("member_case_ids") or []) if cid in valid_ids]
        if not members:
            continue
        clusters.append(ClusterVerdict(
            cluster_id=str(raw.get("cluster_id") or f"cluster_{len(clusters) + 1}")[:60],
            suspected_root_area=str(raw.get("suspected_root_area") or "")[:400],
            affected_focus=str(raw.get("affected_focus") or "unknown")[:80],
            member_case_ids=members,
            occurrence_count=len(members),
            shared_evidence=[str(item)[:300] for item in (raw.get("shared_evidence") or [])],
            why_one_cause=str(raw.get("why_one_cause") or "")[:500],
        ))
    return clusters


def classify_cluster(
    cluster: ClusterVerdict,
    records: dict[str, AnomalyRecord],
    *,
    client: DeepSeekClient,
) -> ClusterVerdict:
    """Classify a cluster from its representative case's full artefacts."""
    representative = next(
        (records[cid] for cid in cluster.member_case_ids if cid in records), None
    )
    if representative is None:
        return cluster
    cluster.representative_case_id = representative.case_id
    bundle = evidence_bundle(representative)
    bundle["cluster_context"] = {
        "cluster_id": cluster.cluster_id,
        "occurrence_count": cluster.occurrence_count,
        "affected_focus": cluster.affected_focus,
        "suspected_root_area": cluster.suspected_root_area,
        "member_case_ids": cluster.member_case_ids[:20],
        "shared_evidence": cluster.shared_evidence,
    }
    business_logic = _business_logic_text()
    try:
        response = client.complete(
            _CLASSIFY_SYSTEM,
            "BUSINESS_LOGIC.md (the only rule source):\n" + business_logic
            + "\n\nRepresentative case:\n"
            + json.dumps(bundle, ensure_ascii=False, indent=1),
        )
        parsed = _parse_json_object(response)
    except (DeepSeekApiError, ValueError, json.JSONDecodeError):
        cluster.classification = "UNKNOWN"
        cluster.reasoning = "the analyst response could not be used"
        return cluster
    classification = str(parsed.get("classification") or "UNKNOWN").upper()
    if classification not in CLASSIFICATIONS:
        classification = "UNKNOWN"
    severity = str(parsed.get("severity") or "NONE").upper()
    if severity not in SEVERITIES:
        severity = "NONE"
    cluster.real = bool(parsed.get("real")) if isinstance(parsed.get("real"), bool) else None
    cluster.classification = classification
    cluster.severity = severity if classification == "BUSINESS_BUG" else "NONE"
    confidence = parsed.get("confidence")
    cluster.confidence = float(confidence) if isinstance(confidence, (int, float)) else None
    cluster.stable_reproduction = parsed.get("stable_reproduction")
    cluster.expected_behavior = str(parsed.get("expected_behavior") or "")[:1200]
    cluster.actual_behavior = str(parsed.get("actual_behavior") or "")[:1200]
    if parsed.get("suspected_root_area"):
        cluster.suspected_root_area = str(parsed["suspected_root_area"])[:400]
    cluster.reasoning = str(parsed.get("reasoning") or "")[:1500]
    return cluster


def _business_logic_text() -> str:
    from .judge import _BUSINESS_LOGIC_PATH

    try:
        return _BUSINESS_LOGIC_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


def reproduce_case(
    case_id: str,
    cases_dir: Path,
    *,
    judge_client: Any = None,
    runner: Callable[..., dict[str, Any]] | None = None,
    judge: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Re-execute a saved scenario to test whether the anomaly reproduces.

    The scenario is replayed exactly as saved -- nothing is regenerated -- and
    the new run is written to ``<case_dir>/repro/<run_id>`` so the original
    evidence is never touched.
    """
    case_dir = cases_dir / case_id
    scenario_path = case_dir / "scenario.json"
    if not scenario_path.is_file():
        return {"case_id": case_id, "reproduced": None, "reason": "no saved scenario"}
    original = _read_json(case_dir / "result.json") or {}
    original_verdict = original.get("judge_verdict")
    original_runner = original.get("runner_result")
    repro_root = case_dir / "repro"
    repro_root.mkdir(exist_ok=True)
    execute = runner or run_scenario
    adjudicate = judge or judge_run
    try:
        outcome = execute(scenario_path, runs_dir=repro_root)
    except Exception as exc:
        return {
            "case_id": case_id, "reproduced": None, "original_verdict": original_verdict,
            "reason": f"runner raised {type(exc).__name__}",
        }
    new_runner = outcome.get("status")
    verdict = None
    if new_runner == "EXECUTED" and outcome.get("run_dir"):
        try:
            judgment = adjudicate(Path(outcome["run_dir"]), client=judge_client)
            verdict = judgment.get("verdict") if isinstance(judgment, dict) else None
        except Exception:
            verdict = "JUDGE_ERROR"
    reproduced = None
    if original_runner == "FAILED":
        reproduced = new_runner == "FAILED"
    elif original_verdict is not None:
        reproduced = verdict == original_verdict
    return {
        "case_id": case_id,
        "run_id": outcome.get("run_id"),
        "original_runner": original_runner,
        "original_verdict": original_verdict,
        "repro_runner": new_runner,
        "repro_verdict": verdict,
        "repro_run_dir": outcome.get("run_dir"),
        "reproduced": reproduced,
    }


_PASS_AUDIT_SYSTEM = """You audit a PASS verdict from a Shared Ledger verification batch.
You receive the ScenarioPlan, the raw business case the local model proposed, the
compiled Scenario, and the final state the database produced.

Answer three questions from the evidence only:
1. compiler_preserved_intent: did the Compiler keep the plan's participants,
   amounts, split methods and operation order? Quote any drift.
2. focus_contract_genuine: does this case really exercise the behaviour its
   focus name promises, or does it merely look like it?
3. judge_missed_anything: is there a concrete contradiction with
   BUSINESS_LOGIC.md that a PASS verdict would have missed? Give numbers, or
   an empty list.

Return exactly one JSON object with keys: compiler_preserved_intent (bool),
intent_note (string), focus_contract_genuine (bool), focus_note (string),
judge_missed_anything (bool), missed_evidence (array of strings).
"""


def audit_pass_case(record: AnomalyRecord, *, client: DeepSeekClient) -> dict[str, Any]:
    """DeepSeek spot-check of one PASS case (compiler intent, focus, missed defects)."""
    bundle = evidence_bundle(record)
    bundle.pop("judge", None)  # keep the audit independent of the verdict
    try:
        response = client.complete(
            _PASS_AUDIT_SYSTEM,
            "Case under audit:\n" + json.dumps(bundle, ensure_ascii=False, indent=1),
        )
        parsed = _parse_json_object(response)
    except (DeepSeekApiError, ValueError, json.JSONDecodeError):
        return {"case_id": record.case_id, "audited": False, "reason": "unusable response"}
    return {
        "case_id": record.case_id,
        "focus": record.focus,
        "audited": True,
        "compiler_preserved_intent": bool(parsed.get("compiler_preserved_intent")),
        "intent_note": str(parsed.get("intent_note") or "")[:600],
        "focus_contract_genuine": bool(parsed.get("focus_contract_genuine")),
        "focus_note": str(parsed.get("focus_note") or "")[:600],
        "judge_missed_anything": bool(parsed.get("judge_missed_anything")),
        "missed_evidence": [str(item)[:400] for item in (parsed.get("missed_evidence") or [])],
    }


__all__ = [
    "AnomalyRecord",
    "CLASSIFICATIONS",
    "ClusterVerdict",
    "SEVERITIES",
    "anomaly_index",
    "audit_pass_case",
    "classify_cluster",
    "cluster_anomalies",
    "evidence_bundle",
    "load_anomalies",
    "reproduce_case",
]
