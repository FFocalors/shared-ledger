from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from agent.app import contracts as c
from agent.app import mock_fixtures
from agent.app.store import EventDraft, IdempotencyConflict, InvariantViolation, ProposalConflict, SQLiteAgentStore, StateConflict, StorageStartupError, StoreNotFound, TurnCheckpoint

NOW = datetime(2026, 10, 8, 4, 0, tzinfo=timezone.utc)
OWNER = uuid.uuid4()
OTHER_OWNER = uuid.uuid4()


def _store(path: Path, *, fault: Any = None) -> SQLiteAgentStore:
    store = SQLiteAgentStore(path, fault_injector=fault)
    store.start()
    return store


def _session(store: SQLiteAgentStore, owner: uuid.UUID = OWNER, *, request_id: uuid.UUID | None = None) -> uuid.UUID:
    ui = c.UIContext(page_type=c.PageType.HOME, captured_at=NOW, client_version="p1-test")
    request = c.CreateSessionRequest(client_request_id=request_id or uuid.uuid4(), title="Trip", ui_context=ui)
    return store.create_session(owner, request, now=NOW).response_snapshot.session.session_id


def _submit(store: SQLiteAgentStore, session_id: uuid.UUID, owner: uuid.UUID = OWNER, *, request_id: uuid.UUID | None = None, text: str = "Record lunch") -> tuple[c.RequestReceipt, uuid.UUID]:
    ui = c.UIContext(page_type=c.PageType.ACTIVITY_OVERVIEW, activity_id=mock_fixtures.ACTIVITY_ID, captured_at=NOW, client_version="p1-test")
    request = c.SubmitTurnRequest(client_request_id=request_id or uuid.uuid4(), text=text, ui_context=ui)
    receipt = store.submit_turn(owner, session_id, request, now=NOW)
    return receipt, receipt.response_snapshot.turn_id


def _snapshot(before: c.TurnStateSnapshot, *, state: c.TurnState, step: c.TurnStep, revision: int | None = None, wait_reason: c.WaitReason | None = None, resume_state: c.ResumeState | None = None, execution: c.ExecutionIdentity | None = None, resolution: c.ExecutionResolution | None = None) -> c.TurnStateSnapshot:
    return c.TurnStateSnapshot.model_validate(before.model_dump(mode="python", by_alias=True, exclude_none=False) | {
        "state": state, "step": step, "state_revision": revision if revision is not None else before.state_revision + 1,
        "wait_reason": wait_reason, "resume_state": resume_state,
        "execution": (execution if execution is not None else before.execution).model_dump(mode="python", by_alias=True, exclude_none=False) if (execution is not None or before.execution is not None) else None,
        "execution_resolution": resolution if resolution is not None else before.execution_resolution,
    })


def _status(snapshot: c.TurnStateSnapshot, *, at: datetime = NOW) -> EventDraft:
    return EventDraft(type=c.EventType.STATUS, occurred_at=at, simulation=False, payload=c.StatusEventPayload(
        state=snapshot.state, step=snapshot.step, state_revision=snapshot.state_revision,
        wait_reason=snapshot.wait_reason, resume_state=snapshot.resume_state))


def _proposal_event(proposal: c.ProposalRecord, *, at: datetime = NOW) -> EventDraft:
    return EventDraft(type=c.EventType.PROPOSAL, occurred_at=at, simulation=proposal.mode == "simulation",
        payload=c.ProposalEventPayload(proposal_id=proposal.proposal_id, revision=proposal.revision, operation=proposal.operation))


def _to_running(store: SQLiteAgentStore, owner: uuid.UUID, turn_id: uuid.UUID) -> c.TurnStateSnapshot:
    aggregate = store.get_turn(owner, turn_id)
    before = aggregate.record.turn
    after = _snapshot(before, state=c.TurnState.RUNNING, step=c.TurnStep.MODEL_DECISION)
    store.transition_turn(owner, after, expected_state_revision=before.state_revision,
        expected_checkpoint_revision=aggregate.checkpoint_revision, events=[_status(after)], now=NOW + timedelta(seconds=1))
    return after


def _waiting_snapshot(running: c.TurnStateSnapshot) -> c.TurnStateSnapshot:
    return _snapshot(running, state=c.TurnState.WAIT_CONFIRM, step=c.TurnStep.AWAITING_USER, wait_reason=c.WaitReason.CONFIRM_REQUIRED)


def _fixture_preview() -> c.ExpensePreview:
    trajectory = mock_fixtures.propose_wait_confirm_and_confirm_disabled()
    step = next(item for item in trajectory.steps if isinstance(item, c.ProposalCardStep))
    return step.card.preview


