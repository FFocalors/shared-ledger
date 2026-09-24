from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from shared_ledger_verifier.runner import _business_logic_commit, run_scenario
from shared_ledger_verifier.supabase import SupabaseConfigurationError, SupabaseRestClient


ROOT = Path(__file__).resolve().parents[1]


class FakeSupabase:
    def __init__(self) -> None:
        self.version = 0
        self.rpc_calls: list[tuple[str, dict]] = []
        self.closed = False

    def create_test_user(self) -> str:
        return "test-user"

    def rpc(self, name: str, payload: dict) -> list[dict]:
        self.rpc_calls.append((name, payload))
        if name == "create_activity":
            return [{"activity_id": "activity-1"}]
        if name == "create_participant":
            return [{"participant_id": f"participant-{payload['name'].lower()}"}]
        if name == "create_expense_auto_rate":
            self.version += 1
            return [{"expense_id": "expense-1", "base_amount": Decimal("100.0"), "version": 1}]
        if name == "create_expense_repayment_v2":
            self.version += 1
            return [
                {
                    "transfer_id": "transfer-1",
                    "amount": payload["amount"],
                    "currency": payload["currency"],
                    "financial_version": self.version,
                }
            ]
        raise AssertionError(f"unexpected RPC {name}")

    def select(self, table: str, *, filters=None, columns="*", limit=1000):
        if table == "activities":
            if columns == "financial_version":
                return [{"financial_version": self.version}]
            return [
                {
                    "id": "activity-1",
                    "type": "normal",
                    "base_currency": "CNY",
                    "multi_currency_enabled": False,
                    "financial_version": self.version,
                }
            ]
        if table == "ledger_units":
            return [{"id": "root-1", "type": "default", "name": "Shared", "is_deleted": False}]
        if table == "participants":
            return [
                {"id": "participant-a", "name": "A", "participant_order": 0, "is_deleted": False},
                {"id": "participant-b", "name": "B", "participant_order": 1, "is_deleted": False},
            ]
        if table == "expenses":
            return [
                {
                    "id": "expense-1",
                    "ledger_unit_id": "root-1",
                    "title": "Lunch",
                    "original_amount": Decimal("100.0"),
                    "original_currency": "CNY",
                    "fx_rate": Decimal("1"),
                    "base_amount": Decimal("100.0"),
                    "split_method": "manual",
                    "original_expense_id": None,
                    "is_deleted": False,
                    "financial_locked": True,
                }
            ]
        if table == "payments":
            return [{"expense_id": "expense-1", "participant_id": "participant-a", "amount": Decimal("100.0"), "base_amount": Decimal("100.0")}]
        if table == "splits":
            return [{"expense_id": "expense-1", "participant_id": "participant-b", "amount": Decimal("100.0"), "base_amount": Decimal("100.0")}]
        if table == "expense_debts":
            return [
                {
                    "id": "debt-1",
                    "expense_id": "expense-1",
                    "debtor_participant_id": "participant-b",
                    "creditor_participant_id": "participant-a",
                    "amount": Decimal("100.0"),
                    "original_amount": Decimal("100.0"),
                    "original_currency": "CNY",
                }
            ]
        if table == "bilateral_debts":
            return []
        if table == "transfers":
            return [{"id": "transfer-1", "from_participant_id": "participant-b", "to_participant_id": "participant-a", "type": "settlement", "amount": Decimal("40.0"), "currency": "CNY", "is_voided": False}]
        if table == "transfer_components":
            return [{"transfer_id": "transfer-1", "component_type": "settlement", "amount": Decimal("40.0")}]
        if table == "transfer_allocations":
            return [{"transfer_id": "transfer-1", "expense_debt_id": "debt-1", "amount": Decimal("40.0"), "original_amount": Decimal("40.0"), "base_amount": Decimal("40.0")}]
        if table == "transfer_expense_allocations":
            return [{"transfer_id": "transfer-1", "expense_id": "expense-1", "debtor_participant_id": "participant-b", "creditor_participant_id": "participant-a", "allocation_mode": "TARGETED", "payment_currency": "CNY", "payment_amount": Decimal("40.0"), "original_currency": "CNY", "original_amount": Decimal("40.0"), "base_amount": Decimal("40.0")}]
        if table in {"prepayment_accounts", "prepayment_usages", "final_settlement_paths"}:
            return []
        if table == "activity_financial_status":
            return [{"financial_status": "active", "completed": False, "has_unsettled_debt": True, "total_debt": Decimal("60.0"), "total_prepayment": Decimal("0.0"), "prepayment_by_currency": [], "financial_version": self.version}]
        raise AssertionError(f"unexpected table {table}")

    def close(self) -> None:
        self.closed = True


