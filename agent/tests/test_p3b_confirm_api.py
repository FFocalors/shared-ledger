from __future__ import annotations

"""P3b HTTP surface: the approved 202 confirmation response.

The engine is P3a (Mock ledger); this file pins the routing contract only:
202 on a real dispatch, idempotent replay, no effect before confirmation, the
frozen 501 as a rollback switch, and an unknown outcome that is never reported
as success.
"""

import uuid
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from agent.app import contracts as c, mock_fixtures
from agent.app.backend import MockBackendAdapter
from agent.app.components import AppComponents
from agent.app.gateway import UnimplementedGateway
from agent.app.harness import MockModelProvider
from agent.app.runtime import UnimplementedRuntime
from agent.app.settings import Settings
from agent.app.store import SQLiteAgentStore
from test_mock_runtime_api import _Control, _DIFakeAuth, _Scope
from test_sqlite_persistence import _proposal, _session, _submit, _wait_with_proposal

OWNER_A = uuid.UUID("11111111-1111-4111-8111-111111111111")


@contextmanager
def _client(database: Path, *, execution_enabled: bool):
    auth = _DIFakeAuth()
    control = _Control()
    scope = _Scope()
    store = SQLiteAgentStore(database, admission_enabled=True)
    provider = MockModelProvider()
    backend = MockBackendAdapter()
    # The confirm route needs the store only; an idle runtime keeps the scheduler
    # from claiming the Turn while the fixture is being prepared.
    runtime = UnimplementedRuntime()
    components = AppComponents(
        store=store, provider=provider, backend=backend, runtime=runtime,
        gateway=UnimplementedGateway(), auth_verifier=auth, scope_authorizer=scope,
        agent_control=control, execution_enabled=execution_enabled,
    )
    settings = Settings(
        storage_path=database, provider_mode="mock", agent_enabled=True,
        execution_enabled=execution_enabled, disable_revision=0,
        api_requests_per_minute=500, mock_model_timeout_seconds=1,
    )
    from agent.app.main import create_app
    app = create_app(settings, components_factory=lambda _: components)
    with TestClient(app) as client:
        yield client, components


def _waiting_backend_proposal(components: AppComponents) -> tuple[uuid.UUID, c.ProposalRecord]:
    store = components.store
    session_id = _session(store, OWNER_A)
    _, turn_id = _submit(store, session_id, OWNER_A)
    proposal = _proposal(OWNER_A, session_id, turn_id, backend=True)
    _wait_with_proposal(store, OWNER_A, turn_id, proposal)
    return turn_id, proposal


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


def test_confirm_returns_202_and_settles_the_execution(tmp_path) -> None:
    with _client(tmp_path / "confirm.sqlite3", execution_enabled=True) as (client, components):
        store = components.store
        turn_id, proposal = _waiting_backend_proposal(components)
        request_id = uuid.uuid4()

        response = _post(client, proposal, _body(proposal, request_id=request_id))

        assert response.status_code == 202, response.text
        body = response.json()
        expected_id = c.derive_execution_id(OWNER_A, proposal.proposal_id, proposal.revision)
        assert body["api_version"] == "1.0.0"
        assert body["turn"]["state"] == "COMPLETED"
        assert body["turn"]["execution_assigned"] is True
        assert body["turn"]["execution_resolution"] == "succeeded"
        assert body["execution"]["execution_id"] == str(expected_id)
        assert body["execution"]["proposal_id"] == str(proposal.proposal_id)
        assert body["execution"]["proposal_revision"] == proposal.revision
        assert body["event_cursor"] >= 1

        assert store.count_mock_executions(proposal.proposal_id) == 1
        assert store.mock_ledger_financial_version(mock_fixtures.ACTIVITY_ID) == 1
        stored = store.get_proposal(OWNER_A, proposal.proposal_id)
        receipt = next(
            item for item in stored.request_receipts
            if item.client_request_id == request_id
        )
        assert receipt.response_kind is c.RequestReceiptKind.EXECUTION_DISPATCHED
        assert receipt.http_status == 202
        assert stored.status is c.ProposalStatus.CONFIRMED
        assert store.get_turn(OWNER_A, turn_id).record.turn.state is c.TurnState.COMPLETED


