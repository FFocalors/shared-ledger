"""Storage compatibility: historical 1.0.0 rows must start under API 1.1.0.

The HTTP API still rejects 1.0.0 requests with 422. Stored JSON and
request_payload_hash must not be rewritten on load.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
import sys

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from agent.app import contracts as c
from agent.app.store import SQLiteAgentStore

import test_identity_api as identity
from test_sqlite_persistence import OWNER, _session, _store, _submit


def _canonical_dumps(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _rewrite_stored_api_version(value: object) -> object:
    if isinstance(value, dict):
        rewritten = {key: _rewrite_stored_api_version(item) for key, item in value.items()}
        if rewritten.get("api_version") == "1.1.0":
            rewritten["api_version"] = "1.0.0"
        versions = rewritten.get("versions")
        if isinstance(versions, dict) and versions.get("api") == "1.1.0":
            versions = dict(versions)
            versions["api"] = "1.0.0"
            rewritten["versions"] = versions
        if (
            rewritten.get("api") == "1.1.0"
            and "semantic" in rewritten
            and "operations" in rewritten
        ):
            rewritten["api"] = "1.0.0"
        return rewritten
    if isinstance(value, list):
        return [_rewrite_stored_api_version(item) for item in value]
    return value


def _replace_hash(value: object, old: str, new: str) -> object:
    if value == old:
        return new
    if isinstance(value, dict):
        return {key: _replace_hash(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_hash(item, old, new) for item in value]
    return value


def _historical_payload_hash(key_scope: str, payload: object, resource_id: uuid.UUID | None = None) -> str:
    document = {
        "api_version": "1.0.0",
        "key_scope": key_scope,
        "resource_id": str(resource_id) if resource_id is not None else None,
        "payload": payload,
    }
    canonical = _canonical_dumps(c._normalize_json(document)).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _downgrade_store_rows(path: Path) -> dict[str, str]:
    """Rewrite a freshly written 1.1.0 store into historical 1.0.0 rows."""
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    preserved: dict[str, str] = {}
    try:
        for row in connection.execute("SELECT * FROM sessions").fetchall():
            request = _rewrite_stored_api_version(json.loads(row["create_request_json"]))
            if not isinstance(request, dict):
                raise AssertionError("session create_request_json must be an object")
            new_hash = _historical_payload_hash(c.ApiActionKind.SESSION_CREATE.value, request)
            old_hash = row["create_payload_hash"]
            values: dict[str, object] = {"create_payload_hash": new_hash}
            for key in row.keys():
                if not key.endswith("_json") or row[key] is None:
                    continue
                document = _replace_hash(
                    _rewrite_stored_api_version(json.loads(row[key])),
                    old_hash,
                    new_hash,
                )
                values[key] = _canonical_dumps(document)
            assignments = ", ".join(f"{key} = ?" for key in values)
            connection.execute(
                f"UPDATE sessions SET {assignments} WHERE session_id = ?",
                [*values.values(), row["session_id"]],
            )
            preserved["create_request_json"] = str(values["create_request_json"])
            preserved["create_payload_hash"] = new_hash

        for row in connection.execute("SELECT * FROM turns").fetchall():
            request = _rewrite_stored_api_version(json.loads(row["request_json"]))
            if not isinstance(request, dict):
                raise AssertionError("turn request_json must be an object")
            new_hash = _historical_payload_hash(
                c.ApiActionKind.TURN_SUBMIT.value,
                request,
                resource_id=uuid.UUID(row["session_id"]),
            )
            old_hash = row["request_payload_hash"]
            values = {"request_payload_hash": new_hash}
            for key in row.keys():
                if not key.endswith("_json") or row[key] is None:
                    continue
                document = _replace_hash(
                    _rewrite_stored_api_version(json.loads(row[key])),
                    old_hash,
                    new_hash,
                )
                values[key] = _canonical_dumps(document)
            assignments = ", ".join(f"{key} = ?" for key in values)
            connection.execute(
                f"UPDATE turns SET {assignments} WHERE turn_id = ?",
                [*values.values(), row["turn_id"]],
            )
            preserved["request_json"] = str(values["request_json"])
            preserved["request_payload_hash"] = new_hash
            preserved["turn_id"] = row["turn_id"]
            preserved["session_id"] = row["session_id"]

        connection.commit()
    finally:
        connection.close()
    return preserved


def _raw_row(path: Path, table: str, key: str, value: str) -> sqlite3.Row:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(f"SELECT * FROM {table} WHERE {key} = ?", (value,)).fetchone()
        if row is None:
            raise AssertionError(f"missing {table} row")
        return row
    finally:
        connection.close()


def test_historical_1_0_0_rows_load_without_rewriting_json_or_hash(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite3"
    store = _store(path)
    try:
        session_id = _session(store)
        _submit(store, session_id)
    finally:
        store.close()

    preserved = _downgrade_store_rows(path)
    assert preserved["request_json"]
    assert "1.0.0" in preserved["request_json"]
    assert "\"api\":\"1.1.0\"" not in preserved["request_json"]
    assert preserved["create_request_json"]
    assert preserved["create_payload_hash"] != ""
    assert preserved["request_payload_hash"] != ""

    store = _store(path)
    try:
        session = store.get_session(OWNER, uuid.UUID(preserved["session_id"]))
        turn = store.get_turn(OWNER, uuid.UUID(preserved["turn_id"]))
        assert session.session_id == uuid.UUID(preserved["session_id"])
        assert turn.record.turn.turn_id == uuid.UUID(preserved["turn_id"])
        assert turn.record.request_payload_hash == preserved["request_payload_hash"]
        assert payload_version(turn.checkpoint.accepted_inputs[0].payload) == "1.0.0"
        assert c.canonical_payload_hash(
            c.ApiActionKind.TURN_SUBMIT,
            turn.checkpoint.accepted_inputs[0].payload,
            resource_id=turn.record.turn.session_id,
        ) == preserved["request_payload_hash"]
        assert c.canonical_payload_hash(
            c.ApiActionKind.SESSION_CREATE,
            # SessionRecord does not expose the request; read it from the raw row after start.
            _loaded_create_request(path, preserved["session_id"]),
        ) == preserved["create_payload_hash"]
    finally:
        store.close()

    session_row = _raw_row(path, "sessions", "session_id", preserved["session_id"])
    turn_row = _raw_row(path, "turns", "turn_id", preserved["turn_id"])
    assert session_row["create_request_json"] == preserved["create_request_json"]
    assert session_row["create_payload_hash"] == preserved["create_payload_hash"]
    assert turn_row["request_json"] == preserved["request_json"]
    assert turn_row["request_payload_hash"] == preserved["request_payload_hash"]


def _loaded_create_request(path: Path, session_id: str) -> c.CreateSessionRequest:
    row = _raw_row(path, "sessions", "session_id", session_id)
    return c.CreateSessionRequest.model_validate_json(row["create_request_json"])


def payload_version(payload: c.ContractModel) -> str:
    return c.payload_api_version(payload)


def test_current_1_1_0_rows_still_start(tmp_path: Path) -> None:
    path = tmp_path / "current.sqlite3"
    store = _store(path)
    try:
        session_id = _session(store)
        receipt, turn_id = _submit(store, session_id)
        expected_hash = receipt.payload_hash
        store.close()
        store = _store(path)
        turn = store.get_turn(OWNER, turn_id)
        assert turn.record.request_payload_hash == expected_hash
        assert payload_version(turn.checkpoint.accepted_inputs[0].payload) == "1.1.0"
    finally:
        store.close()


def test_api_still_rejects_1_0_0_requests(tmp_path: Path) -> None:
    client, components = identity._client(tmp_path)
    try:
        create = client.post(
            "/v1/sessions",
            headers=identity._headers(),
            json={
                "api_version": "1.0.0",
                "client_request_id": str(uuid.uuid4()),
                "title": "Trip",
            },
        )
        body = identity._assert_typed_error(create, 422)
        assert body["code"] == "invalid_request"

        current = client.post(
            "/v1/sessions",
            headers=identity._headers(),
            json={
                "api_version": "1.1.0",
                "client_request_id": str(uuid.uuid4()),
                "title": "Trip",
            },
        )
        assert current.status_code == 201, current.text
        session_id = current.json()["session"]["session_id"]

        submit = client.post(
            f"/v1/sessions/{session_id}/turns",
            headers=identity._headers(),
            json={
                "versions": {"api": "1.0.0", "semantic": "1.0.0", "operations": "1.0.0"},
                "client_request_id": str(uuid.uuid4()),
                "text": "Record lunch",
            },
        )
        submit_body = identity._assert_typed_error(submit, 422)
        assert submit_body["code"] == "invalid_request"
    finally:
        client.__exit__(None, None, None)
        components.value.store.close()
