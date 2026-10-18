"""Narrow P1-02 component interfaces; none grants business capability."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import threading
from typing import Literal, Optional, Protocol, Sequence, TYPE_CHECKING, Any
import uuid

if TYPE_CHECKING:
    import uuid

    from .contracts import (
        BoundEvidenceReference, BoundReadResultReference, BoundReference, CancelTurnRequest,
        CancelTurnResponse, CreateSessionRequest, EventRecord, ProposalAdjustedAccepted,
        ProposalRecord, RequestReceipt, ResumeAuthRequest, ResumeClarificationRequest,
        ResumeProposalAdjustRequest, SessionId, SessionRecord, SubmitTurnRequest, TurnId,
        TurnMutationAccepted, TurnRecord, TurnStateSnapshot, UserId,
    )
    from .store import (
        ClaimedTurn, EventDraft, RecoveryCandidate, TurnAggregate, TurnCheckpoint, TurnView,
    )


ProviderState = Literal["disabled", "unavailable", "simulation"]


@dataclass(frozen=True)
class ProviderHealth:
    status: ProviderState
    inference_available: Literal[False] = False


@dataclass(frozen=True)
class ComponentHealth:
    status: Literal["ready", "disabled", "not_implemented", "not_ready", "simulation"]
    available: bool


@dataclass(frozen=True)
class Principal:
    """Authenticated identity derived only from a trusted AuthVerifier result."""

    user_id: uuid.UUID
    expires_at: Optional[datetime] = None


@dataclass(frozen=True)
class AgentControlSnapshot:
    """Server-owned Agent gate; never populated from a request body or UI context."""

    enabled: bool
    disable_revision: int
    source: Literal["server_config", "simulation"] = "server_config"


class ScopeDenied(RuntimeError):
    """The current authenticated user cannot access the referenced business scope."""


class ScopeUnavailable(RuntimeError):
    """The authoritative business scope adapter is not available."""


class CapabilityUnavailable(RuntimeError):
    """A required P1/P2 capability is intentionally not installed yet."""


class AgentDisabled(RuntimeError):
    """Server-owned Agent control is disabled or changed during a Runtime action."""


class Lifecycle(Protocol):
    def start(self) -> None: ...
    def close(self) -> None: ...


class AgentStore(Lifecycle, Protocol):
    """Typed persistence boundary consumed by Runtime and later API routes."""

    @property
    def schema_initialized(self) -> bool: ...
    def probe_ready(self) -> bool: ...
    def create_session(self, owner_user_id: UserId, request: CreateSessionRequest, *, now: Optional[datetime] = None) -> RequestReceipt: ...
    def submit_turn(self, owner_user_id: UserId, session_id: SessionId, request: SubmitTurnRequest, *, now: Optional[datetime] = None, candidate_profile_id: Optional[str] = None) -> RequestReceipt: ...
    def get_session(self, owner_user_id: UserId, session_id: SessionId) -> SessionRecord: ...
    def get_turn(self, owner_user_id: UserId, turn_id: TurnId) -> TurnAggregate: ...
    def get_proposal(self, owner_user_id: UserId, proposal_id: uuid.UUID) -> ProposalRecord: ...
    def find_action_receipt(self, owner_user_id: UserId, resource_id: uuid.UUID, request: object) -> Optional[RequestReceipt]: ...
    def find_submit_receipt(self, owner_user_id: UserId, session_id: SessionId, request: SubmitTurnRequest) -> Optional[RequestReceipt]: ...
    def list_sessions(self, owner_user_id: UserId, *, before_updated_at: Optional[datetime] = None, before_session_id: Optional[SessionId] = None, limit: int = 50) -> "SessionPage": ...
    def get_session_detail(self, owner_user_id: UserId, session_id: SessionId, *, turn_limit: int = 100, proposal_limit: int = 8) -> "SessionDetailView": ...
    def read_turn_view(self, owner_user_id: UserId, turn_id: TurnId, *, after_seq: int = 0, limit: int = 100) -> TurnView: ...
    def transition_turn(self, owner_user_id: UserId, after: TurnStateSnapshot, *, expected_state_revision: int, expected_checkpoint_revision: int, events: Sequence[EventDraft], checkpoint: Optional[TurnCheckpoint] = None, bound_references: Optional[list[BoundReference]] = None, bound_evidence_references: Optional[list[BoundEvidenceReference]] = None, bound_read_results: Optional[list[BoundReadResultReference]] = None, new_proposal: Optional[ProposalRecord] = None, claim_token: Optional[str] = None, now: Optional[datetime] = None) -> TurnAggregate: ...
    def save_checkpoint(self, owner_user_id: UserId, turn_id: TurnId, *, expected_state_revision: int, expected_checkpoint_revision: int, checkpoint: TurnCheckpoint, bound_references: Optional[list[BoundReference]] = None, bound_evidence_references: Optional[list[BoundEvidenceReference]] = None, bound_read_results: Optional[list[BoundReadResultReference]] = None, events: Sequence[EventDraft] = (), claim_token: Optional[str] = None, now: Optional[datetime] = None) -> TurnAggregate: ...
    def accept_turn_action(self, owner_user_id: UserId, turn_id: TurnId, request: ResumeClarificationRequest | ResumeAuthRequest | CancelTurnRequest, after: TurnStateSnapshot, response: TurnMutationAccepted | CancelTurnResponse, *, events: Sequence[EventDraft], http_status: int = 202, checkpoint: Optional[TurnCheckpoint] = None, now: Optional[datetime] = None) -> RequestReceipt: ...
    def reserve_proposal_adjustment(self, owner_user_id: UserId, turn_id: TurnId, proposal_id: uuid.UUID, request: ResumeProposalAdjustRequest, *, policy_version: str, now: Optional[datetime] = None) -> TurnAggregate: ...
    def release_proposal_adjustment_lease(self, owner_user_id: UserId, turn_id: TurnId, lease_token: str, *, clear_reservation: bool = False, now: Optional[datetime] = None) -> bool: ...
    def renew_proposal_adjustment_lease(self, owner_user_id: UserId, turn_id: TurnId, lease_token: str, *, lease_seconds: int = 60, now: Optional[datetime] = None) -> bool: ...
    def adjust_proposal(self, owner_user_id: UserId, turn_id: TurnId, proposal_id: uuid.UUID, request: ResumeProposalAdjustRequest, replacement: ProposalRecord, *, events: Sequence[EventDraft], now: Optional[datetime] = None) -> RequestReceipt: ...
    def record_confirmation_unavailable(self, owner_user_id: UserId, proposal_id: uuid.UUID, request: object, response: object, *, expected_revision: int, now: Optional[datetime] = None) -> RequestReceipt: ...
    def list_recovery_candidates(self) -> list[RecoveryCandidate]: ...
    def recover_interrupted_turns(self, *, now: Optional[datetime] = None) -> list[TurnAggregate]: ...
    def claim_next(self, worker_id: str, *, lease_seconds: int = 30, now: Optional[datetime] = None) -> Optional[ClaimedTurn]: ...
    def claim_runnable(self, worker_id: str, *, lease_seconds: int = 30, exclude_turn_ids: Sequence[TurnId] = (), now: Optional[datetime] = None, cancellation_event: Optional[threading.Event] = None, candidate_profile_id: Optional[str] = None, enabled_candidate_profile_ids: Optional[Sequence[str]] = None) -> Optional[ClaimedTurn]: ...
    def mark_claim_worker_retired(self, worker_id: str) -> None: ...
    def cleanup_retired_claim_workers(self) -> None: ...
    def renew_claim(self, turn_id: TurnId, claim_token: str, *, lease_seconds: int = 30, now: Optional[datetime] = None) -> bool: ...
    def release_claim(self, turn_id: TurnId, claim_token: str) -> bool: ...


class AuthVerifier(Protocol):
    """Validate a user access token and return only its trusted user identity."""

    @property
    def configured(self) -> bool: ...
    def verify_bearer(self, access_token: str) -> Principal: ...


class ScopeAuthorizer(Protocol):
    """Re-check activity access before returning persisted activity facts/cards."""

    def authorize(self, principal: Principal, activity_ids: frozenset["uuid.UUID"], *, action: str) -> None: ...


class AgentControl(Protocol):
    """Return server-owned Agent state and a monotonic invalidation revision.

    Each disable transition must increment ``disable_revision``; re-enabling
    must retain that revision so proposals from before the disable stay stale.
    A configuration-backed implementation relies on the operator persisting
    and increasing this value across restarts.
    """

    def snapshot(self) -> AgentControlSnapshot: ...
    def snapshot_for(self, principal: Principal) -> AgentControlSnapshot: ...


class ProposalAdjustmentPreparer(Protocol):
    """Prepare a trusted, validated proposal replacement; P1-05 owns its real implementation."""

    def prepare(self, owner_user_id: UserId, turn_id: TurnId, proposal: ProposalRecord, request: "ResumeProposalAdjustRequest") -> ProposalRecord: ...


class ModelProvider(Lifecycle, Protocol):
    def health(self) -> ProviderHealth: ...
    async def generate(self, context: Any) -> str: ...


class BackendAdapter(Lifecycle, Protocol):
    def health(self) -> ComponentHealth: ...
    async def read(self, owner_user_id: uuid.UUID, turn_id: uuid.UUID, context: Any, decision: Any) -> Any: ...


class Runtime(Lifecycle, Protocol):
    def health(self) -> ComponentHealth: ...


class Gateway(Protocol):
    def health(self) -> ComponentHealth: ...
