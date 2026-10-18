from __future__ import annotations

import copy
import unittest

from agent.evaluation.t1_release.builder import _make_record
from agent.evaluation.t1_release.goldguard import GoldGuardError, validate_operation_gold
from agent.evaluation.t1_release.runtime import baseline_modules, make_v2_validator
from agent.evaluation.t1_release.signatures import operation_state_signature, prompt_similarity


def _reidentify(state):
    clone = copy.deepcopy(state)
    mapping = {}
    for kind, rows, key in (
        ("activity", clone["activities"], "ref"),
        ("participant", clone["participants"], "ref"),
        ("expense", clone["expenses"], "ref"),
    ):
        for index, row in enumerate(rows):
            old = row[key]
            new = f"{kind}_renamed_{index:02d}"
            mapping[old] = new
    unit = clone.get("ledger_unit")
    if unit is not None:
        mapping[unit["ref"]] = "ledger_unit_renamed"
        if unit.get("parent_ref") is not None:
            mapping[unit["parent_ref"]] = "ledger_unit_parent_renamed"

    def replace_refs(value):
        if isinstance(value, str):
            return mapping.get(value, value)
        if isinstance(value, list):
            return [replace_refs(item) for item in value]
        if isinstance(value, dict):
            return {key: replace_refs(item) for key, item in value.items()}
        return value

    clone = replace_refs(clone)
    return clone


