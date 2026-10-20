"""Run the frozen v2 generation stage in an isolated process.

The v2 release tooling pins the v1 baseline from the v2 snapshot and refuses to
run once the frozen v1.1 package is loaded; this package pins the v1.1 package
from the release-v3 snapshot.  The two pins are both legitimate, so the
generation stage is executed in a child process instead of weakening either.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import profile

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE = "agent.evaluation.t1_release_v3.generate_v2_rows"


class BridgeError(RuntimeError):
    pass


def generate_rows(requests: list[dict[str, Any]]) -> dict[str, Any]:
    """Generate the requested rows with the frozen v2 generator.

    Returns ``{"rows": {key: row}, "contexts": {key: {...}}, "namespace": ...}``.
    """
    work = profile.RUN_ROOT / "conversion" / "_generation"
    work.mkdir(parents=True, exist_ok=True)
    spec_path = work / "spec.json"
    out_path = work / "rows.json"
    spec_path.write_bytes(
        (json.dumps({"rows": requests}, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    )
    if out_path.exists():
        out_path.unlink()
    completed = subprocess.run(
        [sys.executable, "-m", MODULE, "--spec", str(spec_path), "--out", str(out_path)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise BridgeError(
            "the frozen v2 generation stage failed:\n"
            f"{completed.stdout[-4000:]}\n{completed.stderr[-4000:]}"
        )
    if not out_path.is_file():
        raise BridgeError("the generation stage produced no output")
    return json.loads(out_path.read_text(encoding="utf-8"))
