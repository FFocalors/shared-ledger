from __future__ import annotations

import socket
import hashlib
import json
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.evaluation.model_lmstudio import LMStudioError, LMStudioV1Provider, _loopback_endpoint, check_resource_floor
from agent.evaluation.model_scoring import answer_grounding, score_semantic
from agent.evaluation.model_runner import (
    ENABLED_OPERATIONS,
    EvaluationPreflightError,
    _create_sealed_consumption_ledger,
    _metric_groups,
    _must_be_split_file,
    _validate_freeze_approval,
)


def _answer(text: str) -> dict:
    return {"kind": "answer", "basis": "grounded", "text": text, "citations": ["fact_debt_1"]}


def _context() -> dict:
    return {
        "input_text": "",
        "recent_messages": [],
        "read_results": [{"body": {"items": [{"evidence_ref": "fact_debt_1"}]}}],
        "policy_evidence": [],
    }


def test_answer_scorer_rejects_inverted_debt_direction_even_with_same_citation() -> None:
    gold = _answer("林欠陈 20 CNY。")
    prediction = _answer("陈欠林 20 CNY。")
    result = answer_grounding(prediction, gold, _context())
    assert result["citation_exact"] is True
    assert result["financial_anchors_exact"] is True
    assert result["grounded_answer_exact"] is False
    assert result["manual_review_required"] is True


def test_answer_scorer_rejects_unsupported_prepayment_claim_with_same_citation() -> None:
    gold = _answer("普通活动不支持预存。")
    prediction = _answer("普通活动支持预存。")
    result = answer_grounding(prediction, gold, _context())
    assert result["citation_exact"] is True
    assert result["grounded_answer_exact"] is False
    assert result["manual_review_required"] is True


def test_answer_scorer_rejects_write_success_claim_with_same_citation() -> None:
    gold = _answer("该操作只生成待确认提议，没有写入账本。")
    prediction = _answer("该操作已成功写入账本。")
    result = answer_grounding(prediction, gold, _context())
    assert result["citation_exact"] is True
    assert result["grounded_answer_exact"] is False


def test_exact_grounded_answer_passes_but_paraphrase_needs_manual_review() -> None:
    gold = _answer("林欠陈 20 CNY。")
    exact = answer_grounding(_answer("林欠陈 20 CNY。"), gold, _context())
    paraphrase = answer_grounding(_answer("林仍需向陈支付20元。"), gold, _context())
    assert exact["grounded_answer_exact"] is True
    assert paraphrase["grounded_answer_exact"] is False
    assert paraphrase["manual_review_required"] is True


def test_proposal_reference_accuracy_is_separate_from_amount_accuracy() -> None:
    expected = {
        "kind": "propose", "operation": "expense.create",
        "fields": {
            "kind": "expense.create", "ledger_unit_ref": "ledger_unit_1", "title": "晚餐",
            "original_amount": "20", "original_currency": "CNY",
            "payment_allocations": [{"participant_ref": "participant_1", "amount": "20"}],
            "split": {"mode": "equal", "participant_refs": ["participant_1", "participant_2"]},
            "occurred_at": "2026-10-01T00:00:00Z",
        },
    }
    predicted = {
        **expected,
        "fields": {
            **expected["fields"], "original_amount": "200",
            "payment_allocations": [{"participant_ref": "participant_1", "amount": "200"}],
        },
    }
    result = score_semantic(predicted, expected, {"expected": {"operation": "expense.create"}}, _context())
    assert result["operation_exact"] is True
    assert result["parameter_exact"] is False
    assert result["reference_exact"] is True
    assert result["decision_exact"] is False


def test_clarification_prompt_mismatch_does_not_pass_on_slots_alone() -> None:
    expected = {"kind": "clarify", "prompt": "请补充币种。", "missing_slots": ["original_currency"]}
    predicted = {"kind": "clarify", "prompt": "请补充金额。", "missing_slots": ["original_currency"]}
    result = score_semantic(predicted, expected, {"expected": {"operation": None}}, _context())
    assert result["clarification_exact"] is False
    assert result["decision_exact"] is False
    assert result["manual_review_required"] is True


def test_non_explicit_proposal_title_is_not_an_exact_parameter_gate() -> None:
    expected = {"kind": "propose", "operation": "expense.create", "fields": {"kind": "expense.create", "title": "模拟消费", "original_amount": "20", "ledger_unit_ref": "ledger_unit_1"}}
    predicted = {"kind": "propose", "operation": "expense.create", "fields": {"kind": "expense.create", "title": "晚餐", "original_amount": "20", "ledger_unit_ref": "ledger_unit_1"}}
    result = score_semantic(predicted, expected, {"expected": {"operation": "expense.create"}}, _context())
    assert result["parameter_exact"] is True
    assert result["reference_exact"] is True


