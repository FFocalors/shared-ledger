from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app import contracts as c
from app.components import AppComponents
from app.p2_backend import (
    BackendReadError, P2ActivityDTO, P2BackendReadResult, P2DebtDTO,
    P2ExpenseDTO, P2LedgerUnitDTO, P2ParticipantDTO, P2PaymentDTO,
    P2ResolvedScope, P2SplitDTO, ScopeRequest, VerifiedReadContext,
)
from app.p2_journal import P2ErrorProofJournal
from app.p2_model_provider import P2ProviderHealth
from app.p2_runtime import P2Runtime
from app.ports import AgentControlSnapshot, Principal
from app.settings import Settings
from app.store import SQLiteAgentStore


OWNER = uuid.UUID("11111111-1111-4111-8111-111111111111")
ACTIVITY = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
UNIT = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
PAYER = uuid.UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
PARTICIPANT_2 = uuid.UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
TOKEN = "p2-test-access-token"


class _Auth:
    configured = True

    def verify_bearer(self, token: str) -> Principal:
        if token != TOKEN:
            from app.auth import Unauthenticated
            raise Unauthenticated("invalid test token")
        return Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1))


class _Control:
    def snapshot(self) -> AgentControlSnapshot:
        return AgentControlSnapshot(enabled=True, disable_revision=0, source="p2-test")


class _Provider:
    def __init__(self) -> None:
        self.prompts: list[Any] = []

    def start(self) -> None:
        pass

    def close(self) -> None:
        pass

    def health(self) -> P2ProviderHealth:
        return P2ProviderHealth(
            status="ready", inference_available=True,
            reason="last_call_succeeded", last_success_at=datetime.now(timezone.utc),
        )

    async def generate(self, prompt: Any) -> str:
        self.prompts.append(prompt)
        context = prompt.context
        if context.read_results:
            # The second model call receives the exact durable full body.
            assert context.read_results[-1].body.items
            evidence = context.read_results[-1].body.items[0].evidence_ref.value
            return json.dumps({
                "kind": "answer", "basis": "grounded",
                "text": "USD 999 was spent; all balances are settled.",
                "citations": [evidence],
            })
        if context.input_text == "list activities":
            return json.dumps({
                "kind": "read", "operation": "read.activities",
                "criteria": {"kind": "activities", "status": "active"},
            })
        if context.input_text == "read debts":
            scope_ref = context.verified_scope.activity_ref.value
            return json.dumps({
                "kind": "read", "operation": "read.debts",
                "criteria": {"kind": "debts", "activity_ref": scope_ref},
            })
        if context.input_text == "create expense proposal":
            unit_ref = next(item.ref.value for item in context.bound_references if item.kind == "ledger_unit")
            payer_ref = next(item.ref.value for item in context.bound_references if item.kind == "participant")
            return json.dumps({
                "kind": "propose", "operation": "expense.create",
                "fields": {
                    "kind": "expense.create", "ledger_unit_ref": unit_ref,
                    "title": "Lunch", "original_amount": "5.00", "original_currency": "USD",
                    "payment_allocations": [{"participant_ref": payer_ref, "amount": "5.00"}],
                    "split": {"mode": "equal", "participant_refs": [payer_ref]},
                },
            })
        if context.input_text == "expense missing amount":
            return json.dumps({
                "kind": "clarify", "prompt": "请提供金额。", "missing_slots": ["original_amount"],
            })
        scope_ref = context.verified_scope.activity_ref.value
        return json.dumps({
            "kind": "read", "operation": "read.expenses",
            "criteria": {"kind": "expenses", "activity_ref": scope_ref},
        })


