from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent.app import contracts as c
from agent.app import p2_backend as p2_backend
from agent.app import p2_read_backend as p2_read_backend
from agent.app import p2_read_contracts_v3 as p2_read_contracts_v3
from agent.app import p2_source_codec_v3 as p2_source_codec_v3
from agent.app.p2_source_store_v3 import (
    P2V3RequestReferenceRegistry,
    P2V3StoreConflict,
    P2V3StoreNotFound,
    P2V3UnsupportedProfile,
    P2_V3_CANDIDATE_PROFILE_ID,
    P2_V3_MAX_ACTIVE_US,
    P2_V3_MAX_BACKEND_US,
    P2_V3_MAX_GETS,
    P2_V3_MAX_LOGICAL_READS,
    P2_V3_MAX_RESPONSE_BYTES,
    P2_V3_MAX_MODEL_CALLS,
)
from agent.app.p2_read_store import P2_CANDIDATE_PROFILE_ID
from agent.app.p2_v3_store_ports import P2V3StoreBudgetPort
from agent.app.store import EventDraft, SQLiteAgentStore, StateConflict, StoreNotFound
from agent.app import p2_v3_execution_cohort as cohort_verifier
from agent.app.p2_read_contracts_v3 import ExpenseCriteria, P2Scope, P2_V3_VERSIONS


OWNER = uuid.UUID("a1000000-0000-4000-8000-000000000001")
ACTIVITY_ID = uuid.UUID("b1000000-0000-4000-8000-000000000001")
LEDGER_UNIT_ID = uuid.UUID("b1000000-0000-4000-8000-000000000002")
ACTIVITY_REF = "ref_abcdefghijklmnopqrstuv"
LEDGER_UNIT_REF = "ref_zyxwvutsrqponmlkjihgfedc"
EXPENSE_REF_1 = "ref_abcdefghijklmno12345678"
EXPENSE_REF_2 = "ref_qwertyuiopasdfghjklzxcvbn"
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def _store(tmp_path: Path, name: str) -> SQLiteAgentStore:
    root = Path(__import__("os").environ["P2_V3_STORE_TEST_ROOT"])
    root.mkdir(parents=True, exist_ok=True)
    store = _configured_store(root / f"{name}.sqlite3", admission_enabled=True)
    store.start()
    return store


def _configured_store(
    path: Path,
    *,
    allow_synthetic_cohort: bool = True,
    **kwargs: object,
) -> SQLiteAgentStore:
    """Use a server-verified synthetic cohort only inside this explicit CPU fixture."""
    root = Path(__import__("os").environ["P2_V3_STORE_TEST_ROOT"])
    component_root = root / "synthetic-cohort-components"
    component_root.mkdir(parents=True, exist_ok=True)
    component_path = component_root / "fixture.json"
    fixture_bytes = b'{"purpose":"isolated Stage A CPU fixture"}'
    if component_path.exists() and component_path.read_bytes() != fixture_bytes:
        raise AssertionError("synthetic cohort fixture changed during this test run")
    if not component_path.exists():
        component_path.write_bytes(fixture_bytes)
    components = [{
        "path": "fixture.json", "role": "synthetic_fixture", "bytes": len(fixture_bytes),
        "sha256": hashlib.sha256(fixture_bytes).hexdigest(),
    }]
    canonical = lambda value: json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    document = {
        "format": "p2-v3-execution-manifest",
        "manifest_kind": "synthetic_test",
        "profile_id": P2_V3_CANDIDATE_PROFILE_ID,
        "versions": P2_V3_VERSIONS.model_dump(mode="json"),
        "schema_bundle_sha256": hashlib.sha256(b"synthetic-test-schema-bundle").hexdigest(),
        "source_manifest_sha256": hashlib.sha256(canonical(components)).hexdigest(),
        "contract_source_sha256": hashlib.sha256(b"synthetic-test-contract-snapshot").hexdigest(),
        "components": components,
        "safe_config": {
            "debt_source_variant": "expense_debt_line",
            "budgets": dict(cohort_verifier._BUDGETS),
        },
    }
    manifest_bytes = canonical(document)
    manifest_path = root / "synthetic-cohort-manifest.json"
    if manifest_path.exists() and manifest_path.read_bytes() != manifest_bytes:
        raise AssertionError("synthetic cohort manifest changed during this test run")
    if not manifest_path.exists():
        manifest_path.write_bytes(manifest_bytes)
    return SQLiteAgentStore(
        path,
        p2_v3_execution_manifest_path=manifest_path,
        p2_v3_execution_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        p2_v3_execution_repository_root=Path(__file__).parents[1],
        p2_v3_execution_external_component_roots={"synthetic_fixture": component_root},
        test_only_allow_synthetic_p2_v3_cohort=allow_synthetic_cohort,
        **kwargs,
    )


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


def _public(snapshot: c.TurnStateSnapshot) -> c.TurnPublicStatus:
    return c.TurnPublicStatus(
        turn_id=snapshot.turn_id,
        session_id=snapshot.session_id,
        state=snapshot.state,
        step=snapshot.step,
        wait_reason=snapshot.wait_reason,
        resume_state=snapshot.resume_state,
        state_revision=snapshot.state_revision,
        execution_assigned=snapshot.execution is not None,
        execution_resolution=snapshot.execution_resolution,
        context_version=snapshot.context_version,
    )


def _create_running_turn(store: SQLiteAgentStore, *, now: datetime = NOW + timedelta(seconds=1)) -> tuple[uuid.UUID, str]:
    submitted_at = now - timedelta(seconds=1)
    ui = c.UIContext(page_type=c.PageType.HOME, captured_at=submitted_at, client_version="p2-v3-store-edge")
    session = store.create_session(
        OWNER,
        c.CreateSessionRequest(client_request_id=uuid.uuid4(), title="P2 v3 store edge", ui_context=ui),
        now=submitted_at,
    ).response_snapshot.session.session_id
    submitted = store.submit_turn(
        OWNER,
        session,
        c.SubmitTurnRequest(client_request_id=uuid.uuid4(), text="Read the current shared ledger", ui_context=ui),
        now=submitted_at,
        candidate_profile_id=P2_V3_CANDIDATE_PROFILE_ID,
    )
    turn_id = submitted.response_snapshot.turn_id
    claimed = store.claim_runnable(
        "p2v3-edge-worker", candidate_profile_id=P2_V3_CANDIDATE_PROFILE_ID, now=now,
    )
    assert claimed is not None
    assert claimed.turn.record.turn.turn_id == turn_id
    assert claimed.execution_profile_id == P2_V3_CANDIDATE_PROFILE_ID
    before = claimed.turn.record.turn
    after = before.model_copy(update={
        "state": c.TurnState.RUNNING,
        "state_revision": before.state_revision + 1,
        "step": c.TurnStep.BUILD_CONTEXT,
        "wait_reason": None,
        "resume_state": None,
    })
    store.transition_turn(
        OWNER,
        after,
        expected_state_revision=before.state_revision,
        expected_checkpoint_revision=claimed.turn.checkpoint_revision,
        events=[_status(after, now)],
        claim_token=claimed.claim_token,
        candidate_profile_id=P2_V3_CANDIDATE_PROFILE_ID,
        now=now,
    )
    return turn_id, claimed.claim_token


def _create_queued_turn(
    store: SQLiteAgentStore, *, candidate_profile: bool, owner: uuid.UUID = OWNER,
    legacy_candidate: bool = False,
) -> uuid.UUID:
    ui = c.UIContext(page_type=c.PageType.HOME, captured_at=NOW, client_version="p2-v3-mixed-claim")
    session = store.create_session(
        owner,
        c.CreateSessionRequest(client_request_id=uuid.uuid4(), title="Mixed claim", ui_context=ui),
        now=NOW,
    ).response_snapshot.session.session_id
    submitted = store.submit_turn(
        owner,
        session,
        c.SubmitTurnRequest(client_request_id=uuid.uuid4(), text="Read the current shared ledger", ui_context=ui),
        now=NOW,
        candidate_profile_id=(
            P2_V3_CANDIDATE_PROFILE_ID if candidate_profile else
            P2_CANDIDATE_PROFILE_ID if legacy_candidate else None
        ),
    )
    return submitted.response_snapshot.turn_id


def _scope() -> dict[str, object]:
    return {
        "scope_kind": "activity",
        "scope_ref": ACTIVITY_REF,
        "activity_ref": ACTIVITY_REF,
        "ledger_unit_ref": None,
    }


def _admission(store: SQLiteAgentStore, turn_id: uuid.UUID, claim_token: str, at: datetime) -> str:
    return store.create_p2_v3_source_admission(
        OWNER,
        turn_id,
        claim_token=claim_token,
        requested_scope={"scope_kind": "activity", "activity_id": str(ACTIVITY_ID)},
        public_scope=_scope(),
        ui_hint={"activity_id": str(ACTIVITY_ID)},
        now=at,
    )


def _query_and_attempt(
    store: SQLiteAgentStore,
    turn_id: uuid.UUID,
    claim_token: str,
    admission_id: str,
    at: datetime,
    *,
    logical_query_id: str | None = None,
) -> tuple[str, str, int]:
    snapshot = store.get_p2_v3_snapshot(OWNER, turn_id)
    query_id = store.create_p2_v3_logical_query(
        OWNER,
        turn_id,
        claim_token=claim_token,
        admission_id=admission_id,
        operation="read.expenses",
        criteria={"kind": "expenses", "activity_ref": ACTIVITY_REF},
        scope=_scope(),
        expected_revision=snapshot.revision,
        logical_query_id=logical_query_id,
        now=at,
    )
    attempt_id, attempt_seq = store.begin_p2_v3_query_attempt(
        OWNER, turn_id,
        claim_token=claim_token,
        logical_query_id=query_id,
        admission_id=admission_id,
        now=at + timedelta(milliseconds=1),
    )
    return query_id, attempt_id, attempt_seq


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _dispatch_model(
    store: SQLiteAgentStore,
    turn_id: uuid.UUID,
    claim_token: str,
    at: datetime,
    *,
    stage: str = "model",
) -> str:
    reservation = store.reserve_p2_v3_stage(
        OWNER, turn_id,
        claim_token=claim_token,
        stage=stage,
        active_limit_us=1_000,
        now=at,
    )
    store.mark_p2_v3_dispatch_started(
        OWNER, turn_id, reservation,
        claim_token=claim_token,
        prepared_request_sha256=_sha(f"prepared:{reservation}"),
        selected_model_key="configured-test-model",
        validated_measurement_sha256=_sha(f"measurement:{reservation}"),
        now=at + timedelta(milliseconds=1),
    )
    return reservation


def _dispatch_get_from_admission(
    store: SQLiteAgentStore,
    turn_id: uuid.UUID,
    claim_token: str,
    admission_id: str,
    at: datetime,
    *,
    active_limit_us: int = 1_000,
    backend_limit_us: int = 100,
    response_bytes_limit: int = 64,
    source_table: str = "activity_members",
    source_role: str = "membership",
) -> str:
    reservation = store.reserve_p2_v3_stage(
        OWNER, turn_id,
        claim_token=claim_token,
        stage="backend_get",
        active_limit_us=active_limit_us,
        backend_limit_us=backend_limit_us,
        response_bytes_limit=response_bytes_limit,
        admission_id=admission_id,
        source_table=source_table,
        source_role=source_role,
        request_digest=_sha(f"GET /{source_table}?attempt={at.isoformat()}"),
        now=at,
    )
    store.mark_p2_v3_dispatch_started(
        OWNER, turn_id, reservation, claim_token=claim_token, now=at + timedelta(milliseconds=1),
    )
    return reservation


def _continuation_read_fixture(
    store: SQLiteAgentStore,
    turn_id: uuid.UUID,
    claim_token: str,
    at: datetime,
) -> dict[str, object]:
    """Build one Store-accepted, multi-page expense source for nonce tests."""
    from test_p2_source_codec_backend_v3 import SyntheticTransport
    from test_p2_v3_query_store_acceptance import _multi_expense_datasets

    datasets = _multi_expense_datasets(18)
    datasets["activity_members"][0]["user_id"] = str(OWNER)
    datasets["participant_claims"][0]["user_id"] = str(OWNER)
    activity_id = uuid.UUID(datasets["activities"][0]["id"])

    class StoreTransport:
        def __init__(self) -> None:
            self.delegate = SyntheticTransport(datasets)

        def get(self, url: str, headers: object, *, timeout: float, max_response_bytes: int, control: object):
            response = self.delegate.get(
                url, headers, timeout=timeout, max_response_bytes=max_response_bytes, control=control,
            )
            return p2_backend.TransportResponse(response.status, response.body, response.content_range)

    admission, scope = store.create_p2_v3_request_admission(
        OWNER, turn_id, claim_token=claim_token, principal_user_id=OWNER,
        activity_id_hint=activity_id, now=at,
    )
    assert scope is not None
    verified = p2_backend.VerifiedReadContext(
        owner_user_id=OWNER, turn_id=turn_id, principal_user_id=OWNER,
        access_token="synthetic.jwt.cpu", expires_at=at + timedelta(minutes=2),
        refs_by_opaque_token={},
    )
    adapter = p2_read_backend.P2ReadBackendAdapter(
        p2_backend.P2BackendConfig(
            project_url="https://synthetic.invalid",
            publishable_key="sb_publishable_synthetic_cpu_only",
            timeout_seconds=2, page_size=16, max_pages=4, max_rows_per_query=64,
            max_requests_per_read=48, max_total_response_bytes=4_194_304,
            max_total_seconds=20, max_facts=16,
        ),
        transport=StoreTransport(),
        v3_budget_port=P2V3StoreBudgetPort(store, OWNER, turn_id, claim_token),
        v3_locator_port=admission.reference_registry,
    )
    admission_projection = asyncio.run(adapter.admit_scope_v3(
        verified, admission, ui_activity_id_hint=activity_id,
        ui_ledger_unit_id_hint=None,
    ))
    request = p2_read_contracts_v3.P2ReadQueryRequest(
        kind="read", message_type="query_request",
        profile_id=p2_read_contracts_v3.P2_V3_CANDIDATE_PROFILE_ID,
        versions=p2_read_contracts_v3.P2_V3_VERSIONS,
        operation=p2_read_contracts_v3.P2ReadOperation.EXPENSES,
        criteria=p2_read_contracts_v3.ExpenseCriteria(
            kind="expenses", activity_ref=str(scope.activity_ref),
        ),
        scope=scope,
    )
    snapshot = store.get_p2_v3_snapshot(OWNER, turn_id)
    query_id = store.create_p2_v3_logical_query(
        OWNER, turn_id, claim_token=claim_token,
        admission_id=admission.admission_id, operation=request.operation.value,
        criteria=request.criteria, scope=request.scope,
        expected_revision=snapshot.revision, now=at + timedelta(milliseconds=1),
    )
    store.bind_p2_v3_query_descriptor(
        OWNER, turn_id, claim_token=claim_token, admission=admission,
        request=request, logical_query_id=query_id, now=at + timedelta(milliseconds=2),
    )
    attempt_id, attempt_seq = store.begin_p2_v3_query_attempt(
        OWNER, turn_id, claim_token=claim_token, logical_query_id=query_id,
        admission_id=admission.admission_id, now=at + timedelta(milliseconds=3),
    )
    return {
        "admission": admission,
        "admission_projection": admission_projection,
        "adapter": adapter,
        "attempt_id": attempt_id,
        "attempt_seq": attempt_seq,
        "activity_id": activity_id,
        "query_id": query_id,
        "request": request,
        "scope": scope,
        "verified": verified,
    }


