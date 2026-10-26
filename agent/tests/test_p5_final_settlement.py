from __future__ import annotations

"""P5.7 final settlement: server plan selection, version guard, reconcile."""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from agent.app import contracts as c
from agent.app.p5_write import LiveExpenseGateway, LiveWriteConfig, LiveWriteError
from agent.app.ports import Principal
from agent.app.store import SQLiteAgentStore
from test_p5_live_write import ACTIVITY, FakeReadBackend, P1, P2
from test_sqlite_persistence import OWNER, _session, _submit, _wait_with_proposal


TRANSFER = uuid.UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")


def _plan_row(
    from_id, to_id, amount, ordinary, returned, currency, *,
    mode: str = "base_unified", version: int = 5,
) -> dict:
    return {
        "activity_id": str(ACTIVITY),
        "from_participant_id": str(from_id),
        "to_participant_id": str(to_id),
        "amount": amount,
        "ordinary_amount": ordinary,
        "prepayment_return_amount": returned,
        "currency": currency,
        "mode": mode,
        "path_currency": currency,
        "source_financial_version": version,
        "is_prepayment_return": Decimal(ordinary) == 0,
    }


def _two_item_plan(currency: str = "CNY", mode: str = "base_unified") -> list[dict]:
    return [
        _plan_row(P1, P2, "10.0000", "10.0000", "0.0000", currency, mode=mode),
        _plan_row(P2, P1, "4.0000", "4.0000", "0.0000", currency, mode=mode),
    ]


class FakeFinalSettlementTransport:
    def __init__(self) -> None:
        self.preview_calls: list[dict] = []
        self.execute_calls: list[dict] = []
        self.get_calls: list[str] = []
        self.mode = "success"
        self.plan = _two_item_plan()
        self.transfer_rows: list[dict] = []

    def post_json(self, url, headers, payload, *, timeout, max_response_bytes):  # noqa: ANN001
        if url.endswith("/preview_final_settlement_v2"):
            self.preview_calls.append(dict(payload))
            if self.mode == "preview_error":
                return 400, json.dumps({
                    "code": "42501", "message": "caller is not an activity member",
                }).encode()
            return 200, json.dumps(self.plan).encode()
        if url.endswith("/execute_final_settlement_v2"):
            self.execute_calls.append({"url": url, "payload": dict(payload)})
            if self.mode == "ambiguous":
                raise LiveWriteError("upstream_ambiguous", ambiguous=True)
            if self.mode == "version":
                return 400, json.dumps({
                    "code": "40001", "message": "financial_version mismatch; refresh the plan",
                }).encode()
            if self.mode == "stale_plan":
                return 400, json.dumps({
                    "code": "23514", "message": "final settlement does not match current plan",
                }).encode()
            if self.mode == "archived":
                return 400, json.dumps({
                    "code": "55000", "message": "archived activity is read-only",
                }).encode()
            return 200, json.dumps([{
                "transfer_id": str(TRANSFER),
                "amount": payload["amount"],
                "currency": payload["currency"],
                "mode": payload["mode"],
                "financial_version": 6,
            }]).encode()
        return 200, b"[]"

    def get_json(self, url, headers, *, timeout, max_response_bytes):  # noqa: ANN001
        self.get_calls.append(url)
        if "/rest/v1/transfers" in url:
            return 200, json.dumps(self.transfer_rows).encode()
        return 200, b"[]"


