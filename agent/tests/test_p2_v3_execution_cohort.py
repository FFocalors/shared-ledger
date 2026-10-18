from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.app import p2_v3_execution_cohort as cohort_module
from agent.app.components import _verify_v3_provider_wire_pin
from agent.app.p2_read_contracts_v3 import P2_V3_CANDIDATE_PROFILE_ID, P2_V3_VERSIONS


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def _synthetic_manifest(tmp_path: Path, repository_root: Path) -> tuple[Path, str, dict[str, Path]]:
    component_root = tmp_path / "components"
    component_root.mkdir()
    component = component_root / "fixture.json"
    component_bytes = b'{"fixture":"CPU only"}'
    component.write_bytes(component_bytes)
    components = [{
        "path": "fixture.json",
        "role": "synthetic_fixture",
        "bytes": len(component_bytes),
        "sha256": hashlib.sha256(component_bytes).hexdigest(),
    }]
    source_sha = hashlib.sha256(_canonical(components)).hexdigest()
    budgets = dict(cohort_module._BUDGETS)
    document = {
        "format": "p2-v3-execution-manifest",
        "manifest_kind": "synthetic_test",
        "profile_id": P2_V3_CANDIDATE_PROFILE_ID,
        "versions": P2_V3_VERSIONS.model_dump(mode="json"),
        "schema_bundle_sha256": hashlib.sha256(b"synthetic-test-schema-bundle").hexdigest(),
        "source_manifest_sha256": source_sha,
        "contract_source_sha256": hashlib.sha256(b"synthetic-test-contract-snapshot").hexdigest(),
        "components": components,
        "safe_config": {"debt_source_variant": "expense_debt_line", "budgets": budgets},
    }
    raw = _canonical(document)
    manifest = tmp_path / "external-manifest.json"
    manifest.write_bytes(raw)
    return manifest, hashlib.sha256(raw).hexdigest(), {"synthetic_fixture": component_root}


def _production_manifest(
    tmp_path: Path,
    repository_root: Path,
    *,
    duplicate_read_contracts: bool = False,
    provider_wire: str = "compatibility",
    http_timeout_seconds: float = 30.0,
    max_output_tokens: int = 768,
) -> tuple[Path, str, dict[str, Path]]:
    component_root = tmp_path / "production-components"
    component_root.mkdir()
    roles = sorted(cohort_module._REQUIRED_PRODUCTION_ROLES)
    if duplicate_read_contracts:
        roles.append("read_contracts")
    components: list[dict[str, object]] = []
    role_roots: dict[str, Path] = {}
    for index, role in enumerate(roles):
        path = f"component-{index:02d}.bin"
        content = f"synthetic production-role fixture:{role}:{index}".encode("utf-8")
        (component_root / path).write_bytes(content)
        components.append({
            "path": path,
            "role": role,
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        })
        role_roots[role] = component_root
    component_projection = sorted(components, key=lambda item: (str(item["path"]), str(item["role"])))
    source_sha = hashlib.sha256(_canonical(component_projection)).hexdigest()
    schema_sha = next(str(item["sha256"]) for item in components if item["role"] == "schema_bundle")
    contract_sha = next(str(item["sha256"]) for item in components if item["role"] == "read_contracts")
    document = {
        "format": "p2-v3-execution-manifest",
        "manifest_kind": "production",
        "profile_id": P2_V3_CANDIDATE_PROFILE_ID,
        "versions": P2_V3_VERSIONS.model_dump(mode="json"),
        "schema_bundle_sha256": schema_sha,
        "source_manifest_sha256": source_sha,
        "contract_source_sha256": contract_sha,
        "components": components,
        "safe_config": {
            "debt_source_variant": "expense_debt_line",
            "budgets": dict(cohort_module._BUDGETS),
            "provider_wire": provider_wire,
            "model_key": "fixture-model",
            "endpoint_origin": "http://127.0.0.1:1234",
            "http_timeout_seconds": http_timeout_seconds,
            "max_output_tokens": max_output_tokens,
        },
    }
    raw = _canonical(document)
    manifest = tmp_path / "production-external-manifest.json"
    manifest.write_bytes(raw)
    return manifest, hashlib.sha256(raw).hexdigest(), role_roots


