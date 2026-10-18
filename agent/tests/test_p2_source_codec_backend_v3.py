from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlsplit

import pytest
from pydantic import ValidationError

from app import p2_backend as v1
from app import p2_read_backend as backend
from app import p2_read_contracts_v3 as pc
from app import p2_source_codec_v3 as codec


USER = uuid.UUID("00000000-0000-4000-8000-000000000001")
TURN = uuid.UUID("00000000-0000-4000-8000-000000000002")
ACTIVITY = uuid.UUID("00000000-0000-4000-8000-000000000003")
UNIT = uuid.UUID("00000000-0000-4000-8000-000000000004")
P1 = uuid.UUID("00000000-0000-4000-8000-000000000005")
P2 = uuid.UUID("00000000-0000-4000-8000-000000000006")
EXPENSE = uuid.UUID("00000000-0000-4000-8000-000000000007")
REFUND = uuid.UUID("00000000-0000-4000-8000-000000000008")
DEBT = uuid.UUID("00000000-0000-4000-8000-000000000009")
ACCOUNT = uuid.UUID("00000000-0000-4000-8000-000000000010")
USAGE = uuid.UUID("00000000-0000-4000-8000-000000000011")
TRANSFER = uuid.UUID("00000000-0000-4000-8000-000000000012")
COMPONENT = uuid.UUID("00000000-0000-4000-8000-000000000013")
STAMP = "2026-10-14T10:00:00Z"


def _raw_json(value: Any) -> bytes:
    """Serialize JsonNumber tokens as JSON numbers without a float round trip."""
    if isinstance(value, codec.JsonNumber):
        return str(value).encode("ascii")
    if value is None or type(value) in (bool, int, float, str):
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if isinstance(value, list):
        return b"[" + b",".join(_raw_json(item) for item in value) + b"]"
    if isinstance(value, tuple):
        return _raw_json(list(value))
    if isinstance(value, Mapping):
        pieces = []
        for key, item in value.items():
            pieces.append(_raw_json(str(key)) + b":" + _raw_json(item))
        return b"{" + b",".join(pieces) + b"}"
    raise TypeError(type(value).__name__)


def _n(value: str) -> codec.JsonNumber:
    return codec.JsonNumber(value)


def _datasets() -> dict[str, list[dict[str, Any]]]:
    activity = {
        "id": str(ACTIVITY), "name": "旅行账本", "type": "group", "base_currency": "CNY",
        "multi_currency_enabled": True, "is_deleted": False, "archived_at": None,
        "financial_version": _n("7"), "updated_at": STAMP,
    }
    parent = {
        "id": str(EXPENSE), "ledger_unit_id": str(UNIT), "title": "晚餐 🍜",
        "original_amount": _n("48"), "original_currency": "JPY", "fx_rate": _n("0.0000"),
        "base_amount": _n("0"), "occurred_at": "2026-10-14T00:30:00+08:00",
        "original_expense_id": None, "version": _n("2"), "is_deleted": False,
        "financial_locked": False,
    }
    refund = {
        "id": str(REFUND), "ledger_unit_id": str(UNIT), "title": "退款",
        "original_amount": _n("-12.5000"), "original_currency": "JPY", "fx_rate": _n("0.0000"),
        "base_amount": _n("0"), "occurred_at": "2026-10-14T00:45:00+08:00",
        "original_expense_id": str(EXPENSE), "version": _n("1"), "is_deleted": False,
        "financial_locked": False,
    }
    return {
        "activities": [activity],
        "activity_members": [{"activity_id": str(ACTIVITY), "user_id": str(USER)}],
        "ledger_units": [{
            "id": str(UNIT), "activity_id": str(ACTIVITY), "name": "子账本",
            "type": "sub_activity", "is_deleted": False,
            "participant_scope_configured": True, "updated_at": STAMP,
        }],
        "participants": [
            {"id": str(P1), "activity_id": str(ACTIVITY), "name": "甲", "participant_order": _n("0"), "is_deleted": False, "updated_at": STAMP},
            {"id": str(P2), "activity_id": str(ACTIVITY), "name": "乙", "participant_order": _n("1"), "is_deleted": False, "updated_at": STAMP},
        ],
        "sub_activity_participants": [
            {"activity_id": str(ACTIVITY), "ledger_unit_id": str(UNIT), "participant_id": str(P1)},
            {"activity_id": str(ACTIVITY), "ledger_unit_id": str(UNIT), "participant_id": str(P2)},
        ],
        "participant_claims": [{
            "id": "00000000-0000-4000-8000-000000000014", "activity_id": str(ACTIVITY),
            "participant_id": str(P1), "user_id": str(USER), "claimed_at": STAMP,
        }],
        "expenses": [parent, refund],
        "payments": [
            {"id": "00000000-0000-4000-8000-000000000015", "expense_id": str(EXPENSE), "participant_id": str(P1), "amount": _n("48"), "base_amount": _n("0")},
            {"id": "00000000-0000-4000-8000-000000000016", "expense_id": str(REFUND), "participant_id": str(P1), "amount": _n("-12.5"), "base_amount": _n("0")},
        ],
        "splits": [
            {"id": "00000000-0000-4000-8000-000000000017", "expense_id": str(EXPENSE), "participant_id": str(P2), "amount": _n("48"), "base_amount": _n("0")},
            {"id": "00000000-0000-4000-8000-000000000018", "expense_id": str(REFUND), "participant_id": str(P2), "amount": _n("-12.5"), "base_amount": _n("0")},
        ],
        "expense_debts": [{
            "id": str(DEBT), "activity_id": str(ACTIVITY), "ledger_unit_id": str(UNIT),
            "expense_id": str(EXPENSE), "debtor_participant_id": str(P1),
            "creditor_participant_id": str(P2), "amount": _n("0"),
            "original_amount": None, "original_currency": "JPY", "fx_rate": None,
            "created_at": STAMP,
        }],
        "prepayment_accounts": [{
            "id": str(ACCOUNT), "activity_id": str(ACTIVITY), "owner_participant_id": str(P1),
            "custodian_participant_id": str(P2), "currency": "CNY", "balance": _n("0"),
            "updated_at": STAMP,
        }],
        "prepayment_usages": [{
            "id": str(USAGE), "activity_id": str(ACTIVITY), "account_id": str(ACCOUNT),
            "expense_debt_id": str(DEBT), "gross_amount": _n("48"), "amount": _n("48"),
            "created_at": STAMP, "prepayment_currency": "JPY", "prepayment_amount": _n("48"),
            "debt_currency": "JPY", "debt_amount": _n("48"), "base_amount": None,
            "bill_fx_rate": None, "bill_occurred_at": None,
        }],
        "transfers": [{
            "id": str(TRANSFER), "activity_id": str(ACTIVITY), "from_participant_id": str(P2),
            "to_participant_id": str(P1), "type": "prepayment_return", "amount": _n("10"),
            "currency": "CNY", "occurred_at": STAMP, "is_voided": False,
        }],
        "transfer_components": [{
            "id": str(COMPONENT), "activity_id": str(ACTIVITY), "transfer_id": str(TRANSFER),
            "component_type": "prepayment_return", "amount": _n("10.0000"), "created_at": STAMP,
        }],
    }


