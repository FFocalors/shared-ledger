from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest

import test_p2_source_codec_backend_v3 as fixtures
from app import p2_read_backend as backend
from app import p2_read_contracts_v3 as pc
from app import p2_source_codec_v3 as codec


OTHER_USER = uuid.UUID("00000000-0000-4000-8000-000000000099")
NON_MEMBER_ACTIVITY = uuid.UUID("00000000-0000-4000-8000-000000000098")


class RecordingTransport(fixtures.SyntheticTransport):
    def __init__(self, datasets: dict[str, list[dict[str, Any]]]) -> None:
        super().__init__(datasets)
        self.urls: list[str] = []

    def get(
        self,
        url: str,
        headers: Mapping[str, str],
        *,
        timeout: float,
        max_response_bytes: int,
        control: Any,
    ) -> fixtures.v1.TransportResponse:
        self.urls.append(url)
        return super().get(
            url, headers, timeout=timeout,
            max_response_bytes=max_response_bytes, control=control,
        )


class IgnoreActivitiesIdFilterTransport(RecordingTransport):
    """Adversarial upstream which ignores only the activities id filter."""

    def get(
        self,
        url: str,
        headers: Mapping[str, str],
        *,
        timeout: float,
        max_response_bytes: int,
        control: Any,
    ) -> fixtures.v1.TransportResponse:
        parsed = urlsplit(url)
        if parsed.path.endswith("/activities"):
            query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "id"]
            url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))
        return super().get(
            url, headers, timeout=timeout,
            max_response_bytes=max_response_bytes, control=control,
        )


class IgnoreMembershipUserFilterTransport(RecordingTransport):
    """Adversarial upstream which returns membership rows for other users."""

    def get(
        self,
        url: str,
        headers: Mapping[str, str],
        *,
        timeout: float,
        max_response_bytes: int,
        control: Any,
    ) -> fixtures.v1.TransportResponse:
        parsed = urlsplit(url)
        if parsed.path.endswith("/activity_members"):
            query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "user_id"]
            url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))
        return super().get(
            url, headers, timeout=timeout,
            max_response_bytes=max_response_bytes, control=control,
        )


def _activity_attempt(
    *,
    datasets: dict[str, list[dict[str, Any]]] | None = None,
    transport_type: type[RecordingTransport] = RecordingTransport,
) -> tuple[
    backend.P2ReadBackendAdapter,
    codec.V3ExecutionIdentity,
    fixtures.FakeLocator,
    fixtures.FakeBudget,
    RecordingTransport,
    fixtures.v1.VerifiedReadContext,
    codec.AdmissionOnlyBinding,
    pc.P2ReadQueryRequest,
    codec.QueryAttemptBinding,
    pc.P2SourceAuthorizationGrant,
]:
    adapter, identity, locator, budget, original, verified, admission = fixtures._harness()
    transport = transport_type(datasets if datasets is not None else original.datasets)
    adapter._transport = transport

    request = fixtures._request(pc.P2ReadOperation.ACTIVITIES, None, "")
    logical_id = "activity-discovery-negative-" + uuid.uuid4().hex
    query_ref = locator.query_ref(logical_id, identity=identity)
    locator.descriptors[query_ref] = codec.V3QueryDescriptor(
        request=request,
        public_request_digest=backend._canonical_sha(request.model_dump(mode="json", exclude_none=False)),
        normalized_selection_digest=backend._canonical_sha({
            "criteria": request.criteria.model_dump(mode="json", exclude_none=False),
            "ui_expense_ids": (),
        }),
    )
    binding = codec.QueryAttemptBinding(
        identity=identity,
        logical_query_id=logical_id,
        query_attempt_id="attempt-activity-discovery",
        page_index=0,
        claim_token="synthetic-claim",
    )
    grant = pc.P2SourceAuthorizationGrant(
        principal_ref=locator.principal_ref,
        owner_turn_ref=locator.owner_ref,
        generation=identity.generation,
        source_input_seq=identity.input_seq,
        input_digest=identity.input_digest,
        operation=request.operation,
        scope=None,
        criteria_digest=pc.p2_criteria_digest(request.criteria),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=2),
        grant_ref=locator.ref("activity-discovery-grant"),
    )
    return adapter, identity, locator, budget, transport, verified, admission, request, binding, grant


def _assert_pending_without_capability(
    result: backend.P2V3PendingSourceAttempt,
    locator: fixtures.FakeLocator,
) -> None:
    assert isinstance(result, backend.P2V3PendingSourceAttempt)
    assert not hasattr(result.page, "next_page_ref")
    assert locator.continuations == {}


def test_unscoped_discovery_ignores_membership_for_another_principal() -> None:
    async def run() -> None:
        datasets = fixtures._datasets()
        datasets["activity_members"] = [{
            "activity_id": str(fixtures.ACTIVITY), "user_id": str(OTHER_USER),
        }]
        (adapter, _, locator, budget, transport, verified, admission,
         request, binding, grant) = _activity_attempt(datasets=datasets)

        pending = await adapter.read_candidate_v3(
            request, verified, grant, admission=admission,
            admission_projection=None, query_binding=binding,
            context_version="synthetic-context",
        )

        _assert_pending_without_capability(pending, locator)
        assert pending.page.items == ()
        assert transport.tables == ["activity_members"]
        query = dict(parse_qsl(urlsplit(transport.urls[0]).query, keep_blank_values=True))
        assert query["user_id"] == f"eq.{verified.principal_user_id}"
        assert budget.gets == 1

    asyncio.run(run())