def _proposal(owner: uuid.UUID, session_id: uuid.UUID, turn_id: uuid.UUID, *, backend: bool = False, revision: int = 1, nonce: str = "N" * 32, receipts: list[c.RequestReceipt] | None = None) -> c.ProposalRecord:
    intent = mock_fixtures._expense_create(mock_fixtures.references(turn_id))
    preview_data = _fixture_preview().model_dump(mode="python", by_alias=True, exclude_none=False)
    preview_data["simulation"] = not backend
    preview = c.ExpensePreview.model_validate(preview_data)
    command = preconditions = digest = confirmation_nonce = None
    mode: str = "simulation"
    if backend:
        mode = "backend"
        command = c.FixedExpenseCreateCommand(operation="expense.create", activity_id=mock_fixtures.ACTIVITY_ID,
            ledger_unit_id=mock_fixtures.UNIT_ID, title="Lunch", original_amount="12.50", original_currency="CNY",
            payment_allocations=[c.CanonicalPayment(participant_id=mock_fixtures.PARTICIPANT_1, amount="12.50")],
            split=c.CanonicalEqualSplit(mode="equal", participant_ids=[mock_fixtures.PARTICIPANT_1, mock_fixtures.PARTICIPANT_2]),
            occurred_at=NOW, expected_financial_version="0")
        preconditions = c.PreconditionSnapshot(activity_id=mock_fixtures.ACTIVITY_ID, permission_checked=True,
            agent_disable_revision=0, activity_financial_version="0", expense_version=None, policy_version="p1-test", verified_at=NOW)
        digest = c.canonical_command_digest(command, preconditions, policy_version="p1-test")
        confirmation_nonce = nonce
    return c.ProposalRecord(proposal_id=uuid.uuid4(), owner_user_id=owner, session_id=session_id, turn_id=turn_id,
        revision=revision, operation="expense.create", mode=mode, status=c.ProposalStatus.PENDING, intent=intent,
        canonical_command=command, preview=preview, preconditions=preconditions, command_digest=digest,
        confirmation_nonce=confirmation_nonce, policy_version="p1-test",
        # The API and Store compare expiry against the real clock, so a fixed
        # NOW-based deadline rots: this fixture's proposals silently became
        # expired on 2026-10-13. Keep the other fixture timestamps frozen for
        # deterministic event ordering, but make the deadline live-relative.
        expires_at=datetime.now(timezone.utc) + timedelta(days=5),
        execution=None, request_receipts=receipts or [])


def _wait_with_proposal(store: SQLiteAgentStore, owner: uuid.UUID, turn_id: uuid.UUID, proposal: c.ProposalRecord) -> c.TurnStateSnapshot:
    running = _to_running(store, owner, turn_id)
    waiting = _waiting_snapshot(running)
    aggregate = store.get_turn(owner, turn_id)
    store.transition_turn(owner, waiting, expected_state_revision=running.state_revision,
        expected_checkpoint_revision=aggregate.checkpoint_revision, events=[_status(waiting), _proposal_event(proposal)],
        new_proposal=proposal, now=NOW + timedelta(seconds=2))
    return waiting


def _public(snapshot: c.TurnStateSnapshot) -> c.TurnPublicStatus:
    return c.TurnPublicStatus(turn_id=snapshot.turn_id, session_id=snapshot.session_id, state=snapshot.state,
        step=snapshot.step, wait_reason=snapshot.wait_reason, resume_state=snapshot.resume_state,
        state_revision=snapshot.state_revision, execution_assigned=snapshot.execution is not None,
        execution_resolution=snapshot.execution_resolution, context_version=snapshot.context_version)




def test_different_store_connections_serialize_global_submit_idempotency(tmp_path: Path) -> None:
    path = tmp_path / "shared.sqlite3"
    left, right = _store(path), _store(path)
    session = _session(left)
    key = uuid.uuid4()
    ui = c.UIContext(page_type=c.PageType.HOME, captured_at=NOW, client_version="test")
    request = c.SubmitTurnRequest(client_request_id=key, text="same body", ui_context=ui)
    barrier = threading.Barrier(2)
    def submit(store: SQLiteAgentStore) -> c.RequestReceipt:
        barrier.wait(timeout=3)
        return store.submit_turn(OWNER, session, request, now=NOW)
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(submit, (left, right)))
    assert receipts[0] == receipts[1]
    turn_id = receipts[0].response_snapshot.turn_id
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM turns").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM events WHERE turn_id = ?", (str(turn_id),)).fetchone()[0] == 1
    second_session = _session(left)
    with pytest.raises(IdempotencyConflict):
        right.submit_turn(OWNER, second_session, request, now=NOW)
    with pytest.raises(IdempotencyConflict):
        right.submit_turn(OWNER, session, request.model_copy(update={"text": "changed"}), now=NOW)
    altered_context = ui.model_copy(update={"client_version": "different-context"})
    with pytest.raises(IdempotencyConflict):
        right.submit_turn(OWNER, session, request.model_copy(update={"ui_context": altered_context}), now=NOW)
    with pytest.raises(StoreNotFound):
        right.get_turn(OTHER_OWNER, turn_id)
    left.close(); right.close()


