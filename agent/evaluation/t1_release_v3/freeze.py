"""A fresh source freeze for the release-v3 preparation.

The v2 source manifest pinned a fixed allowlist for the v2 generator.  A new
version needs its own freeze, so this records the exact bytes this preparation
depends on: the release-v3 tooling, the v2 generator it drives, the generated
envelope schema, the frozen v1.1 inputs, and the pinned snapshot.  No v2 receipt
is reused.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import hashing, profile

AGENT_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = AGENT_DIR.parent

# Every source this preparation depends on, repository-relative.
AGENT_SOURCES = (
    "agent/evaluation/t1_release_v3/__init__.py",
    "agent/evaluation/t1_release_v3/profile.py",
    "agent/evaluation/t1_release_v3/snapshot.py",
    "agent/evaluation/t1_release_v3/schema.py",
    "agent/evaluation/t1_release_v3/runtime.py",
    "agent/evaluation/t1_release_v3/hashing.py",
    "agent/evaluation/t1_release_v3/v11_evidence.py",
    "agent/evaluation/t1_release_v3/convert.py",
    "agent/evaluation/t1_release_v3/rbr03.py",
    "agent/evaluation/t1_release_v3/rbr04.py",
    # These four determine the candidate's AA allocations and its review
    # artefacts, so a freeze that omits them does not bind what it claims to.
    "agent/evaluation/t1_release_v3/base_allocation.py",
    "agent/evaluation/t1_release_v3/near_pairs.py",
    "agent/evaluation/t1_release_v3/packet.py",
    "agent/evaluation/t1_release_v3/handoff.py",
    "agent/evaluation/t1_release_v3/bridge.py",
    "agent/evaluation/t1_release_v3/generate_v2_rows.py",
    "agent/evaluation/t1_release_v3/slice_rbr01.py",
    "agent/evaluation/t1_release_v3/slice_rbr03.py",
    "agent/evaluation/t1_release_v3/slice_rbr04.py",
    "agent/evaluation/t1_release_v3/build_candidate.py",
    "agent/evaluation/t1_release_v3/freeze.py",
    # The frozen v2 generator this preparation drives, unmodified in behaviour.
    "agent/evaluation/t1_release/builder.py",
    "agent/evaluation/t1_release/boundary.py",
    "agent/evaluation/t1_release/goldguard.py",
    "agent/evaluation/t1_release/checker.py",
    "agent/evaluation/t1_release/signatures.py",
    "agent/evaluation/t1_release/runtime.py",
    # The conversion target and its generated envelope.
    "agent/dataset_contracts/t1-release-v3/dataset-envelope.schema.json",
    "agent/dataset_contracts/t1-protocol-v1.1.0/manifest.json",
    "agent/dataset_contracts/t1-protocol-v1.1.0/applicability-policy.json",
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def freeze_source_manifest() -> dict[str, Any]:
    from . import snapshot

    manifest = snapshot.verify_snapshot()
    missing = [name for name in AGENT_SOURCES if not (REPO_ROOT / name).is_file()]
    if missing:
        raise RuntimeError(f"source freeze is missing required files: {missing}")

    sources = {
        name: {"sha256": _sha256_file(REPO_ROOT / name), "bytes": (REPO_ROOT / name).stat().st_size}
        for name in AGENT_SOURCES
    }
    v11 = snapshot.v11_manifest()
    payload: dict[str, Any] = {
        "format": "t1-release-v3-source-freeze",
        "release_version": profile.RELEASE_VERSION,
        "profile": profile.V11_PROFILE,
        "versions": {
            "api": profile.V11_API_VERSION,
            "semantic": profile.V11_SEMANTIC_VERSION,
            "operations": profile.V11_OPERATIONS_VERSION,
            "trajectory": profile.V11_TRAJECTORY_VERSION,
            "execution_key": profile.V11_EXECUTION_KEY_VERSION,
        },
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "agent_git_head": _git("rev-parse", "HEAD"),
        "agent_git_dirty": bool(_git("status", "--porcelain")),
        "main_git_head": _git("-C", str(REPO_ROOT.parent / "shared-ledger"), "rev-parse", "HEAD"),
        "snapshot_manifest_sha256": manifest["snapshot_manifest_sha256"],
        "protocol_v1_1_manifest_sha256": _sha256_file(
            AGENT_DIR / profile.V11_MANIFEST_RELATIVE
        ),
        "protocol_v1_1_versions": v11["versions"],
        "source_count": len(sources),
        "sources": sources,
    }
    payload["source_manifest_sha256"] = hashing.sha256(payload)
    return payload


def write_source_manifest(payload: dict[str, Any] | None = None) -> Path:
    payload = payload or freeze_source_manifest()
    target = profile.REVIEW_ROOT / "source-manifest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(
        (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    return target


def verify_source_manifest(payload: dict[str, Any]) -> None:
    """Re-prove every frozen source.  Called before and after a generation."""
    recorded = dict(payload)
    claimed = recorded.pop("source_manifest_sha256", None)
    if claimed != hashing.sha256(recorded):
        raise RuntimeError("source manifest self-hash does not match its content")
    for name, entry in payload["sources"].items():
        path = REPO_ROOT / name
        if not path.is_file() or _sha256_file(path) != entry["sha256"]:
            raise RuntimeError(f"frozen source changed during the preparation: {name}")
