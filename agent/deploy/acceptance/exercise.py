"""HTTP-only, redacted P1-06 container restart exercise.

Run ``before-restart`` against the fixture container, preserve its one-line JSON,
recreate the container or restore the DB volume, then run ``after-restart`` with the
captured JSON. This helper does not inspect or alter the database directly except for
the explicit read-only ``scan-database`` mode.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import ProxyHandler, Request, build_opener
import uuid


FIXTURE = "p1-06-container-acceptance-v1"
OWNER_A_TOKEN = "fixture-owner-a-v1"
OWNER_B_TOKEN = "fixture-owner-b-v1"
OWNER_A_ONE_SHOT_TOKEN = "fixture-owner-a-once-v1"
REFRESH_SENTINEL = "fixture-refresh-sentinel-never-submitted"
NONCE_SENTINEL = "N" * 32
DIGEST_SENTINEL = "a" * 64
HOLD_PROMPT = "P1-06 restart auth hold"
_OPENER = build_opener(ProxyHandler({}))


class ExerciseFailure(RuntimeError):
    def __init__(self, code: str, status: int | None = None) -> None:
        self.code = code
        self.status = status
        super().__init__(code)


def _require(condition: bool, code: str, status: int | None = None) -> None:
    if not condition:
        raise ExerciseFailure(code, status)


def _base_url() -> str:
    raw = os.environ.get("P1_06_BASE_URL", "http://127.0.0.1:8765")
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname or ""
        loopback = host.lower() == "localhost"
        try:
            import ipaddress
            loopback = loopback or ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass
        _ = parsed.port
    except ValueError:
        raise ExerciseFailure("base_url_invalid") from None
    _require(
        parsed.scheme in ("http", "https") and loopback and parsed.path in ("", "/")
        and parsed.username is None and parsed.password is None
        and not parsed.query and not parsed.fragment,
        "base_url_invalid",
    )
    return raw.rstrip("/")


def _request(
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 4.0,
) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json"}
    data = None
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = Request(_base_url() + path, data=data, headers=headers, method=method)
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            status = int(response.status)
            raw = response.read(262_145)
    except HTTPError as exc:
        status = int(exc.code)
        try:
            raw = exc.read(262_145)
        except Exception:
            raw = b""
        try:
            exc.close()
        except Exception:
            pass
    except (URLError, TimeoutError, OSError, ValueError):
        raise ExerciseFailure("http_transport_failed") from None
    if len(raw) > 262_144:
        raise ExerciseFailure("http_response_oversized", status)
    try:
        parsed = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeError, ValueError, json.JSONDecodeError):
        parsed = {}
    return status, parsed if isinstance(parsed, dict) else {}


def _expect_status(result: tuple[int, dict[str, Any]], expected: int, code: str) -> dict[str, Any]:
    status, payload = result
    _require(status == expected, code, status)
    return payload


def _new_id() -> str:
    return str(uuid.uuid4())


def _wait_ready(timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status, _ = _request("GET", "/health/ready", timeout=2.0)
            if status == 200:
                return
        except ExerciseFailure:
            pass
        time.sleep(0.15)
    raise ExerciseFailure("service_not_ready")


def _all_events(turn_id: str, token: str = OWNER_A_TOKEN) -> dict[str, Any]:
    collected: list[dict[str, Any]] = []
    cursor = 0
    final: dict[str, Any] = {}
    for _ in range(10):
        query = urlencode({"after_seq": cursor, "limit": 100})
        response = _expect_status(
            _request("GET", f"/v1/turns/{turn_id}/events?{query}", token=token),
            200,
            "events_unavailable",
        )
        events = response.get("events")
        _require(isinstance(events, list), "events_malformed")
        collected.extend(item for item in events if isinstance(item, dict))
        final = response
        if not response.get("has_more"):
            final["events"] = collected
            return final
        next_cursor = response.get("next_after_seq")
        _require(isinstance(next_cursor, int) and next_cursor > cursor, "events_cursor_invalid")
        cursor = next_cursor
    raise ExerciseFailure("events_page_limit")


def _projection(view: dict[str, Any]) -> dict[str, Any]:
    projected: list[dict[str, Any]] = []
    states: list[str] = []
    counts: Counter[str] = Counter()
    for event in view.get("events", []):
        kind = event.get("type")
        seq = event.get("seq")
        _require(isinstance(kind, str) and isinstance(seq, int), "event_projection_invalid")
        item: dict[str, Any] = {"seq": seq, "type": kind}
        counts[kind] += 1
        if kind == "status":
            payload = event.get("payload", {})
            state = payload.get("state")
            item.update({
                "state": state,
                "step": payload.get("step"),
                "state_revision": payload.get("state_revision"),
                "wait_reason": payload.get("wait_reason"),
                "resume_state": payload.get("resume_state"),
            })
            if isinstance(state, str) and (not states or states[-1] != state):
                states.append(state)
        projected.append(item)
    return {
        "state": view.get("turn", {}).get("state"),
        "wait_reason": view.get("turn", {}).get("wait_reason"),
        "resume_state": view.get("turn", {}).get("resume_state"),
        "eventseq": [item["seq"] for item in projected],
        "events": projected,
        "states": states,
        "counters": dict(sorted(counts.items())),
    }


def _wait_for_state(turn_id: str, expected: set[str], timeout: float = 15.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] | None = None
    delay = 0.1
    while time.monotonic() < deadline:
        last = _all_events(turn_id)
        state = last.get("turn", {}).get("state")
        if state in expected:
            return last
        time.sleep(delay)
        delay = min(0.5, delay * 1.5)
    raise ExerciseFailure("turn_state_timeout")


def _latest_revision(view: dict[str, Any], state: str) -> int:
    matches = [
        event.get("payload", {}).get("state_revision")
        for event in view.get("events", [])
        if event.get("type") == "status" and event.get("payload", {}).get("state") == state
    ]
    _require(bool(matches) and isinstance(matches[-1], int), "state_revision_missing")
    return matches[-1]


def _resume_clarification(turn_id: str, waiting: dict[str, Any]) -> dict[str, Any]:
    status = _request(
        "POST",
        f"/v1/turns/{turn_id}/resume/clarification",
        token=OWNER_A_TOKEN,
        body={
            "client_request_id": _new_id(),
            "expected_state_revision": _latest_revision(waiting, "WAIT_INPUT"),
            "text": "12.50 CNY",
        },
    )
    _expect_status(status, 202, "clarification_resume_failed")
    return _wait_for_state(turn_id, {"WAIT_CONFIRM"})


def _status_timeline(view: dict[str, Any]) -> set[str]:
    return {
        item.get("state") for item in _projection(view)["events"]
        if item.get("type") == "status"
    }


def _proposal_id(view: dict[str, Any]) -> tuple[str, int, str]:
    proposals = [
        event.get("payload", {}) for event in view.get("events", [])
        if event.get("type") == "proposal"
    ]
    _require(bool(proposals), "proposal_event_missing")
    latest = proposals[-1]
    proposal_id, revision, operation = latest.get("proposal_id"), latest.get("revision"), latest.get("operation")
    _require(isinstance(proposal_id, str) and isinstance(revision, int) and isinstance(operation, str), "proposal_event_invalid")
    return proposal_id, revision, operation


def _assert_simulation_card(view: dict[str, Any], proposal_id: str, revision: int) -> None:
    cards = view.get("proposal_cards", [])
    matches = [card for card in cards if card.get("proposal_id") == proposal_id]
    _require(len(matches) == 1, "simulation_card_missing")
    card = matches[0]
    _require(
        card.get("card_kind") == "simulation_pending"
        and card.get("mode") == "simulation"
        and card.get("status") == "pending"
        and card.get("revision") == revision
        and card.get("confirmation_enabled") is False
        and "confirmation_nonce" not in card
        and "command_digest" not in card,
        "simulation_card_invalid",
    )


def _create_session() -> str:
    response = _expect_status(
        _request(
            "POST",
            "/v1/sessions",
            token=OWNER_A_TOKEN,
            body={
                "api_version": "1.0.0",
                "client_request_id": _new_id(),
                "title": "P1-06 container acceptance",
            },
        ),
        201,
        "session_create_failed",
    )
    session_id = response.get("session", {}).get("session_id")
    _require(isinstance(session_id, str), "session_id_missing")
    return session_id


def _submit(session_id: str, text: str, *, token: str = OWNER_A_TOKEN) -> str:
    response = _expect_status(
        _request(
            "POST",
            f"/v1/sessions/{session_id}/turns",
            token=token,
            body={"client_request_id": _new_id(), "text": text},
        ),
        202,
        "turn_submit_failed",
    )
    turn_id = response.get("turn_id")
    _require(isinstance(turn_id, str), "turn_id_missing")
    return turn_id


def _assert_owner_boundary(session_id: str) -> dict[str, Any]:
    owner_b_list = _expect_status(_request("GET", "/v1/sessions", token=OWNER_B_TOKEN), 200, "owner_b_list_failed")
    cross_owner = _request("GET", f"/v1/sessions/{session_id}", token=OWNER_B_TOKEN)
    _require(cross_owner[0] == 404, "owner_boundary_failed", cross_owner[0])
    _require(owner_b_list.get("items") == [], "owner_b_saw_owner_a_sessions")
    return {"owner_b_session_count": 0, "cross_owner_session_status": 404}


def _before_restart() -> dict[str, Any]:
    _wait_ready()
    provider = _expect_status(_request("GET", "/health/provider"), 200, "provider_health_unavailable")
    _require(provider.get("inference_available") is False, "fixture_inference_unexpectedly_available")
    session_id = _create_session()
    boundary = _assert_owner_boundary(session_id)

    read_turn_id = _submit(session_id, "查有哪些活动")
    read_view = _wait_for_state(read_turn_id, {"COMPLETED"})
    read_summary = _projection(read_view)
    _require({"QUEUED", "RUNNING", "COMPLETED"}.issubset(set(read_summary["states"])), "read_checkpoints_missing")

    proposal_turn_id = _submit(session_id, "记录午餐")
    waiting = _wait_for_state(proposal_turn_id, {"WAIT_INPUT"})
    clarified = _resume_clarification(proposal_turn_id, waiting)
    proposal_id, proposal_revision, operation = _proposal_id(clarified)
    _require(operation == "expense.create", "proposal_operation_unexpected")
    _require(clarified.get("turn", {}).get("state") == "WAIT_CONFIRM", "proposal_not_waiting_for_confirmation")
    _assert_simulation_card(clarified, proposal_id, proposal_revision)
    proposal_summary = _projection(clarified)
    _require(
        {"QUEUED", "RUNNING", "WAIT_INPUT", "WAIT_CONFIRM"}.issubset(set(proposal_summary["states"])),
        "proposal_checkpoints_missing",
    )

    cancel_turn_id = _submit(session_id, "记录晚餐")
    cancel_waiting = _wait_for_state(cancel_turn_id, {"WAIT_INPUT"})
    cancel_summary = _projection(cancel_waiting)
    _require(cancel_summary["wait_reason"] == "missing_fields", "cancel_fixture_not_waiting_for_input")

    # This separate checkpoint proves that the post-submit Runtime auth probe is
    # bound to a process-local grant. The one-shot dummy passes the API request,
    # then expires before the worker can plan; the next process gets a fresh counter.
    auth_wait_turn_id = _submit(
        session_id,
        "查有哪些活动",
        token=OWNER_A_ONE_SHOT_TOKEN,
    )
    # Do not make another owner-A API call during the worker's first auth probe:
    # any valid owner-A request binds a fresh process-local Runtime grant.
    time.sleep(0.35)
    auth_wait = _wait_for_state(auth_wait_turn_id, {"WAIT_INPUT"})
    auth_wait_summary = _projection(auth_wait)
    _require(
        auth_wait_summary["wait_reason"] == "auth_required"
        and auth_wait_summary["resume_state"] == "QUEUED"
        and "COMPLETED" not in auth_wait_summary["states"],
        "auth_wait_fixture_not_ready",
    )

    # This exact prompt delays only the in-memory mock provider. The deployment runner
    # recreates the container while it is RUNNING; startup recovery then requires HTTP
    # reauthentication because Runtime grants are deliberately process-local.
    hold_turn_id = _submit(session_id, HOLD_PROMPT)
    hold_view = _wait_for_state(hold_turn_id, {"RUNNING"}, timeout=5.0)
    hold_summary = _projection(hold_view)
    _require("QUEUED" in hold_summary["states"] and "RUNNING" in hold_summary["states"], "restart_hold_not_running")

    return {
        "version": 1,
        "fixture": FIXTURE,
        "session_id": session_id,
        "read_turn_id": read_turn_id,
        "proposal_turn_id": proposal_turn_id,
        "proposal_id": proposal_id,
        "proposal_revision": proposal_revision,
        "proposal_operation": operation,
        "cancel_turn_id": cancel_turn_id,
        "auth_wait_turn_id": auth_wait_turn_id,
        "hold_turn_id": hold_turn_id,
        "before": {
            "read": read_summary,
            "proposal": proposal_summary,
            "cancel": cancel_summary,
            "auth_wait": auth_wait_summary,
            "hold": hold_summary,
            "owner_boundary": boundary,
            "provider": {"status": provider.get("status"), "inference_available": False},
        },
    }


def _load_evidence(raw: str | None) -> dict[str, Any]:
    if raw:
        try:
            value = json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            raise ExerciseFailure("evidence_json_invalid") from None
    else:
        evidence_path = os.environ.get("P1_06_EVIDENCE_PATH")
        if not evidence_path:
            raise ExerciseFailure("evidence_required")
        try:
            value = json.loads(Path(evidence_path).expanduser().read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            raise ExerciseFailure("evidence_file_unavailable") from None
    _require(isinstance(value, dict) and value.get("fixture") == FIXTURE and value.get("version") == 1, "evidence_fixture_mismatch")
    for key in ("session_id", "read_turn_id", "proposal_turn_id", "proposal_id", "cancel_turn_id", "hold_turn_id"):
        _require(isinstance(value.get(key), str), "evidence_id_missing")
    _require(isinstance(value.get("proposal_revision"), int), "evidence_revision_missing")
    return value


def _assert_event_prefix(before: dict[str, Any], current: dict[str, Any], code: str) -> None:
    expected = before.get("events", [])
    observed = _projection(current).get("events", [])
    _require(isinstance(expected, list) and len(observed) >= len(expected), code)
    _require(observed[:len(expected)] == expected, code)


def _after_restart(evidence: dict[str, Any]) -> dict[str, Any]:
    _wait_ready()
    session_id = evidence["session_id"]
    read_turn_id = evidence["read_turn_id"]
    proposal_turn_id = evidence["proposal_turn_id"]
    proposal_id = evidence["proposal_id"]
    cancel_turn_id = evidence["cancel_turn_id"]
    hold_turn_id = evidence["hold_turn_id"]
    before = evidence["before"]

    # First post-restart owner-A auth uses an intentionally one-shot dummy. If the
    # recovered Runtime has not yet checked its empty grant map, its verification is
    # the second use and fails; later exercise requests use the regular fixture token.
    probe = _expect_status(
        _request("GET", f"/v1/turns/{hold_turn_id}/events", token=OWNER_A_ONE_SHOT_TOKEN),
        200,
        "recovery_probe_failed",
    )
    _require(isinstance(probe.get("events"), list), "recovery_probe_malformed")
    second_use = _request("GET", f"/v1/turns/{hold_turn_id}/events", token=OWNER_A_ONE_SHOT_TOKEN)
    _require(second_use[0] == 401, "one_shot_fixture_token_not_expired", second_use[0])
    time.sleep(0.35)
    recovered = _wait_for_state(hold_turn_id, {"WAIT_INPUT"}, timeout=20.0)
    recovered_projection = _projection(recovered)
    _require(
        recovered_projection["state"] == "WAIT_INPUT"
        and recovered_projection["wait_reason"] == "auth_required"
        and recovered_projection["resume_state"] == "QUEUED"
        and recovered_projection["events"][-1].get("step") == "auth_required",
        "runtime_did_not_require_fresh_auth",
    )
    _require("COMPLETED" not in recovered_projection["states"], "turn_planned_without_fresh_auth")
    _assert_event_prefix(before["hold"], recovered, "hold_events_changed")

    session = _expect_status(_request("GET", f"/v1/sessions/{session_id}", token=OWNER_A_TOKEN), 200, "session_restore_unavailable")
    visible_turns = {item.get("turn_id") for item in session.get("turns", []) if isinstance(item, dict)}
    _require({read_turn_id, proposal_turn_id, cancel_turn_id, hold_turn_id}.issubset(visible_turns), "turn_restore_missing")

    read_view = _all_events(read_turn_id)
    proposal_view = _all_events(proposal_turn_id)
    _assert_event_prefix(before["read"], read_view, "read_events_changed")
    _assert_event_prefix(before["proposal"], proposal_view, "proposal_events_changed")
    _require(read_view.get("turn", {}).get("state") == "COMPLETED", "read_turn_restore_changed")
    _require(proposal_view.get("turn", {}).get("state") == "WAIT_CONFIRM", "proposal_auto_advanced")
    _require(_proposal_id(proposal_view)[:2] == (proposal_id, evidence["proposal_revision"]), "proposal_reference_changed")
    _assert_simulation_card(proposal_view, proposal_id, evidence["proposal_revision"])
    _require(not any(item.get("type") == "execution_result" for item in proposal_view.get("events", [])), "proposal_execution_event_present")

    cancel_view = _all_events(cancel_turn_id)
    _assert_event_prefix(before["cancel"], cancel_view, "cancel_events_changed")
    _require(
        cancel_view.get("turn", {}).get("state") == "WAIT_INPUT"
        and cancel_view.get("turn", {}).get("wait_reason") == "missing_fields",
        "cancel_turn_restore_changed",
    )
    cancel_response = _expect_status(
        _request(
            "POST",
            f"/v1/turns/{cancel_turn_id}/cancel",
            token=OWNER_A_TOKEN,
            body={
                "client_request_id": _new_id(),
                "expected_state_revision": _latest_revision(cancel_view, "WAIT_INPUT"),
                "reason": "P1-06 acceptance cleanup",
            },
        ),
        202,
        "cancel_after_restore_failed",
    )
    _require(cancel_response.get("result") == "cancelled", "cancel_after_restore_not_cancelled")
    cancelled = _all_events(cancel_turn_id)
    _require(cancelled.get("turn", {}).get("state") == "CANCELLED", "cancel_state_not_durable")

    resumed = _expect_status(
        _request(
            "POST",
            f"/v1/turns/{hold_turn_id}/resume/auth",
            token=OWNER_A_TOKEN,
            body={
                "client_request_id": _new_id(),
                "expected_state_revision": _latest_revision(recovered, "WAIT_INPUT"),
            },
        ),
        202,
        "auth_resume_failed",
    )
    _require(resumed.get("state") == "QUEUED", "auth_resume_not_queued")
    authorized = _wait_for_state(hold_turn_id, {"COMPLETED"}, timeout=25.0)

    # The frozen P1 endpoint returns 501 and records write=false. The body contains
    # only placeholders and the values are never emitted in evidence or diagnostics.
    confirm_response = _request(
        "POST",
        f"/v1/proposals/{proposal_id}/confirm",
        token=OWNER_A_TOKEN,
        body={
            "client_request_id": _new_id(),
            "expected_proposal_revision": evidence["proposal_revision"],
            "command_digest": DIGEST_SENTINEL,
            "confirmation_nonce": NONCE_SENTINEL,
        },
    )
    confirm = _expect_status(confirm_response, 501, "confirmation_capability_status_changed")
    _require(
        confirm.get("code") == "execution_capability_unavailable"
        and confirm.get("execution_enabled") is False
        and confirm.get("business_write_performed") is False,
        "confirmation_write_guard_failed",
    )
    proposal_view_after_auth = _all_events(proposal_turn_id)
    _require(proposal_view_after_auth.get("turn", {}).get("state") == "WAIT_CONFIRM", "proposal_changed_after_auth_resume")
    _require(not any(item.get("type") == "execution_result" for item in proposal_view_after_auth.get("events", [])), "proposal_executed_after_restart")

    final_session = _expect_status(_request("GET", f"/v1/sessions/{session_id}", token=OWNER_A_TOKEN), 200, "session_final_read_failed")
    cards = final_session.get("proposal_cards", [])
    matching_cards = [card for card in cards if card.get("proposal_id") == proposal_id]
    _require(len(matching_cards) == 1 and matching_cards[0].get("status") == "pending", "proposal_card_not_durable")
    boundary = _assert_owner_boundary(session_id)

    return {
        "ok": True,
        "phase": "after-restart",
        "fixture": FIXTURE,
        "session_id": session_id,
        "read_turn_id": read_turn_id,
        "proposal_turn_id": proposal_turn_id,
        "proposal_id": proposal_id,
        "cancel_turn_id": cancel_turn_id,
        "hold_turn_id": hold_turn_id,
        "restored": {
            "read_state": read_view["turn"]["state"],
            "proposal_state": proposal_view["turn"]["state"],
            "proposal_eventseq": _projection(proposal_view)["eventseq"],
            "cancel_state": cancelled["turn"]["state"],
            "hold_auth_wait_state": recovered_projection["state"],
            "hold_auth_resume_state": authorized["turn"]["state"],
            "owner_boundary": boundary,
        },
        "execution": {
            "http_status": 501,
            "enabled": False,
            "business_write_performed": False,
            "proposal_still_pending": True,
        },
    }


def _offline_recovery(evidence: dict[str, Any]) -> dict[str, Any]:
    """Verify persisted recovery APIs with the explicit disabled fixture graph."""
    _wait_ready()
    provider = _expect_status(
        _request("GET", "/health/provider"),
        200,
        "offline_provider_health_unavailable",
    )
    _require(
        provider.get("status") == "disabled" and provider.get("inference_available") is False,
        "offline_provider_not_disabled",
    )

    session_id = evidence["session_id"]
    read_turn_id = evidence["read_turn_id"]
    proposal_turn_id = evidence["proposal_turn_id"]
    cancel_turn_id = evidence["cancel_turn_id"]
    auth_wait_turn_id = evidence.get("auth_wait_turn_id")
    _require(isinstance(auth_wait_turn_id, str), "evidence_auth_wait_id_missing")
    proposal_id = evidence["proposal_id"]
    before = evidence.get("before", {})
    _require(isinstance(before, dict), "evidence_before_missing")

    # Session and persisted event APIs must remain readable despite disabled model
    # and Agent controls. This also verifies owner identity on the restored copy.
    session = _expect_status(
        _request("GET", f"/v1/sessions/{session_id}", token=OWNER_A_TOKEN),
        200,
        "offline_session_unreadable",
    )
    visible_turns = {
        item.get("turn_id") for item in session.get("turns", []) if isinstance(item, dict)
    }
    _require(
        {read_turn_id, proposal_turn_id, cancel_turn_id, auth_wait_turn_id}.issubset(visible_turns),
        "offline_persisted_turn_missing",
    )
    read_view = _all_events(read_turn_id)
    proposal_view = _all_events(proposal_turn_id)
    cancel_view = _all_events(cancel_turn_id)
    auth_wait_view = _all_events(auth_wait_turn_id)
    for key, current in (
        ("read", read_view),
        ("proposal", proposal_view),
        ("cancel", cancel_view),
        ("auth_wait", auth_wait_view),
    ):
        _require(isinstance(before.get(key), dict), "offline_checkpoint_evidence_missing")
        _assert_event_prefix(before[key], current, "offline_persisted_events_changed")

    _require(read_view.get("turn", {}).get("state") == "COMPLETED", "offline_read_state_changed")
    _require(
        proposal_view.get("turn", {}).get("state") == "WAIT_CONFIRM"
        and _proposal_id(proposal_view)[:2] == (proposal_id, evidence["proposal_revision"])
        and not any(item.get("type") == "execution_result" for item in proposal_view.get("events", [])),
        "offline_proposal_changed_before_action",
    )
    _require(
        cancel_view.get("turn", {}).get("state") == "WAIT_INPUT"
        and cancel_view.get("turn", {}).get("wait_reason") == "missing_fields",
        "offline_cancel_checkpoint_changed",
    )
    _require(
        auth_wait_view.get("turn", {}).get("state") == "WAIT_INPUT"
        and auth_wait_view.get("turn", {}).get("wait_reason") == "auth_required"
        and auth_wait_view.get("turn", {}).get("resume_state") == "QUEUED",
        "offline_auth_checkpoint_changed",
    )

    resumed = _expect_status(
        _request(
            "POST",
            f"/v1/turns/{auth_wait_turn_id}/resume/auth",
            token=OWNER_A_TOKEN,
            body={
                "client_request_id": _new_id(),
                "expected_state_revision": _latest_revision(auth_wait_view, "WAIT_INPUT"),
            },
        ),
        202,
        "offline_auth_resume_rejected",
    )
    _require(resumed.get("state") == "QUEUED", "offline_auth_resume_not_queued")
    time.sleep(0.35)
    queued = _all_events(auth_wait_turn_id)
    queued_events = _projection(queued)["events"]
    prior_event_count = len(before["auth_wait"].get("events", []))
    resumed_events = queued_events[prior_event_count:]
    _require(
        queued.get("turn", {}).get("state") == "QUEUED"
        and len(resumed_events) == 1
        and resumed_events[0].get("type") == "status"
        and resumed_events[0].get("state") == "QUEUED"
        and not any(item.get("type") == "execution_result" for item in queued.get("events", [])),
        "offline_resume_started_planning",
    )

    cancel_response = _expect_status(
        _request(
            "POST",
            f"/v1/turns/{cancel_turn_id}/cancel",
            token=OWNER_A_TOKEN,
            body={
                "client_request_id": _new_id(),
                "expected_state_revision": _latest_revision(cancel_view, "WAIT_INPUT"),
                "reason": "P1-06 offline recovery cleanup",
            },
        ),
        202,
        "offline_cancel_rejected",
    )
    _require(cancel_response.get("result") == "cancelled", "offline_cancel_not_cancelled")
    cancelled = _all_events(cancel_turn_id)
    _require(cancelled.get("turn", {}).get("state") == "CANCELLED", "offline_cancel_state_not_durable")

    # This is the first confirmation attempt against the fresh copy. The frozen
    # Agent gate rejects it before recording a receipt or changing proposal state.
    confirm_status, confirm = _request(
        "POST",
        f"/v1/proposals/{proposal_id}/confirm",
        token=OWNER_A_TOKEN,
        body={
            "client_request_id": _new_id(),
            "expected_proposal_revision": evidence["proposal_revision"],
            "command_digest": DIGEST_SENTINEL,
            "confirmation_nonce": NONCE_SENTINEL,
        },
    )
    _require(
        confirm_status == 409 and confirm.get("code") == "agent_disabled",
        "offline_confirmation_gate_changed",
        confirm_status,
    )
    proposal_after_confirm = _all_events(proposal_turn_id)
    _require(
        _projection(proposal_after_confirm) == _projection(proposal_view)
        and proposal_after_confirm.get("turn", {}).get("state") == "WAIT_CONFIRM"
        and not any(item.get("type") == "execution_result" for item in proposal_after_confirm.get("events", [])),
        "offline_confirmation_changed_persisted_state",
    )
    _require(
        provider.get("status") == "disabled" and provider.get("inference_available") is False,
        "offline_provider_became_available",
    )

    return {
        "ok": True,
        "phase": "offline-recovery",
        "fixture": FIXTURE,
        "session_id": session_id,
        "read_turn_id": read_turn_id,
        "proposal_turn_id": proposal_turn_id,
        "proposal_id": proposal_id,
        "cancel_turn_id": cancel_turn_id,
        "auth_wait_turn_id": auth_wait_turn_id,
        "restored": {
            "read_state": read_view["turn"]["state"],
            "read_eventseq": _projection(read_view)["eventseq"],
            "proposal_state": proposal_view["turn"]["state"],
            "proposal_eventseq": _projection(proposal_view)["eventseq"],
            "auth_resume_state": queued["turn"]["state"],
            "auth_resume_eventseq": _projection(queued)["eventseq"],
            "cancel_state": cancelled["turn"]["state"],
            "provider_status": provider.get("status"),
        },
        "offline_controls": {
            "auth_resume_accepted": True,
            "resume_queued_without_execution": True,
            "cancel_accepted": True,
            "confirm_http_status": confirm_status,
            "confirm_error": confirm.get("code"),
            "confirm_wrote": False,
            "proposal_still_waiting": True,
        },
    }


def _sentinels() -> tuple[bytes, ...]:
    return tuple(value.encode("ascii") for value in (
        OWNER_A_TOKEN,
        OWNER_B_TOKEN,
        OWNER_A_ONE_SHOT_TOKEN,
        REFRESH_SENTINEL,
        NONCE_SENTINEL,
        DIGEST_SENTINEL,
    ))


def _scan_bytes(content: bytes) -> bool:
    return not any(sentinel in content for sentinel in _sentinels())


def _scan_database() -> dict[str, Any]:
    raw_path = os.environ.get("AGENT_STORAGE_PATH")
    _require(bool(raw_path), "database_path_missing")
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = path.resolve()
    _require(path.is_file(), "database_unavailable")
    try:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2.0)
        try:
            table_rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            tables = 0
            scanned_rows = 0
            for (table,) in table_rows:
                identifier = '"' + str(table).replace('"', '""') + '"'
                cursor = connection.execute("SELECT * FROM " + identifier)
                tables += 1
                for row in cursor:
                    scanned_rows += 1
                    for value in row:
                        if isinstance(value, str):
                            encoded = value.encode("utf-8", "ignore")
                        elif isinstance(value, bytes):
                            encoded = value
                        else:
                            continue
                        _require(_scan_bytes(encoded), "database_secret_sentinel_found")
        finally:
            connection.close()
    except ExerciseFailure:
        raise
    except (OSError, sqlite3.Error, ValueError):
        raise ExerciseFailure("database_scan_failed") from None
    return {"ok": True, "phase": "scan-database", "tables_checked": tables, "rows_checked": scanned_rows, "sentinels_absent": True}


def _scan_text(path_raw: str) -> dict[str, Any]:
    try:
        content = Path(path_raw).expanduser().read_bytes()
    except OSError:
        raise ExerciseFailure("log_scan_file_unavailable") from None
    _require(len(content) <= 50 * 1024 * 1024, "log_scan_file_oversized")
    _require(_scan_bytes(content), "log_secret_sentinel_found")
    return {"ok": True, "phase": "scan-text", "bytes_checked": len(content), "sentinels_absent": True}


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the redacted P1-06 HTTP acceptance exercise")
    parser.add_argument("phase", choices=("before-restart", "after-restart", "offline-recovery", "scan-database", "scan-text"))
    parser.add_argument("--evidence-json", help="redacted JSON emitted by before-restart")
    parser.add_argument("--path", help="file path required by scan-text")
    args = parser.parse_args(argv)
    try:
        if args.phase == "before-restart":
            evidence = _before_restart()
            path_raw = os.environ.get("P1_06_EVIDENCE_PATH")
            if path_raw:
                try:
                    target = Path(path_raw).expanduser()
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(json.dumps(evidence, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                except OSError:
                    raise ExerciseFailure("evidence_write_failed") from None
            _emit(evidence)
        elif args.phase == "after-restart":
            result = _after_restart(_load_evidence(args.evidence_json))
            _emit(result)
        elif args.phase == "offline-recovery":
            result = _offline_recovery(_load_evidence(args.evidence_json))
            _emit(result)
        elif args.phase == "scan-database":
            _emit(_scan_database())
        else:
            if not args.path:
                raise ExerciseFailure("scan_text_path_required")
            _emit(_scan_text(args.path))
    except ExerciseFailure as exc:
        result: dict[str, Any] = {"ok": False, "failure": exc.code}
        if exc.status is not None:
            result["http_status"] = exc.status
        _emit(result)
        return 1
    except Exception:
        _emit({"ok": False, "failure": "unexpected_helper_error"})
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
