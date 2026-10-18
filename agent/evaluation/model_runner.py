"""Gated T1 evaluator: LM Studio candidate + P1 parser + synthetic replay only.

The runner never starts a server, loads/unloads a model, calls a business API,
or performs a write. A read result is injected from the frozen synthetic trace.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import statistics
import time
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path
from typing import Any

from agent.app import contracts as c
from agent.app.harness import ModelOutputError, ModelPrompt, parse_model_output
from agent.evaluation.data_validate import make_envelope_validator, validate_record
from agent.evaluation.model_lmstudio import (
    LMStudioError,
    LMStudioV1Provider,
    check_resource_floor,
    resource_snapshot,
)
from agent.evaluation.model_scoring import score_semantic, summarize_boolean


CONFIG_PATH = Path(__file__).with_name("model_runtime_config.json")
_ENVELOPE_VALIDATOR = make_envelope_validator(Path(__file__).resolve().parents[1])
REPAIR_FEEDBACK = "Return one valid closed semantic decision using only listed references."
ENABLED_OPERATIONS = {
    "read.activities", "read.expenses", "read.debts",
    "expense.create", "expense.update", "expense.presentation.update",
}
BOUNDARY_CASES = {
    "locked_financial_update", "ordinary_prepayment", "permission_denial", "prompt_injection",
}
_DIRECT_WRITE_CLAIM = re.compile(r"(?:已|已经|成功地?)(?:写入|保存|记账|新增|创建|更新|修改)|\b(?:written|saved|committed|executed)\b", re.I)


class EvaluationPreflightError(RuntimeError):
    """A frozen-input, split, resource, or provider gate failed closed."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tracked_preregistration_files(repo_root: Path) -> dict[str, str]:
    """Hash the fixed implementation, prompt, criteria, and protocol source set."""
    relative_paths = [
        "agent/evaluation/model_lmstudio.py",
        "agent/evaluation/model_scoring.py",
        "agent/evaluation/model_runner.py",
        "agent/evaluation/data_validate.py",
        "agent/evaluation/data_signature.py",
        "agent/evaluation/data_simulator.py",
        "agent/evaluation/data_generate.py",
        "agent/evaluation/model_prompt.md",
        "agent/evaluation/model_runtime_config.json",
        "agent/evaluation/tests/test_model_evaluation.py",
        "agent/dataset_contracts/t1/dataset-envelope.schema.json",
        "agent/dataset_contracts/t1/protocol-fingerprint.json",
        "agent/dataset_contracts/t1/cap-coverage-requirements.json",
        "agent/app/harness.py",
        "agent/app/contracts.py",
        "agent/docs/t1/ACCEPTANCE_CRITERIA-T1-v1.json",
        "agent/contracts/v1.0.0/manifest.json",
    ]
    relative_paths.extend(
        path.relative_to(repo_root).as_posix()
        for path in sorted((repo_root / "agent/contracts/v1.0.0/schemas").glob("*.json"))
    )
    result: dict[str, str] = {}
    for relative in relative_paths:
        file_path = repo_root / relative
        if not file_path.is_file():
            raise EvaluationPreflightError(f"preregistration source file is missing: {relative}")
        result[relative] = _sha256_bytes(file_path.read_bytes())
    return result


def _validate_model_preregistration(config: dict[str, Any], provider: LMStudioV1Provider, config_path: Path) -> dict[str, Any]:
    prereg_path = Path(config["model_prereg_path"])
    try:
        prereg_bytes = prereg_path.read_bytes()
        prereg = json.loads(prereg_bytes)
    except (OSError, json.JSONDecodeError) as error:
        raise EvaluationPreflightError("model preregistration is missing or invalid") from error
    if prereg.get("status") != "FROZEN_BEFORE_MODEL_OUTPUTS":
        raise EvaluationPreflightError("model preregistration is not frozen before outputs")
    repo_root = Path(__file__).resolve().parents[2]
    actual_files = tracked_preregistration_files(repo_root)
    if prereg.get("source_files_sha256") != actual_files:
        raise EvaluationPreflightError("evaluation source, prompt, config, criteria, or contract hash changed after preregistration")
    if prereg.get("effective_system_prompt_sha256") != provider.system_prompt_sha256:
        raise EvaluationPreflightError("effective system prompt hash differs from preregistration")
    if prereg.get("semantic_schema_sha256") != provider.semantic_schema_sha256:
        raise EvaluationPreflightError("runtime P1 semantic schema hash differs from preregistration")
    if prereg.get("runtime_config_sha256") != _sha256_bytes(config_path.read_bytes()):
        raise EvaluationPreflightError("runtime config hash differs from preregistration")
    candidate = prereg.get("candidate", {})
    model = config["model"]
    expected_candidate = {
        "model_key": model["model_key"],
        "artifact_sha256": model["artifact_sha256"],
        "artifact_size_bytes": model["artifact_size_bytes"],
        "quantization": model["quantization"],
        "artifact_lineage_status": model["artifact_lineage_status"],
    }
    if any(candidate.get(key) != value for key, value in expected_candidate.items()):
        raise EvaluationPreflightError("candidate identity differs from preregistration")
    return {"document": prereg, "sha256": _sha256_bytes(prereg_bytes)}


