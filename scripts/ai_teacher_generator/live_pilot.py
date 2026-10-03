"""Small, auditable live Teacher pilot. Never modifies frozen Gold Seed artifacts."""
from __future__ import annotations

import copy
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.ai_teacher_generator.generator import (  # noqa: E402
    GeneratorError,
    _json_bytes,
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


FAMILY_STYLES: dict[str, tuple[str, str, str]] = {
    "family_exp_create_001": ("colloquial", "typo_asr_like", "pronoun_ellipsis"),
    "family_exp_clarify_001": ("colloquial", "typo_asr_like", "pronoun_ellipsis"),
    "family_exp_read_001": ("colloquial", "typo_asr_like", "pronoun_ellipsis"),
    "family_exp_read_002": ("colloquial", "typo_asr_like", "pronoun_ellipsis"),
    "family_exp_edit_003": ("colloquial", "typo_asr_like", "pronoun_ellipsis"),
    "family_ictx_001": ("colloquial", "typo_asr_like", "pronoun_ellipsis"),
    "family_conv_006": ("multi_turn", "colloquial", "pronoun_ellipsis"),
    "family_ui_001": ("colloquial", "typo_asr_like", "pronoun_ellipsis"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _find_plan(family: str, style: str, pilot_id: str, index: int) -> dict[str, Any]:
    for seed in range(index * 2, index * 2 + 16):
        try:
            plan = create_plan(family, seed, ROOT, style)
        except GeneratorError:
            continue
        plan = copy.deepcopy(plan)
        plan["live_run_id"] = pilot_id
        return plan
    raise GeneratorError(f"No frozen source sample supports the planned style for {family}.")


def run_live_pilot(
    config: ProviderConfig,
    output_root: Path,
    timeout: float = 60.0,
    *,
    initial_http_attempts: int = 0,
    linked_previous_pilot_id: str | None = None,
    linked_probe_id: str | None = None,
) -> dict[str, Any]:
    before = frozen_assets(ROOT)
    if initial_http_attempts < 0 or initial_http_attempts >= 32:
        raise GeneratorError("Invalid initial HTTP attempt count for the 32-attempt pilot ceiling.")
    pilot_id = "pilot-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    pilot_dir = output_root / pilot_id
    pilot_dir.mkdir(parents=True, exist_ok=False)
    manifest: dict[str, Any] = {
        "pilot_manifest_version": "0.1",
        "pilot_id": pilot_id,
        "linked_previous_pilot_id": linked_previous_pilot_id,
        "linked_probe_id": linked_probe_id,
        "initial_http_attempts": initial_http_attempts,
        "authorized_total_http_attempt_ceiling": 32,
        "adapter_version": ADAPTER_VERSION,
        "opencode_session_id": "opencode-session-" + pilot_id,
        "mode": "live_pilot",
        "provider": config.provider,
        "model": config.model,
        "base_url": config.base_url,
        "temperature": config.temperature,
        "created_at": _now(),
        "generator_version": "0.1.0",
        "prompt_version": "surface-variant-v1.0.0",
        "training_eligible": False,
        "formal_dataset_mutated": False,
        "max_requests": 32,
        "max_retries_per_request": 1,
        "frozen_hashes_before": {
            "scenarios_sha256": before["scenario_sha256"],
            "samples_sha256": before["sample_sha256"],
        },
        "planned_families": [
            {"family_id": family, "planned_variants": list(styles)}
            for family, styles in FAMILY_STYLES.items()
        ],
        "calls": [],
    }
    _write_json(pilot_dir / "pilot_manifest.json", manifest)
    call_number = 0
    total_http_attempts = initial_http_attempts
    call_limit_hit = False
    for family, styles in FAMILY_STYLES.items():
        for style_index, style in enumerate(styles):
            call_number += 1
            if call_number > 32:
                raise GeneratorError("Pilot call limit exceeded.")
            call_id = f"call-{call_number:03d}"
            call_dir = pilot_dir / call_id
            call_dir.mkdir()
            record: dict[str, Any] = {
                "call_id": call_id,
                "family_id": family,
                "variant_style": style,
                "status": "started",
                "attempts": [],
                "training_eligible": False,
                "started_at": _now(),
            }
            try:
                plan = _find_plan(family, style, pilot_id, style_index)
                request_id = f"{pilot_id}-{call_id}"
                request = build_request(plan, run_id=pilot_id + "-" + call_id)
                request["provider_mode"] = "live_openai_compatible"
                request["request_id"] = request_id
                request["local_trace"]["provider"] = config.provider
                request["local_trace"]["model"] = config.model
                request["local_trace"]["call_id"] = call_id
                request["local_trace"]["opencode_session_id"] = manifest["opencode_session_id"]
                _write_json(call_dir / "request.json", request)
                record.update({
                    "request_id": request_id,
                    "source_sample_id": request["local_trace"]["gold_sample_id"],
                    "scenario_id": request["local_trace"]["scenario_id"],
                    "split_group_id": request["local_trace"]["split_group_id"],
                })
                completion = None
                usage: dict[str, Any] = {}
                for attempt_number in (1, 2):
                    attempt_id = f"attempt-{attempt_number:02d}"
                    if total_http_attempts >= 32:
                        record["status"] = "skipped_total_call_limit"
                        record["completed_at"] = _now()
                        _write_json(call_dir / "audit.json", record)
                        manifest["calls"].append(record)
                        _write_json(pilot_dir / "pilot_manifest.json", manifest)
                        call_limit_hit = True
                        break
                    total_http_attempts += 1
                    try:
                        response = request_completion(config, request, timeout=timeout)
                        _write_json(call_dir / f"{attempt_id}_response.json", {
                            "http_status": response["http_status"],
                            "duration_seconds": response["duration_seconds"],
                            "raw_response": response["raw_response"],
                            "headers_recorded": False,
                        })
                        completion, usage = parse_completion(response["raw_response"])
                        record["attempts"].append({"attempt": attempt_number, "status": "response_received", "http_status": response["http_status"], "duration_seconds": response["duration_seconds"]})
                        break
                    except LiveProviderError as error:
                        status = "transient_error" if error.retryable else "failed"
                        record["attempts"].append({"attempt": attempt_number, "status": status, "error_kind": error.kind, "http_status": error.status})
                        _write_json(call_dir / f"{attempt_id}_error.json", {
                            "error_kind": error.kind,
                            "http_status": error.status,
                            "message": str(error)[:1000],
                        })
                        if attempt_number == 1 and error.retryable:
                            continue
                        break
                if completion is None:
                    if call_limit_hit:
                        break
                    record["status"] = "request_failed"
                    record["completed_at"] = _now()
                    _write_json(call_dir / "audit.json", record)
                    manifest["calls"].append(record)
                    _write_json(pilot_dir / "pilot_manifest.json", manifest)
                    continue
                _write_json(call_dir / "parsed_response.json", completion)
                try:
                    candidate = make_candidate(
                        plan, request, completion, provider=config.provider, model=config.model,
                        temperature=config.temperature, generated_at=_now(),
                    )
                    _write_json(call_dir / "candidate_sample.json", candidate)
                    validation = validate_candidate(candidate, plan["scenario"], ROOT)
                    record["candidate_id"] = candidate["sample_id"]
                    record["machine_validation"] = validation
                    record["status"] = "machine_pass" if validation["valid"] else "machine_reject"
                    record["surface_form"] = candidate["surface_form"]
                    record["ground_truth_drift"] = candidate["expected"] != plan["seed_sample"]["expected"]
                except (GeneratorError, ValueError, KeyError, TypeError) as error:
                    record["status"] = "candidate_rejected"
                    record["error_kind"] = "candidate_validation"
                    record["error_message"] = str(error)[:1000]
                record["usage"] = usage
            except (GeneratorError, OSError, ValueError, KeyError) as error:
                record["status"] = "setup_failed"
                record["error_kind"] = "setup"
                record["error_message"] = str(error)[:1000]
            record["completed_at"] = _now()
            _write_json(call_dir / "audit.json", record)
            manifest["calls"].append(record)
            _write_json(pilot_dir / "pilot_manifest.json", manifest)
        if call_limit_hit:
            break
    after = frozen_assets(ROOT)
    manifest["completed_at"] = _now()
    manifest["status"] = (
        "provider_blocked"
        if not any(call.get("status") in {"machine_pass", "machine_reject", "candidate_rejected"} for call in manifest["calls"])
        else "awaiting_human_review"
    )
    manifest["frozen_hashes_after"] = {
        "scenarios_sha256": after["scenario_sha256"],
        "samples_sha256": after["sample_sha256"],
    }
    manifest["frozen_hashes_unchanged"] = (
        before["scenario_sha256"] == after["scenario_sha256"]
        and before["sample_sha256"] == after["sample_sha256"]
    )
    manifest["summary"] = summarize(manifest["calls"])
    manifest["summary"]["cumulative_http_attempts_including_probe"] = total_http_attempts
    manifest["summary"]["total_http_attempt_ceiling"] = 32
    _write_json(pilot_dir / "pilot_manifest.json", manifest)
    return manifest


def summarize(calls: list[dict[str, Any]]) -> dict[str, Any]:
    def count(predicate) -> int:
        return sum(1 for call in calls if predicate(call))
    successful = count(lambda c: c.get("status") in {"machine_pass", "machine_reject"})
    usage_records = [c.get("usage", {}) for c in calls]
    numeric = lambda key: sum(x.get(key) or 0 for x in usage_records if isinstance(x.get(key), (int, float)))
    costs = [x.get("provider_cost") for x in usage_records if x.get("provider_cost") is not None]
    return {
        "planned_requests": len(calls),
        "http_attempts": sum(len(c.get("attempts", [])) for c in calls),
        "http_completion_success": count(lambda c: any(a.get("status") == "response_received" for a in c.get("attempts", []))),
        "parse_or_candidate_failures": count(lambda c: c.get("status") in {"request_failed", "candidate_rejected", "setup_failed"}),
        "machine_pass": count(lambda c: c.get("status") == "machine_pass"),
        "machine_reject": count(lambda c: c.get("status") == "machine_reject"),
        "ground_truth_drift": count(lambda c: c.get("ground_truth_drift") is True),
        "prompt_tokens": numeric("prompt_tokens"),
        "completion_tokens": numeric("completion_tokens"),
        "total_tokens": numeric("total_tokens"),
        "provider_cost": sum(costs) if costs else None,
        "provider_cost_reported_calls": len(costs),
        "successful_calls_per_machine_pass": round(successful / max(1, count(lambda c: c.get("status") == "machine_pass")), 3),
    }


def run_adapter_fix_verification(config: ProviderConfig, pilot_dir: Path, original_manifest: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
    """One new, non-retried request per Family; stop immediately on 403."""
    prior_attempts = int(original_manifest.get("summary", {}).get("http_attempts", 0))
    if prior_attempts > 24 or prior_attempts + len(FAMILY_STYLES) > 32:
        raise GeneratorError("Adapter verification would exceed the authorized 32-call ceiling.")
    verify_dir = pilot_dir / "adapter-fix-verification"
    verify_dir.mkdir(parents=True, exist_ok=False)
    verify_id = "verify-" + uuid.uuid4().hex[:8]
    manifest: dict[str, Any] = {
        "verification_manifest_version": "0.1",
        "verification_id": verify_id,
        "linked_pilot_id": original_manifest["pilot_id"],
        "mode": "adapter_fix_verification",
        "adapter_version": ADAPTER_VERSION,
        "prompt_version": "surface-variant-v1.0.0",
        "attempt_reason": "Correct OpenCode Go chat-completions endpoint path after the initial 403 response.",
        "provider": config.provider,
        "model": config.model,
        "base_url": config.base_url,
        "temperature": config.temperature,
        "created_at": _now(),
        "max_new_requests": 8,
        "retry_per_request": 0,
        "prior_http_attempts": prior_attempts,
        "authorized_total_ceiling": 32,
        "training_eligible": False,
        "calls": [],
    }
    _write_json(verify_dir / "verification_manifest.json", manifest)
    for index, (family, styles) in enumerate(FAMILY_STYLES.items(), start=1):
        call_id = f"verify-call-{index:02d}"
        call_dir = verify_dir / call_id
        call_dir.mkdir()
        record: dict[str, Any] = {"call_id": call_id, "family_id": family, "variant_style": styles[0], "attempts": [], "training_eligible": False}
        try:
            plan = _find_plan(family, styles[0], original_manifest["pilot_id"] + "-" + verify_id, 0)
            request = build_request(plan, run_id=original_manifest["pilot_id"] + "-" + verify_id + "-" + call_id)
            request["provider_mode"] = "live_openai_compatible"
            request["request_id"] = verify_id + "-" + call_id
            request["local_trace"].update({"provider": config.provider, "model": config.model, "call_id": call_id, "adapter_version": ADAPTER_VERSION})
            request["local_trace"]["opencode_session_id"] = "opencode-session-" + original_manifest["pilot_id"] + "-" + verify_id
            _write_json(call_dir / "request.json", request)
            record.update({"request_id": request["request_id"], "source_sample_id": request["local_trace"]["gold_sample_id"], "scenario_id": request["local_trace"]["scenario_id"], "split_group_id": request["local_trace"]["split_group_id"]})
            response = request_completion(config, request, timeout=timeout)
            _write_json(call_dir / "response.json", {"http_status": response["http_status"], "duration_seconds": response["duration_seconds"], "raw_response": response["raw_response"], "headers_recorded": False})
            record["attempts"].append({"attempt": 1, "status": "response_received", "http_status": response["http_status"], "duration_seconds": response["duration_seconds"]})
            parsed, usage = parse_completion(response["raw_response"])
            _write_json(call_dir / "parsed_response.json", parsed)
            candidate = make_candidate(plan, request, parsed, provider=config.provider, model=config.model, temperature=config.temperature, generated_at=_now())
            _write_json(call_dir / "candidate_sample.json", candidate)
            record["machine_validation"] = validate_candidate(candidate, plan["scenario"], ROOT)
            record["candidate_id"] = candidate["sample_id"]
            record["surface_form"] = candidate["surface_form"]
            record["ground_truth_drift"] = candidate["expected"] != plan["seed_sample"]["expected"]
            record["usage"] = usage
            record["status"] = "machine_pass" if record["machine_validation"]["valid"] else "machine_reject"
        except LiveProviderError as error:
            record["status"] = "request_failed"
            record["error_kind"] = error.kind
            record["http_status"] = error.status
            record["retryable"] = error.retryable
            record["attempts"].append({"attempt": 1, "status": "failed", "error_kind": error.kind, "http_status": error.status})
            _write_json(call_dir / "error.json", {"error_kind": error.kind, "http_status": error.status, "message": str(error)[:1000]})
            if error.status == 403:
                record["stop_reason"] = "Provider returned HTTP 403; verification halted immediately by instruction."
        except (GeneratorError, OSError, ValueError, KeyError, TypeError) as error:
            record["status"] = "candidate_or_setup_failed"
            record["error_message"] = str(error)[:1000]
            _write_json(call_dir / "error.json", {"error_kind": "candidate_or_setup", "message": str(error)[:1000]})
        record["completed_at"] = _now()
        _write_json(call_dir / "audit.json", record)
        manifest["calls"].append(record)
        _write_json(verify_dir / "verification_manifest.json", manifest)
        if record.get("http_status") == 403:
            break
    manifest["status"] = "provider_blocked" if any(x.get("http_status") == 403 for x in manifest["calls"]) else "verification_complete"
    manifest["completed_at"] = _now()
    manifest["summary"] = summarize(manifest["calls"])
    _write_json(verify_dir / "verification_manifest.json", manifest)
    original_manifest["adapter_fix_verification"] = {
        "manifest_path": "adapter-fix-verification/verification_manifest.json",
        "verification_id": verify_id,
        "status": manifest["status"],
        "new_http_attempts": manifest["summary"]["http_attempts"],
        "cumulative_http_attempts": prior_attempts + manifest["summary"]["http_attempts"],
        "authorized_total_ceiling": 32,
    }
    original_manifest["summary"]["http_attempts"] = prior_attempts + manifest["summary"]["http_attempts"]
    original_manifest["summary"]["adapter_fix_verification_successes"] = manifest["summary"]["http_completion_success"]
    _write_json(pilot_dir / "pilot_manifest.json", original_manifest)
    return manifest


def run_connectivity_probe(config: ProviderConfig, output_root: Path, timeout: float = 60.0) -> dict[str, Any]:
    """Single, no-retry request to verify provider connectivity and response shape."""
    before = frozen_assets(ROOT)
    probe_id = "probe-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    probe_dir = output_root / "connectivity-probes" / probe_id
    probe_dir.mkdir(parents=True, exist_ok=False)
    session_id = "opencode-session-" + probe_id
    plan = _find_plan("family_exp_create_001", "colloquial", probe_id, 0)
    request = build_request(plan, run_id=probe_id)
    request["provider_mode"] = "live_openai_compatible"
    request["request_id"] = probe_id + "-request"
    request["local_trace"].update({"provider": config.provider, "model": config.model, "adapter_version": ADAPTER_VERSION, "opencode_session_id": session_id})
    _write_json(probe_dir / "request.json", request)
    manifest: dict[str, Any] = {
        "probe_manifest_version": "0.1",
        "probe_id": probe_id,
        "mode": "connectivity_probe",
        "provider": config.provider,
        "model": config.model,
        "base_url": config.base_url,
        "adapter_version": ADAPTER_VERSION,
        "prompt_version": "surface-variant-v1.0.0",
        "opencode_session_id": session_id,
        "retry_per_request": 0,
        "training_eligible": False,
        "headers_recorded": False,
        "request_id": request["request_id"],
        "family_id": "family_exp_create_001",
        "frozen_hashes_before": {"scenarios_sha256": before["scenario_sha256"], "samples_sha256": before["sample_sha256"]},
        "started_at": _now(),
    }
    status = "probe_failed"
    try:
        response = request_completion(config, request, timeout=timeout)
        _write_json(probe_dir / "response.json", {"http_status": response["http_status"], "duration_seconds": response["duration_seconds"], "raw_response": response["raw_response"], "headers_recorded": False})
        parsed, usage = parse_completion(response["raw_response"])
        from scripts.ai_teacher_generator.generator import parse_response
        surface = parse_response(parsed, plan["seed_sample"])
        _write_json(probe_dir / "parsed_surface_form.json", surface)
        manifest.update({"http_status": response["http_status"], "duration_seconds": response["duration_seconds"], "usage": usage, "response_schema_valid": True})
        status = "probe_passed"
    except LiveProviderError as error:
        manifest.update({"error_kind": error.kind, "http_status": error.status, "retryable": error.retryable})
        _write_json(probe_dir / "error.json", {"error_kind": error.kind, "http_status": error.status, "message": str(error)[:1000], "headers_recorded": False})
    except (GeneratorError, OSError, ValueError, KeyError, TypeError) as error:
        manifest.update({"error_kind": "response_or_setup", "message": str(error)[:1000]})
        _write_json(probe_dir / "error.json", {"error_kind": "response_or_setup", "message": str(error)[:1000], "headers_recorded": False})
    after = frozen_assets(ROOT)
    manifest.update({
        "status": status,
        "completed_at": _now(),
        "frozen_hashes_after": {"scenarios_sha256": after["scenario_sha256"], "samples_sha256": after["sample_sha256"]},
        "frozen_hashes_unchanged": before["scenario_sha256"] == after["scenario_sha256"] and before["sample_sha256"] == after["sample_sha256"],
        "http_attempts": 1,
    })
    _write_json(probe_dir / "probe_manifest.json", manifest)
    return manifest
