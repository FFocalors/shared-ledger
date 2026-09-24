from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from shared_ledger_verifier.deepseek import DeepSeekApiError
from shared_ledger_verifier.judge import _business_logic_commit, judge_run


VERIFICATION_ROOT = Path(__file__).resolve().parents[1]
BUSINESS_LOGIC_PATH = VERIFICATION_ROOT.parent / "docs" / "backend" / "BUSINESS_LOGIC.md"


class FakeJudgeClient:
    model = "fake-model"

    def __init__(self, *responses: Any):
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _response(verdict: str) -> dict[str, Any]:
    differences = ["A concrete mismatch"] if verdict == "FAIL" else []
    return {
        "verdict": verdict,
        "confidence": 0.95 if verdict != "UNCERTAIN" else 0.4,
        "summary": f"Result: {verdict}",
        "expected": ["B owes A 100 CNY"],
        "actual": ["bilateral_debts contains B -> A for 100 CNY"],
        "differences": differences,
        "rules": ["Section 8: Debt"],
        "analysis": None if verdict == "PASS" else "Rule-based analysis",
    }


def _make_run(folder: Path, *, secret_text: str = "") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    scenario = {
        "schema_version": 1,
        "scenario_id": "basic_single_payment",
        "description": f"A pays 100 CNY and B bears it. {secret_text}".strip(),
        "activity": {"type": "normal", "base_currency": "CNY", "multi_currency_enabled": False},
        "participants": ["A", "B"],
        "operations": [
            {
                "type": "create_expense",
                "ref": "expense_1",
                "title": "Lunch",
                "amount": "100.0",
                "currency": "CNY",
                "payments": {"A": "100.0"},
                "split_method": "manual",
                "splits": {"B": "100.0"},
            }
        ],
    }
    state = {
        "activity": {
            "type": "normal",
            "base_currency": "CNY",
            "multi_currency_enabled": False,
            "financial_version": 123456,
            "financial_status": "active",
            "completed": False,
            "has_unsettled_debt": True,
            "total_debt": "100.0",
            "total_prepayment": "0.0",
            "prepayment_by_currency": [],
        },
        "participants": [
            {"ref": "A", "name": "A", "order": 0, "is_deleted": False},
            {"ref": "B", "name": "B", "order": 1, "is_deleted": False},
        ],
        "expenses": [
            {
                "ref": "expense_1",
                "ledger_unit_type": "default",
                "title": "Lunch",
                "amount": "100.0",
                "currency": "CNY",
                "base_amount": "100.0",
                "fx_rate": "1.0",
                "split_method": "manual",
                "original_expense_ref": None,
                "is_deleted": False,
                "financial_locked": False,
                "payments": [{"participant": "A", "amount": "100.0", "base_amount": "100.0"}],
                "splits": [{"participant": "B", "amount": "100.0", "base_amount": "100.0"}],
            }
        ],
        "expense_debts": [
            {
                "expense_ref": "expense_1",
                "debtor": "B",
                "creditor": "A",
                "amount": "100.0",
                "currency": "CNY",
                "base_amount": "100.0",
            }
        ],
        "bilateral_debts": [
            {"debtor": "B", "creditor": "A", "amount": "100.0", "currency": "CNY", "base_amount": "100.0"}
        ],
        "transfers": [],
        "transfer_components": [],
        "transfer_allocations": [],
        "transfer_expense_allocations": [],
        "prepayment_accounts": [],
        "prepayment_usages": [],
        "final_settlement_paths": [],
    }
    (folder / "scenario.json").write_text(json.dumps(scenario), encoding="utf-8")
    (folder / "state_final.json").write_text(json.dumps(state), encoding="utf-8")
    (folder / "result.json").write_text(json.dumps({"status": "EXECUTED"}), encoding="utf-8")
    return folder