class SyntheticTransport:
    def __init__(self, datasets: dict[str, list[dict[str, Any]]]) -> None:
        self.datasets = datasets
        self.tables: list[str] = []

    @staticmethod
    def _matches(row: Mapping[str, Any], name: str, value: str) -> bool:
        if value.startswith("eq."):
            expected: Any = value[3:]
            if expected in {"true", "false"}:
                expected = expected == "true"
            return row.get(name) == expected
        if value.startswith("in.(["):
            return row.get(name) in value[5:-1].split(",")
        if value.startswith("in.("):
            return row.get(name) in value[4:-1].split(",")
        return True

    def get(self, url: str, headers: Mapping[str, str], *, timeout: float, max_response_bytes: int, control: Any) -> v1.TransportResponse:
        parsed = urlsplit(url)
        table = parsed.path.rsplit("/", 1)[-1]
        self.tables.append(table)
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        values: dict[str, list[str]] = {}
        for key, value in pairs:
            values.setdefault(key, []).append(value)
        rows = list(self.datasets[table])
        for key, items in values.items():
            if key in {"select", "order", "limit", "offset"}:
                continue
            for item in items:
                rows = [row for row in rows if self._matches(row, key, item)]
        order = values.get("order", ["id.asc"])[0]
        for directive in reversed(order.split(",")):
            column, _, direction = directive.partition(".")
            rows.sort(key=lambda row: (row.get(column) is None, row.get(column)), reverse=direction == "desc")
        offset = int(values.get("offset", ["0"])[0])
        limit = int(values.get("limit", ["16"])[0])
        total = len(rows)
        selected = rows[offset:offset + limit]
        fields = values["select"][0].split(",")
        selected = [{field: row[field] for field in fields} for row in selected]
        if not selected:
            content_range = f"*/{total}"
        else:
            content_range = f"{offset}-{offset + len(selected) - 1}/{total}"
        body = _raw_json(selected)
        if len(body) > max_response_bytes:
            raise AssertionError("synthetic response exceeded requested cap")
        return v1.TransportResponse(200, body, content_range)


class FakeBudget:
    def __init__(self) -> None:
        self.gets = 0
        self.bytes = 0
        self.backend_us = 0
        self.active_us = 0
        self.capture_chain_pages: dict[str, int] = {}
        self.capture_chain_table_pages: dict[tuple[str, str], int] = {}
        self.logical_query_ids: set[str] = set()
        self.max_gets = codec.MAX_GETS_PER_TURN
        self.max_bytes = codec.MAX_TURN_RESPONSE_BYTES
        self.max_backend_us = codec.MAX_BACKEND_US_PER_TURN
        self.max_active_us = codec.MAX_ACTIVE_US_PER_TURN
        self.capture_number = 0

    def test_only_accept_p2_v3_admission_metadata(
        self, admission: codec.AdmissionOnlyBinding,
        projection: codec.P2V3ScopeMetadataProjection,
    ) -> codec.P2V3ScopeMetadataProjection:
        """Preserve source-shape coverage without claiming Store acceptance."""
        assert admission.reference_registry is None
        return projection

    def remaining_limits(self, binding: codec.SourceBinding, *, logical_query_id: str | None = None, capture_chain_id: str | None = None, table: str | None = None) -> codec.RemainingBudget:
        return codec.RemainingBudget(
            active_us=max(0, self.max_active_us - self.active_us),
            backend_us=max(0, self.max_backend_us - self.backend_us),
            response_bytes=max(0, self.max_bytes - self.bytes),
            get_attempts=max(0, self.max_gets - self.gets),
            turn_remaining_us=max(0, self.max_active_us - self.active_us),
            capture_chain_pages=self.capture_chain_pages.get(capture_chain_id or "", 0),
            capture_chain_table_pages=self.capture_chain_table_pages.get((capture_chain_id or "", table or ""), 0),
        )

    def reserve_get(self, binding: codec.SourceBinding, *, source_role: str, request_digest: str, active_limit_us: int, backend_limit_us: int, response_bytes_limit: int, logical_query_id: str | None = None, capture_chain_id: str | None = None, table: str | None = None) -> str:
        if self.gets >= self.max_gets or self.bytes >= self.max_bytes or self.backend_us >= self.max_backend_us or self.active_us >= self.max_active_us:
            raise backend.P2ReadBackendError("read_limit_exceeded")
        if capture_chain_id is not None:
            if self.capture_chain_pages.get(capture_chain_id, 0) >= codec.MAX_SOURCE_PAGES_PER_CAPTURE_CHAIN or self.capture_chain_table_pages.get((capture_chain_id, table or ""), 0) >= codec.MAX_PAGES_PER_TABLE:
                raise backend.P2ReadBackendError("read_limit_exceeded")
            self.capture_chain_pages[capture_chain_id] = self.capture_chain_pages.get(capture_chain_id, 0) + 1
            key = (capture_chain_id, table or "")
            self.capture_chain_table_pages[key] = self.capture_chain_table_pages.get(key, 0) + 1
        self.gets += 1
        return f"res-{self.gets}"

    def mark_dispatch_started(self, binding: codec.SourceBinding, reservation_id: str) -> None:
        return None

    def settle_get(self, binding: codec.SourceBinding, reservation_id: str, *, outcome: str, actual_active_us: int, actual_backend_us: int, actual_response_bytes: int, raw_body_sha256: str | None) -> None:
        self.backend_us += actual_backend_us
        self.active_us += actual_active_us
        self.bytes += actual_response_bytes

    def record_cost_only_capture(self, binding: codec.SourceBinding, reservation_id: str, *, http_status: int, content_range: str | None, returned_count: int, response_bytes: int, raw_body_sha256: str, observed_at: datetime) -> str:
        self.capture_number += 1
        return f"capture-{self.capture_number}"

    def reserve_processing(self, binding: codec.SourceBinding, *, active_limit_us: int, backend_limit_us: int) -> str:
        return f"cpu-{self.capture_number}"

    def settle_processing(self, binding: codec.SourceBinding, reservation_id: str, *, actual_active_us: int, actual_backend_us: int) -> None:
        self.active_us += actual_active_us
        self.backend_us += actual_backend_us


