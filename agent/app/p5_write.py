"""P5.0 real write path for `expense.create`.

This module is deliberately narrow: it calls one existing, reviewed business RPC
(`public.create_expense_auto_rate`) with the caller's own Supabase access token,
and it never uses a service-role key. It adds no business semantics; the RPC
still owns membership, archive, allocation, conservation and FX checks.

What P5.0 adds on the Agent side:

* a preview built from a *fresh server read* (Activity financial version,
  participants, ledger units), never from client- or model-supplied IDs;
* an execution identity derived from (actor, proposal, revision), so a repeated
  confirmation cannot dispatch a second write;
* a pre-dispatch version re-read that closes a stale preview instead of writing;
* four terminal outcomes: succeeded, rejected, closed and unknown. An unknown
  transport result is never reported as success.

Known limit: `create_expense_auto_rate` has no server-side request id, so a lost
response cannot be recovered by a unique database key. This module therefore
refuses to retry an unknown execution; reconciliation is bounded and read-only.
"""

from __future__ import annotations

import http.client
import json
import socket
import ssl
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import urlencode, urlsplit

from . import contracts as c
from .p2_backend import (
    BackendReadError, BoundRef, P2BackendAdapter, ScopeRequest, VerifiedReadContext,
)
from .ports import ComponentHealth, Principal, ScopeDenied
from .store import (
    ProposalConflict, ProposalExpired, SQLiteAgentStore, StateConflict,
)


P5_POLICY_VERSION = "p5-live-expense-create-v1"
P5_UPDATE_POLICY_VERSION = "p5-live-expense-update-v1"
P5_PRESENTATION_POLICY_VERSION = "p5-live-expense-presentation-v1"
P5_DELETE_POLICY_VERSION = "p5-live-expense-delete-v1"
P5_REPAYMENT_POLICY_VERSION = "p5-live-repayment-v1"
P5_VOID_POLICY_VERSION = "p5-live-transfer-void-v1"
P5_PREPAYMENT_POLICY_VERSION = "p5-live-prepayment-v1"
P5_PREPAYMENT_RETURN_POLICY_VERSION = "p5-live-prepayment-return-v1"
RPC_CREATE_EXPENSE = "/rest/v1/rpc/create_expense_auto_rate"
RPC_UPDATE_EXPENSE = "/rest/v1/rpc/update_expense_auto_rate"
RPC_UPDATE_PRESENTATION = "/rest/v1/rpc/update_expense_presentation"
RPC_DELETE_EXPENSE = "/rest/v1/rpc/delete_expense"
RPC_PREVIEW_REPAYMENT = "/rest/v1/rpc/preview_expense_repayment"
RPC_CREATE_REPAYMENT = "/rest/v1/rpc/create_expense_repayment_v2"
RPC_LIST_REPAYMENT_CANDIDATES = "/rest/v1/rpc/list_transfer_expense_candidates"
RPC_VOID_SETTLEMENT = "/rest/v1/rpc/void_settlement_transfer"
RPC_VOID_PREPAYMENT = "/rest/v1/rpc/void_prepayment_transfer"
RPC_PREVIEW_PREPAYMENT = "/rest/v1/rpc/preview_prepayment"
RPC_CREATE_PREPAYMENT = "/rest/v1/rpc/create_prepayment_v2"
RPC_CREATE_PREPAYMENT_RETURN = "/rest/v1/rpc/create_prepayment_return_v2"
_PREPAYMENT_ACCOUNT_SELECT = "id,balance"
_TRANSFER_SELECT = (
    "id,activity_id,type,from_participant_id,to_participant_id,amount,currency,"
    "recorded_by,is_voided,voided_at,voided_by,void_reason"
)
_ACTIVITY_STATE_SELECT = "id,created_by,archived_at,is_deleted,financial_version"

# Public schema constraint `expenses_icon_key_supported`. The server normalizes
# an unknown key to "money"; P5.2 rejects it instead of silently changing it.
SUPPORTED_ICON_KEYS = frozenset({
    "money", "dining", "shopping", "transport", "hotel", "ticket",
    "fuel", "entertainment", "medical", "gift", "grocery", "flight",
})

_EXPENSE_SELECT = (
    "id,ledger_unit_id,title,original_amount,original_currency,base_amount,"
    "split_method,occurred_at,note,original_expense_id,version,is_deleted,"
    "financial_locked,icon_key,created_by"
)
_PAYMENT_SELECT = "id,expense_id,participant_id,amount"
_SPLIT_SELECT = "id,expense_id,participant_id,amount"
_UNIT_SELECT = "id,activity_id,name,is_deleted"

_PREFLIGHT_CLOSE_SUMMARY = {
    "foreign_currency_not_in_p5": "P5 executes base-currency expenses only",
    "preview_stale": "the preview is no longer current",
    "expense_changed": "the Expense changed after the preview",
    "expense_deleted": "the Expense was deleted",
    "expense_financial_locked": "the Expense is financially locked",
    "refund_update_not_in_p5": "linked refund updates are outside P5.1",
    "expense_not_found": "the Expense was not found",
    "invalid_command": "the fixed update command is incomplete",
    "amount_allocation_mismatch": "payments or manual splits do not match the new amount",
    "expense_version_conflict": "the Expense version changed after the preview",
    "invalid_icon_key": "the icon key is not supported",
    "no_change": "the presentation fields did not change",
    "delete_not_permitted": "only the Expense creator or Activity creator may delete it",
    "activity_not_found": "the Activity was not found",
    "repayment_invalid": "the repayment request is invalid",
    "repayment_participant_invalid": "the repayment participants are not active in this Activity",
    "repayment_exceeds_debt_or_target": "the repayment exceeds the selected debt or target",
    "repayment_version_conflict": "the Activity financial version changed",
    "actor_not_permitted": "the current user may not record this repayment",
    "repayment_preview_rejected": "the server refused the repayment preview",
    "request_id_conflict": "the request id was already used with a different payload",
    "transfer_not_found": "the Transfer was not found",
    "transfer_already_voided": "the Transfer is already voided",
    "void_not_permitted": "only the recorder or the Activity creator may void this Transfer",
    "unsupported_transfer_type": "the Transfer type cannot be voided by this API",
    "void_state_changed": "the Transfer state changed after the preview",
    "transfer_type_changed": "the Transfer type changed after the preview",
    "activity_changed": "the Activity changed while the void outcome was unresolved",
    "void_not_applied": "the Transfer is not voided and its Activity version is unchanged",
    "voided_elsewhere": "the Transfer is voided but this execution cannot be proven to be the author",
    "prepayment_requires_large_activity": "prepayment is supported only in large activities",
    "prepayment_invalid": "the prepayment request is invalid",
    "prepayment_participant_invalid": "the prepayment participants are not active in this Activity",
    "prepayment_currency_unsupported": "the Activity does not accept this currency",
    "prepayment_amount_precision": "base-currency prepayment amounts need one decimal place",
    "prepayment_preview_rejected": "the server refused the prepayment preview",
    "prepayment_version_conflict": "the Activity financial version changed",
    "prepayment_return_exceeds_balance": "the return exceeds the balance the server holds",
    "prepayment_account_unavailable": "the prepayment account could not be read",
}


class LiveWriteError(RuntimeError):
    """Stable, redacted write-path failure.

    `ambiguous` means the request may have reached Postgres and committed; the
    caller must record UNKNOWN rather than retry.
    """

    def __init__(
        self,
        code: str,
        *,
        ambiguous: bool = False,
        retryable: bool = False,
        http_status: int | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.ambiguous = ambiguous
        self.retryable = retryable
        self.http_status = http_status


@dataclass(frozen=True, slots=True)
class LiveWriteConfig:
    project_url: str
    publishable_key: str = field(repr=False, compare=False)
    timeout_seconds: float = 5.0
    max_response_bytes: int = 262_144
    policy_version: str = P5_POLICY_VERSION


class LiveWriteTransport(Protocol):
    def post_json(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        *,
        timeout: float,
        max_response_bytes: int,
    ) -> tuple[int, bytes]: ...

    def get_json(
        self,
        url: str,
        headers: Mapping[str, str],
        *,
        timeout: float,
        max_response_bytes: int,
    ) -> tuple[int, bytes]: ...


class StdlibWriteTransport:
    """Bounded GET/POST; no redirects, no retries, no connection reuse."""

    def post_json(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        *,
        timeout: float,
        max_response_bytes: int,
    ) -> tuple[int, bytes]:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        return self._request(
            "POST", url, headers, body=body, timeout=timeout,
            max_response_bytes=max_response_bytes, mutating=True,
        )

    def get_json(
        self,
        url: str,
        headers: Mapping[str, str],
        *,
        timeout: float,
        max_response_bytes: int,
    ) -> tuple[int, bytes]:
        return self._request(
            "GET", url, headers, body=None, timeout=timeout,
            max_response_bytes=max_response_bytes, mutating=False,
        )

    def _request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        *,
        body: bytes | None,
        timeout: float,
        max_response_bytes: int,
        mutating: bool,
    ) -> tuple[int, bytes]:
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise LiveWriteError("invalid_endpoint")
        if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise LiveWriteError("invalid_endpoint")
        connection: http.client.HTTPConnection | None = None
        request_sent = False
        try:
            if parsed.scheme == "https":
                connection = http.client.HTTPSConnection(
                    parsed.hostname, parsed.port or 443,
                    timeout=timeout, context=ssl.create_default_context(),
                )
            else:
                connection = http.client.HTTPConnection(
                    parsed.hostname, parsed.port or 80, timeout=timeout,
                )
            path = parsed.path or "/"
            if parsed.query:
                path = f"{path}?{parsed.query}"
            request_sent = True
            connection.request(method, path, body=body, headers=dict(headers))
            response = connection.getresponse()
            content = response.read(max_response_bytes + 1)
            if len(content) > max_response_bytes:
                raise LiveWriteError("upstream_response_too_large", ambiguous=mutating)
            return int(response.status), content
        except LiveWriteError:
            raise
        except (ConnectionRefusedError, socket.gaierror) as exc:
            # The request never left this process.
            raise LiveWriteError("upstream_unreachable", retryable=True) from exc
        except (TimeoutError, socket.timeout, ConnectionResetError, ssl.SSLError,
                http.client.RemoteDisconnected, http.client.IncompleteRead, OSError) as exc:
            # Once request() started, a timeout or reset on a mutating request
            # cannot tell us whether Postgres committed. Never retry it. A GET
            # is always safe to retry.
            ambiguous = mutating and request_sent
            raise LiveWriteError(
                "upstream_ambiguous" if ambiguous else "upstream_unreachable",
                ambiguous=ambiguous, retryable=not ambiguous,
            ) from exc
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass


@dataclass(frozen=True, slots=True)
class LiveTransferState:
    transfer_id: uuid.UUID
    activity_id: uuid.UUID
    transfer_type: str
    from_participant_id: uuid.UUID
    to_participant_id: uuid.UUID
    amount: str
    currency: str
    recorded_by: uuid.UUID
    is_voided: bool
    voided_at: datetime | None
    voided_by: uuid.UUID | None
    void_reason: str | None


@dataclass(frozen=True, slots=True)
class LiveActivityState:
    activity_id: uuid.UUID
    created_by: uuid.UUID | None
    archived_at: datetime | None
    is_deleted: bool
    financial_version: int


@dataclass(frozen=True, slots=True)
class LiveWriteOutcome:
    resolution: c.ExecutionResolution
    code: str
    summary: str


@dataclass(frozen=True, slots=True)
class LiveExpenseState:
    expense_id: uuid.UUID
    ledger_unit_id: uuid.UUID
    title: str
    original_amount: str
    original_currency: str
    base_amount: str
    split_method: str
    occurred_at: datetime | None
    note: str | None
    original_expense_id: uuid.UUID | None
    version: int
    is_deleted: bool
    financial_locked: bool
    icon_key: str | None
    created_by: uuid.UUID | None
    payments: tuple[tuple[uuid.UUID, str], ...]
    splits: tuple[tuple[uuid.UUID, str], ...]

    def canonical_split(self) -> c.CanonicalSplit:
        if self.split_method == "equal":
            return c.CanonicalEqualSplit(
                mode="equal",
                participant_ids=[participant_id for participant_id, _ in self.splits],
            )
        return c.CanonicalManualSplit(
            mode="manual",
            allocations=[
                c.CanonicalPayment(participant_id=participant_id, amount=amount)
                for participant_id, amount in self.splits
            ],
        )

    def canonical_payments(self) -> list[c.CanonicalPayment]:
        return [
            c.CanonicalPayment(participant_id=participant_id, amount=amount)
            for participant_id, amount in self.payments
        ]


