from __future__ import annotations

"""P5.5b Transfer void: type dispatch, permission, version guard, reconcile."""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest

from agent.app import contracts as c
from agent.app.p5_write import LiveExpenseGateway, LiveWriteConfig, LiveWriteError
from agent.app.ports import Principal
from agent.app.store import SQLiteAgentStore
from test_p5_live_write import ACTIVITY, FakeReadBackend, P1, P2
from test_sqlite_persistence import OWNER, _session, _submit, _wait_with_proposal


TRANSFER = uuid.UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
OTHER_USER = uuid.UUID("99999999-9999-4999-8999-999999999999")


class FakeVoidTransport:
    def __init__(self) -> None:
        self.get_calls: list[str] = []
        self.post_calls: list[dict] = []
        self.mode = "success"
        self.transfer = {
            "id": str(TRANSFER),
            "activity_id": str(ACTIVITY),
            "type": "settlement",
            "from_participant_id": str(P1),
            "to_participant_id": str(P2),
            "amount": "10.0",
            "currency": "CNY",
            "recorded_by": str(OWNER),
            "is_voided": False,
            "voided_at": None,
            "voided_by": None,
            "void_reason": None,
        }
        self.activity = {
            "id": str(ACTIVITY),
            "created_by": str(OWNER),
            "archived_at": None,
            "is_deleted": False,
            "financial_version": 5,
        }

    def get_json(self, url, headers, *, timeout, max_response_bytes):  # noqa: ANN001
        self.get_calls.append(url)
        table = urlsplit(url).path.rsplit("/", 1)[-1]
        if table == "transfers":
            return 200, json.dumps([self.transfer]).encode()
        if table == "activities":
            return 200, json.dumps([self.activity]).encode()
        return 200, b"[]"

    def post_json(self, url, headers, payload, *, timeout, max_response_bytes):  # noqa: ANN001
        self.post_calls.append({"url": url, "payload": dict(payload)})
        if self.mode == "ambiguous":
            raise LiveWriteError("upstream_ambiguous", ambiguous=True)
        if self.mode == "already_voided":
            return 200, json.dumps([{
                "transfer_id": str(TRANSFER), "voided": False, "financial_version": 5,
            }]).encode()
        if self.mode == "already_voided_race":
            self.transfer["is_voided"] = True
            return 400, json.dumps({
                "code": "55000", "message": "transfer is already voided",
            }).encode()
        if self.mode == "reject_archived":
            return 400, json.dumps({
                "code": "55000", "message": "archived activity is read-only",
            }).encode()
        if self.mode == "reject_deleted":
            return 404, json.dumps({
                "code": "P0002", "message": "transfer was not found",
            }).encode()
        if self.mode == "reject_permission":
            return 403, json.dumps({
                "code": "42501", "message": "member may void only a transfer they recorded",
            }).encode()
        if self.mode == "reject_dependency":
            return 400, json.dumps({
                "code": "23514", "message": "void active prepayment returns before voiding the source transfer",
            }).encode()
        return 200, json.dumps([{
            "transfer_id": str(TRANSFER), "voided": True, "financial_version": 6,
        }]).encode()


def _intent(reason: str = "test void") -> c.VoidTransferIntent:
    return c.VoidTransferIntent(
        kind="transfer.void", transfer_id=TRANSFER, void_reason=reason,
    )


def _setup(
    tmp_path, name: str, *,
    transfer_type: str = "settlement",
    recorded_by: uuid.UUID = OWNER,
    creator: uuid.UUID = OWNER,
    archived: bool = False,
    deleted: bool = False,
):
    store = SQLiteAgentStore(tmp_path / f"{name}.sqlite3", admission_enabled=True)
    store.start()
    session = _session(store, OWNER)
    _, turn_id = _submit(store, session, OWNER)
    read_backend = FakeReadBackend(version=5, base_currency="CNY")
    transport = FakeVoidTransport()
    transport.transfer["type"] = transfer_type
    transport.transfer["recorded_by"] = str(recorded_by)
    transport.activity["created_by"] = str(creator)
    transport.activity["archived_at"] = (
        datetime.now(timezone.utc).isoformat() if archived else None
    )
    transport.activity["is_deleted"] = deleted
    gateway = LiveExpenseGateway(
        LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
        store, read_backend, transport,
    )
    proposal = asyncio.run(gateway.build_void_preview(
        owner_user_id=OWNER,
        session_id=session,
        turn_id=turn_id,
        intent=_intent(),
        access_token="token-a",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        agent_disable_revision=0,
        now=datetime.now(timezone.utc),
    ))
    waiting = _wait_with_proposal(store, OWNER, turn_id, proposal)
    principal = Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1))
    return store, gateway, transport, proposal, waiting, principal, turn_id


