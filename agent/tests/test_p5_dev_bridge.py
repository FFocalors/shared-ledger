from __future__ import annotations

"""P5.0 device bridge: documented `记账` command -> live preview -> real write.

The bridge is server-flagged and only used for physical-device acceptance. These
tests pin the parser and the full Turn path without calling a model.
"""

import json
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlsplit

from fastapi.testclient import TestClient

from app import contracts as c
from app.components import AppComponents
from app.p2_harness import P2ReferenceLabel
from app.p2_journal import P2ErrorProofJournal
from app.p2_runtime import P2Runtime
from app.p5_dev_intent import (
    parse_dev_expense_create, parse_dev_expense_update,
    parse_dev_presentation_command,
)
from app.p5_write import LiveExpenseGateway, LiveWriteConfig
from app.settings import Settings
from app.store import SQLiteAgentStore
from test_p2_runtime import (
    ACTIVITY, OWNER, PARTICIPANT_2, PAYER, TOKEN, UNIT,
    _Auth, _Backend, _Control, _Provider, _auth, _create_session, _events, _submit, _wait,
)


TURN = uuid.UUID("99999999-9999-4999-8999-999999999999")


def _references() -> list[c.BoundReference]:
    return [
        c.BoundLedgerUnitReference(
            kind="ledger_unit", ref=c.LedgerUnitRef.U01, entity_id=UNIT,
            source_turn_id=TURN, scope_activity_id=ACTIVITY,
        ),
        c.BoundParticipantReference(
            kind="participant", ref=c.ParticipantRef.P01, entity_id=PAYER,
            source_turn_id=TURN, scope_activity_id=ACTIVITY,
        ),
        c.BoundParticipantReference(
            kind="participant", ref=c.ParticipantRef.P02, entity_id=PARTICIPANT_2,
            source_turn_id=TURN, scope_activity_id=ACTIVITY,
        ),
    ]


def _labels() -> dict:
    return {
        c.ParticipantRef.P01: P2ReferenceLabel(kind="participant", ref=c.ParticipantRef.P01, display_name="Alex"),
        c.ParticipantRef.P02: P2ReferenceLabel(kind="participant", ref=c.ParticipantRef.P02, display_name="Rin"),
        c.LedgerUnitRef.U01: P2ReferenceLabel(kind="ledger_unit", ref=c.LedgerUnitRef.U01, display_name="Main"),
    }


def test_dev_parser_defaults_to_first_payer_and_every_participant() -> None:
    intent = parse_dev_expense_create("记账 午餐 12.50", _references(), _labels(), "CNY")
    assert intent is not None
    assert intent.ledger_unit_ref is c.LedgerUnitRef.U01
    assert intent.title == "午餐"
    assert intent.original_amount == "12.50"
    assert intent.original_currency == "CNY"
    assert intent.payment_allocations[0].participant_ref is c.ParticipantRef.P01
    assert intent.split.participant_refs == [c.ParticipantRef.P01, c.ParticipantRef.P02]


def test_dev_parser_resolves_explicit_names() -> None:
    intent = parse_dev_expense_create(
        "记账 打车 30 付款人=Rin 分摊=Alex", _references(), _labels(), "CNY",
    )
    assert intent is not None
    assert intent.payment_allocations[0].participant_ref is c.ParticipantRef.P02
    assert intent.split.participant_refs == [c.ParticipantRef.P01]


def test_dev_parser_declines_unknown_names_foreign_currency_and_plain_text() -> None:
    assert parse_dev_expense_create("记账 午餐 12.50 付款人=Nobody", _references(), _labels(), "CNY") is None
    assert parse_dev_expense_create("记账 午餐 12.50 外币 USD", _references(), _labels(), "CNY") is None
    assert parse_dev_expense_create("今天花了多少", _references(), _labels(), "CNY") is None
    assert parse_dev_expense_create("记账 午餐 12.50", _references(), _labels(), None) is None


