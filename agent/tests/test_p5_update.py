from __future__ import annotations

"""P5.1 financial update: preview, dual version preflight, and outcomes.

The PostgREST transport is faked; the Store, contracts, Gateway and state
machine are real. Every test asserts both the business effect and the RPC count.
"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlsplit

import pytest

from agent.app import contracts as c
from agent.app.p5_write import LiveExpenseGateway, LiveWriteConfig, LiveWriteError
from agent.app.ports import Principal, ScopeDenied
from agent.app.store import SQLiteAgentStore
from test_p5_live_write import (
    ACTIVITY, FakeReadBackend, P1, P2, UNIT, _references,
)
from test_sqlite_persistence import OWNER, _session, _submit, _wait_with_proposal


EXPENSE = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")


class FakeUpdateTransport:
    def __init__(self) -> None:
        self.get_calls: list[str] = []
        self.post_calls: list[dict] = []
        self.mode = "success"
        self.expense = {
            "id": str(EXPENSE),
            "ledger_unit_id": str(UNIT),
            "title": "Lunch",
            "original_amount": "12.50",
            "original_currency": "CNY",
            "base_amount": "12.5",
            "split_method": "aa",
            "occurred_at": "2026-10-25T12:00:00+00:00",
            "note": None,
            "original_expense_id": None,
            "version": 3,
            "is_deleted": False,
            "financial_locked": False,
            "icon_key": "money",
        }
        self.payments = [{"participant_id": str(P1), "amount": "12.50"}]
        self.splits = [
            {"participant_id": str(P1), "amount": "6.25"},
            {"participant_id": str(P2), "amount": "6.25"},
        ]
        self.units = [
            {"id": str(UNIT), "activity_id": str(ACTIVITY), "name": "Main", "is_deleted": False},
        ]

    def get_json(self, url, headers, *, timeout, max_response_bytes):  # noqa: ANN001
        self.get_calls.append(url)
        parsed = urlsplit(url)
        table = parsed.path.rsplit("/", 1)[-1]
        params = dict(parse_qsl(parsed.query))
        if table == "expenses":
            if "id" in params:
                return 200, json.dumps([self.expense]).encode()
            return 200, json.dumps([{
                "id": self.expense["id"],
                "ledger_unit_id": self.expense["ledger_unit_id"],
                "title": self.expense["title"],
                "version": self.expense["version"],
            }]).encode()
        if table == "payments":
            return 200, json.dumps(self.payments).encode()
        if table == "splits":
            return 200, json.dumps(self.splits).encode()
        if table == "ledger_units":
            return 200, json.dumps(self.units).encode()
        return 200, b"[]"

    def post_json(self, url, headers, payload, *, timeout, max_response_bytes):  # noqa: ANN001
        self.post_calls.append({"url": url, "payload": dict(payload)})
        if self.mode == "ambiguous":
            raise LiveWriteError("upstream_ambiguous", ambiguous=True)
        if self.mode == "reject":
            return 403, json.dumps({"code": "23514", "message": "locked"}).encode()
        return 200, json.dumps([{
            "updated_expense_id": self.expense["id"],
            "base_amount": "15.0",
            "version": 4,
        }]).encode()


def _update_intent() -> c.ExpenseUpdateIntent:
    return c.ExpenseUpdateIntent(
        kind="expense.update",
        expense_ref=c.ExpenseRef.SELECTED,
        title=None,
        original_amount="15.00",
        original_currency=None,
        payment_allocations=[
            c.PaymentAllocation(participant_ref=c.ParticipantRef.P01, amount="15.00"),
        ],
        split=None,
        note=None,
        occurred_at=None,
    )


def _all_references(turn_id: uuid.UUID) -> list[c.BoundReference]:
    return [
        *_references(turn_id),
        c.BoundExpenseReference(
            kind="expense", ref=c.ExpenseRef.SELECTED, entity_id=EXPENSE,
            source_turn_id=turn_id, scope_activity_id=ACTIVITY,
        ),
    ]


def _setup(tmp_path, name: str, *, activity_version: int = 5):
    store = SQLiteAgentStore(tmp_path / f"{name}.sqlite3", admission_enabled=True)
    store.start()
    session = _session(store, OWNER)
    _, turn_id = _submit(store, session, OWNER)
    read_backend = FakeReadBackend(version=activity_version, base_currency="CNY")
    transport = FakeUpdateTransport()
    gateway = LiveExpenseGateway(
        LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
        store, read_backend, transport,
    )
    proposal = asyncio.run(gateway.build_update_preview(
        owner_user_id=OWNER,
        session_id=session,
        turn_id=turn_id,
        intent=_update_intent(),
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


def test_update_preview_reads_both_versions_without_rpc(tmp_path) -> None:
    store, _, read_backend, transport, proposal, waiting, _, _ = _setup(tmp_path, "p5u-preview")
    try:
        assert waiting.state is c.TurnState.WAIT_CONFIRM
        assert proposal.operation == "expense.update"
        assert proposal.canonical_command is not None
        assert isinstance(proposal.canonical_command, c.FixedExpenseUpdateCommand)
        assert proposal.canonical_command.expected_expense_version == "3"
        assert proposal.canonical_command.expected_financial_version == str(read_backend.version)
        assert proposal.preconditions is not None
        assert proposal.preconditions.expense_version == "3"
        assert proposal.preview is not None
        assert proposal.preview.before is not None
        assert proposal.preview.after.expense_version == "4"
        changed = {item.field for item in proposal.preview.changes}
        assert "original_amount" in changed
        assert "base_amount" in changed
        assert transport.post_calls == []
        assert transport.get_calls
    finally:
        store.close()


def test_update_confirmation_writes_once_with_the_real_rpc_shape(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(tmp_path, "p5u-confirm")
    try:
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert len(transport.post_calls) == 1
        call = transport.post_calls[0]
        assert call["url"].endswith("/rest/v1/rpc/update_expense_auto_rate")
        assert call["payload"] == {
            "expense_id": str(EXPENSE),
            "ledger_unit_id": str(UNIT),
            "title": "Lunch",
            "original_amount": "15.00",
            "original_currency": "CNY",
            "split_method": "aa",
            "payments": [{"participant_id": str(P1), "amount": "15.00"}],
            "manual_splits": [],
            "aa_participant_ids": [str(P1), str(P2)],
            "occurred_at": proposal.canonical_command.patch.occurred_at.isoformat(),
            "note": None,
            "original_expense_id": None,
        }
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.COMPLETED
        assert store.get_proposal(OWNER, proposal.proposal_id).status is c.ProposalStatus.CONFIRMED
    finally:
        store.close()


def test_update_duplicate_confirmation_never_sends_a_second_rpc(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(tmp_path, "p5u-duplicate")
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


def test_update_concurrent_expense_version_closes_without_rpc(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(tmp_path, "p5u-version")
    try:
        transport.expense["version"] = 4
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == "expense_changed"
        assert transport.post_calls == []
        assert store.get_proposal(OWNER, proposal.proposal_id).status is c.ProposalStatus.CLOSED
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.CANCELLED
    finally:
        store.close()


def test_update_concurrent_activity_version_closes_without_rpc(tmp_path) -> None:
    store, gateway, read_backend, transport, proposal, waiting, principal, _ = _setup(tmp_path, "p5u-activity-version")
    try:
        read_backend.version = 6
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert transport.post_calls == []
    finally:
        store.close()


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("financial_locked", True, "expense_financial_locked"),
        ("is_deleted", True, "expense_deleted"),
        ("original_expense_id", str(uuid.uuid4()), "refund_update_not_in_p5"),
    ],
)
def test_update_rejection_boundaries_close_without_rpc(tmp_path, field, value, code) -> None:
    store, gateway, _, transport, proposal, waiting, principal, _ = _setup(
        tmp_path, f"p5u-{field}",
    )
    try:
        transport.expense[field] = value
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == code
        assert transport.post_calls == []
    finally:
        store.close()


def test_update_archived_activity_closes_without_rpc(tmp_path) -> None:
    store, gateway, read_backend, transport, proposal, waiting, principal, _ = _setup(
        tmp_path, "p5u-archived",
    )
    try:
        read_backend.archived_at = datetime.now(timezone.utc)
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert transport.post_calls == []
    finally:
        store.close()


def test_update_server_rejection_is_terminal(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(tmp_path, "p5u-rejected")
    try:
        transport.mode = "reject"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.REJECTED
        assert len(transport.post_calls) == 1
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.FAILED
        assert turn.execution_resolution is c.ExecutionResolution.REJECTED
    finally:
        store.close()


def test_update_unknown_is_not_retried(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(tmp_path, "p5u-unknown")
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


def test_update_preview_refuses_locked_and_refund_rows(tmp_path) -> None:
    store = SQLiteAgentStore(tmp_path / "p5u-preview-refusals.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        read_backend = FakeReadBackend(version=5, base_currency="CNY")
        transport = FakeUpdateTransport()
        gateway = LiveExpenseGateway(
            LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
            store, read_backend, transport,
        )
        transport.expense["financial_locked"] = True
        with pytest.raises(LiveWriteError) as locked:
            asyncio.run(gateway.build_update_preview(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=_update_intent(), bound_references=_all_references(turn_id),
                access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert locked.value.code == "expense_financial_locked"

        transport.expense["financial_locked"] = False
        transport.expense["original_expense_id"] = str(uuid.uuid4())
        with pytest.raises(LiveWriteError) as refund:
            asyncio.run(gateway.build_update_preview(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=_update_intent(), bound_references=_all_references(turn_id),
                access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert refund.value.code == "refund_update_not_in_p5"
    finally:
        store.close()