def _accept_continuation_page(
    store: SQLiteAgentStore,
    turn_id: uuid.UUID,
    claim_token: str,
    fixture: dict[str, object],
    *,
    attempt_id: str,
    attempt_seq: int,
    at: datetime,
) -> dict[str, str | int]:
    admission = fixture["admission"]
    request = fixture["request"]
    assert isinstance(admission, p2_source_codec_v3.AdmissionOnlyBinding)
    assert isinstance(request, p2_read_contracts_v3.P2ReadQueryRequest)
    query_id = str(fixture["query_id"])
    query_binding = p2_source_codec_v3.QueryAttemptBinding(
        identity=admission.identity, logical_query_id=query_id,
        query_attempt_id=attempt_id, page_index=0, claim_token=claim_token,
    )
    registry = admission.reference_registry
    grant = p2_read_contracts_v3.P2SourceAuthorizationGrant(
        principal_ref=registry.principal_ref(),
        owner_turn_ref=registry.owner_turn_ref(identity=admission.identity),
        generation=admission.identity.generation,
        source_input_seq=admission.identity.input_seq,
        input_digest=admission.identity.input_digest,
        operation=request.operation, scope=request.scope,
        criteria_digest=p2_read_contracts_v3.p2_criteria_digest(request.criteria),
        expires_at=at + timedelta(minutes=2),
        grant_ref="ref_" + secrets.token_urlsafe(24),
    )
    pending = asyncio.run(fixture["adapter"].read_candidate_v3(
        request, fixture["verified"], grant,
        admission=admission, admission_projection=fixture["admission_projection"],
        query_binding=query_binding, context_version="cpu-continuation-source",
    ))
    assert isinstance(pending, p2_read_backend.P2V3PendingSourceAttempt)
    accepted = store.accept_p2_v3_query_attempt(
        OWNER, turn_id, claim_token=claim_token, principal_user_id=OWNER,
        pending=pending, now=at + timedelta(seconds=1),
    )
    assert accepted.historical.page.has_more is True
    live = store.issue_p2_v3_page(
        OWNER, turn_id, claim_token=claim_token, accepted_page=accepted,
        now=at + timedelta(seconds=2),
    )
    assert live.page.next_page_ref is not None
    with store._connection() as connection:
        receipt = connection.execute(
            "SELECT * FROM p2_v3_query_result_receipts WHERE query_result_receipt_id=? AND owner_user_id=? AND turn_id=?",
            (accepted.query_result_receipt_id, str(OWNER), str(turn_id)),
        ).fetchone()
    assert receipt is not None
    proof = store._p2_v3_continuation_proof_from_receipt(receipt)
    return {
        "token": live.page.next_page_ref,
        "attempt_seq": attempt_seq,
        "source_proof_sha256": P2V3RequestReferenceRegistry._continuation_proof_sha256(proof),
        "projection_sha256": str(receipt["projection_sha256"]),
    }


def _start_expense_query_attempt(
    store: SQLiteAgentStore,
    turn_id: uuid.UUID,
    claim_token: str,
    fixture: dict[str, object],
    *,
    at: datetime,
) -> dict[str, object]:
    admission = fixture["admission"]
    request = fixture["request"]
    assert isinstance(admission, p2_source_codec_v3.AdmissionOnlyBinding)
    assert isinstance(request, p2_read_contracts_v3.P2ReadQueryRequest)
    snapshot = store.get_p2_v3_snapshot(OWNER, turn_id)
    query_id = store.create_p2_v3_logical_query(
        OWNER, turn_id, claim_token=claim_token,
        admission_id=admission.admission_id, operation=request.operation.value,
        criteria=request.criteria, scope=request.scope,
        expected_revision=snapshot.revision, now=at,
    )
    store.bind_p2_v3_query_descriptor(
        OWNER, turn_id, claim_token=claim_token, admission=admission,
        request=request, logical_query_id=query_id, now=at + timedelta(milliseconds=1),
    )
    attempt_id, attempt_seq = store.begin_p2_v3_query_attempt(
        OWNER, turn_id, claim_token=claim_token, logical_query_id=query_id,
        admission_id=admission.admission_id, now=at + timedelta(milliseconds=2),
    )
    return {
        **fixture,
        "query_id": query_id,
        "attempt_id": attempt_id,
        "attempt_seq": attempt_seq,
    }


def _build_legacy_database(path: Path, *, version: int) -> tuple[tuple[object, ...], ...]:
    """Build a valid Agent-local pre-v3 database for the append-only upgrade test."""
    if version not in (1, 2, 3):
        raise ValueError("test helper only builds legacy version 1, 2, or 3")
    path.parent.mkdir(parents=True, exist_ok=True)
    store = SQLiteAgentStore(path, admission_enabled=True)
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        for migration in store._migrations[:version]:
            store._apply_migration(connection, migration)
            connection.execute(
                "INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES (?,?,?,?)",
                (migration.version, migration.name, migration.checksum, "2026-10-14T11:00:00+00:00"),
            )
            connection.execute(f"PRAGMA user_version={migration.version}")
        connection.execute("COMMIT")
        return tuple(tuple(row) for row in connection.execute(
            "SELECT version,name,checksum,applied_at FROM schema_migrations ORDER BY version"
        ))
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()
        store.close()


def test_expired_recovery_at_model_and_repair_caps_does_not_double_consume_dispatch_slots(tmp_path: Path) -> None:
    store = _store(tmp_path, "recover-model-cap")
    try:
        turn_id, claim = _create_running_turn(store)
        for index in range(5):
            at = NOW + timedelta(seconds=2 + index * 2)
            reservation = _dispatch_model(store, turn_id, claim, at)
            store.settle_p2_v3_stage(
                OWNER, turn_id, reservation, outcome="actual",
                actual_active_us=100, actual_backend_us=0, actual_response_bytes=0,
                now=at + timedelta(milliseconds=2),
            )
        final_at = NOW + timedelta(seconds=14)
        pending = _dispatch_model(store, turn_id, claim, final_at, stage="repair")

        before = store.get_p2_v3_snapshot(OWNER, turn_id)
        assert (before.model_calls, before.repair_calls, before.model_reserved_calls, before.repair_reserved_calls) == (P2_V3_MAX_MODEL_CALLS, 1, 0, 0)
        aggregate = store.get_turn(OWNER, turn_id)
        assert aggregate.claim_until is not None
        recovered = store.recover_interrupted_turns(now=aggregate.claim_until + timedelta(milliseconds=1))

        assert len(recovered) == 1
        after = store.get_p2_v3_snapshot(OWNER, turn_id)
        assert (after.model_calls, after.repair_calls, after.model_reserved_calls, after.repair_reserved_calls) == (P2_V3_MAX_MODEL_CALLS, 1, 0, 0)
        assert after.active_reserved_us == 0
        assert after.active_used_us == 1_500
        assert after.historical_unknown_consumption is True
        with store._connection() as connection:
            events = connection.execute(
                "SELECT event_kind FROM p2_v3_charge_events WHERE reservation_id=? ORDER BY occurred_at",
                (pending,),
            ).fetchall()
        assert [row["event_kind"] for row in events] == ["reserved", "dispatch_started", "unknown"]
        assert store.recover_interrupted_turns(now=aggregate.claim_until + timedelta(seconds=1)) == []
        with pytest.raises(P2V3StoreConflict, match="already settled"):
            store.settle_p2_v3_stage(
                OWNER, turn_id, pending, outcome="actual",
                actual_active_us=1, actual_backend_us=0, actual_response_bytes=0,
                now=aggregate.claim_until + timedelta(seconds=2),
            )
    finally:
        store.close()


def test_one_mixed_claim_preserves_queue_order_and_default_excludes_v3(tmp_path: Path) -> None:
    store = _store(tmp_path, "mixed-claim")
    try:
        canonical_turn = _create_queued_turn(store, candidate_profile=False)
        candidate_owner = uuid.UUID("a1000000-0000-4000-8000-000000000002")
        candidate_turn = _create_queued_turn(
            store, candidate_profile=True, owner=candidate_owner,
        )

        default_claim = store.claim_runnable("legacy-default", now=NOW + timedelta(seconds=1))
        assert default_claim is not None
        assert default_claim.turn.record.turn.turn_id == canonical_turn
        assert default_claim.execution_profile_id is None
        assert store.claim_runnable("legacy-default-2", now=NOW + timedelta(seconds=1)) is None
        store._release_claim_locked(canonical_turn, default_claim.claim_token)

        mixed_claim = store.claim_runnable(
            "candidate-enabled", enabled_candidate_profile_ids=(P2_V3_CANDIDATE_PROFILE_ID,),
            now=NOW + timedelta(seconds=2),
        )
        assert mixed_claim is not None
        assert mixed_claim.turn.record.turn.turn_id == canonical_turn
        assert mixed_claim.execution_profile_id is None
        before = store.get_turn(OWNER, canonical_turn).record.turn
        cancelled = before.model_copy(update={
            "state": c.TurnState.CANCELLED,
            "step": c.TurnStep.TERMINAL,
            "state_revision": before.state_revision + 1,
            "wait_reason": None,
            "resume_state": None,
        })
        store.accept_turn_action(
            OWNER, canonical_turn,
            c.CancelTurnRequest(
                client_request_id=uuid.uuid4(),
                expected_state_revision=before.state_revision,
                reason="mixed queue order test",
            ),
            cancelled,
            c.CancelTurnResponse(turn=_public(cancelled), result="cancelled"),
            events=[_status(cancelled, NOW + timedelta(seconds=2, milliseconds=1))],
            now=NOW + timedelta(seconds=2, milliseconds=1),
        )

        # The next single scheduler claim selects the next eligible queued row,
        # without a second worker pool or a client-selected profile.
        next_claim = store.claim_runnable(
            "candidate-enabled", enabled_candidate_profile_ids=(P2_V3_CANDIDATE_PROFILE_ID,),
            now=NOW + timedelta(seconds=3),
        )
        assert next_claim is not None
        assert next_claim.turn.record.turn.turn_id == candidate_turn
        assert next_claim.execution_profile_id == P2_V3_CANDIDATE_PROFILE_ID
    finally:
        store.close()


def test_expired_recovery_at_get_48th_dispatch_preserves_single_get_charge(tmp_path: Path) -> None:
    store = _store(tmp_path, "recover-get-cap")
    try:
        turn_id, claim = _create_running_turn(store)
        admission = _admission(store, turn_id, claim, NOW + timedelta(seconds=2))
        metadata_sources = (
            ("activities", "activity"),
            ("activity_members", "membership"),
            ("participants", "participant"),
            ("ledger_units", "ledger_unit"),
            ("sub_activity_participants", "ledger_unit"),
            ("participant_claims", "actor"),
        )
        reservation_index = 0

        def settle_get(current_admission: str, source_table: str, source_role: str, index: int) -> str:
            at = NOW + timedelta(seconds=3 + index / 10)
            reservation = _dispatch_get_from_admission(
                store, turn_id, claim, current_admission, at,
                source_table=source_table, source_role=source_role,
            )
            store.settle_p2_v3_stage(
                OWNER, turn_id, reservation, outcome="actual",
                actual_active_us=50, actual_backend_us=10, actual_response_bytes=8,
                raw_body_sha256=_sha(f"body:{index}"),
                now=at + timedelta(milliseconds=2),
            )
            return reservation

        # One admission chain contributes 6 tables x 4 GETs = 24. A fresh
        # admission creates a second chain; its first five tables contribute
        # four each and the last table contributes three: 47 settled GETs.
        for source_table, source_role in metadata_sources:
            for _ in range(4):
                settle_get(admission, source_table, source_role, reservation_index)
                reservation_index += 1
        second_admission = _admission(
            store, turn_id, claim, NOW + timedelta(seconds=5, milliseconds=350),
        )
        for source_table, source_role in metadata_sources[:-1]:
            for _ in range(4):
                settle_get(second_admission, source_table, source_role, reservation_index)
                reservation_index += 1
        final_table, final_role = metadata_sources[-1]
        for _ in range(3):
            settle_get(second_admission, final_table, final_role, reservation_index)
            reservation_index += 1
        assert reservation_index == 47

        at = NOW + timedelta(seconds=8)
        pending = _dispatch_get_from_admission(
            store, turn_id, claim, second_admission, at,
            source_table=final_table, source_role=final_role,
        )
        before = store.get_p2_v3_snapshot(OWNER, turn_id)
        assert (before.get_attempts, before.get_reserved) == (48, 0)
        # A third fresh admission avoids a per-chain table cap, so the next
        # request must be refused by the Turn-wide 48-GET budget itself.
        third_admission = _admission(
            store, turn_id, claim, at + timedelta(milliseconds=10),
        )
        with pytest.raises(P2V3StoreConflict, match="budget is exhausted"):
            _dispatch_get_from_admission(
                store, turn_id, claim, third_admission, at + timedelta(milliseconds=20),
                source_table="activities", source_role="activity",
            )

        aggregate = store.get_turn(OWNER, turn_id)
        assert aggregate.claim_until is not None
        assert len(store.recover_interrupted_turns(now=aggregate.claim_until + timedelta(milliseconds=1))) == 1

        after = store.get_p2_v3_snapshot(OWNER, turn_id)
        assert (after.get_attempts, after.get_reserved) == (48, 0)
        assert (after.active_reserved_us, after.backend_reserved_us, after.bytes_reserved) == (0, 0, 0)
        assert after.active_used_us == 48 * 1_000 - 47 * (1_000 - 50)
        assert after.backend_used_us == 47 * 10 + 100
        assert after.response_bytes == 47 * 8 + 64
        assert after.historical_unknown_consumption is True
        with store._connection() as connection:
            events = connection.execute(
                "SELECT event_kind FROM p2_v3_charge_events WHERE reservation_id=? ORDER BY occurred_at",
                (pending,),
            ).fetchall()
        assert [row["event_kind"] for row in events] == ["reserved", "dispatch_started", "unknown"]
    finally:
        store.close()


def test_cancel_with_dispatched_work_settles_unknown_and_rejects_late_settlement(tmp_path: Path) -> None:
    store = _store(tmp_path, "cancel-inflight")
    try:
        turn_id, claim = _create_running_turn(store)
        admission = _admission(store, turn_id, claim, NOW + timedelta(seconds=2))
        reservation = _dispatch_get_from_admission(
            store, turn_id, claim, admission, NOW + timedelta(seconds=3),
            active_limit_us=20_000, backend_limit_us=10_000, response_bytes_limit=2048,
        )
        before = store.get_turn(OWNER, turn_id).record.turn
        after = before.model_copy(update={
            "state": c.TurnState.CANCELLED,
            "step": c.TurnStep.TERMINAL,
            "state_revision": before.state_revision + 1,
            "wait_reason": None,
            "resume_state": None,
        })
        request = c.CancelTurnRequest(
            client_request_id=uuid.uuid4(), expected_state_revision=before.state_revision,
            reason="user cancelled while a source request was in flight",
        )
        store.accept_turn_action(
            OWNER, turn_id, request, after,
            c.CancelTurnResponse(turn=_public(after), result="cancelled"),
            events=[_status(after, NOW + timedelta(seconds=4))],
            now=NOW + timedelta(seconds=4),
        )
        terminal = store.get_p2_v3_snapshot(OWNER, turn_id)
        assert terminal.lifecycle == "terminal"
        assert (terminal.active_reserved_us, terminal.backend_reserved_us, terminal.bytes_reserved) == (0, 0, 0)
        assert (terminal.active_used_us, terminal.backend_used_us, terminal.response_bytes) == (20_000, 10_000, 2048)
        assert (terminal.get_attempts, terminal.get_reserved) == (1, 0)
        assert terminal.historical_unknown_consumption is True
        with pytest.raises(P2V3StoreConflict, match="already settled"):
            store.settle_p2_v3_stage(
                OWNER, turn_id, reservation, outcome="actual",
                actual_active_us=100, actual_backend_us=50, actual_response_bytes=4,
                raw_body_sha256=_sha("late-body"), now=NOW + timedelta(seconds=5),
            )
        assert store.get_turn(OWNER, turn_id).record.turn.state == c.TurnState.CANCELLED
    finally:
        store.close()


