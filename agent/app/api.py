"""Frozen P1 `/v1` routes, authenticated at the request boundary."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import math
import re
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import parse_qsl

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter, ValidationError

from .auth import AuthDependencyUnavailable, Unauthenticated
from .components import AppComponents
from .contracts import (
    ApiActionKind, ApiErrorCode, ApiErrorResponse, CancelTurnRequest, CancelTurnResponse,
    ConfirmProposalRequest, ConfirmationUnavailableResponse, CreateSessionRequest,
    EventPollQuery, InactiveProposalCard,
    ListSessionsResponse, PollEventsResponse,
    ProposalEventPayload, ProposalRecord, ProposalStatus, ResumeAuthRequest,
    ResumeClarificationRequest, ResumeProposalAdjustRequest, ResumeState,
    SessionDetailResponse, SessionListQuery,
    SimulationProposalCard, SubmitTurnRequest,
    SubmitTurnAccepted, TurnMutationAccepted, TurnPublicStatus, TurnState, TurnStateSnapshot,
    TurnStep, WaitReason, ConfirmableProposalCard, EventType,
    StatusEventPayload, validate_auth_resume,
)
from .ports import (
    AgentControlSnapshot, AgentDisabled, CapabilityUnavailable, Principal, ScopeDenied,
    ScopeUnavailable,
)
from .p2_backend import BackendReadError
from .store import (
    AdmissionFull, IdempotencyConflict, ProposalConflict, ProposalExpired,
    StateConflict, StoreError, StoreNotFound,
    TurnAggregate, TurnView, EventDraft, _event_digest,
)
from .runtime import RuntimeAuthRequired


T = TypeVar("T")


class _ApiFailure(Exception):
    def __init__(self, status: int, code: ApiErrorCode, message: str, *, retryable: bool = False) -> None:
        self.status = status
        self.code = code
        self.message = message
        self.retryable = retryable


class _RequestRateLimiter:
    """Small bounded in-memory fixed-window limiter for one-worker deployments."""

    def __init__(self, limit_per_minute: int) -> None:
        self._limit = limit_per_minute
        self._lock = threading.Lock()
        self._windows: dict[str, tuple[int, int]] = {}

    def allow(self, key: str, now: float | None = None) -> bool:
        instant = time.monotonic() if now is None else now
        window = int(instant // 60)
        with self._lock:
            current = self._windows.get(key)
            count = current[1] if current is not None and current[0] == window else 0
            if count >= self._limit:
                return False
            if key not in self._windows and len(self._windows) >= 10_000:
                victim = min(self._windows, key=lambda item: (self._windows[item][0], self._windows[item][1]))
                self._windows.pop(victim, None)
            self._windows[key] = (window, count + 1)
            if len(self._windows) > 10_000:
                self._windows = {item: entry for item, entry in self._windows.items() if entry[0] >= window}
            return True


def _error_response(status: int, code: ApiErrorCode, message: str, *, retryable: bool = False) -> JSONResponse:
    body = ApiErrorResponse(code=code, message=message, retryable=retryable)
    return JSONResponse(body.model_dump(mode="json", by_alias=True), status_code=status, headers={"Cache-Control": "no-store"})


def _wire_response(model: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(model.model_dump(mode="json", by_alias=True, exclude_none=False), status_code=status,
                        headers={"Cache-Control": "no-store"})


def _no_constant(value: str) -> Any:
    raise ValueError("non-standard JSON number")


@lru_cache(maxsize=16)
def _contract_adapter(model: type[Any]) -> TypeAdapter[Any]:
    return TypeAdapter(model)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _finite_json(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite_json(item) for item in value.values())
    if isinstance(value, list):
        return all(_finite_json(item) for item in value)
    return True


async def _read_json_object(request: Request, maximum_bytes: int) -> dict[str, Any]:
    content_types = request.headers.getlist("content-type")
    if len(content_types) != 1:
        raise _ApiFailure(400, ApiErrorCode.INVALID_REQUEST, "A single application/json Content-Type is required.")
    media_type = content_types[0].split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise _ApiFailure(400, ApiErrorCode.INVALID_REQUEST, "Content-Type must be application/json.")
    charset_parts = content_types[0].split(";")[1:]
    if any(part.strip().lower() not in ("charset=utf-8", "charset=\"utf-8\"") for part in charset_parts):
        raise _ApiFailure(400, ApiErrorCode.INVALID_REQUEST, "JSON requests must use UTF-8.")
    length_values = request.headers.getlist("content-length")
    if len(length_values) > 1 or (length_values and (not length_values[0].isdigit() or int(length_values[0]) > maximum_bytes)):
        raise _ApiFailure(400, ApiErrorCode.INVALID_REQUEST, "Request payload exceeds the configured byte limit.")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > maximum_bytes:
            raise _ApiFailure(400, ApiErrorCode.INVALID_REQUEST, "Request payload exceeds the configured byte limit.")
        chunks.append(chunk)
    raw = b"".join(chunks)
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_no_constant)
    except (UnicodeError, ValueError, json.JSONDecodeError):
        raise _ApiFailure(400, ApiErrorCode.INVALID_REQUEST, "Request body must be a valid JSON object.") from None
    if not isinstance(document, dict) or not _finite_json(document):
        raise _ApiFailure(400, ApiErrorCode.INVALID_REQUEST, "Request body must be a valid JSON object.")
    return document


async def _request_model(request: Request, model: type[T]) -> T:
    document = await _read_json_object(request, request.app.state.settings.max_request_bytes)
    try:
        return _contract_adapter(model).validate_python(document, from_attributes=True)
    except ValidationError:
        raise _ApiFailure(422, ApiErrorCode.INVALID_REQUEST, "Request body does not match the frozen API contract.") from None


def _parse_query(request: Request, model: type[T]) -> T:
    try:
        pairs = parse_qsl(request.scope.get("query_string", b"").decode("ascii"), keep_blank_values=True, strict_parsing=True)
    except (UnicodeError, ValueError):
        raise _ApiFailure(400, ApiErrorCode.INVALID_REQUEST, "Query parameters are malformed.") from None
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise _ApiFailure(400, ApiErrorCode.INVALID_REQUEST, "Query parameters must not be repeated.")
    allowed = set(model.model_fields)
    if any(key not in allowed for key in keys):
        raise _ApiFailure(400, ApiErrorCode.INVALID_REQUEST, "Query contains an unsupported parameter.")
    values: dict[str, Any] = dict(pairs)
    for key in ("limit", "after_seq"):
        if key in values and (not re.fullmatch(r"(?:0|[1-9][0-9]*)", values[key])):
            raise _ApiFailure(400, ApiErrorCode.INVALID_REQUEST, "Pagination values must be decimal integers.")
        if key in values:
            values[key] = int(values[key])
    try:
        return _contract_adapter(model).validate_python(values, from_attributes=True)
    except ValidationError:
        raise _ApiFailure(422, ApiErrorCode.INVALID_REQUEST, "Query does not match the frozen API contract.") from None


def _require_no_query(request: Request) -> None:
    if request.scope.get("query_string", b""):
        raise _ApiFailure(400, ApiErrorCode.INVALID_REQUEST, "This endpoint does not accept query parameters.")


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError, AttributeError):
        raise _ApiFailure(422, ApiErrorCode.INVALID_REQUEST, "Path identifier must be a UUID.") from None


async def _authenticate(request: Request) -> tuple[AppComponents, Principal]:
    components: AppComponents | None = getattr(request.app.state, "components", None)
    if components is None or components.auth_verifier is None:
        raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE, "Authentication is not configured.", retryable=True)
    if not components.auth_verifier.configured:
        raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE, "Authentication is not configured.", retryable=True)
    values = [value for name, value in request.scope.get("headers", []) if name.lower() == b"authorization"]
    if len(values) != 1:
        raise _ApiFailure(401, ApiErrorCode.UNAUTHENTICATED, "A valid Bearer access token is required.")
    try:
        header = values[0].decode("ascii")
    except UnicodeError:
        raise _ApiFailure(401, ApiErrorCode.UNAUTHENTICATED, "A valid Bearer access token is required.") from None
    match = re.fullmatch(r"Bearer ([A-Za-z0-9._~-]+)", header)
    if match is None:
        raise _ApiFailure(401, ApiErrorCode.UNAUTHENTICATED, "A valid Bearer access token is required.")
    try:
        principal = await asyncio.to_thread(components.auth_verifier.verify_bearer, match.group(1))
    except Unauthenticated:
        raise _ApiFailure(401, ApiErrorCode.UNAUTHENTICATED, "The access token is invalid or no longer active.") from None
    except AuthDependencyUnavailable:
        raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE, "Authentication verification is temporarily unavailable.", retryable=True) from None
    except Exception:
        raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE, "Authentication verification is temporarily unavailable.", retryable=True) from None
    limiter: _RequestRateLimiter = request.app.state.actor_limiter
    if not limiter.allow("actor:" + str(principal.user_id)):
        raise _ApiFailure(429, ApiErrorCode.RATE_LIMITED, "Request rate limit exceeded.", retryable=True)
    request.state.p2_access_token = match.group(1)
    request.state.p2_principal = principal
    bind_grant = getattr(components.runtime, "bind_auth_grant", None)
    bind_turn_grant = getattr(components.runtime, "bind_turn_auth_grant", None)
    if callable(bind_grant) and not callable(bind_turn_grant):
        try:
            bind_grant(principal, match.group(1))
        except Exception:
            # Runtime treats an absent/invalid in-memory grant as auth-required.
            pass
    return components, principal


def _bind_turn_auth_grant(
    request: Request, components: AppComponents, principal: Principal, turn_id: uuid.UUID,
    *, replace: bool = False, existing_only: bool = False,
) -> None:
    bind = getattr(components.runtime, "bind_turn_auth_grant", None)
    if not callable(bind):
        return
    token = getattr(request.state, "p2_access_token", None)
    if not isinstance(token, str) or not token or principal.expires_at is None:
        raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                          "A verified Turn grant could not be retained safely.", retryable=True)
    try:
        bind(principal, turn_id, token, replace=replace, existing_only=existing_only)
    except TypeError:
        # Keep test doubles and older custom Runtime implementations source
        # compatible; the production P2Runtime supports the replacement flag.
        if replace or existing_only:
            raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                              "A verified Turn grant could not be refreshed safely.", retryable=True) from None
        bind(principal, turn_id, token)
    except Exception:
        if existing_only:
            # A replay must return its original durable receipt without issuing
            # a new grant after expiry or restart.
            return
        raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                          "A verified Turn grant could not be retained safely.", retryable=True) from None


async def _store_call(operation: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return await asyncio.to_thread(operation, *args, **kwargs)
    except StoreNotFound:
        raise _ApiFailure(404, ApiErrorCode.NOT_FOUND, "The requested resource was not found.") from None
    except IdempotencyConflict:
        raise _ApiFailure(409, ApiErrorCode.IDEMPOTENCY_CONFLICT, "The request key was already used with different input.") from None
    except AdmissionFull:
        raise _ApiFailure(429, ApiErrorCode.RATE_LIMITED, "Runtime capacity is temporarily full.", retryable=True) from None
    except StateConflict:
        raise _ApiFailure(409, ApiErrorCode.STATE_REVISION_CONFLICT, "The turn state has changed.") from None
    except ProposalExpired:
        raise _ApiFailure(409, ApiErrorCode.PROPOSAL_EXPIRED, "The proposal has expired.") from None
    except ProposalConflict:
        raise _ApiFailure(409, ApiErrorCode.PROPOSAL_REVISION_CONFLICT, "The proposal is no longer current.") from None
    except StoreError:
        raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE, "Durable storage is temporarily unavailable.", retryable=True) from None
    except ValueError:
        raise _ApiFailure(409, ApiErrorCode.STATE_REVISION_CONFLICT, "The requested state or cursor is no longer current.") from None
    except Exception:
        raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE, "The request could not be completed safely.", retryable=True) from None


async def _agent_snapshot(components: AppComponents) -> AgentControlSnapshot:
    if components.agent_control is None:
        raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE, "Agent control is unavailable.", retryable=True)
    try:
        value = await asyncio.to_thread(components.agent_control.snapshot)
        if value.disable_revision < 0:
            raise ValueError("invalid revision")
        return value
    except Exception:
        raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE, "Agent control is unavailable.", retryable=True) from None


async def _require_enabled(components: AppComponents) -> AgentControlSnapshot:
    snapshot = await _agent_snapshot(components)
    if not snapshot.enabled:
        raise _ApiFailure(409, ApiErrorCode.AGENT_DISABLED, "Agent planning is disabled.")
    return snapshot


async def _scope_authorize(
    components: AppComponents, principal: Principal, ids: set[uuid.UUID], action: str,
    *, request: Request | None = None,
) -> None:
    if not ids:
        return
    p2_authorize = getattr(components.backend, "authorize_api_scope", None)
    if callable(p2_authorize):
        token = getattr(request.state, "p2_access_token", None) if request is not None else None
        if not isinstance(token, str) or principal.expires_at is None:
            raise _ApiFailure(401, ApiErrorCode.UNAUTHENTICATED,
                              "The access token must be refreshed before this scope can be checked.")
        try:
            await p2_authorize(
                principal.user_id, tuple(sorted(ids, key=str)), token, principal.expires_at,
            )
            return
        except BackendReadError as exc:
            if exc.code in ("invalid_auth_context", "auth_rejected"):
                raise _ApiFailure(401, ApiErrorCode.UNAUTHENTICATED,
                                  "The access token is invalid or no longer active.") from None
            if exc.code in ("scope_unavailable", "access_denied"):
                raise _ApiFailure(404, ApiErrorCode.NOT_FOUND,
                                  "The requested resource was not found or is not accessible.") from None
            if exc.code == "rate_limited":
                raise _ApiFailure(429, ApiErrorCode.RATE_LIMITED,
                                  "Activity access verification is temporarily rate limited.", retryable=True) from None
            raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                              "Activity access verification is temporarily unavailable.", retryable=True) from None
        except Exception:
            # Never return the adapter's URL, headers, or raw upstream body.
            raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                              "Activity access verification is temporarily unavailable.", retryable=True) from None
    if components.scope_authorizer is None:
        if ids:
            raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE, "Activity access verification is unavailable.", retryable=True)
        return
    try:
        await asyncio.to_thread(components.scope_authorizer.authorize, principal, frozenset(ids), action=action)
    except ScopeDenied:
        raise _ApiFailure(404, ApiErrorCode.NOT_FOUND, "The requested resource was not found.") from None
    except ScopeUnavailable:
        raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE, "Activity access verification is unavailable.", retryable=True) from None


async def _scope_card_visible(components: AppComponents, principal: Principal, ids: set[uuid.UUID], action: str) -> bool:
    # A persisted preview/card must always have a server-resolved activity binding.
    # An empty set means this card cannot establish the scope it would disclose.
    if not ids or components.scope_authorizer is None:
        return False
    try:
        await asyncio.to_thread(components.scope_authorizer.authorize, principal, frozenset(ids), action=action)
        return True
    except (ScopeDenied, ScopeUnavailable):
        return False
    except Exception:
        raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE, "Activity access verification is unavailable.", retryable=True) from None


def _scope_ids_for_turn(aggregate: TurnAggregate, proposals: tuple[ProposalRecord, ...] = ()) -> set[uuid.UUID]:
    ids = {item.scope_activity_id for item in aggregate.record.bound_references}
    ids.update(item.scope_activity_id for item in aggregate.record.bound_evidence_references)
    for proposal in proposals:
        if proposal.preconditions is not None:
            ids.add(proposal.preconditions.activity_id)
        if proposal.canonical_command is not None:
            ids.add(proposal.canonical_command.activity_id)
    return ids


def _safe_scope_free_event(aggregate: TurnAggregate, event: Any, runtime: Any = None) -> bool:
    """Only verified, closed MockRuntime output can be polled without scope."""
    proof = next(
        (item for item in aggregate.checkpoint.event_provenance if item.seq == event.seq),
        None,
    )
    if proof is not None and getattr(event, "simulation", False):
        expected = {
            "conversation_answer": ("message",),
            "policy_answer": ("message",),
            "clarification": ("clarification",),
            "system_error": ("error",),
        }
        if event.type in expected.get(proof.source, ()) and _event_digest(event) == proof.event_sha256:
            return True
    check = getattr(runtime, "safe_scope_free_event", None)
    return bool(check(aggregate, event)) if callable(check) else False


async def _v3_protected_event_activity_ids(
    components: AppComponents, owner_id: uuid.UUID, turn_id: uuid.UUID, event: Any,
) -> tuple[uuid.UUID, ...] | None:
    """Resolve a V3 MESSAGE only through its committed typed sidecar link.

    The returned source IDs are private inputs to a fresh membership check;
    they are never copied into the public v1 event. ``None`` means the event
    is not a V3 protected output, while an empty tuple is valid for a verified
    empty Activity collection.
    """
    if event.type != EventType.MESSAGE:
        return None
    lookup = getattr(components.store, "get_p2_v3_protected_event_activity_ids", None)
    if not callable(lookup):
        return None
    stored = await _store_call(lookup, owner_id, turn_id, event_seq=event.seq)
    if stored is None:
        return None
    try:
        from .p2_read_contracts_v3 import (
            ActivityFact as V3ActivityFact,
            DebtFact as V3DebtFact,
            ExpenseFact as V3ExpenseFact,
            PrepaymentAccountFact as V3PrepaymentAccountFact,
            PrepaymentReturnEventFact as V3PrepaymentReturnEventFact,
            PrepaymentUsageFact as V3PrepaymentUsageFact,
            P2ReadOperation as V3ReadOperation,
            P2_V3_CANDIDATE_PROFILE_ID as V3_PROFILE_ID,
            RefundEventFact as V3RefundEventFact,
        )
        from .p2_event_contracts_v3 import P2V3HistoricalAnswer

        if (
            type(stored.profile_id) is not str or stored.profile_id != V3_PROFILE_ID
            or type(stored.event_seq) is not int or stored.event_seq != event.seq
            or type(stored.activity_ids) is not tuple
            or any(type(item) is not uuid.UUID for item in stored.activity_ids)
            or len(stored.activity_ids) != len(set(stored.activity_ids))
            or type(stored.historical) is not P2V3HistoricalAnswer
        ):
            raise ValueError
        historical = P2V3HistoricalAnswer.model_validate_json(
            stored.historical.model_dump_json(), strict=True,
        )
        evidence = historical.query_evidence
        fact_type_by_operation = {
            V3ReadOperation.ACTIVITIES: V3ActivityFact,
            V3ReadOperation.EXPENSES: V3ExpenseFact,
            V3ReadOperation.DEBTS: V3DebtFact,
            V3ReadOperation.REFUND_EVENTS: V3RefundEventFact,
            V3ReadOperation.PREPAYMENT_ACCOUNTS: V3PrepaymentAccountFact,
            V3ReadOperation.PREPAYMENT_USAGES: V3PrepaymentUsageFact,
            V3ReadOperation.PREPAYMENT_RETURN_EVENTS: V3PrepaymentReturnEventFact,
        }
        fact_type = fact_type_by_operation.get(evidence[0].operation) if len(evidence) == 1 else None
        if (
            event.simulation is not historical.simulation
            or historical.simulation is not False
            or event.payload.text != historical.text
            or event.payload.citations
            or historical.basis != "fresh_read_receipts"
            or len(evidence) != 1
            or fact_type is None
            or any(type(item) is not fact_type for item in historical.fact_cards)
            or any(item.query_evidence_ref != evidence[0].query_evidence_ref
                   for item in historical.fact_cards)
        ):
            raise ValueError
        return stored.activity_ids
    except Exception:
        # Store-side links and payloads are an integrity boundary. If any
        # field is stale or malformed, fail closed without exposing the text.
        raise _ApiFailure(
            503, ApiErrorCode.DEPENDENCY_UNAVAILABLE,
            "Protected activity output could not be verified.", retryable=True,
        ) from None


def _cursor_secret(request: Request) -> bytes:
    configured = request.app.state.settings.cursor_signing_secret
    if configured is not None:
        return configured.get_secret_value().encode("utf-8")
    return request.app.state.ephemeral_cursor_secret


def _encode_cursor(request: Request, owner: uuid.UUID, updated_at: datetime, session_id: uuid.UUID) -> str:
    payload = json.dumps({"o": str(owner), "u": updated_at.isoformat(), "s": str(session_id)}, separators=(",", ":"), sort_keys=True).encode()
    signature = hmac.new(_cursor_secret(request), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload + b"." + signature).decode("ascii").rstrip("=")


def _decode_cursor(request: Request, owner: uuid.UUID, cursor: str) -> tuple[datetime, uuid.UUID]:
    if len(cursor) > 240:
        raise _ApiFailure(400, ApiErrorCode.INVALID_REQUEST, "Pagination cursor is invalid.")
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        if len(raw) < 34 or raw[-33:-32] != b".":
            raise ValueError
        payload, signature = raw[:-33], raw[-32:]
        expected = hmac.new(_cursor_secret(request), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        document = json.loads(payload, object_pairs_hook=_unique_object, parse_constant=_no_constant)
        if set(document) != {"o", "u", "s"} or uuid.UUID(document["o"]) != owner:
            raise ValueError
        updated_at = datetime.fromisoformat(document["u"])
        session_id = uuid.UUID(document["s"])
        if updated_at.tzinfo is None or updated_at.utcoffset() is None:
            raise ValueError
        return updated_at, session_id
    except (ValueError, TypeError, KeyError, UnicodeError, json.JSONDecodeError):
        raise _ApiFailure(400, ApiErrorCode.INVALID_REQUEST, "Pagination cursor is invalid for this owner.") from None


def _public_status(snapshot: TurnStateSnapshot) -> TurnPublicStatus:
    return TurnPublicStatus(
        turn_id=snapshot.turn_id, session_id=snapshot.session_id, state=snapshot.state, step=snapshot.step,
        wait_reason=snapshot.wait_reason, resume_state=snapshot.resume_state,
        state_revision=snapshot.state_revision, execution_assigned=snapshot.execution is not None,
        execution_resolution=snapshot.execution_resolution, context_version=snapshot.context_version,
    )


def _cards(proposals: tuple[ProposalRecord, ...], states: dict[uuid.UUID, TurnStateSnapshot], control: AgentControlSnapshot) -> list[Any]:
    cards: list[Any] = []
    now = datetime.now(timezone.utc)
    for proposal in proposals:
        turn = states.get(proposal.proposal_id)
        if proposal.status == ProposalStatus.PENDING:
            if turn is None or turn.state != TurnState.WAIT_CONFIRM or turn.wait_reason != WaitReason.CONFIRM_REQUIRED:
                continue
            if proposal.expires_at <= now:
                cards.append(InactiveProposalCard(card_kind="inactive", mode=proposal.mode, status="expired",
                    proposal_id=proposal.proposal_id, revision=proposal.revision, operation=proposal.operation,
                    command_digest=proposal.command_digest, preview=proposal.preview, simulation=proposal.mode == "simulation"))
                continue
            if not control.enabled:
                continue
            if proposal.mode == "simulation":
                if proposal.policy_version != f"mock-policy-v1;disable_revision={control.disable_revision}":
                    continue
                if proposal.preview is not None:
                    cards.append(SimulationProposalCard(card_kind="simulation_pending", mode="simulation", status="pending",
                        proposal_id=proposal.proposal_id, revision=proposal.revision, operation=proposal.operation, preview=proposal.preview))
                continue
            if (
                proposal.mode == "backend" and proposal.preconditions is not None
                and proposal.preconditions.agent_disable_revision == control.disable_revision
                and proposal.command_digest is not None and proposal.confirmation_nonce is not None
                and proposal.preview is not None
            ):
                cards.append(ConfirmableProposalCard(card_kind="backend_pending", mode="backend", status="pending",
                    proposal_id=proposal.proposal_id, revision=proposal.revision, operation=proposal.operation,
                    command_digest=proposal.command_digest, confirmation_nonce=proposal.confirmation_nonce,
                    expires_at=proposal.expires_at, preview=proposal.preview))
            continue
        if proposal.preview is not None and proposal.status.value in {"superseded", "cancelled", "expired", "confirmed", "rejected", "closed"}:
            cards.append(InactiveProposalCard(card_kind="inactive", mode=proposal.mode, status=proposal.status.value,
                proposal_id=proposal.proposal_id, revision=proposal.revision, operation=proposal.operation,
                command_digest=proposal.command_digest, preview=proposal.preview, simulation=proposal.mode == "simulation"))
    return cards[:8]


def _step_for_checkpoint(aggregate: TurnAggregate) -> TurnStep:
    decision = aggregate.checkpoint.last_decision
    name = type(decision).__name__ if decision is not None else ""
    if name == "ReadDecision":
        return TurnStep.TOOL_READ
    if name == "ProposeDecision":
        return TurnStep.PREPARE_PROPOSAL
    if aggregate.checkpoint.model_context is None:
        return TurnStep.BUILD_CONTEXT
    return TurnStep.MODEL_DECISION


def _next_state(before: TurnStateSnapshot, state: TurnState, step: TurnStep, **changes: Any) -> TurnStateSnapshot:
    document = before.model_dump(mode="python", by_alias=True, exclude_none=False)
    document.update(changes)
    document.update({"state": state, "step": step, "state_revision": before.state_revision + 1})
    return TurnStateSnapshot.model_validate(document)


def _status_event(snapshot: TurnStateSnapshot, *, simulation: bool = False) -> EventDraft:
    return EventDraft(type=EventType.STATUS, occurred_at=datetime.now(timezone.utc), simulation=simulation,
        payload=StatusEventPayload(state=snapshot.state, step=snapshot.step, state_revision=snapshot.state_revision,
            wait_reason=snapshot.wait_reason, resume_state=snapshot.resume_state))


def _receipt(receipt: Any) -> JSONResponse:
    return _wire_response(receipt.response_snapshot, receipt.http_status)


def install_api_routes(app: FastAPI) -> None:
    async def handle_api_failure(request: Request, exc: _ApiFailure) -> JSONResponse:
        return _error_response(exc.status, exc.code, exc.message, retryable=exc.retryable)

    app.add_exception_handler(_ApiFailure, handle_api_failure)  # type: ignore[arg-type]

    @app.middleware("http")
    async def api_guard(request: Request, call_next: Any) -> Any:
        if request.url.path != "/v1" and not request.url.path.startswith("/v1/"):
            return await call_next(request)
        limiter: _RequestRateLimiter = request.app.state.ip_limiter
        client_host = request.client.host if request.client else "unknown"
        if not limiter.allow("ip:" + client_host):
            response = _error_response(429, ApiErrorCode.RATE_LIMITED, "Request rate limit exceeded.", retryable=True)
        else:
            try:
                response = await call_next(request)
            except _ApiFailure as exc:
                response = _error_response(exc.status, exc.code, exc.message, retryable=exc.retryable)
            except Exception:
                response = _error_response(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE, "The request could not be completed safely.", retryable=True)
        if response.status_code in (404, 405):
            response = _error_response(response.status_code, ApiErrorCode.NOT_FOUND if response.status_code == 404 else ApiErrorCode.INVALID_REQUEST,
                "The requested API route was not found." if response.status_code == 404 else "The HTTP method is not allowed for this route.")
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/v1/sessions", name="listSessions", include_in_schema=True)
    async def list_sessions(request: Request) -> JSONResponse:
        components, principal = await _authenticate(request)
        query = _parse_query(request, SessionListQuery)
        before_updated = before_session = None
        if query.cursor:
            before_updated, before_session = _decode_cursor(request, principal.user_id, query.cursor)
        page = await _store_call(components.store.list_sessions, principal.user_id,
            before_updated_at=before_updated, before_session_id=before_session, limit=query.limit)
        cursor = None
        if page.has_more and page.next_updated_at and page.next_session_id:
            cursor = _encode_cursor(request, principal.user_id, page.next_updated_at, page.next_session_id)
        return _wire_response(ListSessionsResponse(items=list(page.items), next_cursor=cursor))

    @app.post("/v1/sessions", name="createSession", status_code=201, include_in_schema=True)
    async def create_session(request: Request) -> JSONResponse:
        components, principal = await _authenticate(request)
        _require_no_query(request)
        body = await _request_model(request, CreateSessionRequest)
        receipt = await _store_call(components.store.create_session, principal.user_id, body)
        return _receipt(receipt)

    @app.get("/v1/sessions/{session_id}", name="getSession", include_in_schema=True)
    async def get_session(request: Request, session_id: str) -> JSONResponse:
        components, principal = await _authenticate(request)
        _require_no_query(request)
        identity = _parse_uuid(session_id)
        view = await _store_call(components.store.get_session_detail, principal.user_id, identity)
        states: dict[uuid.UUID, TurnStateSnapshot] = {}
        proposal_scopes: dict[uuid.UUID, set[uuid.UUID]] = {}
        for proposal in view.proposals:
            aggregate = view.proposal_turn_aggregates[proposal.proposal_id]
            proposal_scopes[proposal.proposal_id] = _scope_ids_for_turn(aggregate, (proposal,))
            states[proposal.proposal_id] = view.proposal_turn_states[proposal.proposal_id]
        try:
            control = await _agent_snapshot(components)
        except _ApiFailure:
            control = AgentControlSnapshot(enabled=False, disable_revision=0)
        candidates = _cards(view.proposals, states, control)
        visible_cards = []
        for card in candidates:
            if await _scope_card_visible(components, principal, proposal_scopes.get(card.proposal_id, set()), "session_card"):
                visible_cards.append(card)
        response = SessionDetailResponse(session=view.summary, turns=list(view.turns), proposal_cards=visible_cards)
        return _wire_response(response)

    @app.post("/v1/sessions/{session_id}/turns", name="submitTurn", status_code=202, include_in_schema=True)
    async def submit_turn(request: Request, session_id: str) -> JSONResponse:
        components, principal = await _authenticate(request)
        _require_no_query(request)
        identity = _parse_uuid(session_id)
        body = await _request_model(request, SubmitTurnRequest)
        replay = await _store_call(components.store.find_submit_receipt, principal.user_id, identity, body)
        if replay is not None:
            snapshot = replay.response_snapshot
            if isinstance(snapshot, SubmitTurnAccepted):
                _bind_turn_auth_grant(request, components, principal, snapshot.turn_id, existing_only=True)
            return _receipt(replay)
        await _require_enabled(components)
        await _store_call(components.store.get_session, principal.user_id, identity)
        receipt = await _store_call(components.store.submit_turn, principal.user_id, identity, body)
        snapshot = receipt.response_snapshot
        if isinstance(snapshot, SubmitTurnAccepted):
            _bind_turn_auth_grant(request, components, principal, snapshot.turn_id)
        return _receipt(receipt)

    @app.get("/v1/turns/{turn_id}/events", name="pollTurnEvents", include_in_schema=True)
    async def poll_events(request: Request, turn_id: str) -> JSONResponse:
        components, principal = await _authenticate(request)
        identity = _parse_uuid(turn_id)
        query = _parse_query(request, EventPollQuery)
        view: TurnView = await _store_call(components.store.read_turn_view, principal.user_id, identity,
            after_seq=query.after_seq, limit=min(query.limit, 500))
        p2_error_proof = callable(getattr(components.runtime, "safe_scope_free_event", None))
        # A P2 error is visible only when its exact closed payload has a durable
        # journal proof. Hidden records cannot advance the public cursor because
        # the frozen response requires it to equal the last delivered sequence.
        # Read ahead in bounded pages until we find enough visible events or
        # exhaust the log, so a hidden error cannot block the following status.
        events: list[Any] = []
        scan_cursor = query.after_seq
        scanned = 0
        scan_budget = 500
        while True:
            raw_page = [item.event for item in view.events]
            scanned += len(raw_page)
            for event in raw_page:
                hidden_error = (
                    p2_error_proof and event.type == EventType.ERROR
                    and not _safe_scope_free_event(view.turn, event, components.runtime)
                )
                if not hidden_error:
                    events.append(event)
                    if len(events) >= query.limit:
                        break
            if len(events) >= query.limit or not view.has_more:
                break
            if scanned >= scan_budget:
                raise _ApiFailure(
                    503, ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                    "Event log contains too many unverifiable records to page safely.", retryable=True,
                )
            if raw_page:
                scan_cursor = raw_page[-1].seq
            else:
                break
            view = await _store_call(
                components.store.read_turn_view, principal.user_id, identity,
                after_seq=scan_cursor, limit=min(query.limit, scan_budget - scanned),
            )
        scope_ids = _scope_ids_for_turn(view.turn, view.proposals)
        fact_events = [event for event in events if event.type != "status"]
        needs_scope: list[Any] = []
        protected_v3_activity_ids: set[uuid.UUID] = set()
        protected_v3_sequences: set[int] = set()
        for event in fact_events:
            if _safe_scope_free_event(view.turn, event, components.runtime):
                continue
            protected_ids = await _v3_protected_event_activity_ids(
                components, principal.user_id, identity, event,
            )
            if protected_ids is not None:
                protected_v3_sequences.add(event.seq)
                protected_v3_activity_ids.update(protected_ids)
                continue
            needs_scope.append(event)
        all_scope_ids = scope_ids | protected_v3_activity_ids
        if needs_scope and not scope_ids:
            raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE, "Activity scope for stored facts is unavailable.", retryable=True)
        if needs_scope or protected_v3_sequences:
            await _scope_authorize(components, principal, all_scope_ids, "turn_events", request=request)
        try:
            control = await _agent_snapshot(components)
        except _ApiFailure:
            control = AgentControlSnapshot(enabled=False, disable_revision=0)
        next_after = events[-1].seq if events else query.after_seq
        raw_after_delivered = bool(events and any(item.seq > next_after for item in raw_page))
        has_more_visible_or_unread = bool(view.has_more or raw_after_delivered)
        states = {proposal.proposal_id: view.turn.record.turn for proposal in view.proposals}
        candidates = _cards(view.proposals, states, control)
        visible_cards = []
        for card in candidates:
            if await _scope_card_visible(components, principal, scope_ids, "turn_card"):
                visible_cards.append(card)
        response = PollEventsResponse(turn=_public_status(view.turn.record.turn), after_seq=query.after_seq,
            events=events, next_after_seq=next_after,
            has_more=(has_more_visible_or_unread if events else False),
            proposal_cards=visible_cards)
        return _wire_response(response)

    @app.post("/v1/turns/{turn_id}/resume/auth", name="resumeAuth", status_code=202, include_in_schema=True)
    async def resume_auth(request: Request, turn_id: str) -> JSONResponse:
        components, principal = await _authenticate(request)
        _require_no_query(request)
        identity = _parse_uuid(turn_id)
        body = await _request_model(request, ResumeAuthRequest)
        replay = await _store_call(components.store.find_action_receipt, principal.user_id, identity, body)
        if replay is not None:
            return _receipt(replay)
        aggregate: TurnAggregate = await _store_call(components.store.get_turn, principal.user_id, identity)
        before = aggregate.record.turn
        if before.execution is not None:
            after = _next_state(before, TurnState.RECOVERING, TurnStep.RECONCILE,
                wait_reason=None, resume_state=None)
        elif before.resume_state == ResumeState.WAIT_CONFIRM:
            after = _next_state(before, TurnState.WAIT_CONFIRM, TurnStep.AWAITING_USER,
                wait_reason=WaitReason.CONFIRM_REQUIRED, resume_state=None)
        else:
            resumed = TurnState(before.resume_state.value) if before.resume_state else TurnState.QUEUED
            after = _next_state(before, resumed, _step_for_checkpoint(aggregate), wait_reason=None, resume_state=None)
        try:
            validate_auth_resume(before, after, expected_state_revision=body.expected_state_revision)
        except ValueError:
            raise _ApiFailure(409, ApiErrorCode.STATE_REVISION_CONFLICT, "The auth checkpoint is no longer current.") from None
        response = TurnMutationAccepted(turn_id=identity, state=after.state, state_revision=after.state_revision,
                                        event_cursor=0)
        receipt = await _store_call(components.store.accept_turn_action, principal.user_id, identity, body, after,
            response, events=[_status_event(after)], http_status=202)
        _bind_turn_auth_grant(request, components, principal, identity, replace=True)
        if before.execution is not None:
            wake_recovery = getattr(components.runtime, "wake_recovery", None)
            if callable(wake_recovery):
                wake_recovery(identity)
        return _receipt(receipt)

    @app.post("/v1/turns/{turn_id}/resume/clarification", name="resumeClarification", status_code=202, include_in_schema=True)
    async def resume_clarification(request: Request, turn_id: str) -> JSONResponse:
        components, principal = await _authenticate(request)
        _require_no_query(request)
        identity = _parse_uuid(turn_id)
        body = await _request_model(request, ResumeClarificationRequest)
        aggregate: TurnAggregate = await _store_call(components.store.get_turn, principal.user_id, identity)
        _scope_ids = _scope_ids_for_turn(aggregate)
        if _scope_ids:
            await _scope_authorize(components, principal, _scope_ids, "clarification_resume", request=request)
        replay = await _store_call(components.store.find_action_receipt, principal.user_id, identity, body)
        if replay is not None:
            return _receipt(replay)
        await _require_enabled(components)
        before = aggregate.record.turn
        if before.resume_state not in (ResumeState.QUEUED, ResumeState.RUNNING):
            raise _ApiFailure(409, ApiErrorCode.STATE_REVISION_CONFLICT, "The clarification checkpoint is no longer current.")
        after = _next_state(before, TurnState(before.resume_state.value), _step_for_checkpoint(aggregate),
            wait_reason=None, resume_state=None)
        response = TurnMutationAccepted(turn_id=identity, state=after.state, state_revision=after.state_revision,
                                        event_cursor=0)
        receipt = await _store_call(components.store.accept_turn_action, principal.user_id, identity, body, after,
            response, events=[_status_event(after)], http_status=202)
        _bind_turn_auth_grant(request, components, principal, identity, replace=True)
        return _receipt(receipt)

    @app.post("/v1/turns/{turn_id}/resume/proposal-adjust", name="resumeProposalAdjust", status_code=202, include_in_schema=True)
    async def resume_proposal_adjust(request: Request, turn_id: str) -> JSONResponse:
        components, principal = await _authenticate(request)
        _require_no_query(request)
        identity = _parse_uuid(turn_id)
        body = await _request_model(request, ResumeProposalAdjustRequest)
        view: TurnView = await _store_call(components.store.read_turn_view, principal.user_id, identity, after_seq=0, limit=1)
        scope_ids = _scope_ids_for_turn(view.turn, view.proposals)
        if not scope_ids:
            raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE, "Activity scope for the current proposal is unavailable.", retryable=True)
        await _scope_authorize(components, principal, scope_ids, "proposal_adjust", request=request)
        replay = await _store_call(components.store.find_action_receipt, principal.user_id, identity, body)
        if replay is not None:
            return _receipt(replay)
        control = await _require_enabled(components)
        pending = [item for item in view.proposals if item.status == ProposalStatus.PENDING and item.turn_id == identity]
        if len(pending) != 1:
            raise _ApiFailure(409, ApiErrorCode.PROPOSAL_REVISION_CONFLICT, "There is no current pending proposal to adjust.")
        current = pending[0]
        before = view.turn.record.turn
        reservation = view.turn.checkpoint.adjustment_reservation
        accepted_adjustment = next((item for item in view.turn.checkpoint.accepted_inputs
                                    if item.action == ApiActionKind.PROPOSAL_ADJUST
                                    and item.client_request_id == body.client_request_id
                                    and item.payload == body), None)
        resumable_reservation = bool(
            reservation is not None and accepted_adjustment is not None
            and reservation.client_request_id == body.client_request_id
            and reservation.payload_hash == accepted_adjustment.payload_hash
            and reservation.proposal_id == current.proposal_id
            and reservation.expected_proposal_revision == body.expected_proposal_revision
            and reservation.policy_version == current.policy_version
        )
        if (before.state != TurnState.WAIT_CONFIRM
            or before.state_revision != body.expected_state_revision and not resumable_reservation):
            raise _ApiFailure(409, ApiErrorCode.STATE_REVISION_CONFLICT, "The proposal adjustment checkpoint is no longer current.")
        if current.revision != body.expected_proposal_revision:
            raise _ApiFailure(409, ApiErrorCode.PROPOSAL_REVISION_CONFLICT, "The proposal revision has changed.")
        if current.expires_at <= datetime.now(timezone.utc):
            raise _ApiFailure(409, ApiErrorCode.PROPOSAL_EXPIRED, "The proposal has expired.")
        if current.mode == "simulation":
            expected_policy = f"mock-policy-v1;disable_revision={int(control.disable_revision)}"
            if current.policy_version != expected_policy:
                raise _ApiFailure(409, ApiErrorCode.AGENT_DISABLED, "The simulated proposal was invalidated by a policy change.")
            prepare = getattr(components.runtime, "prepare_proposal_adjustment", None)
            if not callable(prepare):
                raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE, "Proposal preparation is unavailable.", retryable=True)
            try:
                receipt = await prepare(principal.user_id, identity, current.proposal_id, body)
            except AdmissionFull:
                raise _ApiFailure(429, ApiErrorCode.RATE_LIMITED, "Runtime capacity is temporarily full.", retryable=True) from None
            except IdempotencyConflict:
                raise _ApiFailure(409, ApiErrorCode.IDEMPOTENCY_CONFLICT, "The request key was already used with different input.") from None
            except RuntimeAuthRequired:
                raise _ApiFailure(401, ApiErrorCode.UNAUTHENTICATED, "Authentication must be refreshed before this adjustment can continue.", retryable=True) from None
            except ProposalExpired:
                raise _ApiFailure(409, ApiErrorCode.PROPOSAL_EXPIRED, "The proposal has expired.") from None
            except AgentDisabled:
                raise _ApiFailure(409, ApiErrorCode.AGENT_DISABLED, "The proposal was invalidated by an Agent control change.") from None
            except (ProposalConflict, StateConflict):
                raise _ApiFailure(409, ApiErrorCode.PROPOSAL_REVISION_CONFLICT, "The proposal is no longer current.") from None
            except CapabilityUnavailable:
                raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE, "Proposal preparation is unavailable.", retryable=True) from None
            except StoreError:
                raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE, "Durable storage is temporarily unavailable.", retryable=True) from None
            except Exception:
                raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE, "Proposal preparation is unavailable.", retryable=True) from None
            return _receipt(receipt)
        if current.mode == "backend" and (current.preconditions is None or current.preconditions.agent_disable_revision != control.disable_revision):
            raise _ApiFailure(409, ApiErrorCode.AGENT_DISABLED, "The proposal was invalidated by an Agent control change.")
        if components.proposal_adjustment_preparer is None:
            raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE, "Proposal preparation is unavailable.", retryable=True)
        try:
            replacement = await asyncio.to_thread(components.proposal_adjustment_preparer.prepare, principal.user_id, identity, current, body)
        except CapabilityUnavailable:
            raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE, "Proposal preparation is unavailable.", retryable=True) from None
        except Exception:
            raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE, "Proposal preparation is unavailable.", retryable=True) from None
        replacement_scope = _scope_ids_for_turn(view.turn, (replacement,))
        if not replacement_scope:
            raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE, "Activity scope for the prepared proposal is unavailable.", retryable=True)
        if replacement.mode == "backend" and (
            replacement.preconditions is None or replacement.preconditions.agent_disable_revision != control.disable_revision
        ):
            raise _ApiFailure(409, ApiErrorCode.AGENT_DISABLED, "The prepared proposal was invalidated by an Agent control change.")
        await _scope_authorize(components, principal, replacement_scope, "prepared_proposal_adjust", request=request)
        now = datetime.now(timezone.utc)
        running = _next_state(before, TurnState.RUNNING, TurnStep.MODEL_DECISION, wait_reason=None, resume_state=None)
        final = _next_state(running, TurnState.WAIT_CONFIRM, TurnStep.AWAITING_USER,
            wait_reason=WaitReason.CONFIRM_REQUIRED, resume_state=None)
        events = [_status_event(running, simulation=current.mode == "simulation"),
                  _status_event(final, simulation=replacement.mode == "simulation"),
                  EventDraft(type=EventType.PROPOSAL, occurred_at=now, simulation=replacement.mode == "simulation",
                    payload=ProposalEventPayload(proposal_id=replacement.proposal_id, revision=replacement.revision, operation=replacement.operation))]
        # Store owns the atomic event cursor and receipt. Its preparation payload is
        # validated by the frozen replacement transition before anything is committed.
        try:
            receipt = await asyncio.to_thread(components.store.adjust_proposal, principal.user_id, identity, current.proposal_id, body, replacement, events=events)
        except StoreNotFound:
            raise _ApiFailure(404, ApiErrorCode.NOT_FOUND, "The requested resource was not found.") from None
        except IdempotencyConflict:
            raise _ApiFailure(409, ApiErrorCode.IDEMPOTENCY_CONFLICT, "The request key was already used with different input.") from None
        except ProposalExpired:
            raise _ApiFailure(409, ApiErrorCode.PROPOSAL_EXPIRED, "The proposal has expired.") from None
        except (ProposalConflict, StateConflict):
            raise _ApiFailure(409, ApiErrorCode.PROPOSAL_REVISION_CONFLICT, "The proposal is no longer current.") from None
        except StoreError:
            raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE, "Durable storage is temporarily unavailable.", retryable=True) from None
        return _receipt(receipt)

    @app.post("/v1/turns/{turn_id}/cancel", name="cancelTurn", status_code=202, include_in_schema=True)
    async def cancel_turn(request: Request, turn_id: str) -> JSONResponse:
        components, principal = await _authenticate(request)
        _require_no_query(request)
        identity = _parse_uuid(turn_id)
        body = await _request_model(request, CancelTurnRequest)
        replay = await _store_call(components.store.find_action_receipt, principal.user_id, identity, body)
        if replay is not None:
            return _receipt(replay)
        aggregate: TurnAggregate = await _store_call(components.store.get_turn, principal.user_id, identity)
        before = aggregate.record.turn
        if before.execution is None:
            after = _next_state(before, TurnState.CANCELLED, TurnStep.TERMINAL,
                wait_reason=None, resume_state=None, execution_resolution=None)
            result = "cancelled"
        else:
            if before.state == TurnState.RECOVERING:
                raise _ApiFailure(409, ApiErrorCode.STATE_REVISION_CONFLICT, "Execution is already being reconciled under its original key.")
            after = _next_state(before, TurnState.RECOVERING, TurnStep.RECONCILE,
                wait_reason=None, resume_state=None, execution_resolution=before.execution_resolution)
            result = "reconciling"
        response = CancelTurnResponse(turn=_public_status(after), result=result)
        receipt = await _store_call(components.store.accept_turn_action, principal.user_id, identity, body, after,
            response, events=[_status_event(after)], http_status=202)
        revoke = getattr(components.runtime, "revoke_turn_auth_grant", None)
        if callable(revoke):
            revoke(principal.user_id, identity)
        return _receipt(receipt)

    @app.post("/v1/proposals/{proposal_id}/confirm", name="confirmProposal", include_in_schema=True)
    async def confirm_proposal(request: Request, proposal_id: str) -> JSONResponse:
        components, principal = await _authenticate(request)
        _require_no_query(request)
        identity = _parse_uuid(proposal_id)
        body = await _request_model(request, ConfirmProposalRequest)
        proposal: ProposalRecord = await _store_call(components.store.get_proposal, principal.user_id, identity)
        turn: TurnAggregate = await _store_call(components.store.get_turn, principal.user_id, proposal.turn_id)
        scope_ids = _scope_ids_for_turn(turn, (proposal,))
        if not scope_ids:
            raise _ApiFailure(503, ApiErrorCode.DEPENDENCY_UNAVAILABLE, "Activity scope for the proposal is unavailable.", retryable=True)
        await _scope_authorize(components, principal, scope_ids, "proposal_confirm", request=request)
        replay = await _store_call(components.store.find_action_receipt, principal.user_id, identity, body)
        if replay is not None:
            return _receipt(replay)
        control = await _require_enabled(components)
        if turn.record.turn.state != TurnState.WAIT_CONFIRM:
            raise _ApiFailure(409, ApiErrorCode.STATE_REVISION_CONFLICT, "The turn is no longer awaiting confirmation.")
        if body.expected_proposal_revision != proposal.revision:
            raise _ApiFailure(409, ApiErrorCode.PROPOSAL_REVISION_CONFLICT, "The proposal revision or confirmation input has changed.") from None
        if proposal.expires_at <= datetime.now(timezone.utc):
            raise _ApiFailure(409, ApiErrorCode.PROPOSAL_EXPIRED, "The proposal has expired.")
        if proposal.mode == "simulation":
            expected_policy = f"mock-policy-v1;disable_revision={int(control.disable_revision)}"
            if proposal.policy_version != expected_policy or proposal.preview is None or not proposal.preview.simulation:
                raise _ApiFailure(409, ApiErrorCode.AGENT_DISABLED, "The simulated proposal was invalidated by a policy change.")
        else:
            if proposal.confirmation_nonce is None or proposal.command_digest is None:
                raise _ApiFailure(409, ApiErrorCode.PROPOSAL_REVISION_CONFLICT, "This proposal is not confirmable.")
            if proposal.preconditions is None or proposal.preconditions.agent_disable_revision != control.disable_revision:
                raise _ApiFailure(409, ApiErrorCode.AGENT_DISABLED, "The proposal was invalidated by an Agent control change.")
            if (
                not hmac.compare_digest(body.command_digest, proposal.command_digest)
                or not hmac.compare_digest(body.confirmation_nonce, proposal.confirmation_nonce)
            ):
                raise _ApiFailure(409, ApiErrorCode.PROPOSAL_REVISION_CONFLICT, "The proposal revision or confirmation input has changed.") from None
        response = ConfirmationUnavailableResponse(code="execution_capability_unavailable",
            message="Execution is unavailable in this service phase.")
        latest_control = await _require_enabled(components)
        if latest_control.disable_revision != control.disable_revision:
            raise _ApiFailure(409, ApiErrorCode.AGENT_DISABLED, "The proposal was invalidated by an Agent control change.")
        receipt = await _store_call(components.store.record_confirmation_unavailable, principal.user_id,
            identity, body, response, expected_revision=proposal.revision)
        return _receipt(receipt)


def install_health_routes(app: FastAPI) -> None:
    @app.get("/health/live", name="healthLive", tags=["health"])
    async def health_live(request: Request) -> dict[str, Any]:
        components: AppComponents | None = getattr(request.app.state, "components", None)
        schema_initialized = bool(getattr(components.store, "schema_initialized", False)) if components else False
        return {
            "status": "live", "service": "shared-ledger-agent", "storage_substrate_ready": None,
            "schema_initialized": schema_initialized,
            "business_api_available": bool(components and components.auth_verifier and components.auth_verifier.configured),
            "runtime_available": _runtime_health(components).available,
            "inference_available": bool(getattr(_provider_health(components), "inference_available", False)),
        }

    @app.get("/health/ready", name="healthReady", tags=["health"])
    def health_ready(request: Request) -> JSONResponse:
        components: AppComponents | None = getattr(request.app.state, "components", None)
        storage_ready = False
        if components is not None:
            try:
                storage_ready = components.store.probe_ready()
            except Exception:
                storage_ready = False
        provider = _provider_health(components)
        schema_initialized = bool(getattr(components.store, "schema_initialized", False)) if components else False
        payload = {
            "status": "ready" if storage_ready else "not_ready", "service": "shared-ledger-agent",
            "storage_substrate_ready": storage_ready, "schema_initialized": storage_ready and schema_initialized,
            "business_api_available": bool(components and components.auth_verifier and components.auth_verifier.configured),
            "runtime_available": _runtime_health(components).available,
            "provider_status": provider.status,
            "inference_available": bool(getattr(provider, "inference_available", False)),
        }
        return JSONResponse(payload, status_code=200 if storage_ready else 503)

    @app.get("/health/provider", name="healthProvider", tags=["health"])
    async def health_provider(request: Request) -> dict[str, Any]:
        components: AppComponents | None = getattr(request.app.state, "components", None)
        provider = _provider_health(components)
        reason = {
            "disabled": "provider_disabled",
            "simulation": "mock_simulation_only",
            "unavailable": "provider_unavailable",
            "ready": "last_inference_succeeded",
        }[provider.status]
        return {
            "status": provider.status,
            "inference_available": bool(getattr(provider, "inference_available", False)),
            "reason": getattr(provider, "reason", reason),
        }


def _provider_health(components: AppComponents | None) -> Any:
    from .ports import ProviderHealth
    if components is None:
        return ProviderHealth(status="unavailable")
    try:
        health = components.provider.health()
        if health.status in ("disabled", "unavailable", "simulation") and not hasattr(health, "inference_available"):
            return ProviderHealth(status=health.status)
        if health.status in ("disabled", "unavailable", "ready") and hasattr(health, "inference_available"):
            return health
        if health.status not in ("disabled", "unavailable", "simulation"):
            return ProviderHealth(status="unavailable")
        return ProviderHealth(status=health.status)
    except Exception:
        return ProviderHealth(status="unavailable")


def _runtime_health(components: AppComponents | None) -> Any:
    from .ports import ComponentHealth
    if components is None:
        return ComponentHealth(status="not_ready", available=False)
    try:
        health = components.runtime.health()
        if health.status == "simulation":
            return ComponentHealth(status="simulation", available=bool(health.available))
        if health.status in ("disabled", "not_implemented", "not_ready", "ready"):
            return ComponentHealth(status=health.status, available=bool(health.available))
        return ComponentHealth(status="not_ready", available=False)
    except Exception:
        return ComponentHealth(status="not_ready", available=False)


def install_frozen_openapi(app: FastAPI) -> None:
    source = Path(__file__).resolve().parents[1] / "contracts" / "v1.0.0" / "openapi.json"
    cached: dict[str, Any] | None = None

    def frozen_openapi() -> dict[str, Any]:
        nonlocal cached
        if cached is None:
            try:
                cached = json.loads(source.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
            except Exception:
                from fastapi import HTTPException
                raise HTTPException(status_code=503, detail="Frozen OpenAPI contract is unavailable.") from None
        return cached

    app.openapi = frozen_openapi  # type: ignore[method-assign]


def configure_api(app: FastAPI) -> None:
    settings = app.state.settings
    app.state.ip_limiter = _RequestRateLimiter(settings.api_requests_per_minute)
    app.state.actor_limiter = _RequestRateLimiter(settings.api_requests_per_minute)
    configured_secret = settings.cursor_signing_secret
    app.state.ephemeral_cursor_secret = (
        configured_secret.get_secret_value().encode("utf-8") if configured_secret is not None else secrets.token_bytes(32)
    )
    install_health_routes(app)
    install_api_routes(app)
    install_frozen_openapi(app)
