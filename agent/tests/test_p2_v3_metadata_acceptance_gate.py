from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from agent.app import p2_source_store_v3 as source_store
from agent.app import p2_read_backend as backend
from agent.app.p2_source_store_v3 import (
    P2V3StoreConflict,
    P2_V3_METADATA_ACCEPTANCE_CAP_US,
)
from agent.app.store import SQLiteAgentStore
from test_p2_v3_admission_metadata_acceptance import (
    _configured_store,
    _make_admission,
    ACTIVITY,
    OWNER,
    UNIT,
)


def _events(store: SQLiteAgentStore, turn_id: Any) -> list[dict[str, Any]]:
    with store._connection() as connection:
        return [dict(row) for row in connection.execute(
            """SELECT e.* FROM p2_v3_metadata_acceptance_events e
               JOIN p2_v3_metadata_acceptance_batches b USING(acceptance_id)
               WHERE b.turn_id=? ORDER BY e.event_seq""",
            (str(turn_id),),
        ).fetchall()]


def _batches(store: SQLiteAgentStore, turn_id: Any) -> list[dict[str, Any]]:
    with store._connection() as connection:
        return [dict(row) for row in connection.execute(
            "SELECT * FROM p2_v3_metadata_acceptance_batches WHERE turn_id=? ORDER BY created_at,acceptance_id",
            (str(turn_id),),
        ).fetchall()]


def _charge_events(store: SQLiteAgentStore, turn_id: Any) -> list[dict[str, Any]]:
    with store._connection() as connection:
        return [dict(row) for row in connection.execute(
            """SELECT * FROM p2_v3_charge_events WHERE turn_id=? AND stage='backend_processing'
                 AND active_limit_us=? AND backend_limit_us=?
               ORDER BY occurred_at,event_id""",
            (str(turn_id), P2_V3_METADATA_ACCEPTANCE_CAP_US, P2_V3_METADATA_ACCEPTANCE_CAP_US),
        ).fetchall()]


def _fail_once(store: SQLiteAgentStore, target: str) -> None:
    fired = False

    def inject(name: str) -> None:
        nonlocal fired
        if name == target and not fired:
            fired = True
            raise RuntimeError("synthetic metadata gate fault")

    store._fault_injector = inject


def _admit(admission: Any, adapter: backend.P2ReadBackendAdapter, verified: Any) -> Any:
    return asyncio.run(adapter.admit_scope_v3(
        verified, admission, ui_activity_id_hint=ACTIVITY,
        ui_ledger_unit_id_hint=UNIT,
    ))


def test_a_b_c_commit_produces_one_cap_charge_then_allows_later_get_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, turn_id, claim, binding, registry, adapter, verified = _make_admission(tmp_path, monkeypatch)
    try:
        projection = _admit(binding, adapter, verified)
        assert projection is not None
        registry.require_metadata_accepted(identity=binding.identity, admission_id=binding.admission_id)

        batches = _batches(store, turn_id)
        assert len(batches) == 1
        acceptance_id = batches[0]["acceptance_id"]
        with store._connection() as connection:
            rows = [dict(row) for row in connection.execute(
                "SELECT * FROM p2_v3_metadata_acceptance_events WHERE acceptance_id=? ORDER BY event_seq",
                (acceptance_id,),
            ).fetchall()]
        assert [row["event_kind"] for row in rows] == [
            "proof_committed", "finalized", "postcommit_observation",
        ]
        assert rows[-1]["observation_outcome"] == "within_cap"
        charges = _charge_events(store, turn_id)
        terminals = [row for row in charges if row["event_kind"] in {"settled", "unknown", "known_no_dispatch"}]
        assert len(terminals) == 1 and terminals[0]["event_kind"] == "settled"
        assert terminals[0]["actual_active_us"] == P2_V3_METADATA_ACCEPTANCE_CAP_US
        assert terminals[0]["actual_backend_us"] == P2_V3_METADATA_ACCEPTANCE_CAP_US

        # A later source GET still has budget. It is reserved under the same
        # admission but intentionally known-no-dispatch, so it creates no proof.
        reservation = store.reserve_p2_v3_stage(
            OWNER,
            turn_id, claim_token=claim, stage="backend_get",
            active_limit_us=10_000, backend_limit_us=10_000,
            response_bytes_limit=1024, admission_id=binding.admission_id,
            source_role="activity", source_table="activities",
            request_digest=__import__("hashlib").sha256(b"later-get-plan").hexdigest(),
        )
        store.settle_p2_v3_stage(
            OWNER,
            turn_id, reservation, outcome="known_no_dispatch",
            actual_active_us=0, actual_backend_us=0, actual_response_bytes=0,
        )
    finally:
        store.close()


