from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from agent.app import contracts as c
from agent.app.p2_read_store import (
    P2_CANDIDATE_PROFILE_ID,
    P2_MAX_ACTIVE_US,
    P2_MAX_BACKEND_US,
    P2_MAX_GETS,
    P2_MAX_LOGICAL_READS,
    P2_MAX_MODEL_CALLS,
    P2_MAX_REPAIRS,
    P2_MAX_RESPONSE_BYTES,
    CandidateChargeReservation,
    CandidateChargeSettlement,
    CandidatePageReceiptDraft,
    canonical_private_json,
    json_sha256,
)
from agent.app.store import (
    EventDraft,
    IdempotencyConflict,
    InvariantViolation,
    SQLiteAgentStore,
    StateConflict,
    StorageStartupError,
    StoreNotFound,
)


NOW = datetime(2026, 10, 14, 3, 30, tzinfo=timezone.utc)
OWNER = uuid.UUID("a1000000-0000-4000-8000-000000000001")
OTHER_OWNER = uuid.UUID("a1000000-0000-4000-8000-000000000002")
PROFILE = P2_CANDIDATE_PROFILE_ID


def _store(path: Path, *, fault: Any = None) -> SQLiteAgentStore:
    store = SQLiteAgentStore(path, fault_injector=fault)
    store.start()
    return store


def _ui() -> c.UIContext:
    return c.UIContext(page_type=c.PageType.HOME, captured_at=NOW, client_version="p2-store-cpu")


def _create_turn(
    store: SQLiteAgentStore,
    *,
    owner: uuid.UUID = OWNER,
    candidate: bool = True,
    request_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, uuid.UUID, c.SubmitTurnRequest, c.RequestReceipt]:
    session_request = c.CreateSessionRequest(
        client_request_id=uuid.uuid4(), title="P2 Store CPU", ui_context=_ui(),
    )
    session_id = store.create_session(owner, session_request, now=NOW).response_snapshot.session.session_id
    request = c.SubmitTurnRequest(
        client_request_id=request_id or uuid.uuid4(), text="Review the account and related entries", ui_context=_ui(),
    )
    receipt = store.submit_turn(
        owner, session_id, request, now=NOW,
        candidate_profile_id=PROFILE if candidate else None,
    )
    return session_id, receipt.response_snapshot.turn_id, request, receipt


def _status(snapshot: c.TurnStateSnapshot, at: datetime) -> EventDraft:
    return EventDraft(
        type=c.EventType.STATUS,
        occurred_at=at,
        simulation=False,
        payload=c.StatusEventPayload(
            state=snapshot.state,
            step=snapshot.step,
            state_revision=snapshot.state_revision,
            wait_reason=snapshot.wait_reason,
            resume_state=snapshot.resume_state,
        ),
    )


def _claim_and_run(
    store: SQLiteAgentStore,
    owner: uuid.UUID,
    turn_id: uuid.UUID,
    *,
    now: datetime = NOW + timedelta(seconds=1),
) -> str:
    claimed = store.claim_runnable("p2-store-worker", candidate_profile_id=PROFILE, now=now)
    assert claimed is not None
    assert claimed.turn.record.turn.turn_id == turn_id
    before = claimed.turn.record.turn
    after = before.model_copy(update={
        "state": c.TurnState.RUNNING,
        "state_revision": before.state_revision + 1,
        "step": c.TurnStep.MODEL_DECISION,
        "wait_reason": None,
        "resume_state": None,
    })
    store.transition_turn(
        owner,
        after,
        expected_state_revision=before.state_revision,
        expected_checkpoint_revision=claimed.turn.checkpoint_revision,
        events=[_status(after, now)],
        claim_token=claimed.claim_token,
        candidate_profile_id=PROFILE,
        now=now,
    )
    return claimed.claim_token


def _cas_args(store: SQLiteAgentStore, owner: uuid.UUID, turn_id: uuid.UUID, claim_token: str) -> dict[str, object]:
    aggregate = store.get_turn(owner, turn_id)
    candidate = store.get_p2_candidate_snapshot(owner, turn_id)
    return {
        "claim_token": claim_token,
        "expected_state_revision": aggregate.record.turn.state_revision,
        "expected_checkpoint_revision": aggregate.checkpoint_revision,
        "expected_candidate_revision": candidate.revision,
    }


def _create_query(
    store: SQLiteAgentStore,
    owner: uuid.UUID,
    turn_id: uuid.UUID,
    claim_token: str,
    *,
    query_id: uuid.UUID,
    operation: str = "read.expenses",
    criteria: dict[str, object] | None = None,
    scope: dict[str, object] | None = None,
) -> Any:
    return store.create_p2_logical_query(
        owner,
        turn_id,
        logical_query_id=query_id,
        operation=operation,
        criteria=criteria if criteria is not None else {"from_date": "2026-10-01", "to_date": "2026-10-14"},
        scope=scope if scope is not None else {"activity_id": str(uuid.UUID("b1000000-0000-4000-8000-000000000001"))},
        now=NOW + timedelta(seconds=2),
        **_cas_args(store, owner, turn_id, claim_token),
    )


def _get_and_settle(
    store: SQLiteAgentStore,
    owner: uuid.UUID,
    turn_id: uuid.UUID,
    claim_token: str,
    query_id: uuid.UUID,
    *,
    active_limit_us: int = 1_000_000,
    backend_limit_us: int = 100_000,
    bytes_limit: int = 4096,
    body: bytes = b'[{"expense":"meal"}]',
    request_marker: str = "GET /rest/v1/expenses?activity=verified",
) -> tuple[uuid.UUID, str]:
    reservation_id = uuid.uuid4()
    request_digest = hashlib.sha256(request_marker.encode("utf-8")).hexdigest()
    store.reserve_p2_candidate_stage(
        owner,
        turn_id,
        stage="backend_get",
        active_limit_us=active_limit_us,
        backend_limit_us=backend_limit_us,
        response_bytes_limit=bytes_limit,
        logical_query_id=query_id,
        request_digest=request_digest,
        reservation_id=reservation_id,
        now=NOW + timedelta(seconds=2),
        **_cas_args(store, owner, turn_id, claim_token),
    )
    body_digest = hashlib.sha256(body).hexdigest()
    store.settle_p2_candidate_stage(
        owner,
        turn_id,
        CandidateChargeSettlement(
            reservation_id=str(reservation_id),
            outcome="actual",
            actual_active_us=min(active_limit_us, max(23_000, min(47_000, backend_limit_us))),
            actual_backend_us=min(47_000, backend_limit_us),
            actual_response_bytes=len(body),
            raw_body_digest=body_digest,
            settled_at=NOW + timedelta(seconds=3),
        ),
    )
    return reservation_id, body_digest


