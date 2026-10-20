"""Tests for the release-v3 candidate build, its gates and its review packet."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.evaluation.t1_release_v3 import (  # noqa: E402
    freeze, hashing, packet, profile, rbr04, runtime, snapshot,
)

CANDIDATE = profile.RUN_ROOT / "candidate-v3"
REPORT = profile.REVIEW_ROOT / "candidate-report.json"
PACKET_DIR = profile.REVIEW_ROOT / "human-review-v3"


@pytest.fixture(scope="module")
def report():
    snapshot.verify_snapshot()
    if not REPORT.is_file():
        from agent.evaluation.t1_release_v3 import build_candidate

        build_candidate.main([])
    return json.loads(REPORT.read_text(encoding="utf-8"))


def test_source_freeze_is_fresh_and_self_consistent(report):
    manifest = json.loads((profile.REVIEW_ROOT / "source-manifest.json").read_text("utf-8"))
    freeze.verify_source_manifest(manifest)
    assert manifest["source_manifest_sha256"] == report["source_manifest_sha256"]
    assert manifest["release_version"] == profile.RELEASE_VERSION
    assert manifest["snapshot_manifest_sha256"] == snapshot.verify_snapshot()["snapshot_manifest_sha256"]
    # No v2 receipt is reachable from this preparation.
    text = json.dumps(manifest)
    for reused in ("f25401a9a4680781a13ef5cee2c94950aa2798f57d2627b0f6f1bb018afdf68e",
                   "08bebb9c96101d6be09c4d5273d4ff7b019c4608c8057aeac64b661f3e0ea820"):
        assert reused not in text


def test_candidate_has_every_row_and_every_rbr_fix(report):
    assert report["row_counts"] == profile.EXPECTED_ROW_COUNTS_V3
    assert report["row_count"] == sum(report["row_counts"].values())
    applied = report["rbr_items_applied"]
    for item in profile.ACTIVE_RBR_ITEMS:
        assert applied[item] > 0, item
    assert applied[profile.RBR01_QUERY_EVIDENCE] == 3
    assert applied[profile.RBR04_AA_TAIL_COVERAGE] == (
        len(rbr04.RBR04_CASES) + len(rbr04.BASE_AA_CASES)
    )
    assert len(rbr04.BASE_AA_CASES) == 12
    assert len(report["base_aa_cases"]) == 12


def test_every_written_row_validates_and_replays(report):
    assert report["validation"]["failures"] == 0
    assert report["validation"]["replay_failures"] == 0
    assert report["validation"]["tool_observations_replayed"] > 200
    validator = runtime.make_v3_validator()
    from agent.evaluation.t1_release_v3 import convert

    total = 0
    for split in ("train", "validation"):
        raw = (CANDIDATE / f"{split}.jsonl").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == report["payload_sha256"][split]
        for line in raw.decode("utf-8").splitlines():
            row = json.loads(line)
            total += 1
            assert list(validator.iter_errors(row)) == []
            assert row["release_version"] == profile.RELEASE_VERSION
            assert row["versions"]["semantic"] == profile.V11_SEMANTIC_VERSION
            for step in row["trace"]:
                if step["kind"] == "model":
                    for hint in convert.TRAINING_ONLY_HINTS:
                        assert hint not in step["context"]["input_text"]
    assert total == report["row_counts"]["train"] + report["row_counts"]["validation"]


def test_family_floor_and_sealed_hold(report):
    gate = report["collection_gate"]
    for operation, per_split in gate["operation_family_counts"].items():
        for split, count in per_split.items():
            # The floor is "at least 20"; read.expenses carries four extra
            # independent base-currency coverage families per split.
            assert count >= 20, (operation, split, count)
            if operation == "read.expenses":
                assert count == 24, (operation, split, count)
            else:
                assert count == 20, (operation, split, count)
    assert report["sealed_written"] is False
    assert report["collection_gate"]["training_eligible"] is False
    assert "root adjudication" in " ".join(report["external_gates_pending"])
    # Unresolved near pairs are the only reason the collection gate does not pass.
    assert gate["collection_passed"] is False
    assert gate["near_pair_findings"] > 0


def test_review_packet_is_new_and_binds_its_rows(report):
    if not (PACKET_DIR / "human-review-manifest.json").is_file():
        packet.build()
    manifest = json.loads((PACKET_DIR / "human-review-manifest.json").read_text("utf-8"))
    assert manifest["row_count"] == 34
    assert manifest["split"] == "train"
    assert manifest["release_version"] == profile.RELEASE_VERSION
    assert manifest["receipt_status"] == "pending"
    # Every required stratum and every RBR fix is visible to the reviewer.
    for name, count in manifest["coverage"].items():
        assert count > 0, name
    assert manifest["coverage"]["rbr01-query-evidence"] == 3
    # Files hash to what the manifest says.
    for entry in manifest["files"]:
        data = (PACKET_DIR / entry["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        assert len(data) == entry["bytes"]


def test_receipt_gate_refuses_a_fabricated_approval():
    manifest = json.loads((PACKET_DIR / "human-review-manifest.json").read_text("utf-8"))
    pending = json.loads(
        (PACKET_DIR / "pending-human-review-receipt.json").read_text("utf-8")
    )
    # The shipped receipt is pending and claims nothing.
    state = packet.validate_external_receipt(manifest, pending)
    assert state["human_reviewed"] is False
    assert state["training_eligible"] is False

    # A pending receipt that pretends to be reviewed is rejected.
    forged = dict(pending, human_reviewed=True, decision="approved")
    with pytest.raises(packet.PacketError):
        packet.validate_external_receipt(manifest, forged)

    # An "approved" receipt without a named human and evidence is rejected.
    unsigned = dict(pending, status="approved", decision="approved", human_reviewed=True,
                    reviewer_kind="agent", reviewer_id="t1-release-v3-checker",
                    evidence="automated")
    with pytest.raises(packet.PacketError):
        packet.validate_external_receipt(manifest, unsigned)

    # Even a properly signed receipt cannot by itself make data trainable.
    signed = dict(pending, status="approved", decision="approved", human_reviewed=True,
                  reviewer_kind="human", reviewer_id="reviewer-1", evidence="ticket-1")
    state = packet.validate_external_receipt(manifest, signed)
    assert state["human_reviewed"] is True
    assert state["training_eligible"] is False
    assert state["training_blockers"]


def test_selection_is_deterministic_and_balanced():
    rows = []
    for split in ("train", "validation"):
        rows += [json.loads(line)
                 for line in (CANDIDATE / f"{split}.jsonl").read_text("utf-8").splitlines()]
    first = [row["sample_id"] for row in packet.select_rows(rows)]
    second = [row["sample_id"] for row in packet.select_rows(rows)]
    assert first == second
    assert len(first) == len(set(first)) == 34
    assert hashing.sha256(first) == hashing.sha256(second)
