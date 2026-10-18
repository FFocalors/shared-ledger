from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent.app import backup, contracts as c, mock_fixtures
from agent.app.backup import (
    BackupSourceError,
    BackupTargetError,
    BackupTimeout,
    BackupValidationError,
    create_backup,
    restore_backup,
    verify_backup,
)
from agent.app.store import EventDraft, SQLiteAgentStore


NOW = datetime(2026, 10, 8, 4, 0, tzinfo=timezone.utc)
OWNER = uuid.UUID("9f668ca1-0b20-4fcf-b0fd-35bde85a9945")


def _store(path: Path) -> SQLiteAgentStore:
    store = SQLiteAgentStore(path, busy_timeout_seconds=0.4)
    store.start()
    return store


def _session(store: SQLiteAgentStore, *, title: str = "Backup validation") -> uuid.UUID:
    request = c.CreateSessionRequest(
        client_request_id=uuid.uuid4(), title=title,
        ui_context=c.UIContext(page_type=c.PageType.HOME, captured_at=NOW, client_version="backup-test"),
    )
    return store.create_session(OWNER, request, now=NOW).response_snapshot.session.session_id


def _submit(store: SQLiteAgentStore, session_id: uuid.UUID) -> uuid.UUID:
    request = c.SubmitTurnRequest(
        client_request_id=uuid.uuid4(), text="record lunch",
        ui_context=c.UIContext(
            page_type=c.PageType.ACTIVITY_OVERVIEW,
            activity_id=mock_fixtures.ACTIVITY_ID,
            captured_at=NOW,
            client_version="backup-test",
        ),
    )
    return store.submit_turn(OWNER, session_id, request, now=NOW).response_snapshot.turn_id


def _next_state(
    before: c.TurnStateSnapshot,
    *,
    state: c.TurnState,
    step: c.TurnStep,
    wait_reason: c.WaitReason | None = None,
    resolution: c.ExecutionResolution | None = None,
    execution: c.ExecutionIdentity | None = None,
) -> c.TurnStateSnapshot:
    data = before.model_dump(mode="python", by_alias=True, exclude_none=False)
    data.update({
        "state": state,
        "step": step,
        "state_revision": before.state_revision + 1,
        "wait_reason": wait_reason,
        "resume_state": None,
        "execution_resolution": resolution,
    })
    if execution is not None:
        data["execution"] = execution.model_dump(mode="python", by_alias=True, exclude_none=False)
    return c.TurnStateSnapshot.model_validate(data)


def _status(snapshot: c.TurnStateSnapshot, *, simulation: bool) -> EventDraft:
    return EventDraft(
        type=c.EventType.STATUS,
        occurred_at=NOW + timedelta(seconds=snapshot.state_revision),
        simulation=simulation,
        payload=c.StatusEventPayload(
            state=snapshot.state,
            step=snapshot.step,
            state_revision=snapshot.state_revision,
            wait_reason=snapshot.wait_reason,
            resume_state=snapshot.resume_state,
        ),
    )


def _make_proposal(
    owner: uuid.UUID,
    session_id: uuid.UUID,
    turn_id: uuid.UUID,
    *,
    backend: bool,
    nonce: str,
) -> c.ProposalRecord:
    intent = mock_fixtures._expense_create(mock_fixtures.references(turn_id))
    trajectory = mock_fixtures.propose_wait_confirm_and_confirm_disabled()
    card = next(item.card for item in trajectory.steps if isinstance(item, c.ProposalCardStep))
    preview_data = card.preview.model_dump(mode="python", by_alias=True, exclude_none=False)
    preview_data["simulation"] = not backend
    preview = c.ExpensePreview.model_validate(preview_data)
    command = preconditions = digest = confirmation_nonce = None
    mode: str = "simulation"
    if backend:
        mode = "backend"
        command = c.FixedExpenseCreateCommand(
            operation="expense.create",
            activity_id=mock_fixtures.ACTIVITY_ID,
            ledger_unit_id=mock_fixtures.UNIT_ID,
            title="Lunch",
            original_amount="12.50",
            original_currency="CNY",
            payment_allocations=[c.CanonicalPayment(participant_id=mock_fixtures.PARTICIPANT_1, amount="12.50")],
            split=c.CanonicalEqualSplit(
                mode="equal",
                participant_ids=[mock_fixtures.PARTICIPANT_1, mock_fixtures.PARTICIPANT_2],
            ),
            occurred_at=NOW,
            expected_financial_version="0",
        )
        preconditions = c.PreconditionSnapshot(
            activity_id=mock_fixtures.ACTIVITY_ID,
            permission_checked=True,
            agent_disable_revision=0,
            activity_financial_version="0",
            expense_version=None,
            policy_version="backup-test",
            verified_at=NOW,
        )
        digest = c.canonical_command_digest(command, preconditions, policy_version="backup-test")
        confirmation_nonce = nonce
    return c.ProposalRecord(
        proposal_id=uuid.uuid4(),
        owner_user_id=owner,
        session_id=session_id,
        turn_id=turn_id,
        revision=1,
        operation="expense.create",
        mode=mode,
        status=c.ProposalStatus.PENDING,
        intent=intent,
        canonical_command=command,
        preview=preview,
        preconditions=preconditions,
        command_digest=digest,
        confirmation_nonce=confirmation_nonce,
        policy_version="backup-test",
        expires_at=NOW + timedelta(days=5),
        execution=None,
        request_receipts=[],
    )


