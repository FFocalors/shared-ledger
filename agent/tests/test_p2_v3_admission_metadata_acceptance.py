from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit
import hashlib
import json

import pytest

from agent.app import contracts as c
from agent.app import p2_backend as v1
from agent.app import p2_read_backend as backend
from agent.app import p2_read_contracts_v3 as pc
from agent.app import p2_source_codec_v3 as codec
from agent.app.p2_source_store_v3 import P2V3StoreConflict, P2_V3_CANDIDATE_PROFILE_ID
from agent.app.p2_read_store import P2_CANDIDATE_PROFILE_ID
from agent.app.store import EventDraft, SQLiteAgentStore
from agent.app.p2_v3_store_ports import P2V3StoreBudgetPort
from agent.app import p2_v3_execution_cohort as cohort_verifier
from test_p2_source_codec_backend_v3 import _datasets


OWNER = uuid.UUID("a1000000-0000-4000-8000-000000000001")
ACTIVITY = uuid.UUID("00000000-0000-4000-8000-000000000003")
UNIT = uuid.UUID("00000000-0000-4000-8000-000000000004")
ROOT_UNIT = uuid.UUID("00000000-0000-4000-8000-000000000019")


def _configured_store(path: Path) -> SQLiteAgentStore:
    root = Path(os.environ["P2_V3_STORE_TEST_ROOT"])
    component_root = root / "synthetic-cohort-components"
    component_root.mkdir(parents=True, exist_ok=True)
    component_path = component_root / "fixture.json"
    fixture_bytes = b'{"purpose":"isolated Stage B metadata acceptance CPU fixture"}'
    component_path.write_bytes(fixture_bytes)
    components = [{
        "path": "fixture.json", "role": "synthetic_fixture", "bytes": len(fixture_bytes),
        "sha256": hashlib.sha256(fixture_bytes).hexdigest(),
    }]
    canonical = lambda value: json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    document = {
        "format": "p2-v3-execution-manifest", "manifest_kind": "synthetic_test",
        "profile_id": P2_V3_CANDIDATE_PROFILE_ID,
        "versions": pc.P2_V3_VERSIONS.model_dump(mode="json"),
        "schema_bundle_sha256": hashlib.sha256(b"synthetic-test-schema-bundle").hexdigest(),
        "source_manifest_sha256": hashlib.sha256(canonical(components)).hexdigest(),
        "contract_source_sha256": hashlib.sha256(b"synthetic-test-contract-snapshot").hexdigest(),
        "components": components,
        "safe_config": {"debt_source_variant": "expense_debt_line", "budgets": dict(cohort_verifier._BUDGETS)},
    }
    manifest_bytes = canonical(document)
    manifest_path = root / "synthetic-cohort-manifest.json"
    manifest_path.write_bytes(manifest_bytes)
    return SQLiteAgentStore(
        path, p2_v3_execution_manifest_path=manifest_path,
        p2_v3_execution_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        p2_v3_execution_repository_root=Path(__file__).parents[1],
        p2_v3_execution_external_component_roots={"synthetic_fixture": component_root},
        test_only_allow_synthetic_p2_v3_cohort=True,
    )


def _status(snapshot: c.TurnStateSnapshot, at: datetime) -> EventDraft:
    return EventDraft(
        type=c.EventType.STATUS, occurred_at=at, simulation=False,
        payload=c.StatusEventPayload(
            state=snapshot.state, step=snapshot.step, state_revision=snapshot.state_revision,
            wait_reason=snapshot.wait_reason, resume_state=snapshot.resume_state,
        ),
    )


