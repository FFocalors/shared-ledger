from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import contracts as c
from app import p2_backend as v1
from app import p2_read_backend as backend
from app import p2_read_contracts_v3 as pc
from app import p2_source_codec_v3 as codec
from app import p2_source_store_v3 as source_store
from app import p2_event_contracts_v3 as pe
from app import p2_v3_execution_cohort as cohort
from app.ports import AgentControlSnapshot
from app.p2_v3_store_ports import P2V3StoreBudgetPort
from app.store import EventDraft, SQLiteAgentStore
from test_p2_source_codec_backend_v3 import SyntheticTransport, _datasets


OWNER = uuid.UUID("a1000000-0000-4000-8000-000000000001")


def _configured_store(path: Path) -> SQLiteAgentStore:
    root = Path(os.environ["P2_V3_STORE_TEST_ROOT"])
    component_root = root / "synthetic-cohort-components"
    component_root.mkdir(parents=True, exist_ok=True)
    component_path = component_root / "fixture.json"
    fixture_bytes = b'{"purpose":"isolated Store query acceptance CPU fixture"}'
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
        "profile_id": source_store.P2_V3_CANDIDATE_PROFILE_ID,
        "versions": pc.P2_V3_VERSIONS.model_dump(mode="json"),
        "schema_bundle_sha256": hashlib.sha256(b"synthetic-test-schema-bundle").hexdigest(),
        "source_manifest_sha256": hashlib.sha256(canonical(components)).hexdigest(),
        "contract_source_sha256": hashlib.sha256(b"synthetic-test-contract-snapshot").hexdigest(),
        "components": components,
        "safe_config": {"debt_source_variant": "expense_debt_line", "budgets": dict(cohort._BUDGETS)},
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
    ui = c.UIContext(page_type=c.PageType.HOME, captured_at=submitted_at, client_version="p2-v3-query-store")
    session = store.create_session(
        OWNER, c.CreateSessionRequest(client_request_id=uuid.uuid4(), title="P2 query CPU", ui_context=ui),
        now=submitted_at,
    ).response_snapshot.session.session_id
    submitted = store.submit_turn(
        OWNER, session,
        c.SubmitTurnRequest(client_request_id=uuid.uuid4(), text="Read my activities", ui_context=ui),
        now=submitted_at, candidate_profile_id=source_store.P2_V3_CANDIDATE_PROFILE_ID,
    )
    turn_id = submitted.response_snapshot.turn_id
    claimed = store.claim_runnable("p2v3-query-worker", candidate_profile_id=source_store.P2_V3_CANDIDATE_PROFILE_ID, now=now)
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
        candidate_profile_id=source_store.P2_V3_CANDIDATE_PROFILE_ID, now=now,
    )
    return turn_id, claimed.claim_token


def _adapter(
    store: SQLiteAgentStore,
    turn_id: uuid.UUID,
    claim_token: str,
    registry: object,
    *,
    datasets: dict[str, list[dict[str, Any]]] | None = None,
) -> backend.P2ReadBackendAdapter:
    datasets = datasets or _datasets()
    datasets["activity_members"][0]["user_id"] = str(OWNER)
    datasets["participant_claims"][0]["user_id"] = str(OWNER)
    return backend.P2ReadBackendAdapter(
        v1.P2BackendConfig(
            project_url="https://synthetic.invalid", publishable_key="sb_publishable_synthetic_cpu_only",
            timeout_seconds=2, page_size=16, max_pages=4, max_rows_per_query=64,
            max_requests_per_read=48, max_total_response_bytes=4_194_304,
            max_total_seconds=20, max_facts=16,
        ),
        transport=SyntheticTransport(datasets),
        v3_budget_port=P2V3StoreBudgetPort(store, OWNER, turn_id, claim_token),
        v3_locator_port=registry,
    )


def _request() -> pc.P2ReadQueryRequest:
    return pc.P2ReadQueryRequest(
        kind="read", message_type="query_request",
        profile_id=pc.P2_V3_CANDIDATE_PROFILE_ID,
        versions=pc.P2_V3_VERSIONS,
        operation=pc.P2ReadOperation.ACTIVITIES,
        criteria=pc.ActivityCriteria(kind="activities", status="any"),
        scope=None,
    )


