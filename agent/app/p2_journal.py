"""P2-only durable proof for stable, source-free error events.

The journal contains no bearer or response body. It is a separate SQLite file
and never opens or migrates the Agent Store database.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import contracts as c
from .store import EventDraft, TurnAggregate


class P2EventProofError(RuntimeError):
    """The proof journal cannot safely record or verify a P2 event."""


class P2ErrorProofJournal:
    """Bounded TTL proof rows keyed by exact durable event payload and Turn."""

    _ALLOWED_ERROR_FIELDS = frozenset({
        (c.ApiErrorCode.UNAUTHENTICATED, "P2 dependency unavailable: auth_rejected.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: auth_verifier_unavailable.", True),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: postgrest_timeout.", True),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: postgrest_unavailable.", True),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: postgrest_failure.", True),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: postgrest_rate_limited.", True),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: postgrest_response_too_large.", True),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: postgrest_budget_exceeded.", True),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: lmstudio_offline.", True),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: lmstudio_timeout.", True),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: lmstudio_busy.", True),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: lmstudio_failed.", True),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: internal_failure.", True),
        (c.ApiErrorCode.AGENT_DISABLED, "P2 agent planning is disabled.", False),
        (c.ApiErrorCode.RATE_LIMITED, "P2 planning generation budget reached.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 query incomplete: narrow the query and submit a new Turn.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 result reference capacity reached; submit a narrower new Turn.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 binding capacity reached; submit a narrower new Turn.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 activity changed during scope resolution. Submit a new Turn to refresh the query.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 read contains a refund or non-positive amount that v1 cannot safely represent.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 read contains a non-positive debt amount that v1 cannot safely represent.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 financial records changed. Submit a new Turn to refresh the query.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 activity scope could not be verified. No data was disclosed.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 capability unavailable: this query cannot be represented safely.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 result freshness binding is unavailable. Submit a new Turn to refresh the query.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 results contain conflicting activity versions. Submit a new Turn to refresh the query.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "当前 Turn 已绑定到不同活动范围。请从所需活动页面创建新 Turn 后重试。", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: internal_failure.", True),
    })

    def __init__(
        self,
        path: Path,
        *,
        max_entries: int = 4096,
        ttl_seconds: int = 7 * 24 * 60 * 60,
    ) -> None:
        if not isinstance(path, Path) or not path.is_absolute():
            raise ValueError("P2 journal path must be an absolute Path")
        if not 1 <= max_entries <= 65_536 or not 60 <= ttl_seconds <= 30 * 24 * 60 * 60:
            raise ValueError("P2 journal bounds are invalid")
        self._path = path
        self._max_entries = max_entries
        self._ttl = timedelta(seconds=ttl_seconds)
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    def start(self) -> None:
        with self._lock:
            if self._connection is not None:
                return
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                connection = sqlite3.connect(self._path, timeout=2, isolation_level=None)
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("PRAGMA synchronous = FULL")
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS p2_event_proofs (
                        owner_id TEXT NOT NULL,
                        turn_id TEXT NOT NULL,
                        event_sha256 TEXT NOT NULL,
                        generation INTEGER NOT NULL,
                        checkpoint_revision INTEGER NOT NULL,
                        resulting_state_revision INTEGER NOT NULL,
                        expires_at TEXT NOT NULL,
                        PRIMARY KEY (owner_id, turn_id, event_sha256)
                    )"""
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS p2_event_proofs_expiry ON p2_event_proofs(expires_at)"
                )
                self._connection = connection
            except (OSError, sqlite3.Error):
                raise P2EventProofError("P2 event proof journal is unavailable") from None

    def close(self) -> None:
        with self._lock:
            connection, self._connection = self._connection, None
            if connection is not None:
                try:
                    connection.close()
                except sqlite3.Error:
                    pass

    def record(
        self,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        event: EventDraft,
        *,
        generation: int,
        checkpoint_revision: int,
        resulting_state_revision: int,
        now: datetime | None = None,
    ) -> None:
        if (
            not isinstance(owner_user_id, uuid.UUID)
            or not isinstance(turn_id, uuid.UUID)
            or event.type != c.EventType.ERROR
            or event.simulation
            or (event.payload.code, event.payload.message, event.payload.retryable) not in self._ALLOWED_ERROR_FIELDS
            or not isinstance(generation, int) or generation < 1
            or not isinstance(checkpoint_revision, int) or checkpoint_revision < 1
            or not isinstance(resulting_state_revision, int) or resulting_state_revision < 1
        ):
            raise P2EventProofError("event is outside the closed P2 proof allowlist")
        instant = now or datetime.now(timezone.utc)
        expires = instant + self._ttl
        digest = self._draft_digest(event)
        with self._lock:
            connection = self._require_connection()
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("DELETE FROM p2_event_proofs WHERE expires_at <= ?", (_stamp(instant),))
                count = int(connection.execute("SELECT COUNT(*) FROM p2_event_proofs").fetchone()[0])
                exists = connection.execute(
                    "SELECT 1 FROM p2_event_proofs WHERE owner_id = ? AND turn_id = ? AND event_sha256 = ?",
                    (str(owner_user_id), str(turn_id), digest),
                ).fetchone()
                if exists is None and count >= self._max_entries:
                    raise P2EventProofError("P2 event proof capacity is full")
                connection.execute(
                    """INSERT OR REPLACE INTO p2_event_proofs (
                        owner_id, turn_id, event_sha256, generation,
                        checkpoint_revision, resulting_state_revision, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (str(owner_user_id), str(turn_id), digest, generation,
                     checkpoint_revision, resulting_state_revision, _stamp(expires)),
                )
                connection.execute("COMMIT")
            except P2EventProofError:
                connection.execute("ROLLBACK")
                raise
            except sqlite3.Error:
                try:
                    connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise P2EventProofError("P2 event proof journal write failed") from None

    def verifies(self, aggregate: TurnAggregate, event: c.AgentEvent, *, now: datetime | None = None) -> bool:
        if (
            event.type != c.EventType.ERROR or event.simulation
            or (event.payload.code, event.payload.message, event.payload.retryable) not in self._ALLOWED_ERROR_FIELDS
        ):
            return False
        instant = now or datetime.now(timezone.utc)
        digest = self._event_digest(event)
        with self._lock:
            connection = self._connection
            if connection is None:
                return False
            try:
                row = connection.execute(
                    """SELECT generation, checkpoint_revision, resulting_state_revision
                       FROM p2_event_proofs
                       WHERE owner_id = ? AND turn_id = ? AND event_sha256 = ? AND expires_at > ?""",
                    (str(aggregate.record.turn.owner_user_id), str(aggregate.record.turn.turn_id),
                     digest, _stamp(instant)),
                ).fetchone()
            except sqlite3.Error:
                return False
        if row is None:
            return False
        generation, checkpoint_revision, state_revision = map(int, row)
        current = aggregate.record.turn
        return (
            generation <= aggregate.checkpoint.generation
            and checkpoint_revision <= aggregate.checkpoint_revision
            and state_revision <= current.state_revision
        )

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise P2EventProofError("P2 event proof journal has not started")
        return self._connection

    @staticmethod
    def _draft_digest(event: EventDraft) -> str:
        payload = event.model_dump(mode="json", by_alias=True, exclude_none=False)
        return _digest(payload)

    @staticmethod
    def _event_digest(event: c.AgentEvent) -> str:
        payload = event.model_dump(mode="json", by_alias=True, exclude_none=False)
        payload.pop("seq", None)
        return _digest(payload)


def _digest(value: Any) -> str:
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _stamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("journal timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
