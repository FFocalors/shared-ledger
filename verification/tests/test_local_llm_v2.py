"""Small offline checks for focused section selection and one-shot Loader validation."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None

from shared_ledger_verifier.local_llm import HTTPResponse, LocalLLMClient
from shared_ledger_verifier.local_llm_v2 import FOCUS_SECTIONS, _schema, run_probe_v2, select_business_sections
from test_local_llm import combined_scenario, simple_scenario


def _refund_scenario() -> dict:
    return {
        "schema_version": 1, "scenario_id": "generated_prepayment_refund",
        "description": "B prepays A before a shared expense and linked refund.",
        "activity": {"type": "normal", "base_currency": "CNY", "multi_currency_enabled": False},
        "participants": ["A", "B", "C"],
        "operations": [
            {"type": "create_prepayment", "ref": "prepayment_1", "owner_participant": "B",
             "custodian_participant": "A", "amount": "50.0", "currency": "CNY"},
            {"type": "create_expense", "ref": "expense_1", "title": "Meal", "amount": "120.0",
             "currency": "CNY", "payments": {"A": "120.0"}, "split_method": "manual",
             "splits": {"B": "60.0", "C": "60.0"}},
            {"type": "linked_refund", "ref": "refund_1", "original_expense_ref": "expense_1",
             "title": "Meal refund", "amount": "-30.0", "currency": "CNY",
             "payments": {"A": "-30.0"}, "split_method": "manual", "splits": {"B": "-30.0"}},
        ],
    }


class ProbeV2Tests(unittest.TestCase):
    def test_operation_schema_requires_loader_fields_per_type(self) -> None:
        aa_items = _schema("expense_aa")["properties"]["operations"]["items"]
        self.assertEqual(len(aa_items["oneOf"]), 1)
        aa = aa_items["oneOf"][0]
        self.assertEqual(aa["properties"]["type"], {"const": "create_expense"})
        self.assertEqual(set(aa["required"]), set(aa["properties"]))
        self.assertFalse(aa["additionalProperties"])
        targeted = _schema("targeted_repayment")["properties"]["operations"]["items"]["oneOf"]
        self.assertEqual([item["properties"]["type"]["const"] for item in targeted],
                         ["create_expense", "targeted_repayment"])
        self.assertEqual(set(targeted[1]["required"]), set(targeted[1]["properties"]))
        refund = _schema("prepayment_refund")["properties"]["operations"]["items"]["oneOf"]
        self.assertEqual([item["properties"]["type"]["const"] for item in refund],
                         ["create_prepayment", "create_expense", "linked_refund"])
        for item in refund:
            self.assertEqual(set(item["required"]), set(item["properties"]))
            self.assertFalse(item["additionalProperties"])

    @unittest.skipUnless(Draft202012Validator is not None, "jsonschema package unavailable")
    def test_schema_accepts_loader_examples_and_rejects_invalid_operation(self) -> None:
        for focus, document in (("expense_aa", simple_scenario()),
                                ("targeted_repayment", combined_scenario()),
                                ("prepayment_refund", _refund_scenario())):
            schema = _schema(focus)
            Draft202012Validator.check_schema(schema)
            validator = Draft202012Validator(schema)
            self.assertTrue(validator.is_valid(document), focus)
            invalid = deepcopy(document)
            invalid["operations"][0]["type"] = "unknown_operation"
            self.assertFalse(validator.is_valid(invalid), focus)
            invalid = deepcopy(document)
            del invalid["operations"][0]["ref"]
            self.assertFalse(validator.is_valid(invalid), focus)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invalid.json"
            invalid = simple_scenario()
            invalid["operations"][0]["type"] = "unknown_operation"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            from shared_ledger_verifier.loader import ScenarioValidationError, load_scenario
            with self.assertRaises(ScenarioValidationError):
                load_scenario(path)

    def test_selected_sections_are_parsed_from_headings(self) -> None:
        document = "preamble\n" + "".join(
            f"## {number}. Rule {number}\nbody {number}\n" for number in range(1, 17)
        )
        for focus, numbers in FOCUS_SECTIONS.items():
            headings, selected = select_business_sections(document, focus)
            self.assertEqual(headings, [f"## {number}. Rule {number}" for number in numbers])
            for number in range(1, 17):
                self.assertEqual(bool(re.search(rf"^body {number}$", selected, re.MULTILINE)),
                                 number in numbers)

    def test_three_requests_are_one_shot_and_each_uses_loader(self) -> None:
        documents = [simple_scenario(), combined_scenario(), _refund_scenario()]
        responses = [
            HTTPResponse(200, json.dumps({"data": [{"id": "qwen/qwen3.5-9b"}]}).encode()),
            *[HTTPResponse(200, json.dumps({"choices": [{"message": {"content": json.dumps(value)}}],
                                           "usage": {"prompt_tokens": 100, "completion_tokens": 200}}).encode())
              for value in documents],
        ]
        requests = []

        def transport(request, timeout):
            requests.append(request)
            return responses.pop(0)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            logic = root / "BUSINESS_LOGIC.md"
            logic.write_text("".join(f"## {number}. Rule {number}\nbody {number}\n"
                                     for number in range(1, 17)), encoding="utf-8")
            with patch("shared_ledger_verifier.local_llm_v2._business_logic_commit", return_value="test"):
                result = run_probe_v2(client=LocalLLMClient(transport=transport),
                                      output_dir=root / "probe", business_logic_path=logic)
            self.assertTrue(result["ready"])
            self.assertEqual(len(requests), 4)
            self.assertEqual([entry["status"] for entry in result["focus_results"].values()],
                             ["VALID", "VALID", "VALID"])
            for focus, entry in result["focus_results"].items():
                self.assertEqual(entry["loader_status"], "VALID")
                self.assertEqual((entry["prompt_tokens"], entry["completion_tokens"]), (100, 200))
                self.assertTrue((root / "probe" / f"generated_v2_1_{focus}.json").exists())
            self.assertTrue((root / "probe" / "probe_v2_1_result.json").exists())
            self.assertNotIn("body 1\n", json.loads(requests[1].data)["messages"][1]["content"])
            self.assertEqual(json.loads(requests[1].data)["response_format"]["type"], "json_schema")


if __name__ == "__main__":
    unittest.main()