def test_second_store_startup_preserves_live_v3_claim_and_reservation(tmp_path: Path) -> None:
    store = _store(tmp_path, "startup-live-claim")
    second: SQLiteAgentStore | None = None
    try:
        wall_start = datetime.now(timezone.utc).replace(microsecond=0)
        turn_id, claim = _create_running_turn(store, now=wall_start + timedelta(seconds=1))
        admission = _admission(store, turn_id, claim, wall_start + timedelta(seconds=2))
        pending = _dispatch_get_from_admission(
            store, turn_id, claim, admission, wall_start + timedelta(seconds=3),
            active_limit_us=50_000, backend_limit_us=20_000, response_bytes_limit=4096,
        )
        before = store.get_p2_v3_snapshot(OWNER, turn_id)
        turn_before = store.get_turn(OWNER, turn_id)
        assert turn_before.claim_token == claim
        assert before.active_reserved_us == 50_000

        second = _configured_store(store._path)
        second.start()
        after = second.get_p2_v3_snapshot(OWNER, turn_id)
        turn_after = second.get_turn(OWNER, turn_id)
        assert turn_after.claim_token == claim
        assert after.revision == before.revision
        assert after.active_reserved_us == 50_000
        assert after.get_attempts == 1
        assert second.claim_runnable(
            "p2v3-second-store", candidate_profile_id=P2_V3_CANDIDATE_PROFILE_ID,
            now=wall_start + timedelta(seconds=4),
        ) is None
        with second._connection() as connection:
            events = connection.execute(
                "SELECT event_kind FROM p2_v3_charge_events WHERE reservation_id=? ORDER BY occurred_at",
                (pending,),
            ).fetchall()
        assert [row["event_kind"] for row in events] == ["reserved", "dispatch_started"]
    finally:
        if second is not None:
            second.close()
        store.close()


def test_second_store_startup_orders_same_timestamp_charge_events_by_causality(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, "startup-same-timestamp-charge-events")
    second: SQLiteAgentStore | None = None
    try:
        wall_start = datetime.now(timezone.utc).replace(microsecond=0)
        turn_id, claim = _create_running_turn(store, now=wall_start + timedelta(seconds=1))
        admission = _admission(store, turn_id, claim, wall_start + timedelta(seconds=2))
        event_at = wall_start + timedelta(seconds=3)
        ids = iter((
            uuid.UUID("30000000-0000-4000-8000-000000000001"),  # reservation
            uuid.UUID("f0000000-0000-4000-8000-000000000001"),  # reserved event
            uuid.UUID("10000000-0000-4000-8000-000000000001"),  # dispatch event
            uuid.UUID("20000000-0000-4000-8000-000000000001"),  # settled event
        ))
        with monkeypatch.context() as event_ids:
            event_ids.setattr(uuid, "uuid4", lambda: next(ids))
            reservation = store.reserve_p2_v3_stage(
                OWNER, turn_id, claim_token=claim, stage="backend_get",
                active_limit_us=500, backend_limit_us=250, response_bytes_limit=128,
                admission_id=admission, source_role="activity",
                request_digest=_sha("GET /activities/0"), now=event_at,
            )
            store.mark_p2_v3_dispatch_started(
                OWNER, turn_id, reservation, claim_token=claim, now=event_at,
            )
            store.settle_p2_v3_stage(
                OWNER, turn_id, reservation, outcome="actual",
                actual_active_us=300, actual_backend_us=100, actual_response_bytes=40,
                raw_body_sha256=_sha("activity-page"), now=event_at,
            )

        # Millisecond-resolution clocks can legitimately give all lifecycle
        # events one timestamp. Startup validation must use event semantics for
        # ties rather than random UUID ordering.
        second = _configured_store(store._path, admission_enabled=True)
        second.start()
        snapshot = second.get_p2_v3_snapshot(OWNER, turn_id)
        assert (snapshot.active_used_us, snapshot.backend_used_us, snapshot.response_bytes) == (300, 100, 40)
        assert (snapshot.active_reserved_us, snapshot.backend_reserved_us, snapshot.bytes_reserved) == (0, 0, 0)
        assert snapshot.get_attempts == 1
        with second._connection() as connection:
            events = connection.execute(
                "SELECT event_kind FROM p2_v3_charge_events WHERE reservation_id=? "
                "ORDER BY occurred_at,CASE event_kind WHEN 'reserved' THEN 0 "
                "WHEN 'dispatch_started' THEN 1 ELSE 2 END,event_id",
                (reservation,),
            ).fetchall()
        assert [row["event_kind"] for row in events] == ["reserved", "dispatch_started", "settled"]
    finally:
        if second is not None:
            second.close()
        store.close()


def test_retired_worker_settles_dispatched_v3_cost_once_and_invalidates_claim(tmp_path: Path) -> None:
    store = _store(tmp_path, "retired-worker")
    try:
        turn_id, claim = _create_running_turn(store)
        admission = _admission(store, turn_id, claim, NOW + timedelta(seconds=2))
        pending = _dispatch_get_from_admission(
            store, turn_id, claim, admission, NOW + timedelta(seconds=3),
            active_limit_us=25_000, backend_limit_us=15_000, response_bytes_limit=3072,
        )
        store.mark_claim_worker_retired("p2v3-edge-worker")
        store.cleanup_retired_claim_workers()

        after = store.get_p2_v3_snapshot(OWNER, turn_id)
        aggregate = store.get_turn(OWNER, turn_id)
        assert aggregate.claim_token is None
        assert after.claim_epoch == 2
        assert after.authority_epoch == 2
        assert (after.active_reserved_us, after.backend_reserved_us, after.bytes_reserved) == (0, 0, 0)
        assert (after.active_used_us, after.backend_used_us, after.response_bytes) == (25_000, 15_000, 3072)
        assert (after.get_attempts, after.get_reserved) == (1, 0)
        assert after.historical_unknown_consumption is True
        with store._connection() as connection:
            events = connection.execute(
                "SELECT event_kind FROM p2_v3_charge_events WHERE reservation_id=? ORDER BY occurred_at",
                (pending,),
            ).fetchall()
        assert [row["event_kind"] for row in events] == ["reserved", "dispatch_started", "unknown"]
        with pytest.raises(P2V3StoreConflict):
            store.settle_p2_v3_stage(
                OWNER, turn_id, pending, outcome="actual",
                actual_active_us=1, actual_backend_us=1, actual_response_bytes=1,
                raw_body_sha256=_sha("late-retired"), now=NOW + timedelta(seconds=4),
            )
        with pytest.raises(StateConflict):
            store.create_p2_v3_source_admission(
                OWNER, turn_id, claim_token=claim,
                requested_scope={"scope_kind": "activity", "activity_id": str(ACTIVITY_ID)},
                public_scope=_scope(), now=NOW + timedelta(seconds=5),
            )
    finally:
        store.close()


@pytest.mark.parametrize("resume_kind", ["auth", "clarification"])
def test_accepted_resume_reuses_immutable_query_with_new_admission_and_attempt(tmp_path: Path, resume_kind: str) -> None:
    store = _store(tmp_path, f"resume-query-{resume_kind}")
    try:
        turn_id, claim = _create_running_turn(store)
        first_admission = _admission(store, turn_id, claim, NOW + timedelta(seconds=2))
        query_id, first_attempt, first_seq = _query_and_attempt(
            store, turn_id, claim, first_admission, NOW + timedelta(seconds=3),
        )
        assert first_seq == 1
        first_get = store.reserve_p2_v3_stage(
            OWNER, turn_id, claim_token=claim, stage="backend_get",
            active_limit_us=100, backend_limit_us=50, response_bytes_limit=64,
            logical_query_id=query_id, query_attempt_id=first_attempt,
            source_role="expense", request_digest=_sha("GET /expenses?page=0&epoch=1"),
            now=NOW + timedelta(seconds=3, milliseconds=2),
        )
        store.mark_p2_v3_dispatch_started(
            OWNER, turn_id, first_get, claim_token=claim, now=NOW + timedelta(seconds=3, milliseconds=3),
        )
        store.settle_p2_v3_stage(
            OWNER, turn_id, first_get, outcome="actual", actual_active_us=20,
            actual_backend_us=10, actual_response_bytes=2,
            raw_body_sha256=_sha("first-page-cost-only"), now=NOW + timedelta(seconds=3, milliseconds=4),
        )
        assert store.get_p2_v3_snapshot(OWNER, turn_id).get_attempts == 1

        aggregate = store.get_turn(OWNER, turn_id)
        before = aggregate.record.turn
        if resume_kind == "auth":
            paused = before.model_copy(update={
                "state": c.TurnState.WAIT_INPUT,
                "step": c.TurnStep.AUTH_REQUIRED,
                "state_revision": before.state_revision + 1,
                "wait_reason": c.WaitReason.AUTH_REQUIRED,
                "resume_state": c.ResumeState.RUNNING,
            })
        else:
            paused = before.model_copy(update={
                "state": c.TurnState.WAIT_INPUT,
                "step": c.TurnStep.AWAITING_USER,
                "state_revision": before.state_revision + 1,
                "wait_reason": c.WaitReason.MISSING_FIELDS,
                "resume_state": c.ResumeState.RUNNING,
            })
        store.transition_turn(
            OWNER, paused,
            expected_state_revision=before.state_revision,
            expected_checkpoint_revision=aggregate.checkpoint_revision,
            events=[_status(paused, NOW + timedelta(seconds=4))],
            claim_token=claim,
            candidate_profile_id=P2_V3_CANDIDATE_PROFILE_ID,
            now=NOW + timedelta(seconds=4),
        )

        if resume_kind == "auth":
            request: object = c.ResumeAuthRequest(
                client_request_id=uuid.uuid4(), expected_state_revision=paused.state_revision,
            )
        else:
            request = c.ResumeClarificationRequest(
                client_request_id=uuid.uuid4(), expected_state_revision=paused.state_revision,
                text="Use the same activity and unchanged expense criteria.",
            )
        resumed = paused.model_copy(update={
            "state": c.TurnState.RUNNING,
            "step": c.TurnStep.BUILD_CONTEXT,
            "state_revision": paused.state_revision + 1,
            "wait_reason": None,
            "resume_state": None,
        })
        store.accept_turn_action(
            OWNER, turn_id, request, resumed,
            c.TurnMutationAccepted(
                turn_id=turn_id, state=resumed.state, state_revision=resumed.state_revision,
                event_cursor=0,
            ),
            events=[_status(resumed, NOW + timedelta(seconds=5))],
            now=NOW + timedelta(seconds=5),
        )

        reclaimed = store.claim_runnable(
            f"p2v3-resume-{resume_kind}", candidate_profile_id=P2_V3_CANDIDATE_PROFILE_ID,
            now=NOW + timedelta(seconds=6),
        )
        assert reclaimed is not None and reclaimed.turn.record.turn.turn_id == turn_id
        new_claim = reclaimed.claim_token
        new_admission = _admission(store, turn_id, new_claim, NOW + timedelta(seconds=7))
        snapshot = store.get_p2_v3_snapshot(OWNER, turn_id)
        reused_query, second_attempt, second_seq = _query_and_attempt(
            store, turn_id, new_claim, new_admission, NOW + timedelta(seconds=8), logical_query_id=query_id,
        )
        assert reused_query == query_id
        assert second_seq == 2
        assert first_attempt != second_attempt
        assert store.get_p2_v3_snapshot(OWNER, turn_id).logical_read_calls == 1
        assert store.get_p2_v3_snapshot(OWNER, turn_id).get_attempts == 1

        with pytest.raises(P2V3StoreConflict, match="source admission is stale"):
            store.reserve_p2_v3_stage(
                OWNER, turn_id, claim_token=new_claim, stage="backend_get",
                active_limit_us=1_000, backend_limit_us=500, response_bytes_limit=512,
                admission_id=first_admission, source_role="activity", source_table="activities",
                request_digest=_sha("GET /activities with retired admission"),
                now=NOW + timedelta(seconds=8, milliseconds=1),
            )
        assert store.get_p2_v3_snapshot(OWNER, turn_id).get_attempts == 1
        with store._connection() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM p2_v3_charge_events WHERE turn_id=? AND event_kind='reserved'",
                (str(turn_id),),
            ).fetchone()[0] == 1

        reservation = store.reserve_p2_v3_stage(
            OWNER, turn_id,
            claim_token=new_claim,
            stage="backend_get",
            active_limit_us=1_000,
            backend_limit_us=500,
            response_bytes_limit=512,
            logical_query_id=query_id,
            query_attempt_id=second_attempt,
            source_role="expense",
            request_digest=_sha("GET /expenses?fresh=1"),
            now=NOW + timedelta(seconds=9),
        )
        store.mark_p2_v3_dispatch_started(
            OWNER, turn_id, reservation, claim_token=new_claim, now=NOW + timedelta(seconds=9, milliseconds=1),
        )
        store.settle_p2_v3_stage(
            OWNER, turn_id, reservation, outcome="actual",
            actual_active_us=100, actual_backend_us=50, actual_response_bytes=2,
            raw_body_sha256=_sha("[]"), now=NOW + timedelta(seconds=9, milliseconds=2),
        )
        resumed_budget = store.get_p2_v3_snapshot(OWNER, turn_id)
        assert resumed_budget.logical_read_calls == 1
        assert resumed_budget.get_attempts == 2
        assert resumed_budget.active_used_us == 120
        assert resumed_budget.backend_used_us == 60
        with store._connection() as connection:
            row = connection.execute(
                """SELECT a.generation,a.input_seq,t.authority_epoch,t.attempt_state
                     FROM p2_v3_query_attempts t
                     JOIN p2_v3_source_admissions a USING(admission_id)
                    WHERE t.attempt_id=?""",
                (second_attempt,),
            ).fetchone()
        assert row is not None
        assert row["generation"] == snapshot.generation
        assert row["input_seq"] == snapshot.input_seq
        assert row["authority_epoch"] == snapshot.authority_epoch
        assert row["attempt_state"] == "started"

        current = store.get_p2_v3_snapshot(OWNER, turn_id)
        with pytest.raises(P2V3StoreConflict, match="cannot change operation, criteria, or scope"):
            store.create_p2_v3_logical_query(
                OWNER, turn_id,
                claim_token=new_claim,
                admission_id=new_admission,
                operation="read.expenses",
                criteria={"kind": "expenses", "activity_ref": ACTIVITY_REF, "title_contains": "coffee"},
                scope=_scope(),
                expected_revision=current.revision,
                logical_query_id=query_id,
                now=NOW + timedelta(seconds=10),
            )
        assert store.get_p2_v3_snapshot(OWNER, turn_id).logical_read_calls == 1
        second_query_id = store.create_p2_v3_logical_query(
            OWNER, turn_id,
            claim_token=new_claim,
            admission_id=new_admission,
            operation="read.expenses",
            criteria={"kind": "expenses", "activity_ref": ACTIVITY_REF, "title_contains": "coffee"},
            scope=_scope(),
            expected_revision=current.revision,
            now=NOW + timedelta(seconds=10, milliseconds=1),
        )
        assert second_query_id != query_id
        assert store.get_p2_v3_snapshot(OWNER, turn_id).logical_read_calls == 2
    finally:
        store.close()


