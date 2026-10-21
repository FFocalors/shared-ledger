from __future__ import annotations

"""P3a mock write path: preview -> confirm -> fixed command -> atomic effect -> receipt.

The four acceptance conditions this file pins:

* an unconfirmed proposal posts nothing,
* the same request never produces a second effect,
* a concurrent ledger change invalidates the preview,
* a lost response is reconciled under the original execution key,
* an unauthorized or archived Activity refuses the write before any effect,
  at dispatch, at application, and in the recovery path.

The execution identity itself is derived from (actor, proposal, revision), so it
is reproducible across restarts and old backups; nothing here mints a random id.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from agent.app import contracts as c
from agent.app import mock_fixtures
from agent.app.p3_execution import (
    MockActivityArchived, MockActivityRoster, MockExecutionStateError,
    MockPermissionDenied, MockPreconditionConflict, mock_effect_for_command,
)
from agent.app.store import ProposalConflict, SQLiteAgentStore
from agent.app.backend import MockBackendAdapter, MockScopeAuthorizer
from agent.app.harness import MockModelProvider
from agent.app.ports import Principal
from agent.app.runtime import MockRuntime
from test_mock_runtime import _Control
from test_sqlite_persistence import (
    OWNER, _proposal, _session, _submit, _wait_with_proposal,
)


class _OwnerAuth:
    """Verify every token as this file's owner (test_mock_runtime uses another)."""

    def verify_bearer(self, token: str) -> Principal:
        return Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1))


def _waiting_turn(tmp_path, name: str) -> tuple[SQLiteAgentStore, c.TurnStateSnapshot, c.ProposalRecord]:
    store = SQLiteAgentStore(tmp_path / f"{name}.sqlite3", admission_enabled=True)
    store.start()
    session = _session(store, OWNER)
    _, turn_id = _submit(store, session, OWNER)
    proposal = _proposal(OWNER, session, turn_id, backend=True)
    waiting = _wait_with_proposal(store, OWNER, turn_id, proposal)
    assert waiting.state is c.TurnState.WAIT_CONFIRM
    assert proposal.execution is None
    return store, waiting, proposal


def _confirm(store: SQLiteAgentStore, waiting: c.TurnStateSnapshot, proposal: c.ProposalRecord, *,
             request_id: uuid.UUID | None = None,
             activity_guard=None) -> c.TurnAggregate:
    request = c.ConfirmProposalRequest(
        client_request_id=request_id or uuid.uuid4(),
        expected_proposal_revision=proposal.revision,
        command_digest=proposal.command_digest,
        confirmation_nonce=proposal.confirmation_nonce,
    )
    return store.confirm_and_dispatch(
        OWNER, proposal.proposal_id, request,
        expected_state_revision=waiting.state_revision,
        expected_proposal_revision=proposal.revision,
        activity_guard=activity_guard,
    )


def _roster(*, members=(OWNER,), archived: bool = False) -> MockActivityRoster:
    roster = MockActivityRoster()
    roster.add(mock_fixtures.ACTIVITY_ID, members, archived=archived)
    return roster


def test_execution_id_is_deterministic_and_bound() -> None:
    proposal_id = uuid.uuid4()
    first = c.derive_execution_id(OWNER, proposal_id, 1)
    assert first == c.derive_execution_id(OWNER, proposal_id, 1)
    assert first != c.derive_execution_id(OWNER, proposal_id, 2)
    assert first != c.derive_execution_id(uuid.uuid4(), proposal_id, 1)

    identity = c.ExecutionIdentity(
        execution_id=first, actor_id=OWNER, proposal_id=proposal_id, proposal_revision=1,
    )
    assert identity.execution_id == first
    # A non-derived id is rejected by the frozen contract itself.
    with pytest.raises(ValueError):
        c.ExecutionIdentity(
            execution_id=uuid.uuid4(), actor_id=OWNER, proposal_id=proposal_id, proposal_revision=1,
        )


def test_unconfirmed_proposal_applies_no_effect(tmp_path) -> None:
    store, waiting, proposal = _waiting_turn(tmp_path, "p3a-unconfirmed")
    try:
        assert waiting.execution is None
        assert store.count_mock_executions(proposal.proposal_id) == 0
        assert store.read_mock_execution(c.derive_execution_id(OWNER, proposal.proposal_id, 1)) is None
        assert store.get_proposal(OWNER, proposal.proposal_id).status is c.ProposalStatus.PENDING
    finally:
        store.close()