def test_resume_receipt_and_full_input_survive_restart_and_replay_before_state_check(tmp_path: Path) -> None:
    path = tmp_path / "resume.sqlite3"
    store = _store(path)
    session = _session(store)
    _, turn_id = _submit(store, session, text="original request with full context")
    running = _to_running(store, OWNER, turn_id)
    waiting = _snapshot(running, state=c.TurnState.WAIT_INPUT, step=c.TurnStep.AWAITING_USER,
        wait_reason=c.WaitReason.MISSING_FIELDS, resume_state=c.ResumeState.QUEUED)
    aggregate = store.get_turn(OWNER, turn_id)
    store.transition_turn(OWNER, waiting, expected_state_revision=running.state_revision,
        expected_checkpoint_revision=aggregate.checkpoint_revision, events=[_status(waiting)], now=NOW + timedelta(seconds=2))
    aggregate = store.get_turn(OWNER, turn_id)
    checkpoint_with_budget = TurnCheckpoint.model_validate(
        aggregate.checkpoint.model_dump(mode="python", by_alias=True, exclude_none=False)
        | {"model_calls": 4, "read_calls": 3, "repair_calls": 1}
    )
    store.save_checkpoint(OWNER, turn_id, expected_state_revision=waiting.state_revision,
        expected_checkpoint_revision=aggregate.checkpoint_revision, checkpoint=checkpoint_with_budget,
        now=NOW + timedelta(milliseconds=500))
    request = c.ResumeClarificationRequest(client_request_id=uuid.uuid4(), expected_state_revision=waiting.state_revision, text="payer is Alex")
    accepted = _snapshot(waiting, state=c.TurnState.QUEUED, step=c.TurnStep.MODEL_DECISION)
    cursor = store.read_turn_view(OWNER, turn_id).event_cursor + 1
    response = c.TurnMutationAccepted(turn_id=turn_id, state=accepted.state, state_revision=accepted.state_revision, event_cursor=cursor)
    receipt = store.accept_turn_action(OWNER, turn_id, request, accepted, response, events=[_status(accepted)], now=NOW + timedelta(seconds=3))
    running_after = _snapshot(accepted, state=c.TurnState.RUNNING, step=c.TurnStep.MODEL_DECISION)
    aggregate = store.get_turn(OWNER, turn_id)
    store.transition_turn(OWNER, running_after, expected_state_revision=accepted.state_revision,
        expected_checkpoint_revision=aggregate.checkpoint_revision, events=[_status(running_after)], now=NOW + timedelta(seconds=4))
    original_submit = aggregate.checkpoint.accepted_inputs[0].payload
    assert isinstance(original_submit, c.SubmitTurnRequest)
    store.close()
    restarted = _store(path)
    durable = restarted.get_turn(OWNER, turn_id)
    assert durable.record.turn.state == c.TurnState.RUNNING
    assert durable.checkpoint.accepted_inputs[0].payload == original_submit
    assert durable.checkpoint.accepted_inputs[0].payload.ui_context.activity_id == mock_fixtures.ACTIVITY_ID
    assert durable.checkpoint.accepted_inputs[-1].payload == request
    assert durable.checkpoint.generation == 2
    assert (durable.checkpoint.model_calls, durable.checkpoint.read_calls, durable.checkpoint.repair_calls) == (0, 0, 0)
    replay = restarted.accept_turn_action(OWNER, turn_id, request, accepted, response, events=[], now=NOW + timedelta(seconds=5))
    assert replay == receipt
    with pytest.raises(IdempotencyConflict):
        restarted.accept_turn_action(OWNER, turn_id, request.model_copy(update={"text": "different clarification"}), accepted, response, events=[_status(accepted)])
    assert restarted.read_turn_view(OWNER, turn_id).event_cursor == 5
    restarted.close()


def test_checkpoint_reference_and_read_result_bindings_are_append_only_across_restart(tmp_path: Path) -> None:
    path = tmp_path / "bindings.sqlite3"
    store = _store(path)
    session = _session(store)
    _, turn_id = _submit(store, session)
    aggregate = store.get_turn(OWNER, turn_id)
    references = mock_fixtures.references(turn_id)
    results = mock_fixtures.tool_results(references)[:2]
    result_bindings = c.bind_stable_read_results([], [c.ResolvedReadResultCandidate(
        result_ref=item.result_ref, result_id=item.result_id, operation=item.operation,
        observed_at=item.observed_at, context_version=item.context_version) for item in results], source_turn_id=turn_id)
    reference_index = {item.ref: item for item in references}
    evidence_candidates: list[c.ResolvedEvidenceCandidate] = []
    for result in results:
        for fact in result.body.items:
            token = fact.activity_ref if isinstance(fact, c.ActivityFact) else fact.expense_ref
            entity = reference_index[token]
            evidence_candidates.append(c.ResolvedEvidenceCandidate(kind=fact.kind, entity_id=entity.entity_id,
                scope_activity_id=entity.scope_activity_id, source_result_id=result.result_id, context_version=result.context_version))
    evidence = c.bind_stable_evidence([], evidence_candidates, source_turn_id=turn_id)
    checkpoint = TurnCheckpoint.model_validate(aggregate.checkpoint.model_dump(mode="python", by_alias=True, exclude_none=False) | {"read_results": results})
    store.save_checkpoint(OWNER, turn_id, expected_state_revision=aggregate.record.turn.state_revision,
        expected_checkpoint_revision=aggregate.checkpoint_revision, checkpoint=checkpoint,
        bound_references=references, bound_evidence_references=evidence, bound_read_results=result_bindings,
        now=NOW + timedelta(seconds=1))
    store.close()
    restarted = _store(path)
    read = restarted.get_turn(OWNER, turn_id)
    assert read.record.bound_references == references
    assert read.record.bound_evidence_references == evidence
    assert read.record.bound_read_results == result_bindings
    assert read.checkpoint.read_results == results
    rebound = list(references)
    rebound[0] = rebound[0].model_copy(update={"entity_id": uuid.uuid4()})
    with pytest.raises(InvariantViolation, match="cannot be removed or rebound"):
        restarted.save_checkpoint(OWNER, turn_id, expected_state_revision=read.record.turn.state_revision,
            expected_checkpoint_revision=read.checkpoint_revision, checkpoint=read.checkpoint,
            bound_references=rebound, bound_evidence_references=evidence, bound_read_results=result_bindings)
    restarted.close()