def _intent(
    *, amount: str = "10.0", currency: str = "CNY",
    mode: str = "base_unified", from_id=P1, to_id=P2,
) -> c.FinalSettlementIntent:
    return c.FinalSettlementIntent(
        kind="settlement.final",
        activity_id=ACTIVITY,
        from_participant_id=from_id,
        to_participant_id=to_id,
        amount=amount,
        currency=currency,
        mode=mode,
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
    tmp_path, name: str, *, intent=None, activity_type: str = "normal",
    plan: list[dict] | None = None, multi_currency_enabled: bool = False,
):
    store = SQLiteAgentStore(tmp_path / f"{name}.sqlite3", admission_enabled=True)
    store.start()
    session = _session(store, OWNER)
    _, turn_id = _submit(store, session, OWNER)
    read_backend = FakeReadBackend(
        version=5, base_currency="CNY",
        activity_type=activity_type, multi_currency_enabled=multi_currency_enabled,
    )
    transport = FakeFinalSettlementTransport()
    if plan is not None:
        transport.plan = plan
    gateway = LiveExpenseGateway(
        LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
        store, read_backend, transport,
    )
    proposal = asyncio.run(gateway.build_final_settlement_preview(
        owner_user_id=OWNER,
        session_id=session,
        turn_id=turn_id,
        intent=intent or _intent(),
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


# ---------------------------------------------------------------- preview/plan


def test_preview_lists_the_complete_plan_and_selects_one_item(tmp_path) -> None:
    store, _, _, transport, proposal, waiting, _, _ = _setup(tmp_path, "p57-preview")
    try:
        assert waiting.state is c.TurnState.WAIT_CONFIRM
        assert proposal.operation == "settlement.final"
        assert isinstance(proposal.preview, c.FinalSettlementPreview)
        preview = proposal.preview
        assert len(preview.plan) == 2
        assert [(item.from_participant_id, item.to_participant_id) for item in preview.plan] == [
            (P1, P2), (P2, P1),
        ]
        assert preview.from_participant_id == P1
        assert preview.to_participant_id == P2
        assert preview.amount == "10.0000"
        assert preview.ordinary_amount == "10.0000"
        assert preview.prepayment_return_amount == "0.0000"
        assert preview.is_prepayment_return is False
        assert preview.mode == "base_unified"
        assert preview.expected_financial_version == "5"
        # The summary carries the selected item and every plan line.
        assert "Ann -> Ben 10.0000 CNY" in preview.summary
        assert "Ben -> Ann 4.0000 CNY" in preview.summary
        assert preview.summary.count("\n") == 0
        assert transport.preview_calls == [{
            "activity_id": str(ACTIVITY), "mode": "base_unified",
        }]
        assert transport.execute_calls == []
    finally:
        store.close()


def test_execute_matches_the_plan_item_and_sends_request_fields(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p57-execute",
    )
    try:
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "final_settlement_created"
        assert len(transport.execute_calls) == 1
        call = transport.execute_calls[0]
        assert call["url"].endswith("/rest/v1/rpc/execute_final_settlement_v2")
        payload = call["payload"]
        assert payload["activity_id"] == str(ACTIVITY)
        assert payload["from_participant_id"] == str(P1)
        assert payload["to_participant_id"] == str(P2)
        assert payload["amount"] == "10.0000"
        assert payload["currency"] == "CNY"
        assert payload["mode"] == "base_unified"
        assert payload["on_behalf_of_participant_id"] is None
        assert payload["expected_financial_version"] == 5
        assert payload["request_id"] == str(
            c.derive_execution_id(OWNER, proposal.proposal_id, proposal.revision)
        )
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.COMPLETED
    finally:
        store.close()


@pytest.mark.parametrize(
    "intent",
    [
        pytest.param(_intent(amount="11.0"), id="amount"),
        pytest.param(_intent(currency="USD"), id="currency"),
        pytest.param(_intent(from_id=P2, to_id=P1), id="direction"),
    ],
)
def test_any_field_mismatch_is_refused_without_an_rpc(tmp_path, intent) -> None:
    store = SQLiteAgentStore(tmp_path / "p57-mismatch.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        transport = FakeFinalSettlementTransport()
        gateway = LiveExpenseGateway(
            LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
            store, FakeReadBackend(version=5, base_currency="CNY"), transport,
        )
        with pytest.raises(LiveWriteError) as excinfo:
            asyncio.run(gateway.build_final_settlement_preview(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=intent, access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert excinfo.value.code == "final_settlement_item_not_in_plan"
        assert transport.execute_calls == []
    finally:
        store.close()


def test_empty_plan_is_refused(tmp_path) -> None:
    store = SQLiteAgentStore(tmp_path / "p57-empty.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        transport = FakeFinalSettlementTransport()
        transport.plan = []
        gateway = LiveExpenseGateway(
            LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
            store, FakeReadBackend(version=5, base_currency="CNY"), transport,
        )
        with pytest.raises(LiveWriteError) as excinfo:
            asyncio.run(gateway.build_final_settlement_preview(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=_intent(), access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert excinfo.value.code == "final_settlement_plan_empty"
        assert transport.execute_calls == []
    finally:
        store.close()


# ------------------------------------------------------- prepayment return path


def test_normal_activity_plan_has_no_prepayment_return_item(tmp_path) -> None:
    store, _, _, _, proposal, _, _, _ = _setup(
        tmp_path, "p57-normal-plan", activity_type="normal",
    )
    try:
        assert proposal.preview.plan
        assert all(not item.is_prepayment_return for item in proposal.preview.plan)
        assert all(
            Decimal(item.prepayment_return_amount) == 0
            for item in proposal.preview.plan
        )
    finally:
        store.close()


def test_large_activity_plan_can_select_a_prepayment_return_item(tmp_path) -> None:
    plan = [
        _plan_row(P1, P2, "10.0000", "10.0000", "0.0000", "CNY"),
        _plan_row(P2, P1, "6.0000", "0.0000", "6.0000", "CNY"),
    ]
    store, gateway, _, transport, proposal, waiting, principal, _ = _setup(
        tmp_path, "p57-return-plan", activity_type="large", plan=plan,
        intent=_intent(from_id=P2, to_id=P1, amount="6.0"),
    )
    try:
        preview = proposal.preview
        assert preview.from_participant_id == P2
        assert preview.to_participant_id == P1
        assert preview.is_prepayment_return is True
        assert preview.ordinary_amount == "0.0000"
        assert preview.prepayment_return_amount == "6.0000"
        assert [item.is_prepayment_return for item in preview.plan] == [False, True]
        assert isinstance(proposal.canonical_command, c.FixedFinalSettlementCommand)
        assert proposal.canonical_command.expected_activity_type == "large"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert transport.execute_calls[0]["payload"]["amount"] == "6.0000"
    finally:
        store.close()


# ------------------------------------------------------------ modes and version


@pytest.mark.parametrize("mode", ["base_unified", "original_currency"])
def test_both_settlement_modes_reach_the_rpc(tmp_path, mode) -> None:
    currency = "CNY" if mode == "base_unified" else "USD"
    plan = _two_item_plan(currency=currency, mode=mode)
    store, gateway, _, transport, proposal, waiting, principal, _ = _setup(
        tmp_path, f"p57-mode-{mode}", plan=plan,
        intent=_intent(currency=currency, mode=mode),
        multi_currency_enabled=(mode == "original_currency"),
    )
    try:
        assert proposal.preview.mode == mode
        assert proposal.preview.currency == currency
        assert transport.preview_calls[0]["mode"] == mode
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        payload = transport.execute_calls[0]["payload"]
        assert payload["mode"] == mode
        assert payload["currency"] == currency
    finally:
        store.close()


def test_duplicate_confirmation_sends_one_rpc(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p57-duplicate",
    )
    try:
        assert _execute(gateway, principal, proposal, waiting).resolution is c.ExecutionResolution.SUCCEEDED
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
        assert len(transport.execute_calls) == 1
        assert transport.execute_calls[0]["payload"]["request_id"] == str(execution_id)
    finally:
        store.close()


def test_preview_version_change_closes_without_rpc(tmp_path) -> None:
    store, gateway, read_backend, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p57-version",
    )
    try:
        read_backend.version = 6
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert transport.execute_calls == []
        assert store.get_proposal(OWNER, proposal.proposal_id).status is c.ProposalStatus.CLOSED
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.CANCELLED
        assert turn.execution is None
    finally:
        store.close()


def test_activity_type_change_closes_without_rpc(tmp_path) -> None:
    store, gateway, read_backend, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p57-type", activity_type="large",
        plan=[
            _plan_row(P1, P2, "10.0000", "10.0000", "0.0000", "CNY"),
            _plan_row(P2, P1, "6.0000", "0.0000", "6.0000", "CNY"),
        ],
    )
    try:
        assert isinstance(proposal.canonical_command, c.FixedFinalSettlementCommand)
        assert proposal.canonical_command.expected_activity_type == "large"
        read_backend.activity_type = "normal"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == "activity_type_changed"
        assert transport.execute_calls == []
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.CANCELLED
    finally:
        store.close()


def test_server_40001_closes_the_dispatched_execution(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p57-40001",
    )
    try:
        transport.mode = "version"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == "final_settlement_version_conflict"
        assert len(transport.execute_calls) == 1
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.CANCELLED
        assert turn.execution is not None  # the dispatch did happen
        assert turn.execution_resolution is c.ExecutionResolution.CLOSED
    finally:
        store.close()


def test_stale_plan_rejection_is_reported_as_rejected(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p57-stale-plan",
    )
    try:
        transport.mode = "stale_plan"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.REJECTED
        assert outcome.code == "final_settlement_stale_plan"
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.FAILED
    finally:
        store.close()


def test_archived_activity_is_rejected_by_the_server(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, _ = _setup(
        tmp_path, "p57-archived",
    )
    try:
        transport.mode = "archived"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.REJECTED
        assert outcome.code == "activity_read_only"
    finally:
        store.close()


# ------------------------------------------------------------------- unknown


def _request_row(command: c.FixedFinalSettlementCommand, *, override: dict | None = None) -> dict:
    payload = {
        "operation": "execute_final_settlement",
        "activity_id": str(command.activity_id),
        "from_participant_id": str(command.from_participant_id),
        "to_participant_id": str(command.to_participant_id),
        "amount": command.amount,
        "currency": command.currency,
        "mode": command.mode,
        "expected_financial_version": int(command.expected_financial_version),
        "occurred_at": command.occurred_at.isoformat(),
        "on_behalf_of_participant_id": None,
    }
    payload.update(override or {})
    return {
        "id": str(TRANSFER),
        "type": "final_settlement",
        "amount": command.amount,
        "currency": command.currency,
        "request_payload": payload,
        "request_result": {
            "transfer_id": str(TRANSFER),
            "amount": command.amount,
            "currency": command.currency,
            "mode": command.mode,
            "financial_version": 6,
        },
    }


def test_unknown_final_settlement_reconciles_by_request_id(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p57-unknown",
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
        assert len(transport.execute_calls) == 1

        transport.transfer_rows = [_request_row(proposal.canonical_command)]
        outcome = asyncio.run(gateway.reconcile(principal, stored, "token-a"))
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "final_settlement_created"
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.COMPLETED
        assert len(transport.execute_calls) == 1
    finally:
        store.close()


def test_unknown_final_settlement_with_a_different_payload_closes(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p57-conflict",
    )
    try:
        transport.mode = "ambiguous"
        assert _execute(gateway, principal, proposal, waiting).resolution is c.ExecutionResolution.UNKNOWN
        transport.transfer_rows = [
            _request_row(proposal.canonical_command, override={"mode": "original_currency"}),
        ]
        stored = store.get_proposal(OWNER, proposal.proposal_id)
        outcome = asyncio.run(gateway.reconcile(principal, stored, "token-a"))
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == "request_id_conflict"
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.CANCELLED
    finally:
        store.close()
