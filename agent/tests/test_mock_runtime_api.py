from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from agent.app import mock_fixtures
from agent.app.backend import MockBackendAdapter, MockScopeAuthorizer
from agent.app.components import AppComponents
from agent.app.gateway import UnimplementedGateway
from agent.app.harness import MockModelProvider, ModelPrompt
from agent.app.ports import (
    AgentControlSnapshot,
    Principal,
    ScopeDenied,
    ScopeUnavailable,
)
from agent.app.runtime import MockRuntime
from agent.app.settings import Settings
from agent.app.store import SQLiteAgentStore


OWNER_A = uuid.UUID("11111111-1111-4111-8111-111111111111")
OWNER_B = uuid.UUID("22222222-2222-4222-8222-222222222222")
ACCESS_SENTINEL = "access-token-sentinel-do-not-persist"
REFRESH_SENTINEL = "refresh-token-sentinel-never-submitted"
PLACEHOLDER_NONCE = "N" * 32
PLACEHOLDER_DIGEST = "a" * 64


class _DIFakeAuth:
    """Explicit identity simulation; no request reaches Supabase or creates a user."""

    configured = True

    def __init__(self, *, one_shot_tokens: frozenset[str] = frozenset()) -> None:
        self._owners = {
            "token-a": OWNER_A,
            "token-a-refresh": OWNER_A,
            "token-b": OWNER_B,
            ACCESS_SENTINEL: OWNER_A,
            "one-shot-token": OWNER_A,
        }
        self._one_shot = one_shot_tokens
        self._calls: Counter[str] = Counter()
        self._revoked: set[str] = set()

    def revoke(self, token: str) -> None:
        self._revoked.add(token)

    def verify_bearer(self, token: str) -> Principal:
        self._calls[token] += 1
        owner = self._owners.get(token)
        if owner is None or token in self._revoked or (token in self._one_shot and self._calls[token] > 1):
            from agent.app.auth import Unauthenticated
            raise Unauthenticated("simulated invalid or expired credential")
        return Principal(owner, datetime.now(timezone.utc) + timedelta(hours=1))


class _Scope:
    def __init__(self) -> None:
        self.denied = False
        self.unavailable = False
        self.calls: list[tuple[uuid.UUID, frozenset[uuid.UUID], str]] = []
        self._fixture = MockScopeAuthorizer()

    def authorize(self, principal: Principal, activity_ids: frozenset[uuid.UUID], *, action: str) -> None:
        self.calls.append((principal.user_id, activity_ids, action))
        if self.unavailable:
            raise ScopeUnavailable("simulated scope adapter failure")
        if self.denied:
            raise ScopeDenied("simulated permission denial")
        self._fixture.authorize(principal, activity_ids, action=action)


class _Control:
    def __init__(self, enabled: bool = True, revision: int = 0) -> None:
        self.enabled = enabled
        self.revision = revision

    def snapshot(self) -> AgentControlSnapshot:
        return AgentControlSnapshot(
            enabled=self.enabled,
            disable_revision=self.revision,
            source="simulation",
        )


class _RecordingProvider(MockModelProvider):
    def __init__(
        self,
        *,
        scripted_responses: tuple[str | BaseException, ...] = (),
        delay_seconds: float = 0,
    ) -> None:
        super().__init__(scripted_responses=scripted_responses, delay_seconds=delay_seconds)
        self.prompts: list[ModelPrompt] = []
        self.after_generate: Any = None

    async def generate(self, prompt: ModelPrompt) -> str:
        self.prompts.append(prompt)
        output = await super().generate(prompt)
        if self.after_generate is not None:
            self.after_generate(prompt)
        return output


def _make_components(
    database: Path,
    *,
    auth: _DIFakeAuth | None = None,
    control: _Control | None = None,
    scope: _Scope | None = None,
    provider: _RecordingProvider | None = None,
) -> AppComponents:
    actual_auth = auth or _DIFakeAuth()
    actual_control = control or _Control()
    actual_scope = scope or _Scope()
    actual_provider = provider or _RecordingProvider()
    actual_store = SQLiteAgentStore(database, admission_enabled=True)
    actual_backend = MockBackendAdapter()
    actual_runtime = MockRuntime(
        actual_store,
        actual_provider,
        actual_backend,
        actual_auth,
        actual_scope,
        actual_control,
        model_timeout_seconds=1,
    )
    return AppComponents(
        store=actual_store,
        provider=actual_provider,
        backend=actual_backend,
        runtime=actual_runtime,
        gateway=UnimplementedGateway(),
        auth_verifier=actual_auth,
        scope_authorizer=actual_scope,
        agent_control=actual_control,
    )