def test_two_store_cas_and_queue_claim_have_single_winners(tmp_path: Path) -> None:
    path = tmp_path / "cas.sqlite3"
    left, right = _store(path), _store(path)
    session = _session(left)
    _, turn_id = _submit(left, session)
    current = left.get_turn(OWNER, turn_id)
    before = current.record.turn
    after = _snapshot(before, state=c.TurnState.RUNNING, step=c.TurnStep.MODEL_DECISION)
    barrier = threading.Barrier(2)
    def transition(store: SQLiteAgentStore) -> str:
        barrier.wait(timeout=3)
        try:
            store.transition_turn(OWNER, after, expected_state_revision=before.state_revision,
                expected_checkpoint_revision=current.checkpoint_revision, events=[_status(after)], now=NOW + timedelta(seconds=1))
            return "won"
        except StateConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(transition, (left, right)))
    assert sorted(results) == ["conflict", "won"]
    view = left.read_turn_view(OWNER, turn_id)
    assert view.turn.record.turn.state == c.TurnState.RUNNING
    assert [event.seq for event in view.events] == [1, 2]
    _, queued_id = _submit(left, session)
    claim_barrier = threading.Barrier(2)
    def claim(store: SQLiteAgentStore) -> Any:
        claim_barrier.wait(timeout=3)
        return store.claim_next("worker", now=NOW + timedelta(seconds=5))
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(claim, (left, right)))
    winners = [item for item in claims if item is not None]
    assert len(winners) == 1
    assert winners[0].turn.record.turn.turn_id == queued_id
    assert left.claim_next("worker-2", now=NOW + timedelta(seconds=6)) is None
    assert right.release_claim(queued_id, winners[0].claim_token)
    left.close(); right.close()


def test_migration_restart_and_fail_closed_schema_and_projection_checks(tmp_path: Path) -> None:
    valid = tmp_path / "valid.sqlite3"
    store = _store(valid)
    session = _session(store)
    _, turn_id = _submit(store, session)
    store.close()
    reopened = _store(valid)
    assert reopened.get_turn(OWNER, turn_id).record.turn.state == c.TurnState.QUEUED
    reopened.close()

    damaged_index = tmp_path / "missing-index.sqlite3"
    db = _store(damaged_index); db.close()
    with sqlite3.connect(damaged_index) as connection:
        connection.execute("DROP INDEX one_pending_proposal_per_session_idx")
    with pytest.raises(StorageStartupError):
        SQLiteAgentStore(damaged_index).start()

    damaged_projection = tmp_path / "bad-projection.sqlite3"
    db = _store(damaged_projection)
    session = _session(db); _, turn_id = _submit(db, session); db.close()
    with sqlite3.connect(damaged_projection) as connection:
        connection.execute("UPDATE turns SET state = 'FAILED' WHERE turn_id = ?", (str(turn_id),))
    with pytest.raises(StorageStartupError):
        SQLiteAgentStore(damaged_projection).start()

    future = tmp_path / "future.sqlite3"
    with sqlite3.connect(future) as connection:
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(StorageStartupError):
        SQLiteAgentStore(future).start()


