from __future__ import annotations

import asyncio
import hashlib
import json
import time
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping

import pytest

from app import p2_backend as v1
from app import p2_read_backend as backend
from app import p2_read_contracts as pc


OWNER = uuid.UUID("10000000-0000-4000-8000-000000000001")
TURN = uuid.UUID("11000000-0000-4000-8000-000000000001")
CLAIM = uuid.UUID("12000000-0000-4000-8000-000000000001")
ACTIVITY = uuid.UUID("20000000-0000-4000-8000-000000000001")
ROOT_UNIT = uuid.UUID("30000000-0000-4000-8000-000000000001")
CHILD_UNIT = uuid.UUID("30000000-0000-4000-8000-000000000002")
OTHER_UNIT = uuid.UUID("30000000-0000-4000-8000-000000000003")
PAYER = uuid.UUID("40000000-0000-4000-8000-000000000001")
SPLIT = uuid.UUID("40000000-0000-4000-8000-000000000002")
EXPENSE = uuid.UUID("50000000-0000-4000-8000-000000000001")
REFUND = uuid.UUID("50000000-0000-4000-8000-000000000002")
DEBT = uuid.UUID("51000000-0000-4000-8000-000000000001")
ACCOUNT = uuid.UUID("52000000-0000-4000-8000-000000000001")
USAGE = uuid.UUID("53000000-0000-4000-8000-000000000001")
TRANSFER = uuid.UUID("54000000-0000-4000-8000-000000000001")
COMPONENT = uuid.UUID("55000000-0000-4000-8000-000000000001")
TOKEN = "eyJhbGci.unit.test.signature"
INPUT_DIGEST = hashlib.sha256(b"candidate read input").hexdigest()
NOW = datetime.now(timezone.utc)