def _client(
    database: Path,
    *,
    auth: _DIFakeAuth | None = None,
    control: _Control | None = None,
    scope: _Scope | None = None,
    provider: _RecordingProvider | None = None,
) -> tuple[TestClient, AppComponents]:
    components = _make_components(
        database, auth=auth, control=control, scope=scope, provider=provider,
    )
    settings = Settings(
        storage_path=database,
        provider_mode="mock",
        agent_enabled=True,
        disable_revision=0,
        api_requests_per_minute=500,
        mock_model_timeout_seconds=1,
    )
    from agent.app.main import create_app
    app = create_app(settings, components_factory=lambda _: components)
    return TestClient(app), components


def _headers(token: str = "token-a") -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def _create_session(client: TestClient, token: str = "token-a") -> uuid.UUID:
    response = client.post("/v1/sessions", headers=_headers(token), json={
        "api_version": "1.0.0",
        "client_request_id": str(uuid.uuid4()),
        "title": "Mock API integration",
    })
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["session"]["session_id"])


def _submit(
    client: TestClient,
    session_id: uuid.UUID,
    text: str,
    *,
    token: str = "token-a",
    ui_context: dict[str, Any] | None = None,
) -> uuid.UUID:
    body: dict[str, Any] = {"client_request_id": str(uuid.uuid4()), "text": text}
    if ui_context is not None:
        body["ui_context"] = ui_context
    response = client.post(
        f"/v1/sessions/{session_id}/turns", headers=_headers(token), json=body,
    )
    assert response.status_code == 202, response.text
    return uuid.UUID(response.json()["turn_id"])


def _wait_state(
    components: AppComponents,
    owner: uuid.UUID,
    turn_id: uuid.UUID,
    expected: set[str],
    *,
    timeout: float = 5,
) -> Any:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = components.store.get_turn(owner, turn_id)
        if last.record.turn.state.value in expected:
            return last
        time.sleep(0.01)
    assert last is not None
    event_details = []
    try:
        view = components.store.read_turn_view(owner, turn_id)
        event_details = [
            (item.event.type, item.event.model_dump(mode="json", by_alias=True))
            for item in view.events
        ]
    except Exception:
        pass
    raise AssertionError(
        f"turn did not reach {expected}; state={last.record.turn.state.value}, "
        f"step={last.record.turn.step.value}, wait={last.record.turn.wait_reason}, "
        f"resume={last.record.turn.resume_state}, checkpoint={last.checkpoint.resume_step}, "
        f"events={event_details}"
    )


def _events(client: TestClient, turn_id: uuid.UUID, token: str = "token-a") -> dict[str, Any]:
    response = client.get(f"/v1/turns/{turn_id}/events", headers=_headers(token))
    assert response.status_code == 200, response.text
    return response.json()


def _message(events: dict[str, Any]) -> dict[str, Any]:
    return next(event for event in events["events"] if event["type"] == "message")


def _assert_typed_error(response: Any, status: int) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"api_version", "code", "message", "retryable"}
    assert body["api_version"] == "1.0.0"
    return body


def _assert_no_secret_in_database(database: Path, *secrets: str) -> None:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        for table in ("sessions", "turns", "events", "proposals"):
            rows = connection.execute(f"SELECT * FROM {table}").fetchall()
            for row in rows:
                serialized = json.dumps(row, ensure_ascii=False, default=str)
                for secret in secrets:
                    assert secret not in serialized, f"{secret!r} was persisted in {table}"
    finally:
        connection.close()