def _validate_freeze_approval(config: dict[str, Any], prereg: dict[str, Any], split: str) -> dict[str, Any]:
    manifest_path = Path(config["freeze_manifest_path"])
    approval_path = Path(config["root_freeze_approval_path"])
    try:
        manifest_bytes = manifest_path.read_bytes()
        approval_bytes = approval_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        approval = json.loads(approval_bytes)
    except (OSError, json.JSONDecodeError) as error:
        raise EvaluationPreflightError("frozen manifest or independent root approval is missing/invalid") from error
    manifest_sha = _sha256_bytes(manifest_bytes)
    approval_sha = _sha256_bytes(approval_bytes)
    if (
        manifest.get("status") != "FROZEN"
        or manifest.get("freeze_status") != "PREPARED_FOR_INDEPENDENT_ROOT_REVIEW"
        or manifest.get("root_freeze_approval") != "pending"
    ):
        raise EvaluationPreflightError("freeze manifest is not the immutable prepared-for-review version")
    if (
        approval.get("status") != "APPROVED_DIAGNOSTIC_FREEZE"
        or approval.get("manifest_sha256") != manifest_sha
    ):
        raise EvaluationPreflightError("root approval is absent or not bound to the exact freeze manifest")
    manifest_hashes = manifest.get("hashes")
    manifest_fingerprint = manifest_hashes.get("protocol_fingerprint_sha256") if isinstance(manifest_hashes, dict) else None
    if approval.get("protocol_fingerprint_sha256") != manifest_fingerprint:
        raise EvaluationPreflightError("root approval and freeze manifest fingerprints differ")
    reviewed_splits = approval.get("reviewed_splits")
    if not isinstance(reviewed_splits, list) or not {"validation", "sealed"}.issubset(set(reviewed_splits)):
        raise EvaluationPreflightError("root approval must review both validation and sealed manifests")
    if (
        approval.get("scope") != "diagnostic_only"
        or approval.get("training_eligible") is not False
        or approval.get("human_review_pending") is not True
    ):
        raise EvaluationPreflightError("root approval scope or human-review status is invalid")
    if manifest_fingerprint != config.get("protocol_fingerprint_sha256"):
        raise EvaluationPreflightError("runtime config and approved freeze fingerprints differ")
    bundles = manifest.get("bundles", {})
    bundle = bundles.get(split, {}) if isinstance(bundles, dict) else {}
    bundle_sha = bundle.get("sha256") if isinstance(bundle, dict) else None
    expected_bundle_path = Path(r"D:\AI\runs\shared-ledger\t1\data") / f"{split}.jsonl"
    if not isinstance(bundle, dict) or Path(bundle.get("path", "")).resolve() != expected_bundle_path.resolve():
        raise EvaluationPreflightError("freeze manifest does not bind the canonical selected split path")
    prereg_data = prereg.get("data_freeze", {})
    config_data = config.get("data_freeze", {})
    if not isinstance(config_data, dict):
        raise EvaluationPreflightError("runtime config has no approved data hash bindings")
    if (
        config_data.get("manifest_sha256") != manifest_sha
        or config_data.get("root_approval_sha256") != approval_sha
        or config_data.get("protocol_fingerprint_sha256") != manifest_fingerprint
    ):
        raise EvaluationPreflightError("runtime config hashes differ from the approved freeze")
    if not isinstance(bundle_sha, str) or not isinstance(prereg_data, dict) or prereg_data.get("manifest_sha256") != manifest_sha:
        raise EvaluationPreflightError("freeze manifest hash is not bound in the model preregistration")
    if prereg_data.get("protocol_fingerprint_sha256") != manifest_fingerprint:
        raise EvaluationPreflightError("protocol fingerprint is not bound in the model preregistration")
    if prereg_data.get("root_approval_sha256") != approval_sha:
        raise EvaluationPreflightError("root approval hash is not bound in the model preregistration")
    prereg_bundles = prereg_data.get("bundle_sha256")
    manifest_bundles = manifest.get("bundles", {})
    if not isinstance(prereg_bundles, dict) or not isinstance(manifest_bundles, dict):
        raise EvaluationPreflightError("freeze bundle hashes are not bound in the model preregistration")
    config_bundles = config_data.get("bundle_sha256")
    if not isinstance(config_bundles, dict):
        raise EvaluationPreflightError("runtime config has no validation/sealed bundle hash bindings")
    for frozen_split in ("validation", "sealed"):
        frozen_bundle = manifest_bundles.get(frozen_split)
        if not isinstance(frozen_bundle, dict) or prereg_bundles.get(frozen_split) != frozen_bundle.get("sha256"):
            raise EvaluationPreflightError("validation and sealed bundle hashes must both be bound in the model preregistration")
        if config_bundles.get(frozen_split) != frozen_bundle.get("sha256"):
            raise EvaluationPreflightError("validation and sealed bundle hashes must both be bound in the runtime config")
    return {
        "manifest": manifest,
        "manifest_sha256": manifest_sha,
        "approval": approval,
        "approval_sha256": approval_sha,
        "bundle_sha256": bundle_sha,
    }


def _create_sealed_consumption_ledger(path: Path, *, bundle_sha256: str, prereg_sha256: str, approval_sha256: str) -> dict[str, Any]:
    """Atomically consume the sealed bundle before opening its JSONL bytes."""
    record = {
        "ledger_version": "t1-sealed-consumption-v1",
        "status": "CONSUMED_AT_START",
        "sealed_bundle_sha256": bundle_sha256,
        "model_preregistration_sha256": prereg_sha256,
        "root_approval_sha256": approval_sha256,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "note": "Consumption is permanent even if file validation or evaluation later fails.",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise EvaluationPreflightError("sealed consumption ledger already exists; one-shot bundle is consumed") from error
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return record


def _read_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "model", "runtime", "resource_thresholds", "protocol_fingerprint_sha256", "status",
        "freeze_manifest_path", "root_freeze_approval_path", "acceptance_thresholds", "data_freeze",
    }
    if not isinstance(config, dict) or not required <= config.keys():
        raise EvaluationPreflightError("runtime config is incomplete")
    if config["status"] not in {"FROZEN_FOR_REVIEW_NOT_RUN", "FROZEN_ROOT_APPROVED"}:
        raise EvaluationPreflightError("runtime config status is not frozen")
    model = config["model"]
    runtime = config["runtime"]
    if (
        runtime.get("evaluation_mode") != "teacher_forced_stepwise_semantic_diagnostic"
        or runtime.get("max_concurrency") != 1
        or runtime.get("repair_attempts") != 1
        or not isinstance(runtime.get("sealed_one_shot_authorized"), bool)
        or model.get("context_length", 0) < 8192
        or model.get("max_output_tokens", 0) < 768
        or model.get("temperature") != 0.0
        or model.get("reasoning") != "off"
        or model.get("parallel") != 1
        or model.get("store") is not False
        or model.get("stream") is not False
    ):
        raise EvaluationPreflightError("runtime configuration differs from the preregistered diagnostic mode")
    return config


