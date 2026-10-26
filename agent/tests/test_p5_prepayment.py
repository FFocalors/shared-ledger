from __future__ import annotations

"""P5.6 large-activity prepayment: preview, create, return, version guard."""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from agent.app import contracts as c
from agent.app.p5_write import LiveExpenseGateway, LiveWriteConfig, LiveWriteError
from agent.app.ports import Principal
from agent.app.store import SQLiteAgentStore
from test_p5_live_write import ACTIVITY, FakeReadBackend, P1, P2
from test_sqlite_persistence import OWNER, _session, _submit, _wait_with_proposal


TRANSFER = uuid.UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")


class FakePrepaymentTransport:
    def __init__(self) -> None:
        self.preview_calls: list[dict] = []
        self.create_calls: list[dict] = []
        self.return_calls: list[dict] = []
        self.get_calls: list[str] = []
        self.mode = "success"
        self.version = 5
        self.balance = "0.0000"
        self.settlement = "4.0000"
        self.prepayment = "6.0000"
        self.new_balance = "6.0000"
        self.remaining_balance = "3.0000"
        self.transfer_rows: list[dict] = []

    def _preview_row(self, payload: dict) -> dict:
        return {
            "activity_id": str(ACTIVITY),
            "owner_participant_id": payload["owner_participant_id"],
            "custodian_participant_id": payload["custodian_participant_id"],
            "amount": payload["amount"],
            "settlement_amount": self.settlement,
            "prepayment_amount": self.prepayment,
            "new_balance": self.new_balance,
            "currency": payload["currency"],
            "financial_version": self.version,
        }

    def post_json(self, url, headers, payload, *, timeout, max_response_bytes):  # noqa: ANN001
        if url.endswith("/preview_prepayment"):
            self.preview_calls.append(dict(payload))
            if self.mode == "preview_normal":
                return 400, json.dumps({
                    "code": "23514", "message": "普通活动不支持预存",
                }).encode()
            if self.mode == "preview_archived":
                return 400, json.dumps({
                    "code": "55000", "message": "archived activity is read-only",
                }).encode()
            return 200, json.dumps([self._preview_row(payload)]).encode()
        if url.endswith("/create_prepayment_v2"):
            self.create_calls.append({"url": url, "payload": dict(payload)})
            if self.mode == "ambiguous":
                raise LiveWriteError("upstream_ambiguous", ambiguous=True)
            if self.mode == "version":
                return 400, json.dumps({
                    "code": "40001", "message": "financial_version mismatch; refresh the plan",
                }).encode()
            if self.mode == "reject_normal":
                return 400, json.dumps({
                    "code": "23514", "message": "普通活动不支持预存",
                }).encode()
            if self.mode == "reject_not_member":
                return 403, json.dumps({
                    "code": "42501", "message": "caller is not an activity member",
                }).encode()
            if self.mode == "idempotent_unavailable":
                return 400, json.dumps({
                    "code": "55000", "message": "idempotent result is unavailable",
                }).encode()
            return 200, json.dumps([{
                "transfer_id": str(TRANSFER),
                "settlement_amount": self.settlement,
                "prepayment_amount": self.prepayment,
                "new_balance": self.new_balance,
                "currency": payload["currency"],
                "financial_version": 6,
            }]).encode()
        if url.endswith("/create_prepayment_return_v2"):
            self.return_calls.append({"url": url, "payload": dict(payload)})
            if self.mode == "ambiguous":
                raise LiveWriteError("upstream_ambiguous", ambiguous=True)
            if self.mode == "version":
                return 400, json.dumps({
                    "code": "40001", "message": "financial_version mismatch; refresh the plan",
                }).encode()
            if self.mode == "reject_balance":
                return 400, json.dumps({
                    "code": "23514",
                    "message": "prepayment return exceeds available balance",
                }).encode()
            if self.mode == "reject_permission":
                return 403, json.dumps({
                    "code": "42501", "message": "actor is not allowed to return this prepayment",
                }).encode()
            return 200, json.dumps([{
                "transfer_id": str(TRANSFER),
                "amount": payload["amount"],
                "currency": payload["currency"],
                "remaining_balance": self.remaining_balance,
                "financial_version": 6,
            }]).encode()
        return 200, b"[]"

    def get_json(self, url, headers, *, timeout, max_response_bytes):  # noqa: ANN001
        self.get_calls.append(url)
        if "/rest/v1/transfers" in url:
            return 200, json.dumps(self.transfer_rows).encode()
        if "/rest/v1/prepayment_accounts" in url:
            if self.mode == "balance_error":
                return 500, b'{"message":"unavailable"}'
            return 200, json.dumps([{"id": str(uuid.uuid4()), "balance": self.balance}]).encode()
        return 200, b"[]"