def test_explicit_proposal_title_is_scored_exactly() -> None:
    expected = {"kind": "propose", "operation": "expense.create", "fields": {"kind": "expense.create", "title": "晚餐", "original_amount": "20"}}
    predicted = {"kind": "propose", "operation": "expense.create", "fields": {"kind": "expense.create", "title": "宵夜", "original_amount": "20"}}
    context = {**_context(), "input_text": "新增晚餐 20 CNY"}
    result = score_semantic(predicted, expected, {"expected": {"operation": "expense.create"}}, context)
    assert result["parameter_exact"] is False


def test_candidate_endpoints_are_loopback_only() -> None:
    assert _loopback_endpoint("http://127.0.0.1:1234/api/v1/chat")
    with pytest.raises(ValueError):
        _loopback_endpoint("https://opencode.ai/zen/go/v1/chat/completions")


def test_transport_timeout_url_error_is_classified_as_timeout() -> None:
    provider = LMStudioV1Provider(
        model_key="candidate", artifact_path="D:/unused.gguf", expected_artifact_sha256="0" * 64,
    )
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError(socket.timeout("timed out"))):
        with pytest.raises(LMStudioError) as error:
            provider._request("http://127.0.0.1:1234/api/v1/models")
    assert error.value.status == "timeout"


def test_context_and_output_configuration_cannot_fall_back_to_smoke_values() -> None:
    provider = LMStudioV1Provider(
        model_key="candidate", artifact_path="D:/unused.gguf", expected_artifact_sha256="0" * 64,
        context_length=512, max_output_tokens=256,
    )
    assert provider.context_length == 8192
    assert provider.max_output_tokens == 768
    assert "expense.create" in provider.system_prompt
    assert "SEMANTIC_DECISION_SCHEMA" not in provider.system_prompt


def test_resource_floor_fails_closed_when_any_measurement_is_unknown() -> None:
    config = {"resource_thresholds": {"before_load_ram_gib": 12, "before_load_vram_mib": 6500, "ready_ram_gib": 8, "ready_vram_mib": 1500}}
    assert not check_resource_floor({"free_ram_gib": 16, "free_vram_mib": None}, "before_load", config)["passed"]
    assert check_resource_floor({"free_ram_gib": 12, "free_vram_mib": 6500}, "before_load", config)["passed"]


def test_sealed_split_is_denied_before_any_file_read() -> None:
    with pytest.raises(EvaluationPreflightError):
        _must_be_split_file(Path(r"D:\AI\runs\shared-ledger\t1\data\sealed.jsonl"), "sealed", False)


def test_sealed_consumption_is_atomic_and_rejects_replay(tmp_path: Path) -> None:
    ledger = tmp_path / "sealed-consumption-ledger.json"
    record = _create_sealed_consumption_ledger(
        ledger, bundle_sha256="a" * 64, prereg_sha256="b" * 64, approval_sha256="c" * 64,
    )
    assert record["status"] == "CONSUMED_AT_START"
    with pytest.raises(EvaluationPreflightError, match="already exists"):
        _create_sealed_consumption_ledger(
            ledger, bundle_sha256="a" * 64, prereg_sha256="b" * 64, approval_sha256="c" * 64,
        )


def _write_root_approved_freeze(tmp_path: Path) -> tuple[dict, dict]:
    manifest = {
        "status": "FROZEN",
        "freeze_status": "PREPARED_FOR_INDEPENDENT_ROOT_REVIEW",
        "root_freeze_approval": "pending",
        "hashes": {"protocol_fingerprint_sha256": "f" * 64},
        "bundles": {
            split: {
                "path": str(Path(r"D:\AI\runs\shared-ledger\t1\data") / f"{split}.jsonl"),
                "sha256": ("a" if split == "validation" else "b") * 64,
            }
            for split in ("validation", "sealed")
        },
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_path = tmp_path / "freeze-manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    approval = {
        "status": "APPROVED_DIAGNOSTIC_FREEZE",
        "manifest_sha256": manifest_sha,
        "protocol_fingerprint_sha256": "f" * 64,
        "reviewed_splits": ["validation", "sealed"],
        "scope": "diagnostic_only",
        "training_eligible": False,
        "human_review_pending": True,
    }
    approval_bytes = json.dumps(approval, sort_keys=True).encode()
    approval_sha = hashlib.sha256(approval_bytes).hexdigest()
    approval_path = tmp_path / "freeze-review-root.json"
    approval_path.write_bytes(approval_bytes)
    config = {
        "freeze_manifest_path": str(manifest_path),
        "root_freeze_approval_path": str(approval_path),
        "protocol_fingerprint_sha256": "f" * 64,
        "data_freeze": {
            "manifest_sha256": manifest_sha,
            "root_approval_sha256": approval_sha,
            "protocol_fingerprint_sha256": "f" * 64,
            "bundle_sha256": {"validation": "a" * 64, "sealed": "b" * 64},
        },
    }
    prereg = {
        "data_freeze": {
            "manifest_sha256": manifest_sha,
            "root_approval_sha256": approval_sha,
            "protocol_fingerprint_sha256": "f" * 64,
            "bundle_sha256": {
                "validation": "a" * 64,
                "sealed": "b" * 64,
            },
        }
    }
    return config, prereg


