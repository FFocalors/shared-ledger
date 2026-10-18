from __future__ import annotations

from pathlib import Path
import sys

import pytest
from pydantic import ValidationError

from app import components as components_module
from app.components import build_components
from app.settings import Settings


def test_settings_and_default_assembly_pass_the_selected_output_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path("D:/AI/runs/shared-ledger/p2/settings-output-budget-config-cpu")

    class NoIoStore:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.args = args
            self.kwargs = kwargs

    monkeypatch.setattr(components_module, "SQLiteAgentStore", NoIoStore)
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
