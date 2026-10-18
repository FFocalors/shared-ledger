from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app import contracts as c
from app.components import AppComponents, _CandidateProfileStore
from app.p2_backend import BackendReadError, P2BackendConfig
from app.p2_read_backend import P2ReadBackendError
from app.p2_journal import P2ErrorProofJournal
from app.p2_model_provider import (
    LMStudioProviderCancelled, LMStudioProviderError, LMStudioProviderErrorCode,
    LMStudioTransportObservation,
)
from app.p2_read_contracts_v3 import P2_V3_CANDIDATE_PROFILE_ID
from app import p2_read_contracts_v3 as pc3
from app.p2_read_prompt_v3 import P2V3PromptBuildConfig
from app.p2_runtime import P2Runtime
from app.p2_token_budget import P2TokenBudgetMeasurement
from app.ports import AgentControlSnapshot
from app.settings import Settings
from app.main import create_app
from test_p2_runtime import OWNER, TOKEN, _Auth, _Backend, _Provider, _wait
from test_p2_source_codec_backend_v3 import ACTIVITY, EXPENSE, SyntheticTransport, _datasets
from test_p2_v3_query_store_acceptance import _configured_store


class _V3AnswerProvider:
    """Fake model transport: selects a read, then cites only the returned QEV."""

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
        if public.query_evidence:
            receipt_ref = private.fresh_receipt_refs[0].query_evidence_ref
            return json.dumps({
                "kind": "answer",
                "basis": "fresh_read_receipts",
                "text": "我找到一个与你查询相关的活动。",
                "citations": [receipt_ref],
            }, ensure_ascii=False)
        return json.dumps({
            "kind": "read",
            "message_type": "query_request",
            "profile_id": P2_V3_CANDIDATE_PROFILE_ID,
            "versions": pc3.P2_V3_VERSIONS.model_dump(mode="json"),
            "operation": "read.activities",
            "criteria": {"kind": "activities", "status": "any"},
            "scope": None,
        })


class _V3FailureProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.failures: list[BaseException] = [
            LMStudioProviderError(LMStudioProviderErrorCode.LENGTH),
            LMStudioProviderCancelled(),
        ]

    async def prepare(self) -> None:
        return None

    async def generate(
        self, public: Any, private: Any, prepared: Any, *,
        before_dispatch: Any, on_transport_result: Any,
    ) -> str:
        self.calls += 1
        _record_test_v3_dispatch(prepared, before_dispatch, on_transport_result)
        raise self.failures.pop(0)


class _V3ExpenseProvider:
    """Controlled provider for one scoped read and its evidence-grounded answer."""

    def __init__(self) -> None:
        self.calls = 0
        self.contexts: list[Any] = []

    async def prepare(self) -> None:
        return None

    async def generate(
        self, public: Any, private: Any, prepared: Any, *,
        before_dispatch: Any, on_transport_result: Any,
    ) -> str:
        self.calls += 1
        _record_test_v3_dispatch(prepared, before_dispatch, on_transport_result)
        self.contexts.append(public)
        if public.query_evidence:
            receipt_ref = private.fresh_receipt_refs[0].query_evidence_ref
            return json.dumps({
                "kind": "answer",
                "basis": "fresh_read_receipts",
                "text": "本轮活动中有一笔晚餐消费。",
                "citations": [receipt_ref],
            }, ensure_ascii=False)
        scope = public.scope_authorization.scope
        assert scope is not None
        return json.dumps({
            "kind": "read",
            "message_type": "query_request",
            "profile_id": P2_V3_CANDIDATE_PROFILE_ID,
            "versions": pc3.P2_V3_VERSIONS.model_dump(mode="json"),
            "operation": "read.expenses",
            "criteria": {
                "kind": "expenses",
                "activity_ref": str(scope.activity_ref),
                "from_date": None,
                "to_date": None,
                "participant_ref": None,
                "title_contains": None,
            },
            "scope": scope.model_dump(mode="json", exclude_none=False),
        }, ensure_ascii=False)


class _V3AnswerFailureProvider(_V3ExpenseProvider):
    """Accept the read and return a bounded provider failure for answer stages."""

    async def generate(
        self, public: Any, private: Any, prepared: Any, *,
        before_dispatch: Any, on_transport_result: Any,
    ) -> str:
        result = await super().generate(
            public, private, prepared,
            before_dispatch=before_dispatch,
            on_transport_result=on_transport_result,
        )
        if public.query_evidence:
            raise LMStudioProviderError(LMStudioProviderErrorCode.LENGTH)
        return result