def test_mock_api_exercises_four_semantics_and_ignores_client_scope_hints(tmp_path: Path) -> None:
    database = tmp_path / "semantic-api.sqlite3"
    provider = _RecordingProvider()
    client, components = _client(database, provider=provider)
    with client:
        session_id = _create_session(client)

        spoofed_ui_context = {
            "page_type": "activity_overview",
            "activity_id": str(mock_fixtures.ACTIVITY_ID),
            "selected_entity": {
                "entity_type": "activity",
                "entity_id": str(mock_fixtures.ACTIVITY_ID),
            },
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "client_version": "test-client",
        }
        conversation_turn = _submit(
            client, session_id, "你好", ui_context=spoofed_ui_context,
        )
        conversation = _wait_state(components, OWNER_A, conversation_turn, {"COMPLETED"})
        assert conversation.checkpoint.model_context is not None
        assert conversation.checkpoint.model_context.verified_scope.kind == "none"
        assert conversation.record.bound_references == []
        conversation_events = _events(client, conversation_turn)
        conversation_message = _message(conversation_events)
        assert conversation_message["simulation"] is True
        assert conversation_message["payload"]["citations"] == []

        policy_turn = _submit(client, session_id, "写入规则是什么？")
        _wait_state(components, OWNER_A, policy_turn, {"COMPLETED"})
        policy_message = _message(_events(client, policy_turn))
        assert policy_message["payload"]["citations"] == ["policy_fact_1"]
        assert "模拟" in policy_message["payload"]["text"]

        expected_operations = {
            "查有哪些活动": "read.activities",
            "查询消费": "read.expenses",
            "查欠款": "read.debts",
        }
        for prompt, expected_operation in expected_operations.items():
            turn_id = _submit(client, session_id, prompt)
            completed = _wait_state(components, OWNER_A, turn_id, {"COMPLETED"})
            assert completed.checkpoint.read_calls == 1
            assert len(completed.checkpoint.read_results) == 1
            result = completed.checkpoint.read_results[0]
            assert result.operation.value == expected_operation
            assert result.simulation is True
            fact_message = _message(_events(client, turn_id))
            assert fact_message["payload"]["citations"]

        assert components.provider.health().inference_available is False
        assert client.get("/health/provider").json() == {
            "status": "simulation",
            "inference_available": False,
            "reason": "mock_simulation_only",
        }
        assert provider.prompts
        prompt_json = "\n".join(prompt.model_dump_json() for prompt in provider.prompts)
        assert ACCESS_SENTINEL not in prompt_json
        assert REFRESH_SENTINEL not in prompt_json
        assert PLACEHOLDER_NONCE not in prompt_json

        # A client role field is not part of the frozen request and cannot grant access.
        forged_role = client.post(
            f"/v1/sessions/{session_id}/turns", headers=_headers(),
            json={"client_request_id": str(uuid.uuid4()), "text": "查欠款", "role": "admin"},
        )
        _assert_typed_error(forged_role, 422)

    _assert_no_secret_in_database(
        database, ACCESS_SENTINEL, REFRESH_SENTINEL, PLACEHOLDER_NONCE,
    )


def test_api_clarification_resumes_to_simulation_and_adjusts_same_proposal(tmp_path: Path) -> None:
    database = tmp_path / "clarify-adjust-api.sqlite3"
    client, components = _client(database)
    with client:
        session_id = _create_session(client)
        turn_id = _submit(client, session_id, "记录午餐")
        waiting = _wait_state(components, OWNER_A, turn_id, {"WAIT_INPUT"})
        assert waiting.record.turn.wait_reason.value == "missing_fields"
        assert waiting.record.turn.resume_state.value == "RUNNING"
        clarification = next(
            event for event in _events(client, turn_id)["events"]
            if event["type"] == "clarification"
        )
        assert "original_amount" in clarification["payload"]["missing_slots"]

        clarification_request = {
            "client_request_id": str(uuid.uuid4()),
            "expected_state_revision": waiting.record.turn.state_revision,
            "text": "12.50 CNY",
        }
        resumed = client.post(
            f"/v1/turns/{turn_id}/resume/clarification",
            headers=_headers(), json=clarification_request,
        )
        assert resumed.status_code == 202, resumed.text
        assert resumed.json()["state"] == "RUNNING"
        proposal_turn = _wait_state(components, OWNER_A, turn_id, {"WAIT_CONFIRM"})
        view = components.store.read_turn_view(OWNER_A, turn_id)
        original = next(item for item in view.proposals if item.status.value == "pending")
        assert original.mode == "simulation"
        assert original.operation == "expense.create"
        assert original.confirmation_nonce is None
        assert original.command_digest is None
        assert original.canonical_command is None
        card = _events(client, turn_id)["proposal_cards"][0]
        assert card["card_kind"] == "simulation_pending"
        assert card["simulation"] is True
        assert card["confirmation_enabled"] is False
        assert "confirmation_nonce" not in card
        assert "command_digest" not in card

        adjust_request = {
            "client_request_id": str(uuid.uuid4()),
            "expected_state_revision": proposal_turn.record.turn.state_revision,
            "expected_proposal_revision": original.revision,
            "text": "改成 20.50 CNY",
        }
        adjusted = client.post(
            f"/v1/turns/{turn_id}/resume/proposal-adjust",
            headers=_headers(), json=adjust_request,
        )
        assert adjusted.status_code == 202, adjusted.text
        assert adjusted.json()["state"] == "WAIT_CONFIRM"
        assert adjusted.json()["proposal_id"] == str(original.proposal_id)
        assert adjusted.json()["proposal_revision"] == original.revision + 1
        assert client.post(
            f"/v1/turns/{turn_id}/resume/proposal-adjust",
            headers=_headers(), json=adjust_request,
        ).json() == adjusted.json()

        updated = components.store.get_proposal(OWNER_A, original.proposal_id)
        assert updated.revision == original.revision + 1
        assert updated.operation == original.operation
        assert updated.mode == "simulation"
        assert updated.intent.kind == "expense.create"
        assert updated.preview is not None and updated.preview.simulation
        assert updated.preview.after is not None
        assert updated.preview.after.original_amount == "20.50"

        # An ordinary query finishes independently and leaves the existing preview intact.
        query_turn = _submit(client, session_id, "你好")
        _wait_state(components, OWNER_A, query_turn, {"COMPLETED"})
        still_pending = components.store.get_proposal(OWNER_A, original.proposal_id)
        assert still_pending.status.value == "pending"
        assert still_pending.revision == updated.revision
        session = client.get(f"/v1/sessions/{session_id}", headers=_headers()).json()
        pending_cards = [card for card in session["proposal_cards"] if card["status"] == "pending"]
        assert len(pending_cards) == 1
        assert pending_cards[0]["proposal_id"] == str(original.proposal_id)

        confirmation = {
            "client_request_id": str(uuid.uuid4()),
            "expected_proposal_revision": updated.revision,
            "command_digest": PLACEHOLDER_DIGEST,
            "confirmation_nonce": PLACEHOLDER_NONCE,
        }
        first_confirm = client.post(
            f"/v1/proposals/{original.proposal_id}/confirm",
            headers=_headers(), json=confirmation,
        )
        assert first_confirm.status_code == 501, first_confirm.text
        confirm_response = first_confirm.json()
        assert confirm_response["code"] == "execution_capability_unavailable"
        assert confirm_response["execution_enabled"] is False
        assert confirm_response["business_write_performed"] is False
        assert components.store.get_turn(OWNER_A, turn_id).record.turn.execution is None

        # Same-key replay remains the exact durable 501 after a later adjustment and gate close.
        latest_turn = components.store.get_turn(OWNER_A, turn_id)
        second_adjust = {
            "client_request_id": str(uuid.uuid4()),
            "expected_state_revision": latest_turn.record.turn.state_revision,
            "expected_proposal_revision": updated.revision,
            "text": "改成 21.75 CNY",
        }
        second_adjusted = client.post(
            f"/v1/turns/{turn_id}/resume/proposal-adjust",
            headers=_headers(), json=second_adjust,
        )
        assert second_adjusted.status_code == 202, second_adjusted.text
        control = components.agent_control
        assert isinstance(control, _Control)
        control.enabled = False
        replay = client.post(
            f"/v1/proposals/{original.proposal_id}/confirm",
            headers=_headers(), json=confirmation,
        )
        assert replay.status_code == 501
        assert replay.json() == confirm_response
        assert components.store.get_turn(OWNER_A, turn_id).record.turn.execution is None

    _assert_no_secret_in_database(
        database, ACCESS_SENTINEL, REFRESH_SENTINEL, PLACEHOLDER_NONCE,
    )