class FakeLocator:
    def __init__(self, identity: codec.V3ExecutionIdentity) -> None:
        self.identity = identity
        self.refs: dict[tuple[str, uuid.UUID, uuid.UUID | None, uuid.UUID | None], str] = {}
        self.entities: dict[str, tuple[str, uuid.UUID]] = {}
        self.captures: dict[str, str] = {}
        self.principal_ref = self.ref("principal")
        self.entities[self.principal_ref] = ("principal", USER)
        self.owner_ref = self.ref("owner")
        self.descriptors: dict[str, codec.V3QueryDescriptor] = {}
        self.evidence: dict[tuple[str, str, int], str] = {}
        self.continuations: dict[tuple[str, str], codec.V3ContinuationProof] = {}
        self.query_sequence = 0
        self.query_for_logical: dict[str, str] = {}
        self._configured_source_origin: tuple[str, str] | None = None

    def bind_configured_source_origin(self, project_url: str) -> None:
        """Mirror the Store registry's write-once HTTPS origin pin.

        The adapter requires this port before the first query GET, and the
        acceptance path reads ``_configured_source_origin`` back, so the fake
        has to validate and retain the same normalized tuple.
        """
        if type(project_url) is not str or len(project_url) > 2048:
            raise backend.P2ReadBackendError("invalid_auth_context")
        parts = urlsplit(project_url)
        if (
            parts.scheme != "https" or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.query or parts.fragment
            or parts.path not in ("", "/")
        ):
            raise backend.P2ReadBackendError("invalid_auth_context")
        origin = (parts.scheme, parts.netloc.lower())
        if self._configured_source_origin is not None and self._configured_source_origin != origin:
            raise backend.P2ReadBackendError("invalid_auth_context")
        self._configured_source_origin = origin

    @staticmethod
    def ref(seed: str) -> str:
        return "ref_" + uuid.uuid5(uuid.NAMESPACE_URL, seed + str(uuid.uuid4())).hex[:22]

    def bind_entity(self, kind: str, entity_id: uuid.UUID, *, activity_id: uuid.UUID | None = None, ledger_unit_id: uuid.UUID | None = None) -> str:
        key = (kind, entity_id, activity_id, ledger_unit_id)
        if key not in self.refs:
            token = self.ref(f"{kind}:{entity_id}:{activity_id}:{ledger_unit_id}")
            self.refs[key] = token
            self.entities[token] = (kind, entity_id)
        return self.refs[key]

    def resolve_entity(self, opaque_ref: str, kind: str, *, activity_id: uuid.UUID) -> uuid.UUID:
        found = self.entities.get(opaque_ref)
        if found is None or found[0] != kind:
            raise backend.P2ReadBackendError("unsupported_scope")
        return found[1]

    def bind_capture(self, capture_id: str, *, identity: codec.V3ExecutionIdentity) -> str:
        return self.captures.setdefault(capture_id, self.ref("capture:" + capture_id))

    def resolve_principal(self, principal_ref: str) -> uuid.UUID:
        if principal_ref != self.principal_ref:
            raise backend.P2ReadBackendError("invalid_auth_context")
        return USER

    def owner_turn_ref(self, *, identity: codec.V3ExecutionIdentity) -> str:
        return self.owner_ref

    def resolve_activity_ref(self, activity_ref: str) -> uuid.UUID:
        return self.resolve_entity(activity_ref, "activity", activity_id=ACTIVITY)

    def query_ref(self, logical_query_id: str, *, identity: codec.V3ExecutionIdentity) -> str:
        return self.query_for_logical.setdefault(logical_query_id, self.ref("query:" + logical_query_id))

    def source_ref(self, logical_query_id: str, *, identity: codec.V3ExecutionIdentity, source_kind: str) -> str:
        return self.ref("source:" + logical_query_id + ":" + source_kind)

    def load_query_descriptor(self, query_ref: str, *, identity: codec.V3ExecutionIdentity) -> codec.V3QueryDescriptor:
        return self.descriptors[query_ref]

    def query_evidence_ref(self, logical_query_id: str, attempt_id: str, *, identity: codec.V3ExecutionIdentity, page_index: int) -> str:
        key = (logical_query_id, attempt_id, page_index)
        return self.evidence.setdefault(key, "qev_" + uuid.uuid5(uuid.NAMESPACE_URL, str(key)).hex[:22])

    def result_ref(self, logical_query_id: str, attempt_id: str, *, identity: codec.V3ExecutionIdentity, page_index: int) -> str:
        return self.ref(f"result:{logical_query_id}:{attempt_id}:{page_index}")

    def criteria_ref(self, criteria_digest: str, *, identity: codec.V3ExecutionIdentity) -> str:
        return self.ref("criteria:" + criteria_digest)

    def issue_continuation(self, *, query_ref: str, attempt_id: str, page_index: int, qev_ref: str, expires_at: datetime, source_proof: codec.V3ContinuationProof) -> str:
        token = self.ref(f"continue:{query_ref}:{attempt_id}:{page_index}")
        self.continuations[(query_ref, token)] = source_proof
        return token

    def load_continuation_proof(self, *, query_ref: str, next_page_ref: str, identity: codec.V3ExecutionIdentity) -> codec.V3ContinuationProof:
        return self.continuations[(query_ref, next_page_ref)]

    def consume_continuation(self, *, query_ref: str, next_page_ref: str, turn_id: uuid.UUID) -> codec.QueryAttemptBinding:
        proof = self.continuations.pop((query_ref, next_page_ref))
        self.query_sequence += 1
        return codec.QueryAttemptBinding(
            identity=self.identity, logical_query_id=proof.logical_query_id,
            query_attempt_id=f"attempt-{self.query_sequence + 1}", page_index=proof.page_index + 1,
            claim_token="cpu-fake-claim",
        )


