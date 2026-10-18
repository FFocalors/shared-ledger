from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest
from pydantic import ValidationError

from app import components as components_module
from app import p2_v3_execution_cohort as cohort_module
from app.components import build_components
from app.p2_local_endpoint import parse_local_p2_endpoint
from app.p2_read_contracts_v3 import P2_V3_CANDIDATE_PROFILE_ID, P2_V3_VERSIONS
from app.settings import Settings


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def _verified_execution_pin(
    tmp_path: Path, settings: Settings,
) -> cohort_module.P2V3VerifiedExecutionCohort:
    """Issue a real production-shaped pin whose wire binding selects these settings.

    The v3 provider gate refuses to assemble without a cohort that the server
    verifier issued and whose wire, model, origin, timeout and output binding
    equal the selected configuration, so this fixture only replaces the pinned
    component *bytes*; the manifest itself is still hashed against its trust
    anchor and verified through the production verifier.
    """
    component_root = tmp_path / "production-components"
    component_root.mkdir()
    components: list[dict[str, object]] = []
    for index, role in enumerate(sorted(cohort_module._REQUIRED_PRODUCTION_ROLES)):
        path = f"component-{index:02d}.bin"
        content = f"synthetic production-role fixture:{role}:{index}".encode("utf-8")
        (component_root / path).write_bytes(content)
        components.append({
            "path": path,
            "role": role,
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        })
    projection = sorted(components, key=lambda item: (str(item["path"]), str(item["role"])))
    document = {
        "format": "p2-v3-execution-manifest",
        "manifest_kind": "production",
        "profile_id": P2_V3_CANDIDATE_PROFILE_ID,
        "versions": P2_V3_VERSIONS.model_dump(mode="json"),
        "schema_bundle_sha256": next(
            str(item["sha256"]) for item in components if item["role"] == "schema_bundle"
        ),
        "source_manifest_sha256": hashlib.sha256(_canonical(projection)).hexdigest(),
        "contract_source_sha256": next(
            str(item["sha256"]) for item in components if item["role"] == "read_contracts"
        ),
        "components": components,
        "safe_config": {
            "debt_source_variant": "expense_debt_line",
            "budgets": dict(cohort_module._BUDGETS),
            "provider_wire": (
                "native_candidate" if settings.p2_v3_native_candidate_enabled else "compatibility"
            ),
            "model_key": settings.p2_lmstudio_model_key,
            "endpoint_origin": parse_local_p2_endpoint(settings.p2_lmstudio_endpoint_url).origin,
            "http_timeout_seconds": settings.p2_model_timeout_seconds,
            "max_output_tokens": settings.p2_max_output_tokens,
        },
    }
    raw = _canonical(document)
    manifest = tmp_path / "production-execution-manifest.json"
    manifest.write_bytes(raw)
    return cohort_module.verify_execution_manifest_file(
        manifest,
        expected_manifest_sha256=hashlib.sha256(raw).hexdigest(),
        repository_root=Path(__file__).parents[1],
        external_component_roots={
            role: component_root for role in cohort_module._REQUIRED_PRODUCTION_ROLES
        },
    )


def test_settings_and_default_assembly_pass_the_selected_output_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path("D:/AI/runs/shared-ledger/p2/settings-output-budget-config-cpu")

    settings = Settings(
        _env_file=None,
        storage_path=root / "runtime.sqlite3",
        p2_journal_path=root / "journal.sqlite3",
        provider_mode="p2",
        supabase_auth_base_url="https://unit-test.supabase.co",
        supabase_api_key="sb_publishable_unit_test_key",
        p2_lmstudio_enabled=True,
        p2_lmstudio_model_key="t0-cp36-20261007",
        p2_token_budget_enabled=True,
        p2_model_artifact_path=root / "synthetic-model.gguf",
        p2_lmstudio_model_path="shared-ledger/t0-cp36-20261007/qwen3.5-4b-q4_k_m.gguf",
        p2_model_artifact_sha256="a" * 64,
        p2_model_artifact_size_bytes=1024,
        p2_model_context_tokens=8192,
        p2_max_input_tokens=6144,
        p2_schema_safety_margin_tokens=512,
        p2_token_counter_python=Path(sys.executable),
        p2_max_output_tokens=1536,
        p2_v3_candidate_enabled=True,
        p2_v3_execution_manifest_path=root / "synthetic-execution-manifest.json",
        p2_v3_execution_manifest_sha256="b" * 64,
        p2_v3_execution_repository_root=root,
        agent_enabled=True,
        disable_revision=0,
    )

    pin = _verified_execution_pin(tmp_path, settings)
    assert pin.max_output_tokens == 1536
    assert pin.model_key == "t0-cp36-20261007"

    class NoIoStore:
        """Stand in for the Store: no IO, but a genuinely verified cohort pin."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            self.args = args
            self.kwargs = kwargs
            self._p2_v3_execution_cohort = pin

    monkeypatch.setattr(components_module, "SQLiteAgentStore", NoIoStore)

    components = build_components(settings)
    assert components.provider._config.max_output_tokens == 1536
    assert components.provider._token_budget_checker.policy.max_output_tokens == 1536
    assert components.runtime._p2_v3_prompt_config.max_output_tokens == 1536
    assert components.runtime._p2_v3_provider._bound_config.max_output_tokens == 1536
    assert not (root / "runtime.sqlite3").exists()
    assert not (root / "journal.sqlite3").exists()


def test_settings_rejects_output_budgets_above_supported_ceiling() -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            storage_path="D:/AI/runs/shared-ledger/p2/settings-output-budget-config-cpu/invalid.sqlite3",
            p2_max_output_tokens=1537,
        )