def _persist_waiting_proposal(
    store: SQLiteAgentStore,
    owner: uuid.UUID,
    session_id: uuid.UUID,
    *,
    backend: bool,
    nonce: str,
) -> tuple[uuid.UUID, c.ProposalRecord]:
    turn_id = _submit(store, session_id)
    aggregate = store.get_turn(owner, turn_id)
    queued = aggregate.record.turn
    running = _next_state(queued, state=c.TurnState.RUNNING, step=c.TurnStep.MODEL_DECISION)
    store.transition_turn(
        owner, running,
        expected_state_revision=queued.state_revision,
        expected_checkpoint_revision=aggregate.checkpoint_revision,
        events=[_status(running, simulation=not backend)],
        now=NOW + timedelta(seconds=1),
    )
    proposal = _make_proposal(owner, session_id, turn_id, backend=backend, nonce=nonce)
    aggregate = store.get_turn(owner, turn_id)
    waiting = _next_state(
        running,
        state=c.TurnState.WAIT_CONFIRM,
        step=c.TurnStep.AWAITING_USER,
        wait_reason=c.WaitReason.CONFIRM_REQUIRED,
    )
    proposal_event = EventDraft(
        type=c.EventType.PROPOSAL,
        occurred_at=NOW + timedelta(seconds=2),
        simulation=not backend,
        payload=c.ProposalEventPayload(
            proposal_id=proposal.proposal_id,
            revision=proposal.revision,
            operation=proposal.operation,
        ),
    )
    store.transition_turn(
        owner, waiting,
        expected_state_revision=running.state_revision,
        expected_checkpoint_revision=aggregate.checkpoint_revision,
        events=[_status(waiting, simulation=not backend), proposal_event],
        new_proposal=proposal,
        now=NOW + timedelta(seconds=2),
    )
    return turn_id, proposal


def _make_unknown_execution(
    store: SQLiteAgentStore,
    owner: uuid.UUID,
    turn_id: uuid.UUID,
    proposal: c.ProposalRecord,
) -> c.ExecutionIdentity:
    waiting = store.get_turn(owner, turn_id).record.turn
    execution = c.ExecutionIdentity(
        execution_id=c.derive_execution_id(owner, proposal.proposal_id, proposal.revision),
        actor_id=owner,
        proposal_id=proposal.proposal_id,
        proposal_revision=proposal.revision,
    )
    executing = _next_state(
        waiting, state=c.TurnState.EXECUTING, step=c.TurnStep.DISPATCH, execution=execution,
    )
    confirmed = c.ProposalRecord.model_validate(
        proposal.model_dump(mode="python", by_alias=True, exclude_none=False)
        | {
            "status": c.ProposalStatus.CONFIRMED,
            "confirmation_nonce": None,
            "execution": execution.model_dump(mode="python", by_alias=True, exclude_none=False),
        }
    )
    aggregate = store.get_turn(owner, turn_id)
    store.transition_turn(
        owner, executing,
        expected_state_revision=waiting.state_revision,
        expected_checkpoint_revision=aggregate.checkpoint_revision,
        events=[_status(executing, simulation=False)],
        updated_proposal=confirmed,
        fixture_execution=True,
        now=NOW + timedelta(seconds=3),
    )
    recovering = _next_state(
        executing,
        state=c.TurnState.RECOVERING,
        step=c.TurnStep.RECONCILE,
        resolution=c.ExecutionResolution.UNKNOWN,
        execution=execution,
    )
    reference = c.ExecutionReference(
        execution_id=execution.execution_id,
        proposal_id=proposal.proposal_id,
        proposal_revision=proposal.revision,
    )
    result_event = EventDraft(
        type=c.EventType.EXECUTION_RESULT,
        occurred_at=NOW + timedelta(seconds=4),
        simulation=False,
        payload=c.ExecutionResultPayload(execution=reference, resolution=c.ExecutionResolution.UNKNOWN),
    )
    aggregate = store.get_turn(owner, turn_id)
    store.transition_turn(
        owner, recovering,
        expected_state_revision=executing.state_revision,
        expected_checkpoint_revision=aggregate.checkpoint_revision,
        events=[_status(recovering, simulation=False), result_event],
        now=NOW + timedelta(seconds=4),
    )
    return execution