def test_dev_update_parser_reads_target_amount_and_directives() -> None:
    cmd = parse_dev_expense_update("改账 Lunch 15.00 付款人=Rin 分摊=Alex")
    assert cmd is not None
    assert cmd.title == "Lunch"
    assert cmd.amount == "15.00"
    assert cmd.payer_name == "Rin"
    assert cmd.split_token == "Alex"
    assert parse_dev_expense_update("改账 Lunch 15.00 USD") is None
    assert parse_dev_expense_update("今天花了多少") is None


class _Transport:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.get_calls: list[str] = []
        self.expense_id = uuid.uuid4()
        self.duplicate_title = False
        self.activity_creator = str(OWNER)
        self.expense = {
            "id": str(self.expense_id),
            "ledger_unit_id": str(UNIT),
            "title": "Lunch",
            "original_amount": "5.00",
            "original_currency": "USD",
            "base_amount": "5.0",
            "split_method": "equal",
            "occurred_at": "2026-10-25T12:00:00+00:00",
            "note": None,
            "original_expense_id": None,
            "version": 3,
            "is_deleted": False,
            "financial_locked": False,
            "icon_key": "money",
            "created_by": str(OWNER),
        }

    def get_json(self, url, headers, *, timeout, max_response_bytes):  # noqa: ANN001
        self.get_calls.append(url)
        parsed = urlsplit(url)
        table = parsed.path.rsplit("/", 1)[-1]
        params = dict(parse_qsl(parsed.query))
        if table == "expenses":
            if self.duplicate_title:
                return 200, json.dumps([
                    self.expense,
                    {**self.expense, "id": str(uuid.uuid4())},
                ]).encode()
            return 200, json.dumps([self.expense]).encode()
        if table == "payments":
            return 200, json.dumps([{
                "participant_id": str(PAYER), "amount": "5.00",
            }]).encode()
        if table == "splits":
            return 200, json.dumps([
                {"participant_id": str(PAYER), "amount": "2.50"},
                {"participant_id": str(PARTICIPANT_2), "amount": "2.50"},
            ]).encode()
        if table == "ledger_units":
            return 200, json.dumps([{
                "id": str(UNIT), "activity_id": str(ACTIVITY),
                "name": "Main", "is_deleted": False,
            }]).encode()
        if table == "activities":
            return 200, json.dumps([{
                "id": str(ACTIVITY), "created_by": self.activity_creator,
            }]).encode()
        return 200, b"[]"

    def post_json(self, url, headers, payload, *, timeout, max_response_bytes):  # noqa: ANN001
        self.calls.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        if url.endswith("/update_expense_presentation"):
            return 200, json.dumps([{
                "updated_expense_id": str(self.expense_id),
                "version": 4,
                "financial_version": 1,
                "financial_locked": self.expense["financial_locked"],
            }]).encode()
        if url.endswith("/delete_expense"):
            return 200, json.dumps([{
                "deleted_expense_id": str(self.expense_id),
                "deleted": True,
                "version": 4,
            }]).encode()
        if url.endswith("/update_expense_auto_rate"):
            return 200, json.dumps([{
                "updated_expense_id": str(self.expense_id),
                "base_amount": "15.0",
                "version": 4,
            }]).encode()
        return 200, json.dumps([{
            "expense_id": str(self.expense_id), "base_amount": "5.0", "version": 1,
        }]).encode()


def _build_client(database, transport: _Transport):
    store = SQLiteAgentStore(database, admission_enabled=True)
    provider = _Provider()
    backend = _Backend()
    auth = _Auth()
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
        gateway=object(), auth_verifier=auth, scope_authorizer=None, agent_control=_Control(),
        execution_enabled=True, live_gateway=gateway,
    )
    settings = Settings(
        storage_path=database, provider_mode="mock", agent_enabled=True,
        execution_enabled=True, disable_revision=0, api_requests_per_minute=500,
    )
    from app.main import create_app

    app = create_app(settings, components_factory=lambda _: components)
    return TestClient(app), components, provider, transport


