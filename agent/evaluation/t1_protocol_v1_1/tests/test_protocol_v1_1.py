from __future__ import annotations

import copy
import hashlib
import json
import uuid
from dataclasses import replace
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import pytest

from evaluation.t1_protocol_v1_1 import v1_contracts as v1
from evaluation.t1_protocol_v1_1.contracts import (
    AnswerDecision,
    NegotiatedVersions,
    ProtocolVersionTuple,
    QueryEvidenceRef,
    QuerySource,
    ReadDecision,
    ReadExpensesCriteria,
    _fact_matches,
    parse_decision,
)
from evaluation.t1_protocol_v1_1.examples import make_synthetic_example
from evaluation.t1_protocol_v1_1.harness import (
    CurrentQueryState,
    PageReceipt,
    _validate_page_receipts,
    bind_trusted_query,
    render_fact_answer,
    render_policy_answer,
    render_query_answer,
    row_identity_digest,
    validate_context_bindings,
    validate_decision,
)
from evaluation.t1_protocol_v1_1.protocol_registry import (
    build_dataset_applicability_policy,
    build_protocol_registry,
    validate_dataset_applicability_policy,
    validate_protocol_registry,
)
from evaluation.t1_protocol_v1_1.trajectory import T1TrajectoryV11
from evaluation.t1_protocol_v1_1 import export_protocol
from evaluation.t1_protocol_v1_1.export_protocol import build_protocol_schemas
from jsonschema import Draft202012Validator


def _current_state(binding, owner, turn, *, revision: int, status: str) -> CurrentQueryState:
    return CurrentQueryState(
        query_ref=binding.query_ref,
        result_id=binding.result_id,
        owner_id=owner,
        source_turn_id=turn,
        generation=binding.generation,
        expected_revision=binding.expected_revision,
        freshness_epoch=binding.freshness_epoch,
        current_generation=binding.generation,
        current_revision=revision,
        current_freshness_epoch=binding.freshness_epoch,
        status=status,
        scope_activity_id=binding.scope_activity_id,
        context_version=binding.context_version,
        source=binding.source,
        source_version=binding.source_version,
        source_fingerprint=binding.source_fingerprint,
        source_snapshot_fingerprint=binding.source_snapshot_fingerprint,
        observed_at=binding.observed_at,
        query_digest=binding.query_digest,
        body_digest=binding.body_digest,
    )


def _merge_two_same_turn_expense_reads(*, both_current: bool = False):
    owner = uuid.UUID("11111111-1111-4111-8111-111111111111")
    turn = uuid.UUID("22222222-2222-4222-8222-222222222222")
    activity_id = uuid.UUID("33333333-3333-4333-8333-333333333333")
    participant_id = uuid.UUID("44444444-4444-4444-8444-444444444444")
    first = make_synthetic_example(
        "expenses_postfilter_empty",
        fixture_key="same-turn-old",
        query_ref_override=QueryEvidenceRef.Q03,
        result_ref_override=v1.ReadResultRef.R01,
        context_version=1,
        observed_at=datetime(2026, 10, 10, 10, tzinfo=timezone.utc),
        source_version="synthetic-source-old",
        expected_revision=1,
        owner_id_override=owner,
        turn_id_override=turn,
        activity_id_override=activity_id,
        participant_id_override=participant_id,
        titles=["Rail old result"],
    )
    second = make_synthetic_example(
        "expenses_postfilter_empty",
        fixture_key="same-turn-latest",
        query_ref_override=QueryEvidenceRef.Q04,
        result_ref_override=v1.ReadResultRef.R02,
        context_version=2,
        observed_at=datetime(2026, 10, 11, 11, tzinfo=timezone.utc),
        source_version="synthetic-source-latest",
        expected_revision=2,
        owner_id_override=owner,
        turn_id_override=turn,
        activity_id_override=activity_id,
        participant_id_override=participant_id,
        expense_ref_offset=5,
        titles=["Rail latest result"],
    )
    refs_by_key = {}
    for ref in first.bound_references + second.bound_references:
        key = (ref.kind, ref.ref)
        if key in refs_by_key:
            assert refs_by_key[key].entity_id == ref.entity_id
        else:
            refs_by_key[key] = ref
    references = list(refs_by_key.values())
    context = type(first.context)(
        context_version=2,
        intent_classification="business",
        input_text=second.context.input_text,
        verified_scope=second.context.verified_scope,
        recent_messages=[],
        pending_slots=[],
        bound_references=v1.model_reference_tokens(references),
        read_results=first.context.read_results + second.context.read_results,
        policy_evidence=[],
        available_permissions=second.context.available_permissions,
        query_observations=first.context.query_observations + second.context.query_observations,
    )
    results = [first.actual_result, second.actual_result]
    bindings = [first.binding, second.binding]
    current_states = [
        _current_state(first.binding, owner, turn, revision=2, status="current" if both_current else "stale"),
        _current_state(second.binding, owner, turn, revision=2, status="current"),
    ]
    read_bindings = first.bound_read_results + second.bound_read_results
    query_set = validate_context_bindings(
        context,
        current_owner_id=owner,
        current_turn_id=turn,
        generation=1,
        expected_revision=2,
        freshness_epoch=1,
        current_context_version=2,
        current_query_states=current_states,
        trusted_tool_results=results,
        bound_queries=bindings,
        bound_references=references,
        bound_evidence_references=first.bound_evidence_references + second.bound_evidence_references,
        bound_read_results=read_bindings,
    )
    return context, query_set, first, second


