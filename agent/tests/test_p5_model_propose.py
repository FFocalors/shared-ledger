from __future__ import annotations

"""Phase 1: natural-language 记账/改账 through the model proposal path.

Tester's eight cases (four bars x create/update):
1. NL only yields a confirmable draft; nothing is written yet.
2. After confirm, exactly one write; amounts come from the server command.
3. Unconfirmed or cancelled means no write (the original stays unchanged).
4. Failures are stated plainly and never look like success.

The dev command bridge is OFF here, so every proposal comes from the model.
"""

import json
import uuid
from typing import Any

from app import contracts as c
from app.components import AppComponents
from app.p2_journal import P2ErrorProofJournal
from app.p2_runtime import P2Runtime
from app.p5_write import LiveExpenseGateway, LiveWriteConfig
from app.settings import Settings
from app.store import SQLiteAgentStore
from test_p2_runtime import (
    OWNER, PAYER, PARTICIPANT_2, UNIT, ACTIVITY,
    _Auth, _Backend, _Control, _auth, _create_session, _events, _submit, _wait,
)
from test_p5_dev_bridge import _Transport, _confirm


CREATE_TEXT = "帮我记一笔午餐 5 块"
CREATE_FX_TEXT = "帮我记一笔午餐 5 欧元"
UPDATE_TEXT = "把那笔午餐改成 15 块"
EXPENSE_ID = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")


class _NLProvider:
    """A model stand-in that answers natural language with propose decisions."""

    def __init__(self) -> None:
        self.prompts: list[Any] = []

    def start(self) -> None:
        pass

    def close(self) -> None:
        pass

    def health(self):  # noqa: ANN201
        from test_p2_runtime import _Provider
        return _Provider().health()

    async def generate(self, prompt: Any) -> str:
        self.prompts.append(prompt)
        context = prompt.context
        refs = context.bound_references
        unit_ref = next((i.ref.value for i in refs if i.kind == "ledger_unit"), None)
        payer_ref = next((i.ref.value for i in refs if i.kind == "participant"), None)
        if context.input_text in (CREATE_TEXT, CREATE_FX_TEXT):
            currency = "EUR" if context.input_text == CREATE_FX_TEXT else "USD"
            return json.dumps({
                "kind": "propose", "operation": "expense.create",
                "fields": {
                    "kind": "expense.create", "ledger_unit_ref": unit_ref,
                    "title": "午餐", "original_amount": "5.00", "original_currency": currency,
                    "payment_allocations": [{"participant_ref": payer_ref, "amount": "5.00"}],
                    "split": {"mode": "equal", "participant_refs": [payer_ref]},
                },
            })
        if context.input_text == UPDATE_TEXT:
            if not context.read_results:
                return json.dumps({
                    "kind": "read", "operation": "read.expenses",
                    "criteria": {"kind": "expenses", "activity_ref": context.verified_scope.activity_ref.value},
                })
            expense_ref = next(i.ref.value for i in refs if i.kind == "expense")
            return json.dumps({
                "kind": "propose", "operation": "expense.update",
                "fields": {
                    "kind": "expense.update", "expense_ref": expense_ref,
                    "original_amount": "15.00",
                    "payment_allocations": [{"participant_ref": payer_ref, "amount": "15.00"}],
                },
            })
        raise AssertionError(f"unexpected input {context.input_text!r}")


def _client(database, transport: _Transport):  # noqa: ANN001, ANN202
    store = SQLiteAgentStore(database, admission_enabled=True)
    provider = _NLProvider()
    backend = _Backend()
    auth = _Auth()
    gateway = LiveExpenseGateway(
        LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="test-key"),
        store, backend, transport,
    )
    runtime = P2Runtime(
        store, provider, backend, auth, _Control(),
        P2ErrorProofJournal(database.with_suffix(".journal.sqlite3")),
        model_timeout_seconds=2, live_gateway=gateway, p5_dev_intent_enabled=False,
    )
    components = AppComponents(
        store=store, provider=provider, backend=backend, runtime=runtime,
        gateway=object(), auth_verifier=auth, scope_authorizer=None, agent_control=_Control(),
        execution_enabled=True, live_gateway=gateway,
    )
    settings = Settings(
        storage_path=database, provider_mode="mock", agent_enabled=True,
        execution_enabled=True, disable_revision=0, api_requests_per_minute=500,
    )
    from fastapi.testclient import TestClient
    from app.main import create_app

    return TestClient(create_app(settings, components_factory=lambda _: components)), components, provider