def test_confirmation_dispatches_deterministic_identity_and_applies_once(tmp_path) -> None:
    store, waiting, proposal = _waiting_turn(tmp_path, "p3a-confirm")
    try:
        dispatched = _confirm(store, waiting, proposal)
        execution = dispatched.record.turn.execution
        expected_id = c.derive_execution_id(OWNER, proposal.proposal_id, proposal.revision)
        assert execution is not None and execution.execution_id == expected_id
        assert execution.actor_id == OWNER and execution.proposal_id == proposal.proposal_id
        assert dispatched.record.turn.state is c.TurnState.EXECUTING
        assert dispatched.record.turn.step is c.TurnStep.DISPATCH
        # Dispatch alone applies nothing: the effect is a separate commit.
        assert store.count_mock_executions(proposal.proposal_id) == 0

        applied = store.apply_mock_execution(OWNER, proposal.proposal_id)
        assert applied["applied"] is True
        assert applied["execution_id"] == str(expected_id)
        assert applied["effect"]["title"] == "Lunch"
        assert applied["effect"]["original_amount"] == "12.50"

        settled = store.settle_mock_execution(
            OWNER, proposal.proposal_id, c.ExecutionResolution.SUCCEEDED,
            result_code="mock_expense_created", result_summary="one expense applied",
        )
        assert settled.record.turn.state is c.TurnState.COMPLETED
        assert settled.record.turn.execution_resolution is c.ExecutionResolution.SUCCEEDED
        assert settled.record.turn.step is c.TurnStep.TERMINAL

        stored = store.read_mock_execution(expected_id)
        assert stored is not None and stored["proposal_id"] == str(proposal.proposal_id)
        assert store.count_mock_executions(proposal.proposal_id) == 1
        # The mock ledger advanced the activity's financial version exactly once.
        assert store.mock_ledger_financial_version(mock_fixtures.ACTIVITY_ID) == 1
    finally:
        store.close()


def test_repeated_confirmation_cannot_apply_a_second_effect(tmp_path) -> None:
    store, waiting, proposal = _waiting_turn(tmp_path, "p3a-repeat")
    try:
        _confirm(store, waiting, proposal)
        # A second confirmation, even with a fresh client request id, must not
        # dispatch a second execution for the same revision.
        with pytest.raises(ProposalConflict):
            _confirm(store, waiting, proposal)
        applied = store.apply_mock_execution(OWNER, proposal.proposal_id)
        assert applied["applied"] is True
        # Re-applying is a no-op under the same key, and the ledger stays at one.
        again = store.apply_mock_execution(OWNER, proposal.proposal_id)
        assert again["applied"] is False
        assert again["execution_id"] == applied["execution_id"]
        assert store.count_mock_executions(proposal.proposal_id) == 1
        assert store.mock_ledger_financial_version(mock_fixtures.ACTIVITY_ID) == 1
        store.settle_mock_execution(OWNER, proposal.proposal_id, c.ExecutionResolution.SUCCEEDED)
        assert store.get_turn(OWNER, proposal.turn_id).record.turn.state is c.TurnState.COMPLETED
    finally:
        store.close()


def test_concurrent_ledger_change_invalidates_the_preview(tmp_path) -> None:
    store, waiting, proposal = _waiting_turn(tmp_path, "p3a-stale")
    try:
        # Another writer changed the activity after the preview was taken.
        assert store.bump_mock_ledger_version(mock_fixtures.ACTIVITY_ID) == 1
        with pytest.raises(MockPreconditionConflict):
            _confirm(store, waiting, proposal)
        # Nothing was dispatched and nothing landed.
        current = store.get_turn(OWNER, proposal.turn_id).record.turn
        assert current.state is c.TurnState.WAIT_CONFIRM and current.execution is None
        assert store.get_proposal(OWNER, proposal.proposal_id).status is c.ProposalStatus.PENDING
        assert store.count_mock_executions(proposal.proposal_id) == 0
    finally:
        store.close()


