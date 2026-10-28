from __future__ import annotations

"""P5.4 linked refunds and explicit negative adjustments."""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlsplit

import pytest
from pydantic import ValidationError

from agent.app import contracts as c
from agent.app.p5_write import LiveExpenseGateway, LiveWriteConfig, LiveWriteError
from agent.app.ports import Principal
from agent.app.store import SQLiteAgentStore
from test_p5_live_write import ACTIVITY, FakeReadBackend, P1, P2, UNIT
from test_sqlite_persistence import OWNER, _session, _submit, _wait_with_proposal


ORIGINAL = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
REFUND_ONE = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


class FakeRefundTransport:
    def __init__(self) -> None:
        self.post_calls: list[dict] = []
        self.get_calls: list[str] = []
        self.mode = "success"
        self.new_expense_id = uuid.uuid4()
        self.expense = {
            "id": str(ORIGINAL),
            "ledger_unit_id": str(UNIT),
            "title": "Lunch",
            "original_amount": "50.00",
            "original_currency": "CNY",
            "base_amount": "50.0",
            "split_method": "aa",
            "occurred_at": "2026-10-25T12:00:00+00:00",
            "note": None,
            "original_expense_id": None,
            "version": 3,
            "is_deleted": False,
            "financial_locked": False,
            "icon_key": "money",
            "created_by": str(OWNER),
        }
        self.refunds: list[dict] = [
            {"id": str(REFUND_ONE), "original_amount": "-10.00"},
        ]

    def get_json(self, url, headers, *, timeout, max_response_bytes):  # noqa: ANN001
        self.get_calls.append(url)
        parsed = urlsplit(url)
        table = parsed.path.rsplit("/", 1)[-1]
        params = dict(parse_qsl(parsed.query))
        if table == "expenses":
            if "original_expense_id" in params:
                return 200, json.dumps(self.refunds).encode()
            return 200, json.dumps([self.expense]).encode()
        return 200, b"[]"

    def post_json(self, url, headers, payload, *, timeout, max_response_bytes):  # noqa: ANN001
        self.post_calls.append({"url": url, "payload": dict(payload)})
        if self.mode == "ambiguous":
            raise LiveWriteError("upstream_ambiguous", ambiguous=True)
        if self.mode == "reject_cap":
            return 400, json.dumps({
                "code": "23514",
                "message": "active linked refunds cannot exceed the original expense amount",
            }).encode()
        if self.mode == "reject_reference":
            return 400, json.dumps({
                "code": "22023",
                "message": "refund reference must be an active positive expense in the same activity",
            }).encode()
        if self.mode == "archived":
            return 400, json.dumps({
                "code": "55000", "message": "archived activity is read-only",
            }).encode()
        return 200, json.dumps([{
            "expense_id": str(self.new_expense_id),
            "base_amount": "-10.0",
            "version": 1,
        }]).encode()


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


def _refund_intent(*, amount: str = "10.0") -> c.ExpenseRefundIntent:
    return c.ExpenseRefundIntent(
        kind="expense.refund",
        original_expense_ref=c.ExpenseRef.SELECTED,
        title="退款-Lunch",
        original_amount=amount,
        payment_allocations=[c.PaymentAllocation(participant_ref=c.ParticipantRef.P01, amount=amount)],
        split=c.EqualSplitIntent(
            mode="equal",
            participant_refs=[c.ParticipantRef.P01, c.ParticipantRef.P02],
        ),
    )


def _refund_bindings(turn_id) -> list[c.BoundReference]:
    return [
        c.BoundExpenseReference(
            kind="expense", ref=c.ExpenseRef.SELECTED, entity_id=ORIGINAL,
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


def _refund_setup(tmp_path, name: str, *, intent: c.ExpenseRefundIntent | None = None):
    store = SQLiteAgentStore(tmp_path / f"{name}.sqlite3", admission_enabled=True)
    store.start()
    session = _session(store, OWNER)
    _, turn_id = _submit(store, session, OWNER)
    read_backend = FakeReadBackend(version=5, base_currency="CNY")
    transport = FakeRefundTransport()
    gateway = LiveExpenseGateway(
        LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
        store, read_backend, transport,
    )
    bindings = _refund_bindings(turn_id)
    proposal = asyncio.run(gateway.build_refund_preview(
        owner_user_id=OWNER,
        session_id=session,
        turn_id=turn_id,
        intent=intent or _refund_intent(),
        bound_references=bindings,
        access_token="token-a",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        agent_disable_revision=0,
        now=datetime.now(timezone.utc),
    ))
    waiting = _wait_with_proposal(store, OWNER, turn_id, proposal)
    principal = Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1))
    return (
        store, gateway, read_backend, transport, proposal, waiting, principal, turn_id,
        bindings[0],
    )