class _Backend:
    def __init__(self) -> None:
        self.read_operations: list[c.ReadOperation] = []
        self.read_context_bodies: list[int] = []
        self.scope_tokens: list[str] = []
        self.version_checks: list[dict[uuid.UUID, int]] = []
        self.gateway_calls = 0

    def start(self) -> None:
        pass

    def close(self) -> None:
        pass

    async def authorize_api_scope(
        self, principal_user_id: uuid.UUID, activity_ids: tuple[uuid.UUID, ...],
        access_token: str, expires_at: datetime,
    ) -> None:
        assert principal_user_id == OWNER
        assert access_token == TOKEN
        assert expires_at > datetime.now(timezone.utc)
        self.scope_tokens.append(access_token)

    async def resolve_scope(
        self, verified: VerifiedReadContext, request: ScopeRequest,
    ) -> P2ResolvedScope:
        assert verified.owner_user_id == OWNER
        assert verified.principal_user_id == OWNER
        assert verified.access_token == TOKEN
        if request.mode == "none":
            return P2ResolvedScope("none", None, (), (), (), datetime.now(timezone.utc))
        if request.ui_activity_id_hint != ACTIVITY:
            raise BackendReadError("scope_unavailable")
        return P2ResolvedScope(
            "activity", _activity(),
            (
                P2ParticipantDTO(PAYER, ACTIVITY, "Alex", 1, False),
                P2ParticipantDTO(PARTICIPANT_2, ACTIVITY, "Rin", 2, False),
            ),
            (P2LedgerUnitDTO(UNIT, ACTIVITY, "Main", "normal", False, False),),
            (), datetime.now(timezone.utc),
        )

    async def read(
        self, owner_user_id: uuid.UUID, turn_id: uuid.UUID, context: c.ModelContext,
        decision: c.ReadDecision, *, verified: VerifiedReadContext,
    ) -> P2BackendReadResult:
        assert owner_user_id == OWNER
        assert verified.turn_id == turn_id
        assert verified.access_token == TOKEN
        expected_permission = {
            c.ReadOperation.ACTIVITIES: c.HarnessPermission.READ_ACTIVITIES,
            c.ReadOperation.EXPENSES: c.HarnessPermission.READ_EXPENSES,
            c.ReadOperation.DEBTS: c.HarnessPermission.READ_DEBTS,
        }[decision.operation]
        assert expected_permission in context.available_permissions
        self.read_operations.append(decision.operation)
        self.read_context_bodies.append(sum(len(item.body.items) for item in context.read_results))
        now = datetime.now(timezone.utc)
        if decision.operation == c.ReadOperation.ACTIVITIES:
            return P2BackendReadResult(
                operation=decision.operation, observed_at=now, source="supabase_postgrest",
                activities=(_activity(),), financial_versions={}, complete=True,
            )
        if decision.operation == c.ReadOperation.EXPENSES:
            expense = P2ExpenseDTO(
                expense_id=uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
                activity_id=ACTIVITY, ledger_unit_id=UNIT, title="Dinner",
                original_amount=Decimal("12.50"), original_currency="USD",
                fx_rate=Decimal("1"), base_amount=Decimal("12.50"),
                occurred_at=now, original_expense_id=None, expense_version=1,
                is_deleted=False, financial_locked=False,
                payments=(P2PaymentDTO(
                    uuid.UUID("12121212-1212-4212-8212-121212121212"),
                    uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"), PAYER,
                    Decimal("12.50"), Decimal("12.50"),
                ),),
                splits=(P2SplitDTO(
                    uuid.UUID("13131313-1313-4313-8313-131313131313"),
                    uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"), PAYER,
                    Decimal("6.25"), Decimal("6.25"),
                ), P2SplitDTO(
                    uuid.UUID("14141414-1414-4414-8414-141414141414"),
                    uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"), PARTICIPANT_2,
                    Decimal("6.25"), Decimal("6.25"),
                )),
            )
            return P2BackendReadResult(
                operation=decision.operation, observed_at=now, source="supabase_postgrest",
                expenses=(expense,), financial_versions={ACTIVITY: 1}, complete=True,
            )
        debt = P2DebtDTO(
            debtor_participant_id=PAYER, creditor_participant_id=PARTICIPANT_2,
            currency="USD", original_amount=Decimal("3.00"),
            base_amount=Decimal("3.00"), base_total=Decimal("3.00"), financial_version=1,
        )
        return P2BackendReadResult(
            operation=decision.operation, observed_at=now, source="supabase_postgrest",
            debts=(debt,), financial_versions={ACTIVITY: 1}, complete=True,
        )

    async def verify_financial_versions(
        self, verified: VerifiedReadContext, expected: dict[uuid.UUID, int],
    ) -> None:
        self.version_checks.append(dict(expected))


def _activity() -> P2ActivityDTO:
    return P2ActivityDTO(
        activity_id=ACTIVITY, name="Trip", activity_type="normal", base_currency="USD",
        multi_currency_enabled=False, is_deleted=False, archived_at=None, financial_version=1,
    )


def _build_client(database: Path) -> tuple[TestClient, AppComponents, _Provider, _Backend]:
    store = SQLiteAgentStore(database, admission_enabled=True)
    provider = _Provider()
    backend = _Backend()
    auth = _Auth()
    runtime = P2Runtime(
        store, provider, backend, auth, _Control(), P2ErrorProofJournal(database.with_suffix(".journal.sqlite3")),
        model_timeout_seconds=2,
    )
    components = AppComponents(
        store=store, provider=provider, backend=backend, runtime=runtime,
        gateway=object(), auth_verifier=auth, scope_authorizer=None, agent_control=_Control(),
    )
    settings = Settings(
        storage_path=database, provider_mode="mock", agent_enabled=True,
        disable_revision=0, api_requests_per_minute=500,
    )
    from app.main import create_app
    return TestClient(create_app(settings, components_factory=lambda _: components)), components, provider, backend


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _create_session(client: TestClient) -> uuid.UUID:
    response = client.post("/v1/sessions", headers=_auth(), json={
        "api_version": "1.0.0", "client_request_id": str(uuid.uuid4()), "title": "P2 runtime test",
    })
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["session"]["session_id"])


def _submit(
    client: TestClient, session_id: uuid.UUID, text: str, *, scoped: bool,
) -> uuid.UUID:
    body: dict[str, Any] = {"client_request_id": str(uuid.uuid4()), "text": text}
    if scoped:
        body["ui_context"] = {
            "page_type": "activity_overview", "activity_id": str(ACTIVITY),
            "captured_at": datetime.now(timezone.utc).isoformat(), "client_version": "p2-test",
        }
    response = client.post(f"/v1/sessions/{session_id}/turns", headers=_auth(), json=body)
    assert response.status_code == 202, response.text
    return uuid.UUID(response.json()["turn_id"])