def _scoped_request(operation: pc.P2ReadOperation, scope: pc.P2Scope) -> pc.P2ReadQueryRequest:
    activity_ref = str(scope.activity_ref)
    criteria: Any = {
        pc.P2ReadOperation.EXPENSES: pc.ExpenseCriteria(
            kind="expenses", activity_ref=activity_ref,
        ),
        pc.P2ReadOperation.DEBTS: pc.DebtCriteria(
            kind="debts", activity_ref=activity_ref,
        ),
        pc.P2ReadOperation.REFUND_EVENTS: pc.RefundEventCriteria(
            kind="refund_events", activity_ref=activity_ref,
        ),
        pc.P2ReadOperation.PREPAYMENT_ACCOUNTS: pc.PrepaymentAccountsCriteria(
            kind="prepayment_accounts", activity_ref=activity_ref,
        ),
        pc.P2ReadOperation.PREPAYMENT_USAGES: pc.PrepaymentUsagesCriteria(
            kind="prepayment_usages", activity_ref=activity_ref,
        ),
        pc.P2ReadOperation.PREPAYMENT_RETURN_EVENTS: pc.PrepaymentReturnCriteria(
            kind="prepayment_return_events", activity_ref=activity_ref,
        ),
    }[operation]
    return pc.P2ReadQueryRequest(
        kind="read", message_type="query_request",
        profile_id=pc.P2_V3_CANDIDATE_PROFILE_ID,
        versions=pc.P2_V3_VERSIONS,
        operation=operation, criteria=criteria, scope=scope,
    )


def _multi_expense_datasets(count: int = 18) -> dict[str, list[dict[str, Any]]]:
    datasets = _datasets()
    template = datasets["expenses"][0]
    payment_template = datasets["payments"][0]
    split_template = datasets["splits"][0]
    expenses: list[dict[str, Any]] = []
    payments: list[dict[str, Any]] = []
    splits: list[dict[str, Any]] = []
    for index in range(count):
        expense_id = uuid.uuid5(uuid.NAMESPACE_URL, f"p2-page-expense-{index}")
        expense = dict(template)
        expense.update({
            "id": str(expense_id),
            "title": f"合成分页账单 {index + 1}",
            "occurred_at": f"2026-10-14T00:{index:02d}:00+08:00",
            "original_expense_id": None,
        })
        expenses.append(expense)
        payment = dict(payment_template)
        payment.update({
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"p2-page-payment-{index}")),
            "expense_id": str(expense_id),
        })
        payments.append(payment)
        split = dict(split_template)
        split.update({
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"p2-page-split-{index}")),
            "expense_id": str(expense_id),
        })
        splits.append(split)
    datasets["expenses"] = expenses
    datasets["payments"] = payments
    datasets["splits"] = splits
    return datasets


def _query_and_attempt(
    store: SQLiteAgentStore,
    turn_id: uuid.UUID,
    claim_token: str,
    admission: codec.AdmissionOnlyBinding,
    request: pc.P2ReadQueryRequest,
    now: datetime,
) -> tuple[str, codec.QueryAttemptBinding]:
    with store._connection() as connection:
        revision = int(connection.execute(
            "SELECT revision FROM p2_v3_turns WHERE owner_user_id=? AND turn_id=?",
            (str(OWNER), str(turn_id)),
        ).fetchone()[0])
    logical_query_id = store.create_p2_v3_logical_query(
        OWNER, turn_id, claim_token=claim_token,
        admission_id=admission.admission_id,
        operation=request.operation.value, criteria=request.criteria,
        scope=request.scope, expected_revision=revision, now=now,
    )
    query_ref = store.bind_p2_v3_query_descriptor(
        OWNER, turn_id, claim_token=claim_token, admission=admission,
        request=request, logical_query_id=logical_query_id, now=now,
    )
    assert query_ref.startswith("ref_")
    attempt_id, attempt_seq = store.begin_p2_v3_query_attempt(
        OWNER, turn_id, claim_token=claim_token,
        logical_query_id=logical_query_id,
        admission_id=admission.admission_id,
        page_index=0, now=now,
    )
    return logical_query_id, codec.QueryAttemptBinding(
        identity=admission.identity, logical_query_id=logical_query_id,
        query_attempt_id=attempt_id, page_index=0, claim_token=claim_token,
    )