def _create_intent(*, amount: str = "10.0", currency: str = "CNY") -> c.PrepaymentIntent:
    return c.PrepaymentIntent(
        kind="prepayment.create",
        activity_id=ACTIVITY,
        owner_participant_id=P1,
        custodian_participant_id=P2,
        amount=amount,
        currency=currency,
    )


def _return_intent(*, amount: str = "3.0", currency: str = "CNY") -> c.PrepaymentReturnIntent:
    return c.PrepaymentReturnIntent(
        kind="prepayment.return",
        activity_id=ACTIVITY,
        owner_participant_id=P1,
        custodian_participant_id=P2,
        amount=amount,
        currency=currency,
    )


def _confirm_request(proposal: c.ProposalRecord, *, request_id: uuid.UUID | None = None):
    return c.ConfirmProposalRequest(
        client_request_id=request_id or uuid.uuid4(),
        expected_proposal_revision=proposal.revision,
        command_digest=proposal.command_digest,
        confirmation_nonce=proposal.confirmation_nonce,
    )


def _execute(gateway, principal, proposal, waiting):
    return asyncio.run(gateway.execute(
        principal=principal,
        proposal=proposal,
        request=_confirm_request(proposal),
        expected_state_revision=waiting.state_revision,
        access_token="token-a",
    ))


