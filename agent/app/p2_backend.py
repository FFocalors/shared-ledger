"""Narrow, read-only Supabase Data API adapter for P2.

This module deliberately does not implement the shared BackendAdapter port yet;
the runtime supplies its verified per-Turn grant and binds returned UUIDs to
opaque model references.
"""

from __future__ import annotations

import asyncio
import base64
import http.client
import ipaddress
import json
import re
import socket
import ssl
import threading
import time
import urllib.parse
import uuid
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Mapping, Protocol, Sequence
from urllib.parse import urlsplit

from . import contracts as c


@dataclass(frozen=True, slots=True)
class BoundRef:
    """Server-held binding from an opaque model ref to one typed database ID."""

    kind: Literal["activity", "expense", "ledger_unit", "participant"]
    object_id: uuid.UUID
    activity_id: uuid.UUID | None = None
    ledger_unit_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class VerifiedReadContext:
    """A validated user credential scoped to one owner and one Turn."""

    owner_user_id: uuid.UUID
    turn_id: uuid.UUID
    principal_user_id: uuid.UUID
    access_token: str = field(repr=False, compare=False)
    expires_at: datetime
    refs_by_opaque_token: Mapping[str, BoundRef] = field(repr=False)


@dataclass(frozen=True, slots=True)
class ScopeRequest:
    mode: Literal["activity", "none"]
    ui_activity_id_hint: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class P2ActivityDTO:
    activity_id: uuid.UUID
    name: str
    activity_type: str
    base_currency: str
    multi_currency_enabled: bool
    is_deleted: bool
    archived_at: datetime | None
    financial_version: int


@dataclass(frozen=True, slots=True)
class P2ParticipantDTO:
    participant_id: uuid.UUID
    activity_id: uuid.UUID
    name: str
    participant_order: int
    is_deleted: bool


@dataclass(frozen=True, slots=True)
class P2LedgerUnitDTO:
    ledger_unit_id: uuid.UUID
    activity_id: uuid.UUID
    name: str
    unit_type: str
    is_deleted: bool
    participant_scope_configured: bool


@dataclass(frozen=True, slots=True)
class P2ChildScopeDTO:
    ledger_unit_id: uuid.UUID
    configured: bool
    participant_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True, slots=True)
class P2ResolvedScope:
    mode: Literal["activity", "none"]
    activity: P2ActivityDTO | None
    participants: tuple[P2ParticipantDTO, ...]
    ledger_units: tuple[P2LedgerUnitDTO, ...]
    child_scopes: tuple[P2ChildScopeDTO, ...]
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class P2PaymentDTO:
    payment_id: uuid.UUID
    expense_id: uuid.UUID
    participant_id: uuid.UUID
    amount: Decimal
    base_amount: Decimal | None


@dataclass(frozen=True, slots=True)
class P2SplitDTO:
    split_id: uuid.UUID
    expense_id: uuid.UUID
    participant_id: uuid.UUID
    amount: Decimal
    base_amount: Decimal | None


@dataclass(frozen=True, slots=True)
class P2ExpenseDTO:
    expense_id: uuid.UUID
    activity_id: uuid.UUID
    ledger_unit_id: uuid.UUID
    title: str
    original_amount: Decimal
    original_currency: str
    fx_rate: Decimal
    base_amount: Decimal
    occurred_at: datetime
    original_expense_id: uuid.UUID | None
    expense_version: int
    is_deleted: bool
    financial_locked: bool
    payments: tuple[P2PaymentDTO, ...]
    splits: tuple[P2SplitDTO, ...]


@dataclass(frozen=True, slots=True)
class P2DebtDTO:
    debtor_participant_id: uuid.UUID
    creditor_participant_id: uuid.UUID
    currency: str
    original_amount: Decimal
    base_amount: Decimal
    base_total: Decimal
    financial_version: int


@dataclass(frozen=True, slots=True)
class P2BackendReadResult:
    """Complete data for this call; activity-list versions are point snapshots.

    Expense/debt readers additionally fence financial facts with start/end
    Activity versions before returning. An activity-list result carries the
    versions observed by its single bounded query only.
    """

    operation: c.ReadOperation
    observed_at: datetime
    source: Literal["supabase_postgrest"]
    activities: tuple[P2ActivityDTO, ...] = ()
    expenses: tuple[P2ExpenseDTO, ...] = ()
    debts: tuple[P2DebtDTO, ...] = ()
    financial_versions: Mapping[uuid.UUID, int] = field(default_factory=dict, repr=False)
    complete: bool = True


class BackendReadError(RuntimeError):
    """A stable, sanitized adapter failure suitable for policy routing."""

    def __init__(self, code: Literal[
        "invalid_auth_context", "scope_unavailable", "unsupported_scope",
        "unsupported_read", "upstream_failure", "invalid_upstream_response",
        "response_too_large", "read_limit_exceeded", "data_changed_during_read",
        "auth_rejected", "access_denied", "rate_limited", "upstream_timeout",
        "upstream_unavailable",
    ]) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class TransportResponse:
    status: int
    body: bytes
    content_range: str | None


@dataclass(slots=True)
class _ReadBudget:
    started_at: float = field(default_factory=time.monotonic)
    requests: int = 0
    response_bytes: int = 0


