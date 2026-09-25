"""Offline tests for the generated-case E2E command and stage boundaries."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shared_ledger_verifier import __main__ as cli
from shared_ledger_verifier.run_generated_case import run_generated_case


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.case_dir = Path(self.temporary.name) / "case"
        self.case_dir.mkdir()
        (self.case_dir / "scenario.json").write_text('{"schema_version":1}', encoding="utf-8")
        self.generated = {
            "status": "VALID", "output_dir": str(self.case_dir), "local_model": "qwen/qwen3.5-9b",
            "compiler_model": "deepseek-v4.1-flash", "business_logic_commit": "abc123",
            "generation_latency_seconds": 1.2, "compiler_latency_seconds": 2.3,
            "repair_count": 0, "loader_result": "VALID", "loader_error": None,
            "error_category": None,
        }
        self.run_dir = self.case_dir / "runs" / "run-1"

    def execute(self, *, runner=None, judge=None):
        with patch("shared_ledger_verifier.run_generated_case.generate_case", return_value=self.generated) as generate:
            result = run_generated_case("expense_aa", runner=runner, judge=judge)
        generate.assert_called_once()
        return result

    def runner(self, scenario_path, *, runs_dir):
        self.assertEqual(Path(scenario_path), self.case_dir / "scenario.json")
        self.assertEqual(Path(runs_dir), self.case_dir / "runs")
        self.run_dir.mkdir(parents=True)
        (self.run_dir / "operations.jsonl").write_text('{"step":1}\n', encoding="utf-8")
        (self.run_dir / "state_final.json").write_text('{"activity":{}}\n', encoding="utf-8")
        return {"status": "EXECUTED", "run_id": "run-1", "run_dir": str(self.run_dir)}

    def test_full_orchestration_and_provenance(self) -> None:
        calls = []

        def judge(run_dir, *, client=None):
            calls.append(Path(run_dir))
            return {"verdict": "PASS", "model": "deepseek-v4.1-flash"}

        result = self.execute(runner=self.runner, judge=judge)
        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual(result["runner_result"], "EXECUTED")
        self.assertEqual(result["judge_verdict"], "PASS")
        self.assertEqual(result["run_id"], "run-1")
        self.assertEqual(result["local_generator_model"], "qwen/qwen3.5-9b")
        self.assertEqual(result["compiler_model"], "deepseek-v4.1-flash")
        self.assertEqual(result["judge_model"], "deepseek-v4.1-flash")
        self.assertEqual(result["business_logic_commit"], "abc123")
        self.assertEqual(result["compiler_repair_count"], 0)
        self.assertIsNotNone(result["runner_latency_seconds"])
        self.assertIsNotNone(result["judge_latency_seconds"])
        self.assertEqual(calls, [self.run_dir])
        for name in ("operations.jsonl", "state_final.json", "judge.json", "result.json"):
            self.assertTrue((self.case_dir / name).is_file(), name)

    def test_compiler_invalid_stops_before_runner(self) -> None:
        self.generated.update(status="COMPILER_INVALID", loader_result="INVALID", error_category="LOADER_INVALID")
        def forbidden(*args, **kwargs):
            self.fail("Runner or Judge must not be called")
        result = self.execute(runner=forbidden, judge=forbidden)
        self.assertEqual(result["status"], "COMPILER_INVALID")
        self.assertEqual(result["loader_result"], "INVALID")
        self.assertIsNone(result["run_id"])

    def test_runner_failure_stops_before_judge(self) -> None:
        def failed_runner(*args, **kwargs):
            return {"status": "FAILED", "run_id": "run-1", "run_dir": str(self.run_dir),
                    "error_code": "INSUFFICIENT_DEBT"}
        def forbidden(*args, **kwargs):
            self.fail("Judge must not be called after Runner failure")
        result = self.execute(runner=failed_runner, judge=forbidden)
        self.assertEqual(result["status"], "RUNNER_FAILED")
        self.assertEqual(result["error_category"], "INSUFFICIENT_DEBT")
        self.assertIsNone(result["judge_verdict"])

    def test_judge_fail_is_preserved_without_retry(self) -> None:
        count = 0
        def failed_judgment(run_dir, *, client=None):
            nonlocal count
            count += 1
            return {"verdict": "FAIL", "model": "deepseek-v4.1-flash", "summary": "Business mismatch"}
        result = self.execute(runner=self.runner, judge=failed_judgment)
        self.assertEqual(count, 1)
        self.assertEqual(result["status"], "COMPLETE")
        self.assertEqual(result["judge_verdict"], "FAIL")
        self.assertEqual(json.loads((self.case_dir / "judge.json").read_text())["verdict"], "FAIL")

    def test_judge_secret_is_not_persisted(self) -> None:
        secret = "sk-testsecret123456"
        def bad_judge(run_dir, *, client=None):
            return {"verdict": "PASS", "model": "deepseek", "summary": secret}
        result = self.execute(runner=self.runner, judge=bad_judge)
        self.assertEqual(result["status"], "JUDGE_ERROR")
        self.assertNotIn(secret, (self.case_dir / "result.json").read_text())
        self.assertNotIn(secret, (self.case_dir / "judge.json").read_text())


class RunGeneratedCaseTests(unittest.TestCase):
    def test_cli_dispatch_and_verdict_is_not_a_pass_requirement(self) -> None:
        result = {
            "status": "COMPLETE", "run_id": "run-1", "loader_result": "VALID",
            "runner_result": "EXECUTED", "judge_verdict": "FAIL", "output_dir": "case-1",
        }
        with patch("shared_ledger_verifier.run_generated_case.run_generated_case", return_value=result) as run:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = cli.main(["run-generated-case", "--focus", "expense_aa"])
        self.assertEqual(code, 0)
        run.assert_called_once_with("expense_aa", seed=None)
        self.assertIn("Judge=FAIL", output.getvalue())

    def test_cli_reports_stage_failure_without_secret_bearing_text(self) -> None:
        result = {
            "status": "JUDGE_ERROR", "run_id": "run-2", "loader_result": "VALID",
            "runner_result": "EXECUTED", "judge_verdict": "JUDGE_ERROR",
            "error_category": "API_ERROR", "output_dir": "case-2",
        }
        with patch("shared_ledger_verifier.run_generated_case.run_generated_case", return_value=result):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = cli.main(["run-generated-case", "--focus", "targeted_repayment"])
        self.assertEqual(code, 1)
        self.assertIn("API_ERROR", output.getvalue())


if __name__ == "__main__":
    unittest.main()