def test_verified_cohort_revalidation_returns_fresh_object_and_rejects_replaced_fields(tmp_path: Path) -> None:
    manifest, expected_sha, roots = _synthetic_manifest(tmp_path, Path(__file__).parents[1])
    verified = cohort_module.verify_execution_manifest_file(
        manifest,
        expected_manifest_sha256=expected_sha,
        repository_root=Path(__file__).parents[1],
        external_component_roots=roots,
    )

    current = verified.verify_unchanged()
    assert current is not verified
    assert cohort_module.is_verified_execution_cohort(current)
    assert cohort_module._cohort_fingerprint(current) == cohort_module._cohort_fingerprint(verified)

    counterfeit = replace(verified, schema_bundle_sha256="0" * 64)
    assert not cohort_module.is_verified_execution_cohort(counterfeit)
    with pytest.raises(cohort_module.P2V3ExecutionManifestError):
        counterfeit.verify_unchanged()


def test_minimal_production_manifest_with_singleton_roles_verifies(tmp_path: Path) -> None:
    repository_root = Path(__file__).parents[1]
    manifest, expected_sha, roots = _production_manifest(tmp_path, repository_root)
    verified = cohort_module.verify_execution_manifest_file(
        manifest,
        expected_manifest_sha256=expected_sha,
        repository_root=repository_root,
        external_component_roots=roots,
    )
    assert verified.manifest_kind == "production"
    assert not verified.is_synthetic
    assert {item.role for item in verified.components} == cohort_module._REQUIRED_PRODUCTION_ROLES
    assert sum(item.role == "read_contracts" for item in verified.components) == 1


def test_native_provider_selection_and_budget_must_match_verified_manifest(tmp_path: Path) -> None:
    repository_root = Path(__file__).parents[1]
    manifest, expected_sha, roots = _production_manifest(
        tmp_path,
        repository_root,
        provider_wire="native_candidate",
        http_timeout_seconds=90.0,
        max_output_tokens=1536,
    )
    verified = cohort_module.verify_execution_manifest_file(
        manifest,
        expected_manifest_sha256=expected_sha,
        repository_root=repository_root,
        external_component_roots=roots,
    )
    store = SimpleNamespace(_p2_v3_execution_cohort=verified)
    settings = SimpleNamespace(
        p2_v3_native_candidate_enabled=True,
        p2_lmstudio_model_key="fixture-model",
        p2_lmstudio_endpoint_url="http://127.0.0.1:1234/v1/chat/completions",
        p2_model_timeout_seconds=90.0,
        p2_max_output_tokens=1536,
    )

    _verify_v3_provider_wire_pin(settings, store)
    assert verified.provider_wire == "native_candidate"
    assert verified.endpoint_origin == "http://127.0.0.1:1234"
    assert verified.http_timeout_seconds == 90.0
    assert verified.max_output_tokens == 1536

    mismatched = SimpleNamespace(**{**vars(settings), "p2_model_timeout_seconds": 30.0})
    with pytest.raises(ValueError, match="differs from the execution manifest pin"):
        _verify_v3_provider_wire_pin(mismatched, store)


def test_production_manifest_rejects_duplicate_read_contract_role_even_with_recomputed_trust_hash(tmp_path: Path) -> None:
    repository_root = Path(__file__).parents[1]
    manifest, trusted_sha, roots = _production_manifest(
        tmp_path, repository_root, duplicate_read_contracts=True,
    )
    # `trusted_sha` is computed from the exact duplicate-role manifest bytes,
    # so this exercises role cardinality rather than a stale-manifest check.
    with pytest.raises(cohort_module.P2V3ExecutionManifestError, match="exactly once"):
        cohort_module.verify_execution_manifest_file(
            manifest,
            expected_manifest_sha256=trusted_sha,
            repository_root=repository_root,
            external_component_roots=roots,
        )


def test_oversized_component_is_rejected_after_stat_without_reading_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "oversized.bin"
    with path.open("wb") as stream:
        stream.truncate(cohort_module.MAX_COMPONENT_BYTES + 1)

    original_open = Path.open
    body_reads: list[int] = []

    class ReadGuard:
        def __init__(self, inner: object) -> None:
            self._inner = inner

        def __enter__(self) -> "ReadGuard":
            return self

        def __exit__(self, *args: object) -> object:
            return self._inner.__exit__(*args)

        def fileno(self) -> int:
            return self._inner.fileno()

        def read(self, size: int = -1) -> bytes:
            body_reads.append(size)
            return self._inner.read(size)

    def tracked_open(target: Path, *args: object, **kwargs: object) -> object:
        inner = original_open(target, *args, **kwargs)
        if target == path:
            return ReadGuard(inner)
        return inner

    monkeypatch.setattr(Path, "open", tracked_open)
    with pytest.raises(cohort_module.P2V3ExecutionManifestError):
        cohort_module._bounded_read(path, cohort_module.MAX_COMPONENT_BYTES, "too large")
    assert body_reads == []
