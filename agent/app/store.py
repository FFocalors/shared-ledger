"""Durable P1-03 SQLite store.

The frozen protocol models remain the public source of truth. This module adds only
private, closed checkpoint envelopes needed to recover accepted inputs and runtime
progress that intentionally do not belong in RequestReceipt or model/event payloads.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import threading
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .p2_read_store import (
    P2_CANDIDATE_PROFILE_ID,
    P2_MAX_ACTIVE_US,
    P2_MAX_BACKEND_US,
    P2_MAX_GETS,
    P2_MAX_LOGICAL_READS,
    P2_MAX_MODEL_CALLS,
    P2_MAX_REPAIRS,
    P2_MAX_RESPONSE_BYTES,
    CandidateChargeReservation,
    CandidateChargeSettlement,
    CandidatePageReceiptDraft,
    CandidateQueryDescriptor,
    CandidateTurnSnapshot,
    canonical_private_json,
    json_sha256,
    receipt_digest as p2_receipt_digest,
    revalidate_model as revalidate_p2_model,
)
from .p2_source_store_v3 import (
    P2_V3_CANDIDATE_PROFILE_ID,
    P2V3UnsupportedProfile,
    P2V3StoreMixin,
)
from .p2_v3_execution_cohort import (
    P2V3ExecutionManifestError,
    P2V3VerifiedExecutionCohort,
    is_verified_execution_cohort,
    verify_execution_manifest_file,
)

from .contracts import (
    AGENT_EVENT_ADAPTER,
    ActivityFact,
    AgentEvent,
    AnswerDecision,
    ApiActionKind,
    ApiErrorCode,
    BoundEvidenceReference,
    BoundReadResultReference,
    BoundReference,
    CancelTurnRequest,
    CancelTurnResponse,
    ClarifyDecision,
    ConfirmProposalRequest,
    ClientRequestId,
    CreateSessionRequest,
    CreateSessionResponse,
    EventRecord,
    EventType,
    ErrorEventPayload,
    ExecutionResolution,
    ClarificationEventPayload,
    DebtFact,
    ExecutionResultPayload,
    ExpenseFact,
    MessageEventPayload,
    ModelReadResult,
    ModelContext,
    PolicyEvidenceRef,
    PolicyEvidence,
    ProposalAdjustedAccepted,
    ProposalEvent,
    ProposalEventPayload,
    ProposalRecord,
    ProposalStatus,
    RequestReceipt,
    RequestReceiptKind,
    ResumeAuthRequest,
    ResumeClarificationRequest,
    ResumeProposalAdjustRequest,
    ResumeState,
    SemanticDecision,
    SessionId,
    SessionRecord,
    SessionSummary,
    SessionSummary,
    StatusEvent,
    StatusEventPayload,
    SubmitTurnAccepted,
    SubmitTurnRequest,
    ToolReadResult,
    TurnId,
    TurnMutationAccepted,
    TurnRecord,
    TurnSummary,
    TurnState,
    TurnStateSnapshot,
    TurnStep,
    TurnSummary,
    WaitReason,
    TurnPublicStatus,
    UIContext,
    UserId,
    canonical_payload_hash,
    validate_auth_resume,
    validate_cancel_transition,
    validate_confirm_transition,
    validate_idempotent_replay,
    validate_proposal_adjustment,
    validate_state_transition,
)


class StoreError(RuntimeError):
    """Sanitized persistence error safe to surface outside the storage boundary."""


class StorageStartupError(StoreError):
    """SQLite could not be opened, migrated, or verified."""


class StoreNotStarted(StoreError):
    """The store lifecycle has not completed startup."""


class StoreNotFound(StoreError):
    """The requested resource is absent from the authenticated owner's scope."""


class StoreConflict(StoreError):
    """A request key, revision, or state precondition conflicts with durable state."""


class IdempotencyConflict(StoreConflict):
    """A previously used action key has a different resource or canonical body."""


class StateConflict(StoreConflict):
    """The requested state/checkpoint revision is no longer current."""


class ProposalConflict(StoreConflict):
    """The proposal revision or pending-proposal condition no longer holds."""


class ProposalExpired(ProposalConflict):
    """The current pending proposal has passed its frozen expiry timestamp."""


class AdmissionFull(StoreConflict):
    """A Runtime concurrency slot is unavailable; the client may retry after release."""


