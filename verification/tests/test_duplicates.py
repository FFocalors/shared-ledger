"""Offline checks for structural duplicate detection."""

from __future__ import annotations

import unittest
from copy import deepcopy

from shared_ledger_verifier.duplicates import (
    mark_duplicates,
    raw_case_fingerprint,
    scenario_fingerprint,
)

SCENARIO = {
    "schema_version": 1,
    "scenario_id": "cny_dinner_aa",
    "description": "A pays for dinner, three people split equally",
    "activity": {"type": "normal", "base_currency": "CNY", "multi_currency_enabled": False},
    "participants": ["alice", "bob", "carol"],
    "operations": [{
        "type": "create_expense", "ref": "dinner", "title": "Dinner",
        "amount": "150.0", "currency": "CNY",
        "payments": {"alice": "150.0"},
        "split_method": "aa", "aa_participants": ["alice", "bob", "carol"],
    }],
}

RAW = {
    "theme": "CNY Dinner AA",
    "participants": ["alice", "bob", "carol"],
    "currency": "CNY",
    "events": [{"type": "expense", "intent": "alice pays 150.0 CNY for a shared dinner split three ways"}],
}


class DuplicateDetectionTests(unittest.TestCase):
    def test_renaming_refs_and_titles_keeps_the_fingerprint(self):
        renamed = deepcopy(SCENARIO)
        renamed["scenario_id"] = "another_id"
        renamed["description"] = "completely different wording"
        renamed["participants"] = ["A", "B", "C"]
        renamed["operations"][0]["ref"] = "expense_1"
        renamed["operations"][0]["title"] = "Team meal"
        renamed["operations"][0]["payments"] = {"A": "150.0"}
        renamed["operations"][0]["aa_participants"] = ["A", "B", "C"]
        self.assertEqual(scenario_fingerprint(SCENARIO), scenario_fingerprint(renamed))

    def test_changing_business_data_changes_the_fingerprint(self):
        for mutate in (
            lambda doc: doc["operations"][0].__setitem__("amount", "151.0"),
            lambda doc: doc["operations"][0].__setitem__("payments", {"bob": "150.0"}),
            lambda doc: doc["participants"].append("dave"),
            lambda doc: doc["operations"][0].__setitem__("split_method", "manual"),
        ):
            changed = deepcopy(SCENARIO)
            mutate(changed)
            self.assertNotEqual(scenario_fingerprint(SCENARIO), scenario_fingerprint(changed))

    def test_reordering_participants_changes_the_fingerprint(self):
        reordered = deepcopy(SCENARIO)
        reordered["participants"] = ["bob", "alice", "carol"]
        self.assertNotEqual(scenario_fingerprint(SCENARIO), scenario_fingerprint(reordered))

    def test_operation_references_are_compared_structurally(self):
        first = deepcopy(SCENARIO)
        first["operations"].append({
            "type": "linked_refund", "ref": "refund_1", "original_expense_ref": "dinner",
            "title": "Refund", "amount": "-50.0", "currency": "CNY",
            "payments": {"bob": "-50.0"}, "split_method": "manual", "splits": {"carol": "-50.0"},
        })
        second = deepcopy(first)
        second["operations"][1]["original_expense_ref"] = "expense_1"
        second["operations"][0]["ref"] = "expense_1"
        second["operations"][1]["ref"] = "refund_9"
        self.assertEqual(scenario_fingerprint(first), scenario_fingerprint(second))

    def test_raw_case_fingerprint_ignores_wording_but_not_numbers(self):
        reworded = deepcopy(RAW)
        reworded["theme"] = "Team lunch"
        reworded["events"][0]["intent"] = "Three colleagues share a 150.0 CNY meal, paid by one of them"
        self.assertEqual(raw_case_fingerprint(RAW), raw_case_fingerprint(reworded))
        changed = deepcopy(RAW)
        changed["events"][0]["intent"] = "alice pays 151.0 CNY for a shared dinner split three ways"
        self.assertNotEqual(raw_case_fingerprint(RAW), raw_case_fingerprint(changed))

    def test_raw_case_fingerprint_tracks_the_event_sequence(self):
        extended = deepcopy(RAW)
        extended["events"].append({"type": "fifo_repayment", "intent": "bob repays 50.0 CNY"})
        self.assertNotEqual(raw_case_fingerprint(RAW), raw_case_fingerprint(extended))

    def test_fingerprints_of_missing_documents_are_none(self):
        self.assertIsNone(scenario_fingerprint(None))
        self.assertIsNone(raw_case_fingerprint({"not": "a raw case"}))

    def test_mark_duplicates_keeps_the_first_occurrence_canonical(self):
        records = [
            {"case_id": "a", "focus": "expense_aa", "scenario_fingerprint": "x"},
            {"case_id": "b", "focus": "expense_aa", "scenario_fingerprint": "y"},
            {"case_id": "c", "focus": "expense_aa", "scenario_fingerprint": "x"},
            {"case_id": "d", "focus": "other", "scenario_fingerprint": "x"},
            {"case_id": "e", "focus": "expense_aa", "scenario_fingerprint": None},
        ]
        # Only the first case of a fingerprint is canonical; a distinct
        # fingerprint or a missing one is never a duplicate.
        self.assertEqual(mark_duplicates(records), {"c": "a", "d": "a"})

    def test_mark_duplicates_is_global_by_default(self):
        records = [
            {"case_id": "a", "focus": "f1", "scenario_fingerprint": "x"},
            {"case_id": "b", "focus": "f2", "scenario_fingerprint": "x"},
            {"case_id": "c", "focus": "f1", "scenario_fingerprint": "x"},
            {"case_id": "d", "focus": "f2", "scenario_fingerprint": "y"},
        ]
        # One business structure is one test, whichever focus label produced it.
        self.assertEqual(mark_duplicates(records), {"b": "a", "c": "a"})

    def test_mark_duplicates_can_keep_one_canonical_per_focus(self):
        records = [
            {"case_id": "a", "focus": "f1", "scenario_fingerprint": "x"},
            {"case_id": "b", "focus": "f2", "scenario_fingerprint": "x"},
            {"case_id": "c", "focus": "f1", "scenario_fingerprint": "x"},
            {"case_id": "d", "focus": "f2", "scenario_fingerprint": "x"},
        ]
        self.assertEqual(
            mark_duplicates(records, group_by_focus=True), {"c": "a", "d": "b"}
        )


if __name__ == "__main__":
    unittest.main()
