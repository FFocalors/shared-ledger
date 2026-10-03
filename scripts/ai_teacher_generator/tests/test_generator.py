import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "ai_teacher_generator"))

from generator import (  # noqa: E402
    GeneratorError,
    build_request,
    create_plan,
    deterministic_mock_response,
    frozen_assets,
    make_candidate,
    parse_response,
    run_mock,
    validate_candidate,
)


class TeacherGeneratorTests(unittest.TestCase):
    def test_frozen_seed_hashes_match_manifest(self):
        assets = frozen_assets(ROOT)
        self.assertEqual(assets["scenario_sha256"], "b4ba7f406f017cd28c7c6885827717ae246b8f4dfb794a76fe00db5f9db59815")
        self.assertEqual(assets["sample_sha256"], "34ffd94d9c5ccbb17e6632b8689194c4be53f7275db828e983f6d6540b406dee")
        self.assertEqual(len(assets["contract_hashes"]), 9)
        self.assertTrue(all(len(digest) == 64 for digest in assets["contract_hashes"].values()))

    def test_plan_is_deterministic_and_retains_all_variant_dimensions(self):
        one = create_plan("family_exp_create_001", 19, ROOT, "colloquial")
        two = create_plan("family_exp_create_001", 19, ROOT, "colloquial")
        self.assertEqual(one["gold_sample_id"], two["gold_sample_id"])
        self.assertEqual(one["difficulty"], one["seed_sample"]["difficulty"])
        self.assertEqual(one["context_profile"], two["context_profile"])
        self.assertEqual(one["matrix"]["sample_target"], 2)
        with self.assertRaises(GeneratorError):
            create_plan("family_fin_002", 0, ROOT)

    def test_teacher_request_contains_locked_semantics_but_no_private_ids(self):
        plan = create_plan("family_exp_create_001", 19, ROOT, "colloquial")
        request = build_request(plan)
        visible = request["teacher_payload"]["messages"][1]["content"]
        self.assertIn("locked_business_facts", visible)
        self.assertIn("locked_expected_output", visible)
        for private_id in (plan["scenario_id"], plan["scenario_family_id"], plan["family_code"], plan["gold_sample_id"]):
            self.assertNotIn(private_id, visible)
        self.assertNotIn("frozen_hashes", visible)
        self.assertNotIn("dataset_version", visible)
        local_hashes = request["local_trace"]["frozen_hashes"]
        self.assertIn("ai_contract_sha256", local_hashes)
        self.assertIn("tool_catalog_sha256", local_hashes)
        self.assertIn("prompt_template_sha256", local_hashes)

    def test_candidate_copies_expected_and_trace_fields_and_passes_validator(self):
        plan = create_plan("family_exp_create_001", 19, ROOT, "colloquial")
        request = build_request(plan)
        candidate = make_candidate(plan, request, deterministic_mock_response(request))
        seed = plan["seed_sample"]
        self.assertEqual(candidate["expected"], seed["expected"])
        for field in ("scenario_id", "scenario_family_id", "split_group_id", "split"):
            self.assertEqual(candidate[field], seed[field])
        self.assertEqual(candidate["trust"]["level"], "SILVER")
        self.assertEqual(candidate["dataset_metadata"]["lifecycle_status"], "generated")
        self.assertTrue(candidate["example_only"])
        self.assertEqual(candidate["source"]["teacher"]["provider"], "mock")
        self.assertTrue(validate_candidate(candidate, plan["scenario"], ROOT)["valid"])

    def test_response_parser_rejects_incomplete_or_gt_shaped_output(self):
        plan = create_plan("family_exp_create_001", 19, ROOT, "colloquial")
        good = deterministic_mock_response(build_request(plan))
        with self.assertRaises(GeneratorError):
            parse_response({"surface_form": {"user_message": "x"}}, plan["seed_sample"])
        with self.assertRaises(GeneratorError):
            parse_response({**good, "expected": plan["seed_sample"]["expected"]}, plan["seed_sample"])

    def test_candidate_duplicate_against_gold_is_reported_for_review(self):
        plan = create_plan("family_exp_create_001", 19, ROOT, "colloquial")
        request = build_request(plan)
        response = {"surface_form": plan["seed_sample"]["surface_form"]}
        candidate = make_candidate(plan, request, response)
        result = validate_candidate(candidate, plan["scenario"], ROOT)
        self.assertTrue(result["valid"])
        self.assertIn("NORMALIZED_DUPLICATE", result["warning_codes"])

    def test_mock_runs_are_byte_repeatable_and_nontraining(self):
        plan = create_plan("family_conv_001", 19, ROOT, "multi_turn")
        before = frozen_assets(ROOT)
        with tempfile.TemporaryDirectory() as temp:
            left, right = Path(temp) / "left", Path(temp) / "right"
            first = run_mock(plan, left, ROOT)
            second = run_mock(plan, right, ROOT)
            self.assertEqual(first, second)
            for filename in ("request.json", "response.json", "candidate_sample.json", "run_manifest.json"):
                self.assertEqual((left / filename).read_bytes(), (right / filename).read_bytes())
            candidate = json.loads((left / "candidate_sample.json").read_text(encoding="utf-8"))
            self.assertEqual(candidate["expected"], plan["seed_sample"]["expected"])
            self.assertTrue(first["candidate_validation"]["valid"])
            self.assertFalse(first["training_eligible"])
            self.assertFalse(first["remote_provider_called"])
        after = frozen_assets(ROOT)
        self.assertEqual(before["scenario_sha256"], after["scenario_sha256"])
        self.assertEqual(before["sample_sha256"], after["sample_sha256"])


if __name__ == "__main__":
    unittest.main()
