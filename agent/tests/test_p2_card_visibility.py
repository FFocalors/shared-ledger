"""P2-mode proposal cards use the same scope decision as the Turn endpoints.

P2 installs a fail-closed `scope_authorizer` because the authoritative check is
`backend.authorize_api_scope` with the caller's own access token. Card
visibility must therefore follow that same decision: a passing check shows the
card, and a denied or unavailable check still withholds it (fail-closed).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app import contracts as c
from app.components import AppComponents, _FailClosedScopeAuthorizer
from app.p2_backend import BackendReadError
from app.p2_journal import P2ErrorProofJournal
from app.p2_runtime import P2Runtime
from app.p5_write import LiveExpenseGateway, LiveWriteConfig
from app.settings import Settings
from app.store import SQLiteAgentStore
from test_p2_runtime import (
    OWNER, TOKEN,
    _Auth, _Backend, _Control, _Provider,
    _auth, _create_session, _events, _submit, _wait,
)
from test_p5_dev_bridge import _Transport


def _build_client(database: Path) -> tuple[TestClient, AppComponents, _Backend]:
    store = SQLiteAgentStore(database, admission_enabled=True)
    provider = _Provider()
    backend = _Backend()
    auth = _Auth()
    transport = _Transport()
    gateway = LiveExpenseGateway(
        LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="test-key"),
        store, backend, transport,
    )
    runtime = P2Runtime(
        store, provider, backend, auth, _Control(),
        P2ErrorProofJournal(database.with_suffix(".journal.sqlite3")),
        model_timeout_seconds=2,
        live_gateway=gateway,
        p5_dev_intent_enabled=True,
    )
    components = AppComponents(
        store=store, provider=provider, backend=backend, runtime=runtime,
        gateway=object(), auth_verifier=auth,
        # Production P2 wiring: the business permission check lives on the
        # backend, so this adapter refuses every Activity scope.
        scope_authorizer=_FailClosedScopeAuthorizer(),
        agent_control=_Control(), execution_enabled=True, live_gateway=gateway,
    )
    settings = Settings(
        storage_path=database, provider_mode="mock", agent_enabled=True,
        execution_enabled=True, disable_revision=0, api_requests_per_minute=500,
    )
    from app.main import create_app

    app = create_app(settings, components_factory=lambda _: components)
    return TestClient(app), components, backend


def _open_card_turn(
    client: TestClient, components: AppComponents,
) -> tuple[uuid.UUID, uuid.UUID, c.ProposalRecord]:
    session_id = _create_session(client)
    turn_id = _submit(client, session_id, "记账 午餐 5.00", scoped=True)
    _wait(components, turn_id, {c.TurnState.WAIT_CONFIRM})
    details = components.store.get_session_detail(OWNER, session_id)
    proposal = next(item for item in details.proposals if item.status is c.ProposalStatus.PENDING)
    return session_id, turn_id, proposal


def _card_ids(body: dict[str, Any]) -> list[str]:
    return [card["proposal_id"] for card in body["proposal_cards"]]


def test_p2_mode_shows_the_card_when_the_backend_scope_check_passes(tmp_path: Path) -> None:
    client, components, backend = _build_client(tmp_path / "p2-card-visible.sqlite3")
    with client:
        session_id, turn_id, proposal = _open_card_turn(client, components)

        detail = client.get(f"/v1/sessions/{session_id}", headers=_auth())
        assert detail.status_code == 200, detail.text
        assert _card_ids(detail.json()) == [str(proposal.proposal_id)]

        polled = _events(client, turn_id)
        assert _card_ids(polled) == [str(proposal.proposal_id)]

        # The decision came from the backend with the caller's own token, not
        # from the fail-closed adapter that is still installed above.
        assert backend.scope_tokens
        assert set(backend.scope_tokens) == {TOKEN}


def test_p2_mode_hides_the_card_when_the_backend_scope_check_denies(tmp_path: Path) -> None:
    client, components, backend = _build_client(tmp_path / "p2-card-denied.sqlite3")
    with client:
        session_id, _, proposal = _open_card_turn(client, components)

        async def deny(*args: object, **kwargs: object) -> None:
            raise BackendReadError("access_denied")

        backend.authorize_api_scope = deny
        detail = client.get(f"/v1/sessions/{session_id}", headers=_auth())
        assert detail.status_code == 200, detail.text
        assert detail.json()["proposal_cards"] == []
        # Only disclosure is withheld; the proposal itself is still persisted.
        details = components.store.get_session_detail(OWNER, session_id)
        assert next(
            item for item in details.proposals if item.proposal_id == proposal.proposal_id
        ).status is c.ProposalStatus.PENDING


def test_p2_mode_hides_the_card_when_the_backend_scope_check_is_unavailable(tmp_path: Path) -> None:
    client, components, backend = _build_client(tmp_path / "p2-card-unavailable.sqlite3")
    with client:
        session_id, _, proposal = _open_card_turn(client, components)
        original_check = backend.authorize_api_scope

        async def unavailable(*args: object, **kwargs: object) -> None:
            raise BackendReadError("scope_unavailable")

        async def broken(*args: object, **kwargs: object) -> None:
            raise RuntimeError("simulated transport failure")

        for check in (unavailable, broken):
            backend.authorize_api_scope = check
            detail = client.get(f"/v1/sessions/{session_id}", headers=_auth())
            assert detail.status_code == 200, detail.text
            assert detail.json()["proposal_cards"] == []

        # Still fail-closed, not sticky: a usable check restores disclosure.
        backend.authorize_api_scope = original_check
        detail = client.get(f"/v1/sessions/{session_id}", headers=_auth())
        assert detail.status_code == 200, detail.text
        assert _card_ids(detail.json()) == [str(proposal.proposal_id)]
