"""Offline checks for raw-case to Compiler to Loader orchestration."""

from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from shared_ledger_verifier.generate_case import generate_case
from shared_ledger_verifier.raw_case import RawCaseError, _schema_for_focus, parse_raw_case
from shared_ledger_verifier.scenario_compiler import CompilerError, CompilerResult, compile_once, parse_compiler_response


RAW = {
    "theme": "Three friends share lunch",
    "participants": ["A", "B", "C"],
    "currency": "CNY",
    "events": [{"type": "expense", "intent": "A and B pay for an AA lunch shared by all three"}],
}
META = {
    "focus": "expense_aa", "local_model": "qwen/qwen3.5-9b",
    "business_logic_sections": ["## 6. Expense"], "business_logic_characters": 100,
    "input_characters": 200, "generation_latency_seconds": 1.25,
    "prompt_tokens": 30, "completion_tokens": 40,
}
VALID = {
    "schema_version": 1, "scenario_id": "lunch_aa", "description": "AA lunch",
    "activity": {"type": "normal", "base_currency": "CNY", "multi_currency_enabled": False},
    "participants": ["A", "B", "C"],
    "operations": [{
        "type": "create_expense", "ref": "lunch", "title": "Lunch", "amount": "120.0",
        "currency": "CNY", "payments": {"A": "60.0", "B": "60.0"},
        "split_method": "aa", "aa_participants": ["A", "B", "C"],
    }],
}


def compiled(scenario: dict, repair: bool = False) -> CompilerResult:
    return CompilerResult(scenario=deepcopy(scenario), response_text=json.dumps(scenario),
                          model="deepseek-v4.1-flash", latency_seconds=0.5, repair=repair)