def _update_transport() -> _Transport:
    transport = _Transport()
    transport.expense_id = EXPENSE_ID
    transport.expense["id"] = str(EXPENSE_ID)
    return transport


def _pending(components, session):  # noqa: ANN001, ANN202
    details = components.store.get_session_detail(OWNER, session)
    return [p for p in details.proposals if p.status is c.ProposalStatus.PENDING]


def _messages(client, turn_id) -> list[str]:  # noqa: ANN001
    return [
        e["payload"]["text"] for e in _events(client, turn_id)["events"]
        if e.get("type") == "message"
    ]


def _writes(transport: _Transport) -> list[dict]:
    return [call for call in transport.calls if "/rest/v1/rpc/" in call["url"]]


def _assert_not_success(texts: list[str]) -> None:
    joined = "".join(texts)
    for word in ("成功", "已记账", "已记录", "已修改", "已改"):
        assert word not in joined, joined


def _cancel(client, components, turn_id):  # noqa: ANN001, ANN202
    turn = components.store.get_turn(OWNER, turn_id).record.turn
    return client.post(f"/v1/turns/{turn_id}/cancel", headers=_auth(), json={
        "client_request_id": str(uuid.uuid4()), "expected_state_revision": turn.state_revision,
    })


# ---- 记账 ---------------------------------------------------------------

def test_create_1_nl_only_produces_a_confirmable_draft(tmp_path) -> None:
    transport = _Transport()
    client, components, provider = _client(tmp_path / "c1.sqlite3", transport)
    with client:
        session = _create_session(client)
        turn_id = _submit(client, session, CREATE_TEXT, scoped=True)
        _wait(components, turn_id, {c.TurnState.WAIT_CONFIRM})

        assert provider.prompts, "the proposal must come from the model path"
        [proposal] = _pending(components, session)
        assert proposal.operation == "expense.create"
        assert proposal.policy_version == "p5-model-expense-create-v1"
        assert proposal.preview is not None
        assert "【P5" not in proposal.preview.summary
        assert proposal.confirmation_nonce and proposal.command_digest
        assert _writes(transport) == []


def test_create_2_confirm_writes_exactly_once_with_server_amounts(tmp_path) -> None:
    transport = _Transport()
    client, components, _ = _client(tmp_path / "c2.sqlite3", transport)
    with client:
        session = _create_session(client)
        turn_id = _submit(client, session, CREATE_TEXT, scoped=True)
        _wait(components, turn_id, {c.TurnState.WAIT_CONFIRM})
        [proposal] = _pending(components, session)
        body = {
            "client_request_id": str(uuid.uuid4()),
            "expected_proposal_revision": proposal.revision,
            "command_digest": proposal.command_digest,
            "confirmation_nonce": proposal.confirmation_nonce,
        }
        first = client.post(f"/v1/proposals/{proposal.proposal_id}/confirm", headers=_auth(), json=body)
        replay = client.post(f"/v1/proposals/{proposal.proposal_id}/confirm", headers=_auth(), json=body)

        assert first.status_code == 202, first.text
        assert first.json()["turn"]["execution_resolution"] == "succeeded"
        assert replay.status_code == 202, replay.text
        writes = _writes(transport)
        assert len(writes) == 1
        payload = writes[0]["payload"]
        command = proposal.canonical_command
        assert payload["ledger_unit_id"] == str(UNIT) == str(command.ledger_unit_id)
        assert payload["original_amount"] == command.original_amount == "5.00"
        assert payload["original_currency"] == "USD"  # the server's base currency
        assert payload["payments"] == [{"participant_id": str(PAYER), "amount": "5.00"}]
        assert components.store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.COMPLETED


def test_create_3_unconfirmed_or_cancelled_never_writes(tmp_path) -> None:
    transport = _Transport()
    client, components, _ = _client(tmp_path / "c3.sqlite3", transport)
    with client:
        session = _create_session(client)
        turn_id = _submit(client, session, CREATE_TEXT, scoped=True)
        _wait(components, turn_id, {c.TurnState.WAIT_CONFIRM})
        [proposal] = _pending(components, session)
        assert _writes(transport) == []  # unconfirmed

        cancelled = _cancel(client, components, turn_id)
        assert cancelled.status_code == 202, cancelled.text
        assert cancelled.json()["turn"]["state"] == "CANCELLED"
        assert _pending(components, session) == []
        late = _confirm(client, proposal)
        assert late.status_code != 202
        assert _writes(transport) == []


