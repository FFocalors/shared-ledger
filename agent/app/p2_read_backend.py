"""Disabled, unassembled backend for the P2 paged-read candidate.

This module owns authenticated read transport, raw page-chain capture and source
fences. It does not register operations or alter the frozen v1 backend.
"""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import re
import secrets
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlencode, urlsplit

from . import p2_backend as v1
from . import p2_read_contracts as pc
from . import p2_read_contracts_v3 as pc3
from . import p2_event_contracts_v3 as pe3
from . import p2_source_codec_v3 as codec3


PROFILE_ID = "p2.read-paged-prepayment-refund.v2-candidate"
PROFILE_VERSIONS = {"api": "2.1.0", "semantic": "2.0.0", "operations": "2.1.0", "trajectory": "2.0.0"}
DEBT_SOURCE_VARIANT = "expense_debt_line"

READ_OPERATIONS = frozenset({
    "read.activities", "read.expenses", "read.debts", "read.refund_events",
    "read.prepayment_accounts", "read.prepayment_usages", "read.prepayment_return_events",
})

# Only public tables that the source map requires. Never add private schema tables
# or arbitrary RPCs here. Scope tables are read by the existing resolver.
_CANDIDATE_TABLES = frozenset({
    "expense_debts", "prepayment_accounts", "prepayment_usages",
    "transfers", "transfer_components",
})
_OPERATION_SOURCE_TABLES = {
    "read.activities": frozenset({"activities"}),
    "read.expenses": frozenset({"expenses", "payments", "splits"}),
    "read.debts": frozenset({"expense_debts", "expenses"}),
    "read.refund_events": frozenset({"expenses"}),
    "read.prepayment_accounts": frozenset({"prepayment_accounts"}),
    "read.prepayment_usages": frozenset({"prepayment_usages", "prepayment_accounts", "expense_debts", "expenses"}),
    "read.prepayment_return_events": frozenset({"transfers", "transfer_components"}),
}

MAX_BACKEND_MS_PER_TURN = 20_000
MAX_TURN_MS = 240_000
MAX_GETS_PER_TURN = 48
MAX_PAGES_PER_QUERY = 4
MAX_ROWS_PER_PAGE = 16
MAX_ROWS_PER_QUERY = 64
MAX_BYTES_PER_RESPONSE = 1_048_576
MAX_BYTES_PER_TURN = 4_194_304

_CONTENT_RANGE = re.compile(r"^(?:(?P<start>[0-9]+)-(?P<end>[0-9]+)|\*)/(?P<total>[0-9]+|\*)$")


class P2ReadBackendError(v1.BackendReadError):
    """Stable, redacted error code for the isolated candidate adapter."""


@dataclass(frozen=True, slots=True)
class QueryBinding:
    query_id: str
    operation: str
    criteria_sha256: str
    scope_sha256: str
    table: str
    query_sha256: str
    owner_user_id: uuid.UUID
    turn_id: uuid.UUID
    generation: int
    context_revision: int
    claim_id: uuid.UUID
    envelope_sha256: str
    financial_versions: tuple[tuple[uuid.UUID, int], ...]


_ACTIVE_QUERY: contextvars.ContextVar[QueryBinding | None] = contextvars.ContextVar(
    "p2_read_active_query", default=None,
)


@dataclass(frozen=True, slots=True)
class CapturedPage:
    query_id: str
    request_sha256: str
    status: int
    content_range: str | None
    body: bytes = field(repr=False, compare=False)
    elapsed_ms: int
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class CandidatePageReceipt:
    operation: str
    table: str
    query_sha256: str
    request_sha256: str
    offset: int
    returned_count: int
    source_total: int
    observed_at: datetime
    raw_body_sha256: str
    source_dto_sha256: str
    projection_sha256: str
    owner_user_id: uuid.UUID
    turn_id: uuid.UUID
    generation: int
    context_revision: int
    claim_id: uuid.UUID
    scope_sha256: str
    criteria_sha256: str
    envelope_sha256: str
    financial_versions: tuple[tuple[uuid.UUID, int], ...]
    previous_receipt_sha256: str | None
    receipt_sha256: str


@dataclass(frozen=True, slots=True)
class CandidateQueryEvidence:
    operation: str
    criteria_sha256: str
    scope_sha256: str
    source_kind: str
    observed_at: datetime
    returned_count: int
    source_total: int
    completeness: str
    zero_kind: str
    query_sha256: str
    raw_body_sha256: str
    normalized_source_sha256: str
    projection_sha256: str
    page_receipts: tuple[CandidatePageReceipt, ...]


@dataclass(frozen=True, slots=True)
class CandidateTablePlan:
    """A fixed per-operation GET plan assembled only by trusted server code."""
    table: str
    select: str
    order: str
    identity_fields: tuple[str, ...]
    filters: Callable[[Any, v1.P2ResolvedScope | None], Sequence[tuple[str, str]]]
    parse_source_row: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    project_row: Callable[[Mapping[str, Any], v1.P2ResolvedScope | None], Mapping[str, Any]]
    source_kind: str


@dataclass(frozen=True, slots=True)
class CandidateEntityBinding:
    ref: str
    kind: str
    entity_id: uuid.UUID
    owner_user_id: uuid.UUID
    turn_id: uuid.UUID
    generation: int
    claim_id: uuid.UUID
    activity_id: uuid.UUID | None
    ledger_unit_id: uuid.UUID | None


@dataclass(slots=True)
class CandidateGrantBinding:
    grant_ref: str
    operation: str
    criteria_sha256: str
    scope_sha256: str
    owner_user_id: uuid.UUID
    turn_id: uuid.UUID
    owner_turn_ref: str
    generation: int
    context_revision: int
    claim_id: uuid.UUID
    source_input_seq: int
    input_digest: str
    scope: Any | None
    resolved_scope: v1.P2ResolvedScope | None = field(repr=False)
    expires_at: datetime
    consumed: bool = False


@dataclass(slots=True)
class CandidateQueryState:
    query_ref: str
    next_page_ref: str | None
    operation: Any
    criteria: Any
    scope: Any
    facts: tuple[Any, ...]
    evidence: Any
    owner_user_id: uuid.UUID
    turn_id: uuid.UUID
    generation: int
    context_revision: int
    claim_id: uuid.UUID
    source_input_seq: int
    input_digest: str
    owner_turn_ref: str
    scope_sha256: str
    criteria_sha256: str
    financial_versions: tuple[tuple[uuid.UUID, int], ...]
    receipts: tuple[CandidatePageReceipt, ...]
    page_index: int = 0
    current: bool = True
    continuation_used: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class CandidateResolvedScope:
    public_scope: Any | None
    private_scope: v1.P2ResolvedScope | None
    participant_refs: Mapping[uuid.UUID, str] = field(repr=False, compare=False)
    ledger_unit_refs: Mapping[uuid.UUID, str] = field(repr=False, compare=False)


