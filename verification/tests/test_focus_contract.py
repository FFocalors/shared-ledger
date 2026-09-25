"""Offline checks for the formal focus contracts."""

from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from shared_ledger_verifier.focus_contract import (
    ALL_FOCUSES,
    COVERAGE_FOCUSES,
    SMOKE_FOCUSES,
    FocusDefinitionError,
    check_focus,
    focus_spec,
)
from shared_ledger_verifier.loader import ScenarioValidationError, load_scenario


def scenario(**overrides) -> dict:
    base = {
        "schema_version": 1,
        "scenario_id": "case_1",
        "description": "generated",
        "activity": {"type": "normal", "base_currency": "CNY", "multi_currency_enabled": False},
        "participants": ["alice", "bob", "carol"],
        "operations": [],
    }
    base.update(overrides)
    return base


def expense(*, ref="expense_1", amount="100.0", payments=None, splits=None, aa=None,
            split_method=None, original_expense_ref=None, title="Shared"):
    operation = {
        "type": "linked_refund" if original_expense_ref else "create_expense",
        "ref": ref,
        "title": title,
        "amount": amount,
        "currency": "CNY",
        "payments": payments if payments is not None else {"alice": amount},
    }
    if original_expense_ref:
        operation["original_expense_ref"] = original_expense_ref
    method = split_method or ("aa" if aa is not None else "manual")
    operation["split_method"] = method
    if method == "aa":
        operation["aa_participants"] = aa
    else:
        operation["splits"] = splits if splits is not None else {"bob": amount}
    return operation