def _confirm_request(proposal: c.ProposalRecord, *, request_id: uuid.UUID | None = None):
    return c.ConfirmProposalRequest(
        client_request_id=request_id or uuid.uuid4(),
        expected_proposal_revision=proposal.revision,
        command_digest=proposal.command_digest,
        confirmation_nonce=proposal.confirmation_nonce,
    )


def _execute(gateway, principal, proposal, waiting, *, request_id=None):
    return asyncio.run(gateway.execute(
        principal=principal,
        proposal=proposal,
        request=_confirm_request(proposal, request_id=request_id),
        expected_state_revision=waiting.state_revision,
        access_token="token-a",
    ))


def test_void_preview_reads_transfer_and_writes_nothing(tmp_path) -> None:
    store, _, transport, proposal, waiting, _, _ = _setup(tmp_path, "p55b-preview")
    try:
        assert waiting.state is c.TurnState.WAIT_CONFIRM
        assert proposal.operation == "transfer.void"
        assert isinstance(proposal.canonical_command, c.FixedVoidTransferCommand)
        assert proposal.canonical_command.transfer_type == "settlement"
        assert proposal.canonical_command.expected_financial_version == "5"
        assert isinstance(proposal.preview, c.TransferVoidPreview)
        assert proposal.preview.is_voided is False
        assert transport.post_calls == []
    finally:
        store.close()


def test_own_settlement_transfer_can_be_voided(tmp_path) -> None:
    store, gateway, transport, proposal, waiting, principal, turn_id = _setup(tmp_path, "p55b-own")
    try:
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "transfer_voided"
        assert len(transport.post_calls) == 1
        assert transport.post_calls[0]["url"].endswith("/rest/v1/rpc/void_settlement_transfer")
        assert transport.post_calls[0]["payload"] == {
            "transfer_id": str(TRANSFER), "void_reason": "test void",
        }
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.COMPLETED
    finally:
        store.close()


def test_prepayment_transfer_uses_the_prepayment_rpc(tmp_path) -> None:
    store, gateway, transport, proposal, waiting, principal, _ = _setup(
        tmp_path, "p55b-prepayment", transfer_type="prepayment",
    )
    try:
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert len(transport.post_calls) == 1
        assert transport.post_calls[0]["url"].endswith("/rest/v1/rpc/void_prepayment_transfer")
    finally:
        store.close()


def test_activity_creator_can_void_another_users_transfer(tmp_path) -> None:
    store, gateway, _, proposal, waiting, principal, _ = _setup(
        tmp_path, "p55b-creator", recorded_by=OTHER_USER, creator=OWNER,
    )
    try:
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
    finally:
        store.close()


def test_member_voiding_another_users_transfer_is_rejected(tmp_path) -> None:
    store, gateway, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p55b-member", recorded_by=OWNER, creator=OTHER_USER,
    )
    try:
        transport.mode = "reject_permission"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.REJECTED
        assert outcome.code == "permission_denied"
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.FAILED
    finally:
        store.close()


def test_already_voided_changed_false_is_idempotent_success(tmp_path) -> None:
    store, gateway, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p55b-already",
    )
    try:
        transport.mode = "already_voided"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "transfer_already_voided"
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.COMPLETED
    finally:
        store.close()


def test_55000_already_voided_race_is_idempotent_success(tmp_path) -> None:
    store, gateway, transport, proposal, waiting, principal, _ = _setup(
        tmp_path, "p55b-55000-race",
    )
    try:
        transport.mode = "already_voided_race"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "transfer_already_voided"
    finally:
        store.close()


