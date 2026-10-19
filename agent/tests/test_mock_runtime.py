from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent.app import contracts as c, mock_fixtures
from agent.app.backend import MockBackendAdapter, MockScopeAuthorizer, build_simulation_proposal
from agent.app.harness import ModelOutputError, MockModelProvider, ModelPrompt, parse_model_output
from agent.app.ports import AgentControlSnapshot, Principal
from agent.app.runtime import MockRuntime, RuntimeAuthRequired
from agent.app.store import AdmissionFull, EventDraft, IdempotencyConflict, SQLiteAgentStore

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))
import test_sqlite_persistence as persistence  # noqa: E402


OWNER = uuid.uuid4()


class _Auth:
    def verify_bearer(self, token: str) -> Principal:
        if token in {"runtime-token", "runtime-token-v2"}:
            owner = OWNER
        elif token.startswith("runtime-token:"):
            owner = uuid.UUID(token.split(":", 1)[1])
        else:
            raise ValueError("unknown test token")
        return Principal(owner, datetime.now(timezone.utc) + timedelta(hours=1))


class _Control:
    def snapshot(self) -> AgentControlSnapshot:
        return AgentControlSnapshot(enabled=True, disable_revision=0, source="simulation")


class _CountingProvider(MockModelProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def generate(self, prompt: ModelPrompt) -> str:
        self.calls += 1
        output = await super().generate(prompt)
        return output


def _runtime(store: SQLiteAgentStore, provider: MockModelProvider | None = None) -> tuple[MockRuntime, MockModelProvider]:
    actual = provider or MockModelProvider()
    runtime = MockRuntime(
        store, actual, MockBackendAdapter(), _Auth(), MockScopeAuthorizer(), _Control(),
        model_timeout_seconds=1,
    )
    runtime.bind_auth_grant(
        Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1)), "runtime-token",
    )
    return runtime, actual


async def _wait_state(
    store: SQLiteAgentStore, turn_id: uuid.UUID, expected: set[c.TurnState], owner_id: uuid.UUID = OWNER,
) -> c.TurnAggregate:
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        aggregate = store.get_turn(owner_id, turn_id)
        if aggregate.record.turn.state in expected:
            return aggregate
        await asyncio.sleep(0.01)
    aggregate = store.get_turn(owner_id, turn_id)
    pytest.fail(
        f"Turn did not reach one of {expected}; state={aggregate.record.turn.state} "
        f"step={aggregate.record.turn.step} wait={aggregate.record.turn.wait_reason} "
        f"checkpoint={aggregate.checkpoint.resume_step}; events="
        f"{[(event.event.type, event.event.model_dump(mode='json')) for event in store.read_turn_view(owner_id, turn_id).events]}"
    )


def test_mock_runtime_reads_fixture_and_keeps_inference_unavailable(tmp_path: Path) -> None:
    store = SQLiteAgentStore(tmp_path / "runtime.sqlite3", admission_enabled=True)
    store.start()
    session = persistence._session(store, OWNER)
    _, turn_id = persistence._submit(store, session, OWNER, text="查询消费")
    runtime, provider = _runtime(store, _CountingProvider())

    async def run() -> None:
        await runtime.start()
        try:
            aggregate = await _wait_state(store, turn_id, {c.TurnState.COMPLETED})
            assert aggregate.checkpoint.read_calls == 1
            assert aggregate.checkpoint.model_calls == 2
            assert aggregate.checkpoint.read_results[0].operation == c.ReadOperation.EXPENSES
            assert aggregate.checkpoint.model_context is not None
            assert aggregate.checkpoint.model_context.read_results[0].body == mock_fixtures.model_results(
                aggregate.checkpoint.read_results
            )[0].body
            assert runtime.health().status == "simulation"
            assert provider.health().inference_available is False
        finally:
            await runtime.close()

    asyncio.run(run())
    store.close()


def test_mock_runtime_creates_preview_only_proposal_and_adjustment_is_idempotent(tmp_path: Path) -> None:
    store = SQLiteAgentStore(tmp_path / "adjustment.sqlite3", admission_enabled=True)
    store.start()
    session = persistence._session(store, OWNER)
    _, turn_id = persistence._submit(store, session, OWNER, text="记录午餐 12.50")
    provider = _CountingProvider()
    runtime, _ = _runtime(store, provider)

    async def run() -> None:
        await runtime.start()
        try:
            waiting = await _wait_state(store, turn_id, {c.TurnState.WAIT_CONFIRM})
            view = store.read_turn_view(OWNER, turn_id)
            original = next(item for item in view.proposals if item.status == c.ProposalStatus.PENDING)
            assert original.operation == "expense.create"
            assert original.mode == "simulation"
            assert original.command_digest is None and original.confirmation_nonce is None
            calls_before = provider.calls
            request = c.ResumeProposalAdjustRequest(
                client_request_id=uuid.uuid4(),
                expected_state_revision=waiting.record.turn.state_revision,
                expected_proposal_revision=original.revision,
                text="改成 20.50",
            )
            first, second = await asyncio.gather(
                runtime.prepare_proposal_adjustment(OWNER, turn_id, original.proposal_id, request),
                runtime.prepare_proposal_adjustment(OWNER, turn_id, original.proposal_id, request),
            )
            assert first == second
            updated = store.get_proposal(OWNER, original.proposal_id)
            after = store.get_turn(OWNER, turn_id)
            assert updated.revision == original.revision + 1
            assert updated.operation == original.operation
            assert updated.mode == "simulation"
            assert updated.command_digest is None and updated.confirmation_nonce is None
            assert updated.preview is not None and updated.preview.simulation
            assert updated.preview.after is not None
            assert updated.preview.after.original_amount == "20.50"
            assert updated.preview.after.title == original.intent.title
            assert after.checkpoint.generation == waiting.checkpoint.generation + 1
            assert after.checkpoint.model_calls == 1
            assert after.checkpoint.read_calls == 0
            assert provider.calls - calls_before == 1
            with pytest.raises(IdempotencyConflict):
                await runtime.prepare_proposal_adjustment(
                    OWNER, turn_id, original.proposal_id,
                    request.model_copy(update={"text": "改成 21.00"}),
                )
        finally:
            await runtime.close()

    asyncio.run(run())
    store.close()


def test_mock_runtime_without_verified_token_pauses_queued_checkpoint(tmp_path: Path) -> None:
    store = SQLiteAgentStore(tmp_path / "auth-pause.sqlite3", admission_enabled=True)
    store.start()
    session = persistence._session(store, OWNER)
    _, turn_id = persistence._submit(store, session, OWNER, text="你好")
    provider = _CountingProvider()
    runtime = MockRuntime(
        store, provider, MockBackendAdapter(), _Auth(), MockScopeAuthorizer(), _Control(),
    )

    async def run() -> None:
        await runtime.start()
        try:
            aggregate = await _wait_state(store, turn_id, {c.TurnState.WAIT_INPUT})
            assert aggregate.record.turn.wait_reason == c.WaitReason.AUTH_REQUIRED
            assert aggregate.record.turn.resume_state == c.ResumeState.QUEUED
            assert aggregate.checkpoint.resume_step == c.TurnStep.BUILD_CONTEXT
            assert provider.calls == 0
        finally:
            await runtime.close()

    asyncio.run(run())
    store.close()


