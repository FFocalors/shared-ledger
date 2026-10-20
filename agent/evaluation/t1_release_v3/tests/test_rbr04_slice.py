"""Tests for the RBR04 AA-tail and multi-person small-amount coverage slice."""
from __future__ import annotations

import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.evaluation.t1_release_v3 import (  # noqa: E402
    convert, profile, rbr04, runtime, snapshot,
)


@pytest.fixture(scope="module")
def report():
    from agent.evaluation.t1_release_v3 import slice_rbr04

    snapshot.verify_snapshot()
    report_path = profile.RUN_ROOT / "conversion" / slice_rbr04.REPORT_NAME
    if not report_path.is_file():
        slice_rbr04.main([])
    return json.loads(report_path.read_text(encoding="utf-8"))


def test_quantum_arithmetic_matches_the_allocator():
    # 150.01 over 6 at the 0.0001 quantum: 1,500,100 units, remainder 4.
    assert rbr04.units("150.01") == 1_500_100
    assert rbr04.units("150.01") % 6 == 4
    shape = rbr04.expected_tail_shape("150.01", 6)
    assert shape["remainder_units"] == 4
    assert shape["distinct_share_count"] == 2
    assert shape["first_share"] == "25.0017"
    assert shape["last_share"] == "25.0016"
    assert Decimal(shape["first_share"]) * 4 + Decimal(shape["last_share"]) * 2 == Decimal("150.01")


def test_tail_predicate_rejects_the_whole_cent_cases_the_review_flagged():
    # Packet rows 15/16/17: 25.00/1, 250.00/10, 50.00/2 -- all whole cent.
    assert rbr04.split_has_tail("25.00", 1) is False
    assert rbr04.split_has_tail("250.00", 10) is False
    assert rbr04.split_has_tail("50.00", 2) is False
    # A 2-decimal amount can never tail when the participant count divides 100.
    for participants in (2, 4, 5, 10, 20, 25):
        assert rbr04.split_has_tail("123.45", participants) is False


def test_every_case_declares_a_tail_and_a_plausible_participant_count():
    assert len(rbr04.RBR04_CASES) == 12
    splits = {case[0] for case in rbr04.RBR04_CASES}
    assert splits == set(profile.SPLITS)
    tags = {case[3] for case in rbr04.RBR04_CASES}
    assert tags == {"aa-tail", "small-multi"}
    for _split, _g, participants, _tag, amount in rbr04.RBR04_CASES:
        assert participants >= 2
        assert rbr04.split_has_tail(amount, participants) is True


def test_slice_cases_are_conserved_and_tailed(report):
    assert report["row_count"] == 8
    assert report["written_splits"] == ["train", "validation"]
    assert report["sealed_generated_not_written"]["row_count"] == 4
    assert len(report["cases"]) == 12
    for case in report["cases"]:
        assert case["conserved"] is True
        assert case["split_mode"] == "equal"
        assert case["payment_total"] == f"{Decimal(case['amount']):.4f}"
        assert case["tail"]["distinct_share_count"] == 2
        assert case["hint_removed"] is True
        # The tail is a real non-whole-cent share.
        assert Decimal(case["tail"]["first_share"]) != Decimal(case["tail"]["last_share"])


def test_written_rows_carry_the_v1_1_tuple_and_validate(report):
    validator = runtime.make_v3_validator()
    rows_path = profile.RUN_ROOT / "conversion" / report["rows_file"]
    raw = rows_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == report["rows_file_sha256"]
    for line in raw.decode("utf-8").splitlines():
        row = json.loads(line)
        assert row["release_version"] == profile.RELEASE_VERSION
        assert row["versions"]["semantic"] == profile.V11_SEMANTIC_VERSION
        assert row["split"] in rbr04.WRITTEN_SPLITS
        assert list(validator.iter_errors(row)) == []
        for step in row["trace"]:
            if step["kind"] == "model":
                for hint in convert.TRAINING_ONLY_HINTS:
                    assert hint not in step["context"]["input_text"]


def test_no_existing_row_or_family_floor_is_disturbed():
    """A coverage case reuses its family, so the state signature is unchanged."""
    from agent.evaluation.t1_release_v3 import bridge

    cases = rbr04.RBR04_CASES[:2]
    requests = []
    for index, (_split, g, _participants, tag, amount) in enumerate(cases):
        requests.append({"key": f"base-{index}", "operation": "expense.create", "family_index": g})
        requests.append({
            "key": f"variant-{index}", "operation": "expense.create", "family_index": g,
            "amount_override": amount, "variant_tag": tag,
        })
    rows = bridge.generate_rows(requests)["rows"]
    for index, (split_name, _g, _participants, _tag, amount) in enumerate(cases):
        base = rows[f"base-{index}"]
        variant = rows[f"variant-{index}"]
        assert base["split"] == variant["split"] == split_name
        # Same state family and signature: no new family is created.
        assert base["state_family_id"] == variant["state_family_id"]
        assert base["operation_state_signature_sha256"] == variant["operation_state_signature_sha256"]
        # Different row identity and amount.
        assert base["sample_id"] != variant["sample_id"]
        assert variant["trace"][-1]["target"]["fields"]["original_amount"] == amount
        assert base["trace"][-1]["target"]["fields"]["original_amount"] != amount


def test_default_amount_is_unchanged_without_an_override():
    """The coverage extension point must not move any v2 row."""
    from agent.evaluation.t1_release_v3 import bridge

    cases = rbr04.RBR04_CASES[:3]
    rows = bridge.generate_rows([
        {"key": f"g{index}", "operation": "expense.create", "family_index": case[1]}
        for index, case in enumerate(cases)
    ])["rows"]
    for index, (_split, _g, participants, _tag, amount) in enumerate(cases):
        fields = rows[f"g{index}"]["trace"][-1]["target"]["fields"]
        # Without an override the amount is still 25 per participant, which is
        # exactly why the default families can never show a tail.
        assert fields["original_amount"] == f"{25 * participants:.2f}"
        assert fields["original_amount"] != amount
        assert rows[f"g{index}"]["release_version"] == profile.V2_RELEASE_VERSION
