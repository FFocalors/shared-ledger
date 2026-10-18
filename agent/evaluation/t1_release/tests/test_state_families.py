from __future__ import annotations

import copy
import time
import unittest

from agent.evaluation.t1_release.checker import initial_state_signature
from agent.evaluation.t1_release.signatures import operation_state_signature


OPERATIONS = (
    "read.activities",
    "read.expenses",
    "read.debts",
    "expense.create",
    "expense.update",
    "expense.presentation.update",
)
CURRENCIES = ("USD", "CNY", "EUR", "JPY", "CAD")
PERMISSIONS = {
    "read.activities": "read.activities",
    "read.expenses": "read.expenses",
    "read.debts": "read.debts",
    "expense.create": "propose.expense.create",
    "expense.update": "propose.expense.update",
    "expense.presentation.update": "propose.expense.presentation.update",
}


def _state(operation: str, participant_count: int = 3, currency: str = "USD") -> dict:
    refs = [f"participant-{index}" for index in range(participant_count)]
    activity_ref = "activity-current"
    permission = PERMISSIONS[operation]
    return {
        "activities": [{
            "ref": activity_ref,
            "role": "current",
            "name": "Weekend trip",
            "kind": "normal",
            "status": "active",
            "base_currency": currency,
            "visible": True,
            "permissions": [permission],
            "member_allowlist": list(refs),
        }],
        "actor": {
            "user_ref": "user-a",
            "authenticated": True,
            "activity_member": True,
            "activity_member_active": True,
            "activity_ref": activity_ref,
            "permissions": [permission],
        },
        "participants": [{"ref": ref, "role": "member", "active": True} for ref in refs],
        "ledger_unit": {
            "ref": "unit-current",
            "activity_ref": activity_ref,
            "role": "normal_root",
            "active": True,
            "parent_active": True,
            "currency": currency,
            "participant_allowlist": list(refs),
        },
        "expenses": [],
        "debts": [],
        "visible_statuses": ["active", "archived"],
        "multi_currency_enabled": False,
        "fx_snapshot": {"snapshot_ref": "fx-old", "quotes": [{"currency": currency, "rate": "1.0"}]},
    }


def _expense(state: dict, ref: str, *, participants: list[str], currency: str = "USD",
             locked: bool = False, target: bool = False, allowed: bool = True) -> dict:
    return {
        "ref": ref,
        "activity_ref": state["activities"][0]["ref"],
        "ledger_unit_ref": state["ledger_unit"]["ref"],
        "title": "Lunch",
        "note": "old note",
        "icon_key": "meal",
        "amount": "42.50",
        "currency": currency,
        "occurred_at": "2026-10-01T09:30:00Z",
        "participant_refs": list(participants),
        "payments": [{"participant_ref": participants[0], "amount": "42.50"}] if participants else [],
        "splits": [{"participant_ref": ref, "amount": "42.50"} for ref in participants],
        "locked": locked,
        "target_allowed": allowed,
        "is_target": target,
        "expense_version": "7",
    }