def _identity() -> codec.V3ExecutionIdentity:
    return codec.V3ExecutionIdentity(
        owner_user_id=USER, turn_id=TURN, generation=1, input_seq=0,
        input_digest="a" * 64, claim_epoch=1, authority_epoch=1, context_revision=1,
    )


def _request(operation: pc.P2ReadOperation, scope: pc.P2Scope | None, activity_ref: str) -> pc.P2ReadQueryRequest:
    if not activity_ref:
        activity_ref = "ref_" + "0" * 22
    criteria: Any = {
        pc.P2ReadOperation.ACTIVITIES: pc.ActivityCriteria(kind="activities", status="any"),
        pc.P2ReadOperation.EXPENSES: pc.ExpenseCriteria(kind="expenses", activity_ref=activity_ref, from_date=date(2026, 10, 13), to_date=date(2026, 10, 13)),
        pc.P2ReadOperation.DEBTS: pc.DebtCriteria(kind="debts", activity_ref=activity_ref, currency="JPY"),
        pc.P2ReadOperation.REFUND_EVENTS: pc.RefundEventCriteria(kind="refund_events", activity_ref=activity_ref),
        pc.P2ReadOperation.PREPAYMENT_ACCOUNTS: pc.PrepaymentAccountsCriteria(kind="prepayment_accounts", activity_ref=activity_ref),
        pc.P2ReadOperation.PREPAYMENT_USAGES: pc.PrepaymentUsagesCriteria(kind="prepayment_usages", activity_ref=activity_ref),
        pc.P2ReadOperation.PREPAYMENT_RETURN_EVENTS: pc.PrepaymentReturnCriteria(kind="prepayment_return_events", activity_ref=activity_ref),
    }[operation]
    return pc.P2ReadQueryRequest(
        kind="read", message_type="query_request", profile_id=pc.P2_V3_CANDIDATE_PROFILE_ID,
        versions=pc.P2_V3_VERSIONS, operation=operation, criteria=criteria, scope=scope,
    )


def _harness() -> tuple[backend.P2ReadBackendAdapter, codec.V3ExecutionIdentity, FakeLocator, FakeBudget, SyntheticTransport, v1.VerifiedReadContext, codec.AdmissionOnlyBinding]:
    identity = _identity()
    locator = FakeLocator(identity)
    budget = FakeBudget()
    transport = SyntheticTransport(_datasets())
    verified = v1.VerifiedReadContext(
        owner_user_id=USER, turn_id=TURN, principal_user_id=USER, access_token="synthetic.jwt.token",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5), refs_by_opaque_token={},
    )
    adapter = backend.P2ReadBackendAdapter(
        v1.P2BackendConfig(
            project_url="https://synthetic.invalid", publishable_key="sb_publishable_synthetic_cpu_only",
            timeout_seconds=2, page_size=16, max_pages=4, max_rows_per_query=64,
            max_requests_per_read=48, max_total_response_bytes=4_194_304,
            max_total_seconds=20, max_facts=16,
        ),
        transport=transport, v3_budget_port=budget, v3_locator_port=locator,
    )
    admission = codec.AdmissionOnlyBinding(identity, "admission-cpu", "synthetic-claim")
    return adapter, identity, locator, budget, transport, verified, admission


