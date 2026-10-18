from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import contracts as c
from app.p2_backend import P2ResolvedScope
from app.p2_identity import P2GrantError
from app.p2_journal import P2ErrorProofJournal
from app.p2_runtime import P2Runtime
from app.ports import AgentControlSnapshot, Principal
from app.store import EventDraft, SQLiteAgentStore


OWNER = uuid.UUID("a1000000-0000-4000-8000-000000000001")
TOKEN = "verified-p2-test-token"


class _Auth:
    def verify_bearer(self, token: str) -> Principal:
        if token != TOKEN:
            raise ValueError("unexpected test token")
        return Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1))


class _Control:
    def snapshot(self) -> AgentControlSnapshot:
        return AgentControlSnapshot(enabled=True, disable_revision=0, source="test")


class _Backend:
    async def resolve_scope(self, verified: object, request: object) -> P2ResolvedScope:
        assert getattr(request, "mode", None) == "none"
        return P2ResolvedScope("none", None, (), (), (), datetime.now(timezone.utc))

    async def authorize_api_scope(self, *args: object) -> None:
        raise AssertionError("no activity scope is expected in these tests")

    async def verify_financial_versions(self, *args: object) -> None:
        return None

    async def read(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("a conversation-only Turn must not read business data")


class _FakeProvider:
    def __init__(self, *, blocked: bool = False, output: str | None = None) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.blocked = blocked
        self.calls = 0
        self.output = output or json.dumps({
            "kind": "answer", "basis": "conversation",
            "text": "hello", "citations": [],
        })

    def start(self) -> None:
        return None

    def close(self) -> None:
        return None

    def health(self) -> object:
        return type("Health", (), {"status": "ready", "inference_available": True})()

    async def generate(self, prompt: object) -> str:
        self.calls += 1
        self.entered.set()
        if self.blocked:
            await self.release.wait()
        return self.output


def _status(snapshot: c.TurnStateSnapshot) -> EventDraft:
    return EventDraft(
        type=c.EventType.STATUS, occurred_at=datetime.now(timezone.utc), simulation=False,
        payload=c.StatusEventPayload(
            state=snapshot.state, step=snapshot.step, state_revision=snapshot.state_revision,
            wait_reason=snapshot.wait_reason, resume_state=snapshot.resume_state,
        ),
    )


def _public(snapshot: c.TurnStateSnapshot) -> c.TurnPublicStatus:
    return c.TurnPublicStatus(
        turn_id=snapshot.turn_id, session_id=snapshot.session_id, state=snapshot.state,
        step=snapshot.step, wait_reason=snapshot.wait_reason, resume_state=snapshot.resume_state,
        state_revision=snapshot.state_revision, execution_assigned=snapshot.execution is not None,
        execution_resolution=snapshot.execution_resolution, context_version=snapshot.context_version,
    )


def _new_store_turn(tmp_path: Path, *, name: str) -> tuple[SQLiteAgentStore, uuid.UUID]:
    store = SQLiteAgentStore(tmp_path / f"{name}.sqlite3", admission_enabled=True)
    store.start()
    now = datetime.now(timezone.utc)
    ui = c.UIContext(page_type=c.PageType.HOME, captured_at=now, client_version="p2-security-test")
    session = store.create_session(
        OWNER,
        c.CreateSessionRequest(client_request_id=uuid.uuid4(), title="Test", ui_context=ui),
        now=now,
    ).response_snapshot.session.session_id
    receipt = store.submit_turn(
        OWNER, session,
        c.SubmitTurnRequest(client_request_id=uuid.uuid4(), text="hello", ui_context=ui),
        now=now,
    )
    return store, receipt.response_snapshot.turn_id


def _runtime(
    tmp_path: Path, store: SQLiteAgentStore, turn_id: uuid.UUID, provider: _FakeProvider,
) -> P2Runtime:
    runtime = P2Runtime(
        store, provider, _Backend(), _Auth(), _Control(),
        P2ErrorProofJournal(tmp_path / "proofs.sqlite3"),
        model_timeout_seconds=2.0, shutdown_timeout_seconds=0.5,
    )
    runtime.bind_turn_auth_grant(
        Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1)),
        turn_id, TOKEN,
    )
    return runtime


