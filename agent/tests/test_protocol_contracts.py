from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError

from agent.app import contracts as c
from agent.app.export_contracts import _openapi, _validate_openapi_references
from agent.app.mock_fixtures import (
    ACTIVITY_ID,
    EXPENSE_ID,
    OWNER,
    PARTICIPANT_1,
    PARTICIPANT_2,
    SESSION,
    TURN,
    UNIT_ID,
    _id,
    build_mock_fixtures,
    fixture_json_bytes,
    model_context,
    references,
    tool_results,
)


NOW = datetime(2026, 10, 7, tzinfo=timezone.utc)


def _validate_trajectory(value: c.MockTrajectory) -> None:
    payload = fixture_json_bytes(value)
    schema = c.MockTrajectory.model_json_schema(mode="validation")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(json.loads(payload))
    assert c.MockTrajectory.model_validate_json(payload) == value


def test_all_mock_trajectories_pass_json_schema_and_source_protocol() -> None:
    fixtures = build_mock_fixtures()
    assert set(fixtures) == {
        "four_semantics",
        "read_then_answer",
        "clarify_auth_cancel_reference_stability",
        "propose_wait_confirm_confirm_disabled",
    }
    for trajectory in fixtures.values():
        _validate_trajectory(trajectory)
    for model in c.schema_catalog():
        Draft202012Validator.check_schema(model.model_json_schema(mode="validation"))


def test_read_trajectory_rejects_reordered_or_future_evidence() -> None:
    fixture = build_mock_fixtures()["read_then_answer"]
    with pytest.raises(ValidationError):
        c.MockTrajectory(
            scenario=fixture.scenario,
            steps=list(reversed(fixture.steps)),
        )

    future_context_steps = list(fixture.steps)
    final_model_step = future_context_steps[2]
    assert isinstance(final_model_step, c.ModelDecisionStep)
    early_read = future_context_steps[0]
    assert isinstance(early_read, c.ModelDecisionStep)
    future_context_steps[0] = early_read.model_copy(update={"context": final_model_step.context})
    with pytest.raises(ValidationError):
        c.MockTrajectory(scenario=fixture.scenario, steps=future_context_steps)


def test_proposal_fixture_binds_same_card_revision_and_turn() -> None:
    fixture = build_mock_fixtures()["propose_wait_confirm_confirm_disabled"]
    _validate_trajectory(fixture)
    altered_steps = list(fixture.steps)
    card_step_index = next(i for i, item in enumerate(altered_steps) if isinstance(item, c.ProposalCardStep))
    card_step = altered_steps[card_step_index]
    assert isinstance(card_step, c.ProposalCardStep)
    altered_card = card_step.card.model_copy(update={"revision": card_step.card.revision + 1})
    altered_steps[card_step_index] = card_step.model_copy(update={"card": altered_card})
    with pytest.raises(ValidationError):
        c.MockTrajectory(scenario=fixture.scenario, steps=altered_steps)


def test_fastapi_parsed_dict_and_json_request_paths_are_equivalent() -> None:
    requests: list[c.ContractModel] = [
        c.CreateSessionRequest(client_request_id=_id("request-create"), title="Trip"),
        c.SubmitTurnRequest(client_request_id=_id("request-submit"), text="查消费"),
        c.ResumeClarificationRequest(
            client_request_id=_id("request-clarify"), expected_state_revision=2, text="两人平摊。"
        ),
        c.ResumeAuthRequest(client_request_id=_id("request-auth"), expected_state_revision=3),
        c.ResumeProposalAdjustRequest(
            client_request_id=_id("request-adjust"),
            expected_state_revision=4,
            expected_proposal_revision=2,
            text="改成 15 元。",
        ),
        c.CancelTurnRequest(client_request_id=_id("request-cancel"), expected_state_revision=5),
        c.ConfirmProposalRequest(
            client_request_id=_id("request-confirm"),
            expected_proposal_revision=2,
            command_digest="a" * 64,
            confirmation_nonce="n" * 32,
        ),
    ]
    for request in requests:
        payload = request.model_dump(mode="json", by_alias=True)
        encoded = json.dumps(payload, ensure_ascii=False)
        adapter = TypeAdapter(type(request))
        from_json = adapter.validate_json(encoded)
        from_fastapi_dict = adapter.validate_python(json.loads(encoded), from_attributes=True)
        assert from_json == from_fastapi_dict == request

    submit_payload = requests[1].model_dump(mode="json")
    submit_payload["text"] = 3.5
    with pytest.raises(ValidationError):
        TypeAdapter(c.SubmitTurnRequest).validate_python(submit_payload, from_attributes=True)
    submit_payload = requests[1].model_dump(mode="json")
    submit_payload["actor_id"] = str(OWNER)
    with pytest.raises(ValidationError):
        TypeAdapter(c.SubmitTurnRequest).validate_python(submit_payload, from_attributes=True)