def test_three_complete_synthetic_examples_distinguish_backend_and_postfilter_zero():
    from evaluation.t1_protocol_v1_1.examples import build_three_complete_examples

    examples = build_three_complete_examples()
    assert len(examples) == 3
    outputs = []
    for example in examples:
        validated = example.validate()
        answer = render_query_answer(validated, expected_context=example.context)
        validate_decision(answer, example.context, validated_queries=validated)
        outputs.append(answer.text)
    assert "backend result contained 0 items" in outputs[0]
    assert "backend result contained 0 items" in outputs[1]
    assert "all 5 backend items were checked" in outputs[2]
    assert examples[2].context.query_observations[0].returned_count == 5
    assert examples[2].context.query_observations[0].matched_count == 0


def test_partial_empty_is_not_rendered_as_no_match():
    example = make_synthetic_example("expenses_postfilter_empty", partial=True)
    answer = render_query_answer(example.validate())
    assert answer.text.startswith("Partial expenses query:")
    assert "No expenses matched" not in answer.text


def test_same_turn_two_versions_retain_old_stale_but_only_latest_is_citable():
    context, validated, old, latest = _merge_two_same_turn_expense_reads()
    assert len(context.query_observations) == 2
    assert len(validated.queries) == 1
    assert validated.queries[0].observation.query_ref == QueryEvidenceRef.Q04
    rendered = render_query_answer(validated, expected_context=context)
    assert rendered.citations == [QueryEvidenceRef.Q04]
    validate_decision(rendered, context, validated_queries=validated)
    with pytest.raises(ValueError):
        render_query_answer(validated, [QueryEvidenceRef.Q03], expected_context=context)
    old_fact = old.actual_result.body.items[0].evidence_ref
    fabricated_amount_claim = AnswerDecision(
        kind="answer", basis="grounded", text="The old expense was 1.00 CAD.", citations=[old_fact]
    )
    with pytest.raises(ValueError):
        validate_decision(fabricated_amount_claim, context, validated_queries=validated)


def test_two_independently_current_queries_keep_their_own_context_versions():
    context, validated, _old, _latest = _merge_two_same_turn_expense_reads(both_current=True)
    assert len(validated.queries) == 2
    assert [item.binding.context_version for item in validated.queries] == [1, 2]
    rendered = render_query_answer(validated, expected_context=context)
    assert rendered.citations == [QueryEvidenceRef.Q03, QueryEvidenceRef.Q04]
    validate_decision(rendered, context, validated_queries=validated)


def test_query_set_cannot_be_reused_for_another_context_with_same_tokens():
    example = make_synthetic_example("expenses_postfilter_empty")
    validated = example.validate()
    other = example.context.model_copy(deep=True)
    other.input_text = "Different original user input."
    answer = render_query_answer(validated)
    with pytest.raises(ValueError):
        validate_decision(answer, other, validated_queries=validated)


def test_source_issuer_rejects_future_p2_label_and_false_simulation():
    example = make_synthetic_example("empty_activities")
    binding = example.binding
    kwargs = dict(
        query_ref=binding.query_ref,
        owner_id=binding.owner_id,
        turn_id=binding.source_turn_id,
        generation=binding.generation,
        expected_revision=binding.expected_revision,
        freshness_epoch=binding.freshness_epoch,
        scope_activity_id=binding.scope_activity_id,
        result=example.actual_result,
        criteria=binding.criteria,
        context_version=binding.context_version,
        source_version=binding.source_version,
        source_fingerprint=binding.source_fingerprint,
        source_snapshot=binding.source_snapshot,
        page=binding.page,
        page_receipts=binding.page_receipts,
    )
    with pytest.raises(ValueError):
        bind_trusted_query(**kwargs, source=QuerySource.P2_T1_ADAPTER)
    with pytest.raises(ValueError):
        bind_trusted_query(**{**kwargs, "result": example.actual_result.model_copy(update={"simulation": False})}, source=QuerySource.SYNTHETIC_SIMULATION)


