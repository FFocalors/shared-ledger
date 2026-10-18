from __future__ import annotations

import asyncio
import base64
import json
import socket
import socketserver
import threading
import time
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable

import pytest

from app import contracts as c
from app.p2_backend import (
    BackendReadError,
    BoundRef,
    P2BackendAdapter,
    P2BackendConfig,
    ScopeRequest,
    TransportResponse,
    VerifiedReadContext,
    _ReadBudget,
    _parse_json_rows,
)


USER_ID = uuid.UUID("10000000-0000-4000-8000-000000000001")
ACTIVITY_ID = uuid.UUID("20000000-0000-4000-8000-000000000001")
UNIT_ID = uuid.UUID("30000000-0000-4000-8000-000000000001")
P1_ID = uuid.UUID("40000000-0000-4000-8000-000000000001")
P2_ID = uuid.UUID("40000000-0000-4000-8000-000000000002")
EXPENSE_ID = uuid.UUID("50000000-0000-4000-8000-000000000001")
PAYMENT_ID = uuid.UUID("60000000-0000-4000-8000-000000000001")
SPLIT_ID = uuid.UUID("70000000-0000-4000-8000-000000000001")
NOW = datetime.now(timezone.utc)
TOKEN = "eyJhbGci.eyJzdWIi.signature"


def make_adapter(
    transport: Any,
    *,
    page_size: int = 4,
    timeout: float = 1.0,
    project_url: str = "https://ledger.example",
) -> P2BackendAdapter:
    return P2BackendAdapter(
        P2BackendConfig(
            project_url=project_url,
            publishable_key="sb_publishable_unit_test",
            timeout_seconds=timeout,
            max_response_bytes=8_192,
            page_size=page_size,
            max_pages=8,
            max_rows_per_query=32,
            max_requests_per_read=48,
            max_total_response_bytes=65_536,
            max_total_seconds=2,
        ),
        transport=transport,
    )


def grant(refs: dict[str, BoundRef] | None = None) -> VerifiedReadContext:
    return VerifiedReadContext(
        owner_user_id=USER_ID,
        turn_id=uuid.UUID("80000000-0000-4000-8000-000000000001"),
        principal_user_id=USER_ID,
        access_token=TOKEN,
        expires_at=NOW + timedelta(hours=1),
        refs_by_opaque_token=refs or {},
    )


def model_context(
    operation: c.ReadOperation,
    refs: list[tuple[str, str]] = (),
    *,
    activity_scope: str | None = None,
) -> c.ModelContext:
    permission = {
        c.ReadOperation.ACTIVITIES: "read.activities",
        c.ReadOperation.EXPENSES: "read.expenses",
        c.ReadOperation.DEBTS: "read.debts",
    }[operation]
    bound = [{"kind": kind, "ref": ref} for kind, ref in refs]
    if activity_scope is not None and ("activity", activity_scope) not in refs:
        bound.append({"kind": "activity", "ref": activity_scope})
    scope = (
        {"kind": "activity", "activity_ref": activity_scope, "permissions": [permission]}
        if activity_scope is not None else
        {"kind": "none", "permissions": [permission]}
    )
    return c.ModelContext.model_validate({
        "context_version": 1,
        "input_text": "show me the available facts",
        "verified_scope": scope,
        "recent_messages": [],
        "pending_slots": [],
        "bound_references": bound,
        "read_results": [],
        "policy_evidence": [],
        "available_permissions": [permission],
    })


class FunctionTransport:
    def __init__(self, response: Callable[..., TransportResponse]) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(
        self, url: str, headers: dict[str, str], *, timeout: float,
        max_response_bytes: int, control: Any,
    ) -> TransportResponse:
        self.calls.append((url, dict(headers)))
        return self.response(url, headers, timeout, max_response_bytes, control)


def json_response(
    rows: list[dict[str, Any]], start: int, total: int, *, status: int = 206,
) -> TransportResponse:
    if total == 0:
        content_range = "*/0"
    else:
        content_range = f"{start}-{start + len(rows) - 1}/{total}"
    return TransportResponse(status, json.dumps(rows).encode("utf-8"), content_range)