def test_create_4_failure_is_explicit_and_not_success(tmp_path) -> None:
    transport = _Transport()
    client, components, _ = _client(tmp_path / "c4.sqlite3", transport)
    with client:
        session = _create_session(client)
        turn_id = _submit(client, session, CREATE_FX_TEXT, scoped=True)
        _wait(components, turn_id, {c.TurnState.COMPLETED})

        assert _pending(components, session) == []
        assert _writes(transport) == []
        texts = _messages(client, turn_id)
        assert any("没有记上" in t for t in texts), texts
        _assert_not_success(texts)


# ---- 改账 ---------------------------------------------------------------

def test_update_1_nl_only_produces_a_confirmable_draft(tmp_path) -> None:
    transport = _update_transport()
    client, components, provider = _client(tmp_path / "u1.sqlite3", transport)
    with client:
        session = _create_session(client)
        turn_id = _submit(client, session, UPDATE_TEXT, scoped=True)
        _wait(components, turn_id, {c.TurnState.WAIT_CONFIRM})

        assert len(provider.prompts) >= 2, "read first, then propose"
        [proposal] = _pending(components, session)
        assert proposal.operation == "expense.update"
        assert proposal.policy_version == "p5-model-expense-update-v1"
        assert proposal.preview is not None
        assert "【P5" not in proposal.preview.summary
        assert isinstance(proposal.canonical_command, c.FixedExpenseUpdateCommand)
        assert proposal.canonical_command.expense_id == EXPENSE_ID
        assert _writes(transport) == []


def test_update_2_confirm_writes_exactly_once_with_server_amounts(tmp_path) -> None:
    transport = _update_transport()
    client, components, _ = _client(tmp_path / "u2.sqlite3", transport)
    with client:
        session = _create_session(client)
        turn_id = _submit(client, session, UPDATE_TEXT, scoped=True)
        _wait(components, turn_id, {c.TurnState.WAIT_CONFIRM})
        [proposal] = _pending(components, session)
        command = proposal.canonical_command
        assert command.expected_expense_version == "3"  # from the server read
        body = {
            "client_request_id": str(uuid.uuid4()),
            "expected_proposal_revision": proposal.revision,
            "command_digest": proposal.command_digest,
            "confirmation_nonce": proposal.confirmation_nonce,
        }
        first = client.post(f"/v1/proposals/{proposal.proposal_id}/confirm", headers=_auth(), json=body)
        replay = client.post(f"/v1/proposals/{proposal.proposal_id}/confirm", headers=_auth(), json=body)

        assert first.status_code == 202, first.text
        assert first.json()["turn"]["execution_resolution"] == "succeeded"
        assert replay.status_code == 202, replay.text
        writes = _writes(transport)
        assert len(writes) == 1
        assert writes[0]["url"].endswith("/rest/v1/rpc/update_expense_auto_rate")
        payload = writes[0]["payload"]
        assert payload["expense_id"] == str(EXPENSE_ID)
        assert payload["original_amount"] == command.patch.original_amount == "15.00"
        assert payload["original_currency"] == "USD"
        assert payload["payments"] == [{"participant_id": str(PAYER), "amount": "15.00"}]
        assert payload["aa_participant_ids"] == [str(PAYER), str(PARTICIPANT_2)]
        assert components.store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.COMPLETED


def test_update_3_unconfirmed_or_cancelled_leaves_the_original(tmp_path) -> None:
    transport = _update_transport()
    original = dict(transport.expense)
    client, components, _ = _client(tmp_path / "u3.sqlite3", transport)
    with client:
        session = _create_session(client)
        turn_id = _submit(client, session, UPDATE_TEXT, scoped=True)
        _wait(components, turn_id, {c.TurnState.WAIT_CONFIRM})
        [proposal] = _pending(components, session)
        assert _writes(transport) == []  # unconfirmed

        cancelled = _cancel(client, components, turn_id)
        assert cancelled.status_code == 202, cancelled.text
        assert cancelled.json()["turn"]["state"] == "CANCELLED"
        assert _pending(components, session) == []
        late = _confirm(client, proposal)
        assert late.status_code != 202
        assert _writes(transport) == []
        assert transport.expense == original


def test_update_4_failure_is_explicit_and_not_success(tmp_path) -> None:
    transport = _update_transport()
    transport.expense["financial_locked"] = True
    client, components, _ = _client(tmp_path / "u4.sqlite3", transport)
    with client:
        session = _create_session(client)
        turn_id = _submit(client, session, UPDATE_TEXT, scoped=True)
        _wait(components, turn_id, {c.TurnState.COMPLETED})

        assert _pending(components, session) == []
        assert _writes(transport) == []
        texts = _messages(client, turn_id)
        assert any("原记录没有改动" in t for t in texts), texts
        _assert_not_success(texts)