@pytest.mark.parametrize(
    ("mode", "state_code"),
    [("reject_archived", "activity_read_only"), ("reject_deleted", "not_found")],
)
def test_archived_or_deleted_activity_is_rejected(tmp_path, mode, state_code) -> None:
    archived = mode == "reject_archived"
    store, gateway, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, f"p55b-{mode}", archived=archived, deleted=not archived,
    )
    try:
        transport.mode = mode
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.REJECTED
        assert outcome.code == state_code
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.FAILED
    finally:
        store.close()


def test_prepayment_return_dependency_is_rejected(tmp_path) -> None:
    store, gateway, transport, proposal, waiting, principal, _ = _setup(
        tmp_path, "p55b-dependency", transfer_type="prepayment",
    )
    try:
        transport.mode = "reject_dependency"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.REJECTED
        assert outcome.code == "constraint_rejected"
    finally:
        store.close()


@pytest.mark.parametrize("changed", ["activity_version", "is_voided", "recorded_by", "type"])
def test_preflight_change_closes_without_rpc(tmp_path, changed) -> None:
    store, gateway, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, f"p55b-change-{changed}",
    )
    try:
        if changed == "activity_version":
            transport.activity["financial_version"] = 6
        elif changed == "is_voided":
            transport.transfer["is_voided"] = True
        elif changed == "recorded_by":
            transport.transfer["recorded_by"] = str(OTHER_USER)
        else:
            transport.transfer["type"] = "prepayment"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert transport.post_calls == []
        assert store.get_proposal(OWNER, proposal.proposal_id).status is c.ProposalStatus.CLOSED
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.CANCELLED
        assert turn.execution is None
    finally:
        store.close()


def test_duplicate_confirmation_sends_one_rpc(tmp_path) -> None:
    store, gateway, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p55b-duplicate",
    )
    try:
        assert _execute(gateway, principal, proposal, waiting).resolution is c.ExecutionResolution.SUCCEEDED
        stored = store.get_proposal(OWNER, proposal.proposal_id)
        again = asyncio.run(gateway.execute(
            principal=principal,
            proposal=stored,
            request=_confirm_request(proposal),
            expected_state_revision=store.get_turn(OWNER, turn_id).record.turn.state_revision,
            access_token="token-a",
        ))
        assert again.resolution is c.ExecutionResolution.SUCCEEDED
        assert len(transport.post_calls) == 1
    finally:
        store.close()


def test_unknown_void_reconciles_to_closed(tmp_path) -> None:
    store, gateway, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p55b-unknown",
    )
    try:
        transport.mode = "ambiguous"
        assert _execute(gateway, principal, proposal, waiting).resolution is c.ExecutionResolution.UNKNOWN
        transport.transfer["is_voided"] = True
        stored = store.get_proposal(OWNER, proposal.proposal_id)
        outcome = asyncio.run(gateway.reconcile(principal, stored, "token-a"))
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == "voided_elsewhere"
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.CANCELLED
        assert len(transport.post_calls) == 1
    finally:
        store.close()


def test_unknown_void_not_applied_closes(tmp_path) -> None:
    store, gateway, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p55b-unknown-not-applied",
    )
    try:
        transport.mode = "ambiguous"
        assert _execute(gateway, principal, proposal, waiting).resolution is c.ExecutionResolution.UNKNOWN
        stored = store.get_proposal(OWNER, proposal.proposal_id)
        outcome = asyncio.run(gateway.reconcile(principal, stored, "token-a"))
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == "void_not_applied"
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.CANCELLED
    finally:
        store.close()


def test_unknown_void_with_activity_change_closes(tmp_path) -> None:
    store, gateway, transport, proposal, waiting, principal, _ = _setup(
        tmp_path, "p55b-unknown-changed",
    )
    try:
        transport.mode = "ambiguous"
        assert _execute(gateway, principal, proposal, waiting).resolution is c.ExecutionResolution.UNKNOWN
        transport.activity["financial_version"] = 6
        stored = store.get_proposal(OWNER, proposal.proposal_id)
        outcome = asyncio.run(gateway.reconcile(principal, stored, "token-a"))
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == "activity_changed"
    finally:
        store.close()