@pytest.mark.parametrize("operation", list(pc.P2ReadOperation))
def test_v3_reads_use_real_fixed_get_plan_and_return_typed_facts(operation: pc.P2ReadOperation) -> None:
    async def run() -> tuple[pc.P2ReadBackendResult, FakeBudget, SyntheticTransport]:
        adapter, identity, locator, budget, transport, verified, admission = _harness()
        if operation is pc.P2ReadOperation.ACTIVITIES:
            request = _request(operation, None, "")
            scope_projection = None
        else:
            scope_projection = await adapter.admit_scope_v3(
                verified, admission, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
            )
            assert scope_projection is not None
            activity_ref = scope_projection.snapshot.activity_ref
            unit_ref = locator.bind_entity("ledger_unit", UNIT, activity_id=ACTIVITY, ledger_unit_id=UNIT)
            scope = pc.P2Scope(
                scope_kind="ledger_unit", scope_ref=unit_ref,
                activity_ref=activity_ref, ledger_unit_ref=unit_ref,
            )
            request = _request(operation, scope, activity_ref)
            if operation is pc.P2ReadOperation.PREPAYMENT_USAGES:
                expense_ref = locator.bind_entity(
                    "expense", EXPENSE, activity_id=ACTIVITY, ledger_unit_id=UNIT,
                )
                criteria = pc.PrepaymentUsagesCriteria(
                    kind="prepayment_usages", activity_ref=activity_ref,
                    expense_ref=expense_ref,
                )
                request = pc.P2ReadQueryRequest(
                    kind="read", message_type="query_request",
                    profile_id=pc.P2_V3_CANDIDATE_PROFILE_ID,
                    versions=pc.P2_V3_VERSIONS, operation=operation,
                    criteria=criteria, scope=scope,
                )
        logical_id = "logical-" + operation.value
        query_ref = locator.query_ref(logical_id, identity=identity)
        locator.query_sequence += 1
        binding = codec.QueryAttemptBinding(identity, logical_id, "attempt-1", 0, "synthetic-claim")
        locator.descriptors[query_ref] = codec.V3QueryDescriptor(
            request=request,
            public_request_digest=backend._canonical_sha(request.model_dump(mode="json", exclude_none=False)),
            normalized_selection_digest=backend._canonical_sha({
                "criteria": request.criteria.model_dump(mode="json", exclude_none=False), "ui_expense_ids": (),
            }),
        )
        grant = pc.P2SourceAuthorizationGrant(
            principal_ref=locator.principal_ref, owner_turn_ref=locator.owner_ref,
            generation=identity.generation, source_input_seq=identity.input_seq,
            input_digest=identity.input_digest, operation=operation, scope=request.scope,
            criteria_digest=pc.p2_criteria_digest(request.criteria),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=2), grant_ref=locator.ref("grant"),
        )
        result = await adapter.read_candidate_v3(
            request, verified, grant, admission=admission,
            admission_projection=scope_projection, query_binding=binding,
            context_version="server-context-r3",
        )
        budget.logical_query_ids.add(logical_id)
        return result, budget, transport

    result, budget, transport = asyncio.run(run())
    assert result.operation is operation
    assert result.query_evidence.profile_id == pc.P2_V3_CANDIDATE_PROFILE_ID
    assert result.query_evidence.versions == pc.P2_V3_VERSIONS
    assert result.query_evidence.query_evidence_ref.startswith("qev_")
    assert len(result.query_evidence.body_digest) == 64
    assert all(item.query_evidence_ref == result.query_evidence.query_evidence_ref for item in result.page.items)
    assert all(not re.search(r"00000000-0000-4000-8000-0000000000", item.model_dump_json()) for item in result.page.items)
    assert result.page.page_index == 0
    if operation is pc.P2ReadOperation.ACTIVITIES:
        assert {"activity_members", "activities"}.issubset(set(transport.tables))
        assert len(result.page.items) == 1
        activity_fact = result.page.items[0]
        assert isinstance(activity_fact, pc.ActivityFact)
        activity_payload = activity_fact.model_dump(mode="python")
        with pytest.raises(ValidationError):
            pc.ActivityFact.model_validate({**activity_payload, "observed_at": None}, strict=True)
        with pytest.raises(ValidationError):
            pc.ActivityFact.model_validate({**activity_payload, "observed_at": datetime(2026, 10, 14, 10, 0)}, strict=True)
    else:
        # Six metadata tables are fenced before and after every financial read.
        assert transport.tables.count("activity_members") == 3
        assert transport.tables.count("activities") >= 2
        assert budget.capture_chain_pages["attempt-1"] == result.query_evidence.page_count
        assert budget.logical_query_ids == {"logical-" + operation.value}
    if operation is pc.P2ReadOperation.EXPENSES:
        item = result.page.items[0]
        assert isinstance(item, pc.ExpenseFact)
        assert item.title == "晚餐 🍜"
        assert item.signed_base_amount == "0"
        assert item.occurred_at.astimezone(timezone.utc).date() == date(2026, 10, 13)
        expense_payload = item.model_dump(mode="python")
        for invalid_time in (None, datetime(2026, 10, 14, 10, 0)):
            with pytest.raises(ValidationError) as error:
                pc.ExpenseFact.model_validate(
                    {**expense_payload, "occurred_at": invalid_time}, strict=True
                )
            assert any(
                detail["loc"] == ("occurred_at",)
                and detail["type"] != "extra_forbidden"
                for detail in error.value.errors()
            )
    if operation is pc.P2ReadOperation.DEBTS:
        item = result.page.items[0]
        assert isinstance(item, pc.DebtFact)
        assert item.original_amount is None and item.original_currency == "JPY"
        assert item.base_amount == "0"
    if operation is pc.P2ReadOperation.REFUND_EVENTS:
        item = result.page.items[0]
        assert isinstance(item, pc.RefundEventFact)
        assert item.signed_original_amount == "-12.5000" and item.signed_base_amount == "0"
        assert item.lineage_status == "verified_same_activity_parent"
    if operation is pc.P2ReadOperation.PREPAYMENT_ACCOUNTS:
        assert isinstance(result.page.items[0], pc.PrepaymentAccountFact)
        assert result.page.items[0].balance == "0"
    if operation is pc.P2ReadOperation.PREPAYMENT_USAGES:
        item = result.page.items[0]
        assert isinstance(item, pc.PrepaymentUsageFact)
        assert item.base_amount is None and item.base_currency is None
        assert item.bill_fx_rate is None
        assert item.bill_occurred_at is None
        raw = item.model_dump(mode="python")
        none_json = item.model_dump_json()
        assert pc.PrepaymentUsageFact.model_validate_json(none_json, strict=True).bill_occurred_at is None

        aware_bill_time = datetime.fromisoformat(STAMP.replace("Z", "+00:00"))
        aware_raw = {**raw, "bill_occurred_at": aware_bill_time}
        aware_fact = pc.PrepaymentUsageFact.model_validate(aware_raw, strict=True)
        assert aware_fact.bill_occurred_at == aware_bill_time
        assert pc.PrepaymentUsageFact.model_validate_json(
            aware_fact.model_dump_json(), strict=True
        ).bill_occurred_at == aware_bill_time

        for invalid in (datetime(2026, 10, 14, 10, 0), "2026-10-14T10:00:00Z", 1):
            with pytest.raises(ValidationError):
                pc.PrepaymentUsageFact.model_validate({**raw, "bill_occurred_at": invalid}, strict=True)
    if operation is pc.P2ReadOperation.PREPAYMENT_RETURN_EVENTS:
        assert isinstance(result.page.items[0], pc.PrepaymentReturnEventFact)
        assert result.page.items[0].amount == "10"


def test_exact_json_numeric_lexemes_nullable_source_columns_and_utc_date_semantics() -> None:
    rows = codec.parse_source_rows(
        b'[{"id":"00000000-0000-4000-8000-000000000009","activity_id":"00000000-0000-4000-8000-000000000003","ledger_unit_id":"00000000-0000-4000-8000-000000000004","expense_id":"00000000-0000-4000-8000-000000000007","debtor_participant_id":"00000000-0000-4000-8000-000000000005","creditor_participant_id":"00000000-0000-4000-8000-000000000006","amount":0,"original_amount":null,"original_currency":"JPY","fx_rate":null,"created_at":"2026-10-14T10:00:00Z"}]',
        "expense_debts",
    )
    assert rows[0]["amount"] == "0" and type(rows[0]["amount"]) is codec.JsonNumber
    assert rows[0]["original_amount"] is None and rows[0]["original_currency"] == "JPY"
    assert codec._time({"t": "2026-10-14T00:30:00+08:00"}, "t").date() == date(2026, 10, 13)
    with pytest.raises(codec.SourceCodecError, match="duplicate_json_key"):
        codec.parse_source_rows(b'[{"id":"x","id":"y"}]', "activities")
    with pytest.raises(codec.SourceCodecError):
        codec.parse_source_rows(b'[{"not":"a source row"}]', "activities")
    bad = _raw_json([{
        **_datasets()["expense_debts"][0], "amount": _n("10000000000000000000"),
    }])
    with pytest.raises(codec.SourceCodecError, match="invalid_source_numeric_lexeme"):
        codec.parse_source_rows(bad, "expense_debts")