def test_lost_response_is_reconciled_with_the_same_key(tmp_path) -> None:
    store, waiting, proposal = _waiting_turn(tmp_path, "p3a-lost")
    try:
        dispatched = _confirm(store, waiting, proposal)
        execution_id = dispatched.record.turn.execution.execution_id
        # The effect landed, then the response was lost before the result was
        # recorded: the Turn is parked as UNKNOWN under the original key.
        store.apply_mock_execution(OWNER, proposal.proposal_id)
        parked = store.mark_execution_unknown(OWNER, proposal.proposal_id)
        assert parked.record.turn.state is c.TurnState.RECOVERING
        assert parked.record.turn.step is c.TurnStep.RECONCILE
        assert parked.record.turn.execution_resolution is c.ExecutionResolution.UNKNOWN
        assert parked.record.turn.execution.execution_id == execution_id

        settled = store.reconcile_mock_execution(OWNER, proposal.turn_id)
        assert settled.record.turn.state is c.TurnState.COMPLETED
        assert settled.record.turn.execution_resolution is c.ExecutionResolution.SUCCEEDED
        # Same key, one effect: reconciliation looked the effect up, it did not
        # apply a second one.
        assert settled.record.turn.execution.execution_id == execution_id
        assert store.count_mock_executions(proposal.proposal_id) == 1
        assert store.mock_ledger_financial_version(mock_fixtures.ACTIVITY_ID) == 1
    finally:
        store.close()


def test_restart_recovery_reuses_the_original_key(tmp_path) -> None:
    path = tmp_path / "p3a-restart.sqlite3"
    store = SQLiteAgentStore(path, admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        proposal = _proposal(OWNER, session, turn_id, backend=True)
        waiting = _wait_with_proposal(store, OWNER, turn_id, proposal)
        dispatched = _confirm(store, waiting, proposal)
        execution_id = dispatched.record.turn.execution.execution_id
        # Effect applied, then the process dies before the result is durable.
        store.apply_mock_execution(OWNER, proposal.proposal_id)
    finally:
        store.close()

    reopened = SQLiteAgentStore(path, admission_enabled=True)
    reopened.start()
    try:
        recovered = reopened.recover_interrupted_turns(
            now=datetime.now(timezone.utc) + timedelta(seconds=5),
        )
        assert [item.record.turn.turn_id for item in recovered] == [turn_id]
        parked = reopened.get_turn(OWNER, turn_id).record.turn
        assert parked.state is c.TurnState.RECOVERING
        assert parked.execution is not None and parked.execution.execution_id == execution_id

        settled = reopened.reconcile_mock_execution(OWNER, turn_id)
        assert settled.record.turn.state is c.TurnState.COMPLETED
        assert settled.record.turn.execution.execution_id == execution_id
        assert reopened.count_mock_executions(proposal.proposal_id) == 1
        assert reopened.mock_ledger_financial_version(mock_fixtures.ACTIVITY_ID) == 1
    finally:
        reopened.close()


def test_dispatch_refuses_a_simulation_proposal(tmp_path) -> None:
    store = SQLiteAgentStore(tmp_path / "p3a-simulation.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        proposal = _proposal(OWNER, session, turn_id, backend=False)
        waiting = _wait_with_proposal(store, OWNER, turn_id, proposal)
        request = c.ConfirmProposalRequest(
            client_request_id=uuid.uuid4(),
            expected_proposal_revision=proposal.revision,
            command_digest="0" * 64,
            confirmation_nonce="N" * 32,
        )
        with pytest.raises(MockExecutionStateError):
            store.confirm_and_dispatch(
                OWNER, proposal.proposal_id, request,
                expected_state_revision=waiting.state_revision,
                expected_proposal_revision=proposal.revision,
            )
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.WAIT_CONFIRM
    finally:
        store.close()


def test_runtime_recovery_hook_settles_under_the_original_key(tmp_path) -> None:
    """The scheduler's recovery hook, not just the store method, must settle it."""
    store, waiting, proposal = _waiting_turn(tmp_path, "p3a-hook")
    try:
        dispatched = _confirm(store, waiting, proposal)
        execution_id = dispatched.record.turn.execution.execution_id
        store.apply_mock_execution(OWNER, proposal.proposal_id)
        store.mark_execution_unknown(OWNER, proposal.proposal_id)

        claimed = store.claim_runnable("p3a-recovery-worker")
        assert claimed is not None
        assert claimed.turn.record.turn.turn_id == proposal.turn_id
        runtime = MockRuntime(
            store, MockModelProvider(), MockBackendAdapter(), _OwnerAuth(),
            MockScopeAuthorizer(), _Control(), model_timeout_seconds=1,
        )
        runtime.bind_auth_grant(
            Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1)), "runtime-token",
        )
        asyncio.run(runtime._inspect_recovery_checkpoint(claimed))

        settled = store.get_turn(OWNER, proposal.turn_id).record.turn
        assert settled.state is c.TurnState.COMPLETED
        assert settled.execution_resolution is c.ExecutionResolution.SUCCEEDED
        assert settled.execution.execution_id == execution_id
        assert store.count_mock_executions(proposal.proposal_id) == 1
        assert store.mock_ledger_financial_version(mock_fixtures.ACTIVITY_ID) == 1
    finally:
        store.close()


