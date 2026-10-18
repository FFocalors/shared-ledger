from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any

import pytest

from app.p2_token_budget import (
    LMStudioSDKTokenBudgetChecker,
    P2ChatMessage,
    P2ModelArtifactBinding,
    P2ResponseFormat,
    P2TokenBudgetError,
    P2TokenBudgetFailure,
    P2TokenBudgetPolicy,
    P2TokenBudgetRequest,
)


MODEL_KEY = "preparation-fixture-model"
MODEL_PATH = "fixture/preparation-model.gguf"
API_HOST = "http://127.0.0.1:1234"


def _checker(
    artifact: Path,
    *,
    digest: str | None = None,
    size: int | None = None,
) -> LMStudioSDKTokenBudgetChecker:
    contents = artifact.read_bytes()
    binding = P2ModelArtifactBinding(
        model_key=MODEL_KEY,
        artifact_path=artifact,
        lmstudio_model_path=MODEL_PATH,
        lmstudio_api_host=API_HOST,
        artifact_sha256=digest or hashlib.sha256(contents).hexdigest(),
        artifact_size_bytes=len(contents) if size is None else size,
        expected_context_tokens=8192,
    )
    return LMStudioSDKTokenBudgetChecker(
        binding,
        P2TokenBudgetPolicy(),
        python_executable=Path(sys.executable).resolve(),
    )


def _request() -> P2TokenBudgetRequest:
    return P2TokenBudgetRequest(
        model_key=MODEL_KEY,
        api_host=API_HOST,
        messages=(P2ChatMessage("system", "system fixture"), P2ChatMessage("user", "user fixture")),
        response_format=P2ResponseFormat(
            '{"type":"json_schema","json_schema":{"name":"fixture","strict":true,"schema":{"type":"object"}}}'
        ),
        max_output_tokens=768,
    )


def _advancing_clock(step_seconds: float = 2.0):
    current = 0.0

    def now() -> float:
        nonlocal current
        value = current
        current += step_seconds
        return value

    return now


def test_explicit_preparation_has_separate_bound_and_default_still_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "small-fixture.gguf"
    artifact.write_bytes(b"small fixture only")
    checker = _checker(artifact)
    digest = checker.binding.artifact_sha256
    helper_calls: list[object] = []

    with monkeypatch.context() as patch:
        patch.setattr("app.p2_token_budget.monotonic", _advancing_clock())
        with pytest.raises(P2TokenBudgetError) as verify_error:
            checker.verify_artifact_binding()
        assert verify_error.value.reason == P2TokenBudgetFailure.COUNTER_TIMEOUT
        assert checker._cached_stat is None

        patch.setattr("app.p2_token_budget.monotonic", _advancing_clock())
        patch.setattr(
            "app.p2_token_budget._run_bounded_helper",
            lambda *_args, **_kwargs: helper_calls.append("unexpected"),
        )
        with pytest.raises(P2TokenBudgetError) as measure_error:
            checker.measure(_request())
        assert measure_error.value.reason == P2TokenBudgetFailure.COUNTER_TIMEOUT
        assert helper_calls == []
        assert checker._cached_stat is None

        patch.setattr("app.p2_token_budget.monotonic", _advancing_clock())
        prepared_digest, elapsed_ms = checker.prepare_artifact_binding(timeout_seconds=30.0)

    assert prepared_digest == digest
    # The injected monotonic clock makes this small-file test exercise the
    # separate >5s readiness allowance without a huge fixture or real sleep.
    assert elapsed_ms > 5000
    assert checker._cached_stat is not None
    assert checker._cached_sha256 == digest
    assert helper_calls == []