def test_preaccept_activity_page_never_mints_continuation_before_store_acceptance() -> None:
    async def run() -> None:
        adapter, identity, locator, budget, transport, verified, admission = _harness()
        many_activities = []
        many_members = []
        for i in range(17):
            aid = uuid.UUID(int=1000 + i)
            many_activities.append({
                "id": str(aid), "name": f"旅行{i}", "type": "group", "base_currency": "CNY",
                "multi_currency_enabled": True, "is_deleted": False, "archived_at": None,
                "financial_version": _n("1"), "updated_at": STAMP,
            })
            many_members.append({"activity_id": str(aid), "user_id": str(USER)})
        transport.datasets["activities"] = many_activities
        transport.datasets["activity_members"] = many_members
        request = _request(pc.P2ReadOperation.ACTIVITIES, None, "")
        logical_id = "continuation-activities"
        query_ref = locator.query_ref(logical_id, identity=identity)
        locator.descriptors[query_ref] = codec.V3QueryDescriptor(
            request=request,
            public_request_digest=backend._canonical_sha(request.model_dump(mode="json", exclude_none=False)),
            normalized_selection_digest=backend._canonical_sha({
                "criteria": request.criteria.model_dump(mode="json", exclude_none=False), "ui_expense_ids": (),
            }),
        )
        budget.logical_query_ids.add(logical_id)
        binding = codec.QueryAttemptBinding(identity, logical_id, "attempt-1", 0, "claim")
        def fresh_grant(seed: str) -> pc.P2SourceAuthorizationGrant:
            return pc.P2SourceAuthorizationGrant(
                principal_ref=locator.principal_ref, owner_turn_ref=locator.owner_ref, generation=1,
                source_input_seq=0, input_digest=identity.input_digest, operation=request.operation,
                scope=None, criteria_digest=pc.p2_criteria_digest(request.criteria),
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=2), grant_ref=locator.ref(seed),
            )
        first = await adapter.read_candidate_v3(
            request, verified, fresh_grant("grant-first"), admission=admission, admission_projection=None,
            query_binding=binding, context_version="ctx",
        )
        assert isinstance(first, backend.P2V3PendingSourceAttempt)
        assert first.page.has_more
        assert not hasattr(first.page, "next_page_ref")
        assert locator.continuations == {}
        assert budget.logical_query_ids == {logical_id}
        assert budget.capture_chain_pages == {"attempt-1": 4}

    asyncio.run(run())


def test_expenses_17_facts_pending_page_keeps_source_captures_without_capability() -> None:
    async def run() -> tuple[backend.P2V3PendingSourceAttempt, FakeBudget, FakeLocator]:
        adapter, identity, locator, budget, transport, verified, admission = _harness()
        many_expenses: list[dict[str, Any]] = []
        many_payments: list[dict[str, Any]] = []
        many_splits: list[dict[str, Any]] = []
        for index in range(17):
            expense_id = uuid.UUID(int=10_000 + index)
            many_expenses.append({
                "id": str(expense_id), "ledger_unit_id": str(UNIT),
                "title": f"餐费 {index}", "original_amount": _n("25.0000"),
                "original_currency": "CNY", "fx_rate": _n("1.0000000000"),
                "base_amount": _n("25.0"), "occurred_at": "2026-10-14T00:30:00+08:00",
                "original_expense_id": None, "version": _n("1"),
                "is_deleted": False, "financial_locked": False,
            })
            many_payments.append({
                "id": str(uuid.UUID(int=20_000 + index)), "expense_id": str(expense_id),
                "participant_id": str(P1), "amount": _n("25"), "base_amount": _n("25.0"),
            })
            many_splits.append({
                "id": str(uuid.UUID(int=30_000 + index)), "expense_id": str(expense_id),
                "participant_id": str(P2), "amount": _n("25.0000"), "base_amount": _n("25"),
            })
        transport.datasets["expenses"] = many_expenses
        transport.datasets["payments"] = many_payments
        transport.datasets["splits"] = many_splits
        projection = await adapter.admit_scope_v3(
            verified, admission, ui_activity_id_hint=ACTIVITY,
            ui_ledger_unit_id_hint=UNIT,
        )
        assert projection is not None
        activity_ref = projection.snapshot.activity_ref
        unit_ref = projection.snapshot.scope_ref
        assert unit_ref is not None
        scope = pc.P2Scope(
            scope_kind="ledger_unit", scope_ref=unit_ref,
            activity_ref=activity_ref, ledger_unit_ref=unit_ref,
        )
        request = _request(pc.P2ReadOperation.EXPENSES, scope, activity_ref)
        logical_id = "logical-expenses-17"
        query_ref = locator.query_ref(logical_id, identity=identity)
        locator.descriptors[query_ref] = codec.V3QueryDescriptor(
            request=request,
            public_request_digest=backend._canonical_sha(request.model_dump(mode="json", exclude_none=False)),
            normalized_selection_digest=backend._canonical_sha({
                "criteria": request.criteria.model_dump(mode="json", exclude_none=False),
                "ui_expense_ids": (),
            }),
        )
        budget.logical_query_ids.add(logical_id)

        def grant(seed: str) -> pc.P2SourceAuthorizationGrant:
            return pc.P2SourceAuthorizationGrant(
                principal_ref=locator.principal_ref, owner_turn_ref=locator.owner_ref,
                generation=identity.generation, source_input_seq=identity.input_seq,
                input_digest=identity.input_digest, operation=request.operation,
                scope=scope, criteria_digest=pc.p2_criteria_digest(request.criteria),
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=2),
                grant_ref=locator.ref(seed),
            )

        first = await adapter.read_candidate_v3(
            request, verified, grant("expense-grant-page-0"), admission=admission,
            admission_projection=projection,
            query_binding=codec.QueryAttemptBinding(identity, logical_id, "expense-attempt-1", 0, "claim-1"),
            context_version="ctx-expense",
        )
        assert first.query_evidence.matched_count == 17
        assert first.query_evidence.source_query_complete is True
        assert first.query_evidence.page_count == 18
        assert len(first.page.items) == 16 and first.page.has_more
        assert not hasattr(first.page, "next_page_ref")
        assert first.projection.historical.page.has_more is True
        assert len(first.bootstrap_captures) == 6
        assert len(first.query_captures) == 18
        # Every query GET is dispatched under this query attempt, so all 18
        # query captures are attempt-bound at page 0 and carry no admission id.
        # Admission-bound metadata GETs live in bootstrap_captures instead.
        assert all(page.witness.binding_kind == "query_attempt" for page in first.query_captures)
        assert all(
            page.witness.admission_id is None
            and page.witness.logical_query_id == logical_id
            and page.witness.query_attempt_id == "expense-attempt-1"
            and page.witness.page_index == 0
            for page in first.query_captures
        )
        assert all(page.witness.binding_kind == "admission" for page in first.bootstrap_captures)
        assert all(page.raw_body and page.request_url and page.witness.capture_id for page in first.bootstrap_captures + first.query_captures)
        assert not locator.continuations
        pending_repr = repr(first)
        assert "餐费 0" not in pending_repr
        assert str(EXPENSE) not in pending_repr
        assert verified.access_token not in pending_repr
        altered_raw = replace(first.query_captures[0], raw_body=first.query_captures[0].raw_body + b" ")
        with pytest.raises(ValueError, match="pending source capture"):
            replace(first, query_captures=(altered_raw, *first.query_captures[1:]))
        altered_witness = replace(
            first.query_captures[-1].witness,
            query_attempt_id="foreign-attempt",
        )
        with pytest.raises(ValueError, match="pending source capture"):
            replace(
                first,
                query_captures=(*first.query_captures[:-1], replace(first.query_captures[-1], witness=altered_witness)),
            )
        wrong_admission_page = replace(
            first.query_captures[0],
            witness=replace(first.query_captures[0].witness, admission_id="foreign-admission"),
        )
        with pytest.raises(ValueError, match="pending source capture"):
            replace(first, query_captures=(wrong_admission_page, *first.query_captures[1:]))
        assert budget.gets == 24  # initial six-row metadata admission plus first 18-GET chain
        assert budget.capture_chain_pages == {"expense-attempt-1": 18}
        assert budget.logical_query_ids == {logical_id}
        return first, budget, locator

    first, budget, _locator = asyncio.run(run())
    assert first.page.items[0].fact_kind == "expense"
    assert budget.bytes < codec.MAX_TURN_RESPONSE_BYTES
    assert budget.backend_us < codec.MAX_BACKEND_US_PER_TURN


