from __future__ import annotations

"""P5.3 logical delete: permission, dual version preflight, idempotency, reconcile."""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlsplit

import pytest

from agent.app import contracts as c
from agent.app.p5_write import LiveExpenseGateway, LiveWriteConfig, LiveWriteError
from agent.app.ports import Principal
from agent.app.store import SQLiteAgentStore
from test_p5_live_write import ACTIVITY, FakeReadBackend
from test_p5_update import EXPENSE, FakeUpdateTransport, _all_references
from test_sqlite_persistence import OWNER, _session, _submit, _wait_with_proposal


OTHER_USER = uuid.UUID("99999999-9999-4999-8999-999999999999")


class FakeDeleteTransport(FakeUpdateTransport):
    def __init__(self) -> None:
        super().__init__()
        self.expense["created_by"] = str(OWNER)
        self.activity_creator = str(OWNER)
        self.deleted_result = True

    def get_json(self, url, headers, *, timeout, max_response_bytes):  # noqa: ANN001
        parsed = urlsplit(url)
        table = parsed.path.rsplit("/", 1)[-1]
        if table == "activities":
            return 200, json.dumps([{
                "id": str(ACTIVITY), "created_by": self.activity_creator,
            }]).encode()
        return super().get_json(
            url, headers, timeout=timeout, max_response_bytes=max_response_bytes,
        )

    def post_json(self, url, headers, payload, *, timeout, max_response_bytes):  # noqa: ANN001
        self.post_calls.append({"url": url, "payload": dict(payload)})
        if self.mode == "ambiguous":
            raise LiveWriteError("upstream_ambiguous", ambiguous=True)
        if self.mode == "archived":
            return 400, json.dumps({
                "code": "55000", "message": "archived activity is read-only",
            }).encode()
        if self.mode == "not_permitted":
            return 403, json.dumps({
                "code": "42501", "message": "only expense creator or activity creator may delete expense",
            }).encode()
        return 200, json.dumps([{
            "deleted_expense_id": self.expense["id"],
            "deleted": self.deleted_result,
            "version": 4 if self.deleted_result else 3,
        }]).encode()


def _delete_intent() -> c.ExpenseDeleteIntent:
    return c.ExpenseDeleteIntent(
        kind="expense.delete", expense_ref=c.ExpenseRef.SELECTED,
    )


def _setup(tmp_path, name: str):
    store = SQLiteAgentStore(tmp_path / f"{name}.sqlite3", admission_enabled=True)
    store.start()
    session = _session(store, OWNER)
    _, turn_id = _submit(store, session, OWNER)
    read_backend = FakeReadBackend(version=5, base_currency="CNY")
    transport = FakeDeleteTransport()
    gateway = LiveExpenseGateway(
        LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
        store, read_backend, transport,
    )
    proposal = asyncio.run(gateway.build_delete_preview(
        owner_user_id=OWNER,
        session_id=session,
        turn_id=turn_id,
        intent=_delete_intent(),
        bound_references=_all_references(turn_id),
        access_token="token-a",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        agent_disable_revision=0,
        now=datetime.now(timezone.utc),
    ))
    waiting = _wait_with_proposal(store, OWNER, turn_id, proposal)
    principal = Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1))
    return store, gateway, read_backend, transport, proposal, waiting, principal, turn_id


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


def test_delete_preview_reads_state_and_writes_nothing(tmp_path) -> None:
    store, _, _, transport, proposal, waiting, _, _ = _setup(tmp_path, "p53-preview")
    try:
        assert waiting.state is c.TurnState.WAIT_CONFIRM
        assert proposal.operation == "expense.delete"
        assert isinstance(proposal.canonical_command, c.FixedExpenseDeleteCommand)
        assert proposal.canonical_command.expected_expense_version == "3"
        assert proposal.canonical_command.expected_financial_version == "5"
        assert proposal.canonical_command.expected_is_deleted is False
        assert proposal.preview is not None and proposal.preview.before is not None
        assert proposal.preview.before.is_deleted is False
        assert proposal.preview.after.is_deleted is True
        assert [item.field for item in proposal.preview.changes] == ["is_deleted"]
        assert transport.post_calls == []
    finally:
        store.close()