def _seed_database(path: Path) -> dict[str, object]:
    store = _store(path)
    pending_session = _session(store, title="Pending proposal")
    pending_turn, pending_proposal = _persist_waiting_proposal(
        store, OWNER, pending_session, backend=True, nonce="N" * 40,
    )
    unknown_session = _session(store, title="Unknown execution")
    unknown_turn, unknown_proposal = _persist_waiting_proposal(
        store, OWNER, unknown_session, backend=True, nonce="U" * 40,
    )
    execution = _make_unknown_execution(store, OWNER, unknown_turn, unknown_proposal)
    store.close()
    return {
        "pending_session": pending_session,
        "pending_turn": pending_turn,
        "pending_proposal": pending_proposal,
        "unknown_session": unknown_session,
        "unknown_turn": unknown_turn,
        "unknown_proposal": unknown_proposal,
        "execution": execution,
    }


def _archive_contents(path: Path) -> tuple[dict[str, object], bytes]:
    with zipfile.ZipFile(path, "r") as archive:
        manifest = json.loads(archive.read("manifest.json"))
        database = archive.read("database.sqlite3")
    return manifest, database


def _write_archive(path: Path, manifest: dict[str, object], database: bytes) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True, separators=(",", ":")))
        archive.writestr("database.sqlite3", database)