def test_mock_parser_rejects_duplicate_nonfinite_unknown_and_deep_json() -> None:
    context = mock_fixtures.model_context()
    invalid = [
        '{"kind":"answer","kind":"answer","basis":"conversation","text":"x","citations":[]}',
        '{"kind":"answer","basis":"conversation","text":NaN,"citations":[]}',
        '{"kind":"answer","basis":"conversation","text":"x","citations":[],"extra":1}',
        "{" + '"nested":' * 2000 + "0" + "}" * 2000,
    ]
    for raw in invalid:
        with pytest.raises(ModelOutputError):
            parse_model_output(raw, context)


def test_simulated_previews_cover_all_frozen_write_operations() -> None:
    refs = mock_fixtures.references()
    by_kind = {item.kind: item.ref for item in refs}
    create = mock_fixtures._expense_create(refs)
    update = c.ExpenseUpdateIntent(
        kind="expense.update", expense_ref=by_kind["expense"], original_amount="25.00",
        payment_allocations=[c.PaymentAllocation(participant_ref=by_kind["participant"], amount="25.00")],
        split=c.EqualSplitIntent(mode="equal", participant_refs=[
            item.ref for item in refs if item.kind == "participant"
        ]),
    )
    presentation = c.ExpensePresentationUpdateIntent(
        kind="expense.presentation.update", expense_ref=by_kind["expense"], title="Dinner",
    )
    for intent in (create, update, presentation):
        proposal = build_simulation_proposal(
            OWNER, uuid.uuid4(), uuid.uuid4(), intent, "mock-policy-v1;disable_revision=0",
        )
        assert proposal.mode == "simulation"
        assert proposal.operation == intent.kind
        assert proposal.preview is not None and proposal.preview.simulation
        assert proposal.preview.after is not None


