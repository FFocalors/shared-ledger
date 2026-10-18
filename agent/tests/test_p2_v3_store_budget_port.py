from __future__ import annotations

import asyncio
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest

from agent.app import p2_read_backend as backend
from test_p2_v3_admission_metadata_acceptance import (
    ACTIVITY,
    UNIT,
    _accepted_row_counts,
    _make_admission,
)


def _charge_counts(store: Any, turn_id: Any) -> tuple[int, int, int, int, int]:
    with store._connection() as connection:
        reserved = int(connection.execute(
            "SELECT COUNT(*) FROM p2_v3_charge_events WHERE turn_id=? AND event_kind='reserved' AND stage='backend_get'",
            (str(turn_id),),
        ).fetchone()[0])
        started = int(connection.execute(
            "SELECT COUNT(*) FROM p2_v3_charge_events WHERE turn_id=? AND event_kind='dispatch_started' AND stage='backend_get'",
            (str(turn_id),),
        ).fetchone()[0])
        settled = int(connection.execute(
            "SELECT COUNT(*) FROM p2_v3_charge_events WHERE turn_id=? AND event_kind='settled' AND stage='backend_get'",
            (str(turn_id),),
        ).fetchone()[0])
        released = int(connection.execute(
            "SELECT COUNT(*) FROM p2_v3_charge_events WHERE turn_id=? AND event_kind='known_no_dispatch' AND stage='backend_get'",
            (str(turn_id),),
        ).fetchone()[0])
        captures = int(connection.execute(
            "SELECT COUNT(*) FROM p2_v3_wire_captures WHERE turn_id=? AND capture_state='cost_only'",
            (str(turn_id),),
        ).fetchone()[0])
    return reserved, started, settled, released, captures


def _unknown_count(store: Any, turn_id: Any) -> int:
    with store._connection() as connection:
        return int(connection.execute(
            "SELECT COUNT(*) FROM p2_v3_charge_events WHERE turn_id=? AND event_kind='unknown' AND stage='backend_get'",
            (str(turn_id),),
        ).fetchone()[0])


def _processing_charge_counts(store: Any, turn_id: Any) -> tuple[int, int, int, int, int]:
    with store._connection() as connection:
        values = []
        for event_kind in ("reserved", "dispatch_started", "settled", "known_no_dispatch", "unknown"):
            values.append(int(connection.execute(
                "SELECT COUNT(*) FROM p2_v3_charge_events WHERE turn_id=? AND stage='backend_processing' AND event_kind=?",
                (str(turn_id), event_kind),
            ).fetchone()[0]))
    return tuple(values)  # type: ignore[return-value]


