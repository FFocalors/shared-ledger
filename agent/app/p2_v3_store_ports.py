"""Request-local adapters from the v3 read protocol to durable Store ports.

These ports account physical work only. A settled wire capture is still
cost-only and cannot be projected as an accepted source fact.
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from . import p2_source_codec_v3 as codec
from .p2_source_store_v3 import P2V3StoreConflict, P2_V3_MAX_ACTIVE_US, P2_V3_MAX_BACKEND_US, P2_V3_MAX_GETS, P2_V3_MAX_GET_RESPONSE_BYTES, P2_V3_MAX_RESPONSE_BYTES


class P2V3StoreBudgetPort:
    """Durable budget adapter scoped to one claimed owner/Turn worker.

    It intentionally keeps only reservation IDs and their local binding in
    memory. Every reservation, dispatch marker, settlement, and wire capture
    is persisted through the existing SQLite Store. It does not accept source
    facts or turn cost-only captures into source proofs.
    """

    __slots__ = ("_store", "_owner", "_turn", "_claim_token", "_reservations")

    def __init__(self, store: Any, owner_user_id: uuid.UUID, turn_id: uuid.UUID, claim_token: str) -> None:
        if type(owner_user_id) is not uuid.UUID or type(turn_id) is not uuid.UUID:
            raise TypeError("Store budget port requires UUID owner and Turn")
        if type(claim_token) is not str or not claim_token:
            raise TypeError("Store budget port requires the active opaque claim token")
        self._store = store
        self._owner = owner_user_id
        self._turn = turn_id
        self._claim_token = claim_token
        self._reservations: dict[str, tuple[Any, str, str | None, str | None]] = {}

    def __repr__(self) -> str:
        return "<P2V3StoreBudgetPort>"

    def _assert_binding(self, binding: codec.SourceBinding) -> codec.V3ExecutionIdentity:
        if not isinstance(binding, (codec.AdmissionOnlyBinding, codec.QueryAttemptBinding)):
            raise P2V3StoreConflict("budget operation requires a typed v3 binding")
        identity = binding.identity
        if (
            identity.owner_user_id != self._owner or identity.turn_id != self._turn
            or binding.claim_token != self._claim_token
        ):
            raise P2V3StoreConflict("budget binding belongs to another owner, Turn or worker claim")
        return identity

    @staticmethod
    def _identity_matches(snapshot: Any, identity: codec.V3ExecutionIdentity) -> bool:
        return (
            snapshot.owner_user_id == str(identity.owner_user_id)
            and snapshot.turn_id == str(identity.turn_id)
            and snapshot.generation == identity.generation
            and snapshot.input_seq == identity.input_seq
            and snapshot.input_digest == identity.input_digest
            and snapshot.claim_epoch == identity.claim_epoch
            and snapshot.authority_epoch == identity.authority_epoch
            and snapshot.context_revision == identity.context_revision
        )

    def _current_snapshot(self, binding: codec.SourceBinding) -> Any:
        identity = self._assert_binding(binding)
        with self._store._connection() as connection:
            _, snapshot, _ = self._store._p2_v3_current_claim(
                connection, self._owner, self._turn, claim_token=self._claim_token,
                now=datetime.now(timezone.utc),
            )
            if not self._identity_matches(snapshot, identity):
                raise P2V3StoreConflict("budget binding is stale for the current Store claim")
            return snapshot

    @staticmethod
    def _chain(binding: codec.SourceBinding, capture_chain_id: str | None) -> tuple[str, str]:
        if isinstance(binding, codec.AdmissionOnlyBinding):
            if capture_chain_id is not None:
                raise P2V3StoreConflict("operation-free admission GET cannot invent a query capture chain")
            return "admission", binding.admission_id
        if capture_chain_id not in (None, binding.query_attempt_id):
            raise P2V3StoreConflict("query GET capture chain differs from its active private attempt")
        return "query_attempt", binding.query_attempt_id

    def remaining_limits(
        self,
        binding: codec.SourceBinding,
        *,
        logical_query_id: str | None = None,
        capture_chain_id: str | None = None,
        table: str | None = None,
    ) -> codec.RemainingBudget:
        snapshot = self._current_snapshot(binding)
        if isinstance(binding, codec.QueryAttemptBinding) and logical_query_id not in (None, binding.logical_query_id):
            raise P2V3StoreConflict("budget query differs from the bound logical query")
        if isinstance(binding, codec.AdmissionOnlyBinding) and logical_query_id is not None:
            raise P2V3StoreConflict("an admission-only budget cannot claim a logical read")
        over_active, over_backend, over_bytes = self._overruns()
        chain_pages = table_pages = 0
        if table is not None:
            if type(table) is not str:
                raise P2V3StoreConflict("capture-chain table is invalid")
            chain_kind, chain_id = self._chain(binding, capture_chain_id)
            charged_clause = """
                AND NOT EXISTS (
                    SELECT 1 FROM p2_v3_charge_events AS terminal
                    WHERE terminal.reservation_id=r.reservation_id
                      AND terminal.event_kind='known_no_dispatch'
                )
            """
            with self._store._connection() as connection:
                chain_pages = int(connection.execute(
                    """SELECT COUNT(*) FROM p2_v3_capture_chain_reservations AS r
                       JOIN p2_v3_charge_events AS reserved
                         ON reserved.reservation_id=r.reservation_id AND reserved.event_kind='reserved'
                       WHERE r.owner_user_id=? AND r.turn_id=? AND r.capture_chain_kind=? AND r.capture_chain_id=?""" + charged_clause,
                    (str(self._owner), str(self._turn), chain_kind, chain_id),
                ).fetchone()[0])
                table_pages = int(connection.execute(
                    """SELECT COUNT(*) FROM p2_v3_capture_chain_reservations AS r
                       JOIN p2_v3_charge_events AS reserved
                         ON reserved.reservation_id=r.reservation_id AND reserved.event_kind='reserved'
                       WHERE r.owner_user_id=? AND r.turn_id=? AND r.capture_chain_kind=? AND r.capture_chain_id=?
                         AND r.source_table=?""" + charged_clause,
                    (str(self._owner), str(self._turn), chain_kind, chain_id, table),
                ).fetchone()[0])
        return codec.RemainingBudget(
            active_us=max(0, P2_V3_MAX_ACTIVE_US - snapshot.active_used_us - snapshot.active_reserved_us - over_active),
            backend_us=max(0, P2_V3_MAX_BACKEND_US - snapshot.backend_used_us - snapshot.backend_reserved_us - over_backend),
            response_bytes=max(0, P2_V3_MAX_RESPONSE_BYTES - snapshot.response_bytes - snapshot.bytes_reserved - over_bytes),
            get_attempts=max(0, P2_V3_MAX_GETS - snapshot.get_attempts - snapshot.get_reserved),
            turn_remaining_us=max(0, P2_V3_MAX_ACTIVE_US - snapshot.active_used_us - snapshot.active_reserved_us - over_active),
            capture_chain_pages=chain_pages,
            capture_chain_table_pages=table_pages,
        )

    def _overruns(self) -> tuple[int, int, int]:
        with self._store._connection() as connection:
            return self._store._p2_v3_overrun_totals(connection, str(self._owner), str(self._turn))

    def reserve_get(
        self,
        binding: codec.SourceBinding,
        *,
        source_role: str,
        request_digest: str,
        active_limit_us: int,
        backend_limit_us: int,
        response_bytes_limit: int,
        logical_query_id: str | None = None,
        capture_chain_id: str | None = None,
        table: str | None = None,
    ) -> str:
        identity = self._assert_binding(binding)
        self._current_snapshot(binding)
        if type(table) is not str:
            raise P2V3StoreConflict("GET reservation requires a fixed source table")
        chain_kind, chain_id = self._chain(binding, capture_chain_id)
        if isinstance(binding, codec.AdmissionOnlyBinding):
            if logical_query_id is not None:
                raise P2V3StoreConflict("admission GET cannot spend a logical-read slot")
            admission_id = binding.admission_id
            query_id = attempt_id = None
            chain_query_id = chain_attempt_id = None
        else:
            if logical_query_id != binding.logical_query_id:
                raise P2V3StoreConflict("query GET does not match its logical query binding")
            admission_id = None
            query_id = binding.logical_query_id
            attempt_id = binding.query_attempt_id
            chain_query_id, chain_attempt_id = binding.logical_query_id, binding.query_attempt_id
        with self._store._connection() as connection:
            charged_clause = """
                AND NOT EXISTS (
                    SELECT 1 FROM p2_v3_charge_events AS terminal
                    WHERE terminal.reservation_id=r.reservation_id
                      AND terminal.event_kind='known_no_dispatch'
                )
            """
            ordinal = int(connection.execute(
                """SELECT COUNT(*) FROM p2_v3_capture_chain_reservations AS r
                   JOIN p2_v3_charge_events AS reserved
                     ON reserved.reservation_id=r.reservation_id AND reserved.event_kind='reserved'
                   WHERE r.owner_user_id=? AND r.turn_id=? AND r.capture_chain_kind=?
                     AND r.capture_chain_id=? AND r.source_table=?""" + charged_clause,
                (str(self._owner), str(self._turn), chain_kind, chain_id, table),
            ).fetchone()[0])
        reservation_id = self._store.reserve_p2_v3_stage(
            self._owner, self._turn, claim_token=self._claim_token,
            stage="backend_get", active_limit_us=active_limit_us,
            backend_limit_us=backend_limit_us, response_bytes_limit=response_bytes_limit,
            logical_query_id=query_id, query_attempt_id=attempt_id,
            admission_id=admission_id, source_role=source_role,
            source_table=table,
            capture_chain_logical_query_id=chain_query_id,
            capture_chain_attempt_id=chain_attempt_id,
            capture_chain_table_ordinal=ordinal, request_digest=request_digest,
        )
        self._reservations[reservation_id] = (binding, "backend_get", request_digest, table)
        return reservation_id

    def reserve_processing(
        self,
        binding: codec.SourceBinding,
        *,
        active_limit_us: int,
        backend_limit_us: int,
    ) -> str:
        self._assert_binding(binding)
        self._current_snapshot(binding)
        reservation_id = self._store.reserve_p2_v3_stage(
            self._owner, self._turn, claim_token=self._claim_token,
            stage="backend_processing", active_limit_us=active_limit_us,
            backend_limit_us=backend_limit_us,
        )
        self._reservations[reservation_id] = (binding, "backend_processing", None, None)
        try:
            self._mark_dispatch_started(binding, reservation_id, "backend_processing")
        except codec.P2V3DispatchStateUncertain:
            raise
        except BaseException as exc:
            if not isinstance(exc, Exception):
                # Control exceptions are never converted into a release or
                # an uncertain-state error. _mark_dispatch_started already
                # released a confirmed pre-marker cancellation; a started
                # marker stays reserved for recovery.
                raise
            try:
                self._settle(binding, reservation_id, "known_no_dispatch", 0, 0, 0, None, "backend_processing")
            except BaseException as settlement_exc:
                if not isinstance(settlement_exc, Exception):
                    raise
                raise codec.P2V3DispatchStateUncertain from exc
            raise
        return reservation_id

    def mark_dispatch_started(self, binding: codec.SourceBinding, reservation_id: str) -> None:
        self._mark_dispatch_started(binding, reservation_id, "backend_get")

    def _local_reservation(
        self, binding: codec.SourceBinding, reservation_id: str, expected_stage: str,
    ) -> tuple[str, str | None, str | None]:
        local = self._reservations.get(reservation_id)
        if local is None or local[0] != binding or local[1] != expected_stage:
            raise P2V3StoreConflict("reservation is not held by this request-local Store port")
        return local[1], local[2], local[3]

    def _charge_state(self, binding: codec.SourceBinding, reservation_id: str, stage: str) -> tuple[sqlite3.Row, sqlite3.Row | None, sqlite3.Row | None]:
        identity = self._assert_binding(binding)
        with self._store._connection() as connection:
            reserved = connection.execute(
                """SELECT * FROM p2_v3_charge_events WHERE reservation_id=? AND owner_user_id=?
                   AND turn_id=? AND event_kind='reserved'""",
                (reservation_id, str(self._owner), str(self._turn)),
            ).fetchone()
            if reserved is None or reserved["stage"] != stage:
                raise P2V3StoreConflict("reservation is not bound to the current request identity")
            if stage == "backend_processing":
                expected_query = expected_attempt = expected_admission = None
                if any(reserved[key] is not None for key in (
                    "logical_query_id", "query_attempt_id", "admission_id", "source_role", "request_digest",
                )):
                    raise P2V3StoreConflict("processing reservation unexpectedly carries source binding fields")
            elif stage == "backend_get":
                expected_query = binding.logical_query_id if isinstance(binding, codec.QueryAttemptBinding) else None
                expected_attempt = binding.query_attempt_id if isinstance(binding, codec.QueryAttemptBinding) else None
                expected_admission = binding.admission_id if isinstance(binding, codec.AdmissionOnlyBinding) else None
            else:
                raise P2V3StoreConflict("reservation stage is not supported by the v3 budget port")
            if (
                reserved["logical_query_id"] != expected_query
                or reserved["query_attempt_id"] != expected_attempt
                or reserved["admission_id"] != expected_admission
                or reserved["generation"] != identity.generation
                or reserved["claim_epoch"] != identity.claim_epoch
                or reserved["authority_epoch"] != identity.authority_epoch
                or reserved["context_revision"] != identity.context_revision
            ):
                raise P2V3StoreConflict("reservation fields differ from the bound query/admission epoch")
            if isinstance(binding, codec.AdmissionOnlyBinding):
                admission = connection.execute(
                    "SELECT * FROM p2_v3_source_admissions WHERE admission_id=? AND owner_user_id=? AND turn_id=?",
                    (binding.admission_id, str(self._owner), str(self._turn)),
                ).fetchone()
                if admission is None or (
                    admission["generation"] != identity.generation
                    or admission["input_seq"] != identity.input_seq
                    or admission["input_digest"] != identity.input_digest
                    or admission["claim_epoch"] != identity.claim_epoch
                    or admission["authority_epoch"] != identity.authority_epoch
                    or admission["context_revision"] != identity.context_revision
                ):
                    raise P2V3StoreConflict("admission reservation differs from its immutable input epoch")
            else:
                query = connection.execute(
                    "SELECT * FROM p2_v3_queries WHERE logical_query_id=? AND owner_user_id=? AND turn_id=?",
                    (binding.logical_query_id, str(self._owner), str(self._turn)),
                ).fetchone()
                attempt = connection.execute(
                    "SELECT * FROM p2_v3_query_attempts WHERE attempt_id=? AND logical_query_id=? AND owner_user_id=? AND turn_id=?",
                    (binding.query_attempt_id, binding.logical_query_id, str(self._owner), str(self._turn)),
                ).fetchone()
                if query is None or attempt is None or (
                    query["generation"] != identity.generation
                    or query["input_seq"] != identity.input_seq
                    or query["input_digest"] != identity.input_digest
                    or query["authority_epoch"] != identity.authority_epoch
                    or attempt["generation"] != identity.generation
                    or attempt["authority_epoch"] != identity.authority_epoch
                    or attempt["criteria_digest"] != query["criteria_digest"]
                    or attempt["scope_digest"] != query["scope_digest"]
                ):
                    raise P2V3StoreConflict("query reservation differs from its immutable descriptor/attempt")
            started = connection.execute(
                "SELECT * FROM p2_v3_charge_events WHERE reservation_id=? AND event_kind='dispatch_started'",
                (reservation_id,),
            ).fetchone()
            terminal = connection.execute(
                """SELECT * FROM p2_v3_charge_events WHERE reservation_id=?
                   AND event_kind IN ('settled','known_no_dispatch','unknown')""",
                (reservation_id,),
            ).fetchone()
            return reserved, started, terminal

    def _mark_dispatch_started(self, binding: codec.SourceBinding, reservation_id: str, stage: str) -> None:
        self._assert_binding(binding)
        self._local_reservation(binding, reservation_id, stage)
        try:
            self._store.mark_p2_v3_dispatch_started(
                self._owner, self._turn, reservation_id, claim_token=self._claim_token,
            )
            return
        except BaseException as original:
            try:
                reserved, started, terminal = self._charge_state(binding, reservation_id, stage)
            except BaseException:
                if not isinstance(original, Exception):
                    raise original
                raise codec.P2V3DispatchStateUncertain from None
            if terminal is None and started is not None:
                try:
                    self._current_snapshot(binding)
                except BaseException:
                    if not isinstance(original, Exception):
                        raise original
                    raise codec.P2V3DispatchStateUncertain from None
                if not isinstance(original, Exception):
                    raise original
                return
            if terminal is None and started is None:
                if not isinstance(original, Exception):
                    try:
                        self._settle(
                            binding, reservation_id, "known_no_dispatch", 0, 0, 0, None, stage,
                        )
                    except BaseException:
                        raise original
                raise original
            if not isinstance(original, Exception):
                raise original
            raise codec.P2V3DispatchStateUncertain from None

    def settle_get(
        self,
        binding: codec.SourceBinding,
        reservation_id: str,
        *,
        outcome: Literal["actual", "known_no_dispatch", "unknown"],
        actual_active_us: int,
        actual_backend_us: int,
        actual_response_bytes: int,
        raw_body_sha256: str | None,
    ) -> None:
        self._settle(
            binding, reservation_id, outcome, actual_active_us, actual_backend_us,
            actual_response_bytes, raw_body_sha256, "backend_get",
        )

    def settle_processing(
        self,
        binding: codec.SourceBinding,
        reservation_id: str,
        *,
        actual_active_us: int,
        actual_backend_us: int,
    ) -> None:
        self._settle(
            binding, reservation_id, "actual", actual_active_us,
            actual_backend_us, 0, None, "backend_processing",
        )

    def _settle(
        self,
        binding: codec.SourceBinding,
        reservation_id: str,
        outcome: str,
        actual_active_us: int,
        actual_backend_us: int,
        actual_response_bytes: int,
        raw_body_sha256: str | None,
        stage: str,
    ) -> None:
        self._assert_binding(binding)
        self._local_reservation(binding, reservation_id, stage)
        attempt = 0
        while attempt < 2:
            attempt += 1
            try:
                self._store.settle_p2_v3_stage(
                    self._owner, self._turn, reservation_id, outcome=outcome,
                    actual_active_us=actual_active_us, actual_backend_us=actual_backend_us,
                    actual_response_bytes=actual_response_bytes,
                    raw_body_sha256=raw_body_sha256,
                )
                return
            except BaseException as original:
                try:
                    reserved, started, terminal = self._charge_state(binding, reservation_id, stage)
                except BaseException:
                    if not isinstance(original, Exception):
                        raise original
                    raise codec.P2V3DispatchStateUncertain from None
                if terminal is not None:
                    if not isinstance(original, Exception):
                        raise original
                    if self._terminal_matches(
                        reserved, terminal, outcome=outcome,
                        actual_active_us=actual_active_us,
                        actual_backend_us=actual_backend_us,
                        actual_response_bytes=actual_response_bytes,
                        raw_body_sha256=raw_body_sha256,
                    ):
                        return
                    raise P2V3StoreConflict("reservation has a conflicting durable terminal settlement") from None
                if not isinstance(original, Exception):
                    # A cancelled/interrupted settlement is not retried. The
                    # persisted reservation remains conservative if no
                    # terminal row can be observed.
                    raise original
                if attempt >= 2 or started is None:
                    raise original
        raise P2V3StoreConflict("reservation settlement did not reach a durable terminal state")

    @staticmethod
    def _terminal_matches(
        reserved: sqlite3.Row,
        terminal: sqlite3.Row,
        *,
        outcome: str,
        actual_active_us: int,
        actual_backend_us: int,
        actual_response_bytes: int,
        raw_body_sha256: str | None,
    ) -> bool:
        active_limit = int(reserved["active_limit_us"])
        backend_limit = int(reserved["backend_limit_us"])
        bytes_limit = int(reserved["response_bytes_limit"])
        if outcome == "unknown":
            event_kind = "unknown"
            charged = (active_limit, backend_limit, bytes_limit)
            overrun = (
                max(0, actual_active_us - active_limit),
                max(0, actual_backend_us - backend_limit),
                max(0, actual_response_bytes - bytes_limit),
            )
            body_sha = None
        elif outcome == "known_no_dispatch":
            event_kind = "known_no_dispatch"
            charged = (min(actual_active_us, active_limit), 0, 0)
            overrun = (max(0, actual_active_us - active_limit), 0, 0)
            body_sha = None
        else:
            exceeded = (
                actual_active_us > active_limit or actual_backend_us > backend_limit
                or actual_response_bytes > bytes_limit
            )
            event_kind = "unknown" if exceeded else "settled"
            charged = (active_limit, backend_limit, bytes_limit) if exceeded else (
                actual_active_us, actual_backend_us, actual_response_bytes,
            )
            overrun = (
                max(0, actual_active_us - active_limit),
                max(0, actual_backend_us - backend_limit),
                max(0, actual_response_bytes - bytes_limit),
            )
            body_sha = None if exceeded else raw_body_sha256
        return (
            terminal["event_kind"] == event_kind
            and (terminal["actual_active_us"], terminal["actual_backend_us"], terminal["actual_response_bytes"]) == charged
            and (terminal["overrun_active_us"], terminal["overrun_backend_us"], terminal["overrun_response_bytes"]) == overrun
            and terminal["raw_body_sha256"] == body_sha
        )

    def record_cost_only_capture(
        self,
        binding: codec.SourceBinding,
        reservation_id: str,
        *,
        http_status: int,
        content_range: str | None,
        returned_count: int,
        response_bytes: int,
        raw_body_sha256: str,
        observed_at: datetime,
    ) -> str:
        self._assert_binding(binding)
        stage, request_digest, table = self._local_reservation(binding, reservation_id, "backend_get")
        assert stage == "backend_get" and request_digest is not None and table is not None
        attempt = 0
        while attempt < 2:
            attempt += 1
            try:
                return self._store.record_p2_v3_wire_capture_cost_only(
                    self._owner, self._turn, reservation_id,
                    http_status=http_status, content_range=content_range,
                    returned_count=returned_count, response_bytes=response_bytes,
                    raw_body_sha256=raw_body_sha256, observed_at=observed_at,
                )
            except BaseException as original:
                try:
                    capture_id = self._find_exact_capture(
                        binding, reservation_id, request_digest=request_digest,
                        http_status=http_status, content_range=content_range,
                        returned_count=returned_count, response_bytes=response_bytes,
                        raw_body_sha256=raw_body_sha256, observed_at=observed_at,
                    )
                except BaseException:
                    if not isinstance(original, Exception):
                        raise original
                    raise codec.P2V3DispatchStateUncertain from None
                if capture_id is not None:
                    if not isinstance(original, Exception):
                        raise original
                    return capture_id
                if not isinstance(original, Exception):
                    raise original
                if attempt >= 2:
                    raise original
        raise P2V3StoreConflict("wire capture did not reach one durable cost-only row")

    def _find_exact_capture(
        self,
        binding: codec.SourceBinding,
        reservation_id: str,
        *,
        request_digest: str,
        http_status: int,
        content_range: str | None,
        returned_count: int,
        response_bytes: int,
        raw_body_sha256: str,
        observed_at: datetime,
    ) -> str | None:
        self._assert_binding(binding)
        from .p2_source_store_v3 import _stamp

        with self._store._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM p2_v3_wire_captures WHERE reservation_id=? AND owner_user_id=? AND turn_id=?",
                (reservation_id, str(self._owner), str(self._turn)),
            ).fetchall()
            if not rows:
                return None
            if len(rows) != 1:
                raise P2V3StoreConflict("reservation has multiple durable wire captures")
            row = rows[0]
            local = self._reservations.get(reservation_id)
            expected_query = binding.logical_query_id if isinstance(binding, codec.QueryAttemptBinding) else None
            expected_attempt = binding.query_attempt_id if isinstance(binding, codec.QueryAttemptBinding) else None
            expected_admission = binding.admission_id if isinstance(binding, codec.AdmissionOnlyBinding) else None
            if (
                row["capture_state"] != "cost_only" or row["reservation_id"] != reservation_id
                or row["raw_body_sha256"] != raw_body_sha256 or row["http_status"] != http_status
                or row["content_range"] != content_range or row["returned_count"] != returned_count
                or row["response_bytes"] != response_bytes or row["observed_at"] != _stamp(observed_at)
                or row["request_digest"] != request_digest or row["source_role"] != _expected_role(local[3])
                or row["logical_query_id"] != expected_query or row["query_attempt_id"] != expected_attempt
                or row["admission_id"] != expected_admission
            ):
                raise P2V3StoreConflict("wire capture differs from the request-local reservation witness")
            return str(row["capture_id"])


def _expected_role(table: str | None) -> str | None:
    roles = {
        "activities": "activity", "activity_members": "membership", "participants": "participant",
        "ledger_units": "ledger_unit", "sub_activity_participants": "ledger_unit",
        "participant_claims": "actor", "expenses": "expense", "payments": "expense",
        "splits": "expense", "expense_debts": "debt", "prepayment_accounts": "prepayment_account",
        "prepayment_usages": "prepayment_usage", "transfers": "prepayment_return",
        "transfer_components": "prepayment_return",
    }
    return roles.get(table or "")