class _FourReadsAndRepairProvider(MockModelProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def generate(self, prompt: ModelPrompt) -> str:
        self.calls += 1
        if self.calls <= 4:
            scope = prompt.context.verified_scope
            decision = c.ReadDecision(
                kind="read", operation=c.ReadOperation.EXPENSES,
                criteria=c.ReadExpensesCriteria(kind="expenses", activity_ref=scope.activity_ref),
            )
            return decision.model_dump_json(by_alias=True, exclude_none=False)
        if self.calls == 5:
            return "{invalid json"
        fact = prompt.context.read_results[0].body.items[0]
        return c.AnswerDecision(
            kind="answer", basis="grounded", text="simulated result",
            citations=[fact.evidence_ref],
        ).model_dump_json(by_alias=True, exclude_none=False)


def test_runtime_enforces_six_model_four_read_and_one_repair_budgets_with_stable_refs(tmp_path: Path) -> None:
    store = SQLiteAgentStore(tmp_path / "budget.sqlite3", admission_enabled=True)
    store.start()
    session = persistence._session(store, OWNER)
    _, turn_id = persistence._submit(store, session, OWNER, text="\u67e5\u8be2\u6d88\u8d39")
    provider = _FourReadsAndRepairProvider()
    runtime, _ = _runtime(store, provider)

    async def run() -> None:
        await runtime.start()
        try:
            aggregate = await _wait_state(store, turn_id, {c.TurnState.COMPLETED})
            assert aggregate.checkpoint.model_calls == 6
            assert aggregate.checkpoint.read_calls == 4
            assert aggregate.checkpoint.repair_calls == 1
            assert provider.calls == 6
            refs = [item.result_ref for item in aggregate.checkpoint.read_results]
            assert refs == [c.ReadResultRef.R01, c.ReadResultRef.R02, c.ReadResultRef.R03, c.ReadResultRef.R04]
            assert len(set(refs)) == 4
            assert [item.result_ref for item in aggregate.record.bound_read_results] == refs
        finally:
            await runtime.close()

    asyncio.run(run())
    store.close()


class _ToggleAuth(_Auth):
    def __init__(self) -> None:
        self.expired = False

    def verify_bearer(self, token: str) -> Principal:
        if self.expired:
            raise ValueError("expired test grant")
        return super().verify_bearer(token)


class _ExpireOnSecondCallProvider(MockModelProvider):
    def __init__(self, auth: _ToggleAuth) -> None:
        super().__init__()
        self.auth = auth
        self.calls = 0

    async def generate(self, prompt: ModelPrompt) -> str:
        self.calls += 1
        output = await super().generate(prompt)
        if self.calls == 2:
            self.auth.expired = True
        return output


class _ClarifyProvider(MockModelProvider):
    async def generate(self, prompt: ModelPrompt) -> str:
        return c.ClarifyDecision(
            kind="clarify", prompt="Please provide the amount.",
            missing_slots=[c.ClarificationSlot.AMOUNT],
        ).model_dump_json(by_alias=True, exclude_none=False)


class _CaptureInputProvider(MockModelProvider):
    def __init__(self) -> None:
        super().__init__()
        self.contexts: list[c.ModelContext] = []
        self.called = asyncio.Event()

    async def generate(self, prompt: ModelPrompt) -> str:
        self.contexts.append(prompt.context)
        self.called.set()
        return c.ClarifyDecision(
            kind="clarify", prompt="Please provide another detail.",
            missing_slots=[c.ClarificationSlot.TITLE],
        ).model_dump_json(by_alias=True, exclude_none=False)


class _BlockingBackend(MockBackendAdapter):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def read(self, owner_user_id: uuid.UUID, turn_id: uuid.UUID,
                   context: c.ModelContext, decision: c.ReadDecision) -> c.ToolReadResult:
        self.started.set()
        await self.release.wait()
        return await super().read(owner_user_id, turn_id, context, decision)


class _BlockFirstProvider(MockModelProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.first_started = asyncio.Event()
        self.release_first = asyncio.Event()

    async def generate(self, prompt: ModelPrompt) -> str:
        self.calls += 1
        if self.calls == 1:
            self.first_started.set()
            await self.release_first.wait()
        return await super().generate(prompt)


class _AlwaysReadProvider(MockModelProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def generate(self, prompt: ModelPrompt) -> str:
        self.calls += 1
        return c.ReadDecision(
            kind="read", operation=c.ReadOperation.EXPENSES,
            criteria=c.ReadExpensesCriteria(kind="expenses", activity_ref=prompt.context.verified_scope.activity_ref),
        ).model_dump_json(by_alias=True, exclude_none=False)


class _CountingBackend(MockBackendAdapter):
    def __init__(self) -> None:
        self.calls = 0

    async def read(self, owner_user_id: uuid.UUID, turn_id: uuid.UUID,
                   context: c.ModelContext, decision: c.ReadDecision) -> c.ToolReadResult:
        self.calls += 1
        return await super().read(owner_user_id, turn_id, context, decision)


class _InvalidTwiceProvider(MockModelProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def generate(self, prompt: ModelPrompt) -> str:
        self.calls += 1
        return "{invalid json"


def test_auth_resume_keeps_latest_clarification_as_model_input(tmp_path: Path) -> None:
    store = SQLiteAgentStore(tmp_path / "clarify-auth-context.sqlite3", admission_enabled=True)
    store.start()
    session = persistence._session(store, OWNER)
    _, turn_id = persistence._submit(store, session, OWNER, text="记录午餐")
    first_runtime, _ = _runtime(store, _ClarifyProvider())

    async def run() -> None:
        await first_runtime.start()
        waiting = await _wait_state(store, turn_id, {c.TurnState.WAIT_INPUT})
        assert waiting.record.turn.wait_reason == c.WaitReason.MISSING_FIELDS
        await first_runtime.close()
        clarification = c.ResumeClarificationRequest(
            client_request_id=uuid.uuid4(),
            expected_state_revision=waiting.record.turn.state_revision,
            text="20.50 CNY",
        )
        clarified_running = persistence._snapshot(
            waiting.record.turn, state=c.TurnState.RUNNING, step=c.TurnStep.MODEL_DECISION,
        )
        response = c.TurnMutationAccepted(
            turn_id=turn_id, state=clarified_running.state,
            state_revision=clarified_running.state_revision, event_cursor=0,
        )
        store.accept_turn_action(
            OWNER, turn_id, clarification, clarified_running, response,
            events=[first_runtime._status_event(clarified_running)],
        )
        accepted = store.get_turn(OWNER, turn_id)
        assert accepted.checkpoint.last_decision is None
        assert accepted.checkpoint.resume_step == c.TurnStep.BUILD_CONTEXT

        capture = _CaptureInputProvider()
        second_runtime = MockRuntime(
            store, capture, MockBackendAdapter(), _Auth(), MockScopeAuthorizer(), _Control(),
        )
        await second_runtime.start()
        try:
            auth_wait = await _wait_state(store, turn_id, {c.TurnState.WAIT_INPUT})
            assert auth_wait.record.turn.wait_reason == c.WaitReason.AUTH_REQUIRED
            assert auth_wait.record.turn.resume_state == c.ResumeState.QUEUED
            second_runtime.bind_auth_grant(
                Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1)), "runtime-token",
            )
            before = auth_wait.record.turn
            resumed = persistence._snapshot(
                before, state=c.TurnState.QUEUED, step=c.TurnStep.BUILD_CONTEXT,
            )
            auth_request = c.ResumeAuthRequest(
                client_request_id=uuid.uuid4(), expected_state_revision=before.state_revision,
            )
            response = c.TurnMutationAccepted(
                turn_id=turn_id, state=resumed.state, state_revision=resumed.state_revision, event_cursor=0,
            )
            store.accept_turn_action(
                OWNER, turn_id, auth_request, resumed, response,
                events=[second_runtime._status_event(resumed)],
            )
            await asyncio.wait_for(capture.called.wait(), timeout=3)
            assert capture.contexts[-1].input_text == "20.50 CNY"
            assert [item.text for item in capture.contexts[-1].recent_messages] == ["记录午餐"]
        finally:
            await second_runtime.close()

    asyncio.run(run())
    store.close()


def test_slow_fixture_read_does_not_hold_model_gate_for_another_actor(tmp_path: Path) -> None:
    store = SQLiteAgentStore(tmp_path / "tool-interleave.sqlite3", admission_enabled=True)
    store.start()
    session_a = persistence._session(store, OWNER)
    _, turn_a = persistence._submit(store, session_a, OWNER, text="查询消费")
    owner_b = uuid.uuid4()
    session_b = persistence._session(store, owner_b)
    _, turn_b = persistence._submit(store, session_b, owner_b, text="你好")
    backend = _BlockingBackend()
    provider = _CountingProvider()
    runtime = MockRuntime(
        store, provider, backend, _Auth(), MockScopeAuthorizer(), _Control(), model_timeout_seconds=2,
    )
    runtime.bind_auth_grant(Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1)), "runtime-token")
    runtime.bind_auth_grant(
        Principal(owner_b, datetime.now(timezone.utc) + timedelta(hours=1)), f"runtime-token:{owner_b}",
    )

    async def run() -> None:
        await runtime.start()
        try:
            await asyncio.wait_for(backend.started.wait(), timeout=3)
            completed_b = await _wait_state(store, turn_b, {c.TurnState.COMPLETED}, owner_b)
            running_a = store.get_turn(OWNER, turn_a)
            assert running_a.record.turn.state == c.TurnState.RUNNING
            assert completed_b.checkpoint.model_calls == 1
            assert provider.calls == 2
            backend.release.set()
            completed_a = await _wait_state(store, turn_a, {c.TurnState.COMPLETED})
            assert completed_a.checkpoint.read_calls == 1
            assert completed_a.checkpoint.model_calls == 2
        finally:
            backend.release.set()
            await runtime.close()

    asyncio.run(run())
    store.close()


def test_cancelled_late_provider_output_keeps_model_gate_until_completion(tmp_path: Path) -> None:
    store = SQLiteAgentStore(tmp_path / "late-output.sqlite3", admission_enabled=True)
    store.start()
    session_a = persistence._session(store, OWNER)
    _, turn_a = persistence._submit(store, session_a, OWNER, text="你好")
    owner_b = uuid.uuid4()
    session_b = persistence._session(store, owner_b)
    provider = _BlockFirstProvider()
    runtime = MockRuntime(
        store, provider, MockBackendAdapter(), _Auth(), MockScopeAuthorizer(), _Control(), model_timeout_seconds=10,
    )
    runtime.bind_auth_grant(Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1)), "runtime-token")
    runtime.bind_auth_grant(
        Principal(owner_b, datetime.now(timezone.utc) + timedelta(hours=1)), f"runtime-token:{owner_b}",
    )

    async def run() -> None:
        await runtime.start()
        try:
            await asyncio.wait_for(provider.first_started.wait(), timeout=3)
            _, turn_b = persistence._submit(store, session_b, owner_b, text="你好")
            before = store.get_turn(OWNER, turn_a).record.turn
            cancelled = persistence._snapshot(
                before, state=c.TurnState.CANCELLED, step=c.TurnStep.TERMINAL,
                wait_reason=None, resume_state=None,
            )
            request = c.CancelTurnRequest(
                client_request_id=uuid.uuid4(), expected_state_revision=before.state_revision,
            )
            response = c.CancelTurnResponse(turn=persistence._public(cancelled), result="cancelled")
            store.accept_turn_action(
                OWNER, turn_a, request, cancelled, response,
                events=[runtime._status_event(cancelled)],
            )
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                running_b = store.get_turn(owner_b, turn_b)
                if (
                    running_b.record.turn.state == c.TurnState.RUNNING
                    and running_b.checkpoint.resume_step == c.TurnStep.MODEL_DECISION
                    and running_b.checkpoint.model_context is not None
                ):
                    break
                await asyncio.sleep(0.01)
            else:
                pytest.fail("second actor did not reach the persisted model-gate wait")
            assert running_b.checkpoint.model_context is not None
            assert running_b.checkpoint.model_calls == 0
            assert provider.calls == 1
            assert store.get_turn(OWNER, turn_a).record.turn.state == c.TurnState.CANCELLED
            provider.release_first.set()
            completed_b = await _wait_state(store, turn_b, {c.TurnState.COMPLETED}, owner_b)
            await _wait_state(store, turn_a, {c.TurnState.CANCELLED})
            assert completed_b.checkpoint.model_calls == 1
            assert provider.calls == 2
        finally:
            provider.release_first.set()
            await runtime.close()

    asyncio.run(run())
    store.close()