class LiveExpenseGateway:
    """Real `expense.create` preview and execution behind the Agent Gateway port."""

    def __init__(
        self,
        config: LiveWriteConfig,
        store: SQLiteAgentStore,
        read_backend: P2BackendAdapter,
        transport: LiveWriteTransport | None = None,
    ) -> None:
        self._config = config
        self._store = store
        self._read_backend = read_backend
        self._transport = transport or StdlibWriteTransport()

    def health(self) -> ComponentHealth:
        return ComponentHealth(status="ready", available=True)

    async def read_expense_state(
        self, access_token: str, expense_id: uuid.UUID,
    ) -> LiveExpenseState:
        rows = await self._get_rows(
            "expenses",
            [("id", f"eq.{expense_id}"), ("select", _EXPENSE_SELECT), ("limit", "2")],
            access_token,
        )
        if len(rows) != 1:
            raise LiveWriteError("expense_not_found")
        row = rows[0]
        payments = await self._get_rows(
            "payments",
            [("expense_id", f"eq.{expense_id}"), ("select", _PAYMENT_SELECT), ("order", "id.asc")],
            access_token,
        )
        splits = await self._get_rows(
            "splits",
            [("expense_id", f"eq.{expense_id}"), ("select", _SPLIT_SELECT), ("order", "id.asc")],
            access_token,
        )
        return LiveExpenseState(
            expense_id=_uuid(row.get("id")),
            ledger_unit_id=_uuid(row.get("ledger_unit_id")),
            title=str(row.get("title")),
            original_amount=_num_text(row.get("original_amount")),
            original_currency=str(row.get("original_currency")),
            base_amount=_num_text(row.get("base_amount")),
            split_method=str(row.get("split_method")),
            occurred_at=_parse_timestamp(row.get("occurred_at")),
            note=row.get("note") if isinstance(row.get("note"), str) else None,
            original_expense_id=_uuid_or_none(row.get("original_expense_id")),
            version=_int(row.get("version")),
            is_deleted=_bool(row.get("is_deleted")),
            financial_locked=_bool(row.get("financial_locked")),
            icon_key=row.get("icon_key") if isinstance(row.get("icon_key"), str) else None,
            created_by=_uuid_or_none(row.get("created_by")),
            payments=tuple(
                (_uuid(item.get("participant_id")), _num_text(item.get("amount")))
                for item in payments
            ),
            splits=tuple(
                (_uuid(item.get("participant_id")), _num_text(item.get("amount")))
                for item in splits
            ),
        )

    async def find_expenses_by_title(
        self, access_token: str, activity_id: uuid.UUID, title: str,
    ) -> list[tuple[uuid.UUID, str, uuid.UUID, int]]:
        units = await self._get_rows(
            "ledger_units",
            [
                ("activity_id", f"eq.{activity_id}"), ("is_deleted", "eq.false"),
                ("select", "id,is_deleted"), ("order", "id.asc"),
            ],
            access_token,
        )
        unit_ids = [
            _uuid(item.get("id")) for item in units if not _bool(item.get("is_deleted"))
        ]
        if not unit_ids:
            return []
        rows = await self._get_rows(
            "expenses",
            [
                ("ledger_unit_id", "in.(" + ",".join(str(item) for item in unit_ids) + ")"),
                ("is_deleted", "eq.false"),
                ("select", "id,ledger_unit_id,title,version"),
                ("order", "id.asc"),
            ],
            access_token,
        )
        return [
            (
                _uuid(item.get("id")), str(item.get("title")),
                _uuid(item.get("ledger_unit_id")), _int(item.get("version")),
            )
            for item in rows
            if str(item.get("title")) == title
        ]

    async def list_expenses(
        self, access_token: str, activity_id: uuid.UUID, *, include_deleted: bool = False,
    ) -> list[tuple[uuid.UUID, str, int]]:
        units = await self._get_rows(
            "ledger_units",
            [
                ("activity_id", f"eq.{activity_id}"), ("is_deleted", "eq.false"),
                ("select", "id,is_deleted"), ("order", "id.asc"),
            ],
            access_token,
        )
        unit_ids = [
            _uuid(item.get("id")) for item in units if not _bool(item.get("is_deleted"))
        ]
        if not unit_ids:
            return []
        params: list[tuple[str, str]] = [
            ("ledger_unit_id", "in.(" + ",".join(str(item) for item in unit_ids) + ")"),
            ("select", "id,title,version"),
            ("order", "id.asc"),
        ]
        if not include_deleted:
            params.append(("is_deleted", "eq.false"))
        rows = await self._get_rows("expenses", params, access_token)
        return [(_uuid(item.get("id")), str(item.get("title")), _int(item.get("version"))) for item in rows]

    async def read_activity_state(
        self, access_token: str, activity_id: uuid.UUID,
    ) -> LiveActivityState:
        rows = await self._get_rows(
            "activities",
            [("id", f"eq.{activity_id}"), ("select", _ACTIVITY_STATE_SELECT), ("limit", "2")],
            access_token,
        )
        if len(rows) != 1:
            raise LiveWriteError("activity_not_found")
        row = rows[0]
        return LiveActivityState(
            activity_id=_uuid(row.get("id")),
            created_by=_uuid_or_none(row.get("created_by")),
            archived_at=_parse_timestamp(row.get("archived_at")),
            is_deleted=_bool(row.get("is_deleted")),
            financial_version=_int(row.get("financial_version")),
        )

    async def read_transfer_state(
        self, access_token: str, transfer_id: uuid.UUID,
    ) -> LiveTransferState:
        rows = await self._get_rows(
            "transfers",
            [("id", f"eq.{transfer_id}"), ("select", _TRANSFER_SELECT), ("limit", "2")],
            access_token,
        )
        if len(rows) != 1:
            raise LiveWriteError("transfer_not_found")
        return _transfer_state(rows[0])

    async def list_transfers(
        self, access_token: str, activity_id: uuid.UUID,
    ) -> list[LiveTransferState]:
        rows = await self._get_rows(
            "transfers",
            [
                ("activity_id", f"eq.{activity_id}"),
                ("select", _TRANSFER_SELECT),
                ("order", "created_at.asc"),
            ],
            access_token,
        )
        return [_transfer_state(row) for row in rows]

    async def read_activity_creator(
        self, access_token: str, activity_id: uuid.UUID,
    ) -> uuid.UUID | None:
        rows = await self._get_rows(
            "activities",
            [("id", f"eq.{activity_id}"), ("select", "id,created_by"), ("limit", "2")],
            access_token,
        )
        if len(rows) != 1:
            raise LiveWriteError("activity_not_found")
        return _uuid_or_none(rows[0].get("created_by"))

    async def _post_rpc(
        self, path: str, access_token: str, payload: Mapping[str, Any],
    ) -> tuple[int, bytes]:
        return await _call_async(
            self._transport.post_json,
            f"{self._config.project_url.rstrip('/')}{path}",
            {
                "apikey": self._config.publishable_key,
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            payload,
            timeout=self._config.timeout_seconds,
            max_response_bytes=self._config.max_response_bytes,
        )

    async def list_repayment_candidates(
        self,
        access_token: str,
        activity_id: uuid.UUID,
        from_participant_id: uuid.UUID,
        to_participant_id: uuid.UUID,
        currency: str,
    ) -> list[dict[str, Any]]:
        status, body = await self._post_rpc(
            RPC_LIST_REPAYMENT_CANDIDATES,
            access_token,
            {
                "activity_id": str(activity_id),
                "from_participant_id": str(from_participant_id),
                "to_participant_id": str(to_participant_id),
                "currency": currency,
            },
        )
        if status != 200:
            raise LiveWriteError(
                _repayment_error_code(status, _raw_error_code(_decode_rows(body))),
                retryable=status >= 500,
            )
        return _decode_read_rows(body)

    async def read_transfer_by_request_id(
        self, access_token: str, activity_id: uuid.UUID, request_id: uuid.UUID,
    ) -> dict[str, Any] | None:
        rows = await self._get_rows(
            "transfers",
            [
                ("activity_id", f"eq.{activity_id}"),
                ("request_id", f"eq.{request_id}"),
                ("select", "id,type,amount,currency,request_payload,request_result"),
                ("limit", "2"),
            ],
            access_token,
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise LiveWriteError("upstream_invalid_response")
        return rows[0]

    async def read_prepayment_balance(
        self,
        access_token: str,
        activity_id: uuid.UUID,
        owner_participant_id: uuid.UUID,
        custodian_participant_id: uuid.UUID,
        currency: str,
    ) -> str:
        """Read one prepayment account balance; absent account means zero."""
        rows = await self._get_rows(
            "prepayment_accounts",
            [
                ("activity_id", f"eq.{activity_id}"),
                ("owner_participant_id", f"eq.{owner_participant_id}"),
                ("custodian_participant_id", f"eq.{custodian_participant_id}"),
                ("currency", f"eq.{currency}"),
                ("select", _PREPAYMENT_ACCOUNT_SELECT),
                ("limit", "2"),
            ],
            access_token,
        )
        if not rows:
            return "0"
        if len(rows) != 1:
            raise LiveWriteError("upstream_invalid_response")
        return _num_text(rows[0].get("balance"))

    async def _get_rows(
        self, route: str, params: Sequence[tuple[str, str]], access_token: str,
    ) -> list[dict[str, Any]]:
        url = f"{self._config.project_url.rstrip('/')}/rest/v1/{route}"
        query = urlencode(list(params))
        if query:
            url = f"{url}?{query}"
        status, body = await _call_async(
            self._transport.get_json,
            url,
            {
                "apikey": self._config.publishable_key,
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
            timeout=self._config.timeout_seconds,
            max_response_bytes=self._config.max_response_bytes,
        )
        if status in (401, 403):
            raise LiveWriteError("auth_rejected", retryable=False, http_status=status)
        if status != 200:
            raise LiveWriteError("upstream_read_failed", retryable=status >= 500)
        return _decode_read_rows(body)

    # ------------------------------------------------------------------ preview

    async def build_preview(
        self,
        *,
        owner_user_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        intent: c.ExpenseCreateIntent,
        bound_references: Sequence[c.BoundReference],
        access_token: str,
        expires_at: datetime,
        agent_disable_revision: int,
        policy_version: str | None = None,
        summary_prefix: str = "",
        now: datetime | None = None,
    ) -> c.ProposalRecord:
        """Build a live proposal from a trusted intent and a fresh server read.

        The intent may only carry opaque references. Every ID used in the fixed
        command comes from a BoundReference, and every referenced entity is then
        re-checked against the authoritative Activity scope read with the
        caller's own JWT.
        """
        if not isinstance(intent, c.ExpenseCreateIntent):
            raise LiveWriteError("unsupported_operation")
        instant = _aware(now)
        activity_id, ledger_unit_id, payments, split = _resolve_create_bindings(
            intent, bound_references, turn_id=turn_id,
        )
        grant = _activity_grant(
            owner_user_id=owner_user_id, turn_id=turn_id,
            access_token=access_token, expires_at=expires_at,
            activity_id=activity_id,
        )
        scope = await self._read_backend.resolve_scope(
            grant, ScopeRequest(mode="activity", ui_activity_id_hint=activity_id),
        )
        _require_writable_activity(scope, original_currency=intent.original_currency)
        participant_ids = {item.participant_id for item in scope.participants if not item.is_deleted}
        unit_ids = {item.ledger_unit_id for item in scope.ledger_units if not item.is_deleted}
        if ledger_unit_id not in unit_ids:
            raise ScopeDenied("ledger unit is outside the refreshed Activity scope")
        for payment in payments:
            if payment.participant_id not in participant_ids:
                raise ScopeDenied("payer is outside the refreshed Activity scope")
        if isinstance(split, c.CanonicalEqualSplit):
            if any(item not in participant_ids for item in split.participant_ids):
                raise ScopeDenied("split participant is outside the refreshed Activity scope")
        else:
            if any(item.participant_id not in participant_ids for item in split.allocations):
                raise ScopeDenied("split participant is outside the refreshed Activity scope")

        occurred_at = intent.occurred_at or instant
        command = c.FixedExpenseCreateCommand(
            operation="expense.create",
            activity_id=activity_id,
            ledger_unit_id=ledger_unit_id,
            title=intent.title,
            original_amount=intent.original_amount,
            original_currency=intent.original_currency,
            payment_allocations=payments,
            split=split,
            occurred_at=occurred_at,
            note=intent.note,
            expected_financial_version=str(scope.activity.financial_version),
        )
        after = c.ExpenseSnapshot(
            ledger_unit_id=ledger_unit_id,
            title=command.title,
            original_amount=command.original_amount,
            original_currency=command.original_currency,
            # P5.0 accepts base-currency expenses only, so no FX computation is
            # needed at preview time; the RPC still stamps an identity snapshot.
            base_amount=command.original_amount,
            payment_allocations=command.payment_allocations,
            split=command.split,
            occurred_at=command.occurred_at,
            note=command.note,
            expense_version="1",
            financial_locked=False,
        )
        preview = c.ExpensePreview(
            kind="expense",
            summary=f"{summary_prefix}新增消费 {command.title} {command.original_amount} {command.original_currency}",
            before=None,
            after=after,
            changes=_create_changes(after),
            activity_financial_version=command.expected_financial_version,
            generated_at=instant,
            simulation=False,
        )
        policy = policy_version or self._config.policy_version
        preconditions = c.PreconditionSnapshot(
            activity_id=activity_id,
            permission_checked=True,
            agent_disable_revision=agent_disable_revision,
            activity_financial_version=command.expected_financial_version,
            expense_version=None,
            policy_version=policy,
            verified_at=instant,
        )
        digest = c.canonical_command_digest(command, preconditions, policy_version=policy)
        return c.ProposalRecord(
            proposal_id=uuid.uuid4(),
            owner_user_id=owner_user_id,
            session_id=session_id,
            turn_id=turn_id,
            revision=1,
            operation="expense.create",
            mode="backend",
            status=c.ProposalStatus.PENDING,
            intent=intent,
            canonical_command=command,
            preview=preview,
            preconditions=preconditions,
            command_digest=digest,
            confirmation_nonce=_new_nonce(),
            policy_version=policy,
            expires_at=instant.replace(microsecond=0) + timedelta(minutes=10),
            execution=None,
            request_receipts=[],
        )

    # --------------------------------------------------------------- update preview

    async def build_update_preview(
        self,
        *,
        owner_user_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        intent: c.ExpenseUpdateIntent,
        bound_references: Sequence[c.BoundReference],
        access_token: str,
        expires_at: datetime,
        agent_disable_revision: int,
        policy_version: str | None = None,
        summary_prefix: str = "",
        now: datetime | None = None,
    ) -> c.ProposalRecord:
        """Build a live update proposal from the current server state.

        The model/dev intent carries only a bound Expense reference and the
        fields the user asked to change. The canonical command stores the full
        merged state so a replay cannot reinterpret an omitted field.
        """
        if not isinstance(intent, c.ExpenseUpdateIntent):
            raise LiveWriteError("unsupported_operation")
        instant = _aware(now)
        binding = _resolve_expense_binding(intent, bound_references, turn_id)
        expense_id = binding.entity_id
        activity_id = binding.scope_activity_id
        resolved_payments, resolved_split = _resolve_update_bindings(
            intent, bound_references, turn_id, activity_id,
        )
        grant = _activity_grant(
            owner_user_id=owner_user_id, turn_id=turn_id,
            access_token=access_token, expires_at=expires_at,
            activity_id=activity_id,
        )
        scope = await self._read_backend.resolve_scope(
            grant, ScopeRequest(mode="activity", ui_activity_id_hint=activity_id),
        )
        _require_writable_activity(scope, original_currency=scope.activity.base_currency)
        state = await self.read_expense_state(access_token, expense_id)
        if state.is_deleted:
            raise LiveWriteError("expense_deleted")
        if state.financial_locked:
            raise LiveWriteError("expense_financial_locked")
        if state.original_expense_id is not None:
            raise LiveWriteError("refund_update_not_in_p5")
        if state.original_currency != scope.activity.base_currency:
            raise LiveWriteError("foreign_currency_not_in_p5")

        unit_ids = {item.ledger_unit_id for item in scope.ledger_units if not item.is_deleted}
        if state.ledger_unit_id not in unit_ids:
            raise ScopeDenied("expense ledger unit is outside the Activity scope")
        # The frozen ExpenseUpdateIntent has no ledger-unit change field; P5.1
        # preserves the Expense's current unit.
        merged_unit = state.ledger_unit_id
        if merged_unit not in unit_ids:
            raise ScopeDenied("target ledger unit is outside the Activity scope")
        merged_currency = intent.original_currency or state.original_currency
        if merged_currency != scope.activity.base_currency:
            raise LiveWriteError("foreign_currency_not_in_p5")
        merged_amount = intent.original_amount or state.original_amount
        merged_title = intent.title or state.title
        merged_payments = resolved_payments or state.canonical_payments()
        merged_split = resolved_split or state.canonical_split()
        merged_occurred = intent.occurred_at or state.occurred_at
        merged_note = intent.note if intent.note is not None else state.note

        merged_decimal = Decimal(merged_amount)
        if sum((Decimal(item.amount) for item in merged_payments), Decimal("0")) != merged_decimal:
            raise LiveWriteError("amount_allocation_mismatch")
        if isinstance(merged_split, c.CanonicalManualSplit) and (
            sum((Decimal(item.amount) for item in merged_split.allocations), Decimal("0"))
            != merged_decimal
        ):
            raise LiveWriteError("amount_allocation_mismatch")

        participant_ids = {item.participant_id for item in scope.participants if not item.is_deleted}
        for item in merged_payments:
            if item.participant_id not in participant_ids:
                raise ScopeDenied("payer is outside the Activity scope")
        if isinstance(merged_split, c.CanonicalEqualSplit):
            if any(item not in participant_ids for item in merged_split.participant_ids):
                raise ScopeDenied("split participant is outside the Activity scope")
        elif any(item.participant_id not in participant_ids for item in merged_split.allocations):
            raise ScopeDenied("split participant is outside the Activity scope")

        before = c.ExpenseSnapshot(
            ledger_unit_id=state.ledger_unit_id,
            title=state.title,
            original_amount=state.original_amount,
            original_currency=state.original_currency,
            base_amount=state.base_amount,
            payment_allocations=state.canonical_payments(),
            split=state.canonical_split(),
            occurred_at=state.occurred_at,
            note=state.note,
            icon_key=state.icon_key,
            expense_version=str(state.version),
            financial_locked=state.financial_locked,
        )
        after = c.ExpenseSnapshot(
            ledger_unit_id=merged_unit,
            title=merged_title,
            original_amount=merged_amount,
            original_currency=merged_currency,
            base_amount=_base_amount_text(merged_amount),
            payment_allocations=merged_payments,
            split=merged_split,
            occurred_at=merged_occurred,
            note=merged_note,
            icon_key=state.icon_key,
            expense_version=str(state.version + 1),
            financial_locked=state.financial_locked,
        )
        changes = _update_changes(before, after)
        if not changes:
            raise LiveWriteError("no_change")

        full_patch = c.CanonicalExpenseUpdatePatch(
            title=merged_title,
            original_amount=merged_amount,
            original_currency=merged_currency,
            ledger_unit_id=merged_unit,
            payment_allocations=merged_payments,
            split=merged_split,
            note=merged_note,
            occurred_at=merged_occurred,
        )
        command = c.FixedExpenseUpdateCommand(
            operation="expense.update",
            activity_id=activity_id,
            expense_id=expense_id,
            expected_expense_version=str(state.version),
            expected_financial_version=str(scope.activity.financial_version),
            patch=full_patch,
        )
        preview = c.ExpensePreview(
            kind="expense",
            summary=f"{summary_prefix}修改消费 {merged_title} {merged_amount} {merged_currency}",
            before=before,
            after=after,
            changes=changes,
            activity_financial_version=command.expected_financial_version,
            generated_at=instant,
            simulation=False,
        )
        policy = policy_version or self._config.policy_version
        preconditions = c.PreconditionSnapshot(
            activity_id=activity_id,
            permission_checked=True,
            agent_disable_revision=agent_disable_revision,
            activity_financial_version=command.expected_financial_version,
            expense_version=str(state.version),
            policy_version=policy,
            verified_at=instant,
        )
        digest = c.canonical_command_digest(command, preconditions, policy_version=policy)
        return c.ProposalRecord(
            proposal_id=uuid.uuid4(),
            owner_user_id=owner_user_id,
            session_id=session_id,
            turn_id=turn_id,
            revision=1,
            operation="expense.update",
            mode="backend",
            status=c.ProposalStatus.PENDING,
            intent=intent,
            canonical_command=command,
            preview=preview,
            preconditions=preconditions,
            command_digest=digest,
            confirmation_nonce=_new_nonce(),
            policy_version=policy,
            expires_at=instant.replace(microsecond=0) + timedelta(minutes=10),
            execution=None,
            request_receipts=[],
        )

    # ----------------------------------------------------------- presentation preview

    async def build_presentation_preview(
        self,
        *,
        owner_user_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        intent: c.ExpensePresentationUpdateIntent,
        bound_references: Sequence[c.BoundReference],
        access_token: str,
        expires_at: datetime,
        agent_disable_revision: int,
        policy_version: str | None = None,
        summary_prefix: str = "",
        now: datetime | None = None,
    ) -> c.ProposalRecord:
        """Build a presentation-only proposal.

        The RPC is explicitly allowed on financially locked Expenses. This
        builder therefore does **not** reject locked, deleted, archived or
        linked-refund rows; those outcomes are the RPC's to return. The only
        Agent-side rejection is a missing/ambiguous binding, an unsupported
        icon key, or a request that changes nothing.
        """
        if not isinstance(intent, c.ExpensePresentationUpdateIntent):
            raise LiveWriteError("unsupported_operation")
        instant = _aware(now)
        binding = _resolve_expense_binding(intent, bound_references, turn_id)
        expense_id = binding.entity_id
        activity_id = binding.scope_activity_id
        grant = _activity_grant(
            owner_user_id=owner_user_id, turn_id=turn_id,
            access_token=access_token, expires_at=expires_at,
            activity_id=activity_id,
        )
        # The activity read supplies membership and the preview's informational
        # financial version. It is NOT used as the presentation version guard.
        scope = await self._read_backend.resolve_scope(
            grant, ScopeRequest(mode="activity", ui_activity_id_hint=activity_id),
        )
        state = await self.read_expense_state(access_token, expense_id)
        if intent.icon_key is not None and intent.icon_key not in SUPPORTED_ICON_KEYS:
            raise LiveWriteError("invalid_icon_key")

        current_icon = state.icon_key or "money"
        merged_title = intent.title or state.title
        merged_note = intent.note if intent.note is not None else state.note
        merged_icon = intent.icon_key if intent.icon_key is not None else current_icon
        if (merged_title, merged_note, merged_icon) == (state.title, state.note, current_icon):
            raise LiveWriteError("no_change")

        before = c.ExpenseSnapshot(
            ledger_unit_id=state.ledger_unit_id,
            title=state.title,
            original_amount=state.original_amount,
            original_currency=state.original_currency,
            base_amount=state.base_amount,
            payment_allocations=state.canonical_payments(),
            split=state.canonical_split(),
            occurred_at=state.occurred_at,
            note=state.note,
            icon_key=current_icon,
            expense_version=str(state.version),
            financial_locked=state.financial_locked,
        )
        after = c.ExpenseSnapshot(
            ledger_unit_id=state.ledger_unit_id,
            title=merged_title,
            original_amount=state.original_amount,
            original_currency=state.original_currency,
            base_amount=state.base_amount,
            payment_allocations=state.canonical_payments(),
            split=state.canonical_split(),
            occurred_at=state.occurred_at,
            note=merged_note,
            icon_key=merged_icon,
            expense_version=str(state.version + 1),
            financial_locked=state.financial_locked,
        )
        changes = _presentation_changes(before, after)
        if not changes:
            raise LiveWriteError("no_change")

        patch = c.CanonicalExpensePresentationPatch(
            title=merged_title, note=merged_note, icon_key=merged_icon,
        )
        command = c.FixedExpensePresentationCommand(
            operation="expense.presentation.update",
            activity_id=activity_id,
            expense_id=expense_id,
            expected_expense_version=str(state.version),
            patch=patch,
        )
        preview = c.ExpensePreview(
            kind="expense",
            summary=f"{summary_prefix}修改消费展示 {merged_title}",
            before=before,
            after=after,
            changes=changes,
            activity_financial_version=str(scope.activity.financial_version),
            generated_at=instant,
            simulation=False,
        )
        policy = policy_version or self._config.policy_version
        preconditions = c.PreconditionSnapshot(
            activity_id=activity_id,
            permission_checked=True,
            agent_disable_revision=agent_disable_revision,
            activity_financial_version=str(scope.activity.financial_version),
            expense_version=str(state.version),
            policy_version=policy,
            verified_at=instant,
        )
        digest = c.canonical_command_digest(command, preconditions, policy_version=policy)
        return c.ProposalRecord(
            proposal_id=uuid.uuid4(),
            owner_user_id=owner_user_id,
            session_id=session_id,
            turn_id=turn_id,
            revision=1,
            operation="expense.presentation.update",
            mode="backend",
            status=c.ProposalStatus.PENDING,
            intent=intent,
            canonical_command=command,
            preview=preview,
            preconditions=preconditions,
            command_digest=digest,
            confirmation_nonce=_new_nonce(),
            policy_version=policy,
            expires_at=instant.replace(microsecond=0) + timedelta(minutes=10),
            execution=None,
            request_receipts=[],
        )

    # --------------------------------------------------------------- delete preview

    async def build_delete_preview(
        self,
        *,
        owner_user_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        intent: c.ExpenseDeleteIntent,
        bound_references: Sequence[c.BoundReference],
        access_token: str,
        expires_at: datetime,
        agent_disable_revision: int,
        policy_version: str | None = None,
        summary_prefix: str = "",
        now: datetime | None = None,
    ) -> c.ProposalRecord:
        """Build a logical-delete proposal.

        Locked and already-deleted Expenses are rejected here; archived or
        deleted Activities are left to the RPC's actual response. Permission is
        checked against the Expense creator and the Activity creator.
        """
        if not isinstance(intent, c.ExpenseDeleteIntent):
            raise LiveWriteError("unsupported_operation")
        instant = _aware(now)
        binding = _resolve_expense_binding(intent, bound_references, turn_id)
        expense_id = binding.entity_id
        activity_id = binding.scope_activity_id
        grant = _activity_grant(
            owner_user_id=owner_user_id, turn_id=turn_id,
            access_token=access_token, expires_at=expires_at,
            activity_id=activity_id,
        )
        scope = await self._read_backend.resolve_scope(
            grant, ScopeRequest(mode="activity", ui_activity_id_hint=activity_id),
        )
        state = await self.read_expense_state(access_token, expense_id)
        if state.is_deleted:
            raise LiveWriteError("expense_deleted")
        if state.financial_locked:
            raise LiveWriteError("expense_financial_locked")
        activity_creator = await self.read_activity_creator(access_token, activity_id)
        if state.created_by != owner_user_id and activity_creator != owner_user_id:
            raise LiveWriteError("delete_not_permitted")

        before = c.ExpenseSnapshot(
            ledger_unit_id=state.ledger_unit_id,
            title=state.title,
            original_amount=state.original_amount,
            original_currency=state.original_currency,
            base_amount=state.base_amount,
            payment_allocations=state.canonical_payments(),
            split=state.canonical_split(),
            occurred_at=state.occurred_at,
            note=state.note,
            icon_key=state.icon_key or "money",
            expense_version=str(state.version),
            financial_locked=state.financial_locked,
            is_deleted=False,
        )
        after = before.model_copy(update={
            "expense_version": str(state.version + 1),
            "is_deleted": True,
        })
        changes: list[c.ExpenseFieldChange] = [
            c.ExpenseDeletedChange(field="is_deleted", before=False, after=True),
        ]
        command = c.FixedExpenseDeleteCommand(
            operation="expense.delete",
            activity_id=activity_id,
            expense_id=expense_id,
            expected_expense_version=str(state.version),
            expected_financial_version=str(scope.activity.financial_version),
            expected_is_deleted=False,
        )
        preview = c.ExpensePreview(
            kind="expense",
            summary=f"{summary_prefix}删除消费 {state.title}",
            before=before,
            after=after,
            changes=changes,
            activity_financial_version=str(scope.activity.financial_version),
            generated_at=instant,
            simulation=False,
        )
        policy = policy_version or self._config.policy_version
        preconditions = c.PreconditionSnapshot(
            activity_id=activity_id,
            permission_checked=True,
            agent_disable_revision=agent_disable_revision,
            activity_financial_version=str(scope.activity.financial_version),
            expense_version=str(state.version),
            policy_version=policy,
            verified_at=instant,
        )
        digest = c.canonical_command_digest(command, preconditions, policy_version=policy)
        return c.ProposalRecord(
            proposal_id=uuid.uuid4(),
            owner_user_id=owner_user_id,
            session_id=session_id,
            turn_id=turn_id,
            revision=1,
            operation="expense.delete",
            mode="backend",
            status=c.ProposalStatus.PENDING,
            intent=intent,
            canonical_command=command,
            preview=preview,
            preconditions=preconditions,
            command_digest=digest,
            confirmation_nonce=_new_nonce(),
            policy_version=policy,
            expires_at=instant.replace(microsecond=0) + timedelta(minutes=10),
            execution=None,
            request_receipts=[],
        )

    # ------------------------------------------------------------- repayment preview

    async def build_repayment_preview(
        self,
        *,
        owner_user_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        intent: c.RepaymentIntent,
        access_token: str,
        expires_at: datetime,
        agent_disable_revision: int,
        policy_version: str | None = None,
        summary_prefix: str = "",
        now: datetime | None = None,
    ) -> c.ProposalRecord:
        """Build a repayment proposal from the server's own preview RPC.

        The server owns allocation, debt capacity, FX and actor authorization.
        The Agent only supplies the validated request and stores the returned
        ``expected_financial_version`` unchanged for the create call.
        """
        if not isinstance(intent, c.RepaymentIntent):
            raise LiveWriteError("unsupported_operation")
        instant = _aware(now)
        grant = _activity_grant(
            owner_user_id=owner_user_id, turn_id=turn_id,
            access_token=access_token, expires_at=expires_at,
            activity_id=intent.activity_id,
        )
        scope = await self._read_backend.resolve_scope(
            grant, ScopeRequest(mode="activity", ui_activity_id_hint=intent.activity_id),
        )
        participants = {
            item.participant_id: item
            for item in scope.participants if not item.is_deleted
        }
        if (
            intent.from_participant_id not in participants
            or intent.to_participant_id not in participants
            or intent.from_participant_id == intent.to_participant_id
        ):
            raise LiveWriteError("repayment_participant_invalid")
        expected_version = scope.activity.financial_version

        status, body = await self._post_rpc(
            RPC_PREVIEW_REPAYMENT,
            access_token,
            {
                "activity_id": str(intent.activity_id),
                "from_participant_id": str(intent.from_participant_id),
                "to_participant_id": str(intent.to_participant_id),
                "amount": intent.amount,
                "currency": intent.currency,
                "mode": intent.mode,
                "target_expense_ids": [str(item) for item in intent.target_expense_ids],
                "expected_financial_version": expected_version,
            },
        )
        if status != 200:
            raise LiveWriteError(
                _repayment_error_code(status, _raw_error_code(_decode_rows(body))),
                retryable=status >= 500,
            )
        rows = _decode_read_rows(body)
        if not rows:
            raise LiveWriteError("repayment_preview_rejected")
        if any(_int(row.get("source_financial_version")) != expected_version for row in rows):
            raise LiveWriteError("repayment_version_conflict")
        try:
            allocations = [
                c.RepaymentAllocation(
                    expense_id=_uuid(row.get("expense_id")),
                    ledger_unit_id=_uuid(row.get("ledger_unit_id")),
                    allocation_mode=str(row.get("allocation_mode")),
                    payment_currency=str(row.get("payment_currency")),
                    payment_amount=_num_text(row.get("payment_amount")),
                    original_currency=str(row.get("original_currency")),
                    original_amount=_num_text(row.get("original_amount")),
                    base_amount=_num_text(row.get("base_amount")),
                    fx_rate=_num_text(row.get("fx_rate")),
                    remaining_original_amount=_num_text(row.get("remaining_original_amount")),
                    remaining_base_amount=_num_text(row.get("remaining_base_amount")),
                    source_financial_version=str(_int(row.get("source_financial_version"))),
                )
                for row in rows
            ]
            from_name = participants[intent.from_participant_id].name
            to_name = participants[intent.to_participant_id].name
            preview = c.RepaymentPreview(
                kind="repayment",
                summary=(
                    f"{summary_prefix}还款 {from_name} -> {to_name} "
                    f"{intent.amount} {intent.currency} {intent.mode}"
                ),
                activity_id=intent.activity_id,
                from_participant_id=intent.from_participant_id,
                to_participant_id=intent.to_participant_id,
                amount=intent.amount,
                currency=intent.currency,
                mode=intent.mode,
                target_expense_ids=(
                    list(intent.target_expense_ids) if intent.mode == "TARGETED" else []
                ),
                allocations=allocations,
                expected_financial_version=str(expected_version),
                generated_at=instant,
                simulation=False,
            )
        except ValueError:
            raise LiveWriteError("repayment_preview_rejected") from None

        command = c.FixedRepaymentCommand(
            operation="settlement.repayment",
            activity_id=intent.activity_id,
            from_participant_id=intent.from_participant_id,
            to_participant_id=intent.to_participant_id,
            amount=intent.amount,
            currency=intent.currency,
            mode=intent.mode,
            target_expense_ids=(
                list(intent.target_expense_ids) if intent.mode == "TARGETED" else []
            ),
            occurred_at=instant,
            expected_financial_version=str(expected_version),
        )
        policy = policy_version or self._config.policy_version
        preconditions = c.PreconditionSnapshot(
            activity_id=intent.activity_id,
            permission_checked=True,
            agent_disable_revision=agent_disable_revision,
            activity_financial_version=str(expected_version),
            expense_version=None,
            policy_version=policy,
            verified_at=instant,
        )
        digest = c.canonical_command_digest(command, preconditions, policy_version=policy)
        return c.ProposalRecord(
            proposal_id=uuid.uuid4(),
            owner_user_id=owner_user_id,
            session_id=session_id,
            turn_id=turn_id,
            revision=1,
            operation="settlement.repayment",
            mode="backend",
            status=c.ProposalStatus.PENDING,
            intent=intent,
            canonical_command=command,
            preview=preview,
            preconditions=preconditions,
            command_digest=digest,
            confirmation_nonce=_new_nonce(),
            policy_version=policy,
            expires_at=instant.replace(microsecond=0) + timedelta(minutes=10),
            execution=None,
            request_receipts=[],
        )

    # ---------------------------------------------------------- prepayment preview

    async def build_prepayment_preview(
        self,
        *,
        owner_user_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        intent: c.PrepaymentIntent,
        access_token: str,
        expires_at: datetime,
        agent_disable_revision: int,
        policy_version: str | None = None,
        summary_prefix: str = "",
        now: datetime | None = None,
    ) -> c.ProposalRecord:
        """Build a prepayment proposal from the server's own preview RPC.

        The server owns the debt cap, the settlement/balance split and the
        resulting balance. The Agent only supplies the request and keeps the
        returned ``financial_version`` and parts unchanged for the create call.
        """
        if not isinstance(intent, c.PrepaymentIntent):
            raise LiveWriteError("unsupported_operation")
        instant = _aware(now)
        grant = _activity_grant(
            owner_user_id=owner_user_id, turn_id=turn_id,
            access_token=access_token, expires_at=expires_at,
            activity_id=intent.activity_id,
        )
        scope = await self._read_backend.resolve_scope(
            grant, ScopeRequest(mode="activity", ui_activity_id_hint=intent.activity_id),
        )
        _require_large_activity(scope)
        participants = {
            item.participant_id: item
            for item in scope.participants if not item.is_deleted
        }
        if (
            intent.owner_participant_id not in participants
            or intent.custodian_participant_id not in participants
            or intent.owner_participant_id == intent.custodian_participant_id
        ):
            raise LiveWriteError("prepayment_participant_invalid")
        _require_prepayment_currency(scope, intent.currency, intent.amount)

        status, body = await self._post_rpc(
            RPC_PREVIEW_PREPAYMENT,
            access_token,
            {
                "activity_id": str(intent.activity_id),
                "owner_participant_id": str(intent.owner_participant_id),
                "custodian_participant_id": str(intent.custodian_participant_id),
                "amount": intent.amount,
                "currency": intent.currency,
            },
        )
        if status != 200:
            rows = _decode_rows(body)
            error_code = _prepayment_error_code(
                status, _raw_error_code(rows), _raw_error_message(rows),
            )
            if error_code is None:
                error_code = (
                    "upstream_read_failed" if status >= 500
                    else "prepayment_preview_rejected"
                )
            raise LiveWriteError(error_code, retryable=status >= 500)
        rows = _decode_read_rows(body)
        if len(rows) != 1:
            raise LiveWriteError("prepayment_preview_rejected")
        row = rows[0]
        if (
            str(row.get("activity_id")) != str(intent.activity_id)
            or str(row.get("owner_participant_id")) != str(intent.owner_participant_id)
            or str(row.get("custodian_participant_id")) != str(intent.custodian_participant_id)
            or str(row.get("currency")) != intent.currency
        ):
            raise LiveWriteError("prepayment_preview_rejected")
        owner_name = participants[intent.owner_participant_id].name
        custodian_name = participants[intent.custodian_participant_id].name
        try:
            preview = c.PrepaymentPreview(
                kind="prepayment",
                summary=(
                    f"{summary_prefix}预存 {owner_name} -> {custodian_name} "
                    f"{intent.amount} {intent.currency}"
                ),
                activity_id=intent.activity_id,
                owner_participant_id=intent.owner_participant_id,
                custodian_participant_id=intent.custodian_participant_id,
                amount=intent.amount,
                currency=intent.currency,
                settlement_amount=_num_text(row.get("settlement_amount")),
                prepayment_amount=_num_text(row.get("prepayment_amount")),
                new_balance=_num_text(row.get("new_balance")),
                expected_financial_version=str(_int(row.get("financial_version"))),
                generated_at=instant,
                simulation=False,
            )
            command = c.FixedPrepaymentCommand(
                operation="prepayment.create",
                activity_id=intent.activity_id,
                owner_participant_id=intent.owner_participant_id,
                custodian_participant_id=intent.custodian_participant_id,
                amount=intent.amount,
                currency=intent.currency,
                occurred_at=instant,
                expected_financial_version=preview.expected_financial_version,
                expected_settlement_amount=preview.settlement_amount,
                expected_prepayment_amount=preview.prepayment_amount,
                expected_new_balance=preview.new_balance,
            )
        except ValueError:
            raise LiveWriteError("prepayment_preview_rejected") from None

        policy = policy_version or self._config.policy_version
        preconditions = c.PreconditionSnapshot(
            activity_id=intent.activity_id,
            permission_checked=True,
            agent_disable_revision=agent_disable_revision,
            activity_financial_version=preview.expected_financial_version,
            expense_version=None,
            policy_version=policy,
            verified_at=instant,
        )
        digest = c.canonical_command_digest(command, preconditions, policy_version=policy)
        return c.ProposalRecord(
            proposal_id=uuid.uuid4(),
            owner_user_id=owner_user_id,
            session_id=session_id,
            turn_id=turn_id,
            revision=1,
            operation="prepayment.create",
            mode="backend",
            status=c.ProposalStatus.PENDING,
            intent=intent,
            canonical_command=command,
            preview=preview,
            preconditions=preconditions,
            command_digest=digest,
            confirmation_nonce=_new_nonce(),
            policy_version=policy,
            expires_at=instant.replace(microsecond=0) + timedelta(minutes=10),
            execution=None,
            request_receipts=[],
        )

    async def build_prepayment_return_preview(
        self,
        *,
        owner_user_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        intent: c.PrepaymentReturnIntent,
        access_token: str,
        expires_at: datetime,
        agent_disable_revision: int,
        policy_version: str | None = None,
        summary_prefix: str = "",
        now: datetime | None = None,
    ) -> c.ProposalRecord:
        """Build a return proposal from the account balance the server exposes.

        There is no server preview RPC for a return, so this reads the account
        (one row, one currency) and shows only the current balance. The balance
        after the return is the server's answer, never a local subtraction.
        """
        if not isinstance(intent, c.PrepaymentReturnIntent):
            raise LiveWriteError("unsupported_operation")
        instant = _aware(now)
        grant = _activity_grant(
            owner_user_id=owner_user_id, turn_id=turn_id,
            access_token=access_token, expires_at=expires_at,
            activity_id=intent.activity_id,
        )
        scope = await self._read_backend.resolve_scope(
            grant, ScopeRequest(mode="activity", ui_activity_id_hint=intent.activity_id),
        )
        _require_large_activity(scope)
        participants = {
            item.participant_id: item
            for item in scope.participants if not item.is_deleted
        }
        if (
            intent.owner_participant_id not in participants
            or intent.custodian_participant_id not in participants
            or intent.owner_participant_id == intent.custodian_participant_id
        ):
            raise LiveWriteError("prepayment_participant_invalid")
        _require_prepayment_currency(scope, intent.currency, intent.amount)
        try:
            balance = await self.read_prepayment_balance(
                access_token, intent.activity_id,
                intent.owner_participant_id, intent.custodian_participant_id,
                intent.currency,
            )
        except LiveWriteError as exc:
            raise LiveWriteError(
                "prepayment_account_unavailable", retryable=exc.retryable,
            ) from None
        expected_version = scope.activity.financial_version
        owner_name = participants[intent.owner_participant_id].name
        custodian_name = participants[intent.custodian_participant_id].name
        try:
            preview = c.PrepaymentReturnPreview(
                kind="prepayment_return",
                summary=(
                    f"{summary_prefix}返还 {custodian_name} -> {owner_name} "
                    f"{intent.amount} {intent.currency}；账户余额 {balance}；"
                    "返还后余额以服务端执行结果为准"
                ),
                activity_id=intent.activity_id,
                owner_participant_id=intent.owner_participant_id,
                custodian_participant_id=intent.custodian_participant_id,
                amount=intent.amount,
                currency=intent.currency,
                current_balance=balance,
                expected_financial_version=str(expected_version),
                generated_at=instant,
                simulation=False,
            )
            command = c.FixedPrepaymentReturnCommand(
                operation="prepayment.return",
                activity_id=intent.activity_id,
                owner_participant_id=intent.owner_participant_id,
                custodian_participant_id=intent.custodian_participant_id,
                amount=intent.amount,
                currency=intent.currency,
                occurred_at=instant,
                expected_financial_version=preview.expected_financial_version,
                expected_current_balance=preview.current_balance,
            )
        except ValueError:
            raise LiveWriteError("prepayment_preview_rejected") from None

        policy = policy_version or self._config.policy_version
        preconditions = c.PreconditionSnapshot(
            activity_id=intent.activity_id,
            permission_checked=True,
            agent_disable_revision=agent_disable_revision,
            activity_financial_version=preview.expected_financial_version,
            expense_version=None,
            policy_version=policy,
            verified_at=instant,
        )
        digest = c.canonical_command_digest(command, preconditions, policy_version=policy)
        return c.ProposalRecord(
            proposal_id=uuid.uuid4(),
            owner_user_id=owner_user_id,
            session_id=session_id,
            turn_id=turn_id,
            revision=1,
            operation="prepayment.return",
            mode="backend",
            status=c.ProposalStatus.PENDING,
            intent=intent,
            canonical_command=command,
            preview=preview,
            preconditions=preconditions,
            command_digest=digest,
            confirmation_nonce=_new_nonce(),
            policy_version=policy,
            expires_at=instant.replace(microsecond=0) + timedelta(minutes=10),
            execution=None,
            request_receipts=[],
        )

    # ----------------------------------------------------------------- void preview

    async def build_void_preview(
        self,
        *,
        owner_user_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        intent: c.VoidTransferIntent,
        access_token: str,
        expires_at: datetime,
        agent_disable_revision: int,
        policy_version: str | None = None,
        summary_prefix: str = "",
        now: datetime | None = None,
    ) -> c.ProposalRecord:
        """Build a void proposal for an existing Transfer.

        The RPC is chosen from the server-read Transfer type; an unknown type
        fails closed. Archived/deleted Activities are captured as preconditions
        and left to the RPC when unchanged.
        """
        if not isinstance(intent, c.VoidTransferIntent):
            raise LiveWriteError("unsupported_operation")
        instant = _aware(now)
        transfer = await self.read_transfer_state(access_token, intent.transfer_id)
        activity = await self.read_activity_state(access_token, transfer.activity_id)
        if transfer.is_voided:
            raise LiveWriteError("transfer_already_voided")
        if transfer.recorded_by != owner_user_id and activity.created_by != owner_user_id:
            raise LiveWriteError("void_not_permitted")
        if transfer.transfer_type not in (
            "settlement", "prepayment", "prepayment_return", "final_settlement",
        ):
            raise LiveWriteError("unsupported_transfer_type")

        preview = c.TransferVoidPreview(
            kind="transfer_void",
            summary=(
                f"{summary_prefix}作废{transfer.transfer_type} "
                f"{transfer.amount} {transfer.currency}"
            ),
            activity_id=transfer.activity_id,
            transfer_id=transfer.transfer_id,
            transfer_type=transfer.transfer_type,
            from_participant_id=transfer.from_participant_id,
            to_participant_id=transfer.to_participant_id,
            amount=transfer.amount,
            currency=transfer.currency,
            void_reason=intent.void_reason,
            is_voided=False,
            expected_financial_version=str(activity.financial_version),
            generated_at=instant,
            simulation=False,
        )
        command = c.FixedVoidTransferCommand(
            operation="transfer.void",
            activity_id=transfer.activity_id,
            transfer_id=transfer.transfer_id,
            transfer_type=transfer.transfer_type,
            expected_financial_version=str(activity.financial_version),
            expected_is_voided=False,
            expected_recorded_by=transfer.recorded_by,
            expected_activity_archived=activity.archived_at is not None,
            expected_activity_deleted=activity.is_deleted,
            void_reason=intent.void_reason,
        )
        policy = policy_version or self._config.policy_version
        preconditions = c.PreconditionSnapshot(
            activity_id=transfer.activity_id,
            permission_checked=True,
            agent_disable_revision=agent_disable_revision,
            activity_financial_version=str(activity.financial_version),
            expense_version=None,
            policy_version=policy,
            verified_at=instant,
        )
        digest = c.canonical_command_digest(command, preconditions, policy_version=policy)
        return c.ProposalRecord(
            proposal_id=uuid.uuid4(),
            owner_user_id=owner_user_id,
            session_id=session_id,
            turn_id=turn_id,
            revision=1,
            operation="transfer.void",
            mode="backend",
            status=c.ProposalStatus.PENDING,
            intent=intent,
            canonical_command=command,
            preview=preview,
            preconditions=preconditions,
            command_digest=digest,
            confirmation_nonce=_new_nonce(),
            policy_version=policy,
            expires_at=instant.replace(microsecond=0) + timedelta(minutes=10),
            execution=None,
            request_receipts=[],
        )

    # ---------------------------------------------------------------- execution

    async def execute(
        self,
        *,
        principal: Principal,
        proposal: c.ProposalRecord,
        request: c.ConfirmProposalRequest,
        expected_state_revision: int,
        access_token: str,
    ) -> LiveWriteOutcome:
        """Preflight, dispatch once, call the real RPC, settle one outcome."""
        command = proposal.canonical_command
        if not isinstance(command, (
            c.FixedExpenseCreateCommand,
            c.FixedExpenseUpdateCommand,
            c.FixedExpensePresentationCommand,
            c.FixedExpenseDeleteCommand,
            c.FixedRepaymentCommand,
            c.FixedVoidTransferCommand,
            c.FixedPrepaymentCommand,
            c.FixedPrepaymentReturnCommand,
        )):
            return await self._close(
                principal, proposal,
                code="unsupported_operation",
                summary="P5 executes expense writes, repayments, prepayments and voids only",
                expected_state_revision=expected_state_revision,
            )
        if proposal.execution is not None:
            return await self._existing_outcome(principal, proposal)
        if proposal.preconditions is None:
            return await self._close(
                principal, proposal,
                code="preview_incomplete",
                summary="preview has no precondition snapshot",
                expected_state_revision=expected_state_revision,
            )
        is_create = isinstance(command, c.FixedExpenseCreateCommand)
        is_presentation = isinstance(command, c.FixedExpensePresentationCommand)
        is_delete = isinstance(command, c.FixedExpenseDeleteCommand)
        is_repayment = isinstance(command, c.FixedRepaymentCommand)
        is_void = isinstance(command, c.FixedVoidTransferCommand)
        is_prepayment = isinstance(command, (
            c.FixedPrepaymentCommand, c.FixedPrepaymentReturnCommand,
        ))
        grant = _activity_grant(
            owner_user_id=principal.user_id, turn_id=proposal.turn_id,
            access_token=access_token, expires_at=_grant_expiry(principal),
            activity_id=command.activity_id,
        )
        try:
            if is_void:
                transfer = await self.read_transfer_state(access_token, command.transfer_id)
                activity = await self.read_activity_state(access_token, transfer.activity_id)
                if transfer.activity_id != command.activity_id:
                    raise LiveWriteError("void_state_changed")
                if transfer.transfer_type != command.transfer_type:
                    raise LiveWriteError("transfer_type_changed")
                if transfer.is_voided != command.expected_is_voided:
                    raise LiveWriteError("void_state_changed")
                if transfer.recorded_by != command.expected_recorded_by:
                    raise LiveWriteError("void_state_changed")
                if activity.financial_version != int(command.expected_financial_version):
                    raise LiveWriteError("preview_stale")
                if (activity.archived_at is not None) != command.expected_activity_archived:
                    raise LiveWriteError("void_state_changed")
                if activity.is_deleted != command.expected_activity_deleted:
                    raise LiveWriteError("void_state_changed")
                if (
                    transfer.recorded_by != principal.user_id
                    and activity.created_by != principal.user_id
                ):
                    raise LiveWriteError("void_not_permitted")
            elif is_repayment:
                # The server preview owns allocation and capacity. The Agent
                # only re-checks the Activity financial version before dispatch.
                await self._read_backend.verify_financial_versions(
                    grant, {command.activity_id: int(command.expected_financial_version)},
                )
                scope = await self._read_backend.resolve_scope(
                    grant, ScopeRequest(mode="activity", ui_activity_id_hint=command.activity_id),
                )
                if scope.activity.financial_version != int(command.expected_financial_version):
                    raise LiveWriteError("preview_stale")
            elif is_prepayment:
                # The create/return RPC own the split, the balance and the actor
                # gate. The Agent re-checks the Activity version, large-only and
                # that both participants are still active.
                await self._read_backend.verify_financial_versions(
                    grant, {command.activity_id: int(command.expected_financial_version)},
                )
                scope = await self._read_backend.resolve_scope(
                    grant, ScopeRequest(mode="activity", ui_activity_id_hint=command.activity_id),
                )
                if (
                    scope.activity is None
                    or scope.activity.financial_version != int(command.expected_financial_version)
                ):
                    raise LiveWriteError("preview_stale")
                _require_large_activity(scope)
                active = {
                    item.participant_id for item in scope.participants if not item.is_deleted
                }
                if (
                    command.owner_participant_id not in active
                    or command.custodian_participant_id not in active
                ):
                    raise LiveWriteError("prepayment_participant_invalid")
            elif is_presentation:
                # Presentation update: only the Expense's own version guards it.
                # Do NOT use activities.financial_version, and do NOT pre-reject
                # locked, deleted, archived or linked-refund rows: those are the
                # RPC's actual responses to return.
                _require_full_presentation_patch(command)
                state = await self.read_expense_state(access_token, command.expense_id)
                if state.version != int(command.expected_expense_version):
                    raise LiveWriteError("expense_version_conflict")
            elif is_delete:
                # Delete rebuilds the debt projection and advances the Activity
                # financial version, so BOTH versions are preconditions. Archived
                # or deleted Activities are still left to the RPC's response.
                await self._read_backend.verify_financial_versions(
                    grant, {command.activity_id: int(command.expected_financial_version)},
                )
                scope = await self._read_backend.resolve_scope(
                    grant, ScopeRequest(mode="activity", ui_activity_id_hint=command.activity_id),
                )
                if scope.activity.financial_version != int(command.expected_financial_version):
                    raise LiveWriteError("preview_stale")
                state = await self.read_expense_state(access_token, command.expense_id)
                if state.version != int(command.expected_expense_version):
                    raise LiveWriteError("expense_changed")
                if state.is_deleted != command.expected_is_deleted:
                    raise LiveWriteError("expense_deleted")
                if state.financial_locked:
                    raise LiveWriteError("expense_financial_locked")
                activity_creator = await self.read_activity_creator(access_token, command.activity_id)
                if (
                    state.created_by != principal.user_id
                    and activity_creator != principal.user_id
                ):
                    raise LiveWriteError("delete_not_permitted")
            else:
                if not is_create:
                    _require_full_update_patch(command)
                # Re-read the authoritative Activity version immediately before
                # dispatch. A mismatch means another financial change landed after
                # the preview was rendered.
                await self._read_backend.verify_financial_versions(
                    grant, {command.activity_id: int(command.expected_financial_version)},
                )
                scope = await self._read_backend.resolve_scope(
                    grant, ScopeRequest(mode="activity", ui_activity_id_hint=command.activity_id),
                )
                if scope.activity.financial_version != int(command.expected_financial_version):
                    raise LiveWriteError("preview_stale")
                _require_writable_activity(
                    scope,
                    original_currency=(
                        command.original_currency if is_create
                        else (command.patch.original_currency or "")
                    ),
                )
                if not is_create:
                    # The RPC cannot compare the Expense version itself, so P5.1
                    # re-reads every mutable precondition it relies on.
                    await self._validate_update_preflight(command, scope, access_token)
        except LiveWriteError as exc:
            if exc.code in ("invalid_auth_context", "auth_rejected"):
                raise LiveWriteError("invalid_auth_context", retryable=False) from exc
            if exc.code in (
                "foreign_currency_not_in_p5", "preview_stale", "expense_changed",
                "expense_deleted", "expense_financial_locked", "refund_update_not_in_p5",
                "expense_not_found",
                "invalid_command",
                "amount_allocation_mismatch",
                "expense_version_conflict",
                "invalid_icon_key",
                "no_change",
                "delete_not_permitted",
                "activity_not_found",
                "repayment_invalid",
                "repayment_participant_invalid",
                "repayment_exceeds_debt_or_target",
                "repayment_version_conflict",
                "actor_not_permitted",
                "repayment_preview_rejected",
                "request_id_conflict",
                "transfer_not_found",
                "transfer_already_voided",
                "void_not_permitted",
                "unsupported_transfer_type",
                "void_state_changed",
                "transfer_type_changed",
                "activity_changed",
                "void_not_applied",
                "voided_elsewhere",
                "prepayment_requires_large_activity",
                "prepayment_invalid",
                "prepayment_participant_invalid",
                "prepayment_currency_unsupported",
                "prepayment_amount_precision",
                "prepayment_preview_rejected",
                "prepayment_version_conflict",
                "prepayment_return_exceeds_balance",
                "prepayment_account_unavailable",
            ):
                return await self._close(
                    principal, proposal,
                    code=exc.code,
                    summary=_PREFLIGHT_CLOSE_SUMMARY.get(exc.code, "preview is no longer valid"),
                    expected_state_revision=expected_state_revision,
                )
            raise
        except BackendReadError as exc:
            if exc.code in ("data_changed_during_read", "scope_unavailable", "access_denied"):
                return await self._close(
                    principal, proposal,
                    code=exc.code,
                    summary="activity state changed before execution",
                    expected_state_revision=expected_state_revision,
                )
            if exc.code in ("invalid_auth_context", "auth_rejected"):
                raise LiveWriteError("invalid_auth_context", retryable=False) from exc
            raise LiveWriteError("preflight_unavailable", retryable=True) from exc
        except ScopeDenied:
            return await self._close(
                principal, proposal,
                code="scope_denied",
                summary="activity scope is no longer writable",
                expected_state_revision=expected_state_revision,
            )

        try:
            await _call_store(
                self._store.confirm_and_dispatch,
                principal.user_id, proposal.proposal_id, request,
                expected_state_revision=expected_state_revision,
                expected_proposal_revision=proposal.revision,
                execution_kind="live",
            )
        except (ProposalConflict, ProposalExpired):
            # Another confirmation won the race; never dispatch a second write.
            return await self._existing_outcome(principal, proposal)
        except StateConflict:
            return await self._close(
                principal, proposal,
                code="preview_stale",
                summary="turn is no longer awaiting this confirmation",
                expected_state_revision=expected_state_revision,
            )

        if is_create:
            rpc_path = RPC_CREATE_EXPENSE
            payload = _rpc_payload(command)
        elif is_presentation:
            rpc_path = RPC_UPDATE_PRESENTATION
            payload = _rpc_payload_presentation(command)
        elif is_delete:
            rpc_path = RPC_DELETE_EXPENSE
            payload = _rpc_payload_delete(command)
        elif is_repayment:
            rpc_path = RPC_CREATE_REPAYMENT
            payload = _rpc_payload_repayment(
                command,
                c.derive_execution_id(
                    principal.user_id, proposal.proposal_id, proposal.revision,
                ),
            )
        elif is_void:
            rpc_path = _void_rpc_path(command.transfer_type)
            payload = _rpc_payload_void(command)
        elif isinstance(command, c.FixedPrepaymentCommand):
            rpc_path = RPC_CREATE_PREPAYMENT
            payload = _rpc_payload_prepayment(
                command,
                c.derive_execution_id(
                    principal.user_id, proposal.proposal_id, proposal.revision,
                ),
            )
        elif isinstance(command, c.FixedPrepaymentReturnCommand):
            rpc_path = RPC_CREATE_PREPAYMENT_RETURN
            payload = _rpc_payload_prepayment(
                command,
                c.derive_execution_id(
                    principal.user_id, proposal.proposal_id, proposal.revision,
                ),
            )
        else:
            rpc_path = RPC_UPDATE_EXPENSE
            payload = _rpc_payload_update(command)
        try:
            status, body = await _call_async(
                self._transport.post_json,
                f"{self._config.project_url.rstrip('/')}{rpc_path}",
                {
                    "apikey": self._config.publishable_key,
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                payload,
                timeout=self._config.timeout_seconds,
                max_response_bytes=self._config.max_response_bytes,
            )
        except LiveWriteError as exc:
            return await self._settle_transport_failure(principal, proposal, exc)

        return await self._settle_rpc_response(
            principal, proposal, status, body, access_token=access_token,
        )

    async def _validate_update_preflight(
        self,
        command: c.FixedExpenseUpdateCommand,
        scope: Any,
        access_token: str,
    ) -> None:
        state = await self.read_expense_state(access_token, command.expense_id)
        if state.version != int(command.expected_expense_version):
            raise LiveWriteError("expense_changed")
        if state.is_deleted:
            raise LiveWriteError("expense_deleted")
        if state.financial_locked:
            raise LiveWriteError("expense_financial_locked")
        if state.original_expense_id is not None:
            raise LiveWriteError("refund_update_not_in_p5")
        if state.original_currency != scope.activity.base_currency:
            raise LiveWriteError("foreign_currency_not_in_p5")
        unit_ids = {item.ledger_unit_id for item in scope.ledger_units if not item.is_deleted}
        if command.patch.ledger_unit_id is not None and command.patch.ledger_unit_id not in unit_ids:
            raise ScopeDenied("ledger unit is outside the Activity scope")
        participant_ids = {item.participant_id for item in scope.participants if not item.is_deleted}
        for item in command.patch.payment_allocations or ():
            if item.participant_id not in participant_ids:
                raise ScopeDenied("payer is outside the Activity scope")
        if isinstance(command.patch.split, c.CanonicalEqualSplit):
            if any(item not in participant_ids for item in command.patch.split.participant_ids):
                raise ScopeDenied("split participant is outside the Activity scope")
        elif isinstance(command.patch.split, c.CanonicalManualSplit):
            if any(item.participant_id not in participant_ids for item in command.patch.split.allocations):
                raise ScopeDenied("split participant is outside the Activity scope")

    # ------------------------------------------------------------------ helpers

    async def reconcile(
        self,
        principal: Principal,
        proposal: c.ProposalRecord,
        access_token: str,
    ) -> LiveWriteOutcome:
        """Read-only reconciliation for a delete whose response was lost.

        Without a server-side request id, a deleted row cannot be attributed to
        this execution. Every clear observation therefore closes the proposal;
        none of them is reported as success.
        """
        command = proposal.canonical_command
        if isinstance(command, c.FixedVoidTransferCommand):
            return await self._reconcile_void(
                principal, proposal, command, access_token,
            )
        if isinstance(command, c.FixedRepaymentCommand):
            return await self._reconcile_repayment(
                principal, proposal, command, access_token,
            )
        if isinstance(command, (c.FixedPrepaymentCommand, c.FixedPrepaymentReturnCommand)):
            return await self._reconcile_prepayment(
                principal, proposal, command, access_token,
            )
        if not isinstance(command, c.FixedExpenseDeleteCommand):
            return await self._existing_outcome(principal, proposal)
        turn = (
            await _call_store(self._store.get_turn, principal.user_id, proposal.turn_id)
        ).record.turn
        if turn.state not in (c.TurnState.RECOVERING, c.TurnState.EXECUTING):
            return await self._existing_outcome(principal, proposal)
        try:
            state = await self.read_expense_state(access_token, command.expense_id)
        except (LiveWriteError, BackendReadError):
            # No clear evidence yet; leave the Turn RECOVERING/UNKNOWN.
            return await self._existing_outcome(principal, proposal)
        if state.is_deleted:
            code = "deleted_elsewhere"
            summary = "the Expense is deleted but this execution cannot be proven to be the author"
        elif state.version == int(command.expected_expense_version):
            code = "delete_not_applied"
            summary = "the Expense is not deleted and its version is unchanged"
        else:
            code = "expense_changed"
            summary = "the Expense changed while the delete outcome was unresolved"
        await _call_store(
            self._store.settle_mock_execution,
            principal.user_id, proposal.proposal_id,
            c.ExecutionResolution.CLOSED,
            result_code=code,
            result_summary=summary,
        )
        return LiveWriteOutcome(c.ExecutionResolution.CLOSED, code, summary)

    async def _reconcile_repayment(
        self,
        principal: Principal,
        proposal: c.ProposalRecord,
        command: c.FixedRepaymentCommand,
        access_token: str,
    ) -> LiveWriteOutcome:
        turn = (
            await _call_store(self._store.get_turn, principal.user_id, proposal.turn_id)
        ).record.turn
        if turn.state not in (c.TurnState.RECOVERING, c.TurnState.EXECUTING):
            return await self._existing_outcome(principal, proposal)
        request_id = c.derive_execution_id(
            principal.user_id, proposal.proposal_id, proposal.revision,
        )
        try:
            row = await self.read_transfer_by_request_id(
                access_token, command.activity_id, request_id,
            )
        except (LiveWriteError, BackendReadError):
            return await self._existing_outcome(principal, proposal)
        if row is None:
            # Absence is not proof that the write did not land (read lag,
            # RLS, or an unreachable read). Stay UNKNOWN.
            return await self._existing_outcome(principal, proposal)
        if not _repayment_payload_matches(row.get("request_payload"), command):
            await _call_store(
                self._store.settle_mock_execution,
                principal.user_id, proposal.proposal_id,
                c.ExecutionResolution.CLOSED,
                result_code="request_id_conflict",
                result_summary="the request id exists with a different payload",
            )
            return LiveWriteOutcome(
                c.ExecutionResolution.CLOSED, "request_id_conflict",
                "request id conflict",
            )
        result = row.get("request_result")
        if not isinstance(result, dict):
            return await self._existing_outcome(principal, proposal)
        transfer_id = result.get("transfer_id")
        financial_version = result.get("financial_version")
        if not isinstance(transfer_id, str) or not isinstance(financial_version, int):
            return await self._existing_outcome(principal, proposal)
        await _call_store(
            self._store.settle_mock_execution,
            principal.user_id, proposal.proposal_id,
            c.ExecutionResolution.SUCCEEDED,
            result_code="repayment_created",
            result_summary=(
                f"transfer_id={transfer_id};financial_version={financial_version}"
            ),
        )
        return LiveWriteOutcome(
            c.ExecutionResolution.SUCCEEDED, "repayment_created",
            "repayment reconciled by request id",
        )

    async def _reconcile_prepayment(
        self,
        principal: Principal,
        proposal: c.ProposalRecord,
        command: c.FixedPrepaymentCommand | c.FixedPrepaymentReturnCommand,
        access_token: str,
    ) -> LiveWriteOutcome:
        turn = (
            await _call_store(self._store.get_turn, principal.user_id, proposal.turn_id)
        ).record.turn
        if turn.state not in (c.TurnState.RECOVERING, c.TurnState.EXECUTING):
            return await self._existing_outcome(principal, proposal)
        request_id = c.derive_execution_id(
            principal.user_id, proposal.proposal_id, proposal.revision,
        )
        try:
            row = await self.read_transfer_by_request_id(
                access_token, command.activity_id, request_id,
            )
        except (LiveWriteError, BackendReadError):
            return await self._existing_outcome(principal, proposal)
        if row is None:
            # Absence is not proof the write did not land; stay UNKNOWN.
            return await self._existing_outcome(principal, proposal)
        is_return = isinstance(command, c.FixedPrepaymentReturnCommand)
        operation = "create_prepayment_return" if is_return else "create_prepayment"
        expected_type = "prepayment_return" if is_return else "prepayment"
        if (
            str(row.get("type")) != expected_type
            or not _prepayment_payload_matches(
                row.get("request_payload"), command, operation,
            )
        ):
            await _call_store(
                self._store.settle_mock_execution,
                principal.user_id, proposal.proposal_id,
                c.ExecutionResolution.CLOSED,
                result_code="request_id_conflict",
                result_summary="the request id exists with a different payload",
            )
            return LiveWriteOutcome(
                c.ExecutionResolution.CLOSED, "request_id_conflict",
                "request id conflict",
            )
        result = row.get("request_result")
        if not isinstance(result, dict):
            return await self._existing_outcome(principal, proposal)
        if is_return:
            required = ("transfer_id", "amount", "remaining_balance", "financial_version")
            code = "prepayment_return_created"
        else:
            required = (
                "transfer_id", "settlement_amount", "prepayment_amount",
                "new_balance", "financial_version",
            )
            code = "prepayment_created"
        if (
            not isinstance(result.get("transfer_id"), str)
            or not isinstance(result.get("financial_version"), int)
            or any(key not in result for key in required)
        ):
            return await self._existing_outcome(principal, proposal)
        await _call_store(
            self._store.settle_mock_execution,
            principal.user_id, proposal.proposal_id,
            c.ExecutionResolution.SUCCEEDED,
            result_code=code,
            result_summary=_prepayment_result_summary(result),
        )
        return LiveWriteOutcome(
            c.ExecutionResolution.SUCCEEDED, code,
            "prepayment reconciled by request id" if not is_return
            else "prepayment return reconciled by request id",
        )

    async def _reconcile_void(
        self,
        principal: Principal,
        proposal: c.ProposalRecord,
        command: c.FixedVoidTransferCommand,
        access_token: str,
    ) -> LiveWriteOutcome:
        turn = (
            await _call_store(self._store.get_turn, principal.user_id, proposal.turn_id)
        ).record.turn
        if turn.state not in (c.TurnState.RECOVERING, c.TurnState.EXECUTING):
            return await self._existing_outcome(principal, proposal)
        try:
            transfer = await self.read_transfer_state(access_token, command.transfer_id)
            activity = await self.read_activity_state(access_token, transfer.activity_id)
        except (LiveWriteError, BackendReadError):
            return await self._existing_outcome(principal, proposal)
        if transfer.is_voided:
            code = "voided_elsewhere"
            summary = "the Transfer is voided but this execution cannot be proven to be the author"
        elif activity.financial_version == int(command.expected_financial_version):
            code = "void_not_applied"
            summary = "the Transfer is not voided and the Activity version is unchanged"
        else:
            code = "activity_changed"
            summary = "the Activity changed while the void outcome was unresolved"
        await _call_store(
            self._store.settle_mock_execution,
            principal.user_id, proposal.proposal_id,
            c.ExecutionResolution.CLOSED,
            result_code=code,
            result_summary=summary,
        )
        return LiveWriteOutcome(c.ExecutionResolution.CLOSED, code, summary)

    async def _existing_outcome(self, principal: Principal, proposal: c.ProposalRecord) -> LiveWriteOutcome:
        turn = (
            await _call_store(self._store.get_turn, principal.user_id, proposal.turn_id)
        ).record.turn
        if turn.state is c.TurnState.COMPLETED and turn.execution_resolution is c.ExecutionResolution.SUCCEEDED:
            return LiveWriteOutcome(c.ExecutionResolution.SUCCEEDED, "already_succeeded", "execution already succeeded")
        if turn.state is c.TurnState.FAILED and turn.execution_resolution is c.ExecutionResolution.REJECTED:
            return LiveWriteOutcome(c.ExecutionResolution.REJECTED, "already_rejected", "execution was rejected")
        if turn.execution_resolution is c.ExecutionResolution.CLOSED:
            return LiveWriteOutcome(c.ExecutionResolution.CLOSED, "already_closed", "execution was closed")
        # EXECUTING or RECOVERING: the original attempt may have landed. Never
        # send it again; report it as unknown and let the caller show reconciliation.
        return LiveWriteOutcome(c.ExecutionResolution.UNKNOWN, "execution_unresolved", "execution is still unresolved")

    async def _close(
        self,
        principal: Principal,
        proposal: c.ProposalRecord,
        *,
        code: str,
        summary: str,
        expected_state_revision: int,
    ) -> LiveWriteOutcome:
        try:
            await _call_store(
                self._store.close_pending_proposal,
                principal.user_id, proposal.proposal_id,
                reason=code,
                expected_state_revision=expected_state_revision,
                expected_proposal_revision=proposal.revision,
            )
        except (ProposalConflict, StateConflict):
            # A concurrent confirmation changed the row. Report the current state
            # rather than pretending the close succeeded.
            return await self._existing_outcome(principal, proposal)
        return LiveWriteOutcome(c.ExecutionResolution.CLOSED, code, summary)

    async def _settle_transport_failure(
        self, principal: Principal, proposal: c.ProposalRecord, exc: LiveWriteError,
    ) -> LiveWriteOutcome:
        if exc.ambiguous:
            await _call_store(
                self._store.mark_execution_unknown,
                principal.user_id, proposal.proposal_id,
            )
            return LiveWriteOutcome(c.ExecutionResolution.UNKNOWN, exc.code, "write outcome is unresolved")
        await _call_store(
            self._store.settle_mock_execution,
            principal.user_id, proposal.proposal_id,
            c.ExecutionResolution.REJECTED,
            result_code=exc.code,
            result_summary="write was not accepted",
        )
        return LiveWriteOutcome(c.ExecutionResolution.REJECTED, exc.code, "write was not accepted")

    async def _settle_rpc_response(
        self, principal: Principal, proposal: c.ProposalRecord, status: int, body: bytes,
        *, access_token: str,
    ) -> LiveWriteOutcome:
        parsed = _decode_rows(body)
        if 200 <= status < 300:
            row = parsed[0] if parsed else None
            if proposal.operation == "transfer.void":
                transfer_id = row.get("transfer_id") if isinstance(row, dict) else None
                voided = row.get("voided") if isinstance(row, dict) else None
                financial_version = row.get("financial_version") if isinstance(row, dict) else None
                if (
                    not isinstance(transfer_id, str)
                    or not isinstance(voided, bool)
                    or not isinstance(financial_version, int)
                ):
                    await _call_store(
                        self._store.mark_execution_unknown,
                        principal.user_id, proposal.proposal_id,
                    )
                    return LiveWriteOutcome(
                        c.ExecutionResolution.UNKNOWN, "upstream_invalid_success",
                        "write outcome is unresolved",
                    )
                code = "transfer_voided" if voided else "transfer_already_voided"
                await _call_store(
                    self._store.settle_mock_execution,
                    principal.user_id, proposal.proposal_id,
                    c.ExecutionResolution.SUCCEEDED,
                    result_code=code,
                    result_summary=(
                        f"transfer_id={transfer_id};financial_version={financial_version};"
                        f"changed={str(voided).lower()}"
                    ),
                )
                return LiveWriteOutcome(
                    c.ExecutionResolution.SUCCEEDED, code,
                    "transfer voided" if voided else "transfer was already voided",
                )
            if proposal.operation == "settlement.repayment":
                transfer_id = row.get("transfer_id") if isinstance(row, dict) else None
                financial_version = row.get("financial_version") if isinstance(row, dict) else None
                if not isinstance(transfer_id, str) or not isinstance(financial_version, int):
                    await _call_store(
                        self._store.mark_execution_unknown,
                        principal.user_id, proposal.proposal_id,
                    )
                    return LiveWriteOutcome(
                        c.ExecutionResolution.UNKNOWN, "upstream_invalid_success",
                        "write outcome is unresolved",
                    )
                await _call_store(
                    self._store.settle_mock_execution,
                    principal.user_id, proposal.proposal_id,
                    c.ExecutionResolution.SUCCEEDED,
                    result_code="repayment_created",
                    result_summary=(
                        f"transfer_id={transfer_id};financial_version={financial_version}"
                    ),
                )
                return LiveWriteOutcome(
                    c.ExecutionResolution.SUCCEEDED, "repayment_created",
                    "repayment created",
                )
            if proposal.operation in ("prepayment.create", "prepayment.return"):
                is_return = proposal.operation == "prepayment.return"
                required = (
                    ("transfer_id", "amount", "remaining_balance", "financial_version")
                    if is_return else
                    (
                        "transfer_id", "settlement_amount", "prepayment_amount",
                        "new_balance", "financial_version",
                    )
                )
                if (
                    not isinstance(row, dict)
                    or not isinstance(row.get("transfer_id"), str)
                    or not isinstance(row.get("financial_version"), int)
                    or any(key not in row for key in required)
                ):
                    await _call_store(
                        self._store.mark_execution_unknown,
                        principal.user_id, proposal.proposal_id,
                    )
                    return LiveWriteOutcome(
                        c.ExecutionResolution.UNKNOWN, "upstream_invalid_success",
                        "write outcome is unresolved",
                    )
                code = (
                    "prepayment_return_created" if is_return
                    else "prepayment_created"
                )
                await _call_store(
                    self._store.settle_mock_execution,
                    principal.user_id, proposal.proposal_id,
                    c.ExecutionResolution.SUCCEEDED,
                    result_code=code,
                    result_summary=_prepayment_result_summary(row),
                )
                return LiveWriteOutcome(
                    c.ExecutionResolution.SUCCEEDED, code,
                    "prepayment return created" if is_return else "prepayment created",
                )
            if proposal.operation == "expense.delete":
                deleted_expense_id = row.get("deleted_expense_id") if isinstance(row, dict) else None
                deleted = row.get("deleted") if isinstance(row, dict) else None
                version = row.get("version") if isinstance(row, dict) else None
                if (
                    not isinstance(deleted_expense_id, str)
                    or not isinstance(deleted, bool)
                    or not isinstance(version, int)
                ):
                    await _call_store(
                        self._store.mark_execution_unknown,
                        principal.user_id, proposal.proposal_id,
                    )
                    return LiveWriteOutcome(
                        c.ExecutionResolution.UNKNOWN, "upstream_invalid_success",
                        "write outcome is unresolved",
                    )
                code = "expense_deleted" if deleted else "expense_already_deleted"
                await _call_store(
                    self._store.settle_mock_execution,
                    principal.user_id, proposal.proposal_id,
                    c.ExecutionResolution.SUCCEEDED,
                    result_code=code,
                    result_summary=(
                        f"expense_id={deleted_expense_id};version={version};"
                        f"changed={str(deleted).lower()}"
                    ),
                )
                return LiveWriteOutcome(
                    c.ExecutionResolution.SUCCEEDED, code,
                    "expense deleted" if deleted else "expense was already deleted",
                )
            expense_id = (
                (row.get("expense_id") or row.get("updated_expense_id"))
                if isinstance(row, dict) else None
            )
            version = row.get("version") if isinstance(row, dict) else None
            if not isinstance(expense_id, str) or not isinstance(version, int):
                # A 2xx without the expected row is NOT proof of success.
                await _call_store(self._store.mark_execution_unknown, principal.user_id, proposal.proposal_id)
                return LiveWriteOutcome(c.ExecutionResolution.UNKNOWN, "upstream_invalid_success", "write outcome is unresolved")
            if proposal.operation == "expense.presentation.update":
                code = "expense_presentation_updated"
                summary_text = "expense presentation updated"
            elif proposal.operation == "expense.update":
                code = "expense_updated"
                summary_text = "expense updated"
            else:
                code = "expense_created"
                summary_text = "expense created"
            await _call_store(
                self._store.settle_mock_execution,
                principal.user_id, proposal.proposal_id,
                c.ExecutionResolution.SUCCEEDED,
                result_code=code,
                result_summary=f"expense_id={expense_id};version={version}",
            )
            return LiveWriteOutcome(c.ExecutionResolution.SUCCEEDED, code, summary_text)

        raw_code = _raw_error_code(parsed)
        if (
            proposal.operation == "transfer.void"
            and raw_code == "55000"
            and isinstance(proposal.canonical_command, c.FixedVoidTransferCommand)
        ):
            # The server raises 55000 both for "already voided" and for an
            # archived activity. A read decides which one it was.
            try:
                state = await self.read_transfer_state(
                    access_token, proposal.canonical_command.transfer_id,
                )
            except (LiveWriteError, BackendReadError):
                state = None
            if state is not None and state.is_voided:
                await _call_store(
                    self._store.settle_mock_execution,
                    principal.user_id, proposal.proposal_id,
                    c.ExecutionResolution.SUCCEEDED,
                    result_code="transfer_already_voided",
                    result_summary="the Transfer was already voided",
                )
                return LiveWriteOutcome(
                    c.ExecutionResolution.SUCCEEDED, "transfer_already_voided",
                    "transfer was already voided",
                )
        if (
            proposal.operation == "settlement.repayment"
            and raw_code == "40001"
        ):
            await _call_store(
                self._store.settle_mock_execution,
                principal.user_id, proposal.proposal_id,
                c.ExecutionResolution.CLOSED,
                result_code="repayment_version_conflict",
                result_summary="the Activity financial version changed before the RPC",
            )
            return LiveWriteOutcome(
                c.ExecutionResolution.CLOSED, "repayment_version_conflict",
                "repayment version conflict",
            )
        if (
            proposal.operation in ("prepayment.create", "prepayment.return")
            and raw_code == "40001"
        ):
            await _call_store(
                self._store.settle_mock_execution,
                principal.user_id, proposal.proposal_id,
                c.ExecutionResolution.CLOSED,
                result_code="prepayment_version_conflict",
                result_summary="the Activity financial version changed before the RPC",
            )
            return LiveWriteOutcome(
                c.ExecutionResolution.CLOSED, "prepayment_version_conflict",
                "prepayment version conflict",
            )
        if proposal.operation in ("prepayment.create", "prepayment.return"):
            message = _raw_error_message(parsed) or ""
            if raw_code == "55000" and "idempotent result" in message:
                # The server matched our request id but cannot replay its
                # result. That is unresolved, never a rejection and never a win.
                await _call_store(
                    self._store.mark_execution_unknown,
                    principal.user_id, proposal.proposal_id,
                )
                return LiveWriteOutcome(
                    c.ExecutionResolution.UNKNOWN, "upstream_ambiguous",
                    "write outcome is unresolved",
                )
            prepayment_code = _prepayment_error_code(status, raw_code, message)
            if prepayment_code is not None:
                await _call_store(
                    self._store.settle_mock_execution,
                    principal.user_id, proposal.proposal_id,
                    c.ExecutionResolution.REJECTED,
                    result_code=prepayment_code,
                    result_summary="server rejected the prepayment",
                )
                return LiveWriteOutcome(
                    c.ExecutionResolution.REJECTED, prepayment_code,
                    "server rejected the prepayment",
                )
        if (
            proposal.operation == "expense.presentation.update"
            and raw_code == "40001"
        ):
            # The RPC's explicit version guard fired after dispatch. Close the
            # dispatched execution; this is not a success.
            await _call_store(
                self._store.settle_mock_execution,
                principal.user_id, proposal.proposal_id,
                c.ExecutionResolution.CLOSED,
                result_code="expense_version_conflict",
                result_summary="expense version changed before the RPC",
            )
            return LiveWriteOutcome(
                c.ExecutionResolution.CLOSED, "expense_version_conflict",
                "expense version conflict",
            )

        code = _business_error_code(status, parsed)
        if status >= 500 and code is None:
            await _call_store(self._store.mark_execution_unknown, principal.user_id, proposal.proposal_id)
            return LiveWriteOutcome(c.ExecutionResolution.UNKNOWN, "upstream_ambiguous", "write outcome is unresolved")
        await _call_store(
            self._store.settle_mock_execution,
            principal.user_id, proposal.proposal_id,
            c.ExecutionResolution.REJECTED,
            result_code=code or "rpc_rejected",
            result_summary="server rejected the write",
        )
        return LiveWriteOutcome(c.ExecutionResolution.REJECTED, code or "rpc_rejected", "server rejected the write")


def _presentation_changes(
    before: c.ExpenseSnapshot, after: c.ExpenseSnapshot,
) -> list[c.ExpenseFieldChange]:
    changes: list[c.ExpenseFieldChange] = []
    if before.title != after.title:
        changes.append(c.ExpenseTitleChange(field="title", before=before.title, after=after.title))
    if before.note != after.note:
        changes.append(c.ExpenseNoteChange(field="note", before=before.note, after=after.note))
    if before.icon_key != after.icon_key:
        changes.append(c.ExpenseIconChange(
            field="icon_key", before=before.icon_key, after=after.icon_key,
        ))
    return changes


def _require_full_presentation_patch(command: c.FixedExpensePresentationCommand) -> None:
    if command.patch.title is None or command.patch.icon_key is None:
        raise LiveWriteError("invalid_command")


def _rpc_payload_presentation(command: c.FixedExpensePresentationCommand) -> dict[str, Any]:
    _require_full_presentation_patch(command)
    patch = command.patch
    return {
        "expense_id": str(command.expense_id),
        "title": patch.title,
        "note": patch.note,
        "icon_key": patch.icon_key,
        "expected_version": int(command.expected_expense_version),
    }


def _rpc_payload_delete(command: c.FixedExpenseDeleteCommand) -> dict[str, Any]:
    return {"expense_id": str(command.expense_id)}


def _rpc_payload_repayment(
    command: c.FixedRepaymentCommand, request_id: uuid.UUID,
) -> dict[str, Any]:
    return {
        "activity_id": str(command.activity_id),
        "from_participant_id": str(command.from_participant_id),
        "to_participant_id": str(command.to_participant_id),
        "amount": command.amount,
        "currency": command.currency,
        "mode": command.mode,
        "target_expense_ids": (
            [str(item) for item in command.target_expense_ids]
            if command.mode == "TARGETED" else []
        ),
        "occurred_at": command.occurred_at.isoformat(),
        "on_behalf_of_participant_id": None,
        "expected_financial_version": int(command.expected_financial_version),
        "request_id": str(request_id),
    }


def _rpc_payload_prepayment(
    command: Any, request_id: uuid.UUID,
) -> dict[str, Any]:
    """The create and return RPCs share these argument names."""
    return {
        "activity_id": str(command.activity_id),
        "owner_participant_id": str(command.owner_participant_id),
        "custodian_participant_id": str(command.custodian_participant_id),
        "amount": command.amount,
        "currency": command.currency,
        "occurred_at": command.occurred_at.isoformat(),
        "on_behalf_of_participant_id": None,
        "expected_financial_version": int(command.expected_financial_version),
        "request_id": str(request_id),
    }


def _repayment_payload_matches(
    stored: Any, command: c.FixedRepaymentCommand,
) -> bool:
    if not isinstance(stored, dict):
        return False
    try:
        return (
            str(stored.get("activity_id")) == str(command.activity_id)
            and str(stored.get("from_participant_id")) == str(command.from_participant_id)
            and str(stored.get("to_participant_id")) == str(command.to_participant_id)
            and Decimal(str(stored.get("amount"))) == Decimal(command.amount)
            and str(stored.get("currency")) == command.currency
            and str(stored.get("mode")) == command.mode
            and [str(item) for item in stored.get("target_expense_ids") or []] == [
                str(item) for item in command.target_expense_ids
            ]
            and stored.get("on_behalf_of_participant_id") in (None, "null")
            and int(stored.get("expected_financial_version"))
            == int(command.expected_financial_version)
        )
    except (TypeError, ValueError):
        return False


def _repayment_error_code(status: int, raw_code: str | None) -> str:
    return {
        "22023": "repayment_invalid",
        "23514": "repayment_exceeds_debt_or_target",
        "23505": "request_id_conflict",
        "42501": "actor_not_permitted",
        "P0002": "repayment_participant_invalid",
        "40001": "repayment_version_conflict",
        "55000": "repayment_preview_rejected",
    }.get(raw_code or "", "upstream_read_failed" if status >= 500 else "repayment_preview_rejected")


def _raw_error_code(rows: list[Any]) -> str | None:
    if not rows or not isinstance(rows[0], dict):
        return None
    code = rows[0].get("code")
    return code if isinstance(code, str) else None


def _raw_error_message(rows: list[Any]) -> str | None:
    if not rows or not isinstance(rows[0], dict):
        return None
    message = rows[0].get("message")
    return message if isinstance(message, str) else None


def _require_large_activity(scope: Any) -> None:
    """Prepayment is a large-activity feature; ordinary activities are refused."""
    activity = getattr(scope, "activity", None)
    if activity is None or activity.activity_type != "large":
        raise LiveWriteError("prepayment_requires_large_activity")


def _require_prepayment_currency(scope: Any, currency: str, amount: str) -> None:
    activity = getattr(scope, "activity", None)
    if activity is None:
        raise LiveWriteError("prepayment_requires_large_activity")
    if currency != activity.base_currency and not activity.multi_currency_enabled:
        raise LiveWriteError("prepayment_currency_unsupported")
    if (
        currency == activity.base_currency
        and Decimal(amount) != Decimal(amount).quantize(Decimal("0.1"))
    ):
        raise LiveWriteError("prepayment_amount_precision")


def _prepayment_error_code(
    status: int, raw_code: str | None, message: str | None,
) -> str | None:
    """Map a prepayment RPC failure, or None when the code is unrecognised."""
    if raw_code is None:
        return None
    if raw_code == "23514":
        text = message or ""
        if "exceeds available balance" in text:
            return "prepayment_return_exceeds_balance"
        if "普通活动" in text or "large activity" in text:
            return "prepayment_requires_large_activity"
        return "prepayment_preview_rejected"
    return {
        "22023": "prepayment_invalid",
        "23505": "request_id_conflict",
        "42501": "actor_not_permitted",
        "P0002": "prepayment_participant_invalid",
        "40001": "prepayment_version_conflict",
        "55000": "activity_read_only",
        "28000": "invalid_auth_context",
    }.get(raw_code)


def _prepayment_payload_matches(
    stored: Any, command: Any, operation: str,
) -> bool:
    if not isinstance(stored, dict):
        return False
    if str(stored.get("operation")) != operation:
        return False
    try:
        return (
            str(stored.get("activity_id")) == str(command.activity_id)
            and str(stored.get("owner_participant_id")) == str(command.owner_participant_id)
            and str(stored.get("custodian_participant_id")) == str(command.custodian_participant_id)
            and Decimal(str(stored.get("amount"))) == Decimal(command.amount)
            and str(stored.get("currency")) == command.currency
            and stored.get("on_behalf_of_participant_id") in (None, "null")
            and int(stored.get("expected_financial_version"))
            == int(command.expected_financial_version)
        )
    except (TypeError, ValueError):
        return False


def _prepayment_result_summary(result: Mapping[str, Any]) -> str:
    parts = [f"transfer_id={result.get('transfer_id')}"]
    for key in (
        "settlement_amount", "prepayment_amount", "new_balance",
        "amount", "remaining_balance",
    ):
        if key in result:
            parts.append(f"{key}={result[key]}")
    parts.append(f"financial_version={result.get('financial_version')}")
    return ";".join(parts)


def _transfer_state(row: dict[str, Any]) -> LiveTransferState:
    return LiveTransferState(
        transfer_id=_uuid(row.get("id")),
        activity_id=_uuid(row.get("activity_id")),
        transfer_type=str(row.get("type")),
        from_participant_id=_uuid(row.get("from_participant_id")),
        to_participant_id=_uuid(row.get("to_participant_id")),
        amount=_num_text(row.get("amount")),
        currency=str(row.get("currency")),
        recorded_by=_uuid(row.get("recorded_by")),
        is_voided=_bool(row.get("is_voided")),
        voided_at=_parse_timestamp(row.get("voided_at")),
        voided_by=_uuid_or_none(row.get("voided_by")),
        void_reason=row.get("void_reason") if isinstance(row.get("void_reason"), str) else None,
    )


def _void_rpc_path(transfer_type: str) -> str:
    if transfer_type == "settlement":
        return RPC_VOID_SETTLEMENT
    if transfer_type in ("prepayment", "prepayment_return", "final_settlement"):
        return RPC_VOID_PREPAYMENT
    raise LiveWriteError("unsupported_transfer_type")


def _rpc_payload_void(command: c.FixedVoidTransferCommand) -> dict[str, Any]:
    return {"transfer_id": str(command.transfer_id), "void_reason": command.void_reason}


def _resolve_expense_binding(
    intent: Any,
    references: Sequence[c.BoundReference],
    turn_id: uuid.UUID,
) -> c.BoundExpenseReference:
    for reference in references:
        if (
            isinstance(reference, c.BoundExpenseReference)
            and reference.source_turn_id == turn_id
            and reference.ref == intent.expense_ref
        ):
            return reference
    raise ScopeDenied("expense reference is not bound to this turn")


def _base_amount_text(amount: str) -> str:
    """Match `round(original_amount, 1)` for a base-currency Expense."""
    return format(
        Decimal(amount).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP), "f",
    )


def _update_changes(
    before: c.ExpenseSnapshot, after: c.ExpenseSnapshot,
) -> list[c.ExpenseFieldChange]:
    changes: list[c.ExpenseFieldChange] = []
    if before.title != after.title:
        changes.append(c.ExpenseTitleChange(field="title", before=before.title, after=after.title))
    if before.original_amount != after.original_amount:
        changes.append(c.ExpenseAmountChange(
            field="original_amount", before=before.original_amount, after=after.original_amount,
        ))
    if before.base_amount != after.base_amount:
        changes.append(c.ExpenseAmountChange(
            field="base_amount", before=before.base_amount, after=after.base_amount,
        ))
    if before.original_currency != after.original_currency:
        changes.append(c.ExpenseCurrencyChange(
            field="original_currency", before=before.original_currency, after=after.original_currency,
        ))
    if before.ledger_unit_id != after.ledger_unit_id:
        changes.append(c.ExpenseLedgerUnitChange(
            field="ledger_unit_id", before=before.ledger_unit_id, after=after.ledger_unit_id,
        ))
    if before.payment_allocations != after.payment_allocations:
        changes.append(c.ExpensePaymentsChange(
            field="payment_allocations", before=before.payment_allocations, after=after.payment_allocations,
        ))
    if before.split != after.split:
        changes.append(c.ExpenseSplitChange(field="split", before=before.split, after=after.split))
    if before.occurred_at != after.occurred_at:
        changes.append(c.ExpenseOccurredAtChange(
            field="occurred_at", before=before.occurred_at, after=after.occurred_at,
        ))
    if before.note != after.note:
        changes.append(c.ExpenseNoteChange(field="note", before=before.note, after=after.note))
    if before.icon_key != after.icon_key:
        changes.append(c.ExpenseIconChange(
            field="icon_key", before=before.icon_key, after=after.icon_key,
        ))
    return changes


def _require_full_update_patch(command: c.FixedExpenseUpdateCommand) -> None:
    patch = command.patch
    if any(
        value is None for value in (
            patch.title, patch.original_amount, patch.original_currency,
            patch.ledger_unit_id, patch.payment_allocations, patch.split, patch.occurred_at,
        )
    ):
        raise LiveWriteError("invalid_command")


def _rpc_payload_update(command: c.FixedExpenseUpdateCommand) -> dict[str, Any]:
    _require_full_update_patch(command)
    patch = command.patch
    payments = [
        {"participant_id": str(item.participant_id), "amount": item.amount}
        for item in patch.payment_allocations or ()
    ]
    if isinstance(patch.split, c.CanonicalEqualSplit):
        split_method = "equal"
        manual_splits: list[dict[str, Any]] = []
        aa_participant_ids = [str(item) for item in patch.split.participant_ids]
    elif isinstance(patch.split, c.CanonicalManualSplit):
        split_method = "manual"
        manual_splits = [
            {"participant_id": str(item.participant_id), "amount": item.amount}
            for item in patch.split.allocations
        ]
        aa_participant_ids = []
    else:  # pragma: no cover - the discriminated union makes this unreachable
        raise LiveWriteError("unsupported_split")
    return {
        "expense_id": str(command.expense_id),
        "ledger_unit_id": str(patch.ledger_unit_id),
        "title": patch.title,
        "original_amount": patch.original_amount,
        "original_currency": patch.original_currency,
        "split_method": split_method,
        "payments": payments,
        "manual_splits": manual_splits,
        "aa_participant_ids": aa_participant_ids,
        "occurred_at": patch.occurred_at.isoformat() if patch.occurred_at is not None else None,
        "note": patch.note,
        # P5.1 rejects linked refunds before dispatch, so the source link is null.
        "original_expense_id": None,
    }


def _decode_read_rows(body: bytes) -> list[dict[str, Any]]:
    if not body:
        return []
    try:
        parsed = json.loads(body.decode("utf-8"), parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveWriteError("upstream_invalid_response") from exc
    if not isinstance(parsed, list) or any(not isinstance(item, dict) for item in parsed):
        raise LiveWriteError("upstream_invalid_response")
    return parsed


def _uuid(value: Any) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise LiveWriteError("upstream_invalid_response") from exc


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    return None if value is None else _uuid(value)


def _num_text(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        return value
    raise LiveWriteError("upstream_invalid_response")


def _int(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise LiveWriteError("upstream_invalid_response")


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    raise LiveWriteError("upstream_invalid_response")


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise LiveWriteError("upstream_invalid_response")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LiveWriteError("upstream_invalid_response") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _resolve_update_bindings(
    intent: c.ExpenseUpdateIntent,
    references: Sequence[c.BoundReference],
    turn_id: uuid.UUID,
    activity_id: uuid.UUID,
) -> tuple[list[c.CanonicalPayment] | None, c.CanonicalSplit | None]:
    participants: dict[str, c.BoundParticipantReference] = {}
    for reference in references:
        if (
            isinstance(reference, c.BoundParticipantReference)
            and reference.source_turn_id == turn_id
            and reference.scope_activity_id == activity_id
        ):
            participants[reference.ref.value] = reference

    def resolve(ref: Any) -> uuid.UUID:
        bound = participants.get(getattr(ref, "value", str(ref)))
        if bound is None:
            raise ScopeDenied("participant reference is not bound to this Activity")
        return bound.entity_id

    payments = None
    if intent.payment_allocations is not None:
        payments = [
            c.CanonicalPayment(participant_id=resolve(item.participant_ref), amount=item.amount)
            for item in intent.payment_allocations
        ]
    split = None
    if isinstance(intent.split, c.EqualSplitIntent):
        split = c.CanonicalEqualSplit(
            mode="equal",
            participant_ids=[resolve(item) for item in intent.split.participant_refs],
        )
    elif isinstance(intent.split, c.ManualSplitIntent):
        split = c.CanonicalManualSplit(
            mode="manual",
            allocations=[
                c.CanonicalPayment(participant_id=resolve(item.participant_ref), amount=item.amount)
                for item in intent.split.allocations
            ],
        )
    return payments, split


def _resolve_create_bindings(
    intent: c.ExpenseCreateIntent,
    references: Sequence[c.BoundReference],
    *,
    turn_id: uuid.UUID,
) -> tuple[uuid.UUID, uuid.UUID, list[c.CanonicalPayment], c.CanonicalSplit]:
    units: dict[str, c.BoundLedgerUnitReference] = {}
    participants: dict[str, c.BoundParticipantReference] = {}
    for reference in references:
        if reference.source_turn_id != turn_id:
            continue
        if isinstance(reference, c.BoundLedgerUnitReference):
            units[reference.ref.value] = reference
        elif isinstance(reference, c.BoundParticipantReference):
            participants[reference.ref.value] = reference

    unit = units.get(intent.ledger_unit_ref.value)
    if unit is None:
        raise ScopeDenied("ledger unit reference is not bound to this turn")
    activity_id = unit.scope_activity_id

    def participant(ref: Any) -> c.BoundParticipantReference:
        bound = participants.get(getattr(ref, "value", str(ref)))
        if bound is None or bound.scope_activity_id != activity_id:
            raise ScopeDenied("participant reference is not bound to this Activity")
        return bound

    payments = [
        c.CanonicalPayment(participant_id=participant(item.participant_ref).entity_id, amount=item.amount)
        for item in intent.payment_allocations
    ]
    if isinstance(intent.split, c.EqualSplitIntent):
        split: c.CanonicalSplit = c.CanonicalEqualSplit(
            mode="equal",
            participant_ids=[participant(item).entity_id for item in intent.split.participant_refs],
        )
    else:
        split = c.CanonicalManualSplit(
            mode="manual",
            allocations=[
                c.CanonicalPayment(participant_id=participant(item.participant_ref).entity_id, amount=item.amount)
                for item in intent.split.allocations
            ],
        )
    return activity_id, unit.entity_id, payments, split


def _require_writable_activity(scope: Any, *, original_currency: str) -> None:
    activity = getattr(scope, "activity", None)
    if activity is None:
        raise ScopeDenied("activity scope is unavailable")
    if activity.is_deleted or activity.archived_at is not None:
        raise ScopeDenied("activity is not writable")
    if original_currency.upper() != activity.base_currency:
        raise LiveWriteError("foreign_currency_not_in_p5")


def _activity_grant(
    *,
    owner_user_id: uuid.UUID,
    turn_id: uuid.UUID,
    access_token: str,
    expires_at: datetime,
    activity_id: uuid.UUID,
) -> VerifiedReadContext:
    return VerifiedReadContext(
        owner_user_id=owner_user_id,
        turn_id=turn_id,
        principal_user_id=owner_user_id,
        access_token=access_token,
        expires_at=expires_at,
        refs_by_opaque_token={
            f"p5_activity_{activity_id}": BoundRef(kind="activity", object_id=activity_id),
        },
    )


def _create_changes(after: c.ExpenseSnapshot) -> list[c.ExpenseFieldChange]:
    changes: list[c.ExpenseFieldChange] = [
        c.ExpenseTitleChange(field="title", before=None, after=after.title),
        c.ExpenseAmountChange(field="original_amount", before=None, after=after.original_amount),
        c.ExpenseAmountChange(field="base_amount", before=None, after=after.base_amount),
        c.ExpenseCurrencyChange(field="original_currency", before=None, after=after.original_currency),
        c.ExpenseLedgerUnitChange(field="ledger_unit_id", before=None, after=after.ledger_unit_id),
        c.ExpensePaymentsChange(field="payment_allocations", before=None, after=after.payment_allocations),
        c.ExpenseSplitChange(field="split", before=None, after=after.split),
    ]
    if after.occurred_at is not None:
        changes.append(c.ExpenseOccurredAtChange(field="occurred_at", before=None, after=after.occurred_at))
    if after.note is not None:
        changes.append(c.ExpenseNoteChange(field="note", before=None, after=after.note))
    return changes


def _rpc_payload(command: c.FixedExpenseCreateCommand) -> dict[str, Any]:
    payments = [
        {"participant_id": str(item.participant_id), "amount": item.amount}
        for item in command.payment_allocations
    ]
    if isinstance(command.split, c.CanonicalEqualSplit):
        split_method = "equal"
        manual_splits: list[dict[str, Any]] = []
        aa_participant_ids = [str(item) for item in command.split.participant_ids]
    elif isinstance(command.split, c.CanonicalManualSplit):
        split_method = "manual"
        manual_splits = [
            {"participant_id": str(item.participant_id), "amount": item.amount}
            for item in command.split.allocations
        ]
        aa_participant_ids = []
    else:  # pragma: no cover - the discriminated union makes this unreachable
        raise LiveWriteError("unsupported_split")
    return {
        "ledger_unit_id": str(command.ledger_unit_id),
        "title": command.title,
        "original_amount": command.original_amount,
        "original_currency": command.original_currency,
        "split_method": split_method,
        "payments": payments,
        "manual_splits": manual_splits,
        "aa_participant_ids": aa_participant_ids,
        "occurred_at": command.occurred_at.isoformat() if command.occurred_at is not None else None,
        "note": command.note,
        "original_expense_id": None,
    }


def _business_error_code(status: int, rows: list[Any]) -> str | None:
    """Map the stable Postgres/PostgREST codes P5.0 cares about.

    Anything unrecognised below 500 is still a deterministic refusal, just with a
    generic code. 5xx without a recognised business code is treated as unknown.
    """
    if not rows or not isinstance(rows[0], dict):
        return None
    code = rows[0].get("code")
    if not isinstance(code, str):
        return None
    if code == "42501":
        return "permission_denied"
    if code == "P0002":
        return "not_found"
    if code == "55000":
        return "activity_read_only"
    if code == "23514":
        return "constraint_rejected"
    if code == "22023":
        return "invalid_parameter"
    if code == "23505":
        return "conflict"
    return None


def _decode_rows(body: bytes) -> list[Any]:
    if not body:
        return []
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        return [parsed]
    return []


def _new_nonce() -> str:
    import secrets

    return secrets.token_urlsafe(32)


def _aware(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0)
    if value.tzinfo is None or value.utcoffset() is None:
        raise LiveWriteError("invalid_timestamp")
    return value.astimezone(timezone.utc).replace(microsecond=0)


def _grant_expiry(principal: Principal) -> datetime:
    expiry = principal.expires_at
    if expiry is None or expiry.tzinfo is None or expiry.utcoffset() is None:
        return datetime.now(timezone.utc) + timedelta(seconds=60)
    return expiry


async def _call_async(function: Any, *args: Any, **kwargs: Any) -> Any:
    import asyncio

    return await asyncio.to_thread(function, *args, **kwargs)


async def _call_store(function: Any, *args: Any, **kwargs: Any) -> Any:
    import asyncio

    return await asyncio.to_thread(function, *args, **kwargs)