def _setup(
    tmp_path, name: str, *, is_return: bool = False,
    activity_type: str = "large", intent=None,
    multi_currency_enabled: bool = False,
):
    store = SQLiteAgentStore(tmp_path / f"{name}.sqlite3", admission_enabled=True)
    store.start()
    session = _session(store, OWNER)
    _, turn_id = _submit(store, session, OWNER)
    read_backend = FakeReadBackend(
        version=5, base_currency="CNY",
        activity_type=activity_type, multi_currency_enabled=multi_currency_enabled,
    )
    transport = FakePrepaymentTransport()
    gateway = LiveExpenseGateway(
        LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
        store, read_backend, transport,
    )
    payload_intent = intent or (_return_intent() if is_return else _create_intent())
    builder = (
        gateway.build_prepayment_return_preview if is_return
        else gateway.build_prepayment_preview
    )
    proposal = asyncio.run(builder(
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
    return (
        store, gateway, read_backend, transport, proposal, waiting, principal, turn_id,
    )


# --------------------------------------------------------------------- create


def test_prepayment_preview_shows_settlement_and_balance_parts(tmp_path) -> None:
    store, _, _, transport, proposal, waiting, _, _ = _setup(tmp_path, "p56-preview")
    try:
        assert waiting.state is c.TurnState.WAIT_CONFIRM
        assert proposal.operation == "prepayment.create"
        assert isinstance(proposal.canonical_command, c.FixedPrepaymentCommand)
        assert isinstance(proposal.preview, c.PrepaymentPreview)
        assert proposal.preview.settlement_amount == "4.0000"
        assert proposal.preview.prepayment_amount == "6.0000"
        assert proposal.preview.new_balance == "6.0000"
        assert proposal.preview.expected_financial_version == "5"
        command = proposal.canonical_command
        assert command.expected_settlement_amount == proposal.preview.settlement_amount
        assert command.expected_prepayment_amount == proposal.preview.prepayment_amount
        assert command.expected_new_balance == proposal.preview.new_balance
        assert command.on_behalf_of_participant_id is None
        assert transport.preview_calls == [{
            "activity_id": str(ACTIVITY),
            "owner_participant_id": str(P1),
            "custodian_participant_id": str(P2),
            "amount": "10.0",
            "currency": "CNY",
        }]
        assert transport.create_calls == []
    finally:
        store.close()


def test_prepayment_create_uses_request_id_and_server_version(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p56-create",
    )
    try:
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "prepayment_created"
        assert len(transport.create_calls) == 1
        call = transport.create_calls[0]
        assert call["url"].endswith("/rest/v1/rpc/create_prepayment_v2")
        payload = call["payload"]
        assert payload["activity_id"] == str(ACTIVITY)
        assert payload["owner_participant_id"] == str(P1)
        assert payload["custodian_participant_id"] == str(P2)
        assert payload["amount"] == "10.0"
        assert payload["currency"] == "CNY"
        assert payload["on_behalf_of_participant_id"] is None
        assert payload["expected_financial_version"] == 5
        assert payload["request_id"] == str(
            c.derive_execution_id(OWNER, proposal.proposal_id, proposal.revision)
        )
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.COMPLETED
        assert turn.execution_resolution is c.ExecutionResolution.SUCCEEDED
    finally:
        store.close()


@pytest.mark.parametrize("is_return", [False, True])
def test_normal_activity_is_refused_before_any_rpc(tmp_path, is_return) -> None:
    store = SQLiteAgentStore(tmp_path / f"p56-normal-{is_return}.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        read_backend = FakeReadBackend(version=5, base_currency="CNY", activity_type="normal")
        transport = FakePrepaymentTransport()
        gateway = LiveExpenseGateway(
            LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
            store, read_backend, transport,
        )
        builder = (
            gateway.build_prepayment_return_preview if is_return
            else gateway.build_prepayment_preview
        )
        intent = _return_intent() if is_return else _create_intent()
        with pytest.raises(LiveWriteError) as excinfo:
            asyncio.run(builder(
                owner_user_id=OWNER,
                session_id=session,
                turn_id=turn_id,
                intent=intent,
                access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0,
                now=datetime.now(timezone.utc),
            ))
        assert excinfo.value.code == "prepayment_requires_large_activity"
        assert transport.preview_calls == []
        assert transport.create_calls == []
        assert transport.return_calls == []
    finally:
        store.close()


def test_prepayment_currency_and_precision_are_guarded_locally(tmp_path) -> None:
    store = SQLiteAgentStore(tmp_path / "p56-currency.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        transport = FakePrepaymentTransport()
        gateway = LiveExpenseGateway(
            LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
            store, FakeReadBackend(version=5, base_currency="CNY", activity_type="large"),
            transport,
        )
        with pytest.raises(LiveWriteError) as excinfo:
            asyncio.run(gateway.build_prepayment_preview(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=_create_intent(currency="USD"),
                access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert excinfo.value.code == "prepayment_currency_unsupported"

        with pytest.raises(LiveWriteError) as excinfo:
            asyncio.run(gateway.build_prepayment_preview(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=_create_intent(amount="10.55"),
                access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert excinfo.value.code == "prepayment_amount_precision"
        assert transport.preview_calls == []
    finally:
        store.close()


# --------------------------------------------------------------------- return


def test_return_preview_reads_balance_and_never_computes_the_post_balance(tmp_path) -> None:
    store, _, _, transport, proposal, _, _, _ = _setup(
        tmp_path, "p56-return-preview", is_return=True,
    )
    try:
        assert isinstance(proposal.preview, c.PrepaymentReturnPreview)
        assert proposal.preview.current_balance == "0.0000"
        assert proposal.preview.amount == "3.0"
        assert proposal.preview.currency == "CNY"
        assert proposal.preview.owner_participant_id == P1
        assert proposal.preview.custodian_participant_id == P2
        assert proposal.preview.post_balance_note == "返还后余额以服务端执行结果为准"
        assert "返还后余额以服务端执行结果为准" in proposal.preview.summary
        assert "remaining_balance" not in proposal.preview.model_dump()
        assert isinstance(proposal.canonical_command, c.FixedPrepaymentReturnCommand)
        assert proposal.canonical_command.expected_current_balance == "0.0000"
        assert transport.preview_calls == []
        assert transport.return_calls == []
    finally:
        store.close()


def test_return_execution_reports_the_server_remaining_balance(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p56-return-create", is_return=True,
    )
    try:
        transport.balance = "8.0000"
        transport.remaining_balance = "5.0000"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "prepayment_return_created"
        assert len(transport.return_calls) == 1
        call = transport.return_calls[0]
        assert call["url"].endswith("/rest/v1/rpc/create_prepayment_return_v2")
        payload = call["payload"]
        assert payload["owner_participant_id"] == str(P1)
        assert payload["custodian_participant_id"] == str(P2)
        assert payload["amount"] == "3.0"
        assert payload["on_behalf_of_participant_id"] is None
        assert payload["expected_financial_version"] == 5
        assert payload["request_id"] == str(
            c.derive_execution_id(OWNER, proposal.proposal_id, proposal.revision)
        )
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.execution_resolution is c.ExecutionResolution.SUCCEEDED
        # The preview showed the balance it read, not a locally subtracted one.
        assert proposal.preview.current_balance == "0.0000"
        assert transport.remaining_balance == "5.0000"
    finally:
        store.close()


def test_return_above_balance_is_rejected_by_the_server(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p56-return-over", is_return=True, intent=_return_intent(amount="99.0"),
    )
    try:
        transport.mode = "reject_balance"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.REJECTED
        assert outcome.code == "prepayment_return_exceeds_balance"
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.FAILED
        assert turn.execution_resolution is c.ExecutionResolution.REJECTED
    finally:
        store.close()


def test_return_permission_rejection_is_surfaced(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, _ = _setup(
        tmp_path, "p56-return-permission", is_return=True,
    )
    try:
        transport.mode = "reject_permission"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.REJECTED
        assert outcome.code == "actor_not_permitted"
    finally:
        store.close()


# ------------------------------------------------------------ idempotency/version


def test_duplicate_confirmation_sends_one_rpc(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p56-duplicate",
    )
    try:
        first = _execute(gateway, principal, proposal, waiting)
        assert first.resolution is c.ExecutionResolution.SUCCEEDED
        execution_id = store.get_turn(OWNER, turn_id).record.turn.execution.execution_id
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
        assert transport.create_calls[0]["payload"]["request_id"] == str(execution_id)
        assert store.get_turn(OWNER, turn_id).record.turn.execution.execution_id == execution_id
    finally:
        store.close()


@pytest.mark.parametrize("is_return", [False, True])
def test_version_change_closes_without_rpc(tmp_path, is_return) -> None:
    store, gateway, read_backend, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, f"p56-version-{is_return}", is_return=is_return,
    )
    try:
        read_backend.version = 6
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert transport.create_calls == []
        assert transport.return_calls == []
        assert store.get_proposal(OWNER, proposal.proposal_id).status is c.ProposalStatus.CLOSED
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.CANCELLED
        assert turn.execution is None
    finally:
        store.close()


def test_large_activity_requirement_is_rechecked_before_dispatch(tmp_path) -> None:
    store, gateway, read_backend, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p56-downgrade",
    )
    try:
        read_backend.activity_type = "normal"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == "prepayment_requires_large_activity"
        assert transport.create_calls == []
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.CANCELLED
    finally:
        store.close()


def test_server_version_conflict_after_dispatch_closes(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, _ = _setup(
        tmp_path, "p56-40001",
    )
    try:
        transport.mode = "version"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == "prepayment_version_conflict"
        assert len(transport.create_calls) == 1
    finally:
        store.close()


# ------------------------------------------------------------------- unknown


def _request_row(command: c.FixedPrepaymentCommand, *, payload_override: dict | None = None) -> dict:
    payload = {
        "operation": "create_prepayment",
        "activity_id": str(command.activity_id),
        "owner_participant_id": str(command.owner_participant_id),
        "custodian_participant_id": str(command.custodian_participant_id),
        "amount": command.amount,
        "currency": command.currency,
        "occurred_at": command.occurred_at.isoformat(),
        "on_behalf_of_participant_id": None,
        "expected_financial_version": int(command.expected_financial_version),
    }
    payload.update(payload_override or {})
    return {
        "id": str(TRANSFER),
        "type": "prepayment",
        "amount": command.amount,
        "currency": command.currency,
        "request_payload": payload,
        "request_result": {
            "transfer_id": str(TRANSFER),
            "settlement_amount": "4.0000",
            "prepayment_amount": "6.0000",
            "new_balance": "6.0000",
            "currency": command.currency,
            "financial_version": 6,
        },
    }


def test_unknown_prepayment_stays_unknown_until_the_request_id_is_found(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p56-unknown",
    )
    try:
        transport.mode = "ambiguous"
        assert _execute(gateway, principal, proposal, waiting).resolution is c.ExecutionResolution.UNKNOWN
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.RECOVERING
        assert turn.execution_resolution is c.ExecutionResolution.UNKNOWN

        stored = store.get_proposal(OWNER, proposal.proposal_id)
        still = asyncio.run(gateway.reconcile(principal, stored, "token-a"))
        assert still.resolution is c.ExecutionResolution.UNKNOWN
        assert len(transport.create_calls) == 1

        transport.transfer_rows = [_request_row(proposal.canonical_command)]
        outcome = asyncio.run(gateway.reconcile(principal, stored, "token-a"))
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "prepayment_created"
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.COMPLETED
        assert len(transport.create_calls) == 1
    finally:
        store.close()


def test_unknown_prepayment_with_a_different_payload_closes(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p56-conflict",
    )
    try:
        transport.mode = "ambiguous"
        assert _execute(gateway, principal, proposal, waiting).resolution is c.ExecutionResolution.UNKNOWN
        transport.transfer_rows = [
            _request_row(proposal.canonical_command, payload_override={"amount": "11.0"}),
        ]
        stored = store.get_proposal(OWNER, proposal.proposal_id)
        outcome = asyncio.run(gateway.reconcile(principal, stored, "token-a"))
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == "request_id_conflict"
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.CANCELLED
    finally:
        store.close()


def test_prepayment_preview_rejection_maps_the_server_code(tmp_path) -> None:
    store = SQLiteAgentStore(tmp_path / "p56-preview-reject.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        transport = FakePrepaymentTransport()
        transport.mode = "preview_normal"
        gateway = LiveExpenseGateway(
            LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
            store, FakeReadBackend(version=5, base_currency="CNY", activity_type="large"),
            transport,
        )
        with pytest.raises(LiveWriteError) as excinfo:
            asyncio.run(gateway.build_prepayment_preview(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=_create_intent(), access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert excinfo.value.code == "prepayment_requires_large_activity"
        assert transport.create_calls == []
    finally:
        store.close()


def test_return_preview_reports_an_unreadable_account(tmp_path) -> None:
    store = SQLiteAgentStore(tmp_path / "p56-balance-error.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        transport = FakePrepaymentTransport()
        transport.mode = "balance_error"
        gateway = LiveExpenseGateway(
            LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
            store, FakeReadBackend(version=5, base_currency="CNY", activity_type="large"),
            transport,
        )
        with pytest.raises(LiveWriteError) as excinfo:
            asyncio.run(gateway.build_prepayment_return_preview(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=_return_intent(), access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert excinfo.value.code == "prepayment_account_unavailable"
        assert transport.return_calls == []
    finally:
        store.close()


def test_create_needs_no_claim_from_the_owner_or_custodian(tmp_path) -> None:
    # The authenticated caller (OWNER) is neither participant, and the Agent
    # never asks them to claim either side before previewing a prepayment.
    store, _, _, _, proposal, _, _, _ = _setup(tmp_path, "p56-no-claim")
    try:
        command = proposal.canonical_command
        assert command.owner_participant_id == P1
        assert command.custodian_participant_id == P2
        assert command.on_behalf_of_participant_id is None
    finally:
        store.close()


def test_non_member_creation_is_rejected_by_the_server(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p56-not-member",
    )
    try:
        transport.mode = "reject_not_member"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.REJECTED
        assert outcome.code == "actor_not_permitted"
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.FAILED
    finally:
        store.close()


def test_unreplayable_idempotent_result_is_unknown_not_rejected(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p56-idempotent-unavailable",
    )
    try:
        transport.mode = "idempotent_unavailable"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.UNKNOWN
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.RECOVERING
        assert turn.execution_resolution is c.ExecutionResolution.UNKNOWN
        assert len(transport.create_calls) == 1
    finally:
        store.close()