def test_store_port_confirms_marker_settlement_and_capture_after_commit_faults_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, turn_id, _, binding, registry, adapter, verified = _make_admission(tmp_path, monkeypatch)
    original_mark = store.mark_p2_v3_dispatch_started
    original_settle = store.settle_p2_v3_stage
    original_capture = store.record_p2_v3_wire_capture_cost_only
    faulted: set[str] = set()

    def mark_then_interrupt(owner: Any, turn: Any, reservation_id: str, **kwargs: Any) -> Any:
        result = original_mark(owner, turn, reservation_id, **kwargs)
        if "mark" not in faulted:
            faulted.add("mark")
            raise OSError("synthetic interruption after durable dispatch marker")
        return result

    def settle_then_interrupt(owner: Any, turn: Any, reservation_id: str, **kwargs: Any) -> Any:
        result = original_settle(owner, turn, reservation_id, **kwargs)
        if kwargs.get("outcome") == "actual":
            with store._connection() as connection:
                stage = connection.execute(
                    "SELECT stage FROM p2_v3_charge_events WHERE reservation_id=? AND event_kind='reserved'",
                    (reservation_id,),
                ).fetchone()["stage"]
            fault_key = f"settle_{stage}"
            if stage in {"backend_get", "backend_processing"} and fault_key not in faulted:
                faulted.add(fault_key)
                raise OSError(f"synthetic interruption after durable {stage} settlement")
        return result

    def capture_then_interrupt(owner: Any, turn: Any, reservation_id: str, **kwargs: Any) -> Any:
        result = original_capture(owner, turn, reservation_id, **kwargs)
        if "capture" not in faulted:
            faulted.add("capture")
            raise OSError("synthetic interruption after durable wire capture")
        return result

    monkeypatch.setattr(store, "mark_p2_v3_dispatch_started", mark_then_interrupt)
    monkeypatch.setattr(store, "settle_p2_v3_stage", settle_then_interrupt)
    monkeypatch.setattr(store, "record_p2_v3_wire_capture_cost_only", capture_then_interrupt)
    try:
        result = asyncio.run(adapter.admit_scope_v3(
            verified, binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
        ))
        assert result is not None
        assert faulted == {"mark", "settle_backend_get", "settle_backend_processing", "capture"}
        assert adapter._transport.calls == 6
        assert _charge_counts(store, turn_id) == (6, 6, 6, 0, 6)
        receipts, proofs, locators, captures = _accepted_row_counts(store, binding.admission_id)
        assert receipts == 6 and proofs >= 2 and locators >= 3 and captures == 6
        with store._connection() as connection:
            duplicate_terminals = int(connection.execute(
                """SELECT COUNT(*) FROM (
                     SELECT reservation_id,COUNT(*) AS n FROM p2_v3_charge_events
                     WHERE turn_id=? AND event_kind IN ('settled','known_no_dispatch','unknown')
                     GROUP BY reservation_id HAVING n<>1)""",
                (str(turn_id),),
            ).fetchone()[0])
        assert duplicate_terminals == 0
    finally:
        store.close()


def test_store_port_releases_only_a_confirmed_pre_dispatch_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, turn_id, _, binding, registry, adapter, verified = _make_admission(tmp_path, monkeypatch)
    original_mark = store.mark_p2_v3_dispatch_started
    failed = False

    def fail_before_marker(owner: Any, turn: Any, reservation_id: str, **kwargs: Any) -> Any:
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("synthetic failure before dispatch marker commit")
        return original_mark(owner, turn, reservation_id, **kwargs)

    monkeypatch.setattr(store, "mark_p2_v3_dispatch_started", fail_before_marker)
    try:
        with pytest.raises(backend.P2ReadBackendError):
            asyncio.run(adapter.admit_scope_v3(
                verified, binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
            ))
        assert failed is True and adapter._transport.calls == 0
        assert _charge_counts(store, turn_id) == (1, 0, 0, 1, 0)
        snapshot = store.get_p2_v3_snapshot(binding.identity.owner_user_id, turn_id)
        assert snapshot.get_attempts == 0 and snapshot.get_reserved == 0
        assert snapshot.active_reserved_us == 0 and snapshot.backend_reserved_us == 0
        assert snapshot.bytes_reserved == 0
        with pytest.raises(Exception):
            registry.require_metadata_accepted(identity=binding.identity, admission_id=binding.admission_id)
    finally:
        store.close()