def _create_running_turn(store: SQLiteAgentStore, *, now: datetime) -> tuple[uuid.UUID, str]:
    submitted_at = now - timedelta(seconds=1)
    ui = c.UIContext(page_type=c.PageType.HOME, captured_at=submitted_at, client_version="p2-v3-admission-metadata")
    session = store.create_session(
        OWNER, c.CreateSessionRequest(client_request_id=uuid.uuid4(), title="P2 metadata CPU", ui_context=ui),
        now=submitted_at,
    ).response_snapshot.session.session_id
    submitted = store.submit_turn(
        OWNER, session,
        c.SubmitTurnRequest(client_request_id=uuid.uuid4(), text="Read the current shared ledger", ui_context=ui),
        now=submitted_at, candidate_profile_id=P2_V3_CANDIDATE_PROFILE_ID,
    )
    turn_id = submitted.response_snapshot.turn_id
    claimed = store.claim_runnable("p2v3-metadata-worker", candidate_profile_id=P2_V3_CANDIDATE_PROFILE_ID, now=now)
    assert claimed is not None and claimed.turn.record.turn.turn_id == turn_id
    before = claimed.turn.record.turn
    after = before.model_copy(update={
        "state": c.TurnState.RUNNING, "state_revision": before.state_revision + 1,
        "step": c.TurnStep.BUILD_CONTEXT, "wait_reason": None, "resume_state": None,
    })
    store.transition_turn(
        OWNER, after, expected_state_revision=before.state_revision,
        expected_checkpoint_revision=claimed.turn.checkpoint_revision,
        events=[_status(after, now)], claim_token=claimed.claim_token,
        candidate_profile_id=P2_V3_CANDIDATE_PROFILE_ID, now=now,
    )
    return turn_id, claimed.claim_token


class SyntheticTransport:
    def __init__(self, datasets: dict[str, list[dict[str, Any]]]) -> None:
        self.datasets = datasets
        self.calls = 0

    def get(self, url: str, headers: Any, *, timeout: float, max_response_bytes: int, control: Any) -> v1.TransportResponse:
        self.calls += 1
        parsed = urlsplit(url)
        table = parsed.path.rsplit("/", 1)[-1]
        values: dict[str, list[str]] = {}
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            values.setdefault(key, []).append(value)
        rows = list(self.datasets[table])
        for key, query_values in values.items():
            if key in {"select", "order", "limit", "offset"}:
                continue
            for query_value in query_values:
                if query_value.startswith("eq."):
                    expected: Any = query_value[3:]
                    if expected in {"true", "false"}:
                        expected = expected == "true"
                    rows = [row for row in rows if row.get(key) == expected]
        order = values.get("order", ["id.asc"])[0]
        for directive in reversed(order.split(",")):
            column, _, direction = directive.partition(".")
            rows.sort(key=lambda row: (row.get(column) is None, row.get(column)), reverse=direction == "desc")
        offset = int(values.get("offset", ["0"])[0])
        limit = int(values.get("limit", ["16"])[0])
        total = len(rows)
        selected = rows[offset:offset + limit]
        columns = values["select"][0].split(",")
        selected = [{column: row[column] for column in columns} for row in selected]
        body = _encode_source_json(selected).encode("utf-8")
        if len(body) > max_response_bytes:
            raise AssertionError("synthetic response exceeded requested byte cap")
        content_range = f"{offset}-{offset + len(selected) - 1}/{total}" if selected else f"*/{total}"
        codec.parse_source_rows(body, table=table)
        codec.parse_content_range(
            content_range, expected_offset=offset, row_count=len(selected), status=200,
        )
        return v1.TransportResponse(200, body, content_range)


def _encode_source_json(value: Any) -> str:
    """Encode fixture JsonNumber lexemes as actual JSON numbers, not strings."""
    if type(value).__name__ == "JsonNumber":
        lexeme = str(value)
        if not lexeme or any(ch not in "0123456789-.eE+" for ch in lexeme):
            raise AssertionError("invalid synthetic JSON numeric lexeme")
        return lexeme
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if type(value) is str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if type(value) is int:
        return str(value)
    if type(value) is list or type(value) is tuple:
        return "[" + ",".join(_encode_source_json(item) for item in value) + "]"
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise AssertionError("synthetic JSON object keys must be strings")
        return "{" + ",".join(
            json.dumps(key, ensure_ascii=False) + ":" + _encode_source_json(item)
            for key, item in value.items()
        ) + "}"
    raise AssertionError(f"unsupported synthetic JSON value: {type(value).__name__}")