class _AuthOnceExpenseTransport:
    def __init__(self, datasets: dict[str, list[dict[str, Any]]]) -> None:
        self._inner = SyntheticTransport(datasets)
        self.expense_attempts = 0
        self._fail_first_expense = True

    def get(self, url: str, headers: Any, **kwargs: Any) -> Any:
        from urllib.parse import urlsplit

        table = urlsplit(url).path.rsplit("/", 1)[-1]
        if table == "expenses":
            self.expense_attempts += 1
            if self._fail_first_expense:
                self._fail_first_expense = False
                raise P2ReadBackendError("invalid_auth_context")
        return self._inner.get(url, headers, **kwargs)


def _wait_runtime_state(components: AppComponents, turn_id: uuid.UUID, expected: set[c.TurnState]) -> Any:
    deadline = time.monotonic() + 25
    latest = None
    while time.monotonic() < deadline:
        latest = components.store.get_turn(OWNER, turn_id)
        if latest.record.turn.state in expected:
            return latest
        time.sleep(0.02)
    assert latest is not None
    return latest


class _TrustedControl:
    def snapshot(self) -> AgentControlSnapshot:
        return AgentControlSnapshot(enabled=True, disable_revision=0, source="server_config")


def _record_test_v3_dispatch(
    prepared: Any,
    before_dispatch: Any,
    on_transport_result: Any,
) -> None:
    """Drive the same durable hooks as the provider facade without network I/O."""
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


def test_p2_runtime_preserves_its_timeout_above_the_p1_parent_cap() -> None:
    runtime = P2Runtime(
        object(), object(), object(), object(), object(), object(),
        model_timeout_seconds=75.0,
    )

    assert runtime._model_timeout == 75.0


