from __future__ import annotations

import json
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app import contracts as c
from app import p2_read_contracts_v3 as pc3
from app.components import AppComponents, _CandidateProfileStore
from app.main import create_app
from app.p2_backend import BackendReadError, P2BackendConfig
from app.p2_journal import P2ErrorProofJournal
from app.p2_model_provider import LMStudioTransportObservation
from app.p2_read_prompt_v3 import P2V3PromptBuildConfig
from app.p2_runtime import P2Runtime
from app.p2_token_budget import P2TokenBudgetMeasurement
from app.ports import AgentControlSnapshot
from app.settings import Settings
from app.store import EventDraft
from test_p2_runtime import OWNER, TOKEN, _Auth, _Backend, _Provider, _wait
from test_p2_source_codec_backend_v3 import ACTIVITY, SyntheticTransport
from test_p2_v3_query_store_acceptance import _configured_store, _multi_expense_datasets


class _SemanticProvider:
    """Deterministic fake model for the public Runtime/API semantic paths."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.contexts: list[pc3.P2ModelContext] = []
        self.private_contexts: list[pc3.P2IntentContext] = []

    async def prepare(self) -> None:
        return None

    async def generate(
        self,
        public: pc3.P2ModelContext,
        private: pc3.P2IntentContext,
        prepared: Any,
        *,
        before_dispatch: Any,
        on_transport_result: Any,
    ) -> str:
        self.contexts.append(public)
        self.private_contexts.append(private)
        measurement = P2TokenBudgetMeasurement(
            model_key=prepared.config.model_id,
            api_host="http://127.0.0.1:1234",
            artifact_path="synthetic-cpu-fixture",
            artifact_sha256="a" * 64,
            actual_context_tokens=8192,
            prompt_tokens=1,
            response_format_tokens=0,
            safety_margin_tokens=512,
            budgeted_input_tokens=513,
            max_input_tokens=6144,
            requested_output_tokens=prepared.config.max_output_tokens,
            max_output_tokens=prepared.config.max_output_tokens,
        )
        before_dispatch(prepared.request_sha256, measurement)
        on_transport_result(LMStudioTransportObservation(
            status=200, body_bytes=0, body_sha256="b" * 64,
        ))
        if self.mode == "non_business":
            assert public.guard.allowed_decision_kinds == ("answer",)
            return json.dumps({
                "kind": "answer",
                "basis": "non_business_general",
                "text": "你好，很高兴和你聊天。",
                "citations": [],
            }, ensure_ascii=False)
        if self.mode == "missing_scope":
            assert public.guard.allowed_decision_kinds == ("clarify",)
            assert public.pending_clarifications
            slot = public.pending_clarifications[0].slot
            return json.dumps({
                "kind": "clarify",
                "prompt": "请先选择活动。",
                "missing_slots": [slot],
            }, ensure_ascii=False)
        if self.mode == "proposal_intent":
            assert public.guard.allowed_decision_kinds == ("propose",)
            operation = public.guard.allowed_proposal_operations[0]
            return json.dumps({
                "kind": "propose",
                "operation": operation.value,
                "recognized_intent_text": "识别到新增消费意图。",
            }, ensure_ascii=False)
        if self.mode == "expenses_paged":
            assert public.scope_authorization.status == "verified"
            scope = public.scope_authorization.scope
            assert scope is not None
            if public.continuations:
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
                assert len(public.facts) == 18
                refs = {item.query_evidence_ref for item in public.facts}
                assert len(refs) == 1
                qev = public.guard.fresh_receipt_refs[0]
                return json.dumps({
                    "kind": "answer",
                    "basis": "fresh_read_receipts",
                    "text": "已读取所选活动的两页消费记录。",
                    "citations": [str(qev)],
                }, ensure_ascii=False)
            assert public.guard.allowed_read_operations == (pc3.P2ReadOperation.EXPENSES,)
            return json.dumps({
                "kind": "read",
                "message_type": "query_request",
                "profile_id": public.profile_id,
                "versions": public.versions.model_dump(mode="json"),
                "operation": "read.expenses",
                "criteria": {"kind": "expenses", "activity_ref": str(scope.activity_ref)},
                "scope": scope.model_dump(mode="json"),
            })
        raise AssertionError("unknown CPU semantic-provider mode")


class _TrustedControl:
    def snapshot(self) -> AgentControlSnapshot:
        return AgentControlSnapshot(enabled=True, disable_revision=0, source="server_config")


def _app_components(
    tmp_path: Path,
    monkeypatch: Any,
    provider_mode: str,
    datasets: dict[str, list[dict[str, Any]]] | None = None,
) -> tuple[AppComponents, _SemanticProvider, SyntheticTransport, list[tuple[uuid.UUID, tuple[uuid.UUID, ...]]]]:
    monkeypatch.setenv("P2_V3_STORE_TEST_ROOT", str(tmp_path))
    database = tmp_path / f"{provider_mode}.sqlite3"
    store = _configured_store(database)
    rows = datasets or _multi_expense_datasets(18)
    rows["activity_members"][0]["user_id"] = str(OWNER)
    rows["participant_claims"][0]["user_id"] = str(OWNER)

    transport = SyntheticTransport(rows)
    backend = _Backend()
    backend._transport = transport
    authorized_scopes: list[tuple[uuid.UUID, tuple[uuid.UUID, ...]]] = []

    async def authorize_api_scope(
        principal_id: uuid.UUID,
        activity_ids: tuple[uuid.UUID, ...],
        access_token: str,
        expires_at: Any,
    ) -> None:
        authorized_scopes.append((principal_id, activity_ids))
        if principal_id != OWNER or access_token != TOKEN or expires_at is None:
            raise BackendReadError("invalid_auth_context")
        memberships = {
            uuid.UUID(row["activity_id"])
            for row in rows["activity_members"]
            if row["user_id"] == str(OWNER)
        }
        if not set(activity_ids).issubset(memberships):
            raise BackendReadError("access_denied")

    backend.authorize_api_scope = authorize_api_scope
    auth = _Auth()
    control = _TrustedControl()
    semantic_provider = _SemanticProvider(provider_mode)
    v1_provider = _Provider()
    journal = P2ErrorProofJournal(database.with_suffix(".journal.sqlite3"))
    runtime = P2Runtime(
        store,
        v1_provider,
        backend,
        auth,
        control,
        journal,
        model_timeout_seconds=3,
        v3_provider=semantic_provider,
        v3_prompt_config=P2V3PromptBuildConfig(
            model_id="synthetic-cpu-model",
            endpoint_url="http://127.0.0.1:1234/v1/chat/completions",
        ),
        v3_backend_config=P2BackendConfig(
            project_url="https://synthetic.invalid",
            publishable_key="sb_publishable_synthetic_cpu_only",
            timeout_seconds=2,
            page_size=16,
            max_pages=4,
            max_rows_per_query=64,
            max_requests_per_read=48,
            max_total_response_bytes=4_194_304,
            max_total_seconds=20,
            max_facts=16,
        ),
        enabled_candidate_profile_ids=(pc3.P2_V3_CANDIDATE_PROFILE_ID,),
    )
    components = AppComponents(
        store=_CandidateProfileStore(store, pc3.P2_V3_CANDIDATE_PROFILE_ID),
        provider=v1_provider,
        backend=backend,
        runtime=runtime,
        gateway=object(),
        auth_verifier=auth,
        agent_control=control,
    )
    return components, semantic_provider, transport, authorized_scopes


def _client_app(components: AppComponents, database: Path):
    settings = Settings(
        storage_path=database,
        provider_mode="mock",
        agent_enabled=True,
        disable_revision=0,
        api_requests_per_minute=500,
    )
    return create_app(settings, components_factory=lambda _: components)


def _new_session(client: TestClient) -> str:
    created = client.post("/v1/sessions", headers={"Authorization": f"Bearer {TOKEN}"}, json={
        "api_version": "1.0.0",
        "client_request_id": str(uuid.uuid4()),
        "title": "v3 runtime semantic CPU",
    })
    assert created.status_code == 201, created.text
    return created.json()["session"]["session_id"]


def _submit(
    client: TestClient,
    session_id: str,
    text: str,
    *,
    selected_activity: bool = False,
) -> uuid.UUID:
    body: dict[str, Any] = {"client_request_id": str(uuid.uuid4()), "text": text}
    if selected_activity:
        body["ui_context"] = {
            "page_type": "activity_overview",
            "activity_id": str(ACTIVITY),
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "client_version": "p2-v3-semantics-cpu",
        }
    submitted = client.post(
        f"/v1/sessions/{session_id}/turns",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json=body,
    )
    assert submitted.status_code == 202, submitted.text
    return uuid.UUID(submitted.json()["turn_id"])


def _events(client: TestClient, turn_id: uuid.UUID) -> dict[str, Any]:
    response = client.get(
        f"/v1/turns/{turn_id}/events", headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _wait_for_semantic_turn(
    components: AppComponents, turn_id: uuid.UUID, expected: set[c.TurnState],
) -> Any:
    deadline = time.monotonic() + 30
    aggregate = None
    while time.monotonic() < deadline:
        aggregate = components.store.get_turn(OWNER, turn_id)
        if aggregate.record.turn.state in expected:
            return aggregate
        if aggregate.record.turn.state in {c.TurnState.FAILED, c.TurnState.CANCELLED}:
            break
        time.sleep(0.01)
    assert aggregate is not None
    view = components.store.read_turn_view(OWNER, turn_id)
    events = [
        (getattr(item.event.type, "value", item.event.type), item.event.payload.model_dump(mode="json", by_alias=True))
        for item in view.events
    ]
    raise AssertionError(
        f"Turn ended in {aggregate.record.turn.state}/{aggregate.record.turn.step}; "
        f"resume={aggregate.checkpoint.resume_step}, calls={aggregate.checkpoint.model_calls}, "
        f"reads={aggregate.checkpoint.read_calls}, events={events}"
    )


def test_v3_non_business_turn_answers_without_source_reads(tmp_path: Path, monkeypatch: Any) -> None:
    components, model, transport, _ = _app_components(tmp_path, monkeypatch, "non_business")
    app = _client_app(components, tmp_path / "non_business.sqlite3")
    with TestClient(app) as client:
        session_id = _new_session(client)
        turn_id = _submit(client, session_id, "你好")
        aggregate = _wait(components, turn_id, {c.TurnState.COMPLETED})
        result = _events(client, turn_id)

        assert aggregate.checkpoint.model_calls == 1
        assert len(model.contexts) == 1
        assert model.contexts[0].guard.allowed_decision_kinds == ("answer",)
        assert transport.tables == []
        messages = [item for item in result["events"] if item["type"] == "message"]
        assert len(messages) == 1
        assert messages[0]["payload"]["text"] == "你好，很高兴和你聊天。"
        assert messages[0]["payload"]["citations"] == []

        accepted_input = aggregate.checkpoint.accepted_inputs[-1]
        spoofed_input = accepted_input.model_copy(update={
            "payload": accepted_input.payload.model_copy(update={"text": "查询消费"}),
        })
        spoofed_checkpoint = aggregate.checkpoint.model_copy(update={
            "accepted_inputs": [spoofed_input],
            "last_decision": c.AnswerDecision(
                kind="answer", basis="conversation", text="你好，很高兴和你聊天。", citations=[],
            ),
        })
        spoofed_aggregate = replace(aggregate, checkpoint=spoofed_checkpoint)
        spoofed_message = EventDraft(
            type=c.EventType.MESSAGE,
            occurred_at=datetime.now(timezone.utc),
            simulation=False,
            payload=c.MessageEventPayload(text="你好，很高兴和你聊天。", citations=[]),
        )
        assert not components.runtime.safe_scope_free_event(spoofed_aggregate, spoofed_message)


def test_v3_missing_scope_turn_clarifies_without_source_reads(tmp_path: Path, monkeypatch: Any) -> None:
    components, model, transport, _ = _app_components(tmp_path, monkeypatch, "missing_scope")
    app = _client_app(components, tmp_path / "missing_scope.sqlite3")
    with TestClient(app) as client:
        session_id = _new_session(client)
        turn_id = _submit(client, session_id, "查询消费")
        aggregate = _wait(components, turn_id, {c.TurnState.WAIT_INPUT})
        result = _events(client, turn_id)

        assert aggregate.checkpoint.model_calls == 1
        assert len(model.contexts) == 1
        assert model.contexts[0].pending_clarifications
        assert model.contexts[0].guard.allowed_decision_kinds == ("clarify",)
        assert transport.tables == []
        clarification = [item for item in result["events"] if item["type"] == "clarification"]
        assert len(clarification) == 1
        assert clarification[0]["payload"]["missing_slots"] == [c.ClarificationSlot.ACTIVITY.value]


def test_v3_create_intent_is_recognized_without_proposal_or_business_write(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    components, model, transport, _ = _app_components(tmp_path, monkeypatch, "proposal_intent")
    app = _client_app(components, tmp_path / "proposal_intent.sqlite3")
    with TestClient(app) as client:
        session_id = _new_session(client)
        turn_id = _submit(client, session_id, "新增消费")
        aggregate = _wait(components, turn_id, {c.TurnState.COMPLETED})
        result = _events(client, turn_id)
        session = client.get(
            f"/v1/sessions/{session_id}", headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert session.status_code == 200, session.text

        assert aggregate.checkpoint.model_calls == 1
        assert len(model.contexts) == 1
        assert model.contexts[0].guard.allowed_decision_kinds == ("propose",)
        assert transport.tables == []
        assert session.json()["proposal_cards"] == []
        assert not any(item["type"] == "proposal" for item in result["events"])
        assert any(item["type"] == "message" for item in result["events"])


def test_v3_scoped_expenses_continue_second_page_then_return_18_cited_facts(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    rows = _multi_expense_datasets(18)
    components, model, transport, authorized_scopes = _app_components(
        tmp_path, monkeypatch, "expenses_paged", rows,
    )
    app = _client_app(components, tmp_path / "expenses_paged.sqlite3")
    with TestClient(app) as client:
        session_id = _new_session(client)
        turn_id = _submit(client, session_id, "查询这个活动的消费", selected_activity=True)
        aggregate = _wait_for_semantic_turn(components, turn_id, {c.TurnState.COMPLETED})
        result = _events(client, turn_id)

        assert aggregate.checkpoint.model_calls == 3
        assert aggregate.checkpoint.read_calls == 1
        assert len(model.contexts) == 3
        assert model.contexts[0].scope_authorization.status == "verified"
        assert model.contexts[1].continuations and len(model.contexts[1].facts) == 16
        final_context = model.contexts[2]
        assert len(final_context.facts) == 18
        assert all(isinstance(item, pc3.ExpenseFact) for item in final_context.facts)
        assert final_context.query_evidence[0].operation is pc3.P2ReadOperation.EXPENSES
        assert final_context.query_evidence[0].page_count >= 1
        with components.store._connection() as connection:
            accepted_pages = connection.execute(
                "SELECT page_index, historical_payload_json FROM p2_v3_query_result_receipts "
                "WHERE owner_user_id=? AND turn_id=? ORDER BY page_index",
                (str(OWNER), str(turn_id)),
            ).fetchall()
        assert [int(item["page_index"]) for item in accepted_pages] == [0, 1]
        assert [len(json.loads(item["historical_payload_json"])["page"]["items"])
                for item in accepted_pages] == [16, 2]
        assert authorized_scopes and authorized_scopes[0][0] == OWNER
        assert authorized_scopes[0][1] == (ACTIVITY,)
        messages = [item for item in result["events"] if item["type"] == "message"]
        assert len(messages) == 1
        message = messages[0]["payload"]
        assert message["citations"] == []
        for index in range(1, 19):
            assert f"合成分页账单 {index}" in message["text"]

        stored = components.store.get_p2_v3_protected_event_activity_ids(
            OWNER, turn_id, event_seq=messages[0]["seq"],
        )
        assert stored is not None
        historical = stored.historical
        assert len(historical.query_evidence) == 1
        terminal_qev = historical.query_evidence[0]
        assert terminal_qev.source_query_complete is True
        assert terminal_qev.page.has_more is False
        assert terminal_qev.page.pages_seen == terminal_qev.page_count
        assert len(terminal_qev.matching_fact_refs) == 18
        assert len(historical.fact_cards) == 18
        assert tuple(str(item.expense_ref) for item in historical.fact_cards) == tuple(
            str(item) for item in terminal_qev.matching_fact_refs
        )
        assert all(item.query_evidence_ref == terminal_qev.query_evidence_ref for item in historical.fact_cards)
        assert stored.activity_ids == (ACTIVITY,)
        assert any(
            label.entity_kind == "activity" and label.display_name == "旅行账本"
            for label in historical.source_labels
        )
        assert historical.current_actor is not None
        with components.store._connection() as connection:
            protected = connection.execute(
                "SELECT protected_output_id FROM p2_v3_protected_outputs WHERE owner_user_id=? AND turn_id=?",
                (str(OWNER), str(turn_id)),
            ).fetchone()
            assert protected is not None
            link_counts = tuple(int(connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE protected_output_id=?",
                (protected["protected_output_id"],),
            ).fetchone()[0]) for table in (
                "p2_v3_output_fact_links", "p2_v3_output_query_links", "p2_v3_output_event_links",
            ))
        assert link_counts == (18, 1, 1)
