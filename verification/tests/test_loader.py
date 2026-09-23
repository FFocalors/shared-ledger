from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from shared_ledger_verifier import (
    CreateExpense,
    LinkedRefund,
    CreatePrepayment,
    FifoRepayment,
    ReturnPrepayment,
    ScenarioValidationError,
    TargetedRepayment,
    VoidTransfer,
    load_scenario,
)


class ScenarioLoaderTests(unittest.TestCase):
    def write_scenario(self, document: dict) -> Path:
        folder = Path(tempfile.mkdtemp())
        path = folder / "scenario.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def base_document(self) -> dict:
        return {
            "schema_version": 1,
            "scenario_id": "loader_smoke",
            "description": "Simple expense and repayment",
            "activity": {
                "type": "normal",
                "base_currency": "CNY",
                "multi_currency_enabled": False,
            },
            "participants": ["A", "B"],
            "operations": [
                {
                    "type": "create_expense",
                    "ref": "expense_1",
                    "title": "Lunch",
                    "amount": "100.0",
                    "currency": "CNY",
                    "payments": {"A": "100.0"},
                    "splits": {"B": "100.0"},
                },
                {
                    "type": "targeted_repayment",
                    "ref": "transfer_1",
                    "from_participant": "B",
                    "to_participant": "A",
                    "amount": "40.0",
                    "currency": "CNY",
                    "target_expense_refs": ["expense_1"],
                },
            ],
        }

    def test_loads_decimal_values_and_forwarded_refs(self) -> None:
        scenario = load_scenario(self.write_scenario(self.base_document()))

        expense, repayment = scenario.operations
        self.assertIsInstance(expense, CreateExpense)
        self.assertEqual(expense.amount, Decimal("100.0"))
        self.assertEqual(expense.payments["A"], Decimal("100.0"))
        self.assertIsInstance(repayment, TargetedRepayment)
        self.assertEqual(repayment.target_expense_refs, ("expense_1",))
        self.assertEqual(repayment.amount, Decimal("40.0"))

    def test_aa_and_linked_refund_are_typed(self) -> None:
        document = self.base_document()
        document["participants"] = ["A", "B", "C"]
        document["operations"] = [
            {
                "type": "create_expense",
                "ref": "expense_1",
                "title": "Dinner",
                "amount": "90.0",
                "currency": "CNY",
                "payments": {"A": "90.0"},
                "split_method": "aa",
                "aa_participants": ["A", "B", "C"],
            },
            {
                "type": "linked_refund",
                "ref": "refund_1",
                "original_expense_ref": "expense_1",
                "title": "Partial refund",
                "amount": "-10.0",
                "currency": "CNY",
                "payments": {"B": "-10.0"},
                "split_method": "manual",
                "splits": {"A": "-10.0"},
            },
        ]

        scenario = load_scenario(self.write_scenario(document))
        self.assertEqual(scenario.operations[0].aa_participants, ("A", "B", "C"))
        self.assertIsInstance(scenario.operations[1], LinkedRefund)

    def test_rejects_json_float_amount(self) -> None:
        text = json.dumps(self.base_document()).replace('"100.0"', "100.0", 1)
        path = Path(tempfile.mkdtemp()) / "scenario.json"
        path.write_text(text, encoding="utf-8")

        with self.assertRaisesRegex(ScenarioValidationError, "decimal string"):
            load_scenario(path)

    def test_rejects_unbalanced_expense_and_unknown_database_fields(self) -> None:
        unbalanced = self.base_document()
        unbalanced["operations"][0]["splits"]["B"] = "99.9"
        with self.assertRaisesRegex(ScenarioValidationError, "sum exactly"):
            load_scenario(self.write_scenario(unbalanced))

        with_database_id = self.base_document()
        with_database_id["operations"][0]["expense_id"] = "some-id"
        with self.assertRaisesRegex(ScenarioValidationError, "unknown field"):
            load_scenario(self.write_scenario(with_database_id))

    def test_loads_fifo_prepayment_return_and_void_operations(self) -> None:
        document = self.base_document()
        document["operations"] = [
            {
                "type": "fifo_repayment",
                "ref": "transfer_1",
                "from_participant": "B",
                "to_participant": "A",
                "amount": "20.0",
                "currency": "CNY",
            },
            {
                "type": "create_prepayment",
                "ref": "prepayment_1",
                "owner_participant": "B",
                "custodian_participant": "A",
                "amount": "30.0",
                "currency": "CNY",
            },
            {
                "type": "return_prepayment",
                "ref": "return_1",
                "owner_participant": "B",
                "custodian_participant": "A",
                "amount": "10.0",
                "currency": "CNY",
            },
            {
                "type": "void_transfer",
                "transfer_ref": "prepayment_1",
                "reason": "Entered twice",
            },
        ]

        scenario = load_scenario(self.write_scenario(document))
        self.assertIsInstance(scenario.operations[0], FifoRepayment)
        self.assertIsInstance(scenario.operations[1], CreatePrepayment)
        self.assertIsInstance(scenario.operations[2], ReturnPrepayment)
        self.assertIsInstance(scenario.operations[3], VoidTransfer)

    def test_enforces_one_decimal_for_base_currency_expense(self) -> None:
        document = self.base_document()
        expense = document["operations"][0]
        expense["amount"] = "100.01"
        expense["payments"]["A"] = "100.01"
        expense["splits"]["B"] = "100.01"

        with self.assertRaisesRegex(ScenarioValidationError, "at most 1 fractional digit"):
            load_scenario(self.write_scenario(document))


if __name__ == "__main__":
    unittest.main()
