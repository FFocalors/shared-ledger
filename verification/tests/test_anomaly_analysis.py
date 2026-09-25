"""Offline checks for the anomaly triage helpers (no network, no database)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shared_ledger_verifier.anomaly_analysis import (
    AnomalyRecord,
    anomaly_index,
    audit_pass_case,
    classify_cluster,
    cluster_anomalies,
    evidence_bundle,
    load_anomalies,
    reproduce_case,
)


class FakeClient:
    def __init__(self, responses: list[str]) -> None:
        self.model = "fake"
        self._responses = list(responses)
        self.prompts: list[str] = []

    def complete(self, system: str, user: str) -> str:
        self.prompts.append(user)
        return self._responses.pop(0) if self._responses else "{}"


def write_case(root: Path, case_id: str, *, verdict: str | None, runner: str | None,
               status: str = "COMPLETE", focus: str = "single_payer_aa",
               differences: list[str] | None = None, seed: int = 1) -> Path:
    directory = root / case_id
    directory.mkdir(parents=True)
    (directory / "result.json").write_text(json.dumps({
        "focus": focus, "plan_seed": seed, "status": status,
        "judge_verdict": verdict, "runner_result": runner, "error_category": None,
    }), encoding="utf-8")
    (directory / "judge.json").write_text(json.dumps({
        "verdict": verdict, "summary": "summary text", "differences": differences or [],
    }), encoding="utf-8")
    (directory / "plan.json").write_text(json.dumps({"seed": seed, "focus": focus}), encoding="utf-8")
    (directory / "raw_case.json").write_text(json.dumps({"theme": "t"}), encoding="utf-8")
    (directory / "scenario.json").write_text(json.dumps({"operations": []}), encoding="utf-8")
    (directory / "state_final.json").write_text(json.dumps({"activity": {}}), encoding="utf-8")
    ops = [{"step": 1, "operation": "create_expense", "status": "success"}]
    if runner == "FAILED":
        ops.append({"step": 2, "operation": "fifo_repayment", "status": "failed",
                    "error_code": "23514", "error_message": "too much"})
    (directory / "operations.jsonl").write_text(
        "".join(json.dumps(op) + "\n" for op in ops), encoding="utf-8")
    return directory


class AnomalyAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_only_anomalous_cases_enter_the_pool(self):
        write_case(self.root, "pass-1", verdict="PASS", runner="EXECUTED")
        write_case(self.root, "fail-1", verdict="FAIL", runner="EXECUTED")
        write_case(self.root, "uncertain-1", verdict="UNCERTAIN", runner="EXECUTED")
        write_case(self.root, "runner-1", verdict=None, runner="FAILED", status="RUNNER_FAILED")
        ids = ["pass-1", "fail-1", "uncertain-1", "runner-1"]
        pool = load_anomalies(ids, self.root)
        self.assertEqual([r.case_id for r in pool], ["fail-1", "uncertain-1", "runner-1"])
        self.assertEqual(len(load_anomalies(ids, self.root, include_all=True)), 4)

    def test_runner_failure_carries_its_failed_operation(self):
        write_case(self.root, "runner-1", verdict=None, runner="FAILED", status="RUNNER_FAILED")
        record = load_anomalies(["runner-1"], self.root)[0]
        self.assertEqual(record.failed_operations[0]["error_code"], "23514")
        self.assertIn("fifo_repayment", record.signature())

    def test_index_counts_by_focus_and_signature(self):
        write_case(self.root, "f1", verdict="FAIL", runner="EXECUTED",
                   differences=["Bob's base debt is observed as 0.2 but should be 0.3"])
        write_case(self.root, "f2", verdict="FAIL", runner="EXECUTED",
                   differences=["Bob's base debt is observed as 0.4 but should be 0.5"])
        write_case(self.root, "f3", verdict="FAIL", runner="EXECUTED", focus="multi_payer_aa",
                   differences=["other"])
        pool = load_anomalies(["f1", "f2", "f3"], self.root)
        index = anomaly_index(pool)
        self.assertEqual(index["total_anomalies"], 3)
        self.assertEqual(index["by_focus"]["single_payer_aa"], 2)
        # Numbers are normalised, so the same wording at a different amount groups.
        biggest = index["local_signature_groups"][0]
        self.assertEqual(biggest["occurrence_count"], 2)
        self.assertEqual(sorted(biggest["case_ids"]), ["f1", "f2"])

    def test_cluster_anomalies_uses_only_known_case_ids(self):
        write_case(self.root, "f1", verdict="FAIL", runner="EXECUTED")
        pool = load_anomalies(["f1"], self.root)
        client = FakeClient([json.dumps({"clusters": [
            {"cluster_id": "c1", "suspected_root_area": "base tail", "affected_focus": "single_payer_aa",
             "member_case_ids": ["f1", "does-not-exist"], "occurrence_count": 2,
             "shared_evidence": ["both flag base"], "why_one_cause": "same projection"},
            {"cluster_id": "empty", "member_case_ids": []},
        ]})])
        clusters = cluster_anomalies(anomaly_index(pool), client=client)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].member_case_ids, ["f1"])
        self.assertEqual(clusters[0].occurrence_count, 1)

    def test_cluster_anomalies_accepts_a_fenced_response(self):
        write_case(self.root, "f1", verdict="FAIL", runner="EXECUTED")
        pool = load_anomalies(["f1"], self.root)
        fenced = "```json\n" + json.dumps({"clusters": [
            {"cluster_id": "c1", "member_case_ids": ["f1"], "occurrence_count": 1}
        ]}) + "\n```"
        clusters = cluster_anomalies(anomaly_index(pool), client=FakeClient([fenced]))
        self.assertEqual(clusters[0].cluster_id, "c1")

    def test_classify_cluster_normalises_vocabulary(self):
        directory = write_case(self.root, "f1", verdict="FAIL", runner="EXECUTED")
        record = load_anomalies(["f1"], self.root)[0]
        client = FakeClient([json.dumps({
            "real": True, "classification": "business_bug", "severity": "high",
            "confidence": 0.8, "stable_reproduction": True,
            "expected_behavior": "0.3", "actual_behavior": "0.2",
            "suspected_root_area": "debt projection", "reasoning": "because",
        })])
        clusters = cluster_anomalies(anomaly_index([record]), client=FakeClient([json.dumps(
            {"clusters": [{"cluster_id": "c1", "member_case_ids": ["f1"], "occurrence_count": 1}]}
        )]))
        classify_cluster(clusters[0], {"f1": record}, client=client)
        self.assertEqual(clusters[0].classification, "BUSINESS_BUG")
        self.assertEqual(clusters[0].severity, "HIGH")
        self.assertTrue(clusters[0].real)
        # The classifier must see the full artefacts, not just a summary.
        self.assertIn("state_final", client.prompts[0])
        self.assertIn("scenario_plan", client.prompts[0])
        self.assertTrue(directory.is_dir())

    def test_severity_is_cleared_for_non_bugs(self):
        record = load_anomalies([write_case(self.root, "f1", verdict="FAIL",
                                            runner="EXECUTED").name], self.root)[0]
        client = FakeClient([json.dumps({
            "real": False, "classification": "JUDGE_FALSE_POSITIVE", "severity": "CRITICAL",
            "confidence": 0.9,
        })])
        clusters = cluster_anomalies(anomaly_index([record]), client=FakeClient([json.dumps(
            {"clusters": [{"cluster_id": "c1", "member_case_ids": ["f1"], "occurrence_count": 1}]}
        )]))
        classify_cluster(clusters[0], {"f1": record}, client=client)
        self.assertEqual(clusters[0].classification, "JUDGE_FALSE_POSITIVE")
        self.assertEqual(clusters[0].severity, "NONE")

    def test_unusable_analyst_response_is_unknown(self):
        record = load_anomalies([write_case(self.root, "f1", verdict="FAIL",
                                            runner="EXECUTED").name], self.root)[0]
        clusters = cluster_anomalies(anomaly_index([record]), client=FakeClient([json.dumps(
            {"clusters": [{"cluster_id": "c1", "member_case_ids": ["f1"], "occurrence_count": 1}]}
        )]))
        classify_cluster(clusters[0], {"f1": record}, client=FakeClient(["not json at all"]))
        self.assertEqual(clusters[0].classification, "UNKNOWN")

    def test_evidence_bundle_contains_every_required_artefact(self):
        write_case(self.root, "f1", verdict="FAIL", runner="EXECUTED")
        record = load_anomalies(["f1"], self.root)[0]
        bundle = evidence_bundle(record)
        for key in ("scenario_plan", "raw_case", "scenario", "operations", "state_final", "judge", "focus"):
            self.assertIn(key, bundle)

    def test_reproduce_case_replays_the_saved_scenario(self):
        directory = write_case(self.root, "f1", verdict="FAIL", runner="EXECUTED")
        seen: list[Path] = []

        def runner(scenario_path, *, runs_dir):
            seen.append(Path(scenario_path))
            run_dir = Path(runs_dir) / "run-2"
            run_dir.mkdir(parents=True, exist_ok=True)
            return {"status": "EXECUTED", "run_id": "run-2", "run_dir": str(run_dir)}

        outcome = reproduce_case(
            "f1", self.root, runner=runner,
            judge=lambda run_dir, client=None: {"verdict": "FAIL"},
        )
        # The saved scenario is replayed; nothing is regenerated.
        self.assertEqual(seen, [directory / "scenario.json"])
        self.assertTrue(outcome["reproduced"])
        self.assertEqual(outcome["original_verdict"], "FAIL")
        self.assertEqual(outcome["repro_verdict"], "FAIL")

    def test_reproduce_case_reports_a_missing_scenario(self):
        (self.root / "empty-case").mkdir()
        outcome = reproduce_case("empty-case", self.root)
        self.assertIsNone(outcome["reproduced"])
        self.assertIn("no saved scenario", outcome["reason"])

    def test_reproduce_case_reports_a_runner_exception(self):
        write_case(self.root, "f1", verdict="FAIL", runner="EXECUTED")

        def runner(*args, **kwargs):
            raise RuntimeError("boom")

        outcome = reproduce_case("f1", self.root, runner=runner)
        self.assertIsNone(outcome["reproduced"])
        self.assertIn("RuntimeError", outcome["reason"])

    def test_pass_audit_keeps_the_judge_verdict_out_of_the_prompt(self):
        write_case(self.root, "p1", verdict="PASS", runner="EXECUTED")
        record = load_anomalies(["p1"], self.root, include_all=True)[0]
        client = FakeClient([json.dumps({
            "compiler_preserved_intent": True, "intent_note": "same amounts",
            "focus_contract_genuine": True, "focus_note": "real AA",
            "judge_missed_anything": False, "missed_evidence": [],
        })])
        outcome = audit_pass_case(record, client=client)
        self.assertTrue(outcome["audited"])
        self.assertTrue(outcome["compiler_preserved_intent"])
        self.assertNotIn("summary text", client.prompts[0])

    def test_anomaly_record_flags_itself(self):
        anomalous = AnomalyRecord(case_id="a", focus="f", seed=1, status="RUNNER_FAILED",
                                  judge_verdict=None, runner_result="FAILED",
                                  error_category=None, judge_summary=None, differences=[])
        self.assertTrue(anomalous.is_anomalous)
        healthy = AnomalyRecord(case_id="b", focus="f", seed=1, status="COMPLETE",
                                judge_verdict="PASS", runner_result="EXECUTED",
                                error_category=None, judge_summary=None, differences=[])
        self.assertFalse(healthy.is_anomalous)


if __name__ == "__main__":
    unittest.main()
