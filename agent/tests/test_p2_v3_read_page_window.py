"""P2 v3 read-page window: bounded continuation and fail-closed truncation.

The runtime projects a v3 read as a bounded chain of model pages. This file
covers the derived bound, a complete two-page read (per-page model charge,
single-use continuation nonce, terminal page), the fail-closed path when the
source result cannot be served within the bound, and the Store gates that still
cap a read at page zero plus one continuation page.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import contracts as c
from app import p2_backend as v1
from app import p2_read_contracts_v3 as pc3
from app import p2_source_codec_v3 as codec3
from app import p2_source_store_v3 as source_store
from app.components import AppComponents, _CandidateProfileStore
from app.main import create_app
from app.p2_backend import BackendReadError, P2BackendConfig
from app.p2_journal import P2ErrorProofJournal
from app.p2_read_backend import MAX_PAGES_PER_QUERY
from app.p2_read_prompt_v3 import P2V3PromptBuildConfig
from app.p2_runtime import (
    P2Runtime, _V3_MIN_PAGED_READ_MODEL_CALLS, _v3_read_page_window,
)
from app.settings import Settings
from test_p2_runtime import OWNER, TOKEN, _Auth, _Backend, _Provider
from test_p2_source_codec_backend_v3 import SyntheticTransport
from test_p2_v3_query_store_acceptance import (
    OWNER as STORE_OWNER, _adapter, _configured_store, _create_running_turn,
    _multi_expense_datasets, _query_and_attempt, _scoped_request,
)
from test_p2_v3_runtime_activity_flow import _record_test_v3_dispatch, _TrustedControl
from test_p2_v3_runtime_semantics import _events, _new_session, _submit


class _PagingProvider:
    """Deterministic model: select the scoped read, take every continuation the
    server mints, then cite the terminal receipt. It never invents a page ref."""

    def __init__(self) -> None:
        self.contexts: list[Any] = []

    async def prepare(self) -> None:
        return None

    async def generate(
        self, public: Any, private: Any, prepared: Any, *,
        before_dispatch: Any, on_transport_result: Any,
    ) -> str:
        _record_test_v3_dispatch(prepared, before_dispatch, on_transport_result)
        self.contexts.append(public)
        if public.continuations:
            assert public.guard.allowed_decision_kinds == ("read",)
            hint = public.continuations[0]
            return json.dumps({
                "kind": "read",
                "message_type": "continue_request",
                "profile_id": public.profile_id,
                "versions": public.versions.model_dump(mode="json"),
                "query_ref": str(hint.query_ref),
                "next_page_ref": str(hint.next_page_ref),
            })
        if public.query_evidence:
            assert public.guard.allowed_decision_kinds == ("answer",)
            return json.dumps({
                "kind": "answer",
                "basis": "fresh_read_receipts",
                "text": "已读取所选活动的消费记录。",
                "citations": [str(private.fresh_receipt_refs[0].query_evidence_ref)],
            }, ensure_ascii=False)
        assert pc3.P2ReadOperation.EXPENSES in public.guard.allowed_read_operations
        scope = public.scope_authorization.scope
        assert public.scope_authorization.status == "verified" and scope is not None
        return json.dumps({
            "kind": "read",
            "message_type": "query_request",
            "profile_id": public.profile_id,
            "versions": public.versions.model_dump(mode="json"),
            "operation": "read.expenses",
            "criteria": {"kind": "expenses", "activity_ref": str(scope.activity_ref)},
            "scope": scope.model_dump(mode="json"),
        })


def _harness(
    tmp_path: Path, monkeypatch: Any, fact_count: int,
) -> tuple[AppComponents, _PagingProvider, Path]:
    monkeypatch.setenv("P2_V3_STORE_TEST_ROOT", str(tmp_path))
    database = tmp_path / f"page-window-{fact_count}.sqlite3"
    store = _configured_store(database)
    rows = _multi_expense_datasets(fact_count)
    rows["activity_members"][0]["user_id"] = str(OWNER)
    rows["participant_claims"][0]["user_id"] = str(OWNER)

    backend_adapter = _Backend()
    backend_adapter._transport = SyntheticTransport(rows)

    async def authorize_api_scope(
        principal_id: uuid.UUID, activity_ids: tuple[uuid.UUID, ...],
        access_token: str, expires_at: Any,
    ) -> None:
        if principal_id != OWNER or access_token != TOKEN or expires_at is None:
            raise BackendReadError("invalid_auth_context")
        memberships = {
            uuid.UUID(row["activity_id"])
            for row in rows["activity_members"]
            if row["user_id"] == str(OWNER)
        }
        if not set(activity_ids).issubset(memberships):
            raise BackendReadError("access_denied")

    backend_adapter.authorize_api_scope = authorize_api_scope
    auth = _Auth()
    control = _TrustedControl()
    provider = _PagingProvider()
    runtime = P2Runtime(
        store, _Provider(), backend_adapter, auth, control,
        P2ErrorProofJournal(database.with_suffix(".journal.sqlite3")),
        model_timeout_seconds=3,
        v3_provider=provider,
        v3_prompt_config=P2V3PromptBuildConfig(
            model_id="synthetic-cpu-model",
            endpoint_url="http://127.0.0.1:1234/v1/chat/completions",
        ),
        v3_backend_config=P2BackendConfig(
            project_url="https://synthetic.invalid",
            publishable_key="sb_publishable_synthetic_cpu_only",
            timeout_seconds=2, page_size=16, max_pages=4, max_rows_per_query=64,
            max_requests_per_read=48, max_total_response_bytes=4_194_304,
            max_total_seconds=20, max_facts=16,
        ),
        enabled_candidate_profile_ids=(pc3.P2_V3_CANDIDATE_PROFILE_ID,),
    )
    components = AppComponents(
        store=_CandidateProfileStore(store, pc3.P2_V3_CANDIDATE_PROFILE_ID),
        provider=_Provider(), backend=backend_adapter, runtime=runtime,
        gateway=object(), auth_verifier=auth, agent_control=control,
    )
    return components, provider, database


def _client_app(components: AppComponents, database: Path) -> Any:
    settings = Settings(
        storage_path=database, provider_mode="mock", agent_enabled=True,
        disable_revision=0, api_requests_per_minute=500,
    )
    return create_app(settings, components_factory=lambda _: components)


def _terminal(components: AppComponents, turn_id: uuid.UUID, timeout: float = 30.0) -> Any:
    deadline = time.monotonic() + timeout
    aggregate = None
    while time.monotonic() < deadline:
        aggregate = components.store.get_turn(OWNER, turn_id)
        if aggregate.record.turn.state in (
            c.TurnState.COMPLETED, c.TurnState.FAILED, c.TurnState.CANCELLED,
        ):
            return aggregate
        time.sleep(0.02)
    assert aggregate is not None
    return aggregate


def _page_receipts(components: AppComponents, turn_id: uuid.UUID) -> list[tuple[int, int]]:
    with components.store._connection() as connection:
        rows = connection.execute(
            "SELECT page_index, has_more FROM p2_v3_query_result_receipts "
            "WHERE owner_user_id=? AND turn_id=? ORDER BY page_index",
            (str(OWNER), str(turn_id)),
        ).fetchall()
    return [(int(row["page_index"]), int(row["has_more"])) for row in rows]


def _continuation_nonces(components: AppComponents, turn_id: uuid.UUID) -> tuple[int, int]:
    with components.store._connection() as connection:
        issued = int(connection.execute(
            "SELECT COUNT(*) FROM p2_v3_continuation_nonce_issues WHERE turn_id=?",
            (str(turn_id),),
        ).fetchone()[0])
        consumed = int(connection.execute(
            "SELECT COUNT(*) FROM p2_v3_continuation_nonce_uses WHERE turn_id=?",
            (str(turn_id),),
        ).fetchone()[0])
    return issued, consumed


def test_v3_read_page_window_is_derived_from_existing_budgets() -> None:
    """The page window is the minimum of budgets that already exist."""
    projection_pages = codec3.MAX_FACTS_PER_QUERY // codec3.MAX_FACTS_PER_PAGE
    assert projection_pages == MAX_PAGES_PER_QUERY == 4

    # The default Turn budget (six model calls) affords five pages, so the
    # tighter projection bound decides: four pages, never more.
    assert _v3_read_page_window(6) == 4
    assert _v3_read_page_window(5) == 4
    assert _v3_read_page_window(4) == 3
    assert _v3_read_page_window(3) == 2
    assert _v3_read_page_window(2) == 1
    # A single-page read stays representable at the smallest budget.
    assert _v3_read_page_window(1) == 1

    for max_model_calls in range(2, 7):
        window = _v3_read_page_window(max_model_calls)
        assert 1 <= window <= projection_pages
        # One model call selects the query, one per continuation page, one
        # answers: the window can never exceed what the budget can pay for.
        assert window + 1 <= max_model_calls

    # A planned read reserves the smallest read that can continue at all; the
    # reservation is a floor, not the window's worst case.
    assert _V3_MIN_PAGED_READ_MODEL_CALLS == 3


def test_v3_read_projects_both_pages_charges_each_and_terminates(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    """A source result that ends inside the window is answered in full."""
    components, model, database = _harness(tmp_path, monkeypatch, 20)
    app = _client_app(components, database)
    with TestClient(app) as client:
        session_id = _new_session(client)
        turn_id = _submit(client, session_id, "查询这个活动的消费", selected_activity=True)
        aggregate = _terminal(components, turn_id)
        assert aggregate.record.turn.state is c.TurnState.COMPLETED
        # Selection, one continuation and the answer are all charged; the
        # checkpoint reservation matches the two-page sequence exactly.
        assert components.store.get_p2_v3_snapshot(OWNER, turn_id).model_calls == 3
        assert aggregate.checkpoint.model_calls == _V3_MIN_PAGED_READ_MODEL_CALLS == 3
        assert aggregate.checkpoint.read_calls == 1
        assert len(model.contexts) == 3

        page_request = model.contexts[1]
        assert len(page_request.facts) == 16
        assert page_request.query_evidence[0].page.has_more is True
        assert len(page_request.continuations) == 1
        final = model.contexts[2]
        assert len(final.facts) == 20
        assert final.guard.allowed_decision_kinds == ("answer",)
        assert all(item.query_evidence_ref == final.query_evidence[0].query_evidence_ref
                   for item in final.facts)

        result = _events(client, turn_id)
        messages = [item for item in result["events"] if item["type"] == "message"]
        assert len(messages) == 1
        for index in (1, 16, 17, 20):
            assert f"合成分页账单 {index}" in messages[0]["payload"]["text"]

        stored = components.store.get_p2_v3_protected_event_activity_ids(
            OWNER, turn_id, event_seq=messages[0]["seq"],
        )
        assert stored is not None
        terminal_qev = stored.historical.query_evidence
        assert len(terminal_qev) == 1
        assert terminal_qev[0].page.has_more is False
        assert terminal_qev[0].page.model_projection_complete is True
        assert terminal_qev[0].page.truncated is False
        assert len(terminal_qev[0].matching_fact_refs) == 20
        assert len(stored.historical.fact_cards) == 20

        assert _page_receipts(components, turn_id) == [(0, 1), (1, 0)]
        # Every continuation the Store minted was consumed exactly once.
        assert _continuation_nonces(components, turn_id) == (1, 1)


def test_v3_read_beyond_the_bound_fails_closed_without_a_partial_answer(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    """33 matching facts need a third page, which this candidate cannot serve."""
    components, model, database = _harness(tmp_path, monkeypatch, 33)
    app = _client_app(components, database)
    with TestClient(app) as client:
        session_id = _new_session(client)
        turn_id = _submit(client, session_id, "查询这个活动的消费", selected_activity=True)
        aggregate = _terminal(components, turn_id)
        assert aggregate.record.turn.state is c.TurnState.FAILED

        result = _events(client, turn_id)
        assert "message" not in [item["type"] for item in result["events"]]
        errors = [item for item in result["events"] if item["type"] == "error"]
        assert len(errors) == 1
        # The Store rejected the projection at its capacity bound, so this is a
        # capability limit of the bounded read and not a retryable failure.
        payload = errors[0]["payload"]
        assert payload["code"] == "dependency_unavailable"
        assert payload["message"] == (
            "P2 result reference capacity reached; submit a narrower new Turn."
        )
        assert payload["retryable"] is False

        # The model selected the query once and was never asked to continue a
        # result the candidate cannot finish; the answer stage never ran.
        assert len(model.contexts) == 1
        assert components.store.get_p2_v3_snapshot(OWNER, turn_id).model_calls == 1
        assert aggregate.checkpoint.model_calls == _V3_MIN_PAGED_READ_MODEL_CALLS

        with components.store._connection() as connection:
            protected = int(connection.execute(
                "SELECT COUNT(*) FROM p2_v3_protected_outputs "
                "WHERE owner_user_id=? AND turn_id=?",
                (str(OWNER), str(turn_id)),
            ).fetchone()[0])
        # No page was accepted, so nothing could be answered from a truncation.
        assert protected == 0
        assert _page_receipts(components, turn_id) == []
        assert _continuation_nonces(components, turn_id) == (0, 0)


def test_v3_truncation_at_the_page_window_fails_closed(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    """The window edge itself: a page that still has more is never answered.

    The Store currently refuses any read that needs a third page, so the bound
    is driven to its minimum here to reach the runtime's own guard. Production
    keeps the derived window (_v3_read_page_window(6) == 4).
    """
    import app.p2_runtime as runtime_module

    assert _v3_read_page_window(6) == 4
    monkeypatch.setattr(runtime_module, "_v3_read_page_window", lambda _: 1)
    components, model, database = _harness(tmp_path, monkeypatch, 20)
    app = _client_app(components, database)
    with TestClient(app) as client:
        session_id = _new_session(client)
        turn_id = _submit(client, session_id, "查询这个活动的消费", selected_activity=True)
        aggregate = _terminal(components, turn_id)
        assert aggregate.record.turn.state is c.TurnState.FAILED

        result = _events(client, turn_id)
        assert "message" not in [item["type"] for item in result["events"]]
        errors = [item for item in result["events"] if item["type"] == "error"]
        assert len(errors) == 1
        # A window-truncated read is a capability limit, not a retryable
        # dependency failure: the identical Turn cannot succeed, so the client
        # must be told to narrow the query instead of retrying it.
        payload = errors[0]["payload"]
        assert payload["code"] == "dependency_unavailable"
        assert payload["message"] == (
            "P2 result reference capacity reached; submit a narrower new Turn."
        )
        assert payload["retryable"] is False

        # The one-page window was reached with the first page and the runtime
        # stopped there: no continuation decision was requested, and the Store
        # accepted a page whose continuation flag it then refused to act on.
        assert len(model.contexts) == 1
        assert components.store.get_p2_v3_snapshot(OWNER, turn_id).model_calls == 1
        assert _page_receipts(components, turn_id) == [(0, 1)]
        # The Store minted the continuation for the page it issued -- the only
        # legitimate source of a next_page_ref -- and the runtime stopped before
        # consuming it, because it cannot complete the read.
        assert _continuation_nonces(components, turn_id) == (1, 0)
        with components.store._connection() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM p2_v3_protected_outputs "
                "WHERE owner_user_id=? AND turn_id=?",
                (str(OWNER), str(turn_id)),
            ).fetchone()[0] == 0
            attempts = [tuple(row) for row in connection.execute(
                "SELECT attempt_seq, page_index FROM p2_v3_query_attempts "
                "WHERE owner_user_id=? AND turn_id=? ORDER BY attempt_seq, page_index",
                (str(OWNER), str(turn_id)),
            ).fetchall()]
        assert attempts == [(1, 0)]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known gap, not caused by the page window: MessageEventPayload.text is "
        "capped at 2000 characters, so a legal two-page read of 24 facts cannot "
        "be rendered. The overflow is now classified as the non-retryable "
        "capability result 'P2 capability unavailable: this query cannot be "
        "represented safely.', so the client is no longer told to retry; the "
        "answer still cannot be produced. Remove this marker when the answer "
        "projection and that cap agree."
    ),
)
def test_v3_two_page_read_of_24_facts_can_be_rendered(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    components, model, database = _harness(tmp_path, monkeypatch, 24)
    app = _client_app(components, database)
    with TestClient(app) as client:
        session_id = _new_session(client)
        turn_id = _submit(client, session_id, "查询这个活动的消费", selected_activity=True)
        aggregate = _terminal(components, turn_id)
        assert len(model.contexts) == 3
        assert _page_receipts(components, turn_id) == [(0, 1), (1, 0)]
        assert aggregate.record.turn.state is c.TurnState.COMPLETED
        result = _events(client, turn_id)
        messages = [item for item in result["events"] if item["type"] == "message"]
        assert len(messages) == 1
        assert "合成分页账单 24" in messages[0]["payload"]["text"]


def test_store_gates_still_cap_a_read_at_one_continuation_page(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    """Evidence for the remaining gap: the Store, not the Runtime, bounds a read
    to page zero plus one continuation page."""
    monkeypatch.setenv("P2_V3_STORE_TEST_ROOT", str(tmp_path))
    store = _configured_store(tmp_path / "page-window-store.sqlite3")
    store.start()
    now = datetime.now(timezone.utc)
    turn_id, claim_token = _create_running_turn(store, now=now)
    try:
        with pytest.raises(source_store.P2V3StoreConflict, match="atomically consume"):
            store.begin_p2_v3_query_attempt(
                STORE_OWNER, turn_id, claim_token=claim_token,
                logical_query_id="query", admission_id="admission",
                page_index=2, now=now,
            )
        with pytest.raises(source_store.P2V3StoreConflict, match="one continuation page"):
            store.consume_p2_v3_continuation(
                STORE_OWNER, turn_id, claim_token=claim_token,
                logical_query_id="query", raw_next_page_ref="ref_" + "a" * 24,
                admission_id="admission", attempt_seq=1, page_index=2,
                source_proof_sha256="0" * 64, projection_sha256="0" * 64, now=now,
            )

        # A page-zero projection that would need a third page is rejected before
        # any receipt exists, so the runtime can never be handed that read.
        datasets = _multi_expense_datasets(33)
        activity_id = uuid.UUID(datasets["activities"][0]["id"])
        unit_id = uuid.UUID(datasets["ledger_units"][0]["id"])
        admission, scope = store.create_p2_v3_request_admission(
            STORE_OWNER, turn_id, claim_token=claim_token, principal_user_id=STORE_OWNER,
            activity_id_hint=activity_id, ledger_unit_id_hint=unit_id, now=now,
        )
        assert scope is not None
        registry = admission.reference_registry
        adapter = _adapter(store, turn_id, claim_token, registry, datasets=datasets)
        verified = v1.VerifiedReadContext(
            owner_user_id=STORE_OWNER, turn_id=turn_id, principal_user_id=STORE_OWNER,
            access_token="synthetic.jwt.cpu", expires_at=now + timedelta(minutes=2),
            refs_by_opaque_token={},
        )
        admission_projection = asyncio.run(adapter.admit_scope_v3(
            verified, admission, ui_activity_id_hint=activity_id,
            ui_ledger_unit_id_hint=unit_id,
        ))
        request = _scoped_request(pc3.P2ReadOperation.EXPENSES, scope)
        _, query_binding = _query_and_attempt(
            store, turn_id, claim_token, admission, request, now,
        )
        grant = pc3.P2SourceAuthorizationGrant(
            principal_ref=registry.principal_ref(),
            owner_turn_ref=registry.owner_turn_ref(identity=admission.identity),
            generation=admission.identity.generation,
            source_input_seq=admission.identity.input_seq,
            input_digest=admission.identity.input_digest,
            operation=request.operation, scope=scope,
            criteria_digest=pc3.p2_criteria_digest(request.criteria),
            expires_at=now + timedelta(minutes=2),
            grant_ref="ref_" + secrets.token_urlsafe(24),
        )
        pending = asyncio.run(adapter.read_candidate_v3(
            request, verified, grant, admission=admission,
            admission_projection=admission_projection, query_binding=query_binding,
            context_version="cpu-page-window",
        ))
        assert pending.projection.historical.page.has_more is True
        assert len(pending.projection.historical.query_evidence.matching_fact_refs) == 33
        with pytest.raises(
            source_store.P2V3StoreConflict, match="one-continuation source bound",
        ):
            store.accept_p2_v3_query_attempt(
                STORE_OWNER, turn_id, claim_token=claim_token,
                principal_user_id=STORE_OWNER, pending=pending,
                now=now + timedelta(milliseconds=1),
            )
        with store._connection() as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM p2_v3_query_result_receipts WHERE turn_id=?",
                (str(turn_id),),
            ).fetchone()[0] == 0
    finally:
        store.close()