def test_pagination_uses_count_exact_and_advances_by_server_cap() -> None:
    rows = [{"id": str(uuid.UUID(int=index + 1))} for index in range(6)]
    offsets: list[int] = []

    def response(url: str, headers: dict[str, str], *_: Any) -> TransportResponse:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        offset = int(query["offset"][0])
        requested = int(query["limit"][0])
        offsets.append(offset)
        assert requested == 4
        assert headers["Prefer"] == "count=exact"
        assert not any(name.lower() == "range" for name in headers)
        page = rows[offset:offset + min(requested, 2)]
        return json_response(page, offset, len(rows))

    transport = FunctionTransport(response)
    adapter = make_adapter(transport)
    result = asyncio.run(adapter._get_json_rows("activities", [], grant(), budget=_ReadBudget()))

    assert len(result) == 6
    assert offsets == [0, 2, 4]


@pytest.mark.parametrize(
    ("ranges", "expected_code"),
    [
        (["0-1/*"], "read_limit_exceeded"),
        (["1-2/3"], "invalid_upstream_response"),
        (["0-1/3", "2-2/4"], "data_changed_during_read"),
        (["0-1/4", "2-3/4"], "invalid_upstream_response"),
    ],
)
def test_pagination_rejects_unknown_wrong_changed_and_duplicate_ranges(
    ranges: list[str], expected_code: str,
) -> None:
    rows = [{"id": str(uuid.UUID(int=index + 1))} for index in range(4)]
    index = 0

    def response(url: str, *_: Any) -> TransportResponse:
        nonlocal index
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        offset = int(query["offset"][0])
        page = rows[offset:offset + 2]
        if expected_code == "invalid_upstream_response" and len(ranges) == 2 and offset == 2:
            page = rows[0:2]
        current = ranges[min(index, len(ranges) - 1)]
        index += 1
        return TransportResponse(206, json.dumps(page).encode(), current)

    adapter = make_adapter(FunctionTransport(response), page_size=2)
    with pytest.raises(BackendReadError) as caught:
        asyncio.run(adapter._get_json_rows("activities", [], grant(), budget=_ReadBudget()))
    assert caught.value.code == expected_code


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "auth_rejected"),
        (403, "access_denied"),
        (429, "rate_limited"),
        (408, "upstream_timeout"),
        (504, "upstream_timeout"),
        (502, "upstream_unavailable"),
        (503, "upstream_unavailable"),
    ],
)
def test_http_statuses_have_stable_sanitized_codes(status: int, code: str) -> None:
    adapter = make_adapter(FunctionTransport(lambda *_: TransportResponse(status, b"secret body", None)))
    with pytest.raises(BackendReadError) as caught:
        asyncio.run(adapter._get_json_rows("activities", [], grant(), budget=_ReadBudget()))
    assert caught.value.code == code
    assert "secret" not in str(caught.value)


def test_strict_json_and_publishable_key_role() -> None:
    with pytest.raises(BackendReadError):
        _parse_json_rows(b'[{"id":"a","id":"b"}]')
    with pytest.raises(BackendReadError):
        _parse_json_rows(b"[NaN]")

    def jwt_key(role: str) -> str:
        claims = base64.urlsafe_b64encode(json.dumps({"role": role}).encode()).decode().rstrip("=")
        return f"eyJhbGci.{claims}.signature"

    adapter = make_adapter(FunctionTransport(lambda *_: TransportResponse(200, b"[]", "*/0")))
    P2BackendAdapter(P2BackendConfig("https://ledger.example", jwt_key("anon")))
    with pytest.raises(ValueError):
        P2BackendAdapter(P2BackendConfig("https://ledger.example", jwt_key("service_role")))
    with pytest.raises(ValueError):
        P2BackendAdapter(P2BackendConfig("https://ledger.example", "sb_secret_do_not_use"))
    assert adapter


