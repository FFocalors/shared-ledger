from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from textwrap import dedent

import pytest
from jsonschema import ValidationError

from agent.evaluation.t1_release.builder import _make_record
from agent.evaluation.t1_release.runtime import SNAPSHOT_ROOT, baseline_modules, make_v2_validator


REPO_ROOT = Path(__file__).resolve().parents[4]
CORE_SNAPSHOT_FILES = {
    "app/contracts.py",
    "app/harness.py",
    "evaluation/data_signature.py",
    "evaluation/data_simulator.py",
    "evaluation/data_validate.py",
}


def _run_isolated(source: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", dedent(source), *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        timeout=90,
        check=False,
    )


@pytest.mark.parametrize(
    "preload",
    ["agent_app", "evaluation"],
)
def test_mutable_workspace_modules_preloaded_before_runtime_are_rejected(preload: str) -> None:
    if preload == "agent_app":
        source = """
            import agent.app.contracts
            from agent.evaluation.t1_release import runtime
            try:
                runtime.verify_snapshot()
            except runtime.BaselineError:
                print('REJECTED')
            else:
                print('ACCEPTED')
        """
    else:
        source = """
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path.cwd() / 'agent'))
            import evaluation.data_signature
            from agent.evaluation.t1_release import runtime
            try:
                runtime.verify_snapshot()
            except runtime.BaselineError:
                print('REJECTED')
            else:
                print('ACCEPTED')
        """
    result = _run_isolated(source)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "REJECTED"


def test_namespace_packages_are_pinned_before_frozen_imports() -> None:
    result = _run_isolated(
        """
        import importlib
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path.cwd() / 'agent'))
        import evaluation
        import agent
        from agent.evaluation.t1_release import runtime
        runtime.verify_snapshot()
        contracts, _, signature, simulator, validator = runtime.baseline_modules()
        expected = runtime.SNAPSHOT_AGENT.resolve()
        assert Path(next(iter(evaluation.__path__))).resolve() == (expected / 'evaluation')
        assert Path(next(iter(agent.__path__))).resolve() == expected
        modules = (contracts, signature, simulator, validator)
        assert all(Path(module.__file__).resolve().is_relative_to(expected) for module in modules)
        assert Path(importlib.import_module('evaluation.data_signature').__file__).resolve() == (
            expected / 'evaluation/data_signature.py'
        )
        print('PINNED')
        """
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "PINNED"


def test_any_noncore_hash_change_in_a_temp_snapshot_copy_is_rejected() -> None:
    manifest_path = SNAPSHOT_ROOT / "snapshot-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    noncore = next(path for path in manifest["files"] if path not in CORE_SNAPSHOT_FILES)

    # The copy lives under this D: checkout and is removed after the isolated check.
    with tempfile.TemporaryDirectory(prefix="t1-runtime-snapshot-copy-", dir=REPO_ROOT) as temp_dir:
        copied_root = Path(temp_dir) / "baseline-snapshot"
        shutil.copytree(SNAPSHOT_ROOT, copied_root)
        changed_file = copied_root / "agent" / Path(noncore)
        with changed_file.open("ab") as stream:
            stream.write(b"\n# isolated hash-integrity test\n")

        result = _run_isolated(
            """
            import sys
            from pathlib import Path
            from agent.evaluation.t1_release import runtime
            root = Path(sys.argv[1]).resolve()
            runtime.SNAPSHOT_ROOT = root
            runtime.SNAPSHOT_AGENT = root / 'agent'
            runtime._SNAPSHOT_STAT_CACHE = {}
            try:
                runtime.verify_snapshot()
            except runtime.BaselineError:
                print('REJECTED')
            else:
                print('ACCEPTED')
            """,
            str(copied_root),
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "REJECTED"


def test_strict_v2_schema_rejects_an_invalid_nested_state_envelope() -> None:
    record = _make_record("expense.create", 0)
    validator = make_v2_validator()
    _, _, _, _, data_validate = baseline_modules()
    data_validate.validate_record(record, validator)

    invalid = json.loads(json.dumps(record))
    invalid["operation_state"]["actor"]["unexpected_nested_field"] = "not in strict schema"
    with pytest.raises(ValidationError):
        data_validate.validate_record(invalid, validator)
