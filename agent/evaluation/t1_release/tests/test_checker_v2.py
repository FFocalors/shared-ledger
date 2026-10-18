from __future__ import annotations

import copy
import hashlib
import unittest

from agent.evaluation.t1_release.checker import (
    OPERATIONS,
    check_collection,
    initial_state_signature,
)
from agent.evaluation.t1_release.signatures import operation_state_signature


CURRENCIES = ("USD", "CNY", "EUR", "JPY", "CAD")
PERMISSION = {
    "read.activities": "read.activities",
    "read.expenses": "read.expenses",
    "read.debts": "read.debts",
    "expense.create": "propose.expense.create",
    "expense.update": "propose.expense.update",
    "expense.presentation.update": "propose.expense.presentation.update",
}
HEX_LETTERS = "abcdefghijklmnop"


def _state(operation: str, participants: int = 3, currency: str = "USD") -> dict:
    people = [f"participant-{i}" for i in range(participants)]
    activity_ref = "activity-current"
    permission = PERMISSION[operation]
    return {
        "activities": [{
            "ref": activity_ref, "role": "current", "name": "Trip", "kind": "normal",
            "status": "active", "base_currency": currency, "visible": True,
            "permissions": [permission], "member_allowlist": list(people),
        }],
        "actor": {
            "user_ref": "user-1", "authenticated": True, "activity_member": True,
            "activity_member_active": True, "activity_ref": activity_ref,
            "permissions": [permission],
        },
        "participants": [{"ref": ref, "role": "member", "active": True} for ref in people],
        "ledger_unit": {
            "ref": "unit-current", "activity_ref": activity_ref, "role": "normal_root",
            "active": True, "parent_active": True, "currency": currency,
            "participant_allowlist": list(people),
        },
        "expenses": [], "debts": [], "visible_statuses": ["active", "archived"],
        "fx_snapshot": {"snapshot_ref": "old", "quotes": [{"currency": currency, "rate": "1.0"}]},
        "multi_currency_enabled": False,
    }


def _expense(state: dict, ref: str, people: list[str], *, currency: str = "USD",
             locked: bool = False, target: bool = False) -> dict:
    return {
        "ref": ref, "activity_ref": state["activities"][0]["ref"],
        "ledger_unit_ref": state["ledger_unit"]["ref"], "title": "Dinner", "note": "old",
        "amount": "45.50", "currency": currency, "occurred_at": "2026-10-01T10:00:00Z",
        "participant_refs": list(people), "payments": [], "splits": [], "locked": locked,
        "target_allowed": True, "is_target": target, "expense_version": "5",
    }