def test_credentials_are_hidden_from_repr_and_expired_grants_fail_before_transport() -> None:
    transport = FunctionTransport(lambda *_: TransportResponse(200, b"[]", "*/0"))
    adapter = make_adapter(transport)
    current_grant = grant()
    assert TOKEN not in repr(current_grant)
    assert "sb_publishable_unit_test" not in repr(P2BackendConfig(
        "https://ledger.example", "sb_publishable_unit_test",
    ))
    expired = VerifiedReadContext(
        owner_user_id=USER_ID, turn_id=current_grant.turn_id, principal_user_id=USER_ID,
        access_token=TOKEN, expires_at=NOW - timedelta(seconds=1), refs_by_opaque_token={},
    )
    with pytest.raises(BackendReadError) as caught:
        asyncio.run(adapter._get_json_rows("activities", [], expired, budget=_ReadBudget()))
    assert caught.value.code == "invalid_auth_context"
    assert transport.calls == []


def test_lookup_uses_exact_contract_enum_value_not_str_enum() -> None:
    adapter = make_adapter(FunctionTransport(lambda *_: TransportResponse(200, b"[]", "*/0")))
    criteria = c.ReadDecision.model_validate({
        "kind": "read",
        "operation": "read.expenses",
        "criteria": {"kind": "expenses", "activity_ref": "activity_1"},
    }).criteria
    assert criteria.activity_ref is c.ActivityRef.A01
    assert str(criteria.activity_ref) == "ActivityRef.A01"
    assert adapter._lookup_ref(grant({"activity_1": BoundRef("activity", ACTIVITY_ID)}),
                               criteria.activity_ref, "activity").object_id == ACTIVITY_ID
    with pytest.raises(BackendReadError):
        adapter._lookup_ref(
            grant({"ActivityRef.A01": BoundRef("activity", ACTIVITY_ID)}),
            criteria.activity_ref, "activity",
        )


def source_rows(*, out_of_scope_payer: bool = False, debt: bool = False) -> dict[str, list[dict[str, Any]]]:
    activity = {
        "id": str(ACTIVITY_ID), "name": "Trip", "type": "normal",
        "base_currency": "USD", "multi_currency_enabled": True,
        "is_deleted": False, "archived_at": None, "financial_version": 7,
    }
    units = [{
        "id": str(UNIT_ID), "activity_id": str(ACTIVITY_ID), "name": "Child",
        "type": "sub_activity", "is_deleted": False,
        "participant_scope_configured": True,
    }]
    participants = [
        {"id": str(P1_ID), "activity_id": str(ACTIVITY_ID), "name": "A",
         "participant_order": 1, "is_deleted": False},
        {"id": str(P2_ID), "activity_id": str(ACTIVITY_ID), "name": "B",
         "participant_order": 2, "is_deleted": False},
    ]
    data: dict[str, list[dict[str, Any]]] = {
        "activities": [activity],
        "activity_members": [{"activity_id": str(ACTIVITY_ID)}],
        "ledger_units": units,
        "participants": participants,
        "sub_activity_participants": [{
            "activity_id": str(ACTIVITY_ID), "ledger_unit_id": str(UNIT_ID),
            "participant_id": str(P1_ID),
        }],
        "expenses": [],
        "payments": [],
        "splits": [],
        "rpc/list_settlement_options": [],
    }
    if debt:
        data["rpc/list_settlement_options"] = [{
            "debtor_participant_id": str(P1_ID),
            "creditor_participant_id": str(P2_ID),
            "currency": "USD",
            "original_amount": "4.2500",
            "base_amount": "5.1",
            "base_total": "5.1",
            "financial_version": 7,
        }]
    else:
        payer = P2_ID if out_of_scope_payer else P1_ID
        data["expenses"] = [{
            "id": str(EXPENSE_ID), "ledger_unit_id": str(UNIT_ID),
            "title": "Refund", "original_amount": "-12.5000",
            "original_currency": "USD", "fx_rate": "1.2", "base_amount": "-15.0",
            "occurred_at": "2026-10-10T04:05:06Z",
            "original_expense_id": str(uuid.UUID("50000000-0000-4000-8000-000000000002")),
            "version": 2, "is_deleted": False, "financial_locked": True,
        }]
        data["payments"] = [{
            "id": str(PAYMENT_ID), "expense_id": str(EXPENSE_ID),
            "participant_id": str(payer), "amount": "-12.5000", "base_amount": "-15.0",
        }]
        data["splits"] = [{
            "id": str(SPLIT_ID), "expense_id": str(EXPENSE_ID),
            "participant_id": str(P1_ID), "amount": "-12.5000", "base_amount": "-15.0",
        }]
    return data