def test_api_adjustment_auth_pause_resumes_and_retries_the_same_reserved_input(tmp_path: Path) -> None:
    database = tmp_path / "adjust-auth-resume-api.sqlite3"
    auth = _DIFakeAuth()
    provider = _RecordingProvider()
    client, components = _client(database, auth=auth, provider=provider)
    with client:
        session_id = _create_session(client)
        turn_id = _submit(client, session_id, "记录午餐 12.50 CNY")
        original_waiting = _wait_state(components, OWNER_A, turn_id, {"WAIT_CONFIRM"})
        proposal = next(
            item for item in components.store.read_turn_view(OWNER_A, turn_id).proposals
            if item.status.value == "pending"
        )
        initial_generation = original_waiting.checkpoint.generation
        initial_provider_calls = len(provider.prompts)

        request = {
            "client_request_id": str(uuid.uuid4()),
            "expected_state_revision": original_waiting.record.turn.state_revision,
            "expected_proposal_revision": proposal.revision,
            "text": "改成 20.50 CNY",
        }
        # The adjustment is accepted and charged before the provider returns.
        # Revoke its bearer from inside that provider call so the post-call identity
        # verification must persist an auth pause instead of replacing the proposal.
        provider.after_generate = lambda _prompt: auth.revoke("token-a")
        interrupted = client.post(
            f"/v1/turns/{turn_id}/resume/proposal-adjust",
            headers=_headers(), json=request,
        )
        assert _assert_typed_error(interrupted, 401)["retryable"] is True

        paused = components.store.get_turn(OWNER_A, turn_id)
        assert paused.record.turn.state.value == "WAIT_INPUT"
        assert paused.record.turn.wait_reason.value == "auth_required"
        assert paused.record.turn.resume_state.value == "WAIT_CONFIRM"
        assert paused.checkpoint.generation == initial_generation + 1
        assert paused.checkpoint.model_calls == 1
        assert paused.checkpoint.read_calls == 0
        assert paused.checkpoint.repair_calls == 0
        reservation = paused.checkpoint.adjustment_reservation
        assert reservation is not None
        assert reservation.client_request_id == uuid.UUID(request["client_request_id"])
        assert reservation.proposal_id == proposal.proposal_id
        assert reservation.expected_proposal_revision == proposal.revision
        assert reservation.lease_token is None
        assert reservation.lease_expires_at is None
        accepted_adjustment = next(
            item for item in paused.checkpoint.accepted_inputs
            if item.client_request_id == reservation.client_request_id
        )
        expected_adjustment = type(accepted_adjustment.payload).model_validate(request)
        assert accepted_adjustment.payload == expected_adjustment
        assert accepted_adjustment.payload_hash == reservation.payload_hash
        assert accepted_adjustment.payload.text == request["text"]
        still_current = components.store.get_proposal(OWNER_A, proposal.proposal_id)
        assert still_current.revision == proposal.revision
        assert still_current.status.value == "pending"
        assert len(provider.prompts) == initial_provider_calls + 1

        auth_resume_request = {
            "client_request_id": str(uuid.uuid4()),
            "expected_state_revision": paused.record.turn.state_revision,
        }
        auth_resumed = client.post(
            f"/v1/turns/{turn_id}/resume/auth",
            headers=_headers("token-a-refresh"), json=auth_resume_request,
        )
        assert auth_resumed.status_code == 202, auth_resumed.text
        assert auth_resumed.json()["state"] == "WAIT_CONFIRM"
        after_auth_resume = components.store.get_turn(OWNER_A, turn_id)
        assert after_auth_resume.record.turn.state.value == "WAIT_CONFIRM"
        assert after_auth_resume.checkpoint.generation == paused.checkpoint.generation
        assert after_auth_resume.checkpoint.model_calls == paused.checkpoint.model_calls
        assert after_auth_resume.checkpoint.read_calls == paused.checkpoint.read_calls
        assert after_auth_resume.checkpoint.adjustment_reservation is not None
        assert after_auth_resume.checkpoint.adjustment_reservation.payload_hash == reservation.payload_hash

        # The accepted request keeps its original expected_state_revision and key.
        retried = client.post(
            f"/v1/turns/{turn_id}/resume/proposal-adjust",
            headers=_headers("token-a-refresh"), json=request,
        )
        assert retried.status_code == 202, retried.text
        retried_body = retried.json()
        assert retried_body["proposal_id"] == str(proposal.proposal_id)
        assert retried_body["proposal_revision"] == proposal.revision + 1
        after_retry = components.store.get_turn(OWNER_A, turn_id)
        updated = components.store.get_proposal(OWNER_A, proposal.proposal_id)
        assert after_retry.record.turn.state.value == "WAIT_CONFIRM"
        assert after_retry.checkpoint.generation == paused.checkpoint.generation
        assert after_retry.checkpoint.model_calls == 2
        assert after_retry.checkpoint.read_calls == paused.checkpoint.read_calls
        assert after_retry.checkpoint.adjustment_reservation is None
        assert updated.revision == proposal.revision + 1
        assert updated.status.value == "pending"
        assert updated.operation == proposal.operation
        assert updated.preview is not None and updated.preview.after is not None
        assert updated.preview.after.original_amount == "20.50"
        adjust_receipts = [
            item for item in after_retry.record.request_receipts
            if item.key_scope.value == "turns.resume.proposal_adjust"
            and item.client_request_id == uuid.UUID(request["client_request_id"])
        ]
        assert len(adjust_receipts) == 1
        assert adjust_receipts[0].response_snapshot.model_dump(
            mode="json", by_alias=True, exclude_none=False,
        ) == retried_body

        calls_after_retry = len(provider.prompts)
        replay = client.post(
            f"/v1/turns/{turn_id}/resume/proposal-adjust",
            headers=_headers("token-a-refresh"), json=request,
        )
        assert replay.status_code == 202
        assert replay.json() == retried_body
        assert len(provider.prompts) == calls_after_retry
        final = components.store.get_turn(OWNER_A, turn_id)
        final_receipts = [
            item for item in final.record.request_receipts
            if item.key_scope.value == "turns.resume.proposal_adjust"
            and item.client_request_id == uuid.UUID(request["client_request_id"])
        ]
        assert len(final_receipts) == 1


