from __future__ import annotations

import json
import sqlite3
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent.app import api
from agent.app.backend import UnimplementedBackendAdapter
from agent.app.components import AppComponents
from agent.app.contracts import (
    ApiErrorCode, EventType, ErrorEventPayload, ResumeAuthRequest,
    ResumeClarificationRequest, ResumeProposalAdjustRequest, TurnState, TurnStep,
    canonical_command_digest,
)
from agent.app.gateway import UnimplementedGateway
from agent.app.model_provider import DisabledModelProvider
from agent.app.ports import AgentControlSnapshot, CapabilityUnavailable, Principal, ScopeDenied, ScopeUnavailable
from agent.app.runtime import UnimplementedRuntime
from agent.app.settings import Settings
from agent.app.store import EventDraft, SQLiteAgentStore


TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))
import test_sqlite_persistence as persistence  # noqa: E402


NOW = datetime(2026, 10, 8, 4, 0, tzinfo=timezone.utc)
OWNER_A = uuid.uuid4()
OWNER_B = uuid.uuid4()


class _Auth:
    configured = True

    def verify_bearer(self, token: str) -> Principal:
        if token == "token-a":
            return Principal(user_id=OWNER_A)
        if token == "token-b":
            return Principal(user_id=OWNER_B)
        if token == "auth-down":
            from agent.app.auth import AuthDependencyUnavailable
            raise AuthDependencyUnavailable("private upstream detail")
        from agent.app.auth import Unauthenticated
        raise Unauthenticated("private invalid-token detail")


class _Scope:
    def __init__(self) -> None:
        self.denied = False
        self.unavailable = False
        self.calls: list[tuple[uuid.UUID, frozenset[uuid.UUID], str]] = []

    def authorize(self, principal: Principal, activity_ids: frozenset[uuid.UUID], *, action: str) -> None:
        self.calls.append((principal.user_id, activity_ids, action))
        if self.unavailable:
            raise ScopeUnavailable("private scope adapter detail")
        if self.denied:
            raise ScopeDenied("private authorization detail")


class _Control:
    def __init__(self, enabled: bool = True, revision: int = 0) -> None:
        self.enabled = enabled
        self.revision = revision

    def snapshot(self) -> AgentControlSnapshot:
        return AgentControlSnapshot(enabled=self.enabled, disable_revision=self.revision)


class _Preparer:
    def __init__(self, available: bool = True) -> None:
        self.available = available
        self.calls = 0

    def prepare(self, owner_user_id: uuid.UUID, turn_id: uuid.UUID, proposal: Any, request: Any) -> Any:
        self.calls += 1
        if not self.available:
            raise CapabilityUnavailable("private preparation detail")
        return type(proposal).model_validate(proposal.model_dump(mode="python", by_alias=True, exclude_none=False) | {
            "revision": proposal.revision + 1,
            "confirmation_nonce": "Q" * 32 if proposal.mode == "backend" else None,
            "request_receipts": [],
        })


class _Components:
    def __init__(self, path: Path, *, enabled: bool = True, revision: int = 0, preparer_available: bool = True) -> None:
        self.scope = _Scope()
        self.control = _Control(enabled, revision)
        self.preparer = _Preparer(preparer_available)
        self.value = AppComponents(
            store=SQLiteAgentStore(path),
            provider=DisabledModelProvider(),
            backend=UnimplementedBackendAdapter(),
            runtime=UnimplementedRuntime(),
            gateway=UnimplementedGateway(),
            auth_verifier=_Auth(),
            scope_authorizer=self.scope,
            agent_control=self.control,
            proposal_adjustment_preparer=self.preparer,
        )


def _client(tmp_path: Path, *, enabled: bool = True, revision: int = 0, limit: int = 120) -> tuple[TestClient, _Components]:
    components = _Components(tmp_path / "api.sqlite3", enabled=enabled, revision=revision)
    settings = Settings(storage_path=tmp_path / "api.sqlite3", api_requests_per_minute=limit)
    app = api_app(settings, components)
    client = TestClient(app)
    client.__enter__()
    return client, components


def api_app(settings: Settings, components: _Components):
    from agent.app.main import create_app
    return create_app(settings, components_factory=lambda _: components.value)