def test_semantic_boundary_is_closed_and_money_is_decimal_text() -> None:
    fixture = build_mock_fixtures()["four_semantics"]
    kinds = {step.decision.kind for step in fixture.steps if isinstance(step, c.ModelDecisionStep)}
    assert kinds == {"answer", "clarify", "read", "propose"}

    answer = {
        "kind": "answer",
        "basis": "grounded",
        "text": "ok",
        "citations": ["policy_fact_1"],
        "confirmed": True,
    }
    with pytest.raises(ValidationError):
        c.SEMANTIC_DECISION_ADAPTER.validate_python(answer)
    with pytest.raises(ValidationError):
        c.SEMANTIC_DECISION_ADAPTER.validate_python(
            {"kind": "propose", "operation": "expense.update_row_rpc", "fields": {}}
        )
    with pytest.raises(ValidationError):
        c.SEMANTIC_DECISION_ADAPTER.validate_python(
            {
                "kind": "answer",
                "basis": "grounded",
                "text": "See https://example.invalid",
                "citations": ["policy_fact_1"],
            }
        )

    refs = references()
    intent = c.ExpenseCreateIntent(
        kind="expense.create",
        ledger_unit_ref=next(r.ref for r in refs if r.kind == "ledger_unit"),
        title="Lunch",
        original_amount="12.50",
        original_currency="CNY",
        payment_allocations=[
            c.PaymentAllocation(
                participant_ref=next(r.ref for r in refs if r.kind == "participant"),
                amount="12.50",
            )
        ],
        split=c.EqualSplitIntent(
            mode="equal",
            participant_refs=[r.ref for r in refs if r.kind == "participant"],
        ),
    )
    structural_schema = c.ExpenseCreateIntent.model_json_schema(mode="validation")
    invalid_total: dict[str, Any] = intent.model_dump(mode="json")
    invalid_total["original_amount"] = "15.00"
    Draft202012Validator(structural_schema).validate(invalid_total)
    with pytest.raises(ValidationError):
        c.ExpenseCreateIntent.model_validate(invalid_total)
    invalid_float = dict(intent.model_dump(mode="json"), original_amount=12.5)
    with pytest.raises(ValidationError):
        c.ExpenseCreateIntent.model_validate(invalid_float)


def _persisted_context_bindings() -> tuple[
    c.ModelContext,
    list[c.BoundReference],
    list[c.BoundEvidenceReference],
    list[c.BoundReadResultReference],
]:
    refs = references()
    results = tool_results(refs)
    evidence_candidates: list[c.ResolvedEvidenceCandidate] = []
    for result in results:
        for fact in result.body.items:
            entity_id = {
                "activity": ACTIVITY_ID,
                "expense": EXPENSE_ID,
                "debt": _id("debt-fact"),
            }[fact.kind]
            evidence_candidates.append(
                c.ResolvedEvidenceCandidate(
                    kind=fact.kind,
                    entity_id=entity_id,
                    scope_activity_id=ACTIVITY_ID,
                    source_result_id=result.result_id,
                    context_version=result.context_version,
                )
            )
    evidence = c.bind_stable_evidence([], evidence_candidates, source_turn_id=TURN)
    result_bindings = c.bind_stable_read_results(
        [],
        [
            c.ResolvedReadResultCandidate(
                result_ref=result.result_ref,
                result_id=result.result_id,
                operation=result.operation,
                observed_at=result.observed_at,
                context_version=result.context_version,
            )
            for result in results
        ],
        source_turn_id=TURN,
    )
    return model_context(), refs, evidence, result_bindings