def test_unknown_execution_recovery_keeps_key_and_does_not_starve_queued_turn(tmp_path: Path) -> None:
    store = SQLiteAgentStore(tmp_path / "unknown-nonstarve.sqlite3", admission_enabled=True)
    store.start()
    session = persistence._session(store, OWNER)
    _, recovery_id = persistence._submit(store, session, OWNER, text="记录午餐 12.50")
    proposal = persistence._proposal(OWNER, session, recovery_id, backend=True)
    waiting = persistence._wait_with_proposal(store, OWNER, recovery_id, proposal)
    execution = c.ExecutionIdentity(
        execution_id=c.derive_execution_id(OWNER, proposal.proposal_id, proposal.revision),
        actor_id=OWNER, proposal_id=proposal.proposal_id, proposal_revision=proposal.revision,
    )
    executing = persistence._snapshot(
        waiting, state=c.TurnState.EXECUTING, step=c.TurnStep.DISPATCH, execution=execution,
    )
    confirmed = c.ProposalRecord.model_validate(
        proposal.model_dump(mode="python", by_alias=True, exclude_none=False)
        | {"status": c.ProposalStatus.CONFIRMED, "confirmation_nonce": None,
           "execution": execution.model_dump(mode="python", by_alias=True, exclude_none=False)}
    )
    aggregate = store.get_turn(OWNER, recovery_id)
    store.transition_turn(
        OWNER, executing, expected_state_revision=waiting.state_revision,
        expected_checkpoint_revision=aggregate.checkpoint_revision,
        events=[persistence._status(executing)], updated_proposal=confirmed, fixture_execution=True,
    )
    unknown = persistence._snapshot(
        executing, state=c.TurnState.RECOVERING, step=c.TurnStep.RECONCILE,
        resolution=c.ExecutionResolution.UNKNOWN,
    )
    execution_ref = c.ExecutionReference(
        execution_id=execution.execution_id, proposal_id=proposal.proposal_id,
        proposal_revision=proposal.revision,
    )
    unknown_event = EventDraft(
        type=c.EventType.EXECUTION_RESULT, occurred_at=datetime.now(timezone.utc), simulation=False,
        payload=c.ExecutionResultPayload(execution=execution_ref, resolution=c.ExecutionResolution.UNKNOWN),
    )
    aggregate = store.get_turn(OWNER, recovery_id)
    store.transition_turn(
        OWNER, unknown, expected_state_revision=executing.state_revision,
        expected_checkpoint_revision=aggregate.checkpoint_revision,
        events=[persistence._status(unknown), unknown_event],
    )
    _, queued_id = persistence._submit(store, session, OWNER, text="你好")
    provider = _CountingProvider()
    runtime, _ = _runtime(store, provider)

    async def run() -> None:
        await runtime.start()
        try:
            completed = await _wait_state(store, queued_id, {c.TurnState.COMPLETED})
            assert completed.checkpoint.model_calls == 1
            recovered = store.get_turn(OWNER, recovery_id).record.turn
            # P3a filled the previously empty execution-adapter slot: the runtime
            # now settles the unknown outcome under the original key instead of
            # parking it indefinitely. The key is unchanged, the queued Turn is
            # still served, and recovery spends no model call.
            assert recovered.state == c.TurnState.COMPLETED
            assert recovered.execution == execution
            assert recovered.execution_resolution == c.ExecutionResolution.SUCCEEDED
            assert store.count_mock_executions(proposal.proposal_id) == 1
            assert provider.calls == 1
        finally:
            await runtime.close()

    asyncio.run(run())
    store.close()


def test_model_timeout_keeps_gate_until_provider_finishes_and_discards_late_output(tmp_path: Path) -> None:
    store = SQLiteAgentStore(tmp_path / "timeout-gate.sqlite3", admission_enabled=True)
    store.start()
    session_a = persistence._session(store, OWNER)
    _, turn_a = persistence._submit(store, session_a, OWNER, text="你好")
    owner_b = uuid.uuid4()
    session_b = persistence._session(store, owner_b)
    provider = _BlockFirstProvider()
    runtime = MockRuntime(
        store, provider, MockBackendAdapter(), _Auth(), MockScopeAuthorizer(), _Control(),
        model_timeout_seconds=0.05,
    )
    runtime.bind_auth_grant(Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1)), "runtime-token")
    runtime.bind_auth_grant(
        Principal(owner_b, datetime.now(timezone.utc) + timedelta(hours=1)), f"runtime-token:{owner_b}",
    )

    async def run() -> None:
        await runtime.start()
        try:
            await asyncio.wait_for(provider.first_started.wait(), timeout=3)
            _, turn_b = persistence._submit(store, session_b, owner_b, text="你好")
            failed_a = await _wait_state(store, turn_a, {c.TurnState.FAILED})
            assert failed_a.checkpoint.model_calls == 1
            assert failed_a.checkpoint.last_decision is None
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                running_b = store.get_turn(owner_b, turn_b)
                if (
                    running_b.record.turn.state == c.TurnState.RUNNING
                    and running_b.checkpoint.resume_step == c.TurnStep.MODEL_DECISION
                    and running_b.checkpoint.model_context is not None
                ):
                    break
                await asyncio.sleep(0.01)
            else:
                pytest.fail("second actor did not reach the persisted model-gate wait")
            assert running_b.checkpoint.model_context is not None
            assert running_b.checkpoint.model_calls == 0
            assert provider.calls == 1
            provider.release_first.set()
            completed_b = await _wait_state(store, turn_b, {c.TurnState.COMPLETED}, owner_b)
            assert completed_b.checkpoint.model_calls == 1
            assert provider.calls == 2
            # The timed-out result arrived only after its Turn had failed.
            assert store.get_turn(OWNER, turn_a).record.turn.state == c.TurnState.FAILED
            assert store.get_turn(OWNER, turn_a).checkpoint.last_decision is None
        finally:
            provider.release_first.set()
            await runtime.close()

    asyncio.run(run())
    store.close()