class RunnerTests(unittest.TestCase):
    def test_business_logic_commit_tracks_rules_and_migrations(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=f"{'b' * 40}\n", stderr=""
        )
        with patch("shared_ledger_verifier.runner.subprocess.run", return_value=completed) as run_git:
            commit = _business_logic_commit()

        self.assertEqual(commit, "b" * 40)
        self.assertEqual(
            run_git.call_args.args[0],
            ["git", "log", "-n1", "--format=%H", "--", "docs/backend/BUSINESS_LOGIC.md", "supabase/migrations"],
        )

    def test_authenticated_targeted_run_uses_fresh_version_and_decimal_strings(self) -> None:
        client = FakeSupabase()
        scenario = ROOT / "scenarios" / "smoke" / "targeted_partial_repayment.json"
        with tempfile.TemporaryDirectory() as temporary:
            result = run_scenario(scenario, runs_dir=temporary, client=client)
            self.assertEqual(result["status"], "EXECUTED")
            self.assertEqual(result["operation_count"], 2)
            name, payload = next(call for call in client.rpc_calls if call[0] == "create_expense_repayment_v2")
            self.assertEqual(name, "create_expense_repayment_v2")
            self.assertEqual(payload["mode"], "TARGETED")
            self.assertEqual(payload["expected_financial_version"], 1)
            self.assertEqual(payload["amount"], "40.0")
            self.assertIsInstance(payload["amount"], str)
            self.assertTrue(payload["request_id"])
            self.assertEqual(payload["on_behalf_of_participant_id"], "participant-b")
            run_dir = Path(result["run_dir"])
            self.assertEqual(
                {path.name for path in run_dir.iterdir()},
                {"scenario.json", "result.json", "operations.jsonl", "state_final.json"},
            )
            final_state = json.loads((run_dir / "state_final.json").read_text(encoding="utf-8"))
            self.assertEqual(final_state["expenses"][0]["ref"], "expense_1")
            self.assertEqual(final_state["bilateral_debts"], [])
            durable = final_state["transfer_expense_allocations"][0]
            self.assertEqual(durable["transfer_ref"], "transfer_1")
            self.assertEqual(durable["payment_amount"], "40.0")
        self.assertTrue(client.closed)

    def test_invalid_scenario_writes_all_artifacts_without_auth(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "invalid.json"
            source.write_text('{"schema_version": 1.25}', encoding="utf-8")
            result = run_scenario(source, runs_dir=Path(temporary) / "runs")
            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["error_code"], "SCENARIO_FORMAT")
            run_dir = Path(result["run_dir"])
            self.assertEqual(
                {path.name for path in run_dir.iterdir()},
                {"scenario.json", "result.json", "operations.jsonl", "state_final.json"},
            )
            self.assertEqual((run_dir / "scenario.json").read_text(encoding="utf-8"), '{"schema_version": 1.25}')

    def test_supabase_client_rejects_remote_urls_and_service_role_keys(self) -> None:
        with self.assertRaises(SupabaseConfigurationError):
            SupabaseRestClient("https://example.supabase.co", "anon-key")
        with self.assertRaises(SupabaseConfigurationError):
            SupabaseRestClient("http://127.0.0.1:54321", "service_role")
        client = SupabaseRestClient("http://localhost:54321", "anon-key")
        self.assertEqual(client.url, "http://localhost:54321")


if __name__ == "__main__":
    unittest.main()
