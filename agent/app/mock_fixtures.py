"""Small deterministic offline trajectories built only from protocol source models."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from . import contracts as c


NOW = datetime(2026, 10, 7, 0, 0, tzinfo=timezone.utc)


def _id(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, "shared-ledger-agent:p1-01:" + name)


OWNER = _id("owner")
SESSION = _id("session")
TURN = _id("turn")
ACTIVITY_ID = _id("activity")
UNIT_ID = _id("ledger-unit")
EXPENSE_ID = _id("expense")
PARTICIPANT_1 = _id("participant-1")
PARTICIPANT_2 = _id("participant-2")
PROPOSAL_ID = _id("proposal")

PERMISSIONS = [
    c.HarnessPermission.READ_ACTIVITIES,
    c.HarnessPermission.READ_EXPENSES,
    c.HarnessPermission.READ_DEBTS,
    c.HarnessPermission.PROPOSE_EXPENSE_CREATE,
    c.HarnessPermission.PROPOSE_EXPENSE_UPDATE,
    c.HarnessPermission.PROPOSE_EXPENSE_PRESENTATION_UPDATE,
]


def references(turn_id: uuid.UUID = TURN) -> list[c.BoundReference]:
    candidates = [
        c.ResolvedEntityCandidate(kind=c.UiEntityType.ACTIVITY, entity_id=ACTIVITY_ID, scope_activity_id=ACTIVITY_ID),
        c.ResolvedEntityCandidate(kind=c.UiEntityType.LEDGER_UNIT, entity_id=UNIT_ID, scope_activity_id=ACTIVITY_ID),
        c.ResolvedEntityCandidate(kind=c.UiEntityType.EXPENSE, entity_id=EXPENSE_ID, scope_activity_id=ACTIVITY_ID),
        c.ResolvedEntityCandidate(kind=c.UiEntityType.PARTICIPANT, entity_id=PARTICIPANT_1, scope_activity_id=ACTIVITY_ID),
        c.ResolvedEntityCandidate(kind=c.UiEntityType.PARTICIPANT, entity_id=PARTICIPANT_2, scope_activity_id=ACTIVITY_ID),
    ]
    return c.bind_stable_references([], candidates, source_turn_id=turn_id)


def _token(refs: list[c.BoundReference], kind: str, entity_id: uuid.UUID) -> Any:
    item = next(entry for entry in refs if entry.kind == kind and entry.entity_id == entity_id)
    return item.ref


def tool_results(refs: list[c.BoundReference]) -> list[c.ToolReadResult]:
    activity_ref = _token(refs, "activity", ACTIVITY_ID)
    expense_ref = _token(refs, "expense", EXPENSE_ID)
    participant_1_ref = _token(refs, "participant", PARTICIPANT_1)
    participant_2_ref = _token(refs, "participant", PARTICIPANT_2)
    return [
        c.ToolReadResult(
            result_id=_id("result-activities"),
            result_ref=c.ReadResultRef.R01,
            operation=c.ReadOperation.ACTIVITIES,
            observed_at=NOW,
            context_version=1,
            simulation=True,
            body=c.ActivityListResult(
                kind="activities",
                items=[
                    c.ActivityFact(
                        kind="activity",
                        evidence_ref=c.ActivityEvidenceRef.F01,
                        activity_ref=activity_ref,
                        name="Trip",
                        activity_kind=c.ActivityKind.NORMAL,
                        base_currency="CNY",
                        status=c.ActivityStatus.ACTIVE,
                        observed_at=NOW,
                        context_version=1,
                    )
                ],
            ),
        ),
        c.ToolReadResult(
            result_id=_id("result-expenses"),
            result_ref=c.ReadResultRef.R02,
            operation=c.ReadOperation.EXPENSES,
            observed_at=NOW,
            context_version=1,
            simulation=True,
            body=c.ExpenseListResult(
                kind="expenses",
                items=[
                    c.ExpenseFact(
                        kind="expense",
                        evidence_ref=c.ExpenseEvidenceRef.F01,
                        expense_ref=expense_ref,
                        title="Lunch",
                        original_amount="12.50",
                        original_currency="CNY",
                        occurred_at=NOW,
                        participant_refs=[participant_1_ref, participant_2_ref],
                        financial_locked=False,
                        expense_version="1",
                        observed_at=NOW,
                        context_version=1,
                    )
                ],
            ),
        ),
        c.ToolReadResult(
            result_id=_id("result-debts"),
            result_ref=c.ReadResultRef.R03,
            operation=c.ReadOperation.DEBTS,
            observed_at=NOW,
            context_version=1,
            simulation=True,
            body=c.DebtListResult(
                kind="debts",
                items=[
                    c.DebtFact(
                        kind="debt",
                        evidence_ref=c.DebtEvidenceRef.F01,
                        debtor_ref=participant_1_ref,
                        creditor_ref=participant_2_ref,
                        amount="6.25",
                        currency="CNY",
                        observed_at=NOW,
                        context_version=1,
                    )
                ],
            ),
        ),
    ]


def model_results(results: list[c.ToolReadResult]) -> list[c.ModelReadResult]:
    return [
        c.ModelReadResult(
            result_ref=item.result_ref,
            operation=item.operation,
            observed_at=item.observed_at,
            context_version=item.context_version,
            simulation=item.simulation,
            body=item.body,
        )
        for item in results
    ]


def model_context(turn_id: uuid.UUID = TURN) -> c.ModelContext:
    refs = references(turn_id)
    results = tool_results(refs)
    return c.ModelContext(
        context_version=1,
        input_text="查一下这笔消费并记录午餐",
        verified_scope=c.ModelActivityScope(
            kind="activity",
            activity_ref=_token(refs, "activity", ACTIVITY_ID),
            permissions=PERMISSIONS,
        ),
        recent_messages=[],
        pending_slots=[],
        bound_references=c.model_reference_tokens(refs),
        read_results=model_results(results),
        policy_evidence=[
            c.PolicyEvidence(
                evidence_ref=c.PolicyEvidenceRef.P01,
                rule=c.PolicyRule.EXECUTION_CONFIRMATION,
                source=c.PolicySource.DEVELOPMENT_GUIDE,
                version="guide-v0.4.2",
                text="写入提议必须由用户确认；模型不能确认或直接写入。",
                observed_at=NOW,
            )
        ],
        available_permissions=PERMISSIONS,
    )


def _expense_create(refs: list[c.BoundReference]) -> c.ExpenseCreateIntent:
    participant_1_ref = _token(refs, "participant", PARTICIPANT_1)
    participant_2_ref = _token(refs, "participant", PARTICIPANT_2)
    return c.ExpenseCreateIntent(
        kind="expense.create",
        ledger_unit_ref=_token(refs, "ledger_unit", UNIT_ID),
        title="Lunch",
        original_amount="12.50",
        original_currency="CNY",
        payment_allocations=[c.PaymentAllocation(participant_ref=participant_1_ref, amount="12.50")],
        split=c.EqualSplitIntent(mode="equal", participant_refs=[participant_1_ref, participant_2_ref]),
        occurred_at=NOW,
    )


def _expense_snapshot() -> c.ExpenseSnapshot:
    return c.ExpenseSnapshot(
        ledger_unit_id=UNIT_ID,
        title="Lunch",
        original_amount="12.50",
        original_currency="CNY",
        base_amount="12.50",
        payment_allocations=[c.CanonicalPayment(participant_id=PARTICIPANT_1, amount="12.50")],
        split=c.CanonicalEqualSplit(mode="equal", participant_ids=[PARTICIPANT_1, PARTICIPANT_2]),
        occurred_at=NOW,
        expense_version="1",
        financial_locked=False,
    )


def four_semantics() -> c.MockTrajectory:
    refs = references()
    context = model_context()
    activity_ref = _token(refs, "activity", ACTIVITY_ID)
    expense_ref = _token(refs, "expense", EXPENSE_ID)
    participant_1_ref = _token(refs, "participant", PARTICIPANT_1)
    participant_2_ref = _token(refs, "participant", PARTICIPANT_2)
    decisions = [
        c.AnswerDecision(
            kind="answer",
            basis="grounded",
            text="确认操作前需要用户确认。",
            citations=[c.PolicyEvidenceRef.P01],
        ),
        c.ClarifyDecision(
            kind="clarify",
            prompt="请补充付款人和分摊参与人。",
            missing_slots=[c.ClarificationSlot.PAYMENT_ALLOCATIONS, c.ClarificationSlot.SPLIT_PARTICIPANTS],
        ),
        c.ReadDecision(
            kind="read",
            operation=c.ReadOperation.EXPENSES,
            criteria=c.ReadExpensesCriteria(kind="expenses", activity_ref=activity_ref),
        ),
        c.ProposeDecision(kind="propose", operation="expense.create", fields=_expense_create(refs)),
        c.ProposeDecision(
            kind="propose",
            operation="expense.update",
            fields=c.ExpenseUpdateIntent(
                kind="expense.update",
                expense_ref=expense_ref,
                original_amount="15.00",
                payment_allocations=[
                    c.PaymentAllocation(participant_ref=participant_1_ref, amount="15.00")
                ],
                split=c.EqualSplitIntent(
                    mode="equal",
                    participant_refs=[participant_1_ref, participant_2_ref],
                ),
            ),
        ),
        c.ProposeDecision(
            kind="propose",
            operation="expense.presentation.update",
            fields=c.ExpensePresentationUpdateIntent(
                kind="expense.presentation.update",
                expense_ref=expense_ref,
                note="录入备注修正",
            ),
        ),
    ]
    return c.MockTrajectory(
        scenario=c.MockScenario.FOUR_SEMANTICS,
        simulation=True,
        steps=[c.ModelDecisionStep(kind="model_decision", context=context, decision=item) for item in decisions],
    )


def read_then_answer() -> c.MockTrajectory:
    result = tool_results(references())[1]
    context_before = model_context()
    context_before = context_before.model_copy(update={"read_results": []})
    context_after = context_before.model_copy(update={"read_results": model_results([result])})
    return c.MockTrajectory(
        scenario=c.MockScenario.READ_THEN_ANSWER,
        simulation=True,
        steps=[
            c.ModelDecisionStep(
                kind="model_decision",
                context=context_before,
                decision=c.ReadDecision(
                    kind="read",
                    operation=c.ReadOperation.EXPENSES,
                    criteria=c.ReadExpensesCriteria(kind="expenses", activity_ref=c.ActivityRef.A01),
                ),
            ),
            c.ReadResultStep(kind="read_result", result=result),
            c.ModelDecisionStep(
                kind="model_decision",
                context=context_after,
                decision=c.AnswerDecision(
                    kind="answer",
                    basis="grounded",
                    text="消费金额是 12.50 CNY。",
                    citations=[c.ExpenseEvidenceRef.F01],
                ),
            ),
        ],
    )


def _snapshot(
    state: c.TurnState,
    revision: int,
    step: c.TurnStep,
    *,
    turn_id: uuid.UUID = TURN,
    wait_reason: c.Optional[c.WaitReason] = None,
    resume_state: c.Optional[c.ResumeState] = None,
    execution: c.Optional[c.ExecutionIdentity] = None,
    resolution: c.Optional[c.ExecutionResolution] = None,
) -> c.TurnStateSnapshot:
    return c.TurnStateSnapshot(
        turn_id=turn_id,
        session_id=SESSION,
        owner_user_id=OWNER,
        state=state,
        step=step,
        wait_reason=wait_reason,
        resume_state=resume_state,
        state_revision=revision,
        execution=execution,
        execution_resolution=resolution,
        context_version=1,
    )


def _public(snapshot: c.TurnStateSnapshot) -> c.TurnPublicStatus:
    return c.TurnPublicStatus(
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


def clarify_auth_cancel_and_reference_stability() -> c.MockTrajectory:
    turn_id = TURN
    refs = references(turn_id)
    selected_activity = next(item for item in refs if item.kind == "activity")
    context = model_context(turn_id)
    waiting_for_fields = _snapshot(
        c.TurnState.WAIT_INPUT,
        1,
        c.TurnStep.AWAITING_USER,
        wait_reason=c.WaitReason.MISSING_FIELDS,
        resume_state=c.ResumeState.RUNNING,
    )
    planning_after_text = _snapshot(c.TurnState.RUNNING, 2, c.TurnStep.BUILD_CONTEXT)
    wait_confirm = _snapshot(
        c.TurnState.WAIT_CONFIRM,
        3,
        c.TurnStep.AWAITING_USER,
        wait_reason=c.WaitReason.CONFIRM_REQUIRED,
    )
    auth_wait_from_confirm = _snapshot(
        c.TurnState.WAIT_INPUT,
        4,
        c.TurnStep.AUTH_REQUIRED,
        wait_reason=c.WaitReason.AUTH_REQUIRED,
        resume_state=c.ResumeState.WAIT_CONFIRM,
    )
    restored_confirm = _snapshot(
        c.TurnState.WAIT_CONFIRM,
        5,
        c.TurnStep.AWAITING_USER,
        wait_reason=c.WaitReason.CONFIRM_REQUIRED,
    )
    execution = c.ExecutionIdentity(
        execution_id=c.derive_execution_id(OWNER, PROPOSAL_ID, 1),
        actor_id=OWNER,
        proposal_id=PROPOSAL_ID,
        proposal_revision=1,
    )
    executing = _snapshot(c.TurnState.EXECUTING, 6, c.TurnStep.DISPATCH, execution=execution)
    unknown = _snapshot(
        c.TurnState.RECOVERING,
        7,
        c.TurnStep.RECONCILE,
        execution=execution,
        resolution=c.ExecutionResolution.UNKNOWN,
    )
    auth_wait_from_unknown = _snapshot(
        c.TurnState.WAIT_INPUT,
        8,
        c.TurnStep.AUTH_REQUIRED,
        wait_reason=c.WaitReason.AUTH_REQUIRED,
        resume_state=c.ResumeState.RECOVERING,
        execution=execution,
        resolution=c.ExecutionResolution.UNKNOWN,
    )
    restored_unknown = _snapshot(
        c.TurnState.RECOVERING,
        9,
        c.TurnStep.RECONCILE,
        execution=execution,
        resolution=c.ExecutionResolution.UNKNOWN,
    )

    cancel_turn = _id("cancel-turn")
    cancel_before = _snapshot(c.TurnState.RUNNING, 1, c.TurnStep.TOOL_READ, turn_id=cancel_turn)
    cancel_after = _snapshot(c.TurnState.CANCELLED, 2, c.TurnStep.TERMINAL, turn_id=cancel_turn)
    cancel_response = c.CancelTurnResponse(
        turn=_public(cancel_after),
        result="cancelled",
    )
    return c.MockTrajectory(
        scenario=c.MockScenario.CLARIFY_AUTH_CANCEL_AND_REFERENCE_STABILITY,
        simulation=True,
        steps=[
            c.ModelDecisionStep(
                kind="model_decision",
                context=context,
                decision=c.ClarifyDecision(
                    kind="clarify",
                    prompt="请告诉我付款人和分摊对象。",
                    missing_slots=[c.ClarificationSlot.PAYMENT_ALLOCATIONS, c.ClarificationSlot.SPLIT_PARTICIPANTS],
                ),
            ),
            c.ResumeClarificationStep(
                kind="resume_clarification",
                request=c.ResumeClarificationRequest(
                    client_request_id=_id("clarify-request"),
                    expected_state_revision=1,
                    text="我付了 12.50 元，两人平摊。",
                ),
                response=c.TurnMutationAccepted(
                    turn_id=turn_id,
                    state=c.TurnState.RUNNING,
                    state_revision=2,
                    event_cursor=3,
                ),
                before=waiting_for_fields,
                after=planning_after_text,
            ),
            c.StateTransitionStep(
                kind="state_transition",
                before=planning_after_text,
                after=wait_confirm,
                expected_state_revision=2,
            ),
            c.StateTransitionStep(
                kind="state_transition",
                before=wait_confirm,
                after=auth_wait_from_confirm,
                expected_state_revision=3,
            ),
            c.ResumeAuthStep(
                kind="resume_auth",
                request=c.ResumeAuthRequest(client_request_id=_id("auth-confirm-request"), expected_state_revision=4),
                response=c.TurnMutationAccepted(
                    turn_id=turn_id,
                    state=c.TurnState.WAIT_CONFIRM,
                    state_revision=5,
                    event_cursor=4,
                ),
                before=auth_wait_from_confirm,
                after=restored_confirm,
            ),
            c.StateTransitionStep(
                kind="state_transition",
                before=restored_confirm,
                after=executing,
                expected_state_revision=5,
            ),
            c.StateTransitionStep(
                kind="state_transition",
                before=executing,
                after=unknown,
                expected_state_revision=6,
            ),
            c.StateTransitionStep(
                kind="state_transition",
                before=unknown,
                after=auth_wait_from_unknown,
                expected_state_revision=7,
            ),
            c.ResumeAuthStep(
                kind="resume_auth",
                request=c.ResumeAuthRequest(client_request_id=_id("auth-unknown-request"), expected_state_revision=8),
                response=c.TurnMutationAccepted(
                    turn_id=turn_id,
                    state=c.TurnState.RECOVERING,
                    state_revision=9,
                    event_cursor=5,
                ),
                before=auth_wait_from_unknown,
                after=restored_unknown,
            ),
            c.CancelStep(
                kind="cancel",
                request=c.CancelTurnRequest(client_request_id=_id("cancel-request"), expected_state_revision=1),
                response=cancel_response,
                before=cancel_before,
                after=cancel_after,
            ),
            c.ReferenceAssertionStep(
                kind="reference_assertion",
                reference=selected_activity,
                after_resume=selected_activity,
                after_restart=selected_activity,
            ),
        ],
    )


def propose_wait_confirm_and_confirm_disabled() -> c.MockTrajectory:
    refs = references()
    context = model_context()
    after = _expense_snapshot()
    preview = c.ExpensePreview(
        kind="expense",
        summary="新增午餐消费 12.50 CNY",
        before=None,
        after=after,
        changes=[
            c.ExpenseTitleChange(field="title", before=None, after="Lunch"),
            c.ExpenseAmountChange(field="original_amount", before=None, after="12.50"),
            c.ExpenseAmountChange(field="base_amount", before=None, after="12.50"),
            c.ExpenseCurrencyChange(field="original_currency", before=None, after="CNY"),
            c.ExpenseLedgerUnitChange(field="ledger_unit_id", before=None, after=UNIT_ID),
            c.ExpensePaymentsChange(
                field="payment_allocations",
                before=None,
                after=[c.CanonicalPayment(participant_id=PARTICIPANT_1, amount="12.50")],
            ),
            c.ExpenseSplitChange(
                field="split",
                before=None,
                after=c.CanonicalEqualSplit(mode="equal", participant_ids=[PARTICIPANT_1, PARTICIPANT_2]),
            ),
            c.ExpenseOccurredAtChange(field="occurred_at", before=None, after=NOW),
        ],
        activity_financial_version="0",
        generated_at=NOW,
        simulation=True,
    )
    card = c.SimulationProposalCard(
        card_kind="simulation_pending",
        mode="simulation",
        status="pending",
        proposal_id=PROPOSAL_ID,
        revision=1,
        operation="expense.create",
        preview=preview,
        simulation=True,
    )
    before = _snapshot(c.TurnState.RUNNING, 1, c.TurnStep.PREPARE_PROPOSAL)
    after_wait = _snapshot(
        c.TurnState.WAIT_CONFIRM,
        2,
        c.TurnStep.AWAITING_USER,
        wait_reason=c.WaitReason.CONFIRM_REQUIRED,
    )
    return c.MockTrajectory(
        scenario=c.MockScenario.PROPOSE_WAIT_CONFIRM_AND_CONFIRM_DISABLED,
        simulation=True,
        steps=[
            c.ModelDecisionStep(
                kind="model_decision",
                context=context,
                decision=c.ProposeDecision(
                    kind="propose",
                    operation="expense.create",
                    fields=_expense_create(refs),
                ),
            ),
            c.StateTransitionStep(
                kind="state_transition",
                before=before,
                after=after_wait,
                expected_state_revision=1,
            ),
            c.AgentEventStep(
                kind="event",
                turn_id=TURN,
                event=c.StatusEvent(
                    type="status",
                    seq=1,
                    occurred_at=NOW,
                    simulation=True,
                    payload=c.StatusEventPayload(
                        state=c.TurnState.WAIT_CONFIRM,
                        step=c.TurnStep.AWAITING_USER,
                        state_revision=2,
                        wait_reason=c.WaitReason.CONFIRM_REQUIRED,
                    ),
                ),
            ),
            c.AgentEventStep(
                kind="event",
                turn_id=TURN,
                event=c.ProposalEvent(
                    type="proposal",
                    seq=2,
                    occurred_at=NOW,
                    simulation=True,
                    payload=c.ProposalEventPayload(
                        proposal_id=PROPOSAL_ID,
                        revision=1,
                        operation="expense.create",
                    ),
                ),
            ),
            c.ProposalCardStep(kind="proposal_card", turn_id=TURN, card=card),
            c.ConfirmDisabledStep(
                kind="confirm_disabled",
                turn_id=TURN,
                proposal_id=PROPOSAL_ID,
                request=c.ConfirmProposalRequest(
                    client_request_id=_id("confirm-disabled-request"),
                    expected_proposal_revision=1,
                    command_digest="a" * 64,
                    confirmation_nonce="N" * 32,
                ),
                response=c.ConfirmationUnavailableResponse(
                    code="execution_capability_unavailable",
                    message="P1-01 does not enable confirmation or business execution.",
                ),
            ),
        ],
    )


def build_mock_fixtures() -> dict[str, c.MockTrajectory]:
    return {
        "four_semantics": four_semantics(),
        "read_then_answer": read_then_answer(),
        "clarify_auth_cancel_reference_stability": clarify_auth_cancel_and_reference_stability(),
        "propose_wait_confirm_confirm_disabled": propose_wait_confirm_and_confirm_disabled(),
    }


def fixture_json_bytes(trajectory: c.MockTrajectory) -> bytes:
    value = trajectory.model_dump(mode="json")
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