def test_waiting_for_model_gate_rechecks_auth_before_provider_call(tmp_path: Path) -> None:
    store = SQLiteAgentStore(tmp_path / "gate-auth.sqlite3", admission_enabled=True)
    store.start()
    session_a = persistence._session(store, OWNER)
    _, turn_a = persistence._submit(store, session_a, OWNER, text="你好")
    owner_b = uuid.uuid4()
    session_b = persistence._session(store, owner_b)
    auth = _ToggleAuth()
    provider = _BlockFirstProvider()
    runtime = MockRuntime(
        store, provider, MockBackendAdapter(), auth, MockScopeAuthorizer(), _Control(),
        model_timeout_seconds=10,
    )
    runtime.bind_auth_grant(Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1)), "runtime-token")
    runtime.bind_auth_grant(
        Principal(owner_b, datetime.now(timezone.utc) + timedelta(hours=1)), f"runtime-token:{owner_b}",
    )

    async def run() -> None:
        await runtime.start()
        try:
            await asyncio.wait_for(provider.first_started.wait(), timeout=3)
            _, turn_b = persistence._submit(store, session_b, owner_b, text="你好")
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                waiting_b = store.get_turn(owner_b, turn_b)
                if (
                    waiting_b.record.turn.state == c.TurnState.RUNNING
                    and waiting_b.checkpoint.resume_step == c.TurnStep.MODEL_DECISION
                    and waiting_b.checkpoint.model_context is not None
                ):
                    break
                await asyncio.sleep(0.01)
            else:
                pytest.fail("second actor did not reach the persisted model-gate wait")
            assert waiting_b.checkpoint.model_calls == 0
            auth.expired = True
            provider.release_first.set()
            paused_b = await _wait_state(store, turn_b, {c.TurnState.WAIT_INPUT}, owner_b)
            assert paused_b.record.turn.wait_reason == c.WaitReason.AUTH_REQUIRED
            assert paused_b.record.turn.resume_state == c.ResumeState.QUEUED
            assert paused_b.checkpoint.model_calls == 0
            assert provider.calls == 1
        finally:
            provider.release_first.set()
            await runtime.close()

    asyncio.run(run())
    store.close()


def test_read_four_and_single_repair_limits_fail_closed(tmp_path: Path) -> None:
    store = SQLiteAgentStore(tmp_path / "read-boundary.sqlite3", admission_enabled=True)
    store.start()
    session = persistence._session(store, OWNER)
    _, turn_id = persistence._submit(store, session, OWNER, text="查询消费")
    provider = _AlwaysReadProvider()
    backend = _CountingBackend()
    runtime, _ = _runtime(store, provider)
    runtime._backend = backend

    async def run() -> None:
        await runtime.start()
        try:
            failed = await _wait_state(store, turn_id, {c.TurnState.FAILED})
            assert failed.checkpoint.read_calls == 4
            assert failed.checkpoint.model_calls == 5
            assert provider.calls == 5
            assert backend.calls == 4
        finally:
            await runtime.close()

    asyncio.run(run())
    store.close()

    repair_store = SQLiteAgentStore(tmp_path / "repair-boundary.sqlite3", admission_enabled=True)
    repair_store.start()
    repair_session = persistence._session(repair_store, OWNER)
    _, repair_turn = persistence._submit(repair_store, repair_session, OWNER, text="你好")
    invalid = _InvalidTwiceProvider()
    repair_runtime, _ = _runtime(repair_store, invalid)

    async def repair_run() -> None:
        await repair_runtime.start()
        try:
            failed = await _wait_state(repair_store, repair_turn, {c.TurnState.FAILED})
            assert failed.checkpoint.model_calls == 2
            assert failed.checkpoint.repair_calls == 1
            assert invalid.calls == 2
        finally:
            await repair_runtime.close()

    asyncio.run(repair_run())
    repair_store.close()


def test_restart_with_six_saved_model_calls_never_calls_provider_a_seventh_time(tmp_path: Path) -> None:
    store = SQLiteAgentStore(tmp_path / "model-budget-restart.sqlite3", admission_enabled=True)
    store.start()
    session = persistence._session(store, OWNER)
    _, turn_id = persistence._submit(store, session, OWNER, text="你好")
    aggregate = store.get_turn(OWNER, turn_id)
    checkpoint = aggregate.checkpoint.model_copy(update={
        "model_calls": 6, "resume_step": c.TurnStep.MODEL_DECISION,
    })
    store.save_checkpoint(
        OWNER, turn_id, expected_state_revision=aggregate.record.turn.state_revision,
        expected_checkpoint_revision=aggregate.checkpoint_revision, checkpoint=checkpoint,
    )
    provider = _CountingProvider()
    runtime, _ = _runtime(store, provider)

    async def run() -> None:
        await runtime.start()
        try:
            failed = await _wait_state(store, turn_id, {c.TurnState.FAILED})
            assert failed.checkpoint.model_calls == 6
            assert provider.calls == 0
        finally:
            await runtime.close()

    asyncio.run(run())
    store.close()