@pytest.mark.parametrize(
    ("fault_point", "expected_kinds", "expected_observations"),
    [
        ("p2_v3.metadata_acceptance.a.after_commit", ["proof_committed", "unknown"], []),
        ("p2_v3.metadata_acceptance.b.after_commit", ["proof_committed", "finalized", "postcommit_observation"], ["unknown"]),
        ("p2_v3.metadata_acceptance.c.after_commit", ["proof_committed", "finalized", "postcommit_observation", "postcommit_observation"], ["within_cap", "unknown"]),
    ],
)
def test_after_commit_fault_never_returns_or_restores_a_publication_permit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    fault_point: str, expected_kinds: list[str], expected_observations: list[str],
) -> None:
    store, turn_id, _, binding, registry, adapter, verified = _make_admission(tmp_path, monkeypatch)
    _fail_once(store, fault_point)
    try:
        with pytest.raises(backend.P2ReadBackendError):
            _admit(binding, adapter, verified)
        with pytest.raises(P2V3StoreConflict):
            registry.require_metadata_accepted(identity=binding.identity, admission_id=binding.admission_id)
        events = _events(store, turn_id)
        assert [row["event_kind"] for row in events] == expected_kinds
        assert [row["observation_outcome"] for row in events if row["event_kind"] == "postcommit_observation"] == expected_observations
        terminal = [row for row in _charge_events(store, turn_id) if row["event_kind"] in {"settled", "unknown"}]
        assert len(terminal) == 1
        assert terminal[0]["actual_active_us"] == P2_V3_METADATA_ACCEPTANCE_CAP_US
        assert terminal[0]["actual_backend_us"] == P2_V3_METADATA_ACCEPTANCE_CAP_US
    finally:
        store.close()