def test_dev_bridge_creates_a_live_preview_without_a_model_call(tmp_path) -> None:
    transport = _Transport()
    client, components, provider, _ = _build_client(tmp_path / "p5dev.sqlite3", transport)
    with client:
        session = _create_session(client)
        turn_id = _submit(client, session, "记账 午餐 5.00", scoped=True)
        _wait(components, turn_id, {c.TurnState.WAIT_CONFIRM})

        assert provider.prompts == []
        details = components.store.get_session_detail(OWNER, session)
        proposal = next(item for item in details.proposals if item.status is c.ProposalStatus.PENDING)
        assert proposal.mode == "backend"
        assert proposal.policy_version == "p5-dev-intent-v1"
        assert proposal.preview is not None
        assert proposal.preview.summary.startswith("【P5 开发验证】")
        assert proposal.canonical_command is not None
        assert proposal.canonical_command.activity_id == ACTIVITY
        assert proposal.canonical_command.ledger_unit_id == UNIT
        assert proposal.canonical_command.original_currency == "USD"
        assert [item.participant_id for item in proposal.canonical_command.payment_allocations] == [PAYER]
        assert proposal.canonical_command.split.participant_ids == [PAYER, PARTICIPANT_2]
        assert transport.calls == []


def test_dev_bridge_confirmation_reaches_the_real_rpc_shape(tmp_path) -> None:
    transport = _Transport()
    client, components, _, _ = _build_client(tmp_path / "p5dev-confirm.sqlite3", transport)
    with client:
        session = _create_session(client)
        turn_id = _submit(client, session, "记账 午餐 5.00 付款人=Rin", scoped=True)
        _wait(components, turn_id, {c.TurnState.WAIT_CONFIRM})
        details = components.store.get_session_detail(OWNER, session)
        proposal = next(item for item in details.proposals if item.status is c.ProposalStatus.PENDING)

        response = client.post(
            f"/v1/proposals/{proposal.proposal_id}/confirm",
            headers=_auth(),
            json={
                "client_request_id": str(uuid.uuid4()),
                "expected_proposal_revision": proposal.revision,
                "command_digest": proposal.command_digest,
                "confirmation_nonce": proposal.confirmation_nonce,
            },
        )

        assert response.status_code == 202, response.text
        assert response.json()["turn"]["execution_resolution"] == "succeeded"
        assert len(transport.calls) == 1
        payload = transport.calls[0]["payload"]
        assert payload["ledger_unit_id"] == str(UNIT)
        assert payload["original_amount"] == "5.00"
        assert payload["original_currency"] == "USD"
        assert payload["payments"] == [{"participant_id": str(PARTICIPANT_2), "amount": "5.00"}]
        assert payload["aa_participant_ids"] == [str(PAYER), str(PARTICIPANT_2)]
        assert components.store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.COMPLETED


def test_dev_update_bridge_creates_preview_and_reaches_the_update_rpc(tmp_path) -> None:
    transport = _Transport()
    client, components, provider, _ = _build_client(tmp_path / "p5dev-update.sqlite3", transport)
    with client:
        session = _create_session(client)
        turn_id = _submit(client, session, "改账 Lunch 15.00", scoped=True)
        _wait(components, turn_id, {c.TurnState.WAIT_CONFIRM})

        assert provider.prompts == []
        details = components.store.get_session_detail(OWNER, session)
        proposal = next(item for item in details.proposals if item.status is c.ProposalStatus.PENDING)
        assert proposal.operation == "expense.update"
        assert proposal.policy_version == "p5-dev-expense-update-v1"
        assert proposal.preview is not None
        assert proposal.preview.summary.startswith("【P5 开发验证·改账】")
        assert isinstance(proposal.canonical_command, c.FixedExpenseUpdateCommand)
        assert proposal.canonical_command.expense_id == transport.expense_id
        assert proposal.canonical_command.expected_expense_version == "3"
        assert proposal.canonical_command.patch.original_amount == "15.00"
        assert proposal.canonical_command.patch.payment_allocations == [
            c.CanonicalPayment(participant_id=PAYER, amount="15.00"),
        ]
        assert transport.calls == []

        response = client.post(
            f"/v1/proposals/{proposal.proposal_id}/confirm",
            headers=_auth(),
            json={
                "client_request_id": str(uuid.uuid4()),
                "expected_proposal_revision": proposal.revision,
                "command_digest": proposal.command_digest,
                "confirmation_nonce": proposal.confirmation_nonce,
            },
        )

        assert response.status_code == 202, response.text
        assert response.json()["turn"]["execution_resolution"] == "succeeded"
        assert len(transport.calls) == 1
        assert transport.calls[0]["url"].endswith("/rest/v1/rpc/update_expense_auto_rate")
        payload = transport.calls[0]["payload"]
        assert payload["expense_id"] == str(transport.expense_id)
        assert payload["original_amount"] == "15.00"
        assert payload["original_currency"] == "USD"
        assert payload["payments"] == [{"participant_id": str(PAYER), "amount": "15.00"}]
        assert payload["aa_participant_ids"] == [str(PAYER), str(PARTICIPANT_2)]
        assert components.store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.COMPLETED