def _append_page(
    store: SQLiteAgentStore,
    owner: uuid.UUID,
    turn_id: uuid.UUID,
    claim_token: str,
    query: Any,
    reservation_id: uuid.UUID,
    response_body_digest: str,
    *,
    page_index: int = 0,
    has_more: bool = False,
    source_complete: bool = True,
) -> tuple[uuid.UUID, str]:
    summary = store.get_p2_candidate_snapshot(owner, turn_id)
    body_chain = [{
        "ordinal": 0,
        "raw_body_digest": response_body_digest,
        "actual_response_bytes": len(b'[{"expense":"meal"}]'),
    }]
    raw_body_chain_digest = hashlib.sha256(
        json.dumps(body_chain, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    receipt_id = uuid.uuid4()
    draft = CandidatePageReceiptDraft(
        receipt_id=str(receipt_id),
        logical_query_id=str(query.logical_query_id),
        owner_user_id=str(owner),
        turn_id=str(turn_id),
        generation=summary.generation,
        input_seq=summary.input_seq,
        input_digest=summary.input_digest,
        claim_epoch=summary.claim_epoch,
        read_epoch=summary.read_epoch,
        context_revision=summary.context_revision,
        page_index=page_index,
        criteria_digest=query.criteria_digest,
        scope_digest=query.scope_digest,
        raw_body_digest=raw_body_chain_digest,
        validated_dto_digest=hashlib.sha256(b'[{"typed":"expense"}]').hexdigest(),
        projection_digest=hashlib.sha256(b'[{"fact":"expense"}]').hexdigest(),
        source_version_digest=hashlib.sha256(b"activity-financial-version:7").hexdigest(),
        observed_at=NOW + timedelta(seconds=3),
        source_query_complete=source_complete,
        model_page_has_more=has_more,
        next_page_ref_digest=hashlib.sha256(b"opaque-page-ref-never-stored").hexdigest() if has_more else None,
    )
    final_digest = store.append_p2_candidate_page_receipt(
        owner,
        turn_id,
        draft,
        get_reservation_ids=[reservation_id],
        now=NOW + timedelta(seconds=3),
        **_cas_args(store, owner, turn_id, claim_token),
    )
    return receipt_id, final_digest


def _v1_database(path: Path, *, checksum_override: str | None = None) -> str:
    initial_path = Path(__file__).resolve().parents[1] / "migrations" / "001_initial.sql"
    initial_bytes = initial_path.read_bytes()
    checksum = checksum_override or hashlib.sha256(initial_bytes).hexdigest()
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        connection.executescript(initial_bytes.decode("utf-8"))
        connection.execute(
            "INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES (1,'initial',?,?)",
            (checksum, NOW.isoformat()),
        )
        connection.execute("PRAGMA user_version=1")
    finally:
        connection.close()
    return hashlib.sha256(initial_bytes).hexdigest()


def test_agent_app_migration_upgrades_valid_v1_ledger_without_touching_initial() -> None:
    root = Path(__file__).resolve().parents[2]
    path = Path(__import__("os").environ["P2_STORE_TEST_ROOT"]) / "existing-v1.sqlite3"
    initial_hash = _v1_database(path)
    store = SQLiteAgentStore(path)
    store.start()
    store.close()
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        ledger = connection.execute("SELECT version,name,checksum FROM schema_migrations ORDER BY version").fetchall()
        assert ledger == [
            (1, "initial", initial_hash),
            (2, "p2_read_candidate", hashlib.sha256((root / "agent" / "app" / "p2_read_store_migration.sql").read_bytes()).hexdigest()),
        ]
        assert connection.execute("SELECT count(*) FROM p2_candidate_turns").fetchone()[0] == 0
    finally:
        connection.close()


def test_invalid_v1_checksum_is_rejected_before_002_and_never_auto_repaired() -> None:
    path = Path(__import__("os").environ["P2_STORE_TEST_ROOT"]) / "bad-v1-ledger.sqlite3"
    _v1_database(path, checksum_override="0" * 64)
    with pytest.raises(StorageStartupError):
        SQLiteAgentStore(path).start()
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute(
            "SELECT checksum FROM schema_migrations WHERE version=1"
        ).fetchone()[0] == "0" * 64
        assert connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='p2_candidate_turns'"
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_default_off_assignment_replay_and_legacy_worker_never_downgrade_candidate() -> None:
    path = Path(__import__("os").environ["P2_STORE_TEST_ROOT"]) / "default-off.sqlite3"
    store = _store(path)
    try:
        _, candidate_turn, candidate_request, original = _create_turn(store)
        candidate_before = store.get_p2_candidate_snapshot(OWNER, candidate_turn)
        replay = store.submit_turn(
            OWNER, original.resource_id, candidate_request, now=NOW,
            candidate_profile_id=PROFILE,
        )
        assert replay == original
        assert store.get_p2_candidate_snapshot(OWNER, candidate_turn).revision == candidate_before.revision
        assert store.claim_runnable("legacy-worker", now=NOW + timedelta(seconds=1)) is None
        assert store.claim_next("legacy-next", now=NOW + timedelta(seconds=1)) is None
        with pytest.raises(StateConflict, match="default-off canonical worker"):
            store.transition_turn(
                OWNER,
                store.get_turn(OWNER, candidate_turn).record.turn.model_copy(update={
                    "state": c.TurnState.RUNNING,
                    "state_revision": 2,
                    "step": c.TurnStep.MODEL_DECISION,
                }),
                expected_state_revision=1,
                expected_checkpoint_revision=1,
                events=[],
                now=NOW + timedelta(seconds=2),
            )
        _, legacy_turn, legacy_request, legacy_receipt = _create_turn(store, candidate=False)
        # A request-id replay cannot turn a previously canonical Turn into a candidate.
        with pytest.raises(StateConflict, match="cannot add or change"):
            store.submit_turn(
                OWNER, legacy_receipt.resource_id, legacy_request,
                candidate_profile_id=PROFILE,
            )
        _, other_legacy_turn, _, _ = _create_turn(store, owner=OTHER_OWNER, candidate=False)
        claim = store.claim_runnable("legacy-worker", now=NOW + timedelta(seconds=3))
        assert claim is not None and claim.turn.record.turn.turn_id == legacy_turn
        assert claim.turn.record.turn.turn_id != other_legacy_turn
    finally:
        store.close()


def test_submit_candidate_assignment_rolls_back_with_the_turn_and_replay_does_not_reassign() -> None:
    path = Path(__import__("os").environ["P2_STORE_TEST_ROOT"]) / "submit-rollback.sqlite3"
    should_fail = False

    def fault(name: str) -> None:
        if should_fail and name == "submit_turn.before_commit":
            raise RuntimeError("synthetic candidate submit rollback")

    store = _store(path, fault=fault)
    try:
        session_id = store.create_session(
            OWNER,
            c.CreateSessionRequest(client_request_id=uuid.uuid4(), title="rollback", ui_context=_ui()),
            now=NOW,
        ).response_snapshot.session.session_id
        request = c.SubmitTurnRequest(client_request_id=uuid.uuid4(), text="same turn", ui_context=_ui())
        should_fail = True
        with pytest.raises(RuntimeError, match="synthetic candidate"):
            store.submit_turn(OWNER, session_id, request, candidate_profile_id=PROFILE, now=NOW)
        should_fail = False
        with store._connection() as connection:
            assert connection.execute("SELECT count(*) FROM turns").fetchone()[0] == 0
            assert connection.execute("SELECT count(*) FROM p2_candidate_turns").fetchone()[0] == 0
        canonical = store.submit_turn(OWNER, session_id, request, now=NOW)
        with pytest.raises(StateConflict, match="cannot add or change"):
            store.submit_turn(OWNER, session_id, request, candidate_profile_id=PROFILE, now=NOW)
        assert store.get_turn(OWNER, canonical.response_snapshot.turn_id).record.turn.state == c.TurnState.QUEUED
    finally:
        store.close()


def test_query_replay_actual_get_chain_receipt_and_strict_page_cas() -> None:
    path = Path(__import__("os").environ["P2_STORE_TEST_ROOT"]) / "receipt-chain.sqlite3"
    store = _store(path)
    try:
        _, turn_id, _, _ = _create_turn(store)
        claim = _claim_and_run(store, OWNER, turn_id)
        query_id = uuid.uuid4()
        query = _create_query(store, OWNER, turn_id, claim, query_id=query_id)
        read_count = store.get_p2_candidate_snapshot(OWNER, turn_id).logical_read_calls
        replayed_query = _create_query(store, OWNER, turn_id, claim, query_id=query_id)
        assert replayed_query == query
        assert store.get_p2_candidate_snapshot(OWNER, turn_id).logical_read_calls == read_count == 1

        reservation_id, body_digest = _get_and_settle(store, OWNER, turn_id, claim, query_id)
        receipt_id, receipt_digest = _append_page(
            store, OWNER, turn_id, claim, query, reservation_id, body_digest,
        )
        assert len(receipt_digest) == 64
        assert store.is_p2_candidate_page_current(
            OWNER, turn_id, receipt_id,
            **_cas_args(store, OWNER, turn_id, claim), now=NOW + timedelta(seconds=4),
        )
        summary = store.get_p2_candidate_snapshot(OWNER, turn_id)
        assert summary.logical_read_calls == 1
        assert summary.get_attempts == 1
        assert summary.response_bytes == len(b'[{"expense":"meal"}]')

        # Mutated query facts or a raw continuation reference cannot be persisted as the receipt hash.
        bad = CandidatePageReceiptDraft.model_construct(
            receipt_id=str(uuid.uuid4()),
            logical_query_id=str(query_id), owner_user_id=str(OWNER), turn_id=str(turn_id),
            generation=summary.generation, input_seq=summary.input_seq, input_digest=summary.input_digest,
            claim_epoch=summary.claim_epoch, read_epoch=summary.read_epoch,
            context_revision=summary.context_revision, page_index=1,
            criteria_digest=query.criteria_digest, scope_digest=query.scope_digest,
            raw_body_digest="0" * 64, validated_dto_digest="0" * 64,
            projection_digest="0" * 64, source_version_digest="0" * 64,
            observed_at=NOW, source_query_complete=True, model_page_has_more=False,
            next_page_ref_digest=None,  # Valid shape is still rejected because page 0 is terminal.
        )
        with pytest.raises(Exception):
            store.append_p2_candidate_page_receipt(
                OWNER, turn_id, bad, get_reservation_ids=[reservation_id],
                **_cas_args(store, OWNER, turn_id, claim), now=NOW + timedelta(seconds=5),
            )
    finally:
        store.close()


def test_auth_resume_reuses_logical_query_but_never_reactivates_old_receipt() -> None:
    path = Path(__import__("os").environ["P2_STORE_TEST_ROOT"]) / "auth-resume.sqlite3"
    store = _store(path)
    try:
        _, turn_id, _, _ = _create_turn(store)
        claim = _claim_and_run(store, OWNER, turn_id)
        query_id = uuid.uuid4()
        query = _create_query(store, OWNER, turn_id, claim, query_id=query_id)
        first_reservation, body_digest = _get_and_settle(store, OWNER, turn_id, claim, query_id)
        old_receipt, _ = _append_page(
            store, OWNER, turn_id, claim, query, first_reservation, body_digest,
            has_more=True, source_complete=True,
        )
        before = store.get_p2_candidate_snapshot(OWNER, turn_id)
        before_turn = store.get_turn(OWNER, turn_id).record.turn
        wait = before_turn.model_copy(update={
            "state": c.TurnState.WAIT_INPUT,
            "state_revision": before_turn.state_revision + 1,
            "step": c.TurnStep.AUTH_REQUIRED,
            "wait_reason": c.WaitReason.AUTH_REQUIRED,
            "resume_state": c.ResumeState.QUEUED,
        })
        store.transition_turn(
            OWNER, wait,
            expected_state_revision=before_turn.state_revision,
            expected_checkpoint_revision=store.get_turn(OWNER, turn_id).checkpoint_revision,
            events=[_status(wait, NOW + timedelta(seconds=4))],
            claim_token=claim, candidate_profile_id=PROFILE,
            now=NOW + timedelta(seconds=4),
        )
        request = c.ResumeAuthRequest(
            client_request_id=uuid.uuid4(), expected_state_revision=wait.state_revision,
        )
        resumed = wait.model_copy(update={
            "state": c.TurnState.QUEUED,
            "state_revision": wait.state_revision + 1,
            "step": c.TurnStep.BUILD_CONTEXT,
            "wait_reason": None,
            "resume_state": None,
        })
        store.accept_turn_action(
            OWNER, turn_id, request, resumed,
            c.TurnMutationAccepted(
                turn_id=turn_id, state=resumed.state, state_revision=resumed.state_revision, event_cursor=0,
            ),
            events=[_status(resumed, NOW + timedelta(seconds=5))],
            now=NOW + timedelta(seconds=5),
        )
        after_auth = store.get_p2_candidate_snapshot(OWNER, turn_id)
        assert after_auth.logical_read_calls == before.logical_read_calls == 1
        assert after_auth.active_used_us == before.active_used_us
        assert after_auth.backend_used_us == before.backend_used_us
        assert after_auth.response_bytes == before.response_bytes
        new_claim = _claim_and_run(store, OWNER, turn_id, now=NOW + timedelta(seconds=6))
        reread_query = _create_query(store, OWNER, turn_id, new_claim, query_id=query_id)
        assert reread_query.logical_query_id == query.logical_query_id
        assert store.get_p2_candidate_snapshot(OWNER, turn_id).logical_read_calls == 1
        assert store.is_p2_candidate_page_current(
            OWNER, turn_id, old_receipt,
            **_cas_args(store, OWNER, turn_id, new_claim), now=NOW + timedelta(seconds=8),
        ) is False
        new_reservation, new_body = _get_and_settle(
            store, OWNER, turn_id, new_claim, query_id, request_marker="GET /rest/v1/expenses?offset=0&fresh=1",
        )
        new_receipt, _ = _append_page(
            store, OWNER, turn_id, new_claim, reread_query, new_reservation, new_body,
            has_more=False, source_complete=True,
        )
        assert store.is_p2_candidate_page_current(
            OWNER, turn_id, new_receipt,
            **_cas_args(store, OWNER, turn_id, new_claim), now=NOW + timedelta(seconds=9),
        ) is True
        assert store.get_p2_candidate_snapshot(OWNER, turn_id).get_attempts == 2
    finally:
        store.close()


def test_process_restart_charges_unknown_reservations_and_rereads_same_query_offset_zero() -> None:
    path = Path(__import__("os").environ["P2_STORE_TEST_ROOT"]) / "restart-unknown.sqlite3"
    store = _store(path)
    _, turn_id, _, _ = _create_turn(store)
    claim = _claim_and_run(store, OWNER, turn_id)
    query_id = uuid.uuid4()
    query = _create_query(store, OWNER, turn_id, claim, query_id=query_id)
    first_reservation, body_digest = _get_and_settle(store, OWNER, turn_id, claim, query_id)
    old_receipt, _ = _append_page(
        store, OWNER, turn_id, claim, query, first_reservation, body_digest,
        has_more=True, source_complete=False,
    )
    lost_reservation = uuid.uuid4()
    store.reserve_p2_candidate_stage(
        OWNER, turn_id,
        stage="backend_get", active_limit_us=700_000, backend_limit_us=80_000,
        response_bytes_limit=512, logical_query_id=query_id,
        request_digest=hashlib.sha256(b"GET /rest/v1/expenses?offset=16").hexdigest(),
        reservation_id=lost_reservation, now=NOW + timedelta(seconds=4),
        **_cas_args(store, OWNER, turn_id, claim),
    )
    store.reserve_p2_candidate_stage(
        OWNER, turn_id, stage="backend_processing", active_limit_us=100_000,
        backend_limit_us=50_000, now=NOW + timedelta(seconds=4),
        **_cas_args(store, OWNER, turn_id, claim),
    )
    store.close()

    reopened = _store(path)
    try:
        charged = reopened.get_p2_candidate_snapshot(OWNER, turn_id)
        assert charged.unknown_consumption is True
        assert charged.logical_read_calls == 1
        assert charged.get_attempts == 2
        assert charged.active_used_us >= 800_000
        assert charged.backend_used_us >= 130_000
        assert charged.response_bytes >= 512
        assert charged.active_reserved_us == charged.backend_reserved_us == charged.bytes_reserved == 0

        # Restart invalidated the receipt epoch; interrupted RUNNING work is safely requeued.
        assert reopened.is_p2_candidate_page_current(
            OWNER, turn_id, old_receipt,
            claim_token=claim,
            expected_state_revision=reopened.get_turn(OWNER, turn_id).record.turn.state_revision,
            expected_checkpoint_revision=reopened.get_turn(OWNER, turn_id).checkpoint_revision,
            expected_candidate_revision=charged.revision,
            now=NOW + timedelta(seconds=5),
        ) is False
        reopened.recover_interrupted_turns(now=NOW + timedelta(seconds=40))
        new_claim = _claim_and_run(reopened, OWNER, turn_id, now=NOW + timedelta(seconds=41))
        reread = _create_query(reopened, OWNER, turn_id, new_claim, query_id=query_id)
        assert reread.logical_query_id == query.logical_query_id
        assert reopened.get_p2_candidate_snapshot(OWNER, turn_id).logical_read_calls == 1
        fresh_get, fresh_body = _get_and_settle(
            reopened, OWNER, turn_id, new_claim, query_id,
            request_marker="GET /rest/v1/expenses?offset=0&recovery=1",
        )
        fresh_receipt, _ = _append_page(
            reopened, OWNER, turn_id, new_claim, reread, fresh_get, fresh_body,
            has_more=False, source_complete=True,
        )
        assert reopened.is_p2_candidate_page_current(
            OWNER, turn_id, fresh_receipt,
            **_cas_args(reopened, OWNER, turn_id, new_claim), now=NOW + timedelta(seconds=44),
        ) is True
        final = reopened.get_p2_candidate_snapshot(OWNER, turn_id)
        assert final.model_calls == charged.model_calls
        assert final.logical_read_calls == charged.logical_read_calls
        assert final.active_used_us >= charged.active_used_us
        assert final.get_attempts == 3
    finally:
        reopened.close()


def test_cumulative_quotas_and_fractional_active_charge_are_not_reset_or_refunded() -> None:
    path = Path(__import__("os").environ["P2_STORE_TEST_ROOT"]) / "quotas.sqlite3"
    store = _store(path)
    try:
        _, turn_id, _, _ = _create_turn(store)
        claim = _claim_and_run(store, OWNER, turn_id)
        query_ids: list[uuid.UUID] = []
        for index in range(P2_MAX_LOGICAL_READS):
            query_ids.append(uuid.uuid4())
            _create_query(
                store, OWNER, turn_id, claim, query_id=query_ids[-1],
                criteria={"bucket": index},
            )
        assert store.get_p2_candidate_snapshot(OWNER, turn_id).logical_read_calls == P2_MAX_LOGICAL_READS
        with pytest.raises(StateConflict, match="logical read budget"):
            _create_query(store, OWNER, turn_id, claim, query_id=uuid.uuid4(), criteria={"bucket": 99})

        # A repair call is a model POST too: five normal calls plus one repair use six total.
        for _ in range(P2_MAX_MODEL_CALLS - 1):
            args = _cas_args(store, OWNER, turn_id, claim)
            reservation = store.reserve_p2_candidate_stage(
                OWNER, turn_id, stage="model", active_limit_us=1,
                now=NOW + timedelta(seconds=3), **args,
            )
            store.settle_p2_candidate_stage(
                OWNER, turn_id,
                CandidateChargeSettlement(
                    reservation_id=reservation.reservation_id, outcome="actual", actual_active_us=0,
                    settled_at=NOW + timedelta(seconds=3),
                ),
            )
        repair = store.reserve_p2_candidate_stage(
            OWNER, turn_id, stage="repair", active_limit_us=1,
            now=NOW + timedelta(seconds=5), **_cas_args(store, OWNER, turn_id, claim),
        )
        store.settle_p2_candidate_stage(
            OWNER, turn_id,
            CandidateChargeSettlement(
                reservation_id=repair.reservation_id, outcome="actual", actual_active_us=0,
                settled_at=NOW + timedelta(seconds=5),
            ),
        )
        with pytest.raises(StateConflict, match="model-call budget"):
            store.reserve_p2_candidate_stage(
                OWNER, turn_id, stage="model", active_limit_us=1,
                now=NOW + timedelta(seconds=5), **_cas_args(store, OWNER, turn_id, claim),
            )
        with pytest.raises(StateConflict, match="repair budget"):
            store.reserve_p2_candidate_stage(
                OWNER, turn_id, stage="repair", active_limit_us=1,
                now=NOW + timedelta(seconds=6), **_cas_args(store, OWNER, turn_id, claim),
            )

        query_id = query_ids[0]
        for index in range(P2_MAX_GETS):
            args = _cas_args(store, OWNER, turn_id, claim)
            reservation = store.reserve_p2_candidate_stage(
                OWNER, turn_id, stage="backend_get", active_limit_us=1,
                backend_limit_us=1, response_bytes_limit=1, logical_query_id=query_id,
                request_digest=hashlib.sha256(f"get-{index}".encode()).hexdigest(),
                now=NOW + timedelta(seconds=7), **args,
            )
            store.settle_p2_candidate_stage(
                OWNER, turn_id,
                CandidateChargeSettlement(
                    reservation_id=reservation.reservation_id, outcome="actual", actual_active_us=0,
                    actual_backend_us=0, actual_response_bytes=0,
                    settled_at=NOW + timedelta(seconds=7),
                ),
            )
        final = store.get_p2_candidate_snapshot(OWNER, turn_id)
        assert final.get_attempts == P2_MAX_GETS
        assert final.model_calls == P2_MAX_MODEL_CALLS
        assert final.repair_calls == P2_MAX_REPAIRS
        assert final.logical_read_calls == P2_MAX_LOGICAL_READS
        with pytest.raises(StateConflict, match="GET-attempt budget"):
            store.reserve_p2_candidate_stage(
                OWNER, turn_id, stage="backend_get", active_limit_us=1,
                backend_limit_us=1, response_bytes_limit=1, logical_query_id=query_id,
                request_digest=hashlib.sha256(b"get-49").hexdigest(),
                now=NOW + timedelta(seconds=8), **_cas_args(store, OWNER, turn_id, claim),
            )

        # Parsing, joins and projection are backend work too, separate from GET count/bytes.
        processing = store.reserve_p2_candidate_stage(
            OWNER, turn_id, stage="backend_processing", active_limit_us=2_000,
            backend_limit_us=1_000, now=NOW + timedelta(seconds=8),
            **_cas_args(store, OWNER, turn_id, claim),
        )
        store.settle_p2_candidate_stage(
            OWNER, turn_id,
            CandidateChargeSettlement(
                reservation_id=processing.reservation_id, outcome="actual",
                actual_active_us=700, actual_backend_us=500,
                settled_at=NOW + timedelta(seconds=8),
            ),
        )
        assert store.get_p2_candidate_snapshot(OWNER, turn_id).backend_used_us == 500

        # Active usage is spent in microseconds only on explicit work reservations.
        active_reservation = store.reserve_p2_candidate_stage(
            OWNER, turn_id, stage="local_processing", active_limit_us=123_457,
            now=NOW + timedelta(seconds=9), **_cas_args(store, OWNER, turn_id, claim),
        )
        store.settle_p2_candidate_stage(
            OWNER, turn_id,
            CandidateChargeSettlement(
                reservation_id=active_reservation.reservation_id,
                outcome="actual", actual_active_us=123_456, settled_at=NOW + timedelta(seconds=9),
            ),
        )
        before_wait = store.get_p2_candidate_snapshot(OWNER, turn_id)
        running = store.get_turn(OWNER, turn_id).record.turn
        waiting = running.model_copy(update={
            "state": c.TurnState.WAIT_INPUT,
            "state_revision": running.state_revision + 1,
            "step": c.TurnStep.AWAITING_USER,
            "wait_reason": c.WaitReason.MISSING_FIELDS,
            "resume_state": c.ResumeState.QUEUED,
        })
        store.transition_turn(
            OWNER, waiting,
            expected_state_revision=running.state_revision,
            expected_checkpoint_revision=store.get_turn(OWNER, turn_id).checkpoint_revision,
            events=[_status(waiting, NOW + timedelta(seconds=10))],
            claim_token=claim, candidate_profile_id=PROFILE, now=NOW + timedelta(seconds=10),
        )
        after_wait = store.get_p2_candidate_snapshot(OWNER, turn_id)
        assert after_wait.active_used_us == before_wait.active_used_us == 123_456 + 700
        assert after_wait.active_used_us < P2_MAX_ACTIVE_US
        assert P2_MAX_BACKEND_US == 20_000_000 and P2_MAX_RESPONSE_BYTES == 4 * 1024 * 1024
    finally:
        store.close()


def test_two_store_connections_use_candidate_revision_cas_for_reservations() -> None:
    path = Path(__import__("os").environ["P2_STORE_TEST_ROOT"]) / "two-connection-cas.sqlite3"
    left = _store(path)
    right = _store(path)
    try:
        _, turn_id, _, _ = _create_turn(left)
        claim = _claim_and_run(left, OWNER, turn_id)
        args = _cas_args(left, OWNER, turn_id, claim)
        barrier = threading.Barrier(2)

        def reserve(store: SQLiteAgentStore) -> str:
            barrier.wait(timeout=2)
            try:
                store.reserve_p2_candidate_stage(
                    OWNER, turn_id, stage="local_processing", active_limit_us=500,
                    now=NOW + timedelta(seconds=2), **args,
                )
                return "reserved"
            except StateConflict:
                return "cas_refused"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = sorted(pool.map(reserve, (left, right)))
        assert results == ["cas_refused", "reserved"]
        snapshot = left.get_p2_candidate_snapshot(OWNER, turn_id)
        assert snapshot.active_reserved_us == 500
        assert snapshot.revision == int(args["expected_candidate_revision"]) + 1
    finally:
        left.close()
        right.close()


def test_backend_reservation_and_settlement_cannot_exceed_active_time() -> None:
    reservation_id = uuid.uuid4()
    with pytest.raises(ValueError, match="subset of the active-time reservation"):
        CandidateChargeReservation(
            reservation_id=str(reservation_id), profile_id=PROFILE,
            owner_user_id=str(OWNER), turn_id=str(uuid.uuid4()), stage="backend_processing",
            generation=1, claim_epoch=0, read_epoch=1, context_revision=1,
            active_limit_us=10, backend_limit_us=11, created_at=NOW,
        )
    with pytest.raises(ValueError, match="cannot exceed active execution time"):
        CandidateChargeSettlement(
            reservation_id=str(reservation_id), outcome="actual", actual_active_us=10,
            actual_backend_us=11, settled_at=NOW,
        )


def test_opening_second_store_preserves_unexpired_worker_claim_and_reservation() -> None:
    path = Path(__import__("os").environ["P2_STORE_TEST_ROOT"]) / "live-claim-second-store.sqlite3"
    left = _store(path)
    right: SQLiteAgentStore | None = None
    try:
        _, turn_id, _, _ = _create_turn(left)
        future = datetime.now(timezone.utc) + timedelta(minutes=2)
        claim = _claim_and_run(left, OWNER, turn_id, now=future)
        query_id = uuid.uuid4()
        _create_query(left, OWNER, turn_id, claim, query_id=query_id)
        reservation = left.reserve_p2_candidate_stage(
            OWNER, turn_id, stage="backend_get", active_limit_us=10_000,
            backend_limit_us=5_000, response_bytes_limit=128,
            logical_query_id=query_id, request_digest=hashlib.sha256(b"GET in flight").hexdigest(),
            now=future + timedelta(seconds=2), **_cas_args(left, OWNER, turn_id, claim),
        )
        before = left.get_p2_candidate_snapshot(OWNER, turn_id)
        assert before.backend_reserved_us == 5_000 and before.unknown_consumption is False

        # Startup of a second connection must not infer process death while the claim lease is live.
        right = _store(path)
        after_open = left.get_p2_candidate_snapshot(OWNER, turn_id)
        assert after_open.claim_epoch == before.claim_epoch
        assert after_open.revision == before.revision
        assert after_open.active_reserved_us == before.active_reserved_us == 10_000
        assert after_open.backend_reserved_us == before.backend_reserved_us == 5_000
        assert after_open.get_attempts == before.get_attempts == 1
        assert after_open.unknown_consumption is False

        # The lease takeover, rather than another Store startup, owns crash recovery.
        reclaimed = right.claim_runnable(
            "p2-store-recovery-worker", candidate_profile_id=PROFILE,
            now=future + timedelta(seconds=31),
        )
        assert reclaimed is not None and reclaimed.turn.record.turn.turn_id == turn_id
        after_takeover = right.get_p2_candidate_snapshot(OWNER, turn_id)
        assert after_takeover.claim_epoch == before.claim_epoch + 1
        assert after_takeover.active_reserved_us == after_takeover.backend_reserved_us == 0
        assert after_takeover.active_used_us == 10_000
        assert after_takeover.backend_used_us == 5_000
        assert after_takeover.response_bytes == 128
        assert after_takeover.unknown_consumption is True
        with pytest.raises(StateConflict, match="claim|current|revision"):
            left.reserve_p2_candidate_stage(
                OWNER, turn_id, stage="local_processing", active_limit_us=1,
                now=future + timedelta(seconds=32), **_cas_args(left, OWNER, turn_id, claim),
            )
        assert reservation.logical_query_id == str(query_id)
    finally:
        if right is not None:
            right.close()
        left.close()


def test_recover_interrupted_turns_preserves_live_candidate_claim_before_expired_recovery() -> None:
    path = Path(__import__("os").environ["P2_STORE_TEST_ROOT"]) / "recover-live-lease-two-stores.sqlite3"
    left = _store(path)
    right: SQLiteAgentStore | None = None
    try:
        _, turn_id, _, _ = _create_turn(left)
        future = datetime.now(timezone.utc) + timedelta(minutes=2)
        claimed = left.claim_runnable(
            "p2-live-recovery-owner", lease_seconds=30,
            candidate_profile_id=PROFILE, now=future,
        )
        assert claimed is not None and claimed.turn.record.turn.turn_id == turn_id
        claim = claimed.claim_token
        before_turn = claimed.turn.record.turn
        running = before_turn.model_copy(update={
            "state": c.TurnState.RUNNING,
            "state_revision": before_turn.state_revision + 1,
            "step": c.TurnStep.MODEL_DECISION,
            "wait_reason": None,
            "resume_state": None,
        })
        left.transition_turn(
            OWNER, running,
            expected_state_revision=before_turn.state_revision,
            expected_checkpoint_revision=claimed.turn.checkpoint_revision,
            events=[_status(running, future)],
            claim_token=claim,
            candidate_profile_id=PROFILE,
            now=future,
        )
        query_id = uuid.uuid4()
        query = left.create_p2_logical_query(
            OWNER, turn_id, logical_query_id=query_id,
            operation="read.expenses", criteria={"bucket": "all"},
            scope={"activity_id": "b1000000-0000-4000-8000-000000000001"},
            now=future + timedelta(seconds=1),
            **_cas_args(left, OWNER, turn_id, claim),
        )
        first_get, first_body = _get_and_settle(left, OWNER, turn_id, claim, query_id)
        old_receipt, _ = _append_page(
            left, OWNER, turn_id, claim, query, first_get, first_body,
            has_more=True, source_complete=False,
        )
        pending_get = uuid.uuid4()
        left.reserve_p2_candidate_stage(
            OWNER, turn_id, stage="backend_get",
            active_limit_us=700_000, backend_limit_us=80_000,
            response_bytes_limit=512, logical_query_id=query_id,
            request_digest=hashlib.sha256(b"GET /rest/v1/expenses?offset=16").hexdigest(),
            reservation_id=pending_get, now=future + timedelta(seconds=4),
            **_cas_args(left, OWNER, turn_id, claim),
        )
        before_aggregate = left.get_turn(OWNER, turn_id)
        before_candidate = left.get_p2_candidate_snapshot(OWNER, turn_id)
        before_events = left.read_turn_view(OWNER, turn_id).events
        assert before_aggregate.record.turn.state == c.TurnState.RUNNING
        assert before_aggregate.claim_token == claim
        assert before_aggregate.claim_until == future + timedelta(seconds=30)
        assert before_candidate.lifecycle == "active"
        assert before_candidate.active_reserved_us == 700_000
        assert before_candidate.backend_reserved_us == 80_000
        assert before_candidate.bytes_reserved == 512
        assert before_candidate.unknown_consumption is False

        right = _store(path)
        live_recovery = right.recover_interrupted_turns(now=future + timedelta(seconds=10))
        assert live_recovery == []
        after_live = right.get_turn(OWNER, turn_id)
        after_live_candidate = right.get_p2_candidate_snapshot(OWNER, turn_id)
        assert after_live.record.turn == before_aggregate.record.turn
        assert after_live.checkpoint_revision == before_aggregate.checkpoint_revision
        assert after_live.claim_token == before_aggregate.claim_token == claim
        assert after_live.claim_until == before_aggregate.claim_until
        assert after_live_candidate == before_candidate
        assert right.read_turn_view(OWNER, turn_id).events == before_events
        with sqlite3.connect(path) as connection:
            pending_edges = connection.execute(
                "SELECT event_kind, unknown_flag FROM p2_candidate_charge_events WHERE reservation_id = ? ORDER BY event_kind",
                (str(pending_get),),
            ).fetchall()
            page_count = connection.execute(
                "SELECT COUNT(*) FROM p2_candidate_page_receipts WHERE logical_query_id = ?",
                (str(query_id),),
            ).fetchone()[0]
        assert pending_edges == [("reserved", 0)]
        assert page_count == 1

        expired_at = future + timedelta(seconds=31)
        recovered = right.recover_interrupted_turns(now=expired_at)
        assert len(recovered) == 1
        recovered_turn = right.get_turn(OWNER, turn_id)
        recovered_candidate = right.get_p2_candidate_snapshot(OWNER, turn_id)
        assert recovered_turn.record.turn.state == c.TurnState.QUEUED
        assert recovered_turn.claim_token is None and recovered_turn.claim_until is None
        assert recovered_candidate.claim_epoch == before_candidate.claim_epoch + 1
        assert recovered_candidate.read_epoch == before_candidate.read_epoch + 1
        assert recovered_candidate.active_used_us == before_candidate.active_used_us + 700_000
        assert recovered_candidate.backend_used_us == before_candidate.backend_used_us + 80_000
        assert recovered_candidate.response_bytes == before_candidate.response_bytes + 512
        assert recovered_candidate.active_reserved_us == 0
        assert recovered_candidate.backend_reserved_us == 0
        assert recovered_candidate.bytes_reserved == 0
        assert recovered_candidate.unknown_consumption is True
        assert right.recover_interrupted_turns(now=expired_at + timedelta(seconds=1)) == []
        assert right.get_p2_candidate_snapshot(OWNER, turn_id) == recovered_candidate
        with sqlite3.connect(path) as connection:
            pending_edges = connection.execute(
                "SELECT event_kind, unknown_flag FROM p2_candidate_charge_events WHERE reservation_id = ? ORDER BY event_kind",
                (str(pending_get),),
            ).fetchall()
            page_count = connection.execute(
                "SELECT COUNT(*) FROM p2_candidate_page_receipts WHERE logical_query_id = ?",
                (str(query_id),),
            ).fetchone()[0]
        assert pending_edges == [("reserved", 0), ("unknown", 1)]
        assert page_count == 1

        new_claimed = right.claim_runnable(
            "p2-after-recovery", candidate_profile_id=PROFILE,
            now=expired_at + timedelta(seconds=2),
        )
        assert new_claimed is not None and new_claimed.turn.record.turn.turn_id == turn_id
        new_claim = new_claimed.claim_token
        queued = new_claimed.turn.record.turn
        new_running = queued.model_copy(update={
            "state": c.TurnState.RUNNING,
            "state_revision": queued.state_revision + 1,
            "step": c.TurnStep.MODEL_DECISION,
            "wait_reason": None,
            "resume_state": None,
        })
        right.transition_turn(
            OWNER, new_running,
            expected_state_revision=queued.state_revision,
            expected_checkpoint_revision=new_claimed.turn.checkpoint_revision,
            events=[_status(new_running, expired_at + timedelta(seconds=2))],
            claim_token=new_claim,
            candidate_profile_id=PROFILE,
            now=expired_at + timedelta(seconds=2),
        )
        assert right.is_p2_candidate_page_current(
            OWNER, turn_id, old_receipt,
            **_cas_args(right, OWNER, turn_id, new_claim),
            now=expired_at + timedelta(seconds=2),
        ) is False

        old_snapshot = before_candidate
        stale_draft = CandidatePageReceiptDraft(
            receipt_id=str(uuid.uuid4()), logical_query_id=str(query_id),
            owner_user_id=str(OWNER), turn_id=str(turn_id),
            generation=old_snapshot.generation, input_seq=old_snapshot.input_seq,
            input_digest=old_snapshot.input_digest, claim_epoch=old_snapshot.claim_epoch,
            read_epoch=old_snapshot.read_epoch, context_revision=old_snapshot.context_revision,
            page_index=1, criteria_digest=query.criteria_digest, scope_digest=query.scope_digest,
            raw_body_digest=hashlib.sha256(b"stale-body-chain").hexdigest(),
            validated_dto_digest=hashlib.sha256(b"stale-dto").hexdigest(),
            projection_digest=hashlib.sha256(b"stale-projection").hexdigest(),
            source_version_digest=hashlib.sha256(b"stale-version").hexdigest(),
            observed_at=expired_at + timedelta(seconds=2),
            source_query_complete=False, model_page_has_more=False,
        )
        current_turn = right.get_turn(OWNER, turn_id)
        current_candidate = right.get_p2_candidate_snapshot(OWNER, turn_id)
        with pytest.raises(StateConflict, match="claim|current|RUNNING|revision"):
            right.append_p2_candidate_page_receipt(
                OWNER, turn_id, stale_draft, claim_token=new_claim,
                get_reservation_ids=[pending_get],
                expected_state_revision=current_turn.record.turn.state_revision,
                expected_checkpoint_revision=current_turn.checkpoint_revision,
                expected_candidate_revision=current_candidate.revision,
                now=expired_at + timedelta(seconds=2),
            )
        assert right.get_p2_candidate_snapshot(OWNER, turn_id) == current_candidate
    finally:
        if right is not None:
            right.close()
        left.close()


def test_backend_time_is_cumulative_across_processing_and_get_and_overrun_must_be_unknown() -> None:
    path = Path(__import__("os").environ["P2_STORE_TEST_ROOT"]) / "backend-time-cross-stage.sqlite3"
    store = _store(path)
    try:
        _, turn_id, _, _ = _create_turn(store)
        claim = _claim_and_run(store, OWNER, turn_id)
        process_reservation = store.reserve_p2_candidate_stage(
            OWNER, turn_id, stage="backend_processing", active_limit_us=P2_MAX_BACKEND_US,
            backend_limit_us=P2_MAX_BACKEND_US - 100,
            now=NOW + timedelta(seconds=2), **_cas_args(store, OWNER, turn_id, claim),
        )
        processed = store.settle_p2_candidate_stage(
            OWNER, turn_id,
            CandidateChargeSettlement(
                reservation_id=process_reservation.reservation_id,
                outcome="actual", actual_active_us=P2_MAX_BACKEND_US,
                actual_backend_us=P2_MAX_BACKEND_US - 100,
                settled_at=NOW + timedelta(seconds=3),
            ),
        )
        assert processed.backend_used_us == P2_MAX_BACKEND_US - 100

        query_id = uuid.uuid4()
        _create_query(store, OWNER, turn_id, claim, query_id=query_id)
        with pytest.raises(StateConflict, match="backend-time budget"):
            store.reserve_p2_candidate_stage(
                OWNER, turn_id, stage="backend_get", active_limit_us=10_000,
                backend_limit_us=101, response_bytes_limit=10,
                logical_query_id=query_id, request_digest=hashlib.sha256(b"GET over").hexdigest(),
                now=NOW + timedelta(seconds=4), **_cas_args(store, OWNER, turn_id, claim),
            )

        reservation = store.reserve_p2_candidate_stage(
            OWNER, turn_id, stage="backend_get", active_limit_us=10_000,
            backend_limit_us=100, response_bytes_limit=10, logical_query_id=query_id,
            request_digest=hashlib.sha256(b"GET exact remainder").hexdigest(),
            now=NOW + timedelta(seconds=4), **_cas_args(store, OWNER, turn_id, claim),
        )
        with pytest.raises(ValueError, match="exceeds its durable reservation"):
            store.settle_p2_candidate_stage(
                OWNER, turn_id,
                CandidateChargeSettlement(
                    reservation_id=reservation.reservation_id,
                    outcome="actual", actual_active_us=10_000,
                    actual_backend_us=101, actual_response_bytes=10,
                    raw_body_digest=hashlib.sha256(b"0123456789").hexdigest(),
                    settled_at=NOW + timedelta(seconds=5),
                ),
            )
        # Runtime must convert an observed overrun into explicit conservative UNKNOWN,
        # never publish the result or leave the reservation uncharged.
        final = store.settle_p2_candidate_stage(
            OWNER, turn_id,
            CandidateChargeSettlement(
                reservation_id=reservation.reservation_id,
                outcome="unknown", actual_active_us=10_000,
                actual_backend_us=100, actual_response_bytes=10,
                overrun_backend_us=1,
                settled_at=NOW + timedelta(seconds=6),
            ),
        )
        assert final.backend_used_us == P2_MAX_BACKEND_US
        assert final.get_attempts == 1 and final.response_bytes == 10
        assert final.unknown_consumption is True
        connection = sqlite3.connect(path)
        try:
            diagnostic = connection.execute(
                "SELECT event_kind,actual_backend_us,overrun_backend_us FROM p2_candidate_charge_events WHERE reservation_id=? AND event_kind='unknown'",
                (reservation.reservation_id,),
            ).fetchone()
            assert diagnostic == ("unknown", 100, 1)
        finally:
            connection.close()
        with pytest.raises(StateConflict, match="already settled"):
            store.settle_p2_candidate_stage(
                OWNER, turn_id,
                CandidateChargeSettlement(
                    reservation_id=reservation.reservation_id,
                    outcome="unknown", actual_active_us=10_000,
                    actual_backend_us=100, actual_response_bytes=10,
                    settled_at=NOW + timedelta(seconds=7),
                ),
            )
        with pytest.raises(StateConflict, match="backend-time budget"):
            store.reserve_p2_candidate_stage(
                OWNER, turn_id, stage="backend_processing", active_limit_us=1_000,
                backend_limit_us=1, now=NOW + timedelta(seconds=8),
                **_cas_args(store, OWNER, turn_id, claim),
            )
        store.close()
        store = _store(path)
        reopened = store.get_p2_candidate_snapshot(OWNER, turn_id)
        assert reopened.backend_used_us == P2_MAX_BACKEND_US
        assert reopened.unknown_consumption is True
    finally:
        store.close()


def test_cancel_invalidates_receipts_but_late_worker_can_only_settle_charge() -> None:
    path = Path(__import__("os").environ["P2_STORE_TEST_ROOT"]) / "cancel-late-settle.sqlite3"
    store = _store(path)
    try:
        _, turn_id, _, _ = _create_turn(store)
        claim = _claim_and_run(store, OWNER, turn_id)
        query_id = uuid.uuid4()
        query = _create_query(store, OWNER, turn_id, claim, query_id=query_id)
        reservation = store.reserve_p2_candidate_stage(
            OWNER, turn_id, stage="backend_get", active_limit_us=1_000_000,
            backend_limit_us=100_000, response_bytes_limit=128,
            logical_query_id=query_id, request_digest=hashlib.sha256(b"GET /read").hexdigest(),
            now=NOW + timedelta(seconds=2), **_cas_args(store, OWNER, turn_id, claim),
        )
        before = store.get_turn(OWNER, turn_id).record.turn
        after = before.model_copy(update={
            "state": c.TurnState.CANCELLED,
            "state_revision": before.state_revision + 1,
            "step": c.TurnStep.TERMINAL,
            "wait_reason": None,
            "resume_state": None,
        })
        public = c.TurnPublicStatus(
            turn_id=turn_id, session_id=before.session_id, state=after.state, step=after.step,
            wait_reason=None, resume_state=None, state_revision=after.state_revision,
            execution_assigned=False, execution_resolution=None, context_version=after.context_version,
        )
        cancel = c.CancelTurnRequest(client_request_id=uuid.uuid4(), expected_state_revision=before.state_revision)
        store.accept_turn_action(
            OWNER, turn_id, cancel, after,
            c.CancelTurnResponse(turn=public, result="cancelled"),
            events=[_status(after, NOW + timedelta(seconds=3))], now=NOW + timedelta(seconds=3),
        )
        cancelled = store.get_p2_candidate_snapshot(OWNER, turn_id)
        assert cancelled.lifecycle == "terminal"
        assert cancelled.active_reserved_us == 1_000_000
        # A drained stale worker may durably settle its real cost; it has no API to publish facts.
        body = b"[]"
        body_digest = hashlib.sha256(body).hexdigest()
        settled = store.settle_p2_candidate_stage(
            OWNER, turn_id,
            CandidateChargeSettlement(
                reservation_id=reservation.reservation_id,
                outcome="actual", actual_active_us=100,
                actual_backend_us=10, actual_response_bytes=len(body),
                raw_body_digest=body_digest, settled_at=NOW + timedelta(seconds=4),
            ),
        )
        assert settled.active_used_us == 100
        assert settled.active_reserved_us == 0
        with pytest.raises(StateConflict):
            store.append_p2_candidate_page_receipt(
                OWNER, turn_id,
                CandidatePageReceiptDraft.model_construct(
                    receipt_id=str(uuid.uuid4()), logical_query_id=str(query_id),
                    owner_user_id=str(OWNER), turn_id=str(turn_id), generation=1,
                    input_seq=1, input_digest="0" * 64, claim_epoch=0, read_epoch=1,
                    context_revision=1, page_index=0, criteria_digest=query.criteria_digest,
                    scope_digest=query.scope_digest, raw_body_digest="0" * 64,
                    validated_dto_digest="0" * 64, projection_digest="0" * 64,
                    source_version_digest="0" * 64, observed_at=NOW,
                    source_query_complete=False, model_page_has_more=False,
                    next_page_ref_digest=None,
                ),
                claim_token=claim, get_reservation_ids=[reservation.reservation_id],
                expected_state_revision=after.state_revision,
                expected_checkpoint_revision=store.get_turn(OWNER, turn_id).checkpoint_revision,
                expected_candidate_revision=settled.revision, now=NOW + timedelta(seconds=5),
            )
    finally:
        store.close()


def test_private_query_descriptors_reject_credential_capability_and_float_fields() -> None:
    assert canonical_private_json({"currency": "USD", "owner_id": str(OWNER)}) == json.dumps(
        {"currency": "USD", "owner_id": str(OWNER)}, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    for bad in (
        {"accessToken": "hidden"},
        {"next_page_ref": "opaque"},
        {"secret": "hidden"},
        {"minimum": 1.25},
    ):
        with pytest.raises(ValueError):
            canonical_private_json(bad)