def test_migration_and_business_faults_roll_back_without_losing_existing_storage(tmp_path: Path) -> None:
    migration_path = tmp_path / "migration-fault.sqlite3"
    sqlite3.connect(migration_path).close()
    def fail_migration(name: str) -> None:
        if name == "migration.before_commit":
            raise RuntimeError("injected migration fault")
    with pytest.raises(StorageStartupError):
        SQLiteAgentStore(migration_path, fault_injector=fail_migration).start()
    with sqlite3.connect(migration_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
    repaired = _store(migration_path)
    session = _session(repaired)
    turn_key = uuid.uuid4()
    request = c.SubmitTurnRequest(client_request_id=turn_key, text="durable")
    def fail_submit(name: str) -> None:
        if name == "submit_turn.before_commit":
            raise RuntimeError("injected write fault")
    writer = SQLiteAgentStore(migration_path, fault_injector=fail_submit); writer.start()
    with pytest.raises(RuntimeError, match="injected write fault"):
        writer.submit_turn(OWNER, session, request, now=NOW)
    writer.close()
    with sqlite3.connect(migration_path) as connection:
        assert connection.execute("SELECT count(*) FROM turns").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM events").fetchone()[0] == 0
    repaired.close()


def test_process_exit_before_and_after_commit_recovers_atomic_turn_and_event(tmp_path: Path) -> None:
    child = tmp_path / "crash_writer.py"
    child.write_text("""import os, sys, uuid
from pathlib import Path
from agent.app.contracts import SubmitTurnRequest
from agent.app.store import SQLiteAgentStore
path, phase, owner, session_id, body = sys.argv[1:]
def fault(name):
    if name == 'submit_turn.' + phase + '_commit': os._exit(73)
store = SQLiteAgentStore(Path(path), fault_injector=fault)
store.start()
request = SubmitTurnRequest.model_validate_json(body)
store.submit_turn(uuid.UUID(owner), uuid.UUID(session_id), request)
""", encoding="utf-8")
    path = tmp_path / "crash.sqlite3"
    store = _store(path)
    owner = uuid.uuid4(); owned_session = _session(store, owner)
    request = c.SubmitTurnRequest(client_request_id=uuid.uuid4(), text="process crash")
    env = os.environ.copy(); env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    for phase, expected_count in (("before", 0), ("after", 1)):
        proc = subprocess.run([sys.executable, str(child), str(path), phase, str(owner), str(owned_session), request.model_dump_json()],
            env=env, check=False, timeout=15)
        assert proc.returncode == 73
        store.close(); store = _store(path)
        with sqlite3.connect(path) as connection:
            assert connection.execute("SELECT count(*) FROM turns WHERE owner_user_id = ?", (str(owner),)).fetchone()[0] == expected_count
            assert connection.execute("SELECT count(*) FROM events WHERE owner_user_id = ?", (str(owner),)).fetchone()[0] == expected_count
        if expected_count:
            replay = store.submit_turn(owner, owned_session, request)
            assert replay.response_snapshot.turn_id
    assert store.probe_ready()
    store.close()



def test_pending_proposal_index_is_atomic_across_stores_and_cancel_clears_row(tmp_path: Path) -> None:
    path = tmp_path / "pending.sqlite3"
    left, right = _store(path), _store(path)
    session = _session(left)
    _, turn_a = _submit(left, session); _, turn_b = _submit(left, session)
    running_a = _to_running(left, OWNER, turn_a); running_b = _to_running(left, OWNER, turn_b)
    proposal_a = _proposal(OWNER, session, turn_a, backend=True); proposal_b = _proposal(OWNER, session, turn_b, backend=True)
    barrier = threading.Barrier(2)
    def propose(args: tuple[SQLiteAgentStore, c.TurnStateSnapshot, c.ProposalRecord]) -> str:
        store, running, proposal = args
        waiting = _waiting_snapshot(running)
        barrier.wait(timeout=3)
        try:
            store.transition_turn(OWNER, waiting, expected_state_revision=running.state_revision,
                expected_checkpoint_revision=store.get_turn(OWNER, running.turn_id).checkpoint_revision,
                events=[_status(waiting), _proposal_event(proposal)], new_proposal=proposal, now=NOW + timedelta(seconds=3))
            return "won"
        except ProposalConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(propose, ((left, running_a, proposal_a), (right, running_b, proposal_b))))
    assert sorted(result) == ["conflict", "won"]
    winner = proposal_a if result[0] == "won" else proposal_b
    waiting = left.get_turn(OWNER, winner.turn_id).record.turn
    cancel_request = c.CancelTurnRequest(client_request_id=uuid.uuid4(), expected_state_revision=waiting.state_revision)
    cancelled = _snapshot(waiting, state=c.TurnState.CANCELLED, step=c.TurnStep.TERMINAL)
    cancel_response = c.CancelTurnResponse(turn=_public(cancelled), result="cancelled")
    receipt = left.accept_turn_action(OWNER, winner.turn_id, cancel_request, cancelled, cancel_response,
        events=[_status(cancelled)], now=NOW + timedelta(seconds=4))
    assert receipt.response_snapshot == cancel_response
    persisted = right.get_proposal(OWNER, winner.proposal_id)
    assert persisted.status == c.ProposalStatus.CANCELLED
    assert persisted.confirmation_nonce is None
    left.close(); right.close()


def test_late_planning_output_loses_to_cancel_state_revision_cas(tmp_path: Path) -> None:
    store = _store(tmp_path / "late-cancel.sqlite3")
    session = _session(store); _, turn_id = _submit(store, session)
    running = _to_running(store, OWNER, turn_id)
    cancel_request = c.CancelTurnRequest(client_request_id=uuid.uuid4(), expected_state_revision=running.state_revision)
    cancelled = _snapshot(running, state=c.TurnState.CANCELLED, step=c.TurnStep.TERMINAL)
    receipt = store.accept_turn_action(OWNER, turn_id, cancel_request, cancelled,
        c.CancelTurnResponse(turn=_public(cancelled), result="cancelled"), events=[_status(cancelled)], now=NOW + timedelta(seconds=2))
    assert receipt.response_kind == c.RequestReceiptKind.TURN_CANCELLED
    stale = _snapshot(running, state=c.TurnState.WAIT_CONFIRM, step=c.TurnStep.AWAITING_USER, wait_reason=c.WaitReason.CONFIRM_REQUIRED)
    proposal = _proposal(OWNER, session, turn_id)
    with pytest.raises(StateConflict):
        store.transition_turn(OWNER, stale, expected_state_revision=running.state_revision,
            expected_checkpoint_revision=store.get_turn(OWNER, turn_id).checkpoint_revision,
            events=[_status(stale), _proposal_event(proposal)], new_proposal=proposal)
    view = store.read_turn_view(OWNER, turn_id)
    assert view.turn.record.turn.state == c.TurnState.CANCELLED
    assert view.event_cursor == 3
    store.close()


