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
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import urlsplit

from . import contracts as c
from .p2_backend import (
    BackendReadError, BoundRef, P2BackendAdapter, ScopeRequest, VerifiedReadContext,
)
from .ports import ComponentHealth, Principal, ScopeDenied
from .store import (
    ProposalConflict, ProposalExpired, SQLiteAgentStore, StateConflict,
)


P5_POLICY_VERSION = "p5-live-expense-create-v1"
RPC_CREATE_EXPENSE = "/rest/v1/rpc/create_expense_auto_rate"


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


class StdlibWriteTransport:
    """One bounded POST; no redirects, no retries, no connection reuse."""

    def post_json(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
        *,
        timeout: float,
        max_response_bytes: int,
    ) -> tuple[int, bytes]:
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise LiveWriteError("invalid_endpoint")
        if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise LiveWriteError("invalid_endpoint")
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
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
            connection.request("POST", path, body=body, headers=dict(headers))
            response = connection.getresponse()
            content = response.read(max_response_bytes + 1)
            if len(content) > max_response_bytes:
                raise LiveWriteError("upstream_response_too_large", ambiguous=True)
            return int(response.status), content
        except LiveWriteError:
            raise
        except (ConnectionRefusedError, socket.gaierror) as exc:
            # The request never left this process.
            raise LiveWriteError("upstream_unreachable", retryable=True) from exc
        except (TimeoutError, socket.timeout, ConnectionResetError, ssl.SSLError,
                http.client.RemoteDisconnected, http.client.IncompleteRead, OSError) as exc:
            # Once request() started, a timeout or reset cannot tell us whether
            # Postgres committed. Never retry automatically.
            ambiguous = request_sent
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
class LiveWriteOutcome:
    resolution: c.ExecutionResolution
    code: str
    summary: str


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
        if not isinstance(command, c.FixedExpenseCreateCommand):
            return await self._close(
                principal, proposal,
                code="unsupported_operation",
                summary="P5.0 only executes expense.create",
                expected_state_revision=expected_state_revision,
            )
        if proposal.execution is not None:
            return await self._existing_outcome(principal, proposal)
        if proposal.preconditions is None or command.expected_financial_version is None:
            return await self._close(
                principal, proposal,
                code="preview_incomplete",
                summary="preview has no financial-version precondition",
                expected_state_revision=expected_state_revision,
            )
        grant = _activity_grant(
            owner_user_id=principal.user_id, turn_id=proposal.turn_id,
            access_token=access_token, expires_at=_grant_expiry(principal),
            activity_id=command.activity_id,
        )
        try:
            # Re-read the authoritative version immediately before dispatch. A
            # mismatch means some other financial change landed after preview.
            await self._read_backend.verify_financial_versions(
                grant, {command.activity_id: int(command.expected_financial_version)},
            )
            scope = await self._read_backend.resolve_scope(
                grant, ScopeRequest(mode="activity", ui_activity_id_hint=command.activity_id),
            )
            if scope.activity.financial_version != int(command.expected_financial_version):
                raise LiveWriteError("preview_stale")
            _require_writable_activity(scope, original_currency=command.original_currency)
        except LiveWriteError as exc:
            if exc.code in ("foreign_currency_not_in_p5", "preview_stale"):
                return await self._close(
                    principal, proposal,
                    code=exc.code,
                    summary="preview is no longer valid for this Activity",
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

        payload = _rpc_payload(command)
        try:
            status, body = await _call_async(
                self._transport.post_json,
                f"{self._config.project_url.rstrip('/')}{RPC_CREATE_EXPENSE}",
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

        return await self._settle_rpc_response(principal, proposal, status, body)

    # ------------------------------------------------------------------ helpers

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
    ) -> LiveWriteOutcome:
        parsed = _decode_rows(body)
        if 200 <= status < 300:
            row = parsed[0] if parsed else None
            expense_id = row.get("expense_id") if isinstance(row, dict) else None
            version = row.get("version") if isinstance(row, dict) else None
            if not isinstance(expense_id, str) or not isinstance(version, int):
                # A 2xx without the expected row is NOT proof of success.
                await _call_store(self._store.mark_execution_unknown, principal.user_id, proposal.proposal_id)
                return LiveWriteOutcome(c.ExecutionResolution.UNKNOWN, "upstream_invalid_success", "write outcome is unresolved")
            await _call_store(
                self._store.settle_mock_execution,
                principal.user_id, proposal.proposal_id,
                c.ExecutionResolution.SUCCEEDED,
                result_code="expense_created",
                result_summary=f"expense_id={expense_id};version={version}",
            )
            return LiveWriteOutcome(c.ExecutionResolution.SUCCEEDED, "expense_created", "expense created")

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