def test_online_wal_backup_restores_real_store_and_concurrent_commits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source db #one.sqlite3"
    archive = tmp_path / "backup folder" / "agent restore #one.zip"
    target = tmp_path / "restored database #one.sqlite3"
    archive.parent.mkdir()
    expected = _seed_database(source)

    # Keep a WAL reader open so committed state remains in WAL while the live
    # store continues writing through its normal transaction methods.
    held_connection = sqlite3.connect(source, isolation_level=None)
    assert held_connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    monkeypatch.setattr(backup, "_BACKUP_PAGES", 1)
    monkeypatch.setattr(backup, "_BACKUP_SLEEP_SECONDS", 0.001)
    writer = _store(source)
    stop = threading.Event()
    committed: list[uuid.UUID] = []

    def write_commits() -> None:
        while not stop.is_set():
            try:
                committed.append(_submit(writer, expected["pending_session"]))
            except Exception as exc:  # pragma: no cover - assertion below reports unexpected writer failures
                committed.append(exc)  # type: ignore[arg-type]
                return
            time.sleep(0.002)

    thread = threading.Thread(target=write_commits, daemon=True)
    thread.start()
    try:
        time.sleep(0.02)
        assert Path(str(source) + "-wal").exists()
        commits_at_start = len(committed)
        info = create_backup(source, archive, timeout_seconds=8)
        commits_at_finish = len(committed)
        assert info.database_sha256 == hashlib.sha256(_archive_contents(archive)[1]).hexdigest()
    finally:
        stop.set()
        thread.join(timeout=3)
        writer.close()
        held_connection.close()

    assert commits_at_finish > commits_at_start
    assert committed and not any(isinstance(item, Exception) for item in committed)
    verified = verify_backup(archive)
    assert verified.archive_sha256 == info.archive_sha256
    restored = restore_backup(archive, target)
    assert restored.database_sha256 == info.database_sha256
    assert not any(Path(str(target) + suffix).exists() for suffix in ("-wal", "-shm", "-journal"))

    # Actual service startup revalidates migration hashes, schema, rows, and FK integrity.
    recovered = _store(target)
    try:
        assert recovered.get_session(OWNER, expected["pending_session"]) is not None
        pending_turn = recovered.get_turn(OWNER, expected["pending_turn"]).record.turn
        assert pending_turn.state == c.TurnState.WAIT_CONFIRM
        pending_proposal = recovered.get_proposal(OWNER, expected["pending_proposal"].proposal_id)
        assert pending_proposal.status == c.ProposalStatus.PENDING
        assert pending_proposal.confirmation_nonce == "N" * 40
        unknown_turn = recovered.get_turn(OWNER, expected["unknown_turn"]).record.turn
        assert unknown_turn.state == c.TurnState.RECOVERING
        assert unknown_turn.execution == expected["execution"]
        assert unknown_turn.execution_resolution == c.ExecutionResolution.UNKNOWN
        confirmed = recovered.get_proposal(OWNER, expected["unknown_proposal"].proposal_id)
        assert confirmed.status == c.ProposalStatus.CONFIRMED
        assert confirmed.execution == expected["execution"]
        assert confirmed.confirmation_nonce is None
        assert len(recovered.read_turn_view(OWNER, expected["unknown_turn"]).events) >= 5
        with sqlite3.connect(target) as connection:
            # Every queued turn and each later status/proposal event came from
            # one complete Store transaction in the SQLite snapshot.
            turn_count = connection.execute("SELECT count(*) FROM turns").fetchone()[0]
            event_turn_count = connection.execute("SELECT count(DISTINCT turn_id) FROM events").fetchone()[0]
            assert turn_count == event_turn_count
            assert turn_count >= 2 + commits_at_start
    finally:
        recovered.close()


def test_missing_source_is_rejected_without_creating_database_or_backup(tmp_path: Path) -> None:
    missing = tmp_path / "missing # ?.sqlite3"
    output = tmp_path / "backup.zip"
    with pytest.raises(BackupSourceError):
        create_backup(missing, output)
    assert not missing.exists()
    assert not output.exists()


def test_digest_tamper_and_protocol_incompatibility_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    _seed_database(source)
    archive = tmp_path / "good.zip"
    create_backup(source, archive)

    manifest, database = _archive_contents(archive)
    damaged = tmp_path / "damaged.zip"
    damaged_bytes = bytearray(database)
    damaged_bytes[-1] ^= 0x01
    _write_archive(damaged, manifest, bytes(damaged_bytes))
    with pytest.raises(BackupValidationError):
        verify_backup(damaged)

    incompatible_manifest = dict(manifest)
    incompatible_manifest["operations_version"] = "999.0.0"
    incompatible = tmp_path / "incompatible.zip"
    _write_archive(incompatible, incompatible_manifest, database)
    with pytest.raises(BackupValidationError):
        verify_backup(incompatible)

    # Recompute the external archive digest after changing the internal
    # migration ledger: installed migration files, not the manifest, remain
    # the authority for compatibility.
    migration_path = tmp_path / "migration-tampered.sqlite3"
    migration_path.write_bytes(database)
    with sqlite3.connect(migration_path) as connection:
        connection.execute("UPDATE schema_migrations SET checksum = ?", ("0" * 64,))
    migration_bytes = migration_path.read_bytes()
    tampered_ledger_manifest = dict(manifest)
    tampered_ledger_manifest["database_sha256"] = hashlib.sha256(migration_bytes).hexdigest()
    tampered_ledger_manifest["database_size_bytes"] = len(migration_bytes)
    tampered_ledger = tmp_path / "tampered-ledger.zip"
    _write_archive(tampered_ledger, tampered_ledger_manifest, migration_bytes)
    with pytest.raises(BackupValidationError):
        verify_backup(tampered_ledger)


