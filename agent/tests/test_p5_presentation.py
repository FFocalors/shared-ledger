from __future__ import annotations

"""P5.2 presentation update: locked Expenses, version guard, and outcomes.

The RPC is faked; the Store, contracts, Gateway and state machine are real.
"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from agent.app import contracts as c
from agent.app.p5_write import LiveExpenseGateway, LiveWriteConfig, LiveWriteError
from agent.app.ports import Principal
from agent.app.store import SQLiteAgentStore
from test_p5_live_write import FakeReadBackend
from test_p5_update import EXPENSE, FakeUpdateTransport, _all_references
from test_sqlite_persistence import OWNER, _session, _submit, _wait_with_proposal


class FakePresentationTransport(FakeUpdateTransport):
    def post_json(self, url, headers, payload, *, timeout, max_response_bytes):  # noqa: ANN001
        self.post_calls.append({"url": url, "payload": dict(payload)})
        if self.mode == "ambiguous":
            raise LiveWriteError("upstream_ambiguous", ambiguous=True)
        if self.mode == "version_conflict":
            return 400, json.dumps({
                "code": "40001", "message": "expense version mismatch; refresh the expense",
            }).encode()
        if self.mode == "reject":
            return 400, json.dumps({
                "code": "55000", "message": "deleted expense cannot be modified or restored",
            }).encode()
        return 200, json.dumps([{
            "updated_expense_id": self.expense["id"],
            "version": 4,
            "financial_version": 5,
            "financial_locked": self.expense["financial_locked"],
        }]).encode()


def _intent(*, icon_key: str | None = "dining", title: str | None = None) -> c.ExpensePresentationUpdateIntent:
    return c.ExpensePresentationUpdateIntent(
        kind="expense.presentation.update",
        expense_ref=c.ExpenseRef.SELECTED,
        title=title,
        note=None,
        icon_key=icon_key,
    )


def _setup(tmp_path, name: str, *, intent=None, locked: bool = False):
    store = SQLiteAgentStore(tmp_path / f"{name}.sqlite3", admission_enabled=True)
    store.start()
    session = _session(store, OWNER)
    _, turn_id = _submit(store, session, OWNER)
    read_backend = FakeReadBackend(version=5, base_currency="CNY")
    transport = FakePresentationTransport()
    transport.expense["financial_locked"] = locked
    gateway = LiveExpenseGateway(
        LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
        store, read_backend, transport,
    )
    proposal = asyncio.run(gateway.build_presentation_preview(
        owner_user_id=OWNER,
        session_id=session,
        turn_id=turn_id,
        intent=intent or _intent(),
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


def test_locked_expense_can_change_presentation_and_financial_fields_are_unchanged(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p52-locked", locked=True,
    )
    try:
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert len(transport.post_calls) == 1
        payload = transport.post_calls[0]["payload"]
        assert set(payload) == {
            "expense_id", "title", "note", "icon_key", "expected_version",
        }
        assert payload["icon_key"] == "dining"
        assert payload["expected_version"] == 3
        assert "original_amount" not in payload
        assert "payments" not in payload
        assert "split_method" not in payload

        preview = proposal.preview
        assert preview is not None and preview.before is not None
        assert preview.before.financial_locked is True
        assert preview.after.financial_locked is True
        assert preview.before.original_amount == preview.after.original_amount
        assert preview.before.base_amount == preview.after.base_amount
        assert preview.before.payment_allocations == preview.after.payment_allocations
        assert preview.before.split == preview.after.split
        assert preview.before.occurred_at == preview.after.occurred_at
    finally:
        store.close()


def test_unlocked_expense_can_change_presentation(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p52-unlocked",
    )
    try:
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert len(transport.post_calls) == 1
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.COMPLETED
    finally:
        store.close()


def test_presentation_expense_version_change_closes_without_rpc(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p52-preflight-version",
    )
    try:
        transport.expense["version"] = 4
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == "expense_version_conflict"
        assert transport.post_calls == []
        assert store.get_proposal(OWNER, proposal.proposal_id).status is c.ProposalStatus.CLOSED
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.CANCELLED
        assert turn.execution is None
    finally:
        store.close()


def test_server_40001_closes_the_dispatched_execution_and_never_retries(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p52-server-version",
    )
    try:
        transport.mode = "version_conflict"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == "expense_version_conflict"
        assert len(transport.post_calls) == 1
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.CANCELLED
        assert turn.execution_resolution is c.ExecutionResolution.CLOSED
        assert turn.execution is not None
        assert store.get_proposal(OWNER, proposal.proposal_id).status is c.ProposalStatus.CLOSED

        stored = store.get_proposal(OWNER, proposal.proposal_id)
        again = asyncio.run(gateway.execute(
            principal=principal,
            proposal=stored,
            request=_confirm_request(proposal),
            expected_state_revision=turn.state_revision,
            access_token="token-a",
        ))
        assert again.resolution is c.ExecutionResolution.CLOSED
        assert len(transport.post_calls) == 1
    finally:
        store.close()


def test_presentation_activity_version_is_not_the_guard(tmp_path) -> None:
    store, gateway, read_backend, transport, proposal, waiting, principal, _ = _setup(
        tmp_path, "p52-activity-version",
    )
    try:
        read_backend.version = 99
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert len(transport.post_calls) == 1
    finally:
        store.close()


def test_presentation_no_change_is_rejected(tmp_path) -> None:
    store = SQLiteAgentStore(tmp_path / "p52-no-change.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        read_backend = FakeReadBackend(version=5, base_currency="CNY")
        transport = FakePresentationTransport()
        gateway = LiveExpenseGateway(
            LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
            store, read_backend, transport,
        )
        with pytest.raises(LiveWriteError) as caught:
            asyncio.run(gateway.build_presentation_preview(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=_intent(icon_key="money"), bound_references=_all_references(turn_id),
                access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert caught.value.code == "no_change"
    finally:
        store.close()


def test_presentation_invalid_icon_is_rejected(tmp_path) -> None:
    store = SQLiteAgentStore(tmp_path / "p52-bad-icon.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        read_backend = FakeReadBackend(version=5, base_currency="CNY")
        transport = FakePresentationTransport()
        gateway = LiveExpenseGateway(
            LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
            store, read_backend, transport,
        )
        with pytest.raises(LiveWriteError) as caught:
            asyncio.run(gateway.build_presentation_preview(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=_intent(icon_key="not_an_icon"), bound_references=_all_references(turn_id),
                access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert caught.value.code == "invalid_icon_key"
    finally:
        store.close()


def test_presentation_deleted_row_is_not_pre_rejected(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p52-deleted",
    )
    try:
        transport.expense["is_deleted"] = True
        transport.mode = "reject"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.REJECTED
        assert len(transport.post_calls) == 1
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.FAILED
    finally:
        store.close()


def test_presentation_duplicate_confirmation_sends_one_rpc(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p52-duplicate",
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


def test_presentation_unknown_is_not_retried(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p52-unknown",
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
        again = asyncio.run(gateway.execute(
            principal=principal,
            proposal=stored,
            request=_confirm_request(proposal),
            expected_state_revision=turn.state_revision,
            access_token="token-a",
        ))
        assert again.resolution is c.ExecutionResolution.UNKNOWN
        assert len(transport.post_calls) == 1
    finally:
        store.close()