@pytest.mark.parametrize("timeout_seconds", [0, 0.099, 30.001, math.inf, math.nan, True, "30"])
def test_explicit_preparation_rejects_invalid_deadline(
    tmp_path: Path,
    timeout_seconds: object,
) -> None:
    artifact = tmp_path / "small-fixture.gguf"
    artifact.write_bytes(b"fixture")
    checker = _checker(artifact)

    with pytest.raises(ValueError):
        checker.prepare_artifact_binding(timeout_seconds=timeout_seconds)  # type: ignore[arg-type]
    assert checker._cached_stat is None


def test_wrong_hash_changed_stat_and_timeout_never_populate_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "small-fixture.gguf"
    artifact.write_bytes(b"small fixture only")

    wrong_hash_checker = _checker(artifact, digest="0" * 64)
    with pytest.raises(P2TokenBudgetError) as hash_error:
        wrong_hash_checker.prepare_artifact_binding(timeout_seconds=30.0)
    assert hash_error.value.reason == P2TokenBudgetFailure.ARTIFACT_BINDING_CHANGED
    assert wrong_hash_checker._cached_stat is None

    changed_stat_checker = _checker(artifact)
    real_stat_signature = __import__("app.p2_token_budget", fromlist=["_stat_signature"])._stat_signature
    stat_calls = 0

    def changed_during_hash(path: Path) -> tuple[str, int, int, int]:
        nonlocal stat_calls
        stat_calls += 1
        signature = real_stat_signature(path)
        if stat_calls == 2:
            return (signature[0], signature[1], signature[2] + 1, signature[3])
        return signature

    monkeypatch.setattr("app.p2_token_budget._stat_signature", changed_during_hash)
    with pytest.raises(P2TokenBudgetError) as stat_error:
        changed_stat_checker.prepare_artifact_binding(timeout_seconds=30.0)
    assert stat_error.value.reason == P2TokenBudgetFailure.ARTIFACT_BINDING_CHANGED
    assert changed_stat_checker._cached_stat is None
    assert stat_calls == 2

    timeout_checker = _checker(artifact)
    ticks = iter((0.0, 0.0, 0.0, 2.0))
    monkeypatch.setattr("app.p2_token_budget.monotonic", lambda: next(ticks))
    with pytest.raises(P2TokenBudgetError) as timeout_error:
        timeout_checker.prepare_artifact_binding(timeout_seconds=1.0)
    assert timeout_error.value.reason == P2TokenBudgetFailure.COUNTER_TIMEOUT
    assert timeout_checker._cached_stat is None


def test_prepared_binding_keeps_measurement_bounded_and_mutation_fails_before_counter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "small-fixture.gguf"
    artifact.write_bytes(b"small fixture only")
    checker = _checker(artifact)
    digest, _preparation_hash_ms = checker.prepare_artifact_binding(timeout_seconds=30.0)
    calls: list[dict[str, Any]] = []

    def fake_counter(args: list[str], *, stdin: bytes, timeout: float) -> tuple[int, bytes]:
        assert args[-1] == "--counter-child"
        assert 0 < timeout <= 5.0
        payload = json.loads(stdin.decode("utf-8"))
        calls.append(payload)
        response = {
            "ok": True,
            "model_key": MODEL_KEY,
            "api_host": API_HOST,
            "model_path": MODEL_PATH,
            "artifact_sha256": digest,
            "actual_context_tokens": 8192,
            "prompt_tokens": 20,
            "response_format_tokens": 10,
        }
        return 0, json.dumps(response, separators=(",", ":")).encode("utf-8")

    monkeypatch.setattr("app.p2_token_budget._run_bounded_helper", fake_counter)
    measurement = checker.measure(_request())
    assert measurement.total_measurement_ms <= 5000
    assert measurement.artifact_sha256 == digest
    assert len(calls) == 1

    artifact.write_bytes(b"changed artifact size")
    with pytest.raises(P2TokenBudgetError) as changed_error:
        checker.measure(_request())
    assert changed_error.value.reason == P2TokenBudgetFailure.ARTIFACT_BINDING_CHANGED
    assert len(calls) == 1