def test_resume_query_lookup_fails_closed_for_wrong_owner_and_terminal_turn(tmp_path: Path) -> None:
    store = _store(tmp_path, "resume-query-lookup-fail-closed")
    try:
        now = datetime.now(timezone.utc)
        turn_id, claim = _create_running_turn(store, now=now)
        assert store.get_p2_v3_resume_query_descriptor(
            OWNER, turn_id, claim_token=claim,
        ) is None
        admission_id = _admission(store, turn_id, claim, now + timedelta(seconds=2))
        query_id, _attempt_id, _attempt_seq = _query_and_attempt(
            store, turn_id, claim, admission_id, now + timedelta(seconds=3),
        )
        descriptor = store.get_p2_v3_resume_query_descriptor(
            OWNER, turn_id, claim_token=claim,
        )
        assert descriptor is not None
        assert descriptor.logical_query_id == query_id
        assert descriptor.operation == "read.expenses"
        assert descriptor.input_digest == store.get_p2_v3_snapshot(OWNER, turn_id).input_digest
        assert descriptor.private_selection_refs == ()

        with pytest.raises((P2V3StoreNotFound, StoreNotFound)):
            store.get_p2_v3_resume_query_descriptor(
                uuid.uuid4(), turn_id, claim_token=claim,
            )

        aggregate = store.get_turn(OWNER, turn_id)
        before = aggregate.record.turn
        cancelled = before.model_copy(update={
            "state": c.TurnState.CANCELLED,
            "step": c.TurnStep.TERMINAL,
            "state_revision": before.state_revision + 1,
            "wait_reason": None,
            "resume_state": None,
        })
        store.transition_turn(
            OWNER,
            cancelled,
            expected_state_revision=before.state_revision,
            expected_checkpoint_revision=aggregate.checkpoint_revision,
            events=[_status(cancelled, now + timedelta(seconds=4))],
            claim_token=claim,
            candidate_profile_id=P2_V3_CANDIDATE_PROFILE_ID,
            now=now + timedelta(seconds=4),
        )
        with pytest.raises((P2V3StoreConflict, StateConflict)):
            store.get_p2_v3_resume_query_descriptor(
                OWNER, turn_id, claim_token=claim,
            )
        with store._connection() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM p2_v3_queries WHERE turn_id=?",
                (str(turn_id),),
            ).fetchone()[0] == 1
            assert connection.execute(
                "SELECT COUNT(*) FROM p2_v3_query_attempts WHERE turn_id=?",
                (str(turn_id),),
            ).fetchone()[0] == 1
    finally:
        store.close()


@pytest.mark.parametrize("starting_version", [1, 2, 3])
def test_current_migrations_upgrade_legacy_ledger_without_rewriting_existing_migrations(
    tmp_path: Path, starting_version: int,
) -> None:
    root = Path(__import__("os").environ["P2_V3_STORE_TEST_ROOT"])
    database = root / f"migration-v{starting_version}-to-v6.sqlite3"
    before_rows = _build_legacy_database(database, version=starting_version)
    migration_files = (
        Path(r"D:\project\Android\shared-ledger-agent\agent\migrations\001_initial.sql"),
        Path(r"D:\project\Android\shared-ledger-agent\agent\app\p2_read_store_migration.sql"),
        Path(r"D:\project\Android\shared-ledger-agent\agent\app\p2_source_store_v3_migration.sql"),
        Path(r"D:\project\Android\shared-ledger-agent\agent\app\p2_v3_source_proof_migration.sql"),
    )
    before_bytes = tuple(path.read_bytes() for path in migration_files)
    before_hashes = tuple(hashlib.sha256(content).hexdigest() for content in before_bytes)

    store = _configured_store(database, admission_enabled=True)
    try:
        store.start()
        with store._connection() as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
            rows = tuple(tuple(row) for row in connection.execute(
                "SELECT version,name,checksum,applied_at FROM schema_migrations ORDER BY version"
            ))
            assert rows[:starting_version] == before_rows
            assert rows[2][:3] == (3, "p2_source_candidate", before_hashes[2])
            assert rows[3][:3] == (4, "p2_v3_source_proofs", before_hashes[3])
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        store.close()
        store.start()
        with store._connection() as connection:
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
            assert tuple(tuple(row) for row in connection.execute(
                "SELECT version,name,checksum,applied_at FROM schema_migrations ORDER BY version"
            )) == rows
    finally:
        store.close()

    assert tuple(path.read_bytes() for path in migration_files) == before_bytes


def test_v3_upgrade_preserves_existing_v2_candidate_row_byte_for_byte(tmp_path: Path) -> None:
    store = _store(tmp_path, "preserve-v2-row")
    try:
        v2_turn = _create_queued_turn(store, candidate_profile=False, legacy_candidate=True)
        with store._connection() as connection:
            before_row = tuple(connection.execute(
                "SELECT * FROM p2_candidate_turns WHERE turn_id=?", (str(v2_turn),),
            ).fetchone())
            assert before_row
        database = store._path
    finally:
        store.close()

    connection = sqlite3.connect(database, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        triggers = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND (name LIKE 'p2_v3_%' OR name='p2_v2_excludes_v3_family')"
        )]
        for name in triggers:
            connection.execute(f'DROP TRIGGER "{name}"')
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'p2_v3_%' ORDER BY name DESC"
        )]
        for table in tables:
            connection.execute(f'DROP TABLE "{table}"')
        connection.execute("DELETE FROM schema_migrations WHERE version>=3")
        connection.execute("PRAGMA user_version=2")
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()

    upgraded = _configured_store(database, admission_enabled=True)
    try:
        # Exercise append-only migrations 003 and 004 here. A full Store.start also runs the
        # existing v2 process-recovery hook, which intentionally advances its
        # read epoch and is a separate lifecycle behavior.
        connection = upgraded._connect()
        try:
            upgraded._migrate(connection)
            upgraded._verify_schema(connection)
            upgraded._verify_database_integrity(connection)
            upgraded._verify_all_rows(connection)
            upgraded._verify_p2_candidate_rows(connection)
            upgraded._verify_p2_v3_rows(connection)
            after_row = tuple(connection.execute(
                "SELECT * FROM p2_candidate_turns WHERE turn_id=?", (str(v2_turn),),
            ).fetchone())
            assert after_row == before_row
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            connection.close()
    finally:
        upgraded.close()


@pytest.mark.parametrize(("operation", "criteria", "scope", "query_table", "query_role"), [
    ("read.activities", {"kind": "activities", "status": "active"}, None, "activities", "activity"),
    ("read.expenses", {"kind": "expenses", "activity_ref": ACTIVITY_REF}, _scope(), "expenses", "expense"),
    ("read.debts", {"kind": "debts", "activity_ref": ACTIVITY_REF}, _scope(), "expense_debts", "debt"),
    ("read.refund_events", {"kind": "refund_events", "activity_ref": ACTIVITY_REF}, _scope(), "expenses", "refund_parent"),
    ("read.prepayment_accounts", {"kind": "prepayment_accounts", "activity_ref": ACTIVITY_REF}, _scope(), "prepayment_accounts", "prepayment_account"),
    ("read.prepayment_usages", {"kind": "prepayment_usages", "activity_ref": ACTIVITY_REF}, _scope(), "prepayment_usages", "prepayment_usage"),
    ("read.prepayment_return_events", {"kind": "prepayment_return_events", "activity_ref": ACTIVITY_REF}, _scope(), "transfers", "prepayment_return"),
])
def test_capture_chain_uses_source_table_get_ordinal_and_separates_bootstrap_metadata(
    tmp_path: Path,
    operation: str,
    criteria: dict[str, object],
    scope: dict[str, object] | None,
    query_table: str,
    query_role: str,
) -> None:
    """Ordinal is a per-chain/table GET slot, not model page_index or HTTP offset."""
    store = _store(tmp_path, f"capture-chain-{operation.rsplit('.', 1)[-1]}")
    try:
        turn_id, claim = _create_running_turn(store)
        if scope is None:
            admission_id = store.create_p2_v3_source_admission(
                OWNER, turn_id, claim_token=claim,
                requested_scope={"scope_kind": "none"}, public_scope=None,
                now=NOW + timedelta(seconds=2),
            )
        else:
            admission_id = _admission(store, turn_id, claim, NOW + timedelta(seconds=2))

        clock = 3

        def settled_get(
            *, table: str, role: str, reservation_admission_id: str | None,
            logical_query_id: str | None = None, query_attempt_id: str | None = None,
            chain_query_id: str | None = None, chain_attempt_id: str | None = None,
            table_ordinal: int | None = None,
        ) -> str:
            nonlocal clock
            at = NOW + timedelta(seconds=clock)
            reservation = store.reserve_p2_v3_stage(
                OWNER, turn_id, claim_token=claim, stage="backend_get",
                active_limit_us=2_000, backend_limit_us=1_000, response_bytes_limit=64,
                logical_query_id=logical_query_id, query_attempt_id=query_attempt_id,
                admission_id=reservation_admission_id, source_role=role, source_table=table,
                capture_chain_logical_query_id=chain_query_id,
                capture_chain_attempt_id=chain_attempt_id,
                capture_chain_table_ordinal=table_ordinal,
                request_digest=_sha(f"GET /{table}?slot={clock}"), now=at,
            )
            store.mark_p2_v3_dispatch_started(
                OWNER, turn_id, reservation, claim_token=claim,
                now=at + timedelta(milliseconds=1),
            )
            store.settle_p2_v3_stage(
                OWNER, turn_id, reservation, outcome="actual",
                actual_active_us=100, actual_backend_us=50, actual_response_bytes=2,
                raw_body_sha256=_sha(f"[]:{table}:{clock}"),
                now=at + timedelta(milliseconds=2),
            )
            clock += 1
            return reservation

        # The operation-free bootstrap has a private admission chain and may
        # read only the exact six-table metadata allowlist.
        bootstrap = settled_get(
            table="activities", role="activity", reservation_admission_id=admission_id,
        )
        before = store.get_p2_v3_snapshot(OWNER, turn_id)
        with pytest.raises(ValueError, match="fixed scope metadata allowlist"):
            store.reserve_p2_v3_stage(
                OWNER, turn_id, claim_token=claim, stage="backend_get",
                active_limit_us=2_000, backend_limit_us=1_000, response_bytes_limit=64,
                admission_id=admission_id, source_role="expense", source_table="expenses",
                request_digest=_sha("GET /expenses?must-not-be-bootstrap"),
                now=NOW + timedelta(seconds=10),
            )
        after = store.get_p2_v3_snapshot(OWNER, turn_id)
        assert after.get_attempts == before.get_attempts
        with store._connection() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM p2_v3_charge_events WHERE event_kind='reserved' AND turn_id=?",
                (str(turn_id),),
            ).fetchone()[0] == 1
            bootstrap_link = connection.execute(
                "SELECT * FROM p2_v3_capture_chain_reservations WHERE reservation_id=?",
                (bootstrap,),
            ).fetchone()
            assert bootstrap_link["capture_chain_kind"] == "admission"
            assert bootstrap_link["capture_chain_id"] == admission_id
            assert bootstrap_link["table_get_ordinal"] == 0
            assert bootstrap_link["capture_chain_logical_query_id"] is None
            assert bootstrap_link["capture_chain_attempt_id"] is None

        snapshot = store.get_p2_v3_snapshot(OWNER, turn_id)
        query_id = store.create_p2_v3_logical_query(
            OWNER, turn_id, claim_token=claim, admission_id=admission_id,
            operation=operation, criteria=criteria, scope=scope,
            expected_revision=snapshot.revision, now=NOW + timedelta(seconds=11),
        )
        attempt_id, _ = store.begin_p2_v3_query_attempt(
            OWNER, turn_id, claim_token=claim, logical_query_id=query_id,
            admission_id=admission_id, now=NOW + timedelta(seconds=12),
        )

        metadata_gets = (
            ("activities", "activity"),
            ("activity_members", "membership"),
            ("participants", "participant"),
            ("ledger_units", "ledger_unit"),
            ("sub_activity_participants", "ledger_unit"),
            ("participant_claims", "actor"),
        )
        post_or_pre_metadata: list[str] = []
        for table, role in metadata_gets:
            post_or_pre_metadata.append(settled_get(
                table=table, role=role, reservation_admission_id=admission_id,
                chain_query_id=query_id, chain_attempt_id=attempt_id,
                table_ordinal=0 if table != "activities" else 0,
            ))
        # The same Activity endpoint may be reread at range offset 0 in the
        # post-fence. It is the second GET for this table in the chain, not
        # model page 1 or HTTP offset 1.
        second_activity_metadata = settled_get(
            table="activities", role="financial_version", reservation_admission_id=admission_id,
            chain_query_id=query_id, chain_attempt_id=attempt_id, table_ordinal=1,
        )
        query_get = settled_get(
            table=query_table, role=query_role, reservation_admission_id=None,
            logical_query_id=query_id, query_attempt_id=attempt_id,
        )

        with store._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM p2_v3_capture_chain_reservations WHERE turn_id=? ORDER BY chain_sequence",
                (str(turn_id),),
            ).fetchall()
            assert len(rows) == 1 + len(metadata_gets) + 1 + 1
            metadata = [
                row for row in rows
                if row["reservation_binding_kind"] == "admission"
                and row["capture_chain_kind"] == "query_attempt"
            ]
            assert {row["source_table"] for row in metadata} == {table for table, _ in metadata_gets}
            assert all(row["capture_chain_attempt_id"] == attempt_id for row in metadata)
            assert all(row["capture_chain_logical_query_id"] == query_id for row in metadata)
            assert all(row["reservation_query_attempt_id"] is None for row in metadata)
            assert all(row["table_get_ordinal"] == 0 for row in metadata if row["source_table"] != "activities")
            activities = [row for row in metadata if row["source_table"] == "activities"]
            assert [row["table_get_ordinal"] for row in activities] == [0, 1]
            financial = next(row for row in rows if row["reservation_id"] == query_get)
            assert financial["reservation_binding_kind"] == "query_attempt"
            assert financial["capture_chain_kind"] == "query_attempt"
            assert financial["capture_chain_attempt_id"] == attempt_id
            attempt = connection.execute(
                "SELECT page_index FROM p2_v3_query_attempts WHERE attempt_id=?", (attempt_id,),
            ).fetchone()
            assert attempt["page_index"] == 0
            assert financial["table_get_ordinal"] == (2 if query_table == "activities" else 0)
            assert connection.execute(
                "SELECT COUNT(*) FROM p2_v3_source_get_receipts WHERE turn_id=?", (str(turn_id),),
            ).fetchone()[0] == 0  # cost-only is not accepted source evidence
    finally:
        store.close()


