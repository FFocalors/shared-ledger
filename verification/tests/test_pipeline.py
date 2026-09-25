"""Offline checks for the producer/consumer pipeline.

The stages are replaced with fakes so these tests exercise the orchestration --
bounded queues, worker pools, per-case isolation, shutdown -- without touching a
model or a database.
"""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from shared_ledger_verifier.generate_case import CaseRun, result_template
from shared_ledger_verifier.pipeline import (
    LOCAL_GENERATOR_CONCURRENCY,
    DeepSeekGate,
    GatedClient,
    PipelineConfig,
    build_batch_plans,
    run_pipeline,
    summarise_pipeline,
)


def _fake_start_case(focus, *, plan=None, seed=None, output_dir=None, business_logic_path=None):
    directory = Path(output_dir) if output_dir else Path(tempfile.mkdtemp()) / f"{focus}-{plan.seed}"
    directory.mkdir(parents=True, exist_ok=True)
    result = result_template(focus, plan, output_dir=directory)
    result["plan_seed"] = plan.seed if plan is not None else seed
    return CaseRun(focus=focus, output_dir=directory, result=result, plan=plan)


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.trace: list[tuple[str, str, str]] = []
        self.lock = threading.Lock()
        self.active: dict[str, int] = {}
        self.max_active: dict[str, int] = {}

    def _note(self, stage: str, case_id: str) -> None:
        with self.lock:
            self.trace.append((stage, case_id, threading.current_thread().name))
            self.active[stage] = self.active.get(stage, 0) + 1
            self.max_active[stage] = max(self.max_active.get(stage, 0), self.active[stage])

    def _release(self, stage: str) -> None:
        with self.lock:
            self.active[stage] -= 1

    def _stages(self, *, compile_invalid: set[str] | None = None, sleep: Any = 0.0):
        invalid = compile_invalid or set()
        if isinstance(sleep, dict):
            schedule = {stage: float(value) for stage, value in sleep.items()}
            sleep = lambda stage, _map=schedule: _map.get(stage, 0.0)  # noqa: E731
        else:
            fixed = float(sleep)
            sleep = lambda stage, _value=fixed: _value  # noqa: E731

        def generate(run, *, local_client=None, on_progress=None):
            self._note("generate", run.output_dir.name)
            if sleep("generate"):
                time.sleep(sleep("generate"))
            run.result["status"] = "PENDING"
            run.result["raw_case"] = True
            self._release("generate")
            return run

        def compile_stage(run, *, compiler_client=None, on_progress=None):
            self._note("compile", run.output_dir.name)
            if sleep("compile"):
                time.sleep(sleep("compile"))
            status = "COMPILER_INVALID" if run.output_dir.name in invalid else "VALID"
            run.result["status"] = status
            run.result["focus_result"] = "FOCUS_VALID" if status == "VALID" else None
            self._release("compile")
            return run

        def execute(run, *, runner=None, on_progress=None):
            self._note("execute", run.output_dir.name)
            if sleep("execute"):
                time.sleep(sleep("execute"))
            run.result["status"] = "EXECUTED"
            self._release("execute")
            return run

        def judge_stage(run, *, judge=None, judge_client=None, on_progress=None):
            self._note("judge", run.output_dir.name)
            if sleep("judge"):
                time.sleep(sleep("judge"))
            run.result["status"] = "COMPLETE"
            run.result["judge_verdict"] = "PASS"
            self._release("judge")
            return run

        return generate, compile_stage, execute, judge_stage

    def _run(self, plans, config=None, **kwargs):
        generate, compile_stage, execute, judge_stage = self._stages(**kwargs)
        with patch("shared_ledger_verifier.pipeline.start_case", _fake_start_case), \
             patch("shared_ledger_verifier.pipeline.stage_generate", generate), \
             patch("shared_ledger_verifier.pipeline.stage_compile", compile_stage), \
             patch("shared_ledger_verifier.pipeline.stage_execute", execute), \
             patch("shared_ledger_verifier.pipeline.stage_judge", judge_stage):
            return run_pipeline(plans, config=config)

    def test_every_plan_reaches_every_stage(self):
        plans = build_batch_plans(["expense_aa", "fifo_repayment"], per_focus=3, seed_base=1)
        payload = self._run(plans)
        self.assertEqual(len(payload["results"]), 6)
        for stage in ("generate", "compile", "execute", "judge"):
            self.assertEqual(
                sum(1 for entry in self.trace if entry[0] == stage), 6, stage
            )
        self.assertEqual(len({r["output_dir"] for r in payload["results"]}), 6)

    def test_results_come_back_in_plan_order(self):
        plans = build_batch_plans({"expense_aa": 4, "void_transfer": 4}, seed_base=10)
        payload = self._run(plans)
        seeds = [run["plan_seed"] for run in payload["results"]]
        self.assertEqual(seeds, [plan.seed for plan in plans])

    def test_worker_pools_run_concurrently(self):
        plans = build_batch_plans(["expense_aa"], per_focus=8, seed_base=1)
        config = PipelineConfig(
            generator_workers=1, compiler_workers=2, runner_workers=2, judge_workers=4,
            deepseek_max_concurrency=4, raw_queue_size=2, compiled_queue_size=2, judge_queue_size=2,
        )
        # Compilation is made the slow stage so the pool must overlap; a fast
        # compiler pool would simply never be busy twice at once.
        self._run(plans, config=config,
                  sleep={"generate": 0.002, "compile": 0.03, "execute": 0.002, "judge": 0.02})
        self.assertEqual(self.max_active["generate"], 1, "the local model must stay single-request")
        self.assertGreater(self.max_active["compile"], 1)
        self.assertGreater(self.max_active["judge"], 1)

    def test_queues_stay_bounded(self):
        plans = build_batch_plans(["expense_aa"], per_focus=12, seed_base=1)
        config = PipelineConfig(
            generator_workers=1, compiler_workers=2, runner_workers=1, judge_workers=1,
            deepseek_max_concurrency=2, raw_queue_size=2, compiled_queue_size=3, judge_queue_size=4,
        )
        payload = self._run(plans, config=config, sleep=0.01)
        queue_max = payload["stats"]["queue_max"]
        self.assertLessEqual(queue_max["raw"], 2)
        self.assertLessEqual(queue_max["compiled"], 3)
        self.assertLessEqual(queue_max["judge"], 4)

    def test_a_stage_failure_does_not_stall_the_batch(self):
        plans = build_batch_plans(["expense_aa"], per_focus=6, seed_base=1)
        payload = self._run(plans, compile_invalid={
            f"{plan.focus}-{plan.seed}" for plan in plans[:2]
        })
        statuses = [run["status"] for run in payload["results"]]
        self.assertEqual(statuses.count("COMPILER_INVALID"), 2)
        self.assertEqual(statuses.count("COMPLETE"), 4)
        # Cases that failed compilation never reach the runner or the judge.
        self.assertEqual(sum(1 for e in self.trace if e[0] == "execute"), 4)

    def test_generator_is_clamped_to_one_worker(self):
        config = PipelineConfig(generator_workers=4)
        resolved, clamped = config.resolved()
        self.assertTrue(clamped)
        self.assertEqual(resolved.generator_workers, LOCAL_GENERATOR_CONCURRENCY)
        self.assertEqual(resolved.compiler_workers, config.compiler_workers)

    def test_deepseek_gate_bounds_concurrency(self):
        gate = DeepSeekGate(2)
        peaks: list[int] = []
        active = 0
        lock = threading.Lock()

        class Client:
            model = "test"

            def complete(self, *args, **kwargs):
                nonlocal active
                with lock:
                    active += 1
                    peaks.append(active)
                time.sleep(0.02)
                with lock:
                    active -= 1
                return "ok"

        gated = GatedClient(Client(), gate)
        threads = [threading.Thread(target=gated.complete) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertLessEqual(max(peaks), 2)

    def test_batch_plans_are_reproducible_and_seed_unique(self):
        first = build_batch_plans({"multi_payer_aa": 3, "aa_rounding": 2}, seed_base=7)
        second = build_batch_plans({"multi_payer_aa": 3, "aa_rounding": 2}, seed_base=7)
        self.assertEqual([p.seed for p in first], [p.seed for p in second])
        self.assertEqual([p.fingerprint() for p in first], [p.fingerprint() for p in second])
        self.assertEqual([p.seed for p in first], [7, 8, 9, 10, 11])
        self.assertEqual([p.focus for p in first],
                         ["multi_payer_aa"] * 3 + ["aa_rounding"] * 2)
        self.assertEqual(len({p.fingerprint() for p in first}), len(first))

    def test_batch_plans_reject_unknown_focus(self):
        with self.assertRaises(Exception):
            build_batch_plans(["not_a_focus"], per_focus=1)

    def test_summary_reports_throughput_and_errors(self):
        payload = {
            "results": [
                {"status": "COMPLETE", "error_category": None},
                {"status": "RUNNER_FAILED", "error_category": "TIMEOUT"},
                {"status": "COMPILER_INVALID", "error_category": "INVALID_JSON"},
            ],
            "stats": {"elapsed_seconds": 36.0, "queue_max": {"raw": 2}},
            "config": {"judge_workers": 4},
            "worker_failures": [],
        }
        summary = summarise_pipeline(payload)
        self.assertEqual(summary["cases"], 3)
        self.assertEqual(summary["statuses"]["COMPLETE"], 1)
        self.assertEqual(summary["error_categories"]["INVALID_JSON"], 1)
        self.assertEqual(summary["cases_per_hour"], 300.0)
        self.assertEqual(summary["deepseek_timeouts"], 1)
        self.assertEqual(summary["queue_max"], {"raw": 2})


if __name__ == "__main__":
    unittest.main()