def test_committed_dispatch_marker_followed_by_exception_is_unknown_not_released(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, turn_id, _, binding, registry, adapter, verified = _make_admission(tmp_path, monkeypatch)
    original = store.mark_p2_v3_dispatch_started

    def marker_then_raise(*args: Any, **kwargs: Any) -> None:
        original(*args, **kwargs)
        raise RuntimeError("synthetic exception after dispatch marker COMMIT")

    store.mark_p2_v3_dispatch_started = marker_then_raise
    try:
        with pytest.raises(backend.P2ReadBackendError):
            _admit(binding, adapter, verified)
        with pytest.raises(P2V3StoreConflict):
            registry.require_metadata_accepted(identity=binding.identity, admission_id=binding.admission_id)
        assert _batches(store, turn_id) == []
        charges = _charge_events(store, turn_id)
        assert [row["event_kind"] for row in charges].count("dispatch_started") == 1
        assert [row["event_kind"] for row in charges].count("unknown") == 1
        assert not any(row["event_kind"] == "known_no_dispatch" for row in charges)
        assert charges[-1]["actual_active_us"] == P2_V3_METADATA_ACCEPTANCE_CAP_US
        assert charges[-1]["actual_backend_us"] == P2_V3_METADATA_ACCEPTANCE_CAP_US
    finally:
        store.close()


def test_postclaim_recheck_time_is_inside_cap_and_late_overrun_is_irreversible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, turn_id, _, binding, registry, adapter, verified = _make_admission(tmp_path, monkeypatch)
    original_check = store._p2_v3_metadata_claim_is_current

    class ControlledMonotonic:
        value = 5_000_000_000

        def __call__(self) -> int:
            return self.value

        def advance_us(self, amount: int) -> None:
            self.value += amount * 1000

    clock = ControlledMonotonic()
    monkeypatch.setattr(source_store.time, "monotonic_ns", clock)

    def slow_claim_check(*args: Any, **kwargs: Any) -> bool:
        valid = original_check(*args, **kwargs)
        clock.advance_us(P2_V3_METADATA_ACCEPTANCE_CAP_US + 1)
        return valid

    store._p2_v3_metadata_claim_is_current = slow_claim_check
    try:
        with pytest.raises(backend.P2ReadBackendError):
            _admit(binding, adapter, verified)
        with pytest.raises(P2V3StoreConflict):
            registry.require_metadata_accepted(identity=binding.identity, admission_id=binding.admission_id)
        events = _events(store, turn_id)
        assert [row["event_kind"] for row in events] == [
            "proof_committed", "finalized", "postcommit_observation", "postcommit_observation",
        ]
        assert [row["observation_outcome"] for row in events if row["event_kind"] == "postcommit_observation"] == [
            "within_cap", "overrun",
        ]
        acceptance_id = _batches(store, turn_id)[0]["acceptance_id"]
        with store._connection() as connection:
            overrun = store._p2_v3_overrun_totals(
                connection, str(binding.identity.owner_user_id), str(turn_id),
            )
        assert overrun[0] == 1 and overrun[1] == 1
        with store._connection() as connection:
            charged = connection.execute(
                "SELECT actual_active_us,actual_backend_us FROM p2_v3_charge_events WHERE reservation_id=(SELECT processing_reservation_id FROM p2_v3_metadata_acceptance_batches WHERE acceptance_id=?) AND event_kind='settled'",
                (acceptance_id,),
            ).fetchone()
        assert tuple(charged) == (P2_V3_METADATA_ACCEPTANCE_CAP_US, P2_V3_METADATA_ACCEPTANCE_CAP_US)
    finally:
        store.close()


def test_v4_database_upgrades_append_only_to_v5_without_rewriting_old_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("P2_V3_STORE_TEST_ROOT", str(tmp_path))
    database = tmp_path / "v4-upgrade.sqlite3"
    bootstrap = _configured_store(database)
    connection = sqlite3.connect(database, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        for migration in bootstrap._migrations[:4]:
            bootstrap._apply_migration(connection, migration)
            connection.execute(
                "INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES (?,?,?,?)",
                (migration.version, migration.name, migration.checksum, "2026-10-15T00:00:00+00:00"),
            )
            connection.execute(f"PRAGMA user_version={migration.version}")
        connection.execute("COMMIT")
        before = tuple(tuple(row) for row in connection.execute(
            "SELECT version,name,checksum,applied_at FROM schema_migrations ORDER BY version"
        ))
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()
        bootstrap.close()

    store = _configured_store(database)
    try:
        store.start()
        with store._connection() as connection:
            # Starting from a v4 bootstrap, the store applies every later
            # migration; rows 1-4 must be preserved exactly (asserted below).
            assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
            after = tuple(tuple(row) for row in connection.execute(
                "SELECT version,name,checksum,applied_at FROM schema_migrations WHERE version<=4 ORDER BY version"
            ))
            assert after == before
            assert connection.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE version=5 AND name='p2_v3_metadata_acceptance'"
            ).fetchone()[0] == 1
            for table in (
                "p2_v3_metadata_acceptance_batches", "p2_v3_metadata_acceptance_proofs",
                "p2_v3_metadata_acceptance_events", "p2_v3_output_metadata_acceptances",
            ):
                assert connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,),
                ).fetchone() is not None
    finally:
        store.close()