@pytest.mark.parametrize("suffix", [None, "-wal", "-shm", "-journal"])
def test_restore_refuses_existing_target_or_any_sidecar_without_modifying_it(tmp_path: Path, suffix: str | None) -> None:
    source = tmp_path / "source.sqlite3"
    _seed_database(source)
    archive = tmp_path / "backup.zip"
    create_backup(source, archive)
    target = tmp_path / "existing-target.sqlite3"
    path = target if suffix is None else Path(str(target) + suffix)
    sentinel = b"do not replace or delete"
    path.write_bytes(sentinel)

    with pytest.raises(BackupTargetError):
        restore_backup(archive, target)
    assert path.read_bytes() == sentinel
    if suffix is not None:
        assert not target.exists()


def test_locked_source_fails_with_bounded_time_and_cleans_staging_files(tmp_path: Path) -> None:
    source = tmp_path / "locked source.sqlite3"
    _seed_database(source)
    with sqlite3.connect(source, timeout=1, isolation_level=None) as setup:
        setup.execute("PRAGMA journal_mode=DELETE")
    lock = sqlite3.connect(source, timeout=0.05, isolation_level=None)
    lock.execute("BEGIN EXCLUSIVE")
    lock.execute("UPDATE sessions SET title = title WHERE session_id = (SELECT session_id FROM sessions LIMIT 1)")
    output = tmp_path / "should-not-publish.zip"
    started = time.monotonic()
    try:
        with pytest.raises(BackupTimeout):
            create_backup(source, output, timeout_seconds=0.25)
    finally:
        lock.execute("ROLLBACK")
        lock.close()
    assert time.monotonic() - started < 2.0
    assert not output.exists()
    assert not list(tmp_path.glob(".shared-ledger-*"))


def test_cli_has_documented_exit_codes_and_sanitized_diagnostics(tmp_path: Path) -> None:
    help_result = subprocess.run(
        [sys.executable, "-m", "agent.app.backup", "--help"],
        capture_output=True, text=True, check=False,
    )
    assert help_result.returncode == 0
    assert " ".join(help_result.stdout.split()).endswith(
        "Exit codes: 0 success; 2 usage; 3 source/target precondition; 4 corrupt or incompatible backup; "
        "5 timeout/locked database; 6 operational failure."
    )

    missing = tmp_path / "secret-looking access-token.sqlite3"
    failure = subprocess.run(
        [sys.executable, "-m", "agent.app.backup", "backup", "--source", str(missing), "--output", str(tmp_path / "x.zip")],
        capture_output=True, text=True, check=False,
    )
    assert failure.returncode == BackupSourceError.exit_code
    assert "secret-looking" not in failure.stderr
    assert "database source is unavailable" in failure.stderr


def test_archive_contains_no_sqlite_sidecar_entries(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    _seed_database(source)
    archive = tmp_path / "backup.zip"
    create_backup(source, archive)
    with zipfile.ZipFile(archive, "r") as contents:
        assert set(contents.namelist()) == {"manifest.json", "database.sqlite3"}
    assert set(_archive_contents(archive)[0]) == {
        "archive_format", "archive_format_version", "created_at", "database_entry", "database_sha256",
        "database_size_bytes", "execution_key_version", "migrations", "operations_version", "api_version",
        "schema_version", "semantic_version",
    }


def test_large_valid_database_uses_volume_tmp_for_verify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    volume = tmp_path / "persistent database volume"
    volume.mkdir()
    source = volume / "large source.sqlite3"
    archive = volume / "large backup.zip"
    target = volume / "large restored.sqlite3"
    verify_tmp = volume / ".p1-06-tmp"
    verify_tmp.mkdir()
    store = _store(source)
    store.close()

    # Leave a large freelist in a schema-valid SQLite file. This exercises a
    # >16 MiB database artifact without introducing extra app schema objects.
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE temporary_payload (payload BLOB)")
        connection.execute("INSERT INTO temporary_payload(payload) VALUES (zeroblob(?))", (18 * 1024 * 1024,))
        connection.execute("DROP TABLE temporary_payload")
    assert source.stat().st_size > 16 * 1024 * 1024

    monkeypatch.setattr(backup.tempfile, "tempdir", str(verify_tmp))
    info = create_backup(source, archive)
    assert info.size_bytes > 16 * 1024 * 1024
    assert verify_backup(archive).database_sha256 == info.database_sha256
    assert list(verify_tmp.iterdir()) == []
    restored = restore_backup(archive, target)
    assert target.stat().st_size > 16 * 1024 * 1024
    assert restored.database_sha256 == info.database_sha256
    recovered = _store(target)
    recovered.close()
