from __future__ import annotations

import builtins
import uuid
import time
import sys
from pathlib import Path

from app import contracts as c
from app.contracts import ResumeAuthRequest, ResumeClarificationRequest
from app.p2_model_provider import LMStudioProviderError, LMStudioProviderErrorCode
import app.components as components_module
from app.components import build_components
from app.p2_token_budget import LMStudioSDKTokenBudgetChecker
from app.settings import Settings
from test_p2_runtime import _build_client, _create_session, _submit, _wait


def test_hidden_unproved_error_does_not_block_following_status_for_limit_one(tmp_path) -> None:
    client, components, provider, _backend = _build_client(tmp_path / "p2-hidden-error.sqlite3")

    async def unavailable(_prompt):
        raise LMStudioProviderError(LMStudioProviderErrorCode.OFFLINE)

    provider.generate = unavailable
    with client:
        session_id = _create_session(client)
        turn_id = _submit(client, session_id, "list activities", scoped=False)
        aggregate = _wait(components, turn_id, {c.TurnState.WAIT_INPUT})
        view = components.store.read_turn_view(
            aggregate.record.turn.owner_user_id, turn_id, after_seq=0, limit=20,
        )
        error = next(item.event for item in view.events if item.event.type == c.EventType.ERROR)
        following_status = next(
            item.event for item in view.events
            if item.event.type == c.EventType.STATUS and item.event.seq > error.seq
        )

        # Simulate loss of the isolated proof journal. The status event must
        # still be retrievable even when the caller requests one visible event.
        components.runtime._journal.close()
        response = client.get(
            f"/v1/turns/{turn_id}/events?after_seq={error.seq - 1}&limit=1",
            headers={"Authorization": "Bearer p2-test-access-token"},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert [event["type"] for event in payload["events"]] == ["status"]
        assert payload["events"][0]["seq"] == following_status.seq
        assert payload["next_after_seq"] == following_status.seq
        assert payload["has_more"] is False


def test_historical_deterministic_clarification_remains_pollable_after_success(tmp_path) -> None:
    client, components, provider, _backend = _build_client(tmp_path / "p2-clarification-history.sqlite3")
    with client:
        session_id = _create_session(client)
        turn_id = _submit(client, session_id, "expense missing amount", scoped=False)
        waiting = _wait(components, turn_id, {c.TurnState.WAIT_INPUT})
        assert waiting.record.turn.wait_reason == c.WaitReason.MISSING_FIELDS

        clarification = next(
            item.event for item in components.store.read_turn_view(
                waiting.record.turn.owner_user_id, turn_id, after_seq=0, limit=20,
            ).events if item.event.type == c.EventType.CLARIFICATION
        )
        assert clarification.payload.prompt == "请提供金额。"

        async def safe_conversation_answer(prompt):
            assert prompt.context.verified_scope.kind == "none"
            return '{"kind":"answer","basis":"conversation","text":"test","citations":[]}'

        provider.generate = safe_conversation_answer

        request = ResumeClarificationRequest(
            client_request_id=uuid.uuid4(),
            expected_state_revision=waiting.record.turn.state_revision,
            text="hello",
        )
        resumed = client.post(
            f"/v1/turns/{turn_id}/resume/clarification",
            headers={"Authorization": "Bearer p2-test-access-token"},
            json=request.model_dump(mode="json", by_alias=True),
        )
        assert resumed.status_code == 202, resumed.text
        completed = _wait(components, turn_id, {c.TurnState.COMPLETED})
        assert completed.record.turn.state == c.TurnState.COMPLETED

        history = client.get(
            f"/v1/turns/{turn_id}/events?after_seq=0&limit=100",
            headers={"Authorization": "Bearer p2-test-access-token"},
        )
        assert history.status_code == 200, history.text
        history_payload = history.json()
        restored_clarification = next(
            item for item in history_payload["events"] if item["type"] == "clarification"
        )
        assert restored_clarification["payload"]["prompt"] == "请提供金额。"
        assert history_payload["next_after_seq"] == history_payload["events"][-1]["seq"]


def test_auth_resume_keeps_same_generation_budget_and_replays_proved_history(tmp_path) -> None:
    client, components, provider, _backend = _build_client(tmp_path / "p2-auth-resume.sqlite3")
    original_generate = provider.generate
    first_call = True

    async def offline_once(prompt):
        nonlocal first_call
        if first_call:
            first_call = False
            raise LMStudioProviderError(LMStudioProviderErrorCode.OFFLINE)
        return await original_generate(prompt)

    provider.generate = offline_once
    with client:
        session_id = _create_session(client)
        turn_id = _submit(client, session_id, "list activities", scoped=False)
        waiting = _wait(components, turn_id, {c.TurnState.WAIT_INPUT})
        assert waiting.record.turn.wait_reason == c.WaitReason.AUTH_REQUIRED
        assert waiting.checkpoint.generation == 1
        assert waiting.checkpoint.model_calls == 1
        assert waiting.checkpoint.read_calls == 0

        request = ResumeAuthRequest(
            client_request_id=uuid.uuid4(),
            expected_state_revision=waiting.record.turn.state_revision,
        )
        resumed = client.post(
            f"/v1/turns/{turn_id}/resume/auth",
            headers={"Authorization": "Bearer p2-test-access-token"},
            json=request.model_dump(mode="json", by_alias=True),
        )
        assert resumed.status_code == 202, resumed.text
        completed = _wait(components, turn_id, {c.TurnState.COMPLETED})
        assert completed.checkpoint.generation == 1
        assert completed.checkpoint.model_calls == 3
        assert completed.checkpoint.read_calls == 1
        deadline = time.monotonic() + 1
        while len(components.runtime._turn_grants) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(components.runtime._turn_grants) == 0

        # The accepted resume receipt is stable and does not recreate a terminal
        # grant when replayed.
        replay = client.post(
            f"/v1/turns/{turn_id}/resume/auth",
            headers={"Authorization": "Bearer p2-test-access-token"},
            json=request.model_dump(mode="json", by_alias=True),
        )
        assert replay.status_code == 202, replay.text
        assert replay.json() == resumed.json()
        assert len(components.runtime._turn_grants) == 0

        history = client.get(
            f"/v1/turns/{turn_id}/events?after_seq=0&limit=100",
            headers={"Authorization": "Bearer p2-test-access-token"},
        )
        assert history.status_code == 200, history.text
        events = history.json()["events"]
        assert any(event["type"] == "error" for event in events)
        assert any(event["type"] == "message" for event in events)


def test_auth_resume_after_read_does_not_reuse_body_without_private_provenance(tmp_path) -> None:
    client, components, provider, _backend = _build_client(tmp_path / "p2-auth-resume-stale-body.sqlite3")
    original_generate = provider.generate
    calls = 0

    async def read_then_offline(prompt):
        nonlocal calls
        calls += 1
        if calls == 1:
            return await original_generate(prompt)
        raise LMStudioProviderError(LMStudioProviderErrorCode.OFFLINE)

    provider.generate = read_then_offline
    with client:
        session_id = _create_session(client)
        turn_id = _submit(client, session_id, "list activities", scoped=False)
        waiting = _wait(components, turn_id, {c.TurnState.WAIT_INPUT})
        assert waiting.record.turn.wait_reason == c.WaitReason.AUTH_REQUIRED
        assert waiting.checkpoint.model_calls == 2
        assert waiting.checkpoint.read_calls == 1
        assert waiting.checkpoint.read_results[0].body.items

        request = ResumeAuthRequest(
            client_request_id=uuid.uuid4(),
            expected_state_revision=waiting.record.turn.state_revision,
        )
        resumed = client.post(
            f"/v1/turns/{turn_id}/resume/auth",
            headers={"Authorization": "Bearer p2-test-access-token"},
            json=request.model_dump(mode="json", by_alias=True),
        )
        assert resumed.status_code == 202, resumed.text
        clarified = _wait(components, turn_id, {c.TurnState.WAIT_INPUT})
        assert clarified.record.turn.wait_reason == c.WaitReason.MISSING_FIELDS
        assert clarified.checkpoint.generation == 1
        assert clarified.checkpoint.model_calls == 2
        assert clarified.checkpoint.read_calls == 1
        assert calls == 2, "old durable body must not be sent to the model after P2 provenance is lost"

        history = client.get(
            f"/v1/turns/{turn_id}/events?after_seq=0&limit=100",
            headers={"Authorization": "Bearer p2-test-access-token"},
        )
        assert history.status_code == 200, history.text
        events = history.json()["events"]
        assert any(event["type"] == "error" for event in events)
        assert any(event["type"] == "clarification" for event in events)


def test_p2_factory_is_no_io_and_token_budget_requires_explicit_binding(tmp_path) -> None:
    database = tmp_path / "factory-no-io.sqlite3"
    common = {
        "storage_path": database,
        "provider_mode": "p2",
        "supabase_auth_base_url": "https://unit-test.supabase.co",
        "supabase_api_key": "sb_publishable_unit_test_key",
        "agent_enabled": True,
        "disable_revision": 0,
    }

    disabled = build_components(Settings(**common))
    assert not database.exists()


    assert disabled.provider.health().status == "disabled"
    assert disabled.provider.health().inference_available is False
    assert disabled.provider._token_budget_checker is None
    assert not database.with_suffix(".p2journal.sqlite3").exists()

    explicit = build_components(Settings(
        **common,
        p2_lmstudio_enabled=True,
        p2_token_budget_enabled=True,
        p2_lmstudio_endpoint_url="http://host.docker.internal:1234/v1/chat/completions",
        p2_model_artifact_path=tmp_path / "not-loaded-model.gguf",
        p2_lmstudio_model_path="D:\\models\\frozen-model.gguf",
        p2_model_artifact_sha256="a" * 64,
        p2_model_artifact_size_bytes=1024,
        p2_token_counter_python=Path(sys.executable),
    ))
    assert isinstance(explicit.provider._token_budget_checker, LMStudioSDKTokenBudgetChecker)
    assert explicit.provider._config.endpoint_url == "http://host.docker.internal:1234/v1/chat/completions"
    assert explicit.provider._token_budget_checker.binding.lmstudio_api_host == (
        "http://host.docker.internal:1234"
    )
    health = explicit.provider.health()
    assert health.status == "unavailable"
    assert health.inference_available is False
    assert health.reason == "not_tested"
    assert not database.exists()


def test_default_assembly_does_not_import_candidate_or_lmstudio_sdk(monkeypatch, tmp_path) -> None:
    attempted: list[str] = []
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name in {"app.p2_read_provider", "lmstudio"}:
            attempted.append(name)
            raise AssertionError(f"default assembly attempted forbidden import: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    database = tmp_path / "default-candidate-off.sqlite3"
    components = build_components(Settings(storage_path=database))

    assert components.provider.health().status == "disabled"
    assert not database.exists()
    assert not attempted
    assert not hasattr(components_module, "P2ReadProvider")

