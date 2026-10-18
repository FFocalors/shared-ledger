from __future__ import annotations

import copy
import unittest

from agent.evaluation.t1_release.boundary import (
    BOUNDARY_CASES,
    _rebuild_read_trace,
    _refresh_record_signatures,
    build_boundary_records,
    validate_boundary_gold,
)
from agent.evaluation.t1_release.checker import check_collection
from agent.evaluation.t1_release.builder import _fixture_from_state
from agent.evaluation.t1_release.goldguard import validate_operation_gold
from agent.evaluation.t1_release.tests.test_checker_v2 import _row


class BoundaryV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = build_boundary_records()

    def test_all_eight_boundary_cases_are_valid_in_each_split(self) -> None:
        self.assertEqual(24, len(self.rows))
        self.assertEqual(
            {f"boundary_{case}" for case in BOUNDARY_CASES},
            {tag for row in self.rows for tag in row["coverage_tags"] if tag.startswith("boundary_")},
        )
        for split in ("train", "validation", "sealed"):
            split_rows = [row for row in self.rows if row["split"] == split]
            self.assertEqual(set(BOUNDARY_CASES), {
                tag.removeprefix("boundary_")
                for row in split_rows for tag in row["coverage_tags"]
                if tag.startswith("boundary_")
            })
        for row in self.rows:
            report = validate_boundary_gold(row)
            self.assertTrue(report["valid"])
            self.assertEqual(64, len(report["source_facts_sha256"]))
            validate_operation_gold(row)

    def test_legitimate_injection_read_remains_supported_and_complete_but_not_floor_evidence(self) -> None:
        rows = [row for row in self.rows if "boundary_untrusted_tool_data_injection" in row["coverage_tags"]]
        self.assertEqual(3, len(rows))
        self.assertTrue(all(row["expected"]["supported_in_v1"] for row in rows))
        self.assertTrue(all(row["expected"]["must_complete"] for row in rows))
        self.assertTrue(all(row["trace"][-1]["target"]["kind"] == "answer" for row in rows))
        self.assertTrue(all(row["trace"][-1]["target"]["basis"] == "grounded" for row in rows))

        report = check_collection(rows)
        self.assertEqual(3, report["verified_boundary_rows"])
        self.assertEqual(3, report["boundary_rows_excluded_from_positive_family_floor"])
        self.assertEqual(0, report["operation_family_counts"]["read.activities"]["train"])
        self.assertEqual(0, report["operation_family_counts"]["read.activities"]["validation"])
        self.assertEqual(0, report["operation_family_counts"]["read.activities"]["sealed"])

    def test_boundary_rows_still_participate_in_global_state_and_prompt_leak_checks(self) -> None:
        source = next(row for row in self.rows if "boundary_untrusted_tool_data_injection" in row["coverage_tags"]
                      and row["split"] == "train")
        leaked = copy.deepcopy(source)
        leaked["split"] = "validation"
        leaked["sample_id"] = "t1-boundary-injection-leak-validation"
        report = check_collection([source, leaked])
        pair_kinds = {item["kind"] for item in report["pair_findings"]}
        self.assertIn("full_initial_state_leakage", pair_kinds)
        self.assertIn("exact_prompt_duplicate", pair_kinds)
        self.assertFalse(report["preparation_eligible"])

    def test_injection_query_variants_are_real_filters_and_not_cross_split_prompt_leaks(self) -> None:
        rows = [row for row in self.rows if "boundary_untrusted_tool_data_injection" in row["coverage_tags"]]
        self.assertEqual({"train", "validation", "sealed"}, {row["split"] for row in rows})
        prompts = {row["split"]: row["trace"][0]["context"]["input_text"] for row in rows}
        self.assertEqual(3, len(set(prompts.values())))
        report = check_collection(rows)
        injection_pairs = [pair for pair in report["pair_findings"]
                           if pair["left"]["sample_id"].startswith("t1-boundary-untrusted-tool-data-injection")
                           and pair["right"]["sample_id"].startswith("t1-boundary-untrusted-tool-data-injection")]
        self.assertFalse(any(pair["kind"] == "exact_prompt_duplicate" for pair in injection_pairs))
        self.assertFalse(any(pair["kind"] == "near_prompt_candidate" for pair in injection_pairs))

    def test_final_context_cannot_replace_the_first_user_request(self) -> None:
        row = next(row for row in self.rows if "boundary_locked_expense_financial_change" in row["coverage_tags"]
                   and row["split"] == "train")
        altered = copy.deepcopy(row)
        altered["trace"][-1]["context"]["input_text"] = "请修改另一项费用的金额。"
        with self.assertRaises(ValueError):
            validate_boundary_gold(altered)

    def test_state_fixture_and_policy_evidence_are_bound_not_self_reported(self) -> None:
        row = next(row for row in self.rows if "boundary_child_unbound_payer" in row["coverage_tags"]
                   and row["split"] == "train")
        bad_fixture = copy.deepcopy(row)
        bad_fixture["fixture_state"]["activities"][0]["name"] += "偏移"
        with self.assertRaises(ValueError):
            validate_boundary_gold(bad_fixture)

        bad_policy = copy.deepcopy(row)
        bad_policy["trace"][-1]["context"]["policy_evidence"][0]["version"] = "attacker-version"
        with self.assertRaises(ValueError):
            validate_boundary_gold(bad_policy)

    def test_unrelated_locked_expense_does_not_justify_denial_for_requested_unlocked_expense(self) -> None:
        row = next(row for row in self.rows if "boundary_locked_expense_financial_change" in row["coverage_tags"]
                   and row["split"] == "train")
        altered = copy.deepcopy(row)
        state = altered["operation_state"]
        requested = state["expenses"][0]
        requested["locked"] = False
        unrelated = copy.deepcopy(requested)
        unrelated.update({"ref": "expense_2", "locked": True, "is_target": False,
                          "title": "另一个锁定费用"})
        state["expenses"].append(unrelated)
        first_context = altered["trace"][0]["context"]
        first_context["bound_references"].append({"kind": "expense", "ref": "expense_2"})
        request = first_context["input_text"]
        target = copy.deepcopy(altered["trace"][-1]["target"])
        altered["fixture_state"] = _fixture_from_state("expense.update", 0, state)
        _rebuild_read_trace(
            altered, operation="expense.update", prompt=request, target=target,
            policies=("expense_financial_lock",),
        )
        _refresh_record_signatures(altered, "expense.update")
        with self.assertRaises(ValueError):
            validate_boundary_gold(altered)

    def test_hidden_proposal_in_any_model_step_is_rejected(self) -> None:
        row = next(row for row in self.rows if "boundary_untrusted_tool_data_injection" in row["coverage_tags"]
                   and row["split"] == "train")
        altered = copy.deepcopy(row)
        altered["trace"][0]["target"] = {
            "kind": "propose", "operation": "expense.create", "fields": {},
        }
        with self.assertRaises(ValueError):
            validate_boundary_gold(altered)

    def test_first_model_context_cannot_temporarily_expand_scope_or_participant_refs(self) -> None:
        row = next(row for row in self.rows if "boundary_child_unbound_payer" in row["coverage_tags"]
                   and row["split"] == "train")
        state = row["operation_state"]
        current = next(item for item in state["activities"] if item["role"] == "current")
        unit = state["ledger_unit"]
        outsider = next(ref for ref in current["member_allowlist"]
                        if ref not in unit["participant_allowlist"])

        widened_permission = copy.deepcopy(row)
        context = widened_permission["trace"][0]["context"]
        context["available_permissions"].append("read.debts")
        context["verified_scope"]["permissions"].append("read.debts")
        with self.assertRaises(ValueError):
            validate_boundary_gold(widened_permission)

        widened_binding = copy.deepcopy(row)
        widened_binding["trace"][0]["context"]["bound_references"].append(
            {"kind": "participant", "ref": outsider},
        )
        with self.assertRaises(ValueError):
            validate_boundary_gold(widened_binding)

    def test_actor_denial_answer_cannot_offer_unauthorized_reads_or_writes(self) -> None:
        row = next(row for row in self.rows if "boundary_actor_not_authorized" in row["coverage_tags"]
                   and row["split"] == "train")
        altered = copy.deepcopy(row)
        altered["trace"][-1]["target"]["text"] = "我可以替你读取账本并准备记录。"
        with self.assertRaises(ValueError):
            validate_boundary_gold(altered)

    def test_missing_amount_requires_otherwise_eligible_active_create_state(self) -> None:
        row = next(row for row in self.rows if "boundary_missing_amount" in row["coverage_tags"]
                   and row["split"] == "train")
        altered = copy.deepcopy(row)
        state = altered["operation_state"]
        current = next(item for item in state["activities"] if item["role"] == "current")
        current["status"] = "archived"
        altered["fixture_state"] = _fixture_from_state("expense.create", 0, state)
        request = altered["trace"][0]["context"]["input_text"]
        target = copy.deepcopy(altered["trace"][-1]["target"])
        _rebuild_read_trace(altered, operation="expense.create", prompt=request, target=target)
        _refresh_record_signatures(altered, "expense.create")
        with self.assertRaises(ValueError):
            validate_boundary_gold(altered)

    def test_unverified_boundary_tag_cannot_resolve_or_hide_a_positive_record(self) -> None:
        row = _row("expense.create", 0)
        row["coverage_tags"] = ["boundary_untrusted_tool_data_injection"]
        report = check_collection([row])
        self.assertTrue(any(item["kind"] == "invalid_boundary_gold" for item in report["blocking_issues"]))
        self.assertFalse(report["preparation_eligible"])

    def test_nonpositive_untagged_row_is_a_blocker(self) -> None:
        row = _row("expense.create", 0)
        row["expected"]["supported_in_v1"] = False
        row["expected"]["must_complete"] = False
        report = check_collection([row])
        self.assertTrue(any(item["kind"] == "unverified_nonpositive_record"
                            for item in report["blocking_issues"]))

    def test_injection_label_does_not_accept_a_proposal_or_unconsumed_context(self) -> None:
        row = next(row for row in self.rows if "boundary_untrusted_tool_data_injection" in row["coverage_tags"]
                   and row["split"] == "train")
        altered = copy.deepcopy(row)
        altered["trace"][-1]["target"] = {
            "kind": "propose", "operation": "expense.create", "fields": {},
        }
        with self.assertRaises(ValueError):
            validate_boundary_gold(altered)
        report = check_collection([altered])
        self.assertTrue(any(item["kind"] == "invalid_boundary_gold" for item in report["blocking_issues"]))


if __name__ == "__main__":
    unittest.main()