def test_capture_chain_31_to_32_two_store_race_and_33rd_rejection_are_atomic(tmp_path: Path) -> None:
    store = _store(tmp_path, "capture-chain-32-race")
    second: SQLiteAgentStore | None = None
    try:
        base_at = datetime.now(timezone.utc).replace(microsecond=0)
        turn_id, claim = _create_running_turn(store, now=base_at + timedelta(seconds=1))
        admission = _admission(store, turn_id, claim, base_at + timedelta(seconds=2))
        query_id, attempt_id, _ = _query_and_attempt(
            store, turn_id, claim, admission, base_at + timedelta(seconds=3),
        )
        sources = (
            ("activities", "activity"),
            ("activity_members", "membership"),
            ("participants", "participant"),
            ("ledger_units", "ledger_unit"),
            ("sub_activity_participants", "ledger_unit"),
            ("expenses", "expense"),
            ("payments", "expense"),
            ("splits", "expense"),
            ("participant_claims", "actor"),
        )

        def reserve_query_get(adapter: SQLiteAgentStore, table: str, role: str, at: datetime) -> str:
            return adapter.reserve_p2_v3_stage(
                OWNER, turn_id, claim_token=claim, stage="backend_get",
                active_limit_us=100, backend_limit_us=50, response_bytes_limit=64,
                logical_query_id=query_id, query_attempt_id=attempt_id,
                source_role=role, source_table=table,
                request_digest=_sha(f"GET /{table}?at={at.isoformat()}"), now=at,
            )

        def charge_query_get(adapter: SQLiteAgentStore, table: str, role: str, index: int) -> None:
            at = base_at + timedelta(seconds=4, milliseconds=index * 10)
            reservation = reserve_query_get(adapter, table, role, at)
            adapter.mark_p2_v3_dispatch_started(
                OWNER, turn_id, reservation, claim_token=claim,
                now=at + timedelta(milliseconds=1),
            )
            adapter.settle_p2_v3_stage(
                OWNER, turn_id, reservation, outcome="actual",
                actual_active_us=10, actual_backend_us=5, actual_response_bytes=2,
                raw_body_sha256=_sha(f"body:{index}"), now=at + timedelta(milliseconds=2),
            )

        # Seven tables at four GETs each plus three on splits gives exactly 31.
        index = 0
        for table, role in sources[:7]:
            for _ in range(4):
                charge_query_get(store, table, role, index)
                index += 1
        for _ in range(3):
            charge_query_get(store, "splits", "expense", index)
            index += 1
        assert index == 31
        assert store.get_p2_v3_snapshot(OWNER, turn_id).get_attempts == 31

        second = _configured_store(store._path, admission_enabled=True)
        second.start()
        barrier = Barrier(2)

        def contender(args: tuple[SQLiteAgentStore, str, str]) -> str:
            adapter, table, role = args
            barrier.wait(timeout=3)
            try:
                return reserve_query_get(adapter, table, role, base_at + timedelta(seconds=8))
            except P2V3StoreConflict as error:
                return f"conflict:{error}"

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(contender, (
                (store, "splits", "expense"),
                (second, "participant_claims", "actor"),
            )))
        winners = [value for value in results if not value.startswith("conflict:")]
        conflicts = [value for value in results if value.startswith("conflict:")]
        assert len(winners) == 1, results
        assert len(conflicts) == 1, results

        winner = winners[0]
        store.mark_p2_v3_dispatch_started(
            OWNER, turn_id, winner, claim_token=claim, now=base_at + timedelta(seconds=8, milliseconds=1),
        )
        store.settle_p2_v3_stage(
            OWNER, turn_id, winner, outcome="actual", actual_active_us=10,
            actual_backend_us=5, actual_response_bytes=2,
            raw_body_sha256=_sha("last-allowed-get"), now=base_at + timedelta(seconds=8, milliseconds=2),
        )
        with store._connection() as connection:
            before = (
                connection.execute(
                    "SELECT COUNT(*) FROM p2_v3_charge_events WHERE turn_id=? AND event_kind='reserved'",
                    (str(turn_id),),
                ).fetchone()[0],
                connection.execute(
                    "SELECT COUNT(*) FROM p2_v3_capture_chain_reservations WHERE turn_id=?",
                    (str(turn_id),),
                ).fetchone()[0],
            )
        assert before == (32, 32)

        # Use a table below its own four-request cap so only the chain-wide
        # 32-GET ceiling can reject the next reservation.
        with pytest.raises(P2V3StoreConflict, match="capture chain page budget is exhausted"):
            reserve_query_get(store, "participant_claims", "actor", base_at + timedelta(seconds=9))
        with store._connection() as connection:
            after = (
                connection.execute(
                    "SELECT COUNT(*) FROM p2_v3_charge_events WHERE turn_id=? AND event_kind='reserved'",
                    (str(turn_id),),
                ).fetchone()[0],
                connection.execute(
                    "SELECT COUNT(*) FROM p2_v3_capture_chain_reservations WHERE turn_id=?",
                    (str(turn_id),),
                ).fetchone()[0],
            )
        assert after == before  # the rejected 33rd GET left no orphan rows
        assert store.get_p2_v3_snapshot(OWNER, turn_id).get_attempts == 32
    finally:
        if second is not None:
            second.close()
        store.close()


def test_capture_chain_same_table_cap_and_known_no_dispatch_vs_unknown_cost(tmp_path: Path) -> None:
    store = _store(tmp_path, "capture-chain-table-cap")
    try:
        turn_id, claim = _create_running_turn(store)
        admission = _admission(store, turn_id, claim, NOW + timedelta(seconds=2))

        known_no_dispatch = store.reserve_p2_v3_stage(
            OWNER, turn_id, claim_token=claim, stage="backend_get",
            active_limit_us=100, backend_limit_us=50, response_bytes_limit=64,
            admission_id=admission, source_role="membership", source_table="activity_members",
            request_digest=_sha("GET /activity_members pre-dispatch"), now=NOW + timedelta(seconds=3),
        )
        store.settle_p2_v3_stage(
            OWNER, turn_id, known_no_dispatch, outcome="known_no_dispatch",
            actual_active_us=10, actual_backend_us=0, actual_response_bytes=0,
            now=NOW + timedelta(seconds=3, milliseconds=1),
        )
        assert store.get_p2_v3_snapshot(OWNER, turn_id).get_attempts == 0

        # The proven pre-dispatch reservation is not a GET: it frees ordinal 0.
        first_unknown = _dispatch_get_from_admission(
            store, turn_id, claim, admission, NOW + timedelta(seconds=4),
            source_table="activity_members", source_role="membership",
        )
        store.settle_p2_v3_stage(
            OWNER, turn_id, first_unknown, outcome="unknown", now=NOW + timedelta(seconds=4, milliseconds=2),
        )
        second_actual = _dispatch_get_from_admission(
            store, turn_id, claim, admission, NOW + timedelta(seconds=5),
            source_table="activity_members", source_role="membership",
        )
        store.settle_p2_v3_stage(
            OWNER, turn_id, second_actual, outcome="actual", actual_active_us=20,
            actual_backend_us=10, actual_response_bytes=2,
            raw_body_sha256=_sha("actual page"), now=NOW + timedelta(seconds=5, milliseconds=2),
        )

        pending = _dispatch_get_from_admission(
            store, turn_id, claim, admission, NOW + timedelta(seconds=6),
            source_table="activity_members", source_role="membership",
        )
        with pytest.raises(P2V3StoreConflict, match="already pending"):
            _dispatch_get_from_admission(
                store, turn_id, claim, admission, NOW + timedelta(seconds=6, milliseconds=1),
                source_table="activity_members", source_role="membership",
            )
        store.settle_p2_v3_stage(
            OWNER, turn_id, pending, outcome="unknown", now=NOW + timedelta(seconds=6, milliseconds=2),
        )

        fourth_ordinal_no_dispatch = store.reserve_p2_v3_stage(
            OWNER, turn_id, claim_token=claim, stage="backend_get",
            active_limit_us=100, backend_limit_us=50, response_bytes_limit=64,
            admission_id=admission, source_role="membership", source_table="activity_members",
            request_digest=_sha("GET /activity_members known no dispatch at ordinal3"),
            capture_chain_table_ordinal=3, now=NOW + timedelta(seconds=7),
        )
        store.settle_p2_v3_stage(
            OWNER, turn_id, fourth_ordinal_no_dispatch, outcome="known_no_dispatch",
            actual_active_us=10, actual_backend_us=0, actual_response_bytes=0,
            now=NOW + timedelta(seconds=7, milliseconds=1),
        )
        fourth_dispatched = _dispatch_get_from_admission(
            store, turn_id, claim, admission, NOW + timedelta(seconds=8),
            source_table="activity_members", source_role="membership",
        )
        store.settle_p2_v3_stage(
            OWNER, turn_id, fourth_dispatched, outcome="unknown", now=NOW + timedelta(seconds=8, milliseconds=2),
        )

        before = store.get_p2_v3_snapshot(OWNER, turn_id)
        with pytest.raises(P2V3StoreConflict, match="source table page budget is exhausted"):
            _dispatch_get_from_admission(
                store, turn_id, claim, admission, NOW + timedelta(seconds=9),
                source_table="activity_members", source_role="membership",
            )
        after = store.get_p2_v3_snapshot(OWNER, turn_id)
        assert after.get_attempts == before.get_attempts == 4
        with store._connection() as connection:
            rows = connection.execute(
                "SELECT reservation_id,table_get_ordinal FROM p2_v3_capture_chain_reservations "
                "WHERE capture_chain_kind='admission' AND capture_chain_id=? ORDER BY chain_sequence",
                (admission,),
            ).fetchall()
            events = {
                row["reservation_id"]: row["event_kind"]
                for row in connection.execute(
                    "SELECT reservation_id,event_kind FROM p2_v3_charge_events "
                    "WHERE turn_id=? AND stage='backend_get' AND event_kind IN ('known_no_dispatch','unknown')",
                    (str(turn_id),),
                ).fetchall()
            }
            reserved_count = connection.execute(
                "SELECT COUNT(*) FROM p2_v3_charge_events WHERE turn_id=? AND stage='backend_get' AND event_kind='reserved'",
                (str(turn_id),),
            ).fetchone()[0]
        assert [row["table_get_ordinal"] for row in rows] == [0, 0, 1, 2, 3, 3]
        assert events[known_no_dispatch] == "known_no_dispatch"
        assert events[first_unknown] == "unknown" and events[pending] == "unknown"
        assert events[fourth_ordinal_no_dispatch] == "known_no_dispatch"
        assert events[fourth_dispatched] == "unknown"
        assert reserved_count == 6  # rejected pending duplicate and fifth page wrote no rows
    finally:
        store.close()


def test_cross_owner_and_table_role_get_rejections_write_no_charge_or_link(tmp_path: Path) -> None:
    store = _store(tmp_path, "capture-chain-owner-role-negative")
    try:
        turn_id, claim = _create_running_turn(store)
        admission = _admission(store, turn_id, claim, NOW + timedelta(seconds=2))
        before = store.get_p2_v3_snapshot(OWNER, turn_id)
        with pytest.raises(StoreNotFound):
            store.reserve_p2_v3_stage(
                uuid.UUID("a1000000-0000-4000-8000-000000000009"), turn_id,
                claim_token=claim, stage="backend_get", active_limit_us=100,
                backend_limit_us=50, response_bytes_limit=64,
                admission_id=admission, source_role="activity", source_table="activities",
                request_digest=_sha("foreign owner"), now=NOW + timedelta(seconds=3),
            )
        with pytest.raises(ValueError, match="does not match its exact source table"):
            store.reserve_p2_v3_stage(
                OWNER, turn_id, claim_token=claim, stage="backend_get", active_limit_us=100,
                backend_limit_us=50, response_bytes_limit=64,
                admission_id=admission, source_role="participant", source_table="activity_members",
                request_digest=_sha("wrong role for table"), now=NOW + timedelta(seconds=4),
            )
        with pytest.raises(ValueError, match="exact v3 table allowlist"):
            store.reserve_p2_v3_stage(
                OWNER, turn_id, claim_token=claim, stage="backend_get", active_limit_us=100,
                backend_limit_us=50, response_bytes_limit=64,
                admission_id=admission, source_role="refund_parent", source_table="expense_refund_sources",
                request_digest=_sha("private source table is not allowed"), now=NOW + timedelta(seconds=5),
            )
        after = store.get_p2_v3_snapshot(OWNER, turn_id)
        assert (after.get_attempts, after.get_reserved, after.revision) == (
            before.get_attempts, before.get_reserved, before.revision,
        )
        with store._connection() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM p2_v3_charge_events WHERE turn_id=? AND stage='backend_get'",
                (str(turn_id),),
            ).fetchone()[0] == 0
            assert connection.execute(
                "SELECT COUNT(*) FROM p2_v3_capture_chain_reservations WHERE turn_id=?",
                (str(turn_id),),
            ).fetchone()[0] == 0
    finally:
        store.close()


def test_typed_date_query_and_exact_selection_resume_reject_descriptor_changes(tmp_path: Path) -> None:
    store = _store(tmp_path, "criteria-date-selection-binding")
    try:
        turn_id, claim = _create_running_turn(store)
        admission = _admission(store, turn_id, claim, NOW + timedelta(seconds=2))
        criteria = ExpenseCriteria(
            kind="expenses", activity_ref=ACTIVITY_REF,
            from_date=date(2026, 10, 13), to_date=date(2026, 10, 14),
        )
        selected = (EXPENSE_REF_1, EXPENSE_REF_2)
        snapshot = store.get_p2_v3_snapshot(OWNER, turn_id)
        query_id = store.create_p2_v3_logical_query(
            OWNER, turn_id, claim_token=claim, admission_id=admission,
            operation="read.expenses", criteria=criteria, scope=_scope(),
            private_selection_refs=selected, expected_revision=snapshot.revision,
            now=NOW + timedelta(seconds=3),
        )
        current = store.get_p2_v3_snapshot(OWNER, turn_id)
        resumed = store.create_p2_v3_logical_query(
            OWNER, turn_id, claim_token=claim, admission_id=admission,
            operation="read.expenses", criteria=criteria, scope=_scope(),
            private_selection_refs=tuple(reversed(selected)), expected_revision=current.revision,
            logical_query_id=query_id, now=NOW + timedelta(seconds=4),
        )
        assert resumed == query_id
        assert store.get_p2_v3_snapshot(OWNER, turn_id).logical_read_calls == 1

        changed_criteria = criteria.model_copy(update={"from_date": date(2026, 10, 12)})
        current = store.get_p2_v3_snapshot(OWNER, turn_id)
        with pytest.raises(P2V3StoreConflict, match="cannot change operation, criteria, or scope"):
            store.create_p2_v3_logical_query(
                OWNER, turn_id, claim_token=claim, admission_id=admission,
                operation="read.expenses", criteria=changed_criteria, scope=_scope(),
                private_selection_refs=selected, expected_revision=current.revision,
                logical_query_id=query_id, now=NOW + timedelta(seconds=5),
            )

        changed_selection = (EXPENSE_REF_1, "ref_1234567890abcdefghijklmn")
        with pytest.raises(P2V3StoreConflict, match="descriptor is missing, stale or changed"):
            store.create_p2_v3_logical_query(
                OWNER, turn_id, claim_token=claim, admission_id=admission,
                operation="read.expenses", criteria=criteria, scope=_scope(),
                private_selection_refs=changed_selection, expected_revision=current.revision,
                logical_query_id=query_id, now=NOW + timedelta(seconds=6),
            )

        unit_scope = P2Scope(
            scope_kind="ledger_unit", scope_ref=LEDGER_UNIT_REF,
            activity_ref=ACTIVITY_REF, ledger_unit_ref=LEDGER_UNIT_REF,
        )
        unit_admission = store.create_p2_v3_source_admission(
            OWNER, turn_id, claim_token=claim,
            requested_scope={
                "scope_kind": "ledger_unit", "activity_id": str(ACTIVITY_ID),
                "ledger_unit_id": str(LEDGER_UNIT_ID),
            },
            public_scope=unit_scope,
            now=NOW + timedelta(seconds=7),
        )
        current = store.get_p2_v3_snapshot(OWNER, turn_id)
        with pytest.raises(P2V3StoreConflict, match="cannot change operation, criteria, or scope"):
            store.create_p2_v3_logical_query(
                OWNER, turn_id, claim_token=claim, admission_id=unit_admission,
                operation="read.expenses", criteria=criteria, scope=unit_scope,
                private_selection_refs=selected, expected_revision=current.revision,
                logical_query_id=query_id, now=NOW + timedelta(seconds=8),
            )
        assert store.get_p2_v3_snapshot(OWNER, turn_id).logical_read_calls == 1
        with store._connection() as connection:
            stored = connection.execute(
                "SELECT q.criteria_json,d.selected_refs_json FROM p2_v3_queries q "
                "JOIN p2_v3_query_descriptor_bindings d USING(logical_query_id) WHERE q.logical_query_id=?",
                (query_id,),
            ).fetchone()
        assert '"from_date":"2026-10-13"' in stored["criteria_json"]
        assert json.loads(stored["selected_refs_json"]) == sorted(selected)
    finally:
        store.close()


