"""Strict server-side verifier for a disabled P2 v3 execution cohort.

The external manifest is data only. Component files are hashed, never imported
or executed. Synthetic cohorts are accepted only by explicitly test-configured
Stores and can never be used as an application execution pin.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Mapping, Optional

from .p2_local_endpoint import normalize_local_http_origin
from .p2_read_contracts_v3 import P2_V3_CANDIDATE_PROFILE_ID, P2_V3_VERSIONS


class P2V3ExecutionManifestError(ValueError):
    """The server supplied execution manifest or a component is invalid."""


@dataclass(frozen=True)
class P2V3ManifestComponent:
    path: str
    role: str
    byte_count: int
    sha256: str


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SEAL = object()

MAX_MANIFEST_BYTES = 262_144
MAX_COMPONENTS = 64
MAX_COMPONENT_BYTES = 8 * 1024 * 1024
MAX_TOTAL_COMPONENT_BYTES = 64 * 1024 * 1024

_ROLE_SET = frozenset({
    "schema_bundle", "agent_store", "p2_v3_store", "migration_001", "migration_002",
    "migration_003", "migration_004", "migration_005", "migration_006",
    "read_contracts", "event_contracts",
    "source_codec", "source_backend", "runtime", "api", "provider_adapter",
    "provider_configuration", "prompt_source", "model_configuration", "dependency_lock",
    "app_settings", "app_composition", "app_entrypoint", "shared_provider",
    "v3_provider_facade", "native_v3_provider", "token_budget_checker", "local_endpoint_policy",
    "format_repair_policy", "runtime_policy", "sent_decision_guard",
    "store_budget_port", "p2_identity", "p2_harness", "p2_journal",
    "execution_cohort_verifier", "counter_sdk_metadata", "synthetic_fixture",
    "legacy_auth", "legacy_contracts", "legacy_ports", "legacy_runtime",
    "legacy_backend", "legacy_gateway", "legacy_model_provider", "legacy_harness",
    "p2_backend_transport", "p2_prompt_policy", "p2_schema_wire",
    "legacy_p2_event_contracts", "legacy_p2_read_contracts", "p2_read_store",
})
_REQUIRED_PRODUCTION_ROLES = frozenset({
    "schema_bundle", "agent_store", "p2_v3_store", "migration_001", "migration_002",
    "migration_003", "migration_004", "migration_005", "migration_006",
    "read_contracts", "event_contracts",
    "source_codec", "source_backend", "runtime", "api", "provider_adapter",
    "provider_configuration", "prompt_source", "model_configuration", "dependency_lock",
    "app_settings", "app_entrypoint", "shared_provider", "native_v3_provider",
    "token_budget_checker", "local_endpoint_policy",
    "format_repair_policy", "runtime_policy", "sent_decision_guard",
    "store_budget_port", "p2_identity", "p2_harness", "p2_journal",
    "execution_cohort_verifier", "counter_sdk_metadata",
    "legacy_auth", "legacy_contracts", "legacy_ports", "legacy_runtime",
    "legacy_backend", "legacy_gateway", "legacy_model_provider", "legacy_harness",
    "p2_backend_transport", "p2_prompt_policy", "p2_schema_wire",
    "legacy_p2_event_contracts", "legacy_p2_read_contracts", "p2_read_store",
})
_BUDGETS = {
    "model_calls": 6,
    "repair_calls": 1,
    "logical_reads": 4,
    "active_us": 240_000_000,
    "backend_us": 20_000_000,
    "get_calls": 48,
    "response_bytes": 4_194_304,
    "response_bytes_per_get": 1_048_576,
    "get_rows_per_page": 16,
    "pages_per_table": 4,
    "rows_per_table": 64,
    "source_pages_per_capture_chain": 32,
}
_MANIFEST_KEYS = frozenset({
    "format", "manifest_kind", "profile_id", "versions", "schema_bundle_sha256",
    "source_manifest_sha256", "contract_source_sha256", "components", "safe_config",
})


@dataclass(frozen=True)
class P2V3VerifiedExecutionCohort:
    """Opaque proof object issued only after manifest and component verification."""

    manifest_sha256: str
    profile_id: str
    versions: tuple[str, str, str, str]
    schema_bundle_sha256: str
    source_manifest_sha256: str
    contract_source_sha256: str
    safe_config_sha256: str
    provider_wire: Literal["compatibility", "native_candidate"]
    model_key: str | None
    endpoint_origin: str | None
    http_timeout_seconds: float | None
    max_output_tokens: int | None
    manifest_kind: str
    manifest_path: Path = field(repr=False)
    repository_root: Path = field(repr=False)
    external_component_roots: tuple[tuple[str, Path], ...] = field(repr=False)
    components: tuple[P2V3ManifestComponent, ...]
    _seal: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._seal is not _SEAL:
            raise P2V3ExecutionManifestError("execution cohort must come from the server verifier")

    @property
    def is_synthetic(self) -> bool:
        return self.manifest_kind == "synthetic_test"

    def verify_unchanged(self) -> "P2V3VerifiedExecutionCohort":
        """Rehash the external manifest and every listed component at Store startup."""
        freshly_verified = verify_execution_manifest_file(
            self.manifest_path,
            expected_manifest_sha256=self.manifest_sha256,
            repository_root=self.repository_root,
            external_component_roots=dict(self.external_component_roots),
        )
        # A frozen dataclass is not an authenticity boundary: callers can use
        # dataclasses.replace() and retain the private seal. Compare the entire
        # freshly issued projection before allowing this object to stand for it.
        if not is_verified_execution_cohort(self) or _cohort_fingerprint(self) != _cohort_fingerprint(freshly_verified):
            raise P2V3ExecutionManifestError("execution cohort object differs from its freshly verified source")
        return freshly_verified


_ISSUED: dict[int, tuple[object, str]] = {}


def _cohort_fingerprint(value: P2V3VerifiedExecutionCohort) -> str:
    payload = {
        "manifest": value.manifest_sha256, "profile": value.profile_id,
        "versions": list(value.versions), "schema": value.schema_bundle_sha256,
        "source": value.source_manifest_sha256, "contract": value.contract_source_sha256,
        "config": value.safe_config_sha256, "kind": value.manifest_kind,
        "provider_wire": value.provider_wire,
        "model_key": value.model_key,
        "endpoint_origin": value.endpoint_origin,
        "http_timeout_seconds": value.http_timeout_seconds,
        "max_output_tokens": value.max_output_tokens,
        "manifest_path": str(value.manifest_path), "root": str(value.repository_root),
        "external_roots": [[role, str(path)] for role, path in value.external_component_roots],
        "components": [
            [item.path, item.role, item.byte_count, item.sha256] for item in value.components
        ],
    }
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def is_verified_execution_cohort(value: Any) -> bool:
    if not isinstance(value, P2V3VerifiedExecutionCohort) or value._seal is not _SEAL:
        return False
    issued = _ISSUED.get(id(value))
    return issued is not None and issued[0] is value._seal and issued[1] == _cohort_fingerprint(value)


def _sha256(value: str, name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise P2V3ExecutionManifestError(f"{name} must be lowercase SHA-256 hex")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise P2V3ExecutionManifestError("execution manifest contains duplicate JSON keys")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise P2V3ExecutionManifestError("execution manifest contains a non-standard JSON value")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def _component_digest(components: list[P2V3ManifestComponent]) -> str:
    value = [
        {"path": item.path, "role": item.role, "bytes": item.byte_count, "sha256": item.sha256}
        for item in sorted(components, key=lambda entry: (entry.path, entry.role))
    ]
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _bounded_read(path: Path, max_bytes: int, error: str) -> bytes:
    try:
        with path.open("rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
                raise P2V3ExecutionManifestError(error)
            raw = stream.read(max_bytes + 1)
    except P2V3ExecutionManifestError:
        raise
    except OSError:
        raise P2V3ExecutionManifestError(error) from None
    if len(raw) > max_bytes:
        raise P2V3ExecutionManifestError(error)
    return raw


def _safe_component_path(
    raw_path: Any,
    root: Path,
    *,
    role: str,
    external_component_roots: Mapping[str, Path],
) -> tuple[str, Path]:
    if type(raw_path) is not str or not raw_path or "\\" in raw_path or "\x00" in raw_path:
        raise P2V3ExecutionManifestError("component path must be normalized relative POSIX text")
    relative = PurePosixPath(raw_path)
    if relative.is_absolute() or relative.as_posix() != raw_path or any(part in ("", ".", "..") for part in relative.parts):
        raise P2V3ExecutionManifestError("component path escapes or is not normalized under the repository root")
    component_root = external_component_roots.get(role, root).resolve(strict=True)
    candidate = component_root.joinpath(*relative.parts)
    cursor = component_root
    for part in relative.parts:
        cursor = cursor / part
        try:
            if cursor.is_symlink():
                raise P2V3ExecutionManifestError("execution component path cannot traverse a symlink")
        except OSError:
            raise P2V3ExecutionManifestError("execution component path cannot be inspected") from None
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(component_root)
        info = resolved.stat()
    except (OSError, ValueError):
        raise P2V3ExecutionManifestError("execution component is missing or outside the repository root") from None
    if not stat.S_ISREG(info.st_mode):
        raise P2V3ExecutionManifestError("execution component must be a regular non-symlink file")
    return raw_path, resolved


def _parse_manifest(
    raw: bytes,
    root: Path,
    manifest_path: Path,
    external_component_roots: Mapping[str, Path],
    expected_manifest_sha256: str,
) -> P2V3VerifiedExecutionCohort:
    expected = _sha256(expected_manifest_sha256, "trusted expected manifest digest")
    actual_manifest_sha = hashlib.sha256(raw).hexdigest()
    if actual_manifest_sha != expected:
        raise P2V3ExecutionManifestError("execution manifest does not match the server trust anchor")
    if len(raw) > MAX_MANIFEST_BYTES:
        raise P2V3ExecutionManifestError("execution manifest exceeds its byte limit")
    try:
        text = raw.decode("utf-8", errors="strict")
        document = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except P2V3ExecutionManifestError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        raise P2V3ExecutionManifestError("execution manifest is not strict UTF-8 JSON") from None
    if type(document) is not dict or frozenset(document) != _MANIFEST_KEYS:
        raise P2V3ExecutionManifestError("execution manifest has missing or unknown top-level fields")
    if document["format"] != "p2-v3-execution-manifest" or document["manifest_kind"] not in {"production", "synthetic_test"}:
        raise P2V3ExecutionManifestError("execution manifest format or kind is not supported")
    if document["profile_id"] != P2_V3_CANDIDATE_PROFILE_ID:
        raise P2V3ExecutionManifestError("execution manifest profile does not match the reviewed v3 candidate")
    versions = document["versions"]
    expected_versions = P2_V3_VERSIONS.model_dump(mode="json")
    if type(versions) is not dict or versions != expected_versions:
        raise P2V3ExecutionManifestError("execution manifest versions do not match the reviewed v3 tuple")
    safe_config = document["safe_config"]
    base_safe_keys = {"debt_source_variant", "budgets"}
    bound_wire_keys = {
        "provider_wire", "model_key", "endpoint_origin", "http_timeout_seconds", "max_output_tokens",
    }
    if (
        type(safe_config) is not dict
        or not base_safe_keys.issubset(safe_config)
        or frozenset(safe_config) - base_safe_keys not in (frozenset(), frozenset(bound_wire_keys))
        or (document["manifest_kind"] == "production" and not bound_wire_keys.issubset(safe_config))
    ):
        raise P2V3ExecutionManifestError("execution manifest has unsupported or potentially secret config keys")
    if safe_config["debt_source_variant"] != "expense_debt_line" or type(safe_config["budgets"]) is not dict:
        raise P2V3ExecutionManifestError("execution manifest debt source or budget config is invalid")
    if frozenset(safe_config["budgets"]) != frozenset(_BUDGETS):
        raise P2V3ExecutionManifestError("execution manifest budget config has missing or unknown keys")
    for key, expected_value in _BUDGETS.items():
        value = safe_config["budgets"][key]
        if type(value) is not int or value != expected_value:
            raise P2V3ExecutionManifestError("execution manifest budget differs from the reviewed private limits")
    provider_wire: Literal["compatibility", "native_candidate"] = "compatibility"
    bound_model_key: str | None = None
    bound_endpoint_origin: str | None = None
    bound_http_timeout: float | None = None
    bound_max_output: int | None = None
    if bound_wire_keys.issubset(safe_config):
        raw_wire = safe_config["provider_wire"]
        if type(raw_wire) is not str or raw_wire not in {"compatibility", "native_candidate"}:
            raise P2V3ExecutionManifestError("execution manifest provider wire is unsupported")
        provider_wire = raw_wire
        raw_model_key = safe_config["model_key"]
        if (
            type(raw_model_key) is not str or not raw_model_key or len(raw_model_key) > 128
            or any(ord(char) < 32 or ord(char) == 127 for char in raw_model_key)
        ):
            raise P2V3ExecutionManifestError("execution manifest model key is invalid")
        bound_model_key = raw_model_key
        try:
            bound_endpoint_origin = normalize_local_http_origin(safe_config["endpoint_origin"])
        except (TypeError, ValueError, UnicodeError):
            raise P2V3ExecutionManifestError("execution manifest endpoint origin is not local") from None
        if bound_endpoint_origin != safe_config["endpoint_origin"]:
            raise P2V3ExecutionManifestError("execution manifest endpoint origin is not canonical")
        timeout = safe_config["http_timeout_seconds"]
        if (
            type(timeout) not in (int, float) or isinstance(timeout, bool)
            or not 0.1 <= float(timeout) <= 90.0
            or (provider_wire == "compatibility" and float(timeout) > 30.0)
        ):
            raise P2V3ExecutionManifestError("execution manifest HTTP timeout is outside the selected wire policy")
        bound_http_timeout = float(timeout)
        output_tokens = safe_config["max_output_tokens"]
        if type(output_tokens) is not int or not 1 <= output_tokens <= 1536:
            raise P2V3ExecutionManifestError("execution manifest output-token limit is invalid")
        bound_max_output = output_tokens

    raw_components = document["components"]
    if type(raw_components) is not list or not 1 <= len(raw_components) <= MAX_COMPONENTS:
        raise P2V3ExecutionManifestError("execution manifest component list is outside its bounds")
    components: list[P2V3ManifestComponent] = []
    seen_paths: set[str] = set()
    total_bytes = 0
    roles: set[str] = set()
    role_counts: dict[str, int] = {}
    for item in raw_components:
        if type(item) is not dict or frozenset(item) != {"path", "role", "bytes", "sha256"}:
            raise P2V3ExecutionManifestError("execution component has missing or unknown fields")
        role = item["role"]
        if type(role) is not str or role not in _ROLE_SET:
            raise P2V3ExecutionManifestError("execution component role is not allowlisted")
        relative, path = _safe_component_path(
            item["path"], root, role=role, external_component_roots=external_component_roots,
        )
        byte_count = item["bytes"]
        digest = _sha256(item["sha256"], "component digest")
        if type(byte_count) is not int or not 0 <= byte_count <= MAX_COMPONENT_BYTES:
            raise P2V3ExecutionManifestError("execution component byte count is invalid")
        canonical_path = str(path).casefold()
        if canonical_path in seen_paths:
            raise P2V3ExecutionManifestError("execution manifest contains duplicate component paths")
        seen_paths.add(canonical_path)
        roles.add(role)
        role_counts[role] = role_counts.get(role, 0) + 1
        total_bytes += byte_count
        if total_bytes > MAX_TOTAL_COMPONENT_BYTES:
            raise P2V3ExecutionManifestError("execution manifest total component bytes exceed their limit")
        actual_bytes = _bounded_read(path, MAX_COMPONENT_BYTES, "execution component exceeds its byte limit")
        if len(actual_bytes) != byte_count or hashlib.sha256(actual_bytes).hexdigest() != digest:
            raise P2V3ExecutionManifestError("execution component changed or does not match its manifest")
        components.append(P2V3ManifestComponent(relative, role, byte_count, digest))
    if document["manifest_kind"] == "production":
        if not _REQUIRED_PRODUCTION_ROLES.issubset(roles) or "synthetic_fixture" in roles:
            raise P2V3ExecutionManifestError("production manifest omits a required execution component role")
        if any(count != 1 for count in role_counts.values()):
            raise P2V3ExecutionManifestError("production execution component roles must each occur exactly once")
    elif roles != {"synthetic_fixture"} or len(components) != 1:
        raise P2V3ExecutionManifestError("synthetic test manifests contain exactly one synthetic fixture only")

    schema_components = [item for item in components if item.role == "schema_bundle"]
    source_sha = _component_digest(components)
    read_contracts = [item for item in components if item.role == "read_contracts"]
    if document["manifest_kind"] == "production" and (
        len(schema_components) != 1
        or len(read_contracts) != 1
        or sum(item.role == "event_contracts" for item in components) != 1
    ):
        raise P2V3ExecutionManifestError("production manifest must bind one schema bundle and both contract sources")
    schema_sha = schema_components[0].sha256 if len(schema_components) == 1 else hashlib.sha256(b"synthetic-test-schema-bundle").hexdigest()
    contract_sha = read_contracts[0].sha256 if len(read_contracts) == 1 else hashlib.sha256(b"synthetic-test-contract-snapshot").hexdigest()
    if (
        document["schema_bundle_sha256"] != schema_sha
        or document["source_manifest_sha256"] != source_sha
        or document["contract_source_sha256"] != contract_sha
    ):
        raise P2V3ExecutionManifestError("execution cohort component digests do not match its canonical manifest projection")
    config_sha = hashlib.sha256(_canonical_bytes(safe_config)).hexdigest()
    cohort = P2V3VerifiedExecutionCohort(
        manifest_sha256=actual_manifest_sha,
        profile_id=document["profile_id"],
        versions=(versions["api"], versions["semantic"], versions["operations"], versions["trajectory"]),
        schema_bundle_sha256=schema_sha,
        source_manifest_sha256=source_sha,
        contract_source_sha256=contract_sha,
        safe_config_sha256=config_sha,
        provider_wire=provider_wire,
        model_key=bound_model_key,
        endpoint_origin=bound_endpoint_origin,
        http_timeout_seconds=bound_http_timeout,
        max_output_tokens=bound_max_output,
        manifest_kind=document["manifest_kind"],
        manifest_path=manifest_path,
        repository_root=root,
        external_component_roots=tuple(sorted((role, Path(path).resolve(strict=True)) for role, path in external_component_roots.items())),
        components=tuple(components),
        _seal=_SEAL,
    )
    _ISSUED[id(cohort)] = (_SEAL, _cohort_fingerprint(cohort))
    return cohort


def verify_execution_manifest_file(
    manifest_path: Path,
    *,
    expected_manifest_sha256: str,
    repository_root: Path,
    external_component_roots: Optional[Mapping[str, Path]] = None,
) -> P2V3VerifiedExecutionCohort:
    """Verify a deployment manifest against a separately supplied trust anchor."""
    raw_manifest_path = Path(manifest_path)
    try:
        if raw_manifest_path.is_symlink():
            raise P2V3ExecutionManifestError("execution manifest must not be a symlink")
        manifest_stat = raw_manifest_path.stat()
        if not stat.S_ISREG(manifest_stat.st_mode) or manifest_stat.st_size > MAX_MANIFEST_BYTES:
            raise P2V3ExecutionManifestError("execution manifest exceeds its byte limit or is not regular")
        path = raw_manifest_path.resolve(strict=True)
    except P2V3ExecutionManifestError:
        raise
    except OSError:
        raise P2V3ExecutionManifestError("execution manifest is missing or cannot be inspected") from None
    root = Path(repository_root).resolve(strict=True)
    external_roots = {
        role: Path(value).resolve(strict=True)
        for role, value in (external_component_roots or {}).items()
    }
    if set(external_roots) - _ROLE_SET:
        raise P2V3ExecutionManifestError("external component roots contain an unsupported role")
    raw = _bounded_read(path, MAX_MANIFEST_BYTES, "execution manifest exceeds its byte limit")
    return _parse_manifest(raw, root, path, external_roots, expected_manifest_sha256)