def test_page_receipt_deduplicates_stable_entity_identity_not_fact_body_hash():
    digest_a = "a" * 64
    digest_b = "b" * 64
    row = row_identity_digest("expense", uuid.UUID("33333333-3333-4333-8333-333333333333"))
    cursor = "c" * 64
    common = dict(source_version="v1", snapshot_fingerprint=digest_a, scope_fingerprint=digest_b, total_count=2)
    pages = [
        PageReceipt(page_index=0, offset=0, item_digests=[digest_a], row_identity_digests=[row], range_start=0, range_end_exclusive=1, cursor_out_digest=cursor, **common),
        PageReceipt(page_index=1, offset=1, item_digests=[digest_b], row_identity_digests=[row], range_start=1, range_end_exclusive=2, cursor_in_digest=cursor, **common),
    ]
    page = make_synthetic_example("expenses_postfilter_empty").binding.page.model_copy(update={"pages_seen": 2, "expected_total": 2})
    with pytest.raises(ValueError, match="identities must be unique"):
        _validate_page_receipts(
            page, pages, expected_source_version="v1", expected_scope_fingerprint=digest_b,
            expected_snapshot_fingerprint=digest_a,
        )


def test_financial_snapshot_and_page_fences_are_required():
    example = make_synthetic_example("empty_cad_debts")
    assert example.binding.source_snapshot.financial_versions[0].financial_version == "1"
    assert example.binding.source_snapshot.financial_versions[0].private_activity_id == example.scope_activity_id
    bad_pages = [example.binding.page_receipts[0].model_copy(update={"source_version": "drifted-version"})]
    with pytest.raises(ValueError):
        _validate_page_receipts(
            example.binding.page,
            bad_pages,
            expected_source_version=example.binding.source_version,
            expected_scope_fingerprint=example.binding.page_receipts[0].scope_fingerprint,
            expected_snapshot_fingerprint=example.binding.source_snapshot_fingerprint,
        )


def test_title_filter_is_nfc_casefold_literal_and_renderer_escapes_control_text():
    example = make_synthetic_example(
        "expenses_postfilter_empty", title_contains="CAFÉ", titles=["Cafe\u0301 rail\r\n total 999 USD"]
    )
    validated = example.validate()
    assert validated.queries[0].observation.matched_count == 1
    answer = render_query_answer(validated)
    assert "\\r\\n" in answer.text
    assert "\\r\\n total 999 USD" in answer.text
    assert "\r\n total 999 USD" not in answer.text
    assert answer.text.count("\n") == 1


def test_expense_date_filter_uses_utc_calendar_day_and_handles_date_max():
    example = make_synthetic_example("expenses_postfilter_empty", titles=["rail"])
    fact = example.actual_result.body.items[0]
    criteria = example.binding.criteria.model_copy(update={"from_date": date(2026, 10, 10), "to_date": date(2026, 10, 10)})
    utc_previous_day = fact.model_copy(update={"occurred_at": datetime.fromisoformat("2026-10-11T00:30:00+08:00")})
    assert _fact_matches(utc_previous_day, criteria)
    criteria_max = criteria.model_copy(update={"from_date": None, "to_date": date.max})
    max_day = fact.model_copy(update={"occurred_at": datetime.max.replace(tzinfo=timezone.utc)})
    assert _fact_matches(max_day, criteria_max)


def test_wire_date_python_and_json_are_equivalent_and_bool_is_rejected():
    payload = {
        "kind": "expenses", "activity_ref": "activity_1", "from_date": "2026-10-10",
        "to_date": "2026-10-11", "participant_ref": None, "title_contains": "rail",
    }
    as_python = ReadExpensesCriteria.model_validate(payload)
    as_json = ReadExpensesCriteria.model_validate_json(json.dumps(payload))
    assert as_python == as_json
    payload["from_date"] = True
    with pytest.raises(Exception):
        ReadExpensesCriteria.model_validate(payload)
    with pytest.raises(Exception):
        ReadExpensesCriteria.model_validate_json(json.dumps(payload))