def test_output_fact_link_card_ordinal_supports_contract_maximum_with_relational_fixture(tmp_path: Path) -> None:
    """Check the 0..255 SQL envelope only; this synthetic fixture is not a proof acceptance."""
    store = _store(tmp_path, "output-card-ordinal-cap")
    try:
        turn_id, claim = _create_running_turn(store)
        admission_id = _admission(store, turn_id, claim, NOW + timedelta(seconds=2))
        query_id, attempt_id, _ = _query_and_attempt(
            store, turn_id, claim, admission_id, NOW + timedelta(seconds=3),
        )
        with store._connection() as connection:
            pin = connection.execute(
                "SELECT cohort_sha256 FROM p2_v3_turn_execution_pins WHERE turn_id=? AND owner_user_id=?",
                (str(turn_id), str(OWNER)),
            ).fetchone()
            query = connection.execute(
                "SELECT * FROM p2_v3_queries WHERE logical_query_id=?", (query_id,),
            ).fetchone()
            descriptor = connection.execute(
                "SELECT normalized_criteria_digest FROM p2_v3_query_descriptor_bindings WHERE logical_query_id=?",
                (query_id,),
            ).fetchone()
            event_seq = connection.execute(
                "SELECT MAX(seq) FROM events WHERE turn_id=?", (str(turn_id),),
            ).fetchone()[0]
            assert pin is not None and query is not None and descriptor is not None and event_seq is not None
            qev = "qev_" + "a" * 24
            query_ref = "ref_" + "b" * 24
            payload = "{}"
            digest = _sha(payload)
            result_id = "result-card-cap"
            connection.execute(
                """INSERT INTO p2_v3_query_result_receipts (
                    query_result_receipt_id,owner_user_id,turn_id,cohort_sha256,logical_query_id,
                    query_attempt_id,page_index,query_evidence_ref,query_ref,criteria_digest,
                    normalized_criteria_digest,scope_digest,per_activity_financial_versions_json,
                    historical_payload_json,historical_payload_sha256,projection_sha256,
                    source_query_complete,model_projection_complete,has_more,zero_classification,
                    source_total,matched_total,page_count,observed_at,accepted_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,1,'unknown_or_partial',NULL,NULL,0,?,?)""",
                (result_id, str(OWNER), str(turn_id), pin["cohort_sha256"], query_id,
                 attempt_id, 0, qev, query_ref, query["criteria_digest"],
                 descriptor["normalized_criteria_digest"], query["scope_digest"], "{}",
                 payload, digest, digest, NOW.isoformat(), NOW.isoformat()),
            )
            fact_proof_id = "fact-proof-card-cap"
            fact_ref = "fact_" + "c" * 24
            connection.execute(
                """INSERT INTO p2_v3_query_fact_proofs (
                    fact_proof_id,query_result_receipt_id,owner_user_id,turn_id,query_evidence_ref,
                    fact_ref,fact_kind,activity_ref,scope_ref,financial_version,exact_fact_json,
                    exact_fact_sha256,created_at
                ) VALUES (?,?,?,?,?,?, 'expense', ?, ?, NULL, ?, ?, ?)""",
                (fact_proof_id, result_id, str(OWNER), str(turn_id), qev, fact_ref,
                 ACTIVITY_REF, ACTIVITY_REF, payload, digest, NOW.isoformat()),
            )
            protected_id = "synthetic-output-card-cap"
            connection.execute(
                """INSERT INTO p2_v3_protected_outputs (
                    protected_output_id,owner_user_id,turn_id,cohort_sha256,event_seq,output_kind,
                    provenance_kind,historical_payload_json,historical_payload_sha256,generation,
                    input_seq,input_digest,context_revision,proof_set_sha256,created_at
                ) VALUES (?,?,?,?,?,'answer','source_bearing',?,?,1,1,?,1,?,?)""",
                (protected_id, str(OWNER), str(turn_id), pin["cohort_sha256"], int(event_seq),
                 payload, digest, query["input_digest"], digest, NOW.isoformat()),
            )
            connection.execute(
                """INSERT INTO p2_v3_output_fact_links (
                    protected_output_id,owner_user_id,turn_id,card_ordinal,fact_proof_id,
                    public_card_json,public_card_sha256
                ) VALUES (?,?,?,255,?,?,?)""",
                (protected_id, str(OWNER), str(turn_id), fact_proof_id, payload, digest),
            )
            with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
                connection.execute(
                    """INSERT INTO p2_v3_output_fact_links (
                        protected_output_id,owner_user_id,turn_id,card_ordinal,fact_proof_id,
                        public_card_json,public_card_sha256
                    ) VALUES (?,?,?,256,?,?,?)""",
                    (protected_id, str(OWNER), str(turn_id), fact_proof_id, payload, digest),
                )
            assert connection.execute(
                "SELECT card_ordinal FROM p2_v3_output_fact_links WHERE protected_output_id=?",
                (protected_id,),
            ).fetchone()[0] == 255
    finally:
        store.close()


def test_synthetic_cohort_requires_test_flag_and_default_reopen_cannot_dispatch(tmp_path: Path) -> None:
    root = Path(__import__("os").environ["P2_V3_STORE_TEST_ROOT"])
    database = root / "synthetic-default-off.sqlite3"
    test_store = _configured_store(database, allow_synthetic_cohort=True, admission_enabled=True)
    test_store.start()
    try:
        turn_id = _create_queued_turn(test_store, candidate_profile=True)
        with test_store._connection() as connection:
            before = tuple(connection.execute(
                "SELECT * FROM p2_v3_turn_execution_pins WHERE turn_id=? AND owner_user_id=?",
                (str(turn_id), str(OWNER)),
            ).fetchone())
            assert before
    finally:
        test_store.close()

    with pytest.raises(ValueError, match="synthetic P2 v3 cohorts are permitted only by explicit test configuration"):
        _configured_store(database, allow_synthetic_cohort=False, admission_enabled=True)

    # Reopening historical synthetic state in the default production Store may
    # inspect and preserve it, but it cannot claim or rewrite the old pin.
    production_store = SQLiteAgentStore(database, admission_enabled=True)
    production_store.start()
    try:
        with production_store._connection() as connection:
            preserved = tuple(connection.execute(
                "SELECT * FROM p2_v3_turn_execution_pins WHERE turn_id=? AND owner_user_id=?",
                (str(turn_id), str(OWNER)),
            ).fetchone())
        assert preserved == before
        with pytest.raises(P2V3UnsupportedProfile, match="no current verified execution cohort pin"):
            production_store.claim_runnable(
                "default-off-v3-worker", candidate_profile_id=P2_V3_CANDIDATE_PROFILE_ID,
                now=NOW + timedelta(seconds=2),
            )
        with production_store._connection() as connection:
            after = tuple(connection.execute(
                "SELECT * FROM p2_v3_turn_execution_pins WHERE turn_id=? AND owner_user_id=?",
                (str(turn_id), str(OWNER)),
            ).fetchone())
            claim_token = connection.execute(
                "SELECT claim_token FROM turns WHERE turn_id=?", (str(turn_id),),
            ).fetchone()[0]
        assert after == before
        assert claim_token is None
    finally:
        production_store.close()


def test_v3_assignment_is_atomic_immutable_and_cannot_join_v2_family(tmp_path: Path) -> None:
    store = _store(tmp_path, "pin-and-family")
    try:
        ui = c.UIContext(page_type=c.PageType.HOME, captured_at=NOW, client_version="v3-pin-test")
        session = store.create_session(
            OWNER, c.CreateSessionRequest(client_request_id=uuid.uuid4(), title="pin", ui_context=ui), now=NOW,
        ).response_snapshot.session.session_id
        request = c.SubmitTurnRequest(
            client_request_id=uuid.uuid4(), text="Read current expenses", ui_context=ui,
        )
        submitted = store.submit_turn(
            OWNER, session, request, now=NOW, candidate_profile_id=P2_V3_CANDIDATE_PROFILE_ID,
        )
        turn_id = submitted.response_snapshot.turn_id
        original = store.get_p2_v3_snapshot(OWNER, turn_id)
        assert original.profile_id == P2_V3_CANDIDATE_PROFILE_ID
        assert original.versions == ("3.0.0", "2.1.0", "2.1.0", "2.0.0")

        replay = store.submit_turn(OWNER, session, request, now=NOW + timedelta(seconds=1))
        assert replay.response_snapshot.turn_id == turn_id
        assert store.get_p2_v3_snapshot(OWNER, turn_id) == original
        with pytest.raises(StateConflict, match="cannot add or change a candidate assignment"):
            store.submit_turn(
                OWNER, session, request, now=NOW + timedelta(seconds=2),
                candidate_profile_id=P2_CANDIDATE_PROFILE_ID,
            )

        with pytest.raises(sqlite3.IntegrityError, match="profile pin is immutable"):
            with store._transaction() as connection:
                connection.execute(
                    "UPDATE p2_v3_turns SET schema_bundle_sha256=? WHERE turn_id=?",
                    (_sha("changed-pin"), str(turn_id)),
                )

        with pytest.raises(sqlite3.IntegrityError, match="candidate family"):
            with store._transaction() as connection:
                store._insert_p2_candidate_turn(
                    connection,
                    owner_user_id=OWNER,
                    turn_id=turn_id,
                    profile_id=P2_CANDIDATE_PROFILE_ID,
                    generation=original.generation,
                    input_seq=original.input_seq,
                    input_digest=original.input_digest,
                    context_revision=original.context_revision,
                    state_revision=original.state_revision,
                    lifecycle="queued",
                    now=NOW,
                )

        v2_owner = uuid.UUID("a1000000-0000-4000-8000-000000000003")
        v2_turn = _create_queued_turn(
            store, candidate_profile=False, owner=v2_owner, legacy_candidate=True,
        )
        v2_aggregate = store.get_turn(v2_owner, v2_turn)
        input_seq, input_digest = store._p2_input_binding(v2_aggregate.checkpoint)
        with pytest.raises(sqlite3.IntegrityError, match="candidate family"):
            with store._transaction() as connection:
                store._insert_p2_v3_turn(
                    connection,
                    owner_user_id=v2_owner,
                    turn_id=v2_turn,
                    generation=v2_aggregate.checkpoint.generation,
                    input_seq=input_seq,
                    input_digest=input_digest,
                    context_revision=v2_aggregate.checkpoint_revision,
                    state_revision=v2_aggregate.record.turn.state_revision,
                    lifecycle="queued",
                    execution_cohort=store._p2_v3_execution_cohort,
                    now=NOW,
                )
        assert store.get_p2_v3_snapshot(OWNER, turn_id) == original
    finally:
        store.close()


def test_v3_submit_pin_rolls_back_with_the_turn_before_commit(tmp_path: Path) -> None:
    root = Path(__import__("os").environ["P2_V3_STORE_TEST_ROOT"])
    root.mkdir(parents=True, exist_ok=True)
    path = root / "submit-atomic-v3.sqlite3"
    fail_before_commit = True

    def fail(stage: str) -> None:
        if stage == "submit_turn.before_commit" and fail_before_commit:
            raise RuntimeError("synthetic rollback point")

    store = _configured_store(path, admission_enabled=True, fault_injector=fail)
    try:
        store.start()
        ui = c.UIContext(page_type=c.PageType.HOME, captured_at=NOW, client_version="v3-submit-atomic")
        session = store.create_session(
            OWNER, c.CreateSessionRequest(client_request_id=uuid.uuid4(), title="atomic", ui_context=ui), now=NOW,
        ).response_snapshot.session.session_id
        request = c.SubmitTurnRequest(client_request_id=uuid.uuid4(), text="Read the ledger", ui_context=ui)
        with pytest.raises(RuntimeError, match="synthetic rollback"):
            store.submit_turn(
                OWNER, session, request, now=NOW,
                candidate_profile_id=P2_V3_CANDIDATE_PROFILE_ID,
            )
        with store._connection() as connection:
            assert connection.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM p2_v3_turns").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        fail_before_commit = False
        receipt = store.submit_turn(
            OWNER, session, request, now=NOW + timedelta(seconds=1),
            candidate_profile_id=P2_V3_CANDIDATE_PROFILE_ID,
        )
        assert store.get_p2_v3_snapshot(OWNER, receipt.response_snapshot.turn_id).profile_id == P2_V3_CANDIDATE_PROFILE_ID
        with store._connection() as connection:
            assert connection.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM p2_v3_turns").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    finally:
        store.close()


def test_metadata_admission_costs_no_logical_read_and_v3_shapes_reject_secrets(tmp_path: Path) -> None:
    store = _store(tmp_path, "metadata-and-strict-shapes")
    try:
        turn_id, claim = _create_running_turn(store)
        with pytest.raises(ValueError, match="unsupported"):
            store.create_p2_v3_source_admission(
                OWNER, turn_id, claim_token=claim,
                requested_scope={"scope_kind": "activity", "activity_id": str(ACTIVITY_ID), "bearer": "never-store"},
                public_scope=_scope(), now=NOW + timedelta(seconds=2),
            )
        with pytest.raises(ValueError, match="unsupported"):
            store.create_p2_v3_source_admission(
                OWNER, turn_id, claim_token=claim,
                requested_scope={"scope_kind": "activity", "activity_id": str(ACTIVITY_ID)},
                public_scope=_scope(), ui_hint={"activity_id": str(ACTIVITY_ID), "access_token": "never-store"},
                now=NOW + timedelta(seconds=2),
            )

        admissions = [
            _admission(store, turn_id, claim, NOW + timedelta(seconds=2 + index))
            for index in range(P2_V3_MAX_LOGICAL_READS + 1)
        ]
        assert store.get_p2_v3_snapshot(OWNER, turn_id).logical_read_calls == 0
        current = store.get_p2_v3_snapshot(OWNER, turn_id)
        with pytest.raises(ValueError, match="strict v3 contract"):
            store.create_p2_v3_logical_query(
                OWNER, turn_id, claim_token=claim, admission_id=admissions[0],
                operation="read.expenses",
                criteria={"kind": "expenses", "activity_ref": ACTIVITY_REF, "access_token": "never-store"},
                scope=_scope(), expected_revision=current.revision, now=NOW + timedelta(seconds=8),
            )
        assert store.get_p2_v3_snapshot(OWNER, turn_id).logical_read_calls == 0

        for index in range(P2_V3_MAX_LOGICAL_READS):
            current = store.get_p2_v3_snapshot(OWNER, turn_id)
            store.create_p2_v3_logical_query(
                OWNER, turn_id, claim_token=claim, admission_id=admissions[index],
                operation="read.expenses",
                criteria={"kind": "expenses", "activity_ref": ACTIVITY_REF},
                scope=_scope(), expected_revision=current.revision,
                now=NOW + timedelta(seconds=10 + index),
            )
        assert store.get_p2_v3_snapshot(OWNER, turn_id).logical_read_calls == P2_V3_MAX_LOGICAL_READS
        current = store.get_p2_v3_snapshot(OWNER, turn_id)
        with pytest.raises(P2V3StoreConflict, match="budget is exhausted"):
            store.create_p2_v3_logical_query(
                OWNER, turn_id, claim_token=claim, admission_id=admissions[-1],
                operation="read.expenses",
                criteria={"kind": "expenses", "activity_ref": ACTIVITY_REF},
                scope=_scope(), expected_revision=current.revision, now=NOW + timedelta(seconds=20),
            )
        assert store.get_p2_v3_snapshot(OWNER, turn_id).logical_read_calls == P2_V3_MAX_LOGICAL_READS
        with store._connection() as connection:
            descriptors = connection.execute(
                "SELECT criteria_json,scope_json FROM p2_v3_queries WHERE turn_id=?", (str(turn_id),),
            ).fetchall()
        assert len(descriptors) == P2_V3_MAX_LOGICAL_READS
        assert all("never-store" not in row[0] + row[1] for row in descriptors)
    finally:
        store.close()


