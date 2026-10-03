"""Focused checks for local Backend receipt replay, schema and scope binding."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/ai/dataset/experiments/v0.2/authoritative_backend_receipts"
sys.path.insert(0, str(ROOT / "scripts/ai_training_setup"))
from authoritative_backend_receipt_harness import build  # noqa: E402
from validate_authoritative_backend_receipts import validate  # noqa: E402
from validate_authoritative_result_fixtures import resolve_legacy_alias  # noqa: E402


class AuthoritativeBackendReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        build()  # Executes only transaction-scoped setup/query/rollback on the local repository DB.

    def test_receipts_match_contract_and_batch_totals_reconcile(self):
        report = validate()
        self.assertEqual("valid", report["status"])
        self.assertEqual(2, report["fixture_count"])
        self.assertEqual(9, report["reconstructable_samples"])
        self.assertEqual(60, report["blocked_samples"])

    def test_ids_bind_uniquely_to_exact_scenario_and_tool(self):
        doc = json.loads((OUT / "result_id_registry.json").read_text(encoding="utf-8"))
        ids = [x["result_id"] for x in doc["bindings"]]
        self.assertEqual(len(ids), len(set(ids)))
        pairs = [(x["scenario_id"], x["tool"]) for x in doc["bindings"]]
        self.assertEqual(len(pairs), len(set(pairs)))
        legacy = doc["legacy_conflicts"][0]["legacy_result_id"]
        with self.assertRaisesRegex(ValueError, "exact Scenario and Tool"):
            resolve_legacy_alias(doc["reserved_alias_bindings"], legacy)
        resolved = [resolve_legacy_alias(doc["reserved_alias_bindings"], legacy, x["scenario_id"], x["tool"]) for x in doc["legacy_conflicts"][0]["bindings"]]
        self.assertEqual(len(resolved), len(set(resolved)))

    def test_all_test_state_is_rolled_back(self):
        doc = json.loads((OUT / "backend_result_fixtures.json").read_text(encoding="utf-8"))
        self.assertTrue(all(f["rollback_verified"] for f in doc["fixtures"]))
        self.assertTrue(all(f["rollback_row_count_after_run"] == 0 for f in doc["fixtures"]))

    def test_dynamic_probe_uses_database_events_and_is_not_sample_coverage(self):
        run = json.loads((OUT / "pilot_run.json").read_text(encoding="utf-8"))
        probe = run["dynamic_refund_engine_probe"]
        self.assertTrue(probe["harness_only"])
        self.assertFalse(probe["scenario_coverage"])
        self.assertEqual("100.0000", probe["dynamic_result"]["aggregate_original_refund_amount"])
        self.assertTrue(probe["dynamic_result"]["over_limit_insert_rejected"])


if __name__ == "__main__":
    unittest.main()