def _headers(token: str = "token-a") -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def _create_session(client: TestClient, token: str = "token-a") -> uuid.UUID:
    response = client.post("/v1/sessions", headers=_headers(token), json={
        "api_version": "1.0.0", "client_request_id": str(uuid.uuid4()), "title": "Trip",
    })
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["session"]["session_id"])


def _transition(store: SQLiteAgentStore, owner: uuid.UUID, after: Any, *, updated_proposal: Any = None,
                fixture_execution: bool = False, events: list[Any] | None = None) -> Any:
    before = store.get_turn(owner, after.turn_id)
    return store.transition_turn(owner, after, expected_state_revision=before.record.turn.state_revision,
        expected_checkpoint_revision=before.checkpoint_revision,
        events=events if events is not None else [persistence._status(after)],
        updated_proposal=updated_proposal, fixture_execution=fixture_execution)


def _pause_for_auth(store: SQLiteAgentStore, turn_id: uuid.UUID, resume_state: Any) -> Any:
    aggregate = store.get_turn(OWNER_A, turn_id)
    before = aggregate.record.turn
    if before.state == TurnState.QUEUED:
        running = persistence._snapshot(before, state=TurnState.RUNNING, step=TurnStep.MODEL_DECISION)
        _transition(store, OWNER_A, running)
        before = running
    paused = persistence._snapshot(before, state=TurnState.WAIT_INPUT, step=TurnStep.AUTH_REQUIRED,
        wait_reason=persistence.c.WaitReason.AUTH_REQUIRED, resume_state=resume_state)
    _transition(store, OWNER_A, paused)
    return paused


def _with_disable_revision(proposal: Any, revision: int) -> Any:
    preconditions = proposal.preconditions.model_copy(update={"agent_disable_revision": revision})
    digest = canonical_command_digest(proposal.canonical_command, preconditions,
        policy_version=proposal.policy_version)
    return proposal.model_copy(update={"preconditions": preconditions, "command_digest": digest})


def _assert_typed_error(response: Any, status: int) -> dict[str, Any]:
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"api_version", "code", "message", "retryable"}
    assert body["api_version"] == "1.0.0"
    assert "private" not in json.dumps(body).lower()
    return body


def test_routes_are_authenticated_owner_scoped_and_errors_are_frozen(tmp_path: Path) -> None:
    client, components = _client(tmp_path)
    try:
        session_id = _create_session(client)
        assert client.get("/v1/sessions", headers=_headers("token-b")).json()["items"] == []
        _assert_typed_error(client.get(f"/v1/sessions/{session_id}", headers=_headers("token-b")), 404)
        submit = client.post(f"/v1/sessions/{session_id}/turns", headers=_headers(), json={
            "client_request_id": str(uuid.uuid4()), "text": "Record lunch",
        })
        assert submit.status_code == 202
        turn_id = uuid.UUID(submit.json()["turn_id"])

        _assert_typed_error(client.get(f"/v1/turns/{turn_id}/events", headers=_headers("token-b")), 404)
        for path, body in (
            (f"/v1/turns/{turn_id}/resume/auth", {"client_request_id": str(uuid.uuid4()), "expected_state_revision": 1}),
            (f"/v1/turns/{turn_id}/resume/clarification", {"client_request_id": str(uuid.uuid4()), "expected_state_revision": 1, "text": "CNY"}),
            (f"/v1/turns/{turn_id}/resume/proposal-adjust", {"client_request_id": str(uuid.uuid4()), "expected_state_revision": 1, "expected_proposal_revision": 1, "text": "change title"}),
            (f"/v1/turns/{turn_id}/cancel", {"client_request_id": str(uuid.uuid4()), "expected_state_revision": 1}),
        ):
            _assert_typed_error(client.post(path, headers=_headers("token-b"), json=body), 404)

        foreign_submit = client.post(f"/v1/sessions/{session_id}/turns", headers=_headers("token-b"), json={
            "client_request_id": str(uuid.uuid4()), "text": "try to alter another owner's session",
        })
        _assert_typed_error(foreign_submit, 404)

        # Client-supplied identities and unknown fields cannot affect ownership.
        invalid = client.post("/v1/sessions", headers=_headers(), json={
            "api_version": "1.0.0", "client_request_id": str(uuid.uuid4()), "owner_user_id": str(OWNER_B),
        })
        _assert_typed_error(invalid, 422)
        _assert_typed_error(client.get("/v1/sessions?owner_user_id=" + str(OWNER_B), headers=_headers()), 400)
        _assert_typed_error(client.delete("/v1/sessions", headers=_headers()), 405)
        _assert_typed_error(client.get("/v1/unknown", headers=_headers()), 404)
        _assert_typed_error(client.get("/v1/sessions"), 401)
        _assert_typed_error(client.get("/v1/sessions", headers={"Authorization": "Basic token-a"}), 401)
        _assert_typed_error(client.get("/v1/sessions", headers={"Authorization": "Bearer  token-a"}), 401)
        duplicate_auth = client.get("/v1/sessions", headers=[
            ("Authorization", "Bearer token-a"), ("Authorization", "Bearer token-b"),
        ])
        _assert_typed_error(duplicate_auth, 401)
        _assert_typed_error(client.get("/v1/sessions", headers=_headers("not-a-user")), 401)
        _assert_typed_error(client.get("/v1/sessions", headers=_headers("auth-down")), 503)
    finally:
        client.__exit__(None, None, None)


