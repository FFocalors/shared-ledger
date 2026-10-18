"""Focused T1 generator/replay/leakage regression tests (no model/backend calls)."""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from agent.app import contracts as c
from agent.evaluation.data_generate import AGENT, family_fixture, fixture_payload, iso, dt, all_records, assert_request_gold_consistency
from agent.evaluation.data_simulator import simulate_read
from agent.evaluation.data_validate import DatasetValidationError, make_envelope_validator, validate_record, validate_jsonl


class T1DataPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = make_envelope_validator(AGENT)

    def test_all_111_rows_validate_in_memory_and_request_matches_gold(self):
        bundles = all_records()
        self.assertEqual({key: len(value) for key, value in bundles.items()}, {"train": 37, "validation": 37, "sealed": 37})
        for rows in bundles.values():
            for row in rows:
                validate_record(row, self.validator)
                assert_request_gold_consistency(row)

    def test_expense_update_only_changes_currency_on_explicit_unlocked_target(self):
        for split, rows in all_records().items():
            row = next(item for item in rows if item["expected"]["task_operation"] == "expense.update")
            model = next(step for step in row["trace"] if step["kind"] == "model")
            prompt = model["context"]["input_text"]
            target = model["target"]["fields"]
            self.assertEqual({key for key, value in target.items() if value is not None}, {"kind", "expense_ref", "original_currency"})
            self.assertIn(target["expense_ref"], prompt)
            self.assertEqual(target["expense_ref"], row["fixture_state"]["expenses"][0]["expense_ref"])
            self.assertFalse(row["fixture_state"]["expenses"][0]["financial_locked"])
            self.assertNotEqual(target["original_currency"], row["fixture_state"]["expenses"][0]["original_currency"])

    def test_clarification_has_concrete_fields_and_only_amount_missing(self):
        for split, rows in all_records().items():
            clarification = next(item for item in rows if item["case_type"] == "clarification")
            multi_turn = next(item for item in rows if item["case_type"] == "multi_turn")
            clarify_model = next(step for step in clarification["trace"] if step["kind"] == "model")
            first_turn = next(step for step in multi_turn["trace"] if step["kind"] == "model")
            self.assertEqual(clarify_model["target"]["missing_slots"], ["original_amount"])
            self.assertEqual(first_turn["target"]["kind"], "clarify")
            self.assertEqual(first_turn["target"]["missing_slots"], ["original_amount"])
            self.assertEqual(clarify_model["context"]["input_text"], first_turn["context"]["input_text"])
            followup = next(step["text"] for step in multi_turn["trace"] if step["kind"] == "user_followup")
            self.assertRegex(followup, r"^金额是[0-9]+\.[0-9]{2}。$")

    def test_expense_simulator_applies_date_and_participant_filters(self):
        fx, _, pattern = family_fixture("train", 0, "read.expenses", 2)
        fixture = fixture_payload(fx, 0, pattern)
        first = fixture["expenses"][0]
        decision = c.ReadDecision(
            kind="read", operation=c.ReadOperation.EXPENSES,
            criteria=c.ReadExpensesCriteria(
                kind="expenses", activity_ref=fx["arefs"][0],
                to_date=date.fromisoformat(first["occurred_at"][:10]),
                participant_ref=c.ParticipantRef(first["participant_refs"][1]),
            ),
        )
        result = simulate_read(fixture, decision, observed_at=dt(0, 40), context_version=1, replay_key="test-expense-filter")
        self.assertEqual([item.expense_ref for item in result.body.items], [c.ExpenseRef(first["expense_ref"])])

    def test_debt_simulator_preserves_direction_and_filters_currency(self):
        fx, _, pattern = family_fixture("validation", 1, "read.debts", 2)
        fixture = fixture_payload(fx, 1, pattern, debt_count=5)
        first = fixture["debts"][0]
        decision = c.ReadDecision(
            kind="read", operation=c.ReadOperation.DEBTS,
            criteria=c.ReadDebtsCriteria(
                kind="debts", activity_ref=fx["arefs"][0], currency=first["currency"],
                participant_ref=c.ParticipantRef(first["debtor_ref"]),
            ),
        )
        result = simulate_read(fixture, decision, observed_at=dt(1, 41), context_version=1, replay_key="test-debt-filter")
        self.assertGreaterEqual(len(result.body.items), 1)
        self.assertEqual(result.body.items[0].debtor_ref.value, first["debtor_ref"])
        self.assertEqual(result.body.items[0].creditor_ref.value, first["creditor_ref"])
        self.assertTrue(all(item.currency == first["currency"] for item in result.body.items))

    def test_tampered_saved_result_is_rejected_by_replay(self):
        row = next(item for item in all_records()["train"] if item["expected"]["task_operation"] == "read.expenses")
        tool = next(step for step in row["trace"] if step["kind"] == "tool_result")
        tool["result"]["body"]["items"][0]["original_amount"] = "999.00"
        with self.assertRaises(DatasetValidationError):
            validate_record(row, self.validator)

    def test_sealed_request_denies_before_any_file_open(self):
        sealed = Path(r"D:\AI\runs\shared-ledger\t1\data\sealed.jsonl")
        with patch.object(Path, "open", side_effect=AssertionError("must not open sealed")), patch.object(
            Path, "read_bytes", side_effect=AssertionError("must not read sealed")
        ):
            with self.assertRaises(DatasetValidationError):
                validate_jsonl(sealed, expected_split="sealed", agent_root=AGENT)


if __name__ == "__main__":
    unittest.main()
