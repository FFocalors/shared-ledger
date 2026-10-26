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

import hashlib
import http.client
import json
import socket
import ssl
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
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
P5_FINAL_SETTLEMENT_POLICY_VERSION = "p5-live-final-settlement-v1"
P5_REFUND_POLICY_VERSION = "p5-live-refund-v1"
P5_NEGATIVE_ADJUSTMENT_POLICY_VERSION = "p5-live-negative-adjustment-v1"
P5_ACTIVITY_CREATE_POLICY_VERSION = "p5-live-activity-create-v1"
P5_ACTIVITY_JOIN_POLICY_VERSION = "p5-live-activity-join-v1"
P5_PARTICIPANT_CREATE_POLICY_VERSION = "p5-live-participant-create-v1"
P5_PARTICIPANT_DELETE_POLICY_VERSION = "p5-live-participant-delete-v1"
P5_CLAIM_POLICY_VERSION = "p5-live-participant-claim-v1"
P5_UNCLAIM_POLICY_VERSION = "p5-live-participant-unclaim-v1"
P5_SUB_ACTIVITY_CREATE_POLICY_VERSION = "p5-live-sub-activity-create-v1"
P5_SUB_ACTIVITY_DELETE_POLICY_VERSION = "p5-live-sub-activity-delete-v1"
P5_SUB_ACTIVITY_RESTORE_POLICY_VERSION = "p5-live-sub-activity-restore-v1"
P5_MEMBER_REMOVE_POLICY_VERSION = "p5-live-member-remove-v1"
P5_CREATOR_TRANSFER_POLICY_VERSION = "p5-live-creator-transfer-v1"
P5_ARCHIVE_POLICY_VERSION = "p5-live-activity-archive-v1"
P5_UNARCHIVE_POLICY_VERSION = "p5-live-activity-unarchive-v1"
P5_ACTIVITY_DELETE_POLICY_VERSION = "p5-live-activity-delete-v1"
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
RPC_PREVIEW_FINAL_SETTLEMENT = "/rest/v1/rpc/preview_final_settlement_v2"
RPC_EXECUTE_FINAL_SETTLEMENT = "/rest/v1/rpc/execute_final_settlement_v2"
RPC_CREATE_ACTIVITY = "/rest/v1/rpc/create_activity"
RPC_JOIN_ACTIVITY = "/rest/v1/rpc/join_activity_by_code"
RPC_CREATE_PARTICIPANT = "/rest/v1/rpc/create_participant"
RPC_DELETE_PARTICIPANT = "/rest/v1/rpc/delete_participant"
RPC_CLAIM_PARTICIPANT = "/rest/v1/rpc/claim_participant"
RPC_UNCLAIM_PARTICIPANT = "/rest/v1/rpc/unclaim_participant"
RPC_CREATE_SUB_ACTIVITY = "/rest/v1/rpc/create_sub_activity"
RPC_DELETE_SUB_ACTIVITY = "/rest/v1/rpc/delete_sub_activity"
RPC_RESTORE_SUB_ACTIVITY = "/rest/v1/rpc/restore_sub_activity"
RPC_REMOVE_MEMBER = "/rest/v1/rpc/remove_activity_member"
RPC_TRANSFER_CREATOR = "/rest/v1/rpc/transfer_activity_creator"
RPC_ARCHIVE_ACTIVITY = "/rest/v1/rpc/archive_activity"
RPC_UNARCHIVE_ACTIVITY = "/rest/v1/rpc/unarchive_activity"
RPC_DELETE_ACTIVITY = "/rest/v1/rpc/delete_activity"
_LEDGER_UNIT_SELECT = "id,activity_id,name,type,is_deleted"
_CLAIM_SELECT = "id,activity_id,participant_id,user_id"
_FINANCIAL_STATUS_SELECT = (
    "activity_id,total_debt,total_prepayment,has_unsettled_debt,completed"
)
_ACTIVITY_MANAGEMENT_SELECT = (
    "id,name,type,base_currency,multi_currency_enabled,created_by,"
    "archived_at,is_deleted,participants_locked_at,join_code"
)
_PARTICIPANT_SELECT = "id,activity_id,name,participant_order,is_deleted"
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