def test_model_context_refs_and_evidence_resolve_to_persisted_turn_bindings() -> None:
    context, refs, evidence, read_results = _persisted_context_bindings()
    c.validate_model_context_bindings(
        context,
        source_turn_id=TURN,
        bound_references=refs,
        bound_evidence_references=evidence,
        bound_read_results=read_results,
    )
    with pytest.raises(ValueError):
        c.validate_model_context_bindings(
            context,
            source_turn_id=_id("other-turn"),
            bound_references=refs,
            bound_evidence_references=evidence,
            bound_read_results=read_results,
        )
    with pytest.raises(ValueError):
        c.validate_model_context_bindings(
            context.model_copy(update={"bound_references": context.bound_references[:-1]}),
            source_turn_id=TURN,
            bound_references=refs,
            bound_evidence_references=evidence,
            bound_read_results=read_results,
        )
    reordered = c.bind_stable_read_results(
        read_results,
        [
            c.ResolvedReadResultCandidate(
                result_ref=item.result_ref,
                result_id=item.result_id,
                operation=item.operation,
                observed_at=item.observed_at,
                context_version=item.context_version,
            )
            for item in reversed(read_results)
        ],
        source_turn_id=TURN,
    )
    assert {item.result_id: item.result_ref for item in reordered} == {
        item.result_id: item.result_ref for item in read_results
    }
    first = read_results[0]
    with pytest.raises(ValueError):
        c.bind_stable_read_results(
            read_results,
            [
                c.ResolvedReadResultCandidate(
                    result_ref=first.result_ref,
                    result_id=first.result_id,
                    operation=first.operation,
                    observed_at=first.observed_at,
                    context_version=first.context_version + 1,
                )
            ],
            source_turn_id=TURN,
        )


def test_state_recovery_preserves_execution_identity_and_unknown_outcome() -> None:
    fixture = build_mock_fixtures()["clarify_auth_cancel_reference_stability"]
    for step in fixture.steps:
        if isinstance(step, c.ResumeAuthStep):
            c.validate_auth_resume(
                step.before,
                step.after,
                expected_state_revision=step.request.expected_state_revision,
            )
            if step.before.execution is not None:
                assert step.after.execution == step.before.execution
                assert step.after.execution_resolution == c.ExecutionResolution.UNKNOWN

    assert c.STATE_TRANSITIONS[c.TurnState.WAIT_CONFIRM.value].count(c.TurnState.WAIT_INPUT.value) == 1
    before_unknown = next(
        step.before for step in fixture.steps
        if isinstance(step, c.StateTransitionStep)
        and step.before.state == c.TurnState.RECOVERING
        and step.before.execution_resolution == c.ExecutionResolution.UNKNOWN
    )
    wrong_key = c.ExecutionIdentity(
        execution_id=c.derive_execution_id(OWNER, _id("different-proposal"), 1),
        actor_id=OWNER,
        proposal_id=_id("different-proposal"),
        proposal_revision=1,
    )
    with pytest.raises(ValueError):
        c.TurnStateSnapshot(
            turn_id=before_unknown.turn_id,
            session_id=SESSION,
            owner_user_id=OWNER,
            state=c.TurnState.FAILED,
            step=c.TurnStep.TERMINAL,
            state_revision=before_unknown.state_revision + 1,
            execution=before_unknown.execution,
            execution_resolution=c.ExecutionResolution.UNKNOWN,
            context_version=1,
        )

    with pytest.raises(ValueError):
        c.validate_state_transition(
            before_unknown,
            before_unknown.model_copy(
                update={
                    "state": c.TurnState.RECOVERING,
                    "state_revision": before_unknown.state_revision + 1,
                    "execution": wrong_key,
                }
            ),
            expected_state_revision=before_unknown.state_revision,
        )