def test_complete_version_tuple_is_required_and_old_parser_rejects_query_refs():
    current = {
        "api_version": "1.0.0", "semantic_version": "1.1.0", "operations_version": "1.1.0",
        "trajectory_version": "1.1.0", "execution_key_version": "1",
    }
    legacy = {
        "api_version": v1.API_VERSION, "semantic_version": v1.SEMANTIC_VERSION,
        "operations_version": v1.OPERATIONS_VERSION, "trajectory_version": v1.TRAJECTORY_VERSION,
        "execution_key_version": v1.EXECUTION_KEY_VERSION,
    }
    answer = {"kind": "answer", "basis": "grounded", "text": "No matching expenses.", "citations": ["query_1"]}
    assert parse_decision(answer, negotiated_versions=current).citations == [QueryEvidenceRef.Q01]
    with pytest.raises(Exception):
        parse_decision(answer, negotiated_versions=legacy)
    with pytest.raises(ValueError):
        parse_decision(answer, negotiated_versions={"semantic_version": "1.1.0"})
    with pytest.raises(ValueError):
        ProtocolVersionTuple.model_validate({**current, "operations_version": "1.0.0"})
    assert NegotiatedVersions(**current).execution_key_version == "1"


def test_read_operation_criteria_and_scope_are_cross_checked():
    example = make_synthetic_example("expenses_postfilter_empty")
    decision = ReadDecision(
        kind="read", operation=v1.ReadOperation.EXPENSES,
        criteria=example.binding.criteria,
    )
    validate_decision(decision, example.context)
    wrong_scope_decision = ReadDecision(
        kind="read", operation=v1.ReadOperation.EXPENSES,
        criteria=example.binding.criteria.model_copy(update={"activity_ref": v1.ActivityRef.A02}),
    )
    with pytest.raises(ValueError):
        validate_decision(wrong_scope_decision, example.context)
    global_example = make_synthetic_example("empty_activities")
    global_context = global_example.context.model_copy(deep=True)
    global_context = global_context.model_copy(update={"verified_scope": v1.ModelActivityScope(
        kind="activity", activity_ref=v1.ActivityRef.A01,
        permissions=[v1.HarnessPermission.READ_ACTIVITIES],
    )})
    with pytest.raises(ValueError):
        validate_context_bindings(
            global_context,
            current_owner_id=global_example.owner_id,
            current_turn_id=global_example.turn_id,
            generation=1, expected_revision=1, freshness_epoch=1,
            current_context_version=1,
            current_query_states=[_current_state(global_example.binding, global_example.owner_id, global_example.turn_id, revision=1, status="current")],
            trusted_tool_results=[global_example.actual_result], bound_queries=[global_example.binding],
            bound_references=global_example.bound_references,
            bound_evidence_references=global_example.bound_evidence_references,
            bound_read_results=global_example.bound_read_results,
        )


def test_private_source_snapshot_nested_mutation_is_rejected_at_trust_boundary():
    example = make_synthetic_example("empty_cad_debts")
    fence = example.binding.source_snapshot.financial_versions[0].model_copy(
        update={"financial_version": "2"}
    )
    changed_snapshot = example.binding.source_snapshot.model_copy(update={"financial_versions": [fence]})
    changed_binding = example.binding.model_copy(update={"source_snapshot": changed_snapshot})
    state = _current_state(
        example.binding, example.owner_id, example.turn_id,
        revision=example.binding.expected_revision, status="current",
    )
    with pytest.raises(ValueError):
        validate_context_bindings(
            example.context,
            current_owner_id=example.owner_id,
            current_turn_id=example.turn_id,
            generation=example.binding.generation,
            expected_revision=example.binding.expected_revision,
            freshness_epoch=example.binding.freshness_epoch,
            current_context_version=example.context.context_version,
            current_query_states=[state],
            trusted_tool_results=[example.actual_result],
            bound_queries=[changed_binding],
            bound_references=example.bound_references,
            bound_evidence_references=example.bound_evidence_references,
            bound_read_results=example.bound_read_results,
        )


def test_protocol_registry_cannot_mutate_inherited_capabilities_or_operation_mapping():
    registry = build_protocol_registry()
    altered_cap = copy.deepcopy(registry)
    altered_cap.capabilities[1].operations.append("prepay")
    with pytest.raises(ValueError):
        validate_protocol_registry(altered_cap)
    altered_mapping = copy.deepcopy(registry)
    altered_mapping.operations[0] = altered_mapping.operations[0].model_copy(
        update={"required_capability": "CAP07"}
    )
    with pytest.raises(ValueError):
        validate_protocol_registry(altered_mapping)


