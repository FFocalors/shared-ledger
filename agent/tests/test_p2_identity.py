from __future__ import annotations

from datetime import datetime, timedelta, timezone
import threading
import uuid

import pytest

from app.p2_identity import P2GrantError, P2TurnGrantStore
from app.ports import Principal


NOW = datetime(2026, 10, 11, 4, 0, tzinfo=timezone.utc)


def principal(user_id: uuid.UUID, expires_at: datetime | None = None) -> Principal:
    return Principal(user_id=user_id, expires_at=expires_at or NOW + timedelta(hours=1))


def test_grants_are_isolated_by_owner_and_turn_pair() -> None:
    owner_a, owner_b = uuid.uuid4(), uuid.uuid4()
    turn_a, turn_b = uuid.uuid4(), uuid.uuid4()
    store = P2TurnGrantStore()
    grant_a = store.bind(principal(owner_a), turn_a, "token-a", now=NOW)
    grant_b = store.bind(principal(owner_a), turn_b, "token-b", now=NOW)
    grant_c = store.bind(principal(owner_b), turn_a, "token-c", now=NOW)

    assert store.get(owner_a, turn_a, now=NOW) == grant_a
    assert store.get(owner_a, turn_a, now=NOW).token == "token-a"
    assert store.get(owner_a, turn_b, now=NOW) == grant_b
    assert store.get(owner_a, turn_b, now=NOW).token == "token-b"
    assert store.get(owner_b, turn_a, now=NOW) == grant_c
    assert store.get(owner_b, turn_a, now=NOW).token == "token-c"
    with pytest.raises(P2GrantError):
        store.get(owner_b, turn_b, now=NOW)


def test_binding_requires_a_nonexpired_verified_identity() -> None:
    store = P2TurnGrantStore()
    owner, turn = uuid.uuid4(), uuid.uuid4()

    with pytest.raises(P2GrantError):
        store.bind(principal(owner, NOW), turn, "expired-token", now=NOW)
    with pytest.raises(P2GrantError):
        store.bind(principal(owner, NOW - timedelta(seconds=1)), turn, "expired-token", now=NOW)


def test_auth_expiry_clamps_the_lease_and_long_auth_is_capped_at_300_seconds() -> None:
    owner, turn = uuid.uuid4(), uuid.uuid4()
    store = P2TurnGrantStore()
    short_expiry = NOW + timedelta(seconds=45)
    short = store.bind(principal(owner, short_expiry), turn, "short-token", now=NOW)
    assert short.expires_at == short_expiry

    long = store.bind(principal(owner), uuid.uuid4(), "long-token", now=NOW)
    assert long.expires_at == NOW + timedelta(seconds=300)
    assert long.max_expires_at == NOW + timedelta(seconds=300)


def test_get_expires_and_prunes_the_turn_grant() -> None:
    store = P2TurnGrantStore()
    owner, turn = uuid.uuid4(), uuid.uuid4()
    store.bind(principal(owner), turn, "token", now=NOW)

    with pytest.raises(P2GrantError):
        store.get(owner, turn, now=NOW + timedelta(seconds=300))
    assert len(store) == 0


def test_refresh_rejects_wrong_owner_and_does_not_keep_the_old_grant() -> None:
    store = P2TurnGrantStore()
    owner, other_owner, turn = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    store.bind(principal(owner), turn, "token", now=NOW)

    with pytest.raises(P2GrantError):
        store.refresh(owner, turn, principal(other_owner), now=NOW + timedelta(seconds=10))
    with pytest.raises(P2GrantError):
        store.get(owner, turn, now=NOW + timedelta(seconds=10))


def test_refresh_never_extends_beyond_the_original_300_second_horizon() -> None:
    store = P2TurnGrantStore()
    owner, turn = uuid.uuid4(), uuid.uuid4()
    original = store.bind(principal(owner), turn, "token", now=NOW)
    refreshed = store.refresh(
        owner,
        turn,
        principal(owner, NOW + timedelta(hours=2)),
        now=NOW + timedelta(seconds=120),
    )

    assert refreshed.issued_at == original.issued_at
    assert refreshed.max_expires_at == original.max_expires_at
    assert refreshed.expires_at <= original.max_expires_at
    assert refreshed.expires_at == original.expires_at


def test_revoke_and_clear_remove_terminal_turn_grants() -> None:
    store = P2TurnGrantStore()
    owner_a, owner_b = uuid.uuid4(), uuid.uuid4()
    turn_a, turn_b = uuid.uuid4(), uuid.uuid4()
    store.bind(principal(owner_a), turn_a, "token-a", now=NOW)
    store.bind(principal(owner_b), turn_b, "token-b", now=NOW)

    store.revoke(owner_a, turn_a)
    with pytest.raises(P2GrantError):
        store.get(owner_a, turn_a, now=NOW)
    assert len(store) == 1

    store.clear()
    assert len(store) == 0
    with pytest.raises(P2GrantError):
        store.get(owner_b, turn_b, now=NOW)


def test_token_is_not_exposed_in_grant_repr() -> None:
    store = P2TurnGrantStore()
    grant = store.bind(principal(uuid.uuid4()), uuid.uuid4(), "secret-bearer-token", now=NOW)

    assert "secret-bearer-token" not in repr(grant)
    assert "token=" not in repr(grant)


def test_concurrent_refresh_cannot_resurrect_a_revoked_or_replaced_grant() -> None:
    store = P2TurnGrantStore()
    owner, turn = uuid.uuid4(), uuid.uuid4()
    store.bind(principal(owner), turn, "old-token", now=NOW)
    original_get = store.get
    captured = threading.Event()
    continue_refresh = threading.Event()
    errors: list[BaseException] = []

    def paused_get(
        requested_owner: uuid.UUID,
        requested_turn: uuid.UUID,
        *,
        now: datetime | None = None,
    ):
        result = original_get(requested_owner, requested_turn, now=now)
        if threading.current_thread().name == "refresh-racer":
            captured.set()
            if not continue_refresh.wait(timeout=3):
                raise AssertionError("refresh test synchronization timed out")
        return result

    store.get = paused_get  # type: ignore[method-assign]

    def refresh() -> None:
        try:
            store.refresh(
                owner,
                turn,
                principal(owner, NOW + timedelta(hours=2)),
                now=NOW + timedelta(seconds=2),
            )
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=refresh, name="refresh-racer")
    thread.start()
    assert captured.wait(timeout=3)

    store.revoke(owner, turn)
    replacement = store.bind(principal(owner), turn, "replacement-token", now=NOW + timedelta(seconds=3))
    continue_refresh.set()
    thread.join(timeout=3)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], P2GrantError)
    assert store.get(owner, turn, now=NOW + timedelta(seconds=3)) == replacement
    assert store.get(owner, turn, now=NOW + timedelta(seconds=3)).token == "replacement-token"