# --- authorization and Activity lifecycle ----------------------------------
#
# P3a has no membership table: the roster is the explicit, mutable stand-in.
# Every refusal below must happen before any effect reaches the mock ledger, and
# must leave the Turn exactly where it was so nothing is silently half-done.


def _assert_refused_without_effect(
    store: SQLiteAgentStore, proposal: c.ProposalRecord,
) -> None:
    current = store.get_turn(OWNER, proposal.turn_id).record.turn
    assert current.state is c.TurnState.WAIT_CONFIRM and current.execution is None
    assert store.get_proposal(OWNER, proposal.proposal_id).status is c.ProposalStatus.PENDING
    assert store.count_mock_executions(proposal.proposal_id) == 0
    assert store.mock_ledger_financial_version(mock_fixtures.ACTIVITY_ID) == 0


def test_actor_without_permission_cannot_dispatch_a_write(tmp_path) -> None:
    store, waiting, proposal = _waiting_turn(tmp_path, "p3a-denied")
    try:
        # An Activity the actor is not a member of is indistinguishable from one
        # that does not exist: both refuse at dispatch.
        guard = MockActivityRoster().writable_guard(OWNER)
        with pytest.raises(MockPermissionDenied) as refused:
            _confirm(store, waiting, proposal, activity_guard=guard)
        assert refused.value.code == "actor_not_permitted"
        _assert_refused_without_effect(store, proposal)
    finally:
        store.close()


def test_archived_activity_cannot_dispatch_a_write(tmp_path) -> None:
    store, waiting, proposal = _waiting_turn(tmp_path, "p3a-archived")
    try:
        guard = _roster(archived=True).writable_guard(OWNER)
        with pytest.raises(MockActivityArchived) as refused:
            _confirm(store, waiting, proposal, activity_guard=guard)
        assert refused.value.code == "activity_archived"
        _assert_refused_without_effect(store, proposal)
    finally:
        store.close()


def test_permission_revoked_after_preview_is_refused_at_dispatch(tmp_path) -> None:
    store, waiting, proposal = _waiting_turn(tmp_path, "p3a-revoked")
    try:
        roster = _roster()  # the preview was rendered while the actor was a member
        roster.remove_member(mock_fixtures.ACTIVITY_ID, OWNER)
        with pytest.raises(MockPermissionDenied):
            _confirm(store, waiting, proposal, activity_guard=roster.writable_guard(OWNER))
        _assert_refused_without_effect(store, proposal)
    finally:
        store.close()


def test_archived_after_dispatch_is_refused_before_the_effect_lands(tmp_path) -> None:
    store, waiting, proposal = _waiting_turn(tmp_path, "p3a-late-archive")
    try:
        roster = _roster()
        guard = roster.writable_guard(OWNER)
        dispatched = _confirm(store, waiting, proposal, activity_guard=guard)
        execution_id = dispatched.record.turn.execution.execution_id

        roster.archive(mock_fixtures.ACTIVITY_ID)
        with pytest.raises(MockActivityArchived):
            store.apply_mock_execution(OWNER, proposal.proposal_id, activity_guard=guard)
        assert store.count_mock_executions(proposal.proposal_id) == 0
        assert store.mock_ledger_financial_version(mock_fixtures.ACTIVITY_ID) == 0

        # The caller records the refusal as a rejection under the same key; the
        # Turn must not stay in EXECUTING with an effect that will never land.
        settled = store.settle_mock_execution(
            OWNER, proposal.proposal_id, c.ExecutionResolution.REJECTED,
            result_code=MockActivityArchived.code, result_summary="activity archived",
        )
        assert settled.record.turn.state is c.TurnState.FAILED
        assert settled.record.turn.execution_resolution is c.ExecutionResolution.REJECTED
        assert settled.record.turn.execution.execution_id == execution_id
        assert store.get_proposal(OWNER, proposal.proposal_id).status is c.ProposalStatus.REJECTED
    finally:
        store.close()


