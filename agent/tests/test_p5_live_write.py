from __future__ import annotations

"""P5.0 live write path: preview, version re-read, execution, four outcomes.

The transport and the authoritative read adapter are faked; the Store, the
proposal contract, the Gateway and the state machine are real.
"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from agent.app import contracts as c
from agent.app.p2_backend import (
    BackendReadError, P2ActivityDTO, P2LedgerUnitDTO, P2ParticipantDTO, P2ResolvedScope,
)
from agent.app.p5_write import LiveExpenseGateway, LiveWriteConfig, LiveWriteError
from agent.app.ports import Principal
from agent.app.store import SQLiteAgentStore
from test_sqlite_persistence import OWNER, _session, _submit, _wait_with_proposal


ACTIVITY = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
UNIT = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
P1 = uuid.UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
P2 = uuid.UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")


class FakeReadBackend:
    """Authoritative-read stand-in: only the calls the Gateway actually makes."""

    def __init__(self, *, version: int = 0, base_currency: str = "CNY", archived: bool = False) -> None:
        self.version = version
        self.base_currency = base_currency
        self.archived_at = datetime.now(timezone.utc) if archived else None
        self.calls: list[tuple] = []
        self.participants = (
            P2ParticipantDTO(P1, ACTIVITY, "Ann", 1, False),
            P2ParticipantDTO(P2, ACTIVITY, "Ben", 2, False),
        )
        self.ledger_units = (
            P2LedgerUnitDTO(UNIT, ACTIVITY, "Main", "main", False, False),
        )

    async def resolve_scope(self, grant, request):  # noqa: ANN001
        self.calls.append(("resolve", request.ui_activity_id_hint))
        return P2ResolvedScope(
            mode="activity",
            activity=P2ActivityDTO(
                ACTIVITY, "Trip", "normal", self.base_currency, False, False,
                self.archived_at, self.version,
            ),
            participants=self.participants,
            ledger_units=self.ledger_units,
            child_scopes=(),
            observed_at=datetime.now(timezone.utc),
        )

    async def verify_financial_versions(self, grant, expected):  # noqa: ANN001
        self.calls.append(("verify", dict(expected)))
        for activity_id, version in expected.items():
            if activity_id != ACTIVITY or version != self.version:
                raise BackendReadError("data_changed_during_read")


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.mode = "success"
        self.expense_id = uuid.uuid4()

    def post_json(self, url, headers, payload, *, timeout, max_response_bytes):  # noqa: ANN001
        self.calls.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        if self.mode == "ambiguous":
            raise LiveWriteError("upstream_ambiguous", ambiguous=True)
        if self.mode == "unreachable":
            raise LiveWriteError("upstream_unreachable", retryable=True)
        if self.mode == "reject":
            return 403, json.dumps({"code": "42501", "message": "not a member"}).encode()
        return 200, json.dumps([{
            "expense_id": str(self.expense_id), "base_amount": "12.5", "version": 1,
        }]).encode()


def _intent(*, currency: str = "CNY", amount: str = "12.50") -> c.ExpenseCreateIntent:
    return c.ExpenseCreateIntent(
        kind="expense.create",
        ledger_unit_ref=c.LedgerUnitRef.U01,
        title="Lunch",
        original_amount=amount,
        original_currency=currency,
        payment_allocations=[c.PaymentAllocation(participant_ref=c.ParticipantRef.P01, amount=amount)],
        split=c.EqualSplitIntent(mode="equal", participant_refs=[c.ParticipantRef.P01, c.ParticipantRef.P02]),
        occurred_at=None,
    )


def _references(turn_id: uuid.UUID) -> list[c.BoundReference]:
    return [
        c.BoundLedgerUnitReference(
            kind="ledger_unit", ref=c.LedgerUnitRef.U01, entity_id=UNIT,
            source_turn_id=turn_id, scope_activity_id=ACTIVITY,
        ),
        c.BoundParticipantReference(
            kind="participant", ref=c.ParticipantRef.P01, entity_id=P1,
            source_turn_id=turn_id, scope_activity_id=ACTIVITY,
        ),
        c.BoundParticipantReference(
            kind="participant", ref=c.ParticipantRef.P02, entity_id=P2,
            source_turn_id=turn_id, scope_activity_id=ACTIVITY,
        ),
    ]


def _confirm_request(proposal: c.ProposalRecord, *, request_id: uuid.UUID | None = None) -> c.ConfirmProposalRequest:
    return c.ConfirmProposalRequest(
        client_request_id=request_id or uuid.uuid4(),
        expected_proposal_revision=proposal.revision,
        command_digest=proposal.command_digest,
        confirmation_nonce=proposal.confirmation_nonce,
    )


def _setup(tmp_path, name: str, *, version: int = 0, currency: str = "CNY"):
    store = SQLiteAgentStore(tmp_path / f"{name}.sqlite3", admission_enabled=True)
    store.start()
    session = _session(store, OWNER)
    _, turn_id = _submit(store, session, OWNER)
    read_backend = FakeReadBackend(version=version, base_currency="CNY")
    transport = FakeTransport()
    gateway = LiveExpenseGateway(
        LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
        store, read_backend, transport,
    )
    proposal = asyncio.run(gateway.build_preview(
        owner_user_id=OWNER,
        session_id=session,
        turn_id=turn_id,
        intent=_intent(currency=currency),
        bound_references=_references(turn_id),
        access_token="token-a",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        agent_disable_revision=0,
        now=datetime.now(timezone.utc),
    ))
    waiting = _wait_with_proposal(store, OWNER, turn_id, proposal)
    principal = Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1))
    return store, gateway, read_backend, transport, proposal, waiting, principal, turn_id


def _execute(gateway, principal, proposal, waiting, *, request_id=None):
    return asyncio.run(gateway.execute(
        principal=principal,
        proposal=proposal,
        request=_confirm_request(proposal, request_id=request_id),
        expected_state_revision=waiting.state_revision,
        access_token="token-a",
    ))


def test_preview_reads_server_state_and_writes_nothing(tmp_path) -> None:
    store, _, read_backend, transport, proposal, waiting, _, _ = _setup(tmp_path, "p5-preview", version=7)
    try:
        assert waiting.state is c.TurnState.WAIT_CONFIRM
        assert proposal.mode == "backend"
        assert proposal.canonical_command is not None
        assert proposal.canonical_command.expected_financial_version == "7"
        assert proposal.preconditions is not None
        assert proposal.preconditions.activity_financial_version == "7"
        assert proposal.preview is not None and proposal.preview.simulation is False
        assert proposal.preview.after.ledger_unit_id == UNIT
        assert proposal.preview.after.base_amount == "12.50"
        assert transport.calls == []          # no RPC before confirmation
        assert read_backend.calls            # preview did read authoritative state
    finally:
        store.close()


def test_unconfirmed_proposal_calls_no_rpc(tmp_path) -> None:
    store, _, _, transport, proposal, _, _, _ = _setup(tmp_path, "p5-unconfirmed")
    try:
        assert transport.calls == []
        assert store.get_proposal(OWNER, proposal.proposal_id).status is c.ProposalStatus.PENDING
    finally:
        store.close()


def test_confirmation_writes_once_with_the_real_rpc_shape(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(tmp_path, "p5-confirm")
    try:
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert len(transport.calls) == 1
        call = transport.calls[0]
        assert call["url"].endswith("/rest/v1/rpc/create_expense_auto_rate")
        assert call["headers"]["apikey"] == "anon-key"
        assert call["headers"]["Authorization"] == "Bearer token-a"
        assert call["payload"] == {
            "ledger_unit_id": str(UNIT),
            "title": "Lunch",
            "original_amount": "12.50",
            "original_currency": "CNY",
            "split_method": "equal",
            "payments": [{"participant_id": str(P1), "amount": "12.50"}],
            "manual_splits": [],
            "aa_participant_ids": [str(P1), str(P2)],
            "occurred_at": proposal.canonical_command.occurred_at.isoformat(),
            "note": None,
            "original_expense_id": None,
        }
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.COMPLETED
        assert turn.execution_resolution is c.ExecutionResolution.SUCCEEDED
        assert store.get_proposal(OWNER, proposal.proposal_id).status is c.ProposalStatus.CONFIRMED
    finally:
        store.close()


def test_duplicate_confirmation_never_sends_a_second_rpc(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(tmp_path, "p5-duplicate")
    try:
        first = _execute(gateway, principal, proposal, waiting, request_id=uuid.uuid4())
        assert first.resolution is c.ExecutionResolution.SUCCEEDED
        assert len(transport.calls) == 1

        stored = store.get_proposal(OWNER, proposal.proposal_id)
        second = asyncio.run(gateway.execute(
            principal=principal,
            proposal=stored,
            request=_confirm_request(proposal, request_id=uuid.uuid4()),
            expected_state_revision=store.get_turn(OWNER, turn_id).record.turn.state_revision,
            access_token="token-a",
        ))
        assert second.resolution is c.ExecutionResolution.SUCCEEDED
        assert len(transport.calls) == 1
    finally:
        store.close()


def test_concurrent_financial_change_closes_the_preview_without_rpc(tmp_path) -> None:
    store, gateway, read_backend, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p5-concurrent", version=3,
    )
    try:
        read_backend.version = 4  # some other write landed after the preview
        outcome = _execute(gateway, principal, proposal, waiting)

        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert transport.calls == []
        assert store.get_proposal(OWNER, proposal.proposal_id).status is c.ProposalStatus.CLOSED
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.CANCELLED
        assert turn.execution is None
    finally:
        store.close()


def test_archived_activity_closes_the_preview_without_rpc(tmp_path) -> None:
    store, gateway, read_backend, transport, proposal, waiting, principal, _ = _setup(
        tmp_path, "p5-archived",
    )
    try:
        read_backend.archived_at = datetime.now(timezone.utc)
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert transport.calls == []
    finally:
        store.close()


def test_server_rejection_is_a_terminal_rejected_result(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(tmp_path, "p5-rejected")
    try:
        transport.mode = "reject"
        outcome = _execute(gateway, principal, proposal, waiting)

        assert outcome.resolution is c.ExecutionResolution.REJECTED
        assert len(transport.calls) == 1
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.FAILED
        assert turn.execution_resolution is c.ExecutionResolution.REJECTED
        assert store.get_proposal(OWNER, proposal.proposal_id).status is c.ProposalStatus.REJECTED
    finally:
        store.close()


def test_ambiguous_transport_result_is_unknown_and_is_not_retried(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(tmp_path, "p5-unknown")
    try:
        transport.mode = "ambiguous"
        outcome = _execute(gateway, principal, proposal, waiting)

        assert outcome.resolution is c.ExecutionResolution.UNKNOWN
        assert len(transport.calls) == 1
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.RECOVERING
        assert turn.execution_resolution is c.ExecutionResolution.UNKNOWN

        # A later confirmation under the original key must not send it again.
        stored = store.get_proposal(OWNER, proposal.proposal_id)
        again = asyncio.run(gateway.execute(
            principal=principal,
            proposal=stored,
            request=_confirm_request(proposal, request_id=uuid.uuid4()),
            expected_state_revision=turn.state_revision,
            access_token="token-a",
        ))
        assert again.resolution is c.ExecutionResolution.UNKNOWN
        assert len(transport.calls) == 1
    finally:
        store.close()


def test_foreign_currency_is_outside_p5_and_never_reaches_the_rpc(tmp_path) -> None:
    with pytest.raises(LiveWriteError) as caught:
        _setup(tmp_path, "p5-foreign", currency="USD")
    assert caught.value.code == "foreign_currency_not_in_p5"