def test_v3_api_activity_read_is_returned_to_model_and_committed_as_answer(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    monkeypatch.setenv("P2_V3_STORE_TEST_ROOT", str(tmp_path))
    database = tmp_path / "v3-runtime.sqlite3"
    store = _configured_store(database)
    dataset = _datasets()
    dataset["activity_members"][0]["user_id"] = str(OWNER)
    dataset["participant_claims"][0]["user_id"] = str(OWNER)

    provider = _Provider()
    backend = _Backend()
    backend._transport = SyntheticTransport(dataset)
    api_authorization_calls: list[tuple[uuid.UUID, tuple[uuid.UUID, ...]]] = []

    async def authorize_api_scope(
        principal_id: uuid.UUID, activity_ids: tuple[uuid.UUID, ...],
        access_token: str, expires_at: Any,
    ) -> None:
        api_authorization_calls.append((principal_id, activity_ids))
        if principal_id != OWNER or access_token != TOKEN or expires_at is None:
            raise BackendReadError("invalid_auth_context")
        memberships = {
            uuid.UUID(row["activity_id"])
            for row in dataset["activity_members"]
            if row["user_id"] == str(OWNER)
        }
        if not set(activity_ids).issubset(memberships):
            raise BackendReadError("access_denied")

    backend.authorize_api_scope = authorize_api_scope
    auth = _Auth()
    control = _TrustedControl()
    v3_provider = _V3AnswerProvider()
    v3_config = P2V3PromptBuildConfig(
        model_id="synthetic-cpu-model",
        endpoint_url="http://127.0.0.1:1234/v1/chat/completions",
    )
    runtime = P2Runtime(
        store, provider, backend, auth, control,
        P2ErrorProofJournal(database.with_suffix(".journal.sqlite3")),
        model_timeout_seconds=2,
        v3_provider=v3_provider,
        v3_prompt_config=v3_config,
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
        enabled_candidate_profile_ids=(P2_V3_CANDIDATE_PROFILE_ID,),
    )
    components = AppComponents(
        store=_CandidateProfileStore(store, P2_V3_CANDIDATE_PROFILE_ID),
        provider=provider,
        backend=backend,
        runtime=runtime,
        gateway=object(),
        auth_verifier=auth,
        agent_control=control,
    )
    settings = Settings(
        storage_path=database,
        provider_mode="mock",
        agent_enabled=True,
        disable_revision=0,
        api_requests_per_minute=500,
    )
    app = create_app(settings, components_factory=lambda _: components)

    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        created = client.post("/v1/sessions", headers=headers, json={
            "api_version": "1.0.0",
            "client_request_id": str(uuid.uuid4()),
            "title": "v3 CPU runtime",
        })
        assert created.status_code == 201, created.text
        session_id = created.json()["session"]["session_id"]
        submitted = client.post(f"/v1/sessions/{session_id}/turns", headers=headers, json={
            "client_request_id": str(uuid.uuid4()),
            "text": "查询我的活动",
        })
        assert submitted.status_code == 202, submitted.text
        turn_id = uuid.UUID(submitted.json()["turn_id"])
        aggregate = _wait(components, turn_id, {c.TurnState.COMPLETED})

        # A planned read reserves three model calls, even though this fixture
        # consumes only two provider calls (read selection and final answer).
        assert aggregate.checkpoint.model_calls == 3
        assert aggregate.checkpoint.read_calls == 1
        assert len(v3_provider.contexts) == 2
        assert v3_provider.contexts[1].facts
        assert v3_provider.contexts[1].facts[0].name == "旅行账本"
        polled = client.get(f"/v1/turns/{turn_id}/events", headers=headers)
        assert polled.status_code == 200, polled.text
        message = next(item for item in polled.json()["events"] if item["type"] == "message")
        assert message["payload"]["text"].startswith("我找到一个与你查询相关的活动。")
        assert "旅行账本" in message["payload"]["text"]
        assert message["payload"]["citations"] == []
        assert message["simulation"] is False
        assert api_authorization_calls and api_authorization_calls[0][0] == OWNER
        assert api_authorization_calls[0][1]
        assert all(str(item) not in polled.text for item in api_authorization_calls[0][1])

        # Polling the same historical event rechecks current membership rather
        # than reusing the Turn's earlier source authorization.
        dataset["activity_members"][0]["user_id"] = str(uuid.uuid4())
        revoked = client.get(f"/v1/turns/{turn_id}/events", headers=headers)
        assert revoked.status_code == 404


def test_v3_auth_resume_reuses_scoped_expense_query_and_starts_fresh_attempt(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    monkeypatch.setenv("P2_V3_STORE_TEST_ROOT", str(tmp_path))
    database = tmp_path / "v3-runtime-query-resume.sqlite3"
    store = _configured_store(database)
    dataset = _datasets()
    dataset["activity_members"][0]["user_id"] = str(OWNER)
    dataset["participant_claims"][0]["user_id"] = str(OWNER)

    provider = _Provider()
    backend = _Backend()
    transport = _AuthOnceExpenseTransport(dataset)
    backend._transport = transport
    auth = _Auth()
    control = _TrustedControl()
    v3_provider = _V3ExpenseProvider()
    runtime = P2Runtime(
        store, provider, backend, auth, control,
        P2ErrorProofJournal(database.with_suffix(".journal.sqlite3")),
        model_timeout_seconds=2,
        v3_provider=v3_provider,
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
        enabled_candidate_profile_ids=(P2_V3_CANDIDATE_PROFILE_ID,),
    )
    components = AppComponents(
        store=_CandidateProfileStore(store, P2_V3_CANDIDATE_PROFILE_ID),
        provider=provider,
        backend=backend,
        runtime=runtime,
        gateway=object(),
        auth_verifier=auth,
        agent_control=control,
    )
    settings = Settings(
        storage_path=database,
        provider_mode="mock",
        agent_enabled=True,
        disable_revision=0,
        api_requests_per_minute=500,
    )
    app = create_app(settings, components_factory=lambda _: components)

    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        created = client.post("/v1/sessions", headers=headers, json={
            "api_version": "1.0.0",
            "client_request_id": str(uuid.uuid4()),
            "title": "v3 scoped query recovery",
        })
        assert created.status_code == 201, created.text
        session_id = created.json()["session"]["session_id"]
        submitted = client.post(f"/v1/sessions/{session_id}/turns", headers=headers, json={
            "client_request_id": str(uuid.uuid4()),
            "text": "read expense",
            "ui_context": {
                "page_type": "expense_detail",
                "activity_id": str(ACTIVITY),
                "selected_entity": {"entity_type": "expense", "entity_id": str(EXPENSE)},
                "captured_at": "2026-10-18T00:00:00+08:00",
                "client_version": "p2-v3-recovery-test",
            },
        })
        assert submitted.status_code == 202, submitted.text
        turn_id = uuid.UUID(submitted.json()["turn_id"])
        paused = _wait_runtime_state(components, turn_id, {c.TurnState.WAIT_INPUT})
        assert paused.record.turn.state == c.TurnState.WAIT_INPUT, (
            "turn did not pause for auth"
        )
        assert paused.record.turn.wait_reason == c.WaitReason.AUTH_REQUIRED
        assert v3_provider.calls == 1
        assert transport.expense_attempts == 1
        paused_snapshot = store.get_p2_v3_snapshot(OWNER, turn_id)
        assert paused.checkpoint.model_calls == 3
        assert paused.checkpoint.read_calls == 1
        with store._connection() as connection:
            before = connection.execute(
                "SELECT logical_query_id,operation,generation,input_seq,input_digest FROM p2_v3_queries WHERE turn_id=?",
                (str(turn_id),),
            ).fetchall()
            descriptor_before = connection.execute(
                "SELECT selected_refs_json,context_revision,cohort_sha256 FROM p2_v3_query_descriptor_bindings WHERE turn_id=?",
                (str(turn_id),),
            ).fetchone()
            assert connection.execute(
                "SELECT COUNT(*) FROM p2_v3_query_attempts WHERE turn_id=?",
                (str(turn_id),),
            ).fetchone()[0] == 1
        assert len(before) == 1
        logical_query_id = before[0]["logical_query_id"]
        assert before[0]["operation"] == "read.expenses"
        assert json.loads(descriptor_before["selected_refs_json"])

    # Reopen the same durable database through a new Store and Runtime. No
    # process-local admission registry, grant, or source receipt survives.
    restarted_store = _configured_store(database)
    restarted_provider = _V3ExpenseProvider()
    restarted_backend = _Backend()
    restarted_backend._transport = transport
    restarted_runtime = P2Runtime(
        restarted_store, _Provider(), restarted_backend, auth, control,
        P2ErrorProofJournal(database.with_suffix(".journal.sqlite3")),
        model_timeout_seconds=2,
        v3_provider=restarted_provider,
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
        enabled_candidate_profile_ids=(P2_V3_CANDIDATE_PROFILE_ID,),
    )
    restarted_components = AppComponents(
        store=_CandidateProfileStore(restarted_store, P2_V3_CANDIDATE_PROFILE_ID),
        provider=_Provider(),
        backend=restarted_backend,
        runtime=restarted_runtime,
        gateway=object(),
        auth_verifier=auth,
        agent_control=control,
    )
    restarted_app = create_app(
        settings, components_factory=lambda _: restarted_components,
    )
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(restarted_app) as restarted_client:
        resumed = restarted_client.post(f"/v1/turns/{turn_id}/resume/auth", headers=headers, json={
            "client_request_id": str(uuid.uuid4()),
            "expected_state_revision": paused.record.turn.state_revision,
        })
        assert resumed.status_code == 202, resumed.text
        completed = _wait_runtime_state(
            restarted_components, turn_id, {c.TurnState.COMPLETED},
        )
        assert completed.record.turn.state == c.TurnState.COMPLETED, (
            "turn did not complete after process restart and auth resume"
        )
        assert completed.checkpoint.model_calls == 3
        assert completed.checkpoint.read_calls == 1
        assert v3_provider.calls == 1
        assert restarted_provider.calls == 1  # final answer only; no fresh planning
        assert transport.expense_attempts == 2
        resumed_snapshot = restarted_store.get_p2_v3_snapshot(OWNER, turn_id)
        assert resumed_snapshot.get_attempts > paused_snapshot.get_attempts
        assert resumed_snapshot.active_used_us >= paused_snapshot.active_used_us
        assert resumed_snapshot.backend_used_us >= paused_snapshot.backend_used_us
        with restarted_store._connection() as connection:
            after = connection.execute(
                "SELECT logical_query_id,operation,generation,input_seq,input_digest FROM p2_v3_queries WHERE turn_id=?",
                (str(turn_id),),
            ).fetchall()
            attempts = connection.execute(
                "SELECT logical_query_id,attempt_id,attempt_seq,attempt_state FROM p2_v3_query_attempts WHERE turn_id=? ORDER BY attempt_seq",
                (str(turn_id),),
            ).fetchall()
            result_attempt = connection.execute(
                "SELECT query_attempt_id FROM p2_v3_query_result_receipts WHERE turn_id=?",
                (str(turn_id),),
            ).fetchone()["query_attempt_id"]
            descriptor_after = connection.execute(
                "SELECT selected_refs_json,context_revision,cohort_sha256 FROM p2_v3_query_descriptor_bindings WHERE turn_id=?",
                (str(turn_id),),
            ).fetchone()
            assert connection.execute(
                "SELECT COUNT(*) FROM p2_v3_query_result_receipts WHERE turn_id=?",
                (str(turn_id),),
            ).fetchone()[0] == 1
        assert len(after) == 1 and after[0]["logical_query_id"] == logical_query_id
        assert [row["attempt_seq"] for row in attempts] == [1, 2]
        assert [row["attempt_state"] for row in attempts] == ["started", "started"]
        assert all(row["logical_query_id"] == logical_query_id for row in attempts)
        assert result_attempt == attempts[1]["attempt_id"]
        assert descriptor_after["selected_refs_json"] == descriptor_before["selected_refs_json"]
        assert descriptor_after["cohort_sha256"] == descriptor_before["cohort_sha256"]
        assert descriptor_after["context_revision"] == descriptor_before["context_revision"]
        events = restarted_client.get(f"/v1/turns/{turn_id}/events", headers=headers)
        assert events.status_code == 200, events.text
        message = next(item for item in events.json()["events"] if item["type"] == "message")
        assert "晚餐" in message["payload"]["text"]


def test_v3_model_dispatch_budget_survives_repeated_answer_failure_and_resume(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    monkeypatch.setenv("P2_V3_STORE_TEST_ROOT", str(tmp_path))
    database = tmp_path / "v3-runtime-model-dispatch-budget.sqlite3"
    store = _configured_store(database)
    dataset = _datasets()
    dataset["activity_members"][0]["user_id"] = str(OWNER)
    dataset["participant_claims"][0]["user_id"] = str(OWNER)
    transport = SyntheticTransport(dataset)
    backend = _Backend()
    backend._transport = transport
    auth = _Auth()
    control = _TrustedControl()
    v3_provider = _V3AnswerFailureProvider()
    runtime = P2Runtime(
        store, _Provider(), backend, auth, control,
        P2ErrorProofJournal(database.with_suffix(".journal.sqlite3")),
        model_timeout_seconds=2,
        max_model_calls=3,
        v3_provider=v3_provider,
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
        enabled_candidate_profile_ids=(P2_V3_CANDIDATE_PROFILE_ID,),
    )
    components = AppComponents(
        store=_CandidateProfileStore(store, P2_V3_CANDIDATE_PROFILE_ID),
        provider=_Provider(),
        backend=backend,
        runtime=runtime,
        gateway=object(),
        auth_verifier=auth,
        agent_control=control,
    )
    settings = Settings(
        storage_path=database,
        provider_mode="mock",
        agent_enabled=True,
        disable_revision=0,
        api_requests_per_minute=500,
    )
    app = create_app(settings, components_factory=lambda _: components)

    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        created = client.post("/v1/sessions", headers=headers, json={
            "api_version": "1.0.0",
            "client_request_id": str(uuid.uuid4()),
            "title": "v3 durable model budget",
        })
        assert created.status_code == 201, created.text
        session_id = created.json()["session"]["session_id"]
        submitted = client.post(f"/v1/sessions/{session_id}/turns", headers=headers, json={
            "client_request_id": str(uuid.uuid4()),
            "text": "read expense",
            "ui_context": {
                "page_type": "expense_detail",
                "activity_id": str(ACTIVITY),
                "captured_at": "2026-10-18T00:00:00+08:00",
                "client_version": "p2-v3-model-budget-test",
            },
        })
        assert submitted.status_code == 202, submitted.text
        turn_id = uuid.UUID(submitted.json()["turn_id"])
        first_pause = _wait_runtime_state(components, turn_id, {c.TurnState.WAIT_INPUT})
        assert first_pause.record.turn.wait_reason == c.WaitReason.AUTH_REQUIRED
        first_snapshot = store.get_p2_v3_snapshot(OWNER, turn_id)
        assert first_pause.checkpoint.model_calls == 3  # coarse sequence reservation
        assert first_snapshot.model_calls == 2  # plan + failed answer dispatch
        assert v3_provider.calls == 2

        resumed = client.post(f"/v1/turns/{turn_id}/resume/auth", headers=headers, json={
            "client_request_id": str(uuid.uuid4()),
            "expected_state_revision": first_pause.record.turn.state_revision,
        })
        assert resumed.status_code == 202, resumed.text
        second_pause = _wait_runtime_state(components, turn_id, {c.TurnState.WAIT_INPUT})
        second_snapshot = store.get_p2_v3_snapshot(OWNER, turn_id)
        assert second_pause.checkpoint.model_calls == 3
        assert second_snapshot.model_calls == 3
        assert second_snapshot.model_calls >= first_snapshot.model_calls
        assert v3_provider.calls == 3
        expense_gets_before_budget_stop = transport.tables.count("expenses")

        resumed_again = client.post(f"/v1/turns/{turn_id}/resume/auth", headers=headers, json={
            "client_request_id": str(uuid.uuid4()),
            "expected_state_revision": second_pause.record.turn.state_revision,
        })
        assert resumed_again.status_code == 202, resumed_again.text
        failed = _wait_runtime_state(components, turn_id, {c.TurnState.FAILED})
        assert failed.record.turn.state == c.TurnState.FAILED
        final_snapshot = store.get_p2_v3_snapshot(OWNER, turn_id)
        assert final_snapshot.model_calls == 3
        assert v3_provider.calls == 3  # no fourth transport dispatch
        assert transport.tables.count("expenses") == expense_gets_before_budget_stop
        events = client.get(f"/v1/turns/{turn_id}/events", headers=headers)
        assert events.status_code == 200, events.text
        errors = [item for item in events.json()["events"] if item["type"] == "error"]
        assert errors and "generation budget reached" in errors[-1]["payload"]["message"]


def test_v3_provider_failure_is_persisted_without_automatic_regeneration(
    tmp_path: Path, monkeypatch: Any,
) -> None:
    monkeypatch.setenv("P2_V3_STORE_TEST_ROOT", str(tmp_path))
    database = tmp_path / "v3-length-failure.sqlite3"
    store = _configured_store(database)
    dataset = _datasets()
    dataset["activity_members"][0]["user_id"] = str(OWNER)
    dataset["participant_claims"][0]["user_id"] = str(OWNER)

    provider = _Provider()
    backend = _Backend()
    backend._transport = SyntheticTransport(dataset)
    auth = _Auth()
    control = _TrustedControl()
    v3_provider = _V3FailureProvider()
    runtime = P2Runtime(
        store, provider, backend, auth, control,
        P2ErrorProofJournal(database.with_suffix(".journal.sqlite3")),
        model_timeout_seconds=2,
        v3_provider=v3_provider,
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
        enabled_candidate_profile_ids=(P2_V3_CANDIDATE_PROFILE_ID,),
    )
    components = AppComponents(
        store=_CandidateProfileStore(store, P2_V3_CANDIDATE_PROFILE_ID),
        provider=provider,
        backend=backend,
        runtime=runtime,
        gateway=object(),
        auth_verifier=auth,
        agent_control=control,
    )
    settings = Settings(
        storage_path=database,
        provider_mode="mock",
        agent_enabled=True,
        disable_revision=0,
        api_requests_per_minute=500,
    )
    app = create_app(settings, components_factory=lambda _: components)

    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        created = client.post("/v1/sessions", headers=headers, json={
            "api_version": "1.0.0",
            "client_request_id": str(uuid.uuid4()),
            "title": "v3 CPU length failure",
        })
        assert created.status_code == 201, created.text
        session_id = created.json()["session"]["session_id"]
        for expected_calls in (1, 2):
            submitted = client.post(f"/v1/sessions/{session_id}/turns", headers=headers, json={
                "client_request_id": str(uuid.uuid4()),
                "text": "查询我的活动",
            })
            assert submitted.status_code == 202, submitted.text
            turn_id = uuid.UUID(submitted.json()["turn_id"])
            aggregate = _wait(components, turn_id, {c.TurnState.WAIT_INPUT})
            time.sleep(0.1)

            assert v3_provider.calls == expected_calls
            # The read plan reserves three calls; provider.calls below tracks
            # actual transport invocations for these failure cases.
            assert aggregate.checkpoint.model_calls == 3
            assert aggregate.checkpoint.read_calls == 1
            polled = client.get(f"/v1/turns/{turn_id}/events", headers=headers)
            assert polled.status_code == 200, polled.text
            errors = [item for item in polled.json()["events"] if item["type"] == "error"]
            assert errors
            assert errors[-1]["payload"]["message"] == "P2 dependency unavailable: lmstudio_failed."

        assert backend._transport.tables == []
