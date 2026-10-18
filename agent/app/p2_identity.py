"""P2-only, per-Turn in-memory bearer leases.

The module deliberately exposes no serialization or persistence surface. A lease
is created only after the API AuthVerifier has validated the request token.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import threading
import uuid

from .ports import Principal


@dataclass(frozen=True, slots=True)
class P2TurnGrant:
    owner_user_id: uuid.UUID
    turn_id: uuid.UUID
    issued_at: datetime
    expires_at: datetime
    max_expires_at: datetime
    token: str = field(repr=False, compare=True)


class P2GrantError(ValueError):
    """A Turn grant is missing, expired, or does not match its owner."""


class P2TurnGrantStore:
    """Bounded memory-only leases keyed by the exact (owner, Turn) pair."""

    def __init__(self, *, max_entries: int = 1024, lease_seconds: int = 300) -> None:
        if not isinstance(max_entries, int) or max_entries < 1:
            raise ValueError("max_entries must be a positive integer")
        if not isinstance(lease_seconds, int) or not 30 <= lease_seconds <= 300:
            raise ValueError("lease_seconds must be between 30 and 300")
        self._max_entries = max_entries
        self._max_lease = timedelta(seconds=lease_seconds)
        self._lock = threading.RLock()
        self._grants: dict[tuple[uuid.UUID, uuid.UUID], P2TurnGrant] = {}

    def bind(
        self,
        principal: Principal,
        turn_id: uuid.UUID,
        access_token: str,
        *,
        replace: bool = False,
        existing_only: bool = False,
        now: datetime | None = None,
    ) -> P2TurnGrant:
        instant = now or datetime.now(timezone.utc)
        expiry = principal.expires_at
        if (
            not isinstance(principal.user_id, uuid.UUID)
            or not isinstance(turn_id, uuid.UUID)
            or not isinstance(access_token, str)
            or not access_token
            or len(access_token) > 16_384
            or any(ord(char) < 32 or ord(char) == 127 for char in access_token)
            or expiry is None
            or expiry.tzinfo is None
            or expiry.utcoffset() is None
            or instant.tzinfo is None
            or instant.utcoffset() is None
            or expiry <= instant
        ):
            raise P2GrantError("a fresh verified Turn grant is required")
        key = (principal.user_id, turn_id)
        grant = P2TurnGrant(
            owner_user_id=principal.user_id,
            turn_id=turn_id,
            issued_at=instant.astimezone(timezone.utc),
            expires_at=min(expiry.astimezone(timezone.utc), instant.astimezone(timezone.utc) + self._max_lease),
            max_expires_at=instant.astimezone(timezone.utc) + self._max_lease,
            token=access_token,
        )
        with self._lock:
            self._prune_locked(instant)
            current = self._grants.get(key)
            if current is not None and not replace:
                # Idempotent submit receipt retries must not extend a lease or
                # silently swap credentials. A new accepted resume/input action
                # opts into replacement explicitly at the API boundary.
                if current.token != access_token:
                    raise P2GrantError("an active Turn grant cannot be replaced by a replay")
                return current
            if current is None and existing_only:
                raise P2GrantError("the original Turn grant is no longer active")
            if key not in self._grants and len(self._grants) >= self._max_entries:
                raise P2GrantError("Turn grant capacity is full")
            self._grants[key] = grant
        return grant

    def get(
        self,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        *,
        now: datetime | None = None,
    ) -> P2TurnGrant:
        instant = now or datetime.now(timezone.utc)
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise P2GrantError("a timezone-aware clock is required")
        key = (owner_user_id, turn_id)
        with self._lock:
            grant = self._grants.get(key)
            if grant is not None and grant.expires_at <= instant:
                self._grants.pop(key, None)
                grant = None
        if grant is None or grant.owner_user_id != owner_user_id or grant.turn_id != turn_id:
            raise P2GrantError("no active grant is bound to this Turn")
        return grant

    def refresh(
        self,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        verified: Principal,
        *,
        now: datetime | None = None,
    ) -> P2TurnGrant:
        current = self.get(owner_user_id, turn_id, now=now)
        instant = now or datetime.now(timezone.utc)
        expiry = verified.expires_at
        if (
            verified.user_id != owner_user_id
            or expiry is None
            or expiry.tzinfo is None
            or expiry.utcoffset() is None
            or expiry <= instant
        ):
            self.revoke(owner_user_id, turn_id)
            raise P2GrantError("verified identity does not match this Turn")
        renewed = P2TurnGrant(
            owner_user_id=owner_user_id,
            turn_id=turn_id,
            issued_at=current.issued_at,
            expires_at=min(expiry.astimezone(timezone.utc), current.max_expires_at),
            max_expires_at=current.max_expires_at,
            token=current.token,
        )
        key = (owner_user_id, turn_id)
        with self._lock:
            if self._grants.get(key) != current:
                raise P2GrantError("Turn grant changed during verification")
            self._grants[key] = renewed
        return renewed

    def revoke(self, owner_user_id: uuid.UUID, turn_id: uuid.UUID) -> None:
        with self._lock:
            self._grants.pop((owner_user_id, turn_id), None)

    def clear(self) -> None:
        with self._lock:
            self._grants.clear()

    def prune_expired(self, *, now: datetime | None = None) -> None:
        instant = now or datetime.now(timezone.utc)
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise P2GrantError("a timezone-aware clock is required")
        with self._lock:
            self._prune_locked(instant)

    def _prune_locked(self, now: datetime) -> None:
        expired = [key for key, grant in self._grants.items() if grant.expires_at <= now]
        for key in expired:
            self._grants.pop(key, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._grants)