def test_store_reparses_activities_capture_and_issues_only_after_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("P2_V3_STORE_TEST_ROOT", str(tmp_path))
    store = _configured_store(tmp_path / "candidate.sqlite3")
    store.start()
    now = datetime.now(timezone.utc)
    turn_id, claim_token = _create_running_turn(store, now=now)
    try:
        admission, public_scope = store.create_p2_v3_request_admission(
            OWNER, turn_id, claim_token=claim_token, principal_user_id=OWNER,
            activity_id_hint=None, ledger_unit_id_hint=None, now=now,
        )
        assert public_scope is None
        request = _request()
        _, query_binding = _query_and_attempt(
            store, turn_id, claim_token, admission, request, now,
        )
        registry = admission.reference_registry
        grant = pc.P2SourceAuthorizationGrant(
            principal_ref=registry.principal_ref(),
            owner_turn_ref=registry.owner_turn_ref(identity=admission.identity),
            generation=admission.identity.generation,
            source_input_seq=admission.identity.input_seq,
            input_digest=admission.identity.input_digest,
            operation=request.operation,
            scope=None,
            criteria_digest=pc.p2_criteria_digest(request.criteria),
            expires_at=now + timedelta(minutes=2),
            grant_ref="ref_" + secrets.token_urlsafe(24),
        )
        verified = v1.VerifiedReadContext(
            owner_user_id=OWNER, turn_id=turn_id, principal_user_id=OWNER,
            access_token="synthetic.jwt.cpu", expires_at=now + timedelta(minutes=2),
            refs_by_opaque_token={},
        )
        adapter = _adapter(store, turn_id, claim_token, registry)
        pending = asyncio.run(adapter.read_candidate_v3(
            request, verified, grant, admission=admission,
            admission_projection=None, query_binding=query_binding,
            context_version="cpu-context-v3",
        ))
        assert isinstance(pending, backend.P2V3PendingSourceAttempt)
        assert len(pending.query_captures) >= 1
        assert not hasattr(pending.projection.historical.page, "next_page_ref")

        accepted = store.accept_p2_v3_query_attempt(
            OWNER, turn_id, claim_token=claim_token, principal_user_id=OWNER,
            pending=pending, now=now + timedelta(milliseconds=1),
        )
        assert accepted.query_result_receipt_id
        assert accepted.historical.query_evidence.operation is pc.P2ReadOperation.ACTIVITIES
        assert accepted.historical.page.items
        with store._connection() as connection:
            result_count = int(connection.execute(
                "SELECT COUNT(*) FROM p2_v3_query_result_receipts WHERE query_result_receipt_id=?",
                (accepted.query_result_receipt_id,),
            ).fetchone()[0])
            get_count = int(connection.execute(
                "SELECT COUNT(*) FROM p2_v3_query_result_gets WHERE query_result_receipt_id=?",
                (accepted.query_result_receipt_id,),
            ).fetchone()[0])
            proof_count = int(connection.execute(
                "SELECT COUNT(*) FROM p2_v3_activity_collection_qev_proofs WHERE query_result_receipt_id=?",
                (accepted.query_result_receipt_id,),
            ).fetchone()[0])
        assert (result_count, get_count, proof_count) == (1, len(pending.query_captures), 1)

        live = store.issue_p2_v3_page(
            OWNER, turn_id, claim_token=claim_token, accepted_page=accepted,
            now=now + timedelta(milliseconds=2),
        )
        assert isinstance(live, pc.P2ReadBackendResult)
        assert live.page.items == accepted.historical.page.items
        assert live.page.next_page_ref is None
        with pytest.raises(source_store.P2V3StoreConflict, match="fresh accepted result handle"):
            store.issue_p2_v3_page(
                OWNER, turn_id, claim_token=claim_token, accepted_page=accepted,
                now=now + timedelta(milliseconds=3),
            )

        output = pe.P2V3HistoricalAnswer(
            history_only=True,
            profile_id=pc.P2_V3_CANDIDATE_PROFILE_ID,
            versions=pc.P2_V3_VERSIONS,
            turn_ref=registry.owner_turn_ref(identity=admission.identity),
            generation=admission.identity.generation,
            read_epoch=1,
            context_ref=registry.owner_turn_ref(identity=admission.identity),
            context_digest=hashlib.sha256(b"synthetic-answer-context").hexdigest(),
            context_revision=admission.identity.context_revision,
            observed_at=accepted.historical.query_evidence.observed_at,
            simulation=accepted.historical.query_evidence.simulation,
            kind="answer",
            basis="fresh_read_receipts",
            text="These are the verified activities.",
            citations=(accepted.historical.query_evidence.query_evidence_ref,),
            query_evidence=(accepted.historical.query_evidence,),
            fact_cards=accepted.historical.page.items,
            source_labels=(),
            current_actor=None,
        )
        aggregate = store.get_turn(OWNER, turn_id)
        before = aggregate.record.turn
        after = before.model_copy(update={
            "state": c.TurnState.COMPLETED,
            "state_revision": before.state_revision + 1,
            "step": c.TurnStep.TERMINAL,
            "wait_reason": None,
            "resume_state": None,
        })
        checkpoint = aggregate.checkpoint.model_copy(update={
            "model_context": None,
            "last_decision": None,
            "last_clarification": None,
            "resume_step": None,
        })
        commit_at = now + timedelta(milliseconds=4)
        store.commit_p2_v3_protected_output(
            OWNER, after,
            expected_state_revision=before.state_revision,
            expected_checkpoint_revision=aggregate.checkpoint_revision,
            claim_token=claim_token,
            checkpoint=checkpoint,
            events=[
                EventDraft(
                    type=c.EventType.MESSAGE,
                    occurred_at=commit_at,
                    simulation=output.simulation,
                    payload=c.MessageEventPayload(text=output.text, citations=[]),
                ),
                _status(after, commit_at),
            ],
            accepted_page=accepted,
            historical_output=output,
            gate=AgentControlSnapshot(enabled=True, disable_revision=0, source="simulation"),
            now=commit_at,
        )
        assert accepted._issue_state["protected_output_committed"] is True
        with store._connection() as connection:
            protected = connection.execute(
                "SELECT * FROM p2_v3_protected_outputs WHERE owner_user_id=? AND turn_id=?",
                (str(OWNER), str(turn_id)),
            ).fetchone()
            fact_link_count = int(connection.execute(
                "SELECT COUNT(*) FROM p2_v3_output_fact_links WHERE protected_output_id=?",
                (protected["protected_output_id"],),
            ).fetchone()[0])
            query_link_count = int(connection.execute(
                "SELECT COUNT(*) FROM p2_v3_output_query_links WHERE protected_output_id=?",
                (protected["protected_output_id"],),
            ).fetchone()[0])
            event_link_count = int(connection.execute(
                "SELECT COUNT(*) FROM p2_v3_output_event_links WHERE protected_output_id=?",
                (protected["protected_output_id"],),
            ).fetchone()[0])
        assert protected["output_kind"] == "answer"
        assert protected["provenance_kind"] == "source_bearing"
        assert (fact_link_count, query_link_count, event_link_count) == (len(output.fact_cards), 1, 1)
        stored_output = store.get_p2_v3_protected_event_activity_ids(
            OWNER, turn_id, event_seq=int(protected["event_seq"]),
        )
        expected_activity_ids = tuple(
            registry.resolve_activity_ref(str(item.activity_ref))
            for item in accepted.historical.page.items
        )
        assert stored_output is not None
        assert stored_output.profile_id == pc.P2_V3_CANDIDATE_PROFILE_ID
        assert stored_output.event_seq == int(protected["event_seq"])
        assert stored_output.historical == output
        assert stored_output.activity_ids == expected_activity_ids
        assert store.get_p2_v3_protected_event_activity_ids(
            OWNER, turn_id, event_seq=int(protected["event_seq"]) + 1,
        ) is None
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.COMPLETED
    finally:
        store.close()


