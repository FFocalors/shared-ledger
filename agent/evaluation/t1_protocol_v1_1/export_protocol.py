"""Deterministic Draft 2020-12 schema/example export and drift checker.

Run from the repository root with:
  agent/.venv/Scripts/python.exe -m evaluation.t1_protocol_v1_1.export_protocol --write
  agent/.venv/Scripts/python.exe -m evaluation.t1_protocol_v1_1.export_protocol --check
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator
from . import v1_contracts as v1
from .contracts import (
    DecisionEnvelopeV11,
    ModelContext,
    NegotiatedVersions,
    ProtocolVersionTuple,
    QueryEvidenceObservation,
    build_semantic_decision_schema,
)
from .examples import (
    build_participant_filtered_read_trace,
    build_three_complete_examples,
    build_two_turn_clarify_propose_trace,
)
from .harness import render_query_answer
from .protocol_registry import (
    DatasetApplicabilityPolicy,
    ProtocolRegistry,
    build_dataset_applicability_policy,
    build_protocol_registry,
)
from .trajectory import build_adaptation_schema, build_trajectory_schema


ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "agent" / "evaluation" / "t1_protocol_v1_1"
OUTPUT = Path(os.environ.get(
    "T1_PROTOCOL_EXPORT_DIR",
    str(ROOT / "agent" / "dataset_contracts" / "t1-protocol-v1.1.0"),
)).resolve()
SOURCE_ARCHIVE = OUTPUT / "source-inputs"
DOCS = ROOT / "agent" / "docs" / "t1" / "protocol-v1.1.0"
DRAFT = "https://json-schema.org/draft/2020-12/schema"

PACKAGE_SOURCES = (
    "__init__.py",
    "contracts.py",
    "examples.py",
    "export_protocol.py",
    "harness.py",
    "protocol_registry.py",
    "trajectory.py",
    "v1_contracts.py",
    "tests/test_protocol_v1_1.py",
)
DOC_FILES = (
    "PROTOCOL.md",
    "MIGRATION.md",
    "REQUIREMENTS.json",
    "REQUIREMENTS.md",
    "ROOT_REVIEW.md",
    "evidence/RESULTS.md",
    "evidence/SOURCE-INPUTS.json",
)
SCHEMA_FILES = (
    "adaptation-envelope.schema.json",
    "decision-envelope-v1.1.schema.json",
    "model-context.schema.json",
    "negotiated-versions.schema.json",
    "protocol-registry.schema.json",
    "protocol-version-tuple.schema.json",
    "query-evidence.schema.json",
    "semantic-decision.schema.json",
    "trajectory.schema.json",
    "dataset-applicability.schema.json",
)
EXAMPLE_FILES = (
    "activities-empty.json",
    "debts-cad-empty.json",
    "expenses-postfilter-empty.json",
    "clarify-resume-trace.json",
    "participant-filtered-read-trace.json",
)


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _schema(schema: dict[str, Any], name: str) -> dict[str, Any]:
    result = dict(schema)
    result["$schema"] = DRAFT
    result["$id"] = f"https://shared-ledger.invalid/schemas/{name}"
    Draft202012Validator.check_schema(result)
    return result


def build_protocol_schemas() -> dict[str, dict[str, Any]]:
    negotiation = NegotiatedVersions.model_json_schema(mode="validation")
    version_tuple = {
        "$schema": DRAFT,
        "$id": "https://shared-ledger.invalid/schemas/t1-protocol-version-tuple-1.1.0.json",
        "title": "ProtocolVersionTuple",
        "oneOf": [],
    }
    profiles = (
        {"api_version": "1.0.0", "semantic_version": "1.0.0", "operations_version": "1.0.0", "trajectory_version": "1.0.0", "execution_key_version": "1"},
        {"api_version": "1.0.0", "semantic_version": "1.1.0", "operations_version": "1.1.0", "trajectory_version": "1.1.0", "execution_key_version": "1"},
    )
    for profile in profiles:
        version_tuple["oneOf"].append({
            "type": "object",
            "properties": {key: {"const": value, "type": "string"} for key, value in profile.items()},
            "required": list(profile),
            "additionalProperties": False,
        })
    schemas = {
        SCHEMA_FILES[0]: build_adaptation_schema(),
        SCHEMA_FILES[1]: _schema(DecisionEnvelopeV11.model_json_schema(mode="validation"), "t1-decision-envelope-1.1.0.json"),
        SCHEMA_FILES[2]: _schema(ModelContext.model_json_schema(mode="validation"), "t1-model-context-1.1.0.json"),
        SCHEMA_FILES[3]: _schema(negotiation, "t1-negotiated-versions-1.1.0.json"),
        SCHEMA_FILES[4]: _schema(ProtocolRegistry.model_json_schema(mode="validation"), "t1-protocol-registry-1.1.0.json"),
        SCHEMA_FILES[5]: version_tuple,
        SCHEMA_FILES[6]: _schema(QueryEvidenceObservation.model_json_schema(mode="validation"), "t1-query-evidence-1.1.0.json"),
        SCHEMA_FILES[7]: build_semantic_decision_schema(),
        SCHEMA_FILES[8]: build_trajectory_schema(),
        SCHEMA_FILES[9]: _schema(
            DatasetApplicabilityPolicy.model_json_schema(mode="validation"),
            "t1-dataset-applicability-1.1.0.json",
        ),
    }
    for item in schemas.values():
        Draft202012Validator.check_schema(item)
    return schemas


def build_protocol_examples() -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    names = ("activities-empty", "debts-cad-empty", "expenses-postfilter-empty")
    for name, example in zip(names, build_three_complete_examples(), strict=True):
        validated = example.validate()
        answer = render_query_answer(validated, expected_context=example.context)
        output[f"{name}.json"] = {
            "format": "t1-offline-query-example-v1.1.0",
            "synthetic_only": True,
            "training_eligible": False,
            "model_context": example.context.model_dump(mode="json"),
            "typed_read_results": [item.model_dump(mode="json") for item in example.context.read_results],
            "query_observations": [item.model_dump(mode="json") for item in example.context.query_observations],
            "trusted_rendered_decision": answer.model_dump(mode="json"),
        }
    for name, trace in (
        ("clarify-resume-trace", build_two_turn_clarify_propose_trace()),
        ("participant-filtered-read-trace", build_participant_filtered_read_trace()),
    ):
        output[f"{name}.json"] = {
            "format": "t1-offline-causal-trace-v1.1.0",
            "synthetic_only": True,
            "training_eligible": False,
            "model_contexts": [
                step.context.model_dump(mode="json")
                for step in trace.steps
                if hasattr(step, "context")
            ],
            "trace": trace.model_dump(mode="json"),
        }
    return output


def source_input_paths() -> dict[str, Path]:
    return {
        "vendor/v1_contracts.py": PACKAGE / "v1_contracts.py",
        "agent/app/contracts.py": ROOT / "agent" / "app" / "contracts.py",
        # Read-only projection references used to compare UTC filtering and
        # accepted-input/recent-message behavior. They are archived once and
        # never consulted by --check or imported at runtime.
        "reference/p2_backend.py": ROOT / "agent" / "app" / "p2_backend.py",
        "reference/p2_runtime.py": ROOT / "agent" / "app" / "p2_runtime.py",
        "agent/docs/p1/PROTOCOL_FREEZE.md": ROOT / "agent" / "docs" / "p1" / "PROTOCOL_FREEZE.md",
        "agent/docs/p2/CONTRACT-VERSION-DIFF.md": ROOT / "agent" / "docs" / "p2" / "CONTRACT-VERSION-DIFF.md",
        "agent/docs/p2/IMPLEMENTATION_PLAN.md": ROOT / "agent" / "docs" / "p2" / "IMPLEMENTATION_PLAN.md",
        "agent/docs/t1/release-v2/ROOT-BUSINESS-REVIEW.md": ROOT / "agent" / "docs" / "t1" / "release-v2" / "ROOT-BUSINESS-REVIEW.md",
        "agent/docs/t1/release-v2/P2-CALIBRATION-REVIEW-FINDINGS.md": ROOT / "agent" / "docs" / "t1" / "release-v2" / "P2-CALIBRATION-REVIEW-FINDINGS.md",
        "reference/business/BUSINESS_LOGIC.md": ROOT.parent / "shared-ledger" / "docs" / "backend" / "BUSINESS_LOGIC.md",
        "external/root-protected-baseline.json": Path("D:/AI/runs/shared-ledger/t1-protocol-v1.1.0-20261011/root-protected-baseline.json"),
        "external/root-freeze-requirements.json": Path("D:/AI/runs/shared-ledger/t1-protocol-v1.1.0-20261011/root-freeze-requirements.json"),
        "agent/pyproject.toml": ROOT / "agent" / "pyproject.toml",
        "agent/requirements-contracts.txt": ROOT / "agent" / "requirements-contracts.txt",
        "agent/uv.lock": ROOT / "agent" / "uv.lock",
        "agent/toolchain-contracts.json": ROOT / "agent" / "toolchain-contracts.json",
    }


def _runtime_dependency_snapshot() -> dict[str, Any]:
    packages = ("pydantic", "pydantic-core", "jsonschema", "pytest", "typing-extensions")
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "packages": {name: importlib.metadata.version(name) for name in packages},
    }


def _source_archive_payloads() -> dict[str, bytes]:
    missing = [f"{name} => {path}" for name, path in source_input_paths().items() if not path.is_file()]
    if missing:
        raise FileNotFoundError("source snapshot input missing: " + ", ".join(missing))
    vendor = (PACKAGE / "v1_contracts.py").read_bytes()
    app_contract = (ROOT / "agent" / "app" / "contracts.py").read_bytes()
    if _sha256(vendor) != "9fd214d9d8eb43c6f5b03b1d7e95b2bef274dbf9e8be495f536f495b48a5bf2d":
        raise ValueError("vendored v1 contracts snapshot hash changed; create a separately reviewed new candidate")
    if _sha256(app_contract) != _sha256(vendor):
        raise ValueError("v1 app contracts no longer byte-match the explicitly vendored protocol snapshot")
    payloads = {relative: path.read_bytes() for relative, path in sorted(source_input_paths().items())}
    payloads["runtime-dependencies.json"] = _canonical_json(_runtime_dependency_snapshot())
    return payloads


def _capture_source_archive() -> None:
    if (OUTPUT / "manifest.json").exists():
        raise ValueError("an existing manifest is immutable; use a new versioned candidate to rebind sources")
    if _existing_relative_files(SOURCE_ARCHIVE):
        _validate_source_archive()
        return
    payloads = _source_archive_payloads()
    archive_names = list(payloads)
    for name in archive_names:
        posix_path = PurePosixPath(name)
        if posix_path.is_absolute() or ".." in posix_path.parts or Path(name).is_absolute():
            raise ValueError(f"source archive path escapes its dedicated directory: {name}")
    if len(set(archive_names)) != len(archive_names) or "index.json" in archive_names:
        raise ValueError("source archive input inventory contains a duplicate/reserved path")
    live_sources = source_input_paths()
    entries = [
        {
            "archive_path": name,
            "source_path": str(live_sources[name].resolve()) if name in live_sources else "generated:runtime-dependencies",
            "source_sha256": _sha256(content),
            "size_bytes": len(content),
        }
        for name, content in sorted(payloads.items())
    ]
    p2_source_refs = {
        path.relative_to(ROOT).as_posix(): _sha256(path.read_bytes())
        for path in sorted((ROOT / "agent" / "app").glob("p2_*.py"))
    }
    index = {
        "format": "t1-source-input-snapshot-v1",
        "capture_policy": "one-time; check reads archived bytes only; P2 module hashes are provenance references, not check dependencies",
        "entries": entries,
        "p2_module_provenance_sha256": p2_source_refs,
        "runtime_dependencies_archive_path": "runtime-dependencies.json",
    }
    SOURCE_ARCHIVE.mkdir(parents=True, exist_ok=True)
    for relative, content in sorted(payloads.items()):
        target = SOURCE_ARCHIVE / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    (SOURCE_ARCHIVE / "index.json").write_bytes(_canonical_json(index))


def _validate_source_archive() -> dict[str, Any]:
    index_path = SOURCE_ARCHIVE / "index.json"
    if not index_path.is_file():
        raise FileNotFoundError("source archive exists without index.json; refusing to recapture")
    index_bytes = index_path.read_bytes()
    index = json.loads(index_bytes)
    if index.get("format") != "t1-source-input-snapshot-v1":
        raise ValueError("unsupported source archive index format")
    entries = index.get("entries")
    if not isinstance(entries, list):
        raise ValueError("source archive index has no entries list")
    expected = {"index.json"}
    hash_map: dict[str, str] = {}
    for entry in entries:
        relative = entry.get("archive_path")
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("source archive path must remain inside its dedicated directory")
        expected.add(relative)
        content = (SOURCE_ARCHIVE / Path(relative)).read_bytes()
        digest = _sha256(content)
        if digest != entry.get("source_sha256") or len(content) != entry.get("size_bytes"):
            raise ValueError(f"source archive hash/size mismatch: {relative}")
        hash_map[relative] = digest
    _check_inventory(SOURCE_ARCHIVE, expected, label="source archive")
    return {"index": index, "hashes": hash_map, "index_sha256": _sha256(index_bytes)}


def build_export_files() -> dict[str, bytes]:
    missing_docs = [rel for rel in DOC_FILES if not (DOCS / rel).is_file()]
    if missing_docs:
        raise FileNotFoundError(
            "export documentation prerequisites missing; docs=" + ", ".join(missing_docs)
        )
    _check_source_inventory()
    source_archive = _validate_source_archive()

    package_source_hashes = {
        f"agent/evaluation/t1_protocol_v1_1/{rel}": _sha256((PACKAGE / rel).read_bytes())
        for rel in PACKAGE_SOURCES
    }
    source_input_hashes = source_archive["hashes"]
    doc_hashes = {
        f"agent/docs/t1/protocol-v1.1.0/{rel}": _sha256((DOCS / rel).read_bytes())
        for rel in DOC_FILES
    }
    schemas = build_protocol_schemas()
    examples = build_protocol_examples()
    if set(schemas) != set(SCHEMA_FILES) or set(examples) != set(EXAMPLE_FILES):
        raise RuntimeError("protocol schema/example export inventory changed unexpectedly")

    files: dict[str, bytes] = {}
    schema_hashes: dict[str, str] = {}
    for name, schema in sorted(schemas.items()):
        content = _canonical_json(schema)
        files[f"schemas/{name}"] = content
        schema_hashes[name] = _sha256(content)
    example_hashes: dict[str, str] = {}
    for name, example in sorted(examples.items()):
        content = _canonical_json(example)
        files[f"examples/{name}"] = content
        example_hashes[name] = _sha256(content)

    manifest = {
        "format": "t1-offline-protocol-manifest-v1.1.0",
        "profile": "t1-offline-canonical",
        "versions": {
            "api": "1.0.0",
            "semantic": "1.1.0",
            "operations": "1.1.0",
            "trajectory": "1.1.0",
            "execution_key": "1",
        },
        "status": "offline_frozen_candidate_external_sha_bound_root_approval_required",
        "root_approved": False,
        "root_approval_receipt_required": True,
        "root_approval_receipt_sha256": None,
        "root_approval_binding": "external receipt binds exact manifest, schema and documentation hashes; receipt is not embedded here",
        "production_enabled": False,
        "training_eligible": False,
        "execution_enabled": False,
        "source_hashes": package_source_hashes,
        "source_input_hashes": source_input_hashes,
        "source_archive_index_sha256": source_archive["index_sha256"],
        "p2_module_provenance_sha256": source_archive["index"].get("p2_module_provenance_sha256", {}),
        "schema_hashes": schema_hashes,
        "example_hashes": example_hashes,
        "documentation_hashes": doc_hashes,
        "capability_count": 17,
        "operation_count": 6,
        "executable_operation_count": 0,
        "source_provenance": "synthetic_only; source string does not authorize P2 issuance",
    }
    files["manifest.json"] = _canonical_json(manifest)
    registry_bytes = _canonical_json(build_protocol_registry().model_dump(mode="json"))
    applicability_bytes = _canonical_json(build_dataset_applicability_policy().model_dump(mode="json"))
    files["registry.json"] = registry_bytes
    files["applicability-policy.json"] = applicability_bytes
    files["source-inputs/index.json"] = (SOURCE_ARCHIVE / "index.json").read_bytes()
    for relative, digest in source_input_hashes.items():
        files[f"source-inputs/{relative}"] = (SOURCE_ARCHIVE / Path(relative)).read_bytes()
    files["manifest.json"] = _canonical_json({
        **manifest,
        "registry_sha256": _sha256(registry_bytes),
        "applicability_policy_sha256": _sha256(applicability_bytes),
    })
    return files


def _existing_relative_files(directory: Path) -> set[str]:
    if not directory.exists():
        return set()
    return {path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file()}


def _check_inventory(directory: Path, expected: set[str], *, label: str) -> None:
    actual = _existing_relative_files(directory)
    unknown = sorted(actual - expected)
    missing = sorted(expected - actual)
    if unknown or missing:
        raise ValueError(f"{label} inventory mismatch; missing={missing}; unknown={unknown}")


def _check_source_inventory() -> None:
    package_expected = set(PACKAGE_SOURCES)
    package_actual = {
        path.relative_to(PACKAGE).as_posix()
        for path in PACKAGE.rglob("*")
        if path.is_file()
        and not any(part in {"__pycache__", ".pytest_cache"} for part in path.relative_to(PACKAGE).parts)
        and path.suffix != ".pyc"
    }
    if package_actual != package_expected:
        raise ValueError(
            f"protocol source inventory mismatch; missing={sorted(package_expected-package_actual)}; "
            f"unknown={sorted(package_actual-package_expected)}"
        )
    doc_expected = set(DOC_FILES)
    doc_actual = _existing_relative_files(DOCS)
    if doc_actual != doc_expected:
        raise ValueError(
            f"documentation inventory mismatch; missing={sorted(doc_expected-doc_actual)}; "
            f"unknown={sorted(doc_actual-doc_expected)}"
        )


def write_export(files: dict[str, bytes]) -> None:
    expected = set(files)
    if OUTPUT.exists():
        actual = _existing_relative_files(OUTPUT)
        unknown = sorted(actual - expected)
        if unknown:
            raise ValueError(f"export contains unknown files; refusing to overwrite: {unknown}")
        if (OUTPUT / "manifest.json").exists():
            check_export(files)
            print("existing candidate verified; immutable source archive and manifest were not rewritten")
            return
    for relative, content in sorted(files.items()):
        target = OUTPUT / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def check_export(files: dict[str, bytes]) -> None:
    expected = set(files)
    _check_inventory(OUTPUT, expected, label="export")
    mismatched = [rel for rel, content in files.items() if (OUTPUT / rel).read_bytes() != content]
    if mismatched:
        raise ValueError(f"export drift detected in: {sorted(mismatched)}")
    _check_source_inventory()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write deterministic draft schemas, examples and manifest")
    mode.add_argument("--check", action="store_true", help="check source drift, output bytes and unknown files")
    args = parser.parse_args(argv)
    try:
        if not PACKAGE.is_dir() or Path.cwd().resolve() != ROOT:
            raise RuntimeError(f"run from repository root: {ROOT}")
        if args.write and not (OUTPUT / "manifest.json").exists():
            if SOURCE_ARCHIVE.exists() and not (SOURCE_ARCHIVE / "index.json").exists() and _existing_relative_files(SOURCE_ARCHIVE):
                raise ValueError("partial source archive exists; refusing recapture")
            _capture_source_archive()
        files = build_export_files()
        if args.write:
            write_export(files)
            try:
                display_path = OUTPUT.relative_to(ROOT).as_posix()
            except ValueError:
                display_path = str(OUTPUT)
            print(f"wrote {len(files)} deterministic files under {display_path}")
        else:
            check_export(files)
            print(f"checked {len(files)} files; no source, schema, example, documentation or inventory drift")
    except Exception as exc:
        print(f"export_protocol: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
