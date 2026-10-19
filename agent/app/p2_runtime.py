"""P2 real-provider/read-only runtime layered on the durable v1 Turn scheduler."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import secrets
import time
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

from pydantic import ValidationError

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
    LMStudioProviderErrorCode, LMStudioTransportObservation,
)
from .p2_token_budget import P2TokenBudgetMeasurement
from .p2_read_contracts_v3 import P2_V3_CANDIDATE_PROFILE_ID
from . import p2_event_contracts_v3 as pe3
from . import p2_read_contracts_v3 as pc3
from . import p2_source_codec_v3 as codec3
from .p2_read_backend import MAX_PAGES_PER_QUERY, P2ReadBackendAdapter
from .p2_read_prompt_v3 import P2V3PromptBuildConfig, build_p2_v3_request
from .p2_read_provider_v3 import P2V3ReadProvider
from .p2_source_store_v3 import (
    P2V3StoreConflict, P2V3StoreNotFound, P2V3UnsupportedProfile,
    P2_V3_MAX_ACTIVE_US,
)
from .p2_v3_runtime_policy import P2V3IntentPlan, classify_p2_v3_input
from .p2_v3_sent_guard import validate_sent_p2_v3_decision
from .p2_v3_store_ports import P2V3StoreBudgetPort
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
_ACTIVE_CANDIDATE_PROFILE: ContextVar[str | None] = ContextVar(
    "p2_active_candidate_profile", default=None,
)

# One v3 read is projected as a bounded chain of model pages: page zero, then
# one continuation page per model-authored continuation decision, then the
# answer. Each page therefore costs exactly one model call, which is what ties
# the page count to the Turn-wide model budget:
#
#     model_calls(pages) = _V3_QUERY_SELECTION_MODEL_CALLS
#                        + (pages - 1) * _V3_CONTINUATION_MODEL_CALLS
#                        + _V3_ANSWER_MODEL_CALLS
#
# The selection and answer calls are also what a *single*-page read spends, so
# _V3_MIN_PAGED_READ_MODEL_CALLS is the reservation a planned read already
# takes: the smallest read that can continue at all (selection, one
# continuation decision, answer). That reservation is a floor; the Store still
# charges and enforces every individual call.
_V3_QUERY_SELECTION_MODEL_CALLS = 1
_V3_CONTINUATION_MODEL_CALLS = 1
_V3_ANSWER_MODEL_CALLS = 1
_V3_MIN_PAGED_READ_MODEL_CALLS = (
    _V3_QUERY_SELECTION_MODEL_CALLS
    + _V3_CONTINUATION_MODEL_CALLS
    + _V3_ANSWER_MODEL_CALLS
)
_V3_PLANNED_READ_CALLS = 1


def _v3_read_page_window(max_model_calls: int) -> int:
    """Bounded number of model pages one v3 read may project.

    Every page after the first is a model decision, so the model budget alone
    would allow ``max_model_calls - 1`` pages. Two stricter bounds already
    exist and are never widened here: the read backend projects at most
    ``MAX_PAGES_PER_QUERY`` pages of one logical query, and the strict source
    codec caps one query's projection at
    ``MAX_FACTS_PER_QUERY // MAX_FACTS_PER_PAGE`` pages -- the manifest's
    ``rows_per_table`` / ``get_rows_per_page`` arithmetic. The window is the
    minimum of those existing bounds, never a new budget, and it is clamped to
    at least one page so a single-page read stays representable.
    """
    affordable_pages = (
        max_model_calls - _V3_QUERY_SELECTION_MODEL_CALLS - _V3_ANSWER_MODEL_CALLS
    ) // _V3_CONTINUATION_MODEL_CALLS + 1
    projection_pages = codec3.MAX_FACTS_PER_QUERY // codec3.MAX_FACTS_PER_PAGE
    return max(1, min(affordable_pages, MAX_PAGES_PER_QUERY, projection_pages))


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


# Client-visible capability declines that are NOT retryable. Both strings are
# already in the closed allowlist of `_closed_error`, so classifying with them
# needs no contract, error-code or allowlist change: a result that cannot be
# represented is a capability limit, and retrying the identical Turn cannot
# succeed. Before this, both cases fell through `_safe_internal_error` into
# "P2 dependency unavailable: internal_failure." with retryable=true, which told
# clients to retry work that can never succeed.
_V3_RESULT_NOT_REPRESENTABLE = "P2 capability unavailable: this query cannot be represented safely."
_V3_RESULT_CAPACITY_REACHED = "P2 result reference capacity reached; submit a narrower new Turn."

# The Store rejects a projection that exceeds its one-continuation page or fact
# bound with these exact conflict messages. They describe the same capability
# limit as _V3_RESULT_CAPACITY_REACHED, and the Store exposes no structured code
# for them, so the classification is keyed on these strings.
_V3_STORE_CAPACITY_CONFLICTS = frozenset({
    "scoped fact projection exceeds the one-continuation source bound",
    "scoped fact projection exceeds the one-continuation page bound",
})


class _NoBusinessScopeAuthorizer:
    """Legacy Runtime slot; P2 scope checks go only through its trusted backend."""

    def authorize(self, *_: Any, **__: Any) -> None:
        raise CapabilityUnavailable("P2 never delegates activity scope to the legacy adapter")


class P2Runtime(MockRuntime):
    """Reuse the v1 bounded CAS scheduler; replace every mock business capability."""

    _SAFE_GENERIC_TEXT = "我可以帮助查询已验证的活动、消费和欠款信息。"
    _SAFE_PROPOSAL_TEXT = "已识别你的操作意图；当前候选仅可识别提议，不会预览、确认或写入。"
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
        v3_provider: P2V3ReadProvider | None = None,
        v3_prompt_config: P2V3PromptBuildConfig | None = None,
        v3_backend_config: Any | None = None,
        enabled_candidate_profile_ids: Sequence[str] | None = None,
    ) -> None:
        if (
            not isinstance(model_timeout_seconds, (int, float))
            or isinstance(model_timeout_seconds, bool)
            or not math.isfinite(float(model_timeout_seconds))
            or not 0.1 <= float(model_timeout_seconds) <= 240.0
        ):
            raise ValueError("P2 model timeout must be finite and between 0.1 and 240 seconds")
        # The inherited scheduler only claims/renews Turns and supplies CAS helpers;
        # P2 overrides all model, identity, read, error, and finalization paths.
        super().__init__(
            store, provider, backend, auth_verifier, _NoBusinessScopeAuthorizer(), agent_control,
            task_concurrency=1, model_timeout_seconds=model_timeout_seconds,
            shutdown_timeout_seconds=shutdown_timeout_seconds,
            enabled_candidate_profile_ids=enabled_candidate_profile_ids,
        )
        # MockRuntime clamps the P1 timeout to ten seconds. Restore the separately
        # configured P2 deadline so it can outlast the provider's HTTP timeout.
        self._model_timeout = float(model_timeout_seconds)
        self._p2_provider = provider
        self._p2_backend = backend
        if len({v3_provider is None, v3_prompt_config is None, v3_backend_config is None}) != 1:
            raise ValueError("v3 provider, prompt config, and backend config must be enabled together")
        self._p2_v3_provider = v3_provider
        self._p2_v3_prompt_config = v3_prompt_config
        self._p2_v3_backend_config = v3_backend_config
        # Without an enabled provider no candidate Turn may be claimed as ready.
        self._p2_v3_ready = False
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
            if self._p2_v3_provider is not None:
                try:
                    await self._p2_v3_provider.prepare()
                    self._p2_v3_ready = True
                except Exception:
                    # Candidate preparation is bounded and opt-in. A local
                    # counter/session failure must not prevent the canonical
                    # P1 service from starting; candidate Turns remain gated.
                    self._p2_v3_ready = False
            await super().start()
        except BaseException:
            self._journal.close()
            raise

    async def close(self) -> None:
        await super().close()
        self._turn_grants.clear()
        self._p2_states.clear()
        self._journal.close()

    async def _start_claimed_turn(self, claimed: ClaimedTurn) -> ClaimedTurn:
        # Candidate-pinned Turns require the same server-selected profile on
        # the initial QUEUED -> RUNNING CAS. Keep the canonical/P1 transition
        # path unchanged.
        if claimed.execution_profile_id != P2_V3_CANDIDATE_PROFILE_ID:
            return await super()._start_claimed_turn(claimed)
        aggregate = claimed.turn
        before = aggregate.record.turn
        resume_step = aggregate.checkpoint.resume_step or c.TurnStep.BUILD_CONTEXT
        after = c.TurnStateSnapshot.model_validate(
            before.model_dump(mode="python", by_alias=True, exclude_none=False)
            | {"state": c.TurnState.RUNNING, "step": resume_step,
               "state_revision": before.state_revision + 1, "wait_reason": None,
               "resume_state": None}
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
            candidate_profile_id=P2_V3_CANDIDATE_PROFILE_ID,
        )
        return ClaimedTurn(
            turn=result,
            claim_token=claimed.claim_token,
            claim_until=claimed.claim_until,
            execution_profile_id=claimed.execution_profile_id,
        )

    async def _run_claim(
        self, claimed: ClaimedTurn, *, auth_resume_state: c.ResumeState = c.ResumeState.RUNNING,
    ) -> None:
        turn_id = claimed.turn.record.turn.turn_id
        token = _ACTIVE_TURN.set(turn_id)
        profile_token = _ACTIVE_CANDIDATE_PROFILE.set(
            claimed.execution_profile_id
            if claimed.execution_profile_id == P2_V3_CANDIDATE_PROFILE_ID else None
        )
        renewer = asyncio.create_task(self._renew_loop(turn_id, claimed.claim_token))
        try:
            await self._await_turn_grant(claimed.turn.record.turn.owner_user_id, turn_id)
            await self._run_planning(claimed)
        except LMStudioProviderCancelled as exc:
            # The provider raises this subclass after its owned worker has
            # drained. It is a provider dependency failure, not cancellation
            # of this Runtime task; persist WAIT_INPUT so RUNNING is not
            # reclaimed and sent again with the same model context.
            code, message = _provider_failure(exc)
            owner_id = claimed.turn.record.turn.owner_user_id
            self._turn_grants.revoke(owner_id, turn_id)
            self._p2_states.pop(turn_id, None)
            await self._pause_for_auth(
                claimed, resume_state=auth_resume_state, code=code, message=message,
            )
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
        except (LMStudioProviderError, _ModelTimeout, TimeoutError) as exc:
            code, message = _provider_failure(exc)
            owner_id = claimed.turn.record.turn.owner_user_id
            self._turn_grants.revoke(owner_id, turn_id)
            self._p2_states.pop(turn_id, None)
            await self._pause_for_auth(claimed, resume_state=auth_resume_state,
                                       code=code, message=message)
        except (ModelOutputError, CapabilityUnavailable) as exc:
            await self._terminal_error(claimed, c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                                       _safe_internal_error(exc), retryable=False)
        except P2V3StoreConflict as exc:
            # The Store's projection capacity bounds are capability limits of the
            # bounded read, so the client is told to narrow the query rather than
            # to retry an identical Turn that cannot succeed. Any other conflict
            # keeps the sanitized internal classification.
            if str(exc) in _V3_STORE_CAPACITY_CONFLICTS:
                await self._terminal_error(claimed, c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                                           _V3_RESULT_CAPACITY_REACHED, retryable=False)
            else:
                await self._terminal_error(claimed, c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                                           "P2 dependency unavailable: internal_failure.", retryable=True)
        except Exception:
            await self._terminal_error(claimed, c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                                       "P2 dependency unavailable: internal_failure.", retryable=True)
        finally:
            renewer.cancel()
            await asyncio.wait({renewer}, timeout=0.2)
            # Cleanup and reconciliation must survive cancellation. Awaiting
            # them inline lets a propagating CancelledError skip the claim
            # release, which leaves the Turn RUNNING with a held claim, no
            # durable event and no owner. Running them as their own task keeps
            # the durable work alive, and the second bounded wait gives it a
            # chance to land before the cancellation propagates.
            finalize = asyncio.create_task(
                self._finalize_claim(claimed, auth_resume_state=auth_resume_state),
            )
            try:
                await asyncio.wait({finalize}, timeout=self._shutdown_timeout)
            except asyncio.CancelledError:
                await asyncio.wait({finalize}, timeout=self._shutdown_timeout)
                raise
            _ACTIVE_CANDIDATE_PROFILE.reset(profile_token)
            _ACTIVE_TURN.reset(token)

    async def _finalize_claim(
        self, claimed: ClaimedTurn, *, auth_resume_state: c.ResumeState,
    ) -> None:
        """Leave the Turn durable after planning returns, whatever the reason.

        Releasing the claim alone is not enough. A planning path can exit
        without a terminal or paused transition -- a swallowed
        StateConflict/StoreNotFound, or a task whose cancellation skipped the
        handler chain -- and the Turn would then stay RUNNING with no event and
        no owner. Reconcile first, while the claim is still held, because the
        pause transition CASes on ``claimed.claim_token``; only then release it.
        """
        owner_id = claimed.turn.record.turn.owner_user_id
        turn_id = claimed.turn.record.turn.turn_id
        try:
            final = await asyncio.to_thread(self._store.get_turn, owner_id, turn_id)
            state = final.record.turn.state
            if state == c.TurnState.RUNNING:
                # No classified outcome was persisted for this claim. Pause with
                # the same dependency pause the provider-cancellation path uses,
                # so the Turn is resumable instead of orphaned.
                self._turn_grants.revoke(owner_id, turn_id)
                self._p2_states.pop(turn_id, None)
                await self._pause_for_auth(
                    claimed, resume_state=auth_resume_state,
                    code=c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                    message="P2 dependency unavailable: internal_failure.",
                )
            elif state in (c.TurnState.COMPLETED, c.TurnState.FAILED, c.TurnState.CANCELLED):
                self._p2_states.pop(turn_id, None)
                self._turn_grants.revoke(owner_id, turn_id)
            elif state == c.TurnState.WAIT_INPUT:
                self._p2_states.pop(turn_id, None)
        except Exception:
            self._p2_states.pop(turn_id, None)
        try:
            await asyncio.to_thread(self._store.release_claim, turn_id, claimed.claim_token)
        except Exception:
            pass

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
        if claimed.execution_profile_id == P2_V3_CANDIDATE_PROFILE_ID:
            await self._run_v3_planning(claimed)
            return
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

    async def _generate_v3_model(
        self,
        *,
        owner_id: uuid.UUID,
        turn_id: uuid.UUID,
        claim_token: str,
        public: pc3.P2ModelContext,
        private: pc3.P2IntentContext,
        prepared: Any,
    ) -> str:
        """Dispatch one v3 model request under a durable Turn-wide call slot.

        The facade invokes ``before_dispatch`` only after its exact body and
        token measurement pass validation.  That callback is the irreversible
        boundary recorded by Store; a counter/config failure settles as a
        known no-dispatch and a lost transport result consumes the slot as
        unknown.
        """
        if self._p2_v3_provider is None:
            raise CapabilityUnavailable("v3 model provider is unavailable")
        snapshot = await asyncio.to_thread(
            self._store.get_p2_v3_snapshot, owner_id, turn_id,
        )
        if snapshot.model_calls + snapshot.model_reserved_calls >= self._max_model_calls:
            raise _CallBudgetReached()
        active_limit_us = min(
            P2_V3_MAX_ACTIVE_US,
            max(1, int(self._model_timeout * 1_000_000)),
        )
        try:
            reservation_id = await asyncio.to_thread(
                self._store.reserve_p2_v3_stage,
                owner_id,
                turn_id,
                claim_token=claim_token,
                stage="model",
                active_limit_us=active_limit_us,
            )
        except P2V3StoreConflict:
            # Store applies the same hard candidate cap and Turn-wide active
            # budget atomically. Either exhausted bound prevents dispatch.
            raise _CallBudgetReached() from None

        call_started_ns = time.monotonic_ns()
        dispatch_attempted = False
        settled = False
        budget_exhausted_at_dispatch = False

        def before_dispatch(
            actual_body_sha256: str,
            measurement: P2TokenBudgetMeasurement,
        ) -> None:
            nonlocal dispatch_attempted, budget_exhausted_at_dispatch
            if (
                type(actual_body_sha256) is not str
                or len(actual_body_sha256) != 64
                or not isinstance(measurement, P2TokenBudgetMeasurement)
                or measurement.model_key != self._p2_v3_prompt_config.model_id
            ):
                raise ValueError("v3 dispatch metadata does not match its server binding")
            current = self._store.get_p2_v3_snapshot(owner_id, turn_id)
            if current.model_calls + current.model_reserved_calls > self._max_model_calls:
                budget_exhausted_at_dispatch = True
                raise ValueError("v3 model-call budget is exhausted")
            measurement_fields = {
                "model_key": measurement.model_key,
                "api_host": measurement.api_host,
                "artifact_path": measurement.artifact_path,
                "artifact_sha256": measurement.artifact_sha256,
                "actual_context_tokens": measurement.actual_context_tokens,
                "prompt_tokens": measurement.prompt_tokens,
                "response_format_tokens": measurement.response_format_tokens,
                "safety_margin_tokens": measurement.safety_margin_tokens,
                "budgeted_input_tokens": measurement.budgeted_input_tokens,
                "max_input_tokens": measurement.max_input_tokens,
                "requested_output_tokens": measurement.requested_output_tokens,
                "max_output_tokens": measurement.max_output_tokens,
                "method": measurement.method,
                "artifact_hash_ms": measurement.artifact_hash_ms,
                "total_measurement_ms": measurement.total_measurement_ms,
            }
            measurement_sha256 = hashlib.sha256(json.dumps(
                measurement_fields, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False,
            ).encode("utf-8")).hexdigest()
            # If the commit response is lost, cleanup probes the append-only
            # marker before deciding whether release is still safe.
            dispatch_attempted = True
            self._store.mark_p2_v3_dispatch_started(
                owner_id,
                turn_id,
                reservation_id,
                claim_token=claim_token,
                prepared_request_sha256=actual_body_sha256,
                selected_model_key=measurement.model_key,
                validated_measurement_sha256=measurement_sha256,
            )

        def on_transport_result(observation: LMStudioTransportObservation) -> None:
            nonlocal settled
            if not isinstance(observation, LMStudioTransportObservation):
                raise ValueError("v3 transport observation is invalid")
            actual_active_us = max(0, (time.monotonic_ns() - call_started_ns) // 1_000)
            self._store.settle_p2_v3_stage(
                owner_id,
                turn_id,
                reservation_id,
                outcome="actual",
                actual_active_us=actual_active_us,
                actual_backend_us=0,
                actual_response_bytes=0,
            )
            settled = True

        async def settle_unfinished() -> None:
            nonlocal settled
            if settled:
                return
            actual_active_us = max(0, (time.monotonic_ns() - call_started_ns) // 1_000)

            def settle() -> None:
                nonlocal settled
                if dispatch_attempted:
                    try:
                        self._store.settle_p2_v3_stage(
                            owner_id, turn_id, reservation_id, outcome="unknown",
                        )
                        settled = True
                        return
                    except P2V3StoreConflict:
                        # A marker failure may have happened before its
                        # transaction committed. Only release when Store
                        # confirms that no irreversible marker exists.
                        with self._store._connection() as connection:
                            marker = connection.execute(
                                "SELECT 1 FROM p2_v3_charge_events WHERE reservation_id=? AND event_kind='dispatch_started'",
                                (reservation_id,),
                            ).fetchone()
                            terminal = connection.execute(
                                "SELECT 1 FROM p2_v3_charge_events WHERE reservation_id=? AND event_kind IN ('settled','known_no_dispatch','unknown')",
                                (reservation_id,),
                            ).fetchone()
                        if marker is not None or terminal is not None:
                            settled = terminal is not None
                            return
                self._store.settle_p2_v3_stage(
                    owner_id,
                    turn_id,
                    reservation_id,
                    outcome="known_no_dispatch",
                    actual_active_us=actual_active_us,
                    actual_backend_us=0,
                    actual_response_bytes=0,
                )
                settled = True

            await asyncio.to_thread(settle)

        try:
            result = await asyncio.wait_for(
                self._p2_v3_provider.generate(
                    public,
                    private,
                    prepared,
                    before_dispatch=before_dispatch,
                    on_transport_result=on_transport_result,
                ),
                timeout=self._model_timeout,
            )
        except asyncio.TimeoutError:
            await settle_unfinished()
            raise _ModelTimeout() from None
        except BaseException:
            await settle_unfinished()
            if budget_exhausted_at_dispatch:
                raise _CallBudgetReached() from None
            raise
        if budget_exhausted_at_dispatch:
            raise _CallBudgetReached()
        if not settled:
            await settle_unfinished()
            raise CapabilityUnavailable("v3 provider returned without a settled transport dispatch")
        return result

    async def _run_v3_planning(self, claimed: ClaimedTurn) -> None:
        """Run the first bounded v3 vertical slice on the existing Turn worker.

        This slice deliberately supports only an unscoped Activity discovery
        read. It uses the same Store, claim, Auth verifier, provider transport,
        and scheduler as the existing P2 runtime. Other source operations fail
        closed until their Store accept/issue paths are available.
        """
        if (
            self._p2_v3_provider is None or self._p2_v3_prompt_config is None
            or self._p2_v3_backend_config is None or not self._p2_v3_ready
        ):
            raise _P2DependencyPause(
                c.ApiErrorCode.DEPENDENCY_UNAVAILABLE,
                "P2 v3 candidate is not ready.",
            )

        turn_id = claimed.turn.record.turn.turn_id
        owner_id = claimed.turn.record.turn.owner_user_id
        aggregate = await asyncio.to_thread(self._store.get_turn, owner_id, turn_id)
        if aggregate.record.turn.execution is not None or aggregate.record.turn.state != c.TurnState.RUNNING:
            return
        if claimed.execution_profile_id != P2_V3_CANDIDATE_PROFILE_ID:
            raise CapabilityUnavailable("v3 planning requires an explicit candidate Turn pin")

        gate = await self._current_gate()
        input_text = self._latest_turn_input(aggregate)
        ui = aggregate.record.ui_context_snapshot
        activity_hint = ui.activity_id if ui is not None else None
        ledger_unit_hint = ui.ledger_unit_id if ui is not None else None
        if ui is not None and ui.selected_entity is not None:
            if ui.selected_entity.entity_type is c.UiEntityType.ACTIVITY:
                activity_hint = ui.selected_entity.entity_id
            elif ui.selected_entity.entity_type is c.UiEntityType.LEDGER_UNIT:
                ledger_unit_hint = ui.selected_entity.entity_id
        # Hints only decide whether to attempt the bounded metadata admission.
        # The read allowlist is recomputed from an actually accepted projection.
        plan = classify_p2_v3_input(input_text, scope_verified=activity_hint is not None)
        metadata_activity_hint = activity_hint if plan.classification == "factual_business" else None
        if metadata_activity_hint is None:
            ledger_unit_hint = None
        planned_read = "read" in plan.allowed_decision_kinds
        reserved_model_calls = (
            _V3_MIN_PAGED_READ_MODEL_CALLS if planned_read
            else _V3_QUERY_SELECTION_MODEL_CALLS
        )
        reserved_read_calls = _V3_PLANNED_READ_CALLS if planned_read else 0

        # A query created for this exact generation/input is a durable planning
        # checkpoint. Validate it before reserving another planning sequence so
        # recovery neither spends the model allowance again nor asks the model
        # to select a different query. The Store returns None only when no query
        # exists for this input; descriptor/pin corruption fails closed.
        resume_query = await asyncio.to_thread(
            self._store.get_p2_v3_resume_query_descriptor,
            owner_id, turn_id, claim_token=claimed.claim_token,
        )
        if resume_query is not None:
            dispatched = await asyncio.to_thread(
                self._store.get_p2_v3_snapshot, owner_id, turn_id,
            )
            if dispatched.model_calls + dispatched.model_reserved_calls >= self._max_model_calls:
                raise _CallBudgetReached()

        # Reserve the bounded read/optional-continuation/answer call sequence
        # before admission so every later source identity sees one stable
        # context revision. Non-read semantic branches reserve just one call.
        if resume_query is None:
            if (aggregate.checkpoint.model_calls + reserved_model_calls > self._max_model_calls
                    or aggregate.checkpoint.read_calls + reserved_read_calls > self._max_read_calls):
                raise _CallBudgetReached()
            charged_checkpoint = aggregate.checkpoint.model_copy(update={
                "model_calls": aggregate.checkpoint.model_calls + reserved_model_calls,
                "read_calls": aggregate.checkpoint.read_calls + reserved_read_calls,
                "model_context": None,
                "last_decision": None,
                "last_clarification": None,
                "resume_step": c.TurnStep.MODEL_DECISION,
            })
            aggregate = await self._save_checkpoint(aggregate, charged_checkpoint, claimed.claim_token)

        principal = await self._fresh_identity(
            owner_id, {metadata_activity_hint} if metadata_activity_hint is not None else set(),
            gate_revision=gate.disable_revision,
        )
        active_grant = self._active_grant(owner_id, turn_id)
        ui_hint = None
        if ui is not None:
            # The source Store retains only bounded entity locators as the
            # private UI hint digest. Page metadata, filters, timestamps, and
            # client version remain in the canonical v1 UI snapshot.
            ui_hint = {
                key: str(value)
                for key, value in (
                    ("activity_id", ui.activity_id),
                    ("ledger_unit_id", ui.ledger_unit_id),
                )
                if value is not None
            }
            selected_hint_key = {
                c.UiEntityType.ACTIVITY: "activity_id",
                c.UiEntityType.LEDGER_UNIT: "ledger_unit_id",
                c.UiEntityType.EXPENSE: "expense_id",
                c.UiEntityType.PARTICIPANT: "participant_id",
            }.get(ui.selected_entity.entity_type) if ui.selected_entity is not None else None
            if selected_hint_key is not None:
                ui_hint[selected_hint_key] = str(ui.selected_entity.entity_id)
            if not ui_hint:
                ui_hint = None
        admission, public_scope = await asyncio.to_thread(
            self._store.create_p2_v3_request_admission,
            owner_id,
            turn_id,
            claim_token=claimed.claim_token,
            principal_user_id=principal.user_id,
            activity_id_hint=metadata_activity_hint,
            ledger_unit_id_hint=ledger_unit_hint,
            ui_hint=ui_hint,
        )
        identity = admission.identity
        registry = admission.reference_registry
        verified = self._make_verified_context(owner_id, turn_id, active_grant, aggregate.record.bound_references)
        adapter = P2ReadBackendAdapter(
            self._p2_v3_backend_config,
            transport=getattr(self._p2_backend, "_transport", None),
            v3_budget_port=P2V3StoreBudgetPort(
                self._store, owner_id, turn_id, claimed.claim_token,
            ),
            v3_locator_port=registry,
        )
        projection = None
        if metadata_activity_hint is not None:
            try:
                projection = await adapter.admit_scope_v3(
                    verified, admission, ui_activity_id_hint=metadata_activity_hint,
                    ui_ledger_unit_id_hint=ledger_unit_hint,
                )
            except Exception as exc:
                if isinstance(exc, BackendReadError):
                    raise self._backend_pause(exc) from None
                if hasattr(exc, "code") and isinstance(getattr(exc, "code"), str):
                    try:
                        raise self._backend_pause(BackendReadError(getattr(exc, "code"))) from None
                    except ValueError:
                        pass
                raise
            if projection is None:
                raise CapabilityUnavailable("UI scope hint did not produce an accepted source metadata projection")
        elif public_scope is not None:
            raise CapabilityUnavailable("unresolved UI hints cannot be treated as an authorized scope")

        scope = None
        source_labels: tuple[pc3.P2EntityDisplayLabel, ...] = ()
        current_actor = None
        scope_receipt_ref = None
        if projection is not None:
            snapshot = projection.snapshot
            scope = pc3.P2Scope(
                scope_kind=snapshot.scope_kind,
                scope_ref=snapshot.scope_ref,
                activity_ref=snapshot.activity_ref,
                ledger_unit_ref=snapshot.scope_ref if snapshot.scope_kind == "ledger_unit" else None,
            )
            if public_scope is not None and public_scope != scope:
                raise CapabilityUnavailable("accepted metadata scope differs from the admission hint binding")
            source_labels = tuple(projection.source_labels)
            current_actor = projection.current_actor
            if not source_labels:
                raise CapabilityUnavailable("accepted scope metadata lacks an Activity source receipt")
            scope_receipt_ref = "auth_" + secrets.token_urlsafe(24)

        plan = classify_p2_v3_input(input_text, scope_verified=scope is not None)
        private = self._v3_intent_context(plan, admission, scope=scope)
        public = self._v3_model_context(
            plan, input_text, identity, scope=scope,
            scope_authorization_receipt_ref=scope_receipt_ref,
            current_actor=current_actor, source_labels=source_labels,
        )
        pc3.validate_p2_clarification_projection(public, private)
        raw: str | None = None
        if resume_query is not None:
            # The Store checked this descriptor against the exact current input
            # and immutable cohort. Rebuild only the strict typed request; never
            # call the model to choose new criteria or scope during recovery.
            try:
                raw_descriptor = json.dumps({
                    "kind": "read",
                    "message_type": "query_request",
                    "profile_id": pc3.P2_V3_CANDIDATE_PROFILE_ID,
                    "versions": pc3.P2_V3_VERSIONS.model_dump(mode="json"),
                    "operation": resume_query.operation,
                    "criteria": json.loads(resume_query.criteria_json),
                    "scope": json.loads(resume_query.scope_json),
                }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                shaped = pc3.P2ReadQueryRequest.model_validate_json(raw_descriptor, strict=True)
            except Exception:
                raise CapabilityUnavailable("stored v3 query cannot be restored as a strict request") from None
        else:
            prepared = build_p2_v3_request(public, private, config=self._p2_v3_prompt_config)
            async with self._model_gate:
                raw = await self._generate_v3_model(
                    owner_id=owner_id, turn_id=turn_id, claim_token=claimed.claim_token,
                    public=public, private=private, prepared=prepared,
                )
            if type(raw) is not str:
                raise ModelOutputError("v3 provider response must be text")

            # No grant exists before the model selects an operation. The sent guard
            # checks the exact prepared public guard and allows this metadata-only
            # first read shape. Auth/scope authorization and the operation-specific
            # grant are minted only after that selection.
            shaped = validate_sent_p2_v3_decision(prepared, public, private, raw)
            if not isinstance(shaped, pc3.P2ReadQueryRequest):
                decision = pc3.parse_p2_decision(raw, private)
                if isinstance(decision, pc3.P2AnswerDecision):
                    if plan.classification != "non_business" or decision.basis != "non_business_general":
                        raise CapabilityUnavailable("source-free v3 answers require server-classified non-business input")
                    await self._complete_v3_plain_message(
                        aggregate, claimed.claim_token, decision.text, gate.disable_revision,
                        non_business_decision=decision,
                    )
                    return
                if isinstance(decision, pc3.P2ClarifyDecision):
                    await self._wait_for_v3_clarification(
                        aggregate, claimed.claim_token, decision, plan, gate.disable_revision,
                    )
                    return
                if isinstance(decision, pc3.P2ProposalRecognition):
                    if (
                        plan.classification != "proposal_intent"
                        or decision.operation not in plan.allowed_proposal_operations
                    ):
                        raise CapabilityUnavailable("proposal recognition is outside the server allowlist")
                    await self._complete_v3_plain_message(
                        aggregate, claimed.claim_token, self._SAFE_PROPOSAL_TEXT, gate.disable_revision,
                    )
                    return
                raise CapabilityUnavailable("v3 decision kind is not enabled in this Turn context")
        if (
            plan.classification != "factual_business"
            or shaped.operation not in plan.allowed_read_operations
            or (shaped.operation != pc3.P2ReadOperation.ACTIVITIES and scope is None)
            or (
                shaped.operation != pc3.P2ReadOperation.ACTIVITIES
                and shaped.scope != scope
            )
            or (
                shaped.operation == pc3.P2ReadOperation.ACTIVITIES
                and shaped.scope not in (None, scope)
            )
        ):
            raise CapabilityUnavailable("typed v3 query is outside the current server operation/scope allowlist")

        # Re-verify Auth and create a fresh operation-specific grant against the
        # newly admitted request. Restored queries use this same fresh grant.
        scoped_activity_ids = {projection.snapshot.activity_id} if projection is not None else set()
        principal = await self._fresh_identity(owner_id, scoped_activity_ids, gate_revision=gate.disable_revision)
        active_grant = self._active_grant(owner_id, turn_id)
        expires_at = min(
            datetime.now(timezone.utc) + timedelta(minutes=2),
            active_grant.expires_at,
            principal.expires_at,
        )
        if expires_at <= datetime.now(timezone.utc):
            raise _AuthRequired()
        grant = pc3.P2SourceAuthorizationGrant(
            principal_ref=registry.principal_ref(),
            owner_turn_ref=registry.owner_turn_ref(identity=identity),
            generation=identity.generation,
            source_input_seq=identity.input_seq,
            input_digest=identity.input_digest,
            operation=shaped.operation,
            scope=shaped.scope,
            criteria_digest=pc3.p2_criteria_digest(shaped.criteria),
            expires_at=expires_at,
            grant_ref="ref_" + secrets.token_urlsafe(24),
        )
        trusted_private = private.model_copy(update={"source_authorization_grant": grant})
        decision_payload: Any = (
            shaped.model_dump(mode="json", by_alias=True, exclude_none=False)
            if resume_query is not None else raw
        )
        decision = pc3.parse_p2_decision(decision_payload, trusted_private)
        if not isinstance(decision, pc3.P2ReadQueryRequest):
            raise ModelOutputError("v3 model decision changed after its trusted grant was issued")

        if resume_query is not None:
            private_selection_refs = resume_query.private_selection_refs
        else:
            private_selection_refs: tuple[str, ...] = ()
            if (
                decision.operation is pc3.P2ReadOperation.EXPENSES
                and projection is not None
                and ui is not None
                and ui.selected_entity is not None
                and ui.selected_entity.entity_type is c.UiEntityType.EXPENSE
            ):
                private_selection_refs = (registry.bind_entity(
                    "expense", ui.selected_entity.entity_id,
                    activity_id=projection.snapshot.activity_id,
                ),)

        snapshot = await asyncio.to_thread(self._store.get_p2_v3_snapshot, owner_id, turn_id)
        logical_query_id = await asyncio.to_thread(
            self._store.create_p2_v3_logical_query,
            owner_id,
            turn_id,
            claim_token=claimed.claim_token,
            admission_id=admission.admission_id,
            operation=decision.operation.value,
            criteria=decision.criteria,
            scope=decision.scope,
            expected_revision=snapshot.revision,
            private_selection_refs=private_selection_refs,
            logical_query_id=resume_query.logical_query_id if resume_query is not None else None,
        )
        await asyncio.to_thread(
            self._store.bind_p2_v3_query_descriptor,
            owner_id,
            turn_id,
            claim_token=claimed.claim_token,
            admission=admission,
            request=decision,
            logical_query_id=logical_query_id,
            private_selection_refs=private_selection_refs,
        )
        attempt_id, _attempt_seq = await asyncio.to_thread(
            self._store.begin_p2_v3_query_attempt,
            owner_id,
            turn_id,
            claim_token=claimed.claim_token,
            logical_query_id=logical_query_id,
            admission_id=admission.admission_id,
            page_index=0,
        )
        query_binding = codec3.QueryAttemptBinding(
            identity=identity,
            logical_query_id=logical_query_id,
            query_attempt_id=attempt_id,
            page_index=0,
            claim_token=claimed.claim_token,
        )
        verified = self._make_verified_context(owner_id, turn_id, active_grant, aggregate.record.bound_references)
        try:
            pending = await adapter.read_candidate_v3(
                decision,
                verified,
                grant,
                admission=admission,
                admission_projection=projection,
                query_binding=query_binding,
                context_version=str(aggregate.record.turn.context_version),
            )
            accepted = await asyncio.to_thread(
                self._store.accept_p2_v3_query_attempt,
                owner_id,
                turn_id,
                claim_token=claimed.claim_token,
                principal_user_id=principal.user_id,
                pending=pending,
            )
            live_result = await asyncio.to_thread(
                self._store.issue_p2_v3_page,
                owner_id,
                turn_id,
                claim_token=claimed.claim_token,
                accepted_page=accepted,
            )
        except BackendReadError as exc:
            raise self._backend_pause(exc) from None
        except Exception as exc:
            # The Store adapter has its own closed, sanitized error classes.
            if hasattr(exc, "code") and isinstance(getattr(exc, "code"), str):
                try:
                    raise self._backend_pause(BackendReadError(getattr(exc, "code"))) from None
                except ValueError:
                    pass
            raise

        # Recheck the same Turn claim, current user token and kill switch after
        # the source read; accepted facts are never rendered from pending data.
        current = await asyncio.to_thread(self._store.get_turn, owner_id, turn_id)
        self._ensure_claim_current(current, aggregate, claimed.claim_token)
        await self._fresh_identity(owner_id, scoped_activity_ids, gate_revision=gate.disable_revision)
        current_gate = await self._current_gate()
        if current_gate.disable_revision != gate.disable_revision:
            raise _GateClosed()

        all_facts: list[pc3.P2Fact] = list(live_result.page.items)
        # Page zero plus at most ``page_window - 1`` server-minted continuation
        # pages. Every continuation repeats the whole per-page safety sequence:
        # the decision must be the exact authorized one, the read must present a
        # Store-minted single-use continuation, and the Turn claim, Auth grant
        # and kill-switch revision are re-checked after every source read.
        page_window = _v3_read_page_window(self._max_model_calls)
        pages_seen = 1
        while live_result.page.has_more:
            if (
                live_result.page.page_index != pages_seen - 1
                or live_result.page.next_page_ref is None
            ):
                raise CapabilityUnavailable("v3 source page cannot be continued safely")
            if pages_seen >= page_window:
                # A truncated projection is never presented as a final result.
                # This is a capability limit of the bounded window, not a
                # retryable dependency failure: the same Turn cannot succeed.
                raise _P2TerminalFailure(
                    c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, _V3_RESULT_CAPACITY_REACHED,
                )
            page_qev = live_result.query_evidence
            page_observed = datetime.now(timezone.utc)
            page_receipt = pc3.P2FreshQueryEvidenceRef(
                query_evidence_ref=page_qev.query_evidence_ref,
                query_ref=page_qev.query_ref,
                principal_ref=grant.principal_ref,
                owner_turn_ref=grant.owner_turn_ref,
                generation=identity.generation,
                source_input_seq=identity.input_seq,
                input_digest=identity.input_digest,
                operation=page_qev.operation,
                scope_ref=grant.scope.scope_ref if grant.scope is not None else None,
                criteria_digest=page_qev.criteria_digest,
                observed_at=page_qev.observed_at,
                expires_at=min(expires_at, page_observed + timedelta(minutes=2)),
                next_page_ref=live_result.page.next_page_ref,
                page_index=live_result.page.page_index,
            )
            page_binding = pc3.P2QueryAuthorizationBinding(
                query_evidence_ref=page_qev.query_evidence_ref,
                receipt=page_receipt,
                grant=grant,
            )
            continuation_hint = pc3.P2ContinuationHint(
                query_evidence_ref=page_qev.query_evidence_ref,
                query_ref=page_qev.query_ref,
                next_page_ref=live_result.page.next_page_ref,
            )
            continuation_public = self._v3_model_context(
                plan, input_text, identity, scope=scope,
                query_evidence=(page_qev,), facts=tuple(live_result.page.items),
                allowed_decision_kinds=("read",),
                fresh_receipt_refs=(page_qev.query_evidence_ref,),
                continuations=(continuation_hint,),
                scope_authorization_receipt_ref=scope_receipt_ref,
                current_actor=current_actor, source_labels=source_labels,
            )
            continuation_private = self._v3_intent_context(
                plan, admission, scope=scope, grant=grant,
                receipts=(page_receipt,), bindings=(page_binding,),
            )
            pc3.validate_p2_clarification_projection(continuation_public, continuation_private)
            continuation_prepared = build_p2_v3_request(
                continuation_public, continuation_private, config=self._p2_v3_prompt_config,
            )
            async with self._model_gate:
                raw_continue = await self._generate_v3_model(
                    owner_id=owner_id, turn_id=turn_id, claim_token=claimed.claim_token,
                    public=continuation_public, private=continuation_private,
                    prepared=continuation_prepared,
                )
            if type(raw_continue) is not str:
                raise ModelOutputError("v3 provider response must be text")
            shaped_continue = validate_sent_p2_v3_decision(
                continuation_prepared, continuation_public, continuation_private, raw_continue,
            )
            continue_decision = pc3.parse_p2_decision(raw_continue, continuation_private)
            if not isinstance(continue_decision, pc3.P2ReadContinueRequest) or shaped_continue != continue_decision:
                raise ModelOutputError("v3 paged result requires its exact authorized continuation decision")
            active_grant = self._active_grant(owner_id, turn_id)
            verified = self._make_verified_context(
                owner_id, turn_id, active_grant, aggregate.record.bound_references,
            )
            expected_page_index = pages_seen
            try:
                continued_pending = await adapter.read_candidate_v3(
                    continue_decision, verified, grant,
                    admission=admission, admission_projection=projection,
                    context_version=str(aggregate.record.turn.context_version),
                )
                accepted = await asyncio.to_thread(
                    self._store.accept_p2_v3_query_attempt,
                    owner_id, turn_id, claim_token=claimed.claim_token,
                    principal_user_id=principal.user_id, pending=continued_pending,
                )
                live_result = await asyncio.to_thread(
                    self._store.issue_p2_v3_page,
                    owner_id, turn_id, claim_token=claimed.claim_token,
                    accepted_page=accepted,
                )
            except BackendReadError as exc:
                raise self._backend_pause(exc) from None
            if live_result.page.page_index != expected_page_index:
                raise CapabilityUnavailable("v3 continuation did not produce the next source page")
            pages_seen += 1
            all_facts.extend(live_result.page.items)
            current = await asyncio.to_thread(self._store.get_turn, owner_id, turn_id)
            self._ensure_claim_current(current, aggregate, claimed.claim_token)
            await self._fresh_identity(owner_id, scoped_activity_ids, gate_revision=gate.disable_revision)
            current_gate = await self._current_gate()
            if current_gate.disable_revision != gate.disable_revision:
                raise _GateClosed()

        qev = live_result.query_evidence
        terminal_facts = tuple(
            type(item).model_validate_json(
                item.model_copy(update={"query_evidence_ref": qev.query_evidence_ref}).model_dump_json(),
                strict=True,
            )
            for item in all_facts
        )
        observed_at = datetime.now(timezone.utc)
        receipt_expiry = min(expires_at, observed_at + timedelta(minutes=2))
        fresh_receipt = pc3.P2FreshQueryEvidenceRef(
            query_evidence_ref=qev.query_evidence_ref,
            query_ref=qev.query_ref,
            principal_ref=grant.principal_ref,
            owner_turn_ref=grant.owner_turn_ref,
            generation=identity.generation,
            source_input_seq=identity.input_seq,
            input_digest=identity.input_digest,
            operation=qev.operation,
            scope_ref=grant.scope.scope_ref if grant.scope is not None else None,
            criteria_digest=qev.criteria_digest,
            observed_at=qev.observed_at,
            expires_at=receipt_expiry,
            next_page_ref=None,
            page_index=live_result.page.page_index,
        )
        authorization = pc3.P2QueryAuthorizationBinding(
            query_evidence_ref=qev.query_evidence_ref, receipt=fresh_receipt, grant=grant,
        )
        public_result_context = self._v3_model_context(
            plan, input_text, identity, scope=scope,
            query_evidence=(qev,), facts=terminal_facts,
            allowed_decision_kinds=("answer",),
            fresh_receipt_refs=(qev.query_evidence_ref,),
            scope_authorization_receipt_ref=scope_receipt_ref,
            current_actor=current_actor, source_labels=source_labels,
        )
        private_result_context = self._v3_intent_context(
            plan, admission, scope=scope, grant=grant,
            receipts=(fresh_receipt,), bindings=(authorization,),
        )
        pc3.validate_p2_clarification_projection(public_result_context, private_result_context)
        answer_prepared = build_p2_v3_request(
            public_result_context, private_result_context,
            config=self._p2_v3_prompt_config,
        )
        async with self._model_gate:
            raw_answer = await self._generate_v3_model(
                owner_id=owner_id, turn_id=turn_id, claim_token=claimed.claim_token,
                public=public_result_context, private=private_result_context,
                prepared=answer_prepared,
            )
        if type(raw_answer) is not str:
            raise ModelOutputError("v3 provider response must be text")
        shaped_answer = validate_sent_p2_v3_decision(
            answer_prepared, public_result_context, private_result_context, raw_answer,
        )
        model_answer = pc3.parse_p2_decision(raw_answer, private_result_context)
        if not isinstance(model_answer, pc3.P2AnswerDecision) or shaped_answer != model_answer:
            raise ModelOutputError("v3 final answer is not a citation-bound answer decision")

        # Keep the factual projection in deterministic typed cards; the model
        # chooses only the cited response text, never source amounts or DTOs.
        rendered_facts = self._render_v3_result(
            live_result, facts_override=terminal_facts, source_labels=source_labels,
        )
        text = model_answer.text.rstrip() + "\n\n" + rendered_facts
        answer = pe3.P2V3HistoricalAnswer(
            history_only=True,
            profile_id=pc3.P2_V3_CANDIDATE_PROFILE_ID,
            versions=pc3.P2_V3_VERSIONS,
            turn_ref=grant.owner_turn_ref,
            generation=identity.generation,
            read_epoch=1,
            context_ref=grant.owner_turn_ref,
            context_digest=answer_prepared.context_sha256,
            context_revision=identity.context_revision,
            observed_at=observed_at,
            simulation=qev.simulation,
            kind="answer",
            basis="fresh_read_receipts",
            text=text,
            citations=(qev.query_evidence_ref,),
            query_evidence=(qev,),
            fact_cards=terminal_facts,
            source_labels=source_labels,
            current_actor=current_actor,
        )
        await self._commit_v3_answer(
            current,
            claimed.claim_token,
            accepted,
            answer,
            current_gate,
        )

    @staticmethod
    def _latest_turn_input(aggregate: TurnAggregate) -> str:
        inputs = [item.payload for item in aggregate.checkpoint.accepted_inputs
                  if isinstance(item.payload, (c.SubmitTurnRequest, c.ResumeClarificationRequest))]
        text = inputs[-1].text if inputs else aggregate.record.original_text
        if type(text) is not str or not text.strip():
            raise CapabilityUnavailable("v3 Turn has no accepted nonempty user input")
        return text

    @staticmethod
    def _v3_intent_context(
        plan: P2V3IntentPlan,
        admission: codec3.AdmissionOnlyBinding,
        *,
        scope: pc3.P2Scope | None = None,
        grant: pc3.P2SourceAuthorizationGrant | None = None,
        receipts: tuple[pc3.P2FreshQueryEvidenceRef, ...] = (),
        bindings: tuple[pc3.P2QueryAuthorizationBinding, ...] = (),
    ) -> pc3.P2IntentContext:
        identity = admission.identity
        registry = admission.reference_registry
        pending = tuple(pc3.P2PendingClarification(
            slot=slot,
            reason=reason,
            generation=identity.generation,
            source_input_seq=identity.input_seq,
            input_digest=identity.input_digest,
            operation=operation,
        ) for slot, reason, operation in plan.pending)
        return pc3.P2IntentContext(
            profile_id=pc3.P2_V3_CANDIDATE_PROFILE_ID,
            versions=pc3.P2_V3_VERSIONS,
            classification=plan.classification,
            principal_ref=registry.principal_ref(),
            owner_turn_ref=registry.owner_turn_ref(identity=identity),
            generation=identity.generation,
            source_input_seq=identity.input_seq,
            input_digest=identity.input_digest,
            scope_status="verified" if scope is not None else "absent",
            scope=scope,
            source_authorization_grant=grant,
            fresh_receipt_refs=receipts,
            query_authorization_bindings=bindings,
            clarification_required=bool(pending),
            pending_clarifications=pending,
            proposal_target_resolved=plan.proposal_target_resolved,
            classifier_source="server_policy",
            classifier_version="p2-v3-route-policy-r1",
        )

    @staticmethod
    def _v3_model_context(
        plan: P2V3IntentPlan,
        input_text: str,
        identity: codec3.V3ExecutionIdentity,
        *,
        scope: pc3.P2Scope | None,
        query_evidence: tuple[pc3.P2QueryEvidence, ...] = (),
        facts: tuple[pc3.P2Fact, ...] = (),
        allowed_decision_kinds: tuple[str, ...] | None = None,
        fresh_receipt_refs: tuple[str, ...] = (),
        continuations: tuple[pc3.P2ContinuationHint, ...] = (),
        scope_authorization_receipt_ref: str | None = None,
        current_actor: pc3.P2CurrentActorBinding | None = None,
        source_labels: tuple[pc3.P2EntityDisplayLabel, ...] = (),
    ) -> pc3.P2ModelContext:
        pending = tuple(pc3.P2PendingClarificationProjection(
            slot=slot, reason=reason, operation=operation,
        ) for slot, reason, operation in plan.pending)
        kinds = allowed_decision_kinds or plan.allowed_decision_kinds
        return pc3.P2ModelContext(
            profile_id=pc3.P2_V3_CANDIDATE_PROFILE_ID,
            versions=pc3.P2_V3_VERSIONS,
            context_version="shared-ledger-p2-v3-runtime-r1",
            generation=identity.generation,
            input_text=input_text,
            trusted_intent=pc3.P2TrustedIntent(
                authority="server",
                classification=plan.classification,
                requires_authoritative_evidence=plan.classification in {"factual_business", "ambiguous"},
                source_input_seq=identity.input_seq,
                classifier_version="p2-v3-route-policy-r1",
            ),
            scope_authorization=pc3.P2ScopeAuthorization(
                status="verified" if scope is not None else "absent",
                scope=scope,
                authorization_receipt_ref=(
                    scope_authorization_receipt_ref if scope is not None else None
                ),
            ),
            guard=pc3.P2DecisionGuard(
                source_free_business_answer_allowed=plan.source_free_business_answer_allowed,
                allowed_decision_kinds=kinds,
                allowed_read_operations=plan.allowed_read_operations if "read" in kinds else (),
                fresh_receipt_refs=fresh_receipt_refs,
                proposal_clarification_required=plan.proposal_clarification_required,
                allowed_proposal_operations=plan.allowed_proposal_operations if "propose" in kinds else (),
            ),
            pending_clarifications=pending,
            query_evidence=query_evidence,
            continuations=continuations,
            facts=facts,
            recent_messages=(),
            current_actor=current_actor,
            source_labels=source_labels,
        )

    @staticmethod
    def _render_v3_activity_answer(result: pc3.P2ReadBackendResult) -> str:
        if result.operation is not pc3.P2ReadOperation.ACTIVITIES:
            raise CapabilityUnavailable("activity renderer received another operation")
        evidence = result.query_evidence
        facts = tuple(result.page.items)
        if any(not isinstance(item, pc3.ActivityFact) for item in facts):
            raise CapabilityUnavailable("accepted Activity result contains an incompatible fact")
        complete = (
            evidence.source_query_complete
            and evidence.model_projection_complete
            and not evidence.page.has_more
            and result.page.completeness is pc3.ReadCompleteness.COMPLETE
            and result.page.range_contiguous
            and result.page.source_version_fenced
            and result.page.unique_items_verified
        )
        if not facts:
            if complete and evidence.query_zero_classification in {"backend_zero", "post_filter_zero"}:
                return "当前查询范围内没有符合条件的活动记录。"
            return "本次查询结果不完整，当前没有可确认的活动记录；不能据此判断没有活动。"
        lines = []
        for item in facts:
            details = [item.activity_kind, {"active": "进行中", "archived": "已归档", "unknown": "状态未知"}[item.status]]
            if item.base_currency is not None:
                details.append(f"基准币种 {item.base_currency}")
            lines.append(f"- {item.name}（{'；'.join(details)}）")
        prefix = "已验证的活动：" if complete else "以下是本次已验证的部分活动记录；查询或投影未完成，列表可能不完整："
        return (prefix + "\n" + "\n".join(lines))[:4000]

    @staticmethod
    def _render_v3_result(
        result: pc3.P2ReadBackendResult, *, facts_override: tuple[pc3.P2Fact, ...] | None = None,
        source_labels: tuple[pc3.P2EntityDisplayLabel, ...] = (),
    ) -> str:
        """Render source facts without deriving totals, FX values, or direction."""
        if result.operation is pc3.P2ReadOperation.ACTIVITIES:
            return P2Runtime._render_v3_activity_answer(result)
        evidence = result.query_evidence
        facts = tuple(result.page.items) if facts_override is None else facts_override
        labels = {str(item.entity_ref): item.display_name for item in source_labels}
        display = lambda ref: labels.get(str(ref), str(ref))
        complete = (
            evidence.source_query_complete and evidence.model_projection_complete
            and not evidence.page.has_more
            and result.page.completeness is pc3.ReadCompleteness.COMPLETE
            and result.page.range_contiguous and result.page.source_version_fenced
            and result.page.unique_items_verified
        )
        if not facts:
            if complete and evidence.query_zero_classification in {"backend_zero", "post_filter_zero"}:
                return "当前查询范围内没有符合条件的记录。"
            return "本次查询结果不完整，当前没有可确认的记录；不能据此判断没有记录。"
        lines: list[str] = []
        for fact in facts:
            if isinstance(fact, pc3.ExpenseFact):
                split = "；".join(
                    f"{line.role} {display(line.participant_ref)}: {line.signed_original_amount} {line.original_currency}"
                    f"（基准 {line.signed_base_amount} {line.base_currency}）"
                    for line in fact.payer_split_lines
                )
                lines.append(
                    f"- 消费「{fact.title}」：{fact.signed_original_amount} {fact.original_currency}"
                    f"（基准 {fact.signed_base_amount} {fact.base_currency}）；{split}"
                )
            elif isinstance(fact, pc3.DebtFact):
                original = (
                    f"{fact.original_amount} {fact.original_currency}"
                    if fact.original_amount is not None and fact.original_currency is not None else "原币金额未知"
                )
                lines.append(
                    f"- 欠款方向 {display(fact.debtor_ref)} → {display(fact.creditor_ref)}：{original}；"
                    f"基准 {fact.base_amount} {fact.base_currency}"
                )
            elif isinstance(fact, pc3.RefundEventFact):
                original_direction = "退款" if fact.signed_original_amount.startswith("-") else "退款方向未知"
                lines.append(
                    f"- {original_direction}：{fact.signed_original_amount} {fact.original_currency}；"
                    f"基准 {fact.signed_base_amount} {fact.base_currency}；"
                    f"关联状态 {fact.lineage_status}"
                )
            elif isinstance(fact, pc3.PrepaymentAccountFact):
                lines.append(
                    f"- 预存账户余额 {fact.balance} {fact.currency}；"
                    f"所有者 {display(fact.owner_ref)}；保管人 {display(fact.custodian_ref)}"
                )
            elif isinstance(fact, pc3.PrepaymentUsageFact):
                base = (
                    f"基准 {fact.base_amount} {fact.base_currency}"
                    if fact.base_amount is not None and fact.base_currency is not None else "基准金额未知"
                )
                lines.append(
                    f"- 预存使用 {fact.prepayment_amount} {fact.prepayment_currency}；"
                    f"关联消费 {display(fact.expense_ref)}；债务 {fact.debt_amount} {fact.debt_currency}；{base}"
                )
            elif isinstance(fact, pc3.PrepaymentReturnEventFact):
                lines.append(
                    f"- 预存返还 {fact.amount} {fact.currency}："
                    f"{fact.from_role} {display(fact.from_ref)} → {display(fact.to_ref)}"
                )
            else:
                raise CapabilityUnavailable("accepted source result contains an unsupported fact type")
        prefix = "已验证的来源记录：" if complete else "以下是本次已验证的部分来源记录；查询或投影未完成，列表可能不完整："
        return (prefix + "\n" + "\n".join(lines))[:4000]

    async def _commit_v3_answer(
        self,
        aggregate: TurnAggregate,
        claim_token: str,
        accepted_page: Any,
        historical_output: pe3.P2V3HistoricalAnswer,
        gate: Any,
    ) -> None:
        commit = getattr(self._store, "commit_p2_v3_protected_output", None)
        if not callable(commit):
            raise CapabilityUnavailable("P2 v3 protected output Store path is not available")
        before = aggregate.record.turn
        after = self._next_state(before, c.TurnState.COMPLETED, c.TurnStep.TERMINAL)
        try:
            message_payload = c.MessageEventPayload(text=historical_output.text, citations=[])
        except ValidationError:
            # A complete, Store-accepted read can still exceed the frozen
            # MessageEventPayload text bound. That is a capability limit of this
            # response shape, not a retryable dependency failure.
            raise _P2TerminalFailure(
                c.ApiErrorCode.DEPENDENCY_UNAVAILABLE, _V3_RESULT_NOT_REPRESENTABLE,
            ) from None
        events = [
            EventDraft(
                type=c.EventType.MESSAGE,
                occurred_at=datetime.now(timezone.utc),
                simulation=historical_output.simulation,
                payload=message_payload,
            ),
            self._status_event(after),
        ]
        checkpoint = aggregate.checkpoint.model_copy(update={
            "model_context": None,
            "last_decision": None,
            "last_clarification": None,
            "resume_step": None,
        })
        await asyncio.to_thread(
            commit,
            aggregate.record.turn.owner_user_id,
            after,
            expected_state_revision=before.state_revision,
            expected_checkpoint_revision=aggregate.checkpoint_revision,
            claim_token=claim_token,
            checkpoint=checkpoint,
            events=events,
            accepted_page=accepted_page,
            historical_output=historical_output,
            gate=gate,
        )
        self._p2_states.pop(aggregate.record.turn.turn_id, None)

    async def _complete_v3_plain_message(
        self, aggregate: TurnAggregate, claim_token: str, text: str, gate_revision: int,
        *, non_business_decision: pc3.P2AnswerDecision | None = None,
    ) -> None:
        accepted_decision: c.AnswerDecision | None = None
        if non_business_decision is None:
            if text not in {self._SAFE_GENERIC_TEXT, self._SAFE_PROPOSAL_TEXT}:
                raise CapabilityUnavailable("v3 source-free output is outside the closed message set")
        else:
            if (
                type(non_business_decision) is not pc3.P2AnswerDecision
                or non_business_decision.basis != "non_business_general"
                or non_business_decision.citations
                or non_business_decision.text != text
            ):
                raise CapabilityUnavailable("source-free v3 answer is not a guarded non-business decision")
            try:
                accepted_decision = c.AnswerDecision(
                    kind="answer", basis="conversation", text=text, citations=[],
                )
            except Exception:
                raise CapabilityUnavailable("source-free v3 answer is outside the accepted message contract") from None
            text = accepted_decision.text
        owner_id = aggregate.record.turn.owner_user_id
        turn_id = aggregate.record.turn.turn_id
        current = await asyncio.to_thread(self._store.get_turn, owner_id, turn_id)
        self._ensure_claim_current(current, aggregate, claim_token)
        if current.record.turn.execution is not None or current.record.turn.state != c.TurnState.RUNNING:
            raise StateConflict("v3 Turn is no longer available for source-free completion")
        if accepted_decision is not None:
            plan = classify_p2_v3_input(self._latest_turn_input(current), scope_verified=False)
            if (
                plan.classification != "non_business"
                or plan.allowed_decision_kinds != ("answer",)
                or not plan.source_free_business_answer_allowed
            ):
                raise CapabilityUnavailable("accepted Turn input is not eligible for a source-free answer")
        await self._fresh_identity(owner_id, set(), gate_revision=gate_revision)
        gate = await self._current_gate()
        if not gate.enabled or gate.disable_revision != gate_revision:
            raise _GateClosed()
        before = current.record.turn
        after = self._next_state(before, c.TurnState.COMPLETED, c.TurnStep.TERMINAL)
        checkpoint = current.checkpoint.model_copy(update={
            "model_context": None, "last_decision": accepted_decision, "last_clarification": None,
            "resume_step": None,
        })
        events = [
            EventDraft(
                type=c.EventType.MESSAGE, occurred_at=datetime.now(timezone.utc), simulation=False,
                payload=c.MessageEventPayload(text=text, citations=[]),
            ),
            self._status_event(after),
        ]
        await self._transition(current, after, events, claim_token, checkpoint=checkpoint)

    async def _wait_for_v3_clarification(
        self, aggregate: TurnAggregate, claim_token: str, decision: pc3.P2ClarifyDecision,
        plan: P2V3IntentPlan, gate_revision: int,
    ) -> None:
        allowed = {slot for slot, _reason, _operation in plan.pending}
        requested = {str(slot) for slot in decision.missing_slots}
        if not requested or not requested.issubset(allowed):
            raise CapabilityUnavailable("v3 clarification is not a subset of current server-pending slots")
        slot_map = {
            "activity_scope": c.ClarificationSlot.ACTIVITY,
            "ledger_unit_scope": c.ClarificationSlot.LEDGER_UNIT,
            "expense_target": c.ClarificationSlot.EXPENSE,
            "participant_target": c.ClarificationSlot.SPLIT_PARTICIPANTS,
            "currency": c.ClarificationSlot.CURRENCY,
            "date_range": c.ClarificationSlot.UPDATE_FIELDS,
            "prepayment_account": c.ClarificationSlot.EXPENSE,
            "return_target": c.ClarificationSlot.EXPENSE,
            "proposal_target": c.ClarificationSlot.UPDATE_FIELDS,
            "proposal_title": c.ClarificationSlot.TITLE,
            "proposal_amount": c.ClarificationSlot.AMOUNT,
            "proposal_currency": c.ClarificationSlot.CURRENCY,
            "proposal_participant": c.ClarificationSlot.SPLIT_PARTICIPANTS,
            "proposal_occurred_at": c.ClarificationSlot.UPDATE_FIELDS,
        }
        missing = list(dict.fromkeys(slot_map[slot] for slot in sorted(requested)))
        prompt = " ".join(self._CLARIFICATION_TEXT[slot] for slot in missing)
        owner_id = aggregate.record.turn.owner_user_id
        turn_id = aggregate.record.turn.turn_id
        current = await asyncio.to_thread(self._store.get_turn, owner_id, turn_id)
        self._ensure_claim_current(current, aggregate, claim_token)
        await self._fresh_identity(owner_id, set(), gate_revision=gate_revision)
        gate = await self._current_gate()
        if not gate.enabled or gate.disable_revision != gate_revision:
            raise _GateClosed()
        before = current.record.turn
        resume_state = c.ResumeState.RUNNING
        after = self._next_state(
            before, c.TurnState.WAIT_INPUT, c.TurnStep.AWAITING_USER,
            wait_reason=c.WaitReason.MISSING_FIELDS, resume_state=resume_state,
        )
        checkpoint = current.checkpoint.model_copy(update={
            "model_context": None, "last_decision": None, "last_clarification": None,
            "resume_step": c.TurnStep.MODEL_DECISION,
        })
        events = [
            EventDraft(
                type=c.EventType.CLARIFICATION, occurred_at=datetime.now(timezone.utc), simulation=False,
                payload=c.ClarificationEventPayload(
                    prompt=prompt, missing_slots=missing, resume_state=resume_state,
                ),
            ),
            self._status_event(after),
        ]
        await self._transition(current, after, events, claim_token, checkpoint=checkpoint)

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
        if (
            event.type == c.EventType.MESSAGE
            and not event.simulation
            and not aggregate.record.bound_references
            and not aggregate.record.bound_evidence_references
            and not aggregate.record.bound_read_results
            and not aggregate.checkpoint.read_results
            and not aggregate.checkpoint.persisted_policy_evidence
            and aggregate.record.turn.execution is None
        ):
            try:
                # Execution profile is pinned in the candidate Store family.
                # The frozen v1 Turn snapshot intentionally omits this field.
                candidate = self._store.get_p2_v3_snapshot(
                    aggregate.record.turn.owner_user_id, aggregate.record.turn.turn_id,
                )
            except (P2V3StoreConflict, P2V3StoreNotFound, P2V3UnsupportedProfile, StoreError):
                candidate = None
            if (
                candidate is not None
                and candidate.profile_id == P2_V3_CANDIDATE_PROFILE_ID
                and candidate.owner_user_id == str(aggregate.record.turn.owner_user_id)
                and candidate.turn_id == str(aggregate.record.turn.turn_id)
            ):
                if event.payload.citations:
                    return False
                try:
                    plan = classify_p2_v3_input(self._latest_turn_input(aggregate), scope_verified=False)
                except (CapabilityUnavailable, TypeError, ValueError):
                    return False
                if event.payload.text == self._SAFE_GENERIC_TEXT:
                    return plan.classification == "non_business"
                if event.payload.text == self._SAFE_PROPOSAL_TEXT:
                    return (
                        plan.classification == "proposal_intent"
                        and bool(plan.allowed_proposal_operations)
                    )
                decision = aggregate.checkpoint.last_decision
                return (
                    plan.classification == "non_business"
                    and plan.allowed_decision_kinds == ("answer",)
                    and plan.source_free_business_answer_allowed
                    and isinstance(decision, c.AnswerDecision)
                    and decision.basis == "conversation"
                    and not decision.citations
                    and decision.text == event.payload.text
                )
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
            candidate_profile_id=_ACTIVE_CANDIDATE_PROFILE.get(),
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
            candidate_profile_id=_ACTIVE_CANDIDATE_PROFILE.get(),
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