async def _wait_state(
    store: SQLiteAgentStore, turn_id: uuid.UUID, expected: c.TurnState,
) -> c.TurnAggregate:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        aggregate = await asyncio.to_thread(store.get_turn, OWNER, turn_id)
        if aggregate.record.turn.state == expected:
            return aggregate
        await asyncio.sleep(0.01)
    aggregate = await asyncio.to_thread(store.get_turn, OWNER, turn_id)
    pytest.fail(f"Turn did not reach {expected}: {aggregate.record.turn.state}")


def test_successful_terminal_turn_revokes_its_memory_only_bearer(tmp_path: Path) -> None:
    store, turn_id = _new_store_turn(tmp_path, name="terminal-grant")
    provider = _FakeProvider()
    runtime = _runtime(tmp_path, store, turn_id, provider)

    async def run() -> None:
        await runtime.start()
        try:
            final = await _wait_state(store, turn_id, c.TurnState.COMPLETED)
            assert final.checkpoint.model_calls == 1
            assert provider.calls == 1
            revoke_deadline = time.monotonic() + 1.0
            while time.monotonic() < revoke_deadline:
                try:
                    runtime._turn_grants.get(OWNER, turn_id)
                except P2GrantError:
                    break
                await asyncio.sleep(0.005)
            else:
                pytest.fail("terminal Turn bearer was not revoked by runtime finalization")
            runtime.bind_turn_auth_grant(
                Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1)),
                turn_id, TOKEN, replace=True,
            )
            with pytest.raises(P2GrantError):
                runtime._turn_grants.get(OWNER, turn_id)
        finally:
            await runtime.close()

    try:
        asyncio.run(run())
    finally:
        store.close()


def test_cancel_wins_over_a_late_provider_result_and_cas_persists_no_message(tmp_path: Path) -> None:
    store, turn_id = _new_store_turn(tmp_path, name="late-cancel")
    provider = _FakeProvider(blocked=True, output=json.dumps({
        "kind": "answer", "basis": "conversation",
        "text": "LATE_PRIVATE_PROVIDER_OUTPUT", "citations": [],
    }))
    runtime = _runtime(tmp_path, store, turn_id, provider)

    async def run() -> None:
        await runtime.start()
        try:
            await asyncio.wait_for(provider.entered.wait(), timeout=3)
            claimed = await asyncio.to_thread(store.get_turn, OWNER, turn_id)
            assert claimed.record.turn.state == c.TurnState.RUNNING
            assert claimed.checkpoint.model_calls == 1

            before = claimed.record.turn
            after = c.TurnStateSnapshot.model_validate(
                before.model_dump(mode="python", by_alias=True, exclude_none=False)
                | {
                    "state": c.TurnState.CANCELLED,
                    "step": c.TurnStep.TERMINAL,
                    "state_revision": before.state_revision + 1,
                    "wait_reason": None,
                    "resume_state": None,
                }
            )
            request = c.CancelTurnRequest(
                client_request_id=uuid.uuid4(), expected_state_revision=before.state_revision,
            )
            response = c.CancelTurnResponse(turn=_public(after), result="cancelled")
            await asyncio.to_thread(
                store.accept_turn_action, OWNER, turn_id, request, after, response,
                events=[_status(after)],
            )
            runtime.revoke_turn_auth_grant(OWNER, turn_id)
            provider.release.set()

            final = await _wait_state(store, turn_id, c.TurnState.CANCELLED)
            await asyncio.sleep(0.05)
            view = await asyncio.to_thread(store.read_turn_view, OWNER, turn_id)
            assert final.checkpoint.model_calls == 1
            assert all(event.event.type != c.EventType.MESSAGE for event in view.events)
            assert "LATE_PRIVATE_PROVIDER_OUTPUT" not in str(view.events)
        finally:
            provider.release.set()
            await runtime.close()

    try:
        asyncio.run(run())
    finally:
        store.close()


