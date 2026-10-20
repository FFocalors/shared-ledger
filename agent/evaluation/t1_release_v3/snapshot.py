"""Pinned generation baseline for the release-v3 (offline v1.1 canonical) work.

A v3 run may not read mutable working-tree sources.  Two frozen sets are
copied into one hash-checked snapshot:

* the 72-file v1 baseline contract/simulator set, byte-copied from the
  already-frozen v2 snapshot (its manifest hash is re-asserted), and
* the 19 files of the frozen offline protocol v1.1.0 (9 package sources +
  10 exported schemas), each verified against the v1.1 export manifest
  before it is copied.

The v1.1 export manifest is the authority for the second set, so a working
tree that drifted from the approved v1.1 freeze refuses to snapshot.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import profile

AGENT_DIR = Path(__file__).resolve().parents[2]  # the agent/ package directory


class SnapshotError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    return _sha256(path.read_bytes())


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def legacy_snapshot_files() -> dict[str, dict[str, Any]]:
    """The 72 frozen v1 baseline files, re-verified against the v2 snapshot."""
    manifest_path = profile.V2_SNAPSHOT_ROOT / "snapshot-manifest.json"
    if not manifest_path.is_file():
        raise SnapshotError(f"frozen v2 baseline snapshot is missing: {manifest_path}")
    if _file_sha256(manifest_path) != profile.V2_SNAPSHOT_MANIFEST_SHA256:
        raise SnapshotError("frozen v2 baseline snapshot manifest hash changed")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("files")
    if not isinstance(entries, dict) or len(entries) != 72:
        raise SnapshotError("frozen v2 baseline snapshot must bind exactly 72 files")
    for relative, item in entries.items():
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise SnapshotError("v2 snapshot manifest contains an unsafe relative path")
    return entries


def v11_manifest() -> dict[str, Any]:
    path = AGENT_DIR / profile.V11_MANIFEST_RELATIVE
    if not path.is_file():
        raise SnapshotError(f"frozen v1.1 protocol manifest is missing: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("format") != "t1-offline-protocol-manifest-v1.1.0":
        raise SnapshotError("unexpected v1.1 protocol manifest format")
    if manifest.get("profile") != profile.V11_PROFILE:
        raise SnapshotError("v1.1 protocol manifest profile differs from the conversion target")
    return manifest


def v11_snapshot_sources() -> dict[str, bytes]:
    """The 19 frozen v1.1 files, each proved against the v1.1 export manifest."""
    payloads: dict[str, bytes] = {}
    manifest = v11_manifest()

    sources = manifest.get("source_hashes")
    if not isinstance(sources, dict) or len(sources) != 9:
        raise SnapshotError("v1.1 manifest must bind exactly 9 package sources")
    package_prefix = f"agent/{profile.V11_PACKAGE_RELATIVE.as_posix()}/"
    for recorded, expected in sources.items():
        if not recorded.startswith(package_prefix):
            raise SnapshotError(f"unexpected v1.1 package source path: {recorded}")
        name = recorded[len(package_prefix):]
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".py":
            raise SnapshotError(f"v1.1 package source must be a safe module path: {name}")
        path = AGENT_DIR / profile.V11_PACKAGE_RELATIVE / relative
        if not path.is_file():
            raise SnapshotError(f"v1.1 package source is missing: {name}")
        data = path.read_bytes()
        if _sha256(data) != expected:
            raise SnapshotError(
                f"v1.1 package source drifted from the frozen export manifest: {name}"
            )
        payloads[(profile.V11_PACKAGE_RELATIVE / relative).as_posix()] = data

    schemas = manifest.get("schema_hashes")
    if not isinstance(schemas, dict) or len(schemas) != 10:
        raise SnapshotError("v1.1 manifest must bind exactly 10 exported schemas")
    schema_dir = profile.V11_SCHEMA_DIR_RELATIVE
    for name, expected in schemas.items():
        if "/" in name or not name.endswith(".json"):
            raise SnapshotError(f"v1.1 schema name must be a flat file: {name}")
        path = AGENT_DIR / schema_dir / name
        if not path.is_file():
            raise SnapshotError(f"v1.1 exported schema is missing: {name}")
        data = path.read_bytes()
        if _sha256(data) != expected:
            raise SnapshotError(
                f"v1.1 exported schema drifted from the frozen export manifest: {name}"
            )
        payloads[(schema_dir / name).as_posix()] = data

    if len(payloads) != 19:
        raise SnapshotError("v1.1 snapshot set must contain exactly 19 files")
    return payloads


def build_snapshot(*, root: Path | None = None) -> dict[str, Any]:
    """Materialise the v3 snapshot once.  Refuses to overwrite an existing one."""
    target = (root or profile.SNAPSHOT_ROOT).resolve()
    manifest_path = target / "snapshot-manifest.json"
    if target.exists():
        if manifest_path.is_file():
            return load_snapshot_manifest(target)
        raise SnapshotError(f"refusing to write into a non-snapshot directory: {target}")

    legacy = legacy_snapshot_files()
    files: dict[str, Any] = {}
    for relative, item in legacy.items():
        data = (profile.V2_SNAPSHOT_ROOT / "agent" / Path(relative)).read_bytes()
        if _sha256(data) != item["snapshot_sha256"]:
            raise SnapshotError(f"frozen v2 baseline file failed hash check: {relative}")
        destination = target / "agent" / Path(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        files[relative] = {
            "snapshot_sha256": _sha256(data),
            "bytes": len(data),
            "origin": "v1-baseline-72",
        }

    for relative, data in v11_snapshot_sources().items():
        destination = target / "agent" / Path(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        files[relative] = {
            "snapshot_sha256": _sha256(data),
            "bytes": len(data),
            "origin": "offline-protocol-v1.1.0",
        }

    v11 = v11_manifest()
    manifest = {
        "format": profile.SNAPSHOT_FORMAT,
        "profile": profile.V11_PROFILE,
        "release_version": profile.RELEASE_VERSION,
        "legacy_source_snapshot": {
            "root": str(profile.V2_SNAPSHOT_ROOT),
            "manifest_sha256": profile.V2_SNAPSHOT_MANIFEST_SHA256,
            "files": 72,
        },
        "protocol_v1_1": {
            "manifest_relative": profile.V11_MANIFEST_RELATIVE.as_posix(),
            "manifest_sha256": _file_sha256(AGENT_DIR / profile.V11_MANIFEST_RELATIVE),
            "versions": v11["versions"],
            "files": 19,
        },
        "file_count": len(files),
        "files": files,
    }
    manifest["snapshot_manifest_sha256"] = _sha256(_canonical(manifest))
    target.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(_canonical(manifest) + b"\n")
    return manifest


def load_snapshot_manifest(root: Path | None = None) -> dict[str, Any]:
    manifest_path = (root or profile.SNAPSHOT_ROOT) / "snapshot-manifest.json"
    if not manifest_path.is_file():
        raise SnapshotError(f"v3 snapshot manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != profile.SNAPSHOT_FORMAT:
        raise SnapshotError("unexpected v3 snapshot manifest format")
    return manifest


def verify_snapshot(root: Path | None = None) -> dict[str, Any]:
    """Re-prove every snapshotted byte.  Called before and after a generation."""
    base = (root or profile.SNAPSHOT_ROOT).resolve()
    manifest = load_snapshot_manifest(base)
    recorded = dict(manifest)
    claimed = recorded.pop("snapshot_manifest_sha256", None)
    if claimed != _sha256(_canonical(recorded)):
        raise SnapshotError("v3 snapshot manifest self-hash does not match its content")
    files = manifest.get("files")
    if not isinstance(files, dict) or len(files) != manifest.get("file_count"):
        raise SnapshotError("v3 snapshot manifest file table is malformed")
    if len(files) != 91:
        raise SnapshotError("v3 snapshot must bind exactly 91 files (72 baseline + 19 v1.1)")
    for relative, item in files.items():
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise SnapshotError("v3 snapshot manifest contains an unsafe relative path")
        path = base / "agent" / Path(relative)
        if not path.is_file():
            raise SnapshotError(f"v3 snapshot file is missing: {relative}")
        if _file_sha256(path) != item["snapshot_sha256"]:
            raise SnapshotError(f"v3 snapshot file failed hash check: {relative}")
    return manifest