def test_dataset_applicability_is_explicit_and_rejects_relabel_or_training_enablement():
    policy = build_dataset_applicability_policy()
    validate_dataset_applicability_policy(policy)
    assert policy.entries[3].dataset_id == "legacy-t1-393-v1"
    assert policy.entries[3].direct_training_eligible is False
    changed_entries = list(policy.entries)
    changed_entries[3] = changed_entries[3].model_copy(update={"direct_training_eligible": True})
    altered = policy.model_copy(update={"entries": changed_entries})
    with pytest.raises(ValueError):
        validate_dataset_applicability_policy(altered)
    changed_entries = list(policy.entries)
    changed_entries[3] = changed_entries[3].model_copy(update={"disposition": "synthetic_fixture"})
    relabeled = policy.model_copy(update={"entries": changed_entries})
    with pytest.raises(ValueError):
        validate_dataset_applicability_policy(relabeled)


def test_fact_and_policy_citations_only_allow_their_exact_renderers():
    example = make_synthetic_example(
        "expenses_postfilter_empty", title_contains="Cafe", titles=["Cafe lunch"],
    )
    validated = example.validate()
    fact = example.actual_result.body.items[0]
    fact_answer = render_fact_answer(validated, [fact.evidence_ref], expected_context=example.context)
    validate_decision(fact_answer, example.context, validated_queries=validated)
    arbitrary_fact = AnswerDecision(
        kind="answer", basis="grounded", text="The total is 999999 CAD.", citations=[fact.evidence_ref],
    )
    with pytest.raises(ValueError):
        validate_decision(arbitrary_fact, example.context, validated_queries=validated)

    policy = v1.PolicyEvidence(
        evidence_ref=v1.PolicyEvidenceRef.P01,
        rule=v1.PolicyRule.EXECUTION_CONFIRMATION,
        source=v1.PolicySource.DEVELOPMENT_GUIDE,
        version="0.4.2",
        text="Writes require user confirmation.",
        observed_at=datetime(2026, 10, 12, tzinfo=timezone.utc),
    )
    base = make_synthetic_example("empty_activities").context.model_dump(mode="json")
    base.update(read_results=[], query_observations=[], policy_evidence=[policy.model_dump(mode="json")])
    policy_context = type(example.context).model_validate(base)
    policy_answer = render_policy_answer(policy_context, [v1.PolicyEvidenceRef.P01])
    validate_decision(policy_answer, policy_context)
    from evaluation.t1_protocol_v1_1.trajectory import ModelDecisionStep, UserInputStep
    policy_trace = T1TrajectoryV11(
        trajectory_version="1.1.0",
        versions=NegotiatedVersions(
            api_version="1.0.0", semantic_version="1.1.0", operations_version="1.1.0",
            trajectory_version="1.1.0", execution_key_version="1",
        ),
        scenario="synthetic-static-policy-render",
        original_input_text=policy_context.input_text,
        recent_messages=[], initial_generation=1,
        synthetic_private_turn_id=uuid.uuid4(), synthetic_private_bound_references=[],
        steps=[
            UserInputStep(kind="user_input", seq=0, text=policy_context.input_text),
            ModelDecisionStep(kind="model_decision", seq=1, context=policy_context, decision=policy_answer),
        ],
    )
    assert policy_trace.steps[-1].decision == policy_answer
    forged_policy_answer = AnswerDecision(
        kind="answer", basis="grounded",
        text="Total 999999 CAD; no matching debts exist.",
        citations=[v1.PolicyEvidenceRef.P01],
    )
    with pytest.raises(ValueError):
        validate_decision(forged_policy_answer, policy_context)
    raw_trace = policy_trace.model_dump(mode="json")
    raw_trace["steps"][-1]["decision"] = forged_policy_answer.model_dump(mode="json")
    with pytest.raises(ValueError):
        T1TrajectoryV11.model_validate(raw_trace)


def test_verbatim_input_seal_rejects_unicode_normalization_after_validation():
    example = make_synthetic_example("expenses_postfilter_empty")
    exact_context = example.context.model_copy(update={"input_text": "Café account query"})
    validated = replace(example, context=exact_context).validate()
    validated.context.input_text = "Cafe\u0301 account query"
    with pytest.raises(ValueError):
        render_query_answer(validated)


