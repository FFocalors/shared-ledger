"""Offline checks for the coverage counters that gate batch reporting."""

from __future__ import annotations

import unittest

from shared_ledger_verifier.coverage import CaseRecord, compute_coverage


def record(case_id: str, **overrides) -> CaseRecord:
    base = {
        "case_id": case_id,
        "focus": "single_payer_aa",
        "timestamp": case_id,
        "status": "COMPLETE",
        "focus_result": "FOCUS_VALID",
        "focus_error": None,
        "loader_result": "VALID",
        "runner_result": "EXECUTED",
        "judge_verdict": "PASS",
        "error_category": None,
        "compiler_repair_count": 0,
        "scenario_fingerprint": f"fp-{case_id}",
        "raw_case_fingerprint": f"raw-{case_id}",
        "plan_seed": 1,
        "plan_fingerprint": f"plan-{case_id}",
    }
    base.update(overrides)
    return CaseRecord(**base)


class CoverageTests(unittest.TestCase):
    def test_unique_valid_is_the_only_pass_rate_denominator(self):
        records = [
            record("a", judge_verdict="PASS"),
            record("b", judge_verdict="PASS", scenario_fingerprint="fp-a"),
            record("c", judge_verdict="FAIL"),
        ]
        summary = compute_coverage(records)
        self.assertEqual(summary["generated_count"], 3)
        self.assertEqual(summary["duplicate_count"], 1)
        self.assertEqual(summary["unique_valid_count"], 2)
        self.assertEqual(summary["judge_verdicts"]["PASS"], 1)
        self.assertEqual(summary["judge_verdicts"]["FAIL"], 1)
        self.assertEqual(summary["pass_rate"], 50.0)

    def test_focus_mismatch_cases_are_excluded_from_coverage(self):
        records = [
            record("a"),
            record("b", focus_result="FOCUS_MISMATCH", focus_error="multi_payer_aa: no"),
        ]
        summary = compute_coverage(records)
        self.assertEqual(summary["focus_valid_count"], 1)
        self.assertEqual(summary["focus_mismatch_count"], 1)
        self.assertEqual(summary["unique_valid_count"], 1)
        self.assertEqual(summary["pass_rate"], 100.0)

    def test_loader_invalid_cases_are_not_unique_valid(self):
        records = [record("a"), record("b", loader_result="INVALID")]
        summary = compute_coverage(records)
        self.assertEqual(summary["loader_valid_count"], 1)
        self.assertEqual(summary["loader_invalid_count"], 1)
        self.assertEqual(summary["unique_valid_count"], 1)

    def test_runner_failures_stay_in_the_denominator(self):
        records = [
            record("a", judge_verdict="PASS"),
            record("b", runner_result="FAILED", judge_verdict=None),
        ]
        summary = compute_coverage(records)
        self.assertEqual(summary["unique_valid_count"], 2)
        self.assertEqual(summary["runner_failed_count"], 1)
        self.assertEqual(summary["pass_rate"], 50.0)

    def test_a_generated_but_unexecuted_case_is_not_coverage(self):
        # `generate-case` produces a valid scenario but no evidence, so it must
        # not dilute the pass rate.
        records = [
            record("a", judge_verdict="PASS"),
            record("b", runner_result=None, judge_verdict=None),
        ]
        summary = compute_coverage(records)
        self.assertEqual(summary["generated_count"], 2)
        self.assertEqual(summary["focus_valid_count"], 2)
        self.assertEqual(summary["unique_valid_count"], 1)
        self.assertEqual(summary["pass_rate"], 100.0)
        self.assertFalse(summary["cases"][1]["is_unique_valid"])
        self.assertFalse(summary["cases"][1]["was_executed"])

    def test_duplicate_repeats_do_not_raise_the_pass_count(self):
        records = [record(f"c{index}", scenario_fingerprint="same") for index in range(6)]
        summary = compute_coverage(records)
        self.assertEqual(summary["generated_count"], 6)
        self.assertEqual(summary["duplicate_count"], 5)
        self.assertEqual(summary["unique_valid_count"], 1)
        self.assertEqual(summary["distinct_scenarios"], 1)
        self.assertEqual(summary["judge_verdicts"]["PASS"], 1)

    def test_repairs_and_latencies_are_aggregated(self):
        records = [
            record("a", compiler_repair_count=1, generator_latency_seconds=10.0,
                   compiler_latency_seconds=20.0, runner_latency_seconds=1.0,
                   judge_latency_seconds=30.0),
            record("b", compiler_repair_count=0, generator_latency_seconds=20.0,
                   compiler_latency_seconds=40.0, runner_latency_seconds=3.0,
                   judge_latency_seconds=50.0),
        ]
        summary = compute_coverage(records)
        self.assertEqual(summary["compiler_repair_count"], 1)
        self.assertEqual(summary["average_latencies"]["generator"], 15.0)
        self.assertEqual(summary["average_latencies"]["compiler"], 30.0)
        self.assertEqual(summary["average_latencies"]["runner"], 2.0)
        self.assertEqual(summary["average_latencies"]["judge"], 40.0)

    def test_per_focus_breakdown_reports_mismatch_and_duplicate_rates(self):
        records = [
            record("a", focus="multi_payer_aa"),
            record("b", focus="multi_payer_aa", scenario_fingerprint="fp-a"),
            record("c", focus="multi_payer_aa", focus_result="FOCUS_MISMATCH"),
            record("d", focus="fifo_repayment"),
        ]
        summary = compute_coverage(records)
        breakdown = {entry["focus"]: entry for entry in summary["focus_breakdown"]}
        multi = breakdown["multi_payer_aa"]
        self.assertEqual(multi["generated_count"], 3)
        self.assertEqual(multi["focus_valid_count"], 2)
        self.assertEqual(multi["focus_mismatch_count"], 1)
        self.assertEqual(multi["duplicate_count"], 1)
        self.assertEqual(multi["unique_valid_count"], 1)
        self.assertEqual(multi["duplicate_rate"], 50.0)
        self.assertEqual(breakdown["fifo_repayment"]["unique_valid_count"], 1)

    def test_empty_input_reports_no_rates(self):
        summary = compute_coverage([])
        self.assertEqual(summary["generated_count"], 0)
        self.assertIsNone(summary["pass_rate"])
        self.assertIsNone(summary["coverage_rate"])

    def test_case_flags_are_exposed_for_the_dashboard(self):
        summary = compute_coverage([record("a"), record("b", scenario_fingerprint="fp-a")])
        cases = {case["case_id"]: case for case in summary["cases"]}
        self.assertTrue(cases["a"]["is_unique_valid"])
        self.assertFalse(cases["b"]["is_unique_valid"])
        self.assertTrue(cases["b"]["is_duplicate"])
        self.assertEqual(cases["b"]["duplicate_of"], "a")


if __name__ == "__main__":
    unittest.main()