def test_json_parser_rejects_duplicate_nonfinite_oversized_and_wrong_content_type(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    try:
        headers = {**_headers(), "Content-Type": "application/json"}
        duplicate = client.post("/v1/sessions", headers=headers,
            content=b'{"api_version":"1.0.0","client_request_id":"' + str(uuid.uuid4()).encode() + b'","client_request_id":"' + str(uuid.uuid4()).encode() + b'"}')
        _assert_typed_error(duplicate, 400)
        nonfinite = client.post("/v1/sessions", headers=headers,
            content=b'{"api_version":"1.0.0","client_request_id":"' + str(uuid.uuid4()).encode() + b'","extra":NaN}')
        _assert_typed_error(nonfinite, 400)
        too_large = client.post("/v1/sessions", headers=headers, content=b" " * 1100)
        _assert_typed_error(too_large, 400)
        wrong_type = client.post("/v1/sessions", headers={**_headers(), "Content-Type": "text/plain"}, content=b"{}")
        _assert_typed_error(wrong_type, 400)
    finally:
        client.__exit__(None, None, None)


def test_session_cursor_is_owner_bound_and_mac_separator_is_unambiguous(tmp_path: Path, monkeypatch: Any) -> None:
    client, _ = _client(tmp_path)
    try:
        _create_session(client)
        _create_session(client)
        real_new = api.hmac.new

        class _DotMac:
            def digest(self) -> bytes:
                return b"A" * 5 + b"." + b"B" * 26

        monkeypatch.setattr(api.hmac, "new", lambda *args, **kwargs: _DotMac())
        first = client.get("/v1/sessions?limit=1", headers=_headers())
        assert first.status_code == 200
        cursor = first.json()["next_cursor"]
        assert cursor
        second = client.get("/v1/sessions?limit=1&cursor=" + cursor, headers=_headers())
        assert second.status_code == 200
        assert len(second.json()["items"]) == 1
        monkeypatch.setattr(api.hmac, "new", real_new)
        _assert_typed_error(client.get("/v1/sessions?limit=1&cursor=" + cursor, headers=_headers("token-b")), 400)
        _assert_typed_error(client.get("/v1/sessions?limit=0", headers=_headers()), 422)
        _assert_typed_error(client.get("/v1/sessions?limit=1&limit=1", headers=_headers()), 400)
    finally:
        client.__exit__(None, None, None)


def test_agent_gate_replay_and_backend_disable_revision_scope(tmp_path: Path) -> None:
    client, components = _client(tmp_path, enabled=True, revision=0)
    try:
        session_id = _create_session(client)
        store = components.value.store
        _, turn_id = persistence._submit(store, session_id, OWNER_A)
        proposal = persistence._proposal(OWNER_A, session_id, turn_id, backend=True)
        waiting = persistence._wait_with_proposal(store, OWNER_A, turn_id, proposal)
        detail = client.get(f"/v1/sessions/{session_id}", headers=_headers())
        assert detail.status_code == 200
        assert detail.json()["proposal_cards"][0]["confirmation_nonce"] == proposal.confirmation_nonce

        body = {
            "client_request_id": str(uuid.uuid4()), "expected_proposal_revision": proposal.revision,
            "command_digest": proposal.command_digest, "confirmation_nonce": proposal.confirmation_nonce,
        }
        confirmed = client.post(f"/v1/proposals/{proposal.proposal_id}/confirm", headers=_headers(), json=body)
        assert confirmed.status_code == 501
        assert confirmed.json()["business_write_performed"] is False
        assert proposal.confirmation_nonce not in confirmed.text

        # Persist a replacement revision. Exact confirmation replay still returns
        # the original 501 after state/version/gate changes, but only while scope is fresh.
        current = store.get_proposal(OWNER_A, proposal.proposal_id)
        adjust = ResumeProposalAdjustRequest(client_request_id=uuid.uuid4(),
            expected_state_revision=waiting.state_revision, expected_proposal_revision=current.revision, text="Change title")
        replacement = type(current).model_validate(current.model_dump(mode="python", by_alias=True, exclude_none=False) | {
            "revision": current.revision + 1, "confirmation_nonce": "R" * 32, "request_receipts": [],
        })
        running = persistence._snapshot(waiting, state=TurnState.RUNNING, step=TurnStep.MODEL_DECISION)
        final = persistence._snapshot(running, state=TurnState.WAIT_CONFIRM, step=TurnStep.AWAITING_USER, wait_reason=persistence.c.WaitReason.CONFIRM_REQUIRED)
        store.adjust_proposal(OWNER_A, turn_id, proposal.proposal_id, adjust, replacement,
            events=[persistence._status(running), persistence._status(final), persistence._proposal_event(replacement)])
        components.control.enabled = False
        components.control.revision = 1
        replay = client.post(f"/v1/proposals/{proposal.proposal_id}/confirm", headers=_headers(), json=body)
        assert replay.status_code == 501
        assert replay.json() == confirmed.json()

        # An unavailable current business scope hides cards/facts, while the
        # owner's durable state metadata and status-only poll remain readable.
        components.scope.denied = True
        detail_after_revoke = client.get(f"/v1/sessions/{session_id}", headers=_headers())
        assert detail_after_revoke.status_code == 200
        assert len(detail_after_revoke.json()["turns"]) == 1
        assert detail_after_revoke.json()["proposal_cards"] == []
        status_poll = client.get(f"/v1/turns/{turn_id}/events?after_seq=7", headers=_headers())
        assert status_poll.status_code == 200
        _assert_typed_error(client.post(f"/v1/proposals/{proposal.proposal_id}/confirm", headers=_headers(), json=body), 404)
        _assert_typed_error(client.post(f"/v1/turns/{turn_id}/resume/proposal-adjust", headers=_headers(),
            json=adjust.model_dump(mode="json")), 404)
    finally:
        client.__exit__(None, None, None)


def test_unscoped_non_status_event_fails_closed_but_owner_status_poll_survives(tmp_path: Path) -> None:
    client, components = _client(tmp_path)
    try:
        session_id = _create_session(client)
        response = client.post(f"/v1/sessions/{session_id}/turns", headers=_headers(), json={
            "client_request_id": str(uuid.uuid4()), "text": "hello",
        })
        turn_id = uuid.UUID(response.json()["turn_id"])
        status = client.get(f"/v1/turns/{turn_id}/events", headers=_headers())
        assert status.status_code == 200
        store = components.value.store
        aggregate = store.get_turn(OWNER_A, turn_id)
        store.save_checkpoint(OWNER_A, turn_id, expected_state_revision=aggregate.record.turn.state_revision,
            expected_checkpoint_revision=aggregate.checkpoint_revision, checkpoint=aggregate.checkpoint,
            events=[EventDraft(type=EventType.ERROR, occurred_at=NOW, simulation=False,
                payload=ErrorEventPayload(code=ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                    message="A dependency is unavailable.", retryable=True))])
        _assert_typed_error(client.get(f"/v1/turns/{turn_id}/events", headers=_headers()), 503)
    finally:
        client.__exit__(None, None, None)


def test_store_calls_run_off_event_loop_and_health_live_survives_database_lock(tmp_path: Path) -> None:
    client, components = _client(tmp_path)
    lock = sqlite3.connect(components.value.store._path, timeout=1)
    lock.execute("BEGIN IMMEDIATE")
    try:
        body = {"api_version": "1.0.0", "client_request_id": str(uuid.uuid4()), "title": "locked"}
        with ThreadPoolExecutor(max_workers=1) as pool:
            blocked = pool.submit(client.post, "/v1/sessions", headers=_headers(), json=body)
            time.sleep(0.2)
            started = time.monotonic()
            live = client.get("/health/live")
            elapsed = time.monotonic() - started
            assert live.status_code == 200
            assert elapsed < 0.5
            assert blocked.result(timeout=4).status_code == 503
    finally:
        lock.execute("ROLLBACK")
        lock.close()
        client.__exit__(None, None, None)


def test_auth_required_and_actor_rate_limits_have_typed_responses(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, limit=1)
    try:
        assert client.get("/v1/sessions", headers=_headers()).status_code == 200
        _assert_typed_error(client.get("/v1/sessions", headers=_headers()), 429)
        assert client.get("/health/live").status_code == 200
    finally:
        client.__exit__(None, None, None)


def test_auth_resume_restores_planning_confirmation_and_same_execution_checkpoint(tmp_path: Path) -> None:
    client, components = _client(tmp_path)
    try:
        session_id = _create_session(client)
        store = components.value.store

        # Saved RUNNING checkpoint: accepted resume returns to the exact saved state.
        _, planning_turn = persistence._submit(store, session_id, OWNER_A)
        planning_pause = _pause_for_auth(store, planning_turn, persistence.c.ResumeState.RUNNING)
        planning = store.get_turn(OWNER_A, planning_turn)
        planned_checkpoint = type(planning.checkpoint).model_validate(
            planning.checkpoint.model_dump(mode="python", by_alias=True, exclude_none=False)
            | {"model_calls": 3, "read_calls": 2, "repair_calls": 1}
        )
        store.save_checkpoint(OWNER_A, planning_turn, expected_state_revision=planning_pause.state_revision,
            expected_checkpoint_revision=planning.checkpoint_revision, checkpoint=planned_checkpoint)
        request = ResumeAuthRequest(client_request_id=uuid.uuid4(), expected_state_revision=planning_pause.state_revision)
        wire = request.model_dump(mode="json")
        resumed = client.post(f"/v1/turns/{planning_turn}/resume/auth", headers=_headers(), json=wire)
        assert resumed.status_code == 202
        assert resumed.json()["state"] == "RUNNING"
        assert resumed.json()["event_cursor"] == store.read_turn_view(OWNER_A, planning_turn).event_cursor
        after = store.get_turn(OWNER_A, planning_turn)
        assert (after.checkpoint.model_calls, after.checkpoint.read_calls, after.checkpoint.repair_calls) == (3, 2, 1)
        components.control.enabled = False
        assert client.post(f"/v1/turns/{planning_turn}/resume/auth", headers=_headers(), json=wire).json() == resumed.json()

        # The QUEUED checkpoint remains distinct from RUNNING after auth refresh.
        components.control.enabled = True
        _, queued_turn = persistence._submit(store, session_id, OWNER_A)
        queued_pause = _pause_for_auth(store, queued_turn, persistence.c.ResumeState.QUEUED)
        queued_request = ResumeAuthRequest(client_request_id=uuid.uuid4(), expected_state_revision=queued_pause.state_revision)
        queued = client.post(f"/v1/turns/{queued_turn}/resume/auth", headers=_headers(), json=queued_request.model_dump(mode="json"))
        assert queued.status_code == 202
        assert queued.json()["state"] == "QUEUED"

        # WAIT_CONFIRM is restored with the same proposal revision and nonce.
        confirmation_session = _create_session(client)
        _, confirmation_turn = persistence._submit(store, confirmation_session, OWNER_A)
        proposal = persistence._proposal(OWNER_A, confirmation_session, confirmation_turn, backend=True)
        waiting = persistence._wait_with_proposal(store, OWNER_A, confirmation_turn, proposal)
        paused = _pause_for_auth(store, confirmation_turn, persistence.c.ResumeState.WAIT_CONFIRM)
        components.control.enabled = True
        request = ResumeAuthRequest(client_request_id=uuid.uuid4(), expected_state_revision=paused.state_revision)
        resumed = client.post(f"/v1/turns/{confirmation_turn}/resume/auth", headers=_headers(), json=request.model_dump(mode="json"))
        assert resumed.status_code == 202
        assert resumed.json()["state"] == "WAIT_CONFIRM"
        assert resumed.json()["state_revision"] == paused.state_revision + 1
        assert store.get_proposal(OWNER_A, proposal.proposal_id).confirmation_nonce == proposal.confirmation_nonce
        assert store.get_turn(OWNER_A, confirmation_turn).record.turn.wait_reason == persistence.c.WaitReason.CONFIRM_REQUIRED

        # Assigned execution auth recovery keeps the identical key, unknown outcome,
        # checkpoint budget, and proposal receipt state. It never returns to planning.
        execution_session = _create_session(client)
        _, execution_turn = persistence._submit(store, execution_session, OWNER_A)
        proposal = persistence._proposal(OWNER_A, execution_session, execution_turn, backend=True)
        waiting = persistence._wait_with_proposal(store, OWNER_A, execution_turn, proposal)
        execution = persistence.c.ExecutionIdentity(execution_id=persistence.c.derive_execution_id(OWNER_A, proposal.proposal_id, proposal.revision),
            actor_id=OWNER_A, proposal_id=proposal.proposal_id, proposal_revision=proposal.revision)
        executing = persistence._snapshot(waiting, state=TurnState.EXECUTING, step=TurnStep.DISPATCH, execution=execution)
        confirmed_proposal = type(proposal).model_validate(proposal.model_dump(mode="python", by_alias=True, exclude_none=False) | {
            "status": persistence.c.ProposalStatus.CONFIRMED, "confirmation_nonce": None,
            "execution": execution.model_dump(mode="python", by_alias=True, exclude_none=False),
        })
        _transition(store, OWNER_A, executing, updated_proposal=confirmed_proposal, fixture_execution=True)
        recovering = persistence._snapshot(executing, state=TurnState.RECOVERING, step=TurnStep.RECONCILE,
            resolution=persistence.c.ExecutionResolution.UNKNOWN)
        _transition(store, OWNER_A, recovering)
        paused = _pause_for_auth(store, execution_turn, persistence.c.ResumeState.RECOVERING)
        before = store.get_turn(OWNER_A, execution_turn)
        checkpoint = type(before.checkpoint).model_validate(before.checkpoint.model_dump(mode="python", by_alias=True, exclude_none=False)
            | {"model_calls": 4, "read_calls": 3, "repair_calls": 1})
        store.save_checkpoint(OWNER_A, execution_turn, expected_state_revision=paused.state_revision,
            expected_checkpoint_revision=before.checkpoint_revision, checkpoint=checkpoint)
        request = ResumeAuthRequest(client_request_id=uuid.uuid4(), expected_state_revision=paused.state_revision)
        resumed = client.post(f"/v1/turns/{execution_turn}/resume/auth", headers=_headers(), json=request.model_dump(mode="json"))
        assert resumed.status_code == 202
        assert resumed.json()["state"] == "RECOVERING"
        after = store.get_turn(OWNER_A, execution_turn)
        assert after.record.turn.execution == execution
        assert after.record.turn.execution_resolution == persistence.c.ExecutionResolution.UNKNOWN
        assert (after.checkpoint.model_calls, after.checkpoint.read_calls, after.checkpoint.repair_calls) == (4, 3, 1)
    finally:
        client.__exit__(None, None, None)


def test_clarification_accepts_verbatim_input_replays_before_disable_and_rejects_changed_key(tmp_path: Path) -> None:
    client, components = _client(tmp_path)
    try:
        session_id = _create_session(client)
        store = components.value.store
        _, turn_id = persistence._submit(store, session_id, OWNER_A)
        running = persistence._snapshot(store.get_turn(OWNER_A, turn_id).record.turn,
            state=TurnState.RUNNING, step=TurnStep.MODEL_DECISION)
        _transition(store, OWNER_A, running)
        paused = persistence._snapshot(running, state=TurnState.WAIT_INPUT, step=TurnStep.AWAITING_USER,
            wait_reason=persistence.c.WaitReason.MISSING_FIELDS, resume_state=persistence.c.ResumeState.RUNNING)
        _transition(store, OWNER_A, paused)
        request = ResumeClarificationRequest(client_request_id=uuid.uuid4(),
            expected_state_revision=paused.state_revision, text="  12.50 CNY  ")
        wire = request.model_dump(mode="json")
        accepted = client.post(f"/v1/turns/{turn_id}/resume/clarification", headers=_headers(), json=wire)
        assert accepted.status_code == 202
        assert accepted.json()["state"] == "RUNNING"
        saved = store.get_turn(OWNER_A, turn_id)
        assert saved.checkpoint.accepted_inputs[-1].payload.text == "  12.50 CNY  "
        components.control.enabled = False
        assert client.post(f"/v1/turns/{turn_id}/resume/clarification", headers=_headers(), json=wire).json() == accepted.json()
        changed = dict(wire)
        changed["text"] = "13 CNY"
        _assert_typed_error(client.post(f"/v1/turns/{turn_id}/resume/clarification", headers=_headers(), json=changed), 409)
    finally:
        client.__exit__(None, None, None)


def test_cancel_is_durable_local_and_late_planning_output_loses_cas(tmp_path: Path) -> None:
    client, components = _client(tmp_path)
    try:
        session_id = _create_session(client)
        store = components.value.store
        _, turn_id = persistence._submit(store, session_id, OWNER_A)
        old = store.get_turn(OWNER_A, turn_id).record.turn
        request = {"client_request_id": str(uuid.uuid4()), "expected_state_revision": old.state_revision}
        cancelled = client.post(f"/v1/turns/{turn_id}/cancel", headers=_headers(), json=request)
        assert cancelled.status_code == 202
        assert cancelled.json()["result"] == "cancelled"
        assert cancelled.json()["turn"]["state"] == "CANCELLED"
        components.control.enabled = False
        assert client.post(f"/v1/turns/{turn_id}/cancel", headers=_headers(), json=request).json() == cancelled.json()
        late = persistence._snapshot(old, state=TurnState.RUNNING, step=TurnStep.MODEL_DECISION)
        with pytest.raises(persistence.StateConflict):
            _transition(store, OWNER_A, late)
    finally:
        client.__exit__(None, None, None)


def test_injected_adjust_preparer_rotates_nonce_and_confirm_gates_expiry_and_disable_revision(tmp_path: Path) -> None:
    client, components = _client(tmp_path)
    try:
        session_id = _create_session(client)
        store = components.value.store
        _, turn_id = persistence._submit(store, session_id, OWNER_A)
        proposal = persistence._proposal(OWNER_A, session_id, turn_id, backend=True)
        waiting = persistence._wait_with_proposal(store, OWNER_A, turn_id, proposal)
        adjust = ResumeProposalAdjustRequest(client_request_id=uuid.uuid4(),
            expected_state_revision=waiting.state_revision, expected_proposal_revision=proposal.revision,
            text="change title")
        accepted = client.post(f"/v1/turns/{turn_id}/resume/proposal-adjust", headers=_headers(), json=adjust.model_dump(mode="json"))
        assert accepted.status_code == 202
        assert accepted.json()["proposal_revision"] == proposal.revision + 1
        current = store.get_proposal(OWNER_A, proposal.proposal_id)
        assert current.confirmation_nonce == "Q" * 32
        assert components.preparer.calls == 1

        # An unavailable preparation capability cannot fabricate a replacement.
        current_turn = store.get_turn(OWNER_A, turn_id).record.turn
        unavailable_request = ResumeProposalAdjustRequest(client_request_id=uuid.uuid4(),
            expected_state_revision=current_turn.state_revision,
            expected_proposal_revision=current.revision, text="another change")
        components.preparer.available = False
        _assert_typed_error(client.post(f"/v1/turns/{turn_id}/resume/proposal-adjust", headers=_headers(),
            json=unavailable_request.model_dump(mode="json")), 503)
        assert store.get_proposal(OWNER_A, proposal.proposal_id).revision == current.revision
        components.preparer.available = True

        # Event polling keeps the frozen seq cursor and has_more semantics while
        # each page is read from one owner-scoped SQLite snapshot.
        first_page = client.get(f"/v1/turns/{turn_id}/events?limit=1", headers=_headers())
        assert first_page.status_code == 200
        assert first_page.json()["events"][0]["seq"] == 1
        assert first_page.json()["next_after_seq"] == 1
        assert first_page.json()["has_more"] is True
        second_page = client.get(f"/v1/turns/{turn_id}/events?after_seq=1&limit=1", headers=_headers())
        assert second_page.status_code == 200
        assert second_page.json()["events"][0]["seq"] == 2
        assert second_page.json()["next_after_seq"] == 2

        old_confirm = {"client_request_id": str(uuid.uuid4()), "expected_proposal_revision": proposal.revision,
            "command_digest": proposal.command_digest, "confirmation_nonce": proposal.confirmation_nonce}
        _assert_typed_error(client.post(f"/v1/proposals/{proposal.proposal_id}/confirm", headers=_headers("token-b"), json=old_confirm), 404)
        _assert_typed_error(client.post(f"/v1/proposals/{proposal.proposal_id}/confirm", headers=_headers(), json=old_confirm), 409)

        new_confirm = {"client_request_id": str(uuid.uuid4()), "expected_proposal_revision": current.revision,
            "command_digest": current.command_digest, "confirmation_nonce": current.confirmation_nonce}
        components.control.revision = 1
        stale = client.post(f"/v1/proposals/{proposal.proposal_id}/confirm", headers=_headers(), json=new_confirm)
        assert _assert_typed_error(stale, 409)["code"] == "agent_disabled"
        # Reopening preserves the incremented revision, so the old proposal
        # remains stale after a close/reopen cycle.
        components.control.enabled = False
        components.control.enabled = True
        reopened = client.post(f"/v1/proposals/{proposal.proposal_id}/confirm", headers=_headers(), json=new_confirm)
        assert _assert_typed_error(reopened, 409)["code"] == "agent_disabled"

        # A proposal prepared against the current server revision may reach the
        # phase's durable 501 receipt; no caller-supplied revision is trusted.
        fresh_session = _create_session(client)
        _, fresh_turn = persistence._submit(store, fresh_session, OWNER_A)
        fresh_proposal = _with_disable_revision(
            persistence._proposal(OWNER_A, fresh_session, fresh_turn, backend=True), 1,
        )
        persistence._wait_with_proposal(store, OWNER_A, fresh_turn, fresh_proposal)
        fresh_confirm = {"client_request_id": str(uuid.uuid4()),
            "expected_proposal_revision": fresh_proposal.revision,
            "command_digest": fresh_proposal.command_digest,
            "confirmation_nonce": fresh_proposal.confirmation_nonce}
        unavailable = client.post(f"/v1/proposals/{fresh_proposal.proposal_id}/confirm", headers=_headers(), json=fresh_confirm)
        assert unavailable.status_code == 501
        assert unavailable.json()["execution_enabled"] is False
        confirm_receipt = store.get_proposal(OWNER_A, fresh_proposal.proposal_id).request_receipts[0]
        assert fresh_confirm["confirmation_nonce"] not in confirm_receipt.model_dump_json()
        assert fresh_confirm["confirmation_nonce"] not in store.get_turn(OWNER_A, fresh_turn).checkpoint.model_dump_json()

        # An expired, otherwise correctly bound proposal cannot create a 501 receipt.
        expired_session = _create_session(client)
        _, expired_turn = persistence._submit(store, expired_session, OWNER_A)
        expired = persistence._proposal(OWNER_A, expired_session, expired_turn, backend=True)
        expired = _with_disable_revision(expired, 1)
        expired = type(expired).model_validate(expired.model_dump(mode="python", by_alias=True, exclude_none=False) | {
            "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
        })
        persistence._wait_with_proposal(store, OWNER_A, expired_turn, expired)
        expired_body = {"client_request_id": str(uuid.uuid4()), "expected_proposal_revision": expired.revision,
            "command_digest": expired.command_digest, "confirmation_nonce": expired.confirmation_nonce}
        assert _assert_typed_error(client.post(f"/v1/proposals/{expired.proposal_id}/confirm", headers=_headers(), json=expired_body), 409)["code"] == "proposal_expired"
    finally:
        client.__exit__(None, None, None)