def transport_for_rows(
    data: dict[str, list[dict[str, Any]]], *, server_cap: int | None = None,
) -> FunctionTransport:
    def response(url: str, headers: dict[str, str], *_: Any) -> TransportResponse:
        parsed = urllib.parse.urlsplit(url)
        route = parsed.path.split("/rest/v1/", 1)[1]
        rows = data[route]
        query = urllib.parse.parse_qs(parsed.query)
        offset = int(query.get("offset", ["0"])[0])
        limit = int(query.get("limit", ["64"])[0])
        if server_cap is not None:
            limit = min(limit, server_cap)
        page = rows[offset:offset + limit]
        return json_response(page, offset, len(rows))

    return FunctionTransport(response)


def test_scope_resolution_and_expense_read_preserve_payment_and_split_roles() -> None:
    data = source_rows()
    transport = transport_for_rows(data, server_cap=1)
    adapter = make_adapter(transport, page_size=4)
    resolved = asyncio.run(adapter.resolve_scope(
        grant(), ScopeRequest(mode="activity", ui_activity_id_hint=ACTIVITY_ID),
    ))
    assert resolved.activity is not None
    assert resolved.activity.financial_version == 7
    assert resolved.child_scopes[0].configured
    assert resolved.child_scopes[0].participant_ids == (P1_ID,)

    refs = {
        "activity_1": BoundRef("activity", ACTIVITY_ID),
        "participant_1": BoundRef("participant", P1_ID, activity_id=ACTIVITY_ID),
    }
    decision = c.ReadDecision.model_validate({
        "kind": "read", "operation": "read.expenses",
        "criteria": {
            "kind": "expenses", "activity_ref": "activity_1",
            "participant_ref": "participant_1",
        },
    })
    result = asyncio.run(adapter.read(
        USER_ID, grant().turn_id, model_context(
            c.ReadOperation.EXPENSES,
            [("activity", "activity_1"), ("participant", "participant_1")],
            activity_scope="activity_1",
        ), decision, verified=grant(refs),
    ))
    fact = result.expenses[0]
    assert result.complete and result.financial_versions[ACTIVITY_ID] == 7
    assert fact.original_amount == Decimal("-12.5000")
    assert fact.original_expense_id is not None
    assert fact.payments[0].participant_id == P1_ID
    assert fact.payments[0].amount == Decimal("-12.5000")
    assert fact.splits[0].participant_id == P1_ID
    assert fact.splits[0].amount == Decimal("-12.5000")
    assert all("Bearer " + TOKEN == headers["Authorization"] for _, headers in transport.calls)


def test_configured_child_expense_fails_closed_for_out_of_scope_payer() -> None:
    adapter = make_adapter(transport_for_rows(source_rows(out_of_scope_payer=True)))
    decision = c.ReadDecision.model_validate({
        "kind": "read", "operation": "read.expenses",
        "criteria": {"kind": "expenses", "activity_ref": "activity_1"},
    })
    with pytest.raises(BackendReadError) as caught:
        asyncio.run(adapter.read(
            USER_ID, grant().turn_id, model_context(
                c.ReadOperation.EXPENSES, [("activity", "activity_1")],
                activity_scope="activity_1",
            ), decision,
            verified=grant({"activity_1": BoundRef("activity", ACTIVITY_ID)}),
        ))
    assert caught.value.code == "scope_unavailable"