_MANAGEMENT_OPERATIONS = frozenset({
    "activity.create", "activity.join", "participant.create", "participant.delete",
    "participant.claim", "participant.unclaim",
    "subactivity.create", "subactivity.delete", "subactivity.restore",
    "activity.member.remove", "activity.creator.transfer",
    "activity.archive", "activity.unarchive", "activity.delete",
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
    "final_settlement_plan_empty": "the server has no final settlement items now",
    "final_settlement_item_not_in_plan": "the requested item is not in the current final settlement plan",
    "final_settlement_preview_rejected": "the server refused the final settlement preview",
    "final_settlement_invalid": "the final settlement request is invalid",
    "final_settlement_participant_invalid": "the final settlement participants are not active in this Activity",
    "final_settlement_version_conflict": "the Activity financial version changed",
    "final_settlement_stale_plan": "the server's final settlement plan changed",
    "final_settlement_rejected": "the server refused the final settlement",
    "activity_type_changed": "the Activity type changed after the preview",
    "refund_original_not_found": "the original Expense was not found",
    "refund_original_invalid": "the original Expense cannot be refunded",
    "refund_currency_mismatch": "the refund must use the original Expense currency",
    "refund_exceeds_remaining": "the refund exceeds what is still refundable",
    "refund_source_changed": "the original Expense or its refunds changed after the preview",
    "refund_source_unavailable": "the refund source history could not be read",
    "negative_adjustment_invalid": "the negative adjustment request is invalid",
    "refunded_elsewhere": "a refund landed but this execution cannot be proven to be its author",
    "refund_not_applied": "no refund was recorded and the original Expense is unchanged",
    "adjustment_not_applied": "no negative adjustment was recorded and the Activity is unchanged",
    "management_invalid": "the management request is invalid",
    "activity_name_conflict": "an Activity with this name already exists for this user",
    "participant_list_locked": "the participant list is locked",
    "participant_name_conflict": "a Participant with this name already exists in the Activity",
    "participant_claimed_or_used": "the Participant is claimed or used by financial facts",
    "participant_not_found": "the Participant was not found",
    "join_code_inactive": "the join code is no longer usable",
    "management_state_changed": "the management state changed after the preview",
    "activity_created_elsewhere": "an Activity was created but this execution cannot be proven to be its author",
    "activity_not_created": "no matching Activity exists",
    "joined_elsewhere": "membership exists but this execution cannot be proven to have joined",
    "join_not_applied": "no membership exists for this join code",
    "participant_created_elsewhere": "a Participant was created but this execution cannot be proven to be its author",
    "participant_not_created": "no matching Participant exists",
    "deleted_elsewhere": "the Participant is deleted but this execution cannot be proven to be the author",
    "delete_not_applied": "the Participant is not deleted",
    "conflict": "the request conflicts with existing data",
    "sub_activity_requires_large": "sub-activities require a large activity",
    "sub_activity_root_missing": "the large activity has no root ledger unit",
    "sub_activity_name_conflict": "a ledger unit with this name already exists",
    "sub_activity_participant_invalid": "the selected Participants are not all active in this Activity",
    "sub_activity_not_found": "the sub-activity was not found",
    "not_a_sub_activity": "the ledger unit is not a sub-activity",
    "sub_activity_state_changed": "the sub-activity state changed after the preview",
    "participant_claimed_by_other": "the Participant is already claimed by another member",
    "actor_already_claimed_other": "you already claimed a different Participant in this Activity",
    "claim_state_changed": "the claim state changed after the preview",
    "claim_not_found": "you have no claim to release",
    "participant_claim_conflict": "the Participant claim conflicts with an existing one",
    "sub_activity_created_elsewhere": "a sub-activity matches but this execution cannot be proven to be its author",
    "sub_activity_not_created": "no matching sub-activity exists",
    "sub_activity_deleted_elsewhere": "the sub-activity is deleted but this execution cannot be proven to be the author",
    "sub_activity_delete_not_applied": "the sub-activity is not deleted",
    "sub_activity_restored_elsewhere": "the sub-activity is restored but this execution cannot be proven to be the author",
    "sub_activity_restore_not_applied": "the sub-activity is still deleted",
    "claimed_elsewhere": "a claim exists but this execution cannot be proven to be its author",
    "claim_not_applied": "no claim exists",
    "released_elsewhere": "the claim is released but this execution cannot be proven to be the author",
    "unclaim_not_applied": "the claim still exists",
    "creator_permission_required": "only the Activity creator may do this",
    "activity_archived": "the Activity is archived; unarchive it first",
    "cannot_remove_self": "the creator cannot remove their own membership",
    "cannot_transfer_to_self": "the new creator must be another member",
    "member_not_found": "the target is not an Activity member",
    "new_creator_not_member": "the new creator must be another active member",
    "creator_changed": "the Activity creator changed after the preview",
    "members_changed": "the Activity membership changed after the preview",
    "activity_state_changed": "the Activity state changed after the preview",
    "member_removed_elsewhere": "the member is gone but this execution cannot be proven to be the author",
    "member_remove_not_applied": "the target is still an Activity member",
    "creator_transferred_elsewhere": "the creator changed but this execution cannot be proven to be the author",
    "creator_transfer_not_applied": "the Activity creator is unchanged",
    "archived_elsewhere": "the Activity is archived but this execution cannot be proven to be the author",
    "archive_not_applied": "the Activity is not archived",
    "unarchived_elsewhere": "the Activity is unarchived but this execution cannot be proven to be the author",
    "unarchive_not_applied": "the Activity is still archived",
    "activity_deleted_elsewhere": "the Activity is deleted but this execution cannot be proven to be the author",
    "delete_activity_not_applied": "the Activity is not deleted",
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
class LiveActivityManagementState:
    activity_id: uuid.UUID
    name: str
    activity_type: str
    base_currency: str
    multi_currency_enabled: bool
    created_by: uuid.UUID | None
    archived: bool
    is_deleted: bool
    participants_locked: bool
    join_code: str | None


@dataclass(frozen=True, slots=True)
class LiveParticipantState:
    participant_id: uuid.UUID
    activity_id: uuid.UUID
    name: str
    participant_order: int
    is_deleted: bool


@dataclass(frozen=True, slots=True)
class LiveLedgerUnitState:
    ledger_unit_id: uuid.UUID
    activity_id: uuid.UUID
    name: str
    unit_type: str
    is_deleted: bool


@dataclass(frozen=True, slots=True)
class LiveClaimState:
    claim_id: uuid.UUID
    activity_id: uuid.UUID
    participant_id: uuid.UUID
    user_id: uuid.UUID


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

    async def read_activity_management_state(
        self, access_token: str, activity_id: uuid.UUID,
    ) -> LiveActivityManagementState:
        rows = await self._get_rows(
            "activities",
            [
                ("id", f"eq.{activity_id}"),
                ("select", _ACTIVITY_MANAGEMENT_SELECT),
                ("limit", "2"),
            ],
            access_token,
        )
        if len(rows) != 1:
            raise LiveWriteError("activity_not_found")
        return _activity_management_state(rows[0])

    async def read_activity_by_join_code(
        self, access_token: str, join_code: str,
    ) -> LiveActivityManagementState | None:
        """Only members can read an Activity; a non-member sees no row."""
        rows = await self._get_rows(
            "activities",
            [
                ("join_code", f"eq.{join_code}"),
                ("select", _ACTIVITY_MANAGEMENT_SELECT),
                ("limit", "2"),
            ],
            access_token,
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise LiveWriteError("upstream_invalid_response")
        return _activity_management_state(rows[0])

    async def list_activities_by_name(
        self, access_token: str, name: str,
    ) -> list[LiveActivityManagementState]:
        rows = await self._get_rows(
            "activities",
            [
                ("name", f"eq.{name}"),
                ("is_deleted", "eq.false"),
                ("select", _ACTIVITY_MANAGEMENT_SELECT),
                ("order", "id.asc"),
            ],
            access_token,
        )
        return [_activity_management_state(row) for row in rows]

    async def list_participants(
        self, access_token: str, activity_id: uuid.UUID,
    ) -> list[LiveParticipantState]:
        rows = await self._get_rows(
            "participants",
            [
                ("activity_id", f"eq.{activity_id}"),
                ("is_deleted", "eq.false"),
                ("select", _PARTICIPANT_SELECT),
                ("order", "participant_order.asc"),
            ],
            access_token,
        )
        return [_participant_state(row) for row in rows]

    async def read_participant_state(
        self, access_token: str, participant_id: uuid.UUID,
    ) -> LiveParticipantState:
        rows = await self._get_rows(
            "participants",
            [
                ("id", f"eq.{participant_id}"),
                ("select", _PARTICIPANT_SELECT),
                ("limit", "2"),
            ],
            access_token,
        )
        if len(rows) != 1:
            raise LiveWriteError("participant_not_found")
        return _participant_state(rows[0])

    async def read_participant_usage(
        self, access_token: str, participant_id: uuid.UUID,
    ) -> bool:
        """True when the Participant is claimed or referenced by any fact."""
        for route in ("participant_claims", "payments", "splits"):
            rows = await self._get_rows(
                route,
                [("participant_id", f"eq.{participant_id}"), ("select", "id"), ("limit", "1")],
                access_token,
            )
            if rows:
                return True
        for column in ("from_participant_id", "to_participant_id", "on_behalf_of_participant_id"):
            rows = await self._get_rows(
                "transfers",
                [(column, f"eq.{participant_id}"), ("select", "id"), ("limit", "1")],
                access_token,
            )
            if rows:
                return True
        return False

    async def read_ledger_unit_state(
        self, access_token: str, ledger_unit_id: uuid.UUID,
    ) -> LiveLedgerUnitState:
        rows = await self._get_rows(
            "ledger_units",
            [
                ("id", f"eq.{ledger_unit_id}"),
                ("select", _LEDGER_UNIT_SELECT),
                ("limit", "2"),
            ],
            access_token,
        )
        if len(rows) != 1:
            raise LiveWriteError("sub_activity_not_found")
        return _ledger_unit_state(rows[0])

    async def list_ledger_units(
        self, access_token: str, activity_id: uuid.UUID,
    ) -> list[LiveLedgerUnitState]:
        rows = await self._get_rows(
            "ledger_units",
            [
                ("activity_id", f"eq.{activity_id}"),
                ("select", _LEDGER_UNIT_SELECT),
                ("order", "id.asc"),
            ],
            access_token,
        )
        return [_ledger_unit_state(row) for row in rows]

    async def list_activity_claims(
        self, access_token: str, activity_id: uuid.UUID,
    ) -> list[LiveClaimState]:
        rows = await self._get_rows(
            "participant_claims",
            [
                ("activity_id", f"eq.{activity_id}"),
                ("select", _CLAIM_SELECT),
                ("order", "id.asc"),
            ],
            access_token,
        )
        return [
            LiveClaimState(
                claim_id=_uuid(row.get("id")),
                activity_id=_uuid(row.get("activity_id")),
                participant_id=_uuid(row.get("participant_id")),
                user_id=_uuid(row.get("user_id")),
            )
            for row in rows
        ]

    async def list_activity_members(
        self, access_token: str, activity_id: uuid.UUID,
    ) -> list[uuid.UUID]:
        rows = await self._get_rows(
            "activity_members",
            [
                ("activity_id", f"eq.{activity_id}"),
                ("select", "user_id"),
                ("order", "user_id.asc"),
            ],
            access_token,
        )
        return [_uuid(row.get("user_id")) for row in rows]

    async def read_activity_financial_status(
        self, access_token: str, activity_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Member-readable summary the archive preview must show."""
        rows = await self._get_rows(
            "activity_financial_status",
            [
                ("activity_id", f"eq.{activity_id}"),
                ("select", _FINANCIAL_STATUS_SELECT),
                ("limit", "2"),
            ],
            access_token,
        )
        if len(rows) != 1:
            raise LiveWriteError("activity_not_found")
        return rows[0]

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

    async def read_refunded_amount(
        self, access_token: str, original_expense_id: uuid.UUID,
    ) -> Decimal:
        """Sum the active linked refunds the server currently holds.

        This is the only authority for the refund cap; the Agent never adds up
        its own history.
        """
        rows = await self._get_rows(
            "expenses",
            [
                ("original_expense_id", f"eq.{original_expense_id}"),
                ("is_deleted", "eq.false"),
                ("select", "id,original_amount"),
                ("order", "id.asc"),
                ("limit", "1000"),
            ],
            access_token,
        )
        if len(rows) >= 1000:
            raise LiveWriteError("refund_source_unavailable")
        total = Decimal("0")
        for row in rows:
            try:
                total += abs(Decimal(_num_text(row.get("original_amount"))))
            except (InvalidOperation, ValueError):
                raise LiveWriteError("upstream_invalid_response") from None
        return total

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

    # --------------------------------------------------- final settlement preview

    async def build_final_settlement_preview(
        self,
        *,
        owner_user_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        intent: c.FinalSettlementIntent,
        access_token: str,
        expires_at: datetime,
        agent_disable_revision: int,
        policy_version: str | None = None,
        summary_prefix: str = "",
        now: datetime | None = None,
    ) -> c.ProposalRecord:
        """Select one item from the server's complete current settlement plan.

        The plan is the server's suggestion as a whole. The Agent keeps every
        item, matches the requested direction/amount/currency field by field,
        and copies the matched item into the command unchanged. It never
        computes, reorders or nets anything.
        """
        if not isinstance(intent, c.FinalSettlementIntent):
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
            raise LiveWriteError("final_settlement_participant_invalid")
        activity = scope.activity
        if activity is None:
            raise LiveWriteError("activity_not_found")

        status, body = await self._post_rpc(
            RPC_PREVIEW_FINAL_SETTLEMENT,
            access_token,
            {"activity_id": str(intent.activity_id), "mode": intent.mode},
        )
        if status != 200:
            rows = _decode_rows(body)
            error_code = _final_settlement_error_code(
                status, _raw_error_code(rows), _raw_error_message(rows),
            )
            if error_code is None:
                error_code = (
                    "upstream_read_failed" if status >= 500
                    else "final_settlement_preview_rejected"
                )
            raise LiveWriteError(error_code, retryable=status >= 500)
        rows = _decode_read_rows(body)
        if not rows:
            raise LiveWriteError("final_settlement_plan_empty")
        plan_items: list[c.FinalSettlementPlanItem] = []
        expected_version: int | None = None
        for row in rows:
            if (
                str(row.get("activity_id")) != str(intent.activity_id)
                or str(row.get("mode")) != intent.mode
            ):
                raise LiveWriteError("final_settlement_preview_rejected")
            row_version = _int(row.get("source_financial_version"))
            if expected_version is None:
                expected_version = row_version
            elif row_version != expected_version:
                raise LiveWriteError("final_settlement_preview_rejected")
            try:
                plan_items.append(c.FinalSettlementPlanItem(
                    from_participant_id=_uuid(row.get("from_participant_id")),
                    to_participant_id=_uuid(row.get("to_participant_id")),
                    amount=_num_text(row.get("amount")),
                    ordinary_amount=_num_text(row.get("ordinary_amount")),
                    prepayment_return_amount=_num_text(row.get("prepayment_return_amount")),
                    currency=str(row.get("currency")),
                    is_prepayment_return=_bool(row.get("is_prepayment_return")),
                ))
            except ValueError:
                raise LiveWriteError("final_settlement_preview_rejected") from None
        matches = [
            item for item in plan_items
            if item.from_participant_id == intent.from_participant_id
            and item.to_participant_id == intent.to_participant_id
            and item.currency == intent.currency
            and Decimal(item.amount) == Decimal(intent.amount)
        ]
        if len(matches) != 1:
            raise LiveWriteError("final_settlement_item_not_in_plan")
        selected = matches[0]
        try:
            preview = c.FinalSettlementPreview(
                kind="final_settlement",
                summary=_final_settlement_summary(
                    summary_prefix, participants, plan_items, selected, intent.mode,
                ),
                activity_id=intent.activity_id,
                mode=intent.mode,
                from_participant_id=selected.from_participant_id,
                to_participant_id=selected.to_participant_id,
                amount=selected.amount,
                currency=selected.currency,
                ordinary_amount=selected.ordinary_amount,
                prepayment_return_amount=selected.prepayment_return_amount,
                is_prepayment_return=selected.is_prepayment_return,
                plan=plan_items,
                expected_financial_version=str(expected_version),
                generated_at=instant,
                simulation=False,
            )
            command = c.FixedFinalSettlementCommand(
                operation="settlement.final",
                activity_id=intent.activity_id,
                from_participant_id=preview.from_participant_id,
                to_participant_id=preview.to_participant_id,
                amount=preview.amount,
                currency=preview.currency,
                mode=preview.mode,
                expected_financial_version=preview.expected_financial_version,
                expected_activity_type=activity.activity_type,
                expected_ordinary_amount=preview.ordinary_amount,
                expected_prepayment_return_amount=preview.prepayment_return_amount,
                occurred_at=instant,
            )
        except ValueError:
            raise LiveWriteError("final_settlement_preview_rejected") from None

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
            operation="settlement.final",
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

    # -------------------------------------------------------------- refund preview

    async def build_refund_preview(
        self,
        *,
        owner_user_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        intent: c.ExpenseRefundIntent,
        bound_references: Sequence[c.BoundReference],
        access_token: str,
        expires_at: datetime,
        agent_disable_revision: int,
        policy_version: str | None = None,
        summary_prefix: str = "",
        now: datetime | None = None,
    ) -> c.ProposalRecord:
        """Build a linked-refund proposal from server reads only.

        Currency and FX come from the original Expense; the cap uses the
        server's current active-refund total, never a local running sum.
        """
        if not isinstance(intent, c.ExpenseRefundIntent):
            raise LiveWriteError("unsupported_operation")
        instant = _aware(now)
        activity_id, original_id, payments, split = _resolve_refund_bindings(
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
        if scope.activity is None:
            raise LiveWriteError("activity_not_found")
        try:
            state = await self.read_expense_state(access_token, original_id)
        except LiveWriteError as exc:
            if exc.code == "expense_not_found":
                raise LiveWriteError("refund_original_not_found") from None
            raise
        if state.is_deleted or state.original_expense_id is not None:
            raise LiveWriteError("refund_original_invalid")
        try:
            original_amount = Decimal(state.original_amount)
        except (InvalidOperation, ValueError):
            raise LiveWriteError("upstream_invalid_response") from None
        if original_amount <= 0:
            raise LiveWriteError("refund_original_invalid")
        refunded = await self.read_refunded_amount(access_token, original_id)
        remaining = original_amount - refunded
        if remaining <= 0 or Decimal(intent.original_amount) > remaining:
            raise LiveWriteError("refund_exceeds_remaining")
        currency = state.original_currency
        expected_version = scope.activity.financial_version

        preview = c.RefundPreview(
            kind="refund",
            summary=(
                f"{summary_prefix}退款 {intent.original_amount} {currency} "
                f"退自「{state.title}」（原单 {_num_text(original_amount)} {currency}，"
                f"version {state.version}）；累计已退 {_num_text(refunded)}；"
                f"本次上限 {_num_text(remaining)}"
            ),
            activity_id=activity_id,
            original_expense_id=original_id,
            original_title=state.title,
            refund_title=intent.title,
            original_amount=_num_text(original_amount),
            refunded_amount=_num_text(refunded),
            refund_amount=intent.original_amount,
            remaining_amount=_num_text(remaining),
            currency=currency,
            expected_financial_version=str(expected_version),
            expected_original_version=str(state.version),
            expected_original_financial_locked=state.financial_locked,
            generated_at=instant,
            simulation=False,
        )
        command = c.FixedExpenseRefundCommand(
            operation="expense.refund",
            activity_id=activity_id,
            original_expense_id=original_id,
            ledger_unit_id=state.ledger_unit_id,
            title=intent.title,
            amount=intent.original_amount,
            currency=currency,
            payment_allocations=payments,
            split=split,
            occurred_at=instant,
            note=intent.note,
            expected_financial_version=preview.expected_financial_version,
            expected_original_version=preview.expected_original_version,
            expected_original_financial_locked=preview.expected_original_financial_locked,
            expected_refunded_amount=preview.refunded_amount,
            expected_original_amount=preview.original_amount,
        )

        policy = policy_version or self._config.policy_version
        preconditions = c.PreconditionSnapshot(
            activity_id=activity_id,
            permission_checked=True,
            agent_disable_revision=agent_disable_revision,
            activity_financial_version=preview.expected_financial_version,
            expense_version=preview.expected_original_version,
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
            operation="expense.refund",
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

    async def build_negative_adjustment_preview(
        self,
        *,
        owner_user_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        intent: c.NegativeAdjustmentIntent,
        bound_references: Sequence[c.BoundReference],
        access_token: str,
        expires_at: datetime,
        agent_disable_revision: int,
        policy_version: str | None = None,
        summary_prefix: str = "",
        now: datetime | None = None,
    ) -> c.ProposalRecord:
        """Build an explicit unlinked negative Expense; no original is involved."""
        if not isinstance(intent, c.NegativeAdjustmentIntent):
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
        preview = c.NegativeAdjustmentPreview(
            kind="negative_adjustment",
            summary=(
                f"{summary_prefix}负调整 {intent.title} {intent.original_amount} "
                f"{intent.original_currency}；未关联原单（显式负向调整，不占用退款上限）"
            ),
            activity_id=activity_id,
            title=intent.title,
            amount=intent.original_amount,
            currency=intent.original_currency,
            expected_financial_version=str(scope.activity.financial_version),
            generated_at=instant,
            simulation=False,
        )
        command = c.FixedNegativeAdjustmentCommand(
            operation="expense.negative_adjustment",
            activity_id=activity_id,
            ledger_unit_id=ledger_unit_id,
            title=intent.title,
            amount=intent.original_amount,
            currency=intent.original_currency,
            payment_allocations=payments,
            split=split,
            occurred_at=instant,
            note=intent.note,
            expected_financial_version=preview.expected_financial_version,
        )

        policy = policy_version or self._config.policy_version
        preconditions = c.PreconditionSnapshot(
            activity_id=activity_id,
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
            operation="expense.negative_adjustment",
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

    # ------------------------------------------------- management previews (P5.8a)

    async def build_activity_create_preview(
        self,
        *,
        owner_user_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        intent: c.ActivityCreateIntent,
        access_token: str,
        agent_disable_revision: int,
        policy_version: str | None = None,
        summary_prefix: str = "",
        now: datetime | None = None,
    ) -> c.ProposalRecord:
        """Create an Activity. The caller never supplies a creator id."""
        if not isinstance(intent, c.ActivityCreateIntent):
            raise LiveWriteError("unsupported_operation")
        instant = _aware(now)
        existing = await self.list_activities_by_name(access_token, intent.name)
        if existing:
            raise LiveWriteError("activity_name_conflict")
        preview = c.ManagementPreview(
            kind="management",
            summary=(
                f"{summary_prefix}建活动「{intent.name}」"
                f"（{'大型' if intent.activity_type == 'large' else '普通'}）"
                f"{intent.base_currency}；多币种"
                f"{'开启' if intent.multi_currency_enabled else '关闭'}"
            ),
            operation="activity.create",
            activity_name=intent.name,
            activity_type=intent.activity_type,
            base_currency=intent.base_currency,
            multi_currency_enabled=intent.multi_currency_enabled,
            generated_at=instant,
            simulation=False,
        )
        command = c.FixedActivityCreateCommand(
            operation="activity.create",
            name=intent.name,
            activity_type=intent.activity_type,
            base_currency=intent.base_currency,
            multi_currency_enabled=intent.multi_currency_enabled,
        )
        return self._management_proposal(
            owner_user_id=owner_user_id, session_id=session_id, turn_id=turn_id,
            operation="activity.create", intent=intent, command=command, preview=preview,
            activity_id=None, expense_version=None,
            agent_disable_revision=agent_disable_revision,
            policy_version=policy_version, now=instant,
        )

    async def build_activity_join_preview(
        self,
        *,
        owner_user_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        intent: c.ActivityJoinIntent,
        access_token: str,
        agent_disable_revision: int,
        policy_version: str | None = None,
        summary_prefix: str = "",
        now: datetime | None = None,
    ) -> c.ProposalRecord:
        """Join by code. Joining is not claiming a Participant."""
        if not isinstance(intent, c.ActivityJoinIntent):
            raise LiveWriteError("unsupported_operation")
        instant = _aware(now)
        existing = await self.read_activity_by_join_code(access_token, intent.join_code)
        hint = ""
        if existing is not None:
            hint = f"（已加入：{existing.name}）"
        preview = c.ManagementPreview(
            kind="management",
            summary=(
                f"{summary_prefix}加入活动，加入码 {intent.join_code}{hint}；"
                "加入不等于认领参与人"
            ),
            operation="activity.join",
            join_code=intent.join_code,
            generated_at=instant,
            simulation=False,
        )
        command = c.FixedActivityJoinCommand(
            operation="activity.join", join_code=intent.join_code,
        )
        return self._management_proposal(
            owner_user_id=owner_user_id, session_id=session_id, turn_id=turn_id,
            operation="activity.join", intent=intent, command=command, preview=preview,
            activity_id=None, expense_version=None,
            agent_disable_revision=agent_disable_revision,
            policy_version=policy_version, now=instant,
        )

    async def build_participant_create_preview(
        self,
        *,
        owner_user_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        intent: c.ParticipantCreateIntent,
        access_token: str,
        expires_at: datetime,
        agent_disable_revision: int,
        policy_version: str | None = None,
        summary_prefix: str = "",
        now: datetime | None = None,
    ) -> c.ProposalRecord:
        if not isinstance(intent, c.ParticipantCreateIntent):
            raise LiveWriteError("unsupported_operation")
        instant = _aware(now)
        grant = _activity_grant(
            owner_user_id=owner_user_id, turn_id=turn_id,
            access_token=access_token, expires_at=expires_at,
            activity_id=intent.activity_id,
        )
        await self._read_backend.resolve_scope(
            grant, ScopeRequest(mode="activity", ui_activity_id_hint=intent.activity_id),
        )
        state = await self.read_activity_management_state(access_token, intent.activity_id)
        if state.is_deleted:
            raise LiveWriteError("activity_not_found")
        if state.participants_locked:
            raise LiveWriteError("participant_list_locked")
        participants = await self.list_participants(access_token, intent.activity_id)
        if any(item.name == intent.name for item in participants):
            raise LiveWriteError("participant_name_conflict")
        next_order = max((item.participant_order for item in participants), default=-1) + 1
        order_text = (
            str(intent.participant_order) if intent.participant_order is not None
            else f"自动（当前下一个为 {next_order}）"
        )
        preview = c.ManagementPreview(
            kind="management",
            summary=(
                f"{summary_prefix}加参与人「{intent.name}」到「{state.name}」；"
                f"顺序 {order_text}"
            ),
            operation="participant.create",
            activity_id=intent.activity_id,
            activity_name=state.name,
            participant_name=intent.name,
            participant_order=intent.participant_order,
            generated_at=instant,
            simulation=False,
        )
        command = c.FixedParticipantCreateCommand(
            operation="participant.create",
            activity_id=intent.activity_id,
            name=intent.name,
            participant_order=intent.participant_order,
            expected_participants_locked=False,
            expected_activity_archived=state.archived,
            expected_activity_deleted=False,
        )
        return self._management_proposal(
            owner_user_id=owner_user_id, session_id=session_id, turn_id=turn_id,
            operation="participant.create", intent=intent, command=command, preview=preview,
            activity_id=intent.activity_id, expense_version=None,
            agent_disable_revision=agent_disable_revision,
            policy_version=policy_version, now=instant,
        )

    async def build_participant_delete_preview(
        self,
        *,
        owner_user_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        intent: c.ParticipantDeleteIntent,
        access_token: str,
        expires_at: datetime,
        agent_disable_revision: int,
        policy_version: str | None = None,
        summary_prefix: str = "",
        now: datetime | None = None,
    ) -> c.ProposalRecord:
        if not isinstance(intent, c.ParticipantDeleteIntent):
            raise LiveWriteError("unsupported_operation")
        instant = _aware(now)
        grant = _activity_grant(
            owner_user_id=owner_user_id, turn_id=turn_id,
            access_token=access_token, expires_at=expires_at,
            activity_id=intent.activity_id,
        )
        await self._read_backend.resolve_scope(
            grant, ScopeRequest(mode="activity", ui_activity_id_hint=intent.activity_id),
        )
        participant = await self.read_participant_state(access_token, intent.participant_id)
        if participant.activity_id != intent.activity_id:
            raise LiveWriteError("participant_not_found")
        state = await self.read_activity_management_state(access_token, intent.activity_id)
        if state.is_deleted:
            raise LiveWriteError("activity_not_found")
        if state.participants_locked:
            raise LiveWriteError("participant_list_locked")
        if await self.read_participant_usage(access_token, intent.participant_id):
            raise LiveWriteError("participant_claimed_or_used")
        preview = c.ManagementPreview(
            kind="management",
            summary=(
                f"{summary_prefix}删参与人「{participant.name}」"
                f"（活动「{state.name}」）；未认领、未被付款/分摊/转账引用"
            ),
            operation="participant.delete",
            activity_id=intent.activity_id,
            activity_name=state.name,
            participant_id=intent.participant_id,
            participant_name=participant.name,
            generated_at=instant,
            simulation=False,
        )
        command = c.FixedParticipantDeleteCommand(
            operation="participant.delete",
            activity_id=intent.activity_id,
            participant_id=intent.participant_id,
            expected_participant_name=participant.name,
            expected_participant_deleted=participant.is_deleted,
            expected_claimed_or_used=False,
            expected_participants_locked=False,
            expected_activity_archived=state.archived,
            expected_activity_deleted=False,
        )
        return self._management_proposal(
            owner_user_id=owner_user_id, session_id=session_id, turn_id=turn_id,
            operation="participant.delete", intent=intent, command=command, preview=preview,
            activity_id=intent.activity_id, expense_version=None,
            agent_disable_revision=agent_disable_revision,
            policy_version=policy_version, now=instant,
        )

    # -------------------------------------- claim and sub-activity previews (P5.8b)

    async def build_participant_claim_preview(
        self,
        *,
        owner_user_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        intent: c.ParticipantClaimIntent,
        access_token: str,
        expires_at: datetime,
        agent_disable_revision: int,
        policy_version: str | None = None,
        summary_prefix: str = "",
        now: datetime | None = None,
    ) -> c.ProposalRecord:
        if not isinstance(intent, c.ParticipantClaimIntent):
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
        if scope.activity is None:
            raise LiveWriteError("activity_not_found")
        state = await self.read_activity_management_state(access_token, intent.activity_id)
        if state.is_deleted:
            raise LiveWriteError("activity_not_found")
        participant = await self.read_participant_state(access_token, intent.participant_id)
        if participant.activity_id != intent.activity_id or participant.is_deleted:
            raise LiveWriteError("participant_not_found")
        claims = await self.list_activity_claims(access_token, intent.activity_id)
        mine = next((item for item in claims if item.user_id == owner_user_id), None)
        target = next(
            (item for item in claims if item.participant_id == intent.participant_id), None,
        )
        if target is not None and target.user_id != owner_user_id:
            raise LiveWriteError("participant_claimed_by_other")
        if mine is not None and mine.participant_id != intent.participant_id:
            raise LiveWriteError("actor_already_claimed_other")
        claim_state = "mine" if mine is not None else "none"
        preview = c.ManagementPreview(
            kind="management",
            operation="participant.claim",
            activity_id=intent.activity_id,
            activity_name=state.name,
            participant_id=intent.participant_id,
            participant_name=participant.name,
            summary=(
                f"{summary_prefix}认领「{participant.name}」（活动「{state.name}」）；"
                + (
                    "本人已认领，重复确认不会新建"
                    if claim_state == "mine" else "当前未认领"
                )
            ),
            generated_at=instant,
            simulation=False,
        )
        command = c.FixedParticipantClaimCommand(
            operation="participant.claim",
            activity_id=intent.activity_id,
            participant_id=intent.participant_id,
            expected_financial_version=str(scope.activity.financial_version),
            expected_activity_archived=state.archived,
            expected_claim_state=claim_state,
        )
        return self._management_proposal(
            owner_user_id=owner_user_id, session_id=session_id, turn_id=turn_id,
            operation="participant.claim", intent=intent, command=command, preview=preview,
            activity_id=intent.activity_id, expense_version=None,
            agent_disable_revision=agent_disable_revision,
            policy_version=policy_version, now=instant,
            financial_version=str(scope.activity.financial_version),
        )

    async def build_participant_unclaim_preview(
        self,
        *,
        owner_user_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        intent: c.ParticipantUnclaimIntent,
        access_token: str,
        expires_at: datetime,
        agent_disable_revision: int,
        policy_version: str | None = None,
        summary_prefix: str = "",
        now: datetime | None = None,
    ) -> c.ProposalRecord:
        if not isinstance(intent, c.ParticipantUnclaimIntent):
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
        if scope.activity is None:
            raise LiveWriteError("activity_not_found")
        state = await self.read_activity_management_state(access_token, intent.activity_id)
        if state.is_deleted:
            raise LiveWriteError("activity_not_found")
        claims = await self.list_activity_claims(access_token, intent.activity_id)
        mine = next((item for item in claims if item.user_id == owner_user_id), None)
        if mine is None:
            raise LiveWriteError("claim_not_found")
        participant = await self.read_participant_state(access_token, mine.participant_id)
        preview = c.ManagementPreview(
            kind="management",
            operation="participant.unclaim",
            activity_id=intent.activity_id,
            activity_name=state.name,
            participant_id=mine.participant_id,
            participant_name=participant.name,
            summary=(
                f"{summary_prefix}解除认领「{participant.name}」（活动「{state.name}」）"
            ),
            generated_at=instant,
            simulation=False,
        )
        command = c.FixedParticipantUnclaimCommand(
            operation="participant.unclaim",
            activity_id=intent.activity_id,
            expected_financial_version=str(scope.activity.financial_version),
            expected_activity_archived=state.archived,
            expected_claim_participant_id=mine.participant_id,
        )
        return self._management_proposal(
            owner_user_id=owner_user_id, session_id=session_id, turn_id=turn_id,
            operation="participant.unclaim", intent=intent, command=command, preview=preview,
            activity_id=intent.activity_id, expense_version=None,
            agent_disable_revision=agent_disable_revision,
            policy_version=policy_version, now=instant,
            financial_version=str(scope.activity.financial_version),
        )

    async def build_sub_activity_create_preview(
        self,
        *,
        owner_user_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        intent: c.SubActivityCreateIntent,
        access_token: str,
        expires_at: datetime,
        agent_disable_revision: int,
        policy_version: str | None = None,
        summary_prefix: str = "",
        now: datetime | None = None,
    ) -> c.ProposalRecord:
        if not isinstance(intent, c.SubActivityCreateIntent):
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
        activity = scope.activity
        if activity is None:
            raise LiveWriteError("activity_not_found")
        if activity.activity_type != "large":
            raise LiveWriteError("sub_activity_requires_large")
        state = await self.read_activity_management_state(access_token, intent.activity_id)
        if state.is_deleted:
            raise LiveWriteError("activity_not_found")
        if not any(
            unit.unit_type == "root" and not unit.is_deleted
            for unit in scope.ledger_units
        ):
            raise LiveWriteError("sub_activity_root_missing")
        names = {
            item.participant_id: item.name
            for item in scope.participants if not item.is_deleted
        }
        if any(pid not in names for pid in intent.participant_ids):
            raise LiveWriteError("sub_activity_participant_invalid")
        if any(
            unit.name == intent.name and not unit.is_deleted
            for unit in scope.ledger_units
        ):
            raise LiveWriteError("sub_activity_name_conflict")
        participant_names = [names[pid] for pid in intent.participant_ids]
        preview = c.ManagementPreview(
            kind="management",
            operation="subactivity.create",
            activity_id=intent.activity_id,
            activity_name=state.name,
            sub_activity_name=intent.name,
            participant_names=participant_names,
            summary=(
                f"{summary_prefix}建子活动「{intent.name}」（活动「{state.name}」）"
                f"；参与人 {'、'.join(participant_names)}"
            ),
            generated_at=instant,
            simulation=False,
        )
        command = c.FixedSubActivityCreateCommand(
            operation="subactivity.create",
            activity_id=intent.activity_id,
            name=intent.name,
            participant_ids=list(intent.participant_ids),
            expected_financial_version=str(activity.financial_version),
            expected_activity_type=activity.activity_type,
            expected_activity_archived=state.archived,
        )
        return self._management_proposal(
            owner_user_id=owner_user_id, session_id=session_id, turn_id=turn_id,
            operation="subactivity.create", intent=intent, command=command, preview=preview,
            activity_id=intent.activity_id, expense_version=None,
            agent_disable_revision=agent_disable_revision,
            policy_version=policy_version, now=instant,
            financial_version=str(activity.financial_version),
        )

    async def build_sub_activity_delete_preview(
        self, **kwargs: Any,
    ) -> c.ProposalRecord:
        return await self._build_sub_activity_lifecycle_preview(
            is_restore=False, **kwargs,
        )

    async def build_sub_activity_restore_preview(
        self, **kwargs: Any,
    ) -> c.ProposalRecord:
        return await self._build_sub_activity_lifecycle_preview(
            is_restore=True, **kwargs,
        )

    async def _build_sub_activity_lifecycle_preview(
        self,
        *,
        is_restore: bool,
        owner_user_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        intent: Any,
        access_token: str,
        expires_at: datetime,
        agent_disable_revision: int,
        policy_version: str | None = None,
        summary_prefix: str = "",
        now: datetime | None = None,
    ) -> c.ProposalRecord:
        expected = c.SubActivityRestoreIntent if is_restore else c.SubActivityDeleteIntent
        if not isinstance(intent, expected):
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
        activity = scope.activity
        if activity is None:
            raise LiveWriteError("activity_not_found")
        state = await self.read_activity_management_state(access_token, intent.activity_id)
        if state.is_deleted:
            raise LiveWriteError("activity_not_found")
        unit = await self.read_ledger_unit_state(access_token, intent.sub_activity_id)
        if unit.activity_id != intent.activity_id:
            raise LiveWriteError("sub_activity_not_found")
        if unit.unit_type != "sub_activity":
            raise LiveWriteError("not_a_sub_activity")
        verb = "恢复" if is_restore else "删除"
        operation = "subactivity.restore" if is_restore else "subactivity.delete"
        preview = c.ManagementPreview(
            kind="management",
            operation=operation,
            activity_id=intent.activity_id,
            activity_name=state.name,
            sub_activity_id=unit.ledger_unit_id,
            sub_activity_name=unit.name,
            summary=(
                f"{summary_prefix}{verb}子活动「{unit.name}」（活动「{state.name}」）"
                f"；当前{'已删除' if unit.is_deleted else '未删除'}"
            ),
            generated_at=instant,
            simulation=False,
        )
        command_type = (
            c.FixedSubActivityRestoreCommand if is_restore
            else c.FixedSubActivityDeleteCommand
        )
        command = command_type(
            operation=operation,
            activity_id=intent.activity_id,
            sub_activity_id=unit.ledger_unit_id,
            expected_financial_version=str(activity.financial_version),
            expected_is_deleted=unit.is_deleted,
            expected_activity_type=activity.activity_type,
            expected_activity_archived=state.archived,
        )
        return self._management_proposal(
            owner_user_id=owner_user_id, session_id=session_id, turn_id=turn_id,
            operation=operation, intent=intent, command=command, preview=preview,
            activity_id=intent.activity_id, expense_version=None,
            agent_disable_revision=agent_disable_revision,
            policy_version=policy_version, now=instant,
            financial_version=str(activity.financial_version),
        )

    # ------------------------------- Creator-only administration previews (P5.8c)

    async def _activity_admin_state(
        self,
        owner_user_id: uuid.UUID,
        activity_id: uuid.UUID,
        grant: Any,
        access_token: str,
    ) -> LiveActivityManagementState:
        await self._read_backend.resolve_scope(
            grant, ScopeRequest(mode="activity", ui_activity_id_hint=activity_id),
        )
        state = await self.read_activity_management_state(access_token, activity_id)
        if state.is_deleted:
            raise LiveWriteError("activity_not_found")
        if state.created_by != owner_user_id:
            raise LiveWriteError("creator_permission_required")
        return state

    async def build_activity_member_remove_preview(
        self,
        *,
        owner_user_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        intent: c.ActivityMemberRemoveIntent,
        access_token: str,
        expires_at: datetime,
        agent_disable_revision: int,
        policy_version: str | None = None,
        summary_prefix: str = "",
        now: datetime | None = None,
    ) -> c.ProposalRecord:
        if not isinstance(intent, c.ActivityMemberRemoveIntent):
            raise LiveWriteError("unsupported_operation")
        instant = _aware(now)
        grant = _activity_grant(
            owner_user_id=owner_user_id, turn_id=turn_id,
            access_token=access_token, expires_at=expires_at,
            activity_id=intent.activity_id,
        )
        state = await self._activity_admin_state(
            owner_user_id, intent.activity_id, grant, access_token,
        )
        if state.archived:
            raise LiveWriteError("activity_archived")
        if intent.user_id == owner_user_id:
            raise LiveWriteError("cannot_remove_self")
        members = await self.list_activity_members(access_token, intent.activity_id)
        if intent.user_id not in members:
            raise LiveWriteError("member_not_found")
        claims = await self.list_activity_claims(access_token, intent.activity_id)
        claim = next(
            (item for item in claims if item.user_id == intent.user_id), None,
        )
        participant = None
        if claim is not None:
            participant = await self.read_participant_state(access_token, claim.participant_id)
        user_ref = _mask_user(intent.user_id)
        label = participant.name if participant is not None else "未认领参与人"
        preview = c.ManagementPreview(
            kind="management",
            operation="activity.member.remove",
            activity_id=intent.activity_id,
            activity_name=state.name,
            participant_id=claim.participant_id if claim is not None else None,
            participant_name=participant.name if participant is not None else None,
            target_user_ref=user_ref,
            summary=(
                f"{summary_prefix}移除成员「{label}」（用户 {user_ref}）；"
                "仅撤销访问，不删除参与人与历史账务"
            ),
            generated_at=instant,
            simulation=False,
        )
        command = c.FixedActivityMemberRemoveCommand(
            operation="activity.member.remove",
            activity_id=intent.activity_id,
            user_id=intent.user_id,
            expected_creator_user_id=state.created_by,
            expected_archived=state.archived,
            expected_members_digest=_membership_digest(members),
        )
        return self._management_proposal(
            owner_user_id=owner_user_id, session_id=session_id, turn_id=turn_id,
            operation="activity.member.remove", intent=intent,
            command=command, preview=preview,
            activity_id=intent.activity_id, expense_version=None,
            agent_disable_revision=agent_disable_revision,
            policy_version=policy_version, now=instant,
        )

    async def build_activity_creator_transfer_preview(
        self,
        *,
        owner_user_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        intent: c.ActivityCreatorTransferIntent,
        access_token: str,
        expires_at: datetime,
        agent_disable_revision: int,
        policy_version: str | None = None,
        summary_prefix: str = "",
        now: datetime | None = None,
    ) -> c.ProposalRecord:
        if not isinstance(intent, c.ActivityCreatorTransferIntent):
            raise LiveWriteError("unsupported_operation")
        instant = _aware(now)
        grant = _activity_grant(
            owner_user_id=owner_user_id, turn_id=turn_id,
            access_token=access_token, expires_at=expires_at,
            activity_id=intent.activity_id,
        )
        state = await self._activity_admin_state(
            owner_user_id, intent.activity_id, grant, access_token,
        )
        if state.archived:
            raise LiveWriteError("activity_archived")
        if intent.new_creator_user_id == owner_user_id:
            raise LiveWriteError("cannot_transfer_to_self")
        members = await self.list_activity_members(access_token, intent.activity_id)
        if intent.new_creator_user_id not in members:
            raise LiveWriteError("new_creator_not_member")
        claims = await self.list_activity_claims(access_token, intent.activity_id)
        claim = next(
            (item for item in claims if item.user_id == intent.new_creator_user_id), None,
        )
        participant = None
        if claim is not None:
            participant = await self.read_participant_state(access_token, claim.participant_id)
        user_ref = _mask_user(intent.new_creator_user_id)
        label = participant.name if participant is not None else "未认领参与人"
        preview = c.ManagementPreview(
            kind="management",
            operation="activity.creator.transfer",
            activity_id=intent.activity_id,
            activity_name=state.name,
            participant_id=claim.participant_id if claim is not None else None,
            participant_name=participant.name if participant is not None else None,
            target_user_ref=user_ref,
            summary=(
                f"{summary_prefix}转移创建者给「{label}」（用户 {user_ref}）"
                f"；当前创建者 {_mask_user(owner_user_id)}"
            ),
            generated_at=instant,
            simulation=False,
        )
        command = c.FixedActivityCreatorTransferCommand(
            operation="activity.creator.transfer",
            activity_id=intent.activity_id,
            new_creator_user_id=intent.new_creator_user_id,
            expected_creator_user_id=state.created_by,
            expected_archived=state.archived,
            expected_members_digest=_membership_digest(members),
        )
        return self._management_proposal(
            owner_user_id=owner_user_id, session_id=session_id, turn_id=turn_id,
            operation="activity.creator.transfer", intent=intent,
            command=command, preview=preview,
            activity_id=intent.activity_id, expense_version=None,
            agent_disable_revision=agent_disable_revision,
            policy_version=policy_version, now=instant,
        )

    async def build_activity_archive_preview(self, **kwargs: Any) -> c.ProposalRecord:
        return await self._build_activity_archive_preview(is_unarchive=False, **kwargs)

    async def build_activity_unarchive_preview(self, **kwargs: Any) -> c.ProposalRecord:
        return await self._build_activity_archive_preview(is_unarchive=True, **kwargs)

    async def _build_activity_archive_preview(
        self,
        *,
        is_unarchive: bool,
        owner_user_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        intent: Any,
        access_token: str,
        expires_at: datetime,
        agent_disable_revision: int,
        policy_version: str | None = None,
        summary_prefix: str = "",
        now: datetime | None = None,
    ) -> c.ProposalRecord:
        expected = c.ActivityUnarchiveIntent if is_unarchive else c.ActivityArchiveIntent
        if not isinstance(intent, expected):
            raise LiveWriteError("unsupported_operation")
        instant = _aware(now)
        grant = _activity_grant(
            owner_user_id=owner_user_id, turn_id=turn_id,
            access_token=access_token, expires_at=expires_at,
            activity_id=intent.activity_id,
        )
        state = await self._activity_admin_state(
            owner_user_id, intent.activity_id, grant, access_token,
        )
        status_row = await self.read_activity_financial_status(
            access_token, intent.activity_id,
        )
        debt = _num_text(status_row.get("total_debt"))
        prepayment = _num_text(status_row.get("total_prepayment"))
        unsettled = _bool(status_row.get("has_unsettled_debt"))
        verb = "取消归档" if is_unarchive else "归档"
        operation = "activity.unarchive" if is_unarchive else "activity.archive"
        warning = (
            "活动仍有未结清债务或预存余额" if unsettled else "无未结清债务与预存余额"
        )
        preview = c.ManagementPreview(
            kind="management",
            operation=operation,
            activity_id=intent.activity_id,
            activity_name=state.name,
            unsettled=unsettled,
            financial_summary=f"债务 {debt} / 预存 {prepayment}",
            summary=(
                f"{summary_prefix}{verb}活动「{state.name}」；"
                f"未结清摘要：债务 {debt} / 预存 {prepayment}；{warning}"
            ),
            generated_at=instant,
            simulation=False,
        )
        command_type = (
            c.FixedActivityUnarchiveCommand if is_unarchive
            else c.FixedActivityArchiveCommand
        )
        command = command_type(
            operation=operation,
            activity_id=intent.activity_id,
            expected_creator_user_id=state.created_by,
            expected_archived=state.archived,
        )
        return self._management_proposal(
            owner_user_id=owner_user_id, session_id=session_id, turn_id=turn_id,
            operation=operation, intent=intent,
            command=command, preview=preview,
            activity_id=intent.activity_id, expense_version=None,
            agent_disable_revision=agent_disable_revision,
            policy_version=policy_version, now=instant,
        )

    async def build_activity_delete_preview(
        self,
        *,
        owner_user_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        intent: c.ActivityDeleteIntent,
        access_token: str,
        expires_at: datetime,
        agent_disable_revision: int,
        policy_version: str | None = None,
        summary_prefix: str = "",
        now: datetime | None = None,
    ) -> c.ProposalRecord:
        if not isinstance(intent, c.ActivityDeleteIntent):
            raise LiveWriteError("unsupported_operation")
        instant = _aware(now)
        grant = _activity_grant(
            owner_user_id=owner_user_id, turn_id=turn_id,
            access_token=access_token, expires_at=expires_at,
            activity_id=intent.activity_id,
        )
        state = await self._activity_admin_state(
            owner_user_id, intent.activity_id, grant, access_token,
        )
        if state.archived:
            raise LiveWriteError("activity_archived")
        preview = c.ManagementPreview(
            kind="management",
            operation="activity.delete",
            activity_id=intent.activity_id,
            activity_name=state.name,
            summary=(
                f"{summary_prefix}删除活动「{state.name}」；"
                "仅在未归档时可删除，删除后无法恢复"
            ),
            generated_at=instant,
            simulation=False,
        )
        command = c.FixedActivityDeleteCommand(
            operation="activity.delete",
            activity_id=intent.activity_id,
            expected_creator_user_id=state.created_by,
            expected_archived=state.archived,
            expected_is_deleted=state.is_deleted,
        )
        return self._management_proposal(
            owner_user_id=owner_user_id, session_id=session_id, turn_id=turn_id,
            operation="activity.delete", intent=intent,
            command=command, preview=preview,
            activity_id=intent.activity_id, expense_version=None,
            agent_disable_revision=agent_disable_revision,
            policy_version=policy_version, now=instant,
        )

    def _management_proposal(
        self,
        *,
        owner_user_id: uuid.UUID,
        session_id: uuid.UUID,
        turn_id: uuid.UUID,
        operation: str,
        intent: Any,
        command: Any,
        preview: c.ManagementPreview,
        activity_id: uuid.UUID | None,
        expense_version: str | None,
        agent_disable_revision: int,
        policy_version: str | None,
        now: datetime,
        financial_version: str | None = None,
    ) -> c.ProposalRecord:
        policy = policy_version or self._config.policy_version
        preconditions = c.PreconditionSnapshot(
            activity_id=activity_id,
            permission_checked=True,
            agent_disable_revision=agent_disable_revision,
            activity_financial_version=financial_version,
            expense_version=expense_version,
            policy_version=policy,
            verified_at=now,
        )
        digest = c.canonical_command_digest(command, preconditions, policy_version=policy)
        return c.ProposalRecord(
            proposal_id=uuid.uuid4(),
            owner_user_id=owner_user_id,
            session_id=session_id,
            turn_id=turn_id,
            revision=1,
            operation=operation,
            mode="backend",
            status=c.ProposalStatus.PENDING,
            intent=intent,
            canonical_command=command,
            preview=preview,
            preconditions=preconditions,
            command_digest=digest,
            confirmation_nonce=_new_nonce(),
            policy_version=policy,
            expires_at=now.replace(microsecond=0) + timedelta(minutes=10),
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
            c.FixedFinalSettlementCommand,
            c.FixedExpenseRefundCommand,
            c.FixedNegativeAdjustmentCommand,
            c.FixedActivityCreateCommand,
            c.FixedActivityJoinCommand,
            c.FixedParticipantCreateCommand,
            c.FixedParticipantDeleteCommand,
            c.FixedParticipantClaimCommand,
            c.FixedParticipantUnclaimCommand,
            c.FixedSubActivityCreateCommand,
            c.FixedSubActivityDeleteCommand,
            c.FixedSubActivityRestoreCommand,
            c.FixedActivityMemberRemoveCommand,
            c.FixedActivityCreatorTransferCommand,
            c.FixedActivityArchiveCommand,
            c.FixedActivityUnarchiveCommand,
            c.FixedActivityDeleteCommand,
        )):
            return await self._close(
                principal, proposal,
                code="unsupported_operation",
                summary="P5 executes expense, transfer and management writes only",
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
        is_final_settlement = isinstance(command, c.FixedFinalSettlementCommand)
        is_refund = isinstance(command, c.FixedExpenseRefundCommand)
        is_negative_adjustment = isinstance(command, c.FixedNegativeAdjustmentCommand)
        is_activity_create = isinstance(command, c.FixedActivityCreateCommand)
        is_activity_join = isinstance(command, c.FixedActivityJoinCommand)
        is_participant_create = isinstance(command, c.FixedParticipantCreateCommand)
        is_participant_delete = isinstance(command, c.FixedParticipantDeleteCommand)
        is_claim = isinstance(command, c.FixedParticipantClaimCommand)
        is_unclaim = isinstance(command, c.FixedParticipantUnclaimCommand)
        is_sub_activity_create = isinstance(command, c.FixedSubActivityCreateCommand)
        is_sub_activity_lifecycle = isinstance(command, (
            c.FixedSubActivityDeleteCommand, c.FixedSubActivityRestoreCommand,
        ))
        is_member_remove = isinstance(command, c.FixedActivityMemberRemoveCommand)
        is_creator_transfer = isinstance(command, c.FixedActivityCreatorTransferCommand)
        is_activity_archive = isinstance(command, c.FixedActivityArchiveCommand)
        is_activity_unarchive = isinstance(command, c.FixedActivityUnarchiveCommand)
        is_activity_delete = isinstance(command, c.FixedActivityDeleteCommand)
        is_activity_admin = (
            is_member_remove or is_creator_transfer or is_activity_archive
            or is_activity_unarchive or is_activity_delete
        )
        # Account-level management operations have no Activity to grant.
        grant = None
        command_activity_id = getattr(command, "activity_id", None)
        if command_activity_id is not None:
            grant = _activity_grant(
                owner_user_id=principal.user_id, turn_id=proposal.turn_id,
                access_token=access_token, expires_at=_grant_expiry(principal),
                activity_id=command_activity_id,
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
            elif is_final_settlement:
                # The plan itself is re-validated by the RPC. The Agent re-checks
                # the Activity version, the Activity type the plan was built for,
                # and that both parties are still active.
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
                if scope.activity.activity_type != command.expected_activity_type:
                    raise LiveWriteError("activity_type_changed")
                active = {
                    item.participant_id for item in scope.participants if not item.is_deleted
                }
                if (
                    command.from_participant_id not in active
                    or command.to_participant_id not in active
                ):
                    raise LiveWriteError("final_settlement_participant_invalid")
            elif is_refund:
                # A linked refund is a negative Expense. Everything it inherits
                # (currency, FX, cap) comes from a fresh server read.
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
                try:
                    state = await self.read_expense_state(
                        access_token, command.original_expense_id,
                    )
                except LiveWriteError as exc:
                    if exc.code != "expense_not_found":
                        raise
                    raise LiveWriteError("refund_original_not_found") from None
                if state.is_deleted or state.original_expense_id is not None:
                    raise LiveWriteError("refund_original_invalid")
                if state.version != int(command.expected_original_version):
                    raise LiveWriteError("refund_source_changed")
                if state.financial_locked != command.expected_original_financial_locked:
                    raise LiveWriteError("refund_source_changed")
                if state.original_currency != command.currency:
                    raise LiveWriteError("refund_currency_mismatch")
                if state.ledger_unit_id != command.ledger_unit_id:
                    raise LiveWriteError("refund_source_changed")
                try:
                    original_amount = Decimal(state.original_amount)
                except (InvalidOperation, ValueError):
                    raise LiveWriteError("upstream_invalid_response") from None
                if original_amount <= 0:
                    raise LiveWriteError("refund_original_invalid")
                if original_amount != Decimal(command.expected_original_amount):
                    raise LiveWriteError("refund_source_changed")
                refunded = await self.read_refunded_amount(
                    access_token, command.original_expense_id,
                )
                if refunded != Decimal(command.expected_refunded_amount):
                    raise LiveWriteError("refund_source_changed")
                if refunded + Decimal(command.amount) > original_amount:
                    raise LiveWriteError("refund_exceeds_remaining")
            elif is_negative_adjustment:
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
                _require_writable_activity(scope, original_currency=command.currency)
            elif is_activity_create:
                # Nothing about the Activity exists yet, so there is nothing to
                # re-read; the server fixes the creator from the caller identity.
                pass
            elif is_activity_join:
                existing = await self.read_activity_by_join_code(
                    access_token, command.join_code,
                )
                if existing is not None and (existing.archived or existing.is_deleted):
                    raise LiveWriteError("join_code_inactive")
            elif is_participant_create:
                await self._read_backend.resolve_scope(
                    grant,
                    ScopeRequest(mode="activity", ui_activity_id_hint=command.activity_id),
                )
                state = await self.read_activity_management_state(
                    access_token, command.activity_id,
                )
                if state.is_deleted:
                    raise LiveWriteError("activity_not_found")
                if (
                    state.archived != command.expected_activity_archived
                    or state.participants_locked != command.expected_participants_locked
                ):
                    raise LiveWriteError("management_state_changed")
                participants = await self.list_participants(
                    access_token, command.activity_id,
                )
                if any(item.name == command.name for item in participants):
                    raise LiveWriteError("participant_name_conflict")
            elif is_participant_delete:
                await self._read_backend.resolve_scope(
                    grant,
                    ScopeRequest(mode="activity", ui_activity_id_hint=command.activity_id),
                )
                state = await self.read_activity_management_state(
                    access_token, command.activity_id,
                )
                if (
                    state.is_deleted != command.expected_activity_deleted
                    or state.archived != command.expected_activity_archived
                    or state.participants_locked != command.expected_participants_locked
                ):
                    raise LiveWriteError("management_state_changed")
                participant = await self.read_participant_state(
                    access_token, command.participant_id,
                )
                if (
                    participant.activity_id != command.activity_id
                    or participant.name != command.expected_participant_name
                    or participant.is_deleted != command.expected_participant_deleted
                ):
                    raise LiveWriteError("management_state_changed")
                if await self.read_participant_usage(
                    access_token, command.participant_id,
                ):
                    raise LiveWriteError("participant_claimed_or_used")
            elif is_claim or is_unclaim:
                await self._read_backend.verify_financial_versions(
                    grant, {command.activity_id: int(command.expected_financial_version)},
                )
                state = await self.read_activity_management_state(
                    access_token, command.activity_id,
                )
                if state.is_deleted:
                    raise LiveWriteError("activity_not_found")
                if state.archived != command.expected_activity_archived:
                    raise LiveWriteError("management_state_changed")
                claims = await self.list_activity_claims(
                    access_token, command.activity_id,
                )
                mine = next(
                    (item for item in claims if item.user_id == principal.user_id), None,
                )
                if is_claim:
                    participant = await self.read_participant_state(
                        access_token, command.participant_id,
                    )
                    if (
                        participant.activity_id != command.activity_id
                        or participant.is_deleted
                    ):
                        raise LiveWriteError("participant_not_found")
                    target = next(
                        (item for item in claims
                         if item.participant_id == command.participant_id), None,
                    )
                    if target is not None and target.user_id != principal.user_id:
                        raise LiveWriteError("participant_claimed_by_other")
                    if mine is not None and mine.participant_id != command.participant_id:
                        raise LiveWriteError("actor_already_claimed_other")
                    current = "mine" if mine is not None else "none"
                    if current != command.expected_claim_state:
                        raise LiveWriteError("claim_state_changed")
                else:
                    if (
                        mine is None
                        or mine.participant_id != command.expected_claim_participant_id
                    ):
                        raise LiveWriteError("claim_state_changed")
            elif is_sub_activity_create:
                await self._read_backend.verify_financial_versions(
                    grant, {command.activity_id: int(command.expected_financial_version)},
                )
                scope = await self._read_backend.resolve_scope(
                    grant, ScopeRequest(mode="activity", ui_activity_id_hint=command.activity_id),
                )
                activity = scope.activity
                if activity is None:
                    raise LiveWriteError("activity_not_found")
                if activity.activity_type != command.expected_activity_type:
                    raise LiveWriteError("sub_activity_state_changed")
                if activity.activity_type != "large":
                    raise LiveWriteError("sub_activity_requires_large")
                state = await self.read_activity_management_state(
                    access_token, command.activity_id,
                )
                if state.is_deleted:
                    raise LiveWriteError("activity_not_found")
                if state.archived != command.expected_activity_archived:
                    raise LiveWriteError("sub_activity_state_changed")
                if not any(
                    unit.unit_type == "root" and not unit.is_deleted
                    for unit in scope.ledger_units
                ):
                    raise LiveWriteError("sub_activity_root_missing")
                active = {
                    item.participant_id for item in scope.participants if not item.is_deleted
                }
                if any(pid not in active for pid in command.participant_ids):
                    raise LiveWriteError("sub_activity_participant_invalid")
                if any(
                    unit.name == command.name and not unit.is_deleted
                    for unit in scope.ledger_units
                ):
                    raise LiveWriteError("sub_activity_name_conflict")
            elif is_sub_activity_lifecycle:
                await self._read_backend.verify_financial_versions(
                    grant, {command.activity_id: int(command.expected_financial_version)},
                )
                scope = await self._read_backend.resolve_scope(
                    grant, ScopeRequest(mode="activity", ui_activity_id_hint=command.activity_id),
                )
                activity = scope.activity
                if activity is None:
                    raise LiveWriteError("activity_not_found")
                if activity.activity_type != command.expected_activity_type:
                    raise LiveWriteError("sub_activity_state_changed")
                state = await self.read_activity_management_state(
                    access_token, command.activity_id,
                )
                if state.is_deleted:
                    raise LiveWriteError("activity_not_found")
                if state.archived != command.expected_activity_archived:
                    raise LiveWriteError("sub_activity_state_changed")
                unit = await self.read_ledger_unit_state(
                    access_token, command.sub_activity_id,
                )
                if (
                    unit.activity_id != command.activity_id
                    or unit.unit_type != "sub_activity"
                    or unit.is_deleted != command.expected_is_deleted
                ):
                    raise LiveWriteError("sub_activity_state_changed")
            elif is_activity_admin:
                await self._read_backend.resolve_scope(
                    grant,
                    ScopeRequest(mode="activity", ui_activity_id_hint=command.activity_id),
                )
                state = await self.read_activity_management_state(
                    access_token, command.activity_id,
                )
                if state.is_deleted:
                    raise LiveWriteError("activity_not_found")
                if state.created_by != command.expected_creator_user_id:
                    raise LiveWriteError("creator_changed")
                if principal.user_id != state.created_by:
                    raise LiveWriteError("creator_permission_required")
                if state.archived != command.expected_archived:
                    raise LiveWriteError("activity_state_changed")
                if is_activity_delete and state.is_deleted != command.expected_is_deleted:
                    raise LiveWriteError("activity_state_changed")
                if is_member_remove or is_creator_transfer:
                    members = await self.list_activity_members(
                        access_token, command.activity_id,
                    )
                    if _membership_digest(members) != command.expected_members_digest:
                        raise LiveWriteError("members_changed")
                    if is_member_remove and command.user_id not in members:
                        raise LiveWriteError("member_not_found")
                    if (
                        is_creator_transfer
                        and command.new_creator_user_id not in members
                    ):
                        raise LiveWriteError("new_creator_not_member")
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
                "final_settlement_plan_empty",
                "final_settlement_item_not_in_plan",
                "final_settlement_preview_rejected",
                "final_settlement_invalid",
                "final_settlement_participant_invalid",
                "final_settlement_version_conflict",
                "final_settlement_stale_plan",
                "final_settlement_rejected",
                "activity_type_changed",
                "refund_original_not_found",
                "refund_original_invalid",
                "refund_currency_mismatch",
                "refund_exceeds_remaining",
                "refund_source_changed",
                "refund_source_unavailable",
                "negative_adjustment_invalid",
                "management_invalid",
                "activity_name_conflict",
                "participant_list_locked",
                "participant_name_conflict",
                "participant_claimed_or_used",
                "participant_not_found",
                "join_code_inactive",
                "management_state_changed",
                "activity_created_elsewhere",
                "activity_not_created",
                "joined_elsewhere",
                "join_not_applied",
                "participant_created_elsewhere",
                "participant_not_created",
                "deleted_elsewhere",
                "delete_not_applied",
                "conflict",
                "sub_activity_requires_large",
                "sub_activity_root_missing",
                "sub_activity_name_conflict",
                "sub_activity_participant_invalid",
                "sub_activity_not_found",
                "not_a_sub_activity",
                "sub_activity_state_changed",
                "participant_claimed_by_other",
                "actor_already_claimed_other",
                "claim_state_changed",
                "claim_not_found",
                "participant_claim_conflict",
                "sub_activity_created_elsewhere",
                "sub_activity_not_created",
                "sub_activity_deleted_elsewhere",
                "sub_activity_delete_not_applied",
                "sub_activity_restored_elsewhere",
                "sub_activity_restore_not_applied",
                "claimed_elsewhere",
                "claim_not_applied",
                "released_elsewhere",
                "unclaim_not_applied",
                "creator_permission_required",
                "activity_archived",
                "cannot_remove_self",
                "cannot_transfer_to_self",
                "member_not_found",
                "new_creator_not_member",
                "creator_changed",
                "members_changed",
                "activity_state_changed",
                "member_removed_elsewhere",
                "member_remove_not_applied",
                "creator_transferred_elsewhere",
                "creator_transfer_not_applied",
                "archived_elsewhere",
                "archive_not_applied",
                "unarchived_elsewhere",
                "unarchive_not_applied",
                "activity_deleted_elsewhere",
                "delete_activity_not_applied",
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
        elif isinstance(command, c.FixedFinalSettlementCommand):
            rpc_path = RPC_EXECUTE_FINAL_SETTLEMENT
            payload = _rpc_payload_final_settlement(
                command,
                c.derive_execution_id(
                    principal.user_id, proposal.proposal_id, proposal.revision,
                ),
            )
        elif isinstance(command, c.FixedExpenseRefundCommand):
            rpc_path = RPC_CREATE_EXPENSE
            payload = _rpc_payload_refund(command)
        elif isinstance(command, c.FixedNegativeAdjustmentCommand):
            rpc_path = RPC_CREATE_EXPENSE
            payload = _rpc_payload_negative_adjustment(command)
        elif isinstance(command, c.FixedActivityCreateCommand):
            rpc_path = RPC_CREATE_ACTIVITY
            payload = _rpc_payload_activity_create(command)
        elif isinstance(command, c.FixedActivityJoinCommand):
            rpc_path = RPC_JOIN_ACTIVITY
            payload = {"join_code": command.join_code}
        elif isinstance(command, c.FixedParticipantCreateCommand):
            rpc_path = RPC_CREATE_PARTICIPANT
            payload = _rpc_payload_participant_create(command)
        elif isinstance(command, c.FixedParticipantDeleteCommand):
            rpc_path = RPC_DELETE_PARTICIPANT
            payload = {"participant_id": str(command.participant_id)}
        elif isinstance(command, c.FixedParticipantClaimCommand):
            rpc_path = RPC_CLAIM_PARTICIPANT
            payload = {
                "activity_id": str(command.activity_id),
                "participant_id": str(command.participant_id),
            }
        elif isinstance(command, c.FixedParticipantUnclaimCommand):
            rpc_path = RPC_UNCLAIM_PARTICIPANT
            payload = {"activity_id": str(command.activity_id)}
        elif isinstance(command, c.FixedSubActivityCreateCommand):
            rpc_path = RPC_CREATE_SUB_ACTIVITY
            payload = {
                "activity_id": str(command.activity_id),
                "name": command.name,
                "participant_ids": [str(item) for item in command.participant_ids],
            }
        elif isinstance(command, c.FixedSubActivityDeleteCommand):
            rpc_path = RPC_DELETE_SUB_ACTIVITY
            payload = {"sub_activity_id": str(command.sub_activity_id)}
        elif isinstance(command, c.FixedSubActivityRestoreCommand):
            rpc_path = RPC_RESTORE_SUB_ACTIVITY
            payload = {"sub_activity_id": str(command.sub_activity_id)}
        elif isinstance(command, c.FixedActivityMemberRemoveCommand):
            rpc_path = RPC_REMOVE_MEMBER
            payload = {
                "activity_id": str(command.activity_id),
                "user_id": str(command.user_id),
            }
        elif isinstance(command, c.FixedActivityCreatorTransferCommand):
            rpc_path = RPC_TRANSFER_CREATOR
            payload = {
                "activity_id": str(command.activity_id),
                "new_creator_user_id": str(command.new_creator_user_id),
            }
        elif isinstance(command, c.FixedActivityArchiveCommand):
            rpc_path = RPC_ARCHIVE_ACTIVITY
            payload = {"p_activity_id": str(command.activity_id)}
        elif isinstance(command, c.FixedActivityUnarchiveCommand):
            rpc_path = RPC_UNARCHIVE_ACTIVITY
            payload = {"p_activity_id": str(command.activity_id)}
        elif isinstance(command, c.FixedActivityDeleteCommand):
            rpc_path = RPC_DELETE_ACTIVITY
            payload = {"activity_id": str(command.activity_id)}
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
        if isinstance(command, c.FixedFinalSettlementCommand):
            return await self._reconcile_final_settlement(
                principal, proposal, command, access_token,
            )
        if isinstance(command, c.FixedExpenseRefundCommand):
            return await self._reconcile_refund(
                principal, proposal, command, access_token,
            )
        if isinstance(command, c.FixedNegativeAdjustmentCommand):
            return await self._reconcile_negative_adjustment(
                principal, proposal, command, access_token,
            )
        if isinstance(command, c.FixedActivityCreateCommand):
            return await self._reconcile_activity_create(
                principal, proposal, command, access_token,
            )
        if isinstance(command, c.FixedActivityJoinCommand):
            return await self._reconcile_activity_join(
                principal, proposal, command, access_token,
            )
        if isinstance(command, c.FixedParticipantCreateCommand):
            return await self._reconcile_participant_create(
                principal, proposal, command, access_token,
            )
        if isinstance(command, c.FixedParticipantDeleteCommand):
            return await self._reconcile_participant_delete(
                principal, proposal, command, access_token,
            )
        if isinstance(command, c.FixedParticipantClaimCommand):
            return await self._reconcile_participant_claim(
                principal, proposal, command, access_token,
            )
        if isinstance(command, c.FixedParticipantUnclaimCommand):
            return await self._reconcile_participant_unclaim(
                principal, proposal, command, access_token,
            )
        if isinstance(command, c.FixedSubActivityCreateCommand):
            return await self._reconcile_sub_activity_create(
                principal, proposal, command, access_token,
            )
        if isinstance(command, (
            c.FixedSubActivityDeleteCommand, c.FixedSubActivityRestoreCommand,
        )):
            return await self._reconcile_sub_activity_lifecycle(
                principal, proposal, command, access_token,
            )
        if isinstance(command, c.FixedActivityMemberRemoveCommand):
            return await self._reconcile_member_remove(
                principal, proposal, command, access_token,
            )
        if isinstance(command, c.FixedActivityCreatorTransferCommand):
            return await self._reconcile_creator_transfer(
                principal, proposal, command, access_token,
            )
        if isinstance(command, (
            c.FixedActivityArchiveCommand, c.FixedActivityUnarchiveCommand,
        )):
            return await self._reconcile_activity_archive(
                principal, proposal, command, access_token,
            )
        if isinstance(command, c.FixedActivityDeleteCommand):
            return await self._reconcile_activity_delete(
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

    async def _reconcile_final_settlement(
        self,
        principal: Principal,
        proposal: c.ProposalRecord,
        command: c.FixedFinalSettlementCommand,
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
        if (
            str(row.get("type")) != "final_settlement"
            or not _final_settlement_payload_matches(row.get("request_payload"), command)
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
        required = ("transfer_id", "amount", "currency", "mode", "financial_version")
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("transfer_id"), str)
            or not isinstance(result.get("financial_version"), int)
            or any(key not in result for key in required)
        ):
            return await self._existing_outcome(principal, proposal)
        await _call_store(
            self._store.settle_mock_execution,
            principal.user_id, proposal.proposal_id,
            c.ExecutionResolution.SUCCEEDED,
            result_code="final_settlement_created",
            result_summary=(
                f"transfer_id={result.get('transfer_id')};"
                f"amount={result.get('amount')};currency={result.get('currency')};"
                f"mode={result.get('mode')};"
                f"financial_version={result.get('financial_version')}"
            ),
        )
        return LiveWriteOutcome(
            c.ExecutionResolution.SUCCEEDED, "final_settlement_created",
            "final settlement reconciled by request id",
        )

    async def _reconcile_refund(
        self,
        principal: Principal,
        proposal: c.ProposalRecord,
        command: c.FixedExpenseRefundCommand,
        access_token: str,
    ) -> LiveWriteOutcome:
        """A lost refund response can never be attributed to this execution."""
        turn = (
            await _call_store(self._store.get_turn, principal.user_id, proposal.turn_id)
        ).record.turn
        if turn.state not in (c.TurnState.RECOVERING, c.TurnState.EXECUTING):
            return await self._existing_outcome(principal, proposal)
        try:
            state = await self.read_expense_state(
                access_token, command.original_expense_id,
            )
            refunded = await self.read_refunded_amount(
                access_token, command.original_expense_id,
            )
        except (LiveWriteError, BackendReadError):
            return await self._existing_outcome(principal, proposal)
        if refunded > Decimal(command.expected_refunded_amount):
            code = "refunded_elsewhere"
            summary = "a refund landed but this execution cannot be proven to be its author"
        elif state.version != int(command.expected_original_version):
            code = "refund_source_changed"
            summary = "the original Expense changed while the refund outcome was unresolved"
        else:
            code = "refund_not_applied"
            summary = "no refund is recorded and the original Expense is unchanged"
        await _call_store(
            self._store.settle_mock_execution,
            principal.user_id, proposal.proposal_id,
            c.ExecutionResolution.CLOSED,
            result_code=code,
            result_summary=summary,
        )
        return LiveWriteOutcome(c.ExecutionResolution.CLOSED, code, summary)

    async def _reconcile_negative_adjustment(
        self,
        principal: Principal,
        proposal: c.ProposalRecord,
        command: c.FixedNegativeAdjustmentCommand,
        access_token: str,
    ) -> LiveWriteOutcome:
        turn = (
            await _call_store(self._store.get_turn, principal.user_id, proposal.turn_id)
        ).record.turn
        if turn.state not in (c.TurnState.RECOVERING, c.TurnState.EXECUTING):
            return await self._existing_outcome(principal, proposal)
        grant = _activity_grant(
            owner_user_id=principal.user_id, turn_id=proposal.turn_id,
            access_token=access_token, expires_at=_grant_expiry(principal),
            activity_id=command.activity_id,
        )
        try:
            scope = await self._read_backend.resolve_scope(
                grant, ScopeRequest(mode="activity", ui_activity_id_hint=command.activity_id),
            )
        except (BackendReadError, ScopeDenied):
            return await self._existing_outcome(principal, proposal)
        if (
            scope.activity is None
            or scope.activity.financial_version
            != int(command.expected_financial_version)
        ):
            code = "activity_changed"
            summary = "the Activity changed while the adjustment outcome was unresolved"
        else:
            code = "adjustment_not_applied"
            summary = "no adjustment is recorded and the Activity is unchanged"
        await _call_store(
            self._store.settle_mock_execution,
            principal.user_id, proposal.proposal_id,
            c.ExecutionResolution.CLOSED,
            result_code=code,
            result_summary=summary,
        )
        return LiveWriteOutcome(c.ExecutionResolution.CLOSED, code, summary)

    async def _reconcile_activity_create(
        self,
        principal: Principal,
        proposal: c.ProposalRecord,
        command: c.FixedActivityCreateCommand,
        access_token: str,
    ) -> LiveWriteOutcome:
        turn = (
            await _call_store(self._store.get_turn, principal.user_id, proposal.turn_id)
        ).record.turn
        if turn.state not in (c.TurnState.RECOVERING, c.TurnState.EXECUTING):
            return await self._existing_outcome(principal, proposal)
        try:
            rows = await self.list_activities_by_name(access_token, command.name)
        except (LiveWriteError, BackendReadError):
            return await self._existing_outcome(principal, proposal)
        matches = [
            item for item in rows
            if item.name == command.name
            and item.activity_type == command.activity_type
            and item.base_currency == command.base_currency
            and item.multi_currency_enabled == command.multi_currency_enabled
        ]
        if matches:
            code = "activity_created_elsewhere"
            summary = "an Activity matches but this execution cannot be proven to be its author"
        else:
            code = "activity_not_created"
            summary = "no matching Activity exists"
        await _call_store(
            self._store.settle_mock_execution,
            principal.user_id, proposal.proposal_id,
            c.ExecutionResolution.CLOSED,
            result_code=code,
            result_summary=summary,
        )
        return LiveWriteOutcome(c.ExecutionResolution.CLOSED, code, summary)

    async def _reconcile_activity_join(
        self,
        principal: Principal,
        proposal: c.ProposalRecord,
        command: c.FixedActivityJoinCommand,
        access_token: str,
    ) -> LiveWriteOutcome:
        turn = (
            await _call_store(self._store.get_turn, principal.user_id, proposal.turn_id)
        ).record.turn
        if turn.state not in (c.TurnState.RECOVERING, c.TurnState.EXECUTING):
            return await self._existing_outcome(principal, proposal)
        try:
            existing = await self.read_activity_by_join_code(
                access_token, command.join_code,
            )
        except (LiveWriteError, BackendReadError):
            return await self._existing_outcome(principal, proposal)
        if existing is not None:
            code = "joined_elsewhere"
            summary = "membership exists but this execution cannot be proven to have joined"
        else:
            code = "join_not_applied"
            summary = "no membership is visible for this join code"
        await _call_store(
            self._store.settle_mock_execution,
            principal.user_id, proposal.proposal_id,
            c.ExecutionResolution.CLOSED,
            result_code=code,
            result_summary=summary,
        )
        return LiveWriteOutcome(c.ExecutionResolution.CLOSED, code, summary)

    async def _reconcile_participant_create(
        self,
        principal: Principal,
        proposal: c.ProposalRecord,
        command: c.FixedParticipantCreateCommand,
        access_token: str,
    ) -> LiveWriteOutcome:
        turn = (
            await _call_store(self._store.get_turn, principal.user_id, proposal.turn_id)
        ).record.turn
        if turn.state not in (c.TurnState.RECOVERING, c.TurnState.EXECUTING):
            return await self._existing_outcome(principal, proposal)
        try:
            participants = await self.list_participants(
                access_token, command.activity_id,
            )
        except (LiveWriteError, BackendReadError):
            return await self._existing_outcome(principal, proposal)
        if any(item.name == command.name for item in participants):
            code = "participant_created_elsewhere"
            summary = "a Participant matches but this execution cannot be proven to be its author"
        else:
            code = "participant_not_created"
            summary = "no matching Participant exists"
        await _call_store(
            self._store.settle_mock_execution,
            principal.user_id, proposal.proposal_id,
            c.ExecutionResolution.CLOSED,
            result_code=code,
            result_summary=summary,
        )
        return LiveWriteOutcome(c.ExecutionResolution.CLOSED, code, summary)

    async def _reconcile_participant_delete(
        self,
        principal: Principal,
        proposal: c.ProposalRecord,
        command: c.FixedParticipantDeleteCommand,
        access_token: str,
    ) -> LiveWriteOutcome:
        turn = (
            await _call_store(self._store.get_turn, principal.user_id, proposal.turn_id)
        ).record.turn
        if turn.state not in (c.TurnState.RECOVERING, c.TurnState.EXECUTING):
            return await self._existing_outcome(principal, proposal)
        try:
            participant = await self.read_participant_state(
                access_token, command.participant_id,
            )
        except LiveWriteError as exc:
            if exc.code != "participant_not_found":
                return await self._existing_outcome(principal, proposal)
            participant = None
        except BackendReadError:
            return await self._existing_outcome(principal, proposal)
        if participant is not None and participant.is_deleted:
            code = "deleted_elsewhere"
            summary = "the Participant is deleted but this execution cannot be proven to be the author"
        else:
            code = "delete_not_applied"
            summary = "the Participant is not deleted"
        await _call_store(
            self._store.settle_mock_execution,
            principal.user_id, proposal.proposal_id,
            c.ExecutionResolution.CLOSED,
            result_code=code,
            result_summary=summary,
        )
        return LiveWriteOutcome(c.ExecutionResolution.CLOSED, code, summary)

    async def _reconcile_participant_claim(
        self,
        principal: Principal,
        proposal: c.ProposalRecord,
        command: c.FixedParticipantClaimCommand,
        access_token: str,
    ) -> LiveWriteOutcome:
        turn = (
            await _call_store(self._store.get_turn, principal.user_id, proposal.turn_id)
        ).record.turn
        if turn.state not in (c.TurnState.RECOVERING, c.TurnState.EXECUTING):
            return await self._existing_outcome(principal, proposal)
        try:
            claims = await self.list_activity_claims(access_token, command.activity_id)
        except (LiveWriteError, BackendReadError):
            return await self._existing_outcome(principal, proposal)
        mine = next(
            (item for item in claims if item.user_id == principal.user_id), None,
        )
        if mine is not None:
            code = "claimed_elsewhere"
            summary = "a claim exists but this execution cannot be proven to be its author"
        else:
            code = "claim_not_applied"
            summary = "no claim exists"
        await _call_store(
            self._store.settle_mock_execution,
            principal.user_id, proposal.proposal_id,
            c.ExecutionResolution.CLOSED,
            result_code=code,
            result_summary=summary,
        )
        return LiveWriteOutcome(c.ExecutionResolution.CLOSED, code, summary)

    async def _reconcile_participant_unclaim(
        self,
        principal: Principal,
        proposal: c.ProposalRecord,
        command: c.FixedParticipantUnclaimCommand,
        access_token: str,
    ) -> LiveWriteOutcome:
        turn = (
            await _call_store(self._store.get_turn, principal.user_id, proposal.turn_id)
        ).record.turn
        if turn.state not in (c.TurnState.RECOVERING, c.TurnState.EXECUTING):
            return await self._existing_outcome(principal, proposal)
        try:
            claims = await self.list_activity_claims(access_token, command.activity_id)
        except (LiveWriteError, BackendReadError):
            return await self._existing_outcome(principal, proposal)
        mine = next(
            (item for item in claims if item.user_id == principal.user_id), None,
        )
        if mine is None:
            code = "released_elsewhere"
            summary = "the claim is released but this execution cannot be proven to be the author"
        else:
            code = "unclaim_not_applied"
            summary = "the claim still exists"
        await _call_store(
            self._store.settle_mock_execution,
            principal.user_id, proposal.proposal_id,
            c.ExecutionResolution.CLOSED,
            result_code=code,
            result_summary=summary,
        )
        return LiveWriteOutcome(c.ExecutionResolution.CLOSED, code, summary)

    async def _reconcile_sub_activity_create(
        self,
        principal: Principal,
        proposal: c.ProposalRecord,
        command: c.FixedSubActivityCreateCommand,
        access_token: str,
    ) -> LiveWriteOutcome:
        turn = (
            await _call_store(self._store.get_turn, principal.user_id, proposal.turn_id)
        ).record.turn
        if turn.state not in (c.TurnState.RECOVERING, c.TurnState.EXECUTING):
            return await self._existing_outcome(principal, proposal)
        try:
            units = await self.list_ledger_units(access_token, command.activity_id)
        except (LiveWriteError, BackendReadError):
            return await self._existing_outcome(principal, proposal)
        if any(
            unit.name == command.name and unit.unit_type == "sub_activity"
            and not unit.is_deleted
            for unit in units
        ):
            code = "sub_activity_created_elsewhere"
            summary = "a sub-activity matches but this execution cannot be proven to be its author"
        else:
            code = "sub_activity_not_created"
            summary = "no matching sub-activity exists"
        await _call_store(
            self._store.settle_mock_execution,
            principal.user_id, proposal.proposal_id,
            c.ExecutionResolution.CLOSED,
            result_code=code,
            result_summary=summary,
        )
        return LiveWriteOutcome(c.ExecutionResolution.CLOSED, code, summary)

    async def _reconcile_sub_activity_lifecycle(
        self,
        principal: Principal,
        proposal: c.ProposalRecord,
        command: Any,
        access_token: str,
    ) -> LiveWriteOutcome:
        turn = (
            await _call_store(self._store.get_turn, principal.user_id, proposal.turn_id)
        ).record.turn
        if turn.state not in (c.TurnState.RECOVERING, c.TurnState.EXECUTING):
            return await self._existing_outcome(principal, proposal)
        try:
            unit = await self.read_ledger_unit_state(
                access_token, command.sub_activity_id,
            )
        except LiveWriteError as exc:
            if exc.code != "sub_activity_not_found":
                return await self._existing_outcome(principal, proposal)
            unit = None
        except BackendReadError:
            return await self._existing_outcome(principal, proposal)
        is_delete = isinstance(command, c.FixedSubActivityDeleteCommand)
        if unit is not None and unit.is_deleted:
            code = (
                "sub_activity_deleted_elsewhere" if is_delete
                else "sub_activity_restore_not_applied"
            )
            summary = (
                "the sub-activity is deleted but this execution cannot be proven to be the author"
                if is_delete else "the sub-activity is still deleted"
            )
        elif unit is not None:
            code = (
                "sub_activity_delete_not_applied" if is_delete
                else "sub_activity_restored_elsewhere"
            )
            summary = (
                "the sub-activity is not deleted" if is_delete
                else "the sub-activity is restored but this execution cannot be proven to be the author"
            )
        else:
            code = (
                "sub_activity_delete_not_applied" if is_delete
                else "sub_activity_restore_not_applied"
            )
            summary = "the sub-activity could not be observed"
        await _call_store(
            self._store.settle_mock_execution,
            principal.user_id, proposal.proposal_id,
            c.ExecutionResolution.CLOSED,
            result_code=code,
            result_summary=summary,
        )
        return LiveWriteOutcome(c.ExecutionResolution.CLOSED, code, summary)

    async def _reconcile_member_remove(
        self,
        principal: Principal,
        proposal: c.ProposalRecord,
        command: c.FixedActivityMemberRemoveCommand,
        access_token: str,
    ) -> LiveWriteOutcome:
        turn = (
            await _call_store(self._store.get_turn, principal.user_id, proposal.turn_id)
        ).record.turn
        if turn.state not in (c.TurnState.RECOVERING, c.TurnState.EXECUTING):
            return await self._existing_outcome(principal, proposal)
        try:
            members = await self.list_activity_members(access_token, command.activity_id)
        except (LiveWriteError, BackendReadError):
            return await self._existing_outcome(principal, proposal)
        if command.user_id not in members:
            code = "member_removed_elsewhere"
            summary = "the member is gone but this execution cannot be proven to be the author"
        else:
            code = "member_remove_not_applied"
            summary = "the target is still an Activity member"
        await _call_store(
            self._store.settle_mock_execution,
            principal.user_id, proposal.proposal_id,
            c.ExecutionResolution.CLOSED,
            result_code=code,
            result_summary=summary,
        )
        return LiveWriteOutcome(c.ExecutionResolution.CLOSED, code, summary)

    async def _reconcile_creator_transfer(
        self,
        principal: Principal,
        proposal: c.ProposalRecord,
        command: c.FixedActivityCreatorTransferCommand,
        access_token: str,
    ) -> LiveWriteOutcome:
        turn = (
            await _call_store(self._store.get_turn, principal.user_id, proposal.turn_id)
        ).record.turn
        if turn.state not in (c.TurnState.RECOVERING, c.TurnState.EXECUTING):
            return await self._existing_outcome(principal, proposal)
        try:
            state = await self.read_activity_management_state(
                access_token, command.activity_id,
            )
        except (LiveWriteError, BackendReadError):
            return await self._existing_outcome(principal, proposal)
        if state.created_by is not None and state.created_by != command.expected_creator_user_id:
            code = "creator_transferred_elsewhere"
            summary = "the creator changed but this execution cannot be proven to be the author"
        else:
            code = "creator_transfer_not_applied"
            summary = "the Activity creator is unchanged"
        await _call_store(
            self._store.settle_mock_execution,
            principal.user_id, proposal.proposal_id,
            c.ExecutionResolution.CLOSED,
            result_code=code,
            result_summary=summary,
        )
        return LiveWriteOutcome(c.ExecutionResolution.CLOSED, code, summary)

    async def _reconcile_activity_archive(
        self,
        principal: Principal,
        proposal: c.ProposalRecord,
        command: Any,
        access_token: str,
    ) -> LiveWriteOutcome:
        turn = (
            await _call_store(self._store.get_turn, principal.user_id, proposal.turn_id)
        ).record.turn
        if turn.state not in (c.TurnState.RECOVERING, c.TurnState.EXECUTING):
            return await self._existing_outcome(principal, proposal)
        try:
            state = await self.read_activity_management_state(
                access_token, command.activity_id,
            )
        except (LiveWriteError, BackendReadError):
            return await self._existing_outcome(principal, proposal)
        is_unarchive = isinstance(command, c.FixedActivityUnarchiveCommand)
        if is_unarchive:
            code = "unarchived_elsewhere" if not state.archived else "unarchive_not_applied"
            summary = (
                "the Activity is unarchived but this execution cannot be proven to be the author"
                if not state.archived else "the Activity is still archived"
            )
        else:
            code = "archived_elsewhere" if state.archived else "archive_not_applied"
            summary = (
                "the Activity is archived but this execution cannot be proven to be the author"
                if state.archived else "the Activity is not archived"
            )
        await _call_store(
            self._store.settle_mock_execution,
            principal.user_id, proposal.proposal_id,
            c.ExecutionResolution.CLOSED,
            result_code=code,
            result_summary=summary,
        )
        return LiveWriteOutcome(c.ExecutionResolution.CLOSED, code, summary)

    async def _reconcile_activity_delete(
        self,
        principal: Principal,
        proposal: c.ProposalRecord,
        command: c.FixedActivityDeleteCommand,
        access_token: str,
    ) -> LiveWriteOutcome:
        turn = (
            await _call_store(self._store.get_turn, principal.user_id, proposal.turn_id)
        ).record.turn
        if turn.state not in (c.TurnState.RECOVERING, c.TurnState.EXECUTING):
            return await self._existing_outcome(principal, proposal)
        try:
            state = await self.read_activity_management_state(
                access_token, command.activity_id,
            )
        except (LiveWriteError, BackendReadError):
            return await self._existing_outcome(principal, proposal)
        if state.is_deleted:
            code = "activity_deleted_elsewhere"
            summary = "the Activity is deleted but this execution cannot be proven to be the author"
        else:
            code = "delete_activity_not_applied"
            summary = "the Activity is not deleted"
        await _call_store(
            self._store.settle_mock_execution,
            principal.user_id, proposal.proposal_id,
            c.ExecutionResolution.CLOSED,
            result_code=code,
            result_summary=summary,
        )
        return LiveWriteOutcome(c.ExecutionResolution.CLOSED, code, summary)

    async def _reconcile_void(        self,
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

    async def _settle_management_success(
        self, principal: Principal, proposal: c.ProposalRecord, row: Any, body: bytes,
    ) -> LiveWriteOutcome | None:
        """A 2xx management response must carry the row it claims to have made."""
        record = row if isinstance(row, dict) else {}
        operation = proposal.operation
        if operation == "activity.member.remove":
            removed = _decode_scalar(body)
            if not isinstance(removed, bool):
                return await self._management_invalid_success(principal, proposal)
            code = "member_removed" if removed else "member_already_removed"
            summary = f"removed={str(removed).lower()}"
            text = "member removed" if removed else "the member was already removed"
        elif operation == "activity.creator.transfer":
            new_creator = _decode_scalar(body)
            valid_uuid = False
            if isinstance(new_creator, str):
                try:
                    uuid.UUID(new_creator)
                    valid_uuid = True
                except (ValueError, TypeError):
                    valid_uuid = False
            if not valid_uuid:
                return await self._management_invalid_success(principal, proposal)
            code = "creator_transferred"
            summary = f"new_creator={new_creator}"
            text = "creator transferred"
        elif operation in ("activity.archive", "activity.unarchive"):
            activity_id = record.get("activity_id")
            archived = record.get("archived")
            changed = record.get("changed")
            completed = record.get("completed")
            has_unsettled = record.get("has_unsettled")
            if (
                not isinstance(activity_id, str)
                or not isinstance(archived, bool)
                or not isinstance(changed, bool)
                or not isinstance(completed, bool)
                or not isinstance(has_unsettled, bool)
            ):
                return await self._management_invalid_success(principal, proposal)
            if operation == "activity.archive":
                code = "activity_archived" if changed else "activity_already_archived"
                text = "activity archived" if changed else "activity was already archived"
            else:
                code = "activity_unarchived" if changed else "activity_not_archived"
                text = "activity unarchived" if changed else "activity was not archived"
            warning = record.get("warning")
            summary = (
                f"activity_id={activity_id};changed={str(changed).lower()};"
                f"total_debt={_as_text(record.get('total_debt'))};"
                f"total_prepayment={_as_text(record.get('total_prepayment'))};"
                f"has_unsettled={str(has_unsettled).lower()};"
                f"warning={_as_text(warning) if warning is not None else '-'}"
            )
        elif operation == "activity.delete":
            deleted = _decode_scalar(body)
            if not isinstance(deleted, bool):
                return await self._management_invalid_success(principal, proposal)
            code = "activity_deleted" if deleted else "activity_already_deleted"
            summary = f"deleted={str(deleted).lower()}"
            text = "activity deleted" if deleted else "activity was already deleted"
        elif operation == "participant.unclaim":
            try:
                released = json.loads(body.decode("utf-8")) if body else None
            except (UnicodeDecodeError, json.JSONDecodeError):
                released = None
            if not isinstance(released, bool):
                return await self._management_invalid_success(principal, proposal)
            code = "claim_released" if released else "claim_already_released"
            summary = f"released={str(released).lower()}"
            text = "claim released" if released else "no claim needed releasing"
        elif operation == "participant.claim":
            claim_id = record.get("claim_id")
            claimed_participant_id = record.get("claimed_participant_id")
            is_new = record.get("is_new")
            if (
                not isinstance(claim_id, str)
                or not isinstance(claimed_participant_id, str)
                or not isinstance(is_new, bool)
            ):
                return await self._management_invalid_success(principal, proposal)
            code = "participant_claimed" if is_new else "participant_claim_already_exists"
            summary = (
                f"claim_id={claim_id};participant_id={claimed_participant_id};"
                f"is_new={str(is_new).lower()}"
            )
            text = "participant claimed" if is_new else "claim already existed"
        elif operation == "subactivity.create":
            ledger_unit_id = record.get("ledger_unit_id")
            created_name = record.get("created_name")
            created_type = record.get("created_type")
            if (
                not isinstance(ledger_unit_id, str)
                or not isinstance(created_name, str)
                or created_type != "sub_activity"
            ):
                return await self._management_invalid_success(principal, proposal)
            code = "sub_activity_created"
            summary = f"ledger_unit_id={ledger_unit_id};name={created_name}"
            text = "sub-activity created"
        elif operation in ("subactivity.delete", "subactivity.restore"):
            sub_activity_id = record.get("sub_activity_id")
            changed = record.get("changed")
            is_deleted = record.get("is_deleted")
            financial_version = record.get("financial_version")
            if (
                not isinstance(sub_activity_id, str)
                or not isinstance(changed, bool)
                or not isinstance(is_deleted, bool)
                or not isinstance(financial_version, int)
            ):
                return await self._management_invalid_success(principal, proposal)
            if operation == "subactivity.delete":
                code = "sub_activity_deleted" if changed else "sub_activity_already_deleted"
                text = "sub-activity deleted" if changed else "sub-activity was already deleted"
            else:
                code = "sub_activity_restored" if changed else "sub_activity_not_deleted"
                text = "sub-activity restored" if changed else "sub-activity was not deleted"
            summary = (
                f"ledger_unit_id={sub_activity_id};changed={str(changed).lower()};"
                f"is_deleted={str(is_deleted).lower()};"
                f"financial_version={financial_version}"
            )
        elif operation == "activity.create":
            activity_id = record.get("activity_id")
            join_code = record.get("join_code")
            name = record.get("activity_name")
            activity_type = record.get("activity_type")
            currency = record.get("activity_base_currency")
            multi = record.get("activity_multi_currency_enabled")
            if (
                not isinstance(activity_id, str)
                or not isinstance(join_code, str)
                or len(join_code) != 8
                or not join_code.isdigit()
                or not isinstance(name, str)
                or activity_type not in ("normal", "large")
                or not isinstance(currency, str)
                or not isinstance(multi, bool)
            ):
                return await self._management_invalid_success(principal, proposal)
            code = "activity_created"
            summary = f"activity_id={activity_id};join_code={join_code}"
            text = "activity created"
        elif operation == "activity.join":
            activity_id = record.get("activity_id")
            is_new = record.get("is_new")
            if not isinstance(activity_id, str) or not isinstance(is_new, bool):
                return await self._management_invalid_success(principal, proposal)
            code = "activity_joined" if is_new else "activity_already_member"
            summary = f"activity_id={activity_id};is_new={str(is_new).lower()}"
            text = "activity joined" if is_new else "already a member"
        elif operation == "participant.create":
            participant_id = record.get("participant_id")
            name = record.get("participant_name")
            order = record.get("participant_order")
            if (
                not isinstance(participant_id, str)
                or not isinstance(name, str)
                or not isinstance(order, int)
            ):
                return await self._management_invalid_success(principal, proposal)
            code = "participant_created"
            summary = f"participant_id={participant_id};participant_order={order}"
            text = "participant created"
        else:
            participant_id = record.get("participant_id")
            deleted = record.get("deleted")
            if not isinstance(participant_id, str) or not isinstance(deleted, bool):
                return await self._management_invalid_success(principal, proposal)
            code = "participant_deleted" if deleted else "participant_already_deleted"
            summary = f"participant_id={participant_id};deleted={str(deleted).lower()}"
            text = "participant deleted" if deleted else "participant was already deleted"
        await _call_store(
            self._store.settle_mock_execution,
            principal.user_id, proposal.proposal_id,
            c.ExecutionResolution.SUCCEEDED,
            result_code=code,
            result_summary=summary,
        )
        return LiveWriteOutcome(c.ExecutionResolution.SUCCEEDED, code, text)

    async def _management_invalid_success(
        self, principal: Principal, proposal: c.ProposalRecord,
    ) -> LiveWriteOutcome:
        # A 2xx without the expected row is NOT proof of success.
        await _call_store(
            self._store.mark_execution_unknown,
            principal.user_id, proposal.proposal_id,
        )
        return LiveWriteOutcome(
            c.ExecutionResolution.UNKNOWN, "upstream_invalid_success",
            "write outcome is unresolved",
        )

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
            if proposal.operation == "settlement.final":
                command = proposal.canonical_command
                transfer_id = row.get("transfer_id") if isinstance(row, dict) else None
                amount = row.get("amount") if isinstance(row, dict) else None
                currency = row.get("currency") if isinstance(row, dict) else None
                mode = row.get("mode") if isinstance(row, dict) else None
                financial_version = row.get("financial_version") if isinstance(row, dict) else None
                echoed = (
                    isinstance(command, c.FixedFinalSettlementCommand)
                    and amount is not None and currency is not None and mode is not None
                )
                if echoed:
                    try:
                        echoed = (
                            str(currency) == command.currency
                            and str(mode) == command.mode
                            and Decimal(str(amount)) == Decimal(command.amount)
                        )
                    except (TypeError, ValueError):
                        echoed = False
                if (
                    not isinstance(transfer_id, str)
                    or not isinstance(financial_version, int)
                    or not echoed
                ):
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
                    result_code="final_settlement_created",
                    result_summary=(
                        f"transfer_id={transfer_id};amount={_num_text(amount)};"
                        f"currency={currency};mode={mode};"
                        f"financial_version={financial_version}"
                    ),
                )
                return LiveWriteOutcome(
                    c.ExecutionResolution.SUCCEEDED, "final_settlement_created",
                    "final settlement created",
                )
            if proposal.operation in _MANAGEMENT_OPERATIONS:
                settled = await self._settle_management_success(
                    principal, proposal, row, body,
                )
                if settled is not None:
                    return settled
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
            elif proposal.operation == "expense.refund":
                code = "refund_created"
                summary_text = "refund recorded"
            elif proposal.operation == "expense.negative_adjustment":
                code = "negative_adjustment_created"
                summary_text = "negative adjustment recorded"
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
        if (
            proposal.operation == "settlement.final"
            and raw_code == "40001"
        ):
            # The RPC's version guard fired after dispatch: this is not a win.
            await _call_store(
                self._store.settle_mock_execution,
                principal.user_id, proposal.proposal_id,
                c.ExecutionResolution.CLOSED,
                result_code="final_settlement_version_conflict",
                result_summary="the Activity financial version changed before the RPC",
            )
            return LiveWriteOutcome(
                c.ExecutionResolution.CLOSED, "final_settlement_version_conflict",
                "final settlement version conflict",
            )
        if proposal.operation == "settlement.final":
            message = _raw_error_message(parsed) or ""
            if raw_code == "55000" and "idempotent result" in message:
                await _call_store(
                    self._store.mark_execution_unknown,
                    principal.user_id, proposal.proposal_id,
                )
                return LiveWriteOutcome(
                    c.ExecutionResolution.UNKNOWN, "upstream_ambiguous",
                    "write outcome is unresolved",
                )
            settlement_code = _final_settlement_error_code(status, raw_code, message)
            if settlement_code is not None:
                await _call_store(
                    self._store.settle_mock_execution,
                    principal.user_id, proposal.proposal_id,
                    c.ExecutionResolution.REJECTED,
                    result_code=settlement_code,
                    result_summary="server rejected the final settlement",
                )
                return LiveWriteOutcome(
                    c.ExecutionResolution.REJECTED, settlement_code,
                    "server rejected the final settlement",
                )
        if proposal.operation in _MANAGEMENT_OPERATIONS:
            management_code = _management_error_code(
                proposal.operation, raw_code, _raw_error_message(parsed),
            )
            if management_code is not None:
                await _call_store(
                    self._store.settle_mock_execution,
                    principal.user_id, proposal.proposal_id,
                    c.ExecutionResolution.REJECTED,
                    result_code=management_code,
                    result_summary="server rejected the management write",
                )
                return LiveWriteOutcome(
                    c.ExecutionResolution.REJECTED, management_code,
                    "server rejected the management write",
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


def _rpc_payload_final_settlement(
    command: c.FixedFinalSettlementCommand, request_id: uuid.UUID,
) -> dict[str, Any]:
    return {
        "activity_id": str(command.activity_id),
        "from_participant_id": str(command.from_participant_id),
        "to_participant_id": str(command.to_participant_id),
        "amount": command.amount,
        "currency": command.currency,
        "mode": command.mode,
        "expected_financial_version": int(command.expected_financial_version),
        "request_id": str(request_id),
        "occurred_at": command.occurred_at.isoformat(),
        "on_behalf_of_participant_id": None,
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


def _final_settlement_error_code(
    status: int, raw_code: str | None, message: str | None,
) -> str | None:
    """Map a final settlement RPC failure, or None when unrecognised."""
    if raw_code is None:
        return None
    if raw_code == "23514":
        return (
            "final_settlement_stale_plan"
            if "does not match current plan" in (message or "")
            else "final_settlement_rejected"
        )
    return {
        "22023": "final_settlement_invalid",
        "23505": "request_id_conflict",
        "42501": "actor_not_permitted",
        "P0002": "final_settlement_participant_invalid",
        "40001": "final_settlement_version_conflict",
        "55000": "activity_read_only",
        "28000": "invalid_auth_context",
    }.get(raw_code)


def _final_settlement_payload_matches(
    stored: Any, command: c.FixedFinalSettlementCommand,
) -> bool:
    if not isinstance(stored, dict):
        return False
    if str(stored.get("operation")) != "execute_final_settlement":
        return False
    try:
        return (
            str(stored.get("activity_id")) == str(command.activity_id)
            and str(stored.get("from_participant_id")) == str(command.from_participant_id)
            and str(stored.get("to_participant_id")) == str(command.to_participant_id)
            and Decimal(str(stored.get("amount"))) == Decimal(command.amount)
            and str(stored.get("currency")) == command.currency
            and str(stored.get("mode")) == command.mode
            and stored.get("on_behalf_of_participant_id") in (None, "null")
            and int(stored.get("expected_financial_version"))
            == int(command.expected_financial_version)
        )
    except (TypeError, ValueError):
        return False


def _final_settlement_summary(
    summary_prefix: str,
    participants: Mapping[uuid.UUID, Any],
    plan: Sequence[c.FinalSettlementPlanItem],
    selected: c.FinalSettlementPlanItem,
    mode: str,
) -> str:
    """Render the selected item and the complete plan, item by item."""

    def name(participant_id: uuid.UUID) -> str:
        participant = participants.get(participant_id)
        return participant.name if participant is not None else str(participant_id)

    lines = [
        (
            f"{index}) {name(item.from_participant_id)} -> {name(item.to_participant_id)} "
            f"{item.amount} {item.currency}"
            f"（普通 {item.ordinary_amount} / 预存返还 {item.prepayment_return_amount}）"
        )
        for index, item in enumerate(plan, start=1)
    ]
    head = (
        f"{summary_prefix}结算 {name(selected.from_participant_id)} -> "
        f"{name(selected.to_participant_id)} {selected.amount} {selected.currency}"
        f"（{mode}）；当前完整建议共 {len(plan)} 项："
    )
    return head + "；".join(lines) + "。确认后按已实际发生的付款登记。"


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


def _activity_management_state(row: dict[str, Any]) -> LiveActivityManagementState:
    join_code = row.get("join_code")
    return LiveActivityManagementState(
        activity_id=_uuid(row.get("id")),
        name=str(row.get("name")),
        activity_type=str(row.get("type")),
        base_currency=str(row.get("base_currency")),
        multi_currency_enabled=_bool(row.get("multi_currency_enabled")),
        created_by=_uuid_or_none(row.get("created_by")),
        archived=_parse_timestamp(row.get("archived_at")) is not None,
        is_deleted=_bool(row.get("is_deleted")),
        participants_locked=_parse_timestamp(row.get("participants_locked_at")) is not None,
        join_code=join_code if isinstance(join_code, str) else None,
    )


def _decode_scalar(body: bytes) -> Any:
    """RPCs returning a bare boolean or uuid produce a JSON scalar."""
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _as_text(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bool):
        return str(value).lower()
    if value is None:
        return "-"
    return str(value)


def _membership_digest(member_ids: Sequence[uuid.UUID]) -> str:
    joined = "|".join(sorted(str(item) for item in member_ids))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _mask_user(user_id: uuid.UUID) -> str:
    text = str(user_id)
    return f"{text[:8]}…{text[-4:]}"


def _ledger_unit_state(row: dict[str, Any]) -> LiveLedgerUnitState:
    return LiveLedgerUnitState(
        ledger_unit_id=_uuid(row.get("id")),
        activity_id=_uuid(row.get("activity_id")),
        name=str(row.get("name")),
        unit_type=str(row.get("type")),
        is_deleted=_bool(row.get("is_deleted")),
    )


def _participant_state(row: dict[str, Any]) -> LiveParticipantState:
    return LiveParticipantState(
        participant_id=_uuid(row.get("id")),
        activity_id=_uuid(row.get("activity_id")),
        name=str(row.get("name")),
        participant_order=_int(row.get("participant_order")),
        is_deleted=_bool(row.get("is_deleted")),
    )


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
    return _resolve_expense_ref(intent.expense_ref, references, turn_id)


def _resolve_expense_ref(
    ref: Any,
    references: Sequence[c.BoundReference],
    turn_id: uuid.UUID,
) -> c.BoundExpenseReference:
    for reference in references:
        if (
            isinstance(reference, c.BoundExpenseReference)
            and reference.source_turn_id == turn_id
            and reference.ref == ref
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
    intent: Any,
    references: Sequence[c.BoundReference],
    *,
    turn_id: uuid.UUID,
) -> tuple[uuid.UUID, uuid.UUID, list[c.CanonicalPayment], c.CanonicalSplit]:
    units: dict[str, c.BoundLedgerUnitReference] = {}
    for reference in references:
        if reference.source_turn_id != turn_id:
            continue
        if isinstance(reference, c.BoundLedgerUnitReference):
            units[reference.ref.value] = reference

    unit = units.get(intent.ledger_unit_ref.value)
    if unit is None:
        raise ScopeDenied("ledger unit reference is not bound to this turn")
    activity_id = unit.scope_activity_id
    payments, split = _canonical_children(intent, references, turn_id, activity_id)
    return activity_id, unit.entity_id, payments, split


def _resolve_refund_bindings(
    intent: c.ExpenseRefundIntent,
    references: Sequence[c.BoundReference],
    *,
    turn_id: uuid.UUID,
) -> tuple[uuid.UUID, uuid.UUID, list[c.CanonicalPayment], c.CanonicalSplit]:
    """Bind the refund to its original Expense; the original owns the unit."""
    original = _resolve_expense_ref(intent.original_expense_ref, references, turn_id)
    activity_id = original.scope_activity_id
    payments, split = _canonical_children(intent, references, turn_id, activity_id)
    return activity_id, original.entity_id, payments, split


def _canonical_children(
    intent: Any,
    references: Sequence[c.BoundReference],
    turn_id: uuid.UUID,
    activity_id: uuid.UUID,
) -> tuple[list[c.CanonicalPayment], c.CanonicalSplit]:
    participants: dict[str, c.BoundParticipantReference] = {}
    for reference in references:
        if reference.source_turn_id != turn_id:
            continue
        if isinstance(reference, c.BoundParticipantReference):
            participants[reference.ref.value] = reference

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
    return payments, split


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


def _negate(amount: str) -> str:
    """Turn a positive magnitude into the negative text the RPC expects."""
    try:
        value = Decimal(amount)
    except (InvalidOperation, ValueError):
        raise LiveWriteError("invalid_command") from None
    if value <= 0:
        raise LiveWriteError("invalid_command")
    return format(-value, "f")


def _rpc_payload_activity_create(
    command: c.FixedActivityCreateCommand,
) -> dict[str, Any]:
    # The creator is never sent: the server fixes it from auth.uid().
    return {
        "name": command.name,
        "type": command.activity_type,
        "base_currency": command.base_currency,
        "multi_currency_enabled": command.multi_currency_enabled,
    }


def _rpc_payload_participant_create(
    command: c.FixedParticipantCreateCommand,
) -> dict[str, Any]:
    return {
        "activity_id": str(command.activity_id),
        "name": command.name,
        "participant_order": command.participant_order,
    }


def _management_error_code(
    operation: str, raw_code: str | None, message: str | None = None,
) -> str | None:
    """Map a management RPC failure, or None when the code is unrecognised."""
    if raw_code is None:
        return None
    if raw_code == "22023":
        return "management_invalid"
    if raw_code == "28000":
        return "invalid_auth_context"
    if raw_code == "55000" and "archived activity is read-only" in (message or ""):
        return "activity_read_only"
    if operation in ("activity.member.remove", "activity.creator.transfer",
                     "activity.archive", "activity.unarchive", "activity.delete"):
        if raw_code == "P0002":
            return (
                "member_not_found" if operation == "activity.member.remove"
                else "activity_not_found"
            )
        if raw_code == "42501":
            return "creator_permission_required"
        return None
    if raw_code == "42501":
        return "actor_not_permitted"
    if operation in ("participant.claim", "participant.unclaim"):
        if raw_code == "P0002":
            return "participant_not_found"
        if raw_code == "23505":
            return "participant_claim_conflict"
        if raw_code == "55000":
            return "activity_read_only"
        return None
    if operation in ("subactivity.create", "subactivity.delete", "subactivity.restore"):
        if raw_code == "P0002":
            return "sub_activity_not_found"
        if raw_code == "P0001":
            return "sub_activity_root_missing"
        if raw_code == "23514":
            return "sub_activity_participant_invalid"
        if raw_code == "55000":
            return "activity_read_only"
        return None
    if raw_code == "55000":
        return (
            "participant_list_locked"
            if operation in ("participant.create", "participant.delete")
            else "activity_read_only"
        )
    if raw_code == "P0002":
        return (
            "participant_not_found" if operation == "participant.delete"
            else "activity_not_found"
        )
    if raw_code == "23514":
        return "participant_claimed_or_used"
    if raw_code == "23505":
        return "conflict"
    return None


def _rpc_payload_refund(command: c.FixedExpenseRefundCommand) -> dict[str, Any]:
    return _expense_create_payload(
        ledger_unit_id=command.ledger_unit_id,
        title=command.title,
        amount=command.amount,
        currency=command.currency,
        payment_allocations=command.payment_allocations,
        split=command.split,
        occurred_at=command.occurred_at,
        note=command.note,
        original_expense_id=command.original_expense_id,
    )


def _rpc_payload_negative_adjustment(
    command: c.FixedNegativeAdjustmentCommand,
) -> dict[str, Any]:
    return _expense_create_payload(
        ledger_unit_id=command.ledger_unit_id,
        title=command.title,
        amount=command.amount,
        currency=command.currency,
        payment_allocations=command.payment_allocations,
        split=command.split,
        occurred_at=command.occurred_at,
        note=command.note,
        original_expense_id=None,
    )


def _expense_create_payload(
    *,
    ledger_unit_id: uuid.UUID,
    title: str,
    amount: str,
    currency: str,
    payment_allocations: Sequence[c.CanonicalPayment],
    split: c.CanonicalSplit,
    occurred_at: datetime,
    note: str | None,
    original_expense_id: uuid.UUID | None,
) -> dict[str, Any]:
    """Negative-Expense create payload; every child amount carries the sign."""
    payments = [
        {"participant_id": str(item.participant_id), "amount": _negate(item.amount)}
        for item in payment_allocations
    ]
    if isinstance(split, c.CanonicalEqualSplit):
        split_method = "equal"
        manual_splits: list[dict[str, Any]] = []
        aa_participant_ids = [str(item) for item in split.participant_ids]
    elif isinstance(split, c.CanonicalManualSplit):
        split_method = "manual"
        manual_splits = [
            {"participant_id": str(item.participant_id), "amount": _negate(item.amount)}
            for item in split.allocations
        ]
        aa_participant_ids = []
    else:  # pragma: no cover - the discriminated union makes this unreachable
        raise LiveWriteError("unsupported_split")
    return {
        "ledger_unit_id": str(ledger_unit_id),
        "title": title,
        "original_amount": _negate(amount),
        "original_currency": currency,
        "split_method": split_method,
        "payments": payments,
        "manual_splits": manual_splits,
        "aa_participant_ids": aa_participant_ids,
        "occurred_at": occurred_at.isoformat(),
        "note": note,
        "original_expense_id": (
            str(original_expense_id) if original_expense_id is not None else None
        ),
    }


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