def _must_be_split_file(path: Path, split: str, allow_sealed: bool) -> None:
    if split not in {"validation", "sealed"}:
        raise EvaluationPreflightError("only validation or sealed evaluation is supported")
    if path.name.lower() != f"{split}.jsonl":
        raise EvaluationPreflightError("input filename must identify exactly the selected split")
    normalized = os.path.normcase(os.path.abspath(path))
    expected_root = os.path.normcase(os.path.abspath(r"D:\AI\runs\shared-ledger\t1\data"))
    if os.path.commonpath([normalized, expected_root]) != expected_root:
        raise EvaluationPreflightError("T1 data input must be under the D-only frozen data directory")
    if split == "sealed" and not allow_sealed:
        raise EvaluationPreflightError("sealed split is closed until a one-shot root approval is supplied")


def _validate_envelope(sample: Any, split: str, expected_fingerprint: str) -> list[dict[str, Any]]:
    if not isinstance(sample, dict):
        raise EvaluationPreflightError("envelope row must be an object")
    if sample.get("schema_version") != "shared-ledger-agent-t1-sample-v1":
        raise EvaluationPreflightError("unsupported envelope schema version")
    if sample.get("split") != split:
        raise EvaluationPreflightError("split file contains a row from another split")
    if sample.get("data_origin") != "synthetic" or sample.get("replay_status") != "simulated":
        raise EvaluationPreflightError("T1 model adapter accepts synthetic simulated fixtures only")
    if sample.get("protocol_fingerprint_sha256") != expected_fingerprint:
        raise EvaluationPreflightError("protocol fingerprint differs from the preregistered value")
    review = sample.get("review", {})
    if not isinstance(review, dict) or review.get("status") == "rejected" or review.get("training_eligible") is not False:
        raise EvaluationPreflightError("rejected envelope cannot be evaluated")
    expected = sample.get("expected")
    if not isinstance(expected, dict) or not isinstance(expected.get("supported_in_v1"), bool):
        raise EvaluationPreflightError("envelope expected metadata is invalid")
    if expected.get("operation") is not None and expected.get("operation") not in ENABLED_OPERATIONS:
        raise EvaluationPreflightError("envelope operation is outside the enabled P1 operation set")
    try:
        # Validate the exact freezer schema, P1 target/context contracts, and
        # deterministic fixture replay before any request is sent to the model.
        validate_record(sample, _ENVELOPE_VALIDATOR)
    except Exception as error:
        raise EvaluationPreflightError(
            "envelope failed schema, P1 contract, or deterministic fixture replay validation"
        ) from error
    trace = sample.get("trace")
    if not isinstance(trace, list) or not trace:
        raise EvaluationPreflightError("envelope trace is empty or invalid")
    validated: list[dict[str, Any]] = []
    for step in trace:
        if not isinstance(step, dict):
            raise EvaluationPreflightError("trace step must be an object")
        kind = step.get("kind")
        if kind == "model":
            try:
                context = c.ModelContext.model_validate(step.get("context"))
                target = c.SEMANTIC_DECISION_ADAPTER.validate_python(step.get("target"))
                c.validate_decision_against_context(target, context)
            except Exception as error:
                raise EvaluationPreflightError("model context or target is invalid under P1 contracts") from error
            validated.append({"kind": kind, "context": context, "target": target})
        elif kind == "tool_result":
            if step.get("producer") != "deterministic_synthetic_fixture":
                raise EvaluationPreflightError("tool result must come from the deterministic synthetic fixture")
            try:
                result = c.ToolReadResult.model_validate(step.get("result"))
            except Exception as error:
                raise EvaluationPreflightError("tool result is invalid under the P1 contract") from error
            if not result.simulation:
                raise EvaluationPreflightError("non-simulated backend result is outside this evaluator")
            validated.append({"kind": kind, "result": result})
        elif kind == "user_followup":
            text = step.get("text")
            if not isinstance(text, str) or not text.strip():
                raise EvaluationPreflightError("user follow-up must contain text")
            validated.append({"kind": kind, "text": text})
        else:
            raise EvaluationPreflightError("unknown trace step kind")
    if not any(step["kind"] == "model" for step in validated):
        raise EvaluationPreflightError("trace contains no model step")
    return validated


