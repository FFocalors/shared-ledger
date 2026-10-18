"""Strict, source-only codec for the disabled P2 v3 read candidate.

This module parses captured PostgREST bytes and deterministically projects the
seven v3 read operations.  It has no transport, authority, Store, or persistence
implementation.  A well-formed witness is only a local shape object; live Auth,
RLS, scope currentness, and Store acceptance remain responsibilities of the
future Runtime/Store integration.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Mapping, Protocol, Sequence

from . import p2_read_contracts_v3 as pc


MAX_ROWS_PER_PAGE = 16
MAX_PAGES_PER_TABLE = 4
MAX_ROWS_PER_TABLE = MAX_ROWS_PER_PAGE * MAX_PAGES_PER_TABLE
MAX_SOURCE_PAGES_PER_CAPTURE_CHAIN = 32
MAX_UI_EXPENSE_SELECTION = 32
MAX_FACTS_PER_PAGE = 16
MAX_FACTS_PER_QUERY = 64
MAX_FACTS_PER_CONTEXT = 256
MAX_RESPONSE_BYTES = 1_048_576
MAX_TURN_RESPONSE_BYTES = 4_194_304
MAX_GETS_PER_TURN = 48
MAX_BACKEND_US_PER_TURN = 20_000_000
MAX_ACTIVE_US_PER_TURN = 240_000_000

_CONTENT_RANGE = re.compile(r"^(?:(?P<start>0|[1-9][0-9]*)-(?P<end>0|[1-9][0-9]*)|\*)/(?P<total>0|[1-9][0-9]*|\*)$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_ISO_TIME = re.compile(r"^\d{4}-\d\d-\d\d[Tt ]\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$")
_SOURCE_COLUMNS: dict[str, tuple[str, ...]] = {
    "activities": ("id", "name", "type", "base_currency", "multi_currency_enabled", "is_deleted", "archived_at", "financial_version", "updated_at"),
    "activity_members": ("activity_id", "user_id"),
    "ledger_units": ("id", "activity_id", "name", "type", "is_deleted", "participant_scope_configured", "updated_at"),
    "participants": ("id", "activity_id", "name", "participant_order", "is_deleted", "updated_at"),
    "sub_activity_participants": ("activity_id", "ledger_unit_id", "participant_id"),
    "participant_claims": ("id", "activity_id", "participant_id", "user_id", "claimed_at"),
    "expenses": ("id", "ledger_unit_id", "title", "original_amount", "original_currency", "fx_rate", "base_amount", "occurred_at", "original_expense_id", "version", "is_deleted", "financial_locked"),
    "payments": ("id", "expense_id", "participant_id", "amount", "base_amount"),
    "splits": ("id", "expense_id", "participant_id", "amount", "base_amount"),
    "expense_debts": ("id", "activity_id", "ledger_unit_id", "expense_id", "debtor_participant_id", "creditor_participant_id", "amount", "original_amount", "original_currency", "fx_rate", "created_at"),
    "prepayment_accounts": ("id", "activity_id", "owner_participant_id", "custodian_participant_id", "currency", "balance", "updated_at"),
    "prepayment_usages": ("id", "activity_id", "account_id", "expense_debt_id", "gross_amount", "amount", "created_at", "prepayment_currency", "prepayment_amount", "debt_currency", "debt_amount", "base_amount", "bill_fx_rate", "bill_occurred_at"),
    "transfers": ("id", "activity_id", "from_participant_id", "to_participant_id", "type", "amount", "currency", "occurred_at", "is_voided"),
    "transfer_components": ("id", "activity_id", "transfer_id", "component_type", "amount", "created_at"),
}
_NUMERIC_COLUMNS: dict[str, dict[str, tuple[int, int, bool]]] = {
    "expenses": {"original_amount": (20, 4, False), "fx_rate": (20, 10, False), "base_amount": (20, 1, False)},
    "payments": {"amount": (20, 4, False), "base_amount": (20, 1, True)},
    "splits": {"amount": (20, 4, False), "base_amount": (20, 1, True)},
    "expense_debts": {"amount": (20, 1, False), "original_amount": (20, 4, True), "fx_rate": (20, 10, True)},
    "prepayment_accounts": {"balance": (20, 4, False)},
    "prepayment_usages": {"gross_amount": (20, 4, False), "amount": (20, 4, False), "prepayment_amount": (20, 4, False), "debt_amount": (20, 4, False), "base_amount": (20, 1, True), "bill_fx_rate": (20, 10, True)},
    # Transfers and their components are numeric(20,4); the prepayment return
    # contract exposes that source precision without deriving a base value.
    "transfers": {"amount": (20, 4, False)},
    "transfer_components": {"amount": (20, 4, False)},
}
_UUID_COLUMNS: dict[str, frozenset[str]] = {
    "activities": frozenset({"id"}), "activity_members": frozenset({"activity_id", "user_id"}),
    "ledger_units": frozenset({"id", "activity_id"}), "participants": frozenset({"id", "activity_id"}),
    "sub_activity_participants": frozenset({"activity_id", "ledger_unit_id", "participant_id"}),
    "participant_claims": frozenset({"id", "activity_id", "participant_id", "user_id"}),
    "expenses": frozenset({"id", "ledger_unit_id"}),
    "payments": frozenset({"id", "expense_id", "participant_id"}),
    "splits": frozenset({"id", "expense_id", "participant_id"}),
    "expense_debts": frozenset({"id", "activity_id", "ledger_unit_id", "expense_id", "debtor_participant_id", "creditor_participant_id"}),
    "prepayment_accounts": frozenset({"id", "activity_id", "owner_participant_id", "custodian_participant_id"}),
    "prepayment_usages": frozenset({"id", "activity_id", "account_id", "expense_debt_id"}),
    "transfers": frozenset({"id", "activity_id", "from_participant_id", "to_participant_id"}),
    "transfer_components": frozenset({"id", "activity_id", "transfer_id"}),
}
_NULLABLE_UUID_COLUMNS = {"expenses": frozenset({"original_expense_id"})}
_TIME_COLUMNS = {
    "activities": {"archived_at": True, "updated_at": False},
    "ledger_units": {"updated_at": False}, "participants": {"updated_at": False},
    "participant_claims": {"claimed_at": False}, "expenses": {"occurred_at": False},
    "expense_debts": {"created_at": False}, "prepayment_accounts": {"updated_at": False},
    "prepayment_usages": {"created_at": False, "bill_occurred_at": True},
    "transfers": {"occurred_at": False}, "transfer_components": {"created_at": False},
}
_BOOL_COLUMNS = {
    "activities": frozenset({"multi_currency_enabled", "is_deleted"}),
    "ledger_units": frozenset({"is_deleted", "participant_scope_configured"}),
    "participants": frozenset({"is_deleted"}), "expenses": frozenset({"is_deleted", "financial_locked"}),
    "transfers": frozenset({"is_voided"}),
}
_REQUIRED_TEXT_COLUMNS = {
    "activities": frozenset({"name", "type"}),
    "ledger_units": frozenset({"name", "type"}),
    "participants": frozenset({"name"}),
    "expenses": frozenset({"title", "original_currency"}),
    "expense_debts": frozenset(),
    "prepayment_accounts": frozenset({"currency"}),
    "prepayment_usages": frozenset({"prepayment_currency", "debt_currency"}),
    "transfers": frozenset({"type", "currency"}),
    "transfer_components": frozenset({"component_type"}),
}
_INT_COLUMNS = {
    "activities": {"financial_version": 0}, "participants": {"participant_order": 0},
    "expenses": {"version": 1},
}


class SourceCodecError(ValueError):
    """A source response is not safe to project into v3 facts."""


class P2V3DispatchStateUncertain(RuntimeError):
    """A durable dispatch transition could not be classified safely."""


class JsonNumber(str):
    """Exact JSON number token returned by ``json.loads`` callbacks."""


@dataclass(frozen=True, slots=True)
class V3ExecutionIdentity:
    owner_user_id: uuid.UUID
    turn_id: uuid.UUID
    generation: int
    input_seq: int
    input_digest: str
    claim_epoch: int
    authority_epoch: int
    context_revision: int


@dataclass(frozen=True, slots=True)
class AdmissionOnlyBinding:
    """Short-lived private Store call carrier; secret is never copied to a witness."""

    identity: V3ExecutionIdentity
    admission_id: str
    claim_token: str = field(repr=False, compare=False)
    # Store-issued request-local prospective refs. They confer no authority;
    # the Store accepts them only after reparsing and validating source bytes.
    reference_registry: Any = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class QueryAttemptBinding:
    identity: V3ExecutionIdentity
    logical_query_id: str
    query_attempt_id: str
    page_index: int
    claim_token: str = field(repr=False, compare=False)


SourceBinding = AdmissionOnlyBinding | QueryAttemptBinding


@dataclass(frozen=True, slots=True)
class V3QueryDescriptor:
    request: pc.P2ReadQueryRequest
    ui_expense_ids: tuple[uuid.UUID, ...] = field(default=(), repr=False)
    ui_expense_refs: tuple[str, ...] = field(default=(), repr=False)
    public_request_digest: str = ""
    normalized_selection_digest: str = ""

    def __post_init__(self) -> None:
        if type(self.ui_expense_ids) is not tuple or any(type(item) is not uuid.UUID for item in self.ui_expense_ids):
            raise ValueError("UI expense selections must be a tuple of UUIDs")
        if len(self.ui_expense_ids) > MAX_UI_EXPENSE_SELECTION or len(set(self.ui_expense_ids)) != len(self.ui_expense_ids):
            raise ValueError("UI expense selection exceeds its unique-item bound")
        object.__setattr__(self, "ui_expense_ids", tuple(sorted(self.ui_expense_ids, key=str)))
        if (
            type(self.ui_expense_refs) is not tuple
            or len(self.ui_expense_refs) > MAX_UI_EXPENSE_SELECTION
            or any(type(item) is not str or re.fullmatch(r"ref_[A-Za-z0-9_-]{22,64}", item) is None for item in self.ui_expense_refs)
            or len(set(self.ui_expense_refs)) != len(self.ui_expense_refs)
        ):
            raise ValueError("UI expense opaque refs must be a bounded unique tuple")
        object.__setattr__(self, "ui_expense_refs", tuple(sorted(self.ui_expense_refs)))


class P2V3BudgetPort(Protocol):
    """Future Store-backed accounting seam; CPU tests use explicitly fake ports."""

    def remaining_limits(
        self, binding: SourceBinding, *, logical_query_id: str | None = None,
        capture_chain_id: str | None = None, table: str | None = None,
    ) -> "RemainingBudget": ...

    def reserve_get(
        self, binding: SourceBinding, *, source_role: str, request_digest: str,
        active_limit_us: int, backend_limit_us: int, response_bytes_limit: int,
        logical_query_id: str | None = None, capture_chain_id: str | None = None,
        table: str | None = None,
    ) -> str: ...

    def mark_dispatch_started(self, binding: SourceBinding, reservation_id: str) -> None: ...

    def settle_get(
        self, binding: SourceBinding, reservation_id: str, *,
        outcome: Literal["actual", "known_no_dispatch", "unknown"],
        actual_active_us: int, actual_backend_us: int, actual_response_bytes: int,
        raw_body_sha256: str | None,
    ) -> None: ...

    def record_cost_only_capture(
        self, binding: SourceBinding, reservation_id: str, *, http_status: int,
        content_range: str | None, returned_count: int, response_bytes: int,
        raw_body_sha256: str, observed_at: datetime,
    ) -> str: ...

    def reserve_processing(
        self, binding: SourceBinding, *, active_limit_us: int, backend_limit_us: int,
    ) -> str: ...

    def settle_processing(
        self, binding: SourceBinding, reservation_id: str, *,
        actual_active_us: int, actual_backend_us: int,
    ) -> None: ...


class P2V3LocatorPort(Protocol):
    """Store-private identity lookup only; this cannot create source authority."""

    def bind_entity(
        self, kind: str, entity_id: uuid.UUID, *, activity_id: uuid.UUID,
        ledger_unit_id: uuid.UUID | None = None,
    ) -> str: ...

    def resolve_entity(
        self, opaque_ref: str, kind: str, *, activity_id: uuid.UUID,
    ) -> uuid.UUID: ...

    def bind_capture(self, capture_id: str, *, identity: V3ExecutionIdentity) -> str: ...

    def resolve_principal(self, principal_ref: str) -> uuid.UUID: ...

    def owner_turn_ref(self, *, identity: V3ExecutionIdentity) -> str: ...

    def resolve_activity_ref(self, activity_ref: str) -> uuid.UUID: ...

    def query_ref(self, logical_query_id: str, *, identity: V3ExecutionIdentity) -> str: ...

    def source_ref(self, logical_query_id: str, *, identity: V3ExecutionIdentity, source_kind: str) -> str: ...

    def load_query_descriptor(self, query_ref: str, *, identity: V3ExecutionIdentity) -> V3QueryDescriptor: ...

    def query_evidence_ref(self, logical_query_id: str, attempt_id: str, *, identity: V3ExecutionIdentity, page_index: int) -> str: ...

    def result_ref(self, logical_query_id: str, attempt_id: str, *, identity: V3ExecutionIdentity, page_index: int) -> str: ...

    def criteria_ref(self, criteria_digest: str, *, identity: V3ExecutionIdentity) -> str: ...

    def issue_continuation(
        self, *, query_ref: str, attempt_id: str, page_index: int,
        qev_ref: str, expires_at: datetime, source_proof: "V3ContinuationProof",
    ) -> str: ...

    def load_continuation_proof(
        self, *, query_ref: str, next_page_ref: str, identity: V3ExecutionIdentity,
    ) -> "V3ContinuationProof": ...

    def consume_continuation(
        self, *, query_ref: str, next_page_ref: str, turn_id: uuid.UUID,
    ) -> QueryAttemptBinding: ...


@dataclass(frozen=True, slots=True)
class CapturedPageWitness:
    """Secret-free identity/cost binding for one captured HTTP response."""

    owner_user_id: uuid.UUID
    turn_id: uuid.UUID
    generation: int
    input_seq: int
    input_digest: str
    claim_epoch: int
    authority_epoch: int
    context_revision: int
    binding_kind: Literal["admission", "query_attempt"]
    admission_id: str | None
    logical_query_id: str | None
    query_attempt_id: str | None
    page_index: int | None
    source_role: str
    reservation_id: str
    capture_id: str
    request_sha256: str
    response_sha256: str
    response_bytes: int
    http_status: int
    content_range: str | None
    observed_at: datetime
    elapsed_us: int


@dataclass(frozen=True, slots=True)
class V3ContinuationProof:
    """Secret-free prior attempt binding used only to reject stale page chains."""

    logical_query_id: str
    query_attempt_id: str
    page_index: int
    query_evidence_ref: str
    query_digest: str
    body_digest: str
    projection_digest: str
    normalized_criteria_digest: str
    source_total: int | None
    financial_versions_digest: str
    source_query_complete: bool

    def __post_init__(self) -> None:
        if (
            type(self.logical_query_id) is not str or not self.logical_query_id
            or type(self.query_attempt_id) is not str or not self.query_attempt_id
            or type(self.page_index) is not int or self.page_index < 0
            or type(self.query_evidence_ref) is not str or not self.query_evidence_ref
            or any(re.fullmatch(r"[0-9a-f]{64}", value or "") is None for value in (
                self.query_digest, self.body_digest, self.projection_digest,
                self.normalized_criteria_digest, self.financial_versions_digest,
            ))
            or (self.source_total is not None and (type(self.source_total) is not int or self.source_total < 0))
            or type(self.source_query_complete) is not bool
        ):
            raise ValueError("invalid continuation proof")


@dataclass(frozen=True, slots=True)
class TransientCapturedPage:
    witness: CapturedPageWitness
    raw_body: bytes = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class P2V3ScopeMetadataProjection:
    current_actor: pc.P2CurrentActorBinding | None
    source_labels: tuple[pc.P2EntityDisplayLabel, ...]
    snapshot: SourceSnapshot = field(repr=False)
    snapshot_digest: str
    # Cost-only wire captures are included for private freshness comparison,
    # not represented as accepted source proof or persisted output.
    captures: tuple[CapturedPageWitness, ...] = field(default=(), repr=False)
    reference_registry: Any = field(default=None, repr=False, compare=False)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SourceCodecError("duplicate_json_key")
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise SourceCodecError("non_finite_json_constant")


def parse_source_rows(raw: bytes, table: str) -> tuple[Mapping[str, Any], ...]:
    """Decode exact response bytes; keep decimals as JSON string lexemes.

    Both JSON numbers and string-encoded numerics are validated as their exact
    decimal lexeme. No Python float is constructed.
    """
    if type(raw) is not bytes or len(raw) > MAX_RESPONSE_BYTES:
        raise SourceCodecError("response_byte_bound")
    expected = _SOURCE_COLUMNS.get(table)
    if expected is None:
        raise SourceCodecError("source_table_not_allowlisted")
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            parse_float=JsonNumber,
            parse_int=JsonNumber,
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        if isinstance(exc, SourceCodecError):
            raise
        raise SourceCodecError("invalid_source_json") from None
    if type(payload) is not list or any(type(row) is not dict for row in payload):
        raise SourceCodecError("source_root_must_be_row_array")
    for row in payload:
        if set(row) != set(expected):
            raise SourceCodecError("source_row_columns_mismatch")
        if any(type(value) in (dict, list) for value in row.values()):
            raise SourceCodecError("nested_source_value")
        for column in _UUID_COLUMNS.get(table, ()):
            _validate_uuid_value(row.get(column), nullable=False)
        for column in _NULLABLE_UUID_COLUMNS.get(table, ()):
            _validate_uuid_value(row.get(column), nullable=True)
        for column, (precision, scale, nullable) in _NUMERIC_COLUMNS.get(table, {}).items():
            _validate_numeric_value(row.get(column), precision=precision, scale=scale, nullable=nullable)
        for column, nullable in _TIME_COLUMNS.get(table, {}).items():
            _validate_time_value(row.get(column), nullable=nullable)
        for column in _BOOL_COLUMNS.get(table, ()):
            if type(row.get(column)) is not bool:
                raise SourceCodecError("invalid_source_boolean")
        for column, minimum in _INT_COLUMNS.get(table, {}).items():
            _validate_integer_value(row.get(column), minimum=minimum)
        text_columns = {
            "activities": {"name", "type", "base_currency"},
            "ledger_units": {"name", "type"}, "participants": {"name"},
            "expenses": {"title", "original_currency"}, "expense_debts": {"original_currency"},
            "prepayment_accounts": {"currency"}, "prepayment_usages": {"prepayment_currency", "debt_currency"},
            "transfers": {"type", "currency"}, "transfer_components": {"component_type"},
        }.get(table, set())
        for column in text_columns:
            value = row.get(column)
            if value is not None and (type(value) is not str or len(value) > 200):
                raise SourceCodecError("invalid_source_text")
            if value is None and column in _REQUIRED_TEXT_COLUMNS.get(table, frozenset()):
                raise SourceCodecError("missing_required_source_text")
        for column in {"name", "type", "title", "component_type"}:
            if column in row and row[column] is not None and (not row[column].strip() or len(row[column]) > 200):
                raise SourceCodecError("invalid_source_text")
        for column in {"base_currency", "original_currency", "currency", "prepayment_currency", "debt_currency"}:
            if column in row and row[column] is not None and _CURRENCY.fullmatch(row[column]) is None:
                raise SourceCodecError("invalid_source_currency")
    return tuple(payload)


def _validate_uuid_value(value: Any, *, nullable: bool) -> None:
    if value is None and nullable:
        return
    if type(value) is not str:
        raise SourceCodecError("invalid_uuid_source_value")
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        raise SourceCodecError("invalid_uuid_source_value") from None
    if str(parsed) != value.lower():
        raise SourceCodecError("noncanonical_uuid_source_value")


def _number_lexeme(value: Any, *, nullable: bool) -> str | None:
    if value is None and nullable:
        return None
    if type(value) in (JsonNumber, str):
        return str(value)
    raise SourceCodecError("invalid_source_numeric_type")


def _validate_numeric_value(value: Any, *, precision: int, scale: int, nullable: bool) -> None:
    raw = _number_lexeme(value, nullable=nullable)
    if raw is not None:
        try:
            pc.parse_source_numeric_lexeme(raw, precision=precision, scale=scale)
        except ValueError:
            raise SourceCodecError("invalid_source_numeric_lexeme") from None


def _validate_integer_value(value: Any, *, minimum: int) -> int:
    if type(value) is JsonNumber:
        if re.fullmatch(r"(?:0|[1-9][0-9]*)", value) is None:
            raise SourceCodecError("invalid_source_integer")
        result = int(value)
    elif type(value) is int:
        result = value
    else:
        raise SourceCodecError("invalid_source_integer")
    if not minimum <= result <= pc.MAX_FINANCIAL_VERSION:
        raise SourceCodecError("invalid_source_integer")
    return result


def _validate_time_value(value: Any, *, nullable: bool) -> None:
    if value is None and nullable:
        return
    if type(value) is not str or _ISO_TIME.fullmatch(value) is None:
        raise SourceCodecError("invalid_source_timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise SourceCodecError("invalid_source_timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SourceCodecError("naive_source_timestamp")


@dataclass(frozen=True, slots=True)
class ParsedRange:
    offset: int
    row_count: int
    total: int | None
    total_known: bool
    contiguous: bool
    complete: bool


def parse_content_range(header: str | None, *, expected_offset: int, row_count: int, status: int) -> ParsedRange:
    if type(expected_offset) is not int or expected_offset < 0 or type(row_count) is not int or not 0 <= row_count <= MAX_ROWS_PER_PAGE:
        raise SourceCodecError("invalid_range_input")
    if type(status) is not int or status not in (200, 206):
        raise SourceCodecError("invalid_http_status")
    match = _CONTENT_RANGE.fullmatch(header or "")
    if match is None:
        raise SourceCodecError("invalid_content_range")
    total_text = match.group("total")
    total = None if total_text == "*" else int(total_text)
    first_text, last_text = match.group("start"), match.group("end")
    if first_text is None or last_text is None:
        if row_count != 0:
            raise SourceCodecError("range_does_not_bind_rows")
        if total == 0 and expected_offset == 0:
            return ParsedRange(0, 0, 0, True, True, True)
        if total is not None and total != expected_offset:
            raise SourceCodecError("empty_range_total_mismatch")
        return ParsedRange(expected_offset, 0, total, total is not None, True, total is not None)
    first, last = int(first_text), int(last_text)
    if first != expected_offset or last < first or last - first + 1 != row_count:
        raise SourceCodecError("non_contiguous_content_range")
    if total is not None and (total == 0 or last >= total):
        raise SourceCodecError("range_outside_source_total")
    complete = total is not None and last + 1 == total
    if row_count == 0:
        raise SourceCodecError("empty_page_requires_zero_range")
    return ParsedRange(first, row_count, total, total is not None, True, complete)


@dataclass(frozen=True, slots=True)
class SourcePage:
    table: str
    rows: tuple[Mapping[str, Any], ...] = field(repr=False)
    range: ParsedRange
    offset: int
    status: int
    content_range: str
    request_sha256: str
    # Retained only in the in-memory pending attempt so Store can independently
    # check the server-built request plan against this exact capture. It must
    # never be persisted or included in a public/model DTO.
    request_url: str = field(repr=False, compare=False)
    raw_body_sha256: str
    observed_at: datetime
    elapsed_us: int
    reservation_id: str
    witness: CapturedPageWitness = field(repr=False)
    raw_body: bytes = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class SourceTable:
    table: str
    rows: tuple[Mapping[str, Any], ...] = field(repr=False)
    pages: tuple[SourcePage, ...] = field(repr=False)
    source_total: int | None
    complete: bool
    range_contiguous: bool
    unique_items_verified: bool
    source_digest: str


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    """Fresh rows captured through the v3 adapter; source UUIDs are private."""

    activity_id: uuid.UUID = field(repr=False)
    activity_ref: str
    activity: Mapping[str, Any] = field(repr=False)
    ledger_units: tuple[Mapping[str, Any], ...] = field(repr=False)
    participants: tuple[Mapping[str, Any], ...] = field(repr=False)
    child_rows: tuple[Mapping[str, Any], ...] = field(repr=False)
    claims: tuple[Mapping[str, Any], ...] = field(repr=False)
    membership_rows: tuple[Mapping[str, Any], ...] = field(default=(), repr=False)
    scope_ref: str | None = None
    scope_kind: Literal["activity", "ledger_unit"] = "activity"
    ledger_unit_id: uuid.UUID | None = field(default=None, repr=False)
    witnesses: tuple[SourcePage, ...] = field(default=(), repr=False)


class ReferenceBinder(Protocol):
    """Opaque locator interface. Implementations must be Store-backed in use."""

    def bind_entity(
        self, kind: str, entity_id: uuid.UUID, *, activity_id: uuid.UUID,
        ledger_unit_id: uuid.UUID | None = None,
    ) -> str: ...

    def resolve_entity(
        self, opaque_ref: str, kind: str, *, activity_id: uuid.UUID,
    ) -> uuid.UUID: ...

    def bind_capture(self, capture_id: str, *, identity: V3ExecutionIdentity) -> str: ...


@dataclass(frozen=True, slots=True)
class RemainingBudget:
    active_us: int
    backend_us: int
    response_bytes: int
    get_attempts: int
    turn_remaining_us: int
    capture_chain_pages: int = 0
    capture_chain_table_pages: int = 0

    def __post_init__(self) -> None:
        values = (
            self.active_us, self.backend_us, self.response_bytes, self.get_attempts,
            self.turn_remaining_us, self.capture_chain_pages, self.capture_chain_table_pages,
        )
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("remaining budget values must be nonnegative integers")


def _uuid(row: Mapping[str, Any], key: str) -> uuid.UUID:
    value = row.get(key)
    if type(value) is not str:
        raise SourceCodecError("invalid_uuid_source_value")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        raise SourceCodecError("invalid_uuid_source_value") from None
    if str(parsed) != value.lower():
        raise SourceCodecError("noncanonical_uuid_source_value")
    return parsed


def _text(row: Mapping[str, Any], key: str, *, max_len: int = 200, allow_empty: bool = False) -> str:
    value = row.get(key)
    if type(value) is not str or len(value) > max_len or (not allow_empty and not value.strip()):
        raise SourceCodecError("invalid_source_text")
    return value


def _bool(row: Mapping[str, Any], key: str) -> bool:
    value = row.get(key)
    if type(value) is not bool:
        raise SourceCodecError("invalid_source_boolean")
    return value


def _integer(row: Mapping[str, Any], key: str, *, minimum: int = 0, maximum: int = 2**63 - 1) -> int:
    value = row.get(key)
    if type(value) is JsonNumber and re.fullmatch(r"(?:0|[1-9][0-9]*)", value):
        value = int(value)
    if type(value) is not int or value < minimum or value > maximum:
        raise SourceCodecError("invalid_source_integer")
    return value


def _numeric(row: Mapping[str, Any], key: str, *, precision: int, scale: int, nullable: bool = False, signed: bool = False) -> str | None:
    value = row.get(key)
    if value is None and nullable:
        return None
    if type(value) not in (str, JsonNumber):
        raise SourceCodecError("numeric_value_must_be_string")
    value = str(value)
    if signed:
        return pc.parse_source_numeric_lexeme(value, precision=precision, scale=scale)
    parsed = pc.parse_source_numeric_lexeme(value, precision=precision, scale=scale)
    if Decimal(parsed) < 0:
        raise SourceCodecError("negative_source_amount")
    return parsed


def _currency(row: Mapping[str, Any], key: str, *, nullable: bool = False) -> str | None:
    value = row.get(key)
    if value is None and nullable:
        return None
    if type(value) is not str or _CURRENCY.fullmatch(value) is None:
        raise SourceCodecError("invalid_source_currency")
    return value


def _time(row: Mapping[str, Any], key: str, *, nullable: bool = False) -> datetime | None:
    value = row.get(key)
    if value is None and nullable:
        return None
    if type(value) is not str or _ISO_TIME.fullmatch(value) is None:
        raise SourceCodecError("invalid_source_timestamp")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise SourceCodecError("invalid_source_timestamp") from None
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise SourceCodecError("naive_source_timestamp")
    return dt.astimezone(timezone.utc)


def stable_digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def source_table(rows: Sequence[Mapping[str, Any]], pages: Sequence[SourcePage], *, table: str) -> SourceTable:
    if table not in _SOURCE_COLUMNS:
        raise SourceCodecError("source_table_not_allowlisted")
    ordered = tuple(rows)
    flattened = tuple(row for page in pages for row in page.rows)
    if ordered != flattened:
        raise SourceCodecError("page_rows_do_not_match_table_rows")
    expected_offset = 0
    for page in pages:
        if page.table != table or page.offset != expected_offset:
            raise SourceCodecError("source_page_chain_mismatch")
        expected_offset += page.range.row_count
    seen: set[str] = set()
    unique_field = "activity_id" if table == "activity_members" else "id"
    if table == "sub_activity_participants":
        keys = [(_uuid(row, "ledger_unit_id"), _uuid(row, "participant_id")) for row in ordered]
        if len(keys) != len(set(keys)):
            raise SourceCodecError("duplicate_source_identity")
        unique = True
    else:
        for row in ordered:
            value = row.get(unique_field)
            if type(value) is not str or value in seen:
                raise SourceCodecError("duplicate_source_identity")
            seen.add(value)
        if table == "transfer_components":
            transfer_kinds = [(_uuid(row, "transfer_id"), _text(row, "component_type")) for row in ordered]
            if len(transfer_kinds) != len(set(transfer_kinds)):
                raise SourceCodecError("duplicate_transfer_component_identity")
        unique = True
    totals = {page.range.total for page in pages if page.range.total_known}
    if len(totals) > 1:
        raise SourceCodecError("source_total_changed_between_pages")
    total = next(iter(totals)) if totals else None
    complete = bool(pages) and all(page.range.contiguous for page in pages) and total is not None and len(ordered) == total
    if len(ordered) > MAX_ROWS_PER_TABLE or len(pages) > MAX_PAGES_PER_TABLE:
        raise SourceCodecError("source_table_bound_exceeded")
    if total is not None and len(ordered) > total:
        raise SourceCodecError("source_row_count_exceeds_total")
    return SourceTable(
        table=table, rows=ordered, pages=tuple(pages), source_total=total,
        complete=complete, range_contiguous=bool(pages) and all(page.range.contiguous for page in pages),
        unique_items_verified=unique, source_digest=stable_digest([dict(row) for row in ordered]),
    )


def scope_metadata_is_current(
    before: SourceSnapshot, after: SourceSnapshot, *, compare_claims: bool = True,
) -> bool:
    """Compare exact independent source fences, not Activity FV alone."""
    if before.activity_id != after.activity_id or before.activity_ref != after.activity_ref:
        return False
    activity_fields = (
        "name", "type", "base_currency", "multi_currency_enabled", "is_deleted", "archived_at",
    )
    if (
        _integer(before.activity, "financial_version") != _integer(after.activity, "financial_version")
        or _time(before.activity, "updated_at") != _time(after.activity, "updated_at")
        or any(before.activity.get(field) != after.activity.get(field) for field in activity_fields)
    ):
        return False
    if before.scope_kind != after.scope_kind or before.ledger_unit_id != after.ledger_unit_id:
        return False

    def participant_rows(rows: Sequence[Mapping[str, Any]]) -> tuple[tuple[Any, ...], ...]:
        return tuple(sorted((
            str(_uuid(row, "id")), str(_uuid(row, "activity_id")), _text(row, "name"),
            _integer(row, "participant_order"), _time(row, "updated_at"), _bool(row, "is_deleted"),
        ) for row in rows))

    def unit_rows(rows: Sequence[Mapping[str, Any]]) -> tuple[tuple[Any, ...], ...]:
        return tuple(sorted((
            str(_uuid(row, "id")), str(_uuid(row, "activity_id")), _text(row, "name"),
            _text(row, "type"), _bool(row, "participant_scope_configured"),
            _time(row, "updated_at"), _bool(row, "is_deleted"),
        ) for row in rows))

    if participant_rows(before.participants) != participant_rows(after.participants):
        return False
    if unit_rows(before.ledger_units) != unit_rows(after.ledger_units):
        return False
    def child_set(rows: Sequence[Mapping[str, Any]]) -> tuple[tuple[str, str, str], ...]:
        return tuple(sorted((str(_uuid(row, "activity_id")), str(_uuid(row, "ledger_unit_id")), str(_uuid(row, "participant_id"))) for row in rows))
    if child_set(before.child_rows) != child_set(after.child_rows):
        return False

    def actor(rows: Sequence[Mapping[str, Any]]) -> tuple[tuple[str, str, str, str, datetime], ...]:
        return tuple(sorted((
            str(_uuid(row, "id")), str(_uuid(row, "activity_id")),
            str(_uuid(row, "participant_id")), str(_uuid(row, "user_id")), _time(row, "claimed_at"),
        ) for row in rows))
    return not compare_claims or actor(before.claims) == actor(after.claims)


def project_scope_metadata(
    snapshot: SourceSnapshot,
    principal_user_id: uuid.UUID,
    *,
    binder: ReferenceBinder,
    identity: V3ExecutionIdentity,
) -> P2V3ScopeMetadataProjection:
    """Build candidate actor/labels from exact captured metadata rows.

    Membership and row relationships are checked here, but this shape helper
    cannot independently prove the bearer, RLS, or Store receipt authenticity.
    """
    if type(principal_user_id) is not uuid.UUID:
        raise SourceCodecError("invalid_verified_principal")
    activity_id = snapshot.activity_id
    fv = _integer(snapshot.activity, "financial_version")
    if _uuid(snapshot.activity, "id") != activity_id or _bool(snapshot.activity, "is_deleted"):
        raise SourceCodecError("activity_snapshot_mismatch")
    memberships = snapshot.membership_rows
    if len(memberships) != 1:
        raise SourceCodecError("membership_not_unique")
    membership = memberships[0]
    if _uuid(membership, "activity_id") != activity_id or _uuid(membership, "user_id") != principal_user_id:
        raise SourceCodecError("membership_principal_mismatch")
    active_participant_rows = {
        _uuid(row, "id"): row for row in snapshot.participants if not _bool(row, "is_deleted")
    }
    active_units = {
        _uuid(row, "id"): row for row in snapshot.ledger_units if not _bool(row, "is_deleted")
    }
    if any(_uuid(row, "activity_id") != activity_id for row in (*snapshot.participants, *snapshot.ledger_units)):
        raise SourceCodecError("metadata_row_activity_mismatch")
    for relation in snapshot.child_rows:
        unit_id, participant_id = _uuid(relation, "ledger_unit_id"), _uuid(relation, "participant_id")
        if (
            _uuid(relation, "activity_id") != activity_id or unit_id not in active_units
            or active_units[unit_id].get("type") != "sub_activity"
            or participant_id not in active_participant_rows
        ):
            raise SourceCodecError("invalid_child_scope_metadata")

    def capture_ref(table: str, row: Mapping[str, Any], id_field: str = "id") -> tuple[str, datetime]:
        row_id = row.get(id_field)
        for page in snapshot.witnesses:
            if page.table != table:
                continue
            if any(item.get(id_field) == row_id for item in page.rows):
                return binder.bind_capture(page.witness.capture_id, identity=identity), page.observed_at
        raise SourceCodecError("metadata_row_without_captured_page")

    activity_capture_ref, activity_observed = capture_ref("activities", snapshot.activity)
    labels: list[pc.P2EntityDisplayLabel] = [pc.P2EntityDisplayLabel(
        entity_ref=binder.bind_entity("activity", activity_id, activity_id=activity_id),
        entity_kind="activity", scope_ref=snapshot.scope_ref or snapshot.activity_ref,
        display_name=_text(snapshot.activity, "name"), source_kind="activities",
        observed_at=activity_observed, scope_financial_version=fv,
        source_financial_version=fv, source_row_updated_at=None,
        source_receipt_ref=activity_capture_ref,
    )]
    # Activity-scope labels are public child scopes. The primary/root ledger
    # unit stays in the captured snapshot for factual reads, but must never be
    # exposed as a selectable child reference.
    unit_ids = {
        unit_id for unit_id, unit in active_units.items()
        if unit.get("type") == "sub_activity"
    }
    participant_ids = set(active_participant_rows)
    if snapshot.scope_kind == "ledger_unit":
        if (
            snapshot.ledger_unit_id is None or snapshot.ledger_unit_id not in active_units
            or active_units[snapshot.ledger_unit_id].get("type") != "sub_activity"
        ):
            raise SourceCodecError("current_child_scope_missing")
        unit_ids = {snapshot.ledger_unit_id}
        unit = active_units[snapshot.ledger_unit_id]
        if unit.get("participant_scope_configured") is True:
            participant_ids = {
                _uuid(row, "participant_id") for row in snapshot.child_rows
                if _uuid(row, "ledger_unit_id") == snapshot.ledger_unit_id
            }
    for unit_id in sorted(unit_ids, key=str):
        unit = active_units[unit_id]
        receipt_ref, observed = capture_ref("ledger_units", unit)
        labels.append(pc.P2EntityDisplayLabel(
            entity_ref=binder.bind_entity("ledger_unit", unit_id, activity_id=activity_id, ledger_unit_id=unit_id),
            entity_kind="ledger_unit", scope_ref=snapshot.scope_ref or snapshot.activity_ref,
            display_name=_text(unit, "name"), source_kind="ledger_units", observed_at=observed,
            scope_financial_version=fv, source_financial_version=None,
            source_row_updated_at=_time(unit, "updated_at"), source_receipt_ref=receipt_ref,
        ))
    if len(unit_ids) + len(participant_ids) + 1 > 128:
        raise SourceCodecError("metadata_label_bound_exceeded")
    for participant_id in sorted(participant_ids, key=str):
        participant = active_participant_rows[participant_id]
        receipt_ref, observed = capture_ref("participants", participant)
        labels.append(pc.P2EntityDisplayLabel(
            entity_ref=binder.bind_entity("participant", participant_id, activity_id=activity_id),
            entity_kind="participant", scope_ref=snapshot.scope_ref or snapshot.activity_ref,
            display_name=_text(participant, "name"), source_kind="participants", observed_at=observed,
            scope_financial_version=fv, source_financial_version=None,
            source_row_updated_at=_time(participant, "updated_at"), source_receipt_ref=receipt_ref,
        ))
    if len(snapshot.claims) > 1:
        raise SourceCodecError("current_actor_claim_not_unique")
    actor: pc.P2CurrentActorBinding | None = None
    if snapshot.claims:
        claim = snapshot.claims[0]
        participant_id = _uuid(claim, "participant_id")
        if (
            _uuid(claim, "activity_id") != activity_id or _uuid(claim, "user_id") != principal_user_id
            or participant_id not in active_participant_rows
        ):
            raise SourceCodecError("current_actor_claim_outside_active_roster")
        claim_receipt_ref, claim_observed = capture_ref("participant_claims", claim)
        actor_ref = binder.bind_entity("actor", principal_user_id, activity_id=activity_id)
        actor = pc.P2CurrentActorBinding(
            actor_ref=actor_ref, activity_ref=snapshot.activity_ref,
            participant_ref=binder.bind_entity("participant", participant_id, activity_id=activity_id),
            source_kind="participant_claims.current_auth_user", observed_at=claim_observed,
            scope_financial_version=fv, source_receipt_ref=claim_receipt_ref,
        )
    snapshot_digest = stable_digest({
        "activity": dict(snapshot.activity), "units": [dict(row) for row in snapshot.ledger_units],
        "participants": [dict(row) for row in snapshot.participants],
        "child": [dict(row) for row in snapshot.child_rows],
        "claims": [dict(row) for row in snapshot.claims],
        "membership": [dict(row) for row in snapshot.membership_rows],
    })
    return P2V3ScopeMetadataProjection(
        current_actor=actor, source_labels=tuple(labels), snapshot=snapshot,
        snapshot_digest=snapshot_digest,
        captures=tuple(page.witness for page in snapshot.witnesses),
        reference_registry=binder,
    )


def project_facts(
    operation: pc.P2ReadOperation,
    tables: Mapping[str, SourceTable],
    snapshot: SourceSnapshot | None,
    request: pc.P2ReadQueryRequest,
    *,
    query_evidence_ref: str,
    binder: ReferenceBinder,
    principal_user_id: uuid.UUID,
    context_version: str,
    authorized_expense_ids: frozenset[uuid.UUID] | None = None,
) -> tuple[pc.P2Fact, ...]:
    """Map complete, relation-checked source rows into v3 DTOs, without totals."""
    activity = snapshot.activity if snapshot is not None else None
    activity_id = snapshot.activity_id if snapshot is not None else None
    if operation is pc.P2ReadOperation.ACTIVITIES:
        result: list[pc.P2Fact] = []
        if "activity_members" not in tables:
            raise SourceCodecError("activity_membership_source_missing")
        if type(principal_user_id) is not uuid.UUID:
            raise SourceCodecError("invalid_verified_principal")
        if any(_uuid(row, "user_id") != principal_user_id for row in tables["activity_members"].rows):
            raise SourceCodecError("activity_membership_principal_mismatch")
        member_ids = {_uuid(row, "activity_id") for row in tables["activity_members"].rows}
        for row in tables["activities"].rows:
            act_id = _uuid(row, "id")
            if _bool(row, "is_deleted"):
                continue
            if act_id not in member_ids:
                raise SourceCodecError("activity_without_current_membership")
            name = _text(row, "name")
            archived = _time(row, "archived_at", nullable=True)
            status = "archived" if archived is not None else "active"
            criteria = request.criteria
            if criteria.status != "any" and criteria.status != status:
                continue
            if criteria.name_contains is not None and criteria.name_contains.casefold() not in name.casefold():
                continue
            ref = binder.bind_entity("activity", act_id, activity_id=act_id)
            observed = max((page.observed_at for page in tables["activities"].pages), default=None)
            if observed is None:
                raise SourceCodecError("activity_without_capture_observation")
            if type(context_version) is not str or not context_version.strip() or len(context_version) > 200:
                raise SourceCodecError("invalid_server_context_version")
            result.append(pc.ActivityFact(
                fact_kind="activity", activity_ref=ref, activity_kind=_text(row, "type"), name=name,
                base_currency=_currency(row, "base_currency", nullable=True), status=status,
                observed_at=observed, context_version=context_version, query_evidence_ref=query_evidence_ref,
            ))
        return tuple(result)

    if snapshot is None or activity is None or activity_id is None or request.scope is None:
        raise SourceCodecError("scoped_read_requires_fresh_scope_snapshot")
    if (
        request.profile_id != pc.P2_V3_CANDIDATE_PROFILE_ID
        or request.versions != pc.P2_V3_VERSIONS
        or snapshot.scope_ref != request.scope.scope_ref
        or snapshot.activity_ref != request.scope.activity_ref
        or request.criteria.activity_ref != snapshot.activity_ref
    ):
        raise SourceCodecError("request_scope_snapshot_binding_mismatch")
    scope_ref = request.scope.scope_ref
    active_participants = {
        _uuid(row, "id") for row in snapshot.participants if not _bool(row, "is_deleted")
    }
    units_by_id = {_uuid(row, "id"): row for row in snapshot.ledger_units if not _bool(row, "is_deleted")}
    child_members: dict[uuid.UUID, set[uuid.UUID]] = {}
    for row in snapshot.child_rows:
        unit_id = _uuid(row, "ledger_unit_id")
        participant_id = _uuid(row, "participant_id")
        if _uuid(row, "activity_id") != activity_id or unit_id not in units_by_id or participant_id not in active_participants:
            raise SourceCodecError("invalid_child_scope_relation")
        child_members.setdefault(unit_id, set()).add(participant_id)
    if request.scope.scope_kind == "ledger_unit":
        selected_unit = snapshot.ledger_unit_id
        if selected_unit is None or selected_unit not in units_by_id:
            raise SourceCodecError("child_scope_unavailable")
        selected_unit_ids = {selected_unit}
    else:
        selected_unit = None
        selected_unit_ids = set(units_by_id)
    if not selected_unit_ids:
        raise SourceCodecError("scope_has_no_visible_units")

    def in_scope_unit(row: Mapping[str, Any], field_name: str = "ledger_unit_id") -> uuid.UUID:
        unit_id = _uuid(row, field_name)
        unit = units_by_id.get(unit_id)
        if unit is None or _uuid(unit, "activity_id") != activity_id or unit_id not in selected_unit_ids:
            raise SourceCodecError("row_outside_authorized_scope")
        return unit_id

    def participant_ref(participant_id: uuid.UUID) -> str:
        if participant_id not in active_participants:
            raise SourceCodecError("inactive_or_foreign_participant")
        return binder.bind_entity("participant", participant_id, activity_id=activity_id)

    fv = _integer(activity, "financial_version")
    base_currency = _currency(activity, "base_currency")
    facts: list[pc.P2Fact] = []
    if operation is pc.P2ReadOperation.EXPENSES:
        expenses = tables["expenses"].rows
        ids = {_uuid(row, "id") for row in expenses}
        payments: dict[uuid.UUID, list[Mapping[str, Any]]] = {}
        splits: dict[uuid.UUID, list[Mapping[str, Any]]] = {}
        for table_name, destination in (("payments", payments), ("splits", splits)):
            if ids and table_name not in tables:
                raise SourceCodecError("expense_allocation_source_missing")
            for row in tables.get(table_name, SourceTable(table_name, (), (), 0, True, True, True, "0" * 64)).rows:
                expense_id = _uuid(row, "expense_id")
                if expense_id not in ids:
                    raise SourceCodecError("allocation_outside_selected_expenses")
                destination.setdefault(expense_id, []).append(row)
        criteria = request.criteria
        for row in expenses:
            expense_id = _uuid(row, "id")
            unit_id = in_scope_unit(row)
            if _bool(row, "is_deleted"):
                raise SourceCodecError("deleted_expense_in_source_result")
            if authorized_expense_ids is not None and expense_id not in authorized_expense_ids:
                continue
            occurred = _time(row, "occurred_at")
            assert occurred is not None
            if criteria.from_date is not None and occurred.date() < criteria.from_date or criteria.to_date is not None and occurred.date() > criteria.to_date:
                continue
            title = _text(row, "title")
            if criteria.title_contains is not None and criteria.title_contains.casefold() not in title.casefold():
                continue
            original = _numeric(row, "original_amount", precision=20, scale=4, signed=True)
            if original is None or Decimal(original) == 0:
                raise SourceCodecError("invalid_expense_original_amount")
            original_currency = _currency(row, "original_currency")
            base = _numeric(row, "base_amount", precision=20, scale=1, signed=True)
            assert base is not None
            allocations: list[pc.ParticipantAllocationFact] = []
            for role, source_rows in (("payer", payments.get(expense_id, [])), ("split", splits.get(expense_id, []))):
                if not source_rows:
                    raise SourceCodecError("expense_missing_allocation_rows")
                for line in source_rows:
                    pid = _uuid(line, "participant_id")
                    if units_by_id[unit_id].get("participant_scope_configured") is True and pid not in child_members.get(unit_id, set()):
                        raise SourceCodecError("allocation_outside_configured_child")
                    amount = _numeric(line, "amount", precision=20, scale=4, signed=True)
                    base_line = _numeric(line, "base_amount", precision=20, scale=1, nullable=True, signed=True)
                    if base_line is None:
                        raise SourceCodecError("allocation_base_amount_unknown")
                    allocations.append(pc.ParticipantAllocationFact(
                        participant_ref=participant_ref(pid), role=role,
                        signed_original_amount=amount, original_currency=original_currency,
                        signed_base_amount=base_line, base_currency=base_currency,
                    ))
            criteria_pid = None
            if criteria.participant_ref is not None:
                criteria_pid = binder.resolve_entity(criteria.participant_ref, "participant", activity_id=activity_id)
            if criteria_pid is not None and not any(binder.resolve_entity(item.participant_ref, "participant", activity_id=activity_id) == criteria_pid for item in allocations):
                continue
            facts.append(pc.ExpenseFact(
                fact_kind="expense", expense_ref=binder.bind_entity("expense", expense_id, activity_id=activity_id, ledger_unit_id=unit_id),
                title=title, scope_ref=scope_ref, occurred_at=occurred,
                signed_original_amount=original, original_currency=original_currency,
                signed_base_amount=base, base_currency=base_currency,
                payer_split_lines=tuple(sorted(allocations, key=lambda item: (item.role, item.participant_ref, item.signed_original_amount))),
                expense_version=_integer(row, "version", minimum=1), financial_version=fv,
                query_evidence_ref=query_evidence_ref,
            ))
    elif operation is pc.P2ReadOperation.DEBTS:
        parents = {_uuid(row, "id"): row for row in tables.get("expenses", SourceTable("expenses", (), (), 0, True, True, True, "0" * 64)).rows}
        criteria = request.criteria
        requested_participant = None if criteria.participant_ref is None else binder.resolve_entity(criteria.participant_ref, "participant", activity_id=activity_id)
        for row in tables["expense_debts"].rows:
            if _uuid(row, "activity_id") != activity_id:
                raise SourceCodecError("debt_activity_mismatch")
            debt_id = _uuid(row, "id")
            unit_id = in_scope_unit(row)
            expense_id = _uuid(row, "expense_id")
            parent = parents.get(expense_id)
            if parent is None or _uuid(parent, "ledger_unit_id") != unit_id or _bool(parent, "is_deleted"):
                raise SourceCodecError("debt_parent_expense_unverified")
            debtor = _uuid(row, "debtor_participant_id")
            creditor = _uuid(row, "creditor_participant_id")
            if debtor == creditor:
                raise SourceCodecError("debt_parties_must_differ")
            for pid in (debtor, creditor):
                if units_by_id[unit_id].get("participant_scope_configured") is True and pid not in child_members.get(unit_id, set()):
                    raise SourceCodecError("debt_party_outside_configured_child")
            original = _numeric(row, "original_amount", precision=20, scale=4, nullable=True)
            currency = _currency(row, "original_currency", nullable=True)
            base = _numeric(row, "amount", precision=20, scale=1)
            if criteria.currency is not None and currency is None:
                raise SourceCodecError("unknown_original_currency_cannot_prove_filter")
            if criteria.currency is not None and currency != criteria.currency:
                continue
            if requested_participant is not None and requested_participant not in (debtor, creditor):
                continue
            facts.append(pc.DebtFact(
                fact_kind="debt", debt_ref=binder.bind_entity("debt", debt_id, activity_id=activity_id, ledger_unit_id=unit_id),
                scope_ref=scope_ref, activity_ref=request.scope.activity_ref, ledger_unit_ref=binder.bind_entity("ledger_unit", unit_id, activity_id=activity_id, ledger_unit_id=unit_id),
                expense_ref=binder.bind_entity("expense", expense_id, activity_id=activity_id, ledger_unit_id=unit_id),
                debtor_ref=participant_ref(debtor), creditor_ref=participant_ref(creditor),
                original_amount=original, original_currency=currency, base_amount=base, base_currency=base_currency,
                financial_version=fv, query_evidence_ref=query_evidence_ref,
            ))
    elif operation is pc.P2ReadOperation.REFUND_EVENTS:
        parents_table = tables.get("refund_parents")
        parents = {} if parents_table is None else {_uuid(row, "id"): row for row in parents_table.rows}
        criteria = request.criteria
        for row in tables["expenses"].rows:
            original = _numeric(row, "original_amount", precision=20, scale=4, signed=True)
            if Decimal(original) >= 0:
                continue
            unit_id = in_scope_unit(row)
            occurred = _time(row, "occurred_at")
            assert occurred is not None
            if criteria.from_date is not None and occurred.date() < criteria.from_date or criteria.to_date is not None and occurred.date() > criteria.to_date:
                continue
            parent_raw = row.get("original_expense_id")
            parent_id = None if parent_raw is None else uuid.UUID(parent_raw)
            parent_ref = None
            lineage = "unverified"
            basis = None
            if parent_id is not None:
                if parents_table is None or not parents_table.complete:
                    raise SourceCodecError("refund_parent_relationship_unproven")
                parent = parents.get(parent_id)
                if parent is not None:
                    parent_unit = in_scope_unit(parent)
                    parent_amount = _numeric(parent, "original_amount", precision=20, scale=4, signed=True)
                    if Decimal(parent_amount) <= 0 or parent.get("original_expense_id") is not None or parent.get("original_currency") != row.get("original_currency") or Decimal(parent.get("fx_rate")) != Decimal(row.get("fx_rate")):
                        raise SourceCodecError("refund_parent_relationship_invalid")
                    parent_ref = binder.bind_entity("expense", parent_id, activity_id=activity_id, ledger_unit_id=parent_unit)
                    lineage = "verified_same_activity_parent"
                    basis = "public_parent_relationship"
                else:
                    lineage = "parent_unavailable"
            base = _numeric(row, "base_amount", precision=20, scale=1, signed=True)
            facts.append(pc.RefundEventFact(
                fact_kind="refund_event", refund_ref=binder.bind_entity("refund", _uuid(row, "id"), activity_id=activity_id, ledger_unit_id=unit_id),
                scope_ref=scope_ref, signed_original_amount=original, original_currency=_currency(row, "original_currency"),
                signed_base_amount=base, base_currency=base_currency, occurred_at=occurred,
                parent_expense_ref=parent_ref, lineage_status=lineage, lineage_basis=basis, refund_recipient_ref=None,
                financial_version=fv, query_evidence_ref=query_evidence_ref,
            ))
    elif operation is pc.P2ReadOperation.PREPAYMENT_ACCOUNTS:
        for row in tables["prepayment_accounts"].rows:
            if _uuid(row, "activity_id") != activity_id:
                raise SourceCodecError("account_activity_mismatch")
            owner = _uuid(row, "owner_participant_id")
            custodian = _uuid(row, "custodian_participant_id")
            if owner == custodian:
                raise SourceCodecError("account_roles_must_differ")
            updated = _time(row, "updated_at")
            assert updated is not None
            facts.append(pc.PrepaymentAccountFact(
                fact_kind="prepayment_account", account_ref=binder.bind_entity("prepayment_account", _uuid(row, "id"), activity_id=activity_id),
                activity_ref=request.scope.activity_ref, owner_ref=participant_ref(owner), custodian_ref=participant_ref(custodian),
                balance=_numeric(row, "balance", precision=20, scale=4), currency=_currency(row, "currency"),
                projection_updated_at=updated, financial_version=fv, query_evidence_ref=query_evidence_ref,
            ))
    elif operation is pc.P2ReadOperation.PREPAYMENT_USAGES:
        usage_rows = tables["prepayment_usages"].rows
        if usage_rows and not {"prepayment_accounts", "expense_debts", "expenses"}.issubset(tables):
            raise SourceCodecError("usage_join_source_missing")
        accounts = {_uuid(row, "id"): row for row in tables.get("prepayment_accounts", SourceTable("prepayment_accounts", (), (), 0, True, True, True, "0" * 64)).rows}
        debts = {_uuid(row, "id"): row for row in tables.get("expense_debts", SourceTable("expense_debts", (), (), 0, True, True, True, "0" * 64)).rows}
        parents = {_uuid(row, "id"): row for row in tables.get("expenses", SourceTable("expenses", (), (), 0, True, True, True, "0" * 64)).rows}
        criteria = request.criteria
        filter_expense = None if criteria.expense_ref is None else binder.resolve_entity(criteria.expense_ref, "expense", activity_id=activity_id)
        filter_participant = None if criteria.participant_ref is None else binder.resolve_entity(criteria.participant_ref, "participant", activity_id=activity_id)
        for row in usage_rows:
            if _uuid(row, "activity_id") != activity_id:
                raise SourceCodecError("usage_activity_mismatch")
            account = accounts.get(_uuid(row, "account_id"))
            debt = debts.get(_uuid(row, "expense_debt_id"))
            if account is None or debt is None:
                raise SourceCodecError("usage_join_missing")
            if _uuid(account, "activity_id") != activity_id or _uuid(debt, "activity_id") != activity_id:
                raise SourceCodecError("usage_join_activity_mismatch")
            unit_id = in_scope_unit(debt)
            expense_id = _uuid(debt, "expense_id")
            parent = parents.get(expense_id)
            if parent is None or _uuid(parent, "ledger_unit_id") != unit_id or _bool(parent, "is_deleted"):
                raise SourceCodecError("usage_expense_join_missing")
            owner, custodian = _uuid(account, "owner_participant_id"), _uuid(account, "custodian_participant_id")
            debtor, creditor = _uuid(debt, "debtor_participant_id"), _uuid(debt, "creditor_participant_id")
            if owner != debtor or custodian != creditor or owner == custodian or owner not in active_participants or custodian not in active_participants:
                raise SourceCodecError("usage_account_debt_roles_mismatch")
            if units_by_id[unit_id].get("participant_scope_configured") is True and any(
                participant_id not in child_members.get(unit_id, set())
                for participant_id in (owner, custodian, debtor, creditor)
            ):
                raise SourceCodecError("usage_party_outside_configured_child")
            if filter_expense is not None and expense_id != filter_expense or filter_participant is not None and filter_participant not in (owner, custodian):
                continue
            base_raw = row.get("base_amount")
            base = None if base_raw is None else _numeric(row, "base_amount", precision=20, scale=1)
            bill_fx = None if row.get("bill_fx_rate") is None else _numeric(row, "bill_fx_rate", precision=20, scale=10)
            bill_time = _time(row, "bill_occurred_at", nullable=True)
            facts.append(pc.PrepaymentUsageFact(
                fact_kind="prepayment_usage", usage_ref=binder.bind_entity("prepayment_usage", _uuid(row, "id"), activity_id=activity_id, ledger_unit_id=unit_id),
                account_ref=binder.bind_entity("prepayment_account", _uuid(account, "id"), activity_id=activity_id),
                expense_ref=binder.bind_entity("expense", expense_id, activity_id=activity_id, ledger_unit_id=unit_id),
                debt_ref=binder.bind_entity("debt", _uuid(debt, "id"), activity_id=activity_id, ledger_unit_id=unit_id),
                activity_ref=request.scope.activity_ref, gross_amount=_numeric(row, "gross_amount", precision=20, scale=4),
                amount=_numeric(row, "amount", precision=20, scale=4), prepayment_amount=_numeric(row, "prepayment_amount", precision=20, scale=4),
                prepayment_currency=_currency(row, "prepayment_currency"), debt_amount=_numeric(row, "debt_amount", precision=20, scale=4),
                debt_currency=_currency(row, "debt_currency"), base_amount=base, base_currency=base_currency if base is not None else None,
                bill_fx_rate=bill_fx, bill_occurred_at=bill_time, financial_version=fv, query_evidence_ref=query_evidence_ref,
            ))
    elif operation is pc.P2ReadOperation.PREPAYMENT_RETURN_EVENTS:
        components: dict[uuid.UUID, list[Mapping[str, Any]]] = {}
        transfer_rows = tables["transfers"].rows
        if transfer_rows and "transfer_components" not in tables:
            raise SourceCodecError("return_component_source_missing")
        for component_row in tables.get("transfer_components", SourceTable("transfer_components", (), (), 0, True, True, True, "0" * 64)).rows:
            if _uuid(component_row, "activity_id") != activity_id:
                raise SourceCodecError("return_component_activity_mismatch")
            components.setdefault(_uuid(component_row, "transfer_id"), []).append(component_row)
        criteria = request.criteria
        for row in transfer_rows:
            if _uuid(row, "activity_id") != activity_id or _text(row, "type") != "prepayment_return" or _bool(row, "is_voided"):
                raise SourceCodecError("invalid_return_transfer_source")
            matched_components = [item for item in components.get(_uuid(row, "id"), ()) if _text(item, "component_type") == "prepayment_return"]
            if len(matched_components) != 1:
                raise SourceCodecError("return_component_missing")
            component = matched_components[0]
            amount = _numeric(row, "amount", precision=20, scale=4)
            component_amount = _numeric(component, "amount", precision=20, scale=4)
            if Decimal(amount) != Decimal(component_amount):
                raise SourceCodecError("return_component_amount_mismatch")
            occurred = _time(row, "occurred_at")
            assert occurred is not None
            if criteria.from_date is not None and occurred.date() < criteria.from_date or criteria.to_date is not None and occurred.date() > criteria.to_date:
                continue
            from_id, to_id = _uuid(row, "from_participant_id"), _uuid(row, "to_participant_id")
            facts.append(pc.PrepaymentReturnEventFact(
                fact_kind="prepayment_return_event", return_event_ref=binder.bind_entity("prepayment_return", _uuid(row, "id"), activity_id=activity_id),
                activity_ref=request.scope.activity_ref, amount=amount, currency=_currency(row, "currency"), occurred_at=occurred,
                from_ref=participant_ref(from_id), from_role="custodian", to_ref=participant_ref(to_id), to_role="owner",
                transfer_component_match=True, financial_version=fv, query_evidence_ref=query_evidence_ref,
            ))
    else:
        raise SourceCodecError("unsupported_operation")
    if len(facts) > MAX_FACTS_PER_QUERY:
        raise SourceCodecError("fact_query_bound_exceeded")
    return tuple(facts)