def test_auth_resume_preserves_durable_call_budget_within_generation(tmp_path: Path) -> None:
    store, turn_id = _new_store_turn(tmp_path, name="resume-budget")
    provider = _FakeProvider()
    aggregate = store.get_turn(OWNER, turn_id)
    charged_checkpoint = aggregate.checkpoint.model_copy(update={
        "model_calls": 6, "read_calls": 2, "resume_step": c.TurnStep.BUILD_CONTEXT,
    })
    aggregate = store.save_checkpoint(
        OWNER, turn_id, expected_state_revision=aggregate.record.turn.state_revision,
        expected_checkpoint_revision=aggregate.checkpoint_revision,
        checkpoint=charged_checkpoint,
    )

    before = aggregate.record.turn
    running = c.TurnStateSnapshot.model_validate(
        before.model_dump(mode="python", by_alias=True, exclude_none=False)
        | {
            "state": c.TurnState.RUNNING,
            "step": c.TurnStep.BUILD_CONTEXT,
            "state_revision": before.state_revision + 1,
            "wait_reason": None,
            "resume_state": None,
        }
    )
    aggregate = store.transition_turn(
        OWNER, running, expected_state_revision=before.state_revision,
        expected_checkpoint_revision=aggregate.checkpoint_revision,
        events=[_status(running)],
        checkpoint=aggregate.checkpoint.model_copy(update={"resume_step": c.TurnStep.BUILD_CONTEXT}),
    )

    before = aggregate.record.turn
    paused = c.TurnStateSnapshot.model_validate(
        before.model_dump(mode="python", by_alias=True, exclude_none=False)
        | {
            "state": c.TurnState.WAIT_INPUT,
            "step": c.TurnStep.AUTH_REQUIRED,
            "state_revision": before.state_revision + 1,
            "wait_reason": c.WaitReason.AUTH_REQUIRED,
            "resume_state": c.ResumeState.RUNNING,
        }
    )
    aggregate = store.transition_turn(
        OWNER, paused, expected_state_revision=before.state_revision,
        expected_checkpoint_revision=aggregate.checkpoint_revision,
        events=[_status(paused)],
        checkpoint=aggregate.checkpoint.model_copy(update={"resume_step": c.TurnStep.BUILD_CONTEXT}),
    )

    request = c.ResumeAuthRequest(
        client_request_id=uuid.uuid4(), expected_state_revision=paused.state_revision,
    )
    resumed = c.TurnStateSnapshot.model_validate(
        paused.model_dump(mode="python", by_alias=True, exclude_none=False)
        | {
            "state": c.TurnState.RUNNING,
            "step": c.TurnStep.BUILD_CONTEXT,
            "state_revision": paused.state_revision + 1,
            "wait_reason": None,
            "resume_state": None,
        }
    )
    receipt = store.accept_turn_action(
        OWNER, turn_id, request, resumed,
        c.TurnMutationAccepted(
            turn_id=turn_id, state=resumed.state, state_revision=resumed.state_revision,
            event_cursor=0,
        ),
        events=[_status(resumed)],
    )
    assert receipt.response_snapshot.state == c.TurnState.RUNNING
    runtime = _runtime(tmp_path, store, turn_id, provider)

    async def run() -> None:
        await runtime.start()
        try:
            failed = await _wait_state(store, turn_id, c.TurnState.FAILED)
            assert failed.checkpoint.generation == aggregate.checkpoint.generation
            assert failed.checkpoint.model_calls == 6
            assert failed.checkpoint.read_calls == 2
            assert provider.calls == 0
        finally:
            await runtime.close()

    try:
        asyncio.run(run())
    finally:
        store.close()

