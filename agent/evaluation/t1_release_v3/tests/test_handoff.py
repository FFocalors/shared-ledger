"""Tests for the two handoff packages."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.evaluation.t1_release_v3 import (  # noqa: E402
    handoff, hashing, near_pairs, packet, profile,
)

HANDOFF = profile.REVIEW_ROOT / handoff.REVIEW_HANDOFF
NEAR = HANDOFF / handoff.NEAR_DIR
HUMAN = HANDOFF / handoff.HUMAN_DIR


@pytest.fixture(scope="module", autouse=True)
def packages():
    if not (NEAR / "STATUS.json").is_file() or not (HUMAN / "STATUS.json").is_file():
        handoff.main([])


def _status(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_near_pair_package_states_the_role_honestly():
    status = _status(NEAR / "STATUS.json")
    assert status["findings_total"] == 5429
    assert status["original_review_kind"] == "assistant_technical_review"
    assert status["accepted_by_gate"] == "root_agent"
    assert status["collection_gate_currently_passed"] is False
    assert status["human_reviewed"] is False
    assert status["training_eligible"] is False
    assert sum(status["categories"].values()) == status["findings_total"]
    assert status["categories"]["unclassified"] == 0
    readme = (NEAR / "README.md").read_text(encoding="utf-8")
    assert "not** a `root_agent`" in readme or "not a `root_agent`" in readme
    assert "must not re-run" in readme


def test_near_pair_dispositions_are_sanitised_and_bound():
    raw = json.loads((NEAR / "near-pair-dispositions-v3.json").read_text(encoding="utf-8"))
    status = _status(NEAR / "STATUS.json")
    assert len(raw) == status["findings_total"]
    assert hashing.sha256(raw) == status["dispositions_sha256"]
    for key, item in raw.items():
        # No free text and no sealed identifiers: only the category, the
        # reviewer identity and the hash bindings survive sanitisation.
        assert "evidence" not in item
        assert "sealed" not in json.dumps(item).lower()
        assert item["category"] in near_pairs.CATEGORIES
        assert len(item["left_full_state_signature_sha256"]) == 64
        assert len(item["left_prompt_sha256"]) == 64
    assert (NEAR / "reissue-dispositions.py").is_file()


def test_human_receipt_package_leaves_signing_to_a_human():
    status = _status(HUMAN / "STATUS.json")
    assert status["packet_rows"] == 34
    assert status["receipt_status"] == "pending"
    assert status["human_reviewed"] is False
    assert status["training_eligible"] is False
    assert status["training_blockers"]
    receipt = json.loads(
        (HUMAN / "pending-human-review-receipt.json").read_text(encoding="utf-8")
    )
    assert receipt["status"] == "pending"
    assert receipt["decision"] is None
    assert receipt["reviewer_id"] is None
    assert receipt["human_reviewed"] is False
    manifest = json.loads((HUMAN / "human-review-manifest.json").read_text(encoding="utf-8"))
    assert receipt["packet_sha256"] == manifest["packet_sha256"] == status["packet_sha256"]
    assert receipt["selection_sha256"] == manifest["selection_sha256"]
    assert (HUMAN / "sign-receipt.py").is_file()
    assert (HUMAN / "train-review-v3.md").is_file()


def test_receipt_gate_still_refuses_the_pending_template():
    manifest = json.loads((HUMAN / "human-review-manifest.json").read_text(encoding="utf-8"))
    receipt = json.loads(
        (HUMAN / "pending-human-review-receipt.json").read_text(encoding="utf-8")
    )
    state = packet.validate_external_receipt(manifest, receipt)
    assert state["human_reviewed"] is False
    assert state["training_eligible"] is False
