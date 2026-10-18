"""P2 real-provider/read-only runtime layered on the durable v1 Turn scheduler."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import time
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

from . import contracts as c
from .auth import AuthDependencyUnavailable, Unauthenticated
from .harness import ModelOutputError
from .p2_backend import (
    BackendReadError, BoundRef, P2ActivityDTO, P2BackendAdapter, P2BackendReadResult,
    P2DebtDTO, P2ExpenseDTO, P2ParticipantDTO, ScopeRequest, VerifiedReadContext,
)
from .p2_harness import (
    P2ExpenseSupplement, P2FinancialVersion, P2Harness, P2PaymentLine,
    P2ReferenceLabel, P2ResultProvenance,
)
from .p2_identity import P2GrantError, P2TurnGrant, P2TurnGrantStore
from .p2_journal import P2ErrorProofJournal, P2EventProofError
from .p2_model_provider import (
    LMStudioOpenAIProvider, LMStudioProviderCancelled, LMStudioProviderError,
    LMStudioProviderErrorCode,
)
from .ports import (
    AgentControl, AgentStore, AuthVerifier, CapabilityUnavailable, ComponentHealth,
    Principal, ScopeAuthorizer,
)
from .runtime import MockRuntime, _AuthRequired, _CallBudgetReached, _GateClosed, _ModelTimeout
from .store import (
    ClaimedTurn, EventDraft, StateConflict, StoreError, StoreNotFound, TurnAggregate,
    TurnCheckpoint,
)


_ACTIVE_TURN: ContextVar[uuid.UUID | None] = ContextVar("p2_active_turn", default=None)


@dataclass(slots=True)
class _TurnP2State:
    resolved_scope: Any = None
    scope_activity_id: uuid.UUID | None = None
    scope_fingerprint: str | None = None
    provenance: dict[c.ReadResultRef, P2ResultProvenance] = field(default_factory=dict)
    supplements: dict[c.ReadResultRef, list[P2ExpenseSupplement]] = field(default_factory=dict)
    labels: dict[c.ModelRefToken, P2ReferenceLabel] = field(default_factory=dict)
    result_decisions: dict[c.ReadResultRef, c.ReadDecision] = field(default_factory=dict)
    result_body_hashes: dict[c.ReadResultRef, str] = field(default_factory=dict)
    result_binding_snapshots: dict[c.ReadResultRef, tuple[c.BoundReference, ...]] = field(default_factory=dict)
    result_scope_ids: dict[c.ReadResultRef, uuid.UUID | None] = field(default_factory=dict)
    result_scope_fingerprints: dict[c.ReadResultRef, str] = field(default_factory=dict)


class _P2DependencyPause(Exception):
    def __init__(self, code: c.ApiErrorCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class _P2TerminalFailure(Exception):
    def __init__(self, code: c.ApiErrorCode, message: str, retryable: bool = False) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(message)


class _NoBusinessScopeAuthorizer:
    """Legacy Runtime slot; P2 scope checks go only through its trusted backend."""

    def authorize(self, *_: Any, **__: Any) -> None:
        raise CapabilityUnavailable("P2 never delegates activity scope to the legacy adapter")


class P2Runtime(MockRuntime):
    """Reuse the v1 bounded CAS scheduler; replace every mock business capability."""

    _SAFE_GENERIC_TEXT = "我可以帮助查询已验证的活动、消费和欠款信息。"
    _SAFE_EMPTY_TEXT = "当前查询已完成，没有找到符合条件的记录。"
    _SCOPE_CONFLICT_TEXT = "当前 Turn 已绑定到不同活动范围。请从所需活动页面创建新 Turn 后重试。"
    _CLARIFICATION_TEXT = {
        c.ClarificationSlot.ACTIVITY: "请说明要查询的活动。",
        c.ClarificationSlot.LEDGER_UNIT: "请说明涉及的账本。",
        c.ClarificationSlot.EXPENSE: "请说明涉及的消费记录。",
        c.ClarificationSlot.AMOUNT: "请提供金额。",
        c.ClarificationSlot.CURRENCY: "请提供币种。",
        c.ClarificationSlot.PAYMENT_ALLOCATIONS: "请说明付款人和付款金额。",
        c.ClarificationSlot.TITLE: "请提供消费名称。",
        c.ClarificationSlot.SPLIT: "请说明分摊方式。",
        c.ClarificationSlot.SPLIT_PARTICIPANTS: "请说明参与分摊的人。",
        c.ClarificationSlot.NOTE: "请提供备注内容。",
        c.ClarificationSlot.ICON_KEY: "请说明要使用的图标。",
        c.ClarificationSlot.UPDATE_FIELDS: "请说明要修改的字段。",
    }

    def __init__(
        self,
        store: AgentStore,
        provider: LMStudioOpenAIProvider,
        backend: P2BackendAdapter,
        auth_verifier: AuthVerifier,
        agent_control: AgentControl,
        journal: P2ErrorProofJournal,
        *,
        lease_seconds: int = 300,
        model_timeout_seconds: float = 30.0,
        shutdown_timeout_seconds: float = 3.0,
        max_model_calls: int = 6,
        max_read_calls: int = 4,
        max_repair_calls: int = 1,
        max_turn_grants: int = 1024,
    ) -> None:
        # The inherited scheduler only claims/renews Turns and supplies CAS helpers;
        # P2 overrides all model, identity, read, error, and finalization paths.
        super().__init__(
            store, provider, backend, auth_verifier, _NoBusinessScopeAuthorizer(), agent_control,
            task_concurrency=1, model_timeout_seconds=model_timeout_seconds,
            shutdown_timeout_seconds=shutdown_timeout_seconds,
        )
        self._p2_provider = provider
        self._p2_backend = backend
        self._journal = journal
        self._turn_grants = P2TurnGrantStore(max_entries=max_turn_grants, lease_seconds=lease_seconds)
        self._p2_states: dict[uuid.UUID, _TurnP2State] = {}
        if not isinstance(max_model_calls, int) or not 1 <= max_model_calls <= 6:
            raise ValueError("max_model_calls must be between 1 and 6")
        if not isinstance(max_read_calls, int) or not 1 <= max_read_calls <= 4:
            raise ValueError("max_read_calls must be between 1 and 4")
        if not isinstance(max_repair_calls, int) or not 0 <= max_repair_calls <= 1:
            raise ValueError("max_repair_calls must be between 0 and 1")
        self._max_model_calls = max_model_calls
        self._max_read_calls = max_read_calls
        self._max_repair_calls = max_repair_calls

    def _prune_grants(self) -> None:
        self._turn_grants.prune_expired()

    def bind_auth_grant(self, principal: Principal, access_token: str) -> None:
        """P2 deliberately ignores the legacy owner-wide grant hook."""
        return None

    def bind_turn_auth_grant(
        self, principal: Principal, turn_id: uuid.UUID, access_token: str, *,
        replace: bool = False, existing_only: bool = False,
    ) -> None:
        try:
            aggregate = self._store.get_turn(principal.user_id, turn_id)
        except Exception:
            raise P2GrantError("Turn grant is not bound to a durable Turn") from None
        if aggregate.record.turn.state in (
            c.TurnState.COMPLETED, c.TurnState.FAILED, c.TurnState.CANCELLED,
        ):
            # Terminal receipt retries cannot create a fresh bearer lease.
            return
        self._turn_grants.bind(
            principal, turn_id, access_token, replace=replace, existing_only=existing_only,
        )

    def revoke_turn_auth_grant(self, owner_user_id: uuid.UUID, turn_id: uuid.UUID) -> None:
        self._turn_grants.revoke(owner_user_id, turn_id)
        self._p2_states.pop(turn_id, None)

    def health(self) -> ComponentHealth:
        health = self._p2_provider.health()
        return ComponentHealth(status="ready" if health.status == "ready" else "not_ready",
                               available=health.inference_available)

    async def start(self) -> None:
        self._journal.start()
        try:
            await super().start()
        except BaseException:
            self._journal.close()
            raise

    async def close(self) -> None:
        await super().close()
        self._turn_grants.clear()
        self._p2_states.clear()
        self._journal.close()

    async def _run_claim(
        self, claimed: ClaimedTurn, *, auth_resume_state: c.ResumeState = c.ResumeState.RUNNING,
    ) -> None:
        turn_id = claimed.turn.record.turn.turn_id
        token = _ACTIVE_TURN.set(turn_id)
        renewer = asyncio.create_task(self._renew_loop(turn_id, claimed.claim_token))
        try:
            await self._await_turn_grant(claimed.turn.record.turn.owner_user_id, turn_id)
            await self._run_planning(claimed)
        except asyncio.CancelledError:
            raise
        except _AuthRequired:
            owner_id = claimed.turn.record.turn.owner_user_id
            self._turn_grants.revoke(owner_id, turn_id)
            self._p2_states.pop(turn_id, None)
            await self._pause_for_auth(
                claimed, resume_state=auth_resume_state, code=c.ApiErrorCode.UNAUTHENTICATED,
                message="P2 dependency unavailable: auth_rejected.",
            )
        except _P2DependencyPause as exc:
            owner_id = claimed.turn.record.turn.owner_user_id
            self._turn_grants.revoke(owner_id, turn_id)
            self._p2_states.pop(turn_id, None)
            await self._pause_for_auth(claimed, resume_state=auth_resume_state,
                                       code=exc.code, message=exc.message)
        except _P2TerminalFailure as exc:
            owner_id = claimed.turn.record.turn.owner_user_id
            self._turn_grants.revoke(owner_id, turn_id)
            self._p2_states.pop(turn_id, None)
            await self._terminal_error(claimed, exc.code, exc.message, retryable=exc.retryable)
        except _GateClosed:
            await self._terminal_error(claimed, c.ApiErrorCode.AGENT_DISABLED,
                                       "P2 agent planning is disabled.", retryable=False)
        except _CallBudgetReached:
            await self._terminal_error(claimed, c.ApiErrorCode.RATE_LIMITED,
                                       "P2 planning generation budget reached.", retryable=False)
        except (StateConflict, StoreNotFound):
            pass
        except (LMStudioProviderError, LMStudioProviderCancelled, _ModelTimeout, TimeoutError) as exc:
            code, message = _provider_failure(exc)
            owner_id = claimed.turn.record.turn.owner_user_id
            self._turn_grants.revoke(owner_id, turn_id)
            self._p2_states.pop(turn_id, None)
            await self._pause_for_auth(claimed, resume_state=auth_resume_state,
                                       code=code, message=message)
        except (ModelOutputError, CapabilityUnavailable) as exc:
            await self._terminal_error(claimed, c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                                       _safe_internal_error(exc), retryable=False)
        except Exception:
            await self._terminal_error(claimed, c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                                       "P2 dependency unavailable: internal_failure.", retryable=True)
        finally:
            renewer.cancel()
            await asyncio.wait({renewer}, timeout=0.2)
            try:
                await asyncio.to_thread(self._store.release_claim, turn_id, claimed.claim_token)
            except Exception:
                pass
            try:
                final = await asyncio.to_thread(
                    self._store.get_turn, claimed.turn.record.turn.owner_user_id, turn_id,
                )
                if final.record.turn.state in (c.TurnState.COMPLETED, c.TurnState.FAILED,
                                                c.TurnState.CANCELLED):
                    self._p2_states.pop(turn_id, None)
                    self._turn_grants.revoke(final.record.turn.owner_user_id, turn_id)
                elif final.record.turn.state == c.TurnState.WAIT_INPUT:
                    self._p2_states.pop(turn_id, None)
            except Exception:
                self._p2_states.pop(turn_id, None)
            _ACTIVE_TURN.reset(token)

    async def _await_turn_grant(self, owner_id: uuid.UUID, turn_id: uuid.UUID) -> None:
        """Close the API-admission race without retaining request-wide credentials."""
        deadline = time.monotonic() + min(1.0, max(0.1, self._model_timeout))
        while not self._closing:
            try:
                self._turn_grants.get(owner_id, turn_id)
                return
            except P2GrantError:
                if time.monotonic() >= deadline:
                    raise _AuthRequired() from None
                await asyncio.sleep(0.01)

    async def _run_planning(self, claimed: ClaimedTurn) -> None:
        turn_id = claimed.turn.record.turn.turn_id
        owner_id = claimed.turn.record.turn.owner_user_id
        aggregate = await asyncio.to_thread(self._store.get_turn, owner_id, turn_id)
        if aggregate.record.turn.execution is not None or aggregate.record.turn.state != c.TurnState.RUNNING:
            return
        gate = await self._current_gate()
        state = self._p2_states.setdefault(turn_id, _TurnP2State())
        references = list(aggregate.record.bound_references)
        await self._resolve_scope(aggregate, references, state, gate.disable_revision)

        while not self._closing:
            stage = aggregate.checkpoint.resume_step or aggregate.record.turn.step
            decision = aggregate.checkpoint.last_decision
            context = aggregate.checkpoint.model_context
            if stage == c.TurnStep.TOOL_READ and isinstance(decision, c.ReadDecision):
                if context is None:
                    raise CapabilityUnavailable("saved read decision has no context")
                aggregate = await self._execute_p2_read(aggregate, decision, context, claimed.claim_token,
                                                        gate.disable_revision, state)
                if aggregate.checkpoint.read_results and not aggregate.checkpoint.read_results[-1].body.items:
                    await self._complete_empty_result(
                        aggregate, aggregate.checkpoint.model_context or context,
                        claimed.claim_token, gate.disable_revision,
                    )
                    return
                continue
            if stage == c.TurnStep.FINALIZE and isinstance(decision, c.AnswerDecision):
                if context is None:
                    raise CapabilityUnavailable("saved answer decision has no context")
                try:
                    answer = self._render_answer(decision, context, state)
                except ModelOutputError:
                    # Process restart loses only P2 private freshness metadata. The
                    # v1 DTO remains append-only; require a fresh user input.
                    await self._wait_for_restart_clarification(
                        aggregate, context, claimed.claim_token, gate.disable_revision,
                    )
                    return
                await self._complete_answer(aggregate, answer, context, claimed.claim_token,
                                            gate.disable_revision, state=state)
                return
            if stage == c.TurnStep.AWAITING_USER and isinstance(decision, c.ClarifyDecision):
                if context is None:
                    raise CapabilityUnavailable("saved clarification decision has no context")
                await self._wait_for_input(aggregate, decision, context, claimed.claim_token,
                                           gate.disable_revision)
                return

            if stage == c.TurnStep.MODEL_DECISION and context is not None and context.read_results:
                # A completed read already persisted its full body and the
                # complete durable ref projection. Continue from that exact
                # checkpoint; rebuilding from the pre-read local ref list would
                # omit server-bound refs (and would violate the v1 binding
                # validator). The private provenance is deliberately ephemeral,
                # so after a process restart/auth pause it cannot make old data
                # current again: ask for a fresh user input instead.
                latest = context.read_results[-1]
                provenance = state.provenance.get(latest.result_ref)
                if (provenance is None or not provenance.current
                        or provenance.operation != latest.operation
                        or provenance.observed_at != latest.observed_at
                        or provenance.context_version != latest.context_version):
                    await self._wait_for_restart_clarification(
                        aggregate, context, claimed.claim_token, gate.disable_revision,
                    )
                    return
                references = list(aggregate.record.bound_references)
            else:
                context, references = await self._build_p2_context(
                    aggregate, references, state, gate.disable_revision,
                )

            aggregate = await self._prepare_p2_model_call(aggregate, context, references, claimed.claim_token)
            raw, charged = await self._generate_p2_model(
                aggregate, context, claimed.claim_token, gate_revision=gate.disable_revision,
                state=state,
            )
            await self._ensure_p2_generation(charged, claimed.claim_token, context, gate.disable_revision)
            try:
                parsed = P2Harness.parse(raw, context)
                decision = self._accepted_decision(parsed, context)
            except ModelOutputError:
                raw, charged = await self._generate_p2_model(
                    charged, context, claimed.claim_token, gate_revision=gate.disable_revision,
                    repair_feedback="Return one valid closed decision using only current listed references and citations.",
                    repair=True, state=state,
                )
                await self._ensure_p2_generation(charged, claimed.claim_token, context, gate.disable_revision)
                parsed = P2Harness.parse(raw, context)
                decision = self._accepted_decision(parsed, context)
            if isinstance(decision, c.ReadDecision):
                aggregate = await self._save_decision(charged, decision, context, claimed.claim_token)
                aggregate = await self._execute_p2_read(aggregate, decision, context, claimed.claim_token,
                                                        gate.disable_revision, state)
                if aggregate.checkpoint.read_results and not aggregate.checkpoint.read_results[-1].body.items:
                    await self._complete_empty_result(
                        aggregate, aggregate.checkpoint.model_context or context,
                        claimed.claim_token, gate.disable_revision,
                    )
                    return
                continue
            if isinstance(decision, c.ClarifyDecision):
                decision = self._safe_clarification(decision)
                aggregate = await self._save_decision(charged, decision, context, claimed.claim_token)
                await self._wait_for_input(aggregate, decision, context, claimed.claim_token,
                                           gate.disable_revision)
                return
            if isinstance(decision, c.ProposeDecision):
                # Proposal permission only identifies intent; no proposal or preview is persisted.
                answer = P2Harness.proposal_acknowledgement()
                aggregate = await self._save_decision(charged, answer, context, claimed.claim_token)
                await self._complete_answer(aggregate, answer, context, claimed.claim_token,
                                            gate.disable_revision, state=state, proposal_ack=True)
                return
            answer = self._render_answer(decision, context, state)
            aggregate = await self._save_decision(charged, answer, context, claimed.claim_token)
            await self._complete_answer(aggregate, answer, context, claimed.claim_token,
                                        gate.disable_revision, state=state)
            return

    async def _resolve_scope(
        self,
        aggregate: TurnAggregate,
        references: list[c.BoundReference],
        state: _TurnP2State,
        gate_revision: int,
    ) -> None:
        turn = aggregate.record.turn
        turn_id = turn.turn_id
        previous_scope = aggregate.checkpoint.model_context.verified_scope if aggregate.checkpoint.model_context else None
        hint = aggregate.record.ui_context_snapshot.activity_id if aggregate.record.ui_context_snapshot else None
        if hint is None and isinstance(previous_scope, c.ModelActivityScope):
            bound = next((item for item in references if item.ref == previous_scope.activity_ref), None)
            if bound is not None and bound.kind == "activity":
                hint = bound.entity_id
        owner_id = turn.owner_user_id
        principal = await self._fresh_identity(
            owner_id, {hint} if hint is not None else set(), gate_revision=gate_revision,
        )
        grant = self._active_grant(owner_id, turn_id)
        verified = self._make_verified_context(owner_id, turn_id, grant, references)
        request = ScopeRequest(mode="activity" if hint is not None else "none", ui_activity_id_hint=hint)
        try:
            resolved = await self._p2_backend.resolve_scope(verified, request)
        except BackendReadError as exc:
            raise self._backend_pause(exc) from None
        if resolved.mode == "activity":
            assert resolved.activity is not None
            activity_id = resolved.activity.activity_id
            if any(item.scope_activity_id != activity_id for item in references):
                raise _P2TerminalFailure(c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                                         self._SCOPE_CONFLICT_TEXT, retryable=False)
            candidates = [c.ResolvedEntityCandidate(
                kind=c.UiEntityType.ACTIVITY, entity_id=activity_id, scope_activity_id=activity_id,
            )]
            candidates.extend(c.ResolvedEntityCandidate(
                kind=c.UiEntityType.LEDGER_UNIT,
                entity_id=item.ledger_unit_id, scope_activity_id=activity_id,
            ) for item in resolved.ledger_units if not item.is_deleted)
            candidates.extend(c.ResolvedEntityCandidate(
                kind=c.UiEntityType.PARTICIPANT,
                entity_id=item.participant_id, scope_activity_id=activity_id,
            ) for item in resolved.participants if not item.is_deleted)
            try:
                references[:] = c.bind_stable_references(references, candidates, source_turn_id=turn_id)
            except ValueError:
                raise _P2TerminalFailure(c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                                         self._SCOPE_CONFLICT_TEXT, retryable=False) from None
            state.scope_activity_id = activity_id
            state.scope_fingerprint = _fingerprint({
                "owner": str(owner_id), "turn": str(turn_id), "activity": str(activity_id),
            })
            activity_binding = next(item for item in references if item.kind == "activity" and item.entity_id == activity_id)
            state.labels[activity_binding.ref] = P2ReferenceLabel(
                kind="activity", ref=activity_binding.ref, display_name=resolved.activity.name,
            )
            for item in resolved.ledger_units:
                binding = next((ref for ref in references if ref.kind == "ledger_unit" and ref.entity_id == item.ledger_unit_id), None)
                if binding is not None and not item.is_deleted:
                    state.labels[binding.ref] = P2ReferenceLabel(
                        kind="ledger_unit", ref=binding.ref, display_name=item.name,
                    )
            for item in resolved.participants:
                binding = next((ref for ref in references if ref.kind == "participant" and ref.entity_id == item.participant_id), None)
                if binding is not None and not item.is_deleted:
                    state.labels[binding.ref] = P2ReferenceLabel(
                        kind="participant", ref=binding.ref, display_name=item.name,
                    )
        else:
            if any(item.kind != "activity" for item in references):
                raise _P2TerminalFailure(c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                                         self._SCOPE_CONFLICT_TEXT, retryable=False)
            state.scope_activity_id = None
            state.scope_fingerprint = _fingerprint({"owner": str(owner_id), "turn": str(turn_id), "scope": "none"})
            state.labels = {
                token: label for token, label in state.labels.items()
                if token in {item.ref for item in references}
            }
        state.resolved_scope = resolved

    async def _fresh_identity(
        self,
        owner_id: uuid.UUID,
        activity_ids: set[uuid.UUID] | None = None,
        *,
        gate_revision: int | None = None,
    ) -> Principal:
        turn_id = _ACTIVE_TURN.get()
        if turn_id is None:
            raise _AuthRequired()
        try:
            grant = self._turn_grants.get(owner_id, turn_id)
        except P2GrantError:
            raise _AuthRequired() from None
        try:
            principal = await asyncio.to_thread(self._auth.verify_bearer, grant.token)
        except Unauthenticated:
            self._turn_grants.revoke(owner_id, turn_id)
            raise _AuthRequired() from None
        except AuthDependencyUnavailable:
            self._turn_grants.revoke(owner_id, turn_id)
            raise _P2DependencyPause(c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                                     "P2 dependency unavailable: auth_verifier_unavailable.") from None
        except Exception:
            self._turn_grants.revoke(owner_id, turn_id)
            raise _P2DependencyPause(c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                                     "P2 dependency unavailable: auth_verifier_unavailable.") from None
        now = datetime.now(timezone.utc)
        if (principal.user_id != owner_id or principal.expires_at is None
                or principal.expires_at.tzinfo is None or principal.expires_at.utcoffset() is None
                or principal.expires_at <= now):
            self._turn_grants.revoke(owner_id, turn_id)
            raise _AuthRequired()
        try:
            grant = self._turn_grants.refresh(owner_id, turn_id, principal, now=now)
        except P2GrantError:
            raise _AuthRequired() from None
        gate = await self._current_gate()
        if not gate.enabled or (gate_revision is not None and gate.disable_revision != gate_revision):
            raise _GateClosed()
        ids = activity_ids or set()
        if ids:
            try:
                await self._p2_backend.authorize_api_scope(
                    principal.user_id, tuple(sorted(ids, key=str)), grant.token, grant.expires_at,
                )
            except BackendReadError as exc:
                raise self._backend_pause(exc) from None
        return principal

    def _active_grant(self, owner_id: uuid.UUID, turn_id: uuid.UUID) -> P2TurnGrant:
        try:
            return self._turn_grants.get(owner_id, turn_id)
        except P2GrantError:
            raise _AuthRequired() from None

    @staticmethod
    def _make_verified_context(
        owner_id: uuid.UUID,
        turn_id: uuid.UUID,
        grant: P2TurnGrant,
        references: Sequence[c.BoundReference],
    ) -> VerifiedReadContext:
        refs: dict[str, BoundRef] = {}
        for item in references:
            refs[item.ref.value] = BoundRef(
                kind=item.kind, object_id=item.entity_id, activity_id=item.scope_activity_id,
                ledger_unit_id=item.entity_id if item.kind == "ledger_unit" else None,
            )
        return VerifiedReadContext(
            owner_user_id=owner_id, turn_id=turn_id, principal_user_id=owner_id,
            access_token=grant.token, expires_at=grant.expires_at,
            refs_by_opaque_token=refs,
        )

    async def _build_p2_context(
        self,
        aggregate: TurnAggregate,
        references: list[c.BoundReference],
        state: _TurnP2State,
        gate_revision: int,
        *,
        checkpoint: TurnCheckpoint | None = None,
        bound_evidence: list[c.BoundEvidenceReference] | None = None,
        bound_read_results: list[c.BoundReadResultReference] | None = None,
    ) -> tuple[c.ModelContext, list[c.BoundReference]]:
        turn = aggregate.record.turn
        checkpoint = checkpoint or aggregate.checkpoint
        inputs = [item.payload for item in checkpoint.accepted_inputs
                  if isinstance(item.payload, (c.SubmitTurnRequest, c.ResumeClarificationRequest))]
        input_text = inputs[-1].text if inputs else aggregate.record.original_text
        recent = [c.PriorMessage(role="user", text=item.text) for item in inputs[:-1][-19:]]
        permissions: list[c.HarnessPermission] = []
        if state.scope_activity_id is not None:
            permissions.extend([
                c.HarnessPermission.READ_EXPENSES, c.HarnessPermission.READ_DEBTS,
                c.HarnessPermission.PROPOSE_EXPENSE_CREATE,
                c.HarnessPermission.PROPOSE_EXPENSE_UPDATE,
                c.HarnessPermission.PROPOSE_EXPENSE_PRESENTATION_UPDATE,
            ])
            scope_ref = next(item.ref for item in references
                             if item.kind == "activity" and item.entity_id == state.scope_activity_id)
            verified_scope: c.ModelVerifiedScope = c.ModelActivityScope(
                kind="activity", activity_ref=scope_ref, permissions=permissions,
            )
        else:
            permissions.append(c.HarnessPermission.READ_ACTIVITIES)
            verified_scope = c.ModelNoActivityScope(kind="none", permissions=permissions)
        context = c.ModelContext(
            context_version=turn.context_version, input_text=input_text,
            verified_scope=verified_scope, recent_messages=recent,
            pending_slots=(checkpoint.last_clarification.missing_slots if checkpoint.last_clarification else []),
            bound_references=c.model_reference_tokens(references),
            read_results=[c.ModelReadResult(
                result_ref=item.result_ref, operation=item.operation,
                observed_at=item.observed_at, context_version=item.context_version,
                simulation=item.simulation, body=item.body,
            ) for item in checkpoint.read_results],
            policy_evidence=checkpoint.persisted_policy_evidence,
            available_permissions=permissions,
        )
        try:
            c.validate_model_context_bindings(
                context, source_turn_id=turn.turn_id, bound_references=references,
                bound_evidence_references=(bound_evidence if bound_evidence is not None
                                           else aggregate.record.bound_evidence_references),
                bound_read_results=(bound_read_results if bound_read_results is not None
                                    else aggregate.record.bound_read_results),
            )
        except ValueError:
            # Context may include bindings added at scope resolution; references are
            # the complete candidate set to be atomically persisted before the call.
            raise CapabilityUnavailable("P2 model context does not match durable Turn bindings") from None
        return context, references

    async def _prepare_p2_model_call(
        self, aggregate: TurnAggregate, context: c.ModelContext,
        references: list[c.BoundReference], claim_token: str,
    ) -> TurnAggregate:
        checkpoint = aggregate.checkpoint.model_copy(update={
            "model_context": context,
            "last_decision": None,
            "last_clarification": None,
            "resume_step": c.TurnStep.MODEL_DECISION,
        })
        return await self._save_checkpoint(
            aggregate, checkpoint, claim_token, bound_references=references,
        )

    async def _generate_p2_model(
        self,
        aggregate: TurnAggregate,
        context: c.ModelContext,
        claim_token: str,
        *,
        gate_revision: int,
        state: _TurnP2State,
        repair_feedback: str | None = None,
        repair: bool = False,
    ) -> tuple[str, TurnAggregate]:
        await self._model_gate.acquire()
        try:
            await self._ensure_p2_generation(aggregate, claim_token, context, gate_revision)
            checkpoint = aggregate.checkpoint
            if checkpoint.model_calls >= self._max_model_calls or (
                repair and checkpoint.repair_calls >= self._max_repair_calls
            ):
                raise _CallBudgetReached()
            charged_checkpoint = checkpoint.model_copy(update={
                "model_calls": checkpoint.model_calls + 1,
                "repair_calls": checkpoint.repair_calls + (1 if repair else 0),
            })
            charged = await self._save_checkpoint(aggregate, charged_checkpoint, claim_token)
            current_provenance = list(state.provenance.values())
            current_supplements = self._current_supplements(state)
            envelope = P2Harness.build_envelope(
                context, repair_feedback=repair_feedback,
                expense_supplements=current_supplements,
                reference_labels=list(state.labels.values()),
                provenance=current_provenance,
            )
            try:
                result = await asyncio.wait_for(
                    self._p2_provider.generate(envelope), timeout=self._model_timeout,
                )
            except asyncio.TimeoutError:
                raise _ModelTimeout() from None
            if not isinstance(result, str):
                raise ModelOutputError("provider response must be text")
            return result, charged
        finally:
            self._model_gate.release()

    async def _ensure_p2_generation(
        self, expected: TurnAggregate, claim_token: str,
        context: c.ModelContext, gate_revision: int,
    ) -> TurnAggregate:
        owner_id = expected.record.turn.owner_user_id
        turn_id = expected.record.turn.turn_id
        current = await asyncio.to_thread(self._store.get_turn, owner_id, turn_id)
        self._ensure_claim_current(current, expected, claim_token)
        if current.checkpoint.model_context != context or current.checkpoint.last_decision is not None:
            raise StateConflict("P2 model result no longer matches its durable checkpoint")
        await self._fresh_identity(
            owner_id, {self._scope_id_for_context(current, context)} - {None},
            gate_revision=gate_revision,
        )
        state = self._p2_states.get(turn_id)
        if state is not None:
            await self._verify_financial_versions(current, context, state)
        return current

    @staticmethod
    def _scope_id_for_context(aggregate: TurnAggregate, context: c.ModelContext) -> uuid.UUID | None:
        if not isinstance(context.verified_scope, c.ModelActivityScope):
            return None
        binding = next((item for item in aggregate.record.bound_references
                        if item.ref == context.verified_scope.activity_ref), None)
        return binding.entity_id if binding is not None else None

    @staticmethod
    def _accepted_decision(decision: c.SemanticDecision, context: c.ModelContext) -> c.SemanticDecision:
        try:
            c.validate_decision_against_context(decision, context)
        except ValueError:
            raise ModelOutputError("semantic decision is not valid for the current P2 context") from None
        return decision

    def _render_answer(
        self, decision: c.AnswerDecision, context: c.ModelContext, state: _TurnP2State,
    ) -> c.AnswerDecision:
        provenance = list(state.provenance.values())
        if decision.basis == "conversation":
            if context.read_results:
                if not any(item.body.items and (state.provenance.get(item.result_ref) is not None
                                                and state.provenance[item.result_ref].current)
                           for item in context.read_results):
                    raise ModelOutputError("conversation answer cannot bypass stale financial results")
            if context.verified_scope.kind == "none" and not context.read_results:
                return decision.model_copy(update={"text": self._SAFE_GENERIC_TEXT, "citations": []})
            # Empty reads are handled by a deterministic runtime answer with a
            # scope-authorized event. Model-authored conversation claims are closed.
            raise ModelOutputError("conversation answers cannot bypass business evidence")
        return P2Harness.render_answer(
            decision, context, provenance=provenance,
            expense_supplements=self._current_supplements(state),
            reference_labels=list(state.labels.values()),
        )

    @classmethod
    def _safe_clarification(cls, decision: c.ClarifyDecision) -> c.ClarifyDecision:
        # The model may classify missing fields but cannot author a user-visible
        # factual claim in a clarification prompt.
        text = " ".join(cls._CLARIFICATION_TEXT[slot] for slot in decision.missing_slots)
        return decision.model_copy(update={"prompt": text})

    async def _execute_p2_read(
        self,
        aggregate: TurnAggregate,
        decision: c.ReadDecision,
        context: c.ModelContext,
        claim_token: str,
        gate_revision: int,
        state: _TurnP2State,
    ) -> TurnAggregate:
        if aggregate.checkpoint.read_calls >= self._max_read_calls:
            raise _CallBudgetReached()
        owner_id = aggregate.record.turn.owner_user_id
        turn_id = aggregate.record.turn.turn_id
        activity_ids = {state.scope_activity_id} if state.scope_activity_id is not None else set()
        await self._fresh_identity(owner_id, activity_ids, gate_revision=gate_revision)
        charged_checkpoint = aggregate.checkpoint.model_copy(update={
            "read_calls": aggregate.checkpoint.read_calls + 1,
        })
        charged = await self._save_checkpoint(aggregate, charged_checkpoint, claim_token)
        grant = self._active_grant(owner_id, turn_id)
        verified = self._make_verified_context(owner_id, turn_id, grant, aggregate.record.bound_references)
        try:
            raw = await self._p2_backend.read(
                owner_id, turn_id, context, decision, verified=verified,
            )
        except BackendReadError as exc:
            if exc.code in ("read_limit_exceeded", "response_too_large", "data_changed_during_read"):
                raise _P2TerminalFailure(
                    c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                    "P2 query incomplete: narrow the query and submit a new Turn.", retryable=False,
                ) from None
            raise self._backend_pause(exc) from None
        await self._fresh_identity(owner_id, activity_ids, gate_revision=gate_revision)
        current = await asyncio.to_thread(self._store.get_turn, owner_id, turn_id)
        self._ensure_claim_current(current, charged, claim_token)
        if current.checkpoint_revision != charged.checkpoint_revision or current.checkpoint.generation != charged.checkpoint.generation:
            raise StateConflict("P2 read result no longer matches its charged checkpoint")
        if not raw.complete:
            raise _P2TerminalFailure(
                c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                "P2 query incomplete: narrow the query and submit a new Turn.", retryable=False,
            )
        stored, references, evidence, result_bindings, supplements, provenance = self._bind_p2_read_result(
            charged, raw, decision, state,
        )
        next_checkpoint = charged.checkpoint.model_copy(update={
            "read_results": [*charged.checkpoint.read_results, stored],
            "resume_step": c.TurnStep.MODEL_DECISION,
            "last_decision": None,
        })
        next_context, references = await self._build_p2_context(
            charged, references, state, gate_revision, checkpoint=next_checkpoint,
            bound_evidence=evidence, bound_read_results=result_bindings,
        )
        next_checkpoint = next_checkpoint.model_copy(update={"model_context": next_context})
        saved = await self._save_checkpoint(
            charged, next_checkpoint, claim_token, bound_references=references,
            bound_evidence_references=evidence, bound_read_results=result_bindings,
        )
        committed = next((item for item in saved.checkpoint.read_results
                          if item.result_ref == stored.result_ref), None)
        if committed is None:
            raise StateConflict("P2 result is missing from its committed checkpoint")
        state.result_decisions[stored.result_ref] = decision
        state.result_body_hashes[stored.result_ref] = self._p2_body_fingerprint(committed)
        state.result_binding_snapshots[stored.result_ref] = tuple(saved.record.bound_references)
        state.result_scope_ids[stored.result_ref] = state.scope_activity_id
        state.result_scope_fingerprints[stored.result_ref] = state.scope_fingerprint or ""
        if supplements:
            state.supplements[stored.result_ref] = supplements
        previous = dict(state.provenance)
        state.provenance = {
            result_ref: metadata.model_copy(update={
                "current": self._may_keep_p2_result_current(
                    saved, state, result_ref, metadata, stored.result_ref, provenance,
                ),
            })
            for result_ref, metadata in previous.items()
        }
        if provenance.operation in (c.ReadOperation.EXPENSES, c.ReadOperation.DEBTS):
            provenance = provenance.model_copy(update={
                "current": self._p2_result_snapshot_matches(
                    saved, state, stored.result_ref, provenance,
                ),
            })
        state.provenance[stored.result_ref] = provenance
        return saved

    @staticmethod
    def _current_supplements(state: _TurnP2State) -> list[P2ExpenseSupplement]:
        return [
            item
            for result_ref, values in state.supplements.items()
            if (state.provenance.get(result_ref) is not None
                and state.provenance[result_ref].current
                and state.provenance[result_ref].complete)
            for item in values
        ]

    @staticmethod
    def _p2_body_fingerprint(result: c.ToolReadResult) -> str:
        return _fingerprint(result.model_dump(mode="json", by_alias=True, exclude_none=False))

    def _may_keep_p2_result_current(
        self,
        aggregate: TurnAggregate,
        state: _TurnP2State,
        old_ref: c.ReadResultRef,
        old: P2ResultProvenance,
        new_ref: c.ReadResultRef,
        new: P2ResultProvenance,
    ) -> bool:
        # Only a previously current, distinct financial operation can join the
        # current group. Same-operation rereads never duplicate evidence.
        financial = (c.ReadOperation.EXPENSES, c.ReadOperation.DEBTS)
        if (not old.current or old.operation not in financial or new.operation not in financial
                or old.operation == new.operation):
            return False
        if not self._p2_result_snapshot_matches(aggregate, state, old_ref, old):
            return False
        if not self._p2_result_snapshot_matches(aggregate, state, new_ref, new):
            return False
        if (old.context_version != new.context_version
                or old.context_version != aggregate.record.turn.context_version
                or old.planning_generation != new.planning_generation
                or old.planning_generation != aggregate.checkpoint.generation
                or old.scope_fingerprint != new.scope_fingerprint
                or old.scope_fingerprint != state.scope_fingerprint
                or state.result_scope_ids.get(old_ref) is None
                or state.result_scope_ids.get(old_ref) != state.result_scope_ids.get(new_ref)
                or state.result_scope_ids.get(new_ref) != state.scope_activity_id
                or old.source != "supabase_postgrest" or new.source != "supabase_postgrest"
                or not old.complete or not new.complete or old.has_more or new.has_more
                or old.financial_versions != new.financial_versions):
            return False
        return True

    def _p2_result_snapshot_matches(
        self,
        aggregate: TurnAggregate,
        state: _TurnP2State,
        result_ref: c.ReadResultRef,
        metadata: P2ResultProvenance,
    ) -> bool:
        if (metadata.operation not in (c.ReadOperation.EXPENSES, c.ReadOperation.DEBTS)
                or not metadata.complete or metadata.has_more
                or metadata.source != "supabase_postgrest"
                or metadata.context_version != aggregate.record.turn.context_version
                or metadata.planning_generation != aggregate.checkpoint.generation):
            return False
        stored = next((item for item in aggregate.checkpoint.read_results
                       if item.result_ref == result_ref), None)
        decision = state.result_decisions.get(result_ref)
        snapshot = state.result_binding_snapshots.get(result_ref)
        scope_id = state.result_scope_ids.get(result_ref)
        scope_fingerprint = state.result_scope_fingerprints.get(result_ref)
        if (stored is None or decision is None or not snapshot or scope_id is None
                or not scope_fingerprint or metadata.scope_fingerprint != scope_fingerprint
                or metadata.operation != stored.operation
                or metadata.observed_at != stored.observed_at
                or metadata.context_version != stored.context_version
                or stored.simulation
                or state.result_body_hashes.get(result_ref) != self._p2_body_fingerprint(stored)):
            return False
        model_context = aggregate.checkpoint.model_context
        if model_context is None:
            return False
        visible = next((item for item in model_context.read_results
                        if item.result_ref == result_ref), None)
        if (visible is None or visible.operation != stored.operation
                or visible.observed_at != stored.observed_at
                or visible.context_version != stored.context_version
                or visible.simulation
                or visible.body != stored.body):
            return False
        result_binding = next((item for item in aggregate.record.bound_read_results
                               if item.result_ref == result_ref), None)
        if (result_binding is None or result_binding.result_id != stored.result_id
                or result_binding.source_turn_id != aggregate.record.turn.turn_id
                or result_binding.operation != stored.operation
                or result_binding.observed_at != stored.observed_at
                or result_binding.context_version != stored.context_version):
            return False
        current_bindings = {(item.kind, item.ref.value): item
                            for item in aggregate.record.bound_references}
        for old_binding in snapshot:
            current = current_bindings.get((old_binding.kind, old_binding.ref.value))
            if current != old_binding or current.source_turn_id != aggregate.record.turn.turn_id:
                return False
        if any(item.scope_activity_id != scope_id for item in snapshot):
            return False
        activity_binding = next((item for item in snapshot
                                 if item.kind == "activity" and item.entity_id == scope_id), None)
        if (activity_binding is None
                or not isinstance(model_context.verified_scope, c.ModelActivityScope)
                or model_context.verified_scope.activity_ref != activity_binding.ref):
            return False
        try:
            c.validate_model_context_bindings(
                aggregate.checkpoint.model_context,
                source_turn_id=aggregate.record.turn.turn_id,
                bound_references=aggregate.record.bound_references,
                bound_evidence_references=aggregate.record.bound_evidence_references,
                bound_read_results=aggregate.record.bound_read_results,
            )
        except (ValueError, TypeError):
            return False

        binding_payload = sorted(
            [(item.kind, item.ref.value, str(item.entity_id), str(item.scope_activity_id))
             for item in snapshot],
        )
        turn_fingerprint = _fingerprint({
            "owner": str(aggregate.record.turn.owner_user_id),
            "turn": str(aggregate.record.turn.turn_id), "bindings": binding_payload,
        })
        if turn_fingerprint != metadata.turn_binding_fingerprint:
            return False
        criteria_payload = decision.criteria.model_dump(mode="json", by_alias=True, exclude_none=False)
        if (decision.operation != stored.operation
                or _fingerprint(criteria_payload) != metadata.criteria_fingerprint
                or _fingerprint({
                    "operation": decision.operation.value,
                    "criteria": criteria_payload,
                    "activity_scope": str(scope_id),
                }) != metadata.query_fingerprint):
            return False
        financial_rows: list[tuple[str, int]] = []
        versions = {item.activity_ref: item for item in metadata.financial_versions}
        if len(versions) != len(metadata.financial_versions):
            return False
        for activity_ref, item in versions.items():
            bound = next((ref for ref in snapshot
                          if ref.kind == "activity" and ref.ref == activity_ref), None)
            if bound is None:
                return False
            financial_rows.append((str(bound.entity_id), item.financial_version))
        if len(financial_rows) != 1 or financial_rows[0][0] != str(scope_id):
            return False
        source_fingerprint = _fingerprint({
            "source": metadata.source,
            "financial_versions": sorted(financial_rows),
            "observed_at": metadata.observed_at.isoformat(),
            "result_id": str(stored.result_id),
            "query_fingerprint": metadata.query_fingerprint,
            "scope_fingerprint": metadata.scope_fingerprint,
            "turn_binding_fingerprint": metadata.turn_binding_fingerprint,
        })
        if source_fingerprint != metadata.source_fingerprint:
            return False
        fact_evidence = {fact.evidence_ref: fact for fact in stored.body.items}
        if not fact_evidence:
            return False
        bound_evidence = {item.evidence_ref: item
                          for item in aggregate.record.bound_evidence_references}
        if len(bound_evidence) != len(aggregate.record.bound_evidence_references):
            return False
        for evidence_ref, fact in fact_evidence.items():
            proof = bound_evidence.get(evidence_ref)
            expected_kind = "expense" if isinstance(fact, c.ExpenseFact) else "debt"
            if (proof is None or proof.kind != expected_kind
                    or proof.source_result_id != stored.result_id
                    or proof.source_turn_id != aggregate.record.turn.turn_id
                    or proof.scope_activity_id != scope_id
                    or proof.context_version != stored.context_version):
                return False
            if isinstance(fact, c.ExpenseFact):
                entity = next((ref for ref in snapshot
                               if ref.kind == "expense" and ref.ref == fact.expense_ref), None)
                if (entity is None or entity.entity_id != proof.entity_id
                        or entity.scope_activity_id != scope_id
                        or proof.scope_activity_id != scope_id):
                    return False
                if any(not any(ref.kind == "participant" and ref.ref == token for ref in snapshot)
                       for token in fact.participant_refs):
                    return False
            elif isinstance(fact, c.DebtFact):
                if any(not any(ref.kind == "participant" and ref.ref == token for ref in snapshot)
                       for token in (fact.debtor_ref, fact.creditor_ref)):
                    return False
            else:
                return False

        supplements = state.supplements.get(result_ref, [])
        try:
            P2Harness._validated_supplements(
                model_context, {result_ref: metadata}, supplements,
                {item.ref: item for item in state.labels.values()},
            )
        except ModelOutputError:
            return False
        return True

    def _bind_p2_read_result(
        self,
        aggregate: TurnAggregate,
        raw: P2BackendReadResult,
        decision: c.ReadDecision,
        state: _TurnP2State,
    ) -> tuple[
        c.ToolReadResult,
        list[c.BoundReference],
        list[c.BoundEvidenceReference],
        list[c.BoundReadResultReference],
        list[P2ExpenseSupplement],
        P2ResultProvenance,
    ]:
        turn_id = aggregate.record.turn.turn_id
        used_refs = {item.result_ref for item in aggregate.record.bound_read_results}
        result_ref = next((item for item in c.ReadResultRef if item not in used_refs), None)
        if result_ref is None:
            raise _P2TerminalFailure(c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                                     "P2 result reference capacity reached; submit a narrower new Turn.")
        result_id = uuid.uuid4()
        scope_id = state.scope_activity_id
        if raw.operation in (c.ReadOperation.EXPENSES, c.ReadOperation.DEBTS):
            resolved_activity = state.resolved_scope.activity if state.resolved_scope is not None else None
            current_version = raw.financial_versions.get(scope_id) if scope_id is not None else None
            if (
                resolved_activity is None or resolved_activity.activity_id != scope_id
                or current_version is None or current_version != resolved_activity.financial_version
            ):
                raise _P2TerminalFailure(
                    c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                    "P2 activity changed during scope resolution. Submit a new Turn to refresh the query.",
                )
        entity_candidates: list[c.ResolvedEntityCandidate] = []
        if raw.operation == c.ReadOperation.ACTIVITIES:
            entity_candidates.extend(c.ResolvedEntityCandidate(
                kind=c.UiEntityType.ACTIVITY, entity_id=item.activity_id,
                scope_activity_id=item.activity_id,
            ) for item in raw.activities)
        elif raw.operation == c.ReadOperation.EXPENSES:
            if scope_id is None:
                raise CapabilityUnavailable("P2 expense result has no verified activity scope")
            for expense in raw.expenses:
                if expense.activity_id != scope_id:
                    raise CapabilityUnavailable("P2 expense row escaped its verified activity scope")
                if expense.original_amount <= 0:
                    raise _P2TerminalFailure(
                        c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                        "P2 read contains a refund or non-positive amount that v1 cannot safely represent.",
                    )
                entity_candidates.append(c.ResolvedEntityCandidate(
                    kind=c.UiEntityType.EXPENSE, entity_id=expense.expense_id,
                    scope_activity_id=scope_id,
                ))
                participant_ids = {
                    item.participant_id for item in (*expense.payments, *expense.splits)
                }
                entity_candidates.extend(c.ResolvedEntityCandidate(
                    kind=c.UiEntityType.PARTICIPANT, entity_id=participant_id,
                    scope_activity_id=scope_id,
                ) for participant_id in participant_ids)
        elif raw.operation == c.ReadOperation.DEBTS:
            if scope_id is None:
                raise CapabilityUnavailable("P2 debt result has no verified activity scope")
            participant_ids = {
                participant_id
                for item in raw.debts
                for participant_id in (item.debtor_participant_id, item.creditor_participant_id)
            }
            if any(item.original_amount <= 0 for item in raw.debts):
                raise _P2TerminalFailure(
                    c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                    "P2 read contains a non-positive debt amount that v1 cannot safely represent.",
                )
            entity_candidates.extend(c.ResolvedEntityCandidate(
                kind=c.UiEntityType.PARTICIPANT, entity_id=participant_id,
                scope_activity_id=scope_id,
            ) for participant_id in participant_ids)
        else:
            raise CapabilityUnavailable("P2 operation is outside the frozen read allowlist")
        try:
            references = c.bind_stable_references(
                list(aggregate.record.bound_references), entity_candidates, source_turn_id=turn_id,
            )
        except ValueError:
            raise CapabilityUnavailable("P2 read returned an invalid reference binding") from None
        refs_by_id = {(item.kind, item.entity_id): item for item in references}
        candidates: list[c.ResolvedEvidenceCandidate] = []
        entity_for_fact: list[tuple[str, uuid.UUID, uuid.UUID]] = []
        if raw.operation == c.ReadOperation.ACTIVITIES:
            for item in raw.activities:
                entity_for_fact.append(("activity", item.activity_id, item.activity_id))
        elif raw.operation == c.ReadOperation.EXPENSES:
            for item in raw.expenses:
                entity_for_fact.append(("expense", item.expense_id, item.activity_id))
        else:
            for item in raw.debts:
                assert scope_id is not None
                entity_for_fact.append(("debt", self._debt_evidence_entity_id(turn_id, scope_id, item), scope_id))
        for kind, entity_id, fact_scope_id in entity_for_fact:
            candidates.append(c.ResolvedEvidenceCandidate(
                kind=kind, entity_id=entity_id, scope_activity_id=fact_scope_id,
                source_result_id=result_id, context_version=aggregate.record.turn.context_version,
            ))
        try:
            evidence = c.bind_stable_evidence(
                list(aggregate.record.bound_evidence_references), candidates, source_turn_id=turn_id,
            )
            result_bindings = c.bind_stable_read_results(
                list(aggregate.record.bound_read_results),
                [c.ResolvedReadResultCandidate(
                    result_ref=result_ref, result_id=result_id, operation=raw.operation,
                    observed_at=raw.observed_at, context_version=aggregate.record.turn.context_version,
                )], source_turn_id=turn_id,
            )
        except ValueError:
            raise _P2TerminalFailure(c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                                     "P2 binding capacity reached; submit a narrower new Turn.") from None
        evidence_by_identity = {
            (item.kind, item.source_result_id, item.entity_id, item.context_version): item
            for item in evidence
        }
        facts: list[Any] = []
        supplements: list[P2ExpenseSupplement] = []
        context_version = aggregate.record.turn.context_version
        for source in raw.activities:
            citation = evidence_by_identity[("activity", result_id, source.activity_id, context_version)].evidence_ref
            activity_ref = refs_by_id[("activity", source.activity_id)].ref
            facts.append(c.ActivityFact(
                kind="activity", evidence_ref=citation, activity_ref=activity_ref,
                name=source.name,
                activity_kind=(c.ActivityKind.LARGE if source.activity_type == "large" else c.ActivityKind.NORMAL),
                base_currency=source.base_currency,
                status=(c.ActivityStatus.ARCHIVED if source.archived_at else c.ActivityStatus.ACTIVE),
                observed_at=raw.observed_at, context_version=context_version,
            ))
        for source in raw.expenses:
            citation = evidence_by_identity[("expense", result_id, source.expense_id, context_version)].evidence_ref
            expense_ref = refs_by_id[("expense", source.expense_id)].ref
            participants = sorted(
                {row.participant_id for row in (*source.payments, *source.splits)}, key=str,
            )
            participant_refs = [refs_by_id[("participant", item)].ref for item in participants]
            facts.append(c.ExpenseFact(
                kind="expense", evidence_ref=citation, expense_ref=expense_ref,
                title=source.title, original_amount=_money(source.original_amount),
                original_currency=source.original_currency, occurred_at=source.occurred_at,
                participant_refs=participant_refs, financial_locked=source.financial_locked,
                expense_version=str(source.expense_version), observed_at=raw.observed_at,
                context_version=context_version,
            ))
        for source in raw.debts:
            assert scope_id is not None
            debt_entity = self._debt_evidence_entity_id(turn_id, scope_id, source)
            citation = evidence_by_identity[("debt", result_id, debt_entity, context_version)].evidence_ref
            facts.append(c.DebtFact(
                kind="debt", evidence_ref=citation,
                debtor_ref=refs_by_id[("participant", source.debtor_participant_id)].ref,
                creditor_ref=refs_by_id[("participant", source.creditor_participant_id)].ref,
                amount=_money(source.original_amount), currency=source.currency,
                observed_at=raw.observed_at, context_version=context_version,
            ))
        if raw.operation == c.ReadOperation.ACTIVITIES:
            body: c.ReadResultBody = c.ActivityListResult(kind="activities", items=facts)
        elif raw.operation == c.ReadOperation.EXPENSES:
            body = c.ExpenseListResult(kind="expenses", items=facts)
        else:
            body = c.DebtListResult(kind="debts", items=facts)
        stored = c.ToolReadResult(
            result_id=result_id, result_ref=result_ref, operation=raw.operation,
            observed_at=raw.observed_at, context_version=context_version,
            simulation=False, body=body,
        )
        provenance = self._make_provenance(aggregate, stored, decision, raw, state, references)
        if raw.operation == c.ReadOperation.EXPENSES:
            activity_ref = next(item.ref for item in references
                                if item.kind == "activity" and item.entity_id == scope_id)
            activity = state.resolved_scope.activity
            base_currency = activity.base_currency
            for source, fact in zip(raw.expenses, facts, strict=True):
                participant_lines: list[P2PaymentLine] = []
                for line in source.payments:
                    token = refs_by_id[("participant", line.participant_id)].ref
                    label = state.labels.get(token)
                    if label is None:
                        raise CapabilityUnavailable("P2 payer label is unavailable in the verified scope")
                    participant_lines.append(P2PaymentLine(
                        participant_ref=token, display_name=label.display_name,
                        role="payer", amount=_money(line.amount), currency=source.original_currency,
                        base_amount=_money(line.base_amount) if line.base_amount is not None else None,
                        base_currency=base_currency if line.base_amount is not None else None,
                    ))
                split_lines: list[P2PaymentLine] = []
                for line in source.splits:
                    token = refs_by_id[("participant", line.participant_id)].ref
                    label = state.labels.get(token)
                    if label is None:
                        raise CapabilityUnavailable("P2 split label is unavailable in the verified scope")
                    split_lines.append(P2PaymentLine(
                        participant_ref=token, display_name=label.display_name,
                        role="split_participant", amount=_money(line.amount), currency=source.original_currency,
                        base_amount=_money(line.base_amount) if line.base_amount is not None else None,
                        base_currency=base_currency if line.base_amount is not None else None,
                    ))
                version = raw.financial_versions.get(source.activity_id)
                if version is None:
                    raise CapabilityUnavailable("P2 expense result is missing its source version")
                supplements.append(P2ExpenseSupplement(
                    result_ref=result_ref, evidence_ref=fact.evidence_ref,
                    expense_ref=fact.expense_ref, activity_ref=activity_ref,
                    expense_version=fact.expense_version,
                    original_currency=source.original_currency, base_currency=base_currency,
                    observed_at=raw.observed_at, context_version=context_version,
                    financial_version=version, source_fingerprint=provenance.source_fingerprint,
                    payments=participant_lines, splits=split_lines,
                ))
        return stored, references, evidence, result_bindings, supplements, provenance

    def _make_provenance(
        self,
        aggregate: TurnAggregate,
        stored: c.ToolReadResult,
        decision: c.ReadDecision,
        raw: P2BackendReadResult,
        state: _TurnP2State,
        references: Sequence[c.BoundReference],
    ) -> P2ResultProvenance:
        financial_versions: list[P2FinancialVersion] = []
        for activity_id, version in sorted(raw.financial_versions.items(), key=lambda pair: str(pair[0])):
            binding = next((item for item in references
                            if item.kind == "activity" and item.entity_id == activity_id), None)
            if binding is None:
                raise CapabilityUnavailable("P2 financial version has no typed activity ref")
            base_currency = None
            if state.resolved_scope is not None and state.resolved_scope.activity is not None:
                if state.resolved_scope.activity.activity_id == activity_id:
                    if state.resolved_scope.activity.financial_version != version:
                        raise _P2TerminalFailure(
                            c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                            "P2 activity changed during scope resolution. Submit a new Turn to refresh the query.",
                        )
                    base_currency = state.resolved_scope.activity.base_currency
            activity = next((item for item in raw.activities if item.activity_id == activity_id), None)
            if activity is not None:
                base_currency = activity.base_currency
            financial_versions.append(P2FinancialVersion(
                activity_ref=binding.ref, financial_version=version, base_currency=base_currency,
            ))
        criteria_payload = decision.criteria.model_dump(mode="json", by_alias=True, exclude_none=False)
        criteria_fingerprint = _fingerprint(criteria_payload)
        activity_scope = str(state.scope_activity_id) if state.scope_activity_id is not None else None
        query_fingerprint = _fingerprint({
            "operation": decision.operation.value, "criteria": criteria_payload,
            "activity_scope": activity_scope,
        })
        binding_payload = sorted(
            [(item.kind, item.ref.value, str(item.entity_id), str(item.scope_activity_id))
             for item in references],
        )
        turn_fingerprint = _fingerprint({
            "owner": str(aggregate.record.turn.owner_user_id),
            "turn": str(aggregate.record.turn.turn_id), "bindings": binding_payload,
        })
        scope_fingerprint = state.scope_fingerprint or _fingerprint({"scope": "missing"})
        source_fingerprint = _fingerprint({
            "source": raw.source,
            "financial_versions": sorted((str(key), value) for key, value in raw.financial_versions.items()),
            "observed_at": raw.observed_at.isoformat(),
            "result_id": str(stored.result_id),
            "query_fingerprint": query_fingerprint,
            "scope_fingerprint": scope_fingerprint,
            "turn_binding_fingerprint": turn_fingerprint,
        })
        return P2ResultProvenance(
            result_ref=stored.result_ref, operation=stored.operation,
            source=raw.source, observed_at=stored.observed_at,
            context_version=stored.context_version,
            financial_versions=financial_versions,
            planning_generation=aggregate.checkpoint.generation,
            complete=raw.complete, current=True, page_index=0, has_more=False,
            source_fingerprint=source_fingerprint,
            query_fingerprint=query_fingerprint, scope_fingerprint=scope_fingerprint,
            turn_binding_fingerprint=turn_fingerprint,
            criteria_fingerprint=criteria_fingerprint,
        )

    @staticmethod
    def _debt_evidence_entity_id(turn_id: uuid.UUID, activity_id: uuid.UUID, source: P2DebtDTO) -> uuid.UUID:
        """Server-only row identity; distinguish multiple debts for one debtor."""
        stable = "|".join((
            str(turn_id), str(activity_id), str(source.debtor_participant_id),
            str(source.creditor_participant_id), source.currency,
            str(source.original_amount.normalize()), str(source.base_amount.normalize()),
            str(source.base_total.normalize()), str(source.financial_version),
        ))
        return uuid.uuid5(uuid.NAMESPACE_URL, "shared-ledger:p2:debt:" + stable)

    async def _verify_financial_versions(
        self, aggregate: TurnAggregate, context: c.ModelContext, state: _TurnP2State,
    ) -> None:
        expected: dict[uuid.UUID, int] = {}
        for metadata in state.provenance.values():
            if not metadata.current or metadata.operation not in (c.ReadOperation.EXPENSES, c.ReadOperation.DEBTS):
                continue
            for item in metadata.financial_versions:
                binding = next((ref for ref in aggregate.record.bound_references
                                if ref.kind == "activity" and ref.ref == item.activity_ref), None)
                if binding is None:
                    raise _P2TerminalFailure(
                        c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                        "P2 result freshness binding is unavailable. Submit a new Turn to refresh the query.",
                    )
                prior = expected.setdefault(binding.entity_id, item.financial_version)
                if prior != item.financial_version:
                    raise _P2TerminalFailure(
                        c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                        "P2 results contain conflicting activity versions. Submit a new Turn to refresh the query.",
                    )
        if not expected:
            return
        owner_id = aggregate.record.turn.owner_user_id
        turn_id = aggregate.record.turn.turn_id
        grant = self._active_grant(owner_id, turn_id)
        verified = self._make_verified_context(owner_id, turn_id, grant, aggregate.record.bound_references)
        try:
            await self._p2_backend.verify_financial_versions(verified, expected)
        except BackendReadError as exc:
            if exc.code == "data_changed_during_read":
                raise _P2TerminalFailure(
                    c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                    "P2 financial records changed. Submit a new Turn to refresh the query.",
                ) from None
            raise self._backend_pause(exc) from None

    async def _finalize_guard(
        self, aggregate: TurnAggregate, claim_token: str, context: c.ModelContext, gate_revision: int,
    ) -> None:
        owner_id = aggregate.record.turn.owner_user_id
        turn_id = aggregate.record.turn.turn_id
        current = await asyncio.to_thread(self._store.get_turn, owner_id, turn_id)
        self._ensure_claim_current(current, aggregate, claim_token)
        if current.checkpoint.model_context != context:
            raise StateConflict("P2 final decision no longer matches its durable context")
        state = self._p2_states.get(turn_id)
        if state is not None:
            await self._verify_financial_versions(current, context, state)
        await self._fresh_identity(
            owner_id, {state.scope_activity_id} - {None} if state and state.scope_activity_id else set(),
            gate_revision=gate_revision,
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
        events = [
            EventDraft(
                type=c.EventType.CLARIFICATION, occurred_at=datetime.now(timezone.utc), simulation=False,
                payload=c.ClarificationEventPayload(
                    prompt=decision.prompt, missing_slots=decision.missing_slots, resume_state=resume_state,
                ),
            ),
            self._status_event(after),
        ]
        await self._transition(aggregate, after, events, claim_token, checkpoint=checkpoint)

    async def _wait_for_restart_clarification(
        self, aggregate: TurnAggregate, context: c.ModelContext, claim_token: str, gate_revision: int,
    ) -> None:
        decision = c.ClarifyDecision(
            kind="clarify", prompt=self._CLARIFICATION_TEXT[c.ClarificationSlot.ACTIVITY],
            missing_slots=[c.ClarificationSlot.ACTIVITY],
        )
        checkpoint = aggregate.checkpoint.model_copy(update={
            "last_decision": decision, "last_clarification": decision,
            "resume_step": c.TurnStep.MODEL_DECISION,
        })
        saved = await self._save_checkpoint(aggregate, checkpoint, claim_token)
        await self._wait_for_input(saved, decision, context, claim_token, gate_revision)

    async def _complete_answer(
        self, aggregate: TurnAggregate, decision: c.AnswerDecision, context: c.ModelContext,
        claim_token: str, gate_revision: int, *, state: _TurnP2State | None = None,
        proposal_ack: bool = False,
    ) -> None:
        await self._finalize_guard(aggregate, claim_token, context, gate_revision)
        before = aggregate.record.turn
        after = self._next_state(before, c.TurnState.COMPLETED, c.TurnStep.TERMINAL)
        events = [
            EventDraft(
                type=c.EventType.MESSAGE, occurred_at=datetime.now(timezone.utc), simulation=False,
                payload=c.MessageEventPayload(text=decision.text, citations=decision.citations),
            ),
            self._status_event(after),
        ]
        checkpoint = aggregate.checkpoint.model_copy(update={"resume_step": None})
        await self._transition(aggregate, after, events, claim_token, checkpoint=checkpoint)
        self._p2_states.pop(aggregate.record.turn.turn_id, None)

    async def _complete_empty_result(
        self, aggregate: TurnAggregate, context: c.ModelContext, claim_token: str, gate_revision: int,
    ) -> None:
        """Report a complete empty query without fabricating the citation v1 requires."""
        await self._finalize_guard(aggregate, claim_token, context, gate_revision)
        before = aggregate.record.turn
        after = self._next_state(before, c.TurnState.COMPLETED, c.TurnStep.TERMINAL)
        events = [
            EventDraft(
                type=c.EventType.MESSAGE, occurred_at=datetime.now(timezone.utc), simulation=False,
                payload=c.MessageEventPayload(
                    text="查询已完成，但当前协议无法为零记录结果提供引用式答案。请提交新的查询。",
                    citations=[],
                ),
            ),
            self._status_event(after),
        ]
        await self._transition(
            aggregate, after, events, claim_token,
            checkpoint=aggregate.checkpoint.model_copy(update={"resume_step": None}),
        )
        self._p2_states.pop(aggregate.record.turn.turn_id, None)

    async def _terminal_error(
        self, claimed: ClaimedTurn, code: c.ApiErrorCode, message: str, *, retryable: bool,
    ) -> None:
        owner_id = claimed.turn.record.turn.owner_user_id
        turn_id = claimed.turn.record.turn.turn_id
        try:
            aggregate = await asyncio.to_thread(self._store.get_turn, owner_id, turn_id)
            before = aggregate.record.turn
            if before.state != c.TurnState.RUNNING or before.execution is not None:
                return
            code, message, retryable = _closed_error(code, message, retryable)
            after = self._next_state(
                before, c.TurnState.FAILED, c.TurnStep.TERMINAL, wait_reason=None, resume_state=None,
            )
            event = EventDraft(
                type=c.EventType.ERROR, occurred_at=datetime.now(timezone.utc), simulation=False,
                payload=c.ErrorEventPayload(code=code, message=message, retryable=retryable),
            )
            events: list[EventDraft] = [self._status_event(after)]
            if self._record_error_proof(aggregate, event, after):
                events.insert(0, event)
            await self._transition(
                aggregate, after, events, claimed.claim_token,
                checkpoint=aggregate.checkpoint.model_copy(update={"resume_step": None}),
            )
        except (StateConflict, StoreNotFound, StoreError):
            return
        finally:
            self._p2_states.pop(turn_id, None)

    async def _pause_for_auth(
        self, claimed: ClaimedTurn, *, resume_state: c.ResumeState,
        code: c.ApiErrorCode, message: str,
    ) -> None:
        owner_id = claimed.turn.record.turn.owner_user_id
        turn_id = claimed.turn.record.turn.turn_id
        try:
            aggregate = await asyncio.to_thread(self._store.get_turn, owner_id, turn_id)
            before = aggregate.record.turn
            if before.execution is not None or before.state != c.TurnState.RUNNING:
                return
            code, message, retryable = _closed_error(code, message, True)
            after = self._next_state(
                before, c.TurnState.WAIT_INPUT, c.TurnStep.AUTH_REQUIRED,
                wait_reason=c.WaitReason.AUTH_REQUIRED, resume_state=resume_state,
            )
            checkpoint = aggregate.checkpoint.model_copy(update={
                "resume_step": aggregate.checkpoint.resume_step or before.step,
            })
            error = EventDraft(
                type=c.EventType.ERROR, occurred_at=datetime.now(timezone.utc), simulation=False,
                payload=c.ErrorEventPayload(code=code, message=message, retryable=retryable),
            )
            events: list[EventDraft] = [self._status_event(after)]
            if self._record_error_proof(aggregate, error, after):
                events.insert(0, error)
            await self._transition(aggregate, after, events, claimed.claim_token, checkpoint=checkpoint)
        except (StateConflict, StoreNotFound, StoreError):
            return
        finally:
            self._p2_states.pop(turn_id, None)

    def _record_error_proof(
        self, aggregate: TurnAggregate, event: EventDraft, after: c.TurnStateSnapshot,
    ) -> bool:
        try:
            self._journal.record(
                aggregate.record.turn.owner_user_id, aggregate.record.turn.turn_id, event,
                generation=aggregate.checkpoint.generation,
                checkpoint_revision=aggregate.checkpoint_revision + 1,
                resulting_state_revision=after.state_revision,
            )
            return True
        except P2EventProofError:
            return False

    def safe_scope_free_event(self, aggregate: TurnAggregate, event: Any) -> bool:
        # Error proofs are a separate exact-digest channel and remain verifiable
        # after auth recovery or when business refs exist. They contain only a
        # closed stable code/message, never upstream or financial details.
        if event.type == c.EventType.ERROR:
            return self._journal.verifies(aggregate, event)
        if event.type == c.EventType.CLARIFICATION:
            # Historical clarifications remain safe to poll after resume only
            # when they exactly match the small deterministic slot templates.
            # This does not authorize any business fact event.
            expected = " ".join(
                self._CLARIFICATION_TEXT[slot] for slot in event.payload.missing_slots
            )
            return not event.simulation and event.payload.prompt == expected
        context = aggregate.checkpoint.model_context
        if context is None or context.verified_scope.kind != "none":
            return False
        if (
            aggregate.record.bound_references or aggregate.record.bound_evidence_references
            or aggregate.record.bound_read_results or aggregate.checkpoint.read_results
            or aggregate.checkpoint.persisted_policy_evidence
            or aggregate.record.turn.execution is not None
        ):
            return False
        if event.type == c.EventType.MESSAGE:
            if aggregate.checkpoint.last_decision != c.AnswerDecision(
                kind="answer", basis="conversation", text=self._SAFE_GENERIC_TEXT, citations=[],
            ):
                return False
            return event.payload.text == self._SAFE_GENERIC_TEXT and not event.payload.citations
        if event.type == c.EventType.CLARIFICATION:
            decision = aggregate.checkpoint.last_decision
            return (
                isinstance(decision, c.ClarifyDecision)
                and event.payload.prompt == decision.prompt
                and event.payload.missing_slots == decision.missing_slots
                and event.payload.resume_state == aggregate.record.turn.resume_state
                and not context.read_results
            )
        return False

    def _activity_ids(self, context: c.ModelContext) -> set[uuid.UUID]:
        turn_id = _ACTIVE_TURN.get()
        state = self._p2_states.get(turn_id) if turn_id is not None else None
        if state is None or state.scope_activity_id is None or context.verified_scope.kind != "activity":
            return set()
        return {state.scope_activity_id}

    async def _save_checkpoint(
        self, aggregate: TurnAggregate, checkpoint: TurnCheckpoint, claim_token: str | None,
        *, bound_references: list[c.BoundReference] | None = None,
        bound_evidence_references: list[c.BoundEvidenceReference] | None = None,
        bound_read_results: list[c.BoundReadResultReference] | None = None,
    ) -> TurnAggregate:
        references = bound_references if bound_references is not None else aggregate.record.bound_references
        evidence = (bound_evidence_references if bound_evidence_references is not None
                    else aggregate.record.bound_evidence_references)
        read_bindings = bound_read_results if bound_read_results is not None else aggregate.record.bound_read_results
        if checkpoint.model_context is not None:
            expected_reads = [c.ModelReadResult(
                result_ref=item.result_ref, operation=item.operation,
                observed_at=item.observed_at, context_version=item.context_version,
                simulation=item.simulation, body=item.body,
            ) for item in checkpoint.read_results]
            if checkpoint.model_context.read_results != expected_reads:
                raise CapabilityUnavailable("P2 model context differs from durable full result bodies")
            try:
                c.validate_model_context_bindings(
                    checkpoint.model_context, source_turn_id=aggregate.record.turn.turn_id,
                    bound_references=references, bound_evidence_references=evidence,
                    bound_read_results=read_bindings,
                )
            except ValueError:
                raise CapabilityUnavailable("P2 model context is not bound to durable Turn evidence") from None
        return await asyncio.to_thread(
            self._store.save_checkpoint, aggregate.record.turn.owner_user_id,
            aggregate.record.turn.turn_id,
            expected_state_revision=aggregate.record.turn.state_revision,
            expected_checkpoint_revision=aggregate.checkpoint_revision,
            checkpoint=checkpoint, bound_references=bound_references,
            bound_evidence_references=bound_evidence_references,
            bound_read_results=bound_read_results, claim_token=claim_token,
        )

    @staticmethod
    def _status_event(snapshot: c.TurnStateSnapshot) -> EventDraft:
        return EventDraft(
            type=c.EventType.STATUS, occurred_at=datetime.now(timezone.utc), simulation=False,
            payload=c.StatusEventPayload(
                state=snapshot.state, step=snapshot.step, state_revision=snapshot.state_revision,
                wait_reason=snapshot.wait_reason, resume_state=snapshot.resume_state,
            ),
        )

    async def _wait_for_confirmation(
        self, aggregate: TurnAggregate, decision: c.ProposeDecision, context: c.ModelContext,
        claim_token: str, gate_revision: int,
    ) -> None:
        answer = P2Harness.proposal_acknowledgement()
        saved = await self._save_decision(aggregate, answer, context, claim_token)
        await self._complete_answer(saved, answer, context, claim_token, gate_revision, proposal_ack=True)

    def _make_proposal(self, *args: Any, **kwargs: Any) -> Any:
        raise CapabilityUnavailable("P2 never creates or previews proposals")

    async def prepare_proposal_adjustment(self, *args: Any, **kwargs: Any) -> Any:
        raise CapabilityUnavailable("P2 does not adjust proposals")

    def _backend_pause(self, error: BackendReadError) -> Exception:
        if error.code in ("invalid_auth_context", "auth_rejected"):
            return _AuthRequired()
        if error.code == "data_changed_during_read":
            return _P2TerminalFailure(
                c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                "P2 financial records changed. Submit a new Turn to refresh the query.",
            )
        if error.code in ("scope_unavailable", "access_denied"):
            return _P2TerminalFailure(
                c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                "P2 activity scope could not be verified. No data was disclosed.",
            )
        if error.code in ("unsupported_scope", "unsupported_read", "invalid_upstream_response"):
            return _P2TerminalFailure(
                c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                "P2 capability unavailable: this query cannot be represented safely.",
            )
        cause = {
            "upstream_timeout": "postgrest_timeout",
            "upstream_unavailable": "postgrest_unavailable",
            "upstream_failure": "postgrest_failure",
            "rate_limited": "postgrest_rate_limited",
            "response_too_large": "postgrest_response_too_large",
            "read_limit_exceeded": "postgrest_budget_exceeded",
        }.get(error.code, "postgrest_failure")
        return _P2DependencyPause(
            c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, f"P2 dependency unavailable: {cause}.",
        )


def _provider_failure(error: BaseException) -> tuple[c.ApiErrorCode, str]:
    code = getattr(error, "code", None)
    if isinstance(code, LMStudioProviderErrorCode):
        if code in (LMStudioProviderErrorCode.OFFLINE, LMStudioProviderErrorCode.TIMEOUT):
            cause = "lmstudio_offline" if code == LMStudioProviderErrorCode.OFFLINE else "lmstudio_timeout"
            return c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, f"P2 dependency unavailable: {cause}."
        if code == LMStudioProviderErrorCode.HTTP_BUSY:
            return c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: lmstudio_busy."
        return c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: lmstudio_failed."
    if isinstance(error, _ModelTimeout) or isinstance(error, TimeoutError):
        return c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: lmstudio_timeout."
    return c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: lmstudio_failed."


def _closed_error(
    code: c.ApiErrorCode, message: str, retryable: bool,
) -> tuple[c.ApiErrorCode, str, bool]:
    allowed = {
        (c.ApiErrorCode.UNAUTHENTICATED, "P2 dependency unavailable: auth_rejected.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: auth_verifier_unavailable.", True),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: postgrest_timeout.", True),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: postgrest_unavailable.", True),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: postgrest_failure.", True),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: postgrest_rate_limited.", True),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: postgrest_response_too_large.", True),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: postgrest_budget_exceeded.", True),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: lmstudio_offline.", True),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: lmstudio_timeout.", True),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: lmstudio_busy.", True),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: lmstudio_failed.", True),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 dependency unavailable: internal_failure.", True),
        (c.ApiErrorCode.AGENT_DISABLED, "P2 agent planning is disabled.", False),
        (c.ApiErrorCode.RATE_LIMITED, "P2 planning generation budget reached.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 query incomplete: narrow the query and submit a new Turn.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 result reference capacity reached; submit a narrower new Turn.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 binding capacity reached; submit a narrower new Turn.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 activity changed during scope resolution. Submit a new Turn to refresh the query.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 read contains a refund or non-positive amount that v1 cannot safely represent.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 read contains a non-positive debt amount that v1 cannot safely represent.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 financial records changed. Submit a new Turn to refresh the query.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 activity scope could not be verified. No data was disclosed.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 capability unavailable: this query cannot be represented safely.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 result freshness binding is unavailable. Submit a new Turn to refresh the query.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "P2 results contain conflicting activity versions. Submit a new Turn to refresh the query.", False),
        (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, "当前 Turn 已绑定到不同活动范围。请从所需活动页面创建新 Turn 后重试。", False),
    }
    if (code, message, retryable) not in allowed:
        return (c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                "P2 dependency unavailable: internal_failure.", True)
    return code, message, retryable


def _safe_internal_error(error: BaseException) -> str:
    if isinstance(error, _P2TerminalFailure):
        return error.message
    return "P2 dependency unavailable: internal_failure."


def _money(value: Decimal) -> str:
    return format(value, "f")


def _fingerprint(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

