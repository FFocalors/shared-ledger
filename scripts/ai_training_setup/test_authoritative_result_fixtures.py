import json
import unittest
from pathlib import Path
from scripts.ai_training_setup.validate_authoritative_result_fixtures import binding_errors, resolve_legacy_alias, validate

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/ai/dataset/experiments/v0.2/authoritative_result_fixtures"

class BindingValidationTests(unittest.TestCase):
    def test_same_result_id_cannot_bind_to_two_scenario_tools(self):
        rows = [
            {"scenario_id":"scenario_a", "tool":"get_debt", "result":{"result_id":"r-1"}},
            {"scenario_id":"scenario_b", "tool":"get_final_settlement", "result":{"result_id":"r-1"}},
        ]
        self.assertTrue(any("conflicting bindings" in e for e in binding_errors(rows)))

    def test_unique_result_id_binding_passes(self):
        rows = [{"scenario_id":"scenario_a", "tool":"get_debt", "result":{"result_id":"r-1"}}]
        self.assertEqual([], binding_errors(rows))

    def test_legacy_collision_cannot_be_resolved_without_scope(self):
        registry = json.loads((OUT / "fixture_registry.json").read_text(encoding="utf-8"))
        legacy = registry["legacy_id_conflicts"][0]["legacy_result_id"]
        with self.assertRaisesRegex(ValueError, "exact Scenario and Tool"):
            resolve_legacy_alias(registry["reserved_alias_bindings"], legacy)
        for binding in registry["legacy_id_conflicts"][0]["bindings"]:
            resolved = resolve_legacy_alias(registry["reserved_alias_bindings"], legacy, binding["scenario_id"], binding["tool"])
            self.assertEqual(binding["reserved_unique_fixture_id"], resolved)

    def test_static_policy_does_not_claim_current_refund_total(self):
        doc = json.loads((OUT / "sample_rebuildability.json").read_text(encoding="utf-8"))
        rows = [x for x in doc["samples"] if x["scenario_id"] == "scenario_gs_p0b_037"]
        self.assertTrue(rows)
        self.assertTrue(all(not x["rebuildable"] for x in rows))
        self.assertTrue(all("current cumulative refund amount" in x["blocker"] for x in rows))

if __name__ == "__main__":
    unittest.main()
