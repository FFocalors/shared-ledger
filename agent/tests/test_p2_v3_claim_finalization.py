from __future__ import annotations

"""Claim finalization: no planning exit may orphan a RUNNING Turn.

An auth-resume investigation found a Turn left in ``RUNNING`` with a held claim,
no terminal or paused event and no owner, after a recovered planning task ended
without persisting an outcome. The same shape was reachable whenever planning
returned without a classified result (the swallowed ``StateConflict`` /
``StoreNotFound`` path). These tests pin the invariant for both routes:

* planning raises ``asyncio.CancelledError`` (the observed cancellation), and
* planning returns without persisting anything.

In both cases the Turn must reach a durable state and release its claim instead
of staying RUNNING forever.
"""

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from test_p2_runtime import OWNER
from test_p2_v3_read_page_window import _client_app, _harness
from test_p2_v3_runtime_semantics import _events, _new_session, _submit


def _turn_row(components: Any, turn_id: uuid.UUID) -> dict[str, Any]:
    with components.store._connection() as connection:
        row = connection.execute(
            "SELECT state, step, claim_token FROM turns WHERE turn_id=?", (str(turn_id),),
        ).fetchone()
    assert row is not None
    return dict(row)


_DURABLE_STATES = {"WAIT_INPUT", "WAIT_CONFIRM", "COMPLETED", "FAILED", "CANCELLED"}


def _wait_durable(components: Any, turn_id: uuid.UUID, timeout: float = 30.0) -> dict[str, Any]:
    """Wait for the Turn to settle, then return its row.

    A pause is durable: WAIT_INPUT Turns are never re-claimed, so once the state
    settles it stays settled.
    """
    deadline = time.monotonic() + timeout
    row = _turn_row(components, turn_id)
    while time.monotonic() < deadline:
        row = _turn_row(components, turn_id)
        if row["state"] in _DURABLE_STATES:
            return row
        time.sleep(0.02)
    raise AssertionError(f"Turn never settled: {row}")


def _assert_durable_pause(components: Any, client: TestClient, turn_id: uuid.UUID) -> None:
    row = _wait_durable(components, turn_id)
    assert row["state"] == "WAIT_INPUT", row
    # The claim must not outlive the planning task that held it.
    assert row["claim_token"] is None, f"claim was not released: {row['claim_token']!r}"

    result = _events(client, turn_id)
    assert result["turn"]["state"] == "WAIT_INPUT"
    assert result["turn"]["wait_reason"] == "auth_required"
    types = [item["type"] for item in result["events"]]
    # A durable pause, not a silent disappearance: the client is told why.
    assert "message" not in types
    errors = [item for item in result["events"] if item["type"] == "error"]
    assert len(errors) == 1
    assert errors[0]["payload"]["code"] == "dependency_unavailable"


@pytest.mark.parametrize("route", ["cancelled", "silent"])
def test_planning_exit_without_an_outcome_never_orphans_the_turn(
    tmp_path: Path, monkeypatch: Any, route: str,
) -> None:
    components, _provider, database = _harness(tmp_path, monkeypatch, 3)
    runtime = components.runtime
    entered: list[uuid.UUID] = []

    if route == "cancelled":
        async def _planning(claimed: Any) -> None:
            entered.append(claimed.turn.record.turn.turn_id)
            raise asyncio.CancelledError()
    else:
        async def _planning(claimed: Any) -> None:
            entered.append(claimed.turn.record.turn.turn_id)
            return None

    monkeypatch.setattr(runtime, "_run_v3_planning", _planning, raising=False)
    app = _client_app(components, database)
    with TestClient(app) as client:
        session_id = _new_session(client)
        turn_id = _submit(client, session_id, "查询这个活动的消费", selected_activity=True)
        _assert_durable_pause(components, client, turn_id)

    assert entered == [turn_id], "the patched planning route did not run"
    assert OWNER is not None