class _RequestControl:
    """One-request cancellation handle; abort closes only this request socket."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._socket: socket.socket | None = None
        self._aborted = threading.Event()
        self._connected = threading.Event()

    def bind(self, request_socket: socket.socket) -> None:
        self._connected.set()
        with self._lock:
            self._socket = request_socket
            aborted = self._aborted.is_set()
        if aborted:
            self._close_socket(request_socket)

    def abort(self) -> None:
        self._aborted.set()
        with self._lock:
            request_socket = self._socket
        if request_socket is not None:
            self._close_socket(request_socket)

    @property
    def aborted(self) -> bool:
        return self._aborted.is_set()

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    @staticmethod
    def _close_socket(request_socket: socket.socket) -> None:
        try:
            request_socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            request_socket.close()
        except OSError:
            pass


class ReadOnlyTransport(Protocol):
    def get(
        self, url: str, headers: Mapping[str, str], *, timeout: float,
        max_response_bytes: int, control: _RequestControl,
    ) -> TransportResponse: ...


@dataclass(frozen=True, slots=True)
class P2BackendConfig:
    project_url: str
    publishable_key: str = field(repr=False, compare=False)
    timeout_seconds: float = 5.0
    max_response_bytes: int = 1_048_576
    page_size: int = 64
    max_pages: int = 16
    max_rows_per_query: int = 512
    max_requests_per_read: int = 48
    max_total_response_bytes: int = 4_194_304
    max_total_seconds: float = 20.0
    max_facts: int = 16


_ACTIVITY_SELECT = "id,name,type,base_currency,multi_currency_enabled,is_deleted,archived_at,financial_version"
_ACTIVITY_VERSION_SELECT = "id,is_deleted,financial_version"
_MEMBERSHIP_SELECT = "activity_id"
_UNIT_SELECT = "id,activity_id,name,type,is_deleted,participant_scope_configured"
_PARTICIPANT_SELECT = "id,activity_id,name,participant_order,is_deleted"
_CHILD_SCOPE_SELECT = "activity_id,ledger_unit_id,participant_id"
_EXPENSE_SELECT = (
    "id,ledger_unit_id,title,original_amount,original_currency,fx_rate,base_amount,occurred_at,"
    "original_expense_id,version,is_deleted,financial_locked"
)
_PAYMENT_SELECT = "id,expense_id,participant_id,amount,base_amount"
_SPLIT_SELECT = "id,expense_id,participant_id,amount,base_amount"
_DEBT_SELECT = (
    "debtor_participant_id,creditor_participant_id,currency,original_amount,base_amount,"
    "base_total,financial_version"
)
_RPC_LIST_SETTLEMENT_OPTIONS = "/rpc/list_settlement_options"
_CONTENT_RANGE = re.compile(r"^(?:(?P<start>\d+)-(?P<end>\d+)|\*)/(?P<total>\d+|\*)$")


class StdlibReadOnlyTransport:
    """Finite direct GET using http.client and request-socket cancellation."""

    def get(
        self, url: str, headers: Mapping[str, str], *, timeout: float,
        max_response_bytes: int, control: _RequestControl,
    ) -> TransportResponse:
        connection: http.client.HTTPConnection | None = None
        deadline = time.monotonic() + timeout
        connected = False
        try:
            parsed = urlsplit(url)
            if parsed.scheme == "https":
                connection = http.client.HTTPSConnection(
                    parsed.hostname, parsed.port or 443,
                    timeout=timeout, context=ssl.create_default_context(),
                )
            elif parsed.scheme == "http":
                connection = http.client.HTTPConnection(
                    parsed.hostname, parsed.port or 80, timeout=timeout,
                )
            else:
                raise BackendReadError("upstream_unavailable")
            if not parsed.hostname or control.aborted:
                raise BackendReadError("upstream_timeout" if control.aborted else "upstream_unavailable")
            connection.connect()
            if connection.sock is None:
                raise BackendReadError("upstream_unavailable")
            connected = True
            control.bind(connection.sock)
            self._set_remaining_timeout(connection, deadline, control)
            target = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
            request_headers = {
                **headers,
                "Host": parsed.netloc,
                "Connection": "close",
                "Accept-Encoding": "identity",
            }
            connection.request("GET", target, headers=request_headers)
            self._set_remaining_timeout(connection, deadline, control)
            response = connection.getresponse()
            content_ranges = response.headers.get_all("Content-Range", [])
            if len(content_ranges) > 1:
                raise BackendReadError("invalid_upstream_response")
            content_range = content_ranges[0] if content_ranges else None
            if response.status not in (200, 206):
                return TransportResponse(response.status, b"", content_range)

            chunks: list[bytes] = []
            total = 0
            while True:
                self._set_remaining_timeout(connection, deadline, control)
                chunk = response.read1(min(65_536, max_response_bytes + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_response_bytes:
                    raise BackendReadError("response_too_large")
                chunks.append(chunk)
            return TransportResponse(response.status, b"".join(chunks), content_range)
        except BackendReadError:
            raise
        except (socket.timeout, TimeoutError):
            raise BackendReadError(
                "upstream_timeout" if connected else "upstream_unavailable",
            ) from None
        except (OSError, ssl.SSLError, http.client.HTTPException, ValueError):
            if control.aborted:
                raise BackendReadError(
                    "upstream_timeout" if connected else "upstream_unavailable",
                ) from None
            raise BackendReadError("upstream_unavailable") from None
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _set_remaining_timeout(
        connection: http.client.HTTPConnection,
        deadline: float,
        control: _RequestControl,
    ) -> None:
        remaining = deadline - time.monotonic()
        if control.aborted or remaining <= 0:
            control.abort()
            raise BackendReadError("upstream_timeout")
        if connection.sock is not None:
            connection.sock.settimeout(remaining)


def _safe_project_url(raw: str) -> str:
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname
        if not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError
        loopback = host.lower() == "localhost"
        try:
            loopback = loopback or ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
            raise ValueError
        if parsed.path not in ("", "/"):
            raise ValueError
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError
        return raw.rstrip("/")
    except (TypeError, ValueError):
        raise ValueError("invalid Supabase project URL") from None


def _assert_publishable_key(key: str) -> None:
    if (
        not isinstance(key, str) or not key or len(key) > 4096
        or not re.fullmatch(r"[A-Za-z0-9._~-]+", key)
    ):
        raise ValueError("a publishable Supabase API key is required")
    parts = key.split(".")
    if len(parts) == 3:
        try:
            padded = parts[1] + "=" * (-len(parts[1]) % 4)
            claims = json.loads(
                base64.urlsafe_b64decode(padded.encode("ascii")),
                object_pairs_hook=lambda pairs: _unique_json_object(pairs),
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
            )
        except (ValueError, UnicodeError, json.JSONDecodeError):
            raise ValueError("invalid publishable Supabase API key") from None
        if not isinstance(claims, dict):
            raise ValueError("invalid publishable Supabase API key")
        if not isinstance(claims, dict) or claims.get("role") != "anon":
            raise ValueError("JWT-form Supabase API keys must have anon role")
    elif not key.startswith("sb_publishable_"):
        raise ValueError("a recognized Supabase publishable API key is required")


def _parse_uuid(value: Any) -> uuid.UUID:
    if not isinstance(value, str):
        raise BackendReadError("invalid_upstream_response")
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        raise BackendReadError("invalid_upstream_response") from None


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _parse_decimal(value: Any, *, allow_null: bool = False) -> Decimal | None:
    if value is None and allow_null:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise BackendReadError("invalid_upstream_response")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise BackendReadError("invalid_upstream_response") from None
    if not result.is_finite():
        raise BackendReadError("invalid_upstream_response")
    return result


def _parse_datetime(value: Any, *, allow_null: bool = False) -> datetime | None:
    if value is None and allow_null:
        return None
    if not isinstance(value, str):
        raise BackendReadError("invalid_upstream_response")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise BackendReadError("invalid_upstream_response") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BackendReadError("invalid_upstream_response")
    return parsed.astimezone(timezone.utc)


def _require_bool(row: Mapping[str, Any], key: str) -> bool:
    value = row.get(key)
    if not isinstance(value, bool):
        raise BackendReadError("invalid_upstream_response")
    return value


def _require_int(row: Mapping[str, Any], key: str, *, minimum: int = 0) -> int:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise BackendReadError("invalid_upstream_response")
    return value


def _require_text(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str):
        raise BackendReadError("invalid_upstream_response")
    return value


def _parse_json_rows(body: bytes) -> list[dict[str, Any]]:
    def object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def reject_nonstandard_constant(_: str) -> None:
        raise ValueError("non-standard JSON constant")

    try:
        payload = json.loads(
            body.decode("utf-8"), parse_float=Decimal,
            object_pairs_hook=object_without_duplicate_keys,
            parse_constant=reject_nonstandard_constant,
        )
    except (UnicodeError, ValueError, json.JSONDecodeError, InvalidOperation):
        raise BackendReadError("invalid_upstream_response") from None
    if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
        raise BackendReadError("invalid_upstream_response")
    return payload


def _activity_dto(row: Mapping[str, Any]) -> P2ActivityDTO:
    archived_at = _parse_datetime(row.get("archived_at"), allow_null=True)
    return P2ActivityDTO(
        activity_id=_parse_uuid(row.get("id")),
        name=_require_text(row, "name"),
        activity_type=_require_text(row, "type"),
        base_currency=_require_text(row, "base_currency"),
        multi_currency_enabled=_require_bool(row, "multi_currency_enabled"),
        is_deleted=_require_bool(row, "is_deleted"),
        archived_at=archived_at,
        financial_version=_require_int(row, "financial_version"),
    )


def _participant_dto(row: Mapping[str, Any]) -> P2ParticipantDTO:
    return P2ParticipantDTO(
        participant_id=_parse_uuid(row.get("id")),
        activity_id=_parse_uuid(row.get("activity_id")),
        name=_require_text(row, "name"),
        participant_order=_require_int(row, "participant_order"),
        is_deleted=_require_bool(row, "is_deleted"),
    )


def _unit_dto(row: Mapping[str, Any]) -> P2LedgerUnitDTO:
    return P2LedgerUnitDTO(
        ledger_unit_id=_parse_uuid(row.get("id")),
        activity_id=_parse_uuid(row.get("activity_id")),
        name=_require_text(row, "name"),
        unit_type=_require_text(row, "type"),
        is_deleted=_require_bool(row, "is_deleted"),
        participant_scope_configured=_require_bool(row, "participant_scope_configured"),
    )


def _payment_dto(row: Mapping[str, Any]) -> P2PaymentDTO:
    return P2PaymentDTO(
        payment_id=_parse_uuid(row.get("id")),
        expense_id=_parse_uuid(row.get("expense_id")),
        participant_id=_parse_uuid(row.get("participant_id")),
        amount=_parse_decimal(row.get("amount")),  # type: ignore[arg-type]
        base_amount=_parse_decimal(row.get("base_amount"), allow_null=True),
    )


def _split_dto(row: Mapping[str, Any]) -> P2SplitDTO:
    return P2SplitDTO(
        split_id=_parse_uuid(row.get("id")),
        expense_id=_parse_uuid(row.get("expense_id")),
        participant_id=_parse_uuid(row.get("participant_id")),
        amount=_parse_decimal(row.get("amount")),  # type: ignore[arg-type]
        base_amount=_parse_decimal(row.get("base_amount"), allow_null=True),
    )


def _expense_dto(row: Mapping[str, Any], activity_id: uuid.UUID) -> P2ExpenseDTO:
    occurred_at = _parse_datetime(row.get("occurred_at"))
    original_expense_id = row.get("original_expense_id")
    if original_expense_id is not None:
        original_expense_id = _parse_uuid(original_expense_id)
    currency = _require_text(row, "original_currency")
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise BackendReadError("invalid_upstream_response")
    original_amount = _parse_decimal(row.get("original_amount"))
    fx_rate = _parse_decimal(row.get("fx_rate"))
    base_amount = _parse_decimal(row.get("base_amount"))
    if original_amount == 0 or fx_rate <= 0:
        raise BackendReadError("invalid_upstream_response")
    return P2ExpenseDTO(
        expense_id=_parse_uuid(row.get("id")),
        activity_id=activity_id,
        ledger_unit_id=_parse_uuid(row.get("ledger_unit_id")),
        title=_require_text(row, "title"),
        original_amount=original_amount,  # type: ignore[arg-type]
        original_currency=currency,
        fx_rate=fx_rate,  # type: ignore[arg-type]
        base_amount=base_amount,  # type: ignore[arg-type]
        occurred_at=occurred_at,  # type: ignore[arg-type]
        original_expense_id=original_expense_id,
        expense_version=_require_int(row, "version", minimum=1),
        is_deleted=_require_bool(row, "is_deleted"),
        financial_locked=_require_bool(row, "financial_locked"),
        payments=(), splits=(),
    )


class P2BackendAdapter:
    """Finite GET allowlist and private UUID DTO mapper for the v1 read operations."""

    _TABLES = frozenset({
        "activities", "activity_members", "ledger_units", "participants",
        "sub_activity_participants", "expenses", "payments", "splits",
    })

    def __init__(self, config: P2BackendConfig, transport: ReadOnlyTransport | None = None) -> None:
        self._project_url = _safe_project_url(config.project_url)
        _assert_publishable_key(config.publishable_key)
        if not 0 < config.timeout_seconds <= 30:
            raise ValueError("timeout_seconds is outside the supported bound")
        if not 1_024 <= config.max_response_bytes <= 8_388_608:
            raise ValueError("max_response_bytes is outside the supported bound")
        if not 1 <= config.page_size <= 128 or not 1 <= config.max_pages <= 32:
            raise ValueError("pagination limits are outside the supported bound")
        if not config.page_size <= config.max_rows_per_query <= 2_048:
            raise ValueError("row limit is outside the supported bound")
        if not 1 <= config.max_requests_per_read <= 128:
            raise ValueError("request budget is outside the supported bound")
        if not config.max_response_bytes <= config.max_total_response_bytes <= 33_554_432:
            raise ValueError("total response-byte budget is outside the supported bound")
        if not 1 <= config.max_total_seconds <= 120:
            raise ValueError("total time budget is outside the supported bound")
        if not 1 <= config.max_facts <= 16:
            raise ValueError("max_facts must fit the frozen v1 result limit")
        self._publishable_key = config.publishable_key
        self._timeout = config.timeout_seconds
        self._max_response_bytes = config.max_response_bytes
        self._page_size = config.page_size
        self._max_pages = config.max_pages
        self._max_rows = config.max_rows_per_query
        self._max_requests = config.max_requests_per_read
        self._max_total_response_bytes = config.max_total_response_bytes
        self._max_total_seconds = config.max_total_seconds
        self._max_facts = config.max_facts
        self._transport = transport or StdlibReadOnlyTransport()

    def start(self) -> None:
        """Satisfy the service lifecycle; the adapter acquires no shared resource."""

    def close(self) -> None:
        """Satisfy the service lifecycle; each transport request owns its socket."""

    async def resolve_scope(
        self, verified: VerifiedReadContext, request: ScopeRequest,
    ) -> P2ResolvedScope:
        """Resolve an untrusted UI activity hint under the current user JWT."""
        self._validate_grant(verified)
        if not isinstance(request, ScopeRequest):
            raise BackendReadError("unsupported_scope")
        budget = _ReadBudget()
        now = datetime.now(timezone.utc)
        if request.mode == "none":
            return P2ResolvedScope("none", None, (), (), (), now)
        if request.mode != "activity" or request.ui_activity_id_hint is None:
            raise BackendReadError("unsupported_scope")

        activity_id = request.ui_activity_id_hint
        if not isinstance(activity_id, uuid.UUID):
            raise BackendReadError("unsupported_scope")
        await self._require_membership(activity_id, verified, budget)
        activity_rows = await self._get_table(
            "activities", _ACTIVITY_SELECT,
            [("id", f"eq.{activity_id}"), ("is_deleted", "eq.false")],
            verified, budget=budget, order="id.asc",
        )
        if len(activity_rows) != 1:
            raise BackendReadError("scope_unavailable")
        activity = _activity_dto(activity_rows[0])
        if activity.activity_id != activity_id or activity.is_deleted:
            raise BackendReadError("scope_unavailable")

        units, participants, scopes = await self._load_activity_scope(activity_id, verified, budget)
        end_units, end_participants, end_scopes = await self._load_activity_scope(
            activity_id, verified, budget,
        )
        await self._require_membership(activity_id, verified, budget)
        end_activity = await self._get_activity(activity_id, verified, budget)
        if (
            end_activity.financial_version != activity.financial_version
            or (end_units, end_participants, end_scopes) != (units, participants, scopes)
        ):
            raise BackendReadError("data_changed_during_read")
        self._check_budget(budget, verified)
        return P2ResolvedScope(
            mode="activity", activity=activity, participants=participants,
            ledger_units=units, child_scopes=scopes, observed_at=now,
        )

    async def authorize_api_scope(
        self,
        principal_user_id: uuid.UUID,
        activity_ids: Sequence[uuid.UUID],
        access_token: str,
        expires_at: datetime,
    ) -> None:
        """Recheck API-held activity scopes with this request's verified JWT.

        This is a request-local authorization hook for polling endpoints. It
        returns no database DTOs and never retains credentials between calls.
        """
        if (
            not isinstance(principal_user_id, uuid.UUID)
            or not isinstance(activity_ids, Sequence)
            or isinstance(activity_ids, (str, bytes))
            or len(activity_ids) > self._max_facts
            or any(not isinstance(item, uuid.UUID) for item in activity_ids)
            or len(set(activity_ids)) != len(activity_ids)
        ):
            raise BackendReadError("invalid_auth_context")
        verified = VerifiedReadContext(
            owner_user_id=principal_user_id,
            turn_id=uuid.uuid4(),
            principal_user_id=principal_user_id,
            access_token=access_token,
            expires_at=expires_at,
            refs_by_opaque_token={},
        )
        self._validate_grant(verified, owner_user_id=principal_user_id)
        budget = _ReadBudget()
        for activity_id in activity_ids:
            await self._require_membership(activity_id, verified, budget)
            await self._get_activity(activity_id, verified, budget)
            await self._require_membership(activity_id, verified, budget)
            self._check_budget(budget, verified)

    async def verify_financial_versions(
        self,
        verified: VerifiedReadContext,
        expected: Mapping[uuid.UUID, int],
    ) -> None:
        """Confirm trusted activity versions immediately before answer disclosure.

        Activity UUIDs must already be bound by this Turn. The helper returns no
        business DTOs, performs only fixed membership/activity GETs, and uses a
        request-local grant with an independent bounded budget.
        """
        self._validate_grant(verified)
        if (
            not isinstance(expected, Mapping)
            or not 1 <= len(expected) <= self._max_facts
            or any(
                not isinstance(activity_id, uuid.UUID)
                or isinstance(version, bool)
                or not isinstance(version, int)
                or version < 0
                for activity_id, version in expected.items()
            )
        ):
            raise BackendReadError("invalid_auth_context")
        bound_activity_ids = {
            binding.object_id
            for binding in verified.refs_by_opaque_token.values()
            if (
                isinstance(binding, BoundRef)
                and binding.kind == "activity"
                and isinstance(binding.object_id, uuid.UUID)
                and binding.activity_id in (None, binding.object_id)
            )
        }
        if not set(expected).issubset(bound_activity_ids):
            raise BackendReadError("invalid_auth_context")

        budget = _ReadBudget()
        for activity_id, expected_version in sorted(expected.items(), key=lambda pair: str(pair[0])):
            await self._require_membership(activity_id, verified, budget)
            observed_version = await self._get_financial_version(activity_id, verified, budget)
            await self._require_membership(activity_id, verified, budget)
            if observed_version != expected_version:
                raise BackendReadError("data_changed_during_read")
            self._check_budget(budget, verified)

    def _check_budget(self, budget: _ReadBudget, verified: VerifiedReadContext) -> None:
        if verified.expires_at <= datetime.now(timezone.utc):
            raise BackendReadError("invalid_auth_context")
        if time.monotonic() - budget.started_at >= self._max_total_seconds:
            raise BackendReadError("upstream_timeout")

    async def _require_membership(
        self, activity_id: uuid.UUID, verified: VerifiedReadContext, budget: _ReadBudget,
    ) -> None:
        rows = await self._get_table(
            "activity_members", _MEMBERSHIP_SELECT,
            [("activity_id", f"eq.{activity_id}"),
             ("user_id", f"eq.{verified.principal_user_id}")],
            verified, budget=budget, order="activity_id.asc",
        )
        if len(rows) != 1 or _parse_uuid(rows[0].get("activity_id")) != activity_id:
            raise BackendReadError("scope_unavailable")

    async def _get_activity(
        self, activity_id: uuid.UUID, verified: VerifiedReadContext, budget: _ReadBudget,
    ) -> P2ActivityDTO:
        rows = await self._get_table(
            "activities", _ACTIVITY_SELECT,
            [("id", f"eq.{activity_id}"), ("is_deleted", "eq.false")],
            verified, budget=budget, order="id.asc",
        )
        if len(rows) != 1:
            raise BackendReadError("scope_unavailable")
        activity = _activity_dto(rows[0])
        if activity.activity_id != activity_id or activity.is_deleted:
            raise BackendReadError("scope_unavailable")
        return activity

    async def _get_financial_version(
        self, activity_id: uuid.UUID, verified: VerifiedReadContext, budget: _ReadBudget,
    ) -> int:
        rows = await self._get_table(
            "activities", _ACTIVITY_VERSION_SELECT,
            [("id", f"eq.{activity_id}"), ("is_deleted", "eq.false")],
            verified, budget=budget, order="id.asc",
        )
        if len(rows) != 1:
            raise BackendReadError("scope_unavailable")
        row = rows[0]
        if _parse_uuid(row.get("id")) != activity_id or _require_bool(row, "is_deleted"):
            raise BackendReadError("scope_unavailable")
        return _require_int(row, "financial_version")

    async def _load_activity_scope(
        self, activity_id: uuid.UUID, verified: VerifiedReadContext, budget: _ReadBudget,
    ) -> tuple[tuple[P2LedgerUnitDTO, ...], tuple[P2ParticipantDTO, ...], tuple[P2ChildScopeDTO, ...]]:
        unit_rows = await self._get_table(
            "ledger_units", _UNIT_SELECT,
            [("activity_id", f"eq.{activity_id}"), ("is_deleted", "eq.false")],
            verified, budget=budget, order="id.asc",
        )
        participant_rows = await self._get_table(
            "participants", _PARTICIPANT_SELECT,
            [("activity_id", f"eq.{activity_id}"), ("is_deleted", "eq.false")],
            verified, budget=budget, order="participant_order.asc,id.asc",
        )
        scope_rows = await self._get_table(
            "sub_activity_participants", _CHILD_SCOPE_SELECT,
            [("activity_id", f"eq.{activity_id}")],
            verified, budget=budget, order="ledger_unit_id.asc,participant_id.asc",
        )
        units = tuple(_unit_dto(row) for row in unit_rows)
        participants = tuple(_participant_dto(row) for row in participant_rows)
        unit_by_id = {item.ledger_unit_id: item for item in units}
        participant_by_id = {item.participant_id: item for item in participants}
        if len(unit_by_id) != len(units) or len(participant_by_id) != len(participants):
            raise BackendReadError("invalid_upstream_response")
        if any(item.activity_id != activity_id for item in (*units, *participants)):
            raise BackendReadError("invalid_upstream_response")

        scope_members: dict[uuid.UUID, set[uuid.UUID]] = {}
        for row in scope_rows:
            row_activity_id = _parse_uuid(row.get("activity_id"))
            unit_id = _parse_uuid(row.get("ledger_unit_id"))
            participant_id = _parse_uuid(row.get("participant_id"))
            if row_activity_id != activity_id:
                raise BackendReadError("invalid_upstream_response")
            unit = unit_by_id.get(unit_id)
            participant = participant_by_id.get(participant_id)
            if (
                unit is None or unit.unit_type != "sub_activity"
                or not unit.participant_scope_configured or participant is None
            ):
                raise BackendReadError("invalid_upstream_response")
            members = scope_members.setdefault(unit_id, set())
            if participant_id in members:
                raise BackendReadError("invalid_upstream_response")
            members.add(participant_id)

        child_scopes: list[P2ChildScopeDTO] = []
        for unit in units:
            if unit.unit_type == "sub_activity":
                members = scope_members.get(unit.ledger_unit_id, set())
                if unit.participant_scope_configured and not members:
                    raise BackendReadError("invalid_upstream_response")
                child_scopes.append(P2ChildScopeDTO(
                    ledger_unit_id=unit.ledger_unit_id,
                    configured=unit.participant_scope_configured,
                    participant_ids=tuple(sorted(members, key=str)),
                ))
            elif unit.participant_scope_configured or unit.ledger_unit_id in scope_members:
                raise BackendReadError("invalid_upstream_response")
        return units, participants, tuple(child_scopes)

    @staticmethod
    def _validate_grant(
        verified: VerifiedReadContext,
        *,
        owner_user_id: uuid.UUID | None = None,
        turn_id: uuid.UUID | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        if (
            not isinstance(verified, VerifiedReadContext)
            or not isinstance(verified.access_token, str)
            or not verified.access_token
            or len(verified.access_token) > 16_384
            or not re.fullmatch(r"[A-Za-z0-9._~-]+", verified.access_token)
            or verified.owner_user_id != verified.principal_user_id
            or owner_user_id is not None and verified.owner_user_id != owner_user_id
            or turn_id is not None and verified.turn_id != turn_id
            or not isinstance(verified.expires_at, datetime)
            or verified.expires_at.tzinfo is None
            or verified.expires_at.utcoffset() is None
            or verified.expires_at <= now
            or not isinstance(verified.refs_by_opaque_token, Mapping)
        ):
            raise BackendReadError("invalid_auth_context")

    def _make_url(self, route: str, params: Sequence[tuple[str, str]]) -> str:
        if route in self._TABLES:
            path = f"/rest/v1/{route}"
        elif route == _RPC_LIST_SETTLEMENT_OPTIONS:
            path = f"/rest/v1{route}"
        else:
            raise BackendReadError("unsupported_read")
        url = f"{self._project_url}{path}?{urllib.parse.urlencode(params)}"
        if len(url) > 12_000:
            raise BackendReadError("read_limit_exceeded")
        return url

    async def _get_json_rows(
        self,
        route: str,
        params: Sequence[tuple[str, str]],
        verified: VerifiedReadContext,
        *,
        budget: _ReadBudget,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, ...]] = set()
        offset = 0
        expected_total: int | None = None
        for _ in range(self._max_pages):
            self._check_budget(budget, verified)
            grant_remaining = (verified.expires_at - datetime.now(timezone.utc)).total_seconds()
            if offset >= self._max_rows:
                raise BackendReadError("read_limit_exceeded")
            page_params = list(params)
            if order is not None:
                page_params.append(("order", order))
            page_params.append(("limit", str(self._page_size)))
            page_params.append(("offset", str(offset)))
            url = self._make_url(route, page_params)
            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {verified.access_token}",
                "apikey": self._publishable_key,
                "Prefer": "count=exact",
            }
            elapsed = time.monotonic() - budget.started_at
            remaining = self._max_total_seconds - elapsed
            if remaining <= 0:
                raise BackendReadError("upstream_timeout")
            budget.requests += 1
            if budget.requests > self._max_requests:
                raise BackendReadError("read_limit_exceeded")
            control = _RequestControl()
            request_timeout = min(self._timeout, remaining, grant_remaining)
            timer = threading.Timer(request_timeout, control.abort)
            worker = asyncio.create_task(asyncio.to_thread(
                self._transport.get, url, headers,
                timeout=request_timeout,
                max_response_bytes=self._max_response_bytes,
                control=control,
            ))
            timer.start()
            try:
                async with asyncio.timeout(request_timeout):
                    response = await worker
            except TimeoutError:
                control.abort()
                raise BackendReadError(
                    "upstream_timeout" if control.connected else "upstream_unavailable",
                ) from None
            except asyncio.CancelledError:
                control.abort()
                raise
            except BackendReadError:
                raise
            except Exception:
                raise BackendReadError("upstream_failure") from None
            finally:
                timer.cancel()
            if (
                not isinstance(response, TransportResponse)
                or isinstance(response.status, bool)
                or not isinstance(response.status, int)
                or not 100 <= response.status <= 599
                or response.content_range is not None and not isinstance(response.content_range, str)
            ):
                raise BackendReadError("invalid_upstream_response")
            if control.aborted:
                raise BackendReadError("upstream_timeout")
            self._check_budget(budget, verified)
            if response.status == 401:
                raise BackendReadError("auth_rejected")
            if response.status == 403:
                raise BackendReadError("access_denied")
            if response.status == 429:
                raise BackendReadError("rate_limited")
            if response.status in (408, 504):
                raise BackendReadError("upstream_timeout")
            if response.status in (502, 503):
                raise BackendReadError("upstream_unavailable")
            if response.status not in (200, 206):
                raise BackendReadError("upstream_failure")
            if not isinstance(response.body, bytes):
                raise BackendReadError("invalid_upstream_response")
            if len(response.body) > self._max_response_bytes:
                raise BackendReadError("response_too_large")
            budget.response_bytes += len(response.body)
            if budget.response_bytes > self._max_total_response_bytes:
                raise BackendReadError("response_too_large")
            match = _CONTENT_RANGE.fullmatch(response.content_range or "")
            if match is None or match.group("total") == "*":
                raise BackendReadError("read_limit_exceeded")
            if any(
                value is not None and len(value) > 10
                for value in (match.group("start"), match.group("end"), match.group("total"))
            ):
                raise BackendReadError("read_limit_exceeded")
            total = int(match.group("total"))
            if total > self._max_rows:
                raise BackendReadError("read_limit_exceeded")
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise BackendReadError("data_changed_during_read")
            rows = _parse_json_rows(response.body)
            self._check_budget(budget, verified)
            if len(rows) > self._page_size:
                raise BackendReadError("invalid_upstream_response")
            if total == 0:
                if rows or match.group("start") is not None or offset != 0:
                    raise BackendReadError("invalid_upstream_response")
                return []
            if match.group("start") is None or match.group("end") is None:
                raise BackendReadError("read_limit_exceeded")
            page_start = int(match.group("start"))
            page_end = int(match.group("end"))
            if page_start != offset or page_end < page_start or page_end >= total:
                raise BackendReadError("invalid_upstream_response")
            if len(rows) != page_end - page_start + 1:
                raise BackendReadError("invalid_upstream_response")
            if len(collected) + len(rows) > self._max_rows:
                raise BackendReadError("read_limit_exceeded")
            for row in rows:
                identity = self._row_identity(route, row)
                if identity in seen_keys:
                    raise BackendReadError("invalid_upstream_response")
                seen_keys.add(identity)
            collected.extend(rows)
            offset += len(rows)
            if offset == total:
                self._check_budget(budget, verified)
                return collected
            if offset > total or not rows:
                raise BackendReadError("invalid_upstream_response")
        raise BackendReadError("read_limit_exceeded")

    @staticmethod
    def _row_identity(route: str, row: Mapping[str, Any]) -> tuple[str, ...]:
        if route == _RPC_LIST_SETTLEMENT_OPTIONS:
            keys = ("debtor_participant_id", "creditor_participant_id", "currency")
        elif route == "sub_activity_participants":
            keys = ("activity_id", "ledger_unit_id", "participant_id")
        elif route == "activity_members":
            keys = ("activity_id",)
        else:
            keys = ("id",)
        values = tuple(row.get(key) for key in keys)
        if any(not isinstance(value, str) for value in values):
            raise BackendReadError("invalid_upstream_response")
        return tuple(values)  # type: ignore[return-value]

    @staticmethod
    def _lookup_ref(
        verified: VerifiedReadContext,
        ref: Any,
        expected_kind: Literal["activity", "expense", "ledger_unit", "participant"],
    ) -> BoundRef:
        expected_type: type[c.ContractEnum]
        if expected_kind == "activity":
            expected_type = c.ActivityRef
        elif expected_kind == "expense":
            expected_type = c.ExpenseRef
        elif expected_kind == "ledger_unit":
            expected_type = c.LedgerUnitRef
        else:
            expected_type = c.ParticipantRef
        if not isinstance(ref, expected_type):
            raise BackendReadError("unsupported_scope")
        token = ref.value
        bound = verified.refs_by_opaque_token.get(token)
        if not isinstance(bound, BoundRef) or bound.kind != expected_kind:
            raise BackendReadError("unsupported_scope")
        if not isinstance(bound.object_id, uuid.UUID):
            raise BackendReadError("invalid_auth_context")
        if expected_kind == "activity" and bound.activity_id not in (None, bound.object_id):
            raise BackendReadError("unsupported_scope")
        return bound

    async def read(
        self,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        context: c.ModelContext,
        decision: c.ReadDecision,
        *,
        verified: VerifiedReadContext,
    ) -> P2BackendReadResult:
        """Read one frozen v1 operation and return private, typed source rows."""
        self._validate_grant(verified, owner_user_id=owner_user_id, turn_id=turn_id)
        if not isinstance(decision, c.ReadDecision):
            raise BackendReadError("unsupported_read")
        self._validate_read_context(context, decision, verified)
        budget = _ReadBudget()
        observed_at = datetime.now(timezone.utc)
        if decision.operation == c.ReadOperation.ACTIVITIES:
            return await self._read_activities(decision, verified, observed_at, budget)
        if decision.operation == c.ReadOperation.EXPENSES:
            return await self._read_expenses(decision, verified, observed_at, budget)
        if decision.operation == c.ReadOperation.DEBTS:
            return await self._read_debts(decision, verified, observed_at, budget)
        raise BackendReadError("unsupported_read")

    def _validate_read_context(
        self, context: c.ModelContext, decision: c.ReadDecision,
        verified: VerifiedReadContext,
    ) -> None:
        if not isinstance(context, c.ModelContext):
            raise BackendReadError("unsupported_scope")
        permission_by_operation = {
            c.ReadOperation.ACTIVITIES: c.HarnessPermission.READ_ACTIVITIES,
            c.ReadOperation.EXPENSES: c.HarnessPermission.READ_EXPENSES,
            c.ReadOperation.DEBTS: c.HarnessPermission.READ_DEBTS,
        }
        permission = permission_by_operation.get(decision.operation)
        if permission is None or permission not in context.available_permissions:
            raise BackendReadError("unsupported_read")

        activity_scope_id: uuid.UUID | None = None
        if isinstance(context.verified_scope, c.ModelActivityScope):
            activity_scope = context.verified_scope
            activity_binding = self._lookup_ref(verified, activity_scope.activity_ref, "activity")
            activity_scope_id = activity_binding.object_id
        elif not isinstance(context.verified_scope, c.ModelNoActivityScope):
            raise BackendReadError("unsupported_scope")

        context_refs: set[tuple[str, c.ContractEnum]] = set()
        for reference in context.bound_references:
            expected_kind: Literal["activity", "expense", "ledger_unit", "participant"]
            if isinstance(reference, c.ModelActivityReference):
                expected_kind = "activity"
            elif isinstance(reference, c.ModelExpenseReference):
                expected_kind = "expense"
            elif isinstance(reference, c.ModelLedgerUnitReference):
                expected_kind = "ledger_unit"
            elif isinstance(reference, c.ModelParticipantReference):
                expected_kind = "participant"
            else:
                raise BackendReadError("unsupported_scope")
            binding = self._lookup_ref(verified, reference.ref, expected_kind)
            if activity_scope_id is None:
                if expected_kind != "activity":
                    raise BackendReadError("unsupported_scope")
            elif expected_kind == "activity":
                if binding.object_id != activity_scope_id:
                    raise BackendReadError("unsupported_scope")
            elif binding.activity_id != activity_scope_id:
                raise BackendReadError("unsupported_scope")
            context_refs.add((expected_kind, reference.ref))

        if decision.operation in (c.ReadOperation.EXPENSES, c.ReadOperation.DEBTS):
            if not isinstance(context.verified_scope, c.ModelActivityScope):
                raise BackendReadError("unsupported_scope")
            criteria = decision.criteria
            if not isinstance(criteria, (c.ReadExpensesCriteria, c.ReadDebtsCriteria)):
                raise BackendReadError("unsupported_read")
            if criteria.activity_ref != context.verified_scope.activity_ref:
                raise BackendReadError("unsupported_scope")
            if ("activity", criteria.activity_ref) not in context_refs:
                raise BackendReadError("unsupported_scope")
            if criteria.participant_ref is not None:
                if ("participant", criteria.participant_ref) not in context_refs:
                    raise BackendReadError("unsupported_scope")

    async def _read_activities(
        self, decision: c.ReadDecision, verified: VerifiedReadContext,
        observed_at: datetime, budget: _ReadBudget,
    ) -> P2BackendReadResult:
        criteria = decision.criteria
        if not isinstance(criteria, c.ReadActivitiesCriteria):
            raise BackendReadError("unsupported_read")
        rows = await self._get_table(
            "activities", _ACTIVITY_SELECT, [("is_deleted", "eq.false")], verified,
            budget=budget, order="name.asc,id.asc",
        )
        activities = tuple(_activity_dto(row) for row in rows)
        filtered: list[P2ActivityDTO] = []
        name_filter = criteria.name_contains.casefold() if criteria.name_contains else None
        for item in activities:
            if item.is_deleted:
                continue
            status = "archived" if item.archived_at else "active"
            if criteria.status != "any" and status != criteria.status:
                continue
            if name_filter is not None and name_filter not in item.name.casefold():
                continue
            filtered.append(item)
        if len(filtered) > self._max_facts:
            raise BackendReadError("read_limit_exceeded")
        for item in filtered:
            await self._require_membership(item.activity_id, verified, budget)
        self._check_budget(budget, verified)
        return P2BackendReadResult(
            operation=decision.operation, observed_at=observed_at, source="supabase_postgrest",
            activities=tuple(filtered),
            financial_versions={item.activity_id: item.financial_version for item in filtered},
        )

    async def _read_expenses(
        self, decision: c.ReadDecision, verified: VerifiedReadContext,
        observed_at: datetime, budget: _ReadBudget,
    ) -> P2BackendReadResult:
        criteria = decision.criteria
        if not isinstance(criteria, c.ReadExpensesCriteria):
            raise BackendReadError("unsupported_read")
        activity_ref = self._lookup_ref(verified, criteria.activity_ref, "activity")
        activity_id = activity_ref.object_id
        await self._require_membership(activity_id, verified, budget)
        start_activity = await self._get_activity(activity_id, verified, budget)
        units, participants, child_scopes = await self._load_activity_scope(
            activity_id, verified, budget,
        )
        unit_by_id = {unit.ledger_unit_id: unit for unit in units}
        if not unit_by_id:
            raise BackendReadError("scope_unavailable")
        active_participant_ids = {
            participant.participant_id for participant in participants if not participant.is_deleted
        }
        participant_id: uuid.UUID | None = None
        if criteria.participant_ref is not None:
            participant_ref = self._lookup_ref(verified, criteria.participant_ref, "participant")
            if (
                participant_ref.activity_id != activity_id
                or participant_ref.object_id not in active_participant_ids
            ):
                raise BackendReadError("unsupported_scope")
            participant_id = participant_ref.object_id

        filters: list[tuple[str, str]] = [
            ("ledger_unit_id", f"in.({','.join(str(key) for key in sorted(unit_by_id, key=str))})"),
            ("is_deleted", "eq.false"),
        ]
        if criteria.from_date is not None:
            start = datetime.combine(criteria.from_date, datetime.min.time(), timezone.utc)
            filters.append(("occurred_at", f"gte.{start.isoformat().replace('+00:00', 'Z')}"))
        if criteria.to_date is not None:
            if criteria.to_date == date.max:
                end_inclusive = datetime.combine(criteria.to_date, datetime.max.time(), timezone.utc)
                filters.append(("occurred_at", f"lte.{end_inclusive.isoformat().replace('+00:00', 'Z')}"))
            else:
                end_exclusive = datetime.combine(
                    criteria.to_date + timedelta(days=1), datetime.min.time(), timezone.utc,
                )
                filters.append(("occurred_at", f"lt.{end_exclusive.isoformat().replace('+00:00', 'Z')}"))
        expense_rows = await self._get_table(
            "expenses", _EXPENSE_SELECT, filters, verified,
            budget=budget, order="occurred_at.desc,id.asc",
        )
        expenses_by_id: dict[uuid.UUID, P2ExpenseDTO] = {}
        for row in expense_rows:
            unit_id = _parse_uuid(row.get("ledger_unit_id"))
            unit = unit_by_id.get(unit_id)
            if unit is None or unit.activity_id != activity_id:
                raise BackendReadError("invalid_upstream_response")
            expense = _expense_dto(row, activity_id)
            if expense.is_deleted or expense.expense_id in expenses_by_id:
                raise BackendReadError("invalid_upstream_response")
            expenses_by_id[expense.expense_id] = expense

        if expenses_by_id:
            expense_ids = ",".join(str(item) for item in sorted(expenses_by_id, key=str))
            in_filter = f"in.({expense_ids})"
            payment_rows = await self._get_table(
                "payments", _PAYMENT_SELECT, [("expense_id", in_filter)], verified,
                budget=budget, order="expense_id.asc,id.asc",
            )
            split_rows = await self._get_table(
                "splits", _SPLIT_SELECT, [("expense_id", in_filter)], verified,
                budget=budget, order="expense_id.asc,id.asc",
            )
        else:
            payment_rows = []
            split_rows = []

        payments_by_expense: dict[uuid.UUID, list[P2PaymentDTO]] = {}
        for row in payment_rows:
            payment = _payment_dto(row)
            if payment.expense_id not in expenses_by_id or payment.participant_id not in active_participant_ids:
                raise BackendReadError("invalid_upstream_response")
            payments_by_expense.setdefault(payment.expense_id, []).append(payment)
        splits_by_expense: dict[uuid.UUID, list[P2SplitDTO]] = {}
        for row in split_rows:
            split = _split_dto(row)
            if split.expense_id not in expenses_by_id or split.participant_id not in active_participant_ids:
                raise BackendReadError("invalid_upstream_response")
            splits_by_expense.setdefault(split.expense_id, []).append(split)

        child_scope_by_unit = {scope.ledger_unit_id: scope for scope in child_scopes}
        materialized: list[P2ExpenseDTO] = []
        for expense in expenses_by_id.values():
            payments = tuple(sorted(
                payments_by_expense.get(expense.expense_id, ()), key=lambda row: str(row.payment_id),
            ))
            splits = tuple(sorted(
                splits_by_expense.get(expense.expense_id, ()), key=lambda row: str(row.split_id),
            ))
            if not payments or not splits:
                raise BackendReadError("invalid_upstream_response")
            unit = unit_by_id[expense.ledger_unit_id]
            if unit.unit_type == "sub_activity":
                scope = child_scope_by_unit.get(unit.ledger_unit_id)
                if scope is None:
                    raise BackendReadError("scope_unavailable")
                if scope.configured:
                    allowed = set(scope.participant_ids)
                    if any(row.participant_id not in allowed for row in (*payments, *splits)):
                        raise BackendReadError("scope_unavailable")
            expense = replace(expense, payments=payments, splits=splits)
            if participant_id is not None and participant_id not in {
                *(row.participant_id for row in payments),
                *(row.participant_id for row in splits),
            }:
                continue
            materialized.append(expense)

        if len(materialized) > self._max_facts:
            raise BackendReadError("read_limit_exceeded")
        await self._require_membership(activity_id, verified, budget)
        end_scope = await self._load_activity_scope(activity_id, verified, budget)
        await self._require_membership(activity_id, verified, budget)
        end_activity = await self._get_activity(activity_id, verified, budget)
        if (
            end_activity.financial_version != start_activity.financial_version
            or end_scope != (units, participants, child_scopes)
        ):
            raise BackendReadError("data_changed_during_read")
        self._check_budget(budget, verified)
        return P2BackendReadResult(
            operation=decision.operation, observed_at=observed_at, source="supabase_postgrest",
            expenses=tuple(materialized),
            financial_versions={activity_id: start_activity.financial_version},
        )

    async def _read_debts(
        self, decision: c.ReadDecision, verified: VerifiedReadContext,
        observed_at: datetime, budget: _ReadBudget,
    ) -> P2BackendReadResult:
        criteria = decision.criteria
        if not isinstance(criteria, c.ReadDebtsCriteria):
            raise BackendReadError("unsupported_read")
        activity_ref = self._lookup_ref(verified, criteria.activity_ref, "activity")
        activity_id = activity_ref.object_id
        await self._require_membership(activity_id, verified, budget)
        start_activity = await self._get_activity(activity_id, verified, budget)
        units, participants, child_scopes = await self._load_activity_scope(activity_id, verified, budget)
        if not units:
            raise BackendReadError("scope_unavailable")
        participant_ids = {item.participant_id for item in participants if not item.is_deleted}
        participant_id: uuid.UUID | None = None
        if criteria.participant_ref is not None:
            participant_ref = self._lookup_ref(verified, criteria.participant_ref, "participant")
            if participant_ref.activity_id != activity_id or participant_ref.object_id not in participant_ids:
                raise BackendReadError("unsupported_scope")
            participant_id = participant_ref.object_id

        rows = await self._get_json_rows(
            _RPC_LIST_SETTLEMENT_OPTIONS,
            [("p_activity_id", str(activity_id))], verified,
            budget=budget,
            order="debtor_participant_id.asc,creditor_participant_id.asc,currency.asc",
        )
        debts: list[P2DebtDTO] = []
        for row in rows:
            currency = _require_text(row, "currency")
            if not re.fullmatch(r"[A-Z]{3}", currency):
                raise BackendReadError("invalid_upstream_response")
            debt = P2DebtDTO(
                debtor_participant_id=_parse_uuid(row.get("debtor_participant_id")),
                creditor_participant_id=_parse_uuid(row.get("creditor_participant_id")),
                currency=currency,
                original_amount=_parse_decimal(row.get("original_amount")),  # type: ignore[arg-type]
                base_amount=_parse_decimal(row.get("base_amount")),  # type: ignore[arg-type]
                base_total=_parse_decimal(row.get("base_total")),  # type: ignore[arg-type]
                financial_version=_require_int(row, "financial_version"),
            )
            if (
                debt.debtor_participant_id not in participant_ids
                or debt.creditor_participant_id not in participant_ids
                or debt.debtor_participant_id == debt.creditor_participant_id
                or debt.original_amount <= 0
                or debt.financial_version != start_activity.financial_version
            ):
                raise BackendReadError("data_changed_during_read")
            if participant_id is not None and participant_id not in (
                debt.debtor_participant_id, debt.creditor_participant_id,
            ):
                continue
            if criteria.currency is not None and debt.currency != criteria.currency:
                continue
            debts.append(debt)
        if len(debts) > self._max_facts:
            raise BackendReadError("read_limit_exceeded")
        await self._require_membership(activity_id, verified, budget)
        end_scope = await self._load_activity_scope(activity_id, verified, budget)
        await self._require_membership(activity_id, verified, budget)
        end_activity = await self._get_activity(activity_id, verified, budget)
        if (
            end_activity.financial_version != start_activity.financial_version
            or end_scope != (units, participants, child_scopes)
        ):
            raise BackendReadError("data_changed_during_read")
        self._check_budget(budget, verified)
        return P2BackendReadResult(
            operation=decision.operation, observed_at=observed_at, source="supabase_postgrest",
            debts=tuple(debts), financial_versions={activity_id: start_activity.financial_version},
        )

    async def _get_table(
        self,
        table: str,
        select: str,
        filters: Sequence[tuple[str, str]],
        verified: VerifiedReadContext,
        *,
        budget: _ReadBudget,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        if table not in self._TABLES:
            raise BackendReadError("unsupported_read")
        return await self._get_json_rows(
            table, [("select", select), *filters], verified, budget=budget, order=order,
        )