def test_adjustment_keeps_confirmation_receipts_and_rotates_nonce_atomically(tmp_path: Path) -> None:
    path = tmp_path / "adjust.sqlite3"
    store = _store(path)
    session = _session(store); _, turn_id = _submit(store, session)
    proposal = _proposal(OWNER, session, turn_id, backend=True)
    waiting = _wait_with_proposal(store, OWNER, turn_id, proposal)
    confirm_request = c.ConfirmProposalRequest(client_request_id=uuid.uuid4(), expected_proposal_revision=proposal.revision,
        command_digest=proposal.command_digest, confirmation_nonce=proposal.confirmation_nonce)
    unavailable = c.ConfirmationUnavailableResponse(code="execution_capability_unavailable", message="Confirmation is unavailable in this phase.")
    confirm_receipt = store.record_confirmation_unavailable(OWNER, proposal.proposal_id, confirm_request, unavailable,
        expected_revision=proposal.revision, now=NOW + timedelta(seconds=3))
    current = store.get_proposal(OWNER, proposal.proposal_id)
    request = c.ResumeProposalAdjustRequest(client_request_id=uuid.uuid4(), expected_state_revision=waiting.state_revision,
        expected_proposal_revision=current.revision, text="Change the title")
    replacement = c.ProposalRecord.model_validate(current.model_dump(mode="python", by_alias=True, exclude_none=False)
        | {"revision": 2, "confirmation_nonce": "R" * 32, "request_receipts": []})
    running = _snapshot(waiting, state=c.TurnState.RUNNING, step=c.TurnStep.MODEL_DECISION)
    final = _snapshot(running, state=c.TurnState.WAIT_CONFIRM, step=c.TurnStep.AWAITING_USER, wait_reason=c.WaitReason.CONFIRM_REQUIRED)
    cursor = store.read_turn_view(OWNER, turn_id).event_cursor
    adjusted = store.adjust_proposal(OWNER, turn_id, proposal.proposal_id, request, replacement,
        events=[_status(running), _status(final), _proposal_event(replacement)], now=NOW + timedelta(seconds=4))
    assert adjusted.response_snapshot.state_revision == waiting.state_revision + 2
    assert adjusted.response_snapshot.event_cursor == cursor + 3
    saved = store.get_proposal(OWNER, proposal.proposal_id)
    assert saved.confirmation_nonce == "R" * 32
    assert saved.request_receipts == [confirm_receipt]
    assert store.get_session(OWNER, session).updated_at == NOW + timedelta(seconds=4)
    store.close()
    restarted = _store(path)
    replay = restarted.adjust_proposal(OWNER, turn_id, proposal.proposal_id, request, replacement, events=[], now=NOW + timedelta(seconds=5))
    assert replay == adjusted
    assert restarted.get_proposal(OWNER, proposal.proposal_id).request_receipts == [confirm_receipt]
    assert restarted.record_confirmation_unavailable(OWNER, proposal.proposal_id, confirm_request, unavailable,
        expected_revision=proposal.revision) == confirm_receipt
    restarted.close()