def test_global_queue_limit_is_atomic_across_connections_and_rejected_key_can_retry(tmp_path: Path) -> None:
    path = tmp_path / "global-queue.sqlite3"
    left = SQLiteAgentStore(path, admission_enabled=True)
    right = SQLiteAgentStore(path, admission_enabled=True)
    left.start()
    right.start()
    owners = [uuid.uuid4() for _ in range(17)]
    sessions = [persistence._session(left if index % 2 == 0 else right, owner)
                for index, owner in enumerate(owners)]
    receipts: list[c.RequestReceipt] = []
    requests: list[c.SubmitTurnRequest] = []
    for index in range(15):
        store = left if index % 2 == 0 else right
        ui = c.UIContext(
            page_type=c.PageType.HOME, captured_at=datetime.now(timezone.utc), client_version="p1-test",
        )
        request = c.SubmitTurnRequest(client_request_id=uuid.uuid4(), text=f"queued {index}", ui_context=ui)
        requests.append(request)
        receipts.append(store.submit_turn(owners[index], sessions[index], request))

    contenders: list[tuple[SQLiteAgentStore, uuid.UUID, uuid.UUID, c.SubmitTurnRequest]] = []
    for index in (15, 16):
        ui = c.UIContext(
            page_type=c.PageType.HOME, captured_at=datetime.now(timezone.utc), client_version="p1-test",
        )
        contenders.append((
            left if index == 15 else right, owners[index], sessions[index],
            c.SubmitTurnRequest(
                client_request_id=uuid.uuid4(), text=f"atomic contender {index}", ui_context=ui,
            ),
        ))
    barrier = threading.Barrier(2)

    def race_submit(item: tuple[SQLiteAgentStore, uuid.UUID, uuid.UUID, c.SubmitTurnRequest]):
        store, owner, session_id, request = item
        barrier.wait(timeout=3)
        try:
            return (item, store.submit_turn(owner, session_id, request))
        except AdmissionFull as exc:
            return (item, exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        raced = list(pool.map(race_submit, contenders))
    accepted_races = [(item, result) for item, result in raced if isinstance(result, c.RequestReceipt)]
    rejected_races = [(item, result) for item, result in raced if isinstance(result, AdmissionFull)]
    assert len(accepted_races) == len(rejected_races) == 1
    assert left.submit_turn(owners[0], sessions[0], requests[0]) == receipts[0]

    first_turn = receipts[0].response_snapshot.turn_id
    claimed = left.claim_runnable("queue-test", lease_seconds=30)
    assert claimed is not None and claimed.turn.record.turn.turn_id == first_turn
    before = claimed.turn.record.turn
    running = persistence._snapshot(before, state=c.TurnState.RUNNING, step=c.TurnStep.BUILD_CONTEXT)
    left.transition_turn(
        owners[0], running, expected_state_revision=before.state_revision,
        expected_checkpoint_revision=claimed.turn.checkpoint_revision,
        claim_token=claimed.claim_token, events=[EventDraft(
            type=c.EventType.STATUS, occurred_at=datetime.now(timezone.utc), simulation=True,
            payload=c.StatusEventPayload(
                state=running.state, step=running.step, state_revision=running.state_revision,
            ),
        )],
    )
    rejected_item, _ = rejected_races[0]
    retry_store, retry_owner, retry_session, retry_request = rejected_item
    retried = retry_store.submit_turn(retry_owner, retry_session, retry_request)
    assert retried.response_snapshot.state == c.TurnState.QUEUED
    assert retry_store.submit_turn(retry_owner, retry_session, retry_request) == retried
    left.close()
    right.close()


def test_expired_running_claim_and_adjustment_lease_exclude_same_owner_second_worker(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    store = SQLiteAgentStore(tmp_path / "owner-admission.sqlite3", admission_enabled=True)
    store.start()
    session = persistence._session(store, OWNER)
    _, first_id = persistence._submit(store, session, OWNER, text="first")
    initial = store.get_turn(OWNER, first_id)
    first_claim = store.claim_runnable("owner-test", lease_seconds=1, now=now)
    assert first_claim is not None and first_claim.turn.record.turn.turn_id == first_id
    first_running = persistence._snapshot(
        initial.record.turn, state=c.TurnState.RUNNING, step=c.TurnStep.BUILD_CONTEXT,
    )
    store.transition_turn(
        OWNER, first_running, expected_state_revision=initial.record.turn.state_revision,
        expected_checkpoint_revision=first_claim.turn.checkpoint_revision,
        claim_token=first_claim.claim_token,
        events=[EventDraft(
            type=c.EventType.STATUS, occurred_at=now, simulation=True,
            payload=c.StatusEventPayload(
                state=first_running.state, step=first_running.step,
                state_revision=first_running.state_revision,
            ),
        )], now=now,
    )
    _, second_id = persistence._submit(store, session, OWNER, text="second")
    future = now + timedelta(seconds=2)
    reclaimed = store.claim_runnable("owner-test-2", lease_seconds=30, now=future)
    assert reclaimed is not None and reclaimed.turn.record.turn.turn_id == first_id
    assert store.get_turn(OWNER, second_id).record.turn.state == c.TurnState.QUEUED
    store.release_claim(first_id, reclaimed.claim_token)
    still_first = store.claim_runnable("owner-test-3", lease_seconds=30, now=future)
    assert still_first is not None and still_first.turn.record.turn.turn_id == first_id
    store.release_claim(first_id, still_first.claim_token)
    store.close()

    lease_store = SQLiteAgentStore(tmp_path / "adjustment-admission.sqlite3", admission_enabled=True)
    lease_store.start()
    lease_session = persistence._session(lease_store, OWNER)
    _, wait_id = persistence._submit(lease_store, lease_session, OWNER, text="proposal")
    proposal = persistence._proposal(OWNER, lease_session, wait_id)
    waiting = persistence._wait_with_proposal(lease_store, OWNER, wait_id, proposal)
    adjust = c.ResumeProposalAdjustRequest(
        client_request_id=uuid.uuid4(), expected_state_revision=waiting.state_revision,
        expected_proposal_revision=proposal.revision, text="change title",
    )
    reserved = lease_store.reserve_proposal_adjustment(
        OWNER, wait_id, proposal.proposal_id, adjust, policy_version=proposal.policy_version,
    )
    reservation = reserved.checkpoint.adjustment_reservation
    assert reservation is not None and reservation.lease_token is not None
    _, queued_id = persistence._submit(lease_store, lease_session, OWNER, text="queued behind adjustment")
    assert lease_store.claim_runnable("adjustment-lease-test") is None
    assert lease_store.release_proposal_adjustment_lease(
        OWNER, wait_id, reservation.lease_token,
    )
    claim = lease_store.claim_runnable("adjustment-lease-test-2")
    assert claim is not None and claim.turn.record.turn.turn_id == queued_id
    lease_store.release_claim(queued_id, claim.claim_token)
    lease_store.close()


def test_adjustment_auth_pause_resume_reuses_accepted_body_and_budget(tmp_path: Path) -> None:
    store = SQLiteAgentStore(tmp_path / "adjust-auth.sqlite3", admission_enabled=True)
    store.start()
    session = persistence._session(store, OWNER)
    _, turn_id = persistence._submit(store, session, OWNER, text="\u8bb0\u5f55\u5348\u9910 12.50")
    auth = _ToggleAuth()
    provider = _ExpireOnSecondCallProvider(auth)
    runtime = MockRuntime(store, provider, MockBackendAdapter(), auth, MockScopeAuthorizer(), _Control())
    runtime.bind_auth_grant(Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1)), "runtime-token")

    async def run() -> None:
        await runtime.start()
        try:
            waiting = await _wait_state(store, turn_id, {c.TurnState.WAIT_CONFIRM})
            original = next(item for item in store.read_turn_view(OWNER, turn_id).proposals
                            if item.status == c.ProposalStatus.PENDING)
            request = c.ResumeProposalAdjustRequest(
                client_request_id=uuid.uuid4(),
                expected_state_revision=waiting.record.turn.state_revision,
                expected_proposal_revision=original.revision,
                text="\u6539\u6210 20.50",
            )
            with pytest.raises(RuntimeAuthRequired):
                await runtime.prepare_proposal_adjustment(OWNER, turn_id, original.proposal_id, request)
            paused = store.get_turn(OWNER, turn_id)
            assert paused.record.turn.state == c.TurnState.WAIT_INPUT
            assert paused.record.turn.wait_reason == c.WaitReason.AUTH_REQUIRED
            assert paused.record.turn.resume_state == c.ResumeState.WAIT_CONFIRM
            assert paused.checkpoint.adjustment_reservation is not None
            assert paused.checkpoint.adjustment_reservation.lease_token is None
            assert paused.checkpoint.model_calls == 1
            accepted_generation = paused.checkpoint.generation

            auth.expired = False
            runtime.bind_auth_grant(
                Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1)), "runtime-token-v2",
            )
            before = paused.record.turn
            resumed = persistence._snapshot(
                before, state=c.TurnState.WAIT_CONFIRM, step=c.TurnStep.AWAITING_USER,
                wait_reason=c.WaitReason.CONFIRM_REQUIRED, resume_state=None,
            )
            auth_request = c.ResumeAuthRequest(
                client_request_id=uuid.uuid4(), expected_state_revision=before.state_revision,
            )
            response = c.TurnMutationAccepted(
                turn_id=turn_id, state=resumed.state, state_revision=resumed.state_revision, event_cursor=0,
            )
            store.accept_turn_action(
                OWNER, turn_id, auth_request, resumed, response,
                events=[runtime._status_event(resumed)],
            )
            # The body retains the pre-pause expected revision. Its exact accepted
            # reservation is the proof allowing this retry after auth state advanced.
            receipt = await runtime.prepare_proposal_adjustment(OWNER, turn_id, original.proposal_id, request)
            updated = store.get_proposal(OWNER, original.proposal_id)
            finished = store.get_turn(OWNER, turn_id)
            assert receipt.response_snapshot.proposal_revision == original.revision + 1
            assert updated.operation == original.operation == "expense.create"
            assert updated.preview is not None and updated.preview.after is not None
            assert updated.preview.after.original_amount == "20.50"
            assert updated.preview.after.title == original.intent.title
            assert finished.checkpoint.generation == accepted_generation
            assert finished.checkpoint.model_calls == 2
            assert finished.checkpoint.read_calls == 0
            assert provider.calls == 3
        finally:
            await runtime.close()

    asyncio.run(run())
    store.close()