def test_idempotency_hashes_context_and_replays_original_typed_response() -> None:
    request = c.SubmitTurnRequest(client_request_id=_id("idem"), text="查账")
    first_hash = c.canonical_payload_hash(c.ApiActionKind.TURN_SUBMIT, request, resource_id=SESSION)
    changed = request.model_copy(update={"text": "查另一笔账"})
    changed_hash = c.canonical_payload_hash(c.ApiActionKind.TURN_SUBMIT, changed, resource_id=SESSION)
    assert first_hash != changed_hash
    ui_context = c.UIContext(
        page_type=c.PageType.ACTIVITY_OVERVIEW,
        activity_id=ACTIVITY_ID,
        captured_at=NOW,
        client_version="1.0",
    )
    different_context = ui_context.model_copy(update={"activity_id": _id("other-activity")})
    with_context = request.model_copy(update={"ui_context": ui_context})
    with_other_context = request.model_copy(update={"ui_context": different_context})
    assert c.canonical_payload_hash(
        c.ApiActionKind.TURN_SUBMIT, with_context, resource_id=SESSION
    ) != c.canonical_payload_hash(c.ApiActionKind.TURN_SUBMIT, with_other_context, resource_id=SESSION)

    accepted = c.SubmitTurnAccepted(turn_id=TURN, state="QUEUED", accepted_at=NOW)
    receipt = c.RequestReceipt(
        key_scope=c.ApiActionKind.TURN_SUBMIT,
        owner_user_id=OWNER,
        resource_id=SESSION,
        client_request_id=request.client_request_id,
        payload_hash=first_hash,
        http_status=202,
        response_kind=c.RequestReceiptKind.TURN_ACCEPTED,
        response_snapshot=accepted,
        recorded_at=NOW,
    )
    assert c.validate_idempotent_replay(
        receipt,
        key_scope=c.ApiActionKind.TURN_SUBMIT,
        owner_user_id=OWNER,
        resource_id=SESSION,
        client_request_id=request.client_request_id,
        payload_hash=first_hash,
    ) is receipt
    with pytest.raises(ValueError):
        c.validate_idempotent_replay(
            receipt,
            key_scope=c.ApiActionKind.TURN_SUBMIT,
            owner_user_id=OWNER,
            resource_id=SESSION,
            client_request_id=request.client_request_id,
            payload_hash=changed_hash,
        )

    cancel_response = c.CancelTurnResponse(
        turn=c.TurnPublicStatus(
            turn_id=TURN,
            session_id=SESSION,
            state=c.TurnState.CANCELLED,
            step=c.TurnStep.TERMINAL,
            state_revision=2,
            execution_assigned=False,
            context_version=1,
        ),
        result="cancelled",
    )
    cancel_receipt = c.RequestReceipt(
        key_scope=c.ApiActionKind.TURN_CANCEL,
        owner_user_id=OWNER,
        resource_id=TURN,
        client_request_id=_id("cancel-receipt"),
        payload_hash="b" * 64,
        http_status=200,
        response_kind=c.RequestReceiptKind.TURN_CANCELLED,
        response_snapshot=cancel_response,
        recorded_at=NOW,
    )
    assert isinstance(cancel_receipt.response_snapshot, c.CancelTurnResponse)
    with pytest.raises(ValidationError):
        c.RequestReceipt(
            key_scope=c.ApiActionKind.TURN_CANCEL,
            owner_user_id=OWNER,
            resource_id=TURN,
            client_request_id=_id("cancel-receipt-wrong"),
            payload_hash="c" * 64,
            http_status=202,
            response_kind=c.RequestReceiptKind.TURN_RESUMED,
            response_snapshot=c.TurnMutationAccepted(
                turn_id=TURN,
                state=c.TurnState.CANCELLED,
                state_revision=2,
                event_cursor=3,
            ),
            recorded_at=NOW,
        )


