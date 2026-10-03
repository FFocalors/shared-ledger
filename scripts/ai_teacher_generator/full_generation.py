"""Versioned, bounded Teacher candidate-pool generation for the frozen P0 seed."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
import unicodedata
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.ai_teacher_generator.generator import (  # noqa: E402
    GeneratorError,
    _json_bytes,
    _matrix_rows,
    _read_json,
    _write_json,
    build_request,
    create_plan,
    frozen_assets,
    make_candidate,
    validate_candidate,
)
from scripts.ai_teacher_generator.live_provider import (  # noqa: E402
    ADAPTER_VERSION,
    LiveProviderError,
    ProviderConfig,
    parse_completion,
    request_completion,
)


PILOT_PATH = Path("scripts/ai_teacher_generator/runs/live-pilot/pilot-20260929T074620Z-c314cc93")
HARD_TAGS = {
    "multiple_candidates", "financial_risk", "gated_operation", "multi_currency",
    "stale_context", "unknown_write_state", "pending_default_policy",
    "cross_activity_reference", "contradictory_input", "unsupported",
    "permission_boundary", "missing_payer", "missing_participants",
    "missing_split_method", "d4_preview_only",
}
LANGUAGE_STYLES = ("colloquial", "typo_asr_like", "pronoun_ellipsis", "multi_turn")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _surface_norm(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).casefold())


def _sim(left: str, right: str) -> float:
    return SequenceMatcher(None, _surface_norm(left), _surface_norm(right)).ratio()


def _pilot_review_inputs(root: Path, pilot_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    manifest = _read_json(root / pilot_path / "pilot_manifest.json")
    review = _read_json(root / pilot_path / "human_quality_review.json")
    if manifest.get("training_eligible") is not False or manifest.get("formal_dataset_mutated") is not False:
        raise GeneratorError("Pilot run is not marked isolated and non-training.")
    retained = []
    excluded = []
    for item in review.get("reviews", []):
        if item.get("decision") != "retain_as_unapproved_candidate":
            continue
        sample_id = item.get("candidate_id")
        candidate_path = root / pilot_path / next(
            call["call_id"] for call in manifest["calls"] if call.get("candidate_id") == sample_id
        ) / "candidate_sample.json"
        candidate = _read_json(candidate_path)
        retained.append({"review": item, "candidate": candidate, "source_path": str(candidate_path.relative_to(root))})
    return manifest, retained


def _style_for_slot(samples: list[dict[str, Any]], slot: int, target: int) -> tuple[str, dict[str, Any]]:
    supports: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        for style in _available_styles(sample):
            supports[style].append(sample)
    common = [style for style in LANGUAGE_STYLES if supports.get(style)]
    has_conversation = any(sample.get("surface_form", {}).get("conversation") for sample in samples)
    if has_conversation and "multi_turn" in common:
        order = ["colloquial", "typo_asr_like", "pronoun_ellipsis", "multi_turn"]
    else:
        order = ["colloquial", "typo_asr_like", "pronoun_ellipsis"]
    order = [style for style in order if style in common]
    if not order:
        raise GeneratorError("No supported language-variation style exists for a Gold Family.")
    style = order[slot] if slot < len(order) else order[slot % len(order)]
    sources = sorted(supports[style], key=lambda sample: sample["sample_id"])
    # A repeated style is paired with a different frozen source sample whenever possible.
    source = sources[(slot // len(order)) % len(sources)] if len(sources) > 1 else sources[slot % len(sources)]
    return style, source


def _available_styles(sample: dict[str, Any]) -> list[str]:
    from scripts.ai_teacher_generator.generator import _style_options
    return _style_options(sample)


def build_generation_plan(root: Path = ROOT, pilot_path: Path = PILOT_PATH) -> dict[str, Any]:
    assets = frozen_assets(root)
    pilot_manifest, pilot_items = _pilot_review_inputs(root, pilot_path)
    samples_by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in assets["samples"]:
        if sample.get("trust", {}).get("level") == "GOLD":
            samples_by_family[sample["scenario_family_id"]].append(sample)
    scenarios_by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for scenario in assets["scenarios"]:
        scenarios_by_family[scenario.get("scenario_family_id", "")].append(scenario)
    rows = _matrix_rows(root / "docs/ai/dataset/GOLD_SEED_COVERAGE_MATRIX_V0.1.md")

    # Reconcile the previously retained Pilot cohort against the frozen Gold and itself.
    accepted_pilot: list[dict[str, Any]] = []
    pilot_exclusions: list[dict[str, Any]] = []
    gold_by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for gold in assets["samples"]:
        if gold.get("trust", {}).get("level") == "GOLD":
            gold_by_family[gold["scenario_family_id"]].append(gold)
    for item in pilot_items:
        candidate = item["candidate"]
        text = candidate.get("surface_form", {}).get("user_message", "")
        comparisons = []
        for gold in gold_by_family[candidate["scenario_family_id"]]:
            score = _sim(text, gold.get("surface_form", {}).get("user_message", ""))
            if score >= 0.95:
                comparisons.append({"kind": "frozen_gold_near_duplicate", "sample_id": gold["sample_id"], "similarity": round(score, 4)})
        for prior in accepted_pilot:
            if prior["candidate"]["scenario_family_id"] == candidate["scenario_family_id"]:
                score = _sim(text, prior["candidate"].get("surface_form", {}).get("user_message", ""))
                if score >= 0.95:
                    comparisons.append({"kind": "pilot_near_duplicate", "sample_id": prior["candidate"]["sample_id"], "similarity": round(score, 4)})
        if comparisons:
            pilot_exclusions.append({
                "candidate_id": candidate["sample_id"],
                "family_id": candidate["scenario_family_id"],
                "source_path": item["source_path"],
                "reason": "Near-duplicate threshold >= 0.95 against frozen Gold or retained Pilot candidate.",
                "matches": comparisons,
            })
        else:
            accepted_pilot.append(item)

    reused_by_family: dict[str, list[str]] = defaultdict(list)
    for item in accepted_pilot:
        reused_by_family[item["candidate"]["scenario_family_id"]].append(item["candidate"]["sample_id"])
    run_id = "fullgen-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    family_plans = []
    global_call_index = 0
    for family_id, family_scenarios in scenarios_by_family.items():
        family_samples = sorted(samples_by_family.get(family_id, []), key=lambda sample: sample["sample_id"])
        if not family_samples:
            continue
        scenario = family_scenarios[0]
        family_code = scenario.get("source", {}).get("source_id", "")
        matrix_row = rows[family_code]
        challenges = sorted({tag for sample in family_samples for tag in sample.get("challenge_tags", [])})
        difficulty = sorted({sample.get("difficulty", "normal") for sample in family_samples})
        if family_id in reused_by_family:
            target = len(reused_by_family[family_id])
            new_count = 0
            rationale = "Reuse reviewed Pilot variants; their available style slots are already covered."
        else:
            is_high = any(level in {"hard", "ood"} for level in difficulty) or len(set(challenges) & HARD_TAGS) >= 2
            if is_high:
                target = 4 if len(family_samples) >= 2 else 3
                rationale = "Hard/ambiguous/risk/context-heavy Family; use four variants when two frozen source surfaces support distinct plans, otherwise three."
            elif all(level == "easy" for level in difficulty) and not (set(challenges) & HARD_TAGS):
                target = 2
                rationale = "Easy, low-risk Family; two variants cover its smaller language space without redundant calls."
            else:
                target = 3
                rationale = "Normal complexity; colloquial, ASR-like, and pronoun/ellipsis coverage."
            new_count = target
        calls = []
        if new_count:
            for slot in range(new_count):
                style, source_sample = _style_for_slot(family_samples, slot, new_count)
                # Deterministic seed uniquely selects the requested source sample.
                seed = 510001 + global_call_index * 17
                for candidate_seed in range(seed, seed + 2 * len(family_samples) + 4):
                    try:
                        check = create_plan(family_id, candidate_seed, root, style)
                    except GeneratorError:
                        continue
                    if check["gold_sample_id"] == source_sample["sample_id"]:
                        seed = candidate_seed
                        break
                else:
                    raise GeneratorError(f"Unable to create deterministic plan for {family_id} / {style}.")
                global_call_index += 1
                call_id = f"call-{global_call_index:04d}"
                plan = create_plan(family_id, seed, root, style)
                reason = (
                    f"{style} variation from frozen source {source_sample['sample_id']}; "
                    f"difficulty={plan['difficulty']}; preserve its exact Ground Truth and Context."
                )
                calls.append({
                    "call_id": call_id,
                    "family_id": family_id,
                    "family_code": family_code,
                    "scenario_id": plan["scenario_id"],
                    "source_sample_id": source_sample["sample_id"],
                    "split_group_id": plan["split_group_id"],
                    "seed": seed,
                    "style": style,
                    "difficulty": plan["difficulty"],
                    "context_profile": plan["context_profile"],
                    "variant_reason": reason,
                })
        family_plans.append({
            "family_id": family_id,
            "family_code": family_code,
            "matrix_priority": matrix_row["priority"],
            "matrix_sample_target": matrix_row["sample_target"],
            "task": family_samples[0].get("task", {}).get("primary"),
            "intent_ids": sorted({intent for sample in family_samples for intent in sample.get("scope", {}).get("intent_ids", [])}),
            "tool_ids": sorted({tool for sample in family_samples for tool in sample.get("scope", {}).get("tool_ids", [])}),
            "difficulty": difficulty,
            "challenge_tags": challenges,
            "frozen_gold_sample_ids": [sample["sample_id"] for sample in family_samples],
            "target_candidate_count": target,
            "reused_pilot_candidate_ids": reused_by_family.get(family_id, []),
            "reused_pilot_count": len(reused_by_family.get(family_id, [])),
            "new_api_calls": new_count,
            "rationale": rationale,
            "calls": calls,
        })
    planned_calls = sum(len(family["calls"]) for family in family_plans)
    retry_allowance = (planned_calls + 9) // 10
    return {
        "plan_version": "0.1",
        "run_id": run_id,
        "created_at": _now(),
        "status": "planned",
        "pilot_source": str(pilot_path),
        "pilot_source_run_id": pilot_manifest["pilot_id"],
        "pilot_candidates_input": len(pilot_items),
        "pilot_candidates_reused_after_dedup": len(accepted_pilot),
        "pilot_candidates_excluded_after_dedup": pilot_exclusions,
        "business_family_count": len(family_plans),
        "excluded_family_ids": ["family_fin_002"],
        "family_plans": family_plans,
        "summary": {
            "family_count": len(family_plans),
            "target_candidate_count_including_pilot": sum(x["target_candidate_count"] for x in family_plans),
            "reused_pilot_count": len(accepted_pilot),
            "planned_new_calls": planned_calls,
            "attempt_ceiling": planned_calls + retry_allowance,
            "retry_allowance": retry_allowance,
            "attempt_ceiling_formula": "planned_new_calls + ceil(10% of planned_new_calls)",
            "fin_002_new_calls": 0,
        },
        "frozen_hashes": {
            "scenarios_sha256": assets["scenario_sha256"],
            "samples_sha256": assets["sample_sha256"],
            "matrix_sha256": assets["matrix_sha256"],
            **assets["contract_hashes"],
        },
    }


def write_generation_plan(plan: dict[str, Any], root: Path = ROOT) -> Path:
    run_dir = root / "scripts/ai_teacher_generator/runs/full-generation-v0.1" / plan["run_id"]
    run_dir.mkdir(parents=True, exist_ok=False)
    _write_json(run_dir / "generation_plan.json", plan)
    lines = [
        "# Teacher Full Generation v0.1 Plan",
        "",
        f"Run: `{plan['run_id']}`; Families: {plan['summary']['family_count']}; target pool: {plan['summary']['target_candidate_count_including_pilot']}; reused Pilot: {plan['summary']['reused_pilot_count']}; new calls: {plan['summary']['planned_new_calls']}; attempt ceiling: {plan['summary']['attempt_ceiling']}.",
        "",
        "Candidate counts are stratified by business complexity, challenge tags, source-surface count, and already reviewed Pilot coverage. FIN-002 is excluded.",
        "",
        "| Family | Task | Difficulty | Challenges | Frozen sources | Target | Pilot reused | New calls | Planned variant styles | Rationale |",
        "|---|---|---|---|---|---:|---:|---:|---|---|",
    ]
    for family in plan["family_plans"]:
        styles = ", ".join(call["style"] for call in family["calls"]) or "reuse only"
        lines.append(
            f"| {family['family_code']} | {family['task']} | {', '.join(family['difficulty'])} | "
            f"{', '.join(family['challenge_tags'])} | {', '.join(family['frozen_gold_sample_ids'])} | "
            f"{family['target_candidate_count']} | {family['reused_pilot_count']} | {family['new_api_calls']} | {styles} | {family['rationale']} |"
        )
    _write_json(run_dir / "batch_manifest.json", {
        "batch_manifest_version": "0.1",
        "run_id": plan["run_id"],
        "mode": "planned",
        "training_eligible": False,
        "planned_new_calls": plan["summary"]["planned_new_calls"],
        "attempt_ceiling": plan["summary"]["attempt_ceiling"],
        "completed_calls": 0,
        "calls": [],
    })
    (run_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    plan["run_dir"] = str(run_dir.relative_to(root))
    _write_json(run_dir / "generation_plan.json", plan)
    return run_dir


def load_full_plan(path: Path) -> dict[str, Any]:
    return _read_json(path)


def _record_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate_texts(samples: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    result = []
    for sample in samples:
        result.append((sample.get("sample_id", "unknown"), sample.get("scenario_family_id", ""), sample.get("surface_form", {}).get("user_message", "")))
    return result


def _duplicate_findings(candidate: dict[str, Any], references: list[dict[str, Any]]) -> dict[str, Any]:
    text = candidate.get("surface_form", {}).get("user_message", "")
    normalized = _surface_norm(text)
    exact, normalized_matches, semantic = [], [], []
    for sample_id, family_id, other_text in _candidate_texts(references):
        if not other_text:
            continue
        if text == other_text:
            exact.append(sample_id)
        elif normalized == _surface_norm(other_text):
            normalized_matches.append(sample_id)
        else:
            score = _sim(text, other_text)
            if score >= 0.90:
                semantic.append({"sample_id": sample_id, "family_id": family_id, "similarity": round(score, 4)})
    return {"exact_matches": exact, "normalized_matches": normalized_matches, "semantic_near_matches": semantic}


def run_full_generation(plan_path: Path, config: ProviderConfig, timeout: float = 75.0) -> dict[str, Any]:
    plan = load_full_plan(plan_path)
    root = ROOT
    run_dir = root / plan["run_dir"]
    assets = frozen_assets(root)
    actual_hashes = {
        "scenarios_sha256": assets["scenario_sha256"],
        "samples_sha256": assets["sample_sha256"],
        "matrix_sha256": assets["matrix_sha256"],
        **assets["contract_hashes"],
    }
    if actual_hashes != plan["frozen_hashes"]:
        raise GeneratorError("Frozen inputs changed since the Generation Plan was written.")
    plan_sha = _record_hash(plan_path)
    pilot_manifest, pilot_items = _pilot_review_inputs(root, Path(plan["pilot_source"]))
    reused_ids = {sample_id for family in plan["family_plans"] for sample_id in family["reused_pilot_candidate_ids"]}
    reused_items = [item for item in pilot_items if item["candidate"]["sample_id"] in reused_ids]
    for item in reused_items:
        _write_json(run_dir / "reused_pilot" / f"{item['candidate']['sample_id']}.json", item["candidate"])
    for exclusion in plan["pilot_candidates_excluded_after_dedup"]:
        match = next(item for item in pilot_items if item["candidate"]["sample_id"] == exclusion["candidate_id"])
        _write_json(run_dir / "rejected" / "pilot" / f"{exclusion['candidate_id']}.json", match["candidate"])
        _write_json(run_dir / "rejected" / "pilot" / f"{exclusion['candidate_id']}_audit.json", exclusion)

    batch_path = run_dir / "batch_manifest.json"
    batch = _read_json(batch_path)
    batch.update({
        "mode": "live_full_generation",
        "status": "running",
        "adapter_version": ADAPTER_VERSION,
        "provider": config.provider,
        "model": config.model,
        "base_url": config.base_url,
        "temperature": config.temperature,
        "prompt_version": "surface-variant-v1.0.0",
        "plan_sha256": plan_sha,
        "opencode_session_id": "opencode-session-" + plan["run_id"],
        "created_at": batch.get("created_at") or _now(),
        "started_at": _now(),
        "training_eligible": False,
        "formal_dataset_mutated": False,
        "retry_per_request_max": 1,
        "attempt_ceiling": plan["summary"]["attempt_ceiling"],
        "initial_http_attempts": 0,
        "reused_pilot_count": len(reused_items),
        "reused_pilot_run_id": pilot_manifest["pilot_id"],
        "frozen_hashes_before": actual_hashes,
    })
    batch["calls"] = []
    _write_json(batch_path, batch)
    scenario_by_id = {scenario["scenario_id"]: scenario for scenario in assets["scenarios"]}
    all_gold = [sample for sample in assets["samples"] if sample.get("trust", {}).get("level") == "GOLD"]
    pilot_pool = [item["candidate"] for item in reused_items]
    references = [*all_gold, *pilot_pool]
    batch_candidates: list[dict[str, Any]] = []
    call_lookups = {call["call_id"]: call for family in plan["family_plans"] for call in family["calls"]}
    total_attempts = 0
    http_success = 0
    usage_records: list[dict[str, Any]] = []
    all_new_candidates: list[dict[str, Any]] = []
    stopped_by_provider = False
    flattened_calls = [call for family in plan["family_plans"] for call in family["calls"]]
    for call_plan in flattened_calls:
        call_id = call_plan["call_id"]
        call_dir = run_dir / "calls" / call_id
        call_dir.mkdir(parents=True, exist_ok=False)
        record: dict[str, Any] = {
            **{key: call_plan[key] for key in ("call_id", "family_id", "family_code", "scenario_id", "source_sample_id", "split_group_id", "seed", "style", "difficulty", "variant_reason")},
            "status": "started",
            "attempts": [],
            "training_eligible": False,
            "started_at": _now(),
        }
        try:
            vp = create_plan(call_plan["family_id"], call_plan["seed"], root, call_plan["style"])
            if vp["gold_sample_id"] != call_plan["source_sample_id"]:
                raise GeneratorError("Plan source sample changed before request construction.")
            request = build_request(vp, run_id=f"{plan['run_id']}-{call_id}")
            request["provider_mode"] = "live_openai_compatible"
            request["request_id"] = f"{plan['run_id']}-{call_id}-request"
            request["local_trace"].update({
                "provider": config.provider,
                "model": config.model,
                "call_id": call_id,
                "plan_sha256": plan_sha,
                "opencode_session_id": batch["opencode_session_id"],
                "variant_reason": call_plan["variant_reason"],
            })
            _write_json(call_dir / "variant_plan.json", {key: call_plan[key] for key in call_plan})
            _write_json(call_dir / "request.json", request)
            record["request_id"] = request["request_id"]
            completion = None
            completion_usage: dict[str, Any] = {}
            for attempt_number in (1, 2):
                if total_attempts >= plan["summary"]["attempt_ceiling"]:
                    record["status"] = "attempt_ceiling_reached"
                    stopped_by_provider = True
                    break
                total_attempts += 1
                try:
                    response = request_completion(config, request, timeout=timeout)
                    http_success += 1
                    _write_json(call_dir / f"attempt-{attempt_number:02d}-response.json", {
                        "http_status": response["http_status"],
                        "duration_seconds": response["duration_seconds"],
                        "raw_response": response["raw_response"],
                        "headers_recorded": False,
                    })
                    completion, completion_usage = parse_completion(response["raw_response"])
                    usage_records.append(completion_usage)
                    record["attempts"].append({"attempt": attempt_number, "status": "response_received", "http_status": response["http_status"], "duration_seconds": response["duration_seconds"]})
                    break
                except LiveProviderError as error:
                    record["attempts"].append({"attempt": attempt_number, "status": "transient_error" if error.retryable else "failed", "error_kind": error.kind, "http_status": error.status})
                    _write_json(call_dir / f"attempt-{attempt_number:02d}-error.json", {"error_kind": error.kind, "http_status": error.status, "message": str(error)[:1000]})
                    if error.status in {401, 403}:
                        stopped_by_provider = True
                    if attempt_number == 1 and error.retryable and total_attempts < plan["summary"]["attempt_ceiling"]:
                        continue
                    break
            if completion is None:
                if record["status"] == "started":
                    record["status"] = "request_failed"
                record["completed_at"] = _now()
                _write_json(call_dir / "audit.json", record)
                batch["calls"].append({"call_id": call_id, "family_id": call_plan["family_id"], "status": record["status"], "attempts": record["attempts"], "audit": f"calls/{call_id}/audit.json"})
                batch["completed_calls"] = len(batch["calls"])
                _write_json(batch_path, batch)
                if stopped_by_provider:
                    break
                continue
            _write_json(call_dir / "parsed_response.json", completion)
            candidate = make_candidate(
                vp, request, completion, provider=config.provider, model=config.model,
                temperature=config.temperature, generated_at=_now(),
            )
            # Keep every structurally formed response, even when a later screen rejects it.
            _write_json(call_dir / "candidate_sample.json", candidate)
            all_new_candidates.append(candidate)
            findings = _duplicate_findings(candidate, references + all_new_candidates[:-1])
            record["candidate_id"] = candidate["sample_id"]
            record["duplicate_screen"] = findings
            record["ground_truth_drift"] = candidate["expected"] != vp["seed_sample"]["expected"]
            record["usage"] = completion_usage
            try:
                validation = validate_candidate(candidate, vp["scenario"], root)
                record["machine_validation"] = validation
            except GeneratorError as error:
                record["machine_validation"] = {"valid": False, "error": str(error)[:1000]}
                validation = {"valid": False}
            if record["ground_truth_drift"]:
                record["status"] = "ground_truth_reject"
            elif findings["exact_matches"] or findings["normalized_matches"]:
                record["status"] = "duplicate_reject"
            elif not validation["valid"]:
                record["status"] = "validator_reject"
            else:
                record["status"] = "machine_pass"
                batch_candidates.append(candidate)
            record["semantic_near_duplicate_review_required"] = bool(findings["semantic_near_matches"])
        except (GeneratorError, OSError, ValueError, KeyError, TypeError) as error:
            record["status"] = "candidate_or_plan_reject"
            record["error_kind"] = "candidate_or_plan"
            record["error_message"] = str(error)[:1000]
        record["completed_at"] = _now()
        _write_json(call_dir / "audit.json", record)
        batch["calls"].append({
            "call_id": call_id,
            "family_id": call_plan["family_id"],
            "status": record["status"],
            "attempts": record["attempts"],
            "candidate_id": record.get("candidate_id"),
            "audit": f"calls/{call_id}/audit.json",
        })
        batch["completed_calls"] = len(batch["calls"])
        batch["http_attempts"] = total_attempts
        _write_json(batch_path, batch)
        if stopped_by_provider:
            break
    # Re-read only successful per-call candidates for deterministic artifacts.
    passed_candidates = []
    for item in batch["calls"]:
        if item.get("status") == "machine_pass":
            passed_candidates.append(_read_json(run_dir / "calls" / item["call_id"] / "candidate_sample.json"))
    _write_json(run_dir / "machine_pass_candidates.json", passed_candidates)
    _write_json(run_dir / "candidate_pool_pre_review.json", [*pilot_pool, *passed_candidates])
    after = frozen_assets(root)
    counts = Counter(item.get("status") for item in batch["calls"])
    numeric = lambda key: sum(x.get(key) or 0 for x in usage_records if isinstance(x.get(key), (int, float)))
    costs = [x.get("provider_cost") for x in usage_records if x.get("provider_cost") is not None]
    batch.update({
        "completed_at": _now(),
        "status": "provider_blocked" if stopped_by_provider else ("machine_screened" if len(batch["calls"]) == plan["summary"]["planned_new_calls"] else "incomplete"),
        "http_attempts": total_attempts,
        "http_success_responses": http_success,
        "candidate_status_counts": dict(counts),
        "candidate_count_pilot_reused": len(pilot_pool),
        "candidate_count_machine_pass": len(passed_candidates),
        "candidate_count_pre_review_pool": len(pilot_pool) + len(passed_candidates),
        "usage": {
            "prompt_tokens": numeric("prompt_tokens"),
            "completion_tokens": numeric("completion_tokens"),
            "total_tokens": numeric("total_tokens"),
            "provider_cost": sum(costs) if costs else None,
            "provider_cost_reported_calls": len(costs),
        },
        "frozen_hashes_after": {"scenarios_sha256": after["scenario_sha256"], "samples_sha256": after["sample_sha256"]},
        "frozen_hashes_unchanged": actual_hashes["scenarios_sha256"] == after["scenario_sha256"] and actual_hashes["samples_sha256"] == after["sample_sha256"],
        "reused_pilot_source_run_id": pilot_manifest["pilot_id"],
        "reused_pilot_count": len(pilot_pool),
        "rejected_pilot_count": len(plan["pilot_candidates_excluded_after_dedup"]),
        "training_eligible": False,
    })
    _write_json(batch_path, batch)
    return batch