class P2ReadTurnState:
    """Turn-local accounting/capture object; never stored in an adapter singleton.

    The runtime must create this when the accepted Turn is created and reuse it
    across retries/resume. Reconstructing it on resume would reset the budget.
    """
    def __init__(
        self, owner_user_id: uuid.UUID, turn_id: uuid.UUID, *,
        generation: int, context_revision: int, claim_id: uuid.UUID,
        source_input_seq: int, input_digest: str,
        turn_deadline_monotonic: float, created_monotonic: float | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> None:
        self._clock = monotonic_clock or time.monotonic
        now = self._clock() if created_monotonic is None else created_monotonic
        if (
            type(generation) is not int or generation < 1
            or type(context_revision) is not int or context_revision < 0
            or type(source_input_seq) is not int or source_input_seq < 0
            or not isinstance(input_digest, str) or re.fullmatch(r"[0-9a-f]{64}", input_digest) is None
            or not isinstance(claim_id, uuid.UUID)
            or turn_deadline_monotonic <= now
            or turn_deadline_monotonic - now > MAX_TURN_MS / 1000
        ):
            raise ValueError("candidate Turn deadline is outside the reviewed bound")
        self.owner_user_id = owner_user_id
        self.turn_id = turn_id
        self.generation = generation
        self.context_revision = context_revision
        self.claim_id = claim_id
        self.source_input_seq = source_input_seq
        self.input_digest = input_digest
        self.created_monotonic = now
        self.turn_deadline_monotonic = turn_deadline_monotonic
        self.backend_elapsed_ms = 0
        self._backend_elapsed_exact_ms = 0.0
        self.response_bytes = 0
        self.get_attempts = 0
        self.unknown_consumption = False
        self._active_work_started: float | None = None
        self._active_task: asyncio.Task[Any] | None = None
        self._work_depth = 0
        self._captured: dict[str, list[CapturedPage]] = {}
        self._closed_queries: set[str] = set()
        self._refs: dict[str, CandidateEntityBinding] = {}
        self._entity_refs: dict[tuple[str, uuid.UUID, uuid.UUID | None, uuid.UUID | None], str] = {}
        self._grants: dict[str, CandidateGrantBinding] = {}
        self._queries: dict[str, CandidateQueryState] = {}
        self._lock = threading.RLock()
        self._dispatch_lock = asyncio.Lock()
        self.owner_turn_ref = self.bind_entity(
            "owner_turn", uuid.uuid5(owner_user_id, str(turn_id)),
        )

    @asynccontextmanager
    async def backend_operation(self):
        task = asyncio.current_task()
        if task is None:
            raise P2ReadBackendError("upstream_failure")
        nested = self._active_task is task
        if not nested:
            await self._dispatch_lock.acquire()
            self._active_task = task
            try:
                self.begin_backend_work()
            except BaseException:
                self._active_task = None
                self._dispatch_lock.release()
                raise
        else:
            self._work_depth += 1
        succeeded = False
        try:
            yield
            succeeded = True
        finally:
            if nested:
                self._work_depth -= 1
            else:
                try:
                    self.end_backend_work(check=succeeded)
                finally:
                    self._active_task = None
                    self._dispatch_lock.release()

    def begin_backend_work(self) -> None:
        with self._lock:
            if self._active_work_started is not None:
                self._work_depth += 1
                return
            self.verify_turn_identity_only()
            self._refresh_elapsed_locked()
            if self._backend_elapsed_exact_ms >= MAX_BACKEND_MS_PER_TURN:
                raise P2ReadBackendError("upstream_timeout")
            self._active_work_started = self._clock()
            self._work_depth = 1

    def end_backend_work(self, *, check: bool = False) -> None:
        with self._lock:
            if self._active_work_started is None:
                return
            self._work_depth -= 1
            if self._work_depth <= 0:
                self._refresh_elapsed_locked()
                self._active_work_started = None
                self._work_depth = 0
                if check:
                    self._check_success_budget_locked()

    def _refresh_elapsed_locked(self) -> None:
        if self.backend_elapsed_ms != int(self._backend_elapsed_exact_ms):
            # Keep the integer field observable while preserving exact internal
            # usage; explicit test/diagnostic adjustments seed the exact value.
            self._backend_elapsed_exact_ms = float(self.backend_elapsed_ms)
        if self._active_work_started is not None:
            # Keep fractional milliseconds between checkpoints. Truncating on
            # every refresh would let frequent GET/parse fences lose time.
            now = self._clock()
            elapsed_ms = max(0.0, (now - self._active_work_started) * 1000)
            self._backend_elapsed_exact_ms += elapsed_ms
            self.backend_elapsed_ms = int(self._backend_elapsed_exact_ms)
            self._active_work_started = now

    def verify_turn(self, verified: v1.VerifiedReadContext) -> None:
        if (verified.owner_user_id, verified.turn_id) != (self.owner_user_id, self.turn_id):
            raise P2ReadBackendError("invalid_auth_context")
        with self._lock:
            self.verify_turn_identity_only()
            self._refresh_elapsed_locked()
            if self._clock() >= self.turn_deadline_monotonic:
                raise P2ReadBackendError("upstream_timeout")
            if self._backend_elapsed_exact_ms >= MAX_BACKEND_MS_PER_TURN:
                raise P2ReadBackendError("upstream_timeout")
            if self.response_bytes >= MAX_BYTES_PER_TURN or self.get_attempts >= MAX_GETS_PER_TURN:
                raise P2ReadBackendError("read_limit_exceeded")

    def reserve_get(self, timeout: float, max_response_bytes: int) -> tuple[float, int]:
        if (
            isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or timeout <= 0 or type(max_response_bytes) is not int or max_response_bytes <= 0
        ):
            raise P2ReadBackendError("read_limit_exceeded")
        with self._lock:
            self.verify_turn_identity_only()
            self._refresh_elapsed_locked()
            now = self._clock()
            remaining_backend = (MAX_BACKEND_MS_PER_TURN - self._backend_elapsed_exact_ms) / 1000
            remaining_turn = self.turn_deadline_monotonic - now
            if remaining_turn <= 0 or remaining_backend <= 0:
                raise P2ReadBackendError("upstream_timeout")
            if self.get_attempts >= MAX_GETS_PER_TURN or self.response_bytes >= MAX_BYTES_PER_TURN:
                raise P2ReadBackendError("read_limit_exceeded")
            request_timeout = min(float(timeout), remaining_backend, remaining_turn)
            request_bytes = min(max_response_bytes, MAX_BYTES_PER_TURN - self.response_bytes)
            if request_timeout <= 0 or request_bytes <= 0:
                raise P2ReadBackendError("read_limit_exceeded")
            self.get_attempts += 1
            return request_timeout, request_bytes

    def verify_turn_identity_only(self) -> None:
        if self.unknown_consumption:
            raise P2ReadBackendError("upstream_failure")

    def settle_get(self, elapsed_ms: int, byte_count: int, *, known: bool) -> None:
        if type(elapsed_ms) is not int or elapsed_ms < 0 or type(byte_count) is not int or byte_count < 0:
            with self._lock:
                self.unknown_consumption = True
            raise P2ReadBackendError("upstream_failure")
        with self._lock:
            # backend_elapsed_ms is active wall time for the whole read path
            # (scope GETs, parsing, joins, and projection), not a sum of HTTP
            # times. elapsed_ms remains a per-request diagnostic only.
            self._refresh_elapsed_locked()
            self.response_bytes += byte_count
            if not known:
                self.unknown_consumption = True

    def check_success_budget(self) -> None:
        """Charge active work and reject any result that crossed a Turn cap."""
        with self._lock:
            self._refresh_elapsed_locked()
            self._check_success_budget_locked()

    def _check_success_budget_locked(self) -> None:
        self.verify_turn_identity_only()
        if self._clock() >= self.turn_deadline_monotonic:
            raise P2ReadBackendError("upstream_timeout")
        if self._backend_elapsed_exact_ms >= MAX_BACKEND_MS_PER_TURN:
            raise P2ReadBackendError("upstream_timeout")
        if self.get_attempts > MAX_GETS_PER_TURN or self.response_bytes > MAX_BYTES_PER_TURN:
            raise P2ReadBackendError("read_limit_exceeded")

    def check_response_budget(self, request_cap: int, byte_count: int) -> None:
        if byte_count > request_cap:
            raise P2ReadBackendError("response_too_large")
        self.check_success_budget()

    def mark_query_stale(self, query_ref: str) -> None:
        with self._lock:
            query = self._queries.get(query_ref)
            if query is not None:
                query.current = False

    def fail_continuation(self, query_ref: str) -> None:
        """Invalidate an attempted continuation even if failure precedes GET."""
        with self._lock:
            query = self._queries.get(query_ref)
            if query is not None:
                if query.next_page_ref is not None:
                    query.continuation_used.add(query.next_page_ref)
                query.current = False

    def add_capture(self, page: CapturedPage) -> None:
        with self._lock:
            if page.query_id not in self._closed_queries:
                self._captured.setdefault(page.query_id, []).append(page)

    def take_captures(self, query_id: str) -> tuple[CapturedPage, ...]:
        with self._lock:
            self._closed_queries.add(query_id)
            return tuple(self._captured.pop(query_id, ()))

    def discard_captures(self, query_id: str) -> None:
        with self._lock:
            self._closed_queries.add(query_id)
            self._captured.pop(query_id, None)

    def bind_entity(
        self, kind: str, entity_id: uuid.UUID, *,
        activity_id: uuid.UUID | None = None, ledger_unit_id: uuid.UUID | None = None,
    ) -> str:
        if not isinstance(kind, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", kind):
            raise P2ReadBackendError("unsupported_scope")
        if not isinstance(entity_id, uuid.UUID):
            raise P2ReadBackendError("invalid_upstream_response")
        if activity_id is not None and not isinstance(activity_id, uuid.UUID):
            raise P2ReadBackendError("invalid_upstream_response")
        if ledger_unit_id is not None and not isinstance(ledger_unit_id, uuid.UUID):
            raise P2ReadBackendError("invalid_upstream_response")
        key = (kind, entity_id, activity_id, ledger_unit_id)
        with self._lock:
            existing = self._entity_refs.get(key)
            if existing is not None:
                binding = self._refs.get(existing)
                if binding is None or not self._binding_is_current(binding):
                    raise P2ReadBackendError("unsupported_scope")
                return existing
            ref = "ref_" + secrets.token_urlsafe(24)
            binding = CandidateEntityBinding(
                ref, kind, entity_id, self.owner_user_id, self.turn_id,
                self.generation, self.claim_id, activity_id, ledger_unit_id,
            )
            self._refs[ref] = binding
            self._entity_refs[key] = ref
            return ref

    def resolve_entity(
        self, ref: str, kind: str, *,
        activity_id: uuid.UUID | None = None, ledger_unit_id: uuid.UUID | None = None,
    ) -> CandidateEntityBinding:
        with self._lock:
            binding = self._refs.get(ref)
            if (
                binding is None or binding.kind != kind or not self._binding_is_current(binding)
                or activity_id is not None and binding.activity_id != activity_id
                or ledger_unit_id is not None and binding.ledger_unit_id != ledger_unit_id
            ):
                raise P2ReadBackendError("unsupported_scope")
            return binding

    def _binding_is_current(self, binding: CandidateEntityBinding) -> bool:
        return (
            binding.owner_user_id == self.owner_user_id
            and binding.turn_id == self.turn_id
            and binding.generation == self.generation
            and binding.claim_id == self.claim_id
        )

    def register_grant(self, grant: CandidateGrantBinding) -> None:
        with self._lock:
            if grant.grant_ref in self._grants:
                raise P2ReadBackendError("upstream_failure")
            self._grants[grant.grant_ref] = grant

    def consume_grant(self, grant_ref: str) -> CandidateGrantBinding:
        with self._lock:
            grant = self._grants.get(grant_ref)
            if (
                grant is None or grant.consumed
                or grant.owner_user_id != self.owner_user_id
                or grant.turn_id != self.turn_id
                or grant.generation != self.generation
                or grant.context_revision != self.context_revision
                or grant.claim_id != self.claim_id
                or grant.owner_turn_ref != self.owner_turn_ref
                or grant.source_input_seq != self.source_input_seq
                or grant.input_digest != self.input_digest
                or grant.expires_at <= datetime.now(timezone.utc)
            ):
                raise P2ReadBackendError("invalid_auth_context")
            grant.consumed = True
            return grant

    def get_grant(self, grant_ref: str) -> CandidateGrantBinding:
        with self._lock:
            grant = self._grants.get(grant_ref)
            if (
                grant is None
                or grant.owner_user_id != self.owner_user_id
                or grant.turn_id != self.turn_id
                or grant.generation != self.generation
                or grant.context_revision != self.context_revision
                or grant.claim_id != self.claim_id
                or grant.owner_turn_ref != self.owner_turn_ref
                or grant.source_input_seq != self.source_input_seq
                or grant.input_digest != self.input_digest
                or grant.expires_at <= datetime.now(timezone.utc)
            ):
                raise P2ReadBackendError("invalid_auth_context")
            return grant

    def store_query(self, query: CandidateQueryState) -> None:
        with self._lock:
            if query.query_ref in self._queries:
                raise P2ReadBackendError("upstream_failure")
            self._queries[query.query_ref] = query

    def get_query(self, query_ref: str) -> CandidateQueryState:
        with self._lock:
            query = self._queries.get(query_ref)
            if query is None or not query.current:
                raise P2ReadBackendError("unsupported_scope")
            if (
                query.owner_user_id != self.owner_user_id
                or query.turn_id != self.turn_id
                or query.generation != self.generation
                or query.context_revision != self.context_revision
                or query.claim_id != self.claim_id
            ):
                query.current = False
                raise P2ReadBackendError("unsupported_scope")
            return query


class TurnBudgetCaptureTransport:
    """Wraps the fixed GET transport with per-Turn cost accounting and raw capture."""
    def __init__(self, inner: v1.ReadOnlyTransport, state: P2ReadTurnState) -> None:
        self._inner = inner
        self._state = state

    def get(
        self, url: str, headers: Mapping[str, str], *, timeout: float,
        max_response_bytes: int, control: v1._RequestControl,
    ) -> v1.TransportResponse:
        started = self._state._clock()
        request_timeout, request_cap = self._state.reserve_get(timeout, max_response_bytes)
        response: v1.TransportResponse | None = None
        failure: BaseException | None = None
        deadline_timer = threading.Timer(request_timeout, control.abort)
        deadline_timer.daemon = True
        deadline_timer.start()
        try:
            response = self._inner.get(
                url, headers, timeout=request_timeout, max_response_bytes=request_cap,
                control=control,
            )
            if not isinstance(response, v1.TransportResponse):
                raise P2ReadBackendError("invalid_upstream_response")
        except BaseException as exc:
            # A transport exception may occur after some bytes were read. If the
            # transport cannot report them, preserve an unknown charge and deny
            # later requests instead of silently releasing capacity.
            failure = exc
            raise
        finally:
            deadline_timer.cancel()
            elapsed_ms = max(0, int((self._state._clock() - started) * 1000))
            known = response is not None and isinstance(response.body, bytes)
            byte_count = len(response.body) if known else 0
            try:
                self._state.settle_get(elapsed_ms, byte_count, known=known)
                if failure is None and known and response.status in (200, 206):
                    self._state.check_response_budget(request_cap, byte_count)
            except P2ReadBackendError:
                if failure is None:
                    raise
        if not isinstance(response, v1.TransportResponse) or not isinstance(response.body, bytes):
            raise P2ReadBackendError("invalid_upstream_response")
        binding = _ACTIVE_QUERY.get()
        if binding is not None:
            self._state.add_capture(CapturedPage(
                query_id=binding.query_id,
                request_sha256=_request_url_sha(url),
                status=response.status,
                content_range=response.content_range,
                body=response.body,
                elapsed_ms=max(0, int((self._state._clock() - started) * 1000)),
                observed_at=datetime.now(timezone.utc),
            ))
        return response


@dataclass(frozen=True, slots=True)
class CandidateTableResult:
    rows: tuple[Mapping[str, Any], ...]
    projections: tuple[Mapping[str, Any], ...]
    receipts: tuple[CandidatePageReceipt, ...]
    evidence: CandidateQueryEvidence


@dataclass(slots=True)
class _V3QueryCaptureState:
    operation: pc3.P2ReadOperation
    binding: codec3.QueryAttemptBinding
    source_pages: int = 0
    table_pages: dict[str, int] = field(default_factory=dict)
    captures: list[codec3.CapturedPageWitness] = field(default_factory=list)
    tables: dict[str, codec3.SourceTable] = field(default_factory=dict)
    fence_complete: bool = True
    previous_proof: codec3.V3ContinuationProof | None = None


@dataclass(frozen=True, slots=True)
class P2V3PreacceptProjection:
    """Display-shaped projection held privately until Store source acceptance.

    This intentionally uses the historical, capability-free page contract. It
    is not an accepted source result and cannot be returned to a model/API.
    """

    historical: pe3.P2V3HistoricalReadPayload = field(repr=False)


@dataclass(frozen=True, slots=True)
class P2V3PendingSourceAttempt:
    """Exact in-memory source attempt awaiting independent Store validation.

    Private identities, descriptors, and response bodies are hidden from repr.
    No bearer token or continuation capability is retained here. The Store must
    reparse every page body and atomically accept the attempt before a live DTO
    or a next-page capability can be created.
    """

    identity: codec3.V3ExecutionIdentity = field(repr=False)
    admission: codec3.AdmissionOnlyBinding = field(repr=False)
    query_binding: codec3.QueryAttemptBinding = field(repr=False)
    grant: pc3.P2SourceAuthorizationGrant = field(repr=False)
    request: pc3.P2ReadQueryRequest = field(repr=False)
    descriptor: codec3.V3QueryDescriptor = field(repr=False)
    previous_proof: codec3.V3ContinuationProof | None = field(repr=False)
    admission_projection: codec3.P2V3ScopeMetadataProjection | None = field(repr=False)
    query_tables: tuple[tuple[str, codec3.SourceTable], ...] = field(repr=False)
    bootstrap_captures: tuple[codec3.SourcePage, ...] = field(repr=False)
    query_captures: tuple[codec3.SourcePage, ...] = field(repr=False)
    projection: P2V3PreacceptProjection = field(repr=False)
    resolved_scope_ids: tuple[uuid.UUID, ...] = field(default=(), repr=False)
    context_version: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.identity != self.admission.identity or self.identity != self.query_binding.identity:
            raise ValueError("pending source attempt identity mismatch")
        if self.query_binding.page_index < 0:
            raise ValueError("pending source attempt page index is invalid")
        bootstrap_ids = tuple(page.witness.capture_id for page in self.bootstrap_captures)
        query_ids = tuple(page.witness.capture_id for page in self.query_captures)
        if len(bootstrap_ids) != len(set(bootstrap_ids)) or len(query_ids) != len(set(query_ids)):
            raise ValueError("pending source attempt has duplicate captures")
        if set(bootstrap_ids) & set(query_ids):
            raise ValueError("bootstrap and query captures must be disjoint")
        for page in self.bootstrap_captures:
            witness = page.witness
            if (
                witness.binding_kind != "admission"
                or witness.admission_id != self.admission.admission_id
                or witness.logical_query_id is not None
                or witness.query_attempt_id is not None
                or witness.page_index is not None
            ):
                raise ValueError("bootstrap capture is not bound to the exact admission")
        for page in self.query_captures:
            witness = page.witness
            binding_matches = (
                witness.binding_kind == "admission"
                and witness.admission_id == self.admission.admission_id
                and witness.logical_query_id is None
                and witness.query_attempt_id is None
                and witness.page_index is None
            ) or (
                witness.binding_kind == "query_attempt"
                and witness.admission_id is None
                and witness.logical_query_id == self.query_binding.logical_query_id
                and witness.query_attempt_id == self.query_binding.query_attempt_id
                and witness.page_index == self.query_binding.page_index
            )
            if (
                not binding_matches
                or witness.owner_user_id != self.identity.owner_user_id
                or witness.turn_id != self.identity.turn_id
                or witness.generation != self.identity.generation
                or witness.input_seq != self.identity.input_seq
                or witness.input_digest != self.identity.input_digest
                or witness.claim_epoch != self.identity.claim_epoch
                or witness.authority_epoch != self.identity.authority_epoch
                or witness.context_revision != self.identity.context_revision
                or type(page.raw_body) is not bytes
                or len(page.raw_body) != witness.response_bytes
                or witness.reservation_id != page.reservation_id
                or witness.http_status != page.status
                or witness.content_range != page.content_range
                or witness.elapsed_us != page.elapsed_us
                or hashlib.sha256(page.raw_body).hexdigest() != witness.response_sha256
                or hashlib.sha256(page.raw_body).hexdigest() != page.raw_body_sha256
                or _request_url_sha(page.request_url) != witness.request_sha256
            ):
                raise ValueError("pending source capture does not match its exact witness")
        for page in self.bootstrap_captures:
            witness = page.witness
            if (
                witness.owner_user_id != self.identity.owner_user_id
                or witness.turn_id != self.identity.turn_id
                or witness.generation != self.identity.generation
                or witness.input_seq != self.identity.input_seq
                or witness.input_digest != self.identity.input_digest
                or witness.claim_epoch != self.identity.claim_epoch
                or witness.authority_epoch != self.identity.authority_epoch
                or witness.context_revision != self.identity.context_revision
                or type(page.raw_body) is not bytes
                or len(page.raw_body) != witness.response_bytes
                or witness.reservation_id != page.reservation_id
                or witness.http_status != page.status
                or witness.content_range != page.content_range
                or witness.elapsed_us != page.elapsed_us
                or hashlib.sha256(page.raw_body).hexdigest() != witness.response_sha256
                or hashlib.sha256(page.raw_body).hexdigest() != page.raw_body_sha256
                or _request_url_sha(page.request_url) != witness.request_sha256
            ):
                raise ValueError("bootstrap capture does not match its exact witness")
        if self.admission_projection is None and self.bootstrap_captures:
            raise ValueError("unscoped source attempt cannot carry scope bootstrap captures")
        if self.admission_projection is not None:
            expected = tuple(page.witness.capture_id for page in self.admission_projection.snapshot.witnesses)
            if expected != bootstrap_ids:
                raise ValueError("bootstrap raw pages must exactly match the admitted scope snapshot")
            if tuple(page.witness for page in self.bootstrap_captures) != self.admission_projection.captures:
                raise ValueError("bootstrap witnesses must match the admitted metadata projection")
        historical = self.projection.historical
        if hasattr(historical.page, "next_page_ref"):
            raise ValueError("preaccept projection must not contain a continuation capability")

    @property
    def operation(self) -> pc3.P2ReadOperation:
        return self.projection.historical.operation

    @property
    def query_evidence(self) -> pc3.P2QueryEvidence:
        return self.projection.historical.query_evidence

    @property
    def page(self) -> pe3.P2V3HistoricalReadPage:
        return self.projection.historical.page


class P2ReadBackendAdapter(v1.P2BackendAdapter):
    """Per-Turn source adapter foundation; intentionally absent from composition."""
    _TABLES = v1.P2BackendAdapter._TABLES | _CANDIDATE_TABLES

    _V3_OPERATION_ROLES = {
        "read.activities": frozenset({"activity", "membership", "participant", "ledger_unit", "scope_label", "actor", "financial_version"}),
        "read.expenses": frozenset({"activity", "membership", "participant", "ledger_unit", "expense", "actor", "scope_label", "financial_version"}),
        "read.debts": frozenset({"activity", "membership", "participant", "ledger_unit", "expense", "debt", "actor", "scope_label", "financial_version"}),
        "read.refund_events": frozenset({"activity", "membership", "expense", "refund_parent", "actor", "scope_label", "financial_version"}),
        "read.prepayment_accounts": frozenset({"activity", "membership", "prepayment_account", "actor", "scope_label", "financial_version"}),
        "read.prepayment_usages": frozenset({"activity", "membership", "participant", "ledger_unit", "expense", "debt", "prepayment_account", "prepayment_usage", "actor", "scope_label", "financial_version"}),
        "read.prepayment_return_events": frozenset({"activity", "membership", "prepayment_account", "prepayment_return", "actor", "scope_label", "financial_version"}),
    }
    _V3_TABLE_ROLES = {
        "activities": "activity", "activity_members": "membership",
        "ledger_units": "ledger_unit", "participants": "participant",
        "sub_activity_participants": "ledger_unit", "participant_claims": "actor",
        "expenses": "expense", "payments": "expense", "splits": "expense",
        "expense_debts": "debt", "prepayment_accounts": "prepayment_account",
        "prepayment_usages": "prepayment_usage", "transfers": "prepayment_return",
        "transfer_components": "prepayment_return",
    }
    _V3_ORDERS = {
        "activities": {"id.asc"}, "activity_members": {"activity_id.asc"},
        "ledger_units": {"id.asc"}, "participants": {"participant_order.asc,id.asc"},
        "sub_activity_participants": {"ledger_unit_id.asc,participant_id.asc"},
        "participant_claims": {"id.asc"}, "expenses": {"occurred_at.asc,id.asc", "id.asc"},
        "payments": {"expense_id.asc,id.asc"}, "splits": {"expense_id.asc,id.asc"},
        "expense_debts": {"ledger_unit_id.asc,expense_id.asc,debtor_participant_id.asc,creditor_participant_id.asc,id.asc", "id.asc"},
        "prepayment_accounts": {"owner_participant_id.asc,custodian_participant_id.asc,currency.asc,id.asc", "id.asc"},
        "prepayment_usages": {"bill_occurred_at.asc,expense_debt_id.asc,id.asc", "id.asc"},
        "transfers": {"occurred_at.asc,id.asc", "id.asc"},
        "transfer_components": {"transfer_id.asc,id.asc", "id.asc"},
    }
    _V3_FILTER_COLUMNS = {
        "activities": {"id", "is_deleted"}, "activity_members": {"activity_id", "user_id"},
        "ledger_units": {"activity_id", "is_deleted", "id"},
        "participants": {"activity_id", "is_deleted"},
        "sub_activity_participants": {"activity_id"},
        "participant_claims": {"activity_id", "user_id"},
        "expenses": {"ledger_unit_id", "is_deleted", "id", "original_expense_id"},
        "payments": {"expense_id"}, "splits": {"expense_id"},
        "expense_debts": {"activity_id", "ledger_unit_id", "expense_id", "id"},
        "prepayment_accounts": {"activity_id", "id"},
        "prepayment_usages": {"activity_id", "expense_debt_id", "id"},
        "transfers": {"activity_id", "type", "is_voided", "id"},
        "transfer_components": {"activity_id", "transfer_id", "component_type"},
    }

    def __init__(
        self, config: v1.P2BackendConfig, turn_state: P2ReadTurnState | None = None,
        *, transport: v1.ReadOnlyTransport | None = None,
        v3_budget_port: codec3.P2V3BudgetPort | None = None,
        v3_locator_port: codec3.P2V3LocatorPort | None = None,
    ) -> None:
        if config.page_size != MAX_ROWS_PER_PAGE or config.max_pages != MAX_PAGES_PER_QUERY or config.max_rows_per_query != MAX_ROWS_PER_QUERY:
            raise ValueError("candidate sources require 4 pages of 16 rows (64 rows per table/query cap)")
        source_transport = transport or v1.StdlibReadOnlyTransport()
        self._v3_enabled = turn_state is None
        if self._v3_enabled:
            if v3_budget_port is None or v3_locator_port is None:
                raise ValueError("v3 adapter requires Store-backed budget and locator ports")
            if config.max_response_bytes > codec3.MAX_RESPONSE_BYTES or config.max_total_response_bytes > codec3.MAX_TURN_RESPONSE_BYTES:
                raise ValueError("v3 response limits exceed the candidate source caps")
            if config.max_requests_per_read > codec3.MAX_GETS_PER_TURN or config.max_total_seconds > codec3.MAX_BACKEND_US_PER_TURN / 1_000_000:
                raise ValueError("v3 request or backend-time limits exceed the candidate Turn caps")
            super().__init__(config, source_transport)
            self._v3_budget_port = v3_budget_port
            self._v3_locator_port = v3_locator_port
        else:
            budgeted = TurnBudgetCaptureTransport(source_transport, turn_state)
            super().__init__(config, budgeted)
            self._v3_budget_port = None
            self._v3_locator_port = None
        # Existing canonical max_facts remains 16; this isolated class returns a
        # page envelope capped at 64 and is not passed through the v1 reader.
        self._max_facts = MAX_ROWS_PER_QUERY
        self._turn_state = turn_state
        self._turn_read_lock = asyncio.Lock()

    def _require_v2_state(self) -> P2ReadTurnState:
        if self._turn_state is None:
            raise P2ReadBackendError("invalid_auth_context")
        return self._turn_state

    def _require_v3_ports(self) -> tuple[codec3.P2V3BudgetPort, codec3.P2V3LocatorPort]:
        if self._turn_state is not None or self._v3_budget_port is None or self._v3_locator_port is None:
            raise P2ReadBackendError("invalid_auth_context")
        return self._v3_budget_port, self._v3_locator_port

    @staticmethod
    def _v3_identity_matches(
        identity: codec3.V3ExecutionIdentity, verified: v1.VerifiedReadContext,
    ) -> bool:
        return (
            identity.owner_user_id == verified.owner_user_id
            and identity.turn_id == verified.turn_id
            and type(identity.generation) is int and identity.generation >= 1
            and type(identity.input_seq) is int and identity.input_seq >= 0
            and re.fullmatch(r"[0-9a-f]{64}", identity.input_digest) is not None
            and type(identity.claim_epoch) is int and identity.claim_epoch >= 0
            and type(identity.authority_epoch) is int and identity.authority_epoch >= 0
            and type(identity.context_revision) is int and identity.context_revision >= 0
        )

    async def admit_scope_v3(
        self,
        verified: v1.VerifiedReadContext,
        admission: codec3.AdmissionOnlyBinding,
        *,
        ui_activity_id_hint: uuid.UUID | None,
        ui_ledger_unit_id_hint: uuid.UUID | None = None,
    ) -> codec3.P2V3ScopeMetadataProjection | None:
        """Capture operation-free metadata under the same Turn budget port.

        A null Activity hint is valid only for Activity discovery and creates no
        source grant, logical query, read slot, or QEV.
        """
        budget, locator = self._require_v3_ports()
        if not isinstance(admission, codec3.AdmissionOnlyBinding):
            raise P2ReadBackendError("invalid_auth_context")
        self._validate_grant(
            verified, owner_user_id=admission.identity.owner_user_id,
            turn_id=admission.identity.turn_id,
        )
        if not self._v3_identity_matches(admission.identity, verified):
            raise P2ReadBackendError("invalid_auth_context")
        if ui_activity_id_hint is None:
            if ui_ledger_unit_id_hint is not None:
                raise P2ReadBackendError("unsupported_scope")
            return None
        if type(ui_activity_id_hint) is not uuid.UUID:
            raise P2ReadBackendError("unsupported_scope")
        request_registry = admission.reference_registry
        if request_registry is not None:
            bind_origin = getattr(request_registry, "bind_configured_source_origin", None)
            if not callable(bind_origin):
                raise P2ReadBackendError("invalid_auth_context")
            try:
                bind_origin(self._project_url)
            except Exception as exc:
                raise P2ReadBackendError("invalid_auth_context") from exc
        counts: dict[str, int] = {}
        activity_ref = locator.bind_entity(
            "activity", ui_activity_id_hint, activity_id=ui_activity_id_hint,
        )
        snapshot = await self._v3_capture_scope_snapshot(
            verified, admission, ui_activity_id_hint,
            activity_ref=activity_ref, scope_kind="activity", ledger_unit_id=None, scope_ref=activity_ref,
            operation=None, query_state=None, table_page_counts=counts,
        )
        scope_kind: str = "activity"
        ledger_unit_id: uuid.UUID | None = None
        scope_ref = activity_ref
        if ui_ledger_unit_id_hint is not None:
            if type(ui_ledger_unit_id_hint) is not uuid.UUID:
                raise P2ReadBackendError("unsupported_scope")
            unit_row = next((
                row for row in snapshot.ledger_units
                if row.get("id") == str(ui_ledger_unit_id_hint)
            ), None)
            if (
                unit_row is None or unit_row.get("is_deleted") is not False
                or unit_row.get("type") != "sub_activity"
            ):
                raise P2ReadBackendError("unsupported_scope")
            unit_id = ui_ledger_unit_id_hint
            scope_kind = "ledger_unit"
            ledger_unit_id = unit_id
            scope_ref = locator.bind_entity(
                "ledger_unit", unit_id, activity_id=ui_activity_id_hint,
                ledger_unit_id=unit_id,
            )
        snapshot = codec3.SourceSnapshot(
            activity_id=snapshot.activity_id, activity_ref=activity_ref,
            activity=snapshot.activity, ledger_units=snapshot.ledger_units,
            participants=snapshot.participants, child_rows=snapshot.child_rows,
            claims=snapshot.claims, membership_rows=snapshot.membership_rows,
            scope_ref=scope_ref, scope_kind=scope_kind,
            ledger_unit_id=ledger_unit_id, witnesses=snapshot.witnesses,
        )
        try:
            projection = await self._v3_cpu_stage(
                admission,
                lambda: codec3.project_scope_metadata(
                    snapshot, verified.principal_user_id, binder=locator,
                    identity=admission.identity,
                ),
            )
        except codec3.SourceCodecError as exc:
            raise P2ReadBackendError("unsupported_scope") from exc
        registry = admission.reference_registry
        if registry is not None:
            if registry is not locator:
                raise P2ReadBackendError("invalid_auth_context")
            store = getattr(registry, "_store", None)
            accept = getattr(store, "accept_p2_v3_admission_metadata", None)
            if not callable(accept):
                raise P2ReadBackendError("invalid_auth_context")
            try:
                accepted = accept(
                    admission.identity.owner_user_id, admission.identity.turn_id,
                    binding=admission, projection=projection,
                )
            except Exception as exc:
                raise P2ReadBackendError("invalid_upstream_response") from exc
            accepted_projection = getattr(accepted, "projection", None)
            if not isinstance(accepted_projection, codec3.P2V3ScopeMetadataProjection):
                raise P2ReadBackendError("invalid_upstream_response")
            return accepted_projection
        # Explicitly test-only fake ports may preserve source-shape tests. A
        # production Store admission always carries the sealed registry above;
        # absence of the Store acceptance method is otherwise fail-closed.
        fake_accept = getattr(budget, "test_only_accept_p2_v3_admission_metadata", None)
        if not callable(fake_accept):
            raise P2ReadBackendError("invalid_auth_context")
        accepted_projection = fake_accept(admission, projection)
        if not isinstance(accepted_projection, codec3.P2V3ScopeMetadataProjection):
            raise P2ReadBackendError("invalid_upstream_response")
        return accepted_projection

    async def _v3_capture_scope_snapshot(
        self,
        verified: v1.VerifiedReadContext,
        binding: codec3.SourceBinding,
        activity_id: uuid.UUID,
        *,
        activity_ref: str,
        scope_kind: str,
        ledger_unit_id: uuid.UUID | None,
        scope_ref: str | None,
        operation: pc3.P2ReadOperation | None,
        query_state: _V3QueryCaptureState | None,
        table_page_counts: dict[str, int] | None = None,
    ) -> codec3.SourceSnapshot:
        if type(activity_id) is not uuid.UUID:
            raise P2ReadBackendError("unsupported_scope")
        user_id = verified.principal_user_id
        filters = {
            "activities": [("id", f"eq.{activity_id}")],
            "activity_members": [("activity_id", f"eq.{activity_id}"), ("user_id", f"eq.{user_id}")],
            "ledger_units": [("activity_id", f"eq.{activity_id}")],
            "participants": [("activity_id", f"eq.{activity_id}")],
            "sub_activity_participants": [("activity_id", f"eq.{activity_id}")],
            "participant_claims": [("activity_id", f"eq.{activity_id}"), ("user_id", f"eq.{user_id}")],
        }
        tables: dict[str, codec3.SourceTable] = {}
        filters["activities"].append(("is_deleted", "eq.false"))
        for table in ("activities", "activity_members", "ledger_units", "participants", "sub_activity_participants", "participant_claims"):
            tables[table] = await self._v3_fetch_table(
                verified, binding, table, filters[table],
                order=sorted(self._V3_ORDERS[table])[0], operation=None,
                query_state=query_state, table_page_counts=table_page_counts,
            )
        if any(not table.complete for table in tables.values()):
            raise P2ReadBackendError("read_limit_exceeded")
        if query_state is not None:
            query_state.fence_complete = query_state.fence_complete and all(
                table.complete and table.range_contiguous and table.unique_items_verified
                for table in tables.values()
            )
            for table, source_table in tables.items():
                key = f"__scope_{len(query_state.tables)}_{table}"
                query_state.tables[key] = source_table
            query_state.tables["ledger_units"] = tables["ledger_units"]
        activity_rows = tables["activities"].rows
        if len(activity_rows) != 1:
            raise P2ReadBackendError("scope_unavailable")
        row_activity_id = uuid.UUID(activity_rows[0]["id"])
        if row_activity_id != activity_id:
            raise P2ReadBackendError("unsupported_scope")
        witnesses = tuple(page for table in tables.values() for page in table.pages)
        return codec3.SourceSnapshot(
            activity_id=activity_id,
            activity_ref=activity_ref,
            activity=activity_rows[0],
            ledger_units=tables["ledger_units"].rows,
            participants=tables["participants"].rows,
            child_rows=tables["sub_activity_participants"].rows,
            claims=tables["participant_claims"].rows,
            membership_rows=tables["activity_members"].rows,
            scope_ref=scope_ref,
            scope_kind=scope_kind, ledger_unit_id=ledger_unit_id,
            witnesses=witnesses,
        )

    async def _v3_fetch_table(
        self,
        verified: v1.VerifiedReadContext,
        binding: codec3.SourceBinding,
        table: str,
        filters: Sequence[tuple[str, str]],
        *,
        order: str,
        operation: pc3.P2ReadOperation | None,
        query_state: _V3QueryCaptureState | None,
        table_page_counts: dict[str, int] | None = None,
    ) -> codec3.SourceTable:
        if table not in codec3._SOURCE_COLUMNS or table not in self._V3_TABLE_ROLES:
            raise P2ReadBackendError("unsupported_read")
        role = self._V3_TABLE_ROLES[table]
        if operation is None:
            if role not in {"activity", "membership", "ledger_unit", "participant", "actor"}:
                raise P2ReadBackendError("unsupported_read")
        elif role not in self._V3_OPERATION_ROLES[operation.value]:
            raise P2ReadBackendError("unsupported_read")
        if order not in self._V3_ORDERS.get(table, set()):
            raise P2ReadBackendError("unsupported_read")
        allowed_filters = self._V3_FILTER_COLUMNS.get(table, set())
        for column, value in filters:
            if column not in allowed_filters or not isinstance(value, str) or len(value) > 4096:
                raise P2ReadBackendError("unsupported_read")
            if not re.fullmatch(r"(?:eq\.[A-Za-z0-9_.,()!:-]+|in\.\([A-Za-z0-9_.,-]*\)|gte\.[0-9TZ:+.-]+|lt\.[0-9TZ:+.-]+)", value):
                raise P2ReadBackendError("unsupported_read")
        local_counts = table_page_counts if table_page_counts is not None else {}
        rows: list[Mapping[str, Any]] = []
        pages: list[codec3.SourcePage] = []
        expected_total: int | None = None
        offset = 0
        for _ in range(codec3.MAX_PAGES_PER_TABLE):
            query_logical_id = query_state.binding.logical_query_id if query_state is not None else None
            capture_chain_id = query_state.binding.query_attempt_id if query_state is not None else None
            budget, _ = self._require_v3_ports()
            current_budget = budget.remaining_limits(
                binding, logical_query_id=query_logical_id,
                capture_chain_id=capture_chain_id, table=table,
            )
            count = max(
                query_state.table_pages.get(table, 0), current_budget.capture_chain_table_pages,
            ) if query_state is not None else local_counts.get(table, 0)
            if query_state is not None:
                chain_pages_used = max(query_state.source_pages, current_budget.capture_chain_pages)
            else:
                chain_pages_used = 0
            if count >= codec3.MAX_PAGES_PER_TABLE:
                break
            if query_state is not None and chain_pages_used >= codec3.MAX_SOURCE_PAGES_PER_CAPTURE_CHAIN:
                raise P2ReadBackendError("read_limit_exceeded")
            page = await self._v3_fetch_page(
                verified, binding, table, filters, order=order, offset=offset,
                logical_query_id=query_logical_id, capture_chain_id=capture_chain_id,
            )
            if query_state is not None:
                query_state.source_pages += 1
                query_state.table_pages[table] = count + 1
                query_state.captures.append(page.witness)
            else:
                local_counts[table] = count + 1
            if page.range.total_known:
                if expected_total is not None and expected_total != page.range.total:
                    raise P2ReadBackendError("data_changed_during_read")
                expected_total = page.range.total
            if page.offset != offset:
                raise P2ReadBackendError("invalid_upstream_response")
            rows.extend(page.rows)
            pages.append(page)
            offset += page.range.row_count
            if page.range.row_count == 0:
                break
            if expected_total is not None and offset >= expected_total:
                break
            if page.range.row_count < codec3.MAX_ROWS_PER_PAGE:
                break
        try:
            return codec3.source_table(rows, pages, table=table)
        except codec3.SourceCodecError as exc:
            raise P2ReadBackendError("invalid_upstream_response") from exc

    async def _v3_fetch_page(
        self,
        verified: v1.VerifiedReadContext,
        binding: codec3.SourceBinding,
        table: str,
        filters: Sequence[tuple[str, str]],
        *,
        order: str,
        offset: int,
        logical_query_id: str | None = None,
        capture_chain_id: str | None = None,
    ) -> codec3.SourcePage:
        budget, _ = self._require_v3_ports()
        identity = binding.identity
        remaining = budget.remaining_limits(
            binding, logical_query_id=logical_query_id,
            capture_chain_id=capture_chain_id, table=table,
        )
        if remaining.get_attempts <= 0 or remaining.response_bytes <= 0:
            raise P2ReadBackendError("read_limit_exceeded")
        timeout_cap = min(
            self._timeout, remaining.active_us / 1_000_000,
            remaining.backend_us / 1_000_000, remaining.turn_remaining_us / 1_000_000,
            (verified.expires_at.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds(),
        )
        if timeout_cap <= 0:
            raise P2ReadBackendError("upstream_timeout")
        params = [("select", ",".join(codec3._SOURCE_COLUMNS[table])), *filters,
                  ("order", order), ("limit", str(codec3.MAX_ROWS_PER_PAGE)), ("offset", str(offset))]
        url = f"{self._project_url}/rest/v1/{table}?{urlencode(params)}"
        if len(url) > 12_000:
            raise P2ReadBackendError("read_limit_exceeded")
        request_sha = _request_url_sha(url)
        response_limit = min(self._max_response_bytes, codec3.MAX_RESPONSE_BYTES, remaining.response_bytes)
        if response_limit <= 0:
            raise P2ReadBackendError("read_limit_exceeded")
        reservation = budget.reserve_get(
            binding, source_role=self._V3_TABLE_ROLES[table], request_digest=request_sha,
            active_limit_us=max(1, int(timeout_cap * 1_000_000)),
            backend_limit_us=min(remaining.backend_us, max(1, int(timeout_cap * 1_000_000))),
            response_bytes_limit=response_limit,
            logical_query_id=logical_query_id, capture_chain_id=capture_chain_id,
            table=table,
        )
        try:
            budget.mark_dispatch_started(binding, reservation)
        except asyncio.CancelledError:
            # The Store port has classified a pre-marker cancellation and
            # released it, or retained an already-marked reservation for
            # conservative recovery. Never turn cancellation into a GET.
            raise
        except codec3.P2V3DispatchStateUncertain:
            # The durable marker could not be classified. Do not issue a GET
            # and do not pretend the reservation was certainly pre-dispatch;
            # recovery owns the remaining conservative settlement.
            raise P2ReadBackendError("upstream_failure") from None
        except BaseException as exc:
            try:
                budget.settle_get(
                    binding, reservation, outcome="known_no_dispatch", actual_active_us=0,
                    actual_backend_us=0, actual_response_bytes=0, raw_body_sha256=None,
                )
            except BaseException as settlement_exc:
                if not isinstance(exc, Exception):
                    raise exc
                if not isinstance(settlement_exc, Exception):
                    raise settlement_exc
                raise P2ReadBackendError("upstream_failure") from None
            if not isinstance(exc, Exception):
                raise exc
            if isinstance(exc, P2ReadBackendError):
                raise
            raise P2ReadBackendError("upstream_failure") from None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {verified.access_token}",
            "apikey": self._publishable_key,
            "Prefer": "count=exact",
        }
        control = v1._RequestControl()
        start = time.monotonic()
        response: v1.TransportResponse | None = None
        error: BaseException | None = None
        timer = threading.Timer(timeout_cap, control.abort)
        timer.daemon = True
        timer.start()
        try:
            worker = asyncio.create_task(asyncio.to_thread(
                self._transport.get, url, headers, timeout=timeout_cap,
                max_response_bytes=response_limit, control=control,
            ))
            async with asyncio.timeout(timeout_cap):
                response = await worker
        except BaseException as exc:
            error = exc
            control.abort()
        finally:
            timer.cancel()
        elapsed_us = max(0, int((time.monotonic() - start) * 1_000_000))
        observed_at = datetime.now(timezone.utc)
        is_known = isinstance(response, v1.TransportResponse) and type(response.body) is bytes
        raw = response.body if is_known else b""
        raw_sha = hashlib.sha256(raw).hexdigest() if is_known else None
        try:
            budget.settle_get(
                binding, reservation, outcome="actual" if is_known else "unknown",
                actual_active_us=elapsed_us, actual_backend_us=elapsed_us,
                actual_response_bytes=len(raw) if is_known else 0,
                raw_body_sha256=raw_sha,
            )
        except BaseException as settlement_error:
            # Keep an original transport control signal primary. Otherwise a
            # newly raised control signal from durable accounting must escape
            # even when an ordinary timeout/network exception was already in
            # flight. Ordinary cleanup failures retain the prior mapping.
            if error is not None and not isinstance(error, Exception):
                raise error
            if not isinstance(settlement_error, Exception):
                raise settlement_error
            if error is None:
                raise
        if error is not None and not isinstance(error, Exception):
            # asyncio cancellation and process-control exceptions must not be
            # hidden behind the transport timeout/error mapping.
            raise error
        if not is_known:
            if isinstance(error, (asyncio.TimeoutError, TimeoutError)) or control.aborted:
                raise P2ReadBackendError("upstream_timeout") from None
            raise P2ReadBackendError("upstream_failure") from None
        assert response is not None
        returned_count = 0
        parsed_rows: tuple[Mapping[str, Any], ...] | None = None
        parsed_range: codec3.ParsedRange | None = None
        parse_error: BaseException | None = None
        parse_control: BaseException | None = None
        if response.status in (200, 206):
            try:
                parsed_rows = await self._v3_cpu_stage(
                    binding, lambda: codec3.parse_source_rows(raw, table=table),
                )
                returned_count = len(parsed_rows)
                parsed_range = codec3.parse_content_range(
                    response.content_range, expected_offset=offset,
                    row_count=returned_count, status=response.status,
                )
            except BaseException as exc:
                if not isinstance(exc, Exception):
                    parse_control = exc
                else:
                    parse_error = exc
        try:
            capture_id = budget.record_cost_only_capture(
                binding, reservation, http_status=response.status,
                content_range=response.content_range, returned_count=returned_count,
                response_bytes=len(raw), raw_body_sha256=raw_sha or "0" * 64,
                observed_at=observed_at,
            )
        except BaseException:
            # A cancellation raised while parsing is the caller's original
            # control signal. A later cost-only capture failure must not
            # replace it; the durable GET settlement remains charged and any
            # uncommitted capture stays recoverable as pending work.
            if parse_control is not None:
                raise parse_control
            raise
        if parse_control is not None:
            raise parse_control
        if response.status == 401:
            raise P2ReadBackendError("auth_rejected")
        if response.status == 403:
            raise P2ReadBackendError("access_denied")
        if response.status == 429:
            raise P2ReadBackendError("rate_limited")
        if response.status in (408, 504):
            raise P2ReadBackendError("upstream_timeout")
        if response.status not in (200, 206):
            raise P2ReadBackendError("upstream_failure")
        if parse_error is not None or parsed_rows is None or parsed_range is None:
            if isinstance(parse_error, codec3.SourceCodecError) and str(parse_error) == "query_source_page_limit":
                raise P2ReadBackendError("read_limit_exceeded") from None
            raise P2ReadBackendError("invalid_upstream_response") from None
        witness = codec3.CapturedPageWitness(
            owner_user_id=identity.owner_user_id, turn_id=identity.turn_id,
            generation=identity.generation, input_seq=identity.input_seq,
            input_digest=identity.input_digest, claim_epoch=identity.claim_epoch,
            authority_epoch=identity.authority_epoch, context_revision=identity.context_revision,
            binding_kind="admission" if isinstance(binding, codec3.AdmissionOnlyBinding) else "query_attempt",
            admission_id=binding.admission_id if isinstance(binding, codec3.AdmissionOnlyBinding) else None,
            logical_query_id=binding.logical_query_id if isinstance(binding, codec3.QueryAttemptBinding) else None,
            query_attempt_id=binding.query_attempt_id if isinstance(binding, codec3.QueryAttemptBinding) else None,
            page_index=binding.page_index if isinstance(binding, codec3.QueryAttemptBinding) else None,
            source_role=self._V3_TABLE_ROLES[table], reservation_id=reservation,
            capture_id=capture_id, request_sha256=request_sha, response_sha256=raw_sha or "0" * 64,
            response_bytes=len(raw), http_status=response.status,
            content_range=response.content_range, observed_at=observed_at, elapsed_us=elapsed_us,
        )
        return codec3.SourcePage(
            table=table, rows=parsed_rows, range=parsed_range, offset=offset,
            status=response.status, content_range=response.content_range or "",
            request_sha256=request_sha, request_url=url,
            raw_body_sha256=raw_sha or "0" * 64,
            observed_at=observed_at, elapsed_us=elapsed_us,
            reservation_id=reservation, witness=witness,
            raw_body=raw,
        )

    async def _v3_cpu_stage(self, binding: codec3.SourceBinding, function: Callable[[], Any]) -> Any:
        budget, _ = self._require_v3_ports()
        remaining = budget.remaining_limits(binding)
        limit = min(remaining.active_us, remaining.backend_us, remaining.turn_remaining_us)
        if limit <= 0:
            raise P2ReadBackendError("read_limit_exceeded")
        try:
            reservation = budget.reserve_processing(
                binding, active_limit_us=limit, backend_limit_us=min(limit, codec3.MAX_BACKEND_US_PER_TURN),
            )
        except codec3.P2V3DispatchStateUncertain:
            raise P2ReadBackendError("upstream_failure") from None
        started = time.monotonic()
        try:
            result = function()
        except BaseException as original:
            elapsed = max(0, int((time.monotonic() - started) * 1_000_000))
            try:
                budget.settle_processing(
                    binding, reservation, actual_active_us=elapsed, actual_backend_us=elapsed,
                )
            except BaseException:
                # Preserve cancellation/process-control signals from the work
                # itself. If settlement could not be proven, the durable
                # reservation remains pending for conservative recovery.
                if not isinstance(original, Exception):
                    raise original
                raise
            raise
        elapsed = max(0, int((time.monotonic() - started) * 1_000_000))
        budget.settle_processing(
            binding, reservation, actual_active_us=elapsed, actual_backend_us=elapsed,
        )
        return result

    async def read_candidate_v3(
        self,
        request: pc3.P2ReadQueryRequest | pc3.P2ReadContinueRequest,
        verified: v1.VerifiedReadContext,
        grant: pc3.P2SourceAuthorizationGrant,
        *,
        admission: codec3.AdmissionOnlyBinding,
        admission_projection: codec3.P2V3ScopeMetadataProjection | None,
        query_binding: codec3.QueryAttemptBinding | None = None,
        context_version: str | None = None,
    ) -> P2V3PendingSourceAttempt:
        """Capture one bounded source attempt without issuing a result/capability.

        The return is private pending state only. Store must independently
        reparse and accept every exact capture before constructing the live DTO
        or issuing a continuation. No continuation ref is minted here.
        """
        budget, locator = self._require_v3_ports()
        if not isinstance(admission, codec3.AdmissionOnlyBinding):
            raise P2ReadBackendError("invalid_auth_context")
        self._validate_grant(
            verified, owner_user_id=admission.identity.owner_user_id,
            turn_id=admission.identity.turn_id,
        )
        identity = admission.identity
        if not self._v3_identity_matches(identity, verified):
            raise P2ReadBackendError("invalid_auth_context")
        if not isinstance(grant, pc3.P2SourceAuthorizationGrant):
            raise P2ReadBackendError("invalid_auth_context")
        if request.profile_id != pc3.P2_V3_CANDIDATE_PROFILE_ID or request.versions != pc3.P2_V3_VERSIONS:
            raise P2ReadBackendError("unsupported_read")
        now = datetime.now(timezone.utc)
        if grant.expires_at.tzinfo is None or grant.expires_at.utcoffset() is None or grant.expires_at <= now:
            raise P2ReadBackendError("invalid_auth_context")
        if (
            grant.generation != identity.generation
            or grant.source_input_seq != identity.input_seq
            or grant.input_digest != identity.input_digest
            or locator.resolve_principal(str(grant.principal_ref)) != verified.principal_user_id
            or grant.owner_turn_ref != locator.owner_turn_ref(identity=identity)
        ):
            raise P2ReadBackendError("invalid_auth_context")

        # Pin the configured HTTPS source before the first query GET, including
        # unscoped Activity discovery. A response URL must never establish its
        # own trusted origin during Store acceptance.
        bind_origin = getattr(locator, "bind_configured_source_origin", None)
        if not callable(bind_origin):
            raise P2ReadBackendError("invalid_auth_context")
        try:
            bind_origin(self._project_url)
        except Exception as exc:
            raise P2ReadBackendError("invalid_auth_context") from exc

        if isinstance(request, pc3.P2ReadContinueRequest):
            request_query_ref = str(request.query_ref)
            descriptor = locator.load_query_descriptor(request_query_ref, identity=identity)
            if query_binding is not None:
                raise P2ReadBackendError("unsupported_read")
            try:
                previous_proof = locator.load_continuation_proof(
                    query_ref=request_query_ref, next_page_ref=str(request.next_page_ref),
                    identity=identity,
                )
            except BaseException as exc:
                raise P2ReadBackendError("unsupported_scope") from exc
            query_binding = locator.consume_continuation(
                query_ref=request_query_ref, next_page_ref=str(request.next_page_ref),
                turn_id=identity.turn_id,
            )
            if (
                not isinstance(query_binding, codec3.QueryAttemptBinding)
                or query_binding.identity != identity
                or locator.query_ref(query_binding.logical_query_id, identity=identity) != request_query_ref
            ):
                raise P2ReadBackendError("invalid_auth_context")
            actual_request = descriptor.request
        else:
            previous_proof = None
            if not isinstance(request, pc3.P2ReadQueryRequest) or not isinstance(query_binding, codec3.QueryAttemptBinding):
                raise P2ReadBackendError("invalid_auth_context")
            if query_binding.identity != identity or query_binding.page_index != 0:
                raise P2ReadBackendError("invalid_auth_context")
            query_ref_for_descriptor = locator.query_ref(query_binding.logical_query_id, identity=identity)
            descriptor = locator.load_query_descriptor(query_ref_for_descriptor, identity=identity)
            actual_request = request
            if descriptor.request.model_dump(mode="json", exclude_none=False) != request.model_dump(mode="json", exclude_none=False):
                raise P2ReadBackendError("invalid_auth_context")

        if query_binding is None or query_binding.identity != identity:
            raise P2ReadBackendError("invalid_auth_context")
        criteria = actual_request.criteria
        operation = actual_request.operation
        criteria_sha = pc3.p2_criteria_digest(criteria)
        if (
            grant.operation != operation or grant.criteria_digest != criteria_sha
            or grant.scope != actual_request.scope
        ):
            raise P2ReadBackendError("invalid_auth_context")
        if descriptor.public_request_digest and descriptor.public_request_digest != _canonical_sha(actual_request.model_dump(mode="json", exclude_none=False)):
            raise P2ReadBackendError("invalid_auth_context")
        if (
            type(descriptor.ui_expense_ids) is not tuple
            or len(descriptor.ui_expense_ids) > codec3.MAX_UI_EXPENSE_SELECTION
            or len(set(descriptor.ui_expense_ids)) != len(descriptor.ui_expense_ids)
            or descriptor.ui_expense_ids != tuple(sorted(descriptor.ui_expense_ids, key=str))
        ):
            raise P2ReadBackendError("unsupported_scope")
        expected_selection_digest = _canonical_sha({
            "criteria": actual_request.criteria.model_dump(mode="json", exclude_none=False),
            "ui_expense_refs": descriptor.ui_expense_refs,
        })
        if descriptor.normalized_selection_digest:
            allowed_selection_digests = {expected_selection_digest}
            # Earlier isolated codec fixtures used a private-ID key in this
            # digest. Keep only the empty-selection fixture shape readable;
            # Store-bound descriptors always carry the reviewed opaque-ref
            # digest and any non-empty selection must use that form.
            if not descriptor.ui_expense_refs:
                allowed_selection_digests.add(_canonical_sha({
                    "criteria": actual_request.criteria.model_dump(mode="json", exclude_none=False),
                    "ui_expense_ids": tuple(str(item) for item in descriptor.ui_expense_ids),
                }))
            if descriptor.normalized_selection_digest not in allowed_selection_digests:
                raise P2ReadBackendError("invalid_auth_context")
        if context_version is not None and (type(context_version) is not str or not context_version.strip() or len(context_version) > 200):
            raise P2ReadBackendError("unsupported_read")

        state = _V3QueryCaptureState(
            operation=operation, binding=query_binding,
            previous_proof=previous_proof,
        )
        if actual_request.scope is None:
            if operation is not pc3.P2ReadOperation.ACTIVITIES or admission_projection is not None:
                raise P2ReadBackendError("unsupported_scope")
            start_snapshot = None
            activity_id = None
            ledger_unit_id = None
            scope_kind = None
            scope_ref = None
        else:
            if admission_projection is None:
                raise P2ReadBackendError("unsupported_scope")
            public_scope = actual_request.scope
            activity_id = locator.resolve_activity_ref(str(public_scope.activity_ref))
            if public_scope.scope_kind == "ledger_unit":
                ledger_unit_id = locator.resolve_entity(
                    str(public_scope.ledger_unit_ref), "ledger_unit", activity_id=activity_id,
                )
            else:
                ledger_unit_id = None
            if (
                admission_projection.snapshot.activity_id != activity_id
                or admission_projection.snapshot.scope_ref != public_scope.scope_ref
                or admission_projection.snapshot.scope_kind != public_scope.scope_kind
                or admission_projection.snapshot.ledger_unit_id != ledger_unit_id
            ):
                raise P2ReadBackendError("unsupported_scope")
            self._v3_validate_admission_projection(admission_projection, admission)
            start_snapshot = await self._v3_capture_scope_snapshot(
                verified, query_binding, activity_id,
                activity_ref=str(public_scope.activity_ref), scope_kind=public_scope.scope_kind,
                ledger_unit_id=ledger_unit_id, scope_ref=str(public_scope.scope_ref),
                operation=operation, query_state=state,
            )
            try:
                codec3.project_scope_metadata(
                    start_snapshot, verified.principal_user_id,
                    binder=locator, identity=identity,
                )
            except codec3.SourceCodecError as exc:
                raise P2ReadBackendError("unsupported_scope") from exc
            if not codec3.scope_metadata_is_current(admission_projection.snapshot, start_snapshot):
                raise P2ReadBackendError("data_changed_during_read")
            scope_kind = public_scope.scope_kind
            scope_ref = str(public_scope.scope_ref)

        operation_tables, primary_table = await self._v3_execute_sources(
            actual_request, descriptor, verified, query_binding, state,
            activity_id=activity_id, ledger_unit_id=ledger_unit_id,
            scope_kind=scope_kind, scope_ref=scope_ref,
        )
        if start_snapshot is not None:
            assert activity_id is not None and actual_request.scope is not None
            end_snapshot = await self._v3_capture_scope_snapshot(
                verified, query_binding, activity_id,
                activity_ref=str(actual_request.scope.activity_ref),
                scope_kind=actual_request.scope.scope_kind,
                ledger_unit_id=ledger_unit_id, scope_ref=str(actual_request.scope.scope_ref),
                operation=operation, query_state=state,
            )
            try:
                codec3.project_scope_metadata(
                    end_snapshot, verified.principal_user_id,
                    binder=locator, identity=identity,
                )
            except codec3.SourceCodecError as exc:
                raise P2ReadBackendError("data_changed_during_read") from exc
            if not codec3.scope_metadata_is_current(start_snapshot, end_snapshot):
                raise P2ReadBackendError("data_changed_during_read")
            source_version_fenced = True
        else:
            end_snapshot = None
            source_version_fenced = False

        def project() -> tuple[pc3.P2Fact, ...]:
            return codec3.project_facts(
                operation, operation_tables, start_snapshot, actual_request,
                query_evidence_ref=str(locator.query_evidence_ref(
                    query_binding.logical_query_id, query_binding.query_attempt_id,
                    identity=identity, page_index=query_binding.page_index,
                )),
                binder=locator, principal_user_id=verified.principal_user_id,
                context_version=context_version or "",
                authorized_expense_ids=frozenset(descriptor.ui_expense_ids) if descriptor.ui_expense_ids else None,
            )

        try:
            all_facts = await self._v3_cpu_stage(query_binding, project)
        except codec3.SourceCodecError as exc:
            raise P2ReadBackendError("invalid_upstream_response") from exc
        if len(all_facts) > codec3.MAX_FACTS_PER_QUERY:
            raise P2ReadBackendError("read_limit_exceeded")
        facts_page_index = query_binding.page_index
        if facts_page_index >= 4:
            raise P2ReadBackendError("read_limit_exceeded")
        page_start = facts_page_index * codec3.MAX_FACTS_PER_PAGE
        page_facts = tuple(all_facts[page_start:page_start + codec3.MAX_FACTS_PER_PAGE])
        has_more = len(all_facts) > page_start + len(page_facts)
        query_ref = locator.query_ref(query_binding.logical_query_id, identity=identity)
        result_ref = locator.result_ref(
            query_binding.logical_query_id, query_binding.query_attempt_id,
            identity=identity, page_index=facts_page_index,
        )
        evidence_ref = locator.query_evidence_ref(
            query_binding.logical_query_id, query_binding.query_attempt_id,
            identity=identity, page_index=facts_page_index,
        )
        criteria_ref = locator.criteria_ref(criteria_sha, identity=identity)
        source_kind = operation.value.removeprefix("read.")
        source_ref = locator.source_ref(
            query_binding.logical_query_id, identity=identity, source_kind=source_kind,
        )
        preaccept = self._v3_build_preaccept_projection(
            operation, actual_request, descriptor, state, operation_tables,
            primary_table=primary_table, all_facts=all_facts, page_facts=page_facts,
            page_index=facts_page_index, has_more=has_more,
            query_ref=str(query_ref), result_ref=str(result_ref), evidence_ref=str(evidence_ref),
            criteria_ref=str(criteria_ref), source_ref=str(source_ref), criteria_sha=criteria_sha,
            source_version_fenced=source_version_fenced,
        )
        query_page_by_capture = {
            page.witness.capture_id: page
            for table in state.tables.values()
            for page in table.pages
        }
        try:
            query_captures = tuple(
                query_page_by_capture[witness.capture_id] for witness in state.captures
            )
        except KeyError:
            raise P2ReadBackendError("invalid_upstream_response") from None
        if len(query_captures) != len(state.captures):
            raise P2ReadBackendError("invalid_upstream_response")
        bootstrap_captures = (
            tuple(admission_projection.snapshot.witnesses)
            if admission_projection is not None else ()
        )
        resolved_scope_ids = tuple(
            value for value in (activity_id, ledger_unit_id) if value is not None
        )
        return P2V3PendingSourceAttempt(
            identity=identity,
            admission=admission,
            query_binding=query_binding,
            grant=grant,
            request=actual_request,
            descriptor=descriptor,
            previous_proof=previous_proof,
            admission_projection=admission_projection,
            query_tables=tuple(state.tables.items()),
            bootstrap_captures=bootstrap_captures,
            query_captures=query_captures,
            resolved_scope_ids=resolved_scope_ids,
            context_version=context_version,
            projection=preaccept,
        )

    @staticmethod
    def _v3_validate_admission_projection(
        projection: codec3.P2V3ScopeMetadataProjection,
        admission: codec3.AdmissionOnlyBinding,
    ) -> None:
        identity = admission.identity
        if not isinstance(projection, codec3.P2V3ScopeMetadataProjection):
            raise P2ReadBackendError("unsupported_scope")
        if not projection.captures or any(
            witness.binding_kind != "admission"
            or witness.admission_id != admission.admission_id
            or witness.logical_query_id is not None
            or witness.query_attempt_id is not None
            or witness.owner_user_id != identity.owner_user_id
            or witness.turn_id != identity.turn_id
            or witness.generation != identity.generation
            or witness.input_seq != identity.input_seq
            or witness.input_digest != identity.input_digest
            or witness.claim_epoch != identity.claim_epoch
            or witness.authority_epoch != identity.authority_epoch
            or witness.context_revision != identity.context_revision
            for witness in projection.captures
        ):
            raise P2ReadBackendError("unsupported_scope")

    def _v3_build_preaccept_projection(
        self,
        operation: pc3.P2ReadOperation,
        request: pc3.P2ReadQueryRequest,
        descriptor: codec3.V3QueryDescriptor,
        state: _V3QueryCaptureState,
        tables: Mapping[str, codec3.SourceTable],
        *,
        primary_table: str,
        all_facts: tuple[pc3.P2Fact, ...],
        page_facts: tuple[pc3.P2Fact, ...],
        page_index: int,
        has_more: bool,
        query_ref: str,
        result_ref: str,
        evidence_ref: str,
        criteria_ref: str,
        source_ref: str,
        criteria_sha: str,
        source_version_fenced: bool,
    ) -> P2V3PreacceptProjection:
        budget, locator = self._require_v3_ports()
        if not state.captures or len(state.captures) != state.source_pages:
            raise P2ReadBackendError("invalid_upstream_response")
        if page_index < 0 or page_index >= 4 or len(all_facts) > codec3.MAX_FACTS_PER_QUERY:
            raise P2ReadBackendError("read_limit_exceeded")
        primary = tables.get(primary_table)
        if primary is None:
            raise P2ReadBackendError("invalid_upstream_response")

        captured_tables = tuple(state.tables.values())
        source_complete = (
            state.fence_complete
            and bool(captured_tables)
            and all(
                item.complete and item.range_contiguous and item.unique_items_verified
                for item in captured_tables
            )
        )
        range_contiguous = all(item.range_contiguous for item in captured_tables)
        unique_verified = all(item.unique_items_verified for item in captured_tables)
        stable_totals = source_complete and all(
            item.source_total is not None for item in captured_tables if item.pages
        )
        observed_at = max((item.observed_at for item in state.captures), default=None)
        if observed_at is None:
            raise P2ReadBackendError("invalid_upstream_response")

        normalized_digest = descriptor.normalized_selection_digest or _canonical_sha({
            "criteria": request.criteria.model_dump(mode="json", exclude_none=False),
            "ui_expense_ids": (),
        })
        query_digest = _chain_hash(tuple(item.request_sha256 for item in state.captures))
        # This is a digest of actual response-body digests, distinct from the
        # per-GET raw_body_sha256 stored only in the private transient witness.
        body_digest = _chain_hash(tuple(item.response_sha256 for item in state.captures))
        projection_rows = tuple(
            self._v3_projection_comparison_row(item) for item in all_facts
        )
        projection_digest = _canonical_sha(projection_rows)
        primary_total = primary.source_total
        returned_count = len(primary.rows)
        matched_count = len(all_facts)
        matched_total = matched_count if source_complete else None
        if matched_count:
            zero_classification = "nonzero"
        elif not source_complete:
            zero_classification = "unknown_or_partial"
        elif primary_total == 0:
            zero_classification = "backend_zero"
        else:
            zero_classification = "post_filter_zero"

        versions_by_activity: dict[str, int] = {}
        if request.scope is not None:
            snapshot_table = next((
                item for key, item in state.tables.items() if key.startswith("__scope_") and item.table == "activities"
            ), None)
            # Scope snapshots are captured twice; activity identity/version is
            # stable only after the explicit pre/post fence comparison.
            if snapshot_table is None or len(snapshot_table.rows) != 1:
                raise P2ReadBackendError("invalid_upstream_response")
            row = snapshot_table.rows[0]
            versions_by_activity[str(row["id"])] = codec3._integer(row, "financial_version")
        else:
            activity_table = tables.get("activities")
            if activity_table is not None:
                for row in activity_table.rows:
                    if row.get("is_deleted") is False:
                        versions_by_activity[str(row["id"])] = codec3._integer(row, "financial_version")
        financial_versions = tuple(
            pc3.P2FinancialVersion(
                activity_ref=locator.bind_entity("activity", uuid.UUID(activity_id), activity_id=uuid.UUID(activity_id)),
                financial_version=version,
            )
            for activity_id, version in sorted(versions_by_activity.items())
        )
        financial_versions_digest = _canonical_sha(tuple(
            (item.activity_ref, item.financial_version) for item in financial_versions
        ))

        prior = state.previous_proof
        if prior is not None:
            if (
                prior.logical_query_id != state.binding.logical_query_id
                or prior.page_index != page_index - 1
                or prior.normalized_criteria_digest != normalized_digest
                or prior.query_digest != query_digest
                or prior.body_digest != body_digest
                or prior.projection_digest != projection_digest
                or prior.source_total != primary_total
                or prior.financial_versions_digest != financial_versions_digest
                or prior.source_query_complete != source_complete
            ):
                raise P2ReadBackendError("data_changed_during_read")

        if has_more:
            if page_index >= 3:
                raise P2ReadBackendError("read_limit_exceeded")

        page_complete = not has_more
        summary = pc3.P2PageSummary(
            pages_seen=len(state.captures), has_more=has_more, truncated=has_more,
            source_query_complete=source_complete, model_projection_complete=page_complete,
            range_contiguous=range_contiguous, stable_total_verified=stable_totals,
            source_version_fenced=source_version_fenced,
            unique_items_verified=unique_verified,
            expected_total=matched_count if source_complete else None,
        )
        evidence = pc3.P2QueryEvidence(
            profile_id=pc3.P2_V3_CANDIDATE_PROFILE_ID, versions=pc3.P2_V3_VERSIONS,
            query_evidence_ref=evidence_ref, query_ref=query_ref, result_ref=result_ref,
            operation=operation, criteria_ref=criteria_ref, criteria_digest=criteria_sha,
            normalized_criteria_digest=normalized_digest, backend_criteria_stage="scope_only",
            source_kind=operation.value.removeprefix("read."), source_ref=source_ref,
            source_version=(
                "activity-list-observation" if request.scope is None
                else "activity-fv:" + str(next(iter(versions_by_activity.values())))
            ),
            observed_at=observed_at, simulation=False,
            returned_count=returned_count, matched_count=matched_count,
            source_total=primary_total, matched_total=matched_total,
            page_count=len(state.captures), query_zero_classification=zero_classification,
            source_query_complete=source_complete, model_projection_complete=page_complete,
            matching_fact_refs=tuple(_fact_opaque_ref(item) for item in all_facts),
            financial_versions=financial_versions, page=summary,
            query_digest=query_digest, body_digest=body_digest, projection_digest=projection_digest,
        )
        page = pe3.P2V3HistoricalReadPage(
            items=page_facts, completeness=(
                pc3.ReadCompleteness.COMPLETE if page_complete
                else pc3.ReadCompleteness.PARTIAL
            ), has_more=has_more, page_index=page_index,
            range_contiguous=range_contiguous, stable_total_verified=stable_totals,
            source_version_fenced=source_version_fenced,
            unique_items_verified=unique_verified,
            expected_total=matched_count if source_complete else None,
        )
        try:
            historical = pe3.P2V3HistoricalReadPayload(
                operation=operation, query_evidence=evidence, page=page,
            )
            historical = pe3.P2V3HistoricalReadPayload.model_validate_json(
                historical.model_dump_json(), strict=True,
            )
            return P2V3PreacceptProjection(historical=historical)
        except Exception as exc:
            raise P2ReadBackendError("invalid_upstream_response") from exc

    @staticmethod
    def _v3_projection_comparison_row(fact: pc3.P2Fact) -> Mapping[str, Any]:
        value = fact.model_dump(mode="json", exclude={"query_evidence_ref"})
        # Activity observation time is capture metadata, not the Activity's
        # source identity. It is refreshed on every continuation capture.
        if value.get("fact_kind") == "activity":
            value["observed_at"] = "<fresh-source-observation>"
        return value

    @staticmethod
    def _v3_empty_table(table: str) -> codec3.SourceTable:
        return codec3.SourceTable(
            table=table, rows=(), pages=(), source_total=0, complete=True,
            range_contiguous=True, unique_items_verified=True,
            source_digest=hashlib.sha256(b"[]").hexdigest(),
        )

    @staticmethod
    def _v3_in_filter(column: str, values: Sequence[uuid.UUID]) -> tuple[str, str]:
        unique = tuple(dict.fromkeys(values))
        if not unique:
            raise P2ReadBackendError("unsupported_scope")
        if any(type(item) is not uuid.UUID for item in unique):
            raise P2ReadBackendError("unsupported_scope")
        return column, "in.(" + ",".join(str(item) for item in unique) + ")"

    async def _v3_execute_sources(
        self,
        request: pc3.P2ReadQueryRequest,
        descriptor: codec3.V3QueryDescriptor,
        verified: v1.VerifiedReadContext,
        binding: codec3.QueryAttemptBinding,
        state: _V3QueryCaptureState,
        *,
        activity_id: uuid.UUID | None,
        ledger_unit_id: uuid.UUID | None,
        scope_kind: str | None,
        scope_ref: str | None,
    ) -> tuple[dict[str, codec3.SourceTable], str]:
        operation = request.operation
        tables: dict[str, codec3.SourceTable] = {}

        async def fetch(
            table: str, filters: Sequence[tuple[str, str]], *, alias: str | None = None,
        ) -> codec3.SourceTable:
            order = sorted(self._V3_ORDERS[table])[0]
            result = await self._v3_fetch_table(
                verified, binding, table, filters, order=order,
                operation=operation, query_state=state,
            )
            tables[alias or table] = result
            state.tables[alias or table] = result
            return result

        if operation is pc3.P2ReadOperation.ACTIVITIES:
            member_filters = [("user_id", f"eq.{verified.principal_user_id}")]
            if activity_id is not None:
                member_filters.append(("activity_id", f"eq.{activity_id}"))
            memberships = await fetch("activity_members", member_filters)
            # PostgREST filters are a query hint, not an authorization proof.
            # Validate the returned membership rows before using any returned
            # activity UUID to issue a second source request. This prevents an
            # upstream that ignores user_id from turning another user's
            # membership row into an activities GET.
            try:
                membership_users = tuple(uuid.UUID(row["user_id"]) for row in memberships.rows)
                activity_ids = tuple(uuid.UUID(row["activity_id"]) for row in memberships.rows)
            except (KeyError, TypeError, ValueError, AttributeError):
                raise P2ReadBackendError("invalid_upstream_response") from None
            if any(user_id != verified.principal_user_id for user_id in membership_users):
                raise P2ReadBackendError("invalid_upstream_response")
            if len(set(activity_ids)) != len(activity_ids):
                raise P2ReadBackendError("invalid_upstream_response")
            if activity_ids:
                filters: list[tuple[str, str]] = [self._v3_in_filter("id", activity_ids)]
                activities = await fetch("activities", filters)
            else:
                activities = self._v3_empty_table("activities")
                tables["activities"] = activities
            return tables, "activities" if activity_ids else "activity_members"

        if activity_id is None or scope_kind is None or scope_ref is None:
            raise P2ReadBackendError("unsupported_scope")
        scope = request.scope
        assert scope is not None
        all_units = tuple(
            uuid.UUID(row["id"]) for row in state.tables.get("ledger_units", self._v3_empty_table("ledger_units")).rows
            if row.get("is_deleted") is False
        )
        # Scope fences loaded the complete active-unit snapshot. Derive only
        # private source IDs here; the model-visible filters remain unchanged.
        selected_units = (ledger_unit_id,) if scope_kind == "ledger_unit" and ledger_unit_id is not None else all_units
        if not selected_units:
            raise P2ReadBackendError("scope_unavailable")
        unit_filter = self._v3_in_filter("ledger_unit_id", selected_units)
        activity_filter = ("activity_id", f"eq.{activity_id}")

        if operation is pc3.P2ReadOperation.EXPENSES:
            criteria = request.criteria
            filters: list[tuple[str, str]] = [unit_filter, ("is_deleted", "eq.false")]
            if descriptor.ui_expense_ids:
                ids = tuple(descriptor.ui_expense_ids)
                expenses = await fetch("expenses", [self._v3_in_filter("id", ids), unit_filter, ("is_deleted", "eq.false")])
                returned = {uuid.UUID(row["id"]) for row in expenses.rows}
                if returned != set(ids) or not expenses.complete:
                    raise P2ReadBackendError("unsupported_scope")
            else:
                expenses = await fetch("expenses", filters)
            expense_ids = tuple(uuid.UUID(row["id"]) for row in expenses.rows)
            if expense_ids:
                payments = await fetch("payments", [self._v3_in_filter("expense_id", expense_ids)])
                splits = await fetch("splits", [self._v3_in_filter("expense_id", expense_ids)])
                # Allocation tails cannot be inferred. If either table is
                # bounded before its total, reject the attempt rather than
                # producing a partly funded ExpenseFact.
                if not payments.complete or not splits.complete:
                    raise P2ReadBackendError("read_limit_exceeded")
            else:
                tables["payments"] = self._v3_empty_table("payments")
                tables["splits"] = self._v3_empty_table("splits")
            return tables, "expenses"

        if operation is pc3.P2ReadOperation.DEBTS:
            debts = await fetch("expense_debts", [activity_filter, unit_filter])
            expense_ids = tuple(dict.fromkeys(uuid.UUID(row["expense_id"]) for row in debts.rows))
            if expense_ids:
                await fetch("expenses", [self._v3_in_filter("id", expense_ids)], alias="expenses")
            else:
                tables["expenses"] = self._v3_empty_table("expenses")
            return tables, "expense_debts"

        if operation is pc3.P2ReadOperation.REFUND_EVENTS:
            expenses = await fetch("expenses", [unit_filter, ("is_deleted", "eq.false")])
            parent_ids: tuple[uuid.UUID, ...] = tuple(dict.fromkeys(
                uuid.UUID(row["original_expense_id"])
                for row in expenses.rows if row.get("original_expense_id") is not None
            ))
            # The parent query is only for explicit public original_expense_id
            # links. The private refund marker/table is never requested.
            if parent_ids:
                await fetch("expenses", [self._v3_in_filter("id", parent_ids)], alias="refund_parents")
            return tables, "expenses"

        if operation is pc3.P2ReadOperation.PREPAYMENT_ACCOUNTS:
            await fetch("prepayment_accounts", [activity_filter])
            return tables, "prepayment_accounts"

        if operation is pc3.P2ReadOperation.PREPAYMENT_USAGES:
            criteria = request.criteria
            debt_filters: list[tuple[str, str]] = [activity_filter, unit_filter]
            if criteria.expense_ref is not None:
                expense_id = self._v3_locator_port.resolve_entity(
                    str(criteria.expense_ref), "expense", activity_id=activity_id,
                )
                debt_filters.append(("expense_id", f"eq.{expense_id}"))
            debts = await fetch("expense_debts", debt_filters)
            debt_ids = tuple(dict.fromkeys(uuid.UUID(row["id"]) for row in debts.rows))
            if not debt_ids:
                tables["prepayment_usages"] = self._v3_empty_table("prepayment_usages")
                return tables, "expense_debts"
            usages = await fetch("prepayment_usages", [activity_filter, self._v3_in_filter("expense_debt_id", debt_ids)])
            if not usages.rows:
                return tables, "prepayment_usages"
            account_ids = tuple(dict.fromkeys(uuid.UUID(row["account_id"]) for row in usages.rows))
            expense_ids = tuple(dict.fromkeys(uuid.UUID(row["expense_id"]) for row in debts.rows if uuid.UUID(row["id"]) in set(debt_ids)))
            await fetch("prepayment_accounts", [self._v3_in_filter("id", account_ids), activity_filter])
            if expense_ids:
                await fetch("expenses", [self._v3_in_filter("id", expense_ids)])
            return tables, "prepayment_usages"

        if operation is pc3.P2ReadOperation.PREPAYMENT_RETURN_EVENTS:
            transfers = await fetch("transfers", [activity_filter, ("type", "eq.prepayment_return"), ("is_voided", "eq.false")])
            transfer_ids = tuple(dict.fromkeys(uuid.UUID(row["id"]) for row in transfers.rows))
            if transfer_ids:
                await fetch("transfer_components", [activity_filter, self._v3_in_filter("transfer_id", transfer_ids)])
            return tables, "transfers"

        raise P2ReadBackendError("unsupported_read")

    async def resolve_candidate_scope(
        self,
        verified: v1.VerifiedReadContext,
        request: v1.ScopeRequest,
        *,
        ui_ledger_unit_id_hint: uuid.UUID | None = None,
    ) -> CandidateResolvedScope:
        """Recheck untrusted UI scope hints and mint random P2-only refs."""
        self._require_v2_state()
        self._validate_grant(
            verified, owner_user_id=self._turn_state.owner_user_id,
            turn_id=self._turn_state.turn_id,
        )
        self._turn_state.verify_turn(verified)
        if request.mode == "none":
            if ui_ledger_unit_id_hint is not None:
                raise P2ReadBackendError("unsupported_scope")
            return CandidateResolvedScope(None, None, {}, {})
        if request.mode != "activity" or not isinstance(request.ui_activity_id_hint, uuid.UUID):
            raise P2ReadBackendError("unsupported_scope")
        async with self._turn_state.backend_operation():
            resolved = await super().resolve_scope(verified, request)
        if resolved.activity is None:
            raise P2ReadBackendError("scope_unavailable")
        activity_id = resolved.activity.activity_id
        activity_ref = self._turn_state.bind_entity("activity", activity_id, activity_id=activity_id)
        participants: dict[uuid.UUID, str] = {}
        for participant in resolved.participants:
            if participant.activity_id != activity_id or participant.is_deleted:
                continue
            participants[participant.participant_id] = self._turn_state.bind_entity(
                "participant", participant.participant_id, activity_id=activity_id,
            )
        units: dict[uuid.UUID, str] = {}
        for unit in resolved.ledger_units:
            if unit.activity_id != activity_id or unit.is_deleted:
                continue
            units[unit.ledger_unit_id] = self._turn_state.bind_entity(
                "ledger_unit", unit.ledger_unit_id, activity_id=activity_id,
                ledger_unit_id=unit.ledger_unit_id,
            )
        if ui_ledger_unit_id_hint is None:
            public = pc.P2Scope(
                scope_kind="activity", scope_ref=activity_ref,
                activity_ref=activity_ref, ledger_unit_ref=None,
            )
        else:
            unit = next((item for item in resolved.ledger_units if item.ledger_unit_id == ui_ledger_unit_id_hint), None)
            child = next((item for item in resolved.child_scopes if item.ledger_unit_id == ui_ledger_unit_id_hint), None)
            if (
                unit is None or unit.activity_id != activity_id or unit.is_deleted
                or unit.unit_type != "sub_activity" or child is None
            ):
                raise P2ReadBackendError("unsupported_scope")
            unit_ref = units.get(unit.ledger_unit_id)
            if unit_ref is None:
                raise P2ReadBackendError("unsupported_scope")
            public = pc.P2Scope(
                scope_kind="ledger_unit", scope_ref=unit_ref,
                activity_ref=activity_ref, ledger_unit_ref=unit_ref,
            )
        return CandidateResolvedScope(public, resolved, participants, units)

    async def issue_source_authorization_grant(
        self,
        verified: v1.VerifiedReadContext,
        *,
        operation: Any,
        criteria: Any,
        scope: Any | None,
    ) -> Any:
        """Issue a one-use server-side source grant after fresh JWT scope checks."""
        self._require_v2_state()
        async with self._turn_state.backend_operation():
            return await self._issue_source_authorization_grant_inner(
                verified, operation=operation, criteria=criteria, scope=scope,
            )

    async def _issue_source_authorization_grant_inner(
        self, verified: v1.VerifiedReadContext, *, operation: Any,
        criteria: Any, scope: Any | None,
    ) -> Any:
        self._validate_grant(
            verified, owner_user_id=self._turn_state.owner_user_id,
            turn_id=self._turn_state.turn_id,
        )
        self._turn_state.verify_turn(verified)
        expected_criteria = _criteria_type_for_operation(operation)
        if not isinstance(criteria, expected_criteria):
            raise P2ReadBackendError("unsupported_read")
        if operation == pc.P2ReadOperation.ACTIVITIES:
            if scope is not None and not isinstance(scope, pc.P2Scope):
                raise P2ReadBackendError("unsupported_scope")
        elif not isinstance(scope, pc.P2Scope):
            raise P2ReadBackendError("unsupported_scope")
        criteria_sha = _criteria_sha(criteria)
        scope_sha, private_scope = await self._authorize_scope(
            verified, operation=operation, criteria=criteria, scope=scope,
        )
        expires_at = min(
            verified.expires_at.astimezone(timezone.utc),
            datetime.now(timezone.utc) + timedelta(seconds=30),
            datetime.now(timezone.utc) + timedelta(
                seconds=max(0.0, self._turn_state.turn_deadline_monotonic - self._turn_state._clock()),
            ),
        )
        if expires_at <= datetime.now(timezone.utc):
            raise P2ReadBackendError("invalid_auth_context")
        principal_ref = self._turn_state.bind_entity("principal", verified.principal_user_id)
        grant_ref = _random_ref()
        grant = pc.P2SourceAuthorizationGrant(
            principal_ref=principal_ref,
            owner_turn_ref=self._turn_state.owner_turn_ref,
            generation=self._turn_state.generation,
            source_input_seq=self._turn_state.source_input_seq,
            input_digest=self._turn_state.input_digest,
            operation=operation, scope=scope,
            criteria_digest=criteria_sha, expires_at=expires_at, grant_ref=grant_ref,
        )
        self._turn_state.register_grant(CandidateGrantBinding(
            grant_ref=grant_ref, operation=str(operation), criteria_sha256=criteria_sha,
            scope_sha256=scope_sha, owner_user_id=verified.owner_user_id,
            turn_id=verified.turn_id, owner_turn_ref=self._turn_state.owner_turn_ref,
            generation=self._turn_state.generation,
            context_revision=self._turn_state.context_revision,
            claim_id=self._turn_state.claim_id,
            source_input_seq=self._turn_state.source_input_seq,
            input_digest=self._turn_state.input_digest,
            scope=scope, resolved_scope=private_scope, expires_at=expires_at,
        ))
        return grant

    async def _authorize_scope(
        self, verified: v1.VerifiedReadContext, *, operation: Any,
        criteria: Any, scope: Any | None,
    ) -> tuple[str, v1.P2ResolvedScope | None]:
        if scope is None:
            if operation != pc.P2ReadOperation.ACTIVITIES:
                raise P2ReadBackendError("unsupported_scope")
            return _canonical_sha({"scope": None}), None
        if not isinstance(scope, pc.P2Scope):
            raise P2ReadBackendError("unsupported_scope")
        activity_binding = self._turn_state.resolve_entity(scope.activity_ref, "activity")
        activity_id = activity_binding.entity_id
        if activity_binding.activity_id != activity_id:
            raise P2ReadBackendError("unsupported_scope")
        private = await super().resolve_scope(
            verified, v1.ScopeRequest(mode="activity", ui_activity_id_hint=activity_id),
        )
        if private.activity is None or private.activity.activity_id != activity_id:
            raise P2ReadBackendError("scope_unavailable")
        if scope.scope_kind == "activity":
            if scope.scope_ref != scope.activity_ref or scope.ledger_unit_ref is not None:
                raise P2ReadBackendError("unsupported_scope")
            private_ids: Mapping[str, Any] = {
                "activity_id": str(activity_id),
                "participants": tuple(sorted(str(item.participant_id) for item in private.participants if not item.is_deleted)),
                "units": tuple(sorted(str(item.ledger_unit_id) for item in private.ledger_units if not item.is_deleted)),
                "children": tuple(sorted(
                    (str(item.ledger_unit_id), item.configured, tuple(str(pid) for pid in item.participant_ids))
                    for item in private.child_scopes
                )),
                "financial_version": private.activity.financial_version,
            }
        else:
            unit_binding = self._turn_state.resolve_entity(
                scope.ledger_unit_ref or "", "ledger_unit", activity_id=activity_id,
            )
            if scope.scope_ref != scope.ledger_unit_ref:
                raise P2ReadBackendError("unsupported_scope")
            unit = next((item for item in private.ledger_units if item.ledger_unit_id == unit_binding.entity_id), None)
            child = next((item for item in private.child_scopes if item.ledger_unit_id == unit_binding.entity_id), None)
            if unit is None or unit.is_deleted or unit.unit_type != "sub_activity" or child is None:
                raise P2ReadBackendError("unsupported_scope")
            private_ids = {
                "activity_id": str(activity_id), "ledger_unit_id": str(unit.ledger_unit_id),
                "configured": child.configured,
                "participants": tuple(sorted(str(pid) for pid in child.participant_ids)),
                "financial_version": private.activity.financial_version,
            }
        criteria_ids: dict[str, str] = {}
        for field_name, kind in (("participant_ref", "participant"), ("expense_ref", "expense")):
            ref = getattr(criteria, field_name, None)
            if ref is not None:
                bound = self._turn_state.resolve_entity(ref, kind, activity_id=activity_id)
                if kind == "participant":
                    active_ids = {
                        item.participant_id for item in private.participants if not item.is_deleted
                    }
                    if bound.entity_id not in active_ids:
                        raise P2ReadBackendError("unsupported_scope")
                    if scope.scope_kind == "ledger_unit":
                        child = next(
                            (item for item in private.child_scopes
                             if item.ledger_unit_id == self._turn_state.resolve_entity(
                                 scope.ledger_unit_ref or "", "ledger_unit", activity_id=activity_id,
                             ).entity_id),
                            None,
                        )
                        if child is None or child.configured and bound.entity_id not in child.participant_ids:
                            raise P2ReadBackendError("unsupported_scope")
                else:
                    # An Activity-bound expense ref is not enough to authorize
                    # a child-scoped query. Re-resolve its ledger-unit binding
                    # against the current scope before using it as a filter.
                    if bound.ledger_unit_id is None:
                        raise P2ReadBackendError("unsupported_scope")
                    active_units = {
                        item.ledger_unit_id for item in private.ledger_units
                        if item.activity_id == activity_id and not item.is_deleted
                    }
                    if bound.ledger_unit_id not in active_units:
                        raise P2ReadBackendError("unsupported_scope")
                    if scope.scope_kind == "ledger_unit":
                        selected_unit = self._turn_state.resolve_entity(
                            scope.ledger_unit_ref or "", "ledger_unit", activity_id=activity_id,
                        ).entity_id
                        if bound.ledger_unit_id != selected_unit:
                            raise P2ReadBackendError("unsupported_scope")
                criteria_ids[field_name] = str(bound.entity_id)
        return _canonical_sha({"public_scope": scope.model_dump(mode="json"), "private_scope": private_ids, "criteria_bindings": criteria_ids}), private

    async def read_table_plan(self, verified: v1.VerifiedReadContext, **kwargs: Any) -> CandidateTableResult:
        """Run source retrieval, parsing, joins/projection, and receipt hashing
        under the same cumulative per-Turn backend-time budget.
        """
        self._require_v2_state()
        async with self._turn_state.backend_operation():
            return await self._read_table_plan_inner(verified, **kwargs)

    async def read_candidate(
        self, request: Any, verified: v1.VerifiedReadContext, grant: Any,
    ) -> Any:
        """Execute one strict P2 read request and expose at most 16 typed facts.

        The adapter is intentionally not wired into application composition.
        Runtime code must create and retain ``P2ReadTurnState`` for the accepted
        Turn, mint a verified grant, and validate the typed result separately.
        """
        self._require_v2_state()
        if not isinstance(request, (pc.P2ReadQueryRequest, pc.P2ReadContinueRequest)):
            raise P2ReadBackendError("unsupported_read")
        if not isinstance(grant, pc.P2SourceAuthorizationGrant):
            raise P2ReadBackendError("invalid_auth_context")
        result: pc.P2ReadBackendResult | None = None
        try:
            async with self._turn_state.backend_operation():
                self._validate_grant(
                    verified, owner_user_id=self._turn_state.owner_user_id,
                    turn_id=self._turn_state.turn_id,
                )
                self._turn_state.verify_turn(verified)
                if request.profile_id != PROFILE_ID or request.versions != pc.P2_VERSIONS:
                    raise P2ReadBackendError("unsupported_read")
                if isinstance(request, pc.P2ReadContinueRequest):
                    result = await self._continue_candidate(request, verified, grant)
                else:
                    result = await self._read_candidate_query(request, verified, grant)
                return result
        except BaseException:
            # The final context-manager fence runs after projection and after a
            # normal return expression. If it rejects that result, make its
            # query stale; consumed continuation nonces are never restored.
            if isinstance(request, pc.P2ReadContinueRequest):
                self._turn_state.fail_continuation(request.query_ref)
            elif result is not None:
                self._turn_state.mark_query_stale(result.query_evidence.query_ref)
            raise

    async def _read_candidate_query(
        self, request: pc.P2ReadQueryRequest, verified: v1.VerifiedReadContext,
        public_grant: pc.P2SourceAuthorizationGrant,
    ) -> pc.P2ReadBackendResult:
        criteria = request.criteria
        operation = request.operation
        if not isinstance(criteria, _criteria_type_for_operation(operation)):
            raise P2ReadBackendError("unsupported_read")
        criteria_sha = _criteria_sha(criteria)
        if public_grant.operation != operation or public_grant.criteria_digest != criteria_sha:
            raise P2ReadBackendError("invalid_auth_context")
        if public_grant.scope != request.scope:
            raise P2ReadBackendError("unsupported_scope")
        private_grant = self._turn_state.consume_grant(public_grant.grant_ref)
        self._validate_public_grant_binding(private_grant, public_grant, verified)
        if private_grant.operation != str(operation) or private_grant.criteria_sha256 != criteria_sha:
            raise P2ReadBackendError("invalid_auth_context")
        if private_grant.scope != request.scope:
            raise P2ReadBackendError("unsupported_scope")

        # The single-use source grant already performed a fresh current-user
        # scope resolution. Reuse that private snapshot as the beginning fence;
        # the query still re-resolves scope and financial_version after its GETs.
        # This avoids a redundant full resolver pass while keeping source scope,
        # FV and the current JWT fenced across the actual read.
        scope_sha = private_grant.scope_sha256
        private_scope = private_grant.resolved_scope
        if scope_sha != private_grant.scope_sha256:
            raise P2ReadBackendError("data_changed_during_read")
        if operation != pc.P2ReadOperation.ACTIVITIES and private_scope is None:
            raise P2ReadBackendError("unsupported_scope")
        if private_scope is not None and private_scope.activity is not None:
            activity_id = private_scope.activity.activity_id
            start_versions = {activity_id: private_scope.activity.financial_version}
        else:
            activity_id = None
            start_versions = {}

        envelope_sha = _canonical_sha(request.model_dump(mode="json", exclude_none=False))
        query_ref = _random_ref()
        evidence_ref = _random_ref("qev_")
        result_ref = _random_ref()
        criteria_ref = self._turn_state.bind_entity(
            "criteria", uuid.uuid5(self._turn_state.turn_id, criteria_sha),
            activity_id=activity_id,
        )
        query_sha, facts, source_results, primary_total, returned_count = await self._execute_query_sources(
            request, verified, private_scope, criteria_sha, scope_sha, envelope_sha,
            start_versions, evidence_ref,
        )

        # Scope and financial-version fences surround every financial read. The
        # Activity list is an observed point-in-time listing and carries its
        # source financial versions without claiming a financial transaction.
        if activity_id is not None:
            end_scope_sha, end_scope = await self._authorize_scope(
                verified, operation=operation, criteria=criteria, scope=request.scope,
            )
            if end_scope_sha != scope_sha or end_scope is None or end_scope.activity is None:
                raise P2ReadBackendError("data_changed_during_read")
            if end_scope.activity.financial_version != start_versions[activity_id]:
                raise P2ReadBackendError("data_changed_during_read")
            end_versions = {activity_id: end_scope.activity.financial_version}
        else:
            end_versions = {}
        facts = tuple(facts)
        if len(facts) > MAX_ROWS_PER_QUERY:
            raise P2ReadBackendError("read_limit_exceeded")
        all_fact_refs = tuple(_fact_opaque_ref(item) for item in facts)
        raw_digests = tuple(
            receipt.raw_body_sha256 for source in source_results for receipt in source.receipts
        )
        receipt_hashes = tuple(
            receipt.receipt_sha256 for source in source_results for receipt in source.receipts
        )
        query_digest = _chain_hash(tuple(source.evidence.query_sha256 for source in source_results))
        body_digest = _chain_hash(raw_digests)
        projection_digest = _canonical_sha(tuple(item.model_dump(mode="json") for item in facts))
        normalized_digest = _chain_hash(tuple(source.evidence.normalized_source_sha256 for source in source_results))
        qev = _random_ref("qev_")
        # Use the evidence ref minted before mapping so every typed fact is
        # already bound to the stable query evidence identifier.
        if evidence_ref != qev:
            qev = evidence_ref
        has_more = len(facts) > MAX_ROWS_PER_PAGE
        next_ref = _random_ref() if has_more else None
        source_pages = max(1, sum(len(source.receipts) for source in source_results))
        source_complete = all(source.evidence.completeness == "complete" for source in source_results)
        if not source_results:
            source_complete = True
        observed_at = max(
            (receipt.observed_at for source in source_results for receipt in source.receipts),
            default=datetime.now(timezone.utc),
        )
        expected_total = len(facts) if source_complete else None
        summary = pc.P2PageSummary(
            pages_seen=source_pages, has_more=has_more, truncated=has_more,
            source_query_complete=source_complete,
            model_projection_complete=not has_more,
            range_contiguous=source_complete,
            stable_total_verified=source_complete,
            source_version_fenced=activity_id is None or start_versions == end_versions,
            unique_items_verified=True, expected_total=expected_total,
        )
        evidence = pc.P2QueryEvidence(
            profile_id=PROFILE_ID, versions=pc.P2_VERSIONS,
            query_evidence_ref=qev, query_ref=query_ref, result_ref=result_ref,
            operation=operation, criteria_ref=criteria_ref,
            criteria_digest=criteria_sha, normalized_criteria_digest=_criteria_sha(criteria),
            backend_criteria_stage="scope_only",
            source_kind=operation.value.removeprefix("read."),
            source_ref=_random_ref(),
            source_version=(
                "activity-list-snapshot" if activity_id is None
                else "financial-version:" + str(start_versions[activity_id])
            ),
            observed_at=observed_at, simulation=False,
            returned_count=returned_count, matched_count=len(facts),
            source_total=primary_total, matched_total=len(facts),
            page_count=source_pages,
            query_zero_classification=(
                "backend_zero" if primary_total == 0 and len(facts) == 0
                else "post_filter_zero" if len(facts) == 0 and returned_count > 0
                else "nonzero" if facts else "unknown_or_partial"
            ),
            source_query_complete=source_complete,
            model_projection_complete=not has_more,
            matching_fact_refs=all_fact_refs,
            financial_versions=tuple(
                pc.P2FinancialVersion(
                    activity_ref=self._turn_state.bind_entity("activity", aid, activity_id=aid),
                    financial_version=version,
                ) for aid, version in sorted(start_versions.items(), key=lambda p: str(p[0]))
            ),
            page=summary, query_digest=query_digest,
            body_digest=body_digest, projection_digest=projection_digest,
        )
        facts = tuple(item.model_copy(update={"query_evidence_ref": qev}) for item in facts)
        state = CandidateQueryState(
            query_ref=query_ref, next_page_ref=next_ref, operation=operation,
            criteria=criteria, scope=request.scope, facts=facts, evidence=evidence,
            owner_user_id=verified.owner_user_id, turn_id=verified.turn_id,
            generation=self._turn_state.generation,
            context_revision=self._turn_state.context_revision,
            claim_id=self._turn_state.claim_id,
            source_input_seq=self._turn_state.source_input_seq,
            input_digest=self._turn_state.input_digest,
            owner_turn_ref=self._turn_state.owner_turn_ref,
            scope_sha256=scope_sha,
            criteria_sha256=criteria_sha,
            financial_versions=tuple(sorted(start_versions.items(), key=lambda p: str(p[0]))),
            receipts=tuple(receipt for source in source_results for receipt in source.receipts),
        )
        self._turn_state.store_query(state)
        return self._result_for_page(state, 0)

    async def _continue_candidate(
        self, request: pc.P2ReadContinueRequest, verified: v1.VerifiedReadContext,
        public_grant: pc.P2SourceAuthorizationGrant,
    ) -> pc.P2ReadBackendResult:
        query = self._turn_state.get_query(request.query_ref)
        grant = self._turn_state.get_grant(public_grant.grant_ref)
        self._validate_public_grant_binding(grant, public_grant, verified)
        if (
            query.query_ref != request.query_ref
            or query.owner_user_id != verified.owner_user_id
            or query.turn_id != verified.turn_id
            or query.generation != self._turn_state.generation
            or query.context_revision != self._turn_state.context_revision
            or query.claim_id != self._turn_state.claim_id
            or query.owner_turn_ref != self._turn_state.owner_turn_ref
            or query.source_input_seq != self._turn_state.source_input_seq
            or query.input_digest != self._turn_state.input_digest
            or query.next_page_ref != request.next_page_ref
            or query.next_page_ref in query.continuation_used
            or query.operation != grant.operation
            or query.criteria_sha256 != grant.criteria_sha256
            or query.scope != grant.scope
            or not grant.consumed
        ):
            raise P2ReadBackendError("unsupported_scope")
        query.continuation_used.add(request.next_page_ref)
        fresh_scope: v1.P2ResolvedScope | None = None
        if query.scope is not None:
            try:
                scope_sha, fresh = await self._authorize_scope(
                    verified, operation=query.operation,
                    criteria=query.criteria, scope=query.scope,
                )
            except BaseException:
                # A consumed continuation cannot leave the old result marked
                # current when fresh scope/member authorization fails.
                query.current = False
                raise
            if scope_sha != query.scope_sha256 or fresh is None or fresh.activity is None:
                query.current = False
                raise P2ReadBackendError("data_changed_during_read")
            expected = dict(query.financial_versions)
            if expected != {fresh.activity.activity_id: fresh.activity.financial_version}:
                query.current = False
                raise P2ReadBackendError("data_changed_during_read")
            fresh_scope = fresh
            start_versions = {fresh.activity.activity_id: fresh.activity.financial_version}
        else:
            if query.operation != pc.P2ReadOperation.ACTIVITIES:
                query.current = False
                raise P2ReadBackendError("unsupported_scope")
            start_versions = {}

        # A continuation is a fresh source read from offset zero under the
        # current request credential. Old facts and hashes never restore rows
        # that current RLS no longer returns.
        reread = pc.P2ReadQueryRequest(
            kind="read", message_type="query_request", profile_id=PROFILE_ID,
            versions=pc.P2_VERSIONS, operation=query.operation,
            criteria=query.criteria, scope=query.scope,
        )
        envelope_sha = _canonical_sha(reread.model_dump(mode="json", exclude_none=False))
        new_qev_ref = _random_ref("qev_")
        try:
            _, fresh_facts, source_results, primary_total, returned_count = await self._execute_query_sources(
                reread, verified, fresh_scope, query.criteria_sha256,
                query.scope_sha256, envelope_sha, start_versions, new_qev_ref,
            )
            if query.scope is not None:
                end_scope_sha, end_scope = await self._authorize_scope(
                    verified, operation=query.operation,
                    criteria=query.criteria, scope=query.scope,
                )
                if (
                    end_scope_sha != query.scope_sha256 or end_scope is None
                    or end_scope.activity is None
                    or end_scope.activity.financial_version != start_versions.get(end_scope.activity.activity_id)
                ):
                    raise P2ReadBackendError("data_changed_during_read")
        except BaseException:
            # The supplied continuation ref is already consumed, so callers
            # cannot retry an ambiguous or failed source read with cached facts.
            query.current = False
            raise

        old_source_bindings = tuple(_receipt_source_binding(item) for item in query.receipts)
        new_source_bindings = tuple(
            _receipt_source_binding(item)
            for source in source_results for item in source.receipts
        )
        if old_source_bindings != new_source_bindings:
            query.current = False
            raise P2ReadBackendError("data_changed_during_read")
        if len(fresh_facts) > MAX_ROWS_PER_QUERY:
            query.current = False
            raise P2ReadBackendError("read_limit_exceeded")

        fresh_facts = tuple(
            item.model_copy(update={"query_evidence_ref": new_qev_ref})
            for item in fresh_facts
        )
        source_pages = max(1, sum(len(source.receipts) for source in source_results))
        source_complete = all(source.evidence.completeness == "complete" for source in source_results)
        if not source_results:
            source_complete = True
        has_model_more = len(fresh_facts) > MAX_ROWS_PER_PAGE
        observed_at = max(
            (receipt.observed_at for source in source_results for receipt in source.receipts),
            default=datetime.now(timezone.utc),
        )
        summary = pc.P2PageSummary(
            pages_seen=source_pages, has_more=has_model_more,
            truncated=has_model_more, source_query_complete=source_complete,
            model_projection_complete=not has_model_more,
            range_contiguous=source_complete, stable_total_verified=source_complete,
            source_version_fenced=(query.scope is None or start_versions == dict(query.financial_versions)),
            unique_items_verified=True,
            expected_total=len(fresh_facts) if source_complete else None,
        )
        query.evidence = query.evidence.model_copy(update={
            "query_evidence_ref": new_qev_ref,
            "result_ref": _random_ref(), "source_ref": _random_ref(),
            "source_version": (
                "activity-list-snapshot" if not start_versions
                else "financial-version:" + str(next(iter(start_versions.values())))
            ),
            "observed_at": observed_at, "returned_count": returned_count,
            "matched_count": len(fresh_facts), "source_total": primary_total,
            "matched_total": len(fresh_facts), "page_count": source_pages,
            "query_zero_classification": (
                "backend_zero" if primary_total == 0 and not fresh_facts
                else "post_filter_zero" if not fresh_facts and returned_count > 0
                else "nonzero" if fresh_facts else "unknown_or_partial"
            ),
            "source_query_complete": source_complete,
            "model_projection_complete": not has_model_more,
            "matching_fact_refs": tuple(_fact_opaque_ref(item) for item in fresh_facts),
            "financial_versions": tuple(
                pc.P2FinancialVersion(
                    activity_ref=self._turn_state.bind_entity("activity", activity_id, activity_id=activity_id),
                    financial_version=version,
                ) for activity_id, version in sorted(start_versions.items(), key=lambda pair: str(pair[0]))
            ),
            "page": summary,
            "query_digest": _chain_hash(tuple(source.evidence.query_sha256 for source in source_results)),
            "body_digest": _chain_hash(tuple(
                receipt.raw_body_sha256
                for source in source_results for receipt in source.receipts
            )),
            "projection_digest": _canonical_sha(tuple(
                item.model_dump(mode="json") for item in fresh_facts
            )),
        })
        query.facts = fresh_facts
        query.receipts = tuple(receipt for source in source_results for receipt in source.receipts)
        query.financial_versions = tuple(sorted(start_versions.items(), key=lambda pair: str(pair[0])))

        start = (query.page_index + 1) * MAX_ROWS_PER_PAGE
        if start >= len(query.facts):
            query.current = False
            raise P2ReadBackendError("unsupported_scope")
        query.page_index += 1
        if start + MAX_ROWS_PER_PAGE >= len(query.facts):
            query.next_page_ref = None
        else:
            query.next_page_ref = _random_ref()
        return self._result_for_page(query, query.page_index)

    def _result_for_page(self, query: CandidateQueryState, page_index: int) -> pc.P2ReadBackendResult:
        start = page_index * MAX_ROWS_PER_PAGE
        stop = min(start + MAX_ROWS_PER_PAGE, len(query.facts))
        has_more = stop < len(query.facts)
        next_ref = query.next_page_ref if has_more else None
        page_evidence_ref = _random_ref("qev_")
        page_facts = tuple(
            item.model_copy(update={"query_evidence_ref": page_evidence_ref})
            for item in query.facts[start:stop]
        )
        # The evidence is query-level and source-complete even if only one model
        # page is projected. The page DTO explicitly distinguishes the two.
        evidence = query.evidence.model_copy(update={
            "query_evidence_ref": page_evidence_ref,
            "result_ref": _random_ref(),
            "model_projection_complete": not has_more,
            "projection_digest": _canonical_sha(tuple(
                item.model_copy(update={"query_evidence_ref": page_evidence_ref}).model_dump(mode="json")
                for item in query.facts
            )),
            "page": query.evidence.page.model_copy(update={
                "has_more": has_more,
                "truncated": has_more,
                "model_projection_complete": not has_more,
            }),
        })
        page = pc.P2PageProjection[
            pc.P2Fact
        ](
            items=page_facts,
            completeness=(pc.ReadCompleteness.PARTIAL if has_more else pc.ReadCompleteness.COMPLETE),
            has_more=has_more, next_page_ref=next_ref, page_index=page_index,
            range_contiguous=evidence.page.range_contiguous,
            stable_total_verified=evidence.page.stable_total_verified,
            source_version_fenced=evidence.page.source_version_fenced,
            unique_items_verified=evidence.page.unique_items_verified,
            expected_total=evidence.page.expected_total,
        )
        return pc.P2ReadBackendResult(operation=query.operation, query_evidence=evidence, page=page)

    def _validate_public_grant_binding(
        self, private: CandidateGrantBinding,
        public: pc.P2SourceAuthorizationGrant, verified: v1.VerifiedReadContext,
    ) -> None:
        principal = self._turn_state.resolve_entity(public.principal_ref, "principal")
        if (
            principal.entity_id != verified.principal_user_id
            or private.grant_ref != public.grant_ref
            or private.operation != public.operation.value
            or private.criteria_sha256 != public.criteria_digest
            or private.scope != public.scope
            or private.owner_user_id != verified.owner_user_id
            or private.turn_id != verified.turn_id
            or private.generation != self._turn_state.generation
            or private.context_revision != self._turn_state.context_revision
            or private.claim_id != self._turn_state.claim_id
            or private.owner_turn_ref != self._turn_state.owner_turn_ref
            or private.source_input_seq != self._turn_state.source_input_seq
            or private.input_digest != self._turn_state.input_digest
            or public.owner_turn_ref != self._turn_state.owner_turn_ref
            or public.generation != self._turn_state.generation
            or public.source_input_seq != self._turn_state.source_input_seq
            or public.input_digest != self._turn_state.input_digest
            or public.expires_at <= datetime.now(timezone.utc)
        ):
            raise P2ReadBackendError("invalid_auth_context")

    async def _execute_query_sources(
        self, request: pc.P2ReadQueryRequest, verified: v1.VerifiedReadContext,
        scope: v1.P2ResolvedScope | None, criteria_sha: str, scope_sha: str,
        envelope_sha: str, financial_versions: Mapping[uuid.UUID, int],
        query_evidence_ref: str,
    ) -> tuple[str, list[Any], list[CandidateTableResult], int, int]:
        operation = request.operation
        criteria = request.criteria
        if operation == pc.P2ReadOperation.ACTIVITIES:
            return await self._read_activities_candidate(
                request, verified, scope, criteria_sha, scope_sha, envelope_sha,
                financial_versions, query_evidence_ref,
            )
        if scope is None or scope.activity is None:
            raise P2ReadBackendError("unsupported_scope")
        if operation == pc.P2ReadOperation.EXPENSES:
            return await self._read_expenses_candidate(
                request, verified, scope, criteria_sha, scope_sha, envelope_sha,
                financial_versions, query_evidence_ref,
            )
        if operation == pc.P2ReadOperation.DEBTS:
            return await self._read_debts_candidate(
                request, verified, scope, criteria_sha, scope_sha, envelope_sha,
                financial_versions, query_evidence_ref,
            )
        if operation == pc.P2ReadOperation.REFUND_EVENTS:
            return await self._read_refunds_candidate(
                request, verified, scope, criteria_sha, scope_sha, envelope_sha,
                financial_versions, query_evidence_ref,
            )
        if operation == pc.P2ReadOperation.PREPAYMENT_ACCOUNTS:
            return await self._read_prepayment_accounts_candidate(
                request, verified, scope, criteria_sha, scope_sha, envelope_sha,
                financial_versions, query_evidence_ref,
            )
        if operation == pc.P2ReadOperation.PREPAYMENT_USAGES:
            return await self._read_prepayment_usages_candidate(
                request, verified, scope, criteria_sha, scope_sha, envelope_sha,
                financial_versions, query_evidence_ref,
            )
        if operation == pc.P2ReadOperation.PREPAYMENT_RETURN_EVENTS:
            return await self._read_prepayment_returns_candidate(
                request, verified, scope, criteria_sha, scope_sha, envelope_sha,
                financial_versions, query_evidence_ref,
            )
        raise P2ReadBackendError("unsupported_read")

    async def _fetch_candidate_table(
        self, *, operation: Any, table: str, select: str,
        identity_fields: tuple[str, ...], filters: Sequence[tuple[str, str]],
        scope: v1.P2ResolvedScope | None, verified: v1.VerifiedReadContext,
        criteria: Any, criteria_sha: str, scope_sha: str, envelope_sha: str,
        financial_versions: Mapping[uuid.UUID, int], budget: v1._ReadBudget,
        order: str,
    ) -> CandidateTableResult:
        columns = tuple(select.split(","))
        if not columns or any(not re.fullmatch(r"[a-z][a-z0-9_]*", c) for c in columns):
            raise P2ReadBackendError("unsupported_read")
        fixed_filters = tuple(filters)

        def parse_row(row: Mapping[str, Any]) -> Mapping[str, Any]:
            if set(row) != set(columns):
                raise P2ReadBackendError("invalid_upstream_response")
            if any(isinstance(value, (dict, list)) for value in row.values()):
                raise P2ReadBackendError("invalid_upstream_response")
            return dict(row)

        plan = CandidateTablePlan(
            table=table, select=select, order=order, identity_fields=identity_fields,
            filters=lambda _criteria, _scope: fixed_filters,
            parse_source_row=parse_row,
            project_row=lambda row, _scope: dict(row),
            source_kind=operation.value.removeprefix("read."),
        )
        return await self.read_table_plan(
            verified, operation=operation.value, criteria=criteria, scope=scope,
            criteria_sha256=criteria_sha, scope_sha256=scope_sha,
            envelope_sha256=envelope_sha, financial_versions=financial_versions,
            plan=plan, budget=budget,
        )

    async def _read_activities_candidate(
        self, request: pc.P2ReadQueryRequest, verified: v1.VerifiedReadContext,
        scope: v1.P2ResolvedScope | None, criteria_sha: str, scope_sha: str,
        envelope_sha: str, financial_versions: Mapping[uuid.UUID, int],
        qev_ref: str,
    ) -> tuple[str, list[Any], list[CandidateTableResult], int, int]:
        criteria = request.criteria
        filters: list[tuple[str, str]] = [("is_deleted", "eq.false")]
        if scope is not None and scope.activity is not None:
            filters.append(("id", f"eq.{scope.activity.activity_id}"))
        budget = v1._ReadBudget()
        source = await self._fetch_candidate_table(
            operation=request.operation, table="activities", select=v1._ACTIVITY_SELECT,
            identity_fields=("id",), filters=filters, scope=scope, verified=verified,
            criteria=criteria, criteria_sha=criteria_sha, scope_sha=scope_sha,
            envelope_sha=envelope_sha, financial_versions=financial_versions,
            budget=budget, order="id.asc",
        )
        all_facts: list[Any] = []
        selected_activities: list[v1.P2ActivityDTO] = []
        for row in source.rows:
            activity = v1._activity_dto(row)
            status = "archived" if activity.archived_at is not None else "active"
            if criteria.status != "any" and criteria.status != status:
                continue
            if criteria.name_contains is not None and criteria.name_contains.casefold() not in activity.name.casefold():
                continue
            selected_activities.append(activity)
        # RLS list results are supplemented by one bounded explicit membership
        # query for the selected page, rather than one request per Activity.
        await self._require_memberships(
            tuple(activity.activity_id for activity in selected_activities), verified, budget,
        )
        for activity in selected_activities:
            status = "archived" if activity.archived_at is not None else "active"
            activity_ref = self._turn_state.bind_entity(
                "activity", activity.activity_id, activity_id=activity.activity_id,
            )
            all_facts.append(pc.ActivityFact(
                fact_kind="activity", activity_ref=activity_ref,
                activity_kind=activity.activity_type, name=activity.name,
                base_currency=_currency(activity.base_currency), status=status,
                observed_at=source.evidence.observed_at,
                context_version=str(activity.financial_version),
                query_evidence_ref=qev_ref,
            ))
        return (
            source.evidence.query_sha256, all_facts, [source],
            source.evidence.source_total, len(source.rows),
        )

    async def _require_memberships(
        self, activity_ids: Sequence[uuid.UUID], verified: v1.VerifiedReadContext,
        budget: v1._ReadBudget,
    ) -> None:
        unique = tuple(sorted(set(activity_ids), key=str))
        if len(unique) != len(activity_ids) or len(unique) > MAX_ROWS_PER_QUERY:
            raise P2ReadBackendError("invalid_upstream_response")
        if not unique:
            return
        rows = await self._get_table(
            "activity_members", v1._MEMBERSHIP_SELECT,
            [("activity_id", f"in.({_uuid_list(unique)})"),
             ("user_id", f"eq.{verified.principal_user_id}")],
            verified, budget=budget, order="activity_id.asc",
        )
        actual = tuple(_row_uuid(row, "activity_id") for row in rows)
        if len(actual) != len(unique) or set(actual) != set(unique):
            raise P2ReadBackendError("scope_unavailable")

    async def _read_expenses_candidate(
        self, request: pc.P2ReadQueryRequest, verified: v1.VerifiedReadContext,
        scope: v1.P2ResolvedScope, criteria_sha: str, scope_sha: str,
        envelope_sha: str, financial_versions: Mapping[uuid.UUID, int],
        qev_ref: str,
    ) -> tuple[str, list[Any], list[CandidateTableResult], int, int]:
        criteria = request.criteria
        activity = scope.activity
        assert activity is not None
        units = _scoped_unit_ids(scope, request.scope, self._turn_state)
        if not units:
            raise P2ReadBackendError("unsupported_scope")
        budget = v1._ReadBudget()
        unit_filter = f"in.({_uuid_list(units)})"
        expense_source = await self._fetch_candidate_table(
            operation=request.operation, table="expenses", select=v1._EXPENSE_SELECT,
            identity_fields=("id",),
            filters=(("ledger_unit_id", unit_filter), ("is_deleted", "eq.false")),
            scope=scope, verified=verified, criteria=criteria,
            criteria_sha=criteria_sha, scope_sha=scope_sha, envelope_sha=envelope_sha,
            financial_versions=financial_versions, budget=budget,
            order="occurred_at.asc,id.asc",
        )
        raw_expenses = list(expense_source.rows)
        expense_ids = tuple(_row_uuid(row, "id") for row in raw_expenses)
        sources = [expense_source]
        payments: list[Mapping[str, Any]] = []
        splits: list[Mapping[str, Any]] = []
        if expense_ids:
            id_filter = f"in.({_uuid_list(expense_ids)})"
            payment_source = await self._fetch_candidate_table(
                operation=request.operation, table="payments", select=v1._PAYMENT_SELECT,
                identity_fields=("id",), filters=(("expense_id", id_filter),),
                scope=scope, verified=verified, criteria=criteria,
                criteria_sha=criteria_sha, scope_sha=scope_sha, envelope_sha=envelope_sha,
                financial_versions=financial_versions, budget=budget,
                order="expense_id.asc,id.asc",
            )
            split_source = await self._fetch_candidate_table(
                operation=request.operation, table="splits", select=v1._SPLIT_SELECT,
                identity_fields=("id",), filters=(("expense_id", id_filter),),
                scope=scope, verified=verified, criteria=criteria,
                criteria_sha=criteria_sha, scope_sha=scope_sha, envelope_sha=envelope_sha,
                financial_versions=financial_versions, budget=budget,
                order="expense_id.asc,id.asc",
            )
            payments.extend(payment_source.rows)
            splits.extend(split_source.rows)
            sources.extend((payment_source, split_source))

        active_participants = {
            row.participant_id for row in scope.participants if not row.is_deleted
        }
        child_by_unit = {item.ledger_unit_id: item for item in scope.child_scopes}
        unit_by_id = {item.ledger_unit_id: item for item in scope.ledger_units if not item.is_deleted}
        payment_by_expense: dict[uuid.UUID, list[v1.P2PaymentDTO]] = {}
        split_by_expense: dict[uuid.UUID, list[v1.P2SplitDTO]] = {}
        for row in payments:
            item = v1._payment_dto(row)
            if item.expense_id not in set(expense_ids) or item.participant_id not in active_participants:
                raise P2ReadBackendError("scope_unavailable")
            payment_by_expense.setdefault(item.expense_id, []).append(item)
        for row in splits:
            item = v1._split_dto(row)
            if item.expense_id not in set(expense_ids) or item.participant_id not in active_participants:
                raise P2ReadBackendError("scope_unavailable")
            split_by_expense.setdefault(item.expense_id, []).append(item)
        requested_participant = _criteria_ref_id(self._turn_state, criteria, "participant_ref", "participant", activity.activity_id)
        facts: list[Any] = []
        for row in raw_expenses:
            unit_id = _row_uuid(row, "ledger_unit_id")
            unit = unit_by_id.get(unit_id)
            if unit is None or unit.activity_id != activity.activity_id or unit_id not in units:
                raise P2ReadBackendError("scope_unavailable")
            expense = v1._expense_dto(row, activity.activity_id)
            if criteria.from_date is not None and expense.occurred_at.date() < criteria.from_date:
                continue
            if criteria.to_date is not None and expense.occurred_at.date() > criteria.to_date:
                continue
            if criteria.title_contains is not None and criteria.title_contains.casefold() not in expense.title.casefold():
                continue
            pay_rows = payment_by_expense.get(expense.expense_id, [])
            split_rows = split_by_expense.get(expense.expense_id, [])
            if not pay_rows or not split_rows:
                raise P2ReadBackendError("invalid_upstream_response")
            child = child_by_unit.get(unit_id)
            if unit.unit_type == "sub_activity" and (child is None or child.configured and any(
                item.participant_id not in child.participant_ids for item in (*pay_rows, *split_rows)
            )):
                raise P2ReadBackendError("scope_unavailable")
            allocations: list[Any] = []
            for role, lines in (("payer", pay_rows), ("split", split_rows)):
                for line in lines:
                    if line.base_amount is None:
                        raise P2ReadBackendError("invalid_upstream_response")
                    participant_ref = self._turn_state.bind_entity(
                        "participant", line.participant_id, activity_id=activity.activity_id,
                    )
                    allocations.append(pc.ParticipantAllocationFact(
                        participant_ref=participant_ref, role=role,
                        signed_original_amount=_source_numeric(line.amount, precision=20, scale=4, signed=True),
                        original_currency=_currency(expense.original_currency),
                        signed_base_amount=_source_numeric(line.base_amount, precision=20, scale=1, signed=True),
                        base_currency=_currency(activity.base_currency),
                    ))
            allocations.sort(key=lambda line: (line.role, line.participant_ref, line.signed_original_amount, line.signed_base_amount))
            if requested_participant is not None and not any(
                self._turn_state.resolve_entity(line.participant_ref, "participant").entity_id == requested_participant
                for line in allocations
            ):
                continue
            expense_ref = self._turn_state.bind_entity(
                "expense", expense.expense_id, activity_id=activity.activity_id,
                ledger_unit_id=unit_id,
            )
            unit_ref = self._turn_state.bind_entity(
                "ledger_unit", unit_id, activity_id=activity.activity_id, ledger_unit_id=unit_id,
            )
            facts.append(pc.ExpenseFact(
                fact_kind="expense", expense_ref=expense_ref, scope_ref=request.scope.scope_ref,
                occurred_at=expense.occurred_at,
                signed_original_amount=_source_numeric(expense.original_amount, precision=20, scale=4, signed=True),
                original_currency=_currency(expense.original_currency),
                signed_base_amount=_source_numeric(expense.base_amount, precision=20, scale=1, signed=True),
                base_currency=_currency(activity.base_currency),
                payer_split_lines=tuple(allocations), expense_version=expense.expense_version,
                financial_version=activity.financial_version, query_evidence_ref=qev_ref,
            ))
        if len(facts) > MAX_ROWS_PER_QUERY:
            raise P2ReadBackendError("read_limit_exceeded")
        return (
            _chain_hash(tuple(item.evidence.query_sha256 for item in sources)),
            facts, sources, expense_source.evidence.source_total, len(raw_expenses),
        )

    async def _read_debts_candidate(
        self, request: pc.P2ReadQueryRequest, verified: v1.VerifiedReadContext,
        scope: v1.P2ResolvedScope, criteria_sha: str, scope_sha: str,
        envelope_sha: str, financial_versions: Mapping[uuid.UUID, int],
        qev_ref: str,
    ) -> tuple[str, list[Any], list[CandidateTableResult], int, int]:
        criteria = request.criteria
        activity = scope.activity
        assert activity is not None
        units = _scoped_unit_ids(scope, request.scope, self._turn_state)
        if not units:
            raise P2ReadBackendError("unsupported_scope")
        budget = v1._ReadBudget()
        debt_select = (
            "id,activity_id,ledger_unit_id,expense_id,debtor_participant_id,creditor_participant_id,"
            "amount,original_amount,original_currency,fx_rate,created_at"
        )
        debts_source = await self._fetch_candidate_table(
            operation=request.operation, table="expense_debts", select=debt_select,
            identity_fields=("id",),
            filters=(("activity_id", f"eq.{activity.activity_id}"), ("ledger_unit_id", f"in.({_uuid_list(units)})")),
            scope=scope, verified=verified, criteria=criteria, criteria_sha=criteria_sha,
            scope_sha=scope_sha, envelope_sha=envelope_sha, financial_versions=financial_versions,
            budget=budget, order="ledger_unit_id.asc,expense_id.asc,debtor_participant_id.asc,creditor_participant_id.asc,id.asc",
        )
        debt_rows = list(debts_source.rows)
        sources = [debts_source]
        expense_rows: dict[uuid.UUID, Mapping[str, Any]] = {}
        expense_ids = tuple({_row_uuid(row, "expense_id") for row in debt_rows})
        if expense_ids:
            parent_source = await self._fetch_candidate_table(
                operation=request.operation, table="expenses", select=v1._EXPENSE_SELECT,
                identity_fields=("id",),
                filters=(("id", f"in.({_uuid_list(expense_ids)})"), ("is_deleted", "eq.false")),
                scope=scope, verified=verified, criteria=criteria, criteria_sha=criteria_sha,
                scope_sha=scope_sha, envelope_sha=envelope_sha, financial_versions=financial_versions,
                budget=budget, order="id.asc",
            )
            sources.append(parent_source)
            expense_rows = {_row_uuid(row, "id"): row for row in parent_source.rows}
            if set(expense_rows) != set(expense_ids):
                raise P2ReadBackendError("incomplete_query")
        units_by_id = {item.ledger_unit_id: item for item in scope.ledger_units if not item.is_deleted}
        child_by_unit = {item.ledger_unit_id: item for item in scope.child_scopes}
        active_participants = {item.participant_id for item in scope.participants if not item.is_deleted}
        participant_id = _criteria_ref_id(self._turn_state, criteria, "participant_ref", "participant", activity.activity_id)
        facts: list[Any] = []
        if criteria.currency is not None and any(row.get("original_currency") is None for row in debt_rows):
            # Unknown source currencies cannot be filtered into a proven zero.
            raise P2ReadBackendError("incomplete_query")
        for row in debt_rows:
            debt_id = _row_uuid(row, "id")
            row_activity_id = _row_uuid(row, "activity_id")
            unit_id = _row_uuid(row, "ledger_unit_id")
            expense_id = _row_uuid(row, "expense_id")
            debtor_id = _row_uuid(row, "debtor_participant_id")
            creditor_id = _row_uuid(row, "creditor_participant_id")
            unit = units_by_id.get(unit_id)
            parent = expense_rows.get(expense_id)
            if (
                row_activity_id != activity.activity_id or unit is None or unit.activity_id != activity.activity_id
                or unit_id not in units or parent is None
                or _row_uuid(parent, "ledger_unit_id") != unit_id
                or debtor_id == creditor_id or debtor_id not in active_participants or creditor_id not in active_participants
            ):
                raise P2ReadBackendError("scope_unavailable")
            child = child_by_unit.get(unit_id)
            if unit.unit_type == "sub_activity" and (
                child is None or child.configured and (debtor_id not in child.participant_ids or creditor_id not in child.participant_ids)
            ):
                raise P2ReadBackendError("scope_unavailable")
            amount = _source_numeric(row.get("amount"), precision=20, scale=1)
            original_raw = row.get("original_amount")
            currency_raw = row.get("original_currency")
            original_amount = None if original_raw is None else _source_numeric(original_raw, precision=20, scale=4)
            original_currency = None if currency_raw is None else _currency(currency_raw)
            if original_amount is not None and Decimal(original_amount) <= 0:
                raise P2ReadBackendError("invalid_upstream_response")
            if criteria.currency is not None and original_currency != criteria.currency:
                continue
            if participant_id is not None and participant_id not in (debtor_id, creditor_id):
                continue
            unit_ref = self._turn_state.bind_entity("ledger_unit", unit_id, activity_id=activity.activity_id, ledger_unit_id=unit_id)
            debt_ref = self._turn_state.bind_entity("debt", debt_id, activity_id=activity.activity_id, ledger_unit_id=unit_id)
            expense_ref = self._turn_state.bind_entity("expense", expense_id, activity_id=activity.activity_id, ledger_unit_id=unit_id)
            debtor_ref = self._turn_state.bind_entity("participant", debtor_id, activity_id=activity.activity_id)
            creditor_ref = self._turn_state.bind_entity("participant", creditor_id, activity_id=activity.activity_id)
            facts.append(pc.DebtFact(
                fact_kind="debt", debt_source_variant=DEBT_SOURCE_VARIANT,
                debt_ref=debt_ref,
                scope_ref=request.scope.scope_ref,
                activity_ref=request.scope.activity_ref,
                ledger_unit_ref=unit_ref, expense_ref=expense_ref,
                debtor_ref=debtor_ref, creditor_ref=creditor_ref,
                original_amount=original_amount, original_currency=original_currency,
                base_amount=amount, base_currency=_currency(activity.base_currency),
                financial_version=activity.financial_version, query_evidence_ref=qev_ref,
            ))
        return (
            _chain_hash(tuple(item.evidence.query_sha256 for item in sources)), facts,
            sources, debts_source.evidence.source_total, len(debt_rows),
        )

    async def _read_refunds_candidate(
        self, request: pc.P2ReadQueryRequest, verified: v1.VerifiedReadContext,
        scope: v1.P2ResolvedScope, criteria_sha: str, scope_sha: str,
        envelope_sha: str, financial_versions: Mapping[uuid.UUID, int],
        qev_ref: str,
    ) -> tuple[str, list[Any], list[CandidateTableResult], int, int]:
        criteria = request.criteria
        activity = scope.activity
        assert activity is not None
        # The candidate refund projection is Activity-wide. Parent rows may
        # belong to another child unit within that same Activity, but are only
        # used to establish public lineage and never expose parent details.
        if request.scope.scope_kind != "activity":
            raise P2ReadBackendError("unsupported_scope")
        units = _scoped_unit_ids(scope, request.scope, self._turn_state)
        if not units:
            raise P2ReadBackendError("unsupported_scope")
        budget = v1._ReadBudget()
        source = await self._fetch_candidate_table(
            operation=request.operation, table="expenses", select=v1._EXPENSE_SELECT,
            identity_fields=("id",),
            filters=(("ledger_unit_id", f"in.({_uuid_list(units)})"), ("is_deleted", "eq.false")),
            scope=scope, verified=verified, criteria=criteria, criteria_sha=criteria_sha,
            scope_sha=scope_sha, envelope_sha=envelope_sha, financial_versions=financial_versions,
            budget=budget, order="occurred_at.asc,id.asc",
        )
        all_rows = list(source.rows)
        refund_rows = [row for row in all_rows if _source_decimal(row.get("original_amount")) < 0]
        linked_ids = tuple({
            _row_uuid(row, "original_expense_id")
            for row in refund_rows if row.get("original_expense_id") is not None
        })
        parent_source: CandidateTableResult | None = None
        parents: dict[uuid.UUID, Mapping[str, Any]] = {}
        sources = [source]
        if linked_ids:
            parent_source = await self._fetch_candidate_table(
                operation=request.operation, table="expenses", select=v1._EXPENSE_SELECT,
                identity_fields=("id",),
                filters=(("id", f"in.({_uuid_list(linked_ids)})"), ("is_deleted", "eq.false")),
                scope=scope, verified=verified, criteria=criteria, criteria_sha=criteria_sha,
                scope_sha=scope_sha, envelope_sha=envelope_sha, financial_versions=financial_versions,
                budget=budget, order="id.asc",
            )
            sources.append(parent_source)
            parents = {_row_uuid(row, "id"): row for row in parent_source.rows}
        units_by_id = {item.ledger_unit_id: item for item in scope.ledger_units if not item.is_deleted}
        facts: list[Any] = []
        for row in refund_rows:
            amount = _source_numeric(row.get("original_amount"), precision=20, scale=4, signed=True)
            if Decimal(amount) >= 0:
                continue
            occurred = v1._parse_datetime(row.get("occurred_at"))
            assert occurred is not None
            if criteria.from_date is not None and occurred.date() < criteria.from_date:
                continue
            if criteria.to_date is not None and occurred.date() > criteria.to_date:
                continue
            unit_id = _row_uuid(row, "ledger_unit_id")
            unit = units_by_id.get(unit_id)
            if unit is None or unit.activity_id != activity.activity_id or unit_id not in units:
                raise P2ReadBackendError("scope_unavailable")
            refund_id = _row_uuid(row, "id")
            parent_id = None if row.get("original_expense_id") is None else _row_uuid(row, "original_expense_id")
            parent_ref: str | None = None
            lineage_status = "unverified"
            lineage_basis = None
            if parent_id is not None:
                parent = parents.get(parent_id)
                if parent is None:
                    lineage_status = "parent_unavailable"
                else:
                    parent_unit_id = _row_uuid(parent, "ledger_unit_id")
                    parent_unit = units_by_id.get(parent_unit_id)
                    if (
                        parent_unit is None or parent_unit.activity_id != activity.activity_id
                        or _source_decimal(parent.get("original_amount")) <= 0
                        or parent.get("original_expense_id") is not None
                        or parent.get("original_currency") != row.get("original_currency")
                        or _source_decimal(parent.get("fx_rate")) != _source_decimal(row.get("fx_rate"))
                    ):
                        raise P2ReadBackendError("invalid_upstream_response")
                    parent_ref = self._turn_state.bind_entity(
                        "expense", parent_id, activity_id=activity.activity_id,
                        ledger_unit_id=parent_unit_id,
                    )
                    lineage_status = "verified_same_activity_parent"
                    lineage_basis = "public_parent_relationship"
            unit_ref = self._turn_state.bind_entity("ledger_unit", unit_id, activity_id=activity.activity_id, ledger_unit_id=unit_id)
            refund_ref = self._turn_state.bind_entity("refund", refund_id, activity_id=activity.activity_id, ledger_unit_id=unit_id)
            facts.append(pc.RefundEventFact(
                fact_kind="refund_event", refund_ref=refund_ref, scope_ref=request.scope.scope_ref,
                signed_original_amount=amount,
                original_currency=_currency(row.get("original_currency")),
                signed_base_amount=_source_numeric(row.get("base_amount"), precision=20, scale=1, signed=True),
                base_currency=_currency(activity.base_currency), occurred_at=occurred,
                parent_expense_ref=parent_ref, lineage_status=lineage_status,
                lineage_basis=lineage_basis, refund_recipient_ref=None,
                financial_version=activity.financial_version, query_evidence_ref=qev_ref,
            ))
        return source.evidence.query_sha256, facts, sources, source.evidence.source_total, len(all_rows)

    async def _read_prepayment_accounts_candidate(
        self, request: pc.P2ReadQueryRequest, verified: v1.VerifiedReadContext,
        scope: v1.P2ResolvedScope, criteria_sha: str, scope_sha: str,
        envelope_sha: str, financial_versions: Mapping[uuid.UUID, int],
        qev_ref: str,
    ) -> tuple[str, list[Any], list[CandidateTableResult], int, int]:
        activity = scope.activity
        assert activity is not None
        if request.scope.scope_kind != "activity":
            raise P2ReadBackendError("unsupported_scope")
        budget = v1._ReadBudget()
        select = "id,activity_id,owner_participant_id,custodian_participant_id,currency,balance,updated_at"
        source = await self._fetch_candidate_table(
            operation=request.operation, table="prepayment_accounts", select=select,
            identity_fields=("id",), filters=(("activity_id", f"eq.{activity.activity_id}"),),
            scope=scope, verified=verified, criteria=request.criteria,
            criteria_sha=criteria_sha, scope_sha=scope_sha, envelope_sha=envelope_sha,
            financial_versions=financial_versions, budget=budget,
            order="owner_participant_id.asc,custodian_participant_id.asc,currency.asc,id.asc",
        )
        active = {item.participant_id for item in scope.participants if not item.is_deleted}
        facts: list[Any] = []
        for row in source.rows:
            if _row_uuid(row, "activity_id") != activity.activity_id:
                raise P2ReadBackendError("scope_unavailable")
            owner_id = _row_uuid(row, "owner_participant_id")
            custodian_id = _row_uuid(row, "custodian_participant_id")
            if owner_id == custodian_id or owner_id not in active or custodian_id not in active:
                raise P2ReadBackendError("scope_unavailable")
            account_ref = self._turn_state.bind_entity("prepayment_account", _row_uuid(row, "id"), activity_id=activity.activity_id)
            facts.append(pc.PrepaymentAccountFact(
                fact_kind="prepayment_account", account_ref=account_ref,
                activity_ref=request.scope.activity_ref,
                owner_ref=self._turn_state.bind_entity("participant", owner_id, activity_id=activity.activity_id),
                custodian_ref=self._turn_state.bind_entity("participant", custodian_id, activity_id=activity.activity_id),
                balance=_source_numeric(row.get("balance"), precision=20, scale=4),
                currency=_currency(row.get("currency")),
                projection_updated_at=_source_datetime(row.get("updated_at")),
                financial_version=activity.financial_version, query_evidence_ref=qev_ref,
            ))
        return source.evidence.query_sha256, facts, [source], source.evidence.source_total, len(source.rows)

    async def _read_prepayment_usages_candidate(
        self, request: pc.P2ReadQueryRequest, verified: v1.VerifiedReadContext,
        scope: v1.P2ResolvedScope, criteria_sha: str, scope_sha: str,
        envelope_sha: str, financial_versions: Mapping[uuid.UUID, int],
        qev_ref: str,
    ) -> tuple[str, list[Any], list[CandidateTableResult], int, int]:
        activity = scope.activity
        assert activity is not None
        criteria = request.criteria
        budget = v1._ReadBudget()
        sources: list[CandidateTableResult] = []
        debt_ids_scope: tuple[uuid.UUID, ...] | None = None
        if request.scope.scope_kind == "ledger_unit":
            unit_id = self._turn_state.resolve_entity(
                request.scope.ledger_unit_ref or "", "ledger_unit", activity_id=activity.activity_id,
            ).entity_id
            debt_source = await self._fetch_candidate_table(
                operation=request.operation, table="expense_debts",
                select="id,activity_id,ledger_unit_id,expense_id,debtor_participant_id,creditor_participant_id,amount,original_amount,original_currency,fx_rate,created_at",
                identity_fields=("id",), filters=(("activity_id", f"eq.{activity.activity_id}"),("ledger_unit_id", f"eq.{unit_id}")),
                scope=scope, verified=verified, criteria=criteria, criteria_sha=criteria_sha,
                scope_sha=scope_sha, envelope_sha=envelope_sha, financial_versions=financial_versions,
                budget=budget, order="id.asc",
            )
            sources.append(debt_source)
            debt_ids_scope = tuple(_row_uuid(row, "id") for row in debt_source.rows)
            if not debt_ids_scope:
                return debt_source.evidence.query_sha256, [], sources, 0, 0
        usage_select = (
            "id,activity_id,account_id,expense_debt_id,gross_amount,amount,created_at,"
            "prepayment_currency,prepayment_amount,debt_currency,debt_amount,base_amount,bill_fx_rate,bill_occurred_at"
        )
        filters: list[tuple[str, str]] = [("activity_id", f"eq.{activity.activity_id}")]
        if debt_ids_scope is not None:
            filters.append(("expense_debt_id", f"in.({_uuid_list(debt_ids_scope)})"))
        usage_source = await self._fetch_candidate_table(
            operation=request.operation, table="prepayment_usages", select=usage_select,
            identity_fields=("id",), filters=filters, scope=scope, verified=verified,
            criteria=criteria, criteria_sha=criteria_sha, scope_sha=scope_sha,
            envelope_sha=envelope_sha, financial_versions=financial_versions,
            budget=budget, order="bill_occurred_at.asc,expense_debt_id.asc,id.asc",
        )
        sources.append(usage_source)
        usage_rows = list(usage_source.rows)
        account_ids = tuple({_row_uuid(row, "account_id") for row in usage_rows})
        debt_ids = tuple({_row_uuid(row, "expense_debt_id") for row in usage_rows})
        account_rows: dict[uuid.UUID, Mapping[str, Any]] = {}
        debt_rows: dict[uuid.UUID, Mapping[str, Any]] = {}
        expense_rows: dict[uuid.UUID, Mapping[str, Any]] = {}
        if account_ids:
            account_source = await self._fetch_candidate_table(
                operation=request.operation, table="prepayment_accounts",
                select="id,activity_id,owner_participant_id,custodian_participant_id,currency,balance,updated_at",
                identity_fields=("id",), filters=(("activity_id", f"eq.{activity.activity_id}"),("id",f"in.({_uuid_list(account_ids)})")),
                scope=scope, verified=verified, criteria=criteria, criteria_sha=criteria_sha,
                scope_sha=scope_sha, envelope_sha=envelope_sha, financial_versions=financial_versions,
                budget=budget, order="id.asc",
            )
            sources.append(account_source)
            account_rows={_row_uuid(row,"id"):row for row in account_source.rows}
            debt_source = await self._fetch_candidate_table(
                operation=request.operation, table="expense_debts",
                select="id,activity_id,ledger_unit_id,expense_id,debtor_participant_id,creditor_participant_id,amount,original_amount,original_currency,fx_rate,created_at",
                identity_fields=("id",), filters=(("activity_id",f"eq.{activity.activity_id}"),("id",f"in.({_uuid_list(debt_ids)})")),
                scope=scope, verified=verified, criteria=criteria, criteria_sha=criteria_sha,
                scope_sha=scope_sha, envelope_sha=envelope_sha, financial_versions=financial_versions,
                budget=budget, order="id.asc",
            )
            sources.append(debt_source)
            debt_rows={_row_uuid(row,"id"):row for row in debt_source.rows}
            joined_expense_ids=tuple({_row_uuid(row,"expense_id") for row in debt_rows.values()})
            if joined_expense_ids:
                expense_source=await self._fetch_candidate_table(
                    operation=request.operation, table="expenses", select=v1._EXPENSE_SELECT,
                    identity_fields=("id",), filters=(("id",f"in.({_uuid_list(joined_expense_ids)})"),("is_deleted","eq.false")),
                    scope=scope, verified=verified, criteria=criteria, criteria_sha=criteria_sha,
                    scope_sha=scope_sha, envelope_sha=envelope_sha, financial_versions=financial_versions,
                    budget=budget, order="id.asc",
                )
                sources.append(expense_source)
                expense_rows={_row_uuid(row,"id"):row for row in expense_source.rows}
        if set(account_rows) != set(account_ids) or set(debt_rows) != set(debt_ids):
            if usage_rows:
                raise P2ReadBackendError("incomplete_query")
        active = {item.participant_id for item in scope.participants if not item.is_deleted}
        participant_id = _criteria_ref_id(self._turn_state, criteria, "participant_ref", "participant", activity.activity_id)
        expense_id_filter = _criteria_ref_id(self._turn_state, criteria, "expense_ref", "expense", activity.activity_id)
        facts: list[Any] = []
        for row in usage_rows:
            usage_id = _row_uuid(row,"id")
            account_id = _row_uuid(row,"account_id")
            debt_id = _row_uuid(row,"expense_debt_id")
            account = account_rows.get(account_id)
            debt = debt_rows.get(debt_id)
            if account is None or debt is None or _row_uuid(row,"activity_id") != activity.activity_id:
                raise P2ReadBackendError("scope_unavailable")
            if _row_uuid(account,"activity_id") != activity.activity_id or _row_uuid(debt,"activity_id") != activity.activity_id:
                raise P2ReadBackendError("scope_unavailable")
            owner_id=_row_uuid(account,"owner_participant_id"); custodian_id=_row_uuid(account,"custodian_participant_id")
            debtor_id=_row_uuid(debt,"debtor_participant_id"); creditor_id=_row_uuid(debt,"creditor_participant_id")
            if owner_id != debtor_id or custodian_id != creditor_id or owner_id not in active or custodian_id not in active:
                raise P2ReadBackendError("scope_unavailable")
            unit_id=_row_uuid(debt,"ledger_unit_id"); expense_id=_row_uuid(debt,"expense_id")
            parent=expense_rows.get(expense_id)
            if parent is None or _row_uuid(parent,"ledger_unit_id") != unit_id:
                raise P2ReadBackendError("incomplete_query")
            if request.scope.scope_kind == "ledger_unit" and unit_id != self._turn_state.resolve_entity(request.scope.ledger_unit_ref or "","ledger_unit",activity_id=activity.activity_id).entity_id:
                raise P2ReadBackendError("scope_unavailable")
            if expense_id_filter is not None and expense_id != expense_id_filter:
                continue
            if participant_id is not None and participant_id not in (owner_id,custodian_id):
                continue
            facts.append(pc.PrepaymentUsageFact(
                fact_kind="prepayment_usage",
                usage_ref=self._turn_state.bind_entity("prepayment_usage",usage_id,activity_id=activity.activity_id,ledger_unit_id=unit_id),
                account_ref=self._turn_state.bind_entity("prepayment_account",account_id,activity_id=activity.activity_id),
                expense_ref=self._turn_state.bind_entity("expense",expense_id,activity_id=activity.activity_id,ledger_unit_id=unit_id),
                debt_ref=self._turn_state.bind_entity("debt",debt_id,activity_id=activity.activity_id,ledger_unit_id=unit_id),
                activity_ref=request.scope.activity_ref,
                gross_amount=_source_numeric(row.get("gross_amount"),precision=20,scale=4),
                amount=_source_numeric(row.get("amount"),precision=20,scale=4),
                prepayment_amount=_source_numeric(row.get("prepayment_amount"),precision=20,scale=4),
                prepayment_currency=_currency(row.get("prepayment_currency")),
                debt_amount=_source_numeric(row.get("debt_amount"),precision=20,scale=4),
                debt_currency=_currency(row.get("debt_currency")),
                base_amount=_source_numeric(row.get("base_amount"),precision=20,scale=1) if row.get("base_amount") is not None else None,
                base_currency=_currency(activity.base_currency) if row.get("base_amount") is not None else None,
                bill_fx_rate=_source_numeric(row.get("bill_fx_rate"),precision=20,scale=10) if row.get("bill_fx_rate") is not None else None,
                bill_occurred_at=_source_datetime(row.get("bill_occurred_at"),allow_null=True),
                financial_version=activity.financial_version, query_evidence_ref=qev_ref,
            ))
        return (
            _chain_hash(tuple(item.evidence.query_sha256 for item in sources)), facts,
            sources, usage_source.evidence.source_total, len(usage_rows),
        )

    async def _read_prepayment_returns_candidate(
        self, request: pc.P2ReadQueryRequest, verified: v1.VerifiedReadContext,
        scope: v1.P2ResolvedScope, criteria_sha: str, scope_sha: str,
        envelope_sha: str, financial_versions: Mapping[uuid.UUID, int],
        qev_ref: str,
    ) -> tuple[str, list[Any], list[CandidateTableResult], int, int]:
        activity=scope.activity
        assert activity is not None
        if request.scope.scope_kind != "activity":
            raise P2ReadBackendError("unsupported_scope")
        criteria=request.criteria
        budget=v1._ReadBudget()
        transfer_source=await self._fetch_candidate_table(
            operation=request.operation,table="transfers",
            select="id,activity_id,from_participant_id,to_participant_id,type,amount,currency,occurred_at,is_voided",
            identity_fields=("id",),
            filters=(("activity_id",f"eq.{activity.activity_id}"),("type","eq.prepayment_return"),("is_voided","eq.false")),
            scope=scope,verified=verified,criteria=criteria,criteria_sha=criteria_sha,
            scope_sha=scope_sha,envelope_sha=envelope_sha,financial_versions=financial_versions,
            budget=budget,order="occurred_at.asc,id.asc",
        )
        transfers=list(transfer_source.rows)
        component_source=None
        components: dict[uuid.UUID,Mapping[str,Any]]={}
        sources=[transfer_source]
        transfer_ids=tuple(_row_uuid(row,"id") for row in transfers)
        if transfer_ids:
            component_source=await self._fetch_candidate_table(
                operation=request.operation,table="transfer_components",
                select="id,activity_id,transfer_id,component_type,amount,created_at",
                identity_fields=("id",),
                filters=(("activity_id",f"eq.{activity.activity_id}"),("transfer_id",f"in.({_uuid_list(transfer_ids)})"),("component_type","eq.prepayment_return")),
                scope=scope,verified=verified,criteria=criteria,criteria_sha=criteria_sha,
                scope_sha=scope_sha,envelope_sha=envelope_sha,financial_versions=financial_versions,
                budget=budget,order="transfer_id.asc,id.asc",
            )
            sources.append(component_source)
            for row in component_source.rows:
                transfer_id=_row_uuid(row,"transfer_id")
                if transfer_id in components:
                    raise P2ReadBackendError("invalid_upstream_response")
                components[transfer_id]=row
        active={item.participant_id for item in scope.participants if not item.is_deleted}
        facts=[]
        for row in transfers:
            transfer_id=_row_uuid(row,"id")
            if _row_uuid(row,"activity_id") != activity.activity_id or row.get("type") != "prepayment_return" or row.get("is_voided") is not False:
                raise P2ReadBackendError("invalid_upstream_response")
            component=components.get(transfer_id)
            if component is None or _row_uuid(component,"activity_id") != activity.activity_id or component.get("component_type") != "prepayment_return":
                raise P2ReadBackendError("incomplete_query")
            amount=_source_numeric(row.get("amount"),precision=20,scale=1)
            if amount != _source_numeric(component.get("amount"),precision=20,scale=1):
                raise P2ReadBackendError("invalid_upstream_response")
            occurred=_source_datetime(row.get("occurred_at"))
            if criteria.from_date is not None and occurred.date() < criteria.from_date:
                continue
            if criteria.to_date is not None and occurred.date() > criteria.to_date:
                continue
            from_id=_row_uuid(row,"from_participant_id"); to_id=_row_uuid(row,"to_participant_id")
            if from_id not in active or to_id not in active or from_id==to_id:
                raise P2ReadBackendError("scope_unavailable")
            facts.append(pc.PrepaymentReturnEventFact(
                fact_kind="prepayment_return_event",
                return_event_ref=self._turn_state.bind_entity("prepayment_return",transfer_id,activity_id=activity.activity_id),
                activity_ref=request.scope.activity_ref, amount=amount,
                currency=_currency(row.get("currency")), occurred_at=occurred,
                from_ref=self._turn_state.bind_entity("participant",from_id,activity_id=activity.activity_id),
                from_role="custodian", to_ref=self._turn_state.bind_entity("participant",to_id,activity_id=activity.activity_id),
                to_role="owner", transfer_component_match=True,
                financial_version=activity.financial_version, query_evidence_ref=qev_ref,
            ))
        return (
            _chain_hash(tuple(item.evidence.query_sha256 for item in sources)), facts,
            sources, transfer_source.evidence.source_total, len(transfers),
        )

    async def _read_table_plan_inner(
        self,
        verified: v1.VerifiedReadContext,
        *,
        operation: str,
        criteria: Any,
        scope: v1.P2ResolvedScope | None,
        criteria_sha256: str,
        scope_sha256: str,
        envelope_sha256: str,
        financial_versions: Mapping[uuid.UUID, int],
        plan: CandidateTablePlan,
        budget: v1._ReadBudget,
    ) -> CandidateTableResult:
        """Fetch one fixed source table and prove each actual raw page.

        Operation builders own exact criteria/source mapping. Arbitrary table,
        column, select, order, and endpoint values are rejected here.
        """
        self._validate_candidate_context(verified, operation, plan, criteria_sha256, scope_sha256)
        if plan.table not in _OPERATION_SOURCE_TABLES.get(operation, frozenset()):
            raise P2ReadBackendError("unsupported_read")
        self._validate_sha(envelope_sha256)
        checked_versions = _validate_financial_versions(
            financial_versions, allow_empty=(operation == pc.P2ReadOperation.ACTIVITIES),
        )
        filters = _validate_filters(plan.filters(criteria, scope))
        query_id = uuid.uuid4().hex
        query_sha = _candidate_query_sha(
            operation, criteria_sha256, scope_sha256, plan, filters,
        )
        binding = QueryBinding(
            query_id, operation, criteria_sha256, scope_sha256, plan.table, query_sha,
            self._turn_state.owner_user_id, self._turn_state.turn_id,
            self._turn_state.generation, self._turn_state.context_revision,
            self._turn_state.claim_id, envelope_sha256, checked_versions,
        )
        context_token = _ACTIVE_QUERY.set(binding)
        try:
            async with self._turn_state.backend_operation():
                rows = await self._get_table(
                    plan.table, plan.select, filters, verified,
                    budget=budget, order=plan.order,
                )
        except BaseException:
            self._turn_state.discard_captures(query_id)
            raise
        finally:
            _ACTIVE_QUERY.reset(context_token)
        captures = self._turn_state.take_captures(query_id)
        if not captures:
            raise P2ReadBackendError("invalid_upstream_response")
        projected_rows: list[Mapping[str, Any]] = []
        accepted_rows: list[Mapping[str, Any]] = []
        raw_reparsed_rows: list[Mapping[str, Any]] = []
        receipts: list[CandidatePageReceipt] = []
        page_offset = 0
        expected_total: int | None = None
        seen: set[tuple[str, ...]] = set()
        previous: str | None = None
        for capture in captures:
            if capture.status not in (200, 206):
                raise P2ReadBackendError("invalid_upstream_response")
            parsed_rows = v1._parse_json_rows(capture.body)
            raw_reparsed_rows.extend(parsed_rows)
            start, count, total = _validate_captured_range(capture.content_range, page_offset, len(parsed_rows))
            if expected_total is None:
                expected_total = total
            elif expected_total != total:
                raise P2ReadBackendError("data_changed_during_read")
            if start != page_offset or count != len(parsed_rows) or total > MAX_ROWS_PER_QUERY:
                raise P2ReadBackendError("read_limit_exceeded")
            for row in parsed_rows:
                identity_values = tuple(row.get(name) for name in plan.identity_fields)
                if any(not isinstance(value, str) or not value for value in identity_values):
                    raise P2ReadBackendError("invalid_upstream_response")
                identity = tuple(identity_values)
                if identity in seen:
                    raise P2ReadBackendError("invalid_upstream_response")
                seen.add(identity)
                typed = plan.parse_source_row(row)
                if not isinstance(typed, Mapping):
                    raise P2ReadBackendError("invalid_upstream_response")
                projection = plan.project_row(typed, scope)
                if not isinstance(projection, Mapping):
                    raise P2ReadBackendError("invalid_upstream_response")
                accepted_rows.append(dict(typed))
                projected_rows.append(dict(projection))
            page_typed = accepted_rows[-len(parsed_rows):] if parsed_rows else []
            page_projected = projected_rows[-len(parsed_rows):] if parsed_rows else []
            receipt = _make_page_receipt(
                operation=operation, table=plan.table, query_sha=query_sha,
                offset=page_offset, row_count=len(parsed_rows), total=total,
                observed_at=capture.observed_at, raw_body=capture.body,
                request_sha256=capture.request_sha256,
                typed_rows=page_typed, projected_rows=page_projected, previous=previous,
                binding=binding,
            )
            receipts.append(receipt)
            previous = receipt.receipt_sha256
            page_offset += len(parsed_rows)
        if expected_total is None or page_offset != expected_total:
            raise P2ReadBackendError("incomplete_query")
        if tuple(raw_reparsed_rows) != tuple(rows):
            # The parser's flattened rows and raw response pages must describe
            # exactly the same bytes/objects; no parallel authority is accepted.
            raise P2ReadBackendError("invalid_upstream_response")
        observed = datetime.now(timezone.utc)
        source_total = expected_total
        matched = len(projected_rows)
        evidence = CandidateQueryEvidence(
            operation=operation, criteria_sha256=criteria_sha256,
            scope_sha256=scope_sha256, source_kind=plan.source_kind,
            observed_at=observed, returned_count=source_total,
            source_total=source_total, completeness="complete",
            zero_kind=("backend_zero" if source_total == 0 else "nonzero"),
            query_sha256=query_sha,
            raw_body_sha256=_chain_hash(tuple(item.raw_body_sha256 for item in receipts)),
            normalized_source_sha256=_canonical_sha(tuple(accepted_rows)),
            projection_sha256=_canonical_sha(tuple(projected_rows)),
            page_receipts=tuple(receipts),
        )
        return CandidateTableResult(tuple(accepted_rows), tuple(projected_rows), tuple(receipts), evidence)

    def _validate_candidate_context(
        self, verified: v1.VerifiedReadContext, operation: str, plan: CandidateTablePlan,
        criteria_sha256: str, scope_sha256: str,
    ) -> None:
        self._validate_grant(verified, owner_user_id=self._turn_state.owner_user_id, turn_id=self._turn_state.turn_id)
        self._turn_state.verify_turn(verified)
        if operation not in READ_OPERATIONS:
            raise P2ReadBackendError("unsupported_read")
        self._validate_sha(criteria_sha256)
        self._validate_sha(scope_sha256)
        if plan.table not in _OPERATION_SOURCE_TABLES.get(operation, frozenset()):
            raise P2ReadBackendError("unsupported_read")
        if not plan.select or not plan.identity_fields or not plan.order:
            raise P2ReadBackendError("unsupported_read")
        if not re.fullmatch(r"[a-z][a-z0-9_]*(,[a-z][a-z0-9_]*)*", plan.select):
            raise P2ReadBackendError("unsupported_read")
        if not re.fullmatch(r"[a-z][a-z0-9_]*\.(asc|desc)(,[a-z][a-z0-9_]*\.(asc|desc))*", plan.order):
            raise P2ReadBackendError("unsupported_read")
        if plan.table == "expense_refund_sources" or plan.table.startswith("private."):
            raise P2ReadBackendError("unsupported_read")

    @staticmethod
    def _validate_sha(value: str) -> None:
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise P2ReadBackendError("unsupported_read")


# Backend-specific source parsing and public DTO validation are supplied as
# trusted plans after p2_read_contracts is frozen. No caller/model can choose one.


def _validate_captured_range(raw: str | None, expected_offset: int, parsed_count: int) -> tuple[int, int, int]:
    match = _CONTENT_RANGE.fullmatch(raw or "")
    if match is None or match.group("total") == "*":
        raise P2ReadBackendError("read_limit_exceeded")
    if any(len(value or "") > 12 for value in (match.group("start"), match.group("end"), match.group("total"))):
        raise P2ReadBackendError("read_limit_exceeded")
    total = int(match.group("total"))
    if match.group("start") is None:
        if total != 0 or expected_offset != 0 or parsed_count != 0:
            raise P2ReadBackendError("invalid_upstream_response")
        return 0, 0, total
    start = int(match.group("start"))
    end = int(match.group("end") or "-1")
    count = end - start + 1
    if start != expected_offset or count != parsed_count or count <= 0 or count > MAX_ROWS_PER_PAGE or end >= total:
        raise P2ReadBackendError("invalid_upstream_response")
    return start, count, total


def _make_page_receipt(
    *, operation: str, table: str, query_sha: str, offset: int, row_count: int,
    total: int, observed_at: datetime, raw_body: bytes,
    request_sha256: str,
    typed_rows: Sequence[Mapping[str, Any]], projected_rows: Sequence[Mapping[str, Any]],
    previous: str | None, binding: QueryBinding,
) -> CandidatePageReceipt:
    raw_sha = hashlib.sha256(raw_body).hexdigest()
    typed_sha = _canonical_sha(tuple(typed_rows))
    projection_sha = _canonical_sha(tuple(projected_rows))
    material = {
        "operation": operation, "table": table, "query_sha256": query_sha,
        "request_sha256": request_sha256,
        "offset": offset, "row_count": row_count, "total": total,
        "observed_at": _utc(observed_at), "raw_body_sha256": raw_sha,
        "source_dto_sha256": typed_sha, "projection_sha256": projection_sha,
        "owner_user_id": str(binding.owner_user_id), "turn_id": str(binding.turn_id),
        "generation": binding.generation, "context_revision": binding.context_revision,
        "claim_id": str(binding.claim_id), "scope_sha256": binding.scope_sha256,
        "criteria_sha256": binding.criteria_sha256,
        "envelope_sha256": binding.envelope_sha256,
        "financial_versions": tuple((str(key), value) for key, value in binding.financial_versions),
        "previous_receipt_sha256": previous,
    }
    receipt_sha = _canonical_sha(material)
    return CandidatePageReceipt(
        operation, table, query_sha, request_sha256, offset, row_count, total,
        observed_at, raw_sha, typed_sha, projection_sha, binding.owner_user_id,
        binding.turn_id, binding.generation, binding.context_revision,
        binding.claim_id, binding.scope_sha256, binding.criteria_sha256,
        binding.envelope_sha256, binding.financial_versions, previous, receipt_sha,
    )


def _receipt_source_binding(receipt: CandidatePageReceipt) -> tuple[Any, ...]:
    """Stable data-binding projection, excluding observation-time/hash chain noise."""
    return (
        receipt.operation, receipt.table, receipt.query_sha256,
        receipt.request_sha256, receipt.offset, receipt.returned_count,
        receipt.source_total, receipt.source_dto_sha256, receipt.projection_sha256,
        receipt.owner_user_id, receipt.turn_id, receipt.generation,
        receipt.context_revision, receipt.claim_id, receipt.scope_sha256,
        receipt.criteria_sha256, receipt.envelope_sha256,
        receipt.financial_versions,
    )


def _candidate_query_sha(
    operation: str, criteria_sha: str, scope_sha: str,
    plan: CandidateTablePlan, filters: Sequence[tuple[str, str]],
) -> str:
    query = {
        "profile_id": PROFILE_ID, "versions": PROFILE_VERSIONS,
        "operation": operation, "table": plan.table, "select": plan.select,
        "order": plan.order, "filters": tuple(filters),
        "criteria_sha256": criteria_sha, "scope_sha256": scope_sha,
    }
    return _canonical_sha(query)


def _validate_filters(filters: Sequence[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    if not isinstance(filters, Sequence) or isinstance(filters, (str, bytes)):
        raise P2ReadBackendError("unsupported_read")
    checked: list[tuple[str, str]] = []
    for item in filters:
        if (
            not isinstance(item, tuple) or len(item) != 2
            or not isinstance(item[0], str) or not re.fullmatch(r"[a-z][a-z0-9_]*", item[0])
            or not isinstance(item[1], str) or not item[1] or len(item[1]) > 4096
        ):
            raise P2ReadBackendError("unsupported_read")
        checked.append(item)
    if len(checked) > 32:
        raise P2ReadBackendError("read_limit_exceeded")
    return tuple(checked)


def _validate_financial_versions(
    versions: Mapping[uuid.UUID, int],
    *, allow_empty: bool = False,
) -> tuple[tuple[uuid.UUID, int], ...]:
    if (
        not isinstance(versions, Mapping)
        or (not allow_empty and not 1 <= len(versions) <= 16)
        or len(versions) > 16
    ):
        raise P2ReadBackendError("invalid_auth_context")
    checked: list[tuple[uuid.UUID, int]] = []
    for activity_id, version in versions.items():
        if (
            not isinstance(activity_id, uuid.UUID) or type(version) is not int
            or version < 0 or version > 9_223_372_036_854_775_807
        ):
            raise P2ReadBackendError("invalid_auth_context")
        checked.append((activity_id, version))
    return tuple(sorted(checked, key=lambda pair: str(pair[0])))


def _criteria_type_for_operation(operation: Any) -> type[Any]:
    mapping = {
        pc.P2ReadOperation.ACTIVITIES: pc.ActivityCriteria,
        pc.P2ReadOperation.EXPENSES: pc.ExpenseCriteria,
        pc.P2ReadOperation.DEBTS: pc.DebtCriteria,
        pc.P2ReadOperation.REFUND_EVENTS: pc.RefundEventCriteria,
        pc.P2ReadOperation.PREPAYMENT_ACCOUNTS: pc.PrepaymentAccountsCriteria,
        pc.P2ReadOperation.PREPAYMENT_USAGES: pc.PrepaymentUsagesCriteria,
        pc.P2ReadOperation.PREPAYMENT_RETURN_EVENTS: pc.PrepaymentReturnCriteria,
    }
    try:
        return mapping[operation]
    except (KeyError, TypeError):
        raise P2ReadBackendError("unsupported_read") from None


def _criteria_sha(criteria: Any) -> str:
    if not isinstance(criteria, pc.P2WireModel):
        raise P2ReadBackendError("unsupported_read")
    return pc.p2_criteria_digest(criteria)


def _row_uuid(row: Mapping[str, Any], key: str) -> uuid.UUID:
    return v1._parse_uuid(row.get(key))


def _source_decimal(value: Any) -> Decimal:
    if type(value) not in (str, int, Decimal):
        raise P2ReadBackendError("invalid_upstream_response")
    try:
        result = Decimal(str(value))
    except Exception:
        raise P2ReadBackendError("invalid_upstream_response") from None
    if not result.is_finite():
        raise P2ReadBackendError("invalid_upstream_response")
    return result


def _source_numeric(
    value: Any, *, precision: int, scale: int, signed: bool = False,
) -> str:
    number = _source_decimal(value)
    text = format(number, "f")
    try:
        normalized = pc.parse_source_numeric_lexeme(text, precision=precision, scale=scale)
    except ValueError:
        raise P2ReadBackendError("invalid_upstream_response") from None
    if not signed and number < 0:
        raise P2ReadBackendError("invalid_upstream_response")
    return normalized


def _currency(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Z]{3}", value) is None:
        raise P2ReadBackendError("invalid_upstream_response")
    return value


def _source_datetime(value: Any, *, allow_null: bool = False) -> datetime | None:
    if value is None and allow_null:
        return None
    try:
        parsed = v1._parse_datetime(value)
    except v1.BackendReadError:
        raise P2ReadBackendError("invalid_upstream_response") from None
    return parsed


def _uuid_list(values: Sequence[uuid.UUID]) -> str:
    if not values or any(not isinstance(item, uuid.UUID) for item in values):
        raise P2ReadBackendError("unsupported_scope")
    unique = tuple(sorted(set(values), key=str))
    return ",".join(str(item) for item in unique)


def _scoped_unit_ids(
    scope: v1.P2ResolvedScope, public_scope: pc.P2Scope,
    state: P2ReadTurnState,
) -> tuple[uuid.UUID, ...]:
    if scope.activity is None:
        return ()
    active_units = {
        item.ledger_unit_id for item in scope.ledger_units
        if item.activity_id == scope.activity.activity_id and not item.is_deleted
    }
    if public_scope.scope_kind == "ledger_unit":
        unit_id = state.resolve_entity(
            public_scope.ledger_unit_ref or "", "ledger_unit",
            activity_id=scope.activity.activity_id,
        ).entity_id
        if unit_id not in active_units:
            raise P2ReadBackendError("unsupported_scope")
        return (unit_id,)
    return tuple(sorted(active_units, key=str))


def _criteria_ref_id(
    state: P2ReadTurnState, criteria: Any, field_name: str, kind: str,
    activity_id: uuid.UUID,
) -> uuid.UUID | None:
    ref = getattr(criteria, field_name, None)
    if ref is None:
        return None
    return state.resolve_entity(ref, kind, activity_id=activity_id).entity_id


def _fact_opaque_ref(fact: Any) -> str:
    field_name = {
        "activity": "activity_ref", "expense": "expense_ref", "debt": "debt_ref",
        "refund_event": "refund_ref", "prepayment_account": "account_ref",
        "prepayment_usage": "usage_ref", "prepayment_return_event": "return_event_ref",
    }.get(getattr(fact, "fact_kind", None))
    if field_name is None:
        raise P2ReadBackendError("invalid_upstream_response")
    return getattr(fact, field_name)


def _random_ref(prefix: str = "ref_") -> str:
    if prefix not in {"ref_", "qev_"}:
        raise ValueError("unsupported opaque reference namespace")
    return prefix + secrets.token_urlsafe(24)


def _request_url_sha(url: str) -> str:
    parsed = urlsplit(url)
    # The encoded URL can contain private IDs. Only its digest is retained.
    return hashlib.sha256((parsed.path + "?" + parsed.query).encode("utf-8")).hexdigest()


def _canonical_sha(value: Any) -> str:
    def normal(item: Any) -> Any:
        if isinstance(item, uuid.UUID):
            return str(item)
        if isinstance(item, Decimal):
            return format(item, "f")
        if isinstance(item, datetime):
            return _utc(item)
        if isinstance(item, Mapping):
            return {str(k): normal(v) for k, v in sorted(item.items(), key=lambda pair: str(pair[0]))}
        if isinstance(item, (tuple, list)):
            return [normal(v) for v in item]
        return item
    payload = json.dumps(normal(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _chain_hash(hashes: Sequence[str]) -> str:
    return _canonical_sha(tuple(hashes))


def _utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise P2ReadBackendError("invalid_upstream_response")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