def test_dev_update_bridge_refuses_a_locked_expense_without_a_model_call(tmp_path) -> None:
    transport = _Transport()
    transport.expense["financial_locked"] = True
    client, components, provider, _ = _build_client(tmp_path / "p5dev-locked.sqlite3", transport)
    with client:
        session = _create_session(client)
        turn_id = _submit(client, session, "改账 Lunch 15.00", scoped=True)
        _wait(components, turn_id, {c.TurnState.COMPLETED})

        assert provider.prompts == []
        assert transport.calls == []
        details = components.store.get_session_detail(OWNER, session)
        assert not any(item.status is c.ProposalStatus.PENDING for item in details.proposals)
        events = _events(client, turn_id)["events"]
        messages = [
            item["payload"]["text"] for item in events
            if item.get("type") == "message"
        ]
        assert any("锁定" in text for text in messages)


def test_dev_presentation_parser_resolves_unique_prefix_and_rejects_ambiguity() -> None:
    cmd = parse_dev_presentation_command("改名 Lunch Dinner", ["Lunch", "Dinner"])
    assert cmd is not None
    assert (cmd.kind, cmd.target_title, cmd.value) == ("title", "Lunch", "Dinner")

    spaced = parse_dev_presentation_command("改图标 Team Lunch dining", ["Team Lunch"])
    assert spaced is not None
    assert (spaced.kind, spaced.target_title, spaced.value) == ("icon", "Team Lunch", "dining")

    assert parse_dev_presentation_command("改名 Lunch X", ["Lunch", "Lunch"]) is None
    assert parse_dev_presentation_command("改名 Lunch 2 X", ["Lunch", "Lunch 2"]) is None
    assert parse_dev_presentation_command("改名 Lunch", ["Lunch"]) is None
    assert parse_dev_presentation_command("记账 Lunch 5", ["Lunch"]) is None


def _confirm(client, proposal):
    return client.post(
        f"/v1/proposals/{proposal.proposal_id}/confirm",
        headers=_auth(),
        json={
            "client_request_id": str(uuid.uuid4()),
            "expected_proposal_revision": proposal.revision,
            "command_digest": proposal.command_digest,
            "confirmation_nonce": proposal.confirmation_nonce,
        },
    )


