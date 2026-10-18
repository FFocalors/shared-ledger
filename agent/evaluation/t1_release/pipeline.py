"""Fail-closed T1 v2 release preparation and one-shot bundle writer.

This module accepts already materialized in-memory rows only.  It has no
dataset discovery, generator, network, model, or database entry point.  Source
paths are a fixed allowlist; callers cannot weaken the source freeze by
providing a smaller list.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import checker
from .goldguard import GoldGuardError, validate_operation_gold
from .runtime import (
    SNAPSHOT_MANIFEST_SHA256,
    SNAPSHOT_ROOT,
    baseline_modules,
    make_v2_validator,
    verify_snapshot,
)


class ReleasePipelineError(RuntimeError):
    """A source, validation, approval, or write gate failed closed."""


AGENT_REPO_ROOT = Path(__file__).resolve().parents[3]
MAIN_REPO_ROOT = AGENT_REPO_ROOT.parent / "shared-ledger"
BUSINESS_LOGIC_RELATIVE = Path("docs/backend/BUSINESS_LOGIC.md")
V2_SCHEMA_RELATIVE = Path("agent/dataset_contracts/t1-release-v2/dataset-envelope.schema.json")
EXPECTED_PYTHON_EXECUTABLE = Path(
    r"D:\project\Android\shared-ledger-agent\agent\.venv\Scripts\python.exe"
)
TEACHER_READINESS_ROOT = Path(r"D:\AI\runs\shared-ledger\t1-teacher-readiness-v2-20261011")
TEACHER_PROBE_ROOT = Path(r"D:\AI\runs\shared-ledger\t1-teacher-probe-20261011")
TEACHER_SOURCE_SNAPSHOT_ROOT = Path(
    r"D:\AI\runs\shared-ledger\t1-release-v2-20261011\teacher-source-snapshot"
)

# The whitelist is intentionally fixed and includes every source/test that
# establishes this release protocol.  Missing files block preparation.
REQUIRED_AGENT_SOURCES = (
    "agent/evaluation/t1_release/builder.py",
    "agent/evaluation/t1_release/checker.py",
    "agent/evaluation/t1_release/goldguard.py",
    "agent/evaluation/t1_release/signatures.py",
    "agent/evaluation/t1_release/runtime.py",
    "agent/evaluation/t1_release/boundary.py",
    "agent/evaluation/t1_release/pipeline.py",
    "agent/evaluation/t1_release/human_review.py",
    "agent/evaluation/t1_release/__init__.py",
    "agent/evaluation/t1_release/tests/test_checker_v2.py",
    "agent/evaluation/t1_release/tests/test_goldguard_v2.py",
    "agent/evaluation/t1_release/tests/test_runtime_v2.py",
    "agent/evaluation/t1_release/tests/test_release_v2.py",
    "agent/evaluation/t1_release/tests/test_state_families.py",
    "agent/evaluation/t1_release/tests/test_boundary_v2.py",
    "agent/evaluation/t1_release/tests/test_pipeline_v2.py",
    "agent/evaluation/t1_release/tests/test_human_review_v2.py",
    "agent/dataset_contracts/t1-release-v2/dataset-envelope.schema.json",
    "agent/docs/t1/ACCEPTANCE_CRITERIA-T1-v1.json",
    "agent/docs/t1/release-v2/ACCEPTANCE_CRITERIA-T1-v2.json",
    "agent/docs/t1/BUSINESS_ACCEPTANCE.md",
    "agent/docs/t1/FREEZE-T1.md",
    "agent/docs/t1/MODEL_PREREG-T1-v1.json",
    "agent/docs/t1/TEACHER_STATUS-T1-v1.md",
    "agent/docs/shared-ledger-agent-development-guide-v0.4.html",
    "agent/docs/t1/release-v2/TEACHER-READINESS.md",
    "agent/docs/t1/release-v2/TEACHER-AVAILABILITY.md",
    "agent/evaluation/t1_teacher_readiness_v2/runner.py",
    "agent/evaluation/t1_teacher_readiness_v2/prompt-v2.json",
    "agent/evaluation/t1_teacher_readiness_v2/tests/test_runner.py",
    "agent/evaluation/t1_teacher_readiness_v2/preregistration.json",
    "agent/evaluation/t1_teacher_readiness_v2/evidence/ROOT_REVIEW.json",
    "agent/evaluation/t1_teacher_probe/preregistration.json",
    "agent/evaluation/t1_teacher_probe/evidence/ROOT_REVIEW.json",
    "agent/evaluation/t1_teacher_probe/probe.py",
    "agent/evaluation/t1_teacher_probe/prompts/contract-sanity-v1.json",
    "agent/evaluation/t1_teacher_probe/prompts/language-pilot-v1.json",
    "agent/evaluation/t1_teacher_probe/tests/test_probe.py",
    "scripts/ai_teacher_generator/live_provider.py",
    "agent/pyproject.toml",
    "agent/uv.lock",
)

TEACHER_EVIDENCE_SOURCES = (
    ("teacher/readiness/request.json", TEACHER_READINESS_ROOT / "request.json"),
    ("teacher/readiness/run_manifest.json", TEACHER_READINESS_ROOT / "run_manifest.json"),
    ("teacher/probe/run_manifest.json", TEACHER_PROBE_ROOT / "run_manifest.json"),
    ("teacher/source-snapshot/manifest.json", TEACHER_SOURCE_SNAPSHOT_ROOT / "manifest.json"),
    ("teacher/source-snapshot/manifest.sha256", TEACHER_SOURCE_SNAPSHOT_ROOT / "manifest.sha256"),
)

TEACHER_SOURCE_BINDINGS = {
    "readiness": {
        "fake_http_tests": "agent/evaluation/t1_teacher_readiness_v2/tests/test_runner.py",
        "legacy_provider_config_reader_read_only": "scripts/ai_teacher_generator/live_provider.py",
        "prompt": "agent/evaluation/t1_teacher_readiness_v2/prompt-v2.json",
        "runner": "agent/evaluation/t1_teacher_readiness_v2/runner.py",
    },
    "probe": {
        "business_acceptance_t1": "agent/docs/t1/BUSINESS_ACCEPTANCE.md",
        "fake_http_tests": "agent/evaluation/t1_teacher_probe/tests/test_probe.py",
        "language_prompt": "agent/evaluation/t1_teacher_probe/prompts/language-pilot-v1.json",
        "legacy_provider_adapter_read_only": "scripts/ai_teacher_generator/live_provider.py",
        "model_preregistration_read_only": "agent/docs/t1/MODEL_PREREG-T1-v1.json",
        "probe": "agent/evaluation/t1_teacher_probe/probe.py",
        "sanity_prompt": "agent/evaluation/t1_teacher_probe/prompts/contract-sanity-v1.json",
        "t1_freeze": "agent/docs/t1/FREEZE-T1.md",
        "teacher_status_t1_v1": "agent/docs/t1/TEACHER_STATUS-T1-v1.md",
        "training_guide": "agent/docs/shared-ledger-agent-development-guide-v0.4.html",
    },
}

SPLITS = ("train", "validation", "sealed")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ROOT_APPROVAL_DECISION = "approve_candidate_preparation"
_SEALED_APPROVAL_DECISION = "approve_sealed_write"
_PREPARED_RELEASE_SEAL = object()

# These external hashes were recorded and separately root-reviewed with the
# Teacher availability evidence.  The freeze does not reopen responses or
# repeat a request; it verifies only the already-saved metadata artifacts.
_TEACHER_READINESS_REQUEST_SHA256 = "238ce566518cb33cd9378a595eed0bb4d2e3cb225bf7226029e6b3e942001cec"
_TEACHER_READINESS_MANIFEST_SHA256 = "acaae39eb78dd60ed4c30da003f61d460576360f8fe5f7ee9632641b66a9b170"
_TEACHER_PROBE_MANIFEST_SHA256 = "e3efefa6f039f20f1179d1a4e529ee505a189b0a4e0ecc43c4aef018303f3345"
_TEACHER_SOURCE_SNAPSHOT_MANIFEST_SHA256 = "5cb76d33ae635d6aa1274c8933136ccac5b310e12f61b337064a36163c841ce1"


def _runtime_environment() -> dict[str, str]:
    try:
        actual = Path(sys.executable).resolve(strict=True)
        expected = EXPECTED_PYTHON_EXECUTABLE.resolve(strict=True)
    except OSError as exc:
        raise ReleasePipelineError("the pinned Python executable is unavailable") from exc
    if os.path.normcase(str(actual)) != os.path.normcase(str(expected)):
        raise ReleasePipelineError("release preparation must use the pinned agent virtualenv Python")
    try:
        jsonschema_version = importlib.metadata.version("jsonschema")
        pydantic_version = importlib.metadata.version("pydantic")
    except importlib.metadata.PackageNotFoundError as exc:
        raise ReleasePipelineError("a pinned validation dependency is unavailable") from exc
    return {
        "python_executable": str(actual),
        "python_version": platform.python_version(),
        "jsonschema_version": jsonschema_version,
        "pydantic_version": pydantic_version,
    }


def _verify_teacher_source_snapshot(
    *,
    readiness_sources: Mapping[str, Any],
    probe_sources: Mapping[str, Any],
    readiness_preregistration_sha256: str,
    probe_preregistration_sha256: str,
    snapshot_root: Path = TEACHER_SOURCE_SNAPSHOT_ROOT,
    expected_manifest_sha256: str = _TEACHER_SOURCE_SNAPSHOT_MANIFEST_SHA256,
) -> dict[str, Any]:
    """Verify immutable archived Teacher sources against the saved preregistrations."""
    if snapshot_root.is_symlink():
        raise ReleasePipelineError("Teacher source archive root cannot be a symlink")
    snapshot_root = snapshot_root.resolve(strict=True)
    if not snapshot_root.is_dir():
        raise ReleasePipelineError("Teacher source archive root is not a directory")
    manifest_path = snapshot_root / "manifest.json"
    sidecar_path = snapshot_root / "manifest.sha256"
    for control_path in (manifest_path, sidecar_path):
        try:
            resolved = control_path.resolve(strict=True)
        except OSError as exc:
            raise ReleasePipelineError("pinned Teacher source archive control file is missing") from exc
        if (control_path.is_symlink() or not resolved.is_relative_to(snapshot_root)
                or not resolved.is_file()):
            raise ReleasePipelineError("pinned Teacher source archive control file is unsafe")
    try:
        manifest_bytes = manifest_path.read_bytes()
        sidecar = sidecar_path.read_text(encoding="ascii")
        manifest = json.loads(manifest_bytes)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ReleasePipelineError("pinned Teacher source archive is unavailable or malformed") from exc
    manifest_sha = sha256_bytes(manifest_bytes)
    if (manifest_sha != expected_manifest_sha256
            or sidecar != f"{expected_manifest_sha256}  manifest.json\n"
            or not isinstance(manifest, Mapping)
            or manifest.get("format") != "teacher-source-snapshot-v1"):
        raise ReleasePipelineError("pinned Teacher source archive manifest hash is invalid")

    cohort_sources = {"readiness": readiness_sources, "probe": probe_sources}
    archived_cohorts = manifest.get("cohort_bindings")
    if not isinstance(archived_cohorts, Mapping) or set(archived_cohorts) != set(TEACHER_SOURCE_BINDINGS):
        raise ReleasePipelineError("Teacher source archive cohort binding set changed")
    expected_unique: dict[str, str] = {}
    for cohort, expected in cohort_sources.items():
        fixed = TEACHER_SOURCE_BINDINGS[cohort]
        archived = archived_cohorts.get(cohort)
        if (not isinstance(expected, Mapping) or set(expected) != set(fixed)
                or not isinstance(archived, Mapping) or set(archived) != set(fixed)):
            raise ReleasePipelineError("Teacher source archive differs from the fixed preregistration allowlist")
        for label, relative in fixed.items():
            item = archived.get(label)
            relative_text = Path(relative).as_posix()
            digest = expected.get(label)
            if (not isinstance(digest, str) or not _SHA_RE.fullmatch(digest)
                    or not isinstance(item, Mapping)
                    or item.get("source_path") != relative_text
                    or item.get("sha256") != digest):
                raise ReleasePipelineError("archived Teacher source is not bound to its saved preregistration")
            previous = expected_unique.setdefault(relative_text, digest)
            if previous != digest:
                raise ReleasePipelineError("shared Teacher source has inconsistent cohort bindings")

    provenance = manifest.get("provenance")
    if (not isinstance(provenance, Mapping)
            or provenance.get("readiness_preregistration_sha256") != readiness_preregistration_sha256
            or provenance.get("probe_preregistration_sha256") != probe_preregistration_sha256):
        raise ReleasePipelineError("Teacher source archive is bound to different preregistrations")
    saved_artifacts = provenance.get("verified_saved_artifacts")
    if not isinstance(saved_artifacts, Mapping):
        raise ReleasePipelineError("Teacher source archive lacks saved-run provenance")
    saved_run_hashes = saved_artifacts.get("saved_artifact_sha256")
    expected_saved_run_hashes = {
        "teacher/readiness/request.json": _TEACHER_READINESS_REQUEST_SHA256,
        "teacher/readiness/run_manifest.json": _TEACHER_READINESS_MANIFEST_SHA256,
        "teacher/probe/run_manifest.json": _TEACHER_PROBE_MANIFEST_SHA256,
    }
    if not isinstance(saved_run_hashes, Mapping) or dict(saved_run_hashes) != expected_saved_run_hashes:
        raise ReleasePipelineError("Teacher source archive lacks required saved artifact hashes")

    file_rows = manifest.get("files")
    if not isinstance(file_rows, list) or len(file_rows) != len(expected_unique):
        raise ReleasePipelineError("Teacher source archive file list is incomplete")
    listed: dict[str, Mapping[str, Any]] = {}
    for row in file_rows:
        if not isinstance(row, Mapping):
            raise ReleasePipelineError("Teacher source archive file entry is malformed")
        relative = row.get("source_path")
        normalized = Path(relative) if isinstance(relative, str) else Path("..")
        if (normalized.is_absolute() or ".." in normalized.parts
                or any(part.lower().startswith(".env") for part in normalized.parts)
                or not isinstance(relative, str) or relative in listed):
            raise ReleasePipelineError("Teacher source archive contains an unsafe or duplicate path")
        if (row.get("snapshot_path") != f"sources/{normalized.as_posix()}"
                or row.get("sha256") != expected_unique.get(normalized.as_posix())
                or isinstance(row.get("bytes"), bool) or not isinstance(row.get("bytes"), int)
                or row["bytes"] < 0):
            raise ReleasePipelineError("Teacher source archive file manifest differs from preregistration hashes")
        listed[relative] = row
    if set(listed) != set(expected_unique):
        raise ReleasePipelineError("Teacher source archive path set differs from saved preregistrations")

    expected_files = {"manifest.json", "manifest.sha256"}
    for relative, digest in expected_unique.items():
        relative_path = Path(relative)
        copy_path = snapshot_root / "sources" / relative_path
        cursor = snapshot_root
        for component in ("sources", *relative_path.parts):
            cursor = cursor / component
            if cursor.is_symlink():
                raise ReleasePipelineError("archived Teacher source path cannot contain symlinks")
        try:
            resolved_copy = copy_path.resolve(strict=True)
        except OSError as exc:
            raise ReleasePipelineError("archived Teacher source is missing") from exc
        if (not resolved_copy.is_relative_to(snapshot_root)
                or not resolved_copy.is_file() or _file_sha256(resolved_copy) != digest):
            raise ReleasePipelineError("archived Teacher source bytes do not match the pinned source hash")
        if resolved_copy.stat().st_size != listed[relative]["bytes"]:
            raise ReleasePipelineError("archived Teacher source byte length changed")
        expected_files.add(f"sources/{relative}")
    actual_files: set[str] = set()
    for path in snapshot_root.rglob("*"):
        if path.is_symlink():
            raise ReleasePipelineError("Teacher source archive cannot contain symlinks")
        if path.is_file():
            try:
                if not path.resolve(strict=True).is_relative_to(snapshot_root):
                    raise ReleasePipelineError("Teacher source archive path escapes its root")
            except OSError as exc:
                raise ReleasePipelineError("Teacher source archive path cannot be resolved") from exc
            actual_files.add(path.relative_to(snapshot_root).as_posix())
    if actual_files != expected_files:
        raise ReleasePipelineError("Teacher source archive contains missing or unexpected files")

    return {
        "manifest_sha256": manifest_sha,
        "file_count": len(expected_unique),
        "cohort_binding_count": sum(len(rows) for rows in TEACHER_SOURCE_BINDINGS.values()),
        "source_sha256": dict(sorted(expected_unique.items())),
    }


def _verify_saved_teacher_bindings(agent_root: Path) -> dict[str, Any]:
    """Check preregistration hashes against saved runs and archived source bytes."""
    readiness_prereg_path = agent_root / "agent/evaluation/t1_teacher_readiness_v2/preregistration.json"
    readiness_review_path = agent_root / "agent/evaluation/t1_teacher_readiness_v2/evidence/ROOT_REVIEW.json"
    probe_prereg_path = agent_root / "agent/evaluation/t1_teacher_probe/preregistration.json"
    probe_review_path = agent_root / "agent/evaluation/t1_teacher_probe/evidence/ROOT_REVIEW.json"
    try:
        readiness_prereg_bytes = readiness_prereg_path.read_bytes()
        probe_prereg_bytes = probe_prereg_path.read_bytes()
        readiness_prereg = json.loads(readiness_prereg_bytes)
        probe_prereg = json.loads(probe_prereg_bytes)
        readiness_review = json.loads(readiness_review_path.read_text(encoding="utf-8"))
        probe_review = json.loads(probe_review_path.read_text(encoding="utf-8"))
        readiness_manifest_path = TEACHER_READINESS_ROOT / "run_manifest.json"
        readiness_request_path = TEACHER_READINESS_ROOT / "request.json"
        probe_manifest_path = TEACHER_PROBE_ROOT / "run_manifest.json"
        readiness_manifest = json.loads(readiness_manifest_path.read_text(encoding="utf-8"))
        probe_manifest = json.loads(probe_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleasePipelineError("saved Teacher preregistration evidence is unavailable or malformed") from exc

    readiness_prereg_sha = sha256_bytes(readiness_prereg_bytes)
    probe_prereg_sha = sha256_bytes(probe_prereg_bytes)
    readiness_sources = readiness_prereg.get("source_sha256")
    probe_sources = probe_prereg.get("source_sha256")
    if (not isinstance(readiness_sources, Mapping) or not isinstance(probe_sources, Mapping)
            or readiness_manifest.get("source_sha256") != readiness_sources
            or probe_manifest.get("source_sha256") != probe_sources
            or readiness_manifest.get("prompt_sha256") != readiness_prereg.get("prompt_sha256")
            or probe_manifest.get("prompt_sha256") != probe_prereg.get("prompt_sha256")
            or readiness_manifest.get("preregistration_sha256") != readiness_prereg_sha
            or probe_manifest.get("preregistration_sha256") != probe_prereg_sha
            or readiness_review.get("preregistration_sha256") != readiness_prereg_sha
            or readiness_review.get("source_sha256") != readiness_sources):
        raise ReleasePipelineError("saved Teacher run hashes do not match their preregistration bindings")
    archive_binding = _verify_teacher_source_snapshot(
        readiness_sources=readiness_sources,
        probe_sources=probe_sources,
        readiness_preregistration_sha256=readiness_prereg_sha,
        probe_preregistration_sha256=probe_prereg_sha,
    )
    probe_bindings = probe_review.get("sha256_bindings", {})
    if (not isinstance(probe_bindings, Mapping)
            or probe_bindings.get("preregistration") != probe_prereg_sha
            or probe_bindings.get("run_manifest") != _TEACHER_PROBE_MANIFEST_SHA256):
        raise ReleasePipelineError("saved Teacher probe root review does not bind the preregistration and run manifest")
    actual_hashes = {
        "teacher/readiness/request.json": _file_sha256(readiness_request_path),
        "teacher/readiness/run_manifest.json": _file_sha256(readiness_manifest_path),
        "teacher/probe/run_manifest.json": _file_sha256(probe_manifest_path),
        "teacher/source-snapshot/manifest.json": _file_sha256(TEACHER_SOURCE_SNAPSHOT_ROOT / "manifest.json"),
        "teacher/source-snapshot/manifest.sha256": _file_sha256(TEACHER_SOURCE_SNAPSHOT_ROOT / "manifest.sha256"),
    }
    if (actual_hashes["teacher/readiness/request.json"] != _TEACHER_READINESS_REQUEST_SHA256
            or actual_hashes["teacher/readiness/run_manifest.json"] != _TEACHER_READINESS_MANIFEST_SHA256
            or actual_hashes["teacher/probe/run_manifest.json"] != _TEACHER_PROBE_MANIFEST_SHA256):
        raise ReleasePipelineError("saved Teacher evidence file hashes changed after root review")
    return {
        "saved_artifact_sha256": actual_hashes,
        "readiness_preregistration_sha256": readiness_prereg_sha,
        "readiness_source_sha256": dict(sorted(readiness_sources.items())),
        "probe_preregistration_sha256": probe_prereg_sha,
        "probe_source_sha256": dict(sorted(probe_sources.items())),
        "teacher_source_snapshot": archive_binding,
    }


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReleasePipelineError("release value is not canonical JSON") from exc


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ReleasePipelineError(f"required source is missing or not a regular file: {path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReleasePipelineError("cannot establish the required Git source identity") from exc
    return completed.stdout.strip()


def _git_bytes(root: Path, *args: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReleasePipelineError("cannot establish the required Git source identity") from exc
    return completed.stdout


def _source_manifest_payload(
    *,
    agent_root: Path,
    main_root: Path,
    teacher_evidence_sources: Sequence[tuple[str, Path]],
    required_agent_sources: Sequence[str],
    snapshot_root: Path,
    snapshot_expected_sha256: str,
    snapshot_verifier=verify_snapshot,
) -> dict[str, Any]:
    """Private root-injection seam for hermetic tests; public API is fixed."""
    agent_root = agent_root.resolve()
    main_root = main_root.resolve()
    if not agent_root.is_dir() or not main_root.is_dir():
        raise ReleasePipelineError("agent and main repositories must exist")

    sources: dict[str, str] = {}
    for relative in required_agent_sources:
        normalized = Path(relative)
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ReleasePipelineError("source allowlist contains an unsafe relative path")
        path = (agent_root / normalized).resolve()
        if not path.is_relative_to(agent_root):
            raise ReleasePipelineError("source path escapes the agent repository")
        sources[relative.replace("\\", "/")] = _file_sha256(path)

    business_logic = (main_root / BUSINESS_LOGIC_RELATIVE).resolve()
    if not business_logic.is_relative_to(main_root):
        raise ReleasePipelineError("business logic path escapes the main repository")
    business_hash = _file_sha256(business_logic)
    business_head = _git_bytes(main_root, "show", f"HEAD:{BUSINESS_LOGIC_RELATIVE.as_posix()}")
    business_head_sha = hashlib.sha256(business_head).hexdigest()
    main_head = _git(main_root, "rev-parse", "HEAD")
    agent_head = _git(agent_root, "rev-parse", "HEAD")

    teacher_sources: dict[str, str] = {}
    for label, path in teacher_evidence_sources:
        if Path(label).is_absolute() or ".." in Path(label).parts or ".env" in label.lower():
            raise ReleasePipelineError("teacher evidence allowlist contains an unsafe path")
        teacher_sources[label] = _file_sha256(path.resolve())

    snapshot_root = snapshot_root.resolve()
    manifest_path = snapshot_root / "snapshot-manifest.json"
    snapshot_manifest_sha = _file_sha256(manifest_path)
    if snapshot_manifest_sha != snapshot_expected_sha256:
        raise ReleasePipelineError("pinned baseline snapshot manifest hash changed")
    try:
        verified_manifest = snapshot_verifier()
    except Exception as exc:
        raise ReleasePipelineError("pinned baseline snapshot verification failed") from exc
    if not isinstance(verified_manifest, Mapping) or not isinstance(verified_manifest.get("files"), Mapping):
        raise ReleasePipelineError("snapshot verifier returned malformed manifest metadata")
    if len(verified_manifest["files"]) != 72:
        raise ReleasePipelineError("snapshot verifier did not establish the exact 72-file baseline")

    return {
        "format": "t1-release-v2-source-freeze",
        "environment": _runtime_environment(),
        "agent_git_head": agent_head,
        "main_git_head": main_head,
        "business_logic": {
            "path": "docs/backend/BUSINESS_LOGIC.md",
            "working_tree_sha256": business_hash,
            "head_blob_sha256": business_head_sha,
            "matches_head": business_hash == business_head_sha,
        },
        "snapshot": {
            "identity": snapshot_root.name,
            "manifest_sha256": snapshot_manifest_sha,
            "pinned_manifest_sha256": snapshot_expected_sha256,
            "file_count": len(verified_manifest["files"]),
        },
        "agent_sources": dict(sorted(sources.items())),
        "teacher_evidence": dict(sorted(teacher_sources.items())),
    }


def freeze_source_manifest() -> dict[str, Any]:
    """Hash the fixed source allowlist and return a content-addressed freeze."""
    payload = _source_manifest_payload(
        agent_root=AGENT_REPO_ROOT,
        main_root=MAIN_REPO_ROOT,
        teacher_evidence_sources=TEACHER_EVIDENCE_SOURCES,
        required_agent_sources=REQUIRED_AGENT_SOURCES,
        snapshot_root=SNAPSHOT_ROOT,
        snapshot_expected_sha256=SNAPSHOT_MANIFEST_SHA256,
    )
    payload["teacher_preregistration_bindings"] = _verify_saved_teacher_bindings(AGENT_REPO_ROOT)
    manifest_sha = sha256_bytes(canonical_json(payload))
    return {**payload, "source_manifest_sha256": manifest_sha}


def _source_digest(manifest: Mapping[str, Any]) -> str:
    supplied = manifest.get("source_manifest_sha256")
    body = {key: value for key, value in manifest.items() if key != "source_manifest_sha256"}
    actual = sha256_bytes(canonical_json(body))
    if supplied != actual:
        raise ReleasePipelineError("source manifest digest is invalid")
    return actual


def _verify_source_manifest(manifest: Mapping[str, Any]) -> None:
    expected = _source_digest(manifest)
    current = freeze_source_manifest()
    if current.get("source_manifest_sha256") != expected or current != dict(manifest):
        raise ReleasePipelineError("T1 source freeze changed since preparation")


def _records_bytes(records: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, bytes]:
    if not isinstance(records, Mapping) or set(records) != set(SPLITS):
        raise ReleasePipelineError("records_by_split must contain exactly train, validation, and sealed")
    payloads: dict[str, bytes] = {}
    for split in SPLITS:
        rows = records[split]
        if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence) or not rows:
            raise ReleasePipelineError(f"{split} must be a non-empty in-memory row sequence")
        lines: list[bytes] = []
        for row in rows:
            if not isinstance(row, Mapping) or row.get("split") != split:
                raise ReleasePipelineError(f"{split} contains a malformed or misassigned record")
            lines.append(canonical_json(dict(row)))
        payloads[split] = b"\n".join(lines) + b"\n"
    return payloads


def collection_sha256(records: Mapping[str, Sequence[Mapping[str, Any]]]) -> str:
    """Return the canonical split-payload digest without revealing row content."""
    payloads = _records_bytes(records)
    return sha256_bytes(canonical_json({key: sha256_bytes(value) for key, value in payloads.items()}))


def _root_review_header(root_dispositions: Any, source_sha: str, collection_sha: str) -> Mapping[str, Any]:
    if not isinstance(root_dispositions, Mapping):
        raise ReleasePipelineError("root disposition receipt is required")
    if (root_dispositions.get("decision") != _ROOT_APPROVAL_DECISION
            or root_dispositions.get("review_kind") != "root_agent"
            or not isinstance(root_dispositions.get("reviewer_id"), str)
            or not root_dispositions["reviewer_id"].strip()
            or not isinstance(root_dispositions.get("evidence"), str)
            or not root_dispositions["evidence"].strip()
            or root_dispositions.get("source_manifest_sha256") != source_sha
            or root_dispositions.get("collection_sha256") != collection_sha):
        raise ReleasePipelineError("root approval is missing or bound to different sources/collection")
    return root_dispositions


def _pair_review_map(
    preview: Mapping[str, Any], receipt: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    expected: dict[str, Mapping[str, Any]] = {}
    for item in preview.get("pair_findings", []):
        if item.get("kind") == "near_prompt_candidate":
            expected[item["finding_id"]] = item
        elif item.get("kind") == "exact_prompt_duplicate":
            raise ReleasePipelineError("exact cross-split prompt duplicate blocks preparation")
    raw = receipt.get("pair_dispositions", {})
    if not isinstance(raw, Mapping) or set(raw) != set(expected):
        raise ReleasePipelineError("root dispositions must cover exactly the current near-pair findings")
    accepted: dict[str, Mapping[str, Any]] = {}
    for finding_id, finding in expected.items():
        item = raw[finding_id]
        if not isinstance(item, Mapping):
            raise ReleasePipelineError("root near-pair disposition is malformed")
        bound = {
            "left_full_state_signature_sha256": finding["left_full_state_signature_sha256"],
            "right_full_state_signature_sha256": finding["right_full_state_signature_sha256"],
            "left_prompt_sha256": finding["left_prompt_sha256"],
            "right_prompt_sha256": finding["right_prompt_sha256"],
        }
        if (item.get("decision") != "distinct_initial_states"
                or item.get("review_kind") != "root_agent"
                or not isinstance(item.get("reviewer_id"), str)
                or not item["reviewer_id"].strip()
                or not isinstance(item.get("evidence"), str)
                or not item["evidence"].strip()
                or item.get("source_manifest_sha256") != receipt.get("source_manifest_sha256")
                or item.get("collection_sha256") != receipt.get("collection_sha256")
                or any(item.get(key) != value for key, value in bound.items())):
            raise ReleasePipelineError("root near-pair disposition is not bound to current evidence")
        accepted[finding_id] = {
            "decision": item["decision"], "review_kind": item["review_kind"],
            "reviewer_id": item["reviewer_id"], "evidence": item["evidence"], **bound,
        }
    return accepted


@dataclass(frozen=True)
class PreparedRelease:
    """Validated immutable bytes; JSON metadata is stored as canonical bytes."""

    train_bytes: bytes = field(repr=False)
    validation_bytes: bytes = field(repr=False)
    sealed_bytes: bytes = field(repr=False)
    creation_manifest_bytes: bytes = field(repr=False)
    source_manifest_bytes: bytes = field(repr=False)
    checker_report_bytes: bytes = field(repr=False)
    root_receipt_sha256: str
    collection_sha256: str
    payloads_sha256: str
    creation_manifest_sha256: str
    _seal: object = field(default=None, init=False, repr=False, compare=False)

    def __repr__(self) -> str:
        return (
            "PreparedRelease("
            f"collection_sha256={self.collection_sha256!r}, "
            f"payloads_sha256={self.payloads_sha256!r}, "
            f"creation_manifest_sha256={self.creation_manifest_sha256!r}, "
            "sealed_bytes=<redacted>)"
        )

    def verify_integrity(self) -> None:
        if self._seal is not _PREPARED_RELEASE_SEAL:
            raise ReleasePipelineError("PreparedRelease was not produced by the gated preparation path")
        payloads = {
            "train": sha256_bytes(self.train_bytes),
            "validation": sha256_bytes(self.validation_bytes),
            "sealed": sha256_bytes(self.sealed_bytes),
        }
        payload_digest = sha256_bytes(canonical_json(payloads))
        if payload_digest != self.payloads_sha256:
            raise ReleasePipelineError("prepared payload bytes were changed after validation")
        manifest = json.loads(self.creation_manifest_bytes)
        if sha256_bytes(self.creation_manifest_bytes) != self.creation_manifest_sha256:
            raise ReleasePipelineError("creation manifest bytes were changed after validation")
        if manifest.get("payload_sha256") != payloads:
            raise ReleasePipelineError("creation manifest does not bind prepared payload bytes")
        if manifest.get("collection_sha256") != self.collection_sha256:
            raise ReleasePipelineError("creation manifest collection binding changed")
        if manifest.get("root_creation_receipt_sha256") != self.root_receipt_sha256:
            raise ReleasePipelineError("creation manifest root receipt binding changed")
        source_manifest = json.loads(self.source_manifest_bytes)
        if _source_digest(source_manifest) != manifest.get("source_manifest_sha256"):
            raise ReleasePipelineError("prepared source manifest bytes are inconsistent")
        if sha256_bytes(self.checker_report_bytes) != manifest.get("checker_report_sha256"):
            raise ReleasePipelineError("prepared checker report bytes are inconsistent")

    def source_manifest(self) -> dict[str, Any]:
        return json.loads(self.source_manifest_bytes)

    def checker_report(self) -> dict[str, Any]:
        return json.loads(self.checker_report_bytes)

    def creation_manifest(self) -> dict[str, Any]:
        return json.loads(self.creation_manifest_bytes)


def prepare_in_memory(
    records_by_split: Mapping[str, Sequence[Mapping[str, Any]]],
    source_manifest: Mapping[str, Any],
    root_dispositions: Mapping[str, Any],
) -> PreparedRelease:
    """Validate every row and collection in memory before producing immutable bytes."""
    _verify_source_manifest(source_manifest)
    source_sha = _source_digest(source_manifest)
    frozen_rows: dict[str, list[dict[str, Any]]] = {}
    try:
        for split in SPLITS:
            rows = records_by_split[split]
            frozen_rows[split] = [copy.deepcopy(dict(row)) for row in rows]
    except (KeyError, TypeError, ValueError) as exc:
        raise ReleasePipelineError("all split rows must be copyable mappings") from exc
    payloads = _records_bytes(frozen_rows)
    collection_sha = sha256_bytes(canonical_json({key: sha256_bytes(value) for key, value in payloads.items()}))

    _root_review_header(root_dispositions, source_sha, collection_sha)
    validator = make_v2_validator()
    _, _, _, _, baseline_validator = baseline_modules()
    for split in SPLITS:
        for row in frozen_rows[split]:
            try:
                baseline_validator.validate_record(row, validator)
                validate_operation_gold(row)
            except Exception as exc:
                raise ReleasePipelineError(f"strict schema or independent gold validation failed in {split}") from exc

    flattened = [row for split in SPLITS for row in frozen_rows[split]]
    preview = checker.check_collection(flattened)
    accepted_pair_reviews = _pair_review_map(preview, root_dispositions)
    report = checker.check_collection(flattened, pair_dispositions=accepted_pair_reviews)
    if not report.get("collection_passed") or not report.get("preparation_eligible"):
        raise ReleasePipelineError("independent collection gate blocked the release")
    if report.get("training_eligible") is not False or report.get("training_admission") is not False:
        raise ReleasePipelineError("collection checker unexpectedly asserted training admission")
    _verify_source_manifest(source_manifest)

    source_bytes = canonical_json(dict(source_manifest))
    report_bytes = canonical_json(report)
    payload_hashes = {key: sha256_bytes(value) for key, value in payloads.items()}
    payloads_sha = sha256_bytes(canonical_json(payload_hashes))
    receipt_sha = sha256_bytes(canonical_json(dict(root_dispositions)))
    row_counts = {split: len(frozen_rows[split]) for split in SPLITS}
    manifest_body = {
        "format": "t1-release-v2-creation-manifest",
        "source_manifest_sha256": source_sha,
        "root_creation_receipt_sha256": receipt_sha,
        "collection_sha256": collection_sha,
        "checker_report_sha256": sha256_bytes(report_bytes),
        "payload_sha256": payload_hashes,
        "payloads_sha256": payloads_sha,
        "row_counts": row_counts,
        "checker_version": report.get("checker_version"),
        "collection_passed": True,
        "human_review_pending": True,
        "training_eligible": False,
        "training_blockers": [
            "external_human_review_receipt_required",
            "p2_baseline_calibration_pending",
            "t2_authorization_pending",
        ],
        "sealed_write_pending": True,
    }
    creation_bytes = canonical_json(manifest_body)
    prepared = PreparedRelease(
        train_bytes=payloads["train"],
        validation_bytes=payloads["validation"],
        sealed_bytes=payloads["sealed"],
        creation_manifest_bytes=creation_bytes,
        source_manifest_bytes=source_bytes,
        checker_report_bytes=report_bytes,
        root_receipt_sha256=receipt_sha,
        collection_sha256=collection_sha,
        payloads_sha256=payloads_sha,
        creation_manifest_sha256=sha256_bytes(creation_bytes),
    )
    object.__setattr__(prepared, "_seal", _PREPARED_RELEASE_SEAL)
    prepared.verify_integrity()
    _verify_source_manifest(source_manifest)
    return prepared


def _sealed_receipt(receipt: Any, prepared: PreparedRelease) -> dict[str, Any]:
    if not isinstance(receipt, Mapping):
        raise ReleasePipelineError("explicit one-shot sealed release receipt is required")
    if (receipt.get("decision") != _SEALED_APPROVAL_DECISION
            or receipt.get("review_kind") != "root_agent"
            or receipt.get("one_shot") is not True
            or not isinstance(receipt.get("reviewer_id"), str)
            or not receipt["reviewer_id"].strip()
            or not isinstance(receipt.get("evidence"), str)
            or not receipt["evidence"].strip()
            or receipt.get("source_manifest_sha256") != prepared.creation_manifest().get("source_manifest_sha256")
            or receipt.get("collection_sha256") != prepared.collection_sha256
            or receipt.get("creation_manifest_sha256") != prepared.creation_manifest_sha256
            or receipt.get("sealed_payload_sha256") != sha256_bytes(prepared.sealed_bytes)):
        raise ReleasePipelineError("sealed one-shot receipt is invalid or bound to different bytes")
    return dict(receipt)


def write_prepared_release(
    prepared: PreparedRelease,
    output_root: str | Path,
    sealed_release_receipt: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Atomically publish train/validation then write sealed exactly once last.

    The destination must not exist.  The source freeze and all prevalidated
    bytes are checked again immediately before writing.  A partial failure is
    intentionally not overwritten or retried automatically.
    """
    if not isinstance(prepared, PreparedRelease):
        raise ReleasePipelineError("only an immutable PreparedRelease can be written")
    prepared.verify_integrity()
    _verify_source_manifest(prepared.source_manifest())
    receipt = _sealed_receipt(sealed_release_receipt, prepared)
    output = Path(output_root).expanduser().resolve(strict=False)
    if output.drive.upper() != "D:":
        raise ReleasePipelineError("T1 release output must be on D:")
    if output.exists() or output.is_symlink():
        raise ReleasePipelineError("release destination already exists; overwrite is forbidden")
    agent_root = AGENT_REPO_ROOT.resolve()
    main_root = MAIN_REPO_ROOT.resolve()
    snapshot_root = SNAPSHOT_ROOT.resolve()
    if any(output.is_relative_to(root) for root in (agent_root, main_root, snapshot_root)):
        raise ReleasePipelineError("release output must stay outside source repositories and frozen snapshot")

    parent = output.parent
    parent.mkdir(parents=True, exist_ok=True)
    stage = parent / f".{output.name}.staging-{uuid.uuid4().hex}"
    stage.mkdir()
    try:
        (stage / "train.jsonl").write_bytes(prepared.train_bytes)
        (stage / "validation.jsonl").write_bytes(prepared.validation_bytes)
        (stage / "creation-manifest.json").write_bytes(prepared.creation_manifest_bytes)
        (stage / "checker-report.json").write_bytes(prepared.checker_report_bytes)
        write_receipt = {
            "format": "t1-sealed-write-receipt-v1",
            "receipt": receipt,
            "receipt_sha256": sha256_bytes(canonical_json(receipt)),
            "creation_manifest_sha256": prepared.creation_manifest_sha256,
            "source_manifest_sha256": prepared.creation_manifest().get("source_manifest_sha256"),
            "collection_sha256": prepared.collection_sha256,
        }
        (stage / "sealed-write-receipt.json").write_bytes(canonical_json(write_receipt))
        # Same-volume directory rename publishes the train/validation pair in
        # one operation and never replaces an existing release directory.
        _verify_source_manifest(prepared.source_manifest())
        prepared.verify_integrity()
        os.rename(stage, output)
    except Exception:
        # Only remove a staging directory that has not been atomically moved.
        if stage.exists():
            for child in stage.iterdir():
                child.unlink()
            stage.rmdir()
        raise

    # This is deliberately the final release-file write.  Exclusive creation
    # makes a retry or second invocation fail without replacing sealed bytes.
    _verify_source_manifest(prepared.source_manifest())
    prepared.verify_integrity()
    sealed_path = output / "sealed.jsonl"
    try:
        with sealed_path.open("xb") as stream:
            written = stream.write(prepared.sealed_bytes)
            if written != len(prepared.sealed_bytes):
                raise OSError("short sealed write")
            stream.flush()
            os.fsync(stream.fileno())
    except Exception as exc:
        raise ReleasePipelineError("sealed one-shot write failed; destination is preserved and cannot be retried") from exc
    return {
        "output_root": str(output),
        "creation_manifest_sha256": prepared.creation_manifest_sha256,
        "source_manifest_sha256": prepared.creation_manifest().get("source_manifest_sha256"),
        "collection_sha256": prepared.collection_sha256,
        "sealed_payload_sha256": sha256_bytes(prepared.sealed_bytes),
        "sealed_written_last": True,
        "human_review_pending": True,
        "training_eligible": False,
    }


__all__ = [
    "PreparedRelease", "ReleasePipelineError", "canonical_json", "collection_sha256",
    "freeze_source_manifest", "prepare_in_memory", "sha256_bytes", "write_prepared_release",
]
