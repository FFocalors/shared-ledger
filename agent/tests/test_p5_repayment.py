from __future__ import annotations

"""P5.5a repayment preview/create: request_id, version guard, FIFO/TARGETED."""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from agent.app import contracts as c
from agent.app.p5_write import LiveExpenseGateway, LiveWriteConfig, LiveWriteError
from agent.app.ports import Principal
from agent.app.store import SQLiteAgentStore
from test_p5_live_write import ACTIVITY, FakeReadBackend, P1, P2, UNIT
from test_sqlite_persistence import OWNER, _session, _submit, _wait_with_proposal


EXPENSE = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
TRANSFER = uuid.UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")


class FakeRepaymentTransport:
    def __init__(self) -> None:
        self.preview_calls: list[dict] = []
        self.create_calls: list[dict] = []
        self.candidate_calls: list[dict] = []
        self.mode = "success"
        self.transfer_rows: list[dict] = []
        self.targets: list[uuid.UUID] = []
        self.amount = "10.0"
        self.currency = "CNY"
        self.mode_value = "FIFO"

    def _preview_rows(self) -> list[dict]:
        return [{
            "expense_id": str(EXPENSE),
            "ledger_unit_id": str(UNIT),
            "allocation_mode": self.mode_value,
            "payment_currency": self.currency,
            "payment_amount": self.amount,
            "original_currency": self.currency,
            "original_amount": self.amount,
            "base_amount": self.amount,
            "fx_rate": "1",
            "remaining_original_amount": "5.0",
            "remaining_base_amount": "5.0",
            "source_financial_version": 5,
        }]

    def post_json(self, url, headers, payload, *, timeout, max_response_bytes):  # noqa: ANN001
        if url.endswith("/preview_expense_repayment"):
            self.preview_calls.append(dict(payload))
            if self.mode == "preview_reject":
                return 400, json.dumps({
                    "code": "23514", "message": "repayment exceeds selected residual or bilateral debt",
                }).encode()
            return 200, json.dumps(self._preview_rows()).encode()
        if url.endswith("/list_transfer_expense_candidates"):
            self.candidate_calls.append(dict(payload))
            return 200, json.dumps([{
                "expense_id": str(EXPENSE), "ledger_unit_id": str(UNIT),
                "title": "Lunch", "remaining_original_amount": "10.0",
                "remaining_base_amount": "10.0",
            }]).encode()
        if url.endswith("/create_expense_repayment_v2"):
            self.create_calls.append({"url": url, "payload": dict(payload)})
            if self.mode == "ambiguous":
                raise LiveWriteError("upstream_ambiguous", ambiguous=True)
            if self.mode == "version":
                return 400, json.dumps({
                    "code": "40001", "message": "repayment debt changed while committing; refresh the plan",
                }).encode()
            if self.mode == "reject_over":
                return 400, json.dumps({
                    "code": "23514", "message": "repayment exceeds selected residual or bilateral debt",
                }).encode()
            if self.mode == "reject_participant":
                return 404, json.dumps({
                    "code": "P0002", "message": "transfer participant was not found",
                }).encode()
            if self.mode == "reject_permission":
                return 403, json.dumps({
                    "code": "42501", "message": "actor is not allowed to record this repayment",
                }).encode()
            return 200, json.dumps([{
                "transfer_id": str(TRANSFER),
                "amount": self.amount,
                "currency": self.currency,
                "mode": self.mode_value,
                "financial_version": 6,
            }]).encode()
        return 200, b"[]"

    def get_json(self, url, headers, *, timeout, max_response_bytes):  # noqa: ANN001
        if "/rest/v1/transfers" in url:
            return 200, json.dumps(self.transfer_rows).encode()
        return 200, b"[]"


def _intent(
    *, mode: str = "FIFO", targets: list[uuid.UUID] | None = None,
    amount: str = "10.0", currency: str = "CNY",
) -> c.RepaymentIntent:
    return c.RepaymentIntent(
        kind="settlement.repayment",
        activity_id=ACTIVITY,
        from_participant_id=P1,
        to_participant_id=P2,
        amount=amount,
        currency=currency,
        mode=mode,
        target_expense_ids=targets or [],
    )


