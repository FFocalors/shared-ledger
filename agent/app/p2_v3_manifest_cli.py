"""Create a local V3 execution manifest using the existing verifier format.

This CLI only hashes source/configuration files and emits schema metadata. It
does not load a model, inspect the model artifact, start a service, or contact
any endpoint. A generated manifest is a local pin, not an approval decision.
"""

from __future__ import annotations

import argparse
from email.parser import BytesParser
from email.policy import compat32
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

from . import p2_event_contracts_v3, p2_read_contracts_v3
from .p2_local_endpoint import normalize_local_p2_endpoint, parse_local_p2_endpoint
from .p2_read_contracts_v3 import P2_DEBT_SOURCE_VARIANT, P2_V3_CANDIDATE_PROFILE_ID, P2_V3_VERSIONS
from .p2_v3_execution_cohort import (
    MAX_COMPONENT_BYTES,
    P2V3ExecutionManifestError,
    P2V3ManifestComponent,
    _BUDGETS,
    _canonical_bytes,
    _component_digest,
    _REQUIRED_PRODUCTION_ROLES,
    verify_execution_manifest_file,
)


_ROLE_PATHS = {
    "agent_store": "agent/app/store.py",
    "p2_v3_store": "agent/app/p2_source_store_v3.py",
    "migration_001": "agent/migrations/001_initial.sql",
    "migration_002": "agent/app/p2_read_store_migration.sql",
    "migration_003": "agent/app/p2_source_store_v3_migration.sql",
    "migration_004": "agent/app/p2_v3_source_proof_migration.sql",
    "migration_005": "agent/app/p2_v3_metadata_acceptance_migration.sql",
    "migration_006": "agent/app/p2_v3_scope_fence_capture_migration.sql",
    "read_contracts": "agent/app/p2_read_contracts_v3.py",
    "event_contracts": "agent/app/p2_event_contracts_v3.py",
    "source_codec": "agent/app/p2_source_codec_v3.py",
    "source_backend": "agent/app/p2_read_backend.py",
    "runtime": "agent/app/p2_runtime.py",
    "api": "agent/app/api.py",
    "provider_adapter": "agent/app/p2_read_provider_v3.py",
    "provider_configuration": "agent/app/components.py",
    "prompt_source": "agent/app/p2_read_prompt_v3.py",
    "dependency_lock": "agent/uv.lock",
    "app_settings": "agent/app/settings.py",
    "app_entrypoint": "agent/app/main.py",
    "shared_provider": "agent/app/p2_model_provider.py",
    "native_v3_provider": "agent/app/p2_read_native_provider_v3.py",
    "token_budget_checker": "agent/app/p2_token_budget.py",
    "local_endpoint_policy": "agent/app/p2_local_endpoint.py",
    "format_repair_policy": "agent/app/p2_format_repair.py",
    "runtime_policy": "agent/app/p2_v3_runtime_policy.py",
    "sent_decision_guard": "agent/app/p2_v3_sent_guard.py",
    "store_budget_port": "agent/app/p2_v3_store_ports.py",
    "p2_identity": "agent/app/p2_identity.py",
    "p2_harness": "agent/app/p2_harness.py",
    "p2_journal": "agent/app/p2_journal.py",
    "execution_cohort_verifier": "agent/app/p2_v3_execution_cohort.py",
    "legacy_auth": "agent/app/auth.py",
    "legacy_contracts": "agent/app/contracts.py",
    "legacy_ports": "agent/app/ports.py",
    "legacy_runtime": "agent/app/runtime.py",
    "legacy_backend": "agent/app/backend.py",
    "legacy_gateway": "agent/app/gateway.py",
    "legacy_model_provider": "agent/app/model_provider.py",
    "legacy_harness": "agent/app/harness.py",
    "p2_backend_transport": "agent/app/p2_backend.py",
    "p2_prompt_policy": "agent/app/p2_prompt_policy.py",
    "p2_schema_wire": "agent/app/p2_schema_wire.py",
    "legacy_p2_event_contracts": "agent/app/p2_event_contracts.py",
    "legacy_p2_read_contracts": "agent/app/p2_read_contracts.py",
    "p2_read_store": "agent/app/p2_read_store.py",
}

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FIXED_EXTERNAL_ROLES = ("schema_bundle", "model_configuration", "counter_sdk_metadata")
_FILENAMES = (
    "p2-v3-schema-bundle.json",
    "p2-v3-model-configuration.json",
    "lmstudio-sdk-METADATA",
    "p2-v3-execution-manifest.json",
)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_text(value: str, name: str, *, limit: int = 2048) -> str:
    if type(value) is not str or not value or len(value) > limit or value != value.strip():
        raise ValueError(f"{name} is invalid")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{name} contains a control character")
    return value


def _absolute_path(value: str, name: str) -> Path:
    text = _require_text(value, name, limit=4096)
    path = Path(text)
    if not path.is_absolute():
        raise ValueError(f"{name} must be absolute")
    return path.resolve(strict=False)