def _reidentify_and_reorder(state: dict) -> dict:
    result = copy.deepcopy(state)
    mapping: dict[str, str] = {}
    for row in result.get("activities", []):
        mapping[row["ref"]] = f"activity-new-{len(mapping)}"
    for row in result.get("participants", []):
        mapping[row["ref"]] = f"participant-new-{len(mapping)}"
    for row in result.get("expenses", []):
        mapping[row["ref"]] = f"expense-new-{len(mapping)}"
    unit = result.get("ledger_unit", {})
    if unit.get("ref"):
        mapping[unit["ref"]] = "unit-new"

    def remap(value):
        return mapping.get(value, value)

    for row in result.get("activities", []):
        row["ref"] = remap(row.get("ref"))
        row["member_allowlist"] = [remap(ref) for ref in row.get("member_allowlist", [])]
    for row in result.get("participants", []):
        row["ref"] = remap(row.get("ref"))
    actor = result.get("actor", {})
    actor["activity_ref"] = remap(actor.get("activity_ref"))
    unit["ref"] = remap(unit.get("ref"))
    unit["activity_ref"] = remap(unit.get("activity_ref"))
    unit["participant_allowlist"] = [remap(ref) for ref in unit.get("participant_allowlist", [])]
    for row in result.get("expenses", []):
        row["ref"] = remap(row.get("ref"))
        row["activity_ref"] = remap(row.get("activity_ref"))
        row["ledger_unit_ref"] = remap(row.get("ledger_unit_ref"))
        row["participant_refs"] = [remap(ref) for ref in row.get("participant_refs", [])]
        for group in ("payments", "splits"):
            for allocation in row.get(group, []):
                allocation["participant_ref"] = remap(allocation.get("participant_ref"))
    for row in result.get("debts", []):
        row["activity_ref"] = remap(row.get("activity_ref"))
        row["debtor_ref"] = remap(row.get("debtor_ref"))
        row["creditor_ref"] = remap(row.get("creditor_ref"))
    for key in ("activities", "participants", "expenses", "debts"):
        result.get(key, []).reverse()
    for row in result.get("expenses", []):
        row.get("participant_refs", []).reverse()
        row.get("payments", []).reverse()
        row.get("splits", []).reverse()
    unit.get("participant_allowlist", []).reverse()
    result["fx_snapshot"]["quotes"].reverse()
    return result


def _change_ignored_values(state: dict) -> dict:
    result = copy.deepcopy(state)
    result["actor"]["user_ref"] = "different-user"
    for index, row in enumerate(result.get("activities", [])):
        row["name"] = f"renamed {index}"
        row["date"] = "2041-12-31"
    for row in result.get("expenses", []):
        row["title"] = "another title"
        row["note"] = "different note"
        row["icon_key"] = "receipt"
        row["amount"] = "999999.99"
        row["occurred_at"] = "2039-01-01T00:00:00Z"
        row["expense_version"] = "999"
        row["payments"] = [{"participant_ref": p, "amount": "3.00"} for p in row["participant_refs"]]
        row["splits"] = [{"participant_ref": p, "amount": "4.00"} for p in row["participant_refs"]]
    for row in result.get("debts", []):
        row["amount"] = "87654.32"
    result["fx_snapshot"] = {"snapshot_ref": "fx-new", "quotes": [{"currency": "AUD", "rate": "123.456"}]}
    result["multi_currency_enabled"] = True
    return result