def _typed_refs(value: Any, path: str = "") -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", by_alias=True, exclude_none=False)
    found: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}" if path else key
            if key.endswith("_ref") or key.endswith("_refs"):
                found[child] = item
            else:
                found.update(_typed_refs(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.update(_typed_refs(item, f"{path}[{index}]"))
    return found


def _read_trace_consistent(trace: list[dict[str, Any]], decisions: list[Any]) -> bool:
    model_index = 0
    complete = True
    for index, step in enumerate(trace):
        if step["kind"] == "model":
            decision = decisions[model_index] if model_index < len(decisions) else None
            model_index += 1
            if getattr(step["target"], "kind", None) == "read":
                next_steps = trace[index + 1 :]
                tool = next((item for item in next_steps if item["kind"] == "tool_result"), None)
                if tool is None:
                    complete = False
                elif decision is None or getattr(decision, "kind", None) != "read" or decision.operation != tool["result"].operation:
                    complete = False
                elif not any(
                    item["kind"] == "model"
                    and any(
                        result.model_dump(mode="json", by_alias=True, exclude_none=False)
                        == tool["result"].model_dump(mode="json", by_alias=True, exclude_none=False)
                        for result in item["context"].read_results
                    )
                    for item in next_steps
                ):
                    complete = False
        elif step["kind"] == "user_followup":
            following_model = next((item for item in trace[index + 1 :] if item["kind"] == "model"), None)
            if following_model is None:
                complete = False
            else:
                context = following_model["context"]
                echoed = step["text"] == context.input_text or any(
                    message.role == "user" and message.text == step["text"] for message in context.recent_messages
                )
                if not echoed:
                    complete = False
    return complete


def _metric_groups(sample_results: list[dict[str, Any]], generation_records: list[dict[str, Any]], split: str, config: dict[str, Any]) -> dict[str, Any]:
    metric_names = [
        "semantic_exact", "operation_exact", "parameter_exact", "reference_exact",
        "grounded_answer_exact", "clarification_exact", "decision_exact", "teacher_forced_trace_exact",
    ]
    metrics: dict[str, Any] = {}
    for name in metric_names:
        metrics[name] = summarize_boolean(row[name] for row in sample_results if row.get(name) is not None)
    metrics["first_output_schema_validity"] = summarize_boolean(
        bool(item["schema_valid"]) for item in generation_records if item["attempt"] == 1
    )
    metrics["schema_validity_all_attempts"] = summarize_boolean(bool(item["schema_valid"]) for item in generation_records)
    metrics["repair_recovery"] = summarize_boolean(
        bool(item["schema_valid"]) for item in generation_records if item["attempt"] == 2
    )
    def generation_metric_applies(metric_name: str, item: dict[str, Any]) -> bool:
        if metric_name == "operation_exact":
            return bool(item.get("operation_applicable"))
        if metric_name == "parameter_exact":
            return bool(item.get("parameter_applicable"))
        if metric_name == "grounded_answer_exact":
            return item.get("semantic_kind") == "answer"
        if metric_name == "clarification_exact":
            return item.get("semantic_kind") == "clarify"
        return True

    for metric_name in ("decision_exact", "operation_exact", "parameter_exact", "reference_exact", "grounded_answer_exact", "clarification_exact"):
        metrics[f"first_output_{metric_name}"] = summarize_boolean(
            bool(item.get(metric_name, False)) for item in generation_records
            if item["attempt"] == 1 and generation_metric_applies(metric_name, item)
        )
        metrics[f"repair_output_{metric_name}"] = summarize_boolean(
            bool(item.get(metric_name, False)) for item in generation_records
            if item["attempt"] == 2 and generation_metric_applies(metric_name, item)
        )
    metrics["timeout_rate"] = summarize_boolean(
        item["status"] == "timeout" for item in generation_records
    )
    durations = [item["duration_seconds"] for item in generation_records if isinstance(item.get("duration_seconds"), (int, float))]
    p95 = None
    if durations:
        ordered = sorted(durations)
        p95 = round(ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)], 3)
    metrics["single_concurrency_p95_seconds"] = {
        "value": p95, "denominator": len(durations), "threshold": config["runtime"]["p95_limit_seconds"],
    }
    by_operation: dict[str, dict[str, Any]] = {}
    operation_outcomes = [
        row["operation_results"][operation]
        for row in sample_results for operation in row.get("expected_operations", [])
        if operation in row.get("operation_results", {})
    ]
    parameter_outcomes = [
        row["parameter_results"][operation]
        for row in sample_results for operation in row.get("expected_operations", [])
        if operation in row.get("parameter_results", {})
    ]
    reference_outcomes = [
        row["reference_results"][operation]
        for row in sample_results for operation in row.get("expected_operations", [])
        if operation in row.get("reference_results", {})
        and row.get("reference_applicable", {}).get(operation, False)
    ]
    metrics["operation_choice_exact"] = summarize_boolean(operation_outcomes)
    metrics["required_parameters_exact_case"] = summarize_boolean(parameter_outcomes)
    metrics["typed_reference_binding_exact"] = summarize_boolean(reference_outcomes)
    macro_rates = []
    for operation in sorted(ENABLED_OPERATIONS):
        rows = [row for row in sample_results if operation in row.get("expected_operations", [])]
        by_operation[operation] = {
            "operation_choice_exact": summarize_boolean(row["operation_results"][operation] for row in rows if operation in row.get("operation_results", {})),
            "required_parameters_exact_case": summarize_boolean(row["parameter_results"][operation] for row in rows if operation in row.get("parameter_results", {})),
            "typed_reference_binding_exact": summarize_boolean(
                row["reference_results"][operation] for row in rows
                if operation in row.get("reference_results", {}) and row.get("reference_applicable", {}).get(operation, False)
            ),
            "teacher_forced_trace_exact": summarize_boolean(row["teacher_forced_trace_exact"] for row in rows if row.get("teacher_forced_trace_exact") is not None),
        }
        op_rate = by_operation[operation]["operation_choice_exact"]["rate"]
        if op_rate is not None:
            macro_rates.append(op_rate)
    metrics["operation_choice_macro_rate"] = sum(macro_rates) / len(macro_rates) if macro_rates else None
    metrics["per_operation"] = by_operation
    metrics["supported_complete_task_success"] = "NOT_EVALUATED_TEACHER_FORCED_TRACE_CANNOT_ESTABLISH_CLOSED_LOOP_TASK_SUCCESS"
    metrics["false_refusal"] = summarize_boolean(
        row["false_refusal"] for row in sample_results if row.get("false_refusal") is not None
    )
    field_values: dict[str, list[bool]] = defaultdict(list)
    for row in sample_results:
        for field_name, checks in row.get("parameter_field_checks", {}).items():
            field_values[field_name].extend(checks)
    metrics["parameter_field_accuracy"] = {
        field_name: summarize_boolean(values) for field_name, values in sorted(field_values.items())
    }
    formal_floor = config["sample_floors"]["formal_state_families_per_operation_per_split"]
    diagnostic_floor = config["sample_floors"]["diagnostic_state_families_per_operation_per_split"]
    counts = defaultdict(set)
    for row in sample_results:
        for operation in row.get("expected_operations", []):
            counts[operation].add(row["state_family_id"])
    metrics["sample_sufficiency"] = {
        "split": split,
        "diagnostic_floor_per_operation": diagnostic_floor,
        "formal_floor_per_operation": formal_floor,
        "independent_state_families_by_operation": {op: len(counts[op]) for op in sorted(ENABLED_OPERATIONS)},
        "status": "INSUFFICIENT_SAMPLE" if any(len(counts[op]) < formal_floor for op in ENABLED_OPERATIONS) else "FORMAL_SAMPLE_FLOOR_MET",
    }
    critical_denominator = sum(row.get("is_critical_case", False) for row in sample_results)
    known_critical_errors = sum(row.get("critical_error", False) for row in sample_results)
    unknown_critical_cases = sum(row.get("critical_review_required", False) for row in sample_results)
    if critical_denominator == 0:
        critical_status = "NOT_TESTED"
    elif known_critical_errors:
        critical_status = "FAIL"
    elif unknown_critical_cases:
        critical_status = "NEEDS_REVIEW"
    else:
        critical_status = "PASS_ON_SIMULATED_CASES"
    metrics["critical_errors"] = {
        "numerator": known_critical_errors,
        "denominator": critical_denominator,
        "unknown_cases_requiring_review": unknown_critical_cases,
        "status": critical_status,
    }
    metrics["model_output_attempts"] = len(generation_records)
    metrics["parsed_model_decisions"] = sum(bool(item["schema_valid"]) for item in generation_records)
    metrics["harness_blocks"] = sum(not bool(item["schema_valid"]) for item in generation_records)
    manual_review_count = sum(row.get("manual_review_required", False) for row in sample_results)
    metrics["manual_review_required"] = {
        "numerator": manual_review_count,
        "denominator": len(sample_results),
        "status": "NEEDS_REVIEW" if manual_review_count else "NONE_PENDING",
    }
    metrics["live_backend_agent"] = "NOT_TESTED"
    metrics["duplicate_business_effects"] = "NOT_TESTED_SIMULATED_REPLAY"

    thresholds = config["acceptance_thresholds"]
    per_operation_thresholds: dict[str, dict[str, str]] = {}
    per_operation_metric_bindings = {
        "operation_choice_exact": ("operation_choice_exact_min", "min"),
        "required_parameters_exact_case": ("required_parameters_exact_case_min", "min"),
        "typed_reference_binding_exact": ("typed_reference_binding_exact_min", "min"),
    }
    for operation, operation_metrics in by_operation.items():
        operation_status: dict[str, str] = {}
        for metric_name, (threshold_key, direction) in per_operation_metric_bindings.items():
            rate = operation_metrics[metric_name].get("rate")
            if rate is None:
                status = "NOT_TESTED"
            elif direction == "min":
                status = "PASS" if rate >= thresholds[threshold_key] else "FAIL"
            else:
                status = "PASS" if rate <= thresholds[threshold_key] else "FAIL"
            operation_status[metric_name] = status
        operation_metrics["threshold_statuses"] = operation_status
        per_operation_thresholds[operation] = operation_status

    metric_bindings = {
        "schema_validity": (metrics["schema_validity_all_attempts"], thresholds["schema_validity_min"], "min"),
        "operation_choice_exact": (metrics["operation_choice_exact"], thresholds["operation_choice_exact_min"], "min"),
        "required_parameters_exact_case": (metrics["required_parameters_exact_case"], thresholds["required_parameters_exact_case_min"], "min"),
        "typed_reference_binding_exact": (metrics["typed_reference_binding_exact"], thresholds["typed_reference_binding_exact_min"], "min"),
        "false_refusal": (metrics["false_refusal"], thresholds["false_refusal_max"], "max"),
        "timeout_rate": (metrics["timeout_rate"], thresholds["timeout_rate_max"], "max"),
    }
    threshold_statuses: dict[str, str] = {}
    for metric_name, (metric, threshold, direction) in metric_bindings.items():
        value = metric.get("rate") if isinstance(metric, dict) else None
        if value is None:
            threshold_statuses[metric_name] = "NOT_TESTED"
        elif direction == "min":
            threshold_statuses[metric_name] = "PASS" if value >= threshold else "FAIL"
        else:
            threshold_statuses[metric_name] = "PASS" if value <= threshold else "FAIL"
    for operation, operation_status in per_operation_thresholds.items():
        for metric_name, status in operation_status.items():
            threshold_statuses[f"{operation}.{metric_name}"] = status
    threshold_statuses["critical_errors"] = critical_status
    p95_value = metrics["single_concurrency_p95_seconds"]["value"]
    threshold_statuses["single_concurrency_p95_seconds"] = (
        "NOT_TESTED" if p95_value is None else
        "PASS" if p95_value <= thresholds["single_concurrency_p95_seconds_max"] else "FAIL"
    )
    if metrics["sample_sufficiency"]["status"] == "INSUFFICIENT_SAMPLE":
        for name, value in list(threshold_statuses.items()):
            if value == "PASS":
                threshold_statuses[name] = "INSUFFICIENT_SAMPLE"
        for operation_metrics in by_operation.values():
            for name, value in list(operation_metrics["threshold_statuses"].items()):
                if value == "PASS":
                    operation_metrics["threshold_statuses"][name] = "INSUFFICIENT_SAMPLE"
    threshold_statuses["supported_complete_task_success"] = "NOT_EVALUATED_TEACHER_FORCED_TRACE"
    metrics["threshold_statuses"] = threshold_statuses
    if "FAIL" in threshold_statuses.values():
        metrics["release_gate_status"] = "FAIL"
    elif "NEEDS_REVIEW" in threshold_statuses.values():
        metrics["release_gate_status"] = "NEEDS_REVIEW"
    elif any(value == "NOT_TESTED" for value in threshold_statuses.values()):
        metrics["release_gate_status"] = "NOT_TESTED"
    elif metrics["sample_sufficiency"]["status"] == "INSUFFICIENT_SAMPLE":
        metrics["release_gate_status"] = "INSUFFICIENT_SAMPLE"
    else:
        metrics["release_gate_status"] = "NOT_READY_FOR_END_TO_END_CLOSED_LOOP_AND_REAL_BACKEND"
    if metrics["manual_review_required"]["numerator"] or critical_status == "NEEDS_REVIEW":
        metrics["model_semantic_diagnostic_status"] = "NEEDS_REVIEW"
    elif any(value == "FAIL" for key, value in threshold_statuses.items() if key != "supported_complete_task_success"):
        metrics["model_semantic_diagnostic_status"] = "FAIL"
    elif metrics["sample_sufficiency"]["status"] == "INSUFFICIENT_SAMPLE":
        metrics["model_semantic_diagnostic_status"] = "INSUFFICIENT_SAMPLE"
    elif any(value == "NOT_TESTED" for key, value in threshold_statuses.items() if key != "supported_complete_task_success"):
        metrics["model_semantic_diagnostic_status"] = "NOT_TESTED"
    else:
        metrics["model_semantic_diagnostic_status"] = "STEPWISE_SEMANTIC_THRESHOLDS_MET_ON_SIMULATED_CASES"
    return metrics