def test_api_auth_required_survives_restart_then_http_auth_resume_requeues_turn(tmp_path: Path) -> None:
    database = tmp_path / "auth-restart-api.sqlite3"
    first_auth = _DIFakeAuth(one_shot_tokens=frozenset({"one-shot-token"}))
    first_client, first = _client(database, auth=first_auth)
    with first_client:
        session_id = _create_session(first_client)
        turn_id = _submit(first_client, session_id, "你好", token="one-shot-token")
        paused = _wait_state(first, OWNER_A, turn_id, {"WAIT_INPUT"})
        assert paused.record.turn.wait_reason.value == "auth_required"
        assert paused.record.turn.resume_state.value == "QUEUED"
        assert paused.record.turn.step.value == "auth_required"
        assert paused.checkpoint.model_calls == 0
        assert paused.checkpoint.resume_step.value == "build_context"

    second_auth = _DIFakeAuth()
    second_client, second = _client(database, auth=second_auth)
    with second_client:
        persisted = second.store.get_turn(OWNER_A, turn_id)
        assert persisted.record.turn.state.value == "WAIT_INPUT"
        assert persisted.record.turn.resume_state.value == "QUEUED"
        assert persisted.checkpoint.model_calls == 0
        request = {
            "client_request_id": str(uuid.uuid4()),
            "expected_state_revision": persisted.record.turn.state_revision,
        }
        resumed = second_client.post(
            f"/v1/turns/{turn_id}/resume/auth", headers=_headers(), json=request,
        )
        assert resumed.status_code == 202, resumed.text
        assert resumed.json()["state"] == "QUEUED"
        completed = _wait_state(second, OWNER_A, turn_id, {"COMPLETED"})
        assert completed.record.turn.resume_state is None
        statuses = [
            event.event.payload.state.value
            for event in second.store.read_turn_view(OWNER_A, turn_id).events
            if event.event.type == "status"
        ]
        assert "WAIT_INPUT" in statuses
        assert "QUEUED" in statuses
        assert "RUNNING" in statuses
        assert statuses[-1] == "COMPLETED"
        message = _message(_events(second_client, turn_id))
        assert message["payload"]["citations"] == []