class FakePostgrestTransport:
    """Deterministic in-memory public-table transport using actual JSON bytes."""

    def __init__(self, tables: Mapping[str, list[dict[str, Any]]]) -> None:
        self.tables = {key: [dict(row) for row in rows] for key, rows in tables.items()}
        self.requests: list[tuple[str, dict[str, str]]] = []

    def get(
        self, url: str, headers: Mapping[str, str], *, timeout: float,
        max_response_bytes: int, control: Any,
    ) -> v1.TransportResponse:
        assert headers["Authorization"] == f"Bearer {TOKEN}"
        assert headers["apikey"] == "sb_publishable_candidate_test"
        assert headers["Prefer"] == "count=exact"
        assert not any(key.lower() == "range" for key in headers)
        self.requests.append((url, dict(headers)))
        parsed = urllib.parse.urlsplit(url)
        table = parsed.path.rsplit("/", 1)[-1]
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        rows = list(self.tables.get(table, []))
        for key, values in params.items():
            if key in {"select", "order", "limit", "offset"}:
                continue
            expression = values[-1]
            if expression.startswith("eq."):
                expected = expression[3:]
                rows = [row for row in rows if _same_source_value(row.get(key), expected)]
            elif expression.startswith("in.(") and expression.endswith(")"):
                allowed = set(expression[4:-1].split(","))
                rows = [row for row in rows if str(row.get(key)) in allowed]
            else:
                raise AssertionError(f"unexpected fake filter for {table}.{key}")
        total = len(rows)
        offset = int(params["offset"][-1])
        limit = int(params["limit"][-1])
        selected = rows[offset:offset + limit]
        fields = params["select"][-1].split(",")
        body_rows = [{field: row.get(field) for field in fields} for row in selected]
        body = json.dumps(body_rows, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        assert len(body) <= max_response_bytes
        content_range = "*/0" if total == 0 else f"{offset}-{offset + len(selected) - 1}/{total}"
        status = 200 if total == 0 else 206
        return v1.TransportResponse(status, body, content_range)


class ControlledClock:
    def __init__(self, initial: float | None = None) -> None:
        self.value = time.monotonic() if initial is None else initial

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _same_source_value(value: Any, expected: str) -> bool:
    if isinstance(value, bool):
        return expected.lower() == str(value).lower()
    return str(value) == expected


def _activity_row(activity_id: uuid.UUID, name: str = "Trip") -> dict[str, Any]:
    return {
        "id": str(activity_id), "name": name, "type": "travel",
        "base_currency": "GBP", "multi_currency_enabled": True,
        "is_deleted": False, "archived_at": None, "financial_version": 7,
    }


def _expense_row(
    expense_id: uuid.UUID, *, amount: float, base_amount: float,
    occurred: str, parent: uuid.UUID | None,
) -> dict[str, Any]:
    return {
        "id": str(expense_id), "ledger_unit_id": str(CHILD_UNIT), "title": "Dinner",
        "original_amount": amount, "original_currency": "GBP", "fx_rate": 1.25,
        "base_amount": base_amount, "occurred_at": occurred,
        "original_expense_id": None if parent is None else str(parent),
        "version": 1, "is_deleted": False, "financial_locked": False,
    }


def tables_for(*, activity_rows: list[dict[str, Any]] | None = None) -> dict[str, list[dict[str, Any]]]:
    activities = [_activity_row(ACTIVITY)] if activity_rows is None else activity_rows
    return {
        "activities": activities,
        "activity_members": [{"activity_id": str(row["id"]), "user_id": str(OWNER)} for row in activities],
        "ledger_units": [
            {"id": str(ROOT_UNIT), "activity_id": str(ACTIVITY), "name": "Main", "type": "activity", "is_deleted": False, "participant_scope_configured": False},
            {"id": str(CHILD_UNIT), "activity_id": str(ACTIVITY), "name": "Child", "type": "sub_activity", "is_deleted": False, "participant_scope_configured": True},
            {"id": str(OTHER_UNIT), "activity_id": str(ACTIVITY), "name": "Other", "type": "activity", "is_deleted": False, "participant_scope_configured": False},
        ],
        "participants": [
            {"id": str(PAYER), "activity_id": str(ACTIVITY), "name": "Payer", "participant_order": 0, "is_deleted": False},
            {"id": str(SPLIT), "activity_id": str(ACTIVITY), "name": "Split", "participant_order": 1, "is_deleted": False},
        ],
        "sub_activity_participants": [
            {"activity_id": str(ACTIVITY), "ledger_unit_id": str(CHILD_UNIT), "participant_id": str(PAYER)},
            {"activity_id": str(ACTIVITY), "ledger_unit_id": str(CHILD_UNIT), "participant_id": str(SPLIT)},
        ],
        "expenses": [
            _expense_row(EXPENSE, amount=20.0, base_amount=25.0, occurred="2026-10-01T12:00:00Z", parent=None),
            _expense_row(REFUND, amount=-5.0, base_amount=-6.3, occurred="2026-10-02T12:00:00Z", parent=EXPENSE),
        ],
        "payments": [
            {"id": "60000000-0000-4000-8000-000000000001", "expense_id": str(EXPENSE), "participant_id": str(PAYER), "amount": 20.0, "base_amount": 25.0},
            {"id": "60000000-0000-4000-8000-000000000002", "expense_id": str(REFUND), "participant_id": str(PAYER), "amount": -5.0, "base_amount": -6.3},
        ],
        "splits": [
            {"id": "70000000-0000-4000-8000-000000000001", "expense_id": str(EXPENSE), "participant_id": str(SPLIT), "amount": 20.0, "base_amount": 25.0},
            {"id": "70000000-0000-4000-8000-000000000002", "expense_id": str(REFUND), "participant_id": str(SPLIT), "amount": -5.0, "base_amount": -6.3},
        ],
        "expense_debts": [
            {"id": str(DEBT), "activity_id": str(ACTIVITY), "ledger_unit_id": str(CHILD_UNIT), "expense_id": str(EXPENSE),
             "debtor_participant_id": str(PAYER), "creditor_participant_id": str(SPLIT), "amount": 8.0,
             "original_amount": 6.4, "original_currency": "USD", "fx_rate": 1.25,
             "created_at": "2026-10-01T12:01:00Z"},
        ],
        "prepayment_accounts": [
            {"id": str(ACCOUNT), "activity_id": str(ACTIVITY), "owner_participant_id": str(PAYER),
             "custodian_participant_id": str(SPLIT), "currency": "GBP", "balance": 10.25,
             "updated_at": "2026-10-03T12:00:00Z"},
        ],
        "prepayment_usages": [
            {"id": str(USAGE), "activity_id": str(ACTIVITY), "account_id": str(ACCOUNT), "expense_debt_id": str(DEBT),
             "gross_amount": 6.4, "amount": 6.4, "created_at": "2026-10-01T12:02:00Z",
             "prepayment_currency": "GBP", "prepayment_amount": 5.0,
             "debt_currency": "USD", "debt_amount": 4.0, "base_amount": 6.0,
             "bill_fx_rate": 1.2, "bill_occurred_at": "2026-10-01T12:02:00Z"},
        ],
        "transfers": [
            {"id": str(TRANSFER), "activity_id": str(ACTIVITY), "from_participant_id": str(SPLIT),
             "to_participant_id": str(PAYER), "type": "prepayment_return", "amount": 5.0,
             "currency": "GBP", "occurred_at": "2026-10-04T12:00:00Z", "is_voided": False},
        ],
        "transfer_components": [
            {"id": str(COMPONENT), "activity_id": str(ACTIVITY), "transfer_id": str(TRANSFER),
             "component_type": "prepayment_return", "amount": 5.0, "created_at": "2026-10-04T12:00:00Z"},
        ],
    }


def make_adapter(
    tables: Mapping[str, list[dict[str, Any]]] | None = None,
    *, clock: ControlledClock | None = None,
) -> tuple[backend.P2ReadBackendAdapter, v1.VerifiedReadContext, pc.P2Scope, pc.P2Scope, FakePostgrestTransport]:
    verified = v1.VerifiedReadContext(
        owner_user_id=OWNER, turn_id=TURN, principal_user_id=OWNER,
        access_token=TOKEN, expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        refs_by_opaque_token={},
    )
    created = time.monotonic() if clock is None else clock()
    state = backend.P2ReadTurnState(
        OWNER, TURN, generation=1, context_revision=1, claim_id=CLAIM,
        source_input_seq=1, input_digest=INPUT_DIGEST,
        turn_deadline_monotonic=created + backend.MAX_TURN_MS / 1000,
        created_monotonic=created, monotonic_clock=clock,
    )
    data = dict(tables or tables_for())
    transport = FakePostgrestTransport(data)
    adapter = backend.P2ReadBackendAdapter(
        v1.P2BackendConfig(
            project_url="https://ledger.example", publishable_key="sb_publishable_candidate_test",
            timeout_seconds=2.0, max_response_bytes=1_048_576,
            page_size=16, max_pages=4, max_rows_per_query=64,
            max_requests_per_read=48, max_total_response_bytes=4_194_304,
            max_total_seconds=20.0, max_facts=16,
        ), state, transport=transport,
    )
    activity_ref = state.bind_entity("activity", ACTIVITY, activity_id=ACTIVITY)
    root_ref = state.bind_entity("ledger_unit", ROOT_UNIT, activity_id=ACTIVITY, ledger_unit_id=ROOT_UNIT)
    child_ref = state.bind_entity("ledger_unit", CHILD_UNIT, activity_id=ACTIVITY, ledger_unit_id=CHILD_UNIT)
    state.bind_entity("ledger_unit", OTHER_UNIT, activity_id=ACTIVITY, ledger_unit_id=OTHER_UNIT)
    state.bind_entity("participant", PAYER, activity_id=ACTIVITY)
    state.bind_entity("participant", SPLIT, activity_id=ACTIVITY)
    state.bind_entity("expense", EXPENSE, activity_id=ACTIVITY, ledger_unit_id=CHILD_UNIT)
    activity_scope = pc.P2Scope(
        scope_kind="activity", scope_ref=activity_ref,
        activity_ref=activity_ref, ledger_unit_ref=None,
    )
    child_scope = pc.P2Scope(
        scope_kind="ledger_unit", scope_ref=child_ref,
        activity_ref=activity_ref, ledger_unit_ref=child_ref,
    )
    return adapter, verified, activity_scope, child_scope, transport


def request(operation: pc.P2ReadOperation, criteria: Any, scope: pc.P2Scope | None) -> pc.P2ReadQueryRequest:
    return pc.P2ReadQueryRequest(
        kind="read", message_type="query_request", profile_id=backend.PROFILE_ID,
        versions=pc.P2_VERSIONS, operation=operation, criteria=criteria, scope=scope,
    )


async def execute(
    operation: pc.P2ReadOperation, criteria: Any, scope_kind: str,
) -> tuple[backend.P2ReadBackendAdapter, Any, Any]:
    adapter, verified, activity_scope, child_scope, transport = make_adapter()
    scope = {"activity": activity_scope, "child": child_scope, "none": None}[scope_kind]
    read_request = request(operation, criteria, scope)
    grant = await adapter.issue_source_authorization_grant(
        verified, operation=operation, criteria=criteria, scope=scope,
    )
    result = await adapter.read_candidate(read_request, verified, grant)
    return adapter, result, transport


@pytest.mark.parametrize(
    ("operation", "scope_kind", "criteria_factory", "fact_type"),
    [
        (pc.P2ReadOperation.ACTIVITIES, "none", lambda a, c: pc.ActivityCriteria(kind="activities", status="any"), pc.ActivityFact),
        (pc.P2ReadOperation.EXPENSES, "child", lambda a, c: pc.ExpenseCriteria(kind="expenses", activity_ref=c.activity_ref), pc.ExpenseFact),
        (pc.P2ReadOperation.DEBTS, "child", lambda a, c: pc.DebtCriteria(kind="debts", activity_ref=c.activity_ref), pc.DebtFact),
        (pc.P2ReadOperation.REFUND_EVENTS, "activity", lambda a, c: pc.RefundEventCriteria(kind="refund_events", activity_ref=a.activity_ref), pc.RefundEventFact),
        (pc.P2ReadOperation.PREPAYMENT_ACCOUNTS, "activity", lambda a, c: pc.PrepaymentAccountsCriteria(kind="prepayment_accounts", activity_ref=a.activity_ref), pc.PrepaymentAccountFact),
        (pc.P2ReadOperation.PREPAYMENT_USAGES, "child", lambda a, c: pc.PrepaymentUsagesCriteria(kind="prepayment_usages", activity_ref=c.activity_ref), pc.PrepaymentUsageFact),
        (pc.P2ReadOperation.PREPAYMENT_RETURN_EVENTS, "activity", lambda a, c: pc.PrepaymentReturnCriteria(kind="prepayment_return_events", activity_ref=a.activity_ref), pc.PrepaymentReturnEventFact),
    ],
)
def test_all_seven_operations_return_strict_facts_from_raw_source_bytes(
    operation: pc.P2ReadOperation, scope_kind: str,
    criteria_factory: Any, fact_type: type[Any],
) -> None:
    async def run() -> tuple[backend.P2ReadBackendAdapter, pc.P2ReadBackendResult, FakePostgrestTransport]:
        adapter, verified, activity_scope, child_scope, transport = make_adapter()
        scope = {"activity": activity_scope, "child": child_scope, "none": None}[scope_kind]
        criteria = criteria_factory(activity_scope, child_scope)
        read_request = request(operation, criteria, scope)
        grant = await adapter.issue_source_authorization_grant(
            verified, operation=operation, criteria=criteria, scope=scope,
        )
        result = await adapter.read_candidate(read_request, verified, grant)
        return adapter, result, transport

    adapter, result, transport = asyncio.run(run())
    assert result.operation == operation
    assert result.query_evidence.operation == operation
    assert result.page.items
    assert all(isinstance(item, fact_type) for item in result.page.items)
    assert result.page.completeness == pc.ReadCompleteness.COMPLETE
    assert result.page.expected_total == result.query_evidence.matched_count
    assert result.query_evidence.source_query_complete is True
    assert result.query_evidence.page.model_projection_complete is True
    assert transport.requests
    serialized = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
    assert str(ACTIVITY) not in serialized
    assert TOKEN not in serialized
    assert "sb_publishable_candidate_test" not in serialized
    state = adapter._turn_state
    query = state.get_query(result.query_evidence.query_ref)
    assert query.receipts
    assert all(len(receipt.raw_body_sha256) == 64 for receipt in query.receipts)
    assert all(len(receipt.source_dto_sha256) == 64 for receipt in query.receipts)
    assert all(len(receipt.projection_sha256) == 64 for receipt in query.receipts)


def test_expense_raw_numeric_json_keeps_payer_split_roles_and_signed_refund_lines() -> None:
    async def run() -> pc.P2ReadBackendResult:
        adapter, verified, _, child_scope, _ = make_adapter()
        criteria = pc.ExpenseCriteria(kind="expenses", activity_ref=child_scope.activity_ref)
        grant = await adapter.issue_source_authorization_grant(
            verified, operation=pc.P2ReadOperation.EXPENSES, criteria=criteria, scope=child_scope,
        )
        return await adapter.read_candidate(
            request(pc.P2ReadOperation.EXPENSES, criteria, child_scope), verified, grant,
        )

    result = asyncio.run(run())
    positive = next(fact for fact in result.page.items if Decimal(fact.signed_original_amount) > 0)
    negative = next(fact for fact in result.page.items if Decimal(fact.signed_original_amount) < 0)
    assert {(line.role, Decimal(line.signed_original_amount)) for line in positive.payer_split_lines} == {
        ("payer", Decimal("20.0")), ("split", Decimal("20.0")),
    }
    assert {(line.role, Decimal(line.signed_original_amount)) for line in negative.payer_split_lines} == {
        ("payer", Decimal("-5.0")), ("split", Decimal("-5.0")),
    }
    assert positive.scope_ref == negative.scope_ref


def test_child_usage_without_expense_hint_is_complete_and_cross_child_hint_is_rejected() -> None:
    async def valid() -> tuple[pc.P2ReadBackendResult, backend.P2ReadBackendAdapter, v1.VerifiedReadContext, pc.P2Scope]:
        adapter, verified, _, child_scope, _ = make_adapter()
        criteria = pc.PrepaymentUsagesCriteria(kind="prepayment_usages", activity_ref=child_scope.activity_ref)
        grant = await adapter.issue_source_authorization_grant(
            verified, operation=pc.P2ReadOperation.PREPAYMENT_USAGES,
            criteria=criteria, scope=child_scope,
        )
        result = await adapter.read_candidate(
            request(pc.P2ReadOperation.PREPAYMENT_USAGES, criteria, child_scope), verified, grant,
        )
        return result, adapter, verified, child_scope

    result, adapter, verified, child_scope = asyncio.run(valid())
    assert len(result.page.items) == 1
    assert result.page.items[0].expense_ref

    async def invalid_cross_child_hint() -> None:
        other_expense = uuid.UUID("50000000-0000-4000-8000-000000000099")
        adapter._turn_state.bind_entity(
            "expense", other_expense, activity_id=ACTIVITY, ledger_unit_id=OTHER_UNIT,
        )
        criteria = pc.PrepaymentUsagesCriteria(
            kind="prepayment_usages", activity_ref=child_scope.activity_ref,
            expense_ref=adapter._turn_state.bind_entity(
                "expense", other_expense, activity_id=ACTIVITY, ledger_unit_id=OTHER_UNIT,
            ),
        )
        with pytest.raises(backend.P2ReadBackendError) as error:
            await adapter.issue_source_authorization_grant(
                verified, operation=pc.P2ReadOperation.PREPAYMENT_USAGES,
                criteria=criteria, scope=child_scope,
            )
        assert error.value.code == "unsupported_scope"

    asyncio.run(invalid_cross_child_hint())


def test_unscoped_activity_discovery_pages_16_then_rechecks_membership_before_continue() -> None:
    activity_rows = [
        _activity_row(uuid.UUID(int=2_000 + index), f"Trip {index:02d}")
        for index in range(17)
    ]
    tables = tables_for(activity_rows=activity_rows)

    async def run() -> tuple[backend.P2ReadBackendAdapter, v1.VerifiedReadContext, Any, Any, FakePostgrestTransport]:
        adapter, verified, _, _, transport = make_adapter(tables)
        criteria = pc.ActivityCriteria(kind="activities", status="any")
        grant = await adapter.issue_source_authorization_grant(
            verified, operation=pc.P2ReadOperation.ACTIVITIES, criteria=criteria, scope=None,
        )
        first = await adapter.read_candidate(
            request(pc.P2ReadOperation.ACTIVITIES, criteria, None), verified, grant,
        )
        return adapter, verified, grant, first, transport

    adapter, verified, grant, first, transport = asyncio.run(run())
    assert len(first.page.items) == 16
    assert first.page.has_more is True
    assert first.page.completeness == pc.ReadCompleteness.PARTIAL
    assert first.query_evidence.source_query_complete is True
    assert first.query_evidence.page.model_projection_complete is False
    assert first.page.expected_total == 17
    query_ref = first.query_evidence.query_ref
    next_ref = first.page.next_page_ref
    assert next_ref is not None
    requests_before = len(transport.requests)

    async def continue_page() -> pc.P2ReadBackendResult:
        continuation = pc.P2ReadContinueRequest(
            kind="read", message_type="continue_request", profile_id=backend.PROFILE_ID,
            versions=pc.P2_VERSIONS, query_ref=query_ref, next_page_ref=next_ref,
        )
        return await adapter.read_candidate(continuation, verified, grant)

    second = asyncio.run(continue_page())
    assert len(second.page.items) == 1
    assert second.page.page_index == 1
    assert second.page.has_more is False
    assert second.query_evidence.source_query_complete is True
    assert len(transport.requests) == requests_before + 4  # two source GETs plus two batched membership rechecks

    async def replay() -> None:
        continuation = pc.P2ReadContinueRequest(
            kind="read", message_type="continue_request", profile_id=backend.PROFILE_ID,
            versions=pc.P2_VERSIONS, query_ref=query_ref, next_page_ref=next_ref,
        )
        with pytest.raises(backend.P2ReadBackendError):
            await adapter.read_candidate(continuation, verified, grant)

    asyncio.run(replay())


def test_activity_continuation_does_not_reuse_old_rows_when_membership_shrinks() -> None:
    activity_rows = [
        _activity_row(uuid.UUID(int=3_000 + index), f"Trip {index:02d}")
        for index in range(17)
    ]
    adapter, verified, _, _, transport = make_adapter(tables_for(activity_rows=activity_rows))

    async def first_page() -> tuple[Any, Any, Any]:
        criteria = pc.ActivityCriteria(kind="activities", status="any")
        grant = await adapter.issue_source_authorization_grant(
            verified, operation=pc.P2ReadOperation.ACTIVITIES, criteria=criteria, scope=None,
        )
        result = await adapter.read_candidate(
            request(pc.P2ReadOperation.ACTIVITIES, criteria, None), verified, grant,
        )
        return criteria, grant, result

    criteria, grant, first = asyncio.run(first_page())
    assert first.page.has_more
    # Simulate current JWT RLS no longer exposing one previously visible row.
    transport.tables["activity_members"] = transport.tables["activity_members"][:-1]
    continuation = pc.P2ReadContinueRequest(
        kind="read", message_type="continue_request", profile_id=backend.PROFILE_ID,
        versions=pc.P2_VERSIONS, query_ref=first.query_evidence.query_ref,
        next_page_ref=first.page.next_page_ref,
    )

    async def continue_page() -> None:
        with pytest.raises(v1.BackendReadError) as error:
            await adapter.read_candidate(continuation, verified, grant)
        assert error.value.code == "scope_unavailable"

    asyncio.run(continue_page())
    state = adapter._turn_state._queries[first.query_evidence.query_ref]
    assert state.current is False
    assert state.next_page_ref in state.continuation_used


def test_financial_continuation_rejects_hidden_rows_with_same_owner_and_fv() -> None:
    tables = tables_for()
    expense_ids = [uuid.UUID(int=5_000 + index) for index in range(17)]
    tables["expenses"] = [
        _expense_row(
            expense_id, amount=1.0, base_amount=1.0,
            occurred="2026-10-01T12:00:00Z", parent=None,
        )
        for expense_id in expense_ids
    ]
    tables["expense_debts"] = [
        {
            "id": str(uuid.UUID(int=8_000 + index)), "activity_id": str(ACTIVITY),
            "ledger_unit_id": str(CHILD_UNIT), "expense_id": str(expense_id),
            "debtor_participant_id": str(PAYER), "creditor_participant_id": str(SPLIT),
            "amount": 1.0, "original_amount": 1.0, "original_currency": "USD",
            "fx_rate": 1.25, "created_at": "2026-10-01T12:01:00Z",
        }
        for index, expense_id in enumerate(expense_ids)
    ]
    adapter, verified, _, child_scope, transport = make_adapter(tables)

    async def first_page() -> pc.P2ReadBackendResult:
        criteria = pc.DebtCriteria(kind="debts", activity_ref=child_scope.activity_ref)
        grant = await adapter.issue_source_authorization_grant(
            verified, operation=pc.P2ReadOperation.DEBTS,
            criteria=criteria, scope=child_scope,
        )
        result = await adapter.read_candidate(
            request(pc.P2ReadOperation.DEBTS, criteria, child_scope), verified, grant,
        )
        assert result.page.has_more
        # Same owner, scope and Activity financial_version; current source
        # visibility nevertheless drops one expense as a JWT/RLS change could.
        requests_before = len(transport.requests)
        transport.tables["expense_debts"] = transport.tables["expense_debts"][:-1]
        continuation = pc.P2ReadContinueRequest(
            kind="read", message_type="continue_request", profile_id=backend.PROFILE_ID,
            versions=pc.P2_VERSIONS, query_ref=result.query_evidence.query_ref,
            next_page_ref=result.page.next_page_ref,
        )
        with pytest.raises(v1.BackendReadError) as error:
            await adapter.read_candidate(continuation, verified, grant)
        assert error.value.code == "data_changed_during_read", (
            f"code={error.value.code}, gets={adapter._turn_state.get_attempts}, "
            f"backend_ms={adapter._turn_state.backend_elapsed_ms}"
        )
        query = adapter._turn_state._queries[result.query_evidence.query_ref]
        assert query.current is False
        assert query.next_page_ref in query.continuation_used
        assert query.financial_versions == ((ACTIVITY, 7),)
        assert adapter._turn_state.get_attempts <= backend.MAX_GETS_PER_TURN
        continuation_requests = transport.requests[requests_before:]
        debt_offsets = [
            urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["offset"][-1]
            for url, _ in continuation_requests
            if urllib.parse.urlsplit(url).path.endswith("/expense_debts")
        ]
        assert debt_offsets == ["0"]
        return result

    first = asyncio.run(first_page())
    assert len(first.page.items) == 16


def test_financial_continuation_auth_failure_marks_prior_result_stale() -> None:
    tables = tables_for()
    expense_ids = [uuid.UUID(int=9_000 + index) for index in range(17)]
    tables["expenses"] = [
        _expense_row(
            expense_id, amount=1.0, base_amount=1.0,
            occurred="2026-10-01T12:00:00Z", parent=None,
        )
        for expense_id in expense_ids
    ]
    tables["expense_debts"] = [
        {
            "id": str(uuid.UUID(int=10_000 + index)), "activity_id": str(ACTIVITY),
            "ledger_unit_id": str(CHILD_UNIT), "expense_id": str(expense_id),
            "debtor_participant_id": str(PAYER), "creditor_participant_id": str(SPLIT),
            "amount": 1.0, "original_amount": 1.0, "original_currency": "USD",
            "fx_rate": 1.25, "created_at": "2026-10-01T12:01:00Z",
        }
        for index, expense_id in enumerate(expense_ids)
    ]
    adapter, verified, _, child_scope, transport = make_adapter(tables)

    async def run() -> None:
        criteria = pc.DebtCriteria(kind="debts", activity_ref=child_scope.activity_ref)
        grant = await adapter.issue_source_authorization_grant(
            verified, operation=pc.P2ReadOperation.DEBTS,
            criteria=criteria, scope=child_scope,
        )
        result = await adapter.read_candidate(
            request(pc.P2ReadOperation.DEBTS, criteria, child_scope), verified, grant,
        )
        assert result.page.has_more
        transport.tables["activity_members"] = []
        continuation = pc.P2ReadContinueRequest(
            kind="read", message_type="continue_request", profile_id=backend.PROFILE_ID,
            versions=pc.P2_VERSIONS, query_ref=result.query_evidence.query_ref,
            next_page_ref=result.page.next_page_ref,
        )
        with pytest.raises(v1.BackendReadError) as error:
            await adapter.read_candidate(continuation, verified, grant)
        assert error.value.code == "scope_unavailable"
        query = adapter._turn_state._queries[result.query_evidence.query_ref]
        assert query.current is False
        assert result.page.next_page_ref in query.continuation_used

    asyncio.run(run())


def test_no_rows_are_authoritative_only_when_exact_range_proves_zero() -> None:
    tables = tables_for(activity_rows=[])
    async def run() -> pc.P2ReadBackendResult:
        adapter, verified, _, _, _ = make_adapter(tables)
        criteria = pc.ActivityCriteria(kind="activities", status="any")
        grant = await adapter.issue_source_authorization_grant(
            verified, operation=pc.P2ReadOperation.ACTIVITIES, criteria=criteria, scope=None,
        )
        return await adapter.read_candidate(
            request(pc.P2ReadOperation.ACTIVITIES, criteria, None), verified, grant,
        )
    result = asyncio.run(run())
    assert result.page.items == ()
    assert result.page.completeness == pc.ReadCompleteness.COMPLETE
    assert result.query_evidence.source_query_complete is True
    assert result.query_evidence.query_zero_classification == "backend_zero"


def test_debt_currency_filter_is_local_and_distinguishes_postfilter_zero() -> None:
    async def run() -> tuple[pc.P2ReadBackendResult, FakePostgrestTransport]:
        adapter, verified, _, child_scope, transport = make_adapter()
        criteria = pc.DebtCriteria(
            kind="debts", activity_ref=child_scope.activity_ref, currency="EUR",
        )
        grant = await adapter.issue_source_authorization_grant(
            verified, operation=pc.P2ReadOperation.DEBTS,
            criteria=criteria, scope=child_scope,
        )
        result = await adapter.read_candidate(
            request(pc.P2ReadOperation.DEBTS, criteria, child_scope), verified, grant,
        )
        return result, transport

    result, transport = asyncio.run(run())
    assert result.page.items == ()
    assert result.query_evidence.source_query_complete is True
    assert result.query_evidence.source_total == 1
    assert result.query_evidence.matched_total == 0
    assert result.query_evidence.backend_criteria_stage == "scope_only"
    assert result.query_evidence.query_zero_classification == "post_filter_zero"
    debt_requests = [
        urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        for url, _ in transport.requests
        if urllib.parse.urlsplit(url).path.endswith("/expense_debts")
    ]
    assert debt_requests
    assert all("currency" not in query and "original_currency" not in query for query in debt_requests)


def test_unknown_debt_currency_cannot_be_filtered_into_a_complete_zero() -> None:
    tables = tables_for()
    tables["expense_debts"][0]["original_currency"] = None

    async def run() -> None:
        adapter, verified, _, child_scope, _ = make_adapter(tables)
        criteria = pc.DebtCriteria(
            kind="debts", activity_ref=child_scope.activity_ref, currency="EUR",
        )
        grant = await adapter.issue_source_authorization_grant(
            verified, operation=pc.P2ReadOperation.DEBTS,
            criteria=criteria, scope=child_scope,
        )
        with pytest.raises(backend.P2ReadBackendError) as error:
            await adapter.read_candidate(
                request(pc.P2ReadOperation.DEBTS, criteria, child_scope), verified, grant,
            )
        assert error.value.code == "incomplete_query"

    asyncio.run(run())


def test_turn_budget_transport_clamps_last_get_timeout_to_remaining_backend_time() -> None:
    class RecordingTransport:
        timeout: float | None = None
        max_response_bytes: int | None = None

        def get(self, url: str, headers: Mapping[str, str], *, timeout: float,
                max_response_bytes: int, control: Any) -> v1.TransportResponse:
            self.timeout = timeout
            self.max_response_bytes = max_response_bytes
            return v1.TransportResponse(200, b"[]", "*/0")

    adapter, _, _, _, _ = make_adapter()
    state = adapter._turn_state
    state.backend_elapsed_ms = backend.MAX_BACKEND_MS_PER_TURN - 100
    inner = RecordingTransport()
    wrapped = backend.TurnBudgetCaptureTransport(inner, state)
    wrapped.get(
        "https://ledger.example/rest/v1/activities?select=id&limit=1&offset=0",
        {}, timeout=2.0, max_response_bytes=1024, control=v1._RequestControl(),
    )
    assert inner.timeout is not None and inner.timeout <= 0.100001


def test_turn_budget_transport_clamps_timeout_to_absolute_turn_deadline() -> None:
    class RecordingTransport:
        timeout: float | None = None

        def get(self, url: str, headers: Mapping[str, str], *, timeout: float,
                max_response_bytes: int, control: Any) -> v1.TransportResponse:
            self.timeout = timeout
            return v1.TransportResponse(200, b"[]", "*/0")

    clock = ControlledClock()
    adapter, _, _, _, _ = make_adapter(clock=clock)
    state = adapter._turn_state
    state.turn_deadline_monotonic = clock() + 0.050
    inner = RecordingTransport()
    wrapped = backend.TurnBudgetCaptureTransport(inner, state)
    wrapped.get(
        "https://ledger.example/rest/v1/activities?select=id&limit=1&offset=0",
        {}, timeout=2.0, max_response_bytes=1024, control=v1._RequestControl(),
    )
    assert inner.timeout is not None and inner.timeout <= 0.050001


def test_submillisecond_backend_intervals_do_not_evade_turn_budget() -> None:
    clock = ControlledClock()
    adapter, _, _, _, _ = make_adapter(clock=clock)
    state = adapter._turn_state
    state.backend_elapsed_ms = backend.MAX_BACKEND_MS_PER_TURN - 1
    state.begin_backend_work()
    for _ in range(10):
        clock.advance(0.0002)
        with state._lock:
            state._refresh_elapsed_locked()
    with pytest.raises(backend.P2ReadBackendError) as error:
        state.end_backend_work(check=True)
    assert error.value.code == "upstream_timeout"
    assert state.backend_elapsed_ms >= backend.MAX_BACKEND_MS_PER_TURN


def test_turn_budget_transport_rejects_bytes_over_remaining_cumulative_cap() -> None:
    class OversizeTransport:
        max_response_bytes: int | None = None

        def get(self, url: str, headers: Mapping[str, str], *, timeout: float,
                max_response_bytes: int, control: Any) -> v1.TransportResponse:
            self.max_response_bytes = max_response_bytes
            # Malformed transport deliberately violates its advertised cap;
            # the wrapper must still charge and reject the overrun.
            return v1.TransportResponse(200, b"[]", "*/0")

    adapter, _, _, _, _ = make_adapter()
    state = adapter._turn_state
    state.response_bytes = backend.MAX_BYTES_PER_TURN - 1
    wrapped = backend.TurnBudgetCaptureTransport(OversizeTransport(), state)
    with pytest.raises(backend.P2ReadBackendError) as error:
        wrapped.get(
            "https://ledger.example/rest/v1/activities?select=id&limit=1&offset=0",
            {}, timeout=2.0, max_response_bytes=1024, control=v1._RequestControl(),
        )
    assert error.value.code == "response_too_large"
    assert isinstance(wrapped._inner, OversizeTransport)
    assert wrapped._inner.max_response_bytes == 1
    assert state.response_bytes == backend.MAX_BYTES_PER_TURN + 1


def test_transport_cancellation_preserves_exception_and_unknown_cost_is_not_reused() -> None:
    class CancellingTransport:
        calls = 0

        def get(self, url: str, headers: Mapping[str, str], *, timeout: float,
                max_response_bytes: int, control: Any) -> v1.TransportResponse:
            self.calls += 1
            control.abort()
            raise asyncio.CancelledError()

    adapter, _, _, _, _ = make_adapter()
    state = adapter._turn_state
    inner = CancellingTransport()
    wrapped = backend.TurnBudgetCaptureTransport(inner, state)
    with pytest.raises(asyncio.CancelledError):
        wrapped.get(
            "https://ledger.example/rest/v1/activities?select=id&limit=1&offset=0",
            {}, timeout=2.0, max_response_bytes=1024, control=v1._RequestControl(),
        )
    assert state.unknown_consumption is True
    assert state.get_attempts == 1
    with pytest.raises(backend.P2ReadBackendError) as error:
        wrapped.get(
            "https://ledger.example/rest/v1/activities?select=id&limit=1&offset=0",
            {}, timeout=2.0, max_response_bytes=1024, control=v1._RequestControl(),
        )
    assert error.value.code == "upstream_failure"
    assert inner.calls == 1


def test_final_projection_overrun_cannot_return_a_successful_read() -> None:
    clock = ControlledClock()
    adapter, verified, _, _, _ = make_adapter(clock=clock)

    async def run() -> None:
        criteria = pc.ActivityCriteria(kind="activities", status="any")
        grant = await adapter.issue_source_authorization_grant(
            verified, operation=pc.P2ReadOperation.ACTIVITIES, criteria=criteria, scope=None,
        )
        adapter._turn_state.backend_elapsed_ms = backend.MAX_BACKEND_MS_PER_TURN - 100
        original = adapter._result_for_page

        def delayed_projection(query: Any, page_index: int) -> pc.P2ReadBackendResult:
            result = original(query, page_index)
            clock.advance(0.101)
            return result

        adapter._result_for_page = delayed_projection
        with pytest.raises(backend.P2ReadBackendError) as error:
            await adapter.read_candidate(
                request(pc.P2ReadOperation.ACTIVITIES, criteria, None), verified, grant,
            )
        assert error.value.code == "upstream_timeout"
        assert adapter._turn_state.backend_elapsed_ms >= backend.MAX_BACKEND_MS_PER_TURN
        assert len(adapter._turn_state._queries) == 1
        assert next(iter(adapter._turn_state._queries.values())).current is False

    asyncio.run(run())


def test_final_get_overrun_is_charged_and_cannot_return_a_successful_read() -> None:
    clock = ControlledClock()

    class DelayedMembershipTransport(FakePostgrestTransport):
        def get(self, url: str, headers: Mapping[str, str], *, timeout: float,
                max_response_bytes: int, control: Any) -> v1.TransportResponse:
            response = super().get(
                url, headers, timeout=timeout,
                max_response_bytes=max_response_bytes, control=control,
            )
            if urllib.parse.urlsplit(url).path.endswith("/activity_members"):
                clock.advance(0.101)
            return response

    async def run() -> None:
        adapter, verified, _, _, old_transport = make_adapter(clock=clock)
        state = adapter._turn_state
        delayed = DelayedMembershipTransport(old_transport.tables)
        adapter._transport = backend.TurnBudgetCaptureTransport(delayed, state)
        criteria = pc.ActivityCriteria(kind="activities", status="any")
        grant = await adapter.issue_source_authorization_grant(
            verified, operation=pc.P2ReadOperation.ACTIVITIES, criteria=criteria, scope=None,
        )
        state.backend_elapsed_ms = backend.MAX_BACKEND_MS_PER_TURN - 100
        attempts_before = state.get_attempts
        bytes_before = state.response_bytes
        with pytest.raises(backend.P2ReadBackendError) as error:
            await adapter.read_candidate(
                request(pc.P2ReadOperation.ACTIVITIES, criteria, None), verified, grant,
            )
        assert error.value.code == "upstream_timeout"
        assert state.get_attempts >= attempts_before + 2
        assert state.response_bytes > bytes_before
        assert state.backend_elapsed_ms >= backend.MAX_BACKEND_MS_PER_TURN
        assert state._queries == {}

    asyncio.run(run())


def test_over_budget_continuation_stales_query_and_keeps_nonce_and_cost_consumed() -> None:
    clock = ControlledClock()
    activity_rows = [
        _activity_row(uuid.UUID(int=20_000 + index), f"Trip {index:02d}")
        for index in range(17)
    ]

    async def run() -> None:
        adapter, verified, _, _, _ = make_adapter(tables_for(activity_rows=activity_rows), clock=clock)
        state = adapter._turn_state
        criteria = pc.ActivityCriteria(kind="activities", status="any")
        grant = await adapter.issue_source_authorization_grant(
            verified, operation=pc.P2ReadOperation.ACTIVITIES, criteria=criteria, scope=None,
        )
        first = await adapter.read_candidate(
            request(pc.P2ReadOperation.ACTIVITIES, criteria, None), verified, grant,
        )
        assert first.page.has_more
        query_ref = first.query_evidence.query_ref
        next_ref = first.page.next_page_ref
        assert next_ref is not None
        query = state._queries[query_ref]
        attempts_before = state.get_attempts
        bytes_before = state.response_bytes
        state.backend_elapsed_ms = backend.MAX_BACKEND_MS_PER_TURN - 100
        original = adapter._result_for_page

        def delayed_second_projection(query_state: Any, page_index: int) -> pc.P2ReadBackendResult:
            result = original(query_state, page_index)
            if page_index == 1:
                clock.advance(0.101)
            return result

        adapter._result_for_page = delayed_second_projection
        continuation = pc.P2ReadContinueRequest(
            kind="read", message_type="continue_request", profile_id=backend.PROFILE_ID,
            versions=pc.P2_VERSIONS, query_ref=query_ref, next_page_ref=next_ref,
        )
        with pytest.raises(backend.P2ReadBackendError) as error:
            await adapter.read_candidate(continuation, verified, grant)
        assert error.value.code == "upstream_timeout"
        assert query.current is False
        assert next_ref in query.continuation_used
        assert state.get_attempts > attempts_before
        assert state.response_bytes > bytes_before
        assert state.backend_elapsed_ms >= backend.MAX_BACKEND_MS_PER_TURN

    asyncio.run(run())


def test_continuation_refusal_before_dispatch_still_consumes_current_nonce() -> None:
    activity_rows = [
        _activity_row(uuid.UUID(int=30_000 + index), f"Trip {index:02d}")
        for index in range(17)
    ]

    async def run() -> None:
        adapter, verified, _, _, _ = make_adapter(tables_for(activity_rows=activity_rows))
        state = adapter._turn_state
        criteria = pc.ActivityCriteria(kind="activities", status="any")
        grant = await adapter.issue_source_authorization_grant(
            verified, operation=pc.P2ReadOperation.ACTIVITIES, criteria=criteria, scope=None,
        )
        first = await adapter.read_candidate(
            request(pc.P2ReadOperation.ACTIVITIES, criteria, None), verified, grant,
        )
        query_ref = first.query_evidence.query_ref
        next_ref = first.page.next_page_ref
        assert next_ref is not None
        query = state._queries[query_ref]
        state.backend_elapsed_ms = backend.MAX_BACKEND_MS_PER_TURN
        attempts_before = state.get_attempts
        bytes_before = state.response_bytes
        continuation = pc.P2ReadContinueRequest(
            kind="read", message_type="continue_request", profile_id=backend.PROFILE_ID,
            versions=pc.P2_VERSIONS, query_ref=query_ref, next_page_ref=next_ref,
        )
        with pytest.raises(backend.P2ReadBackendError) as error:
            await adapter.read_candidate(continuation, verified, grant)
        assert error.value.code == "upstream_timeout"
        assert query.current is False
        assert next_ref in query.continuation_used
        assert state.get_attempts == attempts_before
        assert state.response_bytes == bytes_before

    asyncio.run(run())


def test_wrong_or_unknown_content_range_never_produces_complete_result() -> None:
    class BadRangeTransport(FakePostgrestTransport):
        def get(self, *args: Any, **kwargs: Any) -> v1.TransportResponse:
            response = super().get(*args, **kwargs)
            return v1.TransportResponse(response.status, response.body, "0-0/*")

    async def run() -> None:
        adapter, verified, _, _, _ = make_adapter()
        adapter._transport = backend.TurnBudgetCaptureTransport(BadRangeTransport(tables_for()), adapter._turn_state)
        criteria = pc.ActivityCriteria(kind="activities", status="any")
        grant = await adapter.issue_source_authorization_grant(
            verified, operation=pc.P2ReadOperation.ACTIVITIES, criteria=criteria, scope=None,
        )
        with pytest.raises(v1.BackendReadError):
            await adapter.read_candidate(request(pc.P2ReadOperation.ACTIVITIES, criteria, None), verified, grant)

    asyncio.run(run())