class InvariantViolation(StoreError):
    """Stored or proposed data violates a frozen protocol invariant."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


AcceptedRequest = Union[
    SubmitTurnRequest,
    ResumeClarificationRequest,
    ResumeAuthRequest,
    ResumeProposalAdjustRequest,
    CancelTurnRequest,
]


class AcceptedInput(_StrictModel):
    """Typed user input persisted separately from the hash-only replay receipt."""

    action: ApiActionKind
    client_request_id: ClientRequestId
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload: AcceptedRequest
    accepted_at: datetime

    @model_validator(mode="after")
    def payload_matches_action(self) -> "AcceptedInput":
        expected = {
            ApiActionKind.TURN_SUBMIT: SubmitTurnRequest,
            ApiActionKind.CLARIFICATION_RESUME: ResumeClarificationRequest,
            ApiActionKind.AUTH_RESUME: ResumeAuthRequest,
            ApiActionKind.PROPOSAL_ADJUST: ResumeProposalAdjustRequest,
            ApiActionKind.TURN_CANCEL: CancelTurnRequest,
        }.get(self.action)
        if expected is None or not isinstance(self.payload, expected):
            raise ValueError("accepted input type must match its action scope")
        if self.payload.client_request_id != self.client_request_id:
            raise ValueError("accepted input request key must match its typed payload")
        if self.accepted_at.tzinfo is None or self.accepted_at.utcoffset() is None:
            raise ValueError("accepted input timestamp must include a timezone")
        return self


class StoredEventProvenance(_StrictModel):
    """Private proof that one persisted simulated event came from a closed Runtime path."""

    seq: int = Field(ge=1)
    generation: int = Field(ge=1)
    source: Literal["conversation_answer", "policy_answer", "clarification", "system_error"]
    event_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AdjustmentReservation(_StrictModel):
    """Durable, private identity for one in-flight proposal adjustment."""

    client_request_id: uuid.UUID
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposal_id: uuid.UUID
    expected_proposal_revision: int = Field(ge=1)
    policy_version: str = Field(min_length=1, max_length=160)
    lease_token: Optional[str] = Field(default=None, min_length=16, max_length=128)
    lease_expires_at: Optional[datetime] = None

    @model_validator(mode="after")
    def lease_pair_is_complete(self) -> "AdjustmentReservation":
        if (self.lease_token is None) != (self.lease_expires_at is None):
            raise ValueError("adjustment lease token and expiration must be paired")
        if self.lease_expires_at is not None and (
            self.lease_expires_at.tzinfo is None or self.lease_expires_at.utcoffset() is None
        ):
            raise ValueError("adjustment lease expiration must be timezone-aware")
        return self


class TurnCheckpoint(_StrictModel):
    """Closed, typed recovery state; it cannot carry a nonce or arbitrary token map."""

    accepted_inputs: list[AcceptedInput] = Field(max_length=257)
    model_context: Optional[ModelContext] = None
    last_decision: Optional[SemanticDecision] = None
    last_clarification: Optional[ClarifyDecision] = None
    resume_step: Optional[TurnStep] = None
    adjustment_reservation: Optional[AdjustmentReservation] = None
    closed_adjustments: list[AdjustmentReservation] = Field(default_factory=list, max_length=257)
    event_provenance: list[StoredEventProvenance] = Field(default_factory=list, max_length=4096)
    read_results: list[ToolReadResult] = Field(max_length=16)
    persisted_policy_evidence: list[PolicyEvidence] = Field(max_length=64)
    generation: Annotated[int, Field(strict=True, ge=1)] = 1
    model_calls: Annotated[int, Field(strict=True, ge=0, le=6)] = 0
    read_calls: Annotated[int, Field(strict=True, ge=0, le=4)] = 0
    repair_calls: Annotated[int, Field(strict=True, ge=0, le=1)] = 0


class SessionPrivate(_StrictModel):
    record: SessionRecord
    create_request: CreateSessionRequest


class EventDraft(_StrictModel):
    """Typed event payload; the store assigns the sequence inside its write transaction."""

    type: EventType
    occurred_at: datetime
    simulation: bool
    payload: Union[
        StatusEventPayload,
        MessageEventPayload,
        ClarificationEventPayload,
        ProposalEventPayload,
        ExecutionResultPayload,
        ErrorEventPayload,
    ]

    @model_validator(mode="after")
    def payload_matches_type(self) -> "EventDraft":
        expected = {
            EventType.STATUS: StatusEventPayload,
            EventType.MESSAGE: MessageEventPayload,
            EventType.CLARIFICATION: ClarificationEventPayload,
            EventType.PROPOSAL: ProposalEventPayload,
            EventType.EXECUTION_RESULT: ExecutionResultPayload,
            EventType.ERROR: ErrorEventPayload,
        }[self.type]
        if not isinstance(self.payload, expected):
            raise ValueError("event payload type must match its event kind")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("event timestamp must include a timezone")
        return self


@dataclass(frozen=True)
class TurnAggregate:
    record: TurnRecord
    checkpoint: TurnCheckpoint
    queue_order: int
    checkpoint_revision: int
    claim_token: Optional[str]
    claim_until: Optional[datetime]


@dataclass(frozen=True)
class TurnView:
    turn: TurnAggregate
    events: tuple[EventRecord, ...]
    event_cursor: int
    has_more: bool
    proposals: tuple[ProposalRecord, ...]


@dataclass(frozen=True)
class SessionPage:
    items: tuple[SessionSummary, ...]
    has_more: bool
    next_updated_at: Optional[datetime]
    next_session_id: Optional[SessionId]


@dataclass(frozen=True)
class SessionDetailView:
    session: SessionRecord
    summary: SessionSummary
    turns: tuple[TurnSummary, ...]
    turn_aggregates: tuple[TurnAggregate, ...]
    proposals: tuple[ProposalRecord, ...]
    proposal_turn_states: dict[uuid.UUID, TurnStateSnapshot]
    proposal_turn_aggregates: dict[uuid.UUID, TurnAggregate]


@dataclass(frozen=True)
class ClaimedTurn:
    turn: TurnAggregate
    claim_token: str
    claim_until: datetime
    execution_profile_id: Optional[str] = None


@dataclass(frozen=True)
class RecoveryCandidate:
    disposition: Literal["queued", "resume_planning", "reconcile_execution", "await_input", "await_confirmation"]
    turn: TurnAggregate


@dataclass(frozen=True)
class _Migration:
    version: int
    name: str
    sql: str
    checksum: str


class SQLiteAgentStore(P2V3StoreMixin):
    """SQLite Store with short, cross-connection-safe transactions."""

    _EXPECTED_TABLES = {
        "schema_migrations", "sessions", "turns", "events", "proposals",
        "p2_candidate_turns", "p2_candidate_charge_events", "p2_candidate_queries",
        "p2_candidate_page_receipts", "p2_candidate_page_gets",
        "p2_v3_turns", "p2_v3_charge_events", "p2_v3_source_admissions",
        "p2_v3_queries", "p2_v3_query_attempts", "p2_v3_wire_captures",
        "p2_v3_continuation_nonce_uses", "p2_v3_continuation_nonce_issues",
        "p2_v3_execution_cohorts", "p2_v3_execution_cohort_components",
        "p2_v3_turn_execution_pins", "p2_v3_query_descriptor_bindings",
        "p2_v3_capture_chain_reservations", "p2_v3_source_get_receipts",
        "p2_v3_admission_source_receipts", "p2_v3_query_result_receipts",
        "p2_v3_query_result_gets", "p2_v3_entity_locators",
        "p2_v3_query_fact_proofs", "p2_v3_query_fact_sources",
        "p2_v3_activity_collection_qev_proofs", "p2_v3_activity_collection_members",
        "p2_v3_metadata_source_proofs", "p2_v3_protected_outputs",
        "p2_v3_metadata_acceptance_batches", "p2_v3_metadata_acceptance_proofs",
        "p2_v3_metadata_acceptance_events", "p2_v3_output_metadata_acceptances",
        "p2_v3_output_fact_links", "p2_v3_output_query_links",
        "p2_v3_output_metadata_links", "p2_v3_output_event_links",
    }

    def __init__(
        self,
        path: Path,
        *,
        fault_injector: Optional[Callable[[str], None]] = None,
        busy_timeout_seconds: float = 2.0,
        admission_enabled: bool = False,
        p2_v3_execution_manifest_path: Optional[Path] = None,
        p2_v3_execution_manifest_sha256: Optional[str] = None,
        p2_v3_execution_repository_root: Optional[Path] = None,
        p2_v3_execution_external_component_roots: Optional[dict[str, Path]] = None,
        test_only_allow_synthetic_p2_v3_cohort: bool = False,
    ) -> None:
        self._path = path
        self._fault_injector = fault_injector
        self._busy_timeout_ms = max(1, int(busy_timeout_seconds * 1000))
        self._admission_enabled = admission_enabled
        manifest_inputs = (
            p2_v3_execution_manifest_path,
            p2_v3_execution_manifest_sha256,
            p2_v3_execution_repository_root,
        )
        if any(item is not None for item in manifest_inputs) and not all(item is not None for item in manifest_inputs):
            raise ValueError("P2 v3 execution manifest path, trust digest, and repository root must be configured together")
        self._test_only_allow_synthetic_p2_v3_cohort = bool(test_only_allow_synthetic_p2_v3_cohort)
        self._p2_v3_execution_external_component_roots = dict(p2_v3_execution_external_component_roots or {})
        self._p2_v3_execution_cohort: Optional[P2V3VerifiedExecutionCohort] = None
        if all(item is not None for item in manifest_inputs):
            try:
                cohort = verify_execution_manifest_file(
                    Path(p2_v3_execution_manifest_path),
                    expected_manifest_sha256=str(p2_v3_execution_manifest_sha256),
                    repository_root=Path(p2_v3_execution_repository_root),
                    external_component_roots=self._p2_v3_execution_external_component_roots,
                )
            except (OSError, P2V3ExecutionManifestError, TypeError, ValueError):
                raise ValueError("P2 v3 execution cohort failed trusted configuration verification") from None
            if cohort.is_synthetic and not self._test_only_allow_synthetic_p2_v3_cohort:
                raise ValueError("synthetic P2 v3 cohorts are permitted only by explicit test configuration")
            self._p2_v3_execution_cohort = cohort
        self._lifecycle_lock = threading.Lock()
        self._claim_lifecycle_lock = threading.RLock()
        self._claim_workers_lock = threading.Lock()
        self._retired_claim_workers: set[str] = set()
        self._started = False
        self._schema_initialized = False
        self._migrations = self._load_migrations()

    @property
    def schema_initialized(self) -> bool:
        return self._schema_initialized and self._started

    def _verify_configured_p2_v3_execution_cohort(self) -> None:
        cohort = self._p2_v3_execution_cohort
        if cohort is None:
            return
        if not is_verified_execution_cohort(cohort):
            raise StorageStartupError("configured P2 v3 execution cohort is not verifier-issued")
        if cohort.is_synthetic and not self._test_only_allow_synthetic_p2_v3_cohort:
            raise StorageStartupError("synthetic P2 v3 execution cohort is disabled outside tests")
        try:
            cohort = cohort.verify_unchanged()
            self._p2_v3_execution_cohort = cohort
        except (OSError, P2V3ExecutionManifestError, ValueError):
            raise StorageStartupError("configured P2 v3 execution cohort changed after verification") from None

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._started:
                raise StorageStartupError("SQLite store is already started")
            created_file = False
            created_directories: list[Path] = []
            try:
                self._create_parent_directories(created_directories)
                if self._path.exists() and self._path.is_dir():
                    raise OSError("database path is a directory")
                if not self._path.exists():
                    descriptor = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
                    os.close(descriptor)
                    created_file = True
                connection = self._connect()
                try:
                    mode = str(connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
                    if mode != "wal":
                        raise OSError("WAL mode could not be enabled")
                    connection.execute("PRAGMA synchronous=FULL")
                    self._migrate(connection)
                    connection.execute("BEGIN")
                    try:
                        self._verify_configured_p2_v3_execution_cohort()
                        self._verify_schema(connection)
                        self._verify_database_integrity(connection)
                        self._verify_all_rows(connection)
                        self._verify_p2_candidate_rows(connection)
                        self._verify_p2_v3_rows(connection)
                        self._recover_p2_candidate_process_start(connection, instant=_aware_now(None))
                        self._recover_p2_v3_process_start(connection, instant=_aware_now(None))
                        connection.execute("COMMIT")
                    except BaseException:
                        if connection.in_transaction:
                            connection.execute("ROLLBACK")
                        raise
                finally:
                    connection.close()
                self._started = True
                self._schema_initialized = True
                with self._claim_lifecycle_lock:
                    self._cleanup_retired_claim_workers_locked()
            except Exception:
                self._started = False
                self._schema_initialized = False
                if created_file:
                    try:
                        self._path.unlink(missing_ok=True)
                        Path(str(self._path) + "-wal").unlink(missing_ok=True)
                        Path(str(self._path) + "-shm").unlink(missing_ok=True)
                    except OSError:
                        pass
                for directory in reversed(created_directories):
                    try:
                        directory.rmdir()
                    except OSError:
                        pass
                raise StorageStartupError(
                    "configured SQLite storage failed migration or integrity verification"
                ) from None

    def close(self) -> None:
        with self._lifecycle_lock:
            with self._claim_lifecycle_lock:
                if self._started:
                    self._cleanup_retired_claim_workers_locked()
                self._started = False
                self._schema_initialized = False

    def probe_ready(self) -> bool:
        if not self.schema_initialized:
            return False
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                connection.execute(f"PRAGMA user_version = {version + 1}")
                connection.execute("ROLLBACK")
                self._verify_schema(connection)
                return True
        except (sqlite3.Error, StoreError, ValueError):
            return False

    def create_session(
        self,
        owner_user_id: UserId,
        request: CreateSessionRequest,
        *,
        now: Optional[datetime] = None,
    ) -> RequestReceipt:
        self._require_started()
        instant = _aware_now(now)
        payload_hash = canonical_payload_hash(ApiActionKind.SESSION_CREATE, request)
        request_json = _dump_json(request)
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM sessions WHERE owner_user_id = ? AND create_request_id = ?",
                (str(owner_user_id), str(request.client_request_id)),
            ).fetchone()
            if existing is not None:
                stored = self._session_receipt(existing)
                return self._replay_or_conflict(
                    stored,
                    scope=ApiActionKind.SESSION_CREATE,
                    owner_user_id=owner_user_id,
                    resource_id=None,
                    request_id=request.client_request_id,
                    payload_hash=payload_hash,
                )

            session_id = uuid.uuid4()
            summary = SessionSummary(
                session_id=session_id,
                title=request.title,
                created_at=instant,
                updated_at=instant,
                active_turn_count=0,
            )
            response = CreateSessionResponse(session=summary)
            record = SessionRecord(
                session_id=session_id,
                owner_user_id=owner_user_id,
                title=request.title,
                default_activity_hint=None,
                create_request_id=request.client_request_id,
                create_payload_hash=payload_hash,
                create_response=response,
                created_at=instant,
                updated_at=instant,
            )
            private = SessionPrivate(record=record, create_request=request)
            connection.execute(
                """INSERT INTO sessions (
                    session_id, owner_user_id, title, default_activity_hint,
                    create_request_id, create_payload_hash, create_request_json,
                    create_response_json, private_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(session_id), str(owner_user_id), request.title, None,
                    str(request.client_request_id), payload_hash, request_json,
                    _dump_json(response), _dump_json(private), _timestamp(instant), _timestamp(instant),
                ),
            )
            receipt = RequestReceipt(
                key_scope=ApiActionKind.SESSION_CREATE,
                owner_user_id=owner_user_id,
                resource_id=None,
                client_request_id=request.client_request_id,
                payload_hash=payload_hash,
                http_status=201,
                response_kind=RequestReceiptKind.SESSION_CREATED,
                response_snapshot=response,
                recorded_at=instant,
            )
            self._fault("create_session.before_commit")
        self._fault("create_session.after_commit")
        return receipt

    def submit_turn(
        self,
        owner_user_id: UserId,
        session_id: SessionId,
        request: SubmitTurnRequest,
        *,
        now: Optional[datetime] = None,
        candidate_profile_id: Optional[str] = None,
    ) -> RequestReceipt:
        self._require_started()
        instant = _aware_now(now)
        if candidate_profile_id not in (None, P2_CANDIDATE_PROFILE_ID, P2_V3_CANDIDATE_PROFILE_ID):
            raise ValueError("unknown server-side candidate profile")
        payload_hash = canonical_payload_hash(ApiActionKind.TURN_SUBMIT, request, resource_id=session_id)
        request_json = _dump_json(request)
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM turns WHERE owner_user_id = ? AND client_request_id = ?",
                (str(owner_user_id), str(request.client_request_id)),
            ).fetchone()
            if existing is not None:
                aggregate = self._turn_aggregate(existing)
                stored = next(
                    (item for item in aggregate.record.request_receipts if item.key_scope == ApiActionKind.TURN_SUBMIT),
                    None,
                )
                if stored is None:
                    raise InvariantViolation("stored submit request has no original receipt")
                assigned = connection.execute(
                    "SELECT profile_id FROM p2_candidate_turns WHERE turn_id = ? AND owner_user_id = ?",
                    (existing["turn_id"], str(owner_user_id)),
                ).fetchone()
                assigned_v3 = connection.execute(
                    "SELECT profile_id FROM p2_v3_turns WHERE turn_id = ? AND owner_user_id = ?",
                    (existing["turn_id"], str(owner_user_id)),
                ).fetchone()
                if assigned is not None and assigned_v3 is not None:
                    raise InvariantViolation("Turn is assigned to multiple candidate Store families")
                pinned_profile = assigned["profile_id"] if assigned is not None else (
                    assigned_v3["profile_id"] if assigned_v3 is not None else None
                )
                if candidate_profile_id is not None and (
                    pinned_profile != candidate_profile_id
                ):
                    raise StateConflict("idempotent submit replay cannot add or change a candidate assignment")
                return self._replay_or_conflict(
                    stored,
                    scope=ApiActionKind.TURN_SUBMIT,
                    owner_user_id=owner_user_id,
                    resource_id=session_id,
                    request_id=request.client_request_id,
                    payload_hash=payload_hash,
                )

            session = connection.execute(
                "SELECT session_id FROM sessions WHERE session_id = ? AND owner_user_id = ?",
                (str(session_id), str(owner_user_id)),
            ).fetchone()
            if session is None:
                raise StoreNotFound("session is not available to this owner")

            self._check_admission(connection, owner_user_id, target_state=TurnState.QUEUED, now=instant)

            turn_id = uuid.uuid4()
            snapshot = TurnStateSnapshot(
                turn_id=turn_id,
                session_id=session_id,
                owner_user_id=owner_user_id,
                state=TurnState.QUEUED,
                step=TurnStep.ACCEPTED,
                state_revision=1,
                context_version=1,
            )
            accepted = SubmitTurnAccepted(turn_id=turn_id, state=TurnState.QUEUED.value, accepted_at=instant)
            receipt = RequestReceipt(
                key_scope=ApiActionKind.TURN_SUBMIT,
                owner_user_id=owner_user_id,
                resource_id=session_id,
                client_request_id=request.client_request_id,
                payload_hash=payload_hash,
                http_status=202,
                response_kind=RequestReceiptKind.TURN_ACCEPTED,
                response_snapshot=accepted,
                recorded_at=instant,
            )
            record = TurnRecord(
                turn=snapshot,
                client_request_id=request.client_request_id,
                request_payload_hash=payload_hash,
                original_text=request.text,
                ui_context_snapshot=request.ui_context,
                bound_references=[],
                bound_evidence_references=[],
                bound_read_results=[],
                request_receipts=[receipt],
            )
            checkpoint = TurnCheckpoint(
                accepted_inputs=[
                    AcceptedInput(
                        action=ApiActionKind.TURN_SUBMIT,
                        client_request_id=request.client_request_id,
                        payload_hash=payload_hash,
                        payload=request,
                        accepted_at=instant,
                    )
                ],
                read_results=[],
                persisted_policy_evidence=[],
            )
            queue_order = int(connection.execute("SELECT COALESCE(MAX(queue_order), 0) + 1 FROM turns").fetchone()[0])
            connection.execute(
                """INSERT INTO turns (
                    turn_id, session_id, owner_user_id, client_request_id,
                    request_payload_hash, request_json, state, state_revision, step,
                    execution_id, execution_resolution, record_json, checkpoint_json,
                    checkpoint_revision, queue_order, claim_token, claim_until,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)""",
                (
                    str(turn_id), str(session_id), str(owner_user_id), str(request.client_request_id),
                    payload_hash, request_json, snapshot.state.value, snapshot.state_revision,
                    snapshot.step.value, None, None, _dump_json(record), _dump_json(checkpoint),
                    1, queue_order, _timestamp(instant), _timestamp(instant),
                ),
            )
            if candidate_profile_id is not None:
                if candidate_profile_id == P2_CANDIDATE_PROFILE_ID:
                    self._insert_p2_candidate_turn(
                        connection,
                        owner_user_id=owner_user_id,
                        turn_id=turn_id,
                        profile_id=candidate_profile_id,
                        generation=checkpoint.generation,
                        input_seq=1,
                        input_digest=payload_hash,
                        context_revision=1,
                        state_revision=1,
                        lifecycle="queued",
                        now=instant,
                    )
                else:
                    cohort = self._p2_v3_execution_cohort
                    if cohort is None:
                        raise P2V3UnsupportedProfile(
                            "new P2 v3 assignments require a trusted server execution cohort"
                        )
                    try:
                        cohort = cohort.verify_unchanged()
                    except (OSError, P2V3ExecutionManifestError, ValueError):
                        raise P2V3UnsupportedProfile(
                            "configured P2 v3 execution cohort changed before assignment"
                        ) from None
                    self._p2_v3_execution_cohort = cohort
                    self._insert_p2_v3_turn(
                        connection,
                        owner_user_id=owner_user_id,
                        turn_id=turn_id,
                        generation=checkpoint.generation,
                        input_seq=1,
                        input_digest=payload_hash,
                        context_revision=1,
                        state_revision=1,
                        lifecycle="queued",
                        execution_cohort=cohort,
                        now=instant,
                    )
                    self._persist_p2_v3_execution_pin(
                        connection,
                        owner_user_id=owner_user_id,
                        turn_id=turn_id,
                        cohort=cohort,
                        now=instant,
                    )
            status = self._status_draft(snapshot, instant)
            self._append_events(connection, turn_id, owner_user_id, session_id, [status], record, checkpoint)
            self._touch_session(connection, session_id, owner_user_id, instant)
            self._fault("submit_turn.before_commit")
        self._fault("submit_turn.after_commit")
        return receipt

    def transition_turn(
        self,
        owner_user_id: UserId,
        after: TurnStateSnapshot,
        *,
        expected_state_revision: int,
        expected_checkpoint_revision: int,
        events: Sequence[EventDraft],
        checkpoint: Optional[TurnCheckpoint] = None,
        event_sources: Optional[Sequence[Optional[str]]] = None,
        bound_references: Optional[list[BoundReference]] = None,
        bound_evidence_references: Optional[list[BoundEvidenceReference]] = None,
        bound_read_results: Optional[list[BoundReadResultReference]] = None,
        new_proposal: Optional[ProposalRecord] = None,
        updated_proposal: Optional[ProposalRecord] = None,
        fixture_execution: bool = False,
        execution_dispatch: bool = False,
        proposal_result_update: bool = False,
        claim_token: Optional[str] = None,
        candidate_profile_id: Optional[str] = None,
        p2_v3_protected_output: Any = None,
        now: Optional[datetime] = None,
    ) -> TurnAggregate:
        """Commit a legal state edge, status event, optional checkpoint and proposal together."""
        self._require_started()
        instant = _aware_now(now)
        with self._transaction() as connection:
            row = self._owned_turn(connection, owner_user_id, after.turn_id)
            aggregate = self._turn_aggregate(row)
            before = aggregate.record.turn
            candidate_row = self._require_candidate_profile_for_turn(
                connection, owner_user_id, after.turn_id, candidate_profile_id,
            )
            if p2_v3_protected_output is not None and (
                candidate_row is None
                or candidate_row["profile_id"] != P2_V3_CANDIDATE_PROFILE_ID
                or new_proposal is not None or updated_proposal is not None or fixture_execution
            ):
                raise StateConflict("protected P2 v3 output requires its pinned candidate Turn")
            if candidate_row is not None and candidate_row["profile_id"] == P2_V3_CANDIDATE_PROFILE_ID and (
                new_proposal is not None or updated_proposal is not None or fixture_execution
            ):
                raise StateConflict("v3 candidate proposal recognition cannot persist or confirm a business proposal")
            self._check_claim(aggregate, claim_token, instant)
            if aggregate.checkpoint_revision != expected_checkpoint_revision:
                raise StateConflict("turn checkpoint revision precondition failed")
            try:
                validate_state_transition(before, after, expected_state_revision=expected_state_revision)
            except ValueError:
                raise StateConflict("turn state transition precondition failed") from None
            assigning_execution = before.execution is None and after.execution is not None
            if assigning_execution and not (fixture_execution or execution_dispatch):
                raise StateConflict("execution identity assignment requires an explicit dispatch")
            if (fixture_execution or execution_dispatch) and not assigning_execution:
                raise StateConflict("an explicit dispatch must assign the execution identity")
            if before.state != TurnState.RUNNING and after.state == TurnState.RUNNING:
                self._check_admission(
                    connection, owner_user_id, target_state=TurnState.RUNNING,
                    excluding_turn_id=after.turn_id, now=instant,
                )
            if fixture_execution or execution_dispatch:
                if new_proposal is not None or updated_proposal is None or after.execution is None:
                    raise InvariantViolation("execution dispatch requires the existing proposal update")
                current_proposal = self._proposal_by_id(connection, owner_user_id, after.execution.proposal_id)
                try:
                    validate_confirm_transition(
                        before, after, current_proposal,
                        expected_state_revision=expected_state_revision,
                        expected_proposal_revision=after.execution.proposal_revision,
                    )
                except ValueError:
                    raise StateConflict("execution identity does not match the pending proposal") from None
                updated_proposal = self._preserve_proposal_receipts(current_proposal, updated_proposal)
                if (
                    updated_proposal.proposal_id != current_proposal.proposal_id
                    or updated_proposal.revision != current_proposal.revision
                    or updated_proposal.execution != after.execution
                    or updated_proposal.status != ProposalStatus.CONFIRMED
                ):
                    raise InvariantViolation("execution dispatch must atomically confirm the same proposal revision")
                self._validate_proposal_scope(updated_proposal, after)
                changed = connection.execute(
                    "UPDATE proposals SET status = ?, record_json = ?, updated_at = ? "
                    "WHERE proposal_id = ? AND owner_user_id = ? AND revision = ? AND status = 'pending'",
                    (updated_proposal.status.value, _dump_json(updated_proposal), _timestamp(instant),
                     str(updated_proposal.proposal_id), str(owner_user_id), updated_proposal.revision),
                ).rowcount
                if changed != 1:
                    raise ProposalConflict("proposal changed before execution identity dispatch")
            elif updated_proposal is not None:
                if not proposal_result_update:
                    raise InvariantViolation("proposal status updates require an explicit execution dispatch")
                # Settling a dispatched execution may move an already-confirmed
                # proposal to a terminal status. It may not reassign the execution
                # identity, resurrect a pending proposal, or touch another turn.
                if after.execution is None or before.execution != after.execution:
                    raise InvariantViolation("a proposal result update requires the existing execution identity")
                current_proposal = self._proposal_by_id(connection, owner_user_id, after.execution.proposal_id)
                updated_proposal = self._preserve_proposal_receipts(current_proposal, updated_proposal)
                if (
                    updated_proposal.proposal_id != current_proposal.proposal_id
                    or updated_proposal.revision != current_proposal.revision
                    or updated_proposal.execution != after.execution
                    or current_proposal.execution != after.execution
                    or current_proposal.status != ProposalStatus.CONFIRMED
                    or updated_proposal.status not in (ProposalStatus.REJECTED, ProposalStatus.CLOSED)
                ):
                    raise InvariantViolation("a proposal result update may only settle a confirmed execution")
                changed = connection.execute(
                    "UPDATE proposals SET status = ?, record_json = ?, updated_at = ? "
                    "WHERE proposal_id = ? AND owner_user_id = ? AND revision = ? AND status = 'confirmed'",
                    (updated_proposal.status.value, _dump_json(updated_proposal), _timestamp(instant),
                     str(updated_proposal.proposal_id), str(owner_user_id), updated_proposal.revision),
                ).rowcount
                if changed != 1:
                    raise ProposalConflict("proposal changed before its execution result was recorded")
            self._validate_after_owner_session(after, owner_user_id, aggregate.record)
            next_checkpoint = checkpoint if checkpoint is not None else aggregate.checkpoint
            next_checkpoint_revision = aggregate.checkpoint_revision + (1 if checkpoint is not None or event_sources else 0)
            updated = self._record_with_updates(
                aggregate.record,
                turn=after,
                bound_references=bound_references,
                bound_evidence_references=bound_evidence_references,
                bound_read_results=bound_read_results,
            )
            self._validate_status_event_in_batch(after, events)
            if new_proposal is not None:
                self._validate_proposal_scope(new_proposal, after)
                if after.state != TurnState.WAIT_CONFIRM or new_proposal.status != ProposalStatus.PENDING or new_proposal.execution is not None:
                    raise InvariantViolation("a new proposal must be pending and enter WAIT_CONFIRM")
                self._expire_stale_pending_proposals(
                    connection, owner_user_id, after.session_id, instant,
                )
                proposal_events = [event for event in events if event.type == EventType.PROPOSAL]
                if len(proposal_events) != 1 or (
                    proposal_events[0].payload.proposal_id != new_proposal.proposal_id
                    or proposal_events[0].payload.revision != new_proposal.revision
                ):
                    raise InvariantViolation("a new pending proposal requires its exact durable proposal event")
                self._insert_proposal(connection, new_proposal, instant)
            if after.state == TurnState.WAIT_CONFIRM:
                if self._pending_proposal_for_turn(connection, owner_user_id, after.session_id, after.turn_id) is None:
                    raise InvariantViolation("WAIT_CONFIRM requires an owner-scoped pending proposal for this Turn")
            elif not fixture_execution:
                pending = self._pending_proposal_for_turn(connection, owner_user_id, after.session_id, after.turn_id)
                if pending is not None:
                    auth_pauses_waiting_proposal = (
                        before.state == TurnState.WAIT_CONFIRM
                        and after.state == TurnState.WAIT_INPUT
                        and after.wait_reason == WaitReason.AUTH_REQUIRED
                        and after.resume_state == ResumeState.WAIT_CONFIRM
                        and after.execution is None
                    )
                    if auth_pauses_waiting_proposal:
                        pass  # Keep the exact pending proposal and nonce for validate_auth_resume.
                    elif after.state in (TurnState.COMPLETED, TurnState.CANCELLED, TurnState.FAILED):
                        self._cancel_pending_proposals(connection, owner_user_id, after.session_id, after.turn_id, instant)
                    else:
                        raise InvariantViolation("a pending proposal can only remain through its exact auth pause or a terminal transition")
            appended = self._append_events(connection, after.turn_id, owner_user_id, after.session_id, events, updated, next_checkpoint)
            next_checkpoint = _append_event_provenance(next_checkpoint, appended, event_sources)
            self._validate_append_only_bindings(aggregate, updated, next_checkpoint)
            if p2_v3_protected_output is not None:
                self._persist_p2_v3_protected_output_in_transaction(
                    connection,
                    owner_user_id=owner_user_id,
                    after=after,
                    checkpoint=next_checkpoint,
                    appended_events=appended,
                    protected_output=p2_v3_protected_output,
                    claim_token=claim_token,
                    now=instant,
                )
            queue_order = aggregate.queue_order
            if after.state == TurnState.QUEUED and before.state != TurnState.QUEUED:
                queue_order = int(connection.execute("SELECT COALESCE(MAX(queue_order), 0) + 1 FROM turns").fetchone()[0])
            clear_claim = after.state != TurnState.RUNNING
            connection.execute(
                """UPDATE turns SET state = ?, state_revision = ?, step = ?, execution_id = ?,
                    execution_resolution = ?, record_json = ?, checkpoint_json = ?,
                    checkpoint_revision = ?, queue_order = ?, claim_token = ?, claim_until = ?, updated_at = ?
                WHERE turn_id = ? AND owner_user_id = ? AND state_revision = ? AND checkpoint_revision = ?""",
                (
                    after.state.value, after.state_revision, after.step.value,
                    str(after.execution.execution_id) if after.execution else None,
                    after.execution_resolution.value if after.execution_resolution else None,
                    _dump_json(updated), _dump_json(next_checkpoint), next_checkpoint_revision,
                    queue_order,
                    None if clear_claim else aggregate.claim_token,
                    None if clear_claim else row["claim_until"],
                    _timestamp(instant), str(after.turn_id), str(owner_user_id),
                    expected_state_revision, expected_checkpoint_revision,
                ),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise StateConflict("turn state changed during update")
            if candidate_row is not None:
                self._update_candidate_after_transition(
                    connection, owner_user_id=owner_user_id, turn_id=after.turn_id,
                    after=after, checkpoint=next_checkpoint,
                    checkpoint_revision=next_checkpoint_revision,
                    expected_candidate_revision=int(candidate_row["revision"]), now=instant,
                    profile_id=candidate_row["profile_id"],
                )
            self._touch_session(connection, after.session_id, owner_user_id, instant)
            self._fault("transition_turn.before_commit")
            result = self._turn_aggregate(
                connection.execute("SELECT * FROM turns WHERE turn_id = ?", (str(after.turn_id),)).fetchone()
            )
        self._fault("transition_turn.after_commit")
        return result

    def save_checkpoint(
        self,
        owner_user_id: UserId,
        turn_id: TurnId,
        *,
        expected_state_revision: int,
        expected_checkpoint_revision: int,
        checkpoint: TurnCheckpoint,
        bound_references: Optional[list[BoundReference]] = None,
        bound_evidence_references: Optional[list[BoundEvidenceReference]] = None,
        bound_read_results: Optional[list[BoundReadResultReference]] = None,
        events: Sequence[EventDraft] = (),
        event_sources: Optional[Sequence[Optional[str]]] = None,
        claim_token: Optional[str] = None,
        candidate_profile_id: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> TurnAggregate:
        """CAS same-state recovery data without inventing a frozen state transition."""
        self._require_started()
        instant = _aware_now(now)
        with self._transaction() as connection:
            row = self._owned_turn(connection, owner_user_id, turn_id)
            aggregate = self._turn_aggregate(row)
            candidate_row = self._require_candidate_profile_for_turn(
                connection, owner_user_id, turn_id, candidate_profile_id,
            )
            snapshot = aggregate.record.turn
            self._check_claim(aggregate, claim_token, instant)
            if snapshot.state_revision != expected_state_revision or aggregate.checkpoint_revision != expected_checkpoint_revision:
                raise StateConflict("turn state or checkpoint revision precondition failed")
            current_reservation = aggregate.checkpoint.adjustment_reservation
            requested_reservation = checkpoint.adjustment_reservation
            if (current_reservation is None) != (requested_reservation is None):
                raise StateConflict("checkpoint cannot add or remove an adjustment reservation")
            if current_reservation is not None:
                if (
                    requested_reservation is None
                    or current_reservation.client_request_id != requested_reservation.client_request_id
                    or current_reservation.payload_hash != requested_reservation.payload_hash
                    or current_reservation.proposal_id != requested_reservation.proposal_id
                    or current_reservation.lease_token != requested_reservation.lease_token
                    or current_reservation.lease_expires_at is None
                    or current_reservation.lease_expires_at <= instant
                ):
                    raise StateConflict("adjustment lease is no longer current")
                # Lease renewals intentionally do not advance checkpoint_revision;
                # preserve the transaction's freshest expiration while saving semantic work.
                checkpoint = checkpoint.model_copy(update={"adjustment_reservation": current_reservation})
            if snapshot.state in (TurnState.COMPLETED, TurnState.CANCELLED, TurnState.FAILED):
                raise StateConflict("terminal turn checkpoints are immutable")
            updated = self._record_with_updates(
                aggregate.record,
                bound_references=bound_references,
                bound_evidence_references=bound_evidence_references,
                bound_read_results=bound_read_results,
            )
            for draft in events:
                if draft.type == EventType.STATUS:
                    self._validate_status_draft(snapshot, draft)
            appended = self._append_events(connection, turn_id, owner_user_id, snapshot.session_id, events, updated, checkpoint)
            checkpoint = _append_event_provenance(checkpoint, appended, event_sources)
            self._validate_append_only_bindings(aggregate, updated, checkpoint)
            connection.execute(
                """UPDATE turns SET record_json = ?, checkpoint_json = ?, checkpoint_revision = ?, updated_at = ?
                WHERE turn_id = ? AND owner_user_id = ? AND state_revision = ? AND checkpoint_revision = ?""",
                (
                    _dump_json(updated), _dump_json(checkpoint), aggregate.checkpoint_revision + 1,
                    _timestamp(instant), str(turn_id), str(owner_user_id),
                    expected_state_revision, expected_checkpoint_revision,
                ),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise StateConflict("turn checkpoint changed during update")
            if candidate_row is not None:
                self._update_candidate_after_transition(
                    connection, owner_user_id=owner_user_id, turn_id=turn_id,
                    after=snapshot, checkpoint=checkpoint,
                    checkpoint_revision=aggregate.checkpoint_revision + 1,
                    expected_candidate_revision=int(candidate_row["revision"]), now=instant,
                    profile_id=candidate_row["profile_id"],
                )
            self._fault("save_checkpoint.before_commit")
            result = self._turn_aggregate(connection.execute("SELECT * FROM turns WHERE turn_id = ?", (str(turn_id),)).fetchone())
        self._fault("save_checkpoint.after_commit")
        return result

    def accept_turn_action(
        self,
        owner_user_id: UserId,
        turn_id: TurnId,
        request: Union[ResumeClarificationRequest, ResumeAuthRequest, CancelTurnRequest],
        after: TurnStateSnapshot,
        response: Union[TurnMutationAccepted, CancelTurnResponse],
        *,
        events: Sequence[EventDraft],
        http_status: int = 202,
        checkpoint: Optional[TurnCheckpoint] = None,
        now: Optional[datetime] = None,
    ) -> RequestReceipt:
        """Resume/cancel: match any stored receipt before checking current state, then commit all data."""
        self._require_started()
        instant = _aware_now(now)
        if http_status != 202:
            raise ValueError("resume, proposal-adjust, and cancel accepted responses use HTTP 202")
        scope = _action_for_request(request)
        payload_hash = canonical_payload_hash(scope, request, resource_id=turn_id)
        with self._transaction() as connection:
            row = self._owned_turn(connection, owner_user_id, turn_id)
            aggregate = self._turn_aggregate(row)
            candidate_row = self._candidate_assignment_row(connection, owner_user_id, turn_id)
            stored = next(
                (item for item in aggregate.record.request_receipts
                 if item.key_scope == scope and item.resource_id == turn_id
                 and item.client_request_id == request.client_request_id),
                None,
            )
            if stored is not None:
                return self._replay_or_conflict(
                    stored, scope=scope, owner_user_id=owner_user_id, resource_id=turn_id,
                    request_id=request.client_request_id, payload_hash=payload_hash,
                )
            before = aggregate.record.turn
            try:
                self._validate_turn_action(request, before, after, response)
            except ValueError:
                raise StateConflict("turn action state precondition failed") from None
            if isinstance(request, (ResumeAuthRequest, ResumeClarificationRequest)):
                self._check_admission(
                    connection, owner_user_id, target_state=after.state, excluding_turn_id=turn_id, now=instant,
                )
            if not events:
                raise InvariantViolation("accepted turn actions require a durable event in the same transaction")
            self._validate_status_event_in_batch(after, events)
            final_cursor = self._next_event_seq(connection, turn_id) + len(events) - 1
            if isinstance(response, TurnMutationAccepted) and response.event_cursor == 0:
                # The HTTP layer may provide an unassigned cursor. Resolve it from
                # this write transaction so a concurrent checkpoint event cannot
                # make an API pre-read cursor stale or force a false success value.
                response = response.model_copy(update={"event_cursor": final_cursor})
            if isinstance(response, TurnMutationAccepted) and (
                response.turn_id != turn_id or response.state != after.state
                or response.state_revision != after.state_revision
                or response.event_cursor != final_cursor
            ):
                raise InvariantViolation("turn action response must match its resulting snapshot and event cursor")
            if isinstance(response, CancelTurnResponse) and response.turn != _public_status(after):
                raise InvariantViolation("cancel response must match its resulting snapshot")
            if aggregate.checkpoint_revision < 1:
                raise InvariantViolation("stored checkpoint revision is invalid")
            next_checkpoint = checkpoint or aggregate.checkpoint
            next_checkpoint = self._append_accepted_input(
                next_checkpoint, scope, request, payload_hash, instant,
                advance_generation=scope in (ApiActionKind.CLARIFICATION_RESUME, ApiActionKind.PROPOSAL_ADJUST),
            )
            if isinstance(request, ResumeClarificationRequest):
                # A clarification is a new planning input. Do not resume the
                # prior ClarifyDecision's AWAITING_USER stage or reuse its context.
                next_checkpoint = next_checkpoint.model_copy(update={
                    "model_context": None,
                    "last_decision": None,
                    "resume_step": TurnStep.BUILD_CONTEXT,
                })
            if isinstance(request, CancelTurnRequest) and next_checkpoint.adjustment_reservation is not None:
                next_checkpoint = self._close_adjustment_reservation(next_checkpoint).model_copy(update={
                    "resume_step": None,
                })
            receipt = RequestReceipt(
                key_scope=scope, owner_user_id=owner_user_id, resource_id=turn_id,
                client_request_id=request.client_request_id, payload_hash=payload_hash,
                http_status=http_status,
                response_kind=(RequestReceiptKind.TURN_CANCELLED if scope == ApiActionKind.TURN_CANCEL
                               else RequestReceiptKind.TURN_RESUMED),
                response_snapshot=response, recorded_at=instant,
            )
            updated = self._record_with_receipt(
                self._record_with_updates(aggregate.record, turn=after), receipt
            )
            self._validate_append_only_bindings(aggregate, updated, next_checkpoint)
            if after.state == TurnState.WAIT_CONFIRM:
                if self._pending_proposal_for_turn(connection, owner_user_id, after.session_id, turn_id) is None:
                    raise InvariantViolation("WAIT_CONFIRM requires an owner-scoped pending proposal for this Turn")
            elif after.state in (TurnState.COMPLETED, TurnState.CANCELLED, TurnState.FAILED):
                self._cancel_pending_proposals(connection, owner_user_id, after.session_id, turn_id, instant)
            elif self._pending_proposal_for_turn(connection, owner_user_id, after.session_id, turn_id) is not None:
                raise InvariantViolation("a pending proposal cannot be abandoned by a nonterminal action")
            self._append_events(connection, turn_id, owner_user_id, after.session_id, events, updated, next_checkpoint)
            queue_order = aggregate.queue_order
            if after.state == TurnState.QUEUED and before.state != TurnState.QUEUED:
                queue_order = int(connection.execute("SELECT COALESCE(MAX(queue_order), 0) + 1 FROM turns").fetchone()[0])
            clear_claim = after.state not in (TurnState.RUNNING, TurnState.QUEUED)
            connection.execute(
                """UPDATE turns SET state = ?, state_revision = ?, step = ?, execution_id = ?,
                    execution_resolution = ?, record_json = ?, checkpoint_json = ?, checkpoint_revision = ?,
                    queue_order = ?, claim_token = ?, claim_until = ?, updated_at = ?
                WHERE turn_id = ? AND owner_user_id = ? AND state_revision = ? AND checkpoint_revision = ?""",
                (
                    after.state.value, after.state_revision, after.step.value,
                    str(after.execution.execution_id) if after.execution else None,
                    after.execution_resolution.value if after.execution_resolution else None,
                    _dump_json(updated), _dump_json(next_checkpoint), aggregate.checkpoint_revision + 1,
                    queue_order, None if clear_claim else aggregate.claim_token,
                    None if clear_claim else row["claim_until"], _timestamp(instant),
                    str(turn_id), str(owner_user_id), before.state_revision, aggregate.checkpoint_revision,
                ),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise StateConflict("turn changed during accepted action")
            if candidate_row is not None:
                self._update_candidate_after_action(
                    connection, owner_user_id=owner_user_id, turn_id=turn_id,
                    after=after, checkpoint=next_checkpoint,
                    checkpoint_revision=aggregate.checkpoint_revision + 1,
                    expected_candidate_revision=int(candidate_row["revision"]), now=instant,
                    profile_id=candidate_row["profile_id"],
                )
            self._touch_session(connection, after.session_id, owner_user_id, instant)
            self._fault("accept_turn_action.before_commit")
        self._fault("accept_turn_action.after_commit")
        return receipt

    def reserve_proposal_adjustment(
        self,
        owner_user_id: UserId,
        turn_id: TurnId,
        proposal_id: uuid.UUID,
        request: ResumeProposalAdjustRequest,
        *,
        policy_version: str,
        now: Optional[datetime] = None,
    ) -> TurnAggregate:
        """Accept one adjustment input and reserve its generation before model work."""
        self._require_started()
        instant = _aware_now(now)
        scope = ApiActionKind.PROPOSAL_ADJUST
        payload_hash = canonical_payload_hash(scope, request, resource_id=turn_id)
        with self._transaction() as connection:
            row = self._owned_turn(connection, owner_user_id, turn_id)
            aggregate = self._turn_aggregate(row)
            candidate_row = self._candidate_assignment_row(connection, owner_user_id, turn_id)
            if candidate_row is not None and candidate_row["profile_id"] == P2_V3_CANDIDATE_PROFILE_ID:
                raise StateConflict("v3 candidate profile does not persist proposal-adjustment execution")
            before = aggregate.record.turn
            current = self._proposal_by_id(connection, owner_user_id, proposal_id)
            if current.turn_id != turn_id or current.session_id != before.session_id:
                raise StoreNotFound("proposal is not available in this turn")
            if current.status != ProposalStatus.PENDING or current.revision != request.expected_proposal_revision:
                raise ProposalConflict("proposal revision precondition failed")
            if current.expires_at <= instant:
                raise ProposalExpired("proposal has expired")
            existing = aggregate.checkpoint.adjustment_reservation
            if existing is not None:
                if existing.client_request_id == request.client_request_id and existing.payload_hash != payload_hash:
                    raise IdempotencyConflict("adjustment idempotency key was reused with different input")
                if (
                    existing.client_request_id == request.client_request_id
                    and existing.payload_hash == payload_hash
                    and existing.proposal_id == proposal_id
                    and existing.expected_proposal_revision == request.expected_proposal_revision
                    and existing.policy_version == policy_version
                ):
                    if before.state != TurnState.WAIT_CONFIRM:
                        raise StateConflict("an accepted adjustment can resume only after auth returns to WAIT_CONFIRM")
                    if existing.lease_token is not None and existing.lease_expires_at is not None and existing.lease_expires_at > instant:
                        raise AdmissionFull("this adjustment already has an active Runtime lease")
                    self._check_admission(
                        connection, owner_user_id, target_state=TurnState.RUNNING,
                        excluding_turn_id=turn_id, now=instant,
                    )
                    reservation = existing.model_copy(update={
                        "lease_token": str(uuid.uuid4()),
                        "lease_expires_at": instant + timedelta(seconds=60),
                    })
                    checkpoint = aggregate.checkpoint.model_copy(update={"adjustment_reservation": reservation})
                    self._validate_append_only_bindings(aggregate, aggregate.record, checkpoint)
                    changed = connection.execute(
                        "UPDATE turns SET checkpoint_json = ?, checkpoint_revision = ?, updated_at = ? "
                        "WHERE turn_id = ? AND owner_user_id = ? AND state_revision = ? AND checkpoint_revision = ?",
                        (_dump_json(checkpoint), aggregate.checkpoint_revision + 1, _timestamp(instant),
                         str(turn_id), str(owner_user_id), before.state_revision, aggregate.checkpoint_revision),
                    ).rowcount
                    if changed != 1:
                        raise StateConflict("turn changed while reacquiring its adjustment lease")
                    if candidate_row is not None:
                        self._sync_candidate_checkpoint(
                            connection, owner_user_id=owner_user_id, turn_id=turn_id,
                            checkpoint_revision=aggregate.checkpoint_revision + 1,
                            state_revision=before.state_revision,
                            expected_candidate_revision=int(candidate_row["revision"]), now=instant,
                            profile_id=candidate_row["profile_id"],
                        )
                    self._touch_session(connection, before.session_id, owner_user_id, instant)
                    result = self._turn_aggregate(
                        connection.execute("SELECT * FROM turns WHERE turn_id = ?", (str(turn_id),)).fetchone()
                    )
                    return result
                raise ProposalConflict("another adjustment already owns this proposal reservation")
            closed = next((item for item in aggregate.checkpoint.closed_adjustments
                           if item.client_request_id == request.client_request_id), None)
            if closed is not None:
                if closed.payload_hash != payload_hash:
                    raise IdempotencyConflict("adjustment idempotency key was reused with different input")
                raise ProposalConflict("this accepted adjustment was already closed")
            if before.state != TurnState.WAIT_CONFIRM or before.state_revision != request.expected_state_revision:
                raise StateConflict("proposal adjustment state precondition failed")
            self._check_admission(
                connection, owner_user_id, target_state=TurnState.RUNNING,
                excluding_turn_id=turn_id, now=instant,
            )
            checkpoint = self._append_accepted_input(
                aggregate.checkpoint, scope, request, payload_hash, instant, advance_generation=True,
            )
            checkpoint = checkpoint.model_copy(update={
                "model_context": None,
                "last_decision": None,
                "last_clarification": None,
                "resume_step": TurnStep.MODEL_DECISION,
                "adjustment_reservation": AdjustmentReservation(
                    client_request_id=request.client_request_id,
                    payload_hash=payload_hash,
                    proposal_id=proposal_id,
                    expected_proposal_revision=request.expected_proposal_revision,
                    policy_version=policy_version,
                    lease_token=str(uuid.uuid4()),
                    lease_expires_at=instant + timedelta(seconds=60),
                ),
            })
            self._validate_append_only_bindings(aggregate, aggregate.record, checkpoint)
            changed = connection.execute(
                "UPDATE turns SET checkpoint_json = ?, checkpoint_revision = ?, updated_at = ? "
                "WHERE turn_id = ? AND owner_user_id = ? AND state = 'WAIT_CONFIRM' "
                "AND state_revision = ? AND checkpoint_revision = ?",
                (_dump_json(checkpoint), aggregate.checkpoint_revision + 1, _timestamp(instant),
                 str(turn_id), str(owner_user_id), before.state_revision, aggregate.checkpoint_revision),
            ).rowcount
            if changed != 1:
                raise StateConflict("turn changed while reserving its proposal adjustment")
            if candidate_row is not None:
                self._update_candidate_after_action(
                    connection, owner_user_id=owner_user_id, turn_id=turn_id,
                    after=before, checkpoint=checkpoint,
                    checkpoint_revision=aggregate.checkpoint_revision + 1,
                    expected_candidate_revision=int(candidate_row["revision"]), now=instant,
                    profile_id=candidate_row["profile_id"],
                )
            self._touch_session(connection, before.session_id, owner_user_id, instant)
            self._fault("reserve_proposal_adjustment.before_commit")
            result = self._turn_aggregate(
                connection.execute("SELECT * FROM turns WHERE turn_id = ?", (str(turn_id),)).fetchone()
            )
        self._fault("reserve_proposal_adjustment.after_commit")
        return result

    def release_proposal_adjustment_lease(
        self,
        owner_user_id: UserId,
        turn_id: TurnId,
        lease_token: str,
        *,
        clear_reservation: bool = False,
        now: Optional[datetime] = None,
    ) -> bool:
        """Release only the short admission lease; accepted input and budget survive."""
        self._require_started()
        instant = _aware_now(now)
        with self._transaction() as connection:
            row = self._owned_turn(connection, owner_user_id, turn_id)
            aggregate = self._turn_aggregate(row)
            reservation = aggregate.checkpoint.adjustment_reservation
            if reservation is None or reservation.lease_token != lease_token:
                return False
            checkpoint = (self._close_adjustment_reservation(aggregate.checkpoint)
                          if clear_reservation else aggregate.checkpoint.model_copy(update={
                "adjustment_reservation": reservation.model_copy(update={
                    "lease_token": None, "lease_expires_at": None,
                })
            }))
            self._validate_append_only_bindings(aggregate, aggregate.record, checkpoint)
            changed = connection.execute(
                "UPDATE turns SET checkpoint_json = ?, checkpoint_revision = ?, updated_at = ? "
                "WHERE turn_id = ? AND owner_user_id = ? AND state_revision = ? AND checkpoint_revision = ?",
                (_dump_json(checkpoint), aggregate.checkpoint_revision + 1, _timestamp(instant),
                 str(turn_id), str(owner_user_id), aggregate.record.turn.state_revision,
                 aggregate.checkpoint_revision),
            ).rowcount
            if changed != 1:
                raise StateConflict("turn changed while releasing its adjustment lease")
            return True

    def renew_proposal_adjustment_lease(
        self,
        owner_user_id: UserId,
        turn_id: TurnId,
        lease_token: str,
        *,
        lease_seconds: int = 60,
        now: Optional[datetime] = None,
    ) -> bool:
        """Extend only a still-live token without advancing semantic checkpoint CAS."""
        self._require_started()
        if not 1 <= lease_seconds <= 300:
            raise ValueError("invalid adjustment lease duration")
        instant = _aware_now(now)
        with self._transaction() as connection:
            row = self._owned_turn(connection, owner_user_id, turn_id)
            aggregate = self._turn_aggregate(row)
            reservation = aggregate.checkpoint.adjustment_reservation
            if (
                reservation is None or reservation.lease_token != lease_token
                or reservation.lease_expires_at is None or reservation.lease_expires_at <= instant
                or aggregate.record.turn.state != TurnState.WAIT_CONFIRM
            ):
                return False
            checkpoint = aggregate.checkpoint.model_copy(update={
                "adjustment_reservation": reservation.model_copy(update={
                    "lease_expires_at": instant + timedelta(seconds=lease_seconds),
                })
            })
            changed = connection.execute(
                "UPDATE turns SET checkpoint_json = ?, updated_at = ? "
                "WHERE turn_id = ? AND owner_user_id = ? AND state_revision = ? AND checkpoint_revision = ?",
                (_dump_json(checkpoint), _timestamp(instant), str(turn_id), str(owner_user_id),
                 aggregate.record.turn.state_revision, aggregate.checkpoint_revision),
            ).rowcount
            return changed == 1

    def adjust_proposal(
        self,
        owner_user_id: UserId,
        turn_id: TurnId,
        proposal_id: uuid.UUID,
        request: ResumeProposalAdjustRequest,
        replacement: ProposalRecord,
        *,
        events: Sequence[EventDraft],
        now: Optional[datetime] = None,
    ) -> RequestReceipt:
        """Adjust through two frozen edges and commit their events/proposal/receipt atomically."""
        self._require_started()
        instant = _aware_now(now)
        scope = ApiActionKind.PROPOSAL_ADJUST
        payload_hash = canonical_payload_hash(scope, request, resource_id=turn_id)
        with self._transaction() as connection:
            turn_row = self._owned_turn(connection, owner_user_id, turn_id)
            aggregate = self._turn_aggregate(turn_row)
            assignment = self._candidate_assignment_row(connection, owner_user_id, turn_id)
            if assignment is not None and assignment["profile_id"] == P2_V3_CANDIDATE_PROFILE_ID:
                raise StateConflict("v3 candidate proposal recognition cannot persist a proposal adjustment")
            receipt_key = next(
                (item for item in aggregate.record.request_receipts
                 if item.key_scope == scope and item.resource_id == turn_id
                 and item.client_request_id == request.client_request_id),
                None,
            )
            if receipt_key is not None:
                return self._replay_or_conflict(
                    receipt_key, scope=scope, owner_user_id=owner_user_id, resource_id=turn_id,
                    request_id=request.client_request_id, payload_hash=payload_hash,
            )
            before = aggregate.record.turn
            reservation = aggregate.checkpoint.adjustment_reservation
            reservation_matches = bool(
                reservation is not None
                and reservation.client_request_id == request.client_request_id
                and reservation.payload_hash == payload_hash
                and reservation.proposal_id == proposal_id
                and reservation.expected_proposal_revision == request.expected_proposal_revision
            )
            if reservation is not None and (
                not reservation_matches or reservation.lease_token is None
                or reservation.lease_expires_at is None or reservation.lease_expires_at <= instant
            ):
                raise ProposalConflict("proposal adjustment Runtime lease is no longer current")
            effective_state_revision = before.state_revision if reservation_matches else request.expected_state_revision
            if (before.state != TurnState.WAIT_CONFIRM
                or before.state_revision != effective_state_revision):
                raise StateConflict("proposal adjustment state precondition failed")
            current = self._proposal_by_id(connection, owner_user_id, proposal_id)
            if current.turn_id != turn_id or current.session_id != before.session_id:
                raise StoreNotFound("proposal is not available in this turn")
            replacement = self._preserve_proposal_receipts(current, replacement)
            try:
                validate_proposal_adjustment(
                    current, replacement, expected_proposal_revision=request.expected_proposal_revision
                )
            except ValueError:
                raise ProposalConflict("proposal revision precondition failed") from None
            if len(events) != 3 or [item.type for item in events] != [EventType.STATUS, EventType.STATUS, EventType.PROPOSAL]:
                raise InvariantViolation("proposal adjustment requires running, waiting, and proposal events")
            running = TurnStateSnapshot.model_validate(
                before.model_dump(mode="python", by_alias=True, exclude_none=False)
                | {"state": TurnState.RUNNING, "step": TurnStep.MODEL_DECISION,
                   "state_revision": before.state_revision + 1, "wait_reason": None, "resume_state": None}
            )
            final = TurnStateSnapshot.model_validate(
                running.model_dump(mode="python", by_alias=True, exclude_none=False)
                | {"state": TurnState.WAIT_CONFIRM, "step": TurnStep.AWAITING_USER,
                   "state_revision": running.state_revision + 1,
                   "wait_reason": before.wait_reason, "resume_state": None}
            )
            try:
                validate_state_transition(before, running, expected_state_revision=effective_state_revision)
                validate_state_transition(running, final, expected_state_revision=running.state_revision)
            except ValueError:
                raise StateConflict("proposal adjustment transition precondition failed") from None
            self._validate_status_draft(running, events[0])
            self._validate_status_draft(final, events[1])
            proposal_event = events[2]
            if (
                proposal_event.type != EventType.PROPOSAL
                or proposal_event.payload.proposal_id != proposal_id
                or proposal_event.payload.revision != replacement.revision
            ):
                raise InvariantViolation("proposal event must reference the replacement revision")
            self._validate_proposal_scope(replacement, before)
            sequence = self._next_event_seq(connection, turn_id) + len(events) - 1
            response = ProposalAdjustedAccepted(
                proposal_id=proposal_id,
                proposal_revision=replacement.revision,
                turn_id=turn_id,
                state=TurnState.WAIT_CONFIRM.value,
                state_revision=final.state_revision,
                event_cursor=sequence,
            )
            accepted_adjustment = next((item for item in aggregate.checkpoint.accepted_inputs
                                        if item.action == scope
                                        and item.client_request_id == request.client_request_id), None)
            receipt = RequestReceipt(
                key_scope=scope, owner_user_id=owner_user_id, resource_id=turn_id,
                client_request_id=request.client_request_id, payload_hash=payload_hash,
                http_status=202, response_kind=RequestReceiptKind.PROPOSAL_ADJUSTED,
                response_snapshot=response,
                recorded_at=(accepted_adjustment.accepted_at if reservation is not None
                             and accepted_adjustment is not None else instant),
            )
            if reservation is None:
                next_checkpoint = self._append_accepted_input(
                    aggregate.checkpoint, scope, request, payload_hash, instant,
                    advance_generation=True,
                )
            else:
                if (
                    reservation.client_request_id != request.client_request_id
                    or reservation.payload_hash != payload_hash
                    or reservation.proposal_id != proposal_id
                    or reservation.expected_proposal_revision != request.expected_proposal_revision
                ):
                    raise ProposalConflict("proposal adjustment reservation no longer matches this request")
                next_checkpoint = self._close_adjustment_reservation(aggregate.checkpoint)
            updated_turn = self._record_with_receipt(
                self._record_with_updates(aggregate.record, turn=final), receipt
            )
            self._validate_append_only_bindings(aggregate, updated_turn, next_checkpoint)
            changed = connection.execute(
                "UPDATE proposals SET revision = ?, status = ?, record_json = ?, updated_at = ? "
                "WHERE proposal_id = ? AND owner_user_id = ? AND revision = ? AND status = 'pending'",
                (
                    replacement.revision, replacement.status.value, _dump_json(replacement), _timestamp(instant),
                    str(proposal_id), str(owner_user_id), current.revision,
                ),
            ).rowcount
            if changed != 1:
                raise ProposalConflict("proposal revision changed during adjustment")
            self._append_events(
                connection, turn_id, owner_user_id, before.session_id, events, updated_turn,
                next_checkpoint, status_snapshots=(running, final, None),
            )
            changed = connection.execute(
                "UPDATE turns SET state = ?, state_revision = ?, step = ?, record_json = ?, checkpoint_json = ?, checkpoint_revision = ?, claim_token = NULL, claim_until = NULL, updated_at = ? "
                "WHERE turn_id = ? AND owner_user_id = ? AND state_revision = ? AND checkpoint_revision = ?",
                (
                    final.state.value, final.state_revision, final.step.value,
                    _dump_json(updated_turn), _dump_json(next_checkpoint), aggregate.checkpoint_revision + 1,
                    _timestamp(instant), str(turn_id), str(owner_user_id),
                    before.state_revision, aggregate.checkpoint_revision,
                ),
            ).rowcount
            if changed != 1:
                raise StateConflict("turn changed during proposal adjustment")
            self._touch_session(connection, before.session_id, owner_user_id, instant)
            self._fault("adjust_proposal.before_commit")
        self._fault("adjust_proposal.after_commit")
        return receipt

    def record_confirmation_unavailable(
        self,
        owner_user_id: UserId,
        proposal_id: uuid.UUID,
        request: object,
        response: object,
        *,
        expected_revision: int,
        now: Optional[datetime] = None,
    ) -> RequestReceipt:
        """Persist the frozen P1 501 only after atomic current-proposal validation.

        Receipt lookup deliberately precedes revision, expiry, and nonce checks so an
        exact retry still returns the original response after the proposal has changed.
        The nonce is hashed with the request but is never serialized into the receipt.
        """
        from .contracts import ConfirmationUnavailableResponse, ConfirmProposalRequest

        if not isinstance(request, ConfirmProposalRequest) or not isinstance(response, ConfirmationUnavailableResponse):
            raise TypeError("confirmation receipt requires frozen request and unavailable response models")
        self._require_started()
        instant = _aware_now(now)
        scope = ApiActionKind.PROPOSAL_CONFIRM
        payload_hash = canonical_payload_hash(scope, request, resource_id=proposal_id)
        with self._transaction() as connection:
            current = self._proposal_by_id(connection, owner_user_id, proposal_id)
            stored = next(
                (item for item in current.request_receipts if item.client_request_id == request.client_request_id),
                None,
            )
            if stored is not None:
                return self._replay_or_conflict(
                    stored, scope=scope, owner_user_id=owner_user_id, resource_id=proposal_id,
                    request_id=request.client_request_id, payload_hash=payload_hash,
                )
            if request.expected_proposal_revision != expected_revision or current.revision != expected_revision:
                raise ProposalConflict("proposal revision precondition failed")
            if current.status != ProposalStatus.PENDING or current.execution is not None:
                raise ProposalConflict("proposal is not currently confirmable")
            if current.expires_at <= instant:
                raise ProposalExpired("proposal has expired")
            if current.mode == "backend":
                if (
                    current.command_digest is None
                    or not hmac.compare_digest(current.command_digest, request.command_digest)
                    or current.confirmation_nonce is None
                    or not hmac.compare_digest(current.confirmation_nonce, request.confirmation_nonce)
                ):
                    raise ProposalConflict("proposal confirmation precondition failed")
            elif current.mode != "simulation" or current.execution is not None:
                raise ProposalConflict("proposal mode cannot record an unavailable confirmation")
            turn_row = self._owned_turn(connection, owner_user_id, current.turn_id)
            turn = self._turn_aggregate(turn_row).record.turn
            if turn.state != TurnState.WAIT_CONFIRM or turn.wait_reason != WaitReason.CONFIRM_REQUIRED:
                raise StateConflict("turn is not currently awaiting proposal confirmation")
            receipt = RequestReceipt(
                key_scope=scope, owner_user_id=owner_user_id, resource_id=proposal_id,
                client_request_id=request.client_request_id, payload_hash=payload_hash,
                http_status=501, response_kind=RequestReceiptKind.CONFIRMATION_UNAVAILABLE,
                response_snapshot=response, recorded_at=instant,
            )
            document = current.model_dump(mode="python", by_alias=True, exclude_none=False)
            document["request_receipts"] = [
                *[item.model_dump(mode="python", by_alias=True, exclude_none=False) for item in current.request_receipts],
                receipt.model_dump(mode="python", by_alias=True, exclude_none=False),
            ]
            updated = ProposalRecord.model_validate(document)
            changed = connection.execute(
                "UPDATE proposals SET record_json = ?, updated_at = ? WHERE proposal_id = ? AND owner_user_id = ? AND revision = ? AND status = 'pending'",
                (_dump_json(updated), _timestamp(instant), str(proposal_id), str(owner_user_id), expected_revision),
            ).rowcount
            if changed != 1:
                raise ProposalConflict("proposal changed while recording confirmation response")
            self._fault("record_confirmation_unavailable.before_commit")
        self._fault("record_confirmation_unavailable.after_commit")
        return receipt

    # --- P3a mock write path -------------------------------------------------
    #
    # The business effect happens outside the agent, so this path is deliberately
    # two commits: `confirm_and_dispatch` fixes the execution identity and enters
    # EXECUTING, `apply_mock_execution` commits the effect to the mock ledger, and
    # `settle_mock_execution` records the result. A crash between the last two
    # therefore leaves a recoverable UNKNOWN under the original key, never a
    # silent retry with a new one.

    @staticmethod
    def _mock_ledger_version(connection: sqlite3.Connection, activity_id: str) -> int:
        row = connection.execute(
            "SELECT financial_version FROM mock_ledger_state WHERE activity_id = ?", (activity_id,),
        ).fetchone()
        return int(row["financial_version"]) if row is not None else 0

    def mock_ledger_financial_version(self, activity_id: uuid.UUID) -> int:
        self._require_started()
        with self._connection() as connection:
            return self._mock_ledger_version(connection, str(activity_id))

    def bump_mock_ledger_version(
        self, activity_id: uuid.UUID, *, now: Optional[datetime] = None,
    ) -> int:
        """Stand in for another writer changing the activity after a preview."""
        self._require_started()
        instant = _aware_now(now)
        with self._transaction() as connection:
            version = self._mock_ledger_version(connection, str(activity_id)) + 1
            connection.execute(
                "INSERT INTO mock_ledger_state(activity_id, financial_version, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(activity_id) DO UPDATE SET financial_version = excluded.financial_version, "
                "updated_at = excluded.updated_at",
                (str(activity_id), version, _timestamp(instant)),
            )
            return version

    def read_mock_execution(self, execution_id: uuid.UUID) -> Optional[dict[str, Any]]:
        self._require_started()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM mock_execution_ledger WHERE execution_id = ?", (str(execution_id),),
            ).fetchone()
        if row is None:
            return None
        return {
            "execution_id": row["execution_id"],
            "owner_user_id": row["owner_user_id"],
            "proposal_id": row["proposal_id"],
            "proposal_revision": int(row["proposal_revision"]),
            "operation": row["operation"],
            "command_sha256": row["command_sha256"],
            "applied_at": row["applied_at"],
            "effect": json.loads(row["effect_json"]),
        }

    def count_mock_executions(self, proposal_id: uuid.UUID) -> int:
        self._require_started()
        with self._connection() as connection:
            return int(connection.execute(
                "SELECT COUNT(*) FROM mock_execution_ledger WHERE proposal_id = ?", (str(proposal_id),),
            ).fetchone()[0])

    def confirm_and_dispatch(
        self,
        owner_user_id: UserId,
        proposal_id: uuid.UUID,
        request: Any,
        *,
        expected_state_revision: int,
        expected_proposal_revision: int,
        activity_guard: Optional[Callable[[uuid.UUID], None]] = None,
        now: Optional[datetime] = None,
    ) -> TurnAggregate:
        """Assign the deterministic execution identity and enter EXECUTING."""
        from .contracts import (
            ConfirmProposalRequest, ExecutionIdentity, ExecutionReference, ProposalRecord,
            ProposalStatus, derive_execution_id,
        )
        from .p3_execution import MockExecutionStateError, mock_effect_for_command, require_matching_financial_version

        if not isinstance(request, ConfirmProposalRequest):
            raise TypeError("confirming the mock write path requires the frozen confirm request")
        self._require_started()
        instant = _aware_now(now)
        proposal = self.get_proposal(owner_user_id, proposal_id)
        aggregate = self.get_turn(owner_user_id, proposal.turn_id)
        before = aggregate.record.turn
        if proposal.status != ProposalStatus.PENDING or proposal.execution is not None:
            raise ProposalConflict("proposal is not currently confirmable")
        if proposal.revision != expected_proposal_revision:
            raise ProposalConflict("proposal revision precondition failed")
        if proposal.expires_at <= instant:
            raise ProposalExpired("proposal has expired")
        if before.state != TurnState.WAIT_CONFIRM or before.wait_reason != WaitReason.CONFIRM_REQUIRED:
            raise StateConflict("turn is not currently awaiting proposal confirmation")
        if before.state_revision != expected_state_revision:
            raise StateConflict("turn state revision precondition failed")
        if proposal.mode != "backend" or proposal.canonical_command is None:
            raise MockExecutionStateError("the mock write path requires a backend proposal with a fixed command")
        if (
            proposal.command_digest is None
            or not hmac.compare_digest(proposal.command_digest, request.command_digest)
            or proposal.confirmation_nonce is None
            or not hmac.compare_digest(proposal.confirmation_nonce, request.confirmation_nonce)
        ):
            raise ProposalConflict("proposal confirmation precondition failed")
        # Deriving the effect here validates the fixed command before any state moves.
        effect = mock_effect_for_command(proposal.canonical_command)
        # Permission and Activity lifecycle are re-checked at dispatch, not only
        # when the preview was rendered: a proposal can outlive either.
        if activity_guard is not None:
            activity_guard(effect.activity_id)
        with self._connection() as connection:
            require_matching_financial_version(
                proposal.preconditions,
                self._mock_ledger_version(connection, str(effect.activity_id)),
            )
        execution_id = derive_execution_id(owner_user_id, proposal.proposal_id, proposal.revision)
        identity = ExecutionIdentity(
            execution_id=execution_id, actor_id=owner_user_id,
            proposal_id=proposal.proposal_id, proposal_revision=proposal.revision,
        )
        after = TurnStateSnapshot.model_validate(
            before.model_dump(mode="python")
            | {
                "state": TurnState.EXECUTING, "step": TurnStep.DISPATCH,
                "state_revision": before.state_revision + 1,
                "wait_reason": None, "resume_state": None,
                "execution": identity.model_dump(mode="python"),
                "execution_resolution": None,
            }
        )
        confirmed = ProposalRecord.model_validate(
            proposal.model_dump(mode="python", by_alias=True, exclude_none=False)
            | {
                "status": ProposalStatus.CONFIRMED.value,
                # Once confirmed the proposal must not keep exposing the nonce.
                "confirmation_nonce": None,
                # The proposal keeps the full identity, not just a reference, so the
                # recorded executor and the Turn's identity cannot diverge.
                "execution": identity.model_dump(mode="python"),
            }
        )
        result = self.transition_turn(
            owner_user_id, after,
            expected_state_revision=before.state_revision,
            expected_checkpoint_revision=aggregate.checkpoint_revision,
            events=[self._status_draft(after, instant)],
            updated_proposal=confirmed,
            execution_dispatch=True,
            now=instant,
        )
        self._fault("confirm_and_dispatch.after_commit")
        return result

    def apply_mock_execution(
        self, owner_user_id: UserId, proposal_id: uuid.UUID, *,
        activity_guard: Optional[Callable[[uuid.UUID], None]] = None,
        now: Optional[datetime] = None,
    ) -> dict[str, Any]:
        """Apply the fixed effect exactly once, keyed by the execution identity."""
        from .contracts import ProposalStatus
        from .p3_execution import MockExecutionStateError, mock_effect_for_command, require_matching_financial_version

        self._require_started()
        instant = _aware_now(now)
        with self._transaction() as connection:
            proposal = self._proposal_by_id(connection, owner_user_id, proposal_id)
            if proposal.status != ProposalStatus.CONFIRMED or proposal.execution is None:
                raise MockExecutionStateError("the proposal has no dispatched execution")
            execution_id = str(proposal.execution.execution_id)
            existing = connection.execute(
                "SELECT * FROM mock_execution_ledger WHERE execution_id = ?", (execution_id,),
            ).fetchone()
            if existing is not None:
                return {
                    "applied": False, "execution_id": execution_id,
                    "effect": json.loads(existing["effect_json"]),
                }
            if proposal.canonical_command is None:
                raise MockExecutionStateError("the confirmed proposal has no fixed command")
            effect = mock_effect_for_command(proposal.canonical_command)
            # The dispatch-time decision is re-checked before the effect lands.
            # An already-landed effect returned above is reported, not refused:
            # history is not rewritten by a later archive.
            if activity_guard is not None:
                activity_guard(effect.activity_id)
            require_matching_financial_version(
                proposal.preconditions,
                self._mock_ledger_version(connection, str(effect.activity_id)),
            )
            connection.execute(
                "INSERT INTO mock_execution_ledger(execution_id, owner_user_id, proposal_id, "
                "proposal_revision, operation, command_sha256, activity_id, effect_json, applied_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    execution_id, str(owner_user_id), str(proposal.proposal_id), proposal.revision,
                    effect.operation, effect.command_sha256, str(effect.activity_id),
                    json.dumps(effect.as_payload(), ensure_ascii=False, sort_keys=True),
                    _timestamp(instant),
                ),
            )
            connection.execute(
                "INSERT INTO mock_ledger_state(activity_id, financial_version, updated_at) "
                "VALUES (?, ?, ?) ON CONFLICT(activity_id) DO UPDATE SET "
                "financial_version = excluded.financial_version, updated_at = excluded.updated_at",
                (str(effect.activity_id), effect.next_financial_version(), _timestamp(instant)),
            )
            self._fault("apply_mock_execution.before_commit")
        self._fault("apply_mock_execution.after_commit")
        return {"applied": True, "execution_id": execution_id, "effect": effect.as_payload()}

    def settle_mock_execution(
        self,
        owner_user_id: UserId,
        proposal_id: uuid.UUID,
        resolution: ExecutionResolution,
        *,
        result_code: Optional[str] = None,
        result_summary: Optional[str] = None,
        claim_token: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> TurnAggregate:
        """Record the durable execution result and leave the Turn terminal."""
        from .contracts import (
            ExecutionReference, ExecutionResultPayload, ProposalRecord, ProposalStatus,
        )
        from .p3_execution import MockExecutionStateError

        self._require_started()
        instant = _aware_now(now)
        if resolution not in (ExecutionResolution.SUCCEEDED, ExecutionResolution.REJECTED):
            raise MockExecutionStateError("settlement records a succeeded or rejected execution only")
        proposal = self.get_proposal(owner_user_id, proposal_id)
        aggregate = self.get_turn(owner_user_id, proposal.turn_id)
        before = aggregate.record.turn
        if (
            before.execution is None or proposal.execution is None
            or before.execution.execution_id != proposal.execution.execution_id
        ):
            raise MockExecutionStateError("the proposal and turn do not share one execution identity")
        if before.state not in (TurnState.EXECUTING, TurnState.RECOVERING):
            raise MockExecutionStateError("only a dispatched or recovering execution can be settled")
        if before.execution_resolution not in (None, ExecutionResolution.UNKNOWN, resolution):
            raise MockExecutionStateError("a terminal execution resolution is immutable")
        terminal = TurnState.COMPLETED if resolution == ExecutionResolution.SUCCEEDED else TurnState.FAILED
        after = TurnStateSnapshot.model_validate(
            before.model_dump(mode="python")
            | {
                "state": terminal, "step": TurnStep.TERMINAL,
                "state_revision": before.state_revision + 1,
                "wait_reason": None, "resume_state": None,
                "execution_resolution": resolution.value,
            }
        )
        payload = ExecutionResultPayload(
            execution=ExecutionReference(
                execution_id=before.execution.execution_id,
                proposal_id=before.execution.proposal_id,
                proposal_revision=before.execution.proposal_revision,
            ),
            resolution=resolution,
            result_code=result_code,
            result_summary=result_summary,
        )
        rejected_proposal = None
        if resolution == ExecutionResolution.REJECTED:
            rejected_proposal = ProposalRecord.model_validate(
                proposal.model_dump(mode="python", by_alias=True, exclude_none=False)
                | {"status": ProposalStatus.REJECTED.value}
            )
        return self.transition_turn(
            owner_user_id, after,
            expected_state_revision=before.state_revision,
            expected_checkpoint_revision=aggregate.checkpoint_revision,
            events=[
                EventDraft(
                    type=EventType.EXECUTION_RESULT, occurred_at=instant,
                    simulation=False, payload=payload,
                ),
                self._status_draft(after, instant),
            ],
            updated_proposal=rejected_proposal,
            proposal_result_update=rejected_proposal is not None,
            claim_token=claim_token,
            now=instant,
        )

    def mark_execution_unknown(
        self, owner_user_id: UserId, proposal_id: uuid.UUID, *,
        claim_token: Optional[str] = None, now: Optional[datetime] = None,
    ) -> TurnAggregate:
        """Park a dispatched execution whose effect may have landed as UNKNOWN."""
        from .contracts import ExecutionReference, ExecutionResultPayload
        from .p3_execution import MockExecutionStateError

        self._require_started()
        instant = _aware_now(now)
        proposal = self.get_proposal(owner_user_id, proposal_id)
        aggregate = self.get_turn(owner_user_id, proposal.turn_id)
        before = aggregate.record.turn
        if before.execution is None or proposal.execution is None:
            raise MockExecutionStateError("no execution was dispatched for this proposal")
        if before.state not in (TurnState.EXECUTING, TurnState.RECOVERING):
            raise MockExecutionStateError("only a dispatched execution can become unknown")
        after = TurnStateSnapshot.model_validate(
            before.model_dump(mode="python")
            | {
                "state": TurnState.RECOVERING, "step": TurnStep.RECONCILE,
                "state_revision": before.state_revision + 1,
                "wait_reason": None, "resume_state": None,
                "execution_resolution": ExecutionResolution.UNKNOWN.value,
            }
        )
        payload = ExecutionResultPayload(
            execution=ExecutionReference(
                execution_id=before.execution.execution_id,
                proposal_id=before.execution.proposal_id,
                proposal_revision=before.execution.proposal_revision,
            ),
            resolution=ExecutionResolution.UNKNOWN,
        )
        return self.transition_turn(
            owner_user_id, after,
            expected_state_revision=before.state_revision,
            expected_checkpoint_revision=aggregate.checkpoint_revision,
            events=[
                EventDraft(
                    type=EventType.EXECUTION_RESULT, occurred_at=instant,
                    simulation=False, payload=payload,
                ),
                self._status_draft(after, instant),
            ],
            claim_token=claim_token,
            now=instant,
        )

    def reconcile_mock_execution(
        self, owner_user_id: UserId, turn_id: TurnId, *,
        claim_token: Optional[str] = None,
        activity_guard: Optional[Callable[[uuid.UUID], None]] = None,
        now: Optional[datetime] = None,
    ) -> TurnAggregate:
        """Settle a recovering execution by looking up the original key.

        The lookup precedes any application: if the effect already landed the
        ledger row proves it and nothing is applied twice. If it did not land,
        the same execution identity is applied — never a freshly minted one.
        """
        from .contracts import ExecutionResolution
        from .p3_execution import MockExecutionStateError, MockWriteRefused

        aggregate = self.get_turn(owner_user_id, turn_id)
        turn = aggregate.record.turn
        if turn.execution is None or turn.state != TurnState.RECOVERING:
            raise MockExecutionStateError("only a recovering execution can be reconciled")
        proposal = self.get_proposal(owner_user_id, turn.execution.proposal_id)
        try:
            applied = self.apply_mock_execution(
                owner_user_id, proposal.proposal_id, activity_guard=activity_guard, now=now,
            )
        except MockWriteRefused as exc:
            # Authorized at dispatch, but the Activity no longer accepts the
            # write. The effect never landed, so the honest outcome is a
            # rejection under the original key, never a silent application.
            return self.settle_mock_execution(
                owner_user_id, proposal.proposal_id, ExecutionResolution.REJECTED,
                result_code=exc.code, result_summary=str(exc),
                claim_token=claim_token, now=now,
            )
        summary = "mock expense effect applied" if applied["applied"] else "mock expense effect already applied"
        return self.settle_mock_execution(
            owner_user_id, proposal.proposal_id, ExecutionResolution.SUCCEEDED,
            result_code="mock_expense_created", result_summary=summary,
            claim_token=claim_token, now=now,
        )

    def get_turn(self, owner_user_id: UserId, turn_id: TurnId) -> TurnAggregate:
        self._require_started()
        with self._connection() as connection:
            row = self._owned_turn(connection, owner_user_id, turn_id)
            return self._turn_aggregate(row)

    def read_turn_view(
        self,
        owner_user_id: UserId,
        turn_id: TurnId,
        *,
        after_seq: int = 0,
        limit: int = 100,
    ) -> TurnView:
        """Read record and events from one SQLite snapshot so the cursor is internally consistent."""
        self._require_started()
        if after_seq < 0 or not 1 <= limit <= 500:
            raise ValueError("invalid event cursor or page size")
        with self._connection() as connection:
            connection.execute("BEGIN")
            row = self._owned_turn(connection, owner_user_id, turn_id)
            aggregate = self._turn_aggregate(row)
            self._validate_latest_status(connection, aggregate)
            cursor = int(connection.execute(
                "SELECT COALESCE(MAX(seq), 0) FROM events WHERE turn_id = ? AND owner_user_id = ?",
                (str(turn_id), str(owner_user_id)),
            ).fetchone()[0])
            if after_seq > cursor:
                raise ValueError("event cursor is ahead of the current Turn")
            event_rows = connection.execute(
                "SELECT * FROM events WHERE turn_id = ? AND owner_user_id = ? AND seq > ? ORDER BY seq LIMIT ?",
                (str(turn_id), str(owner_user_id), after_seq, limit + 1),
            ).fetchall()
            has_more = len(event_rows) > limit
            events = tuple(self._event_record(connection, item, aggregate) for item in event_rows[:limit])
            proposal_rows = connection.execute(
                "SELECT * FROM proposals WHERE turn_id = ? AND owner_user_id = ? ORDER BY updated_at DESC, proposal_id DESC LIMIT 8",
                (str(turn_id), str(owner_user_id)),
            ).fetchall()
            proposals = tuple(self._proposal_record(item) for item in proposal_rows)
            connection.execute("COMMIT")
            return TurnView(turn=aggregate, events=events, event_cursor=cursor, has_more=has_more, proposals=proposals)

    def get_session(self, owner_user_id: UserId, session_id: SessionId) -> SessionRecord:
        self._require_started()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ? AND owner_user_id = ?",
                (str(session_id), str(owner_user_id)),
            ).fetchone()
            if row is None:
                raise StoreNotFound("session is not available to this owner")
            return self._session_private(row).record

    def get_proposal(self, owner_user_id: UserId, proposal_id: uuid.UUID) -> ProposalRecord:
        self._require_started()
        with self._connection() as connection:
            return self._proposal_by_id(connection, owner_user_id, proposal_id)

    def find_action_receipt(
        self,
        owner_user_id: UserId,
        resource_id: uuid.UUID,
        request: object,
    ) -> Optional[RequestReceipt]:
        """Owner-scoped replay lookup that routes can run before mutable gate checks."""
        self._require_started()
        from .contracts import ConfirmProposalRequest

        scope = _action_for_request(request)
        payload_hash = canonical_payload_hash(scope, request, resource_id=resource_id)
        with self._connection() as connection:
            if scope == ApiActionKind.PROPOSAL_CONFIRM:
                record = self._proposal_by_id(connection, owner_user_id, resource_id)
                candidates = record.request_receipts
            else:
                row = self._owned_turn(connection, owner_user_id, resource_id)
                candidates = self._turn_aggregate(row).record.request_receipts
            stored = next(
                (item for item in candidates if item.key_scope == scope and item.resource_id == resource_id
                 and item.client_request_id == getattr(request, "client_request_id", None)),
                None,
            )
            if stored is None:
                return None
            return self._replay_or_conflict(
                stored,
                scope=scope,
                owner_user_id=owner_user_id,
                resource_id=resource_id,
                request_id=getattr(request, "client_request_id"),
                payload_hash=payload_hash,
            )

    def find_submit_receipt(
        self,
        owner_user_id: UserId,
        session_id: SessionId,
        request: SubmitTurnRequest,
    ) -> Optional[RequestReceipt]:
        """Check global owner request-key replay without first requiring the Session."""
        self._require_started()
        payload_hash = canonical_payload_hash(ApiActionKind.TURN_SUBMIT, request, resource_id=session_id)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM turns WHERE owner_user_id = ? AND client_request_id = ?",
                (str(owner_user_id), str(request.client_request_id)),
            ).fetchone()
            if row is None:
                return None
            aggregate = self._turn_aggregate(row)
            stored = next(
                (item for item in aggregate.record.request_receipts if item.key_scope == ApiActionKind.TURN_SUBMIT),
                None,
            )
            if stored is None:
                raise InvariantViolation("stored submit request has no original receipt")
            return self._replay_or_conflict(
                stored,
                scope=ApiActionKind.TURN_SUBMIT,
                owner_user_id=owner_user_id,
                resource_id=session_id,
                request_id=request.client_request_id,
                payload_hash=payload_hash,
            )

    def list_sessions(
        self,
        owner_user_id: UserId,
        *,
        before_updated_at: Optional[datetime] = None,
        before_session_id: Optional[SessionId] = None,
        limit: int = 50,
    ) -> SessionPage:
        """Return an owner-filtered keyset page, including active count, in one snapshot."""
        self._require_started()
        if not 1 <= limit <= 100 or ((before_updated_at is None) != (before_session_id is None)):
            raise ValueError("invalid session page arguments")
        parameters: list[object] = [str(owner_user_id)]
        after = ""
        if before_updated_at is not None and before_session_id is not None:
            marker = _timestamp(before_updated_at)
            after = " AND (s.updated_at < ? OR (s.updated_at = ? AND s.session_id < ?))"
            parameters.extend([marker, marker, str(before_session_id)])
        parameters.append(limit + 1)
        with self._connection() as connection:
            connection.execute("BEGIN")
            rows = connection.execute(
                """SELECT s.session_id, s.title, s.created_at, s.updated_at,
                    (SELECT COUNT(*) FROM turns t WHERE t.session_id = s.session_id
                        AND t.owner_user_id = s.owner_user_id
                        AND t.state NOT IN ('COMPLETED','CANCELLED','FAILED')) AS active_turn_count
                    FROM sessions s WHERE s.owner_user_id = ?""" + after +
                " ORDER BY s.updated_at DESC, s.session_id DESC LIMIT ?",
                tuple(parameters),
            ).fetchall()
            has_more = len(rows) > limit
            selected = rows[:limit]
            items = tuple(
                SessionSummary(
                    session_id=uuid.UUID(row["session_id"]),
                    title=row["title"],
                    created_at=_parse_datetime(row["created_at"]),
                    updated_at=_parse_datetime(row["updated_at"]),
                    active_turn_count=int(row["active_turn_count"]),
                )
                for row in selected
            )
            next_updated = _parse_datetime(selected[-1]["updated_at"]) if has_more and selected else None
            next_id = uuid.UUID(selected[-1]["session_id"]) if has_more and selected else None
            connection.execute("COMMIT")
            return SessionPage(items, has_more, next_updated, next_id)

    def get_session_detail(
        self,
        owner_user_id: UserId,
        session_id: SessionId,
        *,
        turn_limit: int = 100,
        proposal_limit: int = 8,
    ) -> SessionDetailView:
        """Read an owner-scoped bounded Session projection from a single SQLite view."""
        self._require_started()
        if not 1 <= turn_limit <= 100 or not 1 <= proposal_limit <= 8:
            raise ValueError("invalid session detail limits")
        with self._connection() as connection:
            connection.execute("BEGIN")
            session_row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ? AND owner_user_id = ?",
                (str(session_id), str(owner_user_id)),
            ).fetchone()
            if session_row is None:
                raise StoreNotFound("session is not available to this owner")
            session = self._session_private(session_row).record
            active = int(connection.execute(
                "SELECT COUNT(*) FROM turns WHERE session_id = ? AND owner_user_id = ? AND state NOT IN ('COMPLETED','CANCELLED','FAILED')",
                (str(session_id), str(owner_user_id)),
            ).fetchone()[0])
            summary = SessionSummary(
                session_id=session.session_id,
                title=session.title,
                created_at=session.created_at,
                updated_at=session.updated_at,
                active_turn_count=active,
            )
            turn_rows = connection.execute(
                "SELECT * FROM turns WHERE session_id = ? AND owner_user_id = ? ORDER BY created_at DESC, turn_id DESC LIMIT ?",
                (str(session_id), str(owner_user_id), turn_limit),
            ).fetchall()
            aggregates = tuple(self._turn_aggregate(row) for row in turn_rows)
            turns = tuple(
                TurnSummary(
                    turn_id=item.record.turn.turn_id,
                    state=item.record.turn.state,
                    state_revision=item.record.turn.state_revision,
                    created_at=_parse_datetime(next(row["created_at"] for row in turn_rows if row["turn_id"] == str(item.record.turn.turn_id))),
                    updated_at=_parse_datetime(next(row["updated_at"] for row in turn_rows if row["turn_id"] == str(item.record.turn.turn_id))),
                )
                for item in aggregates
            )
            proposal_rows = connection.execute(
                """SELECT p.*, t.record_json AS turn_record_json FROM proposals p
                    JOIN turns t ON t.turn_id = p.turn_id AND t.owner_user_id = p.owner_user_id
                    WHERE p.session_id = ? AND p.owner_user_id = ?
                    ORDER BY p.updated_at DESC, p.proposal_id DESC LIMIT ?""",
                (str(session_id), str(owner_user_id), proposal_limit),
            ).fetchall()
            proposals = tuple(self._proposal_record(row) for row in proposal_rows)
            proposal_turn_full = {
                uuid.UUID(row["proposal_id"]): self._turn_aggregate(
                    connection.execute(
                        "SELECT * FROM turns WHERE turn_id = ? AND owner_user_id = ?",
                        (row["turn_id"], str(owner_user_id)),
                    ).fetchone()
                )
                for row in proposal_rows
            }
            proposal_turn_states = {
                proposal_id: aggregate.record.turn for proposal_id, aggregate in proposal_turn_full.items()
            }
            connection.execute("COMMIT")
            return SessionDetailView(session, summary, turns, aggregates, proposals, proposal_turn_states, proposal_turn_full)

    def list_recovery_candidates(self) -> list[RecoveryCandidate]:
        """Return typed recovery instructions without executing, confirming, or mutating work."""
        self._require_started()
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM turns WHERE state IN ('QUEUED','RUNNING','WAIT_INPUT','WAIT_CONFIRM','EXECUTING','RECOVERING') "
                "ORDER BY queue_order, turn_id"
            ).fetchall()
            results: list[RecoveryCandidate] = []
            for row in rows:
                aggregate = self._turn_aggregate(row)
                state = aggregate.record.turn.state
                if state == TurnState.QUEUED:
                    disposition: Literal["queued", "resume_planning", "reconcile_execution", "await_input", "await_confirmation"] = "queued"
                elif state == TurnState.RUNNING and aggregate.record.turn.execution is None:
                    disposition = "resume_planning"
                elif state == TurnState.WAIT_INPUT:
                    disposition = "await_input"
                elif state == TurnState.WAIT_CONFIRM:
                    disposition = "await_confirmation"
                elif state in (TurnState.EXECUTING, TurnState.RECOVERING) or aggregate.record.turn.execution is not None:
                    disposition = "reconcile_execution"
                else:
                    raise InvariantViolation("active turn has no valid recovery disposition")
                results.append(RecoveryCandidate(disposition=disposition, turn=aggregate))
            return results

    def recover_interrupted_turns(self, *, now: Optional[datetime] = None) -> list[TurnAggregate]:
        """Move interrupted RUNNING/EXECUTING rows to their frozen restart checkpoints."""
        self._require_started()
        instant = _aware_now(now)
        recovered: list[TurnAggregate] = []
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM turns WHERE state IN ('RUNNING','EXECUTING') ORDER BY queue_order, turn_id"
            ).fetchall()
            for row in rows:
                aggregate = self._turn_aggregate(row)
                before = aggregate.record.turn
                candidate = self._candidate_assignment_row(connection, before.owner_user_id, before.turn_id)
                if candidate is not None:
                    claim_until = _parse_datetime(row["claim_until"]) if row["claim_until"] else None
                    if row["claim_token"] is not None and claim_until is not None and claim_until > instant:
                        # Runtime.start may attach through a second Store connection while a worker is
                        # still inside this lease. Only an expired/missing lease proves this recovery
                        # path may conservatively charge unknown work and invalidate the candidate.
                        continue
                    if candidate["profile_id"] == P2_CANDIDATE_PROFILE_ID:
                        self._recover_p2_candidate_unknown_reservations(
                            connection, owner_user_id=str(before.owner_user_id),
                            turn_id=str(before.turn_id), now=instant,
                        )
                    else:
                        self._recover_p2_v3_pending_reservations(
                            connection, owner_user_id=str(before.owner_user_id),
                            turn_id=str(before.turn_id), now=instant,
                        )
                if before.execution is None:
                    after = TurnStateSnapshot.model_validate(
                        before.model_dump(mode="python")
                        | {"state": TurnState.QUEUED, "state_revision": before.state_revision + 1,
                           "wait_reason": None, "resume_state": None}
                    )
                else:
                    after = TurnStateSnapshot.model_validate(
                        before.model_dump(mode="python")
                        | {"state": TurnState.RECOVERING, "state_revision": before.state_revision + 1,
                           "step": TurnStep.RECONCILE, "wait_reason": None, "resume_state": None}
                    )
                try:
                    validate_state_transition(before, after, expected_state_revision=before.state_revision)
                except ValueError:
                    raise InvariantViolation("interrupted turn cannot be recovered under the frozen state table") from None
                updated = self._record_with_updates(aggregate.record, turn=after)
                status = self._status_draft(after, instant)
                self._append_events(connection, after.turn_id, before.owner_user_id, before.session_id,
                                    [status], updated, aggregate.checkpoint)
                queue_order = aggregate.queue_order
                if after.state == TurnState.QUEUED:
                    queue_order = int(connection.execute("SELECT COALESCE(MAX(queue_order), 0) + 1 FROM turns").fetchone()[0])
                changed = connection.execute(
                    """UPDATE turns SET state = ?, state_revision = ?, step = ?, record_json = ?,
                        queue_order = ?, claim_token = NULL, claim_until = NULL, updated_at = ?
                    WHERE turn_id = ? AND state_revision = ? AND checkpoint_revision = ?""",
                    (after.state.value, after.state_revision, after.step.value, _dump_json(updated), queue_order,
                     _timestamp(instant), str(after.turn_id), before.state_revision, aggregate.checkpoint_revision),
                ).rowcount
                if changed != 1:
                    raise StateConflict("turn changed during restart recovery")
                if candidate is not None and candidate["profile_id"] == P2_CANDIDATE_PROFILE_ID:
                    current_candidate = connection.execute(
                        "SELECT * FROM p2_candidate_turns WHERE turn_id = ? AND owner_user_id = ?",
                        (str(before.turn_id), str(before.owner_user_id)),
                    ).fetchone()
                    changed = connection.execute(
                        """UPDATE p2_candidate_turns SET claim_epoch = claim_epoch + 1,
                            read_epoch = read_epoch + 1, lifecycle = 'queued',
                            context_revision = ?, turn_state_revision = ?, revision = revision + 1,
                            updated_at = ? WHERE turn_id = ? AND owner_user_id = ? AND revision = ?""",
                        (
                            aggregate.checkpoint_revision, after.state_revision, _timestamp(instant),
                            str(before.turn_id), str(before.owner_user_id), int(current_candidate["revision"]),
                        ),
                    ).rowcount
                    if changed != 1:
                        raise StateConflict("candidate restart invalidation lost its Store CAS")
                elif candidate is not None:
                    current_candidate = connection.execute(
                        "SELECT * FROM p2_v3_turns WHERE turn_id=? AND owner_user_id=?",
                        (str(before.turn_id), str(before.owner_user_id)),
                    ).fetchone()
                    self._update_p2_v3_after_transition(
                        connection, owner_user_id=before.owner_user_id, turn_id=before.turn_id,
                        after=after, checkpoint=aggregate.checkpoint,
                        checkpoint_revision=aggregate.checkpoint_revision,
                        expected_revision=int(current_candidate["revision"]), now=instant,
                    )
                self._touch_session(connection, before.session_id, before.owner_user_id, instant)
                recovered.append(self._turn_aggregate(
                    connection.execute("SELECT * FROM turns WHERE turn_id = ?", (str(after.turn_id),)).fetchone()
                ))
            self._fault("recover_interrupted_turns.before_commit")
        return recovered

    def claim_next(self, worker_id: str, *, lease_seconds: int = 30, now: Optional[datetime] = None) -> Optional[ClaimedTurn]:
        """Atomically claim the oldest eligible queued Turn across Store connections."""
        self._require_started()
        if not worker_id or len(worker_id) > 128 or lease_seconds < 1 or lease_seconds > 3600:
            raise ValueError("invalid worker id or lease duration")
        instant = _aware_now(now)
        lease_until = instant + timedelta(seconds=lease_seconds)
        token = f"{worker_id}:{uuid.uuid4()}"
        with self._transaction() as connection:
            row = connection.execute(
                """SELECT * FROM turns WHERE state = 'QUEUED'
                    AND (claim_until IS NULL OR claim_until <= ?)
                    AND NOT EXISTS (
                        SELECT 1 FROM p2_candidate_turns AS p2 WHERE p2.turn_id = turns.turn_id
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM p2_v3_turns AS p3 WHERE p3.turn_id = turns.turn_id
                    )
                    ORDER BY queue_order, turn_id LIMIT 1""",
                (_timestamp(instant),),
            ).fetchone()
            if row is None:
                return None
            changed = connection.execute(
                "UPDATE turns SET claim_token = ?, claim_until = ? WHERE turn_id = ? AND state = 'QUEUED' "
                "AND (claim_until IS NULL OR claim_until <= ?)",
                (token, _timestamp(lease_until), row["turn_id"], _timestamp(instant)),
            ).rowcount
            if changed != 1:
                return None
            claimed_row = connection.execute("SELECT * FROM turns WHERE turn_id = ?", (row["turn_id"],)).fetchone()
            self._fault("claim_next.before_commit")
            aggregate = self._turn_aggregate(claimed_row)
        self._fault("claim_next.after_commit")
        return ClaimedTurn(turn=aggregate, claim_token=token, claim_until=lease_until)

    def claim_runnable(
        self, worker_id: str, *, lease_seconds: int = 30,
        exclude_turn_ids: Sequence[TurnId] = (), now: Optional[datetime] = None,
        cancellation_event: Optional[threading.Event] = None,
        candidate_profile_id: Optional[str] = None,
        enabled_candidate_profile_ids: Optional[Sequence[str]] = None,
    ) -> Optional[ClaimedTurn]:
        """Claim the oldest unowned planning or execution-recovery checkpoint."""
        self._require_started()
        if not worker_id or len(worker_id) > 128 or lease_seconds < 1 or lease_seconds > 3600:
            raise ValueError("invalid worker id or lease duration")
        if candidate_profile_id not in (None, P2_CANDIDATE_PROFILE_ID, P2_V3_CANDIDATE_PROFILE_ID):
            raise ValueError("unknown server-side candidate profile")
        if enabled_candidate_profile_ids is not None:
            if candidate_profile_id is not None or isinstance(enabled_candidate_profile_ids, str):
                raise ValueError("mixed candidate selection cannot be combined with a single-profile selector")
            if any(item not in (P2_CANDIDATE_PROFILE_ID, P2_V3_CANDIDATE_PROFILE_ID)
                   for item in enabled_candidate_profile_ids):
                raise ValueError("mixed candidate selection contains an unknown server-side profile")
            enabled_candidate_profile_ids = tuple(dict.fromkeys(enabled_candidate_profile_ids))
        with self._claim_lifecycle_lock:
            self._cleanup_retired_claim_workers_locked()
            if cancellation_event is not None and cancellation_event.is_set():
                return None
            try:
                claimed = self._claim_runnable_transaction(
                    worker_id, lease_seconds=lease_seconds,
                    exclude_turn_ids=exclude_turn_ids, now=now,
                    candidate_profile_id=candidate_profile_id,
                    enabled_candidate_profile_ids=enabled_candidate_profile_ids,
                )
            except Exception:
                if (
                    cancellation_event is not None and cancellation_event.is_set()
                    or self._claim_worker_is_retired(worker_id)
                ):
                    self._release_claim_worker_prefix_locked(worker_id)
                raise
            if claimed is not None and (
                cancellation_event is not None and cancellation_event.is_set()
                or self._claim_worker_is_retired(worker_id)
            ):
                self._release_claim_locked(claimed.turn.record.turn.turn_id, claimed.claim_token)
                return None
            return claimed

    def _claim_runnable_transaction(
        self, worker_id: str, *, lease_seconds: int = 30,
        exclude_turn_ids: Sequence[TurnId] = (), now: Optional[datetime] = None,
        candidate_profile_id: Optional[str] = None,
        enabled_candidate_profile_ids: Optional[Sequence[str]] = None,
    ) -> Optional[ClaimedTurn]:
        self._require_started()
        if not worker_id or len(worker_id) > 128 or lease_seconds < 1 or lease_seconds > 3600:
            raise ValueError("invalid worker id or lease duration")
        instant = _aware_now(now)
        lease_until = instant + timedelta(seconds=lease_seconds)
        token = f"{worker_id}:{uuid.uuid4()}"
        now_text = _timestamp(instant)
        exclusions = tuple(str(item) for item in exclude_turn_ids)
        excluded_sql = " AND candidate.turn_id NOT IN (" + ",".join("?" for _ in exclusions) + ")" if exclusions else ""
        if enabled_candidate_profile_ids is None:
            if candidate_profile_id is None:
                assignment_sql = """(
                    NOT EXISTS (SELECT 1 FROM p2_candidate_turns p2 WHERE p2.turn_id=candidate.turn_id)
                    AND NOT EXISTS (SELECT 1 FROM p2_v3_turns p3 WHERE p3.turn_id=candidate.turn_id)
                )"""
                assignment_args: tuple[object, ...] = ()
            elif candidate_profile_id == P2_CANDIDATE_PROFILE_ID:
                assignment_sql = """EXISTS (SELECT 1 FROM p2_candidate_turns p2
                    WHERE p2.turn_id=candidate.turn_id AND p2.owner_user_id=candidate.owner_user_id AND p2.profile_id=?)"""
                assignment_args = (candidate_profile_id,)
            else:
                assignment_sql = """EXISTS (SELECT 1 FROM p2_v3_turns p3
                    WHERE p3.turn_id=candidate.turn_id AND p3.owner_user_id=candidate.owner_user_id AND p3.profile_id=?)"""
                assignment_args = (candidate_profile_id,)
        else:
            selected = set(enabled_candidate_profile_ids)
            candidate_terms: list[str] = []
            assignment_values: list[object] = []
            if P2_CANDIDATE_PROFILE_ID in selected:
                candidate_terms.append("EXISTS (SELECT 1 FROM p2_candidate_turns p2 WHERE p2.turn_id=candidate.turn_id AND p2.owner_user_id=candidate.owner_user_id AND p2.profile_id=?)")
                assignment_values.append(P2_CANDIDATE_PROFILE_ID)
            if P2_V3_CANDIDATE_PROFILE_ID in selected:
                candidate_terms.append("EXISTS (SELECT 1 FROM p2_v3_turns p3 WHERE p3.turn_id=candidate.turn_id AND p3.owner_user_id=candidate.owner_user_id AND p3.profile_id=?)")
                assignment_values.append(P2_V3_CANDIDATE_PROFILE_ID)
            candidate_terms.insert(0, "(NOT EXISTS (SELECT 1 FROM p2_candidate_turns p2 WHERE p2.turn_id=candidate.turn_id) AND NOT EXISTS (SELECT 1 FROM p2_v3_turns p3 WHERE p3.turn_id=candidate.turn_id))")
            assignment_sql = "(" + " OR ".join(candidate_terms) + ")"
            assignment_args = tuple(assignment_values)
        with self._transaction() as connection:
            row = connection.execute(
                """SELECT candidate.* FROM turns AS candidate
                    WHERE candidate.state IN ('QUEUED','RUNNING','RECOVERING')
                    AND (candidate.claim_until IS NULL OR candidate.claim_until <= ?)
                    AND ((candidate.state IN ('QUEUED','RUNNING') AND candidate.execution_id IS NULL)
                         OR (candidate.state = 'RECOVERING' AND candidate.execution_id IS NOT NULL))
                    AND NOT EXISTS (
                        SELECT 1 FROM turns AS active
                        WHERE active.owner_user_id = candidate.owner_user_id
                          AND active.turn_id != candidate.turn_id
                          AND active.state = 'RUNNING'
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM turns AS reserved
                        WHERE reserved.owner_user_id = candidate.owner_user_id
                          AND reserved.turn_id != candidate.turn_id
                          AND reserved.state = 'WAIT_CONFIRM'
                          AND julianday(json_extract(reserved.checkpoint_json,
                              '$.adjustment_reservation.lease_expires_at')) > julianday(?)
                    )
                    AND """ + assignment_sql + excluded_sql + """
                    ORDER BY CASE candidate.state WHEN 'RUNNING' THEN 0 WHEN 'RECOVERING' THEN 1 ELSE 2 END,
                             candidate.queue_order, candidate.turn_id LIMIT 1""",
                (now_text, now_text, *assignment_args, *exclusions),
            ).fetchone()
            if row is None:
                return None
            changed = connection.execute(
                "UPDATE turns SET claim_token = ?, claim_until = ? WHERE turn_id = ? AND state = ? "
                "AND (claim_until IS NULL OR claim_until <= ?)",
                (token, _timestamp(lease_until), row["turn_id"], row["state"], now_text),
            ).rowcount
            if changed != 1:
                return None
            assignment = self._candidate_assignment_row(
                connection, uuid.UUID(row["owner_user_id"]), uuid.UUID(row["turn_id"]),
            )
            selected_profile = assignment["profile_id"] if assignment is not None else None
            if selected_profile is not None:
                if selected_profile == P2_CANDIDATE_PROFILE_ID:
                    self._claim_p2_candidate_in_transaction(
                        connection, owner_user_id=uuid.UUID(row["owner_user_id"]),
                        turn_id=uuid.UUID(row["turn_id"]), now=instant,
                    )
                else:
                    self._claim_p2_v3_in_transaction(
                        connection, owner_user_id=uuid.UUID(row["owner_user_id"]),
                        turn_id=uuid.UUID(row["turn_id"]), now=instant,
                    )
            claimed_row = connection.execute("SELECT * FROM turns WHERE turn_id = ?", (row["turn_id"],)).fetchone()
            self._fault("claim_runnable.before_commit")
            aggregate = self._turn_aggregate(claimed_row)
        self._fault("claim_runnable.after_commit")
        return ClaimedTurn(
            turn=aggregate, claim_token=token, claim_until=lease_until,
            execution_profile_id=selected_profile,
        )

    def mark_claim_worker_retired(self, worker_id: str) -> None:
        """Synchronously mark a Runtime worker stale before any bounded async drain."""
        if not worker_id or len(worker_id) > 128:
            raise ValueError("invalid worker id")
        with self._claim_workers_lock:
            self._retired_claim_workers.add(worker_id)

    def cleanup_retired_claim_workers(self) -> None:
        """Clear retired worker leases after their claim calls have serialized."""
        with self._claim_lifecycle_lock:
            self._cleanup_retired_claim_workers_locked()

    def _claim_worker_is_retired(self, worker_id: str) -> bool:
        with self._claim_workers_lock:
            return worker_id in self._retired_claim_workers

    def _cleanup_retired_claim_workers_locked(self) -> None:
        with self._claim_workers_lock:
            worker_ids = tuple(self._retired_claim_workers)
        if not worker_ids or not self._started:
            return
        with self._transaction() as connection:
            for worker_id in worker_ids:
                self._release_claim_worker_prefix_in_transaction(connection, worker_id)
        with self._claim_workers_lock:
            self._retired_claim_workers.difference_update(worker_ids)

    def _release_claim_worker_prefix_locked(self, worker_id: str) -> None:
        with self._transaction() as connection:
            self._release_claim_worker_prefix_in_transaction(connection, worker_id)

    def _release_claim_worker_prefix_in_transaction(self, connection: sqlite3.Connection, worker_id: str) -> None:
        prefix = f"{worker_id}:"
        now = _aware_now(None)
        rows = connection.execute(
            """SELECT turns.turn_id, turns.owner_user_id, turns.state, turns.state_revision,
                      turns.checkpoint_revision, p2_candidate_turns.revision AS v2_revision,
                      p2_v3_turns.revision AS v3_revision
                FROM turns
                LEFT JOIN p2_candidate_turns USING (turn_id, owner_user_id)
                LEFT JOIN p2_v3_turns USING (turn_id, owner_user_id)
                WHERE turns.state IN ('QUEUED','RUNNING','RECOVERING')
                  AND (p2_candidate_turns.turn_id IS NOT NULL OR p2_v3_turns.turn_id IS NOT NULL)
                  AND substr(turns.claim_token, 1, ?) = ?""",
            (len(prefix), prefix),
        ).fetchall()
        connection.execute(
            "UPDATE turns SET claim_token = NULL, claim_until = NULL "
            "WHERE state IN ('QUEUED','RUNNING','RECOVERING') "
            "AND substr(claim_token, 1, ?) = ?",
            (len(prefix), prefix),
        )
        now_text = _timestamp(now)
        for row in rows:
            if row["v2_revision"] is not None:
                changed = connection.execute(
                    """UPDATE p2_candidate_turns SET claim_epoch = claim_epoch + 1,
                        read_epoch = read_epoch + 1, lifecycle = 'queued', context_revision = ?,
                        turn_state_revision = ?, revision = revision + 1, updated_at = ?
                        WHERE turn_id = ? AND owner_user_id = ? AND revision = ?""",
                    (
                        int(row["checkpoint_revision"]), int(row["state_revision"]), now_text,
                        row["turn_id"], row["owner_user_id"], int(row["v2_revision"]),
                    ),
                ).rowcount
                if changed != 1:
                    raise StateConflict("candidate retired-worker invalidation lost its Store CAS")
            else:
                self._recover_p2_v3_pending_reservations(
                    connection, owner_user_id=row["owner_user_id"], turn_id=row["turn_id"], now=now,
                )
                current = connection.execute(
                    "SELECT * FROM p2_v3_turns WHERE turn_id=? AND owner_user_id=?",
                    (row["turn_id"], row["owner_user_id"]),
                ).fetchone()
                snapshot = self._p2_v3_snapshot(current)
                changed = connection.execute(
                    """UPDATE p2_v3_turns SET claim_epoch=claim_epoch+1,authority_epoch=authority_epoch+1,
                        lifecycle='queued',context_revision=?,turn_state_revision=?,revision=revision+1,updated_at=?
                        WHERE turn_id=? AND owner_user_id=? AND revision=? AND claim_epoch=? AND authority_epoch=?""",
                    (
                        int(row["checkpoint_revision"]), int(row["state_revision"]), now_text,
                        row["turn_id"], row["owner_user_id"], snapshot.revision,
                        snapshot.claim_epoch, snapshot.authority_epoch,
                    ),
                ).rowcount
                if changed != 1:
                    raise StateConflict("v3 retired-worker invalidation lost its Store CAS")

    def _release_claim_locked(self, turn_id: TurnId, claim_token: str) -> bool:
        with self._transaction() as connection:
            target = connection.execute(
                "SELECT owner_user_id FROM turns WHERE turn_id = ? AND claim_token = ?",
                (str(turn_id), claim_token),
            ).fetchone()
            changed = connection.execute(
                "UPDATE turns SET claim_token = NULL, claim_until = NULL WHERE turn_id = ? AND claim_token = ? "
                "AND state IN ('QUEUED','RUNNING','RECOVERING')",
                (str(turn_id), claim_token),
            ).rowcount
            if changed == 1 and target is not None:
                self._invalidate_p2_claim_release_in_transaction(
                    connection, owner_user_id=target["owner_user_id"], turn_id=str(turn_id), now=_aware_now(None),
                )
            return changed == 1

    def renew_claim(self, turn_id: TurnId, claim_token: str, *, lease_seconds: int = 30,
                    now: Optional[datetime] = None) -> bool:
        self._require_started()
        if lease_seconds < 1 or lease_seconds > 3600:
            raise ValueError("invalid claim lease")
        instant = _aware_now(now)
        with self._transaction() as connection:
            changed = connection.execute(
                "UPDATE turns SET claim_until = ? WHERE turn_id = ? AND claim_token = ? "
                "AND state IN ('QUEUED','RUNNING','RECOVERING') AND claim_until > ?",
                (_timestamp(instant + timedelta(seconds=lease_seconds)), str(turn_id), claim_token, _timestamp(instant)),
            ).rowcount
            return changed == 1

    def release_claim(self, turn_id: TurnId, claim_token: str) -> bool:
        self._require_started()
        with self._transaction() as connection:
            target = connection.execute(
                "SELECT owner_user_id FROM turns WHERE turn_id = ? AND claim_token = ?",
                (str(turn_id), claim_token),
            ).fetchone()
            changed = connection.execute(
                "UPDATE turns SET claim_token = NULL, claim_until = NULL WHERE turn_id = ? AND claim_token = ? "
                "AND state IN ('QUEUED','RUNNING','RECOVERING')",
                (str(turn_id), claim_token),
            ).rowcount
            if changed == 1 and target is not None:
                self._invalidate_p2_claim_release_in_transaction(
                    connection, owner_user_id=target["owner_user_id"], turn_id=str(turn_id), now=_aware_now(None),
                )
            return changed == 1

    def _invalidate_p2_claim_release_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        owner_user_id: str,
        turn_id: str,
        now: datetime,
    ) -> None:
        candidate = connection.execute(
            "SELECT revision FROM p2_candidate_turns WHERE turn_id = ? AND owner_user_id = ?",
            (turn_id, owner_user_id),
        ).fetchone()
        turn = connection.execute(
            "SELECT state_revision, checkpoint_revision FROM turns WHERE turn_id = ? AND owner_user_id = ?",
            (turn_id, owner_user_id),
        ).fetchone()
        if turn is None:
            raise InvariantViolation("candidate Turn disappeared during claim release")
        if candidate is not None:
            changed = connection.execute(
                """UPDATE p2_candidate_turns SET claim_epoch = claim_epoch + 1,
                    read_epoch = read_epoch + 1, lifecycle = 'queued', context_revision = ?,
                    turn_state_revision = ?, revision = revision + 1, updated_at = ?
                    WHERE turn_id = ? AND owner_user_id = ? AND revision = ?""",
                (
                    int(turn["checkpoint_revision"]), int(turn["state_revision"]), _timestamp(now),
                    turn_id, owner_user_id, int(candidate["revision"]),
                ),
            ).rowcount
            if changed != 1:
                raise StateConflict("candidate claim-release invalidation lost its Store CAS")
            return
        v3 = connection.execute(
            "SELECT * FROM p2_v3_turns WHERE turn_id=? AND owner_user_id=?",
            (turn_id, owner_user_id),
        ).fetchone()
        if v3 is None:
            return
        self._recover_p2_v3_pending_reservations(
            connection, owner_user_id=owner_user_id, turn_id=turn_id, now=now,
        )
        current = connection.execute(
            "SELECT * FROM p2_v3_turns WHERE turn_id=? AND owner_user_id=?",
            (turn_id, owner_user_id),
        ).fetchone()
        snapshot = self._p2_v3_snapshot(current)
        changed = connection.execute(
            """UPDATE p2_v3_turns SET claim_epoch=claim_epoch+1,authority_epoch=authority_epoch+1,
                lifecycle='queued',context_revision=?,turn_state_revision=?,revision=revision+1,updated_at=?
                WHERE turn_id=? AND owner_user_id=? AND revision=? AND claim_epoch=? AND authority_epoch=?""",
            (
                int(turn["checkpoint_revision"]), int(turn["state_revision"]), _timestamp(now),
                turn_id, owner_user_id, snapshot.revision, snapshot.claim_epoch, snapshot.authority_epoch,
            ),
        ).rowcount
        if changed != 1:
            raise StateConflict("v3 claim-release invalidation lost its Store CAS")

    def get_p2_candidate_snapshot(self, owner_user_id: UserId, turn_id: TurnId) -> CandidateTurnSnapshot:
        """Return only the owner-scoped private budget/lifecycle summary."""
        self._require_started()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM p2_candidate_turns WHERE turn_id = ? AND owner_user_id = ?",
                (str(turn_id), str(owner_user_id)),
            ).fetchone()
            if row is None:
                raise StoreNotFound("candidate Turn is not available to this owner")
            return self._p2_candidate_snapshot(row)

    @staticmethod
    def _p2_candidate_snapshot(row: sqlite3.Row) -> CandidateTurnSnapshot:
        values = {
            name: row["turn_state_revision" if name == "state_revision" else name]
            for name in CandidateTurnSnapshot.model_fields
        }
        values["unknown_consumption"] = bool(values["unknown_consumption"])
        return CandidateTurnSnapshot.model_validate(values, strict=True)

    def _insert_p2_candidate_turn(
        self,
        connection: sqlite3.Connection,
        *,
        owner_user_id: UserId,
        turn_id: TurnId,
        profile_id: str,
        generation: int,
        input_seq: int,
        input_digest: str,
        context_revision: int,
        state_revision: int,
        lifecycle: str,
        now: datetime,
    ) -> None:
        if profile_id != P2_CANDIDATE_PROFILE_ID:
            raise ValueError("unknown server-side candidate profile")
        snapshot = CandidateTurnSnapshot.model_validate({
            "profile_id": profile_id,
            "owner_user_id": str(owner_user_id),
            "turn_id": str(turn_id),
            "generation": generation,
            "input_seq": input_seq,
            "input_digest": input_digest,
            "context_revision": context_revision,
            "state_revision": state_revision,
            "lifecycle": lifecycle,
        }, strict=True)
        connection.execute(
            """INSERT INTO p2_candidate_turns (
                turn_id, owner_user_id, profile_id, generation, input_seq, input_digest,
                context_revision, turn_state_revision, claim_epoch, read_epoch, lifecycle,
                revision, model_calls, logical_read_calls, repair_calls, active_used_us,
                active_reserved_us, backend_used_us, backend_reserved_us, get_attempts,
                response_bytes, bytes_reserved, unknown_consumption, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snapshot.turn_id, snapshot.owner_user_id, snapshot.profile_id,
                snapshot.generation, snapshot.input_seq, snapshot.input_digest,
                snapshot.context_revision, snapshot.state_revision, snapshot.claim_epoch,
                snapshot.read_epoch, snapshot.lifecycle, snapshot.revision, snapshot.model_calls,
                snapshot.logical_read_calls, snapshot.repair_calls, snapshot.active_used_us,
                snapshot.active_reserved_us, snapshot.backend_used_us, snapshot.backend_reserved_us,
                snapshot.get_attempts, snapshot.response_bytes, snapshot.bytes_reserved,
                int(snapshot.unknown_consumption), _timestamp(now), _timestamp(now),
            ),
        )

    @staticmethod
    def _p2_lifecycle_for_state(state: TurnState) -> str:
        if state in (TurnState.QUEUED, TurnState.RECOVERING):
            return "queued"
        if state in (TurnState.RUNNING, TurnState.EXECUTING):
            return "active"
        if state in (TurnState.COMPLETED, TurnState.CANCELLED, TurnState.FAILED):
            return "terminal"
        return "waiting"

    @staticmethod
    def _p2_input_binding(checkpoint: TurnCheckpoint) -> tuple[int, str]:
        relevant = [
            (index, item)
            for index, item in enumerate(checkpoint.accepted_inputs, start=1)
            if item.action in (
                ApiActionKind.TURN_SUBMIT,
                ApiActionKind.CLARIFICATION_RESUME,
                ApiActionKind.PROPOSAL_ADJUST,
            )
        ]
        if not relevant:
            raise InvariantViolation("candidate Turn lost its accepted planning input")
        index, accepted = relevant[-1]
        return index, accepted.payload_hash

    @staticmethod
    def _candidate_assignment_row(
        connection: sqlite3.Connection, owner_user_id: UserId, turn_id: TurnId,
    ) -> Optional[sqlite3.Row]:
        v2 = connection.execute(
            "SELECT * FROM p2_candidate_turns WHERE turn_id=? AND owner_user_id=?",
            (str(turn_id), str(owner_user_id)),
        ).fetchone()
        v3 = connection.execute(
            "SELECT * FROM p2_v3_turns WHERE turn_id=? AND owner_user_id=?",
            (str(turn_id), str(owner_user_id)),
        ).fetchone()
        if v2 is not None and v3 is not None:
            raise InvariantViolation("Turn is assigned to multiple candidate Store families")
        return v2 if v2 is not None else v3

    @staticmethod
    def _require_candidate_profile_for_turn(
        connection: sqlite3.Connection,
        owner_user_id: UserId,
        turn_id: TurnId,
        candidate_profile_id: Optional[str],
    ) -> Optional[sqlite3.Row]:
        if candidate_profile_id not in (None, P2_CANDIDATE_PROFILE_ID, P2_V3_CANDIDATE_PROFILE_ID):
            raise ValueError("unknown server-side candidate profile")
        candidate = SQLiteAgentStore._candidate_assignment_row(connection, owner_user_id, turn_id)
        if candidate is None:
            if candidate_profile_id is not None:
                raise StoreNotFound("Turn is not assigned to this candidate profile")
            return None
        if candidate_profile_id != candidate["profile_id"]:
            raise StateConflict("default-off canonical worker cannot execute a candidate-profile Turn")
        return candidate

    def _update_candidate_after_transition(self, connection: sqlite3.Connection, **kwargs: Any) -> None:
        if kwargs["profile_id"] == P2_V3_CANDIDATE_PROFILE_ID:
            kwargs.pop("profile_id", None)
            kwargs["expected_revision"] = kwargs.pop("expected_candidate_revision")
            self._update_p2_v3_after_transition(connection, **kwargs)
        else:
            kwargs.pop("profile_id", None)
            self._update_p2_candidate_after_transition(connection, **kwargs)

    def _update_candidate_after_action(self, connection: sqlite3.Connection, **kwargs: Any) -> None:
        if kwargs["profile_id"] == P2_V3_CANDIDATE_PROFILE_ID:
            kwargs.pop("profile_id", None)
            kwargs["expected_revision"] = kwargs.pop("expected_candidate_revision")
            self._update_p2_v3_after_action(connection, **kwargs)
        else:
            kwargs.pop("profile_id", None)
            self._update_p2_candidate_after_action(connection, **kwargs)

    def _sync_candidate_checkpoint(self, connection: sqlite3.Connection, **kwargs: Any) -> None:
        if kwargs["profile_id"] == P2_V3_CANDIDATE_PROFILE_ID:
            kwargs.pop("profile_id", None)
            kwargs["expected_revision"] = kwargs.pop("expected_candidate_revision")
            self._sync_p2_v3_checkpoint(connection, **kwargs)
        else:
            kwargs.pop("profile_id", None)
            self._sync_p2_candidate_checkpoint(connection, **kwargs)

    def _update_p2_candidate_after_transition(
        self,
        connection: sqlite3.Connection,
        *,
        owner_user_id: UserId,
        turn_id: TurnId,
        after: TurnStateSnapshot,
        checkpoint: TurnCheckpoint,
        checkpoint_revision: int,
        expected_candidate_revision: int,
        now: datetime,
    ) -> None:
        current = connection.execute(
            "SELECT * FROM p2_candidate_turns WHERE turn_id = ? AND owner_user_id = ?",
            (str(turn_id), str(owner_user_id)),
        ).fetchone()
        if current is None:
            raise InvariantViolation("candidate assignment disappeared during Turn transition")
        snapshot = self._p2_candidate_snapshot(current)
        if snapshot.revision != expected_candidate_revision:
            raise StateConflict("candidate Store revision changed during Turn transition")
        leaving_active = after.state != TurnState.RUNNING
        if leaving_active and snapshot.active_reserved_us:
            raise StateConflict("candidate stage must drain and settle before entering a waiting or terminal state")
        input_seq, input_digest = self._p2_input_binding(checkpoint)
        generation_changed = checkpoint.generation != snapshot.generation
        if checkpoint.generation < snapshot.generation or (generation_changed and input_digest == snapshot.input_digest):
            raise InvariantViolation("candidate generation must advance with a new accepted input")
        invalidate = leaving_active or generation_changed
        changed = connection.execute(
            """UPDATE p2_candidate_turns SET generation = ?, input_seq = ?, input_digest = ?,
                context_revision = ?, turn_state_revision = ?,
                claim_epoch = claim_epoch + ?, read_epoch = read_epoch + ?,
                lifecycle = ?, revision = revision + 1, updated_at = ?
                WHERE turn_id = ? AND owner_user_id = ? AND revision = ?
                  AND generation = ? AND claim_epoch = ? AND read_epoch = ?""",
            (
                checkpoint.generation, input_seq, input_digest, checkpoint_revision,
                after.state_revision, int(invalidate), int(invalidate),
                self._p2_lifecycle_for_state(after.state), _timestamp(now),
                str(turn_id), str(owner_user_id), snapshot.revision,
                snapshot.generation, snapshot.claim_epoch, snapshot.read_epoch,
            ),
        ).rowcount
        if changed != 1:
            raise StateConflict("candidate Turn lifecycle update lost its Store CAS")

    def _update_p2_candidate_after_action(
        self,
        connection: sqlite3.Connection,
        *,
        owner_user_id: UserId,
        turn_id: TurnId,
        after: TurnStateSnapshot,
        checkpoint: TurnCheckpoint,
        checkpoint_revision: int,
        expected_candidate_revision: int,
        now: datetime,
    ) -> None:
        current = connection.execute(
            "SELECT * FROM p2_candidate_turns WHERE turn_id = ? AND owner_user_id = ?",
            (str(turn_id), str(owner_user_id)),
        ).fetchone()
        if current is None:
            raise InvariantViolation("candidate assignment disappeared during accepted action")
        snapshot = self._p2_candidate_snapshot(current)
        if snapshot.revision != expected_candidate_revision:
            raise StateConflict("candidate Store revision changed during accepted action")
        input_seq, input_digest = self._p2_input_binding(checkpoint)
        generation_changed = checkpoint.generation != snapshot.generation
        if checkpoint.generation < snapshot.generation or (generation_changed and input_digest == snapshot.input_digest):
            raise InvariantViolation("candidate generation must advance with a new accepted input")
        changed = connection.execute(
            """UPDATE p2_candidate_turns SET generation = ?, input_seq = ?, input_digest = ?,
                context_revision = ?, turn_state_revision = ?,
                claim_epoch = claim_epoch + 1, read_epoch = read_epoch + 1,
                lifecycle = ?, revision = revision + 1, updated_at = ?
                WHERE turn_id = ? AND owner_user_id = ? AND revision = ?
                  AND generation = ? AND claim_epoch = ? AND read_epoch = ?""",
            (
                checkpoint.generation, input_seq, input_digest, checkpoint_revision,
                after.state_revision, self._p2_lifecycle_for_state(after.state), _timestamp(now),
                str(turn_id), str(owner_user_id), snapshot.revision,
                snapshot.generation, snapshot.claim_epoch, snapshot.read_epoch,
            ),
        ).rowcount
        if changed != 1:
            raise StateConflict("candidate accepted-action invalidation lost its Store CAS")

    def _sync_p2_candidate_checkpoint(
        self,
        connection: sqlite3.Connection,
        *,
        owner_user_id: UserId,
        turn_id: TurnId,
        checkpoint_revision: int,
        state_revision: int,
        expected_candidate_revision: int,
        now: datetime,
    ) -> None:
        current = connection.execute(
            "SELECT * FROM p2_candidate_turns WHERE turn_id = ? AND owner_user_id = ?",
            (str(turn_id), str(owner_user_id)),
        ).fetchone()
        if current is None:
            raise InvariantViolation("candidate assignment disappeared while synchronizing checkpoint revision")
        snapshot = self._p2_candidate_snapshot(current)
        if snapshot.revision != expected_candidate_revision:
            raise StateConflict("candidate Store revision changed while synchronizing checkpoint revision")
        changed = connection.execute(
            """UPDATE p2_candidate_turns SET context_revision = ?, turn_state_revision = ?,
                revision = revision + 1, updated_at = ?
                WHERE turn_id = ? AND owner_user_id = ? AND revision = ?
                  AND generation = ? AND claim_epoch = ? AND read_epoch = ?""",
            (
                checkpoint_revision, state_revision, _timestamp(now), str(turn_id),
                str(owner_user_id), snapshot.revision, snapshot.generation,
                snapshot.claim_epoch, snapshot.read_epoch,
            ),
        ).rowcount
        if changed != 1:
            raise StateConflict("candidate checkpoint synchronization lost its Store CAS")

    def _p2_candidate_active_context(
        self,
        connection: sqlite3.Connection,
        owner_user_id: UserId,
        turn_id: TurnId,
        *,
        claim_token: str,
        expected_state_revision: int,
        expected_checkpoint_revision: int,
        expected_candidate_revision: int,
        now: datetime,
    ) -> tuple[sqlite3.Row, CandidateTurnSnapshot, TurnAggregate]:
        turn_row = self._owned_turn(connection, owner_user_id, turn_id)
        aggregate = self._turn_aggregate(turn_row)
        self._check_claim(aggregate, claim_token, now)
        if aggregate.record.turn.state != TurnState.RUNNING:
            raise StateConflict("candidate worker action requires the current RUNNING Turn")
        candidate_row = connection.execute(
            "SELECT * FROM p2_candidate_turns WHERE turn_id = ? AND owner_user_id = ?",
            (str(turn_id), str(owner_user_id)),
        ).fetchone()
        if candidate_row is None:
            raise StoreNotFound("candidate Turn is not available to this owner")
        snapshot = self._p2_candidate_snapshot(candidate_row)
        if (
            snapshot.profile_id != P2_CANDIDATE_PROFILE_ID
            or snapshot.lifecycle != "active"
            or aggregate.record.turn.state_revision != expected_state_revision
            or aggregate.checkpoint_revision != expected_checkpoint_revision
            or snapshot.context_revision != expected_checkpoint_revision
            or snapshot.state_revision != expected_state_revision
            or snapshot.revision != expected_candidate_revision
        ):
            raise StateConflict("candidate owner, claim, generation or Store revision changed")
        return candidate_row, snapshot, aggregate

    def create_p2_logical_query(
        self,
        owner_user_id: UserId,
        turn_id: TurnId,
        *,
        claim_token: str,
        logical_query_id: uuid.UUID,
        operation: str,
        criteria: object,
        scope: object,
        expected_state_revision: int,
        expected_checkpoint_revision: int,
        expected_candidate_revision: int,
        now: Optional[datetime] = None,
    ) -> CandidateQueryDescriptor:
        """Persist one stable logical read identity; page receipts are epoch-scoped separately."""
        self._require_started()
        instant = _aware_now(now)
        criteria_json = canonical_private_json(criteria)
        scope_json = canonical_private_json(scope)
        with self._transaction() as connection:
            candidate_row, snapshot, _ = self._p2_candidate_active_context(
                connection, owner_user_id, turn_id, claim_token=claim_token,
                expected_state_revision=expected_state_revision,
                expected_checkpoint_revision=expected_checkpoint_revision,
                expected_candidate_revision=expected_candidate_revision,
                now=instant,
            )
            query_id = str(logical_query_id)
            existing = connection.execute(
                "SELECT * FROM p2_candidate_queries WHERE logical_query_id = ?",
                (query_id,),
            ).fetchone()
            criteria_digest = json_sha256(criteria_json)
            scope_digest = json_sha256(scope_json)
            if existing is not None:
                descriptor = self._p2_query_descriptor(existing)
                if (
                    descriptor.owner_user_id != str(owner_user_id)
                    or descriptor.turn_id != str(turn_id)
                    or descriptor.operation != operation
                    or descriptor.generation != snapshot.generation
                    or descriptor.input_seq != snapshot.input_seq
                    or descriptor.input_digest != snapshot.input_digest
                    or descriptor.criteria_json != criteria_json
                    or descriptor.criteria_digest != criteria_digest
                    or descriptor.scope_json != scope_json
                    or descriptor.scope_digest != scope_digest
                ):
                    raise StateConflict("logical query identity cannot change owner, Turn, input, scope or criteria")
                return descriptor
            if snapshot.logical_read_calls >= P2_MAX_LOGICAL_READS:
                raise StateConflict("candidate logical read budget is exhausted")
            if operation not in {
                "read.activities", "read.expenses", "read.debts", "read.refund_events",
                "read.prepayment_accounts", "read.prepayment_usages", "read.prepayment_return_events",
            }:
                raise ValueError("operation is not in the fixed candidate read allowlist")
            descriptor = CandidateQueryDescriptor.model_validate({
                "logical_query_id": query_id,
                "profile_id": snapshot.profile_id,
                "owner_user_id": snapshot.owner_user_id,
                "turn_id": snapshot.turn_id,
                "operation": operation,
                "generation": snapshot.generation,
                "input_seq": snapshot.input_seq,
                "input_digest": snapshot.input_digest,
                "criteria_json": criteria_json,
                "criteria_digest": criteria_digest,
                "scope_json": scope_json,
                "scope_digest": scope_digest,
                "created_context_revision": snapshot.context_revision,
                "created_at": instant,
            }, strict=True)
            descriptor = revalidate_p2_model(CandidateQueryDescriptor, descriptor)
            connection.execute(
                """INSERT INTO p2_candidate_queries (
                    logical_query_id, owner_user_id, turn_id, profile_id, operation, generation,
                    input_seq, input_digest, criteria_json, criteria_digest, scope_json, scope_digest,
                    created_context_revision, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    descriptor.logical_query_id, descriptor.owner_user_id, descriptor.turn_id,
                    descriptor.profile_id, descriptor.operation, descriptor.generation,
                    descriptor.input_seq, descriptor.input_digest, descriptor.criteria_json,
                    descriptor.criteria_digest, descriptor.scope_json, descriptor.scope_digest,
                    descriptor.created_context_revision, _timestamp(descriptor.created_at),
                ),
            )
            changed = connection.execute(
                """UPDATE p2_candidate_turns SET logical_read_calls = logical_read_calls + 1,
                    revision = revision + 1, updated_at = ?
                    WHERE turn_id = ? AND owner_user_id = ? AND revision = ?
                      AND logical_read_calls < ? AND generation = ? AND claim_epoch = ? AND read_epoch = ?""",
                (
                    _timestamp(instant), str(turn_id), str(owner_user_id), snapshot.revision,
                    P2_MAX_LOGICAL_READS, snapshot.generation, snapshot.claim_epoch, snapshot.read_epoch,
                ),
            ).rowcount
            if changed != 1:
                raise StateConflict("candidate read budget or revision changed")
            self._fault("p2_candidate.query.before_commit")
            return descriptor

    @staticmethod
    def _p2_query_descriptor(row: sqlite3.Row) -> CandidateQueryDescriptor:
        values = {name: row[name] for name in CandidateQueryDescriptor.model_fields}
        values["created_at"] = _parse_datetime(row["created_at"])
        return CandidateQueryDescriptor.model_validate(values, strict=True)

    def reserve_p2_candidate_stage(
        self,
        owner_user_id: UserId,
        turn_id: TurnId,
        *,
        claim_token: str,
        stage: str,
        active_limit_us: int,
        expected_state_revision: int,
        expected_checkpoint_revision: int,
        expected_candidate_revision: int,
        backend_limit_us: int = 0,
        response_bytes_limit: int = 0,
        logical_query_id: Optional[uuid.UUID] = None,
        request_digest: Optional[str] = None,
        reservation_id: Optional[uuid.UUID] = None,
        now: Optional[datetime] = None,
    ) -> CandidateChargeReservation:
        """Durably reserve budget before active work or a GET can be dispatched."""
        self._require_started()
        instant = _aware_now(now)
        reservation_id = reservation_id or uuid.uuid4()
        with self._transaction() as connection:
            candidate_row, snapshot, _ = self._p2_candidate_active_context(
                connection, owner_user_id, turn_id, claim_token=claim_token,
                expected_state_revision=expected_state_revision,
                expected_checkpoint_revision=expected_checkpoint_revision,
                expected_candidate_revision=expected_candidate_revision,
                now=instant,
            )
            query_id_text = str(logical_query_id) if logical_query_id is not None else None
            if stage == "backend_get":
                query_row = connection.execute(
                    "SELECT * FROM p2_candidate_queries WHERE logical_query_id = ? AND turn_id = ? AND owner_user_id = ?",
                    (query_id_text, str(turn_id), str(owner_user_id)),
                ).fetchone()
                if query_row is None:
                    raise StateConflict("GET reservation requires this owner's stable logical query")
                query = self._p2_query_descriptor(query_row)
                if (
                    query.generation != snapshot.generation
                    or query.input_seq != snapshot.input_seq
                    or query.input_digest != snapshot.input_digest
                ):
                    raise StateConflict("logical query input is no longer current")
            reservation = CandidateChargeReservation.model_validate({
                "reservation_id": str(reservation_id),
                "profile_id": snapshot.profile_id,
                "owner_user_id": snapshot.owner_user_id,
                "turn_id": snapshot.turn_id,
                "stage": stage,
                "generation": snapshot.generation,
                "claim_epoch": snapshot.claim_epoch,
                "read_epoch": snapshot.read_epoch,
                "context_revision": snapshot.context_revision,
                "active_limit_us": active_limit_us,
                "backend_limit_us": backend_limit_us,
                "response_bytes_limit": response_bytes_limit,
                "logical_query_id": query_id_text,
                "request_digest": request_digest,
                "created_at": instant,
            }, strict=True)
            reservation = revalidate_p2_model(CandidateChargeReservation, reservation)
            exists = connection.execute(
                "SELECT 1 FROM p2_candidate_charge_events WHERE reservation_id = ? LIMIT 1",
                (reservation.reservation_id,),
            ).fetchone()
            if exists is not None:
                raise StateConflict("candidate reservation identifiers cannot be replayed")
            if snapshot.active_used_us + snapshot.active_reserved_us + reservation.active_limit_us > P2_MAX_ACTIVE_US:
                raise StateConflict("candidate active-execution budget is exhausted")
            if snapshot.backend_used_us + snapshot.backend_reserved_us + reservation.backend_limit_us > P2_MAX_BACKEND_US:
                raise StateConflict("candidate backend-time budget is exhausted")
            if snapshot.response_bytes + snapshot.bytes_reserved + reservation.response_bytes_limit > P2_MAX_RESPONSE_BYTES:
                raise StateConflict("candidate response-byte budget is exhausted")
            if stage == "repair" and snapshot.repair_calls >= P2_MAX_REPAIRS:
                raise StateConflict("candidate repair budget is exhausted")
            if stage in {"model", "repair"} and snapshot.model_calls >= P2_MAX_MODEL_CALLS:
                raise StateConflict("candidate model-call budget is exhausted")
            if stage not in {"model", "repair", "backend_get", "backend_processing", "local_processing"}:
                raise ValueError("unknown candidate execution stage")
            if stage == "backend_get" and snapshot.get_attempts >= P2_MAX_GETS:
                raise StateConflict("candidate GET-attempt budget is exhausted")
            active_extra = reservation.active_limit_us
            backend_extra = reservation.backend_limit_us
            bytes_extra = reservation.response_bytes_limit
            # Repair is a repair subtype of a model POST, not a seventh extra call.
            model_extra = int(stage in {"model", "repair"})
            repair_extra = int(stage == "repair")
            get_extra = int(stage == "backend_get")
            connection.execute(
                """INSERT INTO p2_candidate_charge_events (
                    charge_event_id, reservation_id, event_kind, owner_user_id, turn_id, profile_id,
                    stage, generation, claim_epoch, read_epoch, context_revision, logical_query_id,
                    active_limit_us, backend_limit_us, response_bytes_limit, actual_active_us,
                    actual_backend_us, actual_response_bytes, request_digest, raw_body_digest,
                    unknown_flag, occurred_at
                ) VALUES (?, ?, 'reserved', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, NULL, 0, ?)""",
                (
                    str(uuid.uuid4()), reservation.reservation_id, reservation.owner_user_id,
                    reservation.turn_id, reservation.profile_id, reservation.stage,
                    reservation.generation, reservation.claim_epoch, reservation.read_epoch,
                    reservation.context_revision, reservation.logical_query_id, active_extra,
                    backend_extra, bytes_extra, reservation.request_digest, _timestamp(instant),
                ),
            )
            changed = connection.execute(
                """UPDATE p2_candidate_turns SET
                    model_calls = model_calls + ?, repair_calls = repair_calls + ?,
                    get_attempts = get_attempts + ?, active_reserved_us = active_reserved_us + ?,
                    backend_reserved_us = backend_reserved_us + ?, bytes_reserved = bytes_reserved + ?,
                    revision = revision + 1, updated_at = ?
                    WHERE turn_id = ? AND owner_user_id = ? AND revision = ? AND lifecycle = 'active'
                      AND generation = ? AND claim_epoch = ? AND read_epoch = ?
                      AND context_revision = ?
                      AND active_used_us + active_reserved_us + ? <= ?
                      AND backend_used_us + backend_reserved_us + ? <= ?
                      AND response_bytes + bytes_reserved + ? <= ?""",
                (
                    model_extra, repair_extra, get_extra, active_extra, backend_extra, bytes_extra,
                    _timestamp(instant), str(turn_id), str(owner_user_id), snapshot.revision,
                    snapshot.generation, snapshot.claim_epoch, snapshot.read_epoch, snapshot.context_revision,
                    active_extra, P2_MAX_ACTIVE_US, backend_extra, P2_MAX_BACKEND_US,
                    bytes_extra, P2_MAX_RESPONSE_BYTES,
                ),
            ).rowcount
            if changed != 1:
                raise StateConflict("candidate budget reservation lost its Store CAS")
            self._fault("p2_candidate.reserve.before_commit")
            return reservation

    def settle_p2_candidate_stage(
        self,
        owner_user_id: UserId,
        turn_id: TurnId,
        settlement: CandidateChargeSettlement,
    ) -> CandidateTurnSnapshot:
        """Settle one reservation exactly once; stale workers may charge but never publish."""
        self._require_started()
        settlement = revalidate_p2_model(CandidateChargeSettlement, settlement)
        with self._transaction() as connection:
            reserved = connection.execute(
                """SELECT * FROM p2_candidate_charge_events WHERE reservation_id = ?
                    AND event_kind = 'reserved' AND owner_user_id = ? AND turn_id = ?""",
                (settlement.reservation_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            if reserved is None:
                raise StoreNotFound("candidate reservation is not available to this owner")
            already = connection.execute(
                "SELECT 1 FROM p2_candidate_charge_events WHERE reservation_id = ? AND event_kind IN ('settled','unknown')",
                (settlement.reservation_id,),
            ).fetchone()
            if already is not None:
                raise StateConflict("candidate reservation was already settled")
            active_limit = int(reserved["active_limit_us"])
            backend_limit = int(reserved["backend_limit_us"])
            bytes_limit = int(reserved["response_bytes_limit"])
            if (
                settlement.actual_active_us > active_limit
                or settlement.actual_backend_us > backend_limit
                or settlement.actual_response_bytes > bytes_limit
            ):
                raise ValueError("actual candidate usage exceeds its durable reservation")
            if reserved["stage"] not in {"backend_get", "backend_processing"} and (
                settlement.actual_backend_us or settlement.actual_response_bytes or settlement.raw_body_digest is not None
            ):
                raise ValueError("non-GET settlement cannot claim backend time or source bytes")
            if reserved["stage"] == "backend_processing" and (
                settlement.actual_response_bytes or settlement.raw_body_digest is not None
            ):
                raise ValueError("backend-processing settlement cannot claim source response bytes")
            if settlement.outcome == "unknown" and (
                settlement.actual_active_us != active_limit
                or settlement.actual_backend_us != backend_limit
                or settlement.actual_response_bytes != bytes_limit
            ):
                raise ValueError("unknown consumption must conservatively charge the entire reservation")
            if settlement.outcome == "actual" and settlement.actual_response_bytes and settlement.raw_body_digest is None:
                raise ValueError("received response bytes require their body digest")
            event_kind = "unknown" if settlement.outcome == "unknown" else "settled"
            connection.execute(
                """INSERT INTO p2_candidate_charge_events (
                    charge_event_id, reservation_id, event_kind, owner_user_id, turn_id, profile_id,
                    stage, generation, claim_epoch, read_epoch, context_revision, logical_query_id,
                    active_limit_us, backend_limit_us, response_bytes_limit, actual_active_us,
                    actual_backend_us, actual_response_bytes, overrun_active_us, overrun_backend_us,
                    overrun_response_bytes, request_digest, raw_body_digest, unknown_flag, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()), settlement.reservation_id, event_kind, reserved["owner_user_id"],
                    reserved["turn_id"], reserved["profile_id"], reserved["stage"],
                    reserved["generation"], reserved["claim_epoch"], reserved["read_epoch"],
                    reserved["context_revision"], reserved["logical_query_id"], active_limit,
                    backend_limit, bytes_limit, settlement.actual_active_us,
                    settlement.actual_backend_us, settlement.actual_response_bytes,
                    settlement.overrun_active_us, settlement.overrun_backend_us,
                    settlement.overrun_response_bytes, reserved["request_digest"], settlement.raw_body_digest,
                    int(settlement.outcome == "unknown"), _timestamp(settlement.settled_at),
                ),
            )
            changed = connection.execute(
                """UPDATE p2_candidate_turns SET
                    active_reserved_us = active_reserved_us - ?, active_used_us = active_used_us + ?,
                    backend_reserved_us = backend_reserved_us - ?, backend_used_us = backend_used_us + ?,
                    bytes_reserved = bytes_reserved - ?, response_bytes = response_bytes + ?,
                    unknown_consumption = CASE WHEN ? = 1 THEN 1 ELSE unknown_consumption END,
                    revision = revision + 1, updated_at = ?
                    WHERE turn_id = ? AND owner_user_id = ? AND active_reserved_us >= ?
                      AND backend_reserved_us >= ? AND bytes_reserved >= ?
                      AND active_used_us + ? <= ? AND backend_used_us + ? <= ?
                      AND response_bytes + ? <= ?""",
                (
                    active_limit, settlement.actual_active_us,
                    backend_limit, settlement.actual_backend_us,
                    bytes_limit, settlement.actual_response_bytes,
                    int(settlement.outcome == "unknown"), _timestamp(settlement.settled_at),
                    str(turn_id), str(owner_user_id), active_limit, backend_limit, bytes_limit,
                    settlement.actual_active_us, P2_MAX_ACTIVE_US,
                    settlement.actual_backend_us, P2_MAX_BACKEND_US,
                    settlement.actual_response_bytes, P2_MAX_RESPONSE_BYTES,
                ),
            ).rowcount
            if changed != 1:
                raise InvariantViolation("candidate reservation ledger and budget summary diverged")
            self._fault("p2_candidate.settle.before_commit")
            row = connection.execute(
                "SELECT * FROM p2_candidate_turns WHERE turn_id = ? AND owner_user_id = ?",
                (str(turn_id), str(owner_user_id)),
            ).fetchone()
            return self._p2_candidate_snapshot(row)

    def append_p2_candidate_page_receipt(
        self,
        owner_user_id: UserId,
        turn_id: TurnId,
        draft: CandidatePageReceiptDraft,
        *,
        claim_token: str,
        get_reservation_ids: Sequence[uuid.UUID],
        expected_state_revision: int,
        expected_checkpoint_revision: int,
        expected_candidate_revision: int,
        now: Optional[datetime] = None,
    ) -> str:
        """Append a page proof linked to settled GET bodies, without storing facts or tokens."""
        self._require_started()
        instant = _aware_now(now)
        draft = revalidate_p2_model(CandidatePageReceiptDraft, draft)
        if not get_reservation_ids or len(get_reservation_ids) > P2_MAX_GETS:
            raise ValueError("page receipt requires a bounded nonempty set of actual GET reservations")
        if len({str(item) for item in get_reservation_ids}) != len(get_reservation_ids):
            raise ValueError("page receipt cannot link a GET reservation more than once")
        with self._transaction() as connection:
            _, snapshot, _ = self._p2_candidate_active_context(
                connection, owner_user_id, turn_id, claim_token=claim_token,
                expected_state_revision=expected_state_revision,
                expected_checkpoint_revision=expected_checkpoint_revision,
                expected_candidate_revision=expected_candidate_revision,
                now=instant,
            )
            if (
                draft.owner_user_id != str(owner_user_id)
                or draft.turn_id != str(turn_id)
                or draft.generation != snapshot.generation
                or draft.input_seq != snapshot.input_seq
                or draft.input_digest != snapshot.input_digest
                or draft.claim_epoch != snapshot.claim_epoch
                or draft.read_epoch != snapshot.read_epoch
                or draft.context_revision != snapshot.context_revision
            ):
                raise StateConflict("candidate page belongs to a stale owner, input, claim, read or context epoch")
            query_row = connection.execute(
                "SELECT * FROM p2_candidate_queries WHERE logical_query_id = ? AND turn_id = ? AND owner_user_id = ?",
                (draft.logical_query_id, str(turn_id), str(owner_user_id)),
            ).fetchone()
            if query_row is None:
                raise StoreNotFound("candidate logical query is not available to this owner")
            query = self._p2_query_descriptor(query_row)
            if (
                query.generation != snapshot.generation
                or query.input_seq != snapshot.input_seq
                or query.input_digest != snapshot.input_digest
                or query.criteria_digest != draft.criteria_digest
                or query.scope_digest != draft.scope_digest
            ):
                raise StateConflict("candidate page criteria or scope differs from its stable logical query")
            previous = connection.execute(
                """SELECT page_index, model_page_has_more FROM p2_candidate_page_receipts
                    WHERE logical_query_id = ? AND read_epoch = ? ORDER BY page_index DESC LIMIT 1""",
                (draft.logical_query_id, draft.read_epoch),
            ).fetchone()
            expected_page_index = 0 if previous is None else int(previous["page_index"]) + 1
            if draft.page_index != expected_page_index or (previous is not None and not bool(previous["model_page_has_more"])):
                raise StateConflict("candidate page receipt is not the next authorized page")
            source_inputs: list[dict[str, object]] = []
            body_inputs: list[dict[str, object]] = []
            for ordinal, reservation_id in enumerate(get_reservation_ids):
                reserved = connection.execute(
                    """SELECT * FROM p2_candidate_charge_events WHERE reservation_id = ?
                        AND event_kind = 'reserved' AND owner_user_id = ? AND turn_id = ?""",
                    (str(reservation_id), str(owner_user_id), str(turn_id)),
                ).fetchone()
                settled = connection.execute(
                    """SELECT * FROM p2_candidate_charge_events WHERE reservation_id = ?
                        AND event_kind = 'settled' AND owner_user_id = ? AND turn_id = ?""",
                    (str(reservation_id), str(owner_user_id), str(turn_id)),
                ).fetchone()
                if reserved is None or settled is None:
                    raise StateConflict("candidate page proof can link only settled actual GETs")
                if (
                    reserved["stage"] != "backend_get"
                    or reserved["logical_query_id"] != draft.logical_query_id
                    or int(reserved["generation"]) != snapshot.generation
                    or int(reserved["claim_epoch"]) != snapshot.claim_epoch
                    or int(reserved["read_epoch"]) != snapshot.read_epoch
                    or reserved["request_digest"] is None
                    or settled["raw_body_digest"] is None
                ):
                    raise StateConflict("candidate GET proof is not bound to this query epoch and body")
                source_inputs.append({
                    "ordinal": ordinal,
                    "reservation_id": str(reservation_id),
                    "request_digest": reserved["request_digest"],
                    "raw_body_digest": settled["raw_body_digest"],
                    "actual_backend_us": int(settled["actual_backend_us"]),
                    "actual_response_bytes": int(settled["actual_response_bytes"]),
                })
                body_inputs.append({
                    "ordinal": ordinal,
                    "raw_body_digest": settled["raw_body_digest"],
                    "actual_response_bytes": int(settled["actual_response_bytes"]),
                })
            body_chain_json = json.dumps(body_inputs, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            expected_raw_body_digest = hashlib.sha256(body_chain_json.encode("utf-8")).hexdigest()
            if draft.raw_body_digest != expected_raw_body_digest:
                raise StateConflict("candidate page raw-body digest does not bind its actual GET bodies")
            source_chain_json = json.dumps(source_inputs, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            source_chain_digest = hashlib.sha256(source_chain_json.encode("utf-8")).hexdigest()
            final_receipt_digest = p2_receipt_digest(draft, source_chain_digest)
            connection.execute(
                """INSERT INTO p2_candidate_page_receipts (
                    receipt_id, logical_query_id, owner_user_id, turn_id, generation, input_seq,
                    input_digest, claim_epoch, read_epoch, context_revision, page_index,
                    criteria_digest, scope_digest, source_get_chain_digest, raw_body_digest,
                    validated_dto_digest, projection_digest, source_version_digest, observed_at,
                    source_query_complete, model_page_has_more, next_page_ref_digest, receipt_digest
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    draft.receipt_id, draft.logical_query_id, draft.owner_user_id, draft.turn_id,
                    draft.generation, draft.input_seq, draft.input_digest, draft.claim_epoch,
                    draft.read_epoch, draft.context_revision, draft.page_index, draft.criteria_digest,
                    draft.scope_digest, source_chain_digest, draft.raw_body_digest,
                    draft.validated_dto_digest, draft.projection_digest, draft.source_version_digest,
                    _timestamp(draft.observed_at), int(draft.source_query_complete),
                    int(draft.model_page_has_more), draft.next_page_ref_digest, final_receipt_digest,
                ),
            )
            for ordinal, reservation_id in enumerate(get_reservation_ids):
                connection.execute(
                    """INSERT INTO p2_candidate_page_gets (
                        receipt_id, reservation_id, settlement_event_kind, owner_user_id, turn_id, ordinal
                    ) VALUES (?, ?, 'settled', ?, ?, ?)""",
                    (draft.receipt_id, str(reservation_id), str(owner_user_id), str(turn_id), ordinal),
                )
            changed = connection.execute(
                """UPDATE p2_candidate_turns SET revision = revision + 1, updated_at = ?
                    WHERE turn_id = ? AND owner_user_id = ? AND revision = ? AND generation = ?
                      AND claim_epoch = ? AND read_epoch = ? AND context_revision = ? AND lifecycle = 'active'""",
                (
                    _timestamp(instant), str(turn_id), str(owner_user_id), snapshot.revision,
                    snapshot.generation, snapshot.claim_epoch, snapshot.read_epoch, snapshot.context_revision,
                ),
            ).rowcount
            if changed != 1:
                raise StateConflict("candidate page publication lost its Store CAS")
            self._fault("p2_candidate.page.before_commit")
            return final_receipt_digest

    def is_p2_candidate_page_current(
        self,
        owner_user_id: UserId,
        turn_id: TurnId,
        receipt_id: uuid.UUID,
        *,
        claim_token: str,
        expected_state_revision: int,
        expected_checkpoint_revision: int,
        expected_candidate_revision: int,
        now: Optional[datetime] = None,
    ) -> bool:
        """Check a historical receipt against current owner/claim/input/read epochs."""
        self._require_started()
        instant = _aware_now(now)
        with self._connection() as connection:
            _, snapshot, _ = self._p2_candidate_active_context(
                connection, owner_user_id, turn_id, claim_token=claim_token,
                expected_state_revision=expected_state_revision,
                expected_checkpoint_revision=expected_checkpoint_revision,
                expected_candidate_revision=expected_candidate_revision,
                now=instant,
            )
            receipt = connection.execute(
                """SELECT * FROM p2_candidate_page_receipts WHERE receipt_id = ?
                    AND owner_user_id = ? AND turn_id = ?""",
                (str(receipt_id), str(owner_user_id), str(turn_id)),
            ).fetchone()
            if receipt is None:
                raise StoreNotFound("candidate page receipt is not available to this owner")
            query = connection.execute(
                "SELECT * FROM p2_candidate_queries WHERE logical_query_id = ? AND turn_id = ? AND owner_user_id = ?",
                (receipt["logical_query_id"], str(turn_id), str(owner_user_id)),
            ).fetchone()
            if query is None:
                raise InvariantViolation("candidate receipt lost its immutable logical query")
            return bool(
                int(receipt["generation"]) == snapshot.generation
                and int(receipt["input_seq"]) == snapshot.input_seq
                and receipt["input_digest"] == snapshot.input_digest
                and int(receipt["claim_epoch"]) == snapshot.claim_epoch
                and int(receipt["read_epoch"]) == snapshot.read_epoch
                and int(query["generation"]) == snapshot.generation
                and int(query["input_seq"]) == snapshot.input_seq
                and query["input_digest"] == snapshot.input_digest
            )

    def _verify_p2_candidate_rows(self, connection: sqlite3.Connection) -> None:
        """Verify private summaries against append-only query, page and charge history."""
        rows = connection.execute("SELECT * FROM p2_candidate_turns ORDER BY turn_id").fetchall()
        for row in rows:
            snapshot = self._p2_candidate_snapshot(row)
            turn_row = connection.execute(
                "SELECT state, state_revision, checkpoint_revision, owner_user_id FROM turns WHERE turn_id = ?",
                (snapshot.turn_id,),
            ).fetchone()
            if turn_row is None or turn_row["owner_user_id"] != snapshot.owner_user_id:
                raise InvariantViolation("candidate Store row is not bound to its owner Turn")
            if snapshot.context_revision > int(turn_row["checkpoint_revision"]):
                raise InvariantViolation("candidate context revision exceeds its canonical Turn checkpoint")
            events = connection.execute(
                "SELECT * FROM p2_candidate_charge_events WHERE turn_id = ? AND owner_user_id = ? ORDER BY occurred_at, charge_event_id",
                (snapshot.turn_id, snapshot.owner_user_id),
            ).fetchall()
            reservations = {event["reservation_id"]: event for event in events if event["event_kind"] == "reserved"}
            settlements = {
                event["reservation_id"]: event
                for event in events if event["event_kind"] in ("settled", "unknown")
            }
            settlement_counts: dict[str, int] = {}
            for event in events:
                if event["event_kind"] in ("settled", "unknown"):
                    settlement_counts[event["reservation_id"]] = settlement_counts.get(event["reservation_id"], 0) + 1
            if (
                any(count != 1 for count in settlement_counts.values())
                or any(reservation_id not in reservations for reservation_id in settlements)
            ):
                raise InvariantViolation("candidate reservation history has a missing or duplicate reservation edge")
            active_used = backend_used = bytes_used = 0
            active_reserved = backend_reserved = bytes_reserved = 0
            model_count = repair_count = get_count = 0
            unknown_seen = False
            for reservation_id, reserved in reservations.items():
                reservation_model = CandidateChargeReservation.model_validate({
                    "reservation_id": reservation_id,
                    "profile_id": reserved["profile_id"],
                    "owner_user_id": reserved["owner_user_id"],
                    "turn_id": reserved["turn_id"],
                    "stage": reserved["stage"],
                    "generation": int(reserved["generation"]),
                    "claim_epoch": int(reserved["claim_epoch"]),
                    "read_epoch": int(reserved["read_epoch"]),
                    "context_revision": int(reserved["context_revision"]),
                    "active_limit_us": int(reserved["active_limit_us"]),
                    "backend_limit_us": int(reserved["backend_limit_us"]),
                    "response_bytes_limit": int(reserved["response_bytes_limit"]),
                    "logical_query_id": reserved["logical_query_id"],
                    "request_digest": reserved["request_digest"],
                    "created_at": _parse_datetime(reserved["occurred_at"]),
                }, strict=True)
                revalidate_p2_model(CandidateChargeReservation, reservation_model)
                model_count += int(reserved["stage"] in {"model", "repair"})
                repair_count += int(reserved["stage"] == "repair")
                get_count += int(reserved["stage"] == "backend_get")
                settled = settlements.get(reservation_id)
                if settled is None:
                    active_reserved += int(reserved["active_limit_us"])
                    backend_reserved += int(reserved["backend_limit_us"])
                    bytes_reserved += int(reserved["response_bytes_limit"])
                    continue
                if (
                    any(reserved[key] != settled[key] for key in (
                        "owner_user_id", "turn_id", "profile_id", "stage", "generation",
                        "claim_epoch", "read_epoch", "context_revision", "logical_query_id",
                        "active_limit_us", "backend_limit_us", "response_bytes_limit", "request_digest",
                    ))
                    or settled["actual_active_us"] is None
                    or settled["actual_backend_us"] is None
                    or settled["actual_response_bytes"] is None
                ):
                    raise InvariantViolation("candidate charge settlement differs from its reservation")
                settlement_model = CandidateChargeSettlement.model_validate({
                    "reservation_id": reservation_id,
                    "outcome": "unknown" if settled["event_kind"] == "unknown" else "actual",
                    "actual_active_us": int(settled["actual_active_us"]),
                    "actual_backend_us": int(settled["actual_backend_us"]),
                    "actual_response_bytes": int(settled["actual_response_bytes"]),
                    "overrun_active_us": int(settled["overrun_active_us"]),
                    "overrun_backend_us": int(settled["overrun_backend_us"]),
                    "overrun_response_bytes": int(settled["overrun_response_bytes"]),
                    "raw_body_digest": settled["raw_body_digest"],
                    "settled_at": _parse_datetime(settled["occurred_at"]),
                }, strict=True)
                revalidate_p2_model(CandidateChargeSettlement, settlement_model)
                if settled["event_kind"] == "unknown":
                    unknown_seen = True
                    if (
                        int(settled["actual_active_us"]) != int(reserved["active_limit_us"])
                        or int(settled["actual_backend_us"]) != int(reserved["backend_limit_us"])
                        or int(settled["actual_response_bytes"]) != int(reserved["response_bytes_limit"])
                        or settled["raw_body_digest"] is not None
                    ):
                        raise InvariantViolation("unknown candidate consumption did not retain its full reservation")
                active_used += int(settled["actual_active_us"])
                backend_used += int(settled["actual_backend_us"])
                bytes_used += int(settled["actual_response_bytes"])
            if (
                (snapshot.active_used_us, snapshot.active_reserved_us) != (active_used, active_reserved)
                or (snapshot.backend_used_us, snapshot.backend_reserved_us) != (backend_used, backend_reserved)
                or (snapshot.response_bytes, snapshot.bytes_reserved) != (bytes_used, bytes_reserved)
                or snapshot.model_calls != model_count
                or snapshot.repair_calls != repair_count
                or snapshot.get_attempts != get_count
                or snapshot.unknown_consumption != unknown_seen
            ):
                raise InvariantViolation("candidate budget summary differs from append-only charge history")
            query_rows = connection.execute(
                "SELECT * FROM p2_candidate_queries WHERE turn_id = ? AND owner_user_id = ? ORDER BY logical_query_id",
                (snapshot.turn_id, snapshot.owner_user_id),
            ).fetchall()
            if snapshot.logical_read_calls != len(query_rows):
                raise InvariantViolation("candidate logical-read count differs from immutable query history")
            for query_row in query_rows:
                self._p2_query_descriptor(query_row)
            page_rows = connection.execute(
                "SELECT * FROM p2_candidate_page_receipts WHERE turn_id = ? AND owner_user_id = ? ORDER BY receipt_id",
                (snapshot.turn_id, snapshot.owner_user_id),
            ).fetchall()
            for page in page_rows:
                query_row = connection.execute(
                    "SELECT * FROM p2_candidate_queries WHERE logical_query_id = ? AND turn_id = ? AND owner_user_id = ?",
                    (page["logical_query_id"], page["turn_id"], page["owner_user_id"]),
                ).fetchone()
                if query_row is None:
                    raise InvariantViolation("candidate page receipt has no immutable query descriptor")
                query = self._p2_query_descriptor(query_row)
                if page["criteria_digest"] != query.criteria_digest or page["scope_digest"] != query.scope_digest:
                    raise InvariantViolation("candidate page receipt criteria or scope changed")
                linked = connection.execute(
                    """SELECT links.ordinal, links.reservation_id, reserved.request_digest,
                               settled.raw_body_digest, settled.actual_backend_us,
                               settled.actual_response_bytes, reserved.logical_query_id,
                               reserved.generation, reserved.claim_epoch, reserved.read_epoch,
                               reserved.stage
                        FROM p2_candidate_page_gets AS links
                        JOIN p2_candidate_charge_events AS reserved
                          ON reserved.reservation_id = links.reservation_id AND reserved.event_kind = 'reserved'
                        JOIN p2_candidate_charge_events AS settled
                          ON settled.reservation_id = links.reservation_id AND settled.event_kind = 'settled'
                        WHERE links.receipt_id = ? ORDER BY links.ordinal""",
                    (page["receipt_id"],),
                ).fetchall()
                if not linked:
                    raise InvariantViolation("candidate page receipt must bind at least one successful GET")
                chain: list[dict[str, object]] = []
                body_chain: list[dict[str, object]] = []
                for ordinal, item in enumerate(linked):
                    if (
                        int(item["ordinal"]) != ordinal
                        or item["stage"] != "backend_get"
                        or item["logical_query_id"] != page["logical_query_id"]
                        or int(item["generation"]) != int(page["generation"])
                        or int(item["claim_epoch"]) != int(page["claim_epoch"])
                        or int(item["read_epoch"]) != int(page["read_epoch"])
                        or item["request_digest"] is None
                        or item["raw_body_digest"] is None
                    ):
                        raise InvariantViolation("candidate page has a mismatched or incomplete GET chain")
                    chain.append({
                        "ordinal": ordinal,
                        "reservation_id": item["reservation_id"],
                        "request_digest": item["request_digest"],
                        "raw_body_digest": item["raw_body_digest"],
                        "actual_backend_us": int(item["actual_backend_us"]),
                        "actual_response_bytes": int(item["actual_response_bytes"]),
                    })
                    body_chain.append({
                        "ordinal": ordinal,
                        "raw_body_digest": item["raw_body_digest"],
                        "actual_response_bytes": int(item["actual_response_bytes"]),
                    })
                chain_bytes = json.dumps(chain, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
                chain_digest = hashlib.sha256(chain_bytes).hexdigest()
                if chain_digest != page["source_get_chain_digest"]:
                    raise InvariantViolation("candidate page source GET chain digest is invalid")
                body_bytes = json.dumps(body_chain, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
                if hashlib.sha256(body_bytes).hexdigest() != page["raw_body_digest"]:
                    raise InvariantViolation("candidate page raw-body digest does not match its actual GET responses")
                draft = CandidatePageReceiptDraft.model_validate({
                    "receipt_id": page["receipt_id"], "logical_query_id": page["logical_query_id"],
                    "owner_user_id": page["owner_user_id"], "turn_id": page["turn_id"],
                    "generation": int(page["generation"]), "input_seq": int(page["input_seq"]),
                    "input_digest": page["input_digest"], "claim_epoch": int(page["claim_epoch"]),
                    "read_epoch": int(page["read_epoch"]), "context_revision": int(page["context_revision"]),
                    "page_index": int(page["page_index"]), "criteria_digest": page["criteria_digest"],
                    "scope_digest": page["scope_digest"], "raw_body_digest": page["raw_body_digest"],
                    "validated_dto_digest": page["validated_dto_digest"],
                    "projection_digest": page["projection_digest"],
                    "source_version_digest": page["source_version_digest"],
                    "observed_at": _parse_datetime(page["observed_at"]),
                    "source_query_complete": bool(page["source_query_complete"]),
                    "model_page_has_more": bool(page["model_page_has_more"]),
                    "next_page_ref_digest": page["next_page_ref_digest"],
                }, strict=True)
                expected_digest = p2_receipt_digest(draft, chain_digest)
                if expected_digest != page["receipt_digest"]:
                    raise InvariantViolation("candidate page receipt digest is invalid")

    def _recover_p2_candidate_unknown_reservations(
        self,
        connection: sqlite3.Connection,
        *,
        owner_user_id: str,
        turn_id: str,
        now: datetime,
    ) -> None:
        pending = connection.execute(
            """SELECT reserved.* FROM p2_candidate_charge_events AS reserved
                LEFT JOIN p2_candidate_charge_events AS settled
                  ON settled.reservation_id = reserved.reservation_id AND settled.event_kind IN ('settled','unknown')
                WHERE reserved.owner_user_id = ? AND reserved.turn_id = ?
                  AND reserved.event_kind = 'reserved' AND settled.reservation_id IS NULL
                ORDER BY reserved.occurred_at, reserved.charge_event_id""",
            (owner_user_id, turn_id),
        ).fetchall()
        for reserved in pending:
            connection.execute(
                """INSERT INTO p2_candidate_charge_events (
                    charge_event_id, reservation_id, event_kind, owner_user_id, turn_id, profile_id,
                    stage, generation, claim_epoch, read_epoch, context_revision, logical_query_id,
                    active_limit_us, backend_limit_us, response_bytes_limit, actual_active_us,
                    actual_backend_us, actual_response_bytes, request_digest, raw_body_digest,
                    unknown_flag, occurred_at
                ) VALUES (?, ?, 'unknown', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 1, ?)""",
                (
                    str(uuid.uuid4()), reserved["reservation_id"], reserved["owner_user_id"],
                    reserved["turn_id"], reserved["profile_id"], reserved["stage"],
                    reserved["generation"], reserved["claim_epoch"], reserved["read_epoch"],
                    reserved["context_revision"], reserved["logical_query_id"],
                    reserved["active_limit_us"], reserved["backend_limit_us"], reserved["response_bytes_limit"],
                    reserved["active_limit_us"], reserved["backend_limit_us"],
                    reserved["response_bytes_limit"], reserved["request_digest"], _timestamp(now),
                ),
            )
            changed = connection.execute(
                """UPDATE p2_candidate_turns SET
                    active_reserved_us = active_reserved_us - ?, active_used_us = active_used_us + ?,
                    backend_reserved_us = backend_reserved_us - ?, backend_used_us = backend_used_us + ?,
                    bytes_reserved = bytes_reserved - ?, response_bytes = response_bytes + ?,
                    unknown_consumption = 1, revision = revision + 1, updated_at = ?
                    WHERE turn_id = ? AND owner_user_id = ? AND active_reserved_us >= ?
                      AND backend_reserved_us >= ? AND bytes_reserved >= ?""",
                (
                    reserved["active_limit_us"], reserved["active_limit_us"],
                    reserved["backend_limit_us"], reserved["backend_limit_us"],
                    reserved["response_bytes_limit"], reserved["response_bytes_limit"],
                    _timestamp(now), turn_id, owner_user_id,
                    reserved["active_limit_us"], reserved["backend_limit_us"], reserved["response_bytes_limit"],
                ),
            ).rowcount
            if changed != 1:
                raise InvariantViolation("unknown candidate charge could not be conservatively retained")

    def _recover_p2_candidate_process_start(self, connection: sqlite3.Connection, *, instant: datetime) -> None:
        candidates = connection.execute("SELECT * FROM p2_candidate_turns ORDER BY turn_id").fetchall()
        for original in candidates:
            owner_user_id = str(original["owner_user_id"])
            turn_id = str(original["turn_id"])
            turn = connection.execute(
                "SELECT state, state_revision, checkpoint_revision, claim_token, claim_until FROM turns WHERE turn_id = ? AND owner_user_id = ?",
                (turn_id, owner_user_id),
            ).fetchone()
            if turn is None:
                raise InvariantViolation("candidate Turn disappeared during Store startup")
            claim_until = _parse_datetime(turn["claim_until"]) if turn["claim_until"] else None
            if turn["claim_token"] is not None and claim_until is not None and claim_until > instant:
                # A second Store connection is not proof that the leased worker crashed.
                # Leave its reservations and epochs alone; lease takeover owns recovery.
                continue
            self._recover_p2_candidate_unknown_reservations(
                connection, owner_user_id=owner_user_id, turn_id=turn_id, now=instant,
            )
            candidate = connection.execute(
                "SELECT * FROM p2_candidate_turns WHERE turn_id = ? AND owner_user_id = ?",
                (turn_id, owner_user_id),
            ).fetchone()
            lifecycle = self._p2_lifecycle_for_state(TurnState(turn["state"]))
            changed = connection.execute(
                """UPDATE p2_candidate_turns SET claim_epoch = claim_epoch + 1,
                    read_epoch = read_epoch + 1, lifecycle = ?, context_revision = ?,
                    turn_state_revision = ?, revision = revision + 1, updated_at = ?
                    WHERE turn_id = ? AND owner_user_id = ? AND revision = ?""",
                (
                    lifecycle, int(turn["checkpoint_revision"]), int(turn["state_revision"]),
                    _timestamp(instant), turn_id, owner_user_id, int(candidate["revision"]),
                ),
            ).rowcount
            if changed != 1:
                raise StateConflict("candidate Store startup invalidation lost its CAS")

    def _claim_p2_candidate_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        owner_user_id: UserId,
        turn_id: TurnId,
        now: datetime,
    ) -> None:
        candidate = connection.execute(
            "SELECT * FROM p2_candidate_turns WHERE turn_id = ? AND owner_user_id = ?",
            (str(turn_id), str(owner_user_id)),
        ).fetchone()
        if candidate is None or candidate["profile_id"] != P2_CANDIDATE_PROFILE_ID:
            raise StateConflict("candidate scheduler claim requires the fixed candidate profile")
        self._recover_p2_candidate_unknown_reservations(
            connection, owner_user_id=str(owner_user_id), turn_id=str(turn_id), now=now,
        )
        candidate = connection.execute(
            "SELECT * FROM p2_candidate_turns WHERE turn_id = ? AND owner_user_id = ?",
            (str(turn_id), str(owner_user_id)),
        ).fetchone()
        turn = connection.execute(
            "SELECT state_revision, checkpoint_revision FROM turns WHERE turn_id = ? AND owner_user_id = ?",
            (str(turn_id), str(owner_user_id)),
        ).fetchone()
        if turn is None:
            raise InvariantViolation("candidate Turn disappeared during claim")
        changed = connection.execute(
            """UPDATE p2_candidate_turns SET claim_epoch = claim_epoch + 1,
                read_epoch = read_epoch + 1, lifecycle = 'active', context_revision = ?,
                turn_state_revision = ?, revision = revision + 1, updated_at = ?
                WHERE turn_id = ? AND owner_user_id = ? AND revision = ? AND profile_id = ?""",
            (
                int(turn["checkpoint_revision"]), int(turn["state_revision"]), _timestamp(now),
                str(turn_id), str(owner_user_id), int(candidate["revision"]), P2_CANDIDATE_PROFILE_ID,
            ),
        ).rowcount
        if changed != 1:
            raise StateConflict("candidate claim invalidation lost its Store CAS")

    def _load_migrations(self) -> tuple[_Migration, ...]:
        directory = Path(__file__).resolve().parents[1] / "migrations"
        files = sorted(directory.glob("*.sql"))
        migrations: list[_Migration] = []
        for expected_version, path in enumerate(files, start=1):
            raw = path.read_bytes()
            prefix, _, name = path.stem.partition("_")
            try:
                version = int(prefix)
            except ValueError:
                raise StorageStartupError("SQLite migration filenames must begin with an ordered version") from None
            if version != expected_version:
                raise StorageStartupError("SQLite migration versions must be contiguous and start at one")
            migrations.append(_Migration(version, name or path.stem, raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()))
        if len(migrations) != 1 or migrations[0].version != 1:
            raise StorageStartupError("candidate Store migration requires the frozen initial migration as version 1")
        candidate_migration = Path(__file__).resolve().with_name("p2_read_store_migration.sql")
        if not candidate_migration.is_file():
            raise StorageStartupError("the Agent-owned candidate Store migration is missing")
        raw = candidate_migration.read_bytes()
        migrations.append(
            _Migration(2, "p2_read_candidate", raw.decode("utf-8"), hashlib.sha256(raw).hexdigest())
        )
        v3_candidate_migration = Path(__file__).resolve().with_name("p2_source_store_v3_migration.sql")
        if not v3_candidate_migration.is_file():
            raise StorageStartupError("the Agent-owned P2 v3 Store migration is missing")
        raw = v3_candidate_migration.read_bytes()
        migrations.append(
            _Migration(3, "p2_source_candidate", raw.decode("utf-8"), hashlib.sha256(raw).hexdigest())
        )
        source_proof_migration = Path(__file__).resolve().with_name("p2_v3_source_proof_migration.sql")
        if not source_proof_migration.is_file():
            raise StorageStartupError("the Agent-owned P2 v3 source proof migration is missing")
        raw = source_proof_migration.read_bytes()
        migrations.append(
            _Migration(4, "p2_v3_source_proofs", raw.decode("utf-8"), hashlib.sha256(raw).hexdigest())
        )
        metadata_acceptance_migration = Path(__file__).resolve().with_name("p2_v3_metadata_acceptance_migration.sql")
        if not metadata_acceptance_migration.is_file():
            raise StorageStartupError("the Agent-owned P2 v3 metadata acceptance migration is missing")
        raw = metadata_acceptance_migration.read_bytes()
        migrations.append(
            _Migration(5, "p2_v3_metadata_acceptance", raw.decode("utf-8"), hashlib.sha256(raw).hexdigest())
        )
        scope_fence_capture_migration = Path(__file__).resolve().with_name("p2_v3_scope_fence_capture_migration.sql")
        if not scope_fence_capture_migration.is_file():
            raise StorageStartupError("the Agent-owned P2 v3 scope-fence capture migration is missing")
        raw = scope_fence_capture_migration.read_bytes()
        migrations.append(
            _Migration(6, "p2_v3_scope_fence_capture", raw.decode("utf-8"), hashlib.sha256(raw).hexdigest())
        )
        mock_execution_migration = Path(__file__).resolve().with_name("p3_mock_execution_migration.sql")
        if not mock_execution_migration.is_file():
            raise StorageStartupError("the Agent-owned P3a mock execution migration is missing")
        raw = mock_execution_migration.read_bytes()
        migrations.append(
            _Migration(7, "p3_mock_execution", raw.decode("utf-8"), hashlib.sha256(raw).hexdigest())
        )
        return tuple(migrations)

    def _migrate(self, connection: sqlite3.Connection) -> None:
        current = int(connection.execute("PRAGMA user_version").fetchone()[0])
        latest = self._migrations[-1].version
        if current > latest:
            raise OSError("database schema version is newer than this service")
        tables = {
            str(row[0]) for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if current == 0 and tables:
            raise OSError("version-zero database contains unexpected application tables")
        if current > 0 and "schema_migrations" not in tables:
            raise OSError("schema migration record is missing")
        if current == 0:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
                )
                self._apply_migration(connection, self._migrations[0])
                connection.execute(
                    "INSERT INTO schema_migrations(version, name, checksum, applied_at) VALUES (?, ?, ?, ?)",
                    (1, self._migrations[0].name, self._migrations[0].checksum, _timestamp(_aware_now(None))),
                )
                connection.execute("PRAGMA user_version = 1")
                self._fault("migration.before_commit")
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            current = 1
        self._validate_migration_ledger(connection, current)
        while current < latest:
            migration = self._migrations[current]
            connection.execute("BEGIN IMMEDIATE")
            try:
                locked_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if locked_version != current:
                    raise OSError("SQLite schema changed while applying an Agent migration")
                self._validate_migration_ledger(connection, current)
                self._apply_migration(connection, migration)
                connection.execute(
                    "INSERT INTO schema_migrations(version, name, checksum, applied_at) VALUES (?, ?, ?, ?)",
                    (migration.version, migration.name, migration.checksum, _timestamp(_aware_now(None))),
                )
                connection.execute(f"PRAGMA user_version = {migration.version}")
                self._fault(f"migration.{migration.version}.before_commit")
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            current = migration.version
        self._validate_migration_ledger(connection, latest)

    def _validate_migration_ledger(self, connection: sqlite3.Connection, current: int) -> None:
        records = connection.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        expected = self._migrations[:current]
        if len(records) != current:
            raise OSError("migration ledger is incomplete")
        for row, migration in zip(records, expected, strict=True):
            if int(row["version"]) != migration.version or row["name"] != migration.name or row["checksum"] != migration.checksum:
                raise OSError("migration version or checksum does not match installed code")

    @staticmethod
    def _apply_migration(connection: sqlite3.Connection, migration: _Migration) -> None:
        for statement in _sql_statements(migration.sql):
            connection.execute(statement)

    def _verify_schema(self, connection: sqlite3.Connection) -> None:
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if user_version != self._migrations[-1].version:
            raise OSError("SQLite user_version does not match the migration set")
        records = connection.execute("SELECT version, name, checksum FROM schema_migrations ORDER BY version").fetchall()
        if len(records) != len(self._migrations):
            raise OSError("SQLite migration ledger is incomplete")
        for row, migration in zip(records, self._migrations, strict=True):
            if (int(row["version"]), row["name"], row["checksum"]) != (migration.version, migration.name, migration.checksum):
                raise OSError("SQLite migration ledger checksum is invalid")
        actual_signature = self._schema_signature(connection)
        expected_signature = self._expected_schema_signature()
        if actual_signature != expected_signature:
            raise OSError("SQLite schema objects differ from the installed migration")
        if not bool(connection.execute("PRAGMA foreign_keys").fetchone()[0]):
            raise OSError("SQLite foreign keys are disabled on this connection")

    def _expected_schema_signature(self) -> tuple[tuple[object, ...], ...]:
        memory = sqlite3.connect(":memory:", isolation_level=None)
        try:
            memory.row_factory = sqlite3.Row
            memory.execute("PRAGMA foreign_keys=ON")
            memory.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)")
            memory.execute("BEGIN IMMEDIATE")
            for migration in self._migrations:
                self._apply_migration(memory, migration)
                memory.execute(
                    "INSERT INTO schema_migrations(version, name, checksum, applied_at) VALUES (?, ?, ?, ?)",
                    (migration.version, migration.name, migration.checksum, "2000-01-01T00:00:00+00:00"),
                )
                memory.execute(f"PRAGMA user_version = {migration.version}")
            memory.execute("COMMIT")
            return self._schema_signature(memory)
        finally:
            memory.close()

    @staticmethod
    def _schema_signature(connection: sqlite3.Connection) -> tuple[tuple[object, ...], ...]:
        return tuple(
            tuple(row)
            for row in connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
            ).fetchall()
        )

    @staticmethod
    def _verify_database_integrity(connection: sqlite3.Connection) -> None:
        integrity = [str(row[0]) for row in connection.execute("PRAGMA integrity_check").fetchall()]
        if integrity != ["ok"]:
            raise OSError("SQLite integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise OSError("SQLite foreign key check failed")

    def _verify_all_rows(self, connection: sqlite3.Connection) -> None:
        for row in connection.execute("SELECT * FROM sessions").fetchall():
            private = self._session_private(row)
            if str(private.record.session_id) != row["session_id"] or str(private.record.owner_user_id) != row["owner_user_id"]:
                raise OSError("session JSON does not match its indexed owner or identifier")
        for row in connection.execute("SELECT * FROM turns").fetchall():
            aggregate = self._turn_aggregate(row)
            self._validate_latest_status(connection, aggregate)
            for provenance in aggregate.checkpoint.event_provenance:
                event_row = connection.execute(
                    "SELECT * FROM events WHERE turn_id = ? AND owner_user_id = ? AND seq = ?",
                    (str(aggregate.record.turn.turn_id), str(aggregate.record.turn.owner_user_id), provenance.seq),
                ).fetchone()
                if event_row is None:
                    raise OSError("safe event provenance has no durable event")
                event_record = self._event_record(connection, event_row, aggregate)
                if not getattr(event_record.event, "simulation", False) or _event_digest(event_record.event) != provenance.event_sha256:
                    raise OSError("safe event provenance does not match its durable event")
        for row in connection.execute("SELECT * FROM proposals").fetchall():
            self._proposal_record(row)
        for row in connection.execute("SELECT * FROM events").fetchall():
            aggregate = self._turn_aggregate(connection.execute("SELECT * FROM turns WHERE turn_id = ?", (row["turn_id"],)).fetchone())
            self._event_record(connection, row, aggregate)

    def _session_private(self, row: sqlite3.Row) -> SessionPrivate:
        private = _load_json(SessionPrivate, row["private_json"])
        record = private.record
        if (
            str(record.session_id) != row["session_id"]
            or str(record.owner_user_id) != row["owner_user_id"]
            or str(record.create_request_id) != row["create_request_id"]
            or record.create_payload_hash != row["create_payload_hash"]
            or _dump_json(record.create_response) != row["create_response_json"]
            or private.create_request.client_request_id != record.create_request_id
            or _dump_json(private.create_request) != row["create_request_json"]
            or private.create_request.title != record.title
            or record.title != row["title"]
            or (str(record.default_activity_hint) if record.default_activity_hint else None) != row["default_activity_hint"]
            or _timestamp(record.created_at) != row["created_at"]
            or _timestamp(record.updated_at) != row["updated_at"]
            or record.create_response.session.session_id != record.session_id
            or record.create_response.session.title != record.title
            or record.create_response.session.created_at != record.created_at
            or record.create_response.session.updated_at > record.updated_at
            or canonical_payload_hash(ApiActionKind.SESSION_CREATE, private.create_request) != record.create_payload_hash
        ):
            raise InvariantViolation("session JSON projection does not match its durable columns")
        return private

    def _session_receipt(self, row: sqlite3.Row) -> RequestReceipt:
        private = self._session_private(row)
        return RequestReceipt(
            key_scope=ApiActionKind.SESSION_CREATE,
            owner_user_id=private.record.owner_user_id,
            resource_id=None,
            client_request_id=private.record.create_request_id,
            payload_hash=private.record.create_payload_hash,
            http_status=201,
            response_kind=RequestReceiptKind.SESSION_CREATED,
            response_snapshot=private.record.create_response,
            recorded_at=private.record.created_at,
        )

    def _turn_aggregate(self, row: sqlite3.Row) -> TurnAggregate:
        if row is None:
            raise InvariantViolation("turn row disappeared while reading")
        record = _load_json(TurnRecord, row["record_json"])
        checkpoint = _load_json(TurnCheckpoint, row["checkpoint_json"])
        snapshot = record.turn
        if (
            not checkpoint.accepted_inputs
            or str(snapshot.turn_id) != row["turn_id"]
            or str(snapshot.session_id) != row["session_id"]
            or str(snapshot.owner_user_id) != row["owner_user_id"]
            or snapshot.state.value != row["state"]
            or snapshot.state_revision != row["state_revision"]
            or snapshot.step.value != row["step"]
            or (str(snapshot.execution.execution_id) if snapshot.execution else None) != row["execution_id"]
            or (snapshot.execution_resolution.value if snapshot.execution_resolution else None) != row["execution_resolution"]
            or str(record.client_request_id) != row["client_request_id"]
            or record.request_payload_hash != row["request_payload_hash"]
            or checkpoint.accepted_inputs[0].client_request_id != record.client_request_id
            or checkpoint.accepted_inputs[0].payload_hash != record.request_payload_hash
            or not isinstance(checkpoint.accepted_inputs[0].payload, SubmitTurnRequest)
            or checkpoint.accepted_inputs[0].payload.text != record.original_text
            or checkpoint.accepted_inputs[0].payload.ui_context != record.ui_context_snapshot
            or checkpoint.accepted_inputs[0].action != ApiActionKind.TURN_SUBMIT
            or _dump_json(checkpoint.accepted_inputs[0].payload) != row["request_json"]
            or canonical_payload_hash(
                ApiActionKind.TURN_SUBMIT,
                checkpoint.accepted_inputs[0].payload,
                resource_id=snapshot.session_id,
            ) != record.request_payload_hash
        ):
            raise InvariantViolation("turn JSON projection does not match its durable columns")
        submit_receipts = [item for item in record.request_receipts if item.key_scope == ApiActionKind.TURN_SUBMIT]
        if (
            len(submit_receipts) != 1
            or submit_receipts[0].owner_user_id != snapshot.owner_user_id
            or submit_receipts[0].resource_id != snapshot.session_id
            or str(submit_receipts[0].client_request_id) != row["client_request_id"]
            or submit_receipts[0].payload_hash != record.request_payload_hash
            or not isinstance(submit_receipts[0].response_snapshot, SubmitTurnAccepted)
            or submit_receipts[0].response_snapshot.turn_id != snapshot.turn_id
        ):
            raise InvariantViolation("initial submit receipt does not bind this Turn and Session")
        self._validate_input_history(record, checkpoint)
        self._validate_binding_ownership(record)
        return TurnAggregate(
            record=record,
            checkpoint=checkpoint,
            queue_order=int(row["queue_order"]),
            checkpoint_revision=int(row["checkpoint_revision"]),
            claim_token=row["claim_token"],
            claim_until=_parse_datetime(row["claim_until"]) if row["claim_until"] else None,
        )

    @staticmethod
    def _validate_input_history(record: TurnRecord, checkpoint: TurnCheckpoint) -> None:
        turn = record.turn
        inputs = checkpoint.accepted_inputs
        receipts = record.request_receipts
        if not inputs or inputs[0].action != ApiActionKind.TURN_SUBMIT:
            raise InvariantViolation("a Turn must preserve its initial accepted submit input")
        if sum(item.action == ApiActionKind.TURN_SUBMIT for item in inputs) != 1:
            raise InvariantViolation("a Turn has exactly one initial submit input")
        receipt_by_key = {
            (item.key_scope, item.resource_id, item.client_request_id): item for item in receipts
        }
        if len(receipt_by_key) != len(receipts):
            raise InvariantViolation("request receipts are unique by scoped client request key")
        seen: set[tuple[ApiActionKind, Optional[uuid.UUID], ClientRequestId]] = set()
        accepted_keys: set[tuple[ApiActionKind, Optional[uuid.UUID], ClientRequestId]] = set()
        for accepted in inputs:
            request = accepted.payload
            resource_id = turn.session_id if accepted.action == ApiActionKind.TURN_SUBMIT else turn.turn_id
            key = (accepted.action, resource_id, accepted.client_request_id)
            if key in seen:
                raise InvariantViolation("accepted input keys are unique within a Turn")
            seen.add(key)
            accepted_keys.add(key)
            try:
                expected_hash = canonical_payload_hash(accepted.action, request, resource_id=resource_id)
            except (TypeError, ValueError):
                raise InvariantViolation("accepted input cannot be canonically hashed") from None
            receipt = receipt_by_key.get(key)
            if accepted.payload_hash != expected_hash:
                raise InvariantViolation("typed accepted input payload hash is invalid")
            if receipt is None:
                request = accepted.payload
                pending = checkpoint.adjustment_reservation
                closed = checkpoint.closed_adjustments
                reservation_matches = any(item is not None and (
                    item.client_request_id == accepted.client_request_id
                    and item.payload_hash == accepted.payload_hash
                    and item.expected_proposal_revision == getattr(request, "expected_proposal_revision", None)
                ) for item in [pending, *closed])
                if accepted.action != ApiActionKind.PROPOSAL_ADJUST or not reservation_matches:
                    raise InvariantViolation(
                        "receiptless accepted input must match a durable active or closed adjustment reservation"
                    )
                continue
            if (receipt.owner_user_id != turn.owner_user_id
                or receipt.payload_hash != accepted.payload_hash
                or receipt.recorded_at != accepted.accepted_at):
                raise InvariantViolation("typed accepted input must match its durable scoped receipt and payload hash")
            if accepted.action in (ApiActionKind.TURN_SUBMIT, ApiActionKind.CLARIFICATION_RESUME,
                                   ApiActionKind.AUTH_RESUME, ApiActionKind.PROPOSAL_ADJUST,
                                   ApiActionKind.TURN_CANCEL) and receipt.http_status != 202:
                raise InvariantViolation("accepted Turn action receipts use their fixed HTTP status")
            if accepted.action == ApiActionKind.TURN_SUBMIT:
                response = receipt.response_snapshot
                if (receipt.response_kind != RequestReceiptKind.TURN_ACCEPTED
                    or not isinstance(response, SubmitTurnAccepted)
                    or response.turn_id != turn.turn_id
                    or response.state != TurnState.QUEUED.value
                    or response.state_revision != 1
                    or response.accepted_at != accepted.accepted_at):
                    raise InvariantViolation("initial submit receipt does not preserve its accepted response")
            elif accepted.action == ApiActionKind.PROPOSAL_ADJUST:
                response = receipt.response_snapshot
                if (receipt.response_kind != RequestReceiptKind.PROPOSAL_ADJUSTED
                    or not isinstance(response, ProposalAdjustedAccepted)
                    or response.turn_id != turn.turn_id):
                    raise InvariantViolation("proposal-adjust receipt does not preserve its typed response")
            elif accepted.action == ApiActionKind.TURN_CANCEL:
                if receipt.response_kind != RequestReceiptKind.TURN_CANCELLED or not isinstance(receipt.response_snapshot, CancelTurnResponse):
                    raise InvariantViolation("cancel receipt does not preserve its typed response")
            else:
                if receipt.response_kind != RequestReceiptKind.TURN_RESUMED or not isinstance(receipt.response_snapshot, TurnMutationAccepted):
                    raise InvariantViolation("resume receipt does not preserve its typed response")
                if receipt.response_snapshot.turn_id != turn.turn_id:
                    raise InvariantViolation("resume response belongs to another Turn")
        if not set(receipt_by_key).issubset(accepted_keys):
            raise InvariantViolation("every durable request receipt must match an accepted Turn input")

    @staticmethod
    def _close_adjustment_reservation(checkpoint: TurnCheckpoint) -> TurnCheckpoint:
        reservation = checkpoint.adjustment_reservation
        if reservation is None:
            return checkpoint
        if len(checkpoint.closed_adjustments) >= 257:
            raise InvariantViolation("closed adjustment history capacity exceeded")
        closed = reservation.model_copy(update={"lease_token": None, "lease_expires_at": None})
        return checkpoint.model_copy(update={
            "adjustment_reservation": None,
            "closed_adjustments": [*checkpoint.closed_adjustments, closed],
        })

    @staticmethod
    def _validate_binding_ownership(record: TurnRecord) -> None:
        turn_id = record.turn.turn_id
        if any(item.source_turn_id != turn_id for item in record.bound_references):
            raise InvariantViolation("entity binding points to a different Turn")
        if any(item.source_turn_id != turn_id for item in record.bound_evidence_references):
            raise InvariantViolation("evidence binding points to a different Turn")
        if any(item.source_turn_id != turn_id for item in record.bound_read_results):
            raise InvariantViolation("read-result binding points to a different Turn")

    def _proposal_record(self, row: sqlite3.Row) -> ProposalRecord:
        record = _load_json(ProposalRecord, row["record_json"])
        if (
            str(record.proposal_id) != row["proposal_id"]
            or str(record.owner_user_id) != row["owner_user_id"]
            or str(record.session_id) != row["session_id"]
            or str(record.turn_id) != row["turn_id"]
            or record.revision != row["revision"]
            or record.status.value != row["status"]
        ):
            raise InvariantViolation("proposal JSON projection does not match its durable columns")
        return record

    def _event_record(self, connection: sqlite3.Connection, row: sqlite3.Row, aggregate: TurnAggregate) -> EventRecord:
        event = AGENT_EVENT_ADAPTER.validate_json(row["event_json"])
        result = EventRecord(
            turn_id=uuid.UUID(row["turn_id"]), seq=int(row["seq"]), event=event,
            created_at=_parse_datetime(row["created_at"]),
        )
        snapshot = aggregate.record.turn
        if (
            row["owner_user_id"] != str(snapshot.owner_user_id)
            or row["session_id"] != str(snapshot.session_id)
            or event.seq != row["seq"]
            or event.type != row["event_type"]
            or event.occurred_at != result.created_at
        ):
            raise InvariantViolation("event JSON does not match its turn, owner, or sequence projection")
        if isinstance(event, ProposalEvent):
            proposal = connection.execute(
                "SELECT * FROM proposals WHERE proposal_id = ? AND owner_user_id = ?",
                (str(event.payload.proposal_id), str(snapshot.owner_user_id)),
            ).fetchone()
            if proposal is None:
                raise InvariantViolation("proposal event references a missing owner-scoped proposal")
            record = self._proposal_record(proposal)
            if record.turn_id != snapshot.turn_id or record.session_id != snapshot.session_id or record.revision < event.payload.revision:
                raise InvariantViolation("proposal event reference does not belong to its source Turn")
        if event.type == "message":
            evidence = {item.evidence_ref for item in aggregate.record.bound_evidence_references}
            evidence.update(item.evidence_ref for item in aggregate.checkpoint.persisted_policy_evidence)
            if any(citation not in evidence for citation in event.payload.citations):
                raise InvariantViolation("message event cites evidence outside its persisted Turn")
        return result

    @staticmethod
    def _validate_latest_status(connection: sqlite3.Connection, aggregate: TurnAggregate) -> None:
        latest = connection.execute(
            "SELECT event_json FROM events WHERE turn_id = ? AND event_type = 'status' ORDER BY seq DESC LIMIT 1",
            (str(aggregate.record.turn.turn_id),),
        ).fetchone()
        if latest is None:
            raise InvariantViolation("every durable Turn must have an initial status event")
        event = AGENT_EVENT_ADAPTER.validate_json(latest["event_json"])
        snapshot = aggregate.record.turn
        if not isinstance(event, StatusEvent) or (
            event.payload.state != snapshot.state
            or event.payload.state_revision != snapshot.state_revision
            or event.payload.step != snapshot.step
            or event.payload.wait_reason != snapshot.wait_reason
            or event.payload.resume_state != snapshot.resume_state
        ):
            raise InvariantViolation("latest status event does not match the durable Turn snapshot")

    def _proposal_by_id(self, connection: sqlite3.Connection, owner_user_id: UserId, proposal_id: uuid.UUID) -> ProposalRecord:
        row = connection.execute(
            "SELECT * FROM proposals WHERE proposal_id = ? AND owner_user_id = ?",
            (str(proposal_id), str(owner_user_id)),
        ).fetchone()
        if row is None:
            raise StoreNotFound("proposal is not available to this owner")
        return self._proposal_record(row)

    @staticmethod
    def _owned_turn(connection: sqlite3.Connection, owner_user_id: UserId, turn_id: TurnId) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM turns WHERE turn_id = ? AND owner_user_id = ?",
            (str(turn_id), str(owner_user_id)),
        ).fetchone()
        if row is None:
            raise StoreNotFound("turn is not available to this owner")
        return row

    @staticmethod
    def _record_with_updates(
        record: TurnRecord,
        *,
        turn: Optional[TurnStateSnapshot] = None,
        bound_references: Optional[list[BoundReference]] = None,
        bound_evidence_references: Optional[list[BoundEvidenceReference]] = None,
        bound_read_results: Optional[list[BoundReadResultReference]] = None,
    ) -> TurnRecord:
        document = record.model_dump(mode="python", by_alias=True, exclude_none=False)
        if turn is not None:
            document["turn"] = turn.model_dump(mode="python", by_alias=True, exclude_none=False)
        if bound_references is not None:
            document["bound_references"] = [item.model_dump(mode="python", by_alias=True, exclude_none=False) for item in bound_references]
        if bound_evidence_references is not None:
            document["bound_evidence_references"] = [item.model_dump(mode="python", by_alias=True, exclude_none=False) for item in bound_evidence_references]
        if bound_read_results is not None:
            document["bound_read_results"] = [item.model_dump(mode="python", by_alias=True, exclude_none=False) for item in bound_read_results]
        return TurnRecord.model_validate(document)

    @staticmethod
    def _record_with_receipt(record: TurnRecord, receipt: RequestReceipt) -> TurnRecord:
        document = record.model_dump(mode="python", by_alias=True, exclude_none=False)
        document["request_receipts"] = [
            *[item.model_dump(mode="python", by_alias=True, exclude_none=False) for item in record.request_receipts],
            receipt.model_dump(mode="python", by_alias=True, exclude_none=False),
        ]
        return TurnRecord.model_validate(document)

    def _validate_append_only_bindings(
        self,
        before: TurnAggregate,
        after: TurnRecord,
        checkpoint: TurnCheckpoint,
    ) -> None:
        if after.turn.turn_id != before.record.turn.turn_id or after.turn.session_id != before.record.turn.session_id or after.turn.owner_user_id != before.record.turn.owner_user_id:
            raise InvariantViolation("turn owner and resource identity are immutable")
        if after.original_text != before.record.original_text or after.ui_context_snapshot != before.record.ui_context_snapshot:
            raise InvariantViolation("initial accepted input is immutable")
        self._append_only_by_key(before.record.bound_references, after.bound_references, lambda item: item.ref, "entity refs")
        self._append_only_by_key(before.record.bound_evidence_references, after.bound_evidence_references, lambda item: item.evidence_ref, "evidence refs")
        self._append_only_by_key(before.record.bound_read_results, after.bound_read_results, lambda item: item.result_ref, "read-result refs")
        old_inputs = before.checkpoint.accepted_inputs
        if len(checkpoint.accepted_inputs) < len(old_inputs) or checkpoint.accepted_inputs[:len(old_inputs)] != old_inputs:
            raise InvariantViolation("accepted user input history is append-only")
        old_provenance = before.checkpoint.event_provenance
        if len(checkpoint.event_provenance) < len(old_provenance) or checkpoint.event_provenance[:len(old_provenance)] != old_provenance:
            raise InvariantViolation("event provenance is append-only")
        old_closed_adjustments = before.checkpoint.closed_adjustments
        if (len(checkpoint.closed_adjustments) < len(old_closed_adjustments)
            or checkpoint.closed_adjustments[:len(old_closed_adjustments)] != old_closed_adjustments):
            raise InvariantViolation("closed adjustment history is append-only")
        if len({item.seq for item in checkpoint.event_provenance}) != len(checkpoint.event_provenance):
            raise InvariantViolation("event provenance sequence numbers are unique")
        generation_delta = checkpoint.generation - before.checkpoint.generation
        input_delta = len(checkpoint.accepted_inputs) - len(old_inputs)
        if generation_delta == 0:
            if input_delta not in (0, 1):
                raise InvariantViolation("one non-planning action may append at most one accepted input")
            if input_delta == 1 and checkpoint.accepted_inputs[-1].action not in (
                ApiActionKind.AUTH_RESUME, ApiActionKind.TURN_CANCEL
            ):
                raise InvariantViolation("new planning input must start a fresh advance generation")
            if (checkpoint.model_calls < before.checkpoint.model_calls
                or checkpoint.read_calls < before.checkpoint.read_calls
                or checkpoint.repair_calls < before.checkpoint.repair_calls):
                raise InvariantViolation("runtime call counters cannot decrease within an advance generation")
        elif generation_delta == 1 and input_delta == 1:
            new_input = checkpoint.accepted_inputs[-1]
            if new_input.action not in (ApiActionKind.CLARIFICATION_RESUME, ApiActionKind.PROPOSAL_ADJUST):
                raise InvariantViolation("only a new clarification or proposal adjustment starts a planning generation")
        else:
            raise InvariantViolation("advance generation can move only with one accepted user planning input")
        reservation = checkpoint.adjustment_reservation
        closed_by_key = {
            (item.client_request_id, item.payload_hash): item
            for item in checkpoint.closed_adjustments
        }
        if len(closed_by_key) != len(checkpoint.closed_adjustments):
            raise InvariantViolation("closed adjustment identities are unique")
        accepted_adjustments = {
            (item.client_request_id, item.payload_hash)
            for item in checkpoint.accepted_inputs
            if item.action == ApiActionKind.PROPOSAL_ADJUST
        }
        if not set(closed_by_key).issubset(accepted_adjustments):
            raise InvariantViolation("closed adjustments must match accepted inputs")
        if reservation is not None:
            latest = next((item for item in checkpoint.accepted_inputs
                           if item.client_request_id == reservation.client_request_id
                           and item.payload_hash == reservation.payload_hash), None)
            if (
                latest is None
                or latest.action != ApiActionKind.PROPOSAL_ADJUST
                or latest.client_request_id != reservation.client_request_id
                or latest.payload_hash != reservation.payload_hash
                or not isinstance(latest.payload, ResumeProposalAdjustRequest)
                or latest.payload.expected_proposal_revision != reservation.expected_proposal_revision
            ):
                raise InvariantViolation("proposal adjustment reservation must bind its exact accepted input")
        old_reads = {str(item.result_id): item for item in before.checkpoint.read_results}
        new_reads = {str(item.result_id): item for item in checkpoint.read_results}
        if any(key not in new_reads or new_reads[key] != value for key, value in old_reads.items()):
            raise InvariantViolation("persisted read-result snapshots are append-only")
        if len(new_reads) != len(checkpoint.read_results) or len({item.result_ref for item in checkpoint.read_results}) != len(checkpoint.read_results):
            raise InvariantViolation("read-result IDs and tokens must be unique within a Turn")
        old_policy = {item.evidence_ref: item for item in before.checkpoint.persisted_policy_evidence}
        new_policy = {item.evidence_ref: item for item in checkpoint.persisted_policy_evidence}
        if any(key not in new_policy or new_policy[key] != value for key, value in old_policy.items()):
            raise InvariantViolation("persisted policy evidence cannot be removed or rebound")
        if len(new_policy) != len(checkpoint.persisted_policy_evidence):
            raise InvariantViolation("policy evidence tokens must be unique within a Turn")
        bound_reads = {item.result_id: item for item in after.bound_read_results}
        evidence_by_ref = {item.evidence_ref: item for item in after.bound_evidence_references}
        entity_by_ref = {item.ref: item for item in after.bound_references}
        for result in checkpoint.read_results:
            reference = bound_reads.get(result.result_id)
            if reference is None or (
                reference.result_ref != result.result_ref
                or reference.source_turn_id != after.turn.turn_id
                or reference.operation != result.operation
                or reference.observed_at != result.observed_at
                or reference.context_version != result.context_version
                or result.context_version != after.turn.context_version
            ):
                raise InvariantViolation("read-result snapshot lacks its same-Turn durable reference")
            for fact in result.body.items:
                evidence = evidence_by_ref.get(fact.evidence_ref)
                if evidence is None or evidence.source_result_id != result.result_id or evidence.kind != fact.kind:
                    raise InvariantViolation("read-result facts must bind typed evidence to their exact durable result")
                ref_tokens = []
                if isinstance(fact, ActivityFact):
                    ref_tokens = [(fact.activity_ref, "activity")]
                elif isinstance(fact, ExpenseFact):
                    ref_tokens = [(fact.expense_ref, "expense"), *((item, "participant") for item in fact.participant_refs)]
                elif isinstance(fact, DebtFact):
                    ref_tokens = [(fact.debtor_ref, "participant"), (fact.creditor_ref, "participant")]
                for token, expected_kind in ref_tokens:
                    bound = entity_by_ref.get(token)
                    if bound is None or bound.kind != expected_kind or bound.source_turn_id != after.turn.turn_id:
                        raise InvariantViolation("read-result fact entity tokens must resolve to same-Turn typed references")
        for evidence in after.bound_evidence_references:
            if evidence.source_turn_id != after.turn.turn_id or evidence.source_result_id not in bound_reads:
                raise InvariantViolation("evidence must point to a read result in the same Turn")
        for reference in after.bound_references:
            if reference.source_turn_id != after.turn.turn_id:
                raise InvariantViolation("entity reference must point to this Turn")
            if reference.kind == "activity" and reference.entity_id != reference.scope_activity_id:
                raise InvariantViolation("Activity references scope to themselves")
            if reference.kind != "activity" and not any(
                item.kind == "activity" and item.entity_id == reference.scope_activity_id
                and item.source_turn_id == after.turn.turn_id for item in after.bound_references
            ):
                raise InvariantViolation("entity reference activity scope must be bound in this Turn")
        if checkpoint.model_context is not None:
            if checkpoint.model_context.context_version != after.turn.context_version:
                raise InvariantViolation("model context version must match the persisted Turn snapshot")
            expected_read_projection = [ModelReadResult(
                result_ref=item.result_ref, operation=item.operation,
                observed_at=item.observed_at, context_version=item.context_version,
                simulation=item.simulation, body=item.body,
            ) for item in checkpoint.read_results]
            if checkpoint.model_context.read_results != expected_read_projection:
                raise InvariantViolation("model-visible read facts must equal the durable full result bodies")
            try:
                from .contracts import validate_model_context_bindings

                validate_model_context_bindings(
                    checkpoint.model_context,
                    source_turn_id=after.turn.turn_id,
                    bound_references=after.bound_references,
                    bound_evidence_references=after.bound_evidence_references,
                    bound_read_results=after.bound_read_results,
                )
            except ValueError:
                raise InvariantViolation("model context does not match this Turn's persisted references") from None
            for item in checkpoint.model_context.policy_evidence:
                if item.evidence_ref not in new_policy or new_policy[item.evidence_ref] != item:
                    raise InvariantViolation("model context policy evidence must be persisted in the checkpoint")
            if checkpoint.last_decision is not None:
                try:
                    from .contracts import validate_decision_against_context

                    validate_decision_against_context(checkpoint.last_decision, checkpoint.model_context)
                except ValueError:
                    raise InvariantViolation("stored semantic decision does not match its typed model context") from None

    @staticmethod
    def _append_only_by_key(old: list[object], new: list[object], key: Callable[[object], object], label: str) -> None:
        indexed = {key(item): item for item in new}
        if any(key(item) not in indexed or indexed[key(item)] != item for item in old):
            raise InvariantViolation(f"persisted {label} cannot be removed or rebound")
        if len(indexed) != len(new):
            raise InvariantViolation(f"persisted {label} tokens must be unique")

    def _append_accepted_input(
        self,
        checkpoint: TurnCheckpoint,
        scope: ApiActionKind,
        request: AcceptedRequest,
        payload_hash: str,
        instant: datetime,
        *,
        advance_generation: bool = False,
    ) -> TurnCheckpoint:
        if len(checkpoint.accepted_inputs) >= 257:
            raise InvariantViolation("accepted input history capacity exceeded")
        updated = checkpoint.model_dump(mode="python", by_alias=True, exclude_none=False)
        updated["accepted_inputs"] = [
                *[item.model_dump(mode="python", by_alias=True, exclude_none=False) for item in checkpoint.accepted_inputs],
                AcceptedInput(action=scope, client_request_id=request.client_request_id,
                              payload_hash=payload_hash, payload=request, accepted_at=instant)
                 .model_dump(mode="python", by_alias=True, exclude_none=False),
            ]
        if advance_generation:
            updated["generation"] = checkpoint.generation + 1
            updated["model_calls"] = 0
            updated["read_calls"] = 0
            updated["repair_calls"] = 0
        return TurnCheckpoint.model_validate(updated)

    @staticmethod
    def _validate_after_owner_session(after: TurnStateSnapshot, owner_user_id: UserId, record: TurnRecord) -> None:
        if after.owner_user_id != owner_user_id or after.turn_id != record.turn.turn_id or after.session_id != record.turn.session_id:
            raise InvariantViolation("state update cannot change owner or resource identity")

    def _validate_proposal_scope(self, proposal: ProposalRecord, turn: TurnStateSnapshot) -> None:
        if proposal.owner_user_id != turn.owner_user_id or proposal.session_id != turn.session_id or proposal.turn_id != turn.turn_id:
            raise InvariantViolation("proposal must belong to the current owner, Session, and Turn")

    @staticmethod
    def _preserve_proposal_receipts(current: ProposalRecord, replacement: ProposalRecord) -> ProposalRecord:
        known = {item.client_request_id: item for item in current.request_receipts}
        for item in replacement.request_receipts:
            if known.get(item.client_request_id) != item:
                raise InvariantViolation("proposal replacement cannot rewrite or invent confirmation receipts")
        document = replacement.model_dump(mode="python", by_alias=True, exclude_none=False)
        document["request_receipts"] = [
            item.model_dump(mode="python", by_alias=True, exclude_none=False)
            for item in current.request_receipts
        ]
        return ProposalRecord.model_validate(document)

    def _pending_proposal_for_turn(
        self,
        connection: sqlite3.Connection,
        owner_user_id: UserId,
        session_id: SessionId,
        turn_id: TurnId,
    ) -> Optional[ProposalRecord]:
        row = connection.execute(
            "SELECT * FROM proposals WHERE owner_user_id = ? AND session_id = ? AND turn_id = ? AND status = 'pending'",
            (str(owner_user_id), str(session_id), str(turn_id)),
        ).fetchone()
        return self._proposal_record(row) if row is not None else None

    def _insert_proposal(self, connection: sqlite3.Connection, proposal: ProposalRecord, instant: datetime) -> None:
        try:
            connection.execute(
                """INSERT INTO proposals(proposal_id, owner_user_id, session_id, turn_id, revision,
                    status, record_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(proposal.proposal_id), str(proposal.owner_user_id), str(proposal.session_id),
                 str(proposal.turn_id), proposal.revision, proposal.status.value, _dump_json(proposal),
                 _timestamp(instant), _timestamp(instant)),
            )
        except sqlite3.IntegrityError:
            raise ProposalConflict("proposal identity or one-pending-per-session constraint failed") from None

    def _append_events(
        self,
        connection: sqlite3.Connection,
        turn_id: TurnId,
        owner_user_id: UserId,
        session_id: SessionId,
        drafts: Sequence[EventDraft],
        record: TurnRecord,
        checkpoint: TurnCheckpoint,
        *,
        status_snapshots: Optional[Sequence[Optional[TurnStateSnapshot]]] = None,
    ) -> list[EventRecord]:
        appended: list[EventRecord] = []
        if status_snapshots is not None and len(status_snapshots) != len(drafts):
            raise InvariantViolation("event status snapshot mapping is incomplete")
        for index, draft in enumerate(drafts):
            sequence = self._next_event_seq(connection, turn_id)
            payload = draft.payload.model_dump(mode="python", by_alias=True, exclude_none=False)
            event_data = {
                "type": draft.type.value,
                "seq": sequence,
                "occurred_at": draft.occurred_at,
                "simulation": draft.simulation,
                "payload": payload,
            }
            try:
                event = AGENT_EVENT_ADAPTER.validate_python(event_data)
            except (ValidationError, ValueError):
                raise InvariantViolation("event payload does not match the frozen event contract") from None
            expected_status = status_snapshots[index] if status_snapshots is not None else None
            self._validate_event_payload(
                connection, turn_id, owner_user_id, session_id, event, record, checkpoint,
                status_snapshot=expected_status,
            )
            stored = EventRecord(turn_id=turn_id, seq=sequence, event=event, created_at=draft.occurred_at)
            connection.execute(
                "INSERT INTO events(turn_id, owner_user_id, session_id, seq, event_type, event_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(turn_id), str(owner_user_id), str(session_id), sequence, event.type,
                 _dump_json(event), _timestamp(draft.occurred_at)),
            )
            appended.append(stored)
        return appended

    def _validate_event_payload(
        self,
        connection: sqlite3.Connection,
        turn_id: TurnId,
        owner_user_id: UserId,
        session_id: SessionId,
        event: AgentEvent,
        record: TurnRecord,
        checkpoint: TurnCheckpoint,
        *,
        status_snapshot: Optional[TurnStateSnapshot] = None,
    ) -> None:
        if isinstance(event, ProposalEvent):
            row = connection.execute(
                "SELECT * FROM proposals WHERE proposal_id = ? AND owner_user_id = ?",
                (str(event.payload.proposal_id), str(owner_user_id)),
            ).fetchone()
            if row is None:
                raise InvariantViolation("proposal event has no persisted proposal")
            proposal = self._proposal_record(row)
            if proposal.turn_id != turn_id or proposal.session_id != session_id or proposal.revision != event.payload.revision:
                raise InvariantViolation("proposal event must reference the current proposal revision in this Turn")
        elif event.type == "message":
            valid = {item.evidence_ref for item in record.bound_evidence_references}
            if checkpoint.model_context is not None:
                valid.update(item.evidence_ref for item in checkpoint.model_context.policy_evidence)
            if any(item not in valid for item in event.payload.citations):
                raise InvariantViolation("message citations must resolve to persisted evidence for this Turn")
        elif event.type == "execution_result":
            execution = record.turn.execution
            if execution is None or event.payload.execution.execution_id != execution.execution_id or event.payload.execution.proposal_id != execution.proposal_id or event.payload.execution.proposal_revision != execution.proposal_revision:
                raise InvariantViolation("execution event must preserve the Turn's stable execution identity")
            if record.turn.execution_resolution != event.payload.resolution:
                raise InvariantViolation("execution event resolution must match the stored state snapshot")
        elif event.type == "status":
            snapshot = status_snapshot or record.turn
            payload = event.payload
            if (payload.state != snapshot.state or payload.state_revision != snapshot.state_revision or payload.step != snapshot.step
                or payload.wait_reason != snapshot.wait_reason or payload.resume_state != snapshot.resume_state):
                raise InvariantViolation("status event must match the Turn snapshot committed in this transaction")

    @staticmethod
    def _next_event_seq(connection: sqlite3.Connection, turn_id: TurnId) -> int:
        return int(connection.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE turn_id = ?", (str(turn_id),)
        ).fetchone()[0])

    @staticmethod
    def _status_draft(snapshot: TurnStateSnapshot, instant: datetime) -> EventDraft:
        return EventDraft(
            type=EventType.STATUS,
            occurred_at=instant,
            simulation=False,
            payload=StatusEventPayload(
                state=snapshot.state, step=snapshot.step, state_revision=snapshot.state_revision,
                wait_reason=snapshot.wait_reason, resume_state=snapshot.resume_state,
            ).model_dump(mode="python", by_alias=True, exclude_none=False),
        )

    @staticmethod
    def _validate_status_draft(snapshot: TurnStateSnapshot, draft: EventDraft) -> None:
        if draft.type != EventType.STATUS:
            return
        try:
            payload = StatusEventPayload.model_validate(draft.payload)
        except ValidationError:
            raise InvariantViolation("status event payload is invalid") from None
        if payload != StatusEventPayload(
            state=snapshot.state, step=snapshot.step, state_revision=snapshot.state_revision,
            wait_reason=snapshot.wait_reason, resume_state=snapshot.resume_state,
        ):
            raise InvariantViolation("status event must match the committed snapshot")

    @classmethod
    def _validate_status_event_in_batch(cls, snapshot: TurnStateSnapshot, events: Sequence[EventDraft]) -> None:
        matching = [event for event in events if event.type == EventType.STATUS]
        if len(matching) != 1:
            raise InvariantViolation("a state transition requires exactly one matching status event")
        cls._validate_status_draft(snapshot, matching[0])

    @staticmethod
    def _validate_turn_action(
        request: Union[ResumeClarificationRequest, ResumeAuthRequest, CancelTurnRequest],
        before: TurnStateSnapshot,
        after: TurnStateSnapshot,
        response: Union[TurnMutationAccepted, CancelTurnResponse],
    ) -> None:
        if isinstance(request, ResumeAuthRequest):
            if not isinstance(response, TurnMutationAccepted):
                raise ValueError("auth resume response type is invalid")
            validate_auth_resume(before, after, expected_state_revision=request.expected_state_revision)
        elif isinstance(request, ResumeClarificationRequest):
            if not isinstance(response, TurnMutationAccepted) or before.state != TurnState.WAIT_INPUT or before.wait_reason.value != "missing_fields" or before.execution is not None or after.state not in (TurnState.QUEUED, TurnState.RUNNING):
                raise ValueError("clarification resume requires an unassigned missing-fields wait")
            validate_state_transition(before, after, expected_state_revision=request.expected_state_revision)
        else:
            if not isinstance(response, CancelTurnResponse):
                raise ValueError("cancel response type is invalid")
            validate_cancel_transition(before, after, response, expected_state_revision=request.expected_state_revision)

    @staticmethod
    def _replay_or_conflict(
        stored: RequestReceipt,
        *,
        scope: ApiActionKind,
        owner_user_id: UserId,
        resource_id: Optional[uuid.UUID],
        request_id: ClientRequestId,
        payload_hash: str,
    ) -> RequestReceipt:
        try:
            return validate_idempotent_replay(
                stored, key_scope=scope, owner_user_id=owner_user_id,
                resource_id=resource_id, client_request_id=request_id, payload_hash=payload_hash,
            )
        except ValueError:
            raise IdempotencyConflict("idempotency key was already used with another resource or request body") from None

    @staticmethod
    def _check_claim(aggregate: TurnAggregate, claim_token: Optional[str], instant: datetime) -> None:
        if aggregate.claim_token is None:
            if claim_token is not None:
                raise StateConflict("turn claim is no longer current")
            return
        if aggregate.claim_until is not None and aggregate.claim_until <= instant:
            raise StateConflict("turn claim lease has expired")
        if claim_token != aggregate.claim_token:
            raise StateConflict("turn is claimed by another worker")

    def _check_admission(
        self,
        connection: sqlite3.Connection,
        owner_user_id: UserId,
        *,
        target_state: TurnState,
        excluding_turn_id: Optional[TurnId] = None,
        now: Optional[datetime] = None,
    ) -> None:
        if not self._admission_enabled or target_state not in (TurnState.QUEUED, TurnState.RUNNING):
            return
        exclusion = " AND turn_id != ?" if excluding_turn_id is not None else ""
        parameters: tuple[object, ...] = (str(owner_user_id),) + ((str(excluding_turn_id),) if excluding_turn_id else ())
        running = int(connection.execute(
            "SELECT COUNT(*) FROM turns WHERE owner_user_id = ? AND state = 'RUNNING'" + exclusion,
            parameters,
        ).fetchone()[0])
        reserved_parameters: tuple[object, ...] = (str(owner_user_id), _timestamp(_aware_now(now)))
        reserved_sql = (
            "SELECT COUNT(*) FROM turns WHERE owner_user_id = ? AND state = 'WAIT_CONFIRM' "
            "AND julianday(json_extract(checkpoint_json, '$.adjustment_reservation.lease_expires_at')) > julianday(?)"
        )
        if excluding_turn_id is not None:
            reserved_sql += " AND turn_id != ?"
            reserved_parameters += (str(excluding_turn_id),)
        reserved = int(connection.execute(reserved_sql, reserved_parameters).fetchone()[0])
        queued = int(connection.execute(
            "SELECT COUNT(*) FROM turns WHERE owner_user_id = ? AND state = 'QUEUED'" + exclusion,
            parameters,
        ).fetchone()[0])
        if target_state == TurnState.RUNNING and running + reserved >= 1:
            raise AdmissionFull("the owner already has a running Turn")
        if target_state == TurnState.QUEUED:
            global_queued = int(connection.execute(
                "SELECT COUNT(*) FROM turns WHERE state = 'QUEUED'" + (" AND turn_id != ?" if excluding_turn_id else ""),
                ((str(excluding_turn_id),) if excluding_turn_id else ()),
            ).fetchone()[0])
            if queued >= 1 or global_queued >= 16:
                raise AdmissionFull("Runtime queue capacity is full")

    def _touch_session(self, connection: sqlite3.Connection, session_id: SessionId, owner_user_id: UserId, instant: datetime) -> None:
        row = connection.execute(
            "SELECT * FROM sessions WHERE session_id = ? AND owner_user_id = ?",
            (str(session_id), str(owner_user_id)),
        ).fetchone()
        if row is None:
            raise StoreNotFound("session is not available to this owner")
        private = self._session_private(row)
        updated_at = max(instant, private.record.updated_at)
        updated_record = SessionRecord.model_validate(
            private.record.model_dump(mode="python", by_alias=True, exclude_none=False)
            | {"updated_at": updated_at}
        )
        updated_private = SessionPrivate(record=updated_record, create_request=private.create_request)
        connection.execute(
            "UPDATE sessions SET updated_at = ?, private_json = ? WHERE session_id = ? AND owner_user_id = ?",
            (_timestamp(updated_at), _dump_json(updated_private), str(session_id), str(owner_user_id)),
        )

    def _cancel_pending_proposals(
        self,
        connection: sqlite3.Connection,
        owner_user_id: UserId,
        session_id: SessionId,
        turn_id: TurnId,
        instant: datetime,
    ) -> None:
        rows = connection.execute(
            "SELECT * FROM proposals WHERE owner_user_id = ? AND session_id = ? AND turn_id = ? AND status = 'pending'",
            (str(owner_user_id), str(session_id), str(turn_id)),
        ).fetchall()
        for row in rows:
            current = self._proposal_record(row)
            document = current.model_dump(mode="python", by_alias=True, exclude_none=False)
            document["status"] = ProposalStatus.CANCELLED
            document["confirmation_nonce"] = None
            cancelled = ProposalRecord.model_validate(document)
            changed = connection.execute(
                "UPDATE proposals SET status = ?, record_json = ?, updated_at = ? "
                "WHERE proposal_id = ? AND owner_user_id = ? AND revision = ? AND status = 'pending'",
                (ProposalStatus.CANCELLED.value, _dump_json(cancelled), _timestamp(instant),
                 str(current.proposal_id), str(owner_user_id), current.revision),
            ).rowcount
            if changed != 1:
                raise ProposalConflict("pending proposal changed while cancelling its Turn")

    def _expire_stale_pending_proposals(
        self,
        connection: sqlite3.Connection,
        owner_user_id: UserId,
        session_id: SessionId,
        instant: datetime,
    ) -> None:
        rows = connection.execute(
            "SELECT * FROM proposals WHERE owner_user_id = ? AND session_id = ? AND status = 'pending'",
            (str(owner_user_id), str(session_id)),
        ).fetchall()
        for row in rows:
            proposal = self._proposal_record(row)
            if proposal.expires_at > instant:
                continue
            if proposal.execution is not None:
                # An assigned execution stays on its existing reconciliation path.
                continue
            turn_row = self._owned_turn(connection, owner_user_id, proposal.turn_id)
            aggregate = self._turn_aggregate(turn_row)
            before = aggregate.record.turn
            if not (
                before.state == TurnState.WAIT_CONFIRM
                or before.state == TurnState.WAIT_INPUT
                and before.wait_reason == WaitReason.AUTH_REQUIRED
                and before.resume_state == ResumeState.WAIT_CONFIRM
            ):
                raise InvariantViolation("pending proposal expiry must match its owner Turn waiting state")
            after = TurnStateSnapshot.model_validate(
                before.model_dump(mode="python", by_alias=True, exclude_none=False)
                | {"state": TurnState.FAILED, "step": TurnStep.TERMINAL,
                   "state_revision": before.state_revision + 1,
                   "wait_reason": None, "resume_state": None}
            )
            try:
                validate_state_transition(before, after, expected_state_revision=before.state_revision)
            except ValueError:
                raise InvariantViolation("expired proposal Turn cannot take its terminal state edge") from None
            expired = ProposalRecord.model_validate(
                proposal.model_dump(mode="python", by_alias=True, exclude_none=False)
                | {"status": ProposalStatus.EXPIRED, "confirmation_nonce": None}
            )
            changed = connection.execute(
                "UPDATE proposals SET status = ?, record_json = ?, updated_at = ? "
                "WHERE proposal_id = ? AND owner_user_id = ? AND revision = ? AND status = 'pending'",
                (expired.status.value, _dump_json(expired), _timestamp(instant),
                 str(proposal.proposal_id), str(owner_user_id), proposal.revision),
            ).rowcount
            if changed != 1:
                raise ProposalConflict("proposal changed while expiring its owner Turn")
            updated = self._record_with_updates(aggregate.record, turn=after)
            checkpoint = self._close_adjustment_reservation(aggregate.checkpoint).model_copy(update={
                "resume_step": None,
            })
            events = [
                EventDraft(
                    type=EventType.ERROR, occurred_at=instant, simulation=proposal.mode == "simulation",
                    payload=ErrorEventPayload(
                        code=ApiErrorCode.PROPOSAL_EXPIRED,
                        message="The simulation could not complete this step.", retryable=False,
                    ),
                ),
                EventDraft(
                    type=EventType.STATUS, occurred_at=instant, simulation=proposal.mode == "simulation",
                    payload=StatusEventPayload(
                        state=after.state, step=after.step, state_revision=after.state_revision,
                        wait_reason=None, resume_state=None,
                    ),
                ),
            ]
            appended = self._append_events(
                connection, before.turn_id, owner_user_id, session_id, events, updated, checkpoint,
            )
            checkpoint = _append_event_provenance(
                checkpoint, appended, ["system_error" if proposal.mode == "simulation" else None, None],
            )
            self._validate_append_only_bindings(aggregate, updated, checkpoint)
            changed = connection.execute(
                "UPDATE turns SET state = ?, state_revision = ?, step = ?, record_json = ?, "
                "checkpoint_json = ?, checkpoint_revision = ?, claim_token = NULL, claim_until = NULL, updated_at = ? "
                "WHERE turn_id = ? AND owner_user_id = ? AND state_revision = ? AND checkpoint_revision = ?",
                (after.state.value, after.state_revision, after.step.value, _dump_json(updated),
                 _dump_json(checkpoint), aggregate.checkpoint_revision + 1, _timestamp(instant),
                 str(before.turn_id), str(owner_user_id), before.state_revision, aggregate.checkpoint_revision),
            ).rowcount
            if changed != 1:
                raise StateConflict("turn changed while expiring its pending proposal")
            self._touch_session(connection, session_id, owner_user_id, instant)

    def _require_started(self) -> None:
        if not self._started:
            raise StoreNotStarted("SQLite store has not started")

    def _fault(self, name: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(name)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self._require_started()
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._path,
            timeout=self._busy_timeout_ms / 1000,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
        connection.execute("PRAGMA synchronous=FULL")
        if not bool(connection.execute("PRAGMA foreign_keys").fetchone()[0]):
            connection.close()
            raise OSError("SQLite foreign keys could not be enabled")
        return connection

    def _create_parent_directories(self, created: list[Path]) -> None:
        missing: list[Path] = []
        current = self._path.parent
        while not current.exists():
            missing.append(current)
            parent = current.parent
            if parent == current:
                break
            current = parent
        for directory in reversed(missing):
            directory.mkdir()
            created.append(directory)


def _sql_statements(source: str) -> Iterator[str]:
    buffer = ""
    for line in source.splitlines():
        buffer += line + "\n"
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                yield statement
            buffer = ""
    if buffer.strip():
        raise StorageStartupError("SQLite migration has an incomplete SQL statement")


def _dump_json(value: BaseModel) -> str:
    try:
        return json.dumps(
            value.model_dump(mode="json", by_alias=True, exclude_none=False),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        raise InvariantViolation("typed storage value cannot be encoded as canonical JSON") from None


def _event_digest(event: BaseModel) -> str:
    return hashlib.sha256(_dump_json(event).encode("utf-8")).hexdigest()


def _append_event_provenance(
    checkpoint: TurnCheckpoint,
    events: Sequence[EventRecord],
    sources: Optional[Sequence[Optional[str]]],
) -> TurnCheckpoint:
    if sources is None:
        return checkpoint
    if len(sources) != len(events):
        raise InvariantViolation("event provenance mapping must match the appended event batch")
    if not any(sources):
        return checkpoint
    additions: list[StoredEventProvenance] = []
    for event_record, source in zip(events, sources, strict=True):
        if source is None:
            continue
        event = event_record.event
        if not getattr(event, "simulation", False):
            raise InvariantViolation("only explicitly simulated Runtime events can carry safe provenance")
        valid = False
        if source == "conversation_answer":
            decision = checkpoint.last_decision
            context = checkpoint.model_context
            valid = (
                event.type == "message"
                and not event.payload.citations
                and isinstance(decision, AnswerDecision)
                and decision.basis == "conversation"
                and decision.text == event.payload.text
                and context is not None
                and context.verified_scope.kind == "none"
                and not context.bound_references
                and not context.read_results
            )
        elif source == "policy_answer":
            decision = checkpoint.last_decision
            policy_refs = {item.evidence_ref for item in checkpoint.persisted_policy_evidence}
            context = checkpoint.model_context
            valid = (
                event.type == "message"
                and bool(event.payload.citations)
                and all(isinstance(item, PolicyEvidenceRef) and item in policy_refs for item in event.payload.citations)
                and isinstance(decision, AnswerDecision)
                and decision.basis == "grounded"
                and decision.text == event.payload.text
                and decision.citations == event.payload.citations
                and context is not None
                and context.verified_scope.kind == "none"
                and not context.bound_references
                and not context.read_results
                and bool(context.policy_evidence)
                and all(item.evidence_ref in policy_refs for item in context.policy_evidence)
            )
        elif source == "clarification":
            clarification = checkpoint.last_clarification
            context = checkpoint.model_context
            valid = (
                event.type == "clarification"
                and clarification is not None
                and event.payload.prompt == clarification.prompt
                and event.payload.missing_slots == clarification.missing_slots
                and context is not None
                and context.verified_scope.kind == "none"
                and not context.bound_references
                and not context.read_results
            )
        elif source == "system_error":
            valid = (
                event.type == "error"
                and event.payload.message == "The simulation could not complete this step."
            )
        if not valid:
            raise InvariantViolation("safe event provenance does not match a persisted Runtime decision")
        additions.append(StoredEventProvenance(
            seq=event_record.seq,
            generation=checkpoint.generation,
            source=source,
            event_sha256=_event_digest(event),
        ))
    if not additions:
        return checkpoint
    if len(checkpoint.event_provenance) + len(additions) > 4096:
        raise InvariantViolation("safe event provenance capacity exceeded")
    return TurnCheckpoint.model_validate(
        checkpoint.model_dump(mode="python", by_alias=True, exclude_none=False)
        | {"event_provenance": [
            *[item.model_dump(mode="python", by_alias=True, exclude_none=False) for item in checkpoint.event_provenance],
            *[item.model_dump(mode="python", by_alias=True, exclude_none=False) for item in additions],
        ]}
    )


def event_has_safe_provenance(checkpoint: TurnCheckpoint, event: AgentEvent) -> bool:
    if not getattr(event, "simulation", False):
        return False
    allowed = {"conversation_answer", "policy_answer", "clarification", "system_error"}
    return any(
        item.seq == event.seq
        and item.source in allowed
        and item.event_sha256 == _event_digest(event)
        for item in checkpoint.event_provenance
    )


def _load_json(model: type[BaseModel], value: str) -> BaseModel:
    try:
        return model.model_validate_json(value)
    except (ValidationError, ValueError, TypeError):
        raise InvariantViolation("stored JSON failed its frozen or private typed model") from None


def _aware_now(value: Optional[datetime]) -> datetime:
    instant = value or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("timestamps must include a timezone")
    return instant.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _aware_now(value).isoformat(timespec="microseconds")


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise InvariantViolation("stored timestamp is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InvariantViolation("stored timestamp has no timezone")
    return parsed


def _public_status(snapshot: TurnStateSnapshot) -> TurnPublicStatus:
    return TurnPublicStatus(
        turn_id=snapshot.turn_id,
        session_id=snapshot.session_id,
        state=snapshot.state,
        step=snapshot.step,
        wait_reason=snapshot.wait_reason,
        resume_state=snapshot.resume_state,
        state_revision=snapshot.state_revision,
        execution_assigned=snapshot.execution is not None,
        execution_resolution=snapshot.execution_resolution,
        context_version=snapshot.context_version,
    )


def _action_for_request(
    request: Union[
        ResumeClarificationRequest,
        ResumeAuthRequest,
        ResumeProposalAdjustRequest,
        CancelTurnRequest,
        ConfirmProposalRequest,
    ],
) -> ApiActionKind:
    if isinstance(request, ResumeClarificationRequest):
        return ApiActionKind.CLARIFICATION_RESUME
    if isinstance(request, ResumeAuthRequest):
        return ApiActionKind.AUTH_RESUME
    if isinstance(request, ResumeProposalAdjustRequest):
        return ApiActionKind.PROPOSAL_ADJUST
    if isinstance(request, ConfirmProposalRequest):
        return ApiActionKind.PROPOSAL_CONFIRM
    return ApiActionKind.TURN_CANCEL