def _adapter(
    store: Any, owner: uuid.UUID, turn: uuid.UUID, claim: str, registry: Any,
    *, include_root_unit: bool = False,
) -> backend.P2ReadBackendAdapter:
    datasets = _datasets()
    datasets["activity_members"][0]["user_id"] = str(owner)
    datasets["participant_claims"][0]["user_id"] = str(owner)
    if include_root_unit:
        datasets["ledger_units"].append({
            "id": str(ROOT_UNIT), "activity_id": str(ACTIVITY), "name": "主账本",
            "type": "root", "is_deleted": False,
            "participant_scope_configured": False, "updated_at": datasets["ledger_units"][0]["updated_at"],
        })
    transport = SyntheticTransport(datasets)
    return backend.P2ReadBackendAdapter(
        v1.P2BackendConfig(
            project_url="https://synthetic.invalid", publishable_key="sb_publishable_synthetic_cpu_only",
            timeout_seconds=2, page_size=16, max_pages=4, max_rows_per_query=64,
            max_requests_per_read=48, max_total_response_bytes=4_194_304,
            max_total_seconds=20, max_facts=16,
        ),
        transport=transport,
        v3_budget_port=P2V3StoreBudgetPort(store, owner, turn, claim),
        v3_locator_port=registry,
    )


def _make_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *,
    ledger_unit_id_hint: uuid.UUID | None = UNIT, include_root_unit: bool = False,
) -> tuple[Any, uuid.UUID, str, Any, Any, backend.P2ReadBackendAdapter, v1.VerifiedReadContext]:
    monkeypatch.setenv("P2_V3_STORE_TEST_ROOT", str(tmp_path))
    store = _configured_store(tmp_path / "candidate.sqlite3")
    store.start()
    now = datetime.now(timezone.utc)
    turn, claim = _create_running_turn(store, now=now)
    binding, _ = store.create_p2_v3_request_admission(
        OWNER, turn, claim_token=claim, principal_user_id=OWNER,
        activity_id_hint=ACTIVITY, ledger_unit_id_hint=ledger_unit_id_hint,
        now=now,
    )
    adapter = _adapter(
        store, OWNER, turn, claim, binding.reference_registry,
        include_root_unit=include_root_unit,
    )
    verified = v1.VerifiedReadContext(
        owner_user_id=OWNER, turn_id=turn, principal_user_id=OWNER,
        access_token="synthetic.jwt.cpu", expires_at=now + timedelta(minutes=5),
        refs_by_opaque_token={},
    )
    return store, turn, claim, binding, binding.reference_registry, adapter, verified


def _accepted_row_counts(store: Any, admission_id: str) -> tuple[int, int, int, int]:
    with store._connection() as connection:
        source_receipts = int(connection.execute(
            "SELECT COUNT(*) FROM p2_v3_admission_source_receipts WHERE admission_id=?", (admission_id,),
        ).fetchone()[0])
        metadata_proofs = int(connection.execute(
            "SELECT COUNT(*) FROM p2_v3_metadata_source_proofs WHERE turn_id=?", (str(connection.execute(
                "SELECT turn_id FROM p2_v3_source_admissions WHERE admission_id=?", (admission_id,),
            ).fetchone()[0]),),
        ).fetchone()[0])
        locators = int(connection.execute(
            "SELECT COUNT(*) FROM p2_v3_entity_locators WHERE turn_id=(SELECT turn_id FROM p2_v3_source_admissions WHERE admission_id=?)",
            (admission_id,),
        ).fetchone()[0])
        captures = int(connection.execute(
            "SELECT COUNT(*) FROM p2_v3_wire_captures WHERE admission_id=? AND capture_state='cost_only'",
            (admission_id,),
        ).fetchone()[0])
    return source_receipts, metadata_proofs, locators, captures