def test_api_scope_denial_hides_business_events_and_cards_but_allows_safe_conversation(tmp_path: Path) -> None:
    database = tmp_path / "scope-api.sqlite3"
    scope = _Scope()
    client, components = _client(database, scope=scope)
    with client:
        session_id = _create_session(client)
        read_turn = _submit(client, session_id, "查询消费")
        _wait_state(components, OWNER_A, read_turn, {"COMPLETED"})

        proposal_turn = _submit(client, session_id, "记录午餐 12.50 CNY")
        _wait_state(components, OWNER_A, proposal_turn, {"WAIT_CONFIRM"})
        conversation_turn = _submit(client, session_id, "你好")
        _wait_state(components, OWNER_A, conversation_turn, {"COMPLETED"})

        scope.denied = True
        _assert_typed_error(
            client.get(f"/v1/turns/{read_turn}/events", headers=_headers()), 404,
        )
        hidden_session = client.get(
            f"/v1/sessions/{session_id}", headers=_headers(),
        )
        assert hidden_session.status_code == 200
        assert hidden_session.json()["proposal_cards"] == []

        safe_events = _events(client, conversation_turn)
        assert _message(safe_events)["payload"]["citations"] == []


def test_api_owner_boundary_covers_events_cards_and_all_mutations(tmp_path: Path) -> None:
    database = tmp_path / "owner-api.sqlite3"
    client, components = _client(database)
    with client:
        session_id = _create_session(client)
        turn_id = _submit(client, session_id, "记录午餐 12.50 CNY")
        waiting = _wait_state(components, OWNER_A, turn_id, {"WAIT_CONFIRM"})
        proposal = next(
            item for item in components.store.read_turn_view(OWNER_A, turn_id).proposals
            if item.status.value == "pending"
        )

        _assert_typed_error(
            client.get(f"/v1/sessions/{session_id}", headers=_headers("token-b")), 404,
        )
        _assert_typed_error(
            client.get(f"/v1/turns/{turn_id}/events", headers=_headers("token-b")), 404,
        )
        mutation_bodies = (
            (f"/v1/turns/{turn_id}/resume/auth", {
                "client_request_id": str(uuid.uuid4()),
                "expected_state_revision": waiting.record.turn.state_revision,
            }),
            (f"/v1/turns/{turn_id}/resume/clarification", {
                "client_request_id": str(uuid.uuid4()),
                "expected_state_revision": waiting.record.turn.state_revision,
                "text": "12.50 CNY",
            }),
            (f"/v1/turns/{turn_id}/resume/proposal-adjust", {
                "client_request_id": str(uuid.uuid4()),
                "expected_state_revision": waiting.record.turn.state_revision,
                "expected_proposal_revision": proposal.revision,
                "text": "改成 20.00 CNY",
            }),
            (f"/v1/turns/{turn_id}/cancel", {
                "client_request_id": str(uuid.uuid4()),
                "expected_state_revision": waiting.record.turn.state_revision,
            }),
            (f"/v1/proposals/{proposal.proposal_id}/confirm", {
                "client_request_id": str(uuid.uuid4()),
                "expected_proposal_revision": proposal.revision,
                "command_digest": PLACEHOLDER_DIGEST,
                "confirmation_nonce": PLACEHOLDER_NONCE,
            }),
        )
        for path, body in mutation_bodies:
            _assert_typed_error(
                client.post(path, headers=_headers("token-b"), json=body), 404,
            )

        owner_events = _events(client, turn_id, "token-a")
        assert owner_events["turn"]["state"] == "WAIT_CONFIRM"
        assert owner_events["proposal_cards"][0]["proposal_id"] == str(proposal.proposal_id)