def test_continuation_issuance_is_private_once_only_and_epoch_bound(tmp_path: Path) -> None:
    store = _store(tmp_path, "continuation-cas")
    try:
        wall_start = datetime.now(timezone.utc).replace(microsecond=0)
        turn_id, claim = _create_running_turn(store, now=wall_start + timedelta(seconds=1))
        fixture = _continuation_read_fixture(store, turn_id, claim, wall_start + timedelta(seconds=2))
        admission = fixture["admission"]
        assert isinstance(admission, p2_source_codec_v3.AdmissionOnlyBinding)
        admission_id = admission.admission_id
        query_id = str(fixture["query_id"])
        first_attempt = str(fixture["attempt_id"])
        first_seq = int(fixture["attempt_seq"])
        assert first_seq == 1
        first = _accept_continuation_page(
            store, turn_id, claim, fixture,
            attempt_id=first_attempt, attempt_seq=first_seq,
            at=wall_start + timedelta(seconds=4),
        )
        with pytest.raises(P2V3StoreConflict, match="not issued"):
            store.consume_p2_v3_continuation(
                OWNER, turn_id, claim_token=claim, logical_query_id=query_id,
                raw_next_page_ref="ref_zzzzzzzzzzzzzzzzzzzzzz", admission_id=admission_id,
                attempt_seq=first_seq, page_index=1,
                source_proof_sha256=str(first["source_proof_sha256"]),
                projection_sha256=str(first["projection_sha256"]),
                now=wall_start + timedelta(seconds=7),
            )

        second_attempt, second_seq = store.begin_p2_v3_query_attempt(
            OWNER, turn_id, claim_token=claim, logical_query_id=query_id,
            admission_id=admission_id, now=wall_start + timedelta(seconds=8),
        )
        assert second_seq == 2 and second_attempt != first_attempt
        with pytest.raises(P2V3StoreConflict, match="latest contiguous page"):
            store.consume_p2_v3_continuation(
                OWNER, turn_id, claim_token=claim, logical_query_id=query_id,
                raw_next_page_ref=str(first["token"]), admission_id=admission_id,
                attempt_seq=first_seq, page_index=1,
                source_proof_sha256=str(first["source_proof_sha256"]),
                projection_sha256=str(first["projection_sha256"]),
                now=wall_start + timedelta(seconds=9),
            )

        second_fixture = _start_expense_query_attempt(
            store, turn_id, claim, fixture, at=wall_start + timedelta(seconds=10),
        )
        second = _accept_continuation_page(
            store, turn_id, claim, second_fixture,
            attempt_id=str(second_fixture["attempt_id"]),
            attempt_seq=int(second_fixture["attempt_seq"]),
            at=wall_start + timedelta(seconds=12),
        )
        page_attempt, page_index, consumed_seq = store.consume_p2_v3_continuation(
            OWNER, turn_id, claim_token=claim, logical_query_id=str(second_fixture["query_id"]),
            raw_next_page_ref=str(second["token"]), admission_id=admission_id,
            attempt_seq=int(second["attempt_seq"]), page_index=1,
            source_proof_sha256=str(second["source_proof_sha256"]),
            projection_sha256=str(second["projection_sha256"]),
            now=wall_start + timedelta(seconds=13),
        )
        assert page_index == 1 and page_attempt and consumed_seq == int(second["attempt_seq"])
        with pytest.raises(P2V3StoreConflict, match="already consumed|latest contiguous page"):
            store.consume_p2_v3_continuation(
                OWNER, turn_id, claim_token=claim, logical_query_id=str(second_fixture["query_id"]),
                raw_next_page_ref=str(second["token"]), admission_id=admission_id,
                attempt_seq=int(second["attempt_seq"]), page_index=1,
                source_proof_sha256=str(second["source_proof_sha256"]),
                projection_sha256=str(second["projection_sha256"]),
                now=wall_start + timedelta(seconds=14),
            )

        old_epoch = store.get_p2_v3_snapshot(OWNER, turn_id).authority_epoch
        assert store.release_claim(turn_id, claim)
        next_claim = store.claim_runnable(
            "nonce-epoch-worker", candidate_profile_id=P2_V3_CANDIDATE_PROFILE_ID,
            now=wall_start + timedelta(seconds=20),
        )
        assert next_claim is not None
        assert store.get_p2_v3_snapshot(OWNER, turn_id).authority_epoch > old_epoch
        activity_id = fixture["activity_id"]
        assert isinstance(activity_id, uuid.UUID)
        new_admission, _ = store.create_p2_v3_request_admission(
            OWNER, turn_id, claim_token=next_claim.claim_token, principal_user_id=OWNER,
            activity_id_hint=activity_id, now=wall_start + timedelta(seconds=21),
        )
        with pytest.raises(P2V3StoreConflict, match="no longer matches"):
            store.consume_p2_v3_continuation(
                OWNER, turn_id, claim_token=next_claim.claim_token,
                logical_query_id=str(second_fixture["query_id"]),
                raw_next_page_ref=str(second["token"]), admission_id=new_admission.admission_id,
                attempt_seq=int(second["attempt_seq"]), page_index=1,
                source_proof_sha256=str(second["source_proof_sha256"]),
                projection_sha256=str(second["projection_sha256"]),
                now=wall_start + timedelta(seconds=22),
            )
    finally:
        store.close()


def test_two_store_connections_only_one_consumer_can_claim_continuation_nonce(tmp_path: Path) -> None:
    store = _store(tmp_path, "continuation-two-connection")
    second: SQLiteAgentStore | None = None
    try:
        # This fixture drives synthetic event timestamps (+1/+2/+4/+8s from here)
        # while the read path it triggers settles charge events on the real
        # clock. The reopen check orders each reservation's events by
        # occurred_at (ties broken by event kind), so a real-clock settle must
        # never precede the synthetic 'reserved' mark. Anchoring the base at
        # "now" put that mark up to 2s in the future, and the test then passed
        # only when the machine happened to be slow enough for real time to
        # overtake it.
        #
        # Anchor the base far enough in the past that every synthetic mark is
        # already behind the real clock, but no further: the Turn claim taken at
        # +1s carries a 30 second lease, so a larger offset (30s was tried)
        # expires the claim mid-test and the read fails with upstream_failure
        # instead.
        wall_start = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=10)
        turn_id, claim = _create_running_turn(store, now=wall_start + timedelta(seconds=1))
        fixture = _continuation_read_fixture(store, turn_id, claim, wall_start + timedelta(seconds=2))
        admission = fixture["admission"]
        assert isinstance(admission, p2_source_codec_v3.AdmissionOnlyBinding)
        query_id = str(fixture["query_id"])
        attempt_id = str(fixture["attempt_id"])
        attempt_seq = int(fixture["attempt_seq"])
        issued = _accept_continuation_page(
            store, turn_id, claim, fixture,
            attempt_id=attempt_id, attempt_seq=attempt_seq,
            at=wall_start + timedelta(seconds=4),
        )
        second = _configured_store(store._path, admission_enabled=True)
        second.start()
        barrier = Barrier(2)

        def consume(adapter: SQLiteAgentStore) -> str:
            barrier.wait(timeout=2)
            try:
                adapter.consume_p2_v3_continuation(
                    OWNER, turn_id, claim_token=claim, logical_query_id=query_id,
                    raw_next_page_ref=str(issued["token"]), admission_id=admission.admission_id,
                    attempt_seq=attempt_seq, page_index=1,
                    source_proof_sha256=str(issued["source_proof_sha256"]),
                    projection_sha256=str(issued["projection_sha256"]),
                    now=wall_start + timedelta(seconds=8),
                )
                return "consumed"
            except P2V3StoreConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(consume, (store, second)))
        assert sorted(outcomes) == ["conflict", "consumed"]
        with store._connection() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM p2_v3_continuation_nonce_uses WHERE logical_query_id=?", (query_id,),
            ).fetchone()[0] == 1
            assert connection.execute(
                "SELECT COUNT(*) FROM p2_v3_query_attempts WHERE logical_query_id=?", (query_id,),
            ).fetchone()[0] == 2
    finally:
        if second is not None:
            second.close()
        store.close()


def test_turn_wide_active_backend_and_bytes_budgets_enforce_exact_caps_and_overrun(tmp_path: Path) -> None:
    store = _store(tmp_path, "turn-budget-caps")
    try:
        turn_id, claim = _create_running_turn(store)
        first = store.reserve_p2_v3_stage(
            OWNER, turn_id, claim_token=claim, stage="backend_processing",
            active_limit_us=P2_V3_MAX_BACKEND_US, backend_limit_us=P2_V3_MAX_BACKEND_US,
            now=NOW + timedelta(seconds=2),
        )
        store.mark_p2_v3_dispatch_started(OWNER, turn_id, first, claim_token=claim, now=NOW + timedelta(seconds=2, milliseconds=1))
        store.settle_p2_v3_stage(
            OWNER, turn_id, first, outcome="actual", actual_active_us=P2_V3_MAX_BACKEND_US,
            actual_backend_us=P2_V3_MAX_BACKEND_US, actual_response_bytes=0,
            now=NOW + timedelta(seconds=2, milliseconds=2),
        )
        with pytest.raises(P2V3StoreConflict, match="physical-work budget is exhausted"):
            store.reserve_p2_v3_stage(
                OWNER, turn_id, claim_token=claim, stage="backend_processing",
                active_limit_us=1, backend_limit_us=1, now=NOW + timedelta(seconds=2, milliseconds=3),
            )
        second = store.reserve_p2_v3_stage(
            OWNER, turn_id, claim_token=claim, stage="local_processing",
            active_limit_us=P2_V3_MAX_ACTIVE_US - P2_V3_MAX_BACKEND_US,
            now=NOW + timedelta(seconds=3),
        )
        store.mark_p2_v3_dispatch_started(OWNER, turn_id, second, claim_token=claim, now=NOW + timedelta(seconds=3, milliseconds=1))
        store.settle_p2_v3_stage(
            OWNER, turn_id, second, outcome="actual",
            actual_active_us=P2_V3_MAX_ACTIVE_US - P2_V3_MAX_BACKEND_US,
            actual_backend_us=0, actual_response_bytes=0,
            now=NOW + timedelta(seconds=3, milliseconds=2),
        )
        snapshot = store.get_p2_v3_snapshot(OWNER, turn_id)
        assert snapshot.active_used_us == P2_V3_MAX_ACTIVE_US
        assert snapshot.backend_used_us == P2_V3_MAX_BACKEND_US
        with pytest.raises(P2V3StoreConflict, match="budget is exhausted"):
            store.reserve_p2_v3_stage(
                OWNER, turn_id, claim_token=claim, stage="local_processing",
                active_limit_us=1, now=NOW + timedelta(seconds=4),
            )
    finally:
        store.close()


def test_get_response_byte_cap_and_overrun_are_durable_unknown_cost(tmp_path: Path) -> None:
    store = _store(tmp_path, "response-byte-cap")
    try:
        at = datetime.now(timezone.utc).replace(microsecond=0)
        turn_id, claim = _create_running_turn(store, now=at + timedelta(seconds=1))
        admission = _admission(store, turn_id, claim, at + timedelta(seconds=2))
        one_mib = 1024 * 1024
        with pytest.raises(ValueError, match="per-GET response cap"):
            store.reserve_p2_v3_stage(
                OWNER, turn_id, claim_token=claim, stage="backend_get",
                active_limit_us=100, backend_limit_us=50, response_bytes_limit=one_mib + 1,
                admission_id=admission, source_role="activity", request_digest=_sha("oversized reservation"),
                now=at + timedelta(seconds=3),
            )

        first = store.reserve_p2_v3_stage(
            OWNER, turn_id, claim_token=claim, stage="backend_get",
            active_limit_us=100, backend_limit_us=50, response_bytes_limit=one_mib,
            admission_id=admission, source_role="activity", request_digest=_sha("GET /activities/0"),
            now=at + timedelta(seconds=3),
        )
        store.mark_p2_v3_dispatch_started(OWNER, turn_id, first, claim_token=claim, now=at + timedelta(seconds=3, milliseconds=1))
        store.settle_p2_v3_stage(
            OWNER, turn_id, first, outcome="actual", actual_active_us=100, actual_backend_us=50,
            actual_response_bytes=one_mib + 1, raw_body_sha256=_sha("too-large-body"),
            now=at + timedelta(seconds=3, milliseconds=2),
        )

        # A second Store instance must see the first GET's overrun. Each later
        # request remains individually within the 1 MiB response cap.
        second_store = _store(tmp_path, "response-byte-cap")
        try:
            request_sizes = (one_mib, one_mib, one_mib - 1)
            for index, size in enumerate(request_sizes, start=1):
                request_at = at + timedelta(seconds=3 + index)
                reservation = second_store.reserve_p2_v3_stage(
                    OWNER, turn_id, claim_token=claim, stage="backend_get",
                    active_limit_us=100, backend_limit_us=50, response_bytes_limit=size,
                    admission_id=admission, source_role="activity", request_digest=_sha(f"GET /activities/{index}"),
                    now=request_at,
                )
                second_store.mark_p2_v3_dispatch_started(
                    OWNER, turn_id, reservation, claim_token=claim, now=request_at + timedelta(milliseconds=1),
                )
                second_store.settle_p2_v3_stage(
                    OWNER, turn_id, reservation, outcome="actual", actual_active_us=100,
                    actual_backend_us=50, actual_response_bytes=size,
                    raw_body_sha256=_sha(f"body-{index}"), now=request_at + timedelta(milliseconds=2),
                )
            snapshot = second_store.get_p2_v3_snapshot(OWNER, turn_id)
            assert (snapshot.active_used_us, snapshot.backend_used_us) == (400, 200)
            assert snapshot.response_bytes == P2_V3_MAX_RESPONSE_BYTES - 1
            assert snapshot.get_attempts == 4
            assert snapshot.historical_unknown_consumption is True
            with second_store._connection() as connection:
                terminal = connection.execute(
                    "SELECT event_kind,actual_response_bytes,overrun_active_us,overrun_backend_us,overrun_response_bytes,raw_body_sha256 FROM p2_v3_charge_events WHERE reservation_id=? AND event_kind IN ('settled','unknown')",
                    (first,),
                ).fetchone()
                captures = connection.execute(
                    "SELECT COUNT(*) FROM p2_v3_wire_captures WHERE reservation_id=?",
                    (first,),
                ).fetchone()[0]
            assert tuple(terminal) == ("unknown", one_mib, 0, 0, 1, None)
            assert captures == 0
            with pytest.raises(P2V3StoreConflict, match="budget is exhausted"):
                second_store.reserve_p2_v3_stage(
                    OWNER, turn_id, claim_token=claim, stage="backend_get",
                    active_limit_us=1, backend_limit_us=1, response_bytes_limit=1,
                    admission_id=admission, source_role="activity", request_digest=_sha("GET /activities/last"),
                    now=at + timedelta(seconds=10),
                )
        finally:
            second_store.close()
    finally:
        store.close()