def test_unscoped_discovery_rejects_wrong_principal_before_fetching_activity() -> None:
    async def run() -> None:
        datasets = fixtures._datasets()
        datasets["activity_members"] = [{
            "activity_id": str(fixtures.ACTIVITY), "user_id": str(OTHER_USER),
        }]
        (adapter, _, locator, budget, transport, verified, admission,
         request, binding, grant) = _activity_attempt(
            datasets=datasets, transport_type=IgnoreMembershipUserFilterTransport,
        )

        with pytest.raises(backend.P2ReadBackendError, match="invalid_upstream_response"):
            await adapter.read_candidate_v3(
                request, verified, grant, admission=admission,
                admission_projection=None, query_binding=binding,
                context_version="synthetic-context",
            )

        assert locator.continuations == {}
        # A wrong-principal membership row must be rejected before its Activity
        # id is used for another source GET.
        assert transport.tables == ["activity_members"]
        assert budget.gets == 1

    asyncio.run(run())


def test_unscoped_discovery_rejects_activity_rows_outside_current_membership() -> None:
    async def run() -> None:
        datasets = fixtures._datasets()
        extra = dict(datasets["activities"][0])
        extra.update({
            "id": str(NON_MEMBER_ACTIVITY),
            "name": "不属于当前成员的活动",
            "financial_version": fixtures._n("8"),
        })
        datasets["activities"] = [*datasets["activities"], extra]
        (adapter, _, locator, budget, transport, verified, admission,
         request, binding, grant) = _activity_attempt(
            datasets=datasets, transport_type=IgnoreActivitiesIdFilterTransport,
        )

        with pytest.raises(backend.P2ReadBackendError, match="invalid_upstream_response"):
            await adapter.read_candidate_v3(
                request, verified, grant, admission=admission,
                admission_projection=None, query_binding=binding,
                context_version="synthetic-context",
            )

        assert transport.tables == ["activity_members", "activities"]
        assert budget.gets == 2
        assert locator.continuations == {}

    asyncio.run(run())


def test_empty_unscoped_membership_skips_activities_get_and_stays_pending() -> None:
    async def run() -> None:
        datasets = fixtures._datasets()
        datasets["activity_members"] = []
        (adapter, _, locator, budget, transport, verified, admission,
         request, binding, grant) = _activity_attempt(datasets=datasets)

        pending = await adapter.read_candidate_v3(
            request, verified, grant, admission=admission,
            admission_projection=None, query_binding=binding,
            context_version="synthetic-context",
        )

        _assert_pending_without_capability(pending, locator)
        assert pending.page.items == ()
        assert pending.page.has_more is False
        assert transport.tables == ["activity_members"]
        assert budget.gets == 1
        assert pending.projection.historical is not None

    asyncio.run(run())


def test_unscoped_financial_read_is_rejected_before_source_dispatch() -> None:
    async def run() -> None:
        (adapter, identity, locator, budget, transport, verified, admission,
         _, _, _) = _activity_attempt()

        valid_scope = pc.P2Scope(
            scope_kind="ledger_unit",
            scope_ref="ref_" + "1" * 22,
            activity_ref="ref_" + "2" * 22,
            ledger_unit_ref="ref_" + "1" * 22,
        )
        scoped = fixtures._request(pc.P2ReadOperation.EXPENSES, valid_scope, valid_scope.activity_ref)
        # Defense-in-depth fixture: bypass request validation to model a corrupted
        # private call. A normally parsed financial query requires a scope.
        request = scoped.model_copy(update={"scope": None})
        logical_id = "unscoped-expenses-" + uuid.uuid4().hex
        query_ref = locator.query_ref(logical_id, identity=identity)
        locator.descriptors[query_ref] = codec.V3QueryDescriptor(
            request=request,
            public_request_digest=backend._canonical_sha(request.model_dump(mode="json", exclude_none=False)),
            normalized_selection_digest=backend._canonical_sha({
                "criteria": request.criteria.model_dump(mode="json", exclude_none=False),
                "ui_expense_ids": (),
            }),
        )
        binding = codec.QueryAttemptBinding(
            identity, logical_id, "attempt-unscoped-expenses", 0, "synthetic-claim",
        )
        grant = pc.P2SourceAuthorizationGrant.model_construct(
            principal_ref=locator.principal_ref,
            owner_turn_ref=locator.owner_ref,
            generation=identity.generation,
            source_input_seq=identity.input_seq,
            input_digest=identity.input_digest,
            operation=pc.P2ReadOperation.EXPENSES,
            scope=None,
            criteria_digest=pc.p2_criteria_digest(request.criteria),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=2),
            grant_ref=locator.ref("invalid-unscoped-expense-grant"),
        )

        with pytest.raises(backend.P2ReadBackendError, match="unsupported_scope"):
            await adapter.read_candidate_v3(
                request, verified, grant, admission=admission,
                admission_projection=None, query_binding=binding,
                context_version="synthetic-context",
            )

        assert transport.tables == []
        assert budget.gets == 0
        assert locator.continuations == {}

    asyncio.run(run())


def test_no_activity_hint_with_ledger_hint_is_rejected_without_get() -> None:
    async def run() -> None:
        adapter, _, _, budget, transport, verified, admission = fixtures._harness()
        with pytest.raises(backend.P2ReadBackendError, match="unsupported_scope"):
            await adapter.admit_scope_v3(
                verified, admission,
                ui_activity_id_hint=None,
                ui_ledger_unit_id_hint=fixtures.UNIT,
            )
        assert transport.tables == []
        assert budget.gets == 0

    asyncio.run(run())