def test_api_disabled_gate_preserves_metadata_and_cancel_then_reopen_stales_old_proposal(tmp_path: Path) -> None:
    database = tmp_path / "disabled-gate-api.sqlite3"
    auth = _DIFakeAuth(one_shot_tokens=frozenset({"one-shot-token"}))
    client, components = _client(database, auth=auth)
    with client:
        session_id = _create_session(client)
        cancel_session_id = _create_session(client)
        auth_session_id = _create_session(client)
        proposal_turn = _submit(client, session_id, "记录午餐 12.50 CNY")
        waiting = _wait_state(components, OWNER_A, proposal_turn, {"WAIT_CONFIRM"})
        proposal = next(
            item for item in components.store.read_turn_view(OWNER_A, proposal_turn).proposals
            if item.status.value == "pending"
        )
        cancel_turn = _submit(client, cancel_session_id, "记录晚餐 18.00 CNY")
        cancel_waiting = _wait_state(components, OWNER_A, cancel_turn, {"WAIT_CONFIRM"})
        auth_turn = _submit(client, auth_session_id, "你好", token="one-shot-token")
        auth_waiting = _wait_state(components, OWNER_A, auth_turn, {"WAIT_INPUT"})
        assert auth_waiting.record.turn.wait_reason.value == "auth_required"
        control = components.agent_control
        assert isinstance(control, _Control)
        control.enabled = False
        control.revision = 1

        session = client.get(f"/v1/sessions/{session_id}", headers=_headers())
        assert session.status_code == 200
        assert session.json()["proposal_cards"] == []
        _assert_typed_error(
            client.post(
                f"/v1/sessions/{session_id}/turns", headers=_headers(),
                json={"client_request_id": str(uuid.uuid4()), "text": "你好"},
            ), 409,
        )
        confirm = {
            "client_request_id": str(uuid.uuid4()),
            "expected_proposal_revision": proposal.revision,
            "command_digest": PLACEHOLDER_DIGEST,
            "confirmation_nonce": PLACEHOLDER_NONCE,
        }
        assert _assert_typed_error(
            client.post(
                f"/v1/proposals/{proposal.proposal_id}/confirm",
                headers=_headers(), json=confirm,
            ), 409,
        )["code"] == "agent_disabled"

        auth_resume = client.post(
            f"/v1/turns/{auth_turn}/resume/auth", headers=_headers(), json={
                "client_request_id": str(uuid.uuid4()),
                "expected_state_revision": auth_waiting.record.turn.state_revision,
            },
        )
        assert auth_resume.status_code == 202, auth_resume.text
        assert auth_resume.json()["state"] == "QUEUED"

        cancel = client.post(
            f"/v1/turns/{cancel_turn}/cancel", headers=_headers(), json={
                "client_request_id": str(uuid.uuid4()),
                "expected_state_revision": cancel_waiting.record.turn.state_revision,
            },
        )
        assert cancel.status_code == 202, cancel.text
        assert cancel.json()["result"] == "cancelled"

        control.enabled = True
        reopened = client.get(f"/v1/sessions/{session_id}", headers=_headers()).json()
        assert all(card["proposal_id"] != str(proposal.proposal_id)
                   for card in reopened["proposal_cards"])
        stale_confirm = client.post(
            f"/v1/proposals/{proposal.proposal_id}/confirm",
            headers=_headers(), json={
                **confirm,
                "client_request_id": str(uuid.uuid4()),
            },
        )
        assert _assert_typed_error(stale_confirm, 409)["code"] == "agent_disabled"