def test_known_no_dispatch_active_overrun_consumes_remaining_after_second_store(tmp_path: Path) -> None:
    at = datetime.now(timezone.utc).replace(microsecond=0)
    first_store = _store(tmp_path, "known-active-overrun")
    second_store = None
    try:
        turn_id, claim = _create_running_turn(first_store, now=at + timedelta(seconds=1))
        first = first_store.reserve_p2_v3_stage(
            OWNER, turn_id, claim_token=claim, stage="local_processing",
            active_limit_us=1, now=at + timedelta(seconds=2),
        )
        first_store.settle_p2_v3_stage(
            OWNER, turn_id, first, outcome="known_no_dispatch", actual_active_us=2,
            now=at + timedelta(seconds=3),
        )

        second_store = _store(tmp_path, "known-active-overrun")
        second = second_store.reserve_p2_v3_stage(
            OWNER, turn_id, claim_token=claim, stage="local_processing",
            active_limit_us=P2_V3_MAX_ACTIVE_US - 2, now=at + timedelta(seconds=4),
        )
        second_store.settle_p2_v3_stage(
            OWNER, turn_id, second, outcome="known_no_dispatch",
            actual_active_us=P2_V3_MAX_ACTIVE_US - 2, now=at + timedelta(seconds=5),
        )
        with pytest.raises(P2V3StoreConflict, match="physical-work budget is exhausted"):
            second_store.reserve_p2_v3_stage(
                OWNER, turn_id, claim_token=claim, stage="local_processing",
                active_limit_us=1, now=at + timedelta(seconds=6),
            )
        with second_store._connection() as connection:
            overruns = connection.execute(
                "SELECT COALESCE(SUM(overrun_active_us),0) FROM p2_v3_charge_events WHERE owner_user_id=? AND turn_id=?",
                (str(OWNER), str(turn_id)),
            ).fetchone()[0]
        assert overruns == 1
    finally:
        if second_store is not None:
            second_store.close()
        first_store.close()


def test_dispatched_backend_overrun_is_cumulative_but_unknown_does_not_ban_remaining_budget(tmp_path: Path) -> None:
    at = datetime.now(timezone.utc).replace(microsecond=0)
    first_store = _store(tmp_path, "backend-overrun")
    second_store = None
    try:
        turn_id, claim = _create_running_turn(first_store, now=at + timedelta(seconds=1))
        first = first_store.reserve_p2_v3_stage(
            OWNER, turn_id, claim_token=claim, stage="backend_processing",
            active_limit_us=1, backend_limit_us=1, now=at + timedelta(seconds=2),
        )
        first_store.mark_p2_v3_dispatch_started(
            OWNER, turn_id, first, claim_token=claim, now=at + timedelta(seconds=3),
        )
        first_store.settle_p2_v3_stage(
            OWNER, turn_id, first, outcome="actual", actual_active_us=2,
            actual_backend_us=2, now=at + timedelta(seconds=4),
        )

        second_store = _store(tmp_path, "backend-overrun")
        remaining = P2_V3_MAX_BACKEND_US - 2
        second = second_store.reserve_p2_v3_stage(
            OWNER, turn_id, claim_token=claim, stage="backend_processing",
            active_limit_us=remaining, backend_limit_us=remaining, now=at + timedelta(seconds=5),
        )
        second_store.mark_p2_v3_dispatch_started(
            OWNER, turn_id, second, claim_token=claim, now=at + timedelta(seconds=6),
        )
        second_store.settle_p2_v3_stage(
            OWNER, turn_id, second, outcome="actual", actual_active_us=remaining,
            actual_backend_us=remaining, now=at + timedelta(seconds=7),
        )
        with pytest.raises(P2V3StoreConflict, match="physical-work budget is exhausted"):
            second_store.reserve_p2_v3_stage(
                OWNER, turn_id, claim_token=claim, stage="backend_processing",
                active_limit_us=1, backend_limit_us=1, now=at + timedelta(seconds=8),
            )
        with second_store._connection() as connection:
            row = connection.execute(
                "SELECT SUM(overrun_backend_us),COUNT(*) FROM p2_v3_charge_events WHERE owner_user_id=? AND turn_id=? AND event_kind='unknown'",
                (str(OWNER), str(turn_id)),
            ).fetchone()
        assert tuple(row) == (1, 1)
    finally:
        if second_store is not None:
            second_store.close()
        first_store.close()


def test_unknown_without_measurements_charges_reservation_and_keeps_remaining_slots(tmp_path: Path) -> None:
    at = datetime.now(timezone.utc).replace(microsecond=0)
    first_store = _store(tmp_path, "unknown-no-measurement")
    second_store = None
    try:
        turn_id, claim = _create_running_turn(first_store, now=at + timedelta(seconds=1))
        model = first_store.reserve_p2_v3_stage(
            OWNER, turn_id, claim_token=claim, stage="model", active_limit_us=100,
            now=at + timedelta(seconds=2),
        )
        first_store.mark_p2_v3_dispatch_started(
            OWNER, turn_id, model, claim_token=claim,
            prepared_request_sha256=_sha("prepared-unknown-model"),
            selected_model_key="configured-test-model",
            validated_measurement_sha256=_sha("measurement-unknown-model"),
            now=at + timedelta(seconds=3),
        )
        first_store.settle_p2_v3_stage(
            OWNER, turn_id, model, outcome="unknown", now=at + timedelta(seconds=4),
        )
        admission = _admission(first_store, turn_id, claim, at + timedelta(seconds=5))
        get = _dispatch_get_from_admission(
            first_store, turn_id, claim, admission, at + timedelta(seconds=6),
            active_limit_us=100, backend_limit_us=50, response_bytes_limit=256,
        )
        first_store.settle_p2_v3_stage(
            OWNER, turn_id, get, outcome="unknown", now=at + timedelta(seconds=7),
        )
        first_snapshot = first_store.get_p2_v3_snapshot(OWNER, turn_id)
        assert (first_snapshot.model_calls, first_snapshot.model_reserved_calls) == (1, 0)
        assert (first_snapshot.get_attempts, first_snapshot.get_reserved) == (1, 0)
        assert (first_snapshot.active_used_us, first_snapshot.backend_used_us, first_snapshot.response_bytes) == (200, 50, 256)

        second_store = _store(tmp_path, "unknown-no-measurement")
        next_model = _dispatch_model(second_store, turn_id, claim, at + timedelta(seconds=8))
        second_store.settle_p2_v3_stage(
            OWNER, turn_id, next_model, outcome="actual", actual_active_us=1_000,
            now=at + timedelta(seconds=9),
        )
        next_get = _dispatch_get_from_admission(
            second_store, turn_id, claim, admission, at + timedelta(seconds=10),
            active_limit_us=1_000, backend_limit_us=100, response_bytes_limit=64,
        )
        second_store.settle_p2_v3_stage(
            OWNER, turn_id, next_get, outcome="actual", actual_active_us=1_000,
            actual_backend_us=100, actual_response_bytes=64, raw_body_sha256=_sha("small response"),
            now=at + timedelta(seconds=11),
        )
        snapshot = second_store.get_p2_v3_snapshot(OWNER, turn_id)
        assert (snapshot.model_calls, snapshot.model_reserved_calls) == (2, 0)
        assert (snapshot.get_attempts, snapshot.get_reserved) == (2, 0)
        assert (snapshot.active_used_us, snapshot.backend_used_us, snapshot.response_bytes) == (2_200, 150, 320)
        with second_store._connection() as connection:
            unknown_rows = connection.execute(
                "SELECT stage,actual_active_us,actual_backend_us,actual_response_bytes,overrun_active_us,overrun_backend_us,overrun_response_bytes,raw_body_sha256 FROM p2_v3_charge_events WHERE reservation_id IN (?,?) AND event_kind='unknown' ORDER BY stage",
                (model, get),
            ).fetchall()
        assert tuple(tuple(row) for row in unknown_rows) == (
            ("backend_get", 100, 50, 256, 0, 0, 0, None),
            ("model", 100, 0, 0, 0, 0, 0, None),
        )
    finally:
        if second_store is not None:
            second_store.close()
        first_store.close()


def test_proven_pre_dispatch_cancellation_releases_model_slot_but_keeps_active_cost(tmp_path: Path) -> None:
    store = _store(tmp_path, "known-no-dispatch")
    try:
        turn_id, claim = _create_running_turn(store)
        reservation = store.reserve_p2_v3_stage(
            OWNER, turn_id, claim_token=claim, stage="model", active_limit_us=1_000,
            now=NOW + timedelta(seconds=2),
        )
        store.settle_p2_v3_stage(
            OWNER, turn_id, reservation, outcome="known_no_dispatch", actual_active_us=125,
            actual_backend_us=0, actual_response_bytes=0, now=NOW + timedelta(seconds=2, milliseconds=1),
        )
        snapshot = store.get_p2_v3_snapshot(OWNER, turn_id)
        assert (snapshot.model_calls, snapshot.model_reserved_calls) == (0, 0)
        assert snapshot.active_used_us == 125
        assert snapshot.active_reserved_us == 0
        with store._connection() as connection:
            events = connection.execute(
                "SELECT event_kind,actual_active_us,actual_backend_us,actual_response_bytes FROM p2_v3_charge_events WHERE reservation_id=? ORDER BY occurred_at",
                (reservation,),
            ).fetchall()
        assert [tuple(row) for row in events] == [
            ("reserved", None, None, None),
            ("known_no_dispatch", 125, 0, 0),
        ]

        second = store.reserve_p2_v3_stage(
            OWNER, turn_id, claim_token=claim, stage="model", active_limit_us=100,
            now=NOW + timedelta(seconds=3),
        )
        store.mark_p2_v3_dispatch_started(
            OWNER, turn_id, second, claim_token=claim,
            prepared_request_sha256=_sha("prepared"), selected_model_key="configured-test-model",
            validated_measurement_sha256=_sha("measured"), now=NOW + timedelta(seconds=3, milliseconds=1),
        )
        snapshot = store.get_p2_v3_snapshot(OWNER, turn_id)
        assert (snapshot.model_calls, snapshot.model_reserved_calls) == (1, 0)
    finally:
        store.close()


def test_two_store_connections_race_for_one_turn_wide_budget_reservation(tmp_path: Path) -> None:
    store = _store(tmp_path, "reservation-two-connection")
    second: SQLiteAgentStore | None = None
    try:
        wall_start = datetime.now(timezone.utc).replace(microsecond=0)
        turn_id, claim = _create_running_turn(store, now=wall_start + timedelta(seconds=1))
        second = _configured_store(store._path, admission_enabled=True)
        second.start()
        barrier = Barrier(2)

        def reserve(adapter: SQLiteAgentStore) -> str:
            barrier.wait(timeout=2)
            try:
                return adapter.reserve_p2_v3_stage(
                    OWNER, turn_id, claim_token=claim, stage="local_processing",
                    active_limit_us=P2_V3_MAX_ACTIVE_US,
                    now=wall_start + timedelta(seconds=2),
                )
            except P2V3StoreConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(reserve, (store, second)))
        assert sum(value != "conflict" for value in outcomes) == 1
        assert outcomes.count("conflict") == 1
        snapshot = store.get_p2_v3_snapshot(OWNER, turn_id)
        assert snapshot.active_reserved_us == P2_V3_MAX_ACTIVE_US
        assert snapshot.active_used_us == 0
        winner = next(value for value in outcomes if value != "conflict")
        store.settle_p2_v3_stage(
            OWNER, turn_id, winner, outcome="known_no_dispatch", actual_active_us=0,
            actual_backend_us=0, actual_response_bytes=0, now=wall_start + timedelta(seconds=3),
        )
        assert store.get_p2_v3_snapshot(OWNER, turn_id).active_reserved_us == 0
    finally:
        if second is not None:
            second.close()
        store.close()


def test_wire_capture_is_cost_only_and_requires_matching_settled_get(tmp_path: Path) -> None:
    store = _store(tmp_path, "wire-cost-only")
    try:
        turn_id, claim = _create_running_turn(store)
        admission = _admission(store, turn_id, claim, NOW + timedelta(seconds=2))
        body = b"[]"
        digest = hashlib.sha256(body).hexdigest()
        reservation = _dispatch_get_from_admission(
            store, turn_id, claim, admission, NOW + timedelta(seconds=3),
            active_limit_us=100, backend_limit_us=50, response_bytes_limit=64,
        )
        store.settle_p2_v3_stage(
            OWNER, turn_id, reservation, outcome="actual", actual_active_us=20,
            actual_backend_us=10, actual_response_bytes=len(body), raw_body_sha256=digest,
            now=NOW + timedelta(seconds=3, milliseconds=2),
        )
        with pytest.raises(P2V3StoreConflict, match="differs from its settled GET cost"):
            store.record_p2_v3_wire_capture_cost_only(
                OWNER, turn_id, reservation, http_status=200, content_range="*/0",
                returned_count=0, response_bytes=len(body), raw_body_sha256=_sha("different"),
                observed_at=NOW + timedelta(seconds=3, milliseconds=3),
            )
        capture_id = store.record_p2_v3_wire_capture_cost_only(
            OWNER, turn_id, reservation, http_status=200, content_range="*/0",
            returned_count=0, response_bytes=len(body), raw_body_sha256=digest,
            observed_at=NOW + timedelta(seconds=3, milliseconds=4),
        )
        with store._connection() as connection:
            capture = connection.execute(
                "SELECT capture_state,http_status,content_range,raw_body_sha256 FROM p2_v3_wire_captures WHERE capture_id=?",
                (capture_id,),
            ).fetchone()
            assert tuple(capture) == ("cost_only", 200, "*/0", digest)
            assert connection.execute("SELECT COUNT(*) FROM p2_v3_continuation_nonce_issues").fetchone()[0] == 0
        assert store.get_p2_v3_snapshot(OWNER, turn_id).logical_read_calls == 0
    finally:
        store.close()


def test_store_rejects_source_component_drift_before_admission_or_budget_write(tmp_path: Path) -> None:
    root = Path(__import__("os").environ["P2_V3_STORE_TEST_ROOT"])
    component_path = root / "synthetic-cohort-components" / "fixture.json"
    original = component_path.read_bytes()
    store = _store(tmp_path, "source-component-drift-store-integration")
    try:
        turn_id, claim = _create_running_turn(store)
        component_path.write_bytes(b'{"purpose":"mutated after verifier issuance"}')
        with pytest.raises(P2V3UnsupportedProfile, match="current execution cohort changed"):
            _admission(store, turn_id, claim, NOW + timedelta(seconds=2))
        with store._connection() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM p2_v3_source_admissions WHERE turn_id=?",
                (str(turn_id),),
            ).fetchone()[0] == 0
            assert connection.execute(
                "SELECT COUNT(*) FROM p2_v3_charge_events WHERE turn_id=?",
                (str(turn_id),),
            ).fetchone()[0] == 0
    finally:
        store.close()
        component_path.write_bytes(original)