class JudgeTests(unittest.TestCase):
    def test_business_logic_commit_tracks_rules_and_migrations(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=f"{'a' * 40}\n", stderr=""
        )
        with patch("shared_ledger_verifier.judge.subprocess.run", return_value=completed) as run_git:
            commit = _business_logic_commit()

        self.assertEqual(commit, "a" * 40)
        self.assertEqual(
            run_git.call_args.args[0],
            ["git", "log", "-1", "--format=%H", "--", "docs/backend/BUSINESS_LOGIC.md", "supabase/migrations"],
        )

    def test_pass_response_uses_full_rules_and_writes_complete_judge_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = _make_run(Path(temporary) / "run")
            client = FakeJudgeClient(json.dumps(_response("PASS")))

            result = judge_run(run_dir, client=client)

            self.assertEqual(result["verdict"], "PASS")
            self.assertEqual(result["provider"], "deepseek")
            self.assertEqual(result["model"], "fake-model")
            self.assertEqual(result["judge_version"], 1)
            self.assertIn("business_logic_commit", result)
            self.assertEqual(result["expected"], ["B owes A 100 CNY"])
            self.assertEqual(json.loads((run_dir / "judge.json").read_text(encoding="utf-8")), result)
            self.assertEqual(client.calls[0][0], (VERIFICATION_ROOT / "prompts" / "business_judge.md").read_text(encoding="utf-8"))
            self.assertIn(BUSINESS_LOGIC_PATH.read_text(encoding="utf-8"), client.calls[0][1])
            state_section = client.calls[0][1].split("STATE_FINAL_JSON_BEGIN\n", 1)[1].split("\nSTATE_FINAL_JSON_END", 1)[0]
            state_sent = json.loads(state_section)
            self.assertNotIn("financial_version", state_sent["activity"])
            self.assertNotIn("name", state_sent["participants"][0])
            payment = state_sent["expenses"][0]["payments"][0]
            self.assertEqual(set(payment), {"participant", "amount", "base_amount"})

    def test_nested_payment_and_split_rows_drop_unknown_identifiers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = _make_run(Path(temporary) / "run")
            state_path = run_dir / "state_final.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.signature123456789"
            state["expenses"][0]["payments"][0].update(
                {"id": "123e4567-e89b-42d3-a456-426614174000", "jwt": jwt}
            )
            state["expenses"][0]["splits"][0]["request_id"] = "private-request-id"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            client = FakeJudgeClient(json.dumps(_response("PASS")))

            result = judge_run(run_dir, client=client)

            prompt = client.calls[0][1]
            state_section = prompt.split("STATE_FINAL_JSON_BEGIN\n", 1)[1].split("\nSTATE_FINAL_JSON_END", 1)[0]
            state_sent = json.loads(state_section)
            self.assertEqual(result["verdict"], "PASS")
            self.assertEqual(set(state_sent["expenses"][0]["payments"][0]), {"participant", "amount", "base_amount"})
            self.assertEqual(set(state_sent["expenses"][0]["splits"][0]), {"participant", "amount", "base_amount"})
            self.assertNotIn("private-request-id", prompt)
            self.assertNotIn(jwt, prompt)

    def test_fail_response_is_saved_as_business_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = _make_run(Path(temporary) / "run")
            result = judge_run(run_dir, client=FakeJudgeClient(json.dumps(_response("FAIL"))))

            self.assertEqual(result["verdict"], "FAIL")
            self.assertEqual(result["differences"], ["A concrete mismatch"])

    def test_uncertain_response_is_not_promoted_to_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = _make_run(Path(temporary) / "run")
            result = judge_run(run_dir, client=FakeJudgeClient(json.dumps(_response("UNCERTAIN"))))

            self.assertEqual(result["verdict"], "UNCERTAIN")
            self.assertEqual(result["confidence"], 0.4)

    def test_invalid_model_output_retries_once_then_writes_judge_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = _make_run(Path(temporary) / "run")
            client = FakeJudgeClient("not json", "{}")

            result = judge_run(run_dir, client=client)

            self.assertEqual(result["verdict"], "JUDGE_ERROR")
            self.assertEqual(result["error_code"], "INVALID_MODEL_OUTPUT")
            self.assertEqual(len(client.calls), 2)
            self.assertEqual(json.loads((run_dir / "judge.json").read_text(encoding="utf-8")), result)

    def test_api_error_preserves_safe_diagnostics_on_both_attempts(self) -> None:
        for responses in ((DeepSeekApiError("secret-body", error_kind="http", status_code=503),), ("bad-json", DeepSeekApiError("secret-body", error_kind="timeout"))):
            with tempfile.TemporaryDirectory() as temporary:
                run_dir = _make_run(Path(temporary) / "run")
                result = judge_run(run_dir, client=FakeJudgeClient(*responses))
                self.assertEqual(result["error_code"], "API_ERROR")
                self.assertEqual(result["error_kind"], responses[-1].error_kind)
                self.assertEqual(result["http_status"], responses[-1].status_code)
                self.assertNotIn("secret-body", (run_dir / "judge.json").read_text())

    def test_secrets_and_sensitive_identifiers_are_not_sent_or_saved(self) -> None:
        secret = "sk-test-secret-very-long-value"
        url = "https://private.supabase.invalid/path"
        uuid = "123e4567-e89b-42d3-a456-426614174000"
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = _make_run(Path(temporary) / "run", secret_text=f"{secret} {url} {uuid}")
            client = FakeJudgeClient(RuntimeError(f"Authorization: Bearer hidden-secret {secret} {url} {uuid}"))

            result = judge_run(run_dir, client=client)

            prompt = client.calls[0][1]
            saved = (run_dir / "judge.json").read_text(encoding="utf-8")
            self.assertEqual(result["verdict"], "JUDGE_ERROR")
            self.assertEqual(result["error_code"], "CLIENT_ERROR")
            for sensitive in (secret, url, uuid, "hidden-secret"):
                self.assertNotIn(sensitive, prompt)
                self.assertNotIn(sensitive, saved)
            self.assertNotIn("Authorization", saved)
            self.assertNotIn("base_url", saved)


if __name__ == "__main__":
    unittest.main()