def test_child_scope_change_during_read_discards_expense_batch() -> None:
    data = source_rows()
    scope_reads = 0

    def response(url: str, headers: dict[str, str], *_: Any) -> TransportResponse:
        nonlocal scope_reads
        parsed = urllib.parse.urlsplit(url)
        route = parsed.path.split("/rest/v1/", 1)[1]
        rows = data[route]
        if route == "sub_activity_participants":
            scope_reads += 1
            if scope_reads >= 2:
                rows = [{**rows[0], "participant_id": str(P2_ID)}]
        query = urllib.parse.parse_qs(parsed.query)
        offset = int(query.get("offset", ["0"])[0])
        limit = int(query.get("limit", ["64"])[0])
        return json_response(rows[offset:offset + limit], offset, len(rows))

    adapter = make_adapter(FunctionTransport(response))
    decision = c.ReadDecision.model_validate({
        "kind": "read", "operation": "read.expenses",
        "criteria": {"kind": "expenses", "activity_ref": "activity_1"},
    })
    with pytest.raises(BackendReadError) as caught:
        asyncio.run(adapter.read(
            USER_ID, grant().turn_id,
            model_context(c.ReadOperation.EXPENSES, [("activity", "activity_1")],
                          activity_scope="activity_1"),
            decision, verified=grant({"activity_1": BoundRef("activity", ACTIVITY_ID)}),
        ))
    assert caught.value.code == "data_changed_during_read"
    assert scope_reads == 2


def test_debts_uses_only_ordered_readonly_settlement_rpc() -> None:
    transport = transport_for_rows(source_rows(debt=True))
    adapter = make_adapter(transport)
    decision = c.ReadDecision.model_validate({
        "kind": "read", "operation": "read.debts",
        "criteria": {"kind": "debts", "activity_ref": "activity_1"},
    })
    result = asyncio.run(adapter.read(
        USER_ID, grant().turn_id, model_context(
            c.ReadOperation.DEBTS, [("activity", "activity_1")],
            activity_scope="activity_1",
        ), decision,
        verified=grant({"activity_1": BoundRef("activity", ACTIVITY_ID)}),
    ))
    rpc_calls = [url for url, _ in transport.calls if "/rpc/" in url]
    assert len(rpc_calls) == 1
    rpc_query = urllib.parse.parse_qs(urllib.parse.urlsplit(rpc_calls[0]).query)
    assert rpc_query["order"] == [
        "debtor_participant_id.asc,creditor_participant_id.asc,currency.asc",
    ]
    assert "list_settlement_options" in rpc_calls[0]
    assert "prepayment" not in " ".join(rpc_calls).lower()
    assert result.debts[0].financial_version == 7
    with pytest.raises(BackendReadError):
        adapter._make_url("/rpc/get_expense_repayment_progress", [])


def test_read_rejects_cross_activity_context_even_with_valid_same_user_bindings() -> None:
    other_activity = uuid.UUID("20000000-0000-4000-8000-000000000002")
    decision = c.ReadDecision.model_validate({
        "kind": "read", "operation": "read.debts",
        "criteria": {"kind": "debts", "activity_ref": "activity_2"},
    })
    context = model_context(
        c.ReadOperation.DEBTS,
        [("activity", "activity_1"), ("activity", "activity_2")],
        activity_scope="activity_1",
    )
    verified = grant({
        "activity_1": BoundRef("activity", ACTIVITY_ID),
        "activity_2": BoundRef("activity", other_activity),
    })
    transport = transport_for_rows(source_rows(debt=True))
    adapter = make_adapter(transport)
    with pytest.raises(BackendReadError) as caught:
        asyncio.run(adapter.read(USER_ID, verified.turn_id, context, decision, verified=verified))
    assert caught.value.code == "unsupported_scope"
    assert transport.calls == []