class GenerateCaseTests(unittest.TestCase):
    def test_basic_smoke_schema_and_parser_require_cny(self):
        for focus in ("expense_aa", "targeted_repayment", "prepayment_refund"):
            self.assertEqual(_schema_for_focus(focus)["properties"]["currency"]["const"], "CNY")
        self.assertNotIn("const", _schema_for_focus("future_fx_focus")["properties"]["currency"])
        with self.assertRaisesRegex(RawCaseError, "CURRENCY_MISMATCH"):
            parse_raw_case(json.dumps({**RAW, "currency": "USD"}), required_currency="CNY")

    def test_raw_case_and_compiler_response_parsing(self):
        self.assertEqual(parse_raw_case(json.dumps(RAW)), RAW)
        with self.assertRaises(RawCaseError):
            parse_raw_case('{"theme":"x","theme":"y","participants":["A","B"],"currency":"CNY","events":[]}')
        with self.assertRaises(RawCaseError):
            parse_raw_case(json.dumps({**RAW, "events": [{"type": "unknown", "intent": "x"}]}))
        self.assertEqual(parse_compiler_response(json.dumps(VALID)), VALID)
        with self.assertRaises(CompilerError):
            parse_compiler_response("```json\n{}\n```")
        with self.assertRaises(CompilerError):
            parse_compiler_response('{"schema_version":1,"schema_version":1}')

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rules = self.root / "BUSINESS_LOGIC.md"
        self.rules.write_text("# Business rules\nCurrent rules.\n", encoding="utf-8")

    def run_case(self, output: str, **kwargs):
        return generate_case("expense_aa", output_dir=self.root / output,
                             business_logic_path=self.rules, **kwargs)

    @patch("shared_ledger_verifier.generate_case.compile_once")
    @patch("shared_ledger_verifier.generate_case.generate_raw_case")
    def test_valid_passes_loader_and_preserves_artifacts(self, raw, compile_mock):
        raw.return_value = (deepcopy(RAW), META)
        compile_mock.return_value = compiled(VALID)
        result = self.run_case("valid")
        self.assertEqual(result["status"], "VALID")
        self.assertEqual(result["loader_result"], "VALID")
        self.assertEqual(result["repair_count"], 0)
        self.assertEqual(compile_mock.call_count, 1)
        self.assertEqual(json.loads((self.root / "valid/raw_case.json").read_text()), RAW)
        self.assertEqual(json.loads((self.root / "valid/scenario.json").read_text()), VALID)
        self.assertEqual(result["local_model"], META["local_model"])
        self.assertEqual(result["compiler_model"], "deepseek-v4.1-flash")
        self.assertEqual(compile_mock.call_args.kwargs["smoke_currency"], "CNY")

    @patch("shared_ledger_verifier.generate_case.compile_once")
    @patch("shared_ledger_verifier.generate_case.generate_raw_case")
    def test_raw_usd_stops_before_compiler(self, raw, compile_mock):
        raw.return_value = ({**RAW, "currency": "USD"}, META)
        result = self.run_case("raw_usd")
        self.assertEqual(result["status"], "RAW_CASE_ERROR")
        self.assertEqual(result["error_category"], "CURRENCY_MISMATCH")
        compile_mock.assert_not_called()

    @patch("shared_ledger_verifier.generate_case.compile_once")
    @patch("shared_ledger_verifier.generate_case.generate_raw_case")
    def test_compiler_usd_gets_one_repair_and_never_passes_loader(self, raw, compile_mock):
        raw.return_value = (deepcopy(RAW), META)
        wrong = deepcopy(VALID)
        wrong["activity"] = {"type": "normal", "base_currency": "USD", "multi_currency_enabled": True}
        wrong["operations"][0]["currency"] = "USD"
        compile_mock.return_value = compiled(wrong)
        result = self.run_case("compiled_usd")
        self.assertEqual(result["status"], "COMPILER_INVALID")
        self.assertEqual(result["repair_count"], 1)
        self.assertIn("CNY-only", result["loader_error"])
        self.assertEqual(compile_mock.call_count, 2)

    @patch("shared_ledger_verifier.generate_case.compile_once")
    @patch("shared_ledger_verifier.generate_case.generate_raw_case")
    def test_loader_invalid_repairs_once(self, raw, compile_mock):
        raw.return_value = (deepcopy(RAW), META)
        invalid = deepcopy(VALID)
        invalid["operations"][0]["payments"]["B"] = "50.0"
        compile_mock.side_effect = [compiled(invalid), compiled(VALID, repair=True)]
        result = self.run_case("repaired")
        self.assertEqual(result["status"], "VALID")
        self.assertEqual(result["repair_count"], 1)
        self.assertEqual(compile_mock.call_count, 2)
        self.assertIsNotNone(compile_mock.call_args.kwargs["loader_error"])

    @patch("shared_ledger_verifier.generate_case.compile_once")
    @patch("shared_ledger_verifier.generate_case.generate_raw_case")
    def test_two_loader_failures_are_compiler_invalid(self, raw, compile_mock):
        raw.return_value = (deepcopy(RAW), META)
        invalid = deepcopy(VALID)
        invalid["operations"][0]["payments"]["B"] = "50.0"
        compile_mock.return_value = compiled(invalid)
        result = self.run_case("invalid")
        self.assertEqual(result["status"], "COMPILER_INVALID")
        self.assertEqual(result["loader_result"], "INVALID")
        self.assertEqual(result["repair_count"], 1)
        self.assertEqual(compile_mock.call_count, 2)

    @patch("shared_ledger_verifier.generate_case.compile_once")
    @patch("shared_ledger_verifier.generate_case.generate_raw_case")
    def test_compiler_parse_error_does_not_repair(self, raw, compile_mock):
        raw.return_value = (deepcopy(RAW), META)
        compile_mock.side_effect = CompilerError("INVALID_JSON", "malformed", response_text="reasoning")
        result = self.run_case("parse_error")
        self.assertEqual(result["status"], "COMPILER_INVALID")
        self.assertEqual(compile_mock.call_count, 1)
        self.assertNotIn("reasoning", (self.root / "parse_error/compiler_result.json").read_text())

    @patch("shared_ledger_verifier.generate_case.compile_once")
    @patch("shared_ledger_verifier.generate_case.generate_raw_case")
    def test_raw_case_error_does_not_call_compiler(self, raw, compile_mock):
        raw.side_effect = RawCaseError("INVALID_RAW_CASE")
        result = self.run_case("raw_error")
        self.assertEqual(result["status"], "RAW_CASE_ERROR")
        compile_mock.assert_not_called()

    @patch("shared_ledger_verifier.generate_case.compile_once")
    @patch("shared_ledger_verifier.generate_case.generate_raw_case")
    def test_secret_in_raw_case_is_not_persisted(self, raw, compile_mock):
        secret = "sk-testsecret123456"
        leaked = deepcopy(RAW)
        leaked["theme"] += " " + secret
        raw.return_value = (leaked, META)
        result = self.run_case("secret")
        self.assertEqual(result["error_category"], "FORBIDDEN_CONTENT")
        self.assertNotIn(secret, (self.root / "secret/result.json").read_text())
        self.assertFalse((self.root / "secret/raw_case.json").exists())
        compile_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