def _catalogue_state(operation: str, index: int) -> dict:
    if operation in {"expense.create", "expense.update"}:
        count = 1 + index % 12
        currency = CURRENCIES[index // 12]
    elif operation in {"read.activities", "read.expenses"}:
        count = 1 + index % 15
        currency = CURRENCIES[index // 15]
    elif operation == "expense.presentation.update":
        count = 4
        currency = CURRENCIES[index // 15]
    else:
        count = 8
        currency = CURRENCIES[(index // 20) % len(CURRENCIES)]
    state = _state(operation, count, currency)
    current = state["activities"][0]
    current["base_currency"] = currency
    state["ledger_unit"]["currency"] = currency

    if operation == "read.activities":
        for offset in range(count - 1):
            state["activities"].append({
                "ref": f"activity-visible-{offset}",
                "role": f"visible-{offset}",
                "name": f"other activity {offset}",
                "kind": "large" if offset % 2 else "normal",
                "status": "archived" if offset % 2 else "active",
                "base_currency": CURRENCIES[offset % len(CURRENCIES)],
                "visible": True,
                "permissions": ["read.activities"],
                "member_allowlist": [],
            })
    elif operation == "read.expenses":
        refs = [row["ref"] for row in state["participants"]]
        state["expenses"] = [
            _expense(state, f"expense-{offset}", participants=[refs[0]], currency=currency,
                     locked=bool(offset % 2))
            for offset in range(count)
        ]
    elif operation == "read.debts":
        debt_currency = CURRENCIES[index // 15]
        current["base_currency"] = debt_currency
        state["ledger_unit"]["currency"] = debt_currency
        nodes = [f"participant-{offset}" for offset in range(3 + index % 5)]
        shape = (index // 5) % 3
        if shape == 0:
            pairs = [(nodes[offset], nodes[offset + 1]) for offset in range(len(nodes) - 1)]
        elif shape == 1:
            pairs = [(nodes[offset], nodes[(offset + 1) % len(nodes)]) for offset in range(len(nodes))]
        else:
            pairs = [(nodes[offset], nodes[0]) for offset in range(1, len(nodes))]
        state["debts"] = [
            {"activity_ref": current["ref"], "debtor_ref": left, "creditor_ref": right,
             "currency": debt_currency, "amount": "1.00"}
            for left, right in pairs
        ]
    elif operation == "expense.create":
        state["ledger_unit"]["participant_allowlist"] = [row["ref"] for row in state["participants"]]
        current["member_allowlist"] = list(state["ledger_unit"]["participant_allowlist"])
        state["ledger_unit"]["role"] = "normal_root"
    elif operation == "expense.update":
        refs = [row["ref"] for row in state["participants"]]
        current["member_allowlist"] = list(refs)
        state["ledger_unit"]["participant_allowlist"] = list(refs)
        state["expenses"] = [_expense(state, "expense-target", participants=refs, currency=currency,
                                       target=True, locked=False)]
    elif operation == "expense.presentation.update":
        candidate_count = 1 + index % 15
        refs = [row["ref"] for row in state["participants"]]
        state["expenses"] = [
            _expense(state, f"expense-{offset}", participants=refs[:2], currency=currency,
                     locked=bool(offset % 2))
            for offset in range(candidate_count)
        ]
    return state


class StateFamilySignatureTests(unittest.TestCase):
    def test_identifiers_order_and_ignored_fields_do_not_change_family(self):
        for operation in OPERATIONS:
            with self.subTest(operation=operation):
                state = _catalogue_state(operation, 7)
                if operation == "expense.update":
                    state["expenses"].append(_expense(
                        state, "non-target", participants=[row["ref"] for row in state["participants"][:2]],
                        currency="AUD", target=False, locked=True,
                    ))
                before = operation_state_signature(state, operation)
                self.assertEqual(before, operation_state_signature(_reidentify_and_reorder(state), operation))
                self.assertEqual(before, operation_state_signature(_change_ignored_values(state), operation))

    def test_create_uses_effective_choice_count_not_participant_claims_or_unit_role(self):
        state = _state("expense.create", 20)
        before = operation_state_signature(state, "expense.create")
        changed = copy.deepcopy(state)
        changed["ledger_unit"]["role"] = "large_child"
        for participant in changed["participants"]:
            participant["role"] = "owner"
        changed["fx_snapshot"]["quotes"].append({"currency": "EUR", "rate": "0.92"})
        self.assertEqual(before, operation_state_signature(changed, "expense.create"))

        changed = copy.deepcopy(state)
        changed["ledger_unit"]["participant_allowlist"] = changed["ledger_unit"]["participant_allowlist"][:-1]
        self.assertNotEqual(before, operation_state_signature(changed, "expense.create"))

    def test_read_activities_binds_current_anchor_and_ignores_member_inventory(self):
        state = _catalogue_state("read.activities", 5)
        before = operation_state_signature(state, "read.activities")
        changed = copy.deepcopy(state)
        changed["participants"].append({"ref": "extra", "role": "member", "active": True})
        changed["activities"][0]["member_allowlist"].append("extra")
        self.assertEqual(before, operation_state_signature(changed, "read.activities"))

        changed = copy.deepcopy(state)
        changed["activities"][0]["base_currency"] = "EUR"
        self.assertNotEqual(before, operation_state_signature(changed, "read.activities"))

    def test_expense_operations_use_reachable_state_and_financial_target_only(self):
        update = _catalogue_state("expense.update", 4)
        before = operation_state_signature(update, "expense.update")
        non_target = _expense(update, "unrelated", participants=["participant-0"], currency="JPY",
                              target=False, locked=True)
        update["expenses"].append(non_target)
        self.assertEqual(before, operation_state_signature(update, "expense.update"))
        update["expenses"][0]["participant_refs"].append("participant-extra")
        self.assertNotEqual(before, operation_state_signature(update, "expense.update"))

        read = _catalogue_state("read.expenses", 4)
        read_before = operation_state_signature(read, "read.expenses")
        read["expenses"].append(_expense(read, "unreachable", participants=["outside"], allowed=False))
        self.assertEqual(read_before, operation_state_signature(read, "read.expenses"))
        read["expenses"].append(_expense(read, "reachable", participants=["participant-0"], currency="EUR"))
        self.assertNotEqual(read_before, operation_state_signature(read, "read.expenses"))

        shared = _state("read.expenses", 2)
        shared["expenses"] = [
            _expense(shared, "expense-a", participants=["participant-0"]),
            _expense(shared, "expense-b", participants=["participant-0"]),
        ]
        shared_signature = operation_state_signature(shared, "read.expenses")
        disjoint = copy.deepcopy(shared)
        disjoint["expenses"][1]["participant_refs"] = ["participant-1"]
        self.assertNotEqual(shared_signature, operation_state_signature(disjoint, "read.expenses"))

        presentation = _catalogue_state("expense.presentation.update", 3)
        presentation_before = operation_state_signature(presentation, "expense.presentation.update")
        irrelevant_presentation_changes = copy.deepcopy(presentation)
        irrelevant_presentation_changes["activities"][0]["base_currency"] = "JPY"
        irrelevant_presentation_changes["activities"][0]["member_allowlist"].append("extra-member")
        irrelevant_presentation_changes["ledger_unit"]["role"] = "large_child"
        for expense in irrelevant_presentation_changes["expenses"]:
            expense["amount"] = "999.00"
            expense["title"] = "renamed same-title group"
        self.assertEqual(presentation_before, operation_state_signature(
            irrelevant_presentation_changes, "expense.presentation.update"
        ))
        toggled = copy.deepcopy(presentation)
        toggled["expenses"][0]["locked"] = not toggled["expenses"][0]["locked"]
        self.assertEqual(presentation_before,
                         operation_state_signature(toggled, "expense.presentation.update"))
        changed_currency = copy.deepcopy(presentation)
        for expense in changed_currency["expenses"]:
            expense["currency"] = "EUR"
        self.assertNotEqual(presentation_before,
                            operation_state_signature(changed_currency, "expense.presentation.update"))
        changed_title_partition = copy.deepcopy(presentation)
        changed_title_partition["expenses"][0]["title"] = "different title"
        self.assertNotEqual(presentation_before, operation_state_signature(
            changed_title_partition, "expense.presentation.update"
        ))
        changed_relationship = copy.deepcopy(presentation)
        changed_relationship["expenses"][0]["participant_refs"] = ["participant-2"]
        self.assertNotEqual(presentation_before, operation_state_signature(
            changed_relationship, "expense.presentation.update"
        ))
        presentation["expenses"].append(_expense(
            presentation, "new-candidate", participants=[], locked=True
        ))
        self.assertNotEqual(presentation_before,
                            operation_state_signature(presentation, "expense.presentation.update"))

    def test_debt_graph_isomorphism_preserves_two_person_reverse_and_detects_topology(self):
        state = _state("read.debts", 2)
        activity_ref = state["activities"][0]["ref"]
        state["debts"] = [{"activity_ref": activity_ref, "debtor_ref": "participant-0",
                            "creditor_ref": "participant-1", "currency": "CNY", "amount": "10.00"}]
        expected = operation_state_signature(state, "read.debts")
        reversed_edge = copy.deepcopy(state)
        reversed_edge["debts"][0]["debtor_ref"], reversed_edge["debts"][0]["creditor_ref"] = (
            reversed_edge["debts"][0]["creditor_ref"], reversed_edge["debts"][0]["debtor_ref"]
        )
        self.assertEqual(expected, operation_state_signature(reversed_edge, "read.debts"))

        state = _state("read.debts", 3)
        activity_ref = state["activities"][0]["ref"]
        state["debts"] = [
            {"activity_ref": activity_ref, "debtor_ref": "participant-0", "creditor_ref": "participant-1",
             "currency": "USD", "amount": "1.00"},
            {"activity_ref": activity_ref, "debtor_ref": "participant-1", "creditor_ref": "participant-2",
             "currency": "USD", "amount": "1.00"},
        ]
        path_signature = operation_state_signature(state, "read.debts")
        state["debts"].append({
            "activity_ref": activity_ref, "debtor_ref": "participant-2", "creditor_ref": "participant-0",
            "currency": "USD", "amount": "1.00",
        })
        cycle_signature = operation_state_signature(state, "read.debts")
        self.assertNotEqual(path_signature, cycle_signature)

    def test_synthetic_catalogue_has_60_unique_families_and_disjoint_splits(self):
        for operation in OPERATIONS:
            with self.subTest(operation=operation):
                signatures = [
                    operation_state_signature(_catalogue_state(operation, index), operation)
                    for index in range(60)
                ]
                self.assertEqual(60, len(set(signatures)))
                split_hashes = [set(signatures[index:index + 20]) for index in (0, 20, 40)]
                self.assertTrue(all(len(partition) == 20 for partition in split_hashes))
                self.assertTrue(split_hashes[0].isdisjoint(split_hashes[1]))
                self.assertTrue(split_hashes[0].isdisjoint(split_hashes[2]))
                self.assertTrue(split_hashes[1].isdisjoint(split_hashes[2]))

    def test_title_graph_canonicalization_scales_for_unique_and_repeated_groups(self):
        def titled_state(count: int, *, repeated: bool) -> dict:
            state = _state("expense.presentation.update", participant_count=2)
            refs = [row["ref"] for row in state["participants"]]
            state["expenses"] = [
                _expense(
                    state,
                    f"expense-{index}",
                    participants=refs,
                )
                for index in range(count)
            ]
            for index, row in enumerate(state["expenses"]):
                row["title"] = f"group-{index // 2}" if repeated else f"unique-{index}"
            return state

        def assert_fast_and_invariant(state: dict) -> None:
            started = time.perf_counter()
            operation_hash = operation_state_signature(state, "expense.presentation.update")
            global_hash = initial_state_signature(state)
            elapsed = time.perf_counter() - started
            self.assertLess(elapsed, 10.0, f"exact canonicalization took {elapsed:.3f}s")

            renamed = _reidentify_and_reorder(state)
            by_title: dict[str, str] = {}
            for index, row in enumerate(renamed["expenses"]):
                title = row["title"]
                by_title.setdefault(title, f"renamed-title-{len(by_title)}")
                row["title"] = by_title[title]
            self.assertEqual(operation_hash,
                             operation_state_signature(renamed, "expense.presentation.update"))
            self.assertEqual(global_hash, initial_state_signature(renamed))

        unique = titled_state(15, repeated=False)
        assert_fast_and_invariant(unique)

        repeated = titled_state(16, repeated=True)
        assert_fast_and_invariant(repeated)

        # Splitting one anonymous pair into two singleton title groups changes
        # the equality partition, even though literal names and IDs are absent.
        split_pair = copy.deepcopy(repeated)
        split_pair["expenses"][1]["title"] = "a newly distinct title"
        self.assertNotEqual(
            operation_state_signature(repeated, "expense.presentation.update"),
            operation_state_signature(split_pair, "expense.presentation.update"),
        )
        self.assertNotEqual(initial_state_signature(repeated), initial_state_signature(split_pair))

        absent_title = copy.deepcopy(unique)
        absent_title["expenses"][0].pop("title")
        self.assertNotEqual(
            operation_state_signature(unique, "expense.presentation.update"),
            operation_state_signature(absent_title, "expense.presentation.update"),
        )


if __name__ == "__main__":
    unittest.main()
