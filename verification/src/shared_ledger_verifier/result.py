"""Writing the four small artifacts produced for every scenario run."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def write_run_artifacts(
    run_dir: str | Path,
    *,
    scenario_bytes: bytes | None,
    result: Mapping[str, Any],
    operations: Sequence[Mapping[str, Any]],
    state_final: Mapping[str, Any],
) -> None:
    """Write the original scenario and the three result files for a run."""

    path = Path(run_dir)
    path.mkdir(parents=True, exist_ok=True)
    if scenario_bytes is not None:
        (path / "scenario.json").write_bytes(scenario_bytes)
    else:
        (path / "scenario.json").write_text("", encoding="utf-8")
    (path / "result.json").write_text(_json_text(result), encoding="utf-8")
    lines = [json.dumps(item, ensure_ascii=False, default=_json_default) for item in operations]
    (path / "operations.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    (path / "state_final.json").write_text(_json_text(state_final), encoding="utf-8")


def _json_text(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=_json_default) + "\n"