class FocusContractTests(unittest.TestCase):
    def parse(self, document: dict):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scenario.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            return load_scenario(path)

    def verdict(self, document: dict, focus: str) -> tuple[str, str | None]:
        return check_focus(self.parse(document), focus)

    # -- registry ---------------------------------------------------------

    def test_registry_covers_the_required_focuses(self):
        expected = {
            "single_payer_aa", "multi_payer_aa", "aa_rounding", "manual_split",
            "fifo_repayment", "targeted_repayment", "multiple_repayments",
            "prepayment_before_debt", "prepayment_after_debt", "prepayment_return",
            "linked_refund", "negative_expense", "void_transfer", "mixed_flow",
            # second wave: the remaining high-value business domains
            "multi_currency", "final_settlement", "large_activity", "refund_boundary",
            "completion_archive",
        }
        self.assertEqual(set(COVERAGE_FOCUSES), expected)
        self.assertEqual(set(SMOKE_FOCUSES), {"expense_aa", "targeted_repayment", "prepayment_refund"})
        self.assertEqual(set(ALL_FOCUSES), expected | {"expense_aa", "prepayment_refund"})
        self.assertEqual(len(ALL_FOCUSES), 21)

    def test_every_focus_declares_a_business_goal_and_dimensions(self):
        for name in ALL_FOCUSES:
            spec = focus_spec(name)
            self.assertTrue(spec.goal.strip(), name)
            self.assertTrue(spec.sections, name)
            self.assertTrue(spec.amount_patterns, name)
            self.assertTrue(spec.operation_counts, name)
            self.assertTrue(spec.edge_tags, name)
            self.assertLessEqual(spec.participants[0], spec.participants[1], name)

    def test_unknown_focus_is_rejected(self):
        with self.assertRaises(FocusDefinitionError):
            focus_spec("not_a_focus")

    # -- shared preconditions --------------------------------------------

    def test_non_cny_activity_fails_every_focus(self):
        document = scenario(
            activity={"type": "normal", "base_currency": "USD", "multi_currency_enabled": True},
            operations=[expense(aa=["alice", "bob", "carol"], payments={"alice": "60.0", "bob": "40.0"})],
        )
        status, reason = self.verdict(document, "expense_aa")
        self.assertEqual(status, "FOCUS_MISMATCH")
        self.assertIn("CNY", reason)

    def test_participant_count_outside_the_declared_range_fails(self):
        document = scenario(
            participants=["alice", "bob"],
            operations=[expense(payments={"alice": "100.0"}, splits={"bob": "100.0"})],
        )
        status, reason = self.verdict(document, "multi_payer_aa")
        self.assertEqual(status, "FOCUS_MISMATCH")
        self.assertIn("participants", reason)

    # -- focus-specific contracts -----------------------------------------

    def test_expense_aa_requires_two_or_three_positive_payers(self):
        good = scenario(operations=[expense(
            aa=["alice", "bob", "carol"], payments={"alice": "60.0", "bob": "40.0"})])
        self.assertEqual(self.verdict(good, "expense_aa")[0], "FOCUS_VALID")
        single = scenario(operations=[expense(
            aa=["alice", "bob", "carol"], payments={"alice": "100.0"})])
        status, reason = self.verdict(single, "expense_aa")
        self.assertEqual(status, "FOCUS_MISMATCH")
        self.assertIn("2-3 positive payers", reason)

    def test_single_payer_aa_requires_exactly_one_full_payer(self):
        good = scenario(operations=[expense(
            aa=["alice", "bob", "carol"], payments={"alice": "100.0"})])
        self.assertEqual(self.verdict(good, "single_payer_aa")[0], "FOCUS_VALID")
        two = scenario(operations=[expense(
            aa=["alice", "bob", "carol"], payments={"alice": "60.0", "bob": "40.0"})])
        self.assertEqual(self.verdict(two, "single_payer_aa")[0], "FOCUS_MISMATCH")

    def test_multi_payer_aa_rejects_a_single_payer(self):
        one = scenario(operations=[expense(
            aa=["alice", "bob", "carol"], payments={"alice": "100.0"})])
        status, reason = self.verdict(one, "multi_payer_aa")
        self.assertEqual(status, "FOCUS_MISMATCH")
        self.assertIn("2-3 positive payers", reason)

    def test_multi_payer_aa_rejects_a_payer_who_covers_everything(self):
        # Two payment entries, but one of them pays the whole amount, so the
        # topology is still single-creditor.
        document = scenario(operations=[expense(
            aa=["alice", "bob", "carol"], payments={"alice": "100.0"})])
        self.assertEqual(self.verdict(document, "multi_payer_aa")[0], "FOCUS_MISMATCH")

    def test_aa_rounding_requires_a_non_exact_division(self):
        exact = scenario(operations=[expense(
            amount="120.0", aa=["alice", "bob", "carol"], payments={"alice": "120.0"})])
        status, reason = self.verdict(exact, "aa_rounding")
        self.assertEqual(status, "FOCUS_MISMATCH")
        self.assertIn("divides exactly", reason)
        inexact = scenario(operations=[expense(
            amount="100.0", aa=["alice", "bob", "carol"], payments={"alice": "100.0"})])
        self.assertEqual(self.verdict(inexact, "aa_rounding")[0], "FOCUS_VALID")

    def test_manual_split_needs_two_different_bearers(self):
        good = scenario(operations=[expense(
            payments={"alice": "100.0"}, splits={"bob": "60.0", "carol": "40.0"})])
        self.assertEqual(self.verdict(good, "manual_split")[0], "FOCUS_VALID")
        single = scenario(operations=[expense(payments={"alice": "100.0"}, splits={"bob": "100.0"})])
        self.assertEqual(self.verdict(single, "manual_split")[0], "FOCUS_MISMATCH")

    def test_targeted_repayment_must_be_strictly_partial(self):
        operations = [
            expense(payments={"alice": "100.0"}, splits={"bob": "100.0"}),
            {"type": "targeted_repayment", "ref": "repay_1", "from_participant": "bob",
             "to_participant": "alice", "amount": "40.0", "currency": "CNY",
             "target_expense_refs": ["expense_1"]},
        ]
        self.assertEqual(self.verdict(scenario(operations=operations), "targeted_repayment")[0], "FOCUS_VALID")
        full = deepcopy(operations)
        full[1]["amount"] = "100.0"
        status, reason = self.verdict(scenario(operations=full), "targeted_repayment")
        self.assertEqual(status, "FOCUS_MISMATCH")
        self.assertIn("strictly partial", reason)

    def test_targeted_repayment_rejects_a_wrong_direction(self):
        operations = [
            expense(payments={"alice": "100.0"}, splits={"bob": "100.0"}),
            {"type": "targeted_repayment", "ref": "repay_1", "from_participant": "alice",
             "to_participant": "bob", "amount": "40.0", "currency": "CNY",
             "target_expense_refs": ["expense_1"]},
        ]
        status, reason = self.verdict(scenario(operations=operations), "targeted_repayment")
        self.assertEqual(status, "FOCUS_MISMATCH")
        self.assertIn("direction", reason)

    def test_fifo_repayment_allows_full_settlement_but_not_overpayment(self):
        base = [
            expense(payments={"alice": "100.0"}, splits={"bob": "100.0"}),
            {"type": "fifo_repayment", "ref": "repay_1", "from_participant": "bob",
             "to_participant": "alice", "amount": "100.0", "currency": "CNY"},
        ]
        self.assertEqual(self.verdict(scenario(operations=base), "fifo_repayment")[0], "FOCUS_VALID")
        over = deepcopy(base)
        over[1]["amount"] = "110.0"
        self.assertEqual(self.verdict(scenario(operations=over), "fifo_repayment")[0], "FOCUS_MISMATCH")

    def test_multiple_repayments_needs_two_instalments_within_the_debt(self):
        operations = [
            expense(payments={"alice": "100.0"}, splits={"bob": "100.0"}),
            {"type": "fifo_repayment", "ref": "r1", "from_participant": "bob",
             "to_participant": "alice", "amount": "30.0", "currency": "CNY"},
            {"type": "fifo_repayment", "ref": "r2", "from_participant": "bob",
             "to_participant": "alice", "amount": "20.0", "currency": "CNY"},
        ]
        self.assertEqual(self.verdict(scenario(operations=operations), "multiple_repayments")[0], "FOCUS_VALID")
        single = operations[:2]
        status, reason = self.verdict(scenario(operations=single), "multiple_repayments")
        self.assertEqual(status, "FOCUS_MISMATCH")
        self.assertIn("at least 2 repayments", reason)

    def test_prepayment_before_debt_needs_the_owner_to_owe_afterwards(self):
        good = scenario(operations=[
            {"type": "create_prepayment", "ref": "prepay_1", "owner_participant": "alice",
             "custodian_participant": "bob", "amount": "100.0", "currency": "CNY"},
            expense(payments={"bob": "100.0"}, splits={"alice": "60.0", "bob": "40.0"}),
        ])
        self.assertEqual(self.verdict(good, "prepayment_before_debt")[0], "FOCUS_VALID")
        backwards = scenario(operations=[
            {"type": "create_prepayment", "ref": "prepay_1", "owner_participant": "alice",
             "custodian_participant": "bob", "amount": "100.0", "currency": "CNY"},
            expense(payments={"alice": "100.0"}, splits={"bob": "100.0"}),
        ])
        status, reason = self.verdict(backwards, "prepayment_before_debt")
        self.assertEqual(status, "FOCUS_MISMATCH")
        self.assertIn("owner", reason)

    def test_prepayment_after_debt_requires_the_expense_first(self):
        good = scenario(operations=[
            expense(payments={"bob": "100.0"}, splits={"alice": "60.0", "bob": "40.0"}),
            {"type": "create_prepayment", "ref": "prepay_1", "owner_participant": "alice",
             "custodian_participant": "bob", "amount": "100.0", "currency": "CNY"},
        ])
        self.assertEqual(self.verdict(good, "prepayment_after_debt")[0], "FOCUS_VALID")
        reordered = scenario(operations=list(reversed(good["operations"])))
        self.assertEqual(self.verdict(reordered, "prepayment_after_debt")[0], "FOCUS_MISMATCH")

    def test_prepayment_return_cannot_exceed_the_prepayment(self):
        good = scenario(operations=[
            {"type": "create_prepayment", "ref": "prepay_1", "owner_participant": "alice",
             "custodian_participant": "bob", "amount": "100.0", "currency": "CNY"},
            {"type": "return_prepayment", "ref": "return_1", "owner_participant": "alice",
             "custodian_participant": "bob", "amount": "40.0", "currency": "CNY"},
        ])
        self.assertEqual(self.verdict(good, "prepayment_return")[0], "FOCUS_VALID")
        too_much = deepcopy(good)
        too_much["operations"][1]["amount"] = "120.0"
        self.assertEqual(self.verdict(too_much, "prepayment_return")[0], "FOCUS_MISMATCH")

    def test_linked_refund_requires_receiver_to_differ_from_beneficiary(self):
        good = scenario(operations=[
            expense(payments={"alice": "100.0"}, splits={"bob": "100.0"}),
            expense(ref="refund_1", amount="-40.0", original_expense_ref="expense_1",
                    payments={"alice": "-40.0"}, splits={"bob": "-40.0"}),
        ])
        self.assertEqual(self.verdict(good, "linked_refund")[0], "FOCUS_VALID")
        degenerate = scenario(operations=[
            expense(payments={"alice": "100.0"}, splits={"bob": "100.0"}),
            expense(ref="refund_1", amount="-40.0", original_expense_ref="expense_1",
                    payments={"alice": "-40.0"}, splits={"alice": "-40.0"}),
        ])
        status, reason = self.verdict(degenerate, "linked_refund")
        self.assertEqual(status, "FOCUS_MISMATCH")
        self.assertIn("receiver and beneficiary", reason)

    def test_negative_expense_rejects_a_linked_refund(self):
        standalone = scenario(operations=[
            expense(amount="-50.0", payments={"alice": "-50.0"}, splits={"bob": "-50.0"}),
        ])
        self.assertEqual(self.verdict(standalone, "negative_expense")[0], "FOCUS_VALID")
        linked = scenario(operations=[
            expense(payments={"alice": "100.0"}, splits={"bob": "100.0"}),
            expense(ref="refund_1", amount="-40.0", original_expense_ref="expense_1",
                    payments={"alice": "-40.0"}, splits={"bob": "-40.0"}),
        ])
        status, reason = self.verdict(linked, "negative_expense")
        self.assertEqual(status, "FOCUS_MISMATCH")
        self.assertIn("linked refund", reason)

    def test_void_transfer_must_reference_a_real_transfer(self):
        good = scenario(operations=[
            expense(payments={"alice": "100.0"}, splits={"bob": "100.0"}),
            {"type": "fifo_repayment", "ref": "repay_1", "from_participant": "bob",
             "to_participant": "alice", "amount": "40.0", "currency": "CNY"},
            {"type": "void_transfer", "transfer_ref": "repay_1", "reason": "mistake"},
        ])
        self.assertEqual(self.verdict(good, "void_transfer")[0], "FOCUS_VALID")
        # A void that points at a non-transfer is stopped earlier, by the Loader,
        # so the focus contract never sees it.
        broken = deepcopy(good)
        broken["operations"][2]["transfer_ref"] = "expense_1"
        with self.assertRaises(ScenarioValidationError):
            self.parse(broken)

    def test_void_transfer_requires_a_void_operation(self):
        no_void = scenario(operations=[
            expense(payments={"alice": "100.0"}, splits={"bob": "100.0"}),
            {"type": "fifo_repayment", "ref": "repay_1", "from_participant": "bob",
             "to_participant": "alice", "amount": "40.0", "currency": "CNY"},
            {"type": "fifo_repayment", "ref": "repay_2", "from_participant": "bob",
             "to_participant": "alice", "amount": "10.0", "currency": "CNY"},
        ])
        status, reason = self.verdict(no_void, "void_transfer")
        self.assertEqual(status, "FOCUS_MISMATCH")
        self.assertIn("void_transfer", reason)

    def test_mixed_flow_needs_breadth(self):
        good = scenario(operations=[
            expense(payments={"alice": "100.0"}, splits={"bob": "60.0", "alice": "40.0"}),
            {"type": "targeted_repayment", "ref": "repay_1", "from_participant": "bob",
             "to_participant": "alice", "amount": "30.0", "currency": "CNY",
             "target_expense_refs": ["expense_1"]},
            {"type": "create_prepayment", "ref": "prepay_1", "owner_participant": "carol",
             "custodian_participant": "alice", "amount": "50.0", "currency": "CNY"},
            expense(ref="refund_1", amount="-20.0", original_expense_ref="expense_1",
                    payments={"carol": "-20.0"}, splits={"bob": "-20.0"}),
        ])
        self.assertEqual(self.verdict(good, "mixed_flow")[0], "FOCUS_VALID")
        shallow = scenario(operations=good["operations"][:3])
        status, reason = self.verdict(shallow, "mixed_flow")
        self.assertEqual(status, "FOCUS_MISMATCH")
        self.assertIn("at least 4 operations", reason)
        without_prepayment = scenario(operations=[
            good["operations"][0], good["operations"][1], good["operations"][3],
            {"type": "fifo_repayment", "ref": "repay_2", "from_participant": "bob",
             "to_participant": "alice", "amount": "10.0", "currency": "CNY"},
        ])
        self.assertEqual(self.verdict(without_prepayment, "mixed_flow")[0], "FOCUS_MISMATCH")

    # -- the historical smoke scenarios ------------------------------------

    def test_historical_smoke_contracts_still_accept_their_own_shape(self):
        aa = scenario(operations=[expense(
            amount="120.0", aa=["alice", "bob", "carol"], payments={"alice": "60.0", "bob": "60.0"})])
        self.assertEqual(self.verdict(aa, "expense_aa")[0], "FOCUS_VALID")
        prepayment_refund = scenario(operations=[
            {"type": "create_prepayment", "ref": "prepay_1", "owner_participant": "alice",
             "custodian_participant": "bob", "amount": "50.0", "currency": "CNY"},
            expense(amount="120.0", payments={"alice": "120.0"},
                    splits={"bob": "60.0", "carol": "60.0"}),
            expense(ref="refund_1", amount="-30.0", original_expense_ref="expense_1",
                    payments={"alice": "-30.0"}, splits={"alice": "-30.0"}),
        ])
        self.assertEqual(self.verdict(prepayment_refund, "prepayment_refund")[0], "FOCUS_VALID")


if __name__ == "__main__":
    unittest.main()