def test_store_port_leaves_unclassifiable_started_marker_pending_without_get(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, turn_id, _, binding, registry, adapter, verified = _make_admission(tmp_path, monkeypatch)
    original_mark = store.mark_p2_v3_dispatch_started
    original_connection = store._connection

    @contextmanager
    def fail_connection_once() -> Iterator[sqlite3.Connection]:
        store._connection = original_connection
        raise OSError("synthetic inability to verify the persisted marker")
        yield  # pragma: no cover

    def commit_marker_then_make_verification_unavailable(owner: Any, turn: Any, reservation_id: str, **kwargs: Any) -> Any:
        result = original_mark(owner, turn, reservation_id, **kwargs)
        store._connection = fail_connection_once
        raise OSError("synthetic lost marker acknowledgement")

    monkeypatch.setattr(store, "mark_p2_v3_dispatch_started", commit_marker_then_make_verification_unavailable)
    try:
        with pytest.raises(backend.P2ReadBackendError):
            asyncio.run(adapter.admit_scope_v3(
                verified, binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
            ))
        store._connection = original_connection
        assert adapter._transport.calls == 0
        assert _charge_counts(store, turn_id) == (1, 1, 0, 0, 0)
        snapshot = store.get_p2_v3_snapshot(binding.identity.owner_user_id, turn_id)
        assert snapshot.get_attempts == 1 and snapshot.get_reserved == 0
        assert snapshot.active_reserved_us > 0 and snapshot.backend_reserved_us > 0
        with pytest.raises(Exception):
            registry.require_metadata_accepted(identity=binding.identity, admission_id=binding.admission_id)
    finally:
        store._connection = original_connection
        store.close()


def test_store_port_preserves_cancellation_after_confirmed_pre_dispatch_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, turn_id, _, binding, registry, adapter, verified = _make_admission(tmp_path, monkeypatch)

    def cancel_before_marker(owner: Any, turn: Any, reservation_id: str, **kwargs: Any) -> None:
        raise asyncio.CancelledError()

    monkeypatch.setattr(store, "mark_p2_v3_dispatch_started", cancel_before_marker)
    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(adapter.admit_scope_v3(
                verified, binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
            ))
        assert adapter._transport.calls == 0
        assert _charge_counts(store, turn_id) == (1, 0, 0, 1, 0)
        snapshot = store.get_p2_v3_snapshot(binding.identity.owner_user_id, turn_id)
        assert snapshot.get_attempts == 0 and snapshot.get_reserved == 0
        with pytest.raises(Exception):
            registry.require_metadata_accepted(identity=binding.identity, admission_id=binding.admission_id)
    finally:
        store.close()


def test_store_port_does_not_dispatch_after_marker_commit_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, turn_id, _, binding, registry, adapter, verified = _make_admission(tmp_path, monkeypatch)
    original_mark = store.mark_p2_v3_dispatch_started

    def mark_then_cancel(owner: Any, turn: Any, reservation_id: str, **kwargs: Any) -> Any:
        result = original_mark(owner, turn, reservation_id, **kwargs)
        raise asyncio.CancelledError()

    monkeypatch.setattr(store, "mark_p2_v3_dispatch_started", mark_then_cancel)
    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(adapter.admit_scope_v3(
                verified, binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
            ))
        assert adapter._transport.calls == 0
        assert _charge_counts(store, turn_id) == (1, 1, 0, 0, 0)
        assert _unknown_count(store, turn_id) == 0
        with pytest.raises(Exception):
            registry.require_metadata_accepted(identity=binding.identity, admission_id=binding.admission_id)
    finally:
        store.close()


def test_store_port_propagates_cancellation_after_get_settlement_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, turn_id, _, binding, registry, adapter, verified = _make_admission(tmp_path, monkeypatch)
    original_settle = store.settle_p2_v3_stage
    cancelled = False

    def settle_then_cancel(owner: Any, turn: Any, reservation_id: str, **kwargs: Any) -> Any:
        nonlocal cancelled
        result = original_settle(owner, turn, reservation_id, **kwargs)
        with store._connection() as connection:
            stage = connection.execute(
                "SELECT stage FROM p2_v3_charge_events WHERE reservation_id=? AND event_kind='reserved'",
                (reservation_id,),
            ).fetchone()["stage"]
        if stage == "backend_get" and kwargs.get("outcome") == "actual" and not cancelled:
            cancelled = True
            raise asyncio.CancelledError()
        return result

    monkeypatch.setattr(store, "settle_p2_v3_stage", settle_then_cancel)
    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(adapter.admit_scope_v3(
                verified, binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
            ))
        assert cancelled is True and adapter._transport.calls == 1
        assert _charge_counts(store, turn_id) == (1, 1, 1, 0, 0)
        with pytest.raises(Exception):
            registry.require_metadata_accepted(identity=binding.identity, admission_id=binding.admission_id)
    finally:
        store.close()


def test_store_port_propagates_cancellation_after_capture_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, turn_id, _, binding, registry, adapter, verified = _make_admission(tmp_path, monkeypatch)
    original_capture = store.record_p2_v3_wire_capture_cost_only

    def capture_then_cancel(owner: Any, turn: Any, reservation_id: str, **kwargs: Any) -> Any:
        result = original_capture(owner, turn, reservation_id, **kwargs)
        raise asyncio.CancelledError()

    monkeypatch.setattr(store, "record_p2_v3_wire_capture_cost_only", capture_then_cancel)
    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(adapter.admit_scope_v3(
                verified, binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
            ))
        assert adapter._transport.calls == 1
        assert _charge_counts(store, turn_id) == (1, 1, 1, 0, 1)
        with pytest.raises(Exception):
            registry.require_metadata_accepted(identity=binding.identity, admission_id=binding.admission_id)
    finally:
        store.close()


def test_transport_cancellation_is_charged_unknown_and_propagated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, turn_id, _, binding, registry, adapter, verified = _make_admission(tmp_path, monkeypatch)

    class CancelTransport:
        calls = 0

        def get(self, *_args: Any, **_kwargs: Any) -> Any:
            self.calls += 1
            raise asyncio.CancelledError()

    transport = CancelTransport()
    adapter._transport = transport
    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(adapter.admit_scope_v3(
                verified, binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
            ))
        assert transport.calls == 1
        assert _charge_counts(store, turn_id) == (1, 1, 0, 0, 0)
        assert _unknown_count(store, turn_id) == 1
        with pytest.raises(Exception):
            registry.require_metadata_accepted(identity=binding.identity, admission_id=binding.admission_id)
    finally:
        store.close()


def test_cpu_parse_cancellation_keeps_get_and_processing_cost_and_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, turn_id, _, binding, registry, adapter, verified = _make_admission(tmp_path, monkeypatch)
    original_cpu_stage = adapter._v3_cpu_stage

    async def cancel_in_cpu_stage(source_binding: Any, _function: Any) -> Any:
        def cancel() -> None:
            raise asyncio.CancelledError()
        return await original_cpu_stage(source_binding, cancel)

    monkeypatch.setattr(adapter, "_v3_cpu_stage", cancel_in_cpu_stage)
    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(adapter.admit_scope_v3(
                verified, binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
            ))
        assert adapter._transport.calls == 1
        assert _charge_counts(store, turn_id) == (1, 1, 1, 0, 1)
        with store._connection() as connection:
            processing = int(connection.execute(
                "SELECT COUNT(*) FROM p2_v3_charge_events WHERE turn_id=? AND event_kind='settled' AND stage='backend_processing'",
                (str(turn_id),),
            ).fetchone()[0])
        assert processing == 1
        with pytest.raises(Exception):
            registry.require_metadata_accepted(identity=binding.identity, admission_id=binding.admission_id)
    finally:
        store.close()


def test_processing_marker_after_commit_cancellation_does_not_release_or_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, turn_id, _, binding, registry, adapter, verified = _make_admission(tmp_path, monkeypatch)
    original_mark = store.mark_p2_v3_dispatch_started
    cancelled = False

    def mark_processing_then_cancel(owner: Any, turn: Any, reservation_id: str, **kwargs: Any) -> Any:
        nonlocal cancelled
        result = original_mark(owner, turn, reservation_id, **kwargs)
        with store._connection() as connection:
            row = connection.execute(
                "SELECT stage FROM p2_v3_charge_events WHERE reservation_id=? AND event_kind='reserved'",
                (reservation_id,),
            ).fetchone()
        if row["stage"] == "backend_processing" and not cancelled:
            cancelled = True
            raise asyncio.CancelledError()
        return result

    monkeypatch.setattr(store, "mark_p2_v3_dispatch_started", mark_processing_then_cancel)
    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(adapter.admit_scope_v3(
                verified, binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
            ))
        assert cancelled is True and adapter._transport.calls == 1
        assert _charge_counts(store, turn_id) == (1, 1, 1, 0, 1)
        assert _processing_charge_counts(store, turn_id) == (1, 1, 0, 0, 0)
        with pytest.raises(Exception):
            registry.require_metadata_accepted(identity=binding.identity, admission_id=binding.admission_id)
        assert _accepted_row_counts(store, binding.admission_id) == (0, 0, 0, 1)
    finally:
        store.close()


def test_settlement_control_exception_before_commit_is_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, turn_id, _, binding, registry, adapter, verified = _make_admission(tmp_path, monkeypatch)
    original_settle = store.settle_p2_v3_stage
    calls = 0

    def cancel_before_get_settlement(owner: Any, turn: Any, reservation_id: str, **kwargs: Any) -> Any:
        nonlocal calls
        with store._connection() as connection:
            row = connection.execute(
                "SELECT stage FROM p2_v3_charge_events WHERE reservation_id=? AND event_kind='reserved'",
                (reservation_id,),
            ).fetchone()
        if row["stage"] == "backend_get" and kwargs.get("outcome") == "actual":
            calls += 1
            raise asyncio.CancelledError()
        return original_settle(owner, turn, reservation_id, **kwargs)

    monkeypatch.setattr(store, "settle_p2_v3_stage", cancel_before_get_settlement)
    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(adapter.admit_scope_v3(
                verified, binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
            ))
        assert calls == 1 and adapter._transport.calls == 1
        assert _charge_counts(store, turn_id) == (1, 1, 0, 0, 0)
        with pytest.raises(Exception):
            registry.require_metadata_accepted(identity=binding.identity, admission_id=binding.admission_id)
        assert _accepted_row_counts(store, binding.admission_id) == (0, 0, 0, 0)
    finally:
        store.close()


def test_capture_control_exception_before_commit_is_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, turn_id, _, binding, registry, adapter, verified = _make_admission(tmp_path, monkeypatch)
    calls = 0

    def cancel_before_capture(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise asyncio.CancelledError()

    monkeypatch.setattr(store, "record_p2_v3_wire_capture_cost_only", cancel_before_capture)
    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(adapter.admit_scope_v3(
                verified, binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
            ))
        assert calls == 1 and adapter._transport.calls == 1
        assert _charge_counts(store, turn_id) == (1, 1, 1, 0, 0)
        with pytest.raises(Exception):
            registry.require_metadata_accepted(identity=binding.identity, admission_id=binding.admission_id)
        assert _accepted_row_counts(store, binding.admission_id) == (0, 0, 0, 0)
    finally:
        store.close()


def test_original_parse_cancellation_survives_settlement_and_capture_cleanup_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, turn_id, _, binding, registry, adapter, verified = _make_admission(tmp_path, monkeypatch)
    original_settle = store.settle_p2_v3_stage
    settle_failures = 0
    capture_failures = 0

    def fail_processing_cleanup(owner: Any, turn: Any, reservation_id: str, **kwargs: Any) -> Any:
        nonlocal settle_failures
        with store._connection() as connection:
            row = connection.execute(
                "SELECT stage FROM p2_v3_charge_events WHERE reservation_id=? AND event_kind='reserved'",
                (reservation_id,),
            ).fetchone()
        if row["stage"] == "backend_processing" and kwargs.get("outcome") == "actual":
            settle_failures += 1
            raise OSError("synthetic processing settlement unavailable")
        return original_settle(owner, turn, reservation_id, **kwargs)

    def fail_capture_cleanup(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal capture_failures
        capture_failures += 1
        raise OSError("synthetic cost capture unavailable")

    original_cpu_stage = adapter._v3_cpu_stage

    async def cancel_during_adapter_parse(source_binding: Any, _function: Any) -> Any:
        def cancel() -> None:
            raise asyncio.CancelledError()
        return await original_cpu_stage(source_binding, cancel)

    monkeypatch.setattr(store, "settle_p2_v3_stage", fail_processing_cleanup)
    monkeypatch.setattr(store, "record_p2_v3_wire_capture_cost_only", fail_capture_cleanup)
    monkeypatch.setattr(adapter, "_v3_cpu_stage", cancel_during_adapter_parse)
    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(adapter.admit_scope_v3(
                verified, binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
            ))
        # The Store port may make one bounded settlement retry after a normal
        # storage OSError. Both attempts fail; the original parser cancellation
        # must still escape and the reservation must remain pending.
        assert settle_failures == 2 and capture_failures == 2 and adapter._transport.calls == 1
        assert _charge_counts(store, turn_id) == (1, 1, 1, 0, 0)
        assert _processing_charge_counts(store, turn_id) == (1, 1, 0, 0, 0)
        with pytest.raises(Exception):
            registry.require_metadata_accepted(identity=binding.identity, admission_id=binding.admission_id)
        assert _accepted_row_counts(store, binding.admission_id) == (0, 0, 0, 0)
    finally:
        store.close()


def test_accounting_control_exception_is_not_swallowed_by_transport_error_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, turn_id, _, binding, registry, adapter, verified = _make_admission(tmp_path, monkeypatch)
    original_settle = store.settle_p2_v3_stage
    settlement_calls = 0

    class TimeoutTransport:
        calls = 0

        def get(self, *_args: Any, **_kwargs: Any) -> Any:
            self.calls += 1
            raise TimeoutError("synthetic upstream timeout")

    transport = TimeoutTransport()
    adapter._transport = transport

    def cancel_during_unknown_settlement(owner: Any, turn: Any, reservation_id: str, **kwargs: Any) -> Any:
        nonlocal settlement_calls
        with store._connection() as connection:
            row = connection.execute(
                "SELECT stage FROM p2_v3_charge_events WHERE reservation_id=? AND event_kind='reserved'",
                (reservation_id,),
            ).fetchone()
        if row["stage"] == "backend_get" and kwargs.get("outcome") == "unknown":
            settlement_calls += 1
            raise asyncio.CancelledError()
        return original_settle(owner, turn, reservation_id, **kwargs)

    monkeypatch.setattr(store, "settle_p2_v3_stage", cancel_during_unknown_settlement)
    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(adapter.admit_scope_v3(
                verified, binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
            ))
        assert transport.calls == 1 and settlement_calls == 1
        assert _charge_counts(store, turn_id) == (1, 1, 0, 0, 0)
        assert _unknown_count(store, turn_id) == 0
        with pytest.raises(Exception):
            registry.require_metadata_accepted(identity=binding.identity, admission_id=binding.admission_id)
        assert _accepted_row_counts(store, binding.admission_id) == (0, 0, 0, 0)
    finally:
        store.close()


def test_non_exception_control_from_parse_is_preserved_after_cost_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, turn_id, _, binding, registry, adapter, verified = _make_admission(tmp_path, monkeypatch)

    class SyntheticProcessControl(BaseException):
        pass

    original_cpu_stage = adapter._v3_cpu_stage

    async def raise_synthetic_control(source_binding: Any, _function: Any) -> Any:
        def raise_control() -> None:
            raise SyntheticProcessControl()
        return await original_cpu_stage(source_binding, raise_control)

    monkeypatch.setattr(adapter, "_v3_cpu_stage", raise_synthetic_control)
    try:
        with pytest.raises(SyntheticProcessControl):
            asyncio.run(adapter.admit_scope_v3(
                verified, binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
            ))
        assert adapter._transport.calls == 1
        assert _charge_counts(store, turn_id) == (1, 1, 1, 0, 1)
        assert _processing_charge_counts(store, turn_id) == (1, 1, 1, 0, 0)
        with pytest.raises(Exception):
            registry.require_metadata_accepted(identity=binding.identity, admission_id=binding.admission_id)
        assert _accepted_row_counts(store, binding.admission_id) == (0, 0, 0, 1)
    finally:
        store.close()