@pytest.mark.parametrize("exhaustion", ["gets", "bytes", "backend"])
def test_turn_budget_exhaustion_is_cumulative_and_stops_before_dispatch(exhaustion: str) -> None:
    async def run() -> tuple[FakeBudget, SyntheticTransport]:
        adapter, identity, locator, budget, transport, verified, admission = _harness()
        request = _request(pc.P2ReadOperation.ACTIVITIES, None, "")
        logical_id = "logical-budget-stop-" + exhaustion
        query_ref = locator.query_ref(logical_id, identity=identity)
        locator.descriptors[query_ref] = codec.V3QueryDescriptor(
            request=request,
            public_request_digest=backend._canonical_sha(request.model_dump(mode="json", exclude_none=False)),
            normalized_selection_digest=backend._canonical_sha({
                "criteria": request.criteria.model_dump(mode="json", exclude_none=False),
                "ui_expense_ids": (),
            }),
        )
        query = codec.QueryAttemptBinding(identity, logical_id, "attempt-budget", 0, "claim")
        grant = pc.P2SourceAuthorizationGrant(
            principal_ref=locator.principal_ref, owner_turn_ref=locator.owner_ref,
            generation=identity.generation, source_input_seq=identity.input_seq,
            input_digest=identity.input_digest, operation=request.operation, scope=None,
            criteria_digest=pc.p2_criteria_digest(request.criteria),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=2), grant_ref=locator.ref("budget-grant"),
        )
        if exhaustion == "gets":
            budget.gets = codec.MAX_GETS_PER_TURN
        elif exhaustion == "bytes":
            budget.bytes = codec.MAX_TURN_RESPONSE_BYTES
        else:
            budget.backend_us = codec.MAX_BACKEND_US_PER_TURN
        with pytest.raises(backend.P2ReadBackendError):
            await adapter.read_candidate_v3(
                request, verified, grant, admission=admission,
                admission_projection=None, query_binding=query, context_version="ctx",
            )
        return budget, transport

    budget, transport = asyncio.run(run())
    assert transport.tables == []
    assert budget.gets in {codec.MAX_GETS_PER_TURN, 0}


def test_capture_chain_32_boundary_is_separate_from_logical_query_and_turn_budget() -> None:
    async def run() -> tuple[FakeBudget, SyntheticTransport]:
        adapter, identity, locator, budget, transport, verified, admission = _harness()
        projection = await adapter.admit_scope_v3(
            verified, admission, ui_activity_id_hint=ACTIVITY,
            ui_ledger_unit_id_hint=UNIT,
        )
        assert projection is not None
        scope = pc.P2Scope(
            scope_kind="ledger_unit", scope_ref=projection.snapshot.scope_ref,
            activity_ref=projection.snapshot.activity_ref,
            ledger_unit_ref=projection.snapshot.scope_ref,
        )
        request = _request(pc.P2ReadOperation.PREPAYMENT_ACCOUNTS, scope, scope.activity_ref or "")
        logical_id = "logical-chain-boundary"
        query_ref = locator.query_ref(logical_id, identity=identity)
        locator.descriptors[query_ref] = codec.V3QueryDescriptor(
            request=request,
            public_request_digest=backend._canonical_sha(request.model_dump(mode="json", exclude_none=False)),
            normalized_selection_digest=backend._canonical_sha({
                "criteria": request.criteria.model_dump(mode="json", exclude_none=False),
                "ui_expense_ids": (),
            }),
        )
        budget.capture_chain_pages["attempt-at-limit"] = codec.MAX_SOURCE_PAGES_PER_CAPTURE_CHAIN
        grant = pc.P2SourceAuthorizationGrant(
            principal_ref=locator.principal_ref, owner_turn_ref=locator.owner_ref,
            generation=identity.generation, source_input_seq=identity.input_seq,
            input_digest=identity.input_digest, operation=request.operation,
            scope=scope, criteria_digest=pc.p2_criteria_digest(request.criteria),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=2), grant_ref=locator.ref("chain-grant"),
        )
        with pytest.raises(backend.P2ReadBackendError, match="read_limit_exceeded"):
            await adapter.read_candidate_v3(
                request, verified, grant, admission=admission,
                admission_projection=projection,
                query_binding=codec.QueryAttemptBinding(identity, logical_id, "attempt-at-limit", 0, "claim"),
                context_version="ctx",
            )
        return budget, transport

    budget, transport = asyncio.run(run())
    assert transport.tables == ["activities", "activity_members", "ledger_units", "participants", "sub_activity_participants", "participant_claims"]
    assert budget.gets == 6  # metadata admission counted to Turn; cap rejected chain before its first page
    assert budget.capture_chain_pages["attempt-at-limit"] == codec.MAX_SOURCE_PAGES_PER_CAPTURE_CHAIN