def test_freeze_gate_matches_separate_approval_artifact_and_manifest_hash(tmp_path: Path) -> None:
    config, prereg = _write_root_approved_freeze(tmp_path)
    result = _validate_freeze_approval(config, prereg, "validation")
    assert result["bundle_sha256"] == "a" * 64
    assert result["approval"]["status"] == "APPROVED_DIAGNOSTIC_FREEZE"


def test_freeze_gate_rejects_old_approval_shape_and_missing_sealed_review(tmp_path: Path) -> None:
    config, prereg = _write_root_approved_freeze(tmp_path)
    approval_path = Path(config["root_freeze_approval_path"])
    approval = json.loads(approval_path.read_bytes())
    approval["status"] = "APPROVED"
    approval.pop("reviewed_splits")
    approval["approved_splits"] = ["validation"]
    approval_bytes = json.dumps(approval, sort_keys=True).encode()
    approval_path.write_bytes(approval_bytes)
    prereg["data_freeze"]["root_approval_sha256"] = hashlib.sha256(approval_bytes).hexdigest()
    with pytest.raises(EvaluationPreflightError, match="root approval is absent"):
        _validate_freeze_approval(config, prereg, "validation")


def _metric_config() -> dict:
    return {
        "runtime": {"p95_limit_seconds": 60},
        "sample_floors": {"diagnostic_state_families_per_operation_per_split": 5, "formal_state_families_per_operation_per_split": 20},
        "acceptance_thresholds": {
            "schema_validity_min": 0.95,
            "operation_choice_exact_min": 0.90,
            "required_parameters_exact_case_min": 0.90,
            "typed_reference_binding_exact_min": 0.90,
            "supported_complete_task_success_min": 0.90,
            "false_refusal_max": 0.05,
            "critical_errors_max": 0,
            "single_concurrency_p95_seconds_max": 60,
            "timeout_rate_max": 0.05,
        },
    }


def test_zero_critical_case_denominator_is_not_a_pass() -> None:
    metrics = _metric_groups([], [], "validation", _metric_config())
    assert metrics["critical_errors"]["denominator"] == 0
    assert metrics["critical_errors"]["status"] == "NOT_TESTED"


def test_unparsed_critical_attempt_is_unknown_not_zero_critical_errors() -> None:
    sample = {
        "state_family_id": "state-family-001",
        "expected_operations": [],
        "operation_results": {}, "parameter_results": {}, "reference_results": {}, "reference_applicable": {},
        "critical_error": False, "is_critical_case": True, "critical_review_required": True,
        "manual_review_required": False, "parameter_field_checks": {}, "false_refusal": None,
    }
    generation = {"sample_id": "t1-case-001", "attempt": 1, "schema_valid": False, "status": "response_received"}
    metrics = _metric_groups([sample], [generation], "validation", _metric_config())
    assert metrics["critical_errors"]["numerator"] == 0
    assert metrics["critical_errors"]["denominator"] == 1
    assert metrics["critical_errors"]["status"] == "NEEDS_REVIEW"
    assert metrics["harness_blocks"] == 1


def test_per_operation_failure_cannot_hide_behind_passing_pooled_rate() -> None:
    operations = sorted(ENABLED_OPERATIONS)
    samples = []
    for operation in operations:
        for index in range(20):
            exact = not (operation == operations[0] and index >= 17)
            samples.append({
                "sample_id": f"{operation}-{index}",
                "state_family_id": f"state-family-{operation}-{index}",
                "expected_operations": [operation],
                "operation_results": {operation: exact},
                "parameter_results": {operation: exact},
                "reference_results": {operation: True},
                "reference_applicable": {operation: True},
                "teacher_forced_trace_exact": None,
                "critical_error": False,
                "is_critical_case": False,
                "critical_review_required": False,
                "manual_review_required": False,
                "false_refusal": None,
            })
    metrics = _metric_groups(samples, [], "validation", _metric_config())
    assert metrics["operation_choice_exact"]["rate"] > 0.90
    assert metrics["per_operation"][operations[0]]["operation_choice_exact"]["rate"] < 0.90
    assert metrics["per_operation"][operations[0]]["threshold_statuses"]["operation_choice_exact"] == "FAIL"
    assert metrics["threshold_statuses"][f"{operations[0]}.operation_choice_exact"] == "FAIL"
    assert metrics["release_gate_status"] == "FAIL"