def test_dev_presentation_bridge_renames_and_reaches_the_rpc(tmp_path) -> None:
    transport = _Transport()
    client, components, provider, _ = _build_client(tmp_path / "p5dev-rename.sqlite3", transport)
    with client:
        session = _create_session(client)
        turn_id = _submit(client, session, "改名 Lunch Dinner", scoped=True)
        _wait(components, turn_id, {c.TurnState.WAIT_CONFIRM})

        assert provider.prompts == []
        details = components.store.get_session_detail(OWNER, session)
        proposal = next(item for item in details.proposals if item.status is c.ProposalStatus.PENDING)
        assert proposal.operation == "expense.presentation.update"
        assert proposal.policy_version == "p5-dev-expense-presentation-v1"
        assert proposal.preview is not None
        assert proposal.preview.summary.startswith("【P5 开发验证·展示】")
        assert transport.calls == []

        response = _confirm(client, proposal)
        assert response.status_code == 202, response.text
        assert response.json()["turn"]["execution_resolution"] == "succeeded"
        assert len(transport.calls) == 1
        assert transport.calls[0]["url"].endswith("/rest/v1/rpc/update_expense_presentation")
        assert transport.calls[0]["payload"] == {
            "expense_id": str(transport.expense_id),
            "title": "Dinner",
            "note": None,
            "icon_key": "money",
            "expected_version": 3,
        }


def test_dev_presentation_bridge_changes_icon_and_note(tmp_path) -> None:
    transport = _Transport()
    client, components, provider, _ = _build_client(tmp_path / "p5dev-icon-note.sqlite3", transport)
    with client:
        session = _create_session(client)

        icon_turn = _submit(client, session, "改图标 Lunch dining", scoped=True)
        _wait(components, icon_turn, {c.TurnState.WAIT_CONFIRM})
        details = components.store.get_session_detail(OWNER, session)
        icon_proposal = next(item for item in details.proposals if item.status is c.ProposalStatus.PENDING)
        assert _confirm(client, icon_proposal).status_code == 202
        assert transport.calls[-1]["payload"]["icon_key"] == "dining"

        note_turn = _submit(client, session, "改备注 Lunch team lunch", scoped=True)
        _wait(components, note_turn, {c.TurnState.WAIT_CONFIRM})
        details = components.store.get_session_detail(OWNER, session)
        note_proposal = next(item for item in details.proposals if item.status is c.ProposalStatus.PENDING)
        assert _confirm(client, note_proposal).status_code == 202
        assert transport.calls[-1]["payload"]["note"] == "team lunch"
        assert provider.prompts == []


def test_dev_presentation_bridge_refuses_bad_icon_no_change_and_unknown_target(tmp_path) -> None:
    transport = _Transport()
    client, components, provider, _ = _build_client(tmp_path / "p5dev-presentation-refusals.sqlite3", transport)
    with client:
        session = _create_session(client)

        for text, marker in (
            ("改图标 Lunch not_an_icon", "图标"),
            ("改名 Lunch Lunch", "新值"),
            ("改名 Missing X", "用法"),
        ):
            turn_id = _submit(client, session, text, scoped=True)
            _wait(components, turn_id, {c.TurnState.COMPLETED})
            details = components.store.get_session_detail(OWNER, session)
            assert not any(item.status is c.ProposalStatus.PENDING for item in details.proposals)
            messages = [
                item["payload"]["text"] for item in _events(client, turn_id)["events"]
                if item.get("type") == "message"
            ]
            assert any(marker in text_value for text_value in messages), (text, messages)

        assert provider.prompts == []
        assert transport.calls == []


def test_dev_presentation_bridge_refuses_duplicate_titles(tmp_path) -> None:
    transport = _Transport()
    transport.duplicate_title = True
    client, components, provider, _ = _build_client(tmp_path / "p5dev-duplicate-title.sqlite3", transport)
    with client:
        session = _create_session(client)
        turn_id = _submit(client, session, "改名 Lunch Dinner", scoped=True)
        _wait(components, turn_id, {c.TurnState.COMPLETED})

        details = components.store.get_session_detail(OWNER, session)
        assert not any(item.status is c.ProposalStatus.PENDING for item in details.proposals)
        messages = [
            item["payload"]["text"] for item in _events(client, turn_id)["events"]
            if item.get("type") == "message"
        ]
        assert any("用法" in text_value for text_value in messages)
        assert provider.prompts == []
        assert transport.calls == []


