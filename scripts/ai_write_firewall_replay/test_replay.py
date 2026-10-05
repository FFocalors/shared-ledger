import importlib.util
import json
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("replay.py")
spec = importlib.util.spec_from_file_location("write_firewall_replay", SCRIPT)
replay = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = replay
spec.loader.exec_module(replay)


class FirewallReplayControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ev = replay.load_frozen_evaluator()
        cls.schema = replay.load_json(replay.SCHEMA_PATH)
        cls.catalog = replay.load_json(replay.TOOL_PATH)
        cls.intent_catalog = replay.load_json(replay.INTENT_PATH)
        cls.intents = {x["intent_id"]: x for x in cls.intent_catalog["intents"]}
        cls.tools = {x["tool_name"]: x for x in cls.catalog["tools"]}
        cls.controls = replay.load_json(replay.CONTROLS_PATH)

    def test_model_l1_l2_valid_calls_are_commonpass_and_capability_differs(self):
        for control in self.controls["model_origin_controls"]:
            if control["control_id"] not in {
                "model_l1_create_expense_valid_with_user_claim",
                "model_l2_void_transfer_valid_with_untrusted_external_claim",
                "model_output_valid_shape_cannot_use_untrusted_simulator_event",
            }:
                continue
            with self.subTest(control=control["control_id"]):
                raw = json.dumps(control["model_output"], ensure_ascii=False, separators=(",", ":"))
                common = replay.common_model_output_check(
                    raw, {control["model_output"]["tool"]}, self.ev, self.schema,
                    self.catalog, self.intents, self.tools,
                )
                self.assertTrue(common["pass"], common["rejections"])
                self.assertEqual(replay.model_origin_arm_decision(common, "arm0"), "hypothetical_model_origin_write_capable_noop")
                self.assertEqual(replay.model_origin_arm_decision(common, "arm1"), "denied_model_origin_write_noop")

    def test_frozen_allowlisted_read_passes_unchanged_in_both_arms(self):
        control = self.controls["read_positive_controls"][0]
        raw = json.dumps(control["model_output"], ensure_ascii=False, separators=(",", ":"))
        common = replay.common_model_output_check(
            raw, set(control["runtime_enabled_tools"]), self.ev, self.schema,
            self.catalog, self.intents, self.tools,
        )
        self.assertTrue(common["pass"], common["rejections"])
        self.assertEqual(replay.model_origin_arm_decision(common, "arm0"), "unchanged_noop")
        self.assertEqual(replay.model_origin_arm_decision(common, "arm1"), "unchanged_noop")

    def test_model_cannot_promote_itself_to_trusted_origin(self):
        control = next(x for x in self.controls["model_origin_controls"] if x["control_id"] == "model_output_extra_origin_confirmed_fields_common_reject")
        raw = json.dumps(control["model_output"], ensure_ascii=False, separators=(",", ":"))
        common = replay.common_model_output_check(
            raw, {"void_transfer"}, self.ev, self.schema, self.catalog, self.intents, self.tools,
        )
        self.assertFalse(common["pass"])
        self.assertIn("frozen_model_output_schema_invalid", common["rejections"])
        self.assertEqual(replay.model_origin_arm_decision(common, "arm1"), "common_reject")

    def test_trusted_positive_invalid_binding_and_d4_controls(self):
        results = []
        for control in self.controls["trusted_origin_controls"]:
            results.append(replay.executor_control_check(
                control, self.ev, self.schema, self.catalog, self.intents, self.tools,
            ))
        by_id = {x["control_id"]: x for x in results}
        self.assertEqual(by_id["trusted_l1_create_expense_exact_confirmation_current_binding"]["decision"], "allow_to_noop_recorder")
        self.assertEqual(by_id["trusted_l2_void_transfer_exact_confirmation_current_binding"]["decision"], "allow_to_noop_recorder")
        for cid in (
            "trusted_l2_void_transfer_forged_confirmation",
            "trusted_l2_void_transfer_stale_financial_version",
            "trusted_l2_void_transfer_payload_entity_mismatch",
            "trusted_l2_void_transfer_payload_digest_mismatch",
            "trusted_l2_void_transfer_actor_activity_conversation_mismatch",
            "trusted_l2_void_transfer_confirmation_tool_intent_substitution",
            "trusted_l2_void_transfer_missing_required_binding",
            "trusted_d4_update_expense_even_with_exact_confirmation",
        ):
            with self.subTest(control=cid):
                self.assertEqual(by_id[cid]["decision"], "reject_noop")
        self.assertTrue(all(x["actual_executor_invocations"] == 0 for x in results))
        exact_l1 = by_id["trusted_l1_create_expense_exact_confirmation_current_binding"]
        self.assertEqual(exact_l1["trusted_command_source"], "simulator_trusted_proposal_command_registry")
        self.assertEqual(exact_l1["canonical_command_recorded_to_noop"]["tool"], "create_expense")
        substitution = by_id["trusted_l2_void_transfer_confirmation_tool_intent_substitution"]
        self.assertIn("simulator_confirmation_tool_mismatch", substitution["rejections"])
        self.assertIn("simulator_confirmation_intent_mismatch", substitution["rejections"])
        missing = by_id["trusted_l2_void_transfer_missing_required_binding"]
        self.assertIn("current_required_binding_missing:financial_version", missing["rejections"])


if __name__ == "__main__":
    unittest.main()