def test_debt_currency_must_be_source_canonical_uppercase() -> None:
    data = source_rows(debt=True)
    data["rpc/list_settlement_options"][0]["currency"] = "usd"
    adapter = make_adapter(transport_for_rows(data))
    decision = c.ReadDecision.model_validate({
        "kind": "read", "operation": "read.debts",
        "criteria": {"kind": "debts", "activity_ref": "activity_1"},
    })
    with pytest.raises(BackendReadError) as caught:
        asyncio.run(adapter.read(
            USER_ID, grant().turn_id,
            model_context(c.ReadOperation.DEBTS, [("activity", "activity_1")],
                          activity_scope="activity_1"),
            decision, verified=grant({"activity_1": BoundRef("activity", ACTIVITY_ID)}),
        ))
    assert caught.value.code == "invalid_upstream_response"


def test_date_max_expense_filter_does_not_overflow() -> None:
    transport = transport_for_rows(source_rows())
    adapter = make_adapter(transport)
    decision = c.ReadDecision.model_validate({
        "kind": "read", "operation": "read.expenses",
        "criteria": {"kind": "expenses", "activity_ref": "activity_1", "to_date": "9999-12-31"},
    })
    asyncio.run(adapter.read(
        USER_ID, grant().turn_id,
        model_context(c.ReadOperation.EXPENSES, [("activity", "activity_1")],
                      activity_scope="activity_1"),
        decision, verified=grant({"activity_1": BoundRef("activity", ACTIVITY_ID)}),
    ))
    expense_request = next(url for url, _ in transport.calls if "/expenses?" in url)
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(expense_request).query)
    assert query["occurred_at"] == ["lte.9999-12-31T23:59:59.999999Z"]


def test_activity_list_excludes_deleted_and_rechecks_membership() -> None:
    rows = source_rows()
    rows["activities"].append({
        **rows["activities"][0],
        "id": str(uuid.UUID("20000000-0000-4000-8000-000000000002")),
        "name": "Deleted", "is_deleted": True,
    })
    transport = transport_for_rows(rows)
    adapter = make_adapter(transport)
    decision = c.ReadDecision.model_validate({
        "kind": "read", "operation": "read.activities",
        "criteria": {"kind": "activities", "status": "any"},
    })
    result = asyncio.run(adapter.read(
        USER_ID, grant().turn_id, model_context(c.ReadOperation.ACTIVITIES),
        decision, verified=grant(),
    ))
    assert [item.name for item in result.activities] == ["Trip"]
    assert any("/activity_members?" in url for url, _ in transport.calls)


def test_scope_none_has_no_financial_facts_or_network_calls() -> None:
    transport = transport_for_rows(source_rows())
    adapter = make_adapter(transport)
    result = asyncio.run(adapter.resolve_scope(grant(), ScopeRequest(mode="none")))
    assert result.mode == "none" and result.activity is None
    assert not result.participants and not result.ledger_units and not result.child_scopes
    assert transport.calls == []


def test_polling_scope_authorization_uses_current_jwt_and_rechecks_membership() -> None:
    transport = transport_for_rows(source_rows())
    adapter = make_adapter(transport)
    asyncio.run(adapter.authorize_api_scope(USER_ID, [ACTIVITY_ID], TOKEN, NOW + timedelta(hours=1)))
    assert len(transport.calls) == 3
    assert all(headers["Authorization"] == f"Bearer {TOKEN}" for _, headers in transport.calls)

    no_member_rows = source_rows()
    no_member_rows["activity_members"] = []
    no_member_adapter = make_adapter(transport_for_rows(no_member_rows))
    with pytest.raises(BackendReadError) as caught:
        asyncio.run(no_member_adapter.authorize_api_scope(
            USER_ID, [ACTIVITY_ID], TOKEN, NOW + timedelta(hours=1),
        ))
    assert caught.value.code == "scope_unavailable"