def test_execution_fixture_unknown_outcome_keeps_original_identity_for_recovery(tmp_path: Path) -> None:
    path = tmp_path / "execution-recovery.sqlite3"
    store = _store(path)
    session = _session(store); _, turn_id = _submit(store, session)
    proposal = _proposal(OWNER, session, turn_id, backend=True)
    waiting = _wait_with_proposal(store, OWNER, turn_id, proposal)
    execution = c.ExecutionIdentity(execution_id=c.derive_execution_id(OWNER, proposal.proposal_id, proposal.revision),
        actor_id=OWNER, proposal_id=proposal.proposal_id, proposal_revision=proposal.revision)
    executing = _snapshot(waiting, state=c.TurnState.EXECUTING, step=c.TurnStep.DISPATCH, execution=execution)
    confirmed = c.ProposalRecord.model_validate(proposal.model_dump(mode="python", by_alias=True, exclude_none=False)
        | {"status": c.ProposalStatus.CONFIRMED, "confirmation_nonce": None, "execution": execution.model_dump(mode="python", by_alias=True, exclude_none=False)})
    aggregate = store.get_turn(OWNER, turn_id)
    store.transition_turn(OWNER, executing, expected_state_revision=waiting.state_revision,
        expected_checkpoint_revision=aggregate.checkpoint_revision, events=[_status(executing)],
        updated_proposal=confirmed, fixture_execution=True, now=NOW + timedelta(seconds=3))
    unknown = _snapshot(executing, state=c.TurnState.RECOVERING, step=c.TurnStep.RECONCILE,
        resolution=c.ExecutionResolution.UNKNOWN)
    ref = c.ExecutionReference(execution_id=execution.execution_id, proposal_id=proposal.proposal_id, proposal_revision=proposal.revision)
    result_event = EventDraft(type=c.EventType.EXECUTION_RESULT, occurred_at=NOW + timedelta(seconds=4), simulation=False,
        payload=c.ExecutionResultPayload(execution=ref, resolution=c.ExecutionResolution.UNKNOWN))
    aggregate = store.get_turn(OWNER, turn_id)
    store.transition_turn(OWNER, unknown, expected_state_revision=executing.state_revision,
        expected_checkpoint_revision=aggregate.checkpoint_revision, events=[_status(unknown), result_event], now=NOW + timedelta(seconds=4))
    candidate = next(item for item in store.list_recovery_candidates() if item.turn.record.turn.turn_id == turn_id)
    assert candidate.disposition == "reconcile_execution"
    assert candidate.turn.record.turn.execution == execution
    assert candidate.turn.record.turn.execution_resolution == c.ExecutionResolution.UNKNOWN
    assert store.recover_interrupted_turns(now=NOW + timedelta(seconds=5)) == []
    store.close()
    reopened = _store(path)
    recovered = reopened.get_turn(OWNER, turn_id).record.turn
    assert recovered.state == c.TurnState.RECOVERING
    assert recovered.execution == execution
    assert recovered.execution_resolution == c.ExecutionResolution.UNKNOWN

    # Authentication pauses an assigned recovery without resetting its budget or identity.
    aggregate = reopened.get_turn(OWNER, turn_id)
    generation = aggregate.checkpoint.generation
    budget = TurnCheckpoint.model_validate(
        aggregate.checkpoint.model_dump(mode="python", by_alias=True, exclude_none=False)
        | {"model_calls": 4, "read_calls": 3, "repair_calls": 1}
    )
    reopened.save_checkpoint(OWNER, turn_id, expected_state_revision=recovered.state_revision,
        expected_checkpoint_revision=aggregate.checkpoint_revision, checkpoint=budget, now=NOW + timedelta(seconds=6))
    paused = _snapshot(recovered, state=c.TurnState.WAIT_INPUT, step=c.TurnStep.AUTH_REQUIRED,
        wait_reason=c.WaitReason.AUTH_REQUIRED, resume_state=c.ResumeState.RECOVERING)
    aggregate = reopened.get_turn(OWNER, turn_id)
    reopened.transition_turn(OWNER, paused, expected_state_revision=recovered.state_revision,
        expected_checkpoint_revision=aggregate.checkpoint_revision, events=[_status(paused)], now=NOW + timedelta(seconds=7))
    assert next(item for item in reopened.list_recovery_candidates()
        if item.turn.record.turn.turn_id == turn_id).disposition == "await_input"
    auth_request = c.ResumeAuthRequest(client_request_id=uuid.uuid4(), expected_state_revision=paused.state_revision)
    resumed = _snapshot(paused, state=c.TurnState.RECOVERING, step=c.TurnStep.RECONCILE)
    cursor = reopened.read_turn_view(OWNER, turn_id).event_cursor + 1
    auth_response = c.TurnMutationAccepted(turn_id=turn_id, state=resumed.state,
        state_revision=resumed.state_revision, event_cursor=cursor)
    auth_receipt = reopened.accept_turn_action(OWNER, turn_id, auth_request, resumed, auth_response,
        events=[_status(resumed)], now=NOW + timedelta(seconds=8))
    after_resume = reopened.get_turn(OWNER, turn_id)
    assert after_resume.record.turn.execution == execution
    assert after_resume.record.turn.execution_resolution == c.ExecutionResolution.UNKNOWN
    assert after_resume.checkpoint.generation == generation
    assert (after_resume.checkpoint.model_calls, after_resume.checkpoint.read_calls,
            after_resume.checkpoint.repair_calls) == (4, 3, 1)
    assert next(item for item in reopened.list_recovery_candidates()
        if item.turn.record.turn.turn_id == turn_id).disposition == "reconcile_execution"
    reopened.close()
    reopened = _store(path)
    durable = reopened.get_turn(OWNER, turn_id)
    assert durable.record.turn.state == c.TurnState.RECOVERING
    assert durable.record.turn.execution == execution
    assert durable.record.turn.execution_resolution == c.ExecutionResolution.UNKNOWN
    assert durable.checkpoint.generation == generation
    assert (durable.checkpoint.model_calls, durable.checkpoint.read_calls,
            durable.checkpoint.repair_calls) == (4, 3, 1)
    assert reopened.accept_turn_action(OWNER, turn_id, auth_request, resumed, auth_response, events=[]) == auth_receipt
    reopened.close()