class _MultiReadThenBlockProvider(MockModelProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.second_call_started = asyncio.Event()
        self.release_second = asyncio.Event()

    async def generate(self, prompt: ModelPrompt) -> str:
        self.calls += 1
        if self.calls == 1:
            scope = prompt.context.verified_scope
            return c.ReadDecision(
                kind="read", operation=c.ReadOperation.EXPENSES,
                criteria=c.ReadExpensesCriteria(kind="expenses", activity_ref=scope.activity_ref),
            ).model_dump_json(by_alias=True, exclude_none=False)
        self.second_call_started.set()
        await self.release_second.wait()
        return await super().generate(prompt)


def test_restart_resumes_model_stage_without_repeating_saved_read_decision(tmp_path: Path) -> None:
    store = SQLiteAgentStore(tmp_path / "restart-stage.sqlite3", admission_enabled=True)
    store.start()
    session = persistence._session(store, OWNER)
    _, turn_id = persistence._submit(store, session, OWNER, text="\u67e5\u8be2\u6d88\u8d39")
    first_provider = _MultiReadThenBlockProvider()
    first_runtime, _ = _runtime(store, first_provider)

    async def run() -> None:
        await first_runtime.start()
        await asyncio.wait_for(first_provider.second_call_started.wait(), timeout=3)
        interrupted = store.get_turn(OWNER, turn_id)
        assert interrupted.checkpoint.model_calls == 2
        assert interrupted.checkpoint.read_calls == 1
        assert len(interrupted.checkpoint.read_results) == 1
        saved_bindings = list(interrupted.record.bound_read_results)
        saved_entity_refs = list(interrupted.record.bound_references)
        await first_runtime.close()

        second_provider = _CountingProvider()
        second_runtime, _ = _runtime(store, second_provider)
        await second_runtime.start()
        try:
            completed = await _wait_state(store, turn_id, {c.TurnState.COMPLETED})
            assert completed.checkpoint.generation == interrupted.checkpoint.generation
            assert completed.checkpoint.model_calls == 3
            assert completed.checkpoint.read_calls == 1
            assert completed.checkpoint.read_results[0] == interrupted.checkpoint.read_results[0]
            assert completed.record.bound_read_results == saved_bindings
            assert completed.record.bound_references == saved_entity_refs
            assert second_provider.calls == 1
        finally:
            await second_runtime.close()

    asyncio.run(run())
    store.close()


def test_runtime_close_discards_inflight_claim_before_restart_resumes_turn(tmp_path: Path) -> None:
    from contextlib import contextmanager

    store = SQLiteAgentStore(tmp_path / "restart-claim-race.sqlite3", admission_enabled=True)
    store.start()
    session = persistence._session(store, OWNER)
    _, turn_id = persistence._submit(store, session, OWNER, text="查询消费")
    first_provider = _MultiReadThenBlockProvider()
    first_runtime = MockRuntime(
        store, first_provider, MockBackendAdapter(), _Auth(), MockScopeAuthorizer(), _Control(),
        model_timeout_seconds=1, shutdown_timeout_seconds=0.1,
    )
    first_runtime.bind_auth_grant(
        Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1)), "runtime-token",
    )
    arm_claim = threading.Event()
    blocked_transaction = threading.Event()
    release_old_claim = threading.Event()
    old_claim_done = threading.Event()
    new_claim_entered = threading.Event()
    thread_state = threading.local()
    old_claim_results = []
    original_claim = store.claim_runnable
    original_transaction = store._transaction

    @contextmanager
    def hooked_transaction():
        if getattr(thread_state, "block_claim_transaction", False):
            blocked_transaction.set()
            if not release_old_claim.wait(5):
                raise TimeoutError("restart claim barrier was not released")
        with original_transaction() as connection:
            yield connection

    def hooked_claim(*args, **kwargs):
        block_this_claim = arm_claim.is_set() and not blocked_transaction.is_set()
        thread_state.block_claim_transaction = block_this_claim
        try:
            result = original_claim(*args, **kwargs)
            if block_this_claim:
                old_claim_results.append(result)
            return result
        finally:
            if block_this_claim:
                old_claim_done.set()
            thread_state.block_claim_transaction = False

    store._transaction = hooked_transaction  # type: ignore[method-assign]
    store.claim_runnable = hooked_claim  # type: ignore[method-assign]

    async def run() -> None:
        second_runtime: MockRuntime | None = None
        try:
            await first_runtime.start()
            await asyncio.wait_for(first_provider.second_call_started.wait(), timeout=3)
            interrupted = store.get_turn(OWNER, turn_id)
            assert interrupted.checkpoint.model_calls == 2
            assert interrupted.checkpoint.read_calls == 1
            assert len(interrupted.checkpoint.read_results) == 1
            saved_read_results = list(interrupted.record.bound_read_results)
            saved_entity_refs = list(interrupted.record.bound_references)

            # claim_runnable has already captured its lease clock when it enters
            # this barrier; the cancelled to_thread worker resumes only after the
            # next Runtime has recovered RUNNING back to QUEUED.
            arm_claim.set()
            assert await asyncio.to_thread(blocked_transaction.wait, 3)
            await first_runtime.close()
            assert not old_claim_done.is_set()

            second_runtime, second_provider = _runtime(store, _CountingProvider())
            await second_runtime.start()
            recovered = store.get_turn(OWNER, turn_id)
            assert recovered.record.turn.state == c.TurnState.QUEUED
            assert recovered.checkpoint.resume_step == c.TurnStep.MODEL_DECISION
            assert recovered.checkpoint.model_calls == 2
            assert recovered.checkpoint.read_calls == 1

            def announce_new_claim(*args, **kwargs):
                new_claim_entered.set()
                return hooked_claim(*args, **kwargs)

            store.claim_runnable = announce_new_claim  # type: ignore[method-assign]
            assert await asyncio.to_thread(new_claim_entered.wait, 3)
            release_old_claim.set()
            assert await asyncio.to_thread(old_claim_done.wait, 3)
            assert old_claim_results == [None]

            completed = await _wait_state(store, turn_id, {c.TurnState.COMPLETED})
            assert completed.checkpoint.model_calls == 3
            assert completed.checkpoint.read_calls == 1
            assert completed.checkpoint.read_results[0] == interrupted.checkpoint.read_results[0]
            assert completed.record.bound_read_results == saved_read_results
            assert completed.record.bound_references == saved_entity_refs
            assert second_provider.calls == 1
        finally:
            release_old_claim.set()
            if first_runtime._started:
                await first_runtime.close()
            if second_runtime is not None:
                await second_runtime.close()
            store.claim_runnable = original_claim  # type: ignore[method-assign]
            store._transaction = original_transaction  # type: ignore[method-assign]

    asyncio.run(run())
    store.close()


