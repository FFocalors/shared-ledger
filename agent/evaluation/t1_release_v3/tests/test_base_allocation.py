"""Tests for the two AA allocation columns (B1) and the base coverage cases (B2)."""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.evaluation.t1_release_v3 import base_allocation as ba  # noqa: E402
from agent.evaluation.t1_release_v3 import profile, rbr04  # noqa: E402


def test_original_column_uses_the_cent_fraction_quantum():
    # p_original_amount * 10000 units, first |remainder| participants +1.
    assert ba.original_allocations("100.00", 3) == [
        Decimal("33.3334"), Decimal("33.3333"), Decimal("33.3333")
    ]
    assert ba.original_allocations("10.00", 6) == [
        Decimal("1.6667"), Decimal("1.6667"), Decimal("1.6667"),
        Decimal("1.6667"), Decimal("1.6666"), Decimal("1.6666"),
    ]
    assert sum(ba.original_allocations("150.01", 6)) == Decimal("150.01")


def test_base_column_uses_the_tenth_quantum_and_b01s_examples():
    assert ba.base_allocations(Decimal("100.0"), 3) == [
        Decimal("33.4"), Decimal("33.3"), Decimal("33.3")
    ]
    assert ba.base_allocations(Decimal("10.0"), 6) == [
        Decimal("1.7"), Decimal("1.7"), Decimal("1.7"), Decimal("1.7"),
        Decimal("1.6"), Decimal("1.6"),
    ]
    assert ba.base_allocations(Decimal("150.0"), 6) == [Decimal("25.0")] * 6
    assert ba.base_allocations(Decimal("710.0"), 3) == [
        Decimal("236.7"), Decimal("236.7"), Decimal("236.6")
    ]


def test_the_two_columns_are_not_the_same_allocation():
    """A row can tail in one column and be even in the other."""
    original = ba.original_allocations("150.01", 6)
    base = ba.base_allocations(ba.expense_base_total("150.01", Decimal("1")), 6)
    assert len(set(original)) == 2          # original tail
    assert len(set(base)) == 1              # base even
    # And the reverse: same shape, different values.
    assert ba.original_allocations("100.00", 3) != ba.base_allocations(Decimal("100.0"), 3)


def test_last_person_shape_is_detected_as_the_superseded_one():
    fallback = [Decimal("33.3"), Decimal("33.3"), Decimal("33.4")]
    persisted = [Decimal("33.4"), Decimal("33.3"), Decimal("33.3")]
    assert ba.is_last_person_fallback(fallback, Decimal("100.0")) is True
    assert ba.is_last_person_fallback(persisted, Decimal("100.0")) is False
    # With no remainder the two shapes coincide and neither is a fallback.
    assert ba.is_last_person_fallback([Decimal("25.0")] * 6, Decimal("150.0")) is False


def test_negative_amounts_keep_the_sign_rule():
    # trunc toward zero, remainder keeps its sign, first |remainder| move by it.
    assert ba.base_allocations(Decimal("-10.0"), 6) == [
        Decimal("-1.7"), Decimal("-1.7"), Decimal("-1.7"), Decimal("-1.7"),
        Decimal("-1.6"), Decimal("-1.6"),
    ]


def test_case_catalogue_covers_the_required_shapes():
    tags = {case[2] for case in rbr04.BASE_AA_CASES}
    assert tags == {"base-100-3", "base-10-6", "orig-tail-base-even", "fx-both-tail"}
    splits = {case[0] for case in rbr04.BASE_AA_CASES}
    assert splits == set(profile.SPLITS)
    assert len(rbr04.BASE_AA_CASES) == 12
    # B01's two examples are present verbatim.
    for tag in ("base-100-3", "base-10-6"):
        expected = rbr04.BASE_AA_EXPECTATIONS[tag]
        assert expected["base_has_tail"] is True
    # The original-tail / base-even case is explicitly present.
    even = rbr04.BASE_AA_EXPECTATIONS["orig-tail-base-even"]
    assert even["original_has_tail"] is True and even["base_has_tail"] is False


def test_quantum_ruling_records_both_columns():
    ruling = rbr04.QUANTUM_RULING
    assert ruling["original_currency_column"]["quantum"] == "0.0001"
    assert ruling["base_currency_column"]["quantum"] == "0.1"
    assert ruling["original_currency_column"]["field"] == "splits.amount"
    assert ruling["base_currency_column"]["field"] == "splits.base_amount"
    assert "last participant" in ruling["base_currency_column"]["persisted_shape"]
    assert "payments" in ruling["payments_note"]


def test_written_candidate_carries_both_columns():
    report = json.loads((profile.REVIEW_ROOT / "candidate-report.json").read_text("utf-8"))
    cases = report["base_aa_cases"]
    assert len(cases) == 12
    for case in cases:
        assert Decimal(sum(Decimal(v) for v in case["original_shares"])) == Decimal(
            case["original_amount"]
        )
        assert Decimal(sum(Decimal(v) for v in case["base_shares"])) == Decimal(
            case["base_amount"]
        )
        tag_shapes = next(
            tag for tag, expected in rbr04.BASE_AA_EXPECTATIONS.items()
            if expected["base_shares"] == case["base_shares"]
        )
        assert tag_shapes
    # Both B01 examples appear among the written rows.
    assert any(case["base_shares"] == ["33.4", "33.3", "33.3"] for case in cases)
    assert any(case["base_shares"] == ["1.7", "1.7", "1.7", "1.7", "1.6", "1.6"]
               for case in cases)
