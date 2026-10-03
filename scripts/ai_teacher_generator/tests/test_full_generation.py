import sys
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "ai_teacher_generator"))

from full_generation import build_generation_plan  # noqa: E402


class FullGenerationPlanTests(unittest.TestCase):
    def test_plan_covers_trainable_families_excludes_fin002_and_caps_calls(self):
        plan = build_generation_plan(ROOT)
        summary = plan["summary"]
        self.assertEqual(plan["business_family_count"], 53)
        self.assertEqual(summary["reused_pilot_count"], 21)
        self.assertEqual(summary["planned_new_calls"], 151)
        self.assertEqual(summary["attempt_ceiling"], 167)
        self.assertEqual(summary["fin_002_new_calls"], 0)
        self.assertEqual(plan["excluded_family_ids"], ["family_fin_002"])
        self.assertEqual(len(plan["pilot_candidates_excluded_after_dedup"]), 1)
        counts = Counter(item["target_candidate_count"] for item in plan["family_plans"])
        self.assertEqual(counts, {2: 6, 3: 28, 4: 19})

    def test_every_new_call_is_pinned_to_a_frozen_source_and_style(self):
        plan = build_generation_plan(ROOT)
        seen = set()
        for family in plan["family_plans"]:
            for call in family["calls"]:
                self.assertNotIn(call["call_id"], seen)
                seen.add(call["call_id"])
                self.assertEqual(call["family_id"], family["family_id"])
                self.assertIn(call["source_sample_id"], family["frozen_gold_sample_ids"])
                self.assertIn(call["style"], {"colloquial", "typo_asr_like", "pronoun_ellipsis", "multi_turn"})
                self.assertTrue(call["variant_reason"])
        self.assertEqual(len(seen), 151)


if __name__ == "__main__":
    unittest.main()