def test_money_versions_nonce_and_preview_contracts_are_type_safe() -> None:
    assert c.FinancialVersion.__metadata__[0].pattern == c.FINANCIAL_VERSION_PATTERN
    assert c.ExpenseVersion.__metadata__[0].pattern == c.EXPENSE_VERSION_PATTERN
    assert c.FinancialVersion.__metadata__[0].pattern
    for bad in ("-1", "01", "9223372036854775808"):
        with pytest.raises(ValidationError):
            TypeAdapter(c.FinancialVersion).validate_python(bad)
    assert TypeAdapter(c.FinancialVersion).validate_python("0") == "0"

    card_schema = c.ConfirmableProposalCard.model_json_schema(mode="validation")
    request_schema = c.ConfirmProposalRequest.model_json_schema(mode="validation")
    assert card_schema["properties"]["confirmation_nonce"]["x-sensitive"] is True
    assert "writeOnly" not in card_schema["properties"]["confirmation_nonce"]
    assert request_schema["properties"]["confirmation_nonce"]["writeOnly"] is True
    assert "confirmation_nonce" not in c.ProposalEvent.model_fields
    assert "confirmation_nonce" not in c.ModelContext.model_fields

    card = build_mock_fixtures()["propose_wait_confirm_confirm_disabled"].steps
    preview = next(step.card.preview for step in card if isinstance(step, c.ProposalCardStep))
    preview_payload = preview.model_dump(mode="json")
    altered_changes = preview_payload["changes"]
    amount_change_index = next(i for i, item in enumerate(altered_changes) if item["field"] == "original_amount")
    altered_changes[amount_change_index]["after"] = "13.00"
    with pytest.raises(ValidationError):
        c.ExpensePreview.model_validate_json(json.dumps(preview_payload))
    with pytest.raises(ValidationError):
        c.CanonicalExpenseUpdatePatch(
            payment_allocations=[
                c.CanonicalPayment(participant_id=PARTICIPANT_1, amount="6.00"),
                c.CanonicalPayment(participant_id=PARTICIPANT_1, amount="6.50"),
            ]
        )


def test_command_digest_binds_command_preconditions_and_policy_versions() -> None:
    command = c.FixedExpenseCreateCommand(
        operation="expense.create",
        activity_id=ACTIVITY_ID,
        ledger_unit_id=UNIT_ID,
        title="Lunch",
        original_amount="12.50",
        original_currency="CNY",
        payment_allocations=[c.CanonicalPayment(participant_id=PARTICIPANT_1, amount="12.50")],
        split=c.CanonicalEqualSplit(mode="equal", participant_ids=[PARTICIPANT_1, PARTICIPANT_2]),
        expected_financial_version="0",
    )
    preconditions = c.PreconditionSnapshot(
        activity_id=ACTIVITY_ID,
        permission_checked=True,
        agent_disable_revision=0,
        activity_financial_version="0",
        policy_version="policy-v1",
        verified_at=NOW,
    )
    digest = c.canonical_command_digest(command, preconditions, policy_version="policy-v1")
    assert digest == c.canonical_command_digest(command, preconditions, policy_version="policy-v1")
    changed_command = command.model_copy(update={"title": "Dinner"})
    assert digest != c.canonical_command_digest(changed_command, preconditions, policy_version="policy-v1")
    changed_preconditions = preconditions.model_copy(update={"agent_disable_revision": 1})
    assert digest != c.canonical_command_digest(command, changed_preconditions, policy_version="policy-v1")
    assert digest != c.canonical_command_digest(command, preconditions, policy_version="policy-v2")


def test_capability_registry_and_openapi_are_complete_and_interoperable() -> None:
    c.validate_capability_registry(c.CAPABILITY_REGISTRY)
    assert len(c.CAPABILITY_REGISTRY) == 17
    assert all(entry.execution_enabled is False for entry in c.CAPABILITY_REGISTRY)
    document = _openapi()
    _validate_openapi_references(document)
    components = document["components"]["schemas"]
    assert "ApiErrorResponse" in components
    assert document["paths"]["/v1/turns/{turn_id}/events"]["get"]["responses"].get("200")
    confirm_responses = document["paths"]["/v1/proposals/{proposal_id}/confirm"]["post"]["responses"]
    assert "501" in confirm_responses and "202" not in confirm_responses