def _setup(tmp_path, name: str, *, intent: c.RepaymentIntent | None = None):
    store = SQLiteAgentStore(tmp_path / f"{name}.sqlite3", admission_enabled=True)
    store.start()
    session = _session(store, OWNER)
    _, turn_id = _submit(store, session, OWNER)
    read_backend = FakeReadBackend(version=5, base_currency="CNY")
    transport = FakeRepaymentTransport()
    payload_intent = intent or _intent()
    transport.mode_value = payload_intent.mode
    gateway = LiveExpenseGateway(
        LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
        store, read_backend, transport,
    )
    proposal = asyncio.run(gateway.build_repayment_preview(
        owner_user_id=OWNER,
        session_id=session,
        turn_id=turn_id,
        intent=payload_intent,
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


def test_repayment_preview_uses_the_server_preview_and_writes_nothing(tmp_path) -> None:
    store, _, _, transport, proposal, waiting, _, _ = _setup(tmp_path, "p55-preview")
    try:
        assert waiting.state is c.TurnState.WAIT_CONFIRM
        assert proposal.operation == "settlement.repayment"
        assert isinstance(proposal.canonical_command, c.FixedRepaymentCommand)
        assert proposal.canonical_command.expected_financial_version == "5"
        assert isinstance(proposal.preview, c.RepaymentPreview)
        assert proposal.preview.expected_financial_version == "5"
        assert proposal.preview.allocations[0].expense_id == EXPENSE
        assert transport.preview_calls and transport.preview_calls[0]["expected_financial_version"] == 5
        assert transport.create_calls == []
    finally:
        store.close()


def test_repayment_confirmation_reaches_the_create_rpc(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p55-confirm",
    )
    try:
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "repayment_created"
        assert len(transport.create_calls) == 1
        call = transport.create_calls[0]
        assert call["url"].endswith("/rest/v1/rpc/create_expense_repayment_v2")
        expected_request_id = c.derive_execution_id(
            OWNER, proposal.proposal_id, proposal.revision,
        )
        assert call["payload"] == {
            "activity_id": str(ACTIVITY),
            "from_participant_id": str(P1),
            "to_participant_id": str(P2),
            "amount": "10.0",
            "currency": "CNY",
            "mode": "FIFO",
            "target_expense_ids": [],
            "occurred_at": proposal.canonical_command.occurred_at.isoformat(),
            "on_behalf_of_participant_id": None,
            "expected_financial_version": 5,
            "request_id": str(expected_request_id),
        }
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.COMPLETED
    finally:
        store.close()


def test_repayment_duplicate_confirmation_uses_one_request_id_and_rpc(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p55-duplicate",
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
        assert len(transport.create_calls) == 1
    finally:
        store.close()


def test_repayment_version_change_closes_without_create_rpc(tmp_path) -> None:
    store, gateway, read_backend, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p55-version",
    )
    try:
        read_backend.version = 6
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert transport.create_calls == []
        assert store.get_proposal(OWNER, proposal.proposal_id).status is c.ProposalStatus.CLOSED
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.CANCELLED
        assert turn.execution is None
    finally:
        store.close()


def test_repayment_server_40001_closes_dispatched_execution(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p55-server-version",
    )
    try:
        transport.mode = "version"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == "repayment_version_conflict"
        assert len(transport.create_calls) == 1
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.CANCELLED
        assert turn.execution_resolution is c.ExecutionResolution.CLOSED
    finally:
        store.close()


@pytest.mark.parametrize(
    ("mode", "code"),
    [
        ("reject_over", "constraint_rejected"),
        ("reject_participant", "not_found"),
        ("reject_permission", "permission_denied"),
    ],
)
def test_repayment_server_rejection_is_terminal(tmp_path, mode, code) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, f"p55-{mode}",
    )
    try:
        transport.mode = mode
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.REJECTED
        assert outcome.code == code
        assert len(transport.create_calls) == 1
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.FAILED
    finally:
        store.close()


def test_repayment_preview_rejection_prevents_a_proposal(tmp_path) -> None:
    store = SQLiteAgentStore(tmp_path / "p55-preview-reject.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        read_backend = FakeReadBackend(version=5, base_currency="CNY")
        transport = FakeRepaymentTransport()
        transport.mode = "preview_reject"
        gateway = LiveExpenseGateway(
            LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
            store, read_backend, transport,
        )
        with pytest.raises(LiveWriteError) as caught:
            asyncio.run(gateway.build_repayment_preview(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=_intent(), access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert caught.value.code == "repayment_exceeds_debt_or_target"
        assert transport.create_calls == []
    finally:
        store.close()


def test_repayment_unknown_reconciles_by_request_id(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p55-unknown",
    )
    try:
        transport.mode = "ambiguous"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.UNKNOWN
        assert len(transport.create_calls) == 1
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.RECOVERING

        request_id = c.derive_execution_id(OWNER, proposal.proposal_id, proposal.revision)
        transport.transfer_rows = [{
            "id": str(TRANSFER),
            "type": "settlement",
            "amount": "10.0",
            "currency": "CNY",
            "request_payload": {
                "activity_id": str(ACTIVITY),
                "from_participant_id": str(P1),
                "to_participant_id": str(P2),
                "amount": "10.0",
                "currency": "CNY",
                "mode": "FIFO",
                "target_expense_ids": [],
                "on_behalf_of_participant_id": None,
                "expected_financial_version": 5,
            },
            "request_result": {
                "transfer_id": str(TRANSFER),
                "amount": "10.0",
                "currency": "CNY",
                "mode": "FIFO",
                "financial_version": 6,
            },
        }]
        stored = store.get_proposal(OWNER, proposal.proposal_id)
        reconciled = asyncio.run(gateway.reconcile(principal, stored, "token-a"))
        assert reconciled.resolution is c.ExecutionResolution.SUCCEEDED
        assert reconciled.code == "repayment_created"
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.COMPLETED
        assert len(transport.create_calls) == 1
    finally:
        store.close()


def test_repayment_unknown_without_a_transfer_stays_unknown(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p55-unknown-absent",
    )
    try:
        transport.mode = "ambiguous"
        assert _execute(gateway, principal, proposal, waiting).resolution is c.ExecutionResolution.UNKNOWN
        stored = store.get_proposal(OWNER, proposal.proposal_id)
        outcome = asyncio.run(gateway.reconcile(principal, stored, "token-a"))
        assert outcome.resolution is c.ExecutionResolution.UNKNOWN
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.RECOVERING
        assert len(transport.create_calls) == 1
    finally:
        store.close()


def test_targeted_repayment_sends_target_expense_ids(tmp_path) -> None:
    intent = _intent(mode="TARGETED", targets=[EXPENSE])
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p55-targeted", intent=intent,
    )
    try:
        assert isinstance(proposal.preview, c.RepaymentPreview)
        assert proposal.preview.target_expense_ids == [EXPENSE]
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert transport.create_calls[0]["payload"]["mode"] == "TARGETED"
        assert transport.create_calls[0]["payload"]["target_expense_ids"] == [str(EXPENSE)]
    finally:
        store.close()