def test_financial_version_change_discards_expense_batch() -> None:
    data = source_rows()
    activity_reads = 0

    def response(url: str, headers: dict[str, str], *_: Any) -> TransportResponse:
        nonlocal activity_reads
        parsed = urllib.parse.urlsplit(url)
        route = parsed.path.split("/rest/v1/", 1)[1]
        rows = data[route]
        if route == "activities":
            activity_reads += 1
            version = 7 if activity_reads == 1 else 8
            rows = [{**rows[0], "financial_version": version}]
        query = urllib.parse.parse_qs(parsed.query)
        offset = int(query.get("offset", ["0"])[0])
        limit = int(query.get("limit", ["64"])[0])
        return json_response(rows[offset:offset + limit], offset, len(rows))

    adapter = make_adapter(FunctionTransport(response))
    decision = c.ReadDecision.model_validate({
        "kind": "read", "operation": "read.expenses",
        "criteria": {"kind": "expenses", "activity_ref": "activity_1"},
    })
    with pytest.raises(BackendReadError) as caught:
        asyncio.run(adapter.read(
            USER_ID, grant().turn_id, model_context(
                c.ReadOperation.EXPENSES, [("activity", "activity_1")],
                activity_scope="activity_1",
            ), decision,
            verified=grant({"activity_1": BoundRef("activity", ACTIVITY_ID)}),
        ))
    assert caught.value.code == "data_changed_during_read"


def test_verify_financial_versions_uses_bound_activity_and_membership_fences() -> None:
    transport = transport_for_rows(source_rows())
    adapter = make_adapter(transport)
    current_grant = grant({"activity_1": BoundRef("activity", ACTIVITY_ID)})

    result = asyncio.run(adapter.verify_financial_versions(
        current_grant, {ACTIVITY_ID: 7},
    ))

    assert result is None
    assert [urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1] for url, _ in transport.calls] == [
        "activity_members", "activities", "activity_members",
    ]
    assert all(headers["Authorization"] == f"Bearer {TOKEN}" for _, headers in transport.calls)
    activity_query = urllib.parse.parse_qs(urllib.parse.urlsplit(transport.calls[1][0]).query)
    assert activity_query["select"] == ["id,is_deleted,financial_version"]
    assert activity_query["id"] == [f"eq.{ACTIVITY_ID}"]
    assert activity_query["is_deleted"] == ["eq.false"]


def test_verify_financial_versions_rejects_changed_version() -> None:
    data = source_rows()

    def response(url: str, *_: Any) -> TransportResponse:
        parsed = urllib.parse.urlsplit(url)
        route = parsed.path.split("/rest/v1/", 1)[1]
        rows = data[route]
        if route == "activities":
            rows = [{**rows[0], "financial_version": 8}]
        query = urllib.parse.parse_qs(parsed.query)
        offset = int(query.get("offset", ["0"])[0])
        limit = int(query.get("limit", ["64"])[0])
        return json_response(rows[offset:offset + limit], offset, len(rows))

    adapter = make_adapter(FunctionTransport(response))
    current_grant = grant({"activity_1": BoundRef("activity", ACTIVITY_ID)})
    with pytest.raises(BackendReadError) as caught:
        asyncio.run(adapter.verify_financial_versions(current_grant, {ACTIVITY_ID: 7}))
    assert caught.value.code == "data_changed_during_read"


@pytest.mark.parametrize(("status", "code"), [(401, "auth_rejected"), (403, "access_denied")])
def test_verify_financial_versions_maps_auth_failures(status: int, code: str) -> None:
    transport = FunctionTransport(lambda *_: TransportResponse(status, b"", None))
    adapter = make_adapter(transport)
    current_grant = grant({"activity_1": BoundRef("activity", ACTIVITY_ID)})
    with pytest.raises(BackendReadError) as caught:
        asyncio.run(adapter.verify_financial_versions(current_grant, {ACTIVITY_ID: 7}))
    assert caught.value.code == code