def test_ui_expense_selection_is_unique_bounded_and_canonicalized() -> None:
    request = _request(pc.P2ReadOperation.ACTIVITIES, None, "")
    values = tuple(uuid.UUID(int=50_000 + index) for index in (3, 1, 2))
    descriptor = codec.V3QueryDescriptor(request=request, ui_expense_ids=values)
    assert descriptor.ui_expense_ids == tuple(sorted(values, key=str))
    with pytest.raises(ValueError):
        codec.V3QueryDescriptor(request=request, ui_expense_ids=(values[0], values[0]))
    with pytest.raises(ValueError):
        codec.V3QueryDescriptor(
            request=request,
            ui_expense_ids=tuple(uuid.UUID(int=60_000 + index) for index in range(codec.MAX_UI_EXPENSE_SELECTION + 1)),
        )


def test_unconfigured_legacy_child_remains_scope_bound_and_configured_empty_stays_empty() -> None:
    async def run(configured: bool, relations: list[dict[str, Any]]) -> tuple[pc.P2ReadBackendResult | None, codec.P2V3ScopeMetadataProjection]:
        adapter, identity, locator, _, transport, verified, admission = _harness()
        transport.datasets["ledger_units"][0]["participant_scope_configured"] = configured
        transport.datasets["sub_activity_participants"] = relations
        projection = await adapter.admit_scope_v3(
            verified, admission, ui_activity_id_hint=ACTIVITY,
            ui_ledger_unit_id_hint=UNIT,
        )
        assert projection is not None
        assert projection.snapshot.activity["updated_at"] == STAMP
        assert projection.source_labels[0].source_row_updated_at is None
        scope = pc.P2Scope(
            scope_kind="ledger_unit", scope_ref=projection.snapshot.scope_ref,
            activity_ref=projection.snapshot.activity_ref,
            ledger_unit_ref=projection.snapshot.scope_ref,
        )
        request = _request(pc.P2ReadOperation.EXPENSES, scope, scope.activity_ref or "")
        logical_id = f"child-{configured}-{len(relations)}"
        query_ref = locator.query_ref(logical_id, identity=identity)
        locator.descriptors[query_ref] = codec.V3QueryDescriptor(
            request=request,
            public_request_digest=backend._canonical_sha(request.model_dump(mode="json", exclude_none=False)),
            normalized_selection_digest=backend._canonical_sha({
                "criteria": request.criteria.model_dump(mode="json", exclude_none=False), "ui_expense_ids": (),
            }),
        )
        grant = pc.P2SourceAuthorizationGrant(
            principal_ref=locator.principal_ref, owner_turn_ref=locator.owner_ref,
            generation=identity.generation, source_input_seq=identity.input_seq,
            input_digest=identity.input_digest, operation=request.operation, scope=scope,
            criteria_digest=pc.p2_criteria_digest(request.criteria),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=2), grant_ref=locator.ref("child-grant"),
        )
        binding = codec.QueryAttemptBinding(identity, logical_id, "attempt-child", 0, "claim")
        if configured and not relations:
            with pytest.raises(backend.P2ReadBackendError, match="invalid_upstream_response"):
                await adapter.read_candidate_v3(
                    request, verified, grant, admission=admission,
                    admission_projection=projection, query_binding=binding, context_version="ctx-child",
                )
            return None, projection
        result = await adapter.read_candidate_v3(
            request, verified, grant, admission=admission,
            admission_projection=projection, query_binding=binding, context_version="ctx-child",
        )
        return result, projection

    result, legacy_projection = asyncio.run(run(False, []))
    assert result is not None and result.query_evidence.matched_count == 2
    assert len([label for label in legacy_projection.source_labels if label.entity_kind == "participant"]) == 2
    assert asyncio.run(run(True, []))[0] is None


def test_configured_child_usage_rejects_outside_party_even_with_valid_parent_rows() -> None:
    async def run() -> None:
        adapter, identity, locator, _, transport, verified, admission = _harness()
        transport.datasets["sub_activity_participants"] = [
            {"activity_id": str(ACTIVITY), "ledger_unit_id": str(UNIT), "participant_id": str(P1)},
        ]
        projection = await adapter.admit_scope_v3(
            verified, admission, ui_activity_id_hint=ACTIVITY,
            ui_ledger_unit_id_hint=UNIT,
        )
        assert projection is not None
        scope = pc.P2Scope(
            scope_kind="ledger_unit", scope_ref=projection.snapshot.scope_ref,
            activity_ref=projection.snapshot.activity_ref,
            ledger_unit_ref=projection.snapshot.scope_ref,
        )
        expense_ref = locator.bind_entity("expense", EXPENSE, activity_id=ACTIVITY, ledger_unit_id=UNIT)
        criteria = pc.PrepaymentUsagesCriteria(
            kind="prepayment_usages", activity_ref=scope.activity_ref or "", expense_ref=expense_ref,
        )
        request = pc.P2ReadQueryRequest(
            kind="read", message_type="query_request", profile_id=pc.P2_V3_CANDIDATE_PROFILE_ID,
            versions=pc.P2_V3_VERSIONS, operation=pc.P2ReadOperation.PREPAYMENT_USAGES,
            criteria=criteria, scope=scope,
        )
        logical_id = "usage-child-negative"
        query_ref = locator.query_ref(logical_id, identity=identity)
        locator.descriptors[query_ref] = codec.V3QueryDescriptor(
            request=request,
            public_request_digest=backend._canonical_sha(request.model_dump(mode="json", exclude_none=False)),
            normalized_selection_digest=backend._canonical_sha({
                "criteria": request.criteria.model_dump(mode="json", exclude_none=False), "ui_expense_ids": (),
            }),
        )
        grant = pc.P2SourceAuthorizationGrant(
            principal_ref=locator.principal_ref, owner_turn_ref=locator.owner_ref,
            generation=identity.generation, source_input_seq=identity.input_seq,
            input_digest=identity.input_digest, operation=request.operation, scope=scope,
            criteria_digest=pc.p2_criteria_digest(request.criteria),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=2), grant_ref=locator.ref("usage-child-grant"),
        )
        with pytest.raises(backend.P2ReadBackendError, match="invalid_upstream_response"):
            await adapter.read_candidate_v3(
                request, verified, grant, admission=admission,
                admission_projection=projection,
                query_binding=codec.QueryAttemptBinding(identity, logical_id, "attempt-usage-child", 0, "claim"),
                context_version="ctx-usage-child",
            )

    asyncio.run(run())