def test_api_expiry_is_rejected_and_new_proposal_expires_old_pending_in_same_session(
    tmp_path: Path,
) -> None:
    database = tmp_path / "expiry-api.sqlite3"
    client, components = _client(database)
    with client:
        session_id = _create_session(client)
        old_turn = _submit(client, session_id, "记录午餐 12.50 CNY")
        old_waiting = _wait_state(components, OWNER_A, old_turn, {"WAIT_CONFIRM"})
        old_proposal = next(
            item for item in components.store.read_turn_view(OWNER_A, old_turn).proposals
            if item.status.value == "pending"
        )

        # Age only this durable simulation fixture so the HTTP endpoint and the
        # proposal replacement transaction exercise their ordinary expiry checks.
        expired_record = old_proposal.model_dump(mode="json", by_alias=True, exclude_none=False)
        expired_record["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "UPDATE proposals SET record_json = ?, updated_at = ? WHERE proposal_id = ?",
                (json.dumps(expired_record, sort_keys=True, separators=(",", ":")),
                 datetime.now(timezone.utc).isoformat(), str(old_proposal.proposal_id)),
            )
            connection.commit()
        finally:
            connection.close()
        expired_confirm = client.post(
            f"/v1/proposals/{old_proposal.proposal_id}/confirm",
            headers=_headers(), json={
                "client_request_id": str(uuid.uuid4()),
                "expected_proposal_revision": old_proposal.revision,
                "command_digest": PLACEHOLDER_DIGEST,
                "confirmation_nonce": PLACEHOLDER_NONCE,
            },
        )
        assert _assert_typed_error(expired_confirm, 409)["code"] == "proposal_expired"

        replacement_turn = _submit(client, session_id, "记录晚餐 18.00 CNY")
        replacement_waiting = _wait_state(
            components, OWNER_A, replacement_turn, {"WAIT_CONFIRM"},
        )
        assert replacement_waiting.record.turn.state.value == "WAIT_CONFIRM"
        old_after = components.store.get_proposal(OWNER_A, old_proposal.proposal_id)
        assert old_after.status.value == "expired"
        assert components.store.get_turn(OWNER_A, old_turn).record.turn.state.value == "FAILED"
        new_proposal = next(
            item for item in components.store.read_turn_view(OWNER_A, replacement_turn).proposals
            if item.status.value == "pending"
        )
        assert new_proposal.proposal_id != old_proposal.proposal_id
        session = client.get(f"/v1/sessions/{session_id}", headers=_headers()).json()
        pending_cards = [card for card in session["proposal_cards"] if card["status"] == "pending"]
        assert len(pending_cards) == 1
        assert pending_cards[0]["proposal_id"] == str(new_proposal.proposal_id)


def test_api_scope_free_runtime_error_is_readable_with_valid_provenance(tmp_path: Path) -> None:
    database = tmp_path / "scope-free-error-api.sqlite3"
    provider = _RecordingProvider(scripted_responses=(RuntimeError("private provider detail"),))
    scope = _Scope()
    client, components = _client(database, provider=provider, scope=scope)
    with client:
        session_id = _create_session(client)
        turn_id = _submit(client, session_id, "你好")
        failed = _wait_state(components, OWNER_A, turn_id, {"FAILED"})
        assert failed.checkpoint.event_provenance
        scope.denied = True
        events = _events(client, turn_id)
        error = next(event for event in events["events"] if event["type"] == "error")
        assert error["simulation"] is True
        assert error["payload"]["message"] == "The simulation could not complete this step."
        assert "private provider detail" not in json.dumps(events)


def test_api_admission_429_has_no_receipt_and_exact_request_retries_when_capacity_frees(
    tmp_path: Path,
) -> None:
    database = tmp_path / "admission-api.sqlite3"
    provider = _RecordingProvider(delay_seconds=0.35)
    client, components = _client(database, provider=provider)
    with client:
        session_id = _create_session(client)
        first = _submit(client, session_id, "你好")
        _wait_state(components, OWNER_A, first, {"RUNNING"})

        second_request = {"client_request_id": str(uuid.uuid4()), "text": "继续对话"}
        second_response = client.post(
            f"/v1/sessions/{session_id}/turns", headers=_headers(), json=second_request,
        )
        assert second_response.status_code == 202, second_response.text
        second = uuid.UUID(second_response.json()["turn_id"])
        assert components.store.get_turn(OWNER_A, second).record.turn.state.value == "QUEUED"

        retry_request = {"client_request_id": str(uuid.uuid4()), "text": "稍后再试"}
        rejected = client.post(
            f"/v1/sessions/{session_id}/turns", headers=_headers(), json=retry_request,
        )
        assert _assert_typed_error(rejected, 429)["retryable"] is True
        before_retry = components.store.get_session_detail(OWNER_A, session_id)
        assert len(before_retry.turns) == 2

        _wait_state(components, OWNER_A, first, {"COMPLETED"})
        _wait_state(components, OWNER_A, second, {"RUNNING"})
        accepted = client.post(
            f"/v1/sessions/{session_id}/turns", headers=_headers(), json=retry_request,
        )
        assert accepted.status_code == 202, accepted.text
        retried_turn = uuid.UUID(accepted.json()["turn_id"])
        assert retried_turn != first and retried_turn != second
        _wait_state(components, OWNER_A, retried_turn, {"COMPLETED"})