def test_clarify_resume_and_participant_filtered_read_traces_are_typed_and_causal():
    from evaluation.t1_protocol_v1_1.examples import (
        build_participant_filtered_read_trace,
        build_two_turn_clarify_propose_trace,
    )

    resumed = build_two_turn_clarify_propose_trace()
    assert resumed.steps[-1].context.input_text == "50 USD."
    assert resumed.steps[-1].context.recent_messages == [
        v1.PriorMessage(role="user", text=resumed.original_input_text)
    ]
    participant_trace = build_participant_filtered_read_trace()
    assert participant_trace.steps[1].decision.criteria.participant_ref == v1.ParticipantRef.P01

    raw_trace = participant_trace.model_dump(mode="json")
    missing = [item for item in raw_trace["synthetic_private_bound_references"] if item["kind"] != "participant"]
    with pytest.raises(ValueError):
        T1TrajectoryV11.model_validate({
            **raw_trace,
            "synthetic_private_bound_references": missing,
        })

    cross_activity = copy.deepcopy(raw_trace["synthetic_private_bound_references"])
    for item in cross_activity:
        if item["kind"] == "participant":
            item["scope_activity_id"] = str(uuid.uuid4())
    with pytest.raises(ValueError):
        T1TrajectoryV11.model_validate({
            **raw_trace,
            "synthetic_private_bound_references": cross_activity,
        })


def test_export_schemas_are_draft202012_closed_and_match_pydantic_cross_field_rules():
    schemas = build_protocol_schemas()
    assert len(schemas) == 10
    for schema in schemas.values():
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(schema)

    tuple_schema = schemas["protocol-version-tuple.schema.json"]
    tuple_validator = Draft202012Validator(tuple_schema)
    current = {
        "api_version": "1.0.0", "semantic_version": "1.1.0", "operations_version": "1.1.0",
        "trajectory_version": "1.1.0", "execution_key_version": "1",
    }
    assert tuple_validator.is_valid(current)
    assert not tuple_validator.is_valid({"semantic_version": "1.1.0"})
    assert not tuple_validator.is_valid({**current, "operations_version": "1.0.0"})

    semantic_validator = Draft202012Validator(schemas["semantic-decision.schema.json"])
    mismatched_read = {
        "kind": "read", "operation": "read.expenses",
        "criteria": {
            "kind": "debts", "activity_ref": "activity_1", "participant_ref": None, "currency": "CAD",
        },
    }
    # JSON Schema closes fields and decision variants; this cross-field operation/kind
    # relationship belongs to the Pydantic validator, which rejects it below.
    assert semantic_validator.is_valid(mismatched_read)
    with pytest.raises(ValueError):
        ReadDecision.model_validate(mismatched_read)


def test_export_source_archive_is_closed_and_detects_byte_drift(tmp_path, monkeypatch):
    archive = tmp_path / "source-inputs"
    archive.mkdir()
    payload = b"immutable source snapshot"
    digest = hashlib.sha256(payload).hexdigest()
    (archive / "reference").mkdir()
    (archive / "reference" / "source.txt").write_bytes(payload)
    index = {
        "format": "t1-source-input-snapshot-v1",
        "entries": [{
            "archive_path": "reference/source.txt",
            "source_path": "D:/reference/source.txt",
            "source_sha256": digest,
            "size_bytes": len(payload),
        }],
        "p2_module_provenance_sha256": {},
    }
    (archive / "index.json").write_text(json.dumps(index), encoding="utf-8")
    monkeypatch.setattr(export_protocol, "SOURCE_ARCHIVE", archive)
    assert export_protocol._validate_source_archive()["hashes"]["reference/source.txt"] == digest

    (archive / "unexpected.bin").write_bytes(b"unlisted")
    with pytest.raises(ValueError, match="inventory mismatch"):
        export_protocol._validate_source_archive()
    (archive / "unexpected.bin").unlink()
    (archive / "reference" / "source.txt").write_bytes(b"drifted")
    with pytest.raises(ValueError, match="hash/size mismatch"):
        export_protocol._validate_source_archive()


def test_source_snapshot_aliases_are_archive_relative_and_contain_projection_inputs():
    sources = export_protocol.source_input_paths()
    assert "reference/p2_backend.py" in sources
    assert "reference/p2_runtime.py" in sources
    assert "reference/business/BUSINESS_LOGIC.md" in sources
    assert "external/root-protected-baseline.json" in sources
    assert all(not Path(name).is_absolute() and ".." not in Path(name).parts for name in sources)

