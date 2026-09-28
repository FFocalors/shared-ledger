import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
SCRIPT_DIR = HERE.parents[1]
ROOT = HERE.parents[3]
sys.path.insert(0, str(SCRIPT_DIR))

from validator import DatasetValidator  # noqa: E402


class OfflineValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = DatasetValidator(ROOT)
        cls.scenarios = json.loads((ROOT / "docs/ai/dataset/examples/scenarios.json").read_text(encoding="utf-8"))
        cls.samples = json.loads((ROOT / "docs/ai/dataset/examples/samples.json").read_text(encoding="utf-8"))
        cls.canonical_scenarios = json.loads((ROOT / "docs/ai/dataset/gold_seed/v0.1/p0a/scenarios.json").read_text(encoding="utf-8"))
        cls.p0b_scenarios = json.loads((ROOT / "docs/ai/dataset/gold_seed/v0.1/p0b/scenarios.json").read_text(encoding="utf-8"))

    def sample(self, sample_id):
        return copy.deepcopy(next(item for item in self.samples if item["sample_id"] == sample_id))

    @staticmethod
    def codes(report):
        return {issue.code for issue in report.errors}

    def test_01_core_read_sample_passes(self):
        self.assertTrue(self.validator.validate_sample(self.sample("sample_008")).valid)

    def test_02_l1_proposal_passes(self):
        self.assertTrue(self.validator.validate_sample(self.sample("sample_001")).valid)

    def test_03_l2_proposal_passes(self):
        self.assertTrue(self.validator.validate_sample(self.sample("sample_006")).valid)

    def test_04_d4_preview_proposal_passes(self):
        self.assertTrue(self.validator.validate_sample(self.sample("sample_005")).valid)

    def test_05_d4_execution_is_rejected(self):
        sample = self.sample("sample_005")
        sample["expected"]["execution"]["execution_allowed"] = True
        self.assertIn("D4_EXECUTION", self.codes(self.validator.validate_sample(sample)))

    def test_06_deferred_tool_call_is_rejected(self):
        sample = self.sample("sample_007")
        sample["expected"]["output_type"] = "tool_call"
        sample["expected"]["model_output"] = {"type": "tool_call", "intent_id": "delete_activity", "tool": "delete_activity", "arguments": {"activity_id": "00000000-0000-4000-8000-000000000100"}}
        self.assertIn("DEFERRED_OUTPUT", self.codes(self.validator.validate_sample(sample)))

    def test_07_gated_confirmation_level_mismatch_is_rejected(self):
        sample = self.sample("sample_006")
        sample["expected"]["model_output"]["confirmation"]["level"] = 1
        self.assertIn("CONFIRMATION_LEVEL", self.codes(self.validator.validate_sample(sample)))

    def test_08_unknown_intent_is_rejected(self):
        sample = self.sample("sample_001")
        sample["scope"]["intent_ids"] = ["not_an_intent"]
        self.assertIn("INTENT_UNKNOWN", self.codes(self.validator.validate_sample(sample)))

    def test_scenario_evidence_line_must_resolve(self):
        scenario = copy.deepcopy(self.scenarios[0])
        scenario["trust"]["evidence_refs"] = ["docs/ai/AI_MODEL_CONTRACT.md#L999999"]
        report = self.validator.validate_scenario(scenario)
        self.assertIn("EVIDENCE_REF_UNRESOLVED", {issue.code for issue in report.errors})

    def test_scenario_operation_arguments_must_match_state(self):
        scenario = copy.deepcopy(self.canonical_scenarios[0])
        scenario["operation"]["arguments"]["original_amount"] = "91"
        self.assertIn("SCENARIO_OPERATION_ARGUMENTS_MISMATCH", self.codes(self.validator.validate_scenario(scenario)))

    def test_scenario_entity_ids_must_be_unique_and_references_declared(self):
        scenario = copy.deepcopy(self.canonical_scenarios[0])
        scenario["state"]["entities"].append(copy.deepcopy(scenario["state"]["entities"][0]))
        self.assertIn("SCENARIO_ENTITY_ID_DUPLICATE", self.codes(self.validator.validate_scenario(scenario)))

    def test_scenario_formal_entity_references_must_be_declared(self):
        scenario = copy.deepcopy(self.canonical_scenarios[0])
        unknown = "00000000-0000-4000-8000-000000000999"
        scenario["operation"]["arguments"]["payments"][0]["participant_id"] = unknown
        scenario["state"]["facts"]["operation_arguments"]["payments"][0]["participant_id"] = unknown
        scenario["ground_truth"]["model_output"]["operation"]["arguments"]["payments"][0]["participant_id"] = unknown
        report = self.validator.validate_scenario(scenario)
        self.assertIn("SCENARIO_ENTITY_REFERENCE_UNDECLARED", self.codes(report))

    def test_scenario_recorded_facts_reject_duplicates_and_unknown_sources(self):
        scenario = copy.deepcopy(self.canonical_scenarios[0])
        fact = {"field": "amount", "value": "90", "source": "made_up"}
        scenario["state"]["facts"]["recorded_facts"] = [fact, copy.deepcopy(fact)]
        codes = self.codes(self.validator.validate_scenario(scenario))
        self.assertTrue({"SCENARIO_RECORDED_FACT_DUPLICATE", "SCENARIO_RECORDED_FACT_SOURCE"} <= codes)

    def test_scenario_lookup_resolution_requires_matching_candidate_count(self):
        scenario = copy.deepcopy(self.canonical_scenarios[0])
        scenario["state"]["facts"]["supporting_lookup_result"]["candidate_ids"] = []
        self.assertIn("SCENARIO_LOOKUP_RESOLUTION_COUNT", self.codes(self.validator.validate_scenario(scenario)))

    def test_scenario_transfer_projection_uses_frozen_vocabulary(self):
        scenario = copy.deepcopy(next(x for x in self.canonical_scenarios if x["scenario_id"] == "scenario_gs_p0a_011"))
        lookup = scenario["state"]["facts"]["supporting_lookup_result"]
        lookup.pop("is_voided")
        lookup["status"] = "active"
        self.assertIn("SCENARIO_FROZEN_VOCABULARY", self.codes(self.validator.validate_scenario(scenario)))

    def test_09_unknown_tool_is_rejected(self):
        sample = self.sample("sample_001")
        sample["scope"]["tool_ids"] = ["not_a_tool"]
        self.assertIn("TOOL_UNKNOWN", self.codes(self.validator.validate_sample(sample)))

    def test_10_ground_truth_argument_conflict_is_rejected(self):
        samples = copy.deepcopy(self.samples)
        next(x for x in samples if x["sample_id"] == "sample_001")["expected"]["model_output"]["operation"]["arguments"]["original_amount"] = "301"
        report = self.validator.validate_dataset(copy.deepcopy(self.scenarios), samples)
        self.assertIn("GROUND_TRUTH_CONFLICT", self.codes(report))

    def test_11_clarification_annotation_mismatch_is_rejected(self):
        sample = self.sample("sample_010")
        sample["expected"]["clarification_annotation"]["missing_fields"] = ["payments"]
        self.assertIn("CLARIFICATION_ANNOTATION_MISMATCH", self.codes(self.validator.validate_sample(sample)))

    def test_12_ambiguous_entity_selection_is_rejected(self):
        sample = self.sample("sample_004")
        item = sample["expected"]["entity_resolution"][0]
        item["expected_entity_id"] = item["candidate_ids"][0]
        self.assertIn("ENTITY_AMBIGUOUS_SELECTED", self.codes(self.validator.validate_sample(sample)))

    def test_13_split_leakage_is_rejected(self):
        scenarios = copy.deepcopy(self.scenarios)
        next(x for x in scenarios if x["scenario_id"] == "scenario_ui_expense_detail")["split"] = "train"
        report = self.validator.validate_dataset(scenarios, copy.deepcopy(self.samples))
        self.assertIn("SPLIT_LEAKAGE", self.codes(report))

    def test_14_pending_policy_train_assignment_is_rejected(self):
        sample = self.sample("sample_010")
        sample["split"] = "train"
        self.assertIn("PENDING_IN_SPLIT", self.codes(self.validator.validate_sample(sample)))

    def test_15_teacher_provenance_missing_is_rejected(self):
        sample = self.sample("sample_001")
        sample["source"]["surface_form_type"] = "teacher_generated"
        sample["source"]["teacher"] = None
        self.assertIn("TEACHER_PROVENANCE_MISSING", self.codes(self.validator.validate_sample(sample)))

    def test_16_manifest_count_mismatch_is_rejected(self):
        manifest = json.loads((ROOT / "docs/ai/dataset/examples/dataset_manifest.json").read_text(encoding="utf-8"))
        manifest["sample_count"] = 100
        report = self.validator.validate_dataset(copy.deepcopy(self.scenarios), copy.deepcopy(self.samples), manifest)
        self.assertIn("MANIFEST_STATISTICS", self.codes(report))

    def test_17_exact_duplicate_is_rejected(self):
        first = self.sample("sample_001")
        second = copy.deepcopy(first)
        second["sample_id"] = "sample_duplicate"
        self.validator._issues = []
        self.validator._deduplicate([first, second])
        self.assertIn("EXACT_DUPLICATE", self.codes(self.validator._report({})))

    def test_18_normalized_duplicate_is_reported(self):
        first = self.sample("sample_001")
        second = copy.deepcopy(first)
        second["sample_id"] = "sample_normalized"
        second["input"]["user_message"] = " ! ".join(first["input"]["user_message"])
        self.validator._issues = []
        self.validator._deduplicate([first, second])
        report = self.validator._report({})
        self.assertTrue(any(item.code == "NORMALIZED_DUPLICATE" for item in report.warnings))

    def test_19_version_mismatch_is_rejected(self):
        sample = self.sample("sample_001")
        sample["dataset_version"] = "9.9"
        self.assertIn("VERSION_MISMATCH", self.codes(self.validator.validate_sample(sample)))

    def test_20_chat_confirmation_cannot_call_financial_tool(self):
        sample = self.sample("sample_006")
        sample["input"]["user_message"] = "确定"
        sample["surface_form"]["user_message"] = "确定"
        sample["expected"]["output_type"] = "tool_call"
        sample["expected"]["model_output"] = {"type": "tool_call", "intent_id": "create_settlement_transfer", "tool": "create_settlement_transfer", "arguments": sample["expected"]["model_output"]["operation"]["arguments"]}
        self.assertTrue({"CHAT_CONFIRMATION_BYPASS", "WRITE_TOOL_CALL"} & self.codes(self.validator.validate_sample(sample)))

    def test_21_bundled_examples_resolve_catalog_blockers(self):
        report = self.validator.load_dataset(ROOT / "docs/ai/dataset/examples")
        self.assertFalse(any(item.code in {"VALIDATOR_BLOCKER", "INTENT_TOOL_MISMATCH"} for item in report.errors))

    def test_22_supporting_lookup_then_clarification_keeps_business_intent(self):
        sample = self.sample("sample_004")
        self.assertTrue(self.validator.validate_sample(sample).valid)
        self.assertEqual(sample["expected"]["model_output"]["intent_id"], "create_expense")
        self.assertEqual(self.validator._tool_role("create_expense", "find_participants"), "SUPPORTING_LOOKUP")

    def test_23_supporting_lookup_then_primary_tool_is_allowed(self):
        scope = {"intent_ids": ["query_expense"], "tool_ids": ["find_expenses", "get_expense"]}
        context = {"server_context": {"enabled_tools": ["find_expenses", "get_expense"]}}
        execution = {"execution_allowed": False, "confirmation_level": 0, "confirmation_required": False, "successful_execution_label_allowed": False}
        self.validator._issues = []
        self.validator._validate_output({"type": "tool_call", "intent_id": "query_expense", "tool": "find_expenses", "arguments": {"activity_id": "00000000-0000-4000-8000-000000000100", "query": "晚饭"}}, scope, context, execution, "<test>", "lookup", "/output")
        self.validator._validate_output({"type": "tool_call", "intent_id": "query_expense", "tool": "get_expense", "arguments": {"activity_id": "00000000-0000-4000-8000-000000000100", "expense_id": "00000000-0000-4000-8000-000000000101"}}, scope, context, execution, "<test>", "primary", "/output")
        self.assertFalse(self.validator._report({}).errors)

        debt_scope = {"intent_ids": ["query_debt"], "tool_ids": ["find_participants"]}
        debt_context = {"server_context": {"enabled_tools": ["find_participants"]}}
        self.validator._issues = []
        self.validator._validate_output({"type": "tool_call", "intent_id": "query_debt", "tool": "find_participants", "arguments": {"activity_id": "00000000-0000-4000-8000-000000000100", "query": "张三"}}, debt_scope, debt_context, execution, "<test>", "debt-lookup", "/output")
        self.assertFalse(self.validator._report({}).errors)

        execution["successful_execution_label_allowed"] = True
        self.validator._issues = []
        self.validator._validate_output({"type": "tool_call", "intent_id": "query_debt", "tool": "find_participants", "arguments": {"activity_id": "00000000-0000-4000-8000-000000000100"}}, debt_scope, debt_context, execution, "<test>", "lookup-success-label", "/output")
        self.assertIn("SUPPORTING_LOOKUP_SUCCESS_LABEL", self.codes(self.validator._report({})))

    def test_24_unrelated_read_tool_is_rejected(self):
        sample = self.sample("sample_004")
        sample["scope"]["tool_ids"] = ["get_final_settlement"]
        self.assertIn("INTENT_TOOL_MISMATCH", self.codes(self.validator.validate_sample(sample)))

    def test_25_write_tool_cannot_be_supporting_lookup(self):
        intent = self.validator.intents["create_expense"]
        original = list(intent["supporting_lookup_tools"])
        try:
            intent["supporting_lookup_tools"] = ["create_activity"]
            execution = {"execution_allowed": False, "confirmation_level": 0, "confirmation_required": False, "successful_execution_label_allowed": False}
            self.validator._issues = []
            self.validator._validate_output({"type": "tool_call", "intent_id": "create_expense", "tool": "create_activity", "arguments": {"name": "x", "type": "normal", "base_currency": "CNY", "multi_currency_enabled": False}}, {"intent_ids": ["create_expense"], "tool_ids": ["create_activity"]}, None, execution, "<test>", "write-lookup", "/output")
            self.assertIn("SUPPORTING_LOOKUP_WRITE", self.codes(self.validator._report({})))
        finally:
            intent["supporting_lookup_tools"] = original

    def test_26_supporting_lookup_confirmation_must_be_l0(self):
        tool = self.validator.tools["find_participants"]
        original = tool["confirmation_level"]
        try:
            tool["confirmation_level"] = 1
            self.validator._issues = []
            self.validator._scope_record({"scope": {"intent_ids": ["create_expense"], "tool_ids": ["find_participants"]}}, "<test>", "lookup", False)
            self.assertIn("SUPPORTING_LOOKUP_CONFIRMATION", self.codes(self.validator._report({})))
        finally:
            tool["confirmation_level"] = original

    def test_27_scenario_rejects_family_text_and_training_words(self):
        scenario = copy.deepcopy(self.canonical_scenarios[0])
        scenario["title"] = "晚餐分账"
        family_text = scenario["scenario_family_id"]
        scenario["state"]["facts"]["recorded_facts"][0]["value"] = family_text
        scenario["ground_truth"]["model_output"]["preview"]["summary"] = "proposal ready"
        codes = self.codes(self.validator.validate_scenario(scenario))
        self.assertTrue({"SCENARIO_CONTENT_FAMILY_TEXT", "SCENARIO_OUTPUT_META_TEXT"} <= codes)

    def test_28_scenario_rejects_low_quality_evidence_and_unused_entities(self):
        scenario = copy.deepcopy(self.canonical_scenarios[0])
        scenario["trust"]["evidence_refs"] = ["docs/ai/schema/intent_catalog.json#L1"]
        scenario["state"]["entities"].append({"alias": "unused", "id": "00000000-0000-4000-8000-000000000199", "type": "expense", "display_name": "unused", "activity_id": "00000000-0000-4000-8000-000000000100"})
        codes = self.codes(self.validator.validate_scenario(scenario))
        self.assertTrue({"EVIDENCE_REF_LOW_QUALITY", "SCENARIO_ENTITY_UNUSED"} <= codes)

    def test_29_scenario_rejects_clarification_tag_mismatch(self):
        scenario = copy.deepcopy(self.canonical_scenarios[0])
        scenario["rule_tags"] = ["clarification"]
        self.assertIn("SCENARIO_RULE_TAG_OUTPUT_MISMATCH", self.codes(self.validator.validate_scenario(scenario)))

    def test_30_batch_assertion_family_substitution_is_rejected(self):
        first, second = (copy.deepcopy(self.canonical_scenarios[i]) for i in (0, 1))
        first["title"], second["title"] = "早饭分账", "晚饭分账"
        first["ground_truth"]["deterministic_assertions"] = ["用户要求的行为输出 proposal，业务参数与已确认事实完全一致。"]
        second["ground_truth"]["deterministic_assertions"] = ["用户要求的行为输出 proposal，业务参数与已确认事实完全一致。"]
        self.validator._issues = []
        self.validator._validate_scenario_batch_authenticity([first, second], "scenarios.json")
        self.assertIn("SCENARIO_ASSERTION_DUPLICATE", self.codes(self.validator._report({})))

    def test_scenario_context_rule_tag_requires_recorded_state(self):
        scenario = copy.deepcopy(self.canonical_scenarios[0])
        scenario["rule_tags"] = ["ui_context"]
        scenario["state"]["facts"].pop("ui_context", None)
        self.assertIn("SCENARIO_CONTEXT_TAG_STATE_MISMATCH", self.codes(self.validator.validate_scenario(scenario)))

    def test_scenario_expected_business_result_checks_lookup_and_metadata(self):
        scenario = copy.deepcopy(next(x for x in self.p0b_scenarios if x["source"]["source_id"] == "ICTX-003"))
        scenario["ground_truth"]["expected_business_result"]["supporting_lookup"]["query"] = "Coverage Matrix training query"
        codes = self.codes(self.validator.validate_scenario(scenario))
        self.assertTrue({"SCENARIO_EXPECTED_LOOKUP_MISMATCH", "SCENARIO_EXPECTED_RESULT_META_TEXT"} <= codes)

    def test_scenario_expected_diff_is_checked_and_d4_before_matches_read(self):
        scenario = copy.deepcopy(next(x for x in self.p0b_scenarios if x["source"]["source_id"] == "UI-002"))
        scenario["ground_truth"]["expected_business_result"]["expected_diff"] = []
        self.assertIn("D4_DIFF", self.codes(self.validator.validate_scenario(scenario)))
        scenario["ground_truth"]["expected_business_result"]["expected_diff"] = copy.deepcopy(scenario["ground_truth"]["model_output"]["preview"]["diff"])
        scenario["ground_truth"]["model_output"]["preview"]["diff"][0]["before"] = "stale title"
        scenario["ground_truth"]["expected_business_result"]["expected_diff"] = copy.deepcopy(scenario["ground_truth"]["model_output"]["preview"]["diff"])
        self.assertIn("D4_BEFORE_READ_MISMATCH", self.codes(self.validator.validate_scenario(scenario)))

    def test_dataset_path_checks_canonical_d4_expected_diff(self):
        scenario = copy.deepcopy(next(x for x in self.p0b_scenarios if x["source"]["source_id"] == "UI-002"))
        scenario["ground_truth"]["expected_business_result"]["expected_diff"] = []
        report = self.validator.validate_dataset([scenario], [])
        self.assertIn("D4_DIFF", self.codes(report))

    def test_scenario_ui_state_uses_frozen_context_enums(self):
        scenario = copy.deepcopy(next(x for x in self.p0b_scenarios if x["source"]["source_id"] == "PRE-GATED-004"))
        scenario["state"]["facts"]["ui_context"]["page_type"] = "prepayment_form"
        self.assertIn("SCENARIO_UI_ENUM", self.codes(self.validator.validate_scenario(scenario)))

    def test_scenario_assertion_quote_template_is_rejected(self):
        scenario = copy.deepcopy(self.p0b_scenarios[0])
        scenario["ground_truth"]["deterministic_assertions"][0] = "本轮用户原话为“晚餐花了90元”，回答不得增加这句话未提供的资金事实。"
        self.validator._issues = []
        self.validator._validate_scenario_batch_authenticity([scenario], "scenarios.json")
        self.assertIn("SCENARIO_ASSERTION_BOILERPLATE", self.codes(self.validator._report({})))


if __name__ == "__main__":
    unittest.main()
