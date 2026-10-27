"""The committed contract snapshot must always match the exported source.

This is the gate that makes `python -m agent.app.export_contracts --check`
unskippable: editing any contract source without re-exporting fails the suite.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent.app import contracts as c
from agent.app import export_contracts


CONTRACTS_ROOT = Path(__file__).resolve().parents[1] / "contracts"


def test_committed_snapshot_matches_the_source_contracts() -> None:
    failures = export_contracts.check_snapshot()
    assert failures == [], (
        "contract snapshot drift; run `python -m agent.app.export_contracts`:\n"
        + "\n".join(failures)
    )


def test_snapshot_directory_is_derived_from_the_api_version() -> None:
    assert export_contracts.OUT == CONTRACTS_ROOT / f"v{c.API_VERSION}"
    assert c.API_VERSION == "1.1.0"
    manifest = json.loads((export_contracts.OUT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["api_version"] == "1.1.0"
    assert manifest["semantic_version"] == c.SEMANTIC_VERSION
    assert manifest["operations_version"] == c.OPERATIONS_VERSION
    assert manifest["trajectory_version"] == c.TRAJECTORY_VERSION
    # The self hash stays null: a manifest cannot contain its own digest.
    assert manifest["self_hash"] is None


def test_previous_contract_version_is_kept_as_history() -> None:
    previous = CONTRACTS_ROOT / "v1.0.0" / "manifest.json"
    assert previous.is_file()
    manifest = json.loads(previous.read_text(encoding="utf-8"))
    assert manifest["api_version"] == "1.0.0"
    # The current check never rewrites or validates history.
    assert export_contracts.OUT != previous.parent


def test_drift_detection_reports_a_changed_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(export_contracts, "OUT", tmp_path / "vsnapshot")
    export_contracts.write_snapshot()
    assert export_contracts.check_snapshot() == []

    target = export_contracts.OUT / "openapi.json"
    target.write_bytes(target.read_bytes() + b" \n")
    failures = export_contracts.check_snapshot()
    assert "drift: openapi.json" in failures


def test_drift_detection_reports_a_missing_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(export_contracts, "OUT", tmp_path / "vsnapshot")
    export_contracts.write_snapshot()
    (export_contracts.OUT / "manifest.json").unlink()
    failures = export_contracts.check_snapshot()
    assert "missing: manifest.json" in failures


def test_drift_detection_reports_an_unexpected_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(export_contracts, "OUT", tmp_path / "vsnapshot")
    export_contracts.write_snapshot()
    (export_contracts.OUT / "schemas" / "Stale.schema.json").write_text("{}\n", encoding="utf-8")
    failures = export_contracts.check_snapshot()
    assert "unexpected: schemas/Stale.schema.json" in failures