@pytest.mark.parametrize("operation", [
    pc.P2ReadOperation.EXPENSES,
    pc.P2ReadOperation.DEBTS,
    pc.P2ReadOperation.REFUND_EVENTS,
    pc.P2ReadOperation.PREPAYMENT_ACCOUNTS,
    pc.P2ReadOperation.PREPAYMENT_USAGES,
    pc.P2ReadOperation.PREPAYMENT_RETURN_EVENTS,
])
def test_store_accepts_scoped_financial_get_chains(operation: pc.P2ReadOperation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("P2_V3_STORE_TEST_ROOT", str(tmp_path))
    database_path = tmp_path / f"{operation.value.rsplit('.', 1)[-1]}.sqlite3"
    store = _configured_store(database_path)
    if operation is pc.P2ReadOperation.EXPENSES:
        store._migrations = store._migrations[:5]
        store.start()
        with store._connection() as connection:
            assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == 5
        store.close()
        store = _configured_store(database_path)
    store.start()
    with store._connection() as connection:
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == 6
    now = datetime.now(timezone.utc)
    turn_id, claim_token = _create_running_turn(store, now=now)
    datasets = _datasets()
    activity_id = uuid.UUID(datasets["activities"][0]["id"])
    unit_id = uuid.UUID(datasets["ledger_units"][0]["id"])
    try:
        admission, scope = store.create_p2_v3_request_admission(
            OWNER, turn_id, claim_token=claim_token, principal_user_id=OWNER,
            activity_id_hint=activity_id, ledger_unit_id_hint=unit_id, now=now,
        )
        assert scope is not None
        adapter = _adapter(store, turn_id, claim_token, admission.reference_registry)
        verified = v1.VerifiedReadContext(
            owner_user_id=OWNER, turn_id=turn_id, principal_user_id=OWNER,
            access_token="synthetic.jwt.cpu", expires_at=now + timedelta(minutes=2),
            refs_by_opaque_token={},
        )
        admission_projection = asyncio.run(adapter.admit_scope_v3(
            verified, admission, ui_activity_id_hint=activity_id,
            ui_ledger_unit_id_hint=unit_id,
        ))
        assert admission_projection is not None
        request = _scoped_request(operation, scope)
        _, query_binding = _query_and_attempt(
            store, turn_id, claim_token, admission, request, now,
        )
        registry = admission.reference_registry
        grant = pc.P2SourceAuthorizationGrant(
            principal_ref=registry.principal_ref(),
            owner_turn_ref=registry.owner_turn_ref(identity=admission.identity),
            generation=admission.identity.generation,
            source_input_seq=admission.identity.input_seq,
            input_digest=admission.identity.input_digest,
            operation=operation, scope=scope,
            criteria_digest=pc.p2_criteria_digest(request.criteria),
            expires_at=now + timedelta(minutes=2),
            grant_ref="ref_" + secrets.token_urlsafe(24),
        )
        pending = asyncio.run(adapter.read_candidate_v3(
            request, verified, grant, admission=admission,
            admission_projection=admission_projection,
            query_binding=query_binding, context_version="cpu-context-v3",
        ))
        assert isinstance(pending, backend.P2V3PendingSourceAttempt)
        accepted = store.accept_p2_v3_query_attempt(
            OWNER, turn_id, claim_token=claim_token, principal_user_id=OWNER,
            pending=pending, now=now + timedelta(milliseconds=1),
        )
        assert accepted.historical.query_evidence.operation is operation
        assert accepted.historical.query_evidence.source_query_complete is True
        assert accepted.historical.page.has_more is False
        assert accepted.historical.page.items
        live = store.issue_p2_v3_page(
            OWNER, turn_id, claim_token=claim_token, accepted_page=accepted,
            now=now + timedelta(milliseconds=2),
        )
        assert live.page.items == accepted.historical.page.items
        with store._connection() as connection:
            assert connection.execute(
                "SELECT 1 FROM p2_v3_query_result_receipts WHERE query_result_receipt_id=?",
                (accepted.query_result_receipt_id,),
            ).fetchone() is not None
    finally:
        store.close()


def test_store_issues_and_accepts_one_scoped_continuation_with_terminal_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("P2_V3_STORE_TEST_ROOT", str(tmp_path))
    store = _configured_store(tmp_path / "one-continuation.sqlite3")
    store.start()
    now = datetime.now(timezone.utc)
    turn_id, claim_token = _create_running_turn(store, now=now)
    datasets = _multi_expense_datasets()
    activity_id = uuid.UUID(datasets["activities"][0]["id"])
    unit_id = uuid.UUID(datasets["ledger_units"][0]["id"])
    try:
        admission, scope = store.create_p2_v3_request_admission(
            OWNER, turn_id, claim_token=claim_token, principal_user_id=OWNER,
            activity_id_hint=activity_id, ledger_unit_id_hint=unit_id, now=now,
        )
        assert scope is not None
        registry = admission.reference_registry
        adapter = _adapter(
            store, turn_id, claim_token, registry, datasets=datasets,
        )
        verified = v1.VerifiedReadContext(
            owner_user_id=OWNER, turn_id=turn_id, principal_user_id=OWNER,
            access_token="synthetic.jwt.cpu", expires_at=now + timedelta(minutes=2),
            refs_by_opaque_token={},
        )
        admission_projection = asyncio.run(adapter.admit_scope_v3(
            verified, admission, ui_activity_id_hint=activity_id,
            ui_ledger_unit_id_hint=unit_id,
        ))
        request = _scoped_request(pc.P2ReadOperation.EXPENSES, scope)
        _, query_binding = _query_and_attempt(
            store, turn_id, claim_token, admission, request, now,
        )
        grant = pc.P2SourceAuthorizationGrant(
            principal_ref=registry.principal_ref(),
            owner_turn_ref=registry.owner_turn_ref(identity=admission.identity),
            generation=admission.identity.generation,
            source_input_seq=admission.identity.input_seq,
            input_digest=admission.identity.input_digest,
            operation=request.operation, scope=scope,
            criteria_digest=pc.p2_criteria_digest(request.criteria),
            expires_at=now + timedelta(minutes=2),
            grant_ref="ref_" + secrets.token_urlsafe(24),
        )

        pending0 = asyncio.run(adapter.read_candidate_v3(
            request, verified, grant, admission=admission,
            admission_projection=admission_projection,
            query_binding=query_binding, context_version="cpu-context-v3",
        ))
        accepted0 = store.accept_p2_v3_query_attempt(
            OWNER, turn_id, claim_token=claim_token, principal_user_id=OWNER,
            pending=pending0, now=now + timedelta(milliseconds=1),
        )
        assert accepted0.historical.page.page_index == 0
        assert accepted0.historical.page.has_more is True
        assert len(accepted0.historical.page.items) == 16
        assert len(accepted0.historical.query_evidence.matching_fact_refs) == 18
        live0 = store.issue_p2_v3_page(
            OWNER, turn_id, claim_token=claim_token, accepted_page=accepted0,
            now=now + timedelta(milliseconds=2),
        )
        assert live0.page.has_more is True
        assert live0.page.next_page_ref is not None

        continue_request = pc.P2ReadContinueRequest(
            kind="read", message_type="continue_request",
            profile_id=pc.P2_V3_CANDIDATE_PROFILE_ID, versions=pc.P2_V3_VERSIONS,
            query_ref=live0.query_evidence.query_ref,
            next_page_ref=live0.page.next_page_ref,
        )
        pending1 = asyncio.run(adapter.read_candidate_v3(
            continue_request, verified, grant, admission=admission,
            admission_projection=admission_projection, context_version="cpu-context-v3",
        ))
        assert pending1.previous_proof is not None
        assert pending1.query_binding.page_index == 1
        accepted1 = store.accept_p2_v3_query_attempt(
            OWNER, turn_id, claim_token=claim_token, principal_user_id=OWNER,
            pending=pending1, now=now + timedelta(milliseconds=3),
        )
        assert accepted1.historical.page.page_index == 1
        assert accepted1.historical.page.has_more is False
        assert len(accepted1.historical.page.items) == 2
        live1 = store.issue_p2_v3_page(
            OWNER, turn_id, claim_token=claim_token, accepted_page=accepted1,
            now=now + timedelta(milliseconds=4),
        )
        assert live1.page.has_more is False
        assert live1.page.next_page_ref is None
        with pytest.raises(source_store.P2V3StoreConflict, match="already consumed"):
            registry.consume_continuation(
                query_ref=live0.query_evidence.query_ref,
                next_page_ref=live0.page.next_page_ref,
                turn_id=turn_id,
            )

        terminal_qev = accepted1.historical.query_evidence
        all_cards = tuple(
            fact.model_copy(update={"query_evidence_ref": terminal_qev.query_evidence_ref})
            for fact in accepted0.historical.page.items + accepted1.historical.page.items
        )
        # The accepted admission metadata is the only legal source of a public
        # answer's labels and actor: the Store commit binds this answer to that
        # durable acceptance projection, so the test must carry it verbatim
        # rather than inventing metadata.
        accepted_projection = accepted1._registry.accepted_metadata_projection_or_none(
            identity=admission.identity, admission_id=accepted1._admission_id,
        )
        assert accepted_projection is not None
        output = pe.P2V3HistoricalAnswer(
            history_only=True,
            profile_id=pc.P2_V3_CANDIDATE_PROFILE_ID,
            versions=pc.P2_V3_VERSIONS,
            turn_ref=registry.owner_turn_ref(identity=admission.identity),
            generation=admission.identity.generation,
            read_epoch=1,
            context_ref=registry.owner_turn_ref(identity=admission.identity),
            context_digest=hashlib.sha256(b"synthetic-paged-answer-context").hexdigest(),
            context_revision=admission.identity.context_revision,
            observed_at=terminal_qev.observed_at,
            simulation=terminal_qev.simulation,
            kind="answer",
            basis="fresh_read_receipts",
            text="These are the verified expenses across both accepted pages.",
            citations=(terminal_qev.query_evidence_ref,),
            query_evidence=(terminal_qev,),
            fact_cards=all_cards,
            source_labels=tuple(accepted_projection.source_labels),
            current_actor=accepted_projection.current_actor,
        )
        aggregate = store.get_turn(OWNER, turn_id)
        before = aggregate.record.turn
        after = before.model_copy(update={
            "state": c.TurnState.COMPLETED,
            "state_revision": before.state_revision + 1,
            "step": c.TurnStep.TERMINAL,
            "wait_reason": None,
            "resume_state": None,
        })
        checkpoint = aggregate.checkpoint.model_copy(update={
            "model_context": None, "last_decision": None,
            "last_clarification": None, "resume_step": None,
        })
        commit_at = now + timedelta(milliseconds=5)
        store.commit_p2_v3_protected_output(
            OWNER, after,
            expected_state_revision=before.state_revision,
            expected_checkpoint_revision=aggregate.checkpoint_revision,
            claim_token=claim_token,
            checkpoint=checkpoint,
            events=[
                EventDraft(
                    type=c.EventType.MESSAGE, occurred_at=commit_at,
                    simulation=output.simulation,
                    payload=c.MessageEventPayload(text=output.text, citations=[]),
                ),
                _status(after, commit_at),
            ],
            accepted_page=accepted1,
            historical_output=output,
            gate=AgentControlSnapshot(enabled=True, disable_revision=0, source="simulation"),
            now=commit_at,
        )
        with store._connection() as connection:
            protected = connection.execute(
                "SELECT * FROM p2_v3_protected_outputs WHERE owner_user_id=? AND turn_id=?",
                (str(OWNER), str(turn_id)),
            ).fetchone()
            proof_count = int(connection.execute(
                "SELECT COUNT(*) FROM p2_v3_query_fact_proofs WHERE query_result_receipt_id=?",
                (accepted1.query_result_receipt_id,),
            ).fetchone()[0])
        assert proof_count == 18
        stored = store.get_p2_v3_protected_event_activity_ids(
            OWNER, turn_id, event_seq=int(protected["event_seq"]),
        )
        assert stored is not None and stored.historical == output
        assert stored.activity_ids == (activity_id,)
    finally:
        store.close()