def test_store_close_waits_for_cancelled_claim_and_leaves_no_late_lease(tmp_path: Path) -> None:
    from contextlib import contextmanager

    path = tmp_path / "store-close-claim-race.sqlite3"
    store = SQLiteAgentStore(path, admission_enabled=True)
    store.start()
    session = persistence._session(store, OWNER)
    _, turn_id = persistence._submit(store, session, OWNER, text="queued for claim")

    worker_id = "p1-mock-runtime:store-close-race"
    cancellation = threading.Event()
    claim_entered_transaction = threading.Event()
    release_claim = threading.Event()
    close_started = threading.Event()
    thread_state = threading.local()
    original_transaction = store._transaction
    original_claim_transaction = store._claim_runnable_transaction

    @contextmanager
    def hooked_transaction():
        if getattr(thread_state, "claim_in_flight", False):
            claim_entered_transaction.set()
            if not release_claim.wait(5):
                raise TimeoutError("Store.close claim barrier was not released")
        with original_transaction() as connection:
            yield connection

    def hooked_claim_transaction(*args, **kwargs):
        thread_state.claim_in_flight = True
        try:
            return original_claim_transaction(*args, **kwargs)
        finally:
            thread_state.claim_in_flight = False

    store._transaction = hooked_transaction  # type: ignore[method-assign]
    store._claim_runnable_transaction = hooked_claim_transaction  # type: ignore[method-assign]
    executor = ThreadPoolExecutor(max_workers=2)
    claim_future = None
    close_future = None
    try:
        claim_future = executor.submit(
            store.claim_runnable, worker_id, cancellation_event=cancellation,
        )
        assert claim_entered_transaction.wait(3)

        cancellation.set()
        store.mark_claim_worker_retired(worker_id)

        def close_store() -> None:
            close_started.set()
            store.close()

        close_future = executor.submit(close_store)
        assert close_started.wait(3)
        # close must serialize behind the in-flight transaction, then perform its
        # retired-prefix cleanup before making the Store unavailable.
        assert not close_future.done()

        release_claim.set()
        assert claim_future.result(timeout=3) is None
        close_future.result(timeout=3)
    finally:
        release_claim.set()
        if claim_future is not None and not claim_future.done():
            claim_future.result(timeout=3)
        if close_future is not None and not close_future.done():
            close_future.result(timeout=3)
        store._transaction = original_transaction  # type: ignore[method-assign]
        store._claim_runnable_transaction = original_claim_transaction  # type: ignore[method-assign]
        executor.shutdown(wait=True)
        if store._started:
            store.close()

    reopened = SQLiteAgentStore(path, admission_enabled=True)
    reopened.start()
    try:
        persisted = reopened.get_turn(OWNER, turn_id)
        assert persisted.record.turn.state == c.TurnState.QUEUED
        assert persisted.claim_token is None
        assert persisted.claim_until is None
    finally:
        reopened.close()


def test_restart_reuses_saved_read_decision_instead_of_calling_model_again(tmp_path: Path) -> None:
    store = SQLiteAgentStore(tmp_path / "restart-tool-read.sqlite3", admission_enabled=True)
    store.start()
    session = persistence._session(store, OWNER)
    _, turn_id = persistence._submit(store, session, OWNER, text="查询消费")
    blocked_backend = _BlockingBackend()
    first_provider = _CountingProvider()
    first_runtime = MockRuntime(
        store, first_provider, blocked_backend, _Auth(), MockScopeAuthorizer(), _Control(),
    )
    first_runtime.bind_auth_grant(
        Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1)), "runtime-token",
    )

    async def run() -> None:
        await first_runtime.start()
        await asyncio.wait_for(blocked_backend.started.wait(), timeout=3)
        interrupted = store.get_turn(OWNER, turn_id)
        assert isinstance(interrupted.checkpoint.last_decision, c.ReadDecision)
        assert interrupted.checkpoint.resume_step == c.TurnStep.TOOL_READ
        assert interrupted.checkpoint.model_calls == 1
        assert interrupted.checkpoint.read_calls == 1
        await first_runtime.close()

        second_provider = _CountingProvider()
        second_runtime, _ = _runtime(store, second_provider)
        await second_runtime.start()
        try:
            completed = await _wait_state(store, turn_id, {c.TurnState.COMPLETED})
            assert completed.checkpoint.model_calls == 2
            assert completed.checkpoint.read_calls == 2
            assert second_provider.calls == 1
            assert len(completed.checkpoint.read_results) == 1
            assert completed.checkpoint.read_results[0].result_ref == c.ReadResultRef.R01
        finally:
            await second_runtime.close()

    asyncio.run(run())
    store.close()