def _read_regular(path: Path, limit: int, name: str) -> bytes:
    if path.is_symlink():
        raise ValueError(f"{name} must not be a symlink")
    with path.open("rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError(f"{name} is not a regular file within its size limit")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"{name} exceeds its size limit")
    return raw


def _component(role: str, relative: str, root: Path) -> tuple[dict[str, Any], P2V3ManifestComponent]:
    path = root.joinpath(*relative.split("/"))
    raw = _read_regular(path, MAX_COMPONENT_BYTES, role)
    item = {"path": relative, "role": role, "bytes": len(raw), "sha256": _sha(raw)}
    return item, P2V3ManifestComponent(relative, role, len(raw), item["sha256"])


def _counter_metadata(raw: bytes) -> tuple[str, str]:
    message = BytesParser(policy=compat32).parsebytes(raw)
    name = str(message.get("Name", "")).strip()
    version = str(message.get("Version", "")).strip()
    if name.casefold() != "lmstudio" or not version or len(version) > 64:
        raise ValueError("counter SDK metadata must identify the lmstudio distribution and version")
    if any(ord(char) < 33 or ord(char) > 126 for char in version):
        raise ValueError("counter SDK version is not safe printable metadata")
    return name, version


def _build_schema_bundle() -> bytes:
    bundle = {
        "format": "p2-v3-schema-bundle",
        "read": p2_read_contracts_v3.export_p2_v3_json_schemas(),
        "events": p2_event_contracts_v3.export_p2_v3_event_json_schemas(),
    }
    return _canonical(bundle)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, help="new D-drive directory for the generated files")
    parser.add_argument("--repository-root", default=None)
    parser.add_argument("--model-key", required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:1234/v1/chat/completions")
    parser.add_argument("--artifact-path", required=True)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--artifact-size-bytes", required=True, type=int)
    parser.add_argument("--lmstudio-model-path", required=True)
    parser.add_argument("--counter-python", required=True)
    parser.add_argument("--counter-sdk-metadata", required=True)
    parser.add_argument("--max-output-tokens", type=int, default=768)
    parser.add_argument(
        "--provider-wire", choices=("compatibility", "native_candidate"), default="compatibility",
        help="pin the P2 v3 provider wire; native_candidate uses /api/v1/chat with a prompt-only schema",
    )
    parser.add_argument("--http-timeout-seconds", type=float, default=30.0)
    return parser


def generate(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = _absolute_path(args.output_dir, "output directory")
    if output_dir.drive.casefold() != "d:":
        raise ValueError("output directory must be on D:")
    repository_root = Path(args.repository_root).resolve(strict=True) if args.repository_root else Path(__file__).resolve().parents[2]
    if not repository_root.is_dir():
        raise ValueError("repository root is invalid")

    model_key = _require_text(args.model_key, "model key", limit=256)
    endpoint = normalize_local_p2_endpoint(args.endpoint)
    endpoint_origin = parse_local_p2_endpoint(endpoint).origin
    artifact_path = _absolute_path(args.artifact_path, "artifact path")
    artifact_sha = args.artifact_sha256
    if type(artifact_sha) is not str or _SHA256.fullmatch(artifact_sha) is None:
        raise ValueError("artifact digest must be lowercase SHA-256 hex")
    if type(args.artifact_size_bytes) is not int or args.artifact_size_bytes <= 0:
        raise ValueError("artifact size must be a positive integer")
    lmstudio_model_path = _require_text(args.lmstudio_model_path, "LM Studio model path", limit=4096)
    counter_python = _absolute_path(args.counter_python, "counter Python path")
    output_tokens = args.max_output_tokens
    if type(output_tokens) is not int or not 1 <= output_tokens <= 1536:
        raise ValueError("max output tokens must be between 1 and 1536")
    if 6144 + output_tokens + 512 > 8192:
        raise ValueError("input, output, and schema margin exceed the fixed context")
    timeout_seconds = args.http_timeout_seconds
    if (
        not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool)
        or not 0.1 <= float(timeout_seconds) <= 90.0
        or (args.provider_wire == "compatibility" and float(timeout_seconds) > 30.0)
    ):
        raise ValueError("HTTP timeout must be at most 30 seconds for compatibility or 90 for native_candidate")

    sdk_metadata_path = _absolute_path(args.counter_sdk_metadata, "counter SDK metadata path")
    sdk_metadata = _read_regular(sdk_metadata_path, 1024 * 1024, "counter SDK metadata")
    sdk_name, sdk_version = _counter_metadata(sdk_metadata)
    schema_raw = _build_schema_bundle()
    if len(schema_raw) > MAX_COMPONENT_BYTES:
        raise ValueError("generated schema bundle exceeds the verifier component limit")

    model_config_raw = _canonical({
        "format": "p2-v3-nonsecret-model-configuration",
        "profile_id": P2_V3_CANDIDATE_PROFILE_ID,
        "model_key": model_key,
        "endpoint_url": endpoint,
        "provider_wire": args.provider_wire,
        "native_endpoint_url": (
            endpoint_origin + "/api/v1/chat" if args.provider_wire == "native_candidate" else None
        ),
        "artifact": {
            "path": str(artifact_path),
            "sha256": artifact_sha,
            "size_bytes": args.artifact_size_bytes,
            "verification": "identity supplied by operator; artifact file not read by this CLI",
        },
        "lmstudio_model_path": lmstudio_model_path,
        "counter": {
            "python_executable": str(counter_python),
            "sdk_distribution": sdk_name,
            "sdk_version": sdk_version,
            "metadata_sha256": _sha(sdk_metadata),
        },
        "limits": {
            "context_tokens": 8192,
            "input_tokens": 6144,
            "output_tokens": output_tokens,
            "schema_safety_margin_tokens": 512,
            "temperature": 0,
            "parallelism": 1,
            "counter_deadline_seconds": 5,
            "http_timeout_seconds": float(timeout_seconds),
        },
    })

    output_dir.mkdir(parents=True, exist_ok=True)
    if output_dir.is_symlink() or any((output_dir / name).exists() for name in _FILENAMES):
        raise FileExistsError("output directory contains an existing manifest-generator output")

    external_payloads = {
        "schema_bundle": (_FILENAMES[0], schema_raw),
        "model_configuration": (_FILENAMES[1], model_config_raw),
        "counter_sdk_metadata": (_FILENAMES[2], sdk_metadata),
    }
    for _, (name, raw) in external_payloads.items():
        path = output_dir / name
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())

    components: list[dict[str, Any]] = []
    component_objects: list[P2V3ManifestComponent] = []
    for role, relative in _ROLE_PATHS.items():
        item, obj = _component(role, relative, repository_root)
        components.append(item)
        component_objects.append(obj)
    for role, (name, raw) in external_payloads.items():
        item = {"path": name, "role": role, "bytes": len(raw), "sha256": _sha(raw)}
        components.append(item)
        component_objects.append(P2V3ManifestComponent(name, role, len(raw), item["sha256"]))

    roles = {item["role"] for item in components}
    if roles != _REQUIRED_PRODUCTION_ROLES:
        raise ValueError("generator role map does not exactly match the verifier's production role set")
    manifest = {
        "format": "p2-v3-execution-manifest",
        "manifest_kind": "production",
        "profile_id": P2_V3_CANDIDATE_PROFILE_ID,
        "versions": P2_V3_VERSIONS.model_dump(mode="json"),
        "schema_bundle_sha256": _sha(schema_raw),
        "source_manifest_sha256": _component_digest(component_objects),
        "contract_source_sha256": next(item.sha256 for item in component_objects if item.role == "read_contracts"),
        "components": components,
        "safe_config": {
            "debt_source_variant": P2_DEBT_SOURCE_VARIANT,
            "budgets": dict(_BUDGETS),
            "provider_wire": args.provider_wire,
            "model_key": model_key,
            "endpoint_origin": endpoint_origin,
            "http_timeout_seconds": float(timeout_seconds),
            "max_output_tokens": output_tokens,
        },
    }
    manifest_raw = _canonical(manifest)
    manifest_path = output_dir / _FILENAMES[3]
    with manifest_path.open("xb") as stream:
        stream.write(manifest_raw)
        stream.flush()
        os.fsync(stream.fileno())
    manifest_sha = _sha(manifest_raw)
    external_roots = {role: output_dir for role in _FIXED_EXTERNAL_ROLES}
    verified = verify_execution_manifest_file(
        manifest_path,
        expected_manifest_sha256=manifest_sha,
        repository_root=repository_root,
        external_component_roots=external_roots,
    )
    if verified.manifest_kind != "production":
        raise P2V3ExecutionManifestError("generated manifest did not verify as production")
    return {
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "repository_root": str(repository_root),
        "external_component_roots": {key: str(value) for key, value in external_roots.items()},
        "component_count": len(components),
        "roles": sorted(roles),
        "provider_wire": args.provider_wire,
        "http_timeout_seconds": float(timeout_seconds),
        "max_output_tokens": output_tokens,
        "candidate_enabled_env": "AGENT_P2_V3_CANDIDATE_ENABLED=true",
        "manifest_path_env": f"AGENT_P2_V3_EXECUTION_MANIFEST_PATH={manifest_path}",
        "manifest_sha_env": f"AGENT_P2_V3_EXECUTION_MANIFEST_SHA256={manifest_sha}",
        "repository_root_env": f"AGENT_P2_V3_EXECUTION_REPOSITORY_ROOT={repository_root}",
        "external_roots_env": "AGENT_P2_V3_EXECUTION_EXTERNAL_COMPONENT_ROOTS=" + json.dumps(
            {key: str(value) for key, value in external_roots.items()}, separators=(",", ":"),
        ),
        "model_artifact_read": False,
        "service_or_model_started": False,
    }


def main(argv: list[str] | None = None) -> int:
    try:
        result = generate(_build_parser().parse_args(argv))
    except (OSError, ValueError, P2V3ExecutionManifestError) as exc:
        print(f"manifest generation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