def test_repeated_confirmation_replays_the_same_202(tmp_path) -> None:
    with _client(tmp_path / "replay.sqlite3", execution_enabled=True) as (client, components):
        store = components.store
        _, proposal = _waiting_backend_proposal(components)
        body = _body(proposal)

        first = _post(client, proposal, body)
        second = _post(client, proposal, body)

        assert first.status_code == 202, first.text
        assert second.status_code == 202, second.text
        assert second.json() == first.json()
        assert store.count_mock_executions(proposal.proposal_id) == 1


def test_confirm_after_dispatch_returns_the_same_execution(tmp_path) -> None:
    with _client(tmp_path / "after-dispatch.sqlite3", execution_enabled=True) as (client, components):
        store = components.store
        _, proposal = _waiting_backend_proposal(components)

        first = _post(client, proposal, _body(proposal))
        second = _post(client, proposal, _body(proposal))

        assert first.status_code == 202, first.text
        assert second.status_code == 202, second.text
        assert second.json()["execution"] == first.json()["execution"]
        assert second.json()["turn"]["state"] == "COMPLETED"
        assert store.count_mock_executions(proposal.proposal_id) == 1


def test_unconfirmed_proposal_posts_no_effect(tmp_path) -> None:
    with _client(tmp_path / "unconfirmed.sqlite3", execution_enabled=True) as (client, components):
        store = components.store
        _, proposal = _waiting_backend_proposal(components)

        assert store.count_mock_executions(proposal.proposal_id) == 0
        body = _body(proposal)
        body["confirmation_nonce"] = "X" * 32  # the caller did not present the preview nonce
        rejected = _post(client, proposal, body)

        assert rejected.status_code == 409, rejected.text
        assert store.count_mock_executions(proposal.proposal_id) == 0
        assert store.mock_ledger_financial_version(mock_fixtures.ACTIVITY_ID) == 0
        assert store.get_proposal(OWNER_A, proposal.proposal_id).status is c.ProposalStatus.PENDING


def test_execution_flag_off_keeps_the_frozen_501(tmp_path) -> None:
    with _client(tmp_path / "rollback.sqlite3", execution_enabled=False) as (client, components):
        store = components.store
        _, proposal = _waiting_backend_proposal(components)

        response = _post(client, proposal, _body(proposal))

        assert response.status_code == 501, response.text
        body = response.json()
        assert body["code"] == "execution_capability_unavailable"
        assert body["execution_enabled"] is False
        assert body["business_write_performed"] is False
        assert store.count_mock_executions(proposal.proposal_id) == 0
        assert store.get_proposal(OWNER_A, proposal.proposal_id).status is c.ProposalStatus.PENDING


def test_unknown_outcome_is_never_reported_as_success(tmp_path) -> None:
    with _client(tmp_path / "unknown.sqlite3", execution_enabled=True) as (client, components):
        store = components.store
        turn_id, proposal = _waiting_backend_proposal(components)
        original_apply = store.apply_mock_execution

        def explode(*_args, **_kwargs):
            raise RuntimeError("simulated crash after dispatch")

        store.apply_mock_execution = explode
        try:
            response = _post(client, proposal, _body(proposal))
        finally:
            store.apply_mock_execution = original_apply

        assert response.status_code == 202, response.text
        body = response.json()
        # Accepted, but explicitly not successful: the Turn is parked for reconciliation.
        assert body["turn"]["state"] == "RECOVERING"
        assert body["turn"]["execution_resolution"] == "unknown"
        assert body["turn"]["execution_assigned"] is True
        assert store.count_mock_executions(proposal.proposal_id) == 0
        execution_id = body["execution"]["execution_id"]

        settled = store.reconcile_mock_execution(OWNER_A, turn_id)
        assert settled.record.turn.state is c.TurnState.COMPLETED
        assert settled.record.turn.execution_resolution is c.ExecutionResolution.SUCCEEDED
        assert str(settled.record.turn.execution.execution_id) == execution_id
        assert store.count_mock_executions(proposal.proposal_id) == 1
        assert store.mock_ledger_financial_version(mock_fixtures.ACTIVITY_ID) == 1