def test_unlocked_expense_can_be_deleted(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(tmp_path, "p53-delete")
    try:
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "expense_deleted"
        assert len(transport.post_calls) == 1
        assert transport.post_calls[0]["url"].endswith("/rest/v1/rpc/delete_expense")
        assert transport.post_calls[0]["payload"] == {"expense_id": str(EXPENSE)}
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.COMPLETED
    finally:
        store.close()


def test_locked_expense_is_rejected_without_rpc(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, _ = _setup(tmp_path, "p53-locked")
    try:
        transport.expense["financial_locked"] = True
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == "expense_financial_locked"
        assert transport.post_calls == []
    finally:
        store.close()


def test_non_creator_and_non_activity_creator_are_rejected(tmp_path) -> None:
    store = SQLiteAgentStore(tmp_path / "p53-permission.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        read_backend = FakeReadBackend(version=5, base_currency="CNY")
        transport = FakeDeleteTransport()
        transport.expense["created_by"] = str(OTHER_USER)
        transport.activity_creator = str(OTHER_USER)
        gateway = LiveExpenseGateway(
            LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
            store, read_backend, transport,
        )
        with pytest.raises(LiveWriteError) as caught:
            asyncio.run(gateway.build_delete_preview(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=_delete_intent(), bound_references=_all_references(turn_id),
                access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert caught.value.code == "delete_not_permitted"
        assert transport.post_calls == []
    finally:
        store.close()


def test_already_deleted_response_is_idempotent_success(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p53-already-deleted",
    )
    try:
        transport.deleted_result = False
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "expense_already_deleted"
        assert len(transport.post_calls) == 1
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.COMPLETED
    finally:
        store.close()


@pytest.mark.parametrize("changed", ["expense_version", "is_deleted", "activity_version"])
def test_preflight_change_closes_without_rpc(tmp_path, changed) -> None:
    store, gateway, read_backend, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, f"p53-change-{changed}",
    )
    try:
        if changed == "expense_version":
            transport.expense["version"] = 4
        elif changed == "is_deleted":
            transport.expense["is_deleted"] = True
        else:
            read_backend.version = 6
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert transport.post_calls == []
        assert store.get_proposal(OWNER, proposal.proposal_id).status is c.ProposalStatus.CLOSED
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.CANCELLED
        assert turn.execution is None
    finally:
        store.close()


def test_archived_activity_is_left_to_the_rpc(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p53-archived",
    )
    try:
        transport.mode = "archived"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.REJECTED
        assert len(transport.post_calls) == 1
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.FAILED
    finally:
        store.close()


def test_duplicate_confirmation_sends_one_rpc(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p53-duplicate",
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


def test_unknown_delete_is_not_retried_and_reconciles_to_closed(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p53-unknown",
    )
    try:
        transport.mode = "ambiguous"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.UNKNOWN
        assert len(transport.post_calls) == 1
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.RECOVERING
        assert turn.execution_resolution is c.ExecutionResolution.UNKNOWN

        stored = store.get_proposal(OWNER, proposal.proposal_id)
        assert asyncio.run(gateway.reconcile(principal, stored, "token-a")).resolution is (
            c.ExecutionResolution.CLOSED
        )
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.CANCELLED
        assert turn.execution_resolution is c.ExecutionResolution.CLOSED
        assert store.get_proposal(OWNER, proposal.proposal_id).status is c.ProposalStatus.CLOSED
        assert len(transport.post_calls) == 1
    finally:
        store.close()


def test_reconcile_marks_already_deleted_elsewhere_as_closed(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p53-reconcile-deleted",
    )
    try:
        transport.mode = "ambiguous"
        assert _execute(gateway, principal, proposal, waiting).resolution is c.ExecutionResolution.UNKNOWN
        transport.expense["is_deleted"] = True
        stored = store.get_proposal(OWNER, proposal.proposal_id)
        outcome = asyncio.run(gateway.reconcile(principal, stored, "token-a"))
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == "deleted_elsewhere"
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.CANCELLED
        assert len(transport.post_calls) == 1
    finally:
        store.close()


def test_reconcile_with_unchanged_undeleted_expense_closes_not_applied(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p53-reconcile-unchanged",
    )
    try:
        transport.mode = "ambiguous"
        assert _execute(gateway, principal, proposal, waiting).resolution is c.ExecutionResolution.UNKNOWN
        stored = store.get_proposal(OWNER, proposal.proposal_id)
        outcome = asyncio.run(gateway.reconcile(principal, stored, "token-a"))
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == "delete_not_applied"
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.CANCELLED
    finally:
        store.close()
