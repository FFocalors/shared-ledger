"""Tests for the RBR03 natural-clarification slice."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.evaluation.t1_release_v3 import (  # noqa: E402
    convert, hashing, profile, rbr03, runtime, snapshot,
)


@pytest.fixture(scope="module")
def report():
    from agent.evaluation.t1_release_v3 import slice_rbr03

    snapshot.verify_snapshot()
    report_path = profile.RUN_ROOT / "conversion" / slice_rbr03.REPORT_NAME
    if not report_path.is_file():
        slice_rbr03.main([])
    return json.loads(report_path.read_text(encoding="utf-8"))


def test_slice_covers_all_splits(report):
    assert report["row_count"] == 6
    assert report["written_splits"] == ["train", "validation"]
    assert report["sealed_generated_not_written"]["row_count"] == 3
    assert len(report["cases"]) == 9


def test_clarification_never_exposes_an_internal_reference(report):
    for case in report["cases"]:
        assert case["exposes_internal_reference"] is False
        assert "expense_ref" not in case["clarification_prompt"]
        assert "expense_ref" not in case["followup"]
        # The follow-up selects by returned facts, not by the internal ref.
        assert case["selected_expense_ref"] not in case["followup"]


def test_each_candidate_is_described_by_returned_facts(report):
    rows_path = profile.RUN_ROOT / "conversion" / report["rows_file"]
    raw = rows_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == report["rows_file_sha256"]
    for line in raw.decode("utf-8").splitlines():
        row = json.loads(line)
        rbr03.validate_natural_clarification(row)
        prompt = row["trace"][2]["target"]["prompt"]
        facts = row["trace"][1]["result"]["body"]["items"]
        for fact in facts:
            assert fact["title"] in prompt
            assert fact["occurred_at"][:10] in prompt
            assert f"{fact['original_amount']} {fact['original_currency']}" in prompt


def test_converted_rows_validate_and_keep_the_proposal(report):
    validator = runtime.make_v3_validator()
    rows_path = profile.RUN_ROOT / "conversion" / report["rows_file"]
    for line in rows_path.read_bytes().decode("utf-8").splitlines():
        row = json.loads(line)
        assert row["release_version"] == profile.RELEASE_VERSION
        assert list(validator.iter_errors(row)) == []
        # Only presentation fields move; the amount and target are unchanged.
        fields = row["trace"][4]["target"]["fields"]
        assert row["trace"][4]["target"]["operation"] == "expense.presentation.update"
        assert "original_amount" not in fields


def test_natural_validator_rejects_a_ref_based_followup():
    row = {
        "sample_id": "x", "split": "train", "case_type": "multi_turn",
        "expected": {"semantic": "propose", "task_operation": "expense.presentation.update"},
        "trace": [
            {"kind": "model", "context": {"input_text": "改标题"},
             "target": {"kind": "read"}},
            {"kind": "tool_result", "result": {"body": {"items": [
                {"expense_ref": "expense_1", "title": "A", "occurred_at": "2026-10-01T00:00:00Z",
                 "original_amount": "1.00", "original_currency": "USD", "participant_refs": ["participant_1"]},
                {"expense_ref": "expense_2", "title": "A", "occurred_at": "2026-10-02T00:00:00Z",
                 "original_amount": "2.00", "original_currency": "USD", "participant_refs": ["participant_1"]},
            ]}}},
            {"kind": "model", "target": {"kind": "clarify", "prompt": "有 2 笔同名费用：A；请选"}},
            {"kind": "user_followup", "text": "expense_ref=expense_1。"},
            {"kind": "model", "context": {"input_text": "expense_ref=expense_1。", "recent_messages": []},
             "target": {"kind": "propose", "operation": "expense.presentation.update",
                        "fields": {"kind": "expense.presentation.update",
                                   "expense_ref": "expense_1", "title": "B"}}},
        ],
    }
    with pytest.raises(rbr03.NaturalClarificationError):
        rbr03.validate_natural_clarification(row)


def test_hashing_matches_the_v2_canonical_form():
    from agent.evaluation.t1_release_v3 import hashing

    value = {"b": 1, "a": [2, 3]}
    assert hashing.canonical_json(value) == b'{"a":[2,3],"b":1}'
    assert hashing.sha256(value) == hashlib.sha256(b'{"a":[2,3],"b":1}').hexdigest()