# ----------------------------------------------------------------- linked refund


def test_refund_preview_binds_the_original_and_the_cap(tmp_path) -> None:
    store, _, _, transport, proposal, waiting, _, _, _ = _refund_setup(
        tmp_path, "p54-preview",
    )
    try:
        assert waiting.state is c.TurnState.WAIT_CONFIRM
        assert proposal.operation == "expense.refund"
        assert isinstance(proposal.preview, c.RefundPreview)
        preview = proposal.preview
        assert preview.original_expense_id == ORIGINAL
        assert preview.original_title == "Lunch"
        assert preview.refund_title == "退款-Lunch"
        assert preview.original_amount == "50.00"
        assert preview.refunded_amount == "10.00"
        assert preview.refund_amount == "10.0"
        assert preview.remaining_amount == "40.00"
        assert preview.currency == "CNY"
        assert preview.expected_original_version == "3"
        assert preview.expected_original_financial_locked is False
        assert preview.expected_financial_version == "5"
        assert "累计已退 10.00" in preview.summary
        assert "本次上限 40.00" in preview.summary
        command = proposal.canonical_command
        assert isinstance(command, c.FixedExpenseRefundCommand)
        assert command.original_expense_id == ORIGINAL
        assert command.ledger_unit_id == UNIT
        assert command.currency == "CNY"
        assert command.expected_refunded_amount == "10.00"
        assert transport.post_calls == []
    finally:
        store.close()