async def run_evaluation(
    *,
    input_path: Path,
    output_path: Path,
    split: str,
    allow_sealed: bool = False,
    config_path: Path = CONFIG_PATH,
) -> dict[str, Any]:
    _must_be_split_file(input_path, split, allow_sealed)
    config = _read_config(config_path)
    fingerprint = config.get("protocol_fingerprint_sha256")
    if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise EvaluationPreflightError("protocol fingerprint is not preregistered")
    provider_config = config["model"]
    provider = LMStudioV1Provider(
        endpoint=config["runtime"]["endpoint"],
        models_endpoint=config["runtime"]["models_endpoint"],
        model_key=provider_config["model_key"],
        artifact_path=provider_config["artifact_path"],
        expected_artifact_sha256=provider_config["artifact_sha256"],
        expected_artifact_size_bytes=provider_config["artifact_size_bytes"],
        expected_quantization=provider_config["quantization"],
        timeout_seconds=config["runtime"]["timeout_seconds"],
        max_output_tokens=provider_config["max_output_tokens"],
        context_length=provider_config["context_length"],
        temperature=provider_config["temperature"],
    )
    prereg_result = _validate_model_preregistration(config, provider, config_path)
    freeze = _validate_freeze_approval(config, prereg_result["document"], split)
    if split == "sealed" and (
        not allow_sealed
        or config["runtime"].get("sealed_one_shot_authorized") is not True
        or freeze["approval"].get("sealed_one_shot_authorized") is not True
    ):
        raise EvaluationPreflightError("sealed run requires explicit root one-shot authorization")
    if not input_path.is_file():
        raise EvaluationPreflightError("split-specific frozen envelope file is missing")
    output_root = Path(config["runtime"]["results_root"])
    if not output_path.resolve().is_relative_to(output_root.resolve()):
        raise EvaluationPreflightError("evaluation output must remain under the D-only results directory")
    consumption_path = Path(config["runtime"]["sealed_consumption_ledger"])
    if not consumption_path.resolve().is_relative_to(output_root.resolve()):
        raise EvaluationPreflightError("sealed consumption ledger must remain under the D-only results directory")
    snapshot = resource_snapshot()
    floor = check_resource_floor(snapshot, "ready", config)
    if not floor["passed"]:
        raise EvaluationPreflightError("resource floor failed before candidate/API use")
    loaded = provider.inspect_loaded_candidate()
    if loaded["parallel"] != 1 or loaded["context_length"] < provider_config["context_length"]:
        raise EvaluationPreflightError("loaded candidate does not match preregistered concurrency/context")
    snapshot_after_catalog = resource_snapshot()
    floor_after_catalog = check_resource_floor(snapshot_after_catalog, "ready", config)
    if not floor_after_catalog["passed"]:
        raise EvaluationPreflightError("resource floor failed after catalog preflight")

    sealed_ledger: dict[str, Any] | None = None
    if split == "sealed":
        sealed_ledger = _create_sealed_consumption_ledger(
            Path(config["runtime"]["sealed_consumption_ledger"]),
            bundle_sha256=freeze["bundle_sha256"],
            prereg_sha256=prereg_result["sha256"],
            approval_sha256=freeze["approval_sha256"],
        )
    input_bytes = input_path.read_bytes()
    file_sha = _sha256_bytes(input_bytes)
    if file_sha != freeze["bundle_sha256"]:
        raise EvaluationPreflightError("selected JSONL hash differs from root-approved frozen bundle")
    validated_samples: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    seen_sample_ids: set[str] = set()
    for line_number, line in enumerate(input_bytes.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw_sample = json.loads(line)
        except json.JSONDecodeError as error:
            raise EvaluationPreflightError(f"invalid JSONL at line {line_number}") from error
        trace = _validate_envelope(raw_sample, split, fingerprint)
        sample_id = raw_sample.get("sample_id")
        if not isinstance(sample_id, str) or sample_id in seen_sample_ids:
            raise EvaluationPreflightError("sample_id is missing or duplicated in the frozen split")
        seen_sample_ids.add(sample_id)
        validated_samples.append((raw_sample, trace))
    if not validated_samples:
        raise EvaluationPreflightError("frozen split contains no samples")
    sample_results: list[dict[str, Any]] = []
    generation_records: list[dict[str, Any]] = []
    for raw_sample, trace in validated_samples:
        sample_id = raw_sample["sample_id"]
        decisions: list[Any] = []
        step_scores: list[dict[str, Any]] = []
        started_sample = time.monotonic()
        for step_index, step in enumerate(trace):
            if step["kind"] != "model":
                continue
            context = step["context"]
            prompt = ModelPrompt(context=context)
            parsed = None
            step_generation: list[dict[str, Any]] = []
            for attempt in (1, 2):
                if attempt == 2 and not step_generation:
                    break
                if attempt == 2 and step_generation[-1]["schema_valid"]:
                    break
                if attempt == 2 and step_generation[-1]["status"] in {"timeout", "transport_error"}:
                    break
                if attempt == 2:
                    prompt = ModelPrompt(context=context, repair_feedback=REPAIR_FEEDBACK)
                generation_started = time.monotonic()
                try:
                    result = await asyncio.wait_for(
                        provider.generate(prompt), timeout=config["runtime"]["timeout_seconds"]
                    )
                    elapsed = round(time.monotonic() - generation_started, 3)
                    generation_status = result.status
                    text = result.text
                    duration = result.duration_seconds
                    metadata = result.metadata()
                except asyncio.TimeoutError:
                    elapsed = round(time.monotonic() - generation_started, 3)
                    generation_status, text, duration, metadata = "timeout", "", elapsed, {"status": "timeout"}
                except LMStudioError as error:
                    elapsed = round(time.monotonic() - generation_started, 3)
                    generation_status, text, duration = ("timeout" if error.status == "timeout" else "transport_error"), "", elapsed
                    metadata = {"status": error.status, "http_status": error.http_status}
                try:
                    parsed_candidate = parse_model_output(text, context)
                    valid = generation_status == "response_received"
                    if valid:
                        parsed = parsed_candidate
                        attempt_score = score_semantic(parsed_candidate, step["target"], raw_sample, context)
                    else:
                        attempt_score = None
                except ModelOutputError:
                    valid = False
                    attempt_score = None
                record = {
                    "sample_id": sample_id,
                    "model_step": step_index,
                    "attempt": attempt,
                    "status": generation_status,
                    "schema_valid": valid,
                    "duration_seconds": duration,
                    "metadata": metadata,
                    "operation_applicable": getattr(step["target"], "kind", None) in {"read", "propose"},
                    "parameter_applicable": getattr(step["target"], "kind", None) in {"read", "propose"},
                    "semantic_kind": getattr(step["target"], "kind", None),
                    "decision_exact": bool(attempt_score and attempt_score.get("decision_exact")),
                    "operation_exact": bool(attempt_score and attempt_score.get("operation_exact")),
                    "parameter_exact": bool(attempt_score and attempt_score.get("parameter_exact")),
                    "reference_exact": bool(attempt_score and attempt_score.get("reference_exact")),
                    "grounded_answer_exact": bool(attempt_score and attempt_score.get("grounded_answer_exact")),
                    "clarification_exact": bool(attempt_score and attempt_score.get("clarification_exact")),
                }
                generation_records.append(record)
                step_generation.append(record)
                if valid:
                    break
                if generation_status in {"timeout", "transport_error"}:
                    break
            decisions.append(parsed)
            target = step["target"]
            gold_wire = target.model_dump(mode="json", by_alias=True, exclude_none=False)
            if parsed is None:
                score = {
                    "semantic_exact": False, "operation_exact": False, "parameter_exact": False,
                    "reference_exact": False, "grounded_answer_exact": False,
                    "clarification_exact": False, "decision_exact": False,
                }
            else:
                score = score_semantic(parsed, target, raw_sample, context)
            step_scores.append({"score": score, "target": gold_wire, "predicted": parsed})

        model_targets = [step["target"] for step in trace if step["kind"] == "model"]
        target_operations = {decision.operation for decision in model_targets if getattr(decision, "kind", None) in {"read", "propose"}}
        expected_operation = raw_sample["expected"].get("task_operation")
        if expected_operation is not None:
            target_operations.add(expected_operation)
        target_kinds = [getattr(target, "kind", None) for target in model_targets]
        step_exact = [bool(item["score"].get("decision_exact")) for item in step_scores]
        read_replay_ok = _read_trace_consistent(trace, decisions)
        # This trace uses stored follow-on contexts and fixture bodies; it is
        # teacher-forced diagnostic scoring, not a model-driven closed loop.
        teacher_forced_trace_exact = bool(step_exact and all(step_exact) and read_replay_ok)
        boundary_case = raw_sample.get("case_type") in BOUNDARY_CASES
        manual_review_required = any(
            item["score"].get("manual_review_required", False) for item in step_scores
        )
        sample_generations = [item for item in generation_records if item["sample_id"] == sample_id]
        parser_blocked = any(not item["schema_valid"] for item in sample_generations)
        predicted_proposals = [decision for decision in decisions if getattr(decision, "kind", None) == "propose"]
        direct_write_claim = any(
            getattr(decision, "kind", None) == "answer" and _DIRECT_WRITE_CLAIM.search(decision.text)
            for decision in decisions if decision is not None
        )
        critical_error = bool(boundary_case and target_kinds and "propose" not in target_kinds and predicted_proposals) or direct_write_claim
        operation_results: dict[str, bool] = {}
        parameter_results: dict[str, bool] = {}
        reference_results: dict[str, bool] = {}
        reference_applicable: dict[str, bool] = {}
        for operation in target_operations:
            matching_indices = [
                index for index, step in enumerate(trace)
                if step["kind"] == "model" and getattr(step["target"], "operation", None) == operation
            ]
            if expected_operation == operation and not matching_indices:
                operation_results[operation] = False
                parameter_results[operation] = False
                reference_results[operation] = False
                reference_applicable[operation] = True
                continue
            score_indices = [
                idx for idx, step in enumerate(trace)
                if step["kind"] == "model" and getattr(step["target"], "operation", None) == operation
            ]
            matched_scores = [step_scores[sum(1 for prior in trace[:idx] if prior["kind"] == "model")] for idx in score_indices]
            operation_results[operation] = bool(matched_scores) and all(item["score"].get("operation_exact") is True for item in matched_scores)
            parameter_results[operation] = bool(matched_scores) and all(item["score"].get("parameter_exact", False) for item in matched_scores)
            reference_results[operation] = bool(matched_scores) and all(item["score"].get("reference_exact", False) for item in matched_scores)
            reference_applicable[operation] = any(_typed_refs(item["target"]) for item in matched_scores)
        field_checks: dict[str, list[bool]] = defaultdict(list)
        for item in step_scores:
            for field_name, passed in item["score"].get("parameter_field_checks", {}).items():
                field_checks[field_name].append(bool(passed))
        sample_row: dict[str, Any] = {
            "sample_id": sample_id,
            "state_family_id": raw_sample["state_family_id"],
            "expected_operations": sorted(target_operations),
            "semantic_exact": all(item["score"].get("semantic_exact", False) for item in step_scores),
            "operation_exact": all(operation_results.values()) if operation_results else None,
            "operation_results": operation_results,
            "parameter_results": parameter_results,
            "reference_results": reference_results,
            "reference_applicable": reference_applicable,
            "parameter_exact": all(item["score"].get("parameter_exact", False) for item in step_scores),
            "reference_exact": all(item["score"].get("reference_exact", False) for item in step_scores),
            "grounded_answer_exact": all(
                item["score"].get("grounded_answer_exact", False)
                for item in step_scores if item["target"].get("kind") == "answer"
            ) if any(item["target"].get("kind") == "answer" for item in step_scores) else None,
            "clarification_exact": all(
                item["score"].get("clarification_exact", False)
                for item in step_scores if item["target"].get("kind") == "clarify"
            ) if any(item["target"].get("kind") == "clarify" for item in step_scores) else None,
            "decision_exact": all(step_exact),
            "teacher_forced_trace_exact": teacher_forced_trace_exact,
            "critical_error": critical_error,
            "is_critical_case": boundary_case,
            "critical_review_required": bool(boundary_case and (manual_review_required or parser_blocked)),
            "manual_review_required": manual_review_required,
            "parser_blocked": parser_blocked,
            "duration_seconds": round(time.monotonic() - started_sample, 3),
            "parameter_field_checks": {key: value for key, value in field_checks.items()},
            "false_refusal": (
                any(
                    target.kind != "clarify" and decision is not None and getattr(decision, "kind", None) == "clarify"
                    for target, decision in zip(model_targets, decisions)
                )
                if raw_sample["expected"].get("supported_in_v1")
                and any(target.kind != "clarify" for target in model_targets)
                else None
            ),
        }
        if split != "sealed":
            sample_row["step_metrics"] = [item["score"] for item in step_scores]
        sample_results.append(sample_row)

    metrics = _metric_groups(sample_results, generation_records, split, config)
    report = {
        "report_version": "t1-model-evaluation-report-v1",
        "status": "COMPLETED_SIMULATED_REPLAY" if sample_results else "NO_SAMPLES",
        "split": split,
        "data_origin": "synthetic",
        "replay_status": "simulated",
        "model_mode": "teacher-forced stepwise semantic diagnostic: LM Studio native v1 + P1 parser + stored synthetic contexts/results",
        "closed_loop_model_tool_replay": "NOT_TESTED; tool results and later contexts are pre-recorded in the envelope",
        "real_backend_agent": "NOT_TESTED",
        "candidate": loaded,
        "artifact_sha256_claim": provider_config["artifact_sha256"],
        "artifact_identity_binding": loaded["loaded_key_to_file_binding"],
        "prompt_sha256": provider.system_prompt_sha256,
        "semantic_schema_sha256": provider.semantic_schema_sha256,
        "runtime_config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "input_file_sha256": file_sha,
        "model_preregistration_sha256": prereg_result["sha256"],
        "freeze_manifest_sha256": freeze["manifest_sha256"],
        "root_approval_sha256": freeze["approval_sha256"],
        "sealed_consumption_status": "CONSUMED" if sealed_ledger else "NOT_CONSUMED",
        "resource_snapshot_before_run": snapshot,
        "resource_floor": floor,
        "resource_snapshot_after_candidate_preflight": snapshot_after_catalog,
        "resource_floor_after_candidate_preflight": floor_after_catalog,
        "sample_count": len(sample_results),
        "model_generation_attempts": len(generation_records),
        "metrics": metrics,
    }
    # A sealed run emits only aggregate metrics and hashes; it never emits row IDs,
    # prompts, decisions, or per-row status.
    if split != "sealed":
        report["sample_metrics"] = sample_results
        report["generation_metadata"] = generation_records
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["validation", "sealed"], required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-sealed-one-shot", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    report = asyncio.run(run_evaluation(
        input_path=args.input,
        output_path=args.output,
        split=args.split,
        allow_sealed=args.allow_sealed_one_shot,
    ))
    print(json.dumps({
        "status": report["status"], "split": report["split"], "sample_count": report["sample_count"],
        "model_generation_attempts": report["model_generation_attempts"],
        "metrics": report["metrics"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
