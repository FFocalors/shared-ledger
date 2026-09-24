from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shared_ledger_verifier import __main__ as cli


class CliTests(unittest.TestCase):
    def _write_run(
        self,
        runs_dir: Path,
        run_id: str,
        scenario_id: str,
        status: str,
        *,
        modified_ns: int,
    ) -> Path:
        run_dir = runs_dir / run_id
        run_dir.mkdir()
        (run_dir / "scenario.json").write_text(
            json.dumps({"scenario_id": scenario_id}), encoding="utf-8"
        )
        (run_dir / "result.json").write_text(
            json.dumps({"status": status}), encoding="utf-8"
        )
        result_path = run_dir / "result.json"
        os.utime(result_path, ns=(modified_ns, modified_ns))
        return run_dir

    def test_judge_all_uses_latest_executed_distinct_smokes_and_summarizes(self) -> None:
        smoke_ids = sorted(cli._smoke_scenario_ids())
        self.assertEqual(len(smoke_ids), 6)
        with tempfile.TemporaryDirectory() as temporary:
            runs_dir = Path(temporary)
            for index, scenario_id in enumerate(smoke_ids):
                self._write_run(
                    runs_dir,
                    f"old-{index}",
                    scenario_id,
                    "EXECUTED",
                    modified_ns=1_000 + index,
                )
            latest_basic = self._write_run(
                runs_dir,
                "latest-basic",
                smoke_ids[0],
                "EXECUTED",
                modified_ns=10_000,
            )
            self._write_run(
                runs_dir,
                "failed-basic",
                smoke_ids[0],
                "FAILED",
                modified_ns=20_000,
            )

            judged: list[Path] = []
            verdicts = ("PASS", "FAIL", "UNCERTAIN", "JUDGE_ERROR", "PASS", "PASS")

            def fake_judge(run_dir: Path) -> dict[str, str]:
                judged.append(run_dir)
                return {"verdict": verdicts[len(judged) - 1]}

            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch.object(cli, "_call_judge", side_effect=fake_judge), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                status = cli.main(["judge-all", str(runs_dir)])

            self.assertEqual(status, 1)
            self.assertEqual(len(judged), 6)
            self.assertIn(latest_basic, judged)
            self.assertNotIn(runs_dir / "old-0", judged)
            self.assertIn("PASS: 3, FAIL: 1, UNCERTAIN: 1, JUDGE_ERROR: 1", stdout.getvalue())

    def test_judge_all_requires_six_distinct_executed_smokes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runs_dir = Path(temporary)
            self._write_run(
                runs_dir,
                "one",
                sorted(cli._smoke_scenario_ids())[0],
                "EXECUTED",
                modified_ns=1_000,
            )
            with patch.object(cli, "_call_judge") as judge, contextlib.redirect_stderr(io.StringIO()):
                status = cli.main(["judge-all", str(runs_dir)])
            self.assertEqual(status, 2)
            judge.assert_not_called()

    def test_judge_command_reports_single_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            stdout = io.StringIO()
            with patch.object(cli, "_call_judge", return_value={"verdict": "PASS", "summary": "ok"}), contextlib.redirect_stdout(stdout):
                status = cli.main(["judge", str(run_dir)])
            self.assertEqual(status, 0)
            self.assertIn("PASS", stdout.getvalue())

    def test_run_and_run_all_keep_execution_exit_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scenarios_dir = Path(temporary) / "scenarios"
            scenarios_dir.mkdir()
            (scenarios_dir / "a.json").write_text("{}", encoding="utf-8")
            (scenarios_dir / "b.json").write_text("{}", encoding="utf-8")

            with patch.object(cli, "run_scenario", return_value={"status": "EXECUTED"}) as run:
                self.assertEqual(cli.main(["run", str(scenarios_dir / "a.json")]), 0)
                run.assert_called_once()

            stdout = io.StringIO()
            with patch.object(
                cli,
                "run_scenario",
                side_effect=({"status": "EXECUTED"}, {"status": "FAILED"}),
            ), contextlib.redirect_stdout(stdout):
                status = cli.main(["run-all", str(scenarios_dir)])
            self.assertEqual(status, 1)
            self.assertIn("run-all: 1/2 scenarios executed", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
