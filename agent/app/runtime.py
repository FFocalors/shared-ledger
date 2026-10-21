"""P1-05 bounded Runtime for visibly simulated, deterministic offline turns."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
import uuid
import weakref
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from . import contracts as c, mock_fixtures
from .backend import MockBackendAdapter
from .harness import ModelOutputError, ModelPrompt, MockModelProvider, parse_model_output
from .p3_execution import MockActivityRoster
from .ports import (
    AgentControl, AgentStore, AuthVerifier, AgentDisabled, CapabilityUnavailable, ComponentHealth,
    Principal, ScopeAuthorizer, ScopeDenied, ScopeUnavailable,
)
from .store import (
    ClaimedTurn, EventDraft, StoreError, StoreNotFound, StateConflict,
    TurnAggregate, TurnCheckpoint,
)


_LOGGER = logging.getLogger(__name__)


class UnimplementedRuntime:
    """Health-only Runtime for the default provider-disabled service."""

    def start(self) -> None:
        pass

    def health(self) -> ComponentHealth:
        return ComponentHealth(status="not_implemented", available=False)

    def close(self) -> None:
        pass


@dataclass(frozen=True)
class _MemoryAuthGrant:
    token: str
    expires_at: datetime


class _AuthRequired(Exception):
    pass


class RuntimeAuthRequired(Exception):
    """A previously accepted adjustment paused at its durable auth checkpoint."""


class _GateClosed(AgentDisabled):
    pass


class _CallBudgetReached(Exception):
    pass


class _ModelTimeout(Exception):
    pass


class MockRuntime:
    """One-worker scheduler with persisted budgets, references, and mock-only I/O."""

    _LEASE_SECONDS = 30
    _MAX_AUTH_GRANTS = 1024
    _SAFE_ERROR = "The simulation could not complete this step."
    _WORKER_ID = "p1-mock-runtime"

    def __init__(
        self,
        store: AgentStore,
        provider: MockModelProvider,
        backend: MockBackendAdapter,
        auth_verifier: AuthVerifier,
        scope_authorizer: ScopeAuthorizer,
        agent_control: AgentControl,
        *,
        task_concurrency: int = 4,
        model_timeout_seconds: float = 2.0,
        shutdown_timeout_seconds: float = 2.0,
        enabled_candidate_profile_ids: Sequence[str] | None = None,
        activity_roster: MockActivityRoster | None = None,
    ) -> None:
        self._store = store
        self._provider = provider
        self._backend = backend
        self._auth = auth_verifier
        self._scope = scope_authorizer
        self._control = agent_control
        self._activity_roster = activity_roster
        self._task_concurrency = max(1, min(int(task_concurrency), 8))
        self._model_timeout = max(0.05, min(float(model_timeout_seconds), 10.0))
        self._shutdown_timeout = max(0.1, min(float(shutdown_timeout_seconds), 10.0))
        self._enabled_candidate_profile_ids = (
            tuple(dict.fromkeys(enabled_candidate_profile_ids))
            if enabled_candidate_profile_ids is not None else None
        )
        self._model_gate = asyncio.Semaphore(1)
        self._scheduler_task: asyncio.Task[None] | None = None
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}
        self._provider_tasks: set[asyncio.Task[str]] = set()
        self._claim_cleanup_tasks: set[asyncio.Task[None]] = set()
        self._worker_id: str | None = None
        self._claim_cancellation = threading.Event()
        self._deferred_recovery: set[uuid.UUID] = set()
        self._grants: dict[uuid.UUID, _MemoryAuthGrant] = {}
        self._grant_lock = threading.Lock()
        self._adjustment_locks: weakref.WeakValueDictionary[uuid.UUID, asyncio.Lock] = weakref.WeakValueDictionary()
        self._closing = False
        self._started = False

    def bind_auth_grant(self, principal: Principal, access_token: str) -> None:
        """Retain a verified token only in memory and only until its trusted expiry."""
        expiry = principal.expires_at
        if (
            expiry is None or expiry.tzinfo is None or expiry.utcoffset() is None
            or expiry <= datetime.now(timezone.utc) or not isinstance(access_token, str)
            or not access_token or len(access_token) > 16_384
        ):
            return
        with self._grant_lock:
            now = datetime.now(timezone.utc)
            self._grants = {
                user_id: grant for user_id, grant in self._grants.items()
                if grant.expires_at > now
            }
            if principal.user_id not in self._grants and len(self._grants) >= self._MAX_AUTH_GRANTS:
                # Fail closed rather than retain an unbounded token cache. The next
                # request can retry after an expired grant is pruned.
                return
            self._grants[principal.user_id] = _MemoryAuthGrant(access_token, expiry.astimezone(timezone.utc))

    def health(self) -> ComponentHealth:
        return ComponentHealth(status="simulation", available=True)

    async def start(self) -> None:
        if self._started:
            raise RuntimeError("Mock Runtime is already started")
        self._closing = False
        self._deferred_recovery.clear()
        # A process may have stopped between any two checkpoint writes. Ordinary
        # planning returns to the durable queue; execution work remains RECOVERING.
        await asyncio.to_thread(self._store.recover_interrupted_turns)
        self._worker_id = f"{self._WORKER_ID}:{uuid.uuid4()}"
        self._claim_cancellation = threading.Event()
        self._started = True
        self._scheduler_task = asyncio.create_task(self._scheduler(), name="p1-mock-runtime-scheduler")

    def _prune_grants(self) -> None:
        now = datetime.now(timezone.utc)
        with self._grant_lock:
            self._grants = {
                user_id: grant for user_id, grant in self._grants.items()
                if grant.expires_at > now
            }

    async def close(self) -> None:
        self._closing = True
        worker_id = self._worker_id
        if worker_id is not None:
            # Mark retirement synchronously. The SQLite claim worker checks this
            # after its transaction too, so cancelling the asyncio.to_thread
            # waiter cannot strand a late lease.
            self._claim_cancellation.set()
            self._store.mark_claim_worker_retired(worker_id)
        scheduler = self._scheduler_task
        self._scheduler_task = None
        if scheduler is not None:
            scheduler.cancel()
            await asyncio.wait({scheduler}, timeout=self._shutdown_timeout)
        active = list(self._tasks.values())
        for task in active:
            task.cancel()
        if active:
            await asyncio.wait(active, timeout=self._shutdown_timeout)
        if worker_id is not None:
            cleanup = asyncio.create_task(asyncio.to_thread(self._store.cleanup_retired_claim_workers))
            self._claim_cleanup_tasks.add(cleanup)
            cleanup.add_done_callback(self._observe_claim_cleanup)
            await asyncio.wait({cleanup}, timeout=self._shutdown_timeout)
        # A mock provider is cooperative, so cancelled calls finish promptly. If a
        # provider ignores cancellation, its completion callback retains the gate.
        with self._grant_lock:
            self._grants.clear()
        self._started = False

    def _observe_claim_cleanup(self, task: asyncio.Task[None]) -> None:
        self._claim_cleanup_tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            # The retirement marker remains available for Store.close or the next
            # claim poll to finish this idempotent cleanup.
            _LOGGER.warning("Runtime claim cleanup failed; a later Store boundary will retry")

    async def _scheduler(self) -> None:
        while not self._closing:
            try:
                self._prune_grants()
                finished = [turn_id for turn_id, task in self._tasks.items() if task.done()]
                for turn_id in finished:
                    self._tasks.pop(turn_id, None)
                if len(self._tasks) >= self._task_concurrency:
                    await asyncio.sleep(0.025)
                    continue
                worker_id = self._worker_id
                if worker_id is None:
                    raise RuntimeError("Runtime scheduler has no active claim worker")
                claimed = await asyncio.to_thread(
                    self._store.claim_runnable,
                    worker_id,
                    lease_seconds=self._LEASE_SECONDS,
                    exclude_turn_ids=tuple(self._deferred_recovery),
                    cancellation_event=self._claim_cancellation,
                    enabled_candidate_profile_ids=self._enabled_candidate_profile_ids,
                )
                if claimed is None:
                    await asyncio.sleep(0.04)
                    continue
                turn_id = claimed.turn.record.turn.turn_id
                if turn_id in self._tasks:
                    await asyncio.to_thread(self._store.release_claim, turn_id, claimed.claim_token)
                    await asyncio.sleep(0.02)
                    continue
                if claimed.turn.record.turn.state == c.TurnState.RECOVERING:
                    await self._inspect_recovery_checkpoint(claimed)
                    await asyncio.to_thread(self._store.release_claim, turn_id, claimed.claim_token)
                    continue
                if claimed.turn.record.turn.execution is not None:
                    self._deferred_recovery.add(turn_id)
                    await asyncio.to_thread(self._store.release_claim, turn_id, claimed.claim_token)
                    continue
                queued_at_claim = claimed.turn.record.turn.state == c.TurnState.QUEUED
                if queued_at_claim:
                    try:
                        claimed = await self._start_claimed_turn(claimed)
                    except (StateConflict, StoreNotFound):
                        await asyncio.to_thread(self._store.release_claim, turn_id, claimed.claim_token)
                        continue
                auth_resume_state = c.ResumeState.QUEUED if queued_at_claim else c.ResumeState.RUNNING
                task = asyncio.create_task(
                    self._run_claim(claimed, auth_resume_state=auth_resume_state),
                    name=f"p1-mock-turn-{turn_id}",
                )
                self._tasks[turn_id] = task
            except asyncio.CancelledError:
                raise
            except Exception:
                # Polling resumes on the next tick. Durable rows remain authoritative.
                await asyncio.sleep(0.1)

    async def _start_claimed_turn(self, claimed: ClaimedTurn) -> ClaimedTurn:
        aggregate = claimed.turn
        before = aggregate.record.turn
        resume_step = aggregate.checkpoint.resume_step or c.TurnStep.BUILD_CONTEXT
        after = c.TurnStateSnapshot.model_validate(
            before.model_dump(mode="python", by_alias=True, exclude_none=False)
            | {"state": c.TurnState.RUNNING, "step": resume_step,
               "state_revision": before.state_revision + 1, "wait_reason": None, "resume_state": None}
        )
        checkpoint = aggregate.checkpoint.model_copy(update={"resume_step": resume_step})
        result = await asyncio.to_thread(
            self._store.transition_turn,
            before.owner_user_id,
            after,
            expected_state_revision=before.state_revision,
            expected_checkpoint_revision=aggregate.checkpoint_revision,
            events=[self._status_event(after)],
            checkpoint=checkpoint,
            claim_token=claimed.claim_token,
        )
        return ClaimedTurn(turn=result, claim_token=claimed.claim_token, claim_until=claimed.claim_until)

    def wake_recovery(self, turn_id: uuid.UUID) -> None:
        """Retry one explicitly auth-resumed UNKNOWN execution checkpoint once."""
        self._deferred_recovery.discard(turn_id)

    async def _inspect_recovery_checkpoint(self, claimed: ClaimedTurn) -> None:
        aggregate = claimed.turn
        turn = aggregate.record.turn
        if turn.execution is None:
            return
        turn_id = turn.turn_id
        owner_id = turn.owner_user_id
        activity_ids = {
            item.entity_id for item in aggregate.record.bound_references
            if item.kind == "activity"
        }
        if not activity_ids and aggregate.checkpoint.model_context is not None:
            activity_ids = self._activity_ids(aggregate.checkpoint.model_context)
        try:
            await self._fresh_identity(owner_id, activity_ids)
        except _AuthRequired:
            current = await asyncio.to_thread(self._store.get_turn, owner_id, turn_id)
            self._ensure_claim_current_recovering(current, aggregate, claimed.claim_token)
            after = self._next_state(
                current.record.turn, c.TurnState.WAIT_INPUT, c.TurnStep.AUTH_REQUIRED,
                wait_reason=c.WaitReason.AUTH_REQUIRED, resume_state=c.ResumeState.RECOVERING,
            )
            await self._transition(
                current, after, [self._status_event(after)], claimed.claim_token,
                checkpoint=current.checkpoint,
            )
            return
        except _GateClosed:
            # A closed kill switch must not settle an execution either.
            self._deferred_recovery.add(turn_id)
            return
        # The effect may already have landed. Settle by looking the original
        # execution key up in the ledger first; only a missing row is applied, and
        # it is applied under that same key. An unknown outcome is never turned
        # into a terminal guess, so any failure here parks the Turn as recoverable.
        try:
            await asyncio.to_thread(
                self._store.reconcile_mock_execution, owner_id, turn_id,
                claim_token=claimed.claim_token,
                activity_guard=(
                    self._activity_roster.writable_guard(owner_id)
                    if self._activity_roster is not None else None
                ),
            )
        except Exception:
            self._deferred_recovery.add(turn_id)
            return

    async def _run_claim(
        self, claimed: ClaimedTurn, *, auth_resume_state: c.ResumeState = c.ResumeState.RUNNING,
    ) -> None:
        turn_id = claimed.turn.record.turn.turn_id
        renewer = asyncio.create_task(self._renew_loop(turn_id, claimed.claim_token))
        try:
            await self._run_planning(claimed)
        except asyncio.CancelledError:
            raise
        except _AuthRequired:
            await self._pause_for_auth(claimed, resume_state=auth_resume_state)
        except _GateClosed:
            await self._fail(claimed, c.ApiErrorCode.AGENT_DISABLED, retryable=False)
        except _CallBudgetReached:
            await self._fail(claimed, c.ApiErrorCode.RATE_LIMITED, retryable=False)
        except (_ModelTimeout, TimeoutError, ModelOutputError, CapabilityUnavailable):
            await self._fail(claimed, c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, retryable=True)
        except (StateConflict, StoreNotFound):
            # Cancel, owner state transition, or lease takeover won the race.
            pass
        except Exception:
            await self._fail(claimed, c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, retryable=True)
        finally:
            renewer.cancel()
            await asyncio.wait({renewer}, timeout=0.2)
            try:
                await asyncio.to_thread(self._store.release_claim, turn_id, claimed.claim_token)
            except Exception:
                pass

    async def _renew_loop(self, turn_id: uuid.UUID, token: str) -> None:
        while not self._closing:
            await asyncio.sleep(self._LEASE_SECONDS / 3)
            try:
                renewed = await asyncio.to_thread(
                    self._store.renew_claim, turn_id, token, lease_seconds=self._LEASE_SECONDS
                )
            except Exception:
                renewed = False
            if not renewed:
                return

    async def _run_planning(self, claimed: ClaimedTurn) -> None:
        owner_id = claimed.turn.record.turn.owner_user_id
        turn_id = claimed.turn.record.turn.turn_id
        aggregate = await asyncio.to_thread(self._store.get_turn, owner_id, turn_id)
        if aggregate.record.turn.execution is not None or aggregate.record.turn.state != c.TurnState.RUNNING:
            return
        gate = await self._current_gate()
        gate_revision = gate.disable_revision

        while not self._closing:
            stage = aggregate.checkpoint.resume_step or aggregate.record.turn.step
            decision = aggregate.checkpoint.last_decision
            context = aggregate.checkpoint.model_context

            # A durable semantic decision is the work item. Resume it at its
            # persisted stage instead of calling the provider a second time.
            if stage == c.TurnStep.TOOL_READ and isinstance(decision, c.ReadDecision):
                if context is None:
                    raise CapabilityUnavailable("saved read decision has no model context")
                aggregate = await self._execute_read(
                    aggregate, decision, context, claimed.claim_token, gate_revision
                )
                continue
            if stage == c.TurnStep.PREPARE_PROPOSAL and isinstance(decision, c.ProposeDecision):
                if context is None:
                    raise CapabilityUnavailable("saved proposal decision has no model context")
                await self._wait_for_confirmation(
                    aggregate, decision, context, claimed.claim_token, gate_revision
                )
                return
            if stage == c.TurnStep.FINALIZE and isinstance(decision, c.AnswerDecision):
                if context is None:
                    raise CapabilityUnavailable("saved answer decision has no model context")
                await self._complete_answer(aggregate, decision, context, claimed.claim_token, gate_revision)
                return
            if stage == c.TurnStep.AWAITING_USER and isinstance(decision, c.ClarifyDecision):
                if context is None:
                    raise CapabilityUnavailable("saved clarification decision has no model context")
                await self._wait_for_input(aggregate, decision, context, claimed.claim_token, gate_revision)
                return

            context, references, policy = self._build_context(aggregate, gate_revision)
            await self._fresh_identity(owner_id, self._activity_ids(context), gate_revision=gate_revision)
            aggregate = await self._prepare_model_call(
                aggregate, context, references, policy, claimed.claim_token,
            )
            raw, charged = await self._generate_model(
                aggregate, context, claimed.claim_token, gate_revision=gate_revision,
            )
            await self._ensure_current_generation(
                charged, claimed.claim_token, context, gate_revision,
            )
            try:
                decision = parse_model_output(raw, context)
            except ModelOutputError:
                raw, charged = await self._generate_model(
                    charged, context, claimed.claim_token, gate_revision=gate_revision,
                    repair_feedback="Return one valid closed semantic decision using only listed references.",
                    repair=True,
                )
                await self._ensure_current_generation(
                    charged, claimed.claim_token, context, gate_revision,
                )
                decision = parse_model_output(raw, context)
            aggregate = await self._save_decision(charged, decision, context, claimed.claim_token)
            if isinstance(decision, c.ReadDecision):
                aggregate = await self._execute_read(
                    aggregate, decision, context, claimed.claim_token, gate_revision
                )
                continue
            if isinstance(decision, c.ClarifyDecision):
                await self._wait_for_input(aggregate, decision, context, claimed.claim_token, gate_revision)
                return
            if isinstance(decision, c.ProposeDecision):
                await self._wait_for_confirmation(
                    aggregate, decision, context, claimed.claim_token, gate_revision
                )
                return
            await self._complete_answer(aggregate, decision, context, claimed.claim_token, gate_revision)
            return

    async def prepare_proposal_adjustment(
        self,
        owner_id: uuid.UUID,
        turn_id: uuid.UUID,
        proposal_id: uuid.UUID,
        request: c.ResumeProposalAdjustRequest,
    ) -> Any:
        """Run and durably finish one simulated adjustment under the shared model gate."""
        lock = self._adjustment_locks.setdefault(turn_id, asyncio.Lock())
        async with lock:
            replay = await asyncio.to_thread(
                self._store.find_action_receipt, owner_id, turn_id, request,
            )
            if replay is not None:
                return replay
            aggregate = await asyncio.to_thread(self._store.get_turn, owner_id, turn_id)
            current_proposal = await asyncio.to_thread(self._store.get_proposal, owner_id, proposal_id)
            if current_proposal.mode != "simulation":
                raise CapabilityUnavailable("only a simulated proposal can use the mock adjustment path")
            control = await self._current_gate()
            policy_version = self._policy_version(control.disable_revision)
            if current_proposal.policy_version != policy_version:
                raise _GateClosed()
            activity_ids = {
                item.entity_id for item in aggregate.record.bound_references
                if item.kind == "activity"
            }
            try:
                await self._fresh_identity(owner_id, activity_ids, gate_revision=control.disable_revision)
            except _AuthRequired:
                raise RuntimeAuthRequired() from None
            aggregate = await asyncio.to_thread(
                self._store.reserve_proposal_adjustment,
                owner_id, turn_id, proposal_id, request,
                policy_version=policy_version,
            )
            reservation = aggregate.checkpoint.adjustment_reservation
            if reservation is None or reservation.lease_token is None:
                raise StateConflict("proposal adjustment has no active Runtime lease")
            lease_token = reservation.lease_token
            clear_reservation = False
            lease_renewer = asyncio.create_task(
                self._renew_adjustment_lease_loop(owner_id, turn_id, lease_token),
                name=f"p1-adjustment-lease-{turn_id}",
            )
            try:
                decision = aggregate.checkpoint.last_decision
                context = aggregate.checkpoint.model_context
                stage = aggregate.checkpoint.resume_step
                if isinstance(decision, c.ProposeDecision) and stage == c.TurnStep.PREPARE_PROPOSAL:
                    if context is None or context.input_text != request.text:
                        raise StateConflict("saved adjustment decision has a different request context")
                else:
                    if context is None or context.input_text != request.text:
                        context, references, policies = self._build_context(aggregate, control.disable_revision)
                        summary = self._adjustment_summary(current_proposal.intent)
                        recent = [item for item in context.recent_messages
                                  if not item.text.startswith("Existing simulated proposal: ")]
                        recent.append(c.PriorMessage(role="assistant", text=summary))
                        context = context.model_copy(update={
                            "input_text": request.text,
                            "recent_messages": recent[-20:],
                        })
                    else:
                        references = list(aggregate.record.bound_references)
                        policies = list(aggregate.checkpoint.persisted_policy_evidence)
                    if stage == c.TurnStep.TOOL_READ and isinstance(decision, c.ReadDecision):
                        if context is None:
                            raise CapabilityUnavailable("saved adjustment read has no model context")
                        aggregate = await self._execute_adjustment_read(
                            aggregate, decision, context, owner_id, lease_token,
                            control.disable_revision,
                        )
                        context = aggregate.checkpoint.model_context
                        if context is None:
                            raise CapabilityUnavailable("adjustment read did not persist its model context")
                        aggregate = await self._prepare_model_call(
                            aggregate, context, list(aggregate.record.bound_references),
                            list(aggregate.checkpoint.persisted_policy_evidence), None,
                        )
                    else:
                        aggregate = await self._prepare_model_call(
                            aggregate, context, references, policies, None,
                        )

                    while True:
                        raw, charged = await self._generate_model(
                            aggregate, context, None,
                            gate_revision=control.disable_revision,
                        )
                        await self._ensure_current_generation(
                            charged, None, context, control.disable_revision,
                        )
                        try:
                            decision = parse_model_output(raw, context)
                        except ModelOutputError:
                            raw, charged = await self._generate_model(
                                charged, context, None,
                                gate_revision=control.disable_revision,
                                repair_feedback="Return one valid closed semantic decision using only listed references.",
                                repair=True,
                            )
                            await self._ensure_current_generation(
                                charged, None, context, control.disable_revision,
                            )
                            decision = parse_model_output(raw, context)
                        aggregate = await self._save_decision(
                            charged, decision, context, None,
                        )
                        if isinstance(decision, c.ReadDecision):
                            aggregate = await self._execute_adjustment_read(
                                aggregate, decision, context, owner_id, lease_token,
                                control.disable_revision,
                            )
                            context = aggregate.checkpoint.model_context
                            if context is None:
                                raise CapabilityUnavailable("adjustment read did not persist its model context")
                            aggregate = await self._prepare_model_call(
                                aggregate, context, list(aggregate.record.bound_references),
                                list(aggregate.checkpoint.persisted_policy_evidence), None,
                            )
                            continue
                        break

                if not isinstance(decision, c.ProposeDecision):
                    clear_reservation = isinstance(decision, c.ClarifyDecision)
                    raise CapabilityUnavailable("the adjustment did not produce a complete simulated proposal")
                if context is None:
                    raise CapabilityUnavailable("adjustment decision has no model context")
                await self._finalize_guard(
                    aggregate, None, context, control.disable_revision,
                )
                latest_control = await self._current_gate()
                if latest_control.disable_revision != control.disable_revision:
                    raise _GateClosed()
                current_proposal = await asyncio.to_thread(self._store.get_proposal, owner_id, proposal_id)
                if (
                    current_proposal.status != c.ProposalStatus.PENDING
                    or current_proposal.revision != request.expected_proposal_revision
                    or current_proposal.expires_at <= datetime.now(timezone.utc)
                ):
                    raise StateConflict("proposal changed while its adjustment was being prepared")
                replacement = self._make_proposal(
                    aggregate, decision, control.disable_revision,
                    proposal_id=proposal_id, revision=current_proposal.revision + 1,
                    expires_at=datetime.now(timezone.utc).replace(microsecond=0) + timedelta(minutes=10),
                )
                before = aggregate.record.turn
                running = self._next_state(
                    before, c.TurnState.RUNNING, c.TurnStep.MODEL_DECISION,
                    wait_reason=None, resume_state=None,
                )
                final = self._next_state(
                    running, c.TurnState.WAIT_CONFIRM, c.TurnStep.AWAITING_USER,
                    wait_reason=c.WaitReason.CONFIRM_REQUIRED, resume_state=None,
                )
                events = [
                    self._status_event(running).model_copy(update={"simulation": True}),
                    self._status_event(final).model_copy(update={"simulation": True}),
                    EventDraft(
                        type=c.EventType.PROPOSAL, occurred_at=datetime.now(timezone.utc),
                        simulation=True,
                        payload=c.ProposalEventPayload(
                            proposal_id=proposal_id, revision=replacement.revision,
                            operation=replacement.operation,
                        ),
                    ),
                ]
                return await asyncio.to_thread(
                    self._store.adjust_proposal, owner_id, turn_id, proposal_id, request,
                    replacement, events=events,
                )
            except _AuthRequired:
                await self._pause_adjustment_for_auth(owner_id, turn_id, lease_token)
                raise RuntimeAuthRequired() from None
            finally:
                lease_renewer.cancel()
                await asyncio.wait({lease_renewer}, timeout=0.2)
                try:
                    await asyncio.to_thread(
                        self._store.release_proposal_adjustment_lease,
                        owner_id, turn_id, lease_token,
                        clear_reservation=clear_reservation,
                    )
                except Exception:
                    pass

    async def _pause_adjustment_for_auth(
        self, owner_id: uuid.UUID, turn_id: uuid.UUID, lease_token: str,
    ) -> None:
        aggregate = await asyncio.to_thread(self._store.get_turn, owner_id, turn_id)
        before = aggregate.record.turn
        reservation = aggregate.checkpoint.adjustment_reservation
        if (
            before.state != c.TurnState.WAIT_CONFIRM or reservation is None
            or reservation.lease_token != lease_token
        ):
            return
        after = self._next_state(
            before, c.TurnState.WAIT_INPUT, c.TurnStep.AUTH_REQUIRED,
            wait_reason=c.WaitReason.AUTH_REQUIRED, resume_state=c.ResumeState.WAIT_CONFIRM,
        )
        checkpoint = aggregate.checkpoint.model_copy(update={
            "resume_step": aggregate.checkpoint.resume_step or c.TurnStep.MODEL_DECISION,
        })
        await self._transition(
            aggregate, after, [self._status_event(after)], None, checkpoint=checkpoint,
        )

    async def _renew_adjustment_lease_loop(
        self, owner_id: uuid.UUID, turn_id: uuid.UUID, lease_token: str,
    ) -> None:
        while not self._closing:
            await asyncio.sleep(15)
            try:
                renewed = await asyncio.to_thread(
                    self._store.renew_proposal_adjustment_lease,
                    owner_id, turn_id, lease_token, lease_seconds=60,
                )
            except Exception:
                renewed = False
            if not renewed:
                return

    async def _execute_adjustment_read(
        self,
        aggregate: TurnAggregate,
        decision: c.ReadDecision,
        context: c.ModelContext,
        owner_id: uuid.UUID,
        lease_token: str,
        gate_revision: int,
    ) -> TurnAggregate:
        if aggregate.checkpoint.read_calls >= 4:
            raise _CallBudgetReached()
        await self._fresh_identity(owner_id, self._activity_ids(context), gate_revision=gate_revision)
        charged = await self._save_checkpoint(
            aggregate, aggregate.checkpoint.model_copy(update={
                "read_calls": aggregate.checkpoint.read_calls + 1,
                "resume_step": c.TurnStep.TOOL_READ,
            }), None,
        )
        raw = await self._backend.read(owner_id, aggregate.record.turn.turn_id, context, decision)
        await self._fresh_identity(owner_id, self._activity_ids(context), gate_revision=gate_revision)
        current = await asyncio.to_thread(self._store.get_turn, owner_id, aggregate.record.turn.turn_id)
        self._ensure_claim_current(current, charged, None)
        reservation = current.checkpoint.adjustment_reservation
        if reservation is None or reservation.lease_token != lease_token:
            raise StateConflict("adjustment lease changed while its read was running")
        if current.checkpoint_revision != charged.checkpoint_revision or current.checkpoint.generation != charged.checkpoint.generation:
            raise StateConflict("adjustment read no longer matches its charged checkpoint")
        if not raw.simulation:
            raise CapabilityUnavailable("mock backend returned a non-simulated result")
        stored, refs, evidence, read_bindings = self._bind_read_result(charged, raw)
        next_checkpoint = charged.checkpoint.model_copy(update={
            "read_results": [*charged.checkpoint.read_results, stored],
            "resume_step": c.TurnStep.MODEL_DECISION,
        })
        next_context = self._context_with_reads(charged, refs, evidence, read_bindings, next_checkpoint)
        next_context = next_context.model_copy(update={"input_text": context.input_text, "recent_messages": []})
        next_checkpoint = next_checkpoint.model_copy(update={"model_context": next_context})
        return await self._save_checkpoint(
            charged, next_checkpoint, None,
            bound_references=refs, bound_evidence_references=evidence,
            bound_read_results=read_bindings,
        )

    def _build_context(
        self, aggregate: TurnAggregate, gate_revision: int,
    ) -> tuple[c.ModelContext, list[c.BoundReference], list[c.PolicyEvidence]]:
        turn = aggregate.record.turn
        checkpoint = aggregate.checkpoint
        # Auth resume is a control action, not a new user message. Select the
        # latest planning input so an auth retry keeps the clarification or
        # adjustment text that was already accepted durably.
        planning_inputs = [
            item for item in checkpoint.accepted_inputs
            if isinstance(item.payload, (
                c.SubmitTurnRequest, c.ResumeClarificationRequest, c.ResumeProposalAdjustRequest,
            ))
        ]
        latest = planning_inputs[-1].payload if planning_inputs else None
        input_text = (
            latest.text if latest is not None else aggregate.record.original_text
        )
        prior_texts = [
            item.payload.text for item in planning_inputs[:-1]
        ][-19:]
        recent = [c.PriorMessage(role="user", text=value) for value in prior_texts]
        conversation = " ".join([*prior_texts, input_text])
        business_terms = (
            "查", "查询", "看一下", "多少", "消费", "支出", "欠款", "债务", "活动",
            "记录", "新增", "添加", "创建", "记一笔", "修改", "更新", "改成",
            "备注", "标题", "图标", "描述",
        )
        has_business = bool(aggregate.record.bound_references or checkpoint.read_results) or any(
            word in conversation for word in business_terms
        )
        references = list(aggregate.record.bound_references)
        if has_business:
            references = c.bind_stable_references(
                references, self._fixture_candidates(), source_turn_id=turn.turn_id
            )
            activity = next(item for item in references if item.kind == "activity")
            permissions = list(mock_fixtures.PERMISSIONS)
            scope: c.ModelVerifiedScope = c.ModelActivityScope(
                kind="activity", activity_ref=activity.ref, permissions=permissions
            )
        else:
            permissions = []
            scope = c.ModelNoActivityScope(kind="none", permissions=[])

        policies = list(checkpoint.persisted_policy_evidence)
        if any(word in conversation for word in ("规则", "政策", "确认", "写入", "执行")) and not policies:
            policies.append(c.PolicyEvidence(
                evidence_ref=c.PolicyEvidenceRef.P01,
                rule=c.PolicyRule.EXECUTION_CONFIRMATION,
                source=c.PolicySource.DEVELOPMENT_GUIDE,
                version=self._policy_version(gate_revision),
                text="写入提议必须先由用户确认；此模拟服务不会执行真实业务写入。",
                observed_at=datetime.now(timezone.utc),
            ))
        context = c.ModelContext(
            context_version=turn.context_version,
            input_text=input_text,
            verified_scope=scope,
            recent_messages=recent,
            pending_slots=(checkpoint.last_clarification.missing_slots if checkpoint.last_clarification else []),
            bound_references=c.model_reference_tokens(references),
            read_results=mock_fixtures.model_results(list(checkpoint.read_results)),
            policy_evidence=policies,
            available_permissions=permissions,
        )
        return context, references, policies

    async def _prepare_model_call(
        self,
        aggregate: TurnAggregate,
        context: c.ModelContext,
        references: list[c.BoundReference],
        policies: list[c.PolicyEvidence],
        claim_token: str | None,
    ) -> TurnAggregate:
        checkpoint = aggregate.checkpoint
        next_checkpoint = checkpoint.model_copy(update={
            "model_context": context,
            "last_decision": None,
            "persisted_policy_evidence": policies,
            "resume_step": c.TurnStep.MODEL_DECISION,
        })
        return await self._save_checkpoint(
            aggregate, next_checkpoint, claim_token,
            bound_references=references,
        )

    async def _generate_model(
        self,
        aggregate: TurnAggregate,
        context: c.ModelContext,
        claim_token: str | None,
        *,
        gate_revision: int,
        repair_feedback: str | None = None,
        repair: bool = False,
    ) -> tuple[str, TurnAggregate]:
        await self._model_gate.acquire()
        provider_task: asyncio.Task[str] | None = None
        transferred = False

        def release_after_completion(task: asyncio.Task[str]) -> None:
            self._provider_tasks.discard(task)
            try:
                task.exception()
            except (asyncio.CancelledError, Exception):
                pass
            self._model_gate.release()

        try:
            owner_id = aggregate.record.turn.owner_user_id
            await self._fresh_identity(
                owner_id, self._activity_ids(context), gate_revision=gate_revision,
            )
            await self._ensure_current_generation(aggregate, claim_token, context, gate_revision)
            checkpoint = aggregate.checkpoint
            if checkpoint.model_calls >= 6 or repair and checkpoint.repair_calls >= 1:
                raise _CallBudgetReached()
            charged_checkpoint = checkpoint.model_copy(update={
                "model_calls": checkpoint.model_calls + 1,
                "repair_calls": checkpoint.repair_calls + (1 if repair else 0),
            })
            charged = await self._save_checkpoint(aggregate, charged_checkpoint, claim_token)
            provider_task = asyncio.create_task(
                self._provider.generate(ModelPrompt(context=context, repair_feedback=repair_feedback)),
                name="p1-mock-provider-call",
            )
            self._provider_tasks.add(provider_task)
            done, _ = await asyncio.wait({provider_task}, timeout=self._model_timeout)
            if not done:
                transferred = True
                provider_task.add_done_callback(release_after_completion)
                raise _ModelTimeout()
            result = provider_task.result()
            if not isinstance(result, str):
                raise ModelOutputError("provider response must be text")
            return result, charged
        except asyncio.CancelledError:
            if provider_task is not None and not transferred:
                transferred = True
                provider_task.cancel()
                provider_task.add_done_callback(release_after_completion)
            raise
        finally:
            if not transferred:
                if provider_task is not None:
                    self._provider_tasks.discard(provider_task)
                self._model_gate.release()

    async def _save_decision(
        self, aggregate: TurnAggregate, decision: c.SemanticDecision,
        context: c.ModelContext, claim_token: str,
    ) -> TurnAggregate:
        clarification = decision if isinstance(decision, c.ClarifyDecision) else None
        if isinstance(decision, c.ReadDecision):
            stage = c.TurnStep.TOOL_READ
        elif isinstance(decision, c.ProposeDecision):
            stage = c.TurnStep.PREPARE_PROPOSAL
        elif isinstance(decision, c.AnswerDecision):
            stage = c.TurnStep.FINALIZE
        else:
            stage = c.TurnStep.AWAITING_USER
        checkpoint = aggregate.checkpoint.model_copy(update={
            "model_context": context,
            "last_decision": decision,
            "last_clarification": clarification,
            "resume_step": stage,
        })
        return await self._save_checkpoint(aggregate, checkpoint, claim_token)

    async def _execute_read(
        self,
        aggregate: TurnAggregate,
        decision: c.ReadDecision,
        context: c.ModelContext,
        claim_token: str | None,
        gate_revision: int,
    ) -> TurnAggregate:
        if aggregate.checkpoint.read_calls >= 4:
            raise _CallBudgetReached()
        owner_id = aggregate.record.turn.owner_user_id
        activity_ids = self._activity_ids(context)
        await self._fresh_identity(owner_id, activity_ids, gate_revision=gate_revision)
        checkpoint = aggregate.checkpoint.model_copy(update={"read_calls": aggregate.checkpoint.read_calls + 1})
        charged = await self._save_checkpoint(aggregate, checkpoint, claim_token)
        raw = await self._backend.read(owner_id, aggregate.record.turn.turn_id, context, decision)
        await self._fresh_identity(owner_id, activity_ids, gate_revision=gate_revision)
        current = await asyncio.to_thread(self._store.get_turn, owner_id, aggregate.record.turn.turn_id)
        self._ensure_claim_current(current, charged, claim_token)
        if current.checkpoint_revision != charged.checkpoint_revision or current.checkpoint.generation != charged.checkpoint.generation:
            raise StateConflict("read result no longer matches its charged checkpoint")
        if not raw.simulation:
            raise CapabilityUnavailable("mock backend returned a non-simulated result")
        stored_result, references, evidence, read_bindings = self._bind_read_result(charged, raw)
        next_checkpoint = charged.checkpoint.model_copy(update={
            "read_results": [*charged.checkpoint.read_results, stored_result],
            "resume_step": c.TurnStep.MODEL_DECISION,
        })
        next_context = self._context_with_reads(charged, references, evidence, read_bindings, next_checkpoint)
        next_checkpoint = next_checkpoint.model_copy(update={"model_context": next_context})
        return await self._save_checkpoint(
            charged, next_checkpoint, claim_token,
            bound_references=references,
            bound_evidence_references=evidence,
            bound_read_results=read_bindings,
        )

    def _bind_read_result(
        self, aggregate: TurnAggregate, raw: c.ToolReadResult,
    ) -> tuple[c.ToolReadResult, list[c.BoundReference], list[c.BoundEvidenceReference], list[c.BoundReadResultReference]]:
        turn_id = aggregate.record.turn.turn_id
        references = c.bind_stable_references(
            list(aggregate.record.bound_references), self._fixture_candidates(), source_turn_id=turn_id
        )
        old_read_bindings = list(aggregate.record.bound_read_results)
        used_result_refs = {item.result_ref for item in old_read_bindings}
        result_ref = next((item for item in c.ReadResultRef if item not in used_result_refs), None)
        if result_ref is None:
            raise CapabilityUnavailable("mock read result reference capacity is exhausted")
        raw = raw.model_copy(update={"result_ref": result_ref})
        result_bindings = c.bind_stable_read_results(old_read_bindings, [c.ResolvedReadResultCandidate(
            result_ref=raw.result_ref, result_id=raw.result_id, operation=raw.operation,
            observed_at=raw.observed_at, context_version=raw.context_version,
        )], source_turn_id=turn_id)
        result_binding = next(item for item in result_bindings if item.result_id == raw.result_id)
        refs_by_token = {item.ref: item for item in references}
        candidates: list[c.ResolvedEvidenceCandidate] = []
        for fact in raw.body.items:
            if isinstance(fact, c.ActivityFact):
                entity_ref = fact.activity_ref
                kind = "activity"
            elif isinstance(fact, c.ExpenseFact):
                entity_ref = fact.expense_ref
                kind = "expense"
            else:
                entity_ref = fact.debtor_ref
                kind = "debt"
            binding = refs_by_token.get(entity_ref)
            if binding is None:
                raise CapabilityUnavailable("mock read fact has an unbound entity")
            candidates.append(c.ResolvedEvidenceCandidate(
                kind=kind, entity_id=binding.entity_id, scope_activity_id=binding.scope_activity_id,
                source_result_id=raw.result_id, context_version=raw.context_version,
            ))
        evidence = c.bind_stable_evidence(
            list(aggregate.record.bound_evidence_references), candidates, source_turn_id=turn_id
        )
        evidence_by_identity = {
            (item.kind, item.source_result_id, item.entity_id, item.context_version): item
            for item in evidence
        }
        facts: list[Any] = []
        for fact in raw.body.items:
            if isinstance(fact, c.ActivityFact):
                kind, token = "activity", fact.activity_ref
            elif isinstance(fact, c.ExpenseFact):
                kind, token = "expense", fact.expense_ref
            else:
                kind, token = "debt", refs_by_token[fact.debtor_ref]
                token = fact.debtor_ref
            binding = refs_by_token[token]
            evidence_binding = evidence_by_identity[(kind, raw.result_id, binding.entity_id, raw.context_version)]
            facts.append(fact.model_copy(update={
                "evidence_ref": evidence_binding.evidence_ref,
                "observed_at": raw.observed_at,
                "context_version": raw.context_version,
            }))
        body = raw.body.model_copy(update={"items": facts})
        result = raw.model_copy(update={"result_ref": result_binding.result_ref, "body": body})
        return result, references, evidence, result_bindings

    @staticmethod
    def _fixture_candidates() -> list[c.ResolvedEntityCandidate]:
        activity = mock_fixtures.ACTIVITY_ID
        return [
            c.ResolvedEntityCandidate(kind=c.UiEntityType.ACTIVITY,
                entity_id=activity, scope_activity_id=activity),
            c.ResolvedEntityCandidate(kind=c.UiEntityType.LEDGER_UNIT,
                entity_id=mock_fixtures.UNIT_ID, scope_activity_id=activity),
            c.ResolvedEntityCandidate(kind=c.UiEntityType.EXPENSE,
                entity_id=mock_fixtures.EXPENSE_ID, scope_activity_id=activity),
            c.ResolvedEntityCandidate(kind=c.UiEntityType.PARTICIPANT,
                entity_id=mock_fixtures.PARTICIPANT_1, scope_activity_id=activity),
            c.ResolvedEntityCandidate(kind=c.UiEntityType.PARTICIPANT,
                entity_id=mock_fixtures.PARTICIPANT_2, scope_activity_id=activity),
        ]

    def _context_with_reads(
        self,
        aggregate: TurnAggregate,
        references: list[c.BoundReference],
        evidence: list[c.BoundEvidenceReference],
        read_bindings: list[c.BoundReadResultReference],
        checkpoint: TurnCheckpoint,
    ) -> c.ModelContext:
        turn = aggregate.record.turn
        binding = next(item for item in references if item.kind == "activity")
        permissions = list(mock_fixtures.PERMISSIONS)
        return c.ModelContext(
            context_version=turn.context_version,
            input_text=aggregate.checkpoint.model_context.input_text if aggregate.checkpoint.model_context else aggregate.record.original_text,
            verified_scope=c.ModelActivityScope(kind="activity", activity_ref=binding.ref, permissions=permissions),
            recent_messages=(aggregate.checkpoint.model_context.recent_messages if aggregate.checkpoint.model_context else []),
            pending_slots=(aggregate.checkpoint.model_context.pending_slots if aggregate.checkpoint.model_context else []),
            bound_references=c.model_reference_tokens(references),
            read_results=mock_fixtures.model_results(checkpoint.read_results),
            policy_evidence=checkpoint.persisted_policy_evidence,
            available_permissions=permissions,
        )

    async def _wait_for_input(
        self, aggregate: TurnAggregate, decision: c.ClarifyDecision,
        context: c.ModelContext, claim_token: str, gate_revision: int,
    ) -> None:
        await self._finalize_guard(aggregate, claim_token, context, gate_revision)
        before = aggregate.record.turn
        resume_state = c.ResumeState.RUNNING
        after = self._next_state(
            before, c.TurnState.WAIT_INPUT, c.TurnStep.AWAITING_USER,
            wait_reason=c.WaitReason.MISSING_FIELDS, resume_state=resume_state,
        )
        checkpoint = aggregate.checkpoint.model_copy(update={"resume_step": c.TurnStep.MODEL_DECISION})
        source = "clarification" if context.verified_scope.kind == "none" and not context.read_results else None
        event_sources = [source, None]
        events = [
            EventDraft(type=c.EventType.CLARIFICATION, occurred_at=datetime.now(timezone.utc), simulation=True,
                payload=c.ClarificationEventPayload(
                    prompt=decision.prompt, missing_slots=decision.missing_slots,
                    resume_state=resume_state,
                )),
            self._status_event(after),
        ]
        await self._transition(aggregate, after, events, claim_token, checkpoint=checkpoint, event_sources=event_sources)

    async def _complete_answer(
        self, aggregate: TurnAggregate, decision: c.AnswerDecision,
        context: c.ModelContext, claim_token: str, gate_revision: int,
    ) -> None:
        await self._finalize_guard(aggregate, claim_token, context, gate_revision)
        before = aggregate.record.turn
        after = self._next_state(before, c.TurnState.COMPLETED, c.TurnStep.TERMINAL)
        source = None
        if context.verified_scope.kind == "none" and not context.bound_references and not context.read_results:
            if decision.basis == "conversation" and not decision.citations:
                source = "conversation_answer"
            elif decision.basis == "grounded" and decision.citations and all(
                isinstance(item, c.PolicyEvidenceRef) for item in decision.citations
            ):
                source = "policy_answer"
        events = [
            EventDraft(type=c.EventType.MESSAGE, occurred_at=datetime.now(timezone.utc), simulation=True,
                payload=c.MessageEventPayload(text=decision.text, citations=decision.citations)),
            self._status_event(after),
        ]
        checkpoint = aggregate.checkpoint.model_copy(update={"resume_step": None})
        await self._transition(
            aggregate, after, events, claim_token,
            checkpoint=checkpoint, event_sources=[source, None],
        )

    async def _wait_for_confirmation(
        self, aggregate: TurnAggregate, decision: c.ProposeDecision,
        context: c.ModelContext, claim_token: str, gate_revision: int,
    ) -> None:
        owner_id = aggregate.record.turn.owner_user_id
        activity_ids = self._activity_ids(context)
        await self._finalize_guard(aggregate, claim_token, context, gate_revision)
        session_id = aggregate.record.turn.session_id
        details = await asyncio.to_thread(self._store.get_session_detail, owner_id, session_id)
        if any(
            item.status == c.ProposalStatus.PENDING and item.expires_at > datetime.now(timezone.utc)
            for item in details.proposals
        ):
            # Ordinary planning cannot replace or stack a pending proposal in a Session.
            answer = c.AnswerDecision(
                kind="answer", basis="conversation",
                text="当前会话已有一个待处理的模拟提议。请先取消或处理它。", citations=[],
            )
            await self._complete_answer(aggregate, answer, context, claim_token, gate_revision)
            return
        proposal = self._make_proposal(aggregate, decision, gate_revision)
        before = aggregate.record.turn
        after = self._next_state(
            before, c.TurnState.WAIT_CONFIRM, c.TurnStep.AWAITING_USER,
            wait_reason=c.WaitReason.CONFIRM_REQUIRED, resume_state=None,
        )
        events = [
            EventDraft(type=c.EventType.PROPOSAL, occurred_at=datetime.now(timezone.utc), simulation=True,
                payload=c.ProposalEventPayload(
                    proposal_id=proposal.proposal_id, revision=proposal.revision, operation=proposal.operation,
                )),
            self._status_event(after),
        ]
        checkpoint = aggregate.checkpoint.model_copy(update={"resume_step": None})
        await self._transition(
            aggregate, after, events, claim_token, checkpoint=checkpoint,
            new_proposal=proposal,
        )

    def _make_proposal(
        self, aggregate: TurnAggregate, decision: c.ProposeDecision, gate_revision: int,
        *, proposal_id: uuid.UUID | None = None, revision: int = 1,
        expires_at: datetime | None = None,
    ) -> c.ProposalRecord:
        return self._proposal_builder(
            aggregate.record.turn.owner_user_id, aggregate.record.turn.session_id,
            aggregate.record.turn.turn_id, decision.fields,
            self._policy_version(gate_revision), proposal_id=proposal_id,
            revision=revision, expires_at=expires_at,
        )

    def _proposal_builder(self, *args: Any, **kwargs: Any) -> c.ProposalRecord:
        from .backend import build_simulation_proposal
        return build_simulation_proposal(*args, **kwargs)

    async def _pause_for_auth(
        self, claimed: ClaimedTurn, *, resume_state: c.ResumeState,
    ) -> None:
        owner_id = claimed.turn.record.turn.owner_user_id
        turn_id = claimed.turn.record.turn.turn_id
        try:
            aggregate = await asyncio.to_thread(self._store.get_turn, owner_id, turn_id)
            before = aggregate.record.turn
            if before.execution is not None or before.state != c.TurnState.RUNNING:
                return
            after = self._next_state(
                before, c.TurnState.WAIT_INPUT, c.TurnStep.AUTH_REQUIRED,
                wait_reason=c.WaitReason.AUTH_REQUIRED,
                resume_state=resume_state,
            )
            checkpoint = aggregate.checkpoint.model_copy(update={
                "resume_step": aggregate.checkpoint.resume_step or before.step,
            })
            await self._transition(
                aggregate, after, [self._status_event(after)], claimed.claim_token,
                checkpoint=checkpoint,
            )
        except (StateConflict, StoreNotFound, StoreError):
            return

    async def _fail(
        self, claimed: ClaimedTurn, code: c.ApiErrorCode, *, retryable: bool,
    ) -> None:
        owner_id = claimed.turn.record.turn.owner_user_id
        turn_id = claimed.turn.record.turn.turn_id
        try:
            aggregate = await asyncio.to_thread(self._store.get_turn, owner_id, turn_id)
            before = aggregate.record.turn
            if before.state != c.TurnState.RUNNING or before.execution is not None:
                return
            after = self._next_state(
                before, c.TurnState.FAILED, c.TurnStep.TERMINAL,
                wait_reason=None, resume_state=None,
            )
            events = [
                EventDraft(type=c.EventType.ERROR, occurred_at=datetime.now(timezone.utc), simulation=True,
                    payload=c.ErrorEventPayload(code=code, message=self._SAFE_ERROR, retryable=retryable)),
                self._status_event(after),
            ]
            await self._transition(
                aggregate, after, events, claimed.claim_token,
                checkpoint=aggregate.checkpoint.model_copy(update={"resume_step": None}),
                event_sources=["system_error", None],
            )
        except (StateConflict, StoreNotFound, StoreError):
            return

    async def _fresh_identity(
        self,
        owner_id: uuid.UUID,
        activity_ids: set[uuid.UUID] | None = None,
        *,
        gate_revision: int | None = None,
    ) -> Principal:
        now = datetime.now(timezone.utc)
        with self._grant_lock:
            grant = self._grants.get(owner_id)
        if grant is None or grant.expires_at <= now:
            if grant is not None:
                with self._grant_lock:
                    if self._grants.get(owner_id) == grant:
                        self._grants.pop(owner_id, None)
            raise _AuthRequired()
        try:
            verified = await asyncio.to_thread(self._auth.verify_bearer, grant.token)
        except Exception:
            raise _AuthRequired() from None
        if (
            verified.user_id != owner_id or verified.expires_at is None
            or verified.expires_at.tzinfo is None or verified.expires_at.utcoffset() is None
            or verified.expires_at <= datetime.now(timezone.utc)
        ):
            raise _AuthRequired()
        refreshed = _MemoryAuthGrant(grant.token, verified.expires_at.astimezone(timezone.utc))
        with self._grant_lock:
            current = self._grants.get(owner_id)
            if current != grant:
                # A concurrent HTTP authentication bound a fresher token while
                # this verification was in flight. Never overwrite that grant.
                raise _AuthRequired()
            self._grants[owner_id] = refreshed
        control = await self._current_gate()
        if not control.enabled or gate_revision is not None and control.disable_revision != gate_revision:
            raise _GateClosed()
        if activity_ids:
            try:
                await asyncio.to_thread(
                    self._scope.authorize, verified, frozenset(activity_ids), action="mock_runtime"
                )
            except Exception:
                raise _AuthRequired() from None
        return verified

    async def _current_gate(self) -> Any:
        try:
            snapshot = await asyncio.to_thread(self._control.snapshot)
        except Exception:
            raise _GateClosed() from None
        if snapshot.disable_revision < 0:
            raise _GateClosed()
        if not snapshot.enabled:
            raise _GateClosed()
        return snapshot

    @staticmethod
    def _activity_ids(context: c.ModelContext) -> set[uuid.UUID]:
        if not isinstance(context.verified_scope, c.ModelActivityScope):
            return set()
        # The contract projection deliberately carries no UUID. The binding is
        # recovered only from the server-persisted typed reference map by callers.
        return {mock_fixtures.ACTIVITY_ID}

    async def _save_checkpoint(
        self,
        aggregate: TurnAggregate,
        checkpoint: TurnCheckpoint,
        claim_token: str | None,
        *,
        bound_references: list[c.BoundReference] | None = None,
        bound_evidence_references: list[c.BoundEvidenceReference] | None = None,
        bound_read_results: list[c.BoundReadResultReference] | None = None,
    ) -> TurnAggregate:
        if checkpoint.model_context is not None:
            expected_reads = mock_fixtures.model_results(list(checkpoint.read_results))
            if checkpoint.model_context.read_results != expected_reads:
                raise CapabilityUnavailable("model context read facts differ from the durable full result snapshots")
        return await asyncio.to_thread(
            self._store.save_checkpoint,
            aggregate.record.turn.owner_user_id,
            aggregate.record.turn.turn_id,
            expected_state_revision=aggregate.record.turn.state_revision,
            expected_checkpoint_revision=aggregate.checkpoint_revision,
            checkpoint=checkpoint,
            bound_references=bound_references,
            bound_evidence_references=bound_evidence_references,
            bound_read_results=bound_read_results,
            claim_token=claim_token,
        )

    async def _transition(
        self,
        aggregate: TurnAggregate,
        after: c.TurnStateSnapshot,
        events: Sequence[EventDraft],
        claim_token: str,
        *,
        checkpoint: TurnCheckpoint,
        bound_references: list[c.BoundReference] | None = None,
        bound_evidence_references: list[c.BoundEvidenceReference] | None = None,
        bound_read_results: list[c.BoundReadResultReference] | None = None,
        new_proposal: c.ProposalRecord | None = None,
        event_sources: Sequence[str | None] | None = None,
    ) -> TurnAggregate:
        before = aggregate.record.turn
        return await asyncio.to_thread(
            self._store.transition_turn,
            before.owner_user_id,
            after,
            expected_state_revision=before.state_revision,
            expected_checkpoint_revision=aggregate.checkpoint_revision,
            events=events,
            checkpoint=checkpoint,
            event_sources=event_sources,
            bound_references=bound_references,
            bound_evidence_references=bound_evidence_references,
            bound_read_results=bound_read_results,
            new_proposal=new_proposal,
            claim_token=claim_token,
        )

    @staticmethod
    def _ensure_claim_current(
        aggregate: TurnAggregate, expected: TurnAggregate, claim_token: str | None,
    ) -> None:
        if (
            aggregate.record.turn.state != expected.record.turn.state
            or aggregate.record.turn.state_revision != expected.record.turn.state_revision
            or aggregate.checkpoint_revision != expected.checkpoint_revision
            or aggregate.checkpoint.generation != expected.checkpoint.generation
            or aggregate.record.turn.execution is not None
            or aggregate.claim_token != claim_token
            or claim_token is not None and (
                aggregate.claim_until is None or aggregate.claim_until <= datetime.now(timezone.utc)
            )
            or claim_token is None and aggregate.claim_until is not None
        ):
            raise StateConflict("Runtime claim or Turn state is no longer current")

    @staticmethod
    def _ensure_claim_current_recovering(
        aggregate: TurnAggregate, expected: TurnAggregate, claim_token: str,
    ) -> None:
        if (
            aggregate.record.turn.state != c.TurnState.RECOVERING
            or aggregate.record.turn.state_revision != expected.record.turn.state_revision
            or aggregate.record.turn.execution != expected.record.turn.execution
            or aggregate.record.turn.execution_resolution != expected.record.turn.execution_resolution
            or aggregate.checkpoint_revision != expected.checkpoint_revision
            or aggregate.checkpoint.generation != expected.checkpoint.generation
            or aggregate.claim_token != claim_token
            or aggregate.claim_until is None or aggregate.claim_until <= datetime.now(timezone.utc)
        ):
            raise StateConflict("recovery claim or original execution identity is no longer current")

    async def _ensure_current_generation(
        self,
        expected: TurnAggregate,
        claim_token: str,
        context: c.ModelContext,
        gate_revision: int,
    ) -> TurnAggregate:
        owner_id = expected.record.turn.owner_user_id
        current = await asyncio.to_thread(self._store.get_turn, owner_id, expected.record.turn.turn_id)
        self._ensure_claim_current(current, expected, claim_token)
        if current.checkpoint.model_context != context:
            raise StateConflict("model output no longer matches its durable context")
        if current.checkpoint.last_decision is not None:
            raise StateConflict("model output was superseded by a durable semantic decision")
        reservation = current.checkpoint.adjustment_reservation
        expected_reservation = expected.checkpoint.adjustment_reservation
        if expected_reservation is not None and (
            reservation is None or reservation.lease_token != expected_reservation.lease_token
        ):
            raise StateConflict("proposal adjustment Runtime lease changed")
        if reservation is not None and (
            reservation.lease_token is None or reservation.lease_expires_at is None
            or reservation.lease_expires_at <= datetime.now(timezone.utc)
        ):
            raise StateConflict("proposal adjustment Runtime lease expired")
        await self._fresh_identity(owner_id, self._activity_ids(context), gate_revision=gate_revision)
        return current

    async def _finalize_guard(
        self,
        aggregate: TurnAggregate,
        claim_token: str,
        context: c.ModelContext,
        gate_revision: int,
    ) -> None:
        current = await asyncio.to_thread(
            self._store.get_turn, aggregate.record.turn.owner_user_id,
            aggregate.record.turn.turn_id,
        )
        self._ensure_claim_current(current, aggregate, claim_token)
        if current.checkpoint.model_context != context:
            raise StateConflict("final decision no longer matches its durable context")
        expected_reservation = aggregate.checkpoint.adjustment_reservation
        current_reservation = current.checkpoint.adjustment_reservation
        if expected_reservation is not None and (
            current_reservation is None
            or current_reservation.lease_token != expected_reservation.lease_token
            or current_reservation.lease_expires_at is None
            or current_reservation.lease_expires_at <= datetime.now(timezone.utc)
        ):
            raise StateConflict("proposal adjustment Runtime lease expired before commit")
        await self._fresh_identity(
            aggregate.record.turn.owner_user_id, self._activity_ids(context),
            gate_revision=gate_revision,
        )

    @staticmethod
    def _next_state(
        before: c.TurnStateSnapshot, state: c.TurnState, step: c.TurnStep, **updates: Any,
    ) -> c.TurnStateSnapshot:
        return c.TurnStateSnapshot.model_validate(
            before.model_dump(mode="python", by_alias=True, exclude_none=False)
            | {"state": state, "step": step, "state_revision": before.state_revision + 1}
            | updates
        )

    @staticmethod
    def _status_event(snapshot: c.TurnStateSnapshot) -> EventDraft:
        return EventDraft(
            type=c.EventType.STATUS,
            occurred_at=datetime.now(timezone.utc),
            simulation=True,
            payload=c.StatusEventPayload(
                state=snapshot.state,
                step=snapshot.step,
                state_revision=snapshot.state_revision,
                wait_reason=snapshot.wait_reason,
                resume_state=snapshot.resume_state,
            ),
        )

    @staticmethod
    def _policy_version(disable_revision: int) -> str:
        return f"mock-policy-v1;disable_revision={int(disable_revision)}"

    @staticmethod
    def _adjustment_summary(intent: c.WriteIntent) -> str:
        fields = [f"operation={intent.kind}"]
        for name in ("title", "original_amount", "original_currency", "note", "icon_key"):
            value = getattr(intent, name, None)
            if value is not None:
                fields.append(f"{name}={value}")
        return "Existing simulated proposal: " + "; ".join(fields)