def test_store_accepts_exact_six_raw_metadata_pages_atomically(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, turn, _, binding, registry, adapter, verified = _make_admission(tmp_path, monkeypatch)
    try:
        projection = asyncio.run(adapter.admit_scope_v3(
            verified, binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
        ))
        assert projection is not None
        registry.require_metadata_accepted(identity=binding.identity, admission_id=binding.admission_id)
        assert projection.snapshot.activity_id == ACTIVITY
        assert projection.snapshot.scope_kind == "ledger_unit"
        assert len(projection.captures) == 6
        receipts, proofs, locators, cost_captures = _accepted_row_counts(store, binding.admission_id)
        assert receipts == 6
        assert proofs >= 2
        assert locators >= 3
        assert cost_captures == 6
        with store._connection() as connection:
            settled = int(connection.execute(
                "SELECT COUNT(*) FROM p2_v3_charge_events WHERE owner_user_id=? AND turn_id=? AND event_kind='settled' AND stage='backend_get'",
                (str(OWNER), str(turn)),
            ).fetchone()[0])
        assert settled == 6
    finally:
        store.close()


def test_activity_metadata_keeps_root_internal_and_publishes_only_child_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, _, binding, registry, adapter, verified = _make_admission(
        tmp_path, monkeypatch, ledger_unit_id_hint=None, include_root_unit=True,
    )
    try:
        projection = asyncio.run(adapter.admit_scope_v3(
            verified, binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=None,
        ))
        assert projection is not None
        assert projection.snapshot.scope_kind == "activity"
        assert {row["id"] for row in projection.snapshot.ledger_units} == {str(ROOT_UNIT), str(UNIT)}

        unit_labels = [label for label in projection.source_labels if label.entity_kind == "ledger_unit"]
        assert len(unit_labels) == 1
        child_label = unit_labels[0]
        assert child_label.display_name == "子账本"
        assert registry.binding_for_ref(str(child_label.entity_ref)) == (
            "ledger_unit", UNIT, ACTIVITY, UNIT,
        )
        registry.require_metadata_accepted(identity=binding.identity, admission_id=binding.admission_id)
        receipt_id = registry.accepted_receipt_id(
            child_label.source_receipt_ref, identity=binding.identity, admission_id=binding.admission_id,
        )
        assert receipt_id

        with store._connection() as connection:
            unit_locators = connection.execute(
                "SELECT private_entity_id FROM p2_v3_entity_locators WHERE turn_id=? AND entity_kind='ledger_unit'",
                (str(binding.identity.turn_id),),
            ).fetchall()
        assert [row["private_entity_id"] for row in unit_locators] == [str(UNIT)]
        receipts, proofs, locators, captures = _accepted_row_counts(store, binding.admission_id)
        assert receipts == 6
        assert proofs >= 2
        assert locators >= 3
        assert captures == 6
    finally:
        store.close()


def test_raw_body_tampering_keeps_cost_but_publishes_no_metadata_proof(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, turn, _, binding, registry, adapter, verified = _make_admission(tmp_path, monkeypatch)
    original = store.accept_p2_v3_admission_metadata

    def tamper(owner: uuid.UUID, turn_id: uuid.UUID, *, binding: Any, projection: Any, now: datetime | None = None) -> Any:
        first_page = projection.snapshot.witnesses[0]
        tampered_page = replace(first_page, raw_body=first_page.raw_body + b" ")
        pages = (tampered_page, *projection.snapshot.witnesses[1:])
        snapshot = replace(projection.snapshot, witnesses=pages)
        changed_projection = replace(
            projection, snapshot=snapshot,
            captures=tuple(page.witness for page in pages),
        )
        return original(owner, turn_id, binding=binding, projection=changed_projection, now=now)

    store.accept_p2_v3_admission_metadata = tamper
    try:
        with pytest.raises(backend.P2ReadBackendError):
            asyncio.run(adapter.admit_scope_v3(
                verified, binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
            ))
        with pytest.raises(P2V3StoreConflict):
            registry.require_metadata_accepted(identity=binding.identity, admission_id=binding.admission_id)
        receipts, proofs, locators, captures = _accepted_row_counts(store, binding.admission_id)
        assert (receipts, proofs, locators, captures) == (0, 0, 0, 6)
        snap = store.get_p2_v3_snapshot(OWNER, turn)
        assert snap.get_attempts == 6
        assert snap.response_bytes > 0
        assert snap.backend_used_us > 0
    finally:
        store.close()


def test_wrong_principal_cannot_open_or_accept_an_owner_turn_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, turn, claim, _, _, _, _ = _make_admission(tmp_path, monkeypatch)
    try:
        with pytest.raises(P2V3StoreConflict):
            store.create_p2_v3_request_admission(
                OWNER, turn, claim_token=claim,
                principal_user_id=uuid.UUID("a1000000-0000-4000-8000-000000000099"),
                activity_id_hint=ACTIVITY, ledger_unit_id_hint=UNIT,
            )
    finally:
        store.close()


def test_metadata_accept_rejects_all_six_pages_from_another_pinned_origin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, turn, _, binding, registry, adapter, verified = _make_admission(tmp_path, monkeypatch)
    original = store.accept_p2_v3_admission_metadata

    def other_origin(owner: uuid.UUID, turn_id: uuid.UUID, *, binding: Any, projection: Any, now: datetime | None = None) -> Any:
        pages = tuple(
            replace(page, request_url=page.request_url.replace("https://synthetic.invalid", "https://other.invalid", 1))
            for page in projection.snapshot.witnesses
        )
        snapshot = replace(projection.snapshot, witnesses=pages)
        changed = replace(projection, snapshot=snapshot, captures=tuple(page.witness for page in pages))
        return original(owner, turn_id, binding=binding, projection=changed, now=now)

    store.accept_p2_v3_admission_metadata = other_origin
    try:
        with pytest.raises(backend.P2ReadBackendError):
            asyncio.run(adapter.admit_scope_v3(
                verified, binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
            ))
        with pytest.raises(P2V3StoreConflict):
            registry.require_metadata_accepted(identity=binding.identity, admission_id=binding.admission_id)
        receipts, proofs, locators, captures = _accepted_row_counts(store, binding.admission_id)
        assert (receipts, proofs, locators, captures) == (0, 0, 0, 6)
        assert store.get_p2_v3_snapshot(OWNER, turn).get_attempts == 6
    finally:
        store.close()


def test_metadata_accept_rechecks_claim_after_capture_and_keeps_get_costs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, turn, _, binding, registry, adapter, verified = _make_admission(tmp_path, monkeypatch)
    original = store.accept_p2_v3_admission_metadata

    def retire_claim(owner: uuid.UUID, turn_id: uuid.UUID, *, binding: Any, projection: Any, now: datetime | None = None) -> Any:
        store.mark_claim_worker_retired("p2v3-metadata-worker")
        store.cleanup_retired_claim_workers()
        return original(owner, turn_id, binding=binding, projection=projection, now=now)

    store.accept_p2_v3_admission_metadata = retire_claim
    try:
        with pytest.raises(backend.P2ReadBackendError):
            asyncio.run(adapter.admit_scope_v3(
                verified, binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
            ))
        with pytest.raises(P2V3StoreConflict):
            registry.require_metadata_accepted(identity=binding.identity, admission_id=binding.admission_id)
        receipts, proofs, locators, captures = _accepted_row_counts(store, binding.admission_id)
        assert (receipts, proofs, locators, captures) == (0, 0, 0, 6)
        snapshot = store.get_p2_v3_snapshot(OWNER, turn)
        assert snapshot.get_attempts == 6 and snapshot.response_bytes > 0
    finally:
        store.close()


def test_source_origin_pin_is_write_once_per_request_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store, _, _, binding, registry, _, _ = _make_admission(tmp_path, monkeypatch)
    try:
        registry.bind_configured_source_origin("https://synthetic.invalid")
        with pytest.raises(P2V3StoreConflict):
            registry.bind_configured_source_origin("https://other.invalid")
        assert registry._configured_source_origin == ("https", "synthetic.invalid")
    finally:
        store.close()