def test_refund_execute_sends_a_negative_linked_expense(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id, _ = _refund_setup(
        tmp_path, "p54-execute",
    )
    try:
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "refund_created"
        assert len(transport.post_calls) == 1
        call = transport.post_calls[0]
        assert call["url"].endswith("/rest/v1/rpc/create_expense_auto_rate")
        payload = call["payload"]
        assert payload["original_amount"] == "-10.0"
        assert payload["original_expense_id"] == str(ORIGINAL)
        assert payload["original_currency"] == "CNY"
        assert payload["ledger_unit_id"] == str(UNIT)
        assert payload["title"] == "退款-Lunch"
        assert payload["payments"] == [{"participant_id": str(P1), "amount": "-10.0"}]
        assert payload["manual_splits"] == []
        assert payload["aa_participant_ids"] == [str(P1), str(P2)]
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.COMPLETED
    finally:
        store.close()


@pytest.mark.parametrize(
    ("refunds", "reason"),
    [
        ([{"id": str(REFUND_ONE), "original_amount": "-10.00"},
          {"id": str(uuid.uuid4()), "original_amount": "-35.00"}], "refund_exceeds_remaining"),
        ([{"id": str(REFUND_ONE), "original_amount": "-50.00"}], "refund_exceeds_remaining"),
    ],
)
def test_refund_over_the_cap_is_refused_without_an_rpc(tmp_path, refunds, reason) -> None:
    store = SQLiteAgentStore(tmp_path / f"p54-cap-{len(refunds)}.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        transport = FakeRefundTransport()
        transport.refunds = refunds
        gateway = LiveExpenseGateway(
            LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
            store, FakeReadBackend(version=5, base_currency="CNY"), transport,
        )
        binding = _refund_bindings(turn_id)
        with pytest.raises(LiveWriteError) as excinfo:
            asyncio.run(gateway.build_refund_preview(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=_refund_intent(), bound_references=binding,
                access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert excinfo.value.code == reason
        assert transport.post_calls == []
    finally:
        store.close()


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("is_deleted", True, "refund_original_invalid"),
        ("original_amount", "-20.00", "refund_original_invalid"),
        ("original_expense_id", str(REFUND_ONE), "refund_original_invalid"),
    ],
)
def test_invalid_original_is_refused(tmp_path, field, value, reason) -> None:
    store = SQLiteAgentStore(tmp_path / f"p54-invalid-{field}.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        transport = FakeRefundTransport()
        transport.expense[field] = value
        gateway = LiveExpenseGateway(
            LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
            store, FakeReadBackend(version=5, base_currency="CNY"), transport,
        )
        binding = _refund_bindings(turn_id)
        with pytest.raises(LiveWriteError) as excinfo:
            asyncio.run(gateway.build_refund_preview(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=_refund_intent(), bound_references=binding,
                access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert excinfo.value.code == reason
        assert transport.post_calls == []
    finally:
        store.close()


def test_server_rejections_surface_as_rejected(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, _, _ = _refund_setup(
        tmp_path, "p54-server-reject",
    )
    try:
        transport.mode = "reject_reference"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.REJECTED
        assert outcome.code == "invalid_parameter"
    finally:
        store.close()


def test_a_recorded_refund_locks_the_original_permanently(tmp_path) -> None:
    # The lock is a server-side fact; after the refund exists the Agent must
    # carry it into the next preview and refuse a preview/execute mismatch.
    store, gateway, _, transport, proposal, waiting, principal, _, _ = _refund_setup(
        tmp_path, "p54-lock",
    )
    try:
        assert proposal.preview.expected_original_financial_locked is False
        transport.expense["financial_locked"] = True
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == "refund_source_changed"
        assert transport.post_calls == []

        # A fresh preview now records the permanent lock instead of rejecting.
        session = store.get_proposal(OWNER, proposal.proposal_id).session_id
        followup_turn = uuid.uuid4()
        followup = asyncio.run(gateway.build_refund_preview(
            owner_user_id=OWNER, session_id=session, turn_id=followup_turn,
            intent=_refund_intent(), bound_references=_refund_bindings(followup_turn),
            access_token="token-a",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            agent_disable_revision=0, now=datetime.now(timezone.utc),
        ))
        assert followup.preview.expected_original_financial_locked is True
    finally:
        store.close()


def test_duplicate_confirmation_sends_one_rpc(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id, _ = _refund_setup(
        tmp_path, "p54-duplicate",
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
        assert len(transport.post_calls) == 1
        assert store.get_turn(OWNER, turn_id).record.turn.execution.execution_id == execution_id
    finally:
        store.close()


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("original_version", "refund_source_changed"),
        ("refunded", "refund_source_changed"),
        ("locked", "refund_source_changed"),
        ("deleted", "refund_original_invalid"),
        ("activity_version", "data_changed_during_read"),
    ],
)
def test_preview_changes_close_without_an_rpc(tmp_path, change, reason) -> None:
    store, gateway, read_backend, transport, proposal, waiting, principal, turn_id, _ = _refund_setup(
        tmp_path, f"p54-change-{change}",
    )
    try:
        if change == "original_version":
            transport.expense["version"] = 4
        elif change == "refunded":
            transport.refunds.append({"id": str(uuid.uuid4()), "original_amount": "-5.00"})
        elif change == "locked":
            transport.expense["financial_locked"] = True
        elif change == "deleted":
            transport.expense["is_deleted"] = True
        else:
            read_backend.version = 6
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == reason
        assert transport.post_calls == []
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.CANCELLED
        assert turn.execution is None
    finally:
        store.close()


@pytest.mark.parametrize(
    ("refund_landed", "code"),
    [(False, "refund_not_applied"), (True, "refunded_elsewhere")],
)
def test_unknown_refund_never_claims_success(tmp_path, refund_landed, code) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id, _ = _refund_setup(
        tmp_path, f"p54-unknown-{refund_landed}",
    )
    try:
        transport.mode = "ambiguous"
        assert _execute(gateway, principal, proposal, waiting).resolution is c.ExecutionResolution.UNKNOWN
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.RECOVERING
        assert turn.execution_resolution is c.ExecutionResolution.UNKNOWN

        if refund_landed:
            # A refund did land, but without a request id it cannot be attributed.
            transport.refunds.append({"id": str(uuid.uuid4()), "original_amount": "-10.00"})
        stored = store.get_proposal(OWNER, proposal.proposal_id)
        outcome = asyncio.run(gateway.reconcile(principal, stored, "token-a"))
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == code
        assert len(transport.post_calls) == 1
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.CANCELLED
    finally:
        store.close()


# ------------------------------------------------------- negative adjustment


def _negative_intent(*, currency: str = "CNY", amount: str = "8.0") -> c.NegativeAdjustmentIntent:
    return c.NegativeAdjustmentIntent(
        kind="expense.negative_adjustment",
        ledger_unit_ref=c.LedgerUnitRef.U01,
        title="折扣",
        original_amount=amount,
        original_currency=currency,
        payment_allocations=[c.PaymentAllocation(participant_ref=c.ParticipantRef.P01, amount=amount)],
        split=c.EqualSplitIntent(
            mode="equal",
            participant_refs=[c.ParticipantRef.P01, c.ParticipantRef.P02],
        ),
    )


def _negative_setup(tmp_path, name: str, *, intent=None, transport=None):
    store = SQLiteAgentStore(tmp_path / f"{name}.sqlite3", admission_enabled=True)
    store.start()
    session = _session(store, OWNER)
    _, turn_id = _submit(store, session, OWNER)
    read_backend = FakeReadBackend(version=5, base_currency="CNY")
    transport = transport or FakeRefundTransport()
    gateway = LiveExpenseGateway(
        LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
        store, read_backend, transport,
    )
    unit_binding = c.BoundLedgerUnitReference(
        kind="ledger_unit", ref=c.LedgerUnitRef.U01, entity_id=UNIT,
        source_turn_id=turn_id, scope_activity_id=ACTIVITY,
    )
    participant_bindings = [
        c.BoundParticipantReference(
            kind="participant", ref=c.ParticipantRef.P01, entity_id=P1,
            source_turn_id=turn_id, scope_activity_id=ACTIVITY,
        ),
        c.BoundParticipantReference(
            kind="participant", ref=c.ParticipantRef.P02, entity_id=P2,
            source_turn_id=turn_id, scope_activity_id=ACTIVITY,
        ),
    ]
    return (
        store, session, turn_id, read_backend, transport, gateway,
        [unit_binding, *participant_bindings],
    )


def test_negative_adjustment_executes_as_an_unlinked_negative_expense(tmp_path) -> None:
    store, session, turn_id, _, transport, gateway, bindings = _negative_setup(
        tmp_path, "p54-negative",
    )
    try:
        proposal = asyncio.run(gateway.build_negative_adjustment_preview(
            owner_user_id=OWNER, session_id=session, turn_id=turn_id,
            intent=_negative_intent(), bound_references=bindings,
            access_token="token-a",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            agent_disable_revision=0, now=datetime.now(timezone.utc),
        ))
        assert proposal.operation == "expense.negative_adjustment"
        assert isinstance(proposal.preview, c.NegativeAdjustmentPreview)
        assert "未关联原单" in proposal.preview.summary
        waiting = _wait_with_proposal(store, OWNER, turn_id, proposal)
        principal = Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1))
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "negative_adjustment_created"
        payload = transport.post_calls[0]["payload"]
        assert payload["original_amount"] == "-8.0"
        assert payload["original_expense_id"] is None
        assert payload["original_currency"] == "CNY"
        assert payload["payments"] == [{"participant_id": str(P1), "amount": "-8.0"}]
        assert payload["aa_participant_ids"] == [str(P1), str(P2)]
    finally:
        store.close()


def test_negative_adjustment_rejects_foreign_currency(tmp_path) -> None:
    store, session, turn_id, _, transport, gateway, bindings = _negative_setup(
        tmp_path, "p54-negative-fx",
    )
    try:
        with pytest.raises(LiveWriteError) as excinfo:
            asyncio.run(gateway.build_negative_adjustment_preview(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=_negative_intent(currency="USD"), bound_references=bindings,
                access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert excinfo.value.code == "foreign_currency_not_in_p5"
        assert transport.post_calls == []
    finally:
        store.close()


@pytest.mark.parametrize(
    ("changed", "code"),
    [(False, "adjustment_not_applied"), (True, "activity_changed")],
)
def test_unknown_negative_adjustment_closes_without_claiming_success(
    tmp_path, changed, code,
) -> None:
    store, session, turn_id, read_backend, transport, gateway, bindings = _negative_setup(
        tmp_path, f"p54-negative-unknown-{changed}",
    )
    try:
        proposal = asyncio.run(gateway.build_negative_adjustment_preview(
            owner_user_id=OWNER, session_id=session, turn_id=turn_id,
            intent=_negative_intent(), bound_references=bindings,
            access_token="token-a",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            agent_disable_revision=0, now=datetime.now(timezone.utc),
        ))
        waiting = _wait_with_proposal(store, OWNER, turn_id, proposal)
        principal = Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1))
        transport.mode = "ambiguous"
        assert _execute(gateway, principal, proposal, waiting).resolution is c.ExecutionResolution.UNKNOWN

        if changed:
            read_backend.version = 6
        stored = store.get_proposal(OWNER, proposal.proposal_id)
        outcome = asyncio.run(gateway.reconcile(principal, stored, "token-a"))
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == code
        assert len(transport.post_calls) == 1
    finally:
        store.close()


def test_plain_create_cannot_express_a_negative_amount() -> None:
    # `记账` has no path to a negative Expense: the frozen create intent rejects it.
    with pytest.raises(ValidationError):
        c.ExpenseCreateIntent(
            kind="expense.create",
            ledger_unit_ref=c.LedgerUnitRef.U01,
            title="Lunch",
            original_amount="-8.0",
            original_currency="CNY",
            payment_allocations=[
                c.PaymentAllocation(participant_ref=c.ParticipantRef.P01, amount="-8.0"),
            ],
            split=c.EqualSplitIntent(
                mode="equal", participant_refs=[c.ParticipantRef.P01],
            ),
        )