def test_verify_financial_versions_rejects_unbound_ids_and_invalid_versions_before_get() -> None:
    transport = FunctionTransport(lambda *_: TransportResponse(200, b"[]", "*/0"))
    adapter = make_adapter(transport)
    other_activity = uuid.UUID("20000000-0000-4000-8000-000000000002")
    current_grant = grant({"activity_1": BoundRef("activity", other_activity)})
    with pytest.raises(BackendReadError) as caught:
        asyncio.run(adapter.verify_financial_versions(current_grant, {ACTIVITY_ID: 7}))
    assert caught.value.code == "invalid_auth_context"
    assert transport.calls == []

    current_grant = grant({"activity_1": BoundRef("activity", ACTIVITY_ID)})
    for invalid in ({ACTIVITY_ID: -1}, {ACTIVITY_ID: True}, {}):
        with pytest.raises(BackendReadError) as caught:
            asyncio.run(adapter.verify_financial_versions(current_grant, invalid))
        assert caught.value.code == "invalid_auth_context"
    assert transport.calls == []


def test_backend_lifecycle_hooks_acquire_no_shared_transport_resource() -> None:
    transport = FunctionTransport(lambda *_: TransportResponse(200, b"[]", "*/0"))
    adapter = make_adapter(transport)

    assert adapter.start() is None
    assert adapter.close() is None
    assert transport.calls == []


def test_per_page_response_byte_cap_is_enforced_at_adapter_boundary() -> None:
    adapter = make_adapter(FunctionTransport(
        lambda *_: TransportResponse(200, b"x" * 8_193, "*/0"),
    ))
    with pytest.raises(BackendReadError) as caught:
        asyncio.run(adapter._get_json_rows("activities", [], grant(), budget=_ReadBudget()))
    assert caught.value.code == "response_too_large"


def test_http_redirect_is_not_followed() -> None:
    request_count = 0

    class RedirectHandler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            nonlocal request_count
            request_count += 1
            while self.rfile.readline() not in (b"\r\n", b""):
                pass
            self.wfile.write(
                b"HTTP/1.1 302 Found\r\nLocation: /rest/v1/activities?secret=redirect\r\n"
                b"Content-Length: 0\r\nConnection: close\r\n\r\n"
            )

    class RedirectServer(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    server = RedirectServer(("127.0.0.1", 0), RedirectHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        adapter = make_adapter(
            None,
            project_url=f"http://127.0.0.1:{server.server_address[1]}",
        )
        with pytest.raises(BackendReadError) as caught:
            asyncio.run(adapter._get_json_rows("activities", [], grant(), budget=_ReadBudget()))
        assert caught.value.code == "upstream_failure"
        assert request_count == 1
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=1)


def test_offline_transport_has_stable_unavailable_code() -> None:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    adapter = make_adapter(None, project_url=f"http://127.0.0.1:{port}", timeout=0.5)
    with pytest.raises(BackendReadError) as caught:
        asyncio.run(adapter._get_json_rows("activities", [], grant(), budget=_ReadBudget()))
    assert caught.value.code == "upstream_unavailable"


@pytest.mark.parametrize("stall", ["headers", "body"])
def test_stdlib_transport_aborts_slow_headers_and_body(stall: str) -> None:
    class SlowHandler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            while self.rfile.readline() not in (b"\r\n", b""):
                pass
            if stall == "headers":
                time.sleep(0.25)
                payload = b"[]"
                head = (
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    b"Content-Range: */0\r\nContent-Length: 2\r\nConnection: close\r\n\r\n"
                )
                try:
                    self.wfile.write(head + payload)
                except OSError:
                    pass
                return
            self.wfile.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                b"Content-Range: */0\r\nContent-Length: 2\r\nConnection: close\r\n\r\n["
            )
            self.wfile.flush()
            time.sleep(0.25)
            try:
                self.wfile.write(b"]")
            except OSError:
                pass

    class SlowServer(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    server = SlowServer(("127.0.0.1", 0), SlowHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        adapter = make_adapter(
            None,
            timeout=0.08,
            project_url=f"http://127.0.0.1:{server.server_address[1]}",
        )
        started = time.monotonic()
        with pytest.raises(BackendReadError) as caught:
            asyncio.run(adapter._get_json_rows("activities", [], grant(), budget=_ReadBudget()))
        assert caught.value.code == "upstream_timeout"
        assert time.monotonic() - started < 0.6
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=1)