def test_dev_delete_bridge_creates_preview_and_reaches_the_rpc(tmp_path) -> None:
    transport = _Transport()
    client, components, provider, _ = _build_client(tmp_path / "p5dev-delete.sqlite3", transport)
    with client:
        session = _create_session(client)
        turn_id = _submit(client, session, "删除 Lunch", scoped=True)
        _wait(components, turn_id, {c.TurnState.WAIT_CONFIRM})

        assert provider.prompts == []
        details = components.store.get_session_detail(OWNER, session)
        proposal = next(item for item in details.proposals if item.status is c.ProposalStatus.PENDING)
        assert proposal.operation == "expense.delete"
        assert proposal.policy_version == "p5-dev-expense-delete-v1"
        assert proposal.preview is not None
        assert proposal.preview.summary.startswith("【P5 开发验证·删除】")
        assert proposal.preview.after.is_deleted is True
        assert transport.calls == []

        response = _confirm(client, proposal)
        assert response.status_code == 202, response.text
        assert response.json()["turn"]["execution_resolution"] == "succeeded"
        assert len(transport.calls) == 1
        assert transport.calls[0]["url"].endswith("/rest/v1/rpc/delete_expense")
        assert transport.calls[0]["payload"] == {"expense_id": str(transport.expense_id)}


def test_dev_delete_bridge_refuses_locked_and_non_creator(tmp_path) -> None:
    transport = _Transport()
    client, components, provider, _ = _build_client(tmp_path / "p5dev-delete-refusals.sqlite3", transport)
    with client:
        session = _create_session(client)

        transport.expense["financial_locked"] = True
        locked_turn = _submit(client, session, "删除 Lunch", scoped=True)
        _wait(components, locked_turn, {c.TurnState.COMPLETED})
        locked_messages = [
            item["payload"]["text"] for item in _events(client, locked_turn)["events"]
            if item.get("type") == "message"
        ]
        assert any("锁定" in text_value for text_value in locked_messages)

        transport.expense["financial_locked"] = False
        transport.expense["created_by"] = str(uuid.uuid4())
        transport.activity_creator = str(uuid.uuid4())
        permission_turn = _submit(client, session, "删除 Lunch", scoped=True)
        _wait(components, permission_turn, {c.TurnState.COMPLETED})
        permission_messages = [
            item["payload"]["text"] for item in _events(client, permission_turn)["events"]
            if item.get("type") == "message"
        ]
        assert any("创建者" in text_value for text_value in permission_messages)

        details = components.store.get_session_detail(OWNER, session)
        assert not any(item.status is c.ProposalStatus.PENDING for item in details.proposals)
        assert provider.prompts == []
        assert transport.calls == []


def test_dev_delete_bridge_refuses_already_deleted_and_duplicate_titles(tmp_path) -> None:
    transport = _Transport()
    client, components, provider, _ = _build_client(tmp_path / "p5dev-delete-deleted.sqlite3", transport)
    with client:
        session = _create_session(client)
        transport.expense["is_deleted"] = True
        deleted_turn = _submit(client, session, "删除 Lunch", scoped=True)
        _wait(components, deleted_turn, {c.TurnState.COMPLETED})
        deleted_messages = [
            item["payload"]["text"] for item in _events(client, deleted_turn)["events"]
            if item.get("type") == "message"
        ]
        assert any("已删除" in text_value for text_value in deleted_messages)
        assert provider.prompts == []
        assert transport.calls == []

    duplicated = _Transport()
    duplicated.duplicate_title = True
    client, components, provider, _ = _build_client(tmp_path / "p5dev-delete-duplicate.sqlite3", duplicated)
    with client:
        session = _create_session(client)
        duplicate_turn = _submit(client, session, "删除 Lunch", scoped=True)
        _wait(components, duplicate_turn, {c.TurnState.COMPLETED})
        duplicate_messages = [
            item["payload"]["text"] for item in _events(client, duplicate_turn)["events"]
            if item.get("type") == "message"
        ]
        assert any("用法" in text_value for text_value in duplicate_messages)
        assert provider.prompts == []
        assert duplicated.calls == []