def test_recovery_hook_refuses_an_archived_activity_under_the_original_key(tmp_path) -> None:
    """Recovery must reject, not apply, when the Activity stopped accepting writes."""
    store, waiting, proposal = _waiting_turn(tmp_path, "p3a-recovery-archive")
    try:
        roster = _roster()
        guard = roster.writable_guard(OWNER)
        dispatched = _confirm(store, waiting, proposal, activity_guard=guard)
        execution_id = dispatched.record.turn.execution.execution_id
        # The outcome is unknown: dispatch committed, the effect may or may not
        # have landed. Then the Activity is archived before reconciliation.
        store.mark_execution_unknown(OWNER, proposal.proposal_id)
        roster.archive(mock_fixtures.ACTIVITY_ID)

        claimed = store.claim_runnable("p3a-recovery-archive-worker")
        assert claimed is not None
        runtime = MockRuntime(
            store, MockModelProvider(), MockBackendAdapter(), _OwnerAuth(),
            MockScopeAuthorizer(), _Control(), model_timeout_seconds=1,
            activity_roster=roster,
        )
        runtime.bind_auth_grant(
            Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1)), "runtime-token",
        )
        asyncio.run(runtime._inspect_recovery_checkpoint(claimed))

        settled = store.get_turn(OWNER, proposal.turn_id).record.turn
        assert settled.state is c.TurnState.FAILED
        assert settled.execution_resolution is c.ExecutionResolution.REJECTED
        assert settled.execution.execution_id == execution_id
        assert store.count_mock_executions(proposal.proposal_id) == 0
        assert store.mock_ledger_financial_version(mock_fixtures.ACTIVITY_ID) == 0
    finally:
        store.close()


def test_an_already_applied_effect_is_reported_after_archive_not_refused(tmp_path) -> None:
    """A later archive does not rewrite an effect that already landed."""
    store, waiting, proposal = _waiting_turn(tmp_path, "p3a-applied-then-archived")
    try:
        roster = _roster()
        guard = roster.writable_guard(OWNER)
        _confirm(store, waiting, proposal, activity_guard=guard)
        applied = store.apply_mock_execution(
            OWNER, proposal.proposal_id, activity_guard=guard,
        )
        assert applied["applied"] is True

        roster.archive(mock_fixtures.ACTIVITY_ID)
        again = store.apply_mock_execution(
            OWNER, proposal.proposal_id, activity_guard=guard,
        )
        assert again["applied"] is False
        assert again["execution_id"] == applied["execution_id"]
        assert store.count_mock_executions(proposal.proposal_id) == 1
        assert store.mock_ledger_financial_version(mock_fixtures.ACTIVITY_ID) == 1
    finally:
        store.close()


def test_effect_without_occurred_at_records_a_current_timestamp() -> None:
    """The frozen command may omit occurred_at; the ledger payload must not crash."""
    command = c.FixedExpenseCreateCommand(
        operation="expense.create",
        activity_id=mock_fixtures.ACTIVITY_ID,
        ledger_unit_id=mock_fixtures.UNIT_ID,
        title="Lunch",
        original_amount="12.50",
        original_currency="CNY",
        payment_allocations=[
            c.CanonicalPayment(participant_id=mock_fixtures.PARTICIPANT_1, amount="12.50"),
        ],
        split=c.CanonicalEqualSplit(
            mode="equal",
            participant_ids=[mock_fixtures.PARTICIPANT_1, mock_fixtures.PARTICIPANT_2],
        ),
        occurred_at=None,
        expected_financial_version="0",
    )
    effect = mock_effect_for_command(command)
    recorded = datetime.fromisoformat(effect.as_payload()["occurred_at"])
    assert recorded.tzinfo is not None
    assert abs((datetime.now(timezone.utc) - recorded).total_seconds()) < 60