def _wait(components: AppComponents, turn_id: uuid.UUID, expected: set[c.TurnState]) -> Any:
    deadline = time.monotonic() + 5
    last = None
    while time.monotonic() < deadline:
        last = components.store.get_turn(OWNER, turn_id)
        if last.record.turn.state in expected:
            return last
        time.sleep(0.01)
    assert last is not None
    try:
        view = components.store.read_turn_view(OWNER, turn_id)
        events = [
            (getattr(item.event.type, "value", item.event.type), item.event.payload.model_dump(mode="json", by_alias=True))
            for item in view.events
        ]
    except Exception as exc:
        events = [f"read event view failed: {type(exc).__name__}: {exc}"]
    raise AssertionError(
        f"Turn ended in {last.record.turn.state}/{last.record.turn.step}; "
        f"resume={last.checkpoint.resume_step}, calls={last.checkpoint.model_calls}, "
        f"reads={last.checkpoint.read_calls}, events={events}"
    )


def _events(client: TestClient, turn_id: uuid.UUID) -> dict[str, Any]:
    response = client.get(f"/v1/turns/{turn_id}/events?after_seq=0&limit=100", headers=_auth())
    assert response.status_code == 200, response.text
    return response.json()


def test_expense_body_is_returned_to_next_model_and_answer_uses_trusted_dto(tmp_path: Path) -> None:
    client, components, provider, backend = _build_client(tmp_path / "p2-runtime.sqlite3")
    with client:
        session_id = _create_session(client)
        turn_id = _submit(client, session_id, "read expenses", scoped=True)
        aggregate = _wait(components, turn_id, {c.TurnState.COMPLETED})
        assert aggregate.checkpoint.model_calls == 2
        assert aggregate.checkpoint.read_calls == 1
        assert backend.read_operations == [c.ReadOperation.EXPENSES]
        assert backend.read_context_bodies == [0]
        assert len(provider.prompts) == 2
        returned_body = provider.prompts[1].context.read_results[0].body
        assert returned_body.items[0].title == "Dinner"
        assert returned_body.items[0].original_amount == "12.50"
        assert aggregate.checkpoint.model_context.read_results[0].body == returned_body
        assert aggregate.checkpoint.read_results[0].simulation is False
        message = next(item for item in _events(client, turn_id)["events"] if item["type"] == "message")
        assert message["simulation"] is False
        assert "12.50 USD" in message["payload"]["text"]
        assert "999" not in message["payload"]["text"]
        assert "settled" not in message["payload"]["text"]
        assert backend.version_checks
        assert backend.scope_tokens and set(backend.scope_tokens) == {TOKEN}


def test_remaining_semantics_are_limited_to_read_and_nonpersisted_proposal_intent(tmp_path: Path) -> None:
    client, components, provider, backend = _build_client(tmp_path / "p2-semantics.sqlite3")
    with client:
        session_id = _create_session(client)
        scenarios = [
            ("list activities", False, c.ReadOperation.ACTIVITIES),
            ("read debts", True, c.ReadOperation.DEBTS),
        ]
        for text, scoped, operation in scenarios:
            turn_id = _submit(client, session_id, text, scoped=scoped)
            aggregate = _wait(components, turn_id, {c.TurnState.COMPLETED})
            assert aggregate.checkpoint.read_calls == 1
            assert backend.read_operations[-1] == operation
            message = next(item for item in _events(client, turn_id)["events"] if item["type"] == "message")
            assert message["simulation"] is False
            assert message["payload"]["citations"]
        proposal_turn = _submit(client, session_id, "create expense proposal", scoped=True)
        proposal = _wait(components, proposal_turn, {c.TurnState.COMPLETED})
        message = next(item for item in _events(client, proposal_turn)["events"] if item["type"] == "message")
        assert "不会创建预览" in message["payload"]["text"]
        assert message["payload"]["citations"] == []
        assert components.store.read_turn_view(OWNER, proposal_turn).proposals == ()
        assert backend.gateway_calls == 0
        assert proposal.checkpoint.read_calls == 0


def test_invalid_write_intent_clarifies_and_does_not_reach_gateway(tmp_path: Path) -> None:
    client, components, provider, backend = _build_client(tmp_path / "p2-clarify.sqlite3")
    with client:
        session_id = _create_session(client)
        turn_id = _submit(client, session_id, "expense missing amount", scoped=True)
        aggregate = _wait(components, turn_id, {c.TurnState.WAIT_INPUT})
        assert aggregate.record.turn.wait_reason == c.WaitReason.MISSING_FIELDS
        events = _events(client, turn_id)["events"]
        clarification = next(item for item in events if item["type"] == "clarification")
        assert clarification["simulation"] is False
        assert "original_amount" in clarification["payload"]["missing_slots"]
        assert backend.gateway_calls == 0