class ReleaseV2Tests(unittest.TestCase):
    def test_read_floor_requests_expose_complete_operation_facts(self):
        activities = _make_record("read.activities", 9)
        activity_tool = next(step for step in activities["trace"] if step["kind"] == "tool_result")
        activity_facts = activity_tool["result"]["body"]["items"]
        self.assertEqual(len(activity_facts), len(activities["operation_state"]["activities"]))
        self.assertTrue(all("协作组" in row["name"] for row in activity_facts))

        expenses = _make_record("read.expenses", 9)
        expense_tool = next(step for step in expenses["trace"] if step["kind"] == "tool_result")
        expense_facts = expense_tool["result"]["body"]["items"]
        self.assertEqual(len(expense_facts), len(expenses["operation_state"]["expenses"]))
        self.assertIsNone(expense_tool["request"]["criteria"]["from_date"])
        self.assertIsNone(expense_tool["request"]["criteria"]["to_date"])
        self.assertIsNone(expense_tool["request"]["criteria"]["participant_ref"])
        self.assertNotIn("title_contains", expenses["scenario"]["requested_values"])
        self.assertEqual(len(expense_facts), len(expenses["trace"][-1]["context"]["read_results"][0]["body"]["items"]))

        debts = _make_record("read.debts", 9)
        debt_tool = next(step for step in debts["trace"] if step["kind"] == "tool_result")
        debt_facts = debt_tool["result"]["body"]["items"]
        self.assertEqual(len(debt_facts), len(debts["operation_state"]["debts"]))
        self.assertEqual(len(debts["operation_state"]["expenses"]), len(debts["operation_state"]["debts"]))
        expenses_by_ref = {row["ref"]: row for row in debts["operation_state"]["expenses"]}
        for debt in debts["operation_state"]["debts"]:
            matching = [
                row for row in expenses_by_ref.values()
                if row["currency"] == debt["currency"]
                and row["amount"] == debt["amount"]
                and row["payments"] == [{"participant_ref": debt["creditor_ref"], "amount": debt["amount"]}]
                and row["splits"] == [{"participant_ref": debt["debtor_ref"], "amount": debt["amount"]}]
            ]
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0]["ledger_unit_ref"], debts["operation_state"]["ledger_unit"]["ref"])

    def test_empty_and_narrow_read_rows_reuse_existing_train_families(self):
        sources = {
            "read.activities": 14,
            "read.expenses": 4,
            "read.debts": 0,
        }
        for operation, source_index in sources.items():
            with self.subTest(operation=operation):
                source = _make_record(operation, source_index)
                source_answer = source["trace"][-1]["target"]
                for variant in ("empty", "narrow"):
                    row = _make_record(operation, source_index, read_variant=variant)
                    answer = row["trace"][-1]["target"]
                    self.assertEqual(source["split"], row["split"])
                    self.assertEqual(source["state_family_id"], row["state_family_id"])
                    self.assertNotEqual(source["sample_id"], row["sample_id"])
                    if variant == "empty":
                        self.assertEqual([], answer["citations"])
                    else:
                        self.assertGreater(len(answer["citations"]), 0)
                        self.assertLess(len(answer["citations"]), len(source_answer["citations"]))
                    validate_operation_gold(row)
                    self.assertEqual([], list(make_v2_validator().iter_errors(row)))

    def test_legacy_unscoped_positive_uses_large_activity_and_bound_parent(self):
        record = _make_record("expense.create", 8)
        state = record["operation_state"]
        unit = state["ledger_unit"]
        self.assertEqual(unit["role"], "legacy_unscoped")
        self.assertEqual(state["activities"][0]["kind"], "large")
        self.assertIsNotNone(unit["parent_ref"])
        self.assertEqual(unit["parent_role"], "large_root")
        self.assertEqual(unit["participant_allowlist"], state["activities"][0]["member_allowlist"])
        validate_operation_gold(record)

    def test_locked_presentation_is_in_train_without_becoming_a_family_axis(self):
        record = _make_record("expense.presentation.update", 15)
        self.assertEqual(record["split"], "train")
        self.assertTrue(all(row["locked"] for row in record["operation_state"]["expenses"]))
        validate_operation_gold(record)

    def test_graph_signature_ignores_id_name_date_amount_and_collection_order(self):
        for operation in ("expense.create", "expense.update", "read.debts", "read.expenses"):
            with self.subTest(operation=operation):
                state = _make_record(operation, 7)["operation_state"]
                before = operation_state_signature(state, operation)
                changed = _reidentify(state)
                title_renames = {
                    title: f"different display title {index}"
                    for index, title in enumerate(dict.fromkeys(
                        row["title"] for row in changed["expenses"]
                    ))
                }
                changed["activities"].reverse()
                changed["participants"].reverse()
                changed["expenses"].reverse()
                changed["debts"].reverse()
                for expense in changed["expenses"]:
                    expense["participant_refs"].reverse()
                    expense["payments"].reverse()
                    expense["splits"].reverse()
                    expense["amount"] = "999.99"
                    expense["title"] = title_renames[expense["title"]]
                    expense["occurred_at"] = "2030-01-01T00:00:00Z"
                changed["ledger_unit"]["participant_allowlist"].reverse()
                self.assertEqual(before, operation_state_signature(changed, operation))

    def test_graph_signature_preserves_authorization_financial_lock_and_debt_direction(self):
        create = _make_record("expense.create", 3)["operation_state"]
        expected = operation_state_signature(create, "expense.create")
        changed = copy.deepcopy(create)
        changed["ledger_unit"]["participant_allowlist"] = changed["ledger_unit"]["participant_allowlist"][:-1]
        self.assertNotEqual(expected, operation_state_signature(changed, "expense.create"))
        changed = copy.deepcopy(create)
        changed["activities"][0]["permissions"] = ["read.activities"]
        self.assertNotEqual(expected, operation_state_signature(changed, "expense.create"))

        financial_update = _make_record("expense.update", 3)["operation_state"]
        expected = operation_state_signature(financial_update, "expense.update")
        changed = copy.deepcopy(financial_update)
        changed["expenses"][0]["locked"] = not changed["expenses"][0]["locked"]
        self.assertNotEqual(expected, operation_state_signature(changed, "expense.update"))

        presentation = _make_record("expense.presentation.update", 3)["operation_state"]
        expected = operation_state_signature(presentation, "expense.presentation.update")
        changed = copy.deepcopy(presentation)
        changed["expenses"][0]["locked"] = not changed["expenses"][0]["locked"]
        self.assertEqual(expected, operation_state_signature(changed, "expense.presentation.update"))
        changed = copy.deepcopy(presentation)
        self.assertGreater(len(changed["expenses"]), 1)
        changed["expenses"].pop()
        self.assertNotEqual(expected, operation_state_signature(changed, "expense.presentation.update"))

        debt = _make_record("read.debts", 3)["operation_state"]
        expected = operation_state_signature(debt, "read.debts")
        changed = copy.deepcopy(debt)
        edge = changed["debts"][0]
        edge["debtor_ref"], edge["creditor_ref"] = edge["creditor_ref"], edge["debtor_ref"]
        self.assertNotEqual(expected, operation_state_signature(changed, "read.debts"))

    def test_gold_guard_catches_wrong_update_amount_ref_and_debt_direction(self):
        record = _make_record("expense.update", 0)
        broken = copy.deepcopy(record)
        broken["trace"][-1]["target"]["fields"]["original_amount"] = "1.00"
        with self.assertRaises(GoldGuardError):
            validate_operation_gold(broken)

        broken = copy.deepcopy(record)
        broken["trace"][-1]["target"]["fields"]["expense_ref"] = broken["trace"][-1]["context"]["verified_scope"]["activity_ref"]
        with self.assertRaises(GoldGuardError):
            validate_operation_gold(broken)

        debt = _make_record("read.debts", 1)
        broken = copy.deepcopy(debt)
        row = broken["fixture_state"]["debts"][0]
        row["debtor_ref"], row["creditor_ref"] = row["creditor_ref"], row["debtor_ref"]
        with self.assertRaises(GoldGuardError):
            validate_operation_gold(broken)

    def test_conservation_and_tool_body_replay_mutations_are_rejected(self):
        create = _make_record("expense.create", 1)
        broken = copy.deepcopy(create)
        broken["trace"][-1]["target"]["fields"]["payment_allocations"][0]["amount"] = "1.00"
        with self.assertRaises(GoldGuardError):
            validate_operation_gold(broken)

        debt = _make_record("read.debts", 2)
        broken = copy.deepcopy(debt)
        tool = next(step for step in broken["trace"] if step["kind"] == "tool_result")
        tool["result"]["body"]["items"][0]["debtor_ref"], tool["result"]["body"]["items"][0]["creditor_ref"] = (
            tool["result"]["body"]["items"][0]["creditor_ref"],
            tool["result"]["body"]["items"][0]["debtor_ref"],
        )
        _, _, _, _, validator_module = baseline_modules()
        with self.assertRaises(Exception):
            validator_module.validate_record(broken, make_v2_validator())

    def test_near_duplicate_threshold_math_is_stable(self):
        seq, jac = prompt_similarity("请读取当前活动ref=activity_1的费用。", "请读取当前活动ref=activity_2的费用。")
        self.assertGreaterEqual(seq, 0.82)
        self.assertGreaterEqual(jac, 0.72)


if __name__ == "__main__":
    unittest.main()