def test_auth_pause_preserves_pending_proposal_and_replays_resume_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "auth-confirm.sqlite3"
    store = _store(path)
    session = _session(store)
    _, turn_id = _submit(store, session)
    proposal = _proposal(OWNER, session, turn_id, backend=True)
    waiting = _wait_with_proposal(store, OWNER, turn_id, proposal)
    aggregate = store.get_turn(OWNER, turn_id)
    generation = aggregate.checkpoint.generation
    checkpoint = TurnCheckpoint.model_validate(
        aggregate.checkpoint.model_dump(mode="python", by_alias=True, exclude_none=False)
        | {"model_calls": 3, "read_calls": 2, "repair_calls": 1}
    )
    store.save_checkpoint(OWNER, turn_id, expected_state_revision=waiting.state_revision,
        expected_checkpoint_revision=aggregate.checkpoint_revision, checkpoint=checkpoint, now=NOW + timedelta(seconds=3))
    paused = _snapshot(waiting, state=c.TurnState.WAIT_INPUT, step=c.TurnStep.AUTH_REQUIRED,
        wait_reason=c.WaitReason.AUTH_REQUIRED, resume_state=c.ResumeState.WAIT_CONFIRM)
    aggregate = store.get_turn(OWNER, turn_id)
    store.transition_turn(OWNER, paused, expected_state_revision=waiting.state_revision,
        expected_checkpoint_revision=aggregate.checkpoint_revision, events=[_status(paused)], now=NOW + timedelta(seconds=4))
    pending = store.get_proposal(OWNER, proposal.proposal_id)
    assert pending.status == c.ProposalStatus.PENDING
    assert pending.confirmation_nonce == proposal.confirmation_nonce
    pause_checkpoint = store.get_turn(OWNER, turn_id).checkpoint
    assert pause_checkpoint.generation == generation
    assert (pause_checkpoint.model_calls, pause_checkpoint.read_calls, pause_checkpoint.repair_calls) == (3, 2, 1)

    request = c.ResumeAuthRequest(client_request_id=uuid.uuid4(), expected_state_revision=paused.state_revision)
    resumed = _snapshot(paused, state=c.TurnState.WAIT_CONFIRM, step=c.TurnStep.AWAITING_USER,
        wait_reason=c.WaitReason.CONFIRM_REQUIRED)
    cursor = store.read_turn_view(OWNER, turn_id).event_cursor + 1
    response = c.TurnMutationAccepted(turn_id=turn_id, state=resumed.state,
        state_revision=resumed.state_revision, event_cursor=cursor)
    receipt = store.accept_turn_action(OWNER, turn_id, request, resumed, response,
        events=[_status(resumed)], now=NOW + timedelta(seconds=5))
    assert store.get_proposal(OWNER, proposal.proposal_id).confirmation_nonce == proposal.confirmation_nonce
    saved = store.get_turn(OWNER, turn_id)
    assert saved.checkpoint.generation == generation
    assert (saved.checkpoint.model_calls, saved.checkpoint.read_calls, saved.checkpoint.repair_calls) == (3, 2, 1)
    store.close()

    restarted = _store(path)
    durable = restarted.get_turn(OWNER, turn_id)
    assert durable.record.turn == resumed
    assert restarted.get_proposal(OWNER, proposal.proposal_id).confirmation_nonce == proposal.confirmation_nonce
    assert durable.checkpoint.generation == generation
    assert (durable.checkpoint.model_calls, durable.checkpoint.read_calls, durable.checkpoint.repair_calls) == (3, 2, 1)
    assert restarted.accept_turn_action(OWNER, turn_id, request, resumed, response, events=[]) == receipt
    assert restarted.read_turn_view(OWNER, turn_id).event_cursor == cursor
    restarted.close()



def test_session_creation_receipt_preserves_original_response_and_request_after_turn_activity(tmp_path: Path) -> None:
    path = tmp_path / "session-receipt.sqlite3"
    store = _store(path)
    ui = c.UIContext(page_type=c.PageType.HOME, captured_at=NOW, client_version="client-1")
    request = c.CreateSessionRequest(client_request_id=uuid.uuid4(), title="Trip", ui_context=ui)
    original = store.create_session(OWNER, request, now=NOW)
    session_id = original.response_snapshot.session.session_id
    _, _ = _submit(store, session_id)
    active = store.get_session(OWNER, session_id)
    assert active.updated_at >= NOW
    assert active.create_response == original.response_snapshot
    store.close()

    restarted = _store(path)
    replay = restarted.create_session(OWNER, request, now=NOW + timedelta(days=1))
    assert replay == original
    assert restarted.get_session(OWNER, session_id).create_response == original.response_snapshot
    changed_context = c.UIContext(page_type=c.PageType.HOME, captured_at=NOW, client_version="client-2")
    with pytest.raises(IdempotencyConflict):
        restarted.create_session(OWNER, request.model_copy(update={"ui_context": changed_context}), now=NOW)
    restarted.close()




def test_wait_confirm_requires_proposal_and_generic_terminal_transition_closes_pending_nonce(tmp_path: Path) -> None:
    path = tmp_path / "terminal-proposal.sqlite3"
    store = _store(path)
    session = _session(store); _, turn_id = _submit(store, session)
    running = _to_running(store, OWNER, turn_id)
    waiting = _waiting_snapshot(running)
    aggregate = store.get_turn(OWNER, turn_id)
    with pytest.raises(InvariantViolation, match="pending proposal"):
        store.transition_turn(OWNER, waiting, expected_state_revision=running.state_revision,
            expected_checkpoint_revision=aggregate.checkpoint_revision, events=[_status(waiting)])
    assert store.get_turn(OWNER, turn_id).record.turn == running

    proposal = _proposal(OWNER, session, turn_id, backend=True)
    aggregate = store.get_turn(OWNER, turn_id)
    store.transition_turn(OWNER, waiting, expected_state_revision=running.state_revision,
        expected_checkpoint_revision=aggregate.checkpoint_revision,
        events=[_status(waiting), _proposal_event(proposal)], new_proposal=proposal, now=NOW + timedelta(seconds=2))
    failed = _snapshot(waiting, state=c.TurnState.FAILED, step=c.TurnStep.TERMINAL)
    aggregate = store.get_turn(OWNER, turn_id)
    store.transition_turn(OWNER, failed, expected_state_revision=waiting.state_revision,
        expected_checkpoint_revision=aggregate.checkpoint_revision, events=[_status(failed)], now=NOW + timedelta(seconds=4))
    persisted = store.get_proposal(OWNER, proposal.proposal_id)
    assert persisted.status == c.ProposalStatus.CANCELLED
    assert persisted.confirmation_nonce is None
    store.close()
    reopened = _store(path)
    assert reopened.get_proposal(OWNER, proposal.proposal_id).confirmation_nonce is None
    reopened.close()
