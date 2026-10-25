from __future__ import annotations

"""P5.0 confirm route: unconfirmed, duplicate confirmation, concurrent change."""

import asyncio
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from agent.app import contracts as c
from agent.app.backend import MockBackendAdapter
from agent.app.components import AppComponents
from agent.app.gateway import UnimplementedGateway
from agent.app.harness import MockModelProvider
from agent.app.p5_write import LiveExpenseGateway, LiveWriteConfig
from agent.app.ports import Principal
from agent.app.runtime import UnimplementedRuntime
from agent.app.settings import Settings
from agent.app.store import SQLiteAgentStore


class _OwnerAuth:
    """Authenticate every token as the owner used by the fixtures."""

    configured = True

    def verify_bearer(self, token: str) -> Principal:
        return Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1))


class _AllowScope:
    """The Gateway's own authoritative read re-checks the real scope."""

    def authorize(self, principal: Principal, activity_ids: frozenset[uuid.UUID], *, action: str) -> None:
        return None

from test_mock_runtime_api import _Control, _DIFakeAuth, _Scope
from test_sqlite_persistence import OWNER, _session, _submit, _wait_with_proposal
from test_p5_live_write import (
    ACTIVITY, FakeReadBackend, FakeTransport, UNIT, P1, P2,
    _intent, _references,
)


@contextmanager
def _client(database: Path):
    store = SQLiteAgentStore(database, admission_enabled=True)
    read_backend = FakeReadBackend(version=5)
    transport = FakeTransport()
    gateway = LiveExpenseGateway(
        LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
        store, read_backend, transport,
    )

    components = AppComponents(
        store=store,
        provider=MockModelProvider(),
        backend=MockBackendAdapter(),
        runtime=UnimplementedRuntime(),
        gateway=UnimplementedGateway(),
        auth_verifier=_OwnerAuth(),
        scope_authorizer=_AllowScope(),
        agent_control=_Control(),
        execution_enabled=True,
        live_gateway=gateway,
    )
    settings = Settings(
        storage_path=database, provider_mode="mock", agent_enabled=True,
        execution_enabled=True, live_write_enabled=False, disable_revision=0,
        api_requests_per_minute=500, mock_model_timeout_seconds=1,
    )
    from agent.app.main import create_app

    app = create_app(settings, components_factory=lambda _: components)
    with TestClient(app) as client:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        proposal = asyncio.run(gateway.build_preview(
            owner_user_id=OWNER,
            session_id=session,
            turn_id=turn_id,
            intent=_intent(),
            bound_references=_references(turn_id),
            access_token="token-a",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            agent_disable_revision=0,
            now=datetime.now(timezone.utc),
        ))
        waiting = _wait_with_proposal(store, OWNER, turn_id, proposal)
        yield SimpleState(client, store, transport, read_backend, proposal, waiting, turn_id)


class SimpleState:
    def __init__(self, client, store, transport, read_backend, proposal, waiting, turn_id):
        self.client = client
        self.store = store
        self.transport = transport
        self.read_backend = read_backend
        self.proposal = proposal
        self.waiting = waiting
        self.turn_id = turn_id


def _body(proposal: c.ProposalRecord, *, request_id: uuid.UUID | None = None) -> dict:
    return {
        "client_request_id": str(request_id or uuid.uuid4()),
        "expected_proposal_revision": proposal.revision,
        "command_digest": proposal.command_digest,
        "confirmation_nonce": proposal.confirmation_nonce,
    }


def _post(client: TestClient, proposal: c.ProposalRecord, body: dict):
    return client.post(
        f"/v1/proposals/{proposal.proposal_id}/confirm",
        headers={"Authorization": "Bearer token-a"},
        json=body,
    )


def test_unconfirmed_live_preview_posts_no_rpc(tmp_path) -> None:
    with _client(tmp_path / "p5-api-unconfirmed.sqlite3") as state:
        assert state.transport.calls == []
        assert state.store.get_proposal(OWNER, state.proposal.proposal_id).status is c.ProposalStatus.PENDING


def test_repeated_live_confirmation_returns_the_same_202_and_one_rpc(tmp_path) -> None:
    with _client(tmp_path / "p5-api-duplicate.sqlite3") as state:
        body = _body(state.proposal)
        first = _post(state.client, state.proposal, body)
        second = _post(state.client, state.proposal, body)
        third = _post(state.client, state.proposal, _body(state.proposal))

        assert first.status_code == 202, first.text
        assert second.status_code == 202, second.text
        assert third.status_code == 202, third.text
        assert len(state.transport.calls) == 1
        assert second.json()["execution"]["execution_id"] == first.json()["execution"]["execution_id"]
        assert third.json()["execution"]["execution_id"] == first.json()["execution"]["execution_id"]


def test_confirmation_after_a_concurrent_financial_change_is_refused(tmp_path) -> None:
    with _client(tmp_path / "p5-api-concurrent.sqlite3") as state:
        state.read_backend.version = 6
        response = _post(state.client, state.proposal, _body(state.proposal))

        assert response.status_code == 409, response.text
        assert state.transport.calls == []
        assert state.store.get_proposal(OWNER, state.proposal.proposal_id).status is c.ProposalStatus.CLOSED
        turn = state.store.get_turn(OWNER, state.turn_id).record.turn
        assert turn.state is c.TurnState.CANCELLED
        assert turn.execution is None