def _catalogue_state(operation: str, index: int) -> dict:
    if operation in {"expense.create", "expense.update"}:
        count = 1 + index % 12
        currency = CURRENCIES[index // 12]
    elif operation in {"read.activities", "read.expenses"}:
        count = 1 + index % 15
        currency = CURRENCIES[index // 15]
    elif operation == "expense.presentation.update":
        count = 1 + index % 15
        currency = CURRENCIES[index // 15]
    elif operation == "read.debts":
        count = 7
        currency = CURRENCIES[index // 15]
    else:
        count = 5
        currency = CURRENCIES[(index // 20) % 5]
    participant_count = count + 1 if operation == "expense.create" else count
    state = _state(operation, participant_count, currency)
    current = state["activities"][0]
    refs = [row["ref"] for row in state["participants"]]

    if operation == "read.activities":
        for offset in range(count - 1):
            state["activities"].append({
                "ref": f"activity-{offset}", "role": f"visible-{offset}",
                "name": f"Other {offset}", "kind": "large" if offset % 2 else "normal",
                "status": "archived" if offset % 2 else "active",
                "base_currency": CURRENCIES[offset % len(CURRENCIES)], "visible": True,
                "permissions": ["read.activities"], "member_allowlist": [],
            })
    elif operation == "read.expenses":
        state["expenses"] = [
            _expense(state, f"expense-{offset}", [refs[0]], currency=currency,
                     locked=bool(offset % 2))
            for offset in range(count)
        ]
    elif operation == "read.debts":
        node_count = 3 + (index % 15) % 5
        nodes = refs[:node_count]
        shape = (index % 15) // 5
        if shape == 0:
            pairs = [(nodes[i], nodes[i + 1]) for i in range(len(nodes) - 1)]
        elif shape == 1:
            pairs = [(nodes[i], nodes[(i + 1) % len(nodes)]) for i in range(len(nodes))]
        else:
            pairs = [(nodes[i], nodes[0]) for i in range(1, len(nodes))]
        state["debts"] = [
            {"activity_ref": current["ref"], "debtor_ref": left, "creditor_ref": right,
             "currency": currency, "amount": "1.00"}
            for left, right in pairs
        ]
    elif operation == "expense.create":
        state["ledger_unit"]["participant_allowlist"] = list(refs)
        # Model a legal large Activity with a child unit and a real proper
        # subset of its active Activity members.
        current["kind"] = "large"
        state["ledger_unit"]["role"] = "large_child"
        state["ledger_unit"]["parent_ref"] = "parent-unit"
        current["member_allowlist"] = list(refs)
        state["ledger_unit"]["participant_allowlist"] = list(refs[:-1])
    elif operation == "expense.update":
        current["member_allowlist"] = list(refs)
        current["kind"] = "large"
        state["expenses"] = [_expense(state, "target-expense", refs, currency=currency, target=True)]
    else:
        state["expenses"] = [
            _expense(state, f"expense-{offset}", refs[:2], currency=currency,
                     locked=bool(offset % 2))
            for offset in range(count)
        ]
    return state


def _human_review() -> dict:
    return {
        "status": "human_approved", "reviewer_kind": "human", "reviewer_id": "root-reviewer",
        "independent_root_review": "approved", "human_review_pending": False,
        "training_eligible": True,
    }


def _prompt(operation: str, index: int) -> str:
    digest = hashlib.sha256(f"{operation}:{index}".encode()).hexdigest()
    payload = "".join(HEX_LETTERS[int(char, 16)] for char in digest)
    return f"Please handle {payload}."


def _row(operation: str, index: int, split: str | None = None) -> dict:
    state = _catalogue_state(operation, index)
    split = split or ("train", "validation", "sealed")[index // 20]
    prompt = _prompt(operation, index)
    return {
        "sample_id": f"sample-{split}-{operation}-{index:02d}",
        "state_family_id": f"producer-lie-{index}",
        "split": split,
        "case_type": "supported_operation",
        "expected": {
            "task_operation": operation, "supported_in_v1": True,
            "must_complete": True, "semantic": "answer",
        },
        "operation_state": state,
        "operation_state_signature_sha256": operation_state_signature(state, operation),
        "trace": [{"kind": "model", "context": {"input_text": prompt}}],
        "review": _human_review(),
    }


def _valid_rows() -> list[dict]:
    if not hasattr(_valid_rows, "cache"):
        _valid_rows.cache = [
            _row(operation, index)
            for operation in OPERATIONS
            for index in range(60)
        ]
    return copy.deepcopy(_valid_rows.cache)


def _reidentify_and_reverse(state: dict) -> dict:
    result = copy.deepcopy(state)
    mapping: dict[str, str] = {}
    for key, prefix in (("activities", "activity-new"), ("participants", "participant-new"),
                        ("expenses", "expense-new")):
        for row in result.get(key, []):
            if row.get("ref") is not None:
                mapping[row["ref"]] = f"{prefix}-{len(mapping)}"
    unit = result.get("ledger_unit", {})
    if unit.get("ref") is not None:
        mapping[unit["ref"]] = "unit-new"

    def mapped(value):
        return mapping.get(value, value)

    for row in result.get("activities", []):
        row["ref"] = mapped(row.get("ref"))
        row["member_allowlist"] = [mapped(ref) for ref in row.get("member_allowlist", [])]
    for row in result.get("participants", []):
        row["ref"] = mapped(row.get("ref"))
    actor = result.get("actor", {})
    actor["activity_ref"] = mapped(actor.get("activity_ref"))
    unit["ref"] = mapped(unit.get("ref"))
    unit["activity_ref"] = mapped(unit.get("activity_ref"))
    unit["participant_allowlist"] = [mapped(ref) for ref in unit.get("participant_allowlist", [])]
    for row in result.get("expenses", []):
        row["ref"] = mapped(row.get("ref"))
        row["activity_ref"] = mapped(row.get("activity_ref"))
        row["ledger_unit_ref"] = mapped(row.get("ledger_unit_ref"))
        row["participant_refs"] = [mapped(ref) for ref in row.get("participant_refs", [])]
    for row in result.get("debts", []):
        row["activity_ref"] = mapped(row.get("activity_ref"))
        row["debtor_ref"] = mapped(row.get("debtor_ref"))
        row["creditor_ref"] = mapped(row.get("creditor_ref"))
    for key in ("activities", "participants", "expenses", "debts"):
        result.get(key, []).reverse()
    for key in ("member_allowlist",):
        for row in result.get("activities", []):
            row[key].reverse()
    unit.get("participant_allowlist", []).reverse()
    for row in result.get("expenses", []):
        row.get("participant_refs", []).reverse()
    return result


class CollectionCheckerV2Tests(unittest.TestCase):
    def test_computed_catalogue_has_required_independent_families(self):
        report = check_collection(_valid_rows())
        self.assertTrue(report["collection_passed"], {
            "blockers": report["blocking_issues"][:5],
            "pairs": [(item["kind"], item["left"], item["right"])
                      for item in report["pair_findings"]],
        })
        self.assertFalse(report["training_admission"])
        self.assertTrue(report["external_human_review_receipt_required"])
        self.assertIn("external_human_review_receipt_required", report["training_blockers"])
        self.assertEqual(0, report["pair_finding_count"])
        for operation in OPERATIONS:
            self.assertEqual({"train": 20, "validation": 20, "sealed": 20},
                             report["operation_family_counts"][operation])

    def test_operation_leakage_detected_despite_unique_family_metadata(self):
        rows = _valid_rows()
        source = next(row for row in rows if row["expected"]["task_operation"] == "read.activities"
                      and row["split"] == "train")
        target = next(row for row in rows if row["expected"]["task_operation"] == "read.activities"
                      and row["split"] == "validation")
        target["operation_state"] = copy.deepcopy(source["operation_state"])
        target["state_family_id"] = "looks-independent"
        # Deliberately stale producer metadata is reported, never used to count.
        report = check_collection(rows)
        # The validation split still has 20 signatures: the injected family
        # was absent there, even though it is a cross-split leak from train.
        self.assertEqual(20, report["operation_family_counts"]["read.activities"]["validation"])
        self.assertTrue(any(item["kind"] == "operation_state_leakage"
                            for item in report["pair_findings"]))
        self.assertFalse(report["training_admission"])

    def test_same_full_initial_state_cannot_escape_by_changing_operation(self):
        rows = _valid_rows()
        read_row = next(row for row in rows if row["expected"]["task_operation"] == "read.expenses"
                        and row["split"] == "sealed" and row["sample_id"].endswith("-45"))
        update_row = next(row for row in rows if row["expected"]["task_operation"] == "expense.update"
                          and row["split"] == "validation" and row["sample_id"].endswith("-36"))
        update_row["operation_state"] = copy.deepcopy(read_row["operation_state"])
        update_row["operation_state_signature_sha256"] = operation_state_signature(
            update_row["operation_state"], "expense.update"
        )
        report = check_collection(rows)
        self.assertTrue(any(item["kind"] == "full_initial_state_leakage"
                            and {item["left"]["sample_id"], item["right"]["sample_id"]}
                            == {read_row["sample_id"], update_row["sample_id"]}
                            and item["left"]["operation"] != item["right"]["operation"]
                            for item in report["pair_findings"]))

    def test_exact_and_near_prompt_pairs_are_reported_unresolved(self):
        rows = _valid_rows()
        train = next(row for row in rows if row["expected"]["task_operation"] == "expense.create"
                     and row["split"] == "train")
        validation = next(row for row in rows if row["expected"]["task_operation"] == "expense.create"
                          and row["split"] == "validation")
        train["trace"][0]["context"]["input_text"] = "新增费用 ledger_unit_12，参加者 participant_1。"
        validation["trace"][0]["context"]["input_text"] = "新增费用 ledger_unit_48，参加者 participant_9。"

        sealed_left = next(row for row in rows if row["expected"]["task_operation"] == "read.debts"
                           and row["split"] == "train")
        sealed_right = next(row for row in rows if row["expected"]["task_operation"] == "read.debts"
                            and row["split"] == "sealed")
        sealed_left["trace"][0]["context"]["input_text"] = "Please update the lunch expense to CNY."
        sealed_right["trace"][0]["context"]["input_text"] = "Please update the lunch expense to USD."

        report = check_collection(rows)
        exact = [item for item in report["pair_findings"] if item["kind"] == "exact_prompt_duplicate"]
        near = [item for item in report["pair_findings"] if item["kind"] == "near_prompt_candidate"]
        self.assertTrue(exact)
        self.assertTrue(near)
        self.assertTrue(all(item["disposition"] == "unresolved_requires_root_review" for item in near))
        self.assertGreater(report["unresolved_pair_count"], 0)
        self.assertFalse(report["training_admission"])
        self.assertNotIn("新增费用", repr(report))

    def test_near_pair_disposition_must_bind_current_hashes_and_root_evidence(self):
        rows = _valid_rows()
        left = next(row for row in rows if row["expected"]["task_operation"] == "read.debts"
                    and row["split"] == "train")
        right = next(row for row in rows if row["expected"]["task_operation"] == "read.debts"
                     and row["split"] == "sealed")
        left["trace"][0]["context"]["input_text"] = "Please update the lunch expense to CNY."
        right["trace"][0]["context"]["input_text"] = "Please update the lunch expense to USD."
        report = check_collection(rows)
        candidate = next(item for item in report["pair_findings"]
                         if item["kind"] == "near_prompt_candidate"
                         and {item["left"]["sample_id"], item["right"]["sample_id"]}
                         == {left["sample_id"], right["sample_id"]})
        bad = {
            "decision": "distinct_initial_states", "review_kind": "root_agent",
            "reviewer_id": "root:t1-state-review", "evidence": "Distinct computed state graph facts.",
            "left_full_state_signature_sha256": "0" * 64,
            "right_full_state_signature_sha256": candidate["right_full_state_signature_sha256"],
            "left_prompt_sha256": candidate["left_prompt_sha256"],
            "right_prompt_sha256": candidate["right_prompt_sha256"],
        }
        rejected = check_collection(rows, pair_dispositions={candidate["finding_id"]: bad})
        rejected_pair = next(item for item in rejected["pair_findings"]
                             if item["finding_id"] == candidate["finding_id"])
        self.assertEqual("unresolved_requires_root_review", rejected_pair["disposition"])

        accepted = dict(bad)
        accepted.update({
            "left_full_state_signature_sha256": candidate["left_full_state_signature_sha256"],
            "right_full_state_signature_sha256": candidate["right_full_state_signature_sha256"],
        })
        adjudicated = check_collection(rows, pair_dispositions={candidate["finding_id"]: accepted})
        adjudicated_pair = next(item for item in adjudicated["pair_findings"]
                                if item["finding_id"] == candidate["finding_id"])
        self.assertEqual("reviewed_distinct_by_root_agent", adjudicated_pair["disposition"])
        self.assertTrue(adjudicated["preparation_eligible"])
        self.assertFalse(adjudicated["training_eligible"])

    def test_invalid_or_wrong_split_is_a_blocker(self):
        rows = _valid_rows()
        row = next(row for row in rows if row["expected"]["task_operation"] == "read.activities"
                   and row["split"] == "validation")
        row["split"] = "holdout"
        report = check_collection(rows)
        self.assertTrue(any(item["kind"] == "invalid_split" for item in report["blocking_issues"]))
        self.assertFalse(report["training_admission"])

    def test_reidentification_order_money_date_name_and_version_do_not_create_families(self):
        rows = _valid_rows()
        row = next(row for row in rows if row["expected"]["task_operation"] == "read.expenses"
                   and row["split"] == "train")
        original = copy.deepcopy(row["operation_state"])
        changed = _reidentify_and_reverse(original)
        changed["actor"]["user_ref"] = "different-user"
        for activity in changed["activities"]:
            activity["name"] = "renamed ledger"
            activity["date"] = "2042-12-30"
        for expense in changed["expenses"]:
            expense["title"] = "new title"
            expense["amount"] = "999999.00"
            expense["occurred_at"] = "2042-01-01T00:00:00Z"
            expense["expense_version"] = "9000"
            expense["payments"] = [{"participant_ref": "irrelevant", "amount": "2.00"}]
            expense["splits"] = [{"participant_ref": "irrelevant", "amount": "3.00"}]
        changed["fx_snapshot"] = {"snapshot_ref": "new", "quotes": [{"currency": "AUD", "rate": "0.01"}]}
        self.assertEqual(initial_state_signature(original), initial_state_signature(changed))
        self.assertEqual(operation_state_signature(original, "read.expenses"),
                         operation_state_signature(changed, "read.expenses"))
        row["operation_state"] = changed
        row["operation_state_signature_sha256"] = operation_state_signature(changed, "read.expenses")
        report = check_collection(rows)
        self.assertEqual(20, report["operation_family_counts"]["read.expenses"]["train"])

    def test_full_state_tracks_anonymous_title_equivalence_not_literal_names_or_targets(self):
        state = _state("expense.presentation.update", participants=2)
        state["expenses"] = [
            _expense(state, "expense-a", ["participant-0"], target=False),
            _expense(state, "expense-b", ["participant-1"], target=True),
        ]
        same_title_signature = initial_state_signature(state)

        renamed = copy.deepcopy(state)
        renamed["expenses"][0]["title"] = "Supper"
        renamed["expenses"][1]["title"] = "Supper"
        renamed["expenses"][1]["is_target"] = False
        self.assertEqual(same_title_signature, initial_state_signature(renamed))

        distinct_title_partition = copy.deepcopy(state)
        distinct_title_partition["expenses"][1]["title"] = "Breakfast"
        self.assertNotEqual(same_title_signature, initial_state_signature(distinct_title_partition))

    def test_family_counts_ignore_family_metadata_and_recompute_from_state(self):
        rows = _valid_rows()
        validation_rows = [row for row in rows if row["expected"]["task_operation"] == "expense.update"
                           and row["split"] == "validation"]
        validation_rows[1]["operation_state"] = copy.deepcopy(validation_rows[0]["operation_state"])
        validation_rows[1]["state_family_id"] = "distinct-metadata-family"
        report = check_collection(rows)
        self.assertEqual(19, report["operation_family_counts"]["expense.update"]["validation"])
        self.assertFalse(report["training_admission"])

    def test_agent_validation_is_not_human_training_approval(self):
        row = _row("expense.create", 0)
        row["review"] = {
            "status": "auto_validated", "reviewer_kind": "agent", "reviewer_id": "validator",
            "independent_root_review": "pending", "human_review_pending": True,
            "training_eligible": False,
        }
        report = check_collection([row])
        self.assertFalse(report["training_admission"])
        self.assertFalse(report["human_review_metadata_is_trusted"])
        self.assertEqual(1, report["row_review_claims_pending"])
        self.assertIn("external_human_review_receipt_required", report["training_blockers"])

    def test_untrusted_nonpositive_case_type_cannot_count_as_positive_family(self):
        row = _row("expense.create", 0)
        row["case_type"] = "permission_denial"
        report = check_collection([row])
        self.assertTrue(any(item["kind"] == "unverified_case_type"
                            for item in report["blocking_issues"]))
        self.assertEqual(0, report["operation_family_counts"]["expense.create"]["train"])


if __name__ == "__main__":
    unittest.main()
