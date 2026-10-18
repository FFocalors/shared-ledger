"""Synthetic-only causal trace and explicit old-to-new adaptation envelope."""
from __future__ import annotations

import uuid
from typing import Annotated, Literal, Union

from pydantic import Field, model_validator

from . import v1_contracts as v1
from .contracts import (
    CLOSED_CAPABILITY_ACKNOWLEDGEMENT,
    ModelContext,
    NegotiatedVersions,
    QueryEvidenceObservation,
    QueryEvidenceRef,
    ReadDecision,
    SemanticDecision,
    _fact_matches,
    backend_criteria_for,
    body_digest,
    normalized_criteria,
    post_filter_for,
)
from .harness import _render_fact, render_policy_answer, validate_decision


class UserInputStep(v1.ContractModel):
    kind: Literal["user_input"] = "user_input"
    seq: int = Field(strict=True, ge=0)
    text: v1.StrictText


class UserClarificationStep(v1.ContractModel):
    """A new accepted user input after a typed clarify decision; not a tool result."""

    kind: Literal["user_clarification"] = "user_clarification"
    seq: int = Field(strict=True, ge=1)
    text: v1.StrictText
    responds_to_seq: int = Field(strict=True, ge=1)
    generation: int = Field(strict=True, ge=2)


class ModelDecisionStep(v1.ContractModel):
    kind: Literal["model_decision"] = "model_decision"
    seq: int = Field(strict=True, ge=1)
    context: ModelContext
    decision: SemanticDecision


class ToolObservationStep(v1.ContractModel):
    kind: Literal["tool_observation"] = "tool_observation"
    seq: int = Field(strict=True, ge=1)
    query: QueryEvidenceObservation
    result: v1.ModelReadResult


TraceStep = Annotated[
    Union[UserInputStep, UserClarificationStep, ModelDecisionStep, ToolObservationStep],
    Field(discriminator="kind"),
]


class T1TrajectoryV11(v1.ContractModel):
    """Ordered synthetic trace. It is not a live private-binding or adapter proof."""

    trajectory_version: Literal["1.1.0"]
    versions: NegotiatedVersions
    scenario: v1.ShortText
    original_input_text: v1.StrictText
    recent_messages: list[v1.PriorMessage] = Field(max_length=19)
    initial_generation: int = Field(default=1, strict=True, ge=1)
    synthetic_private_turn_id: uuid.UUID
    synthetic_private_bound_references: list[v1.BoundReference] = Field(max_length=64)
    steps: list[TraceStep] = Field(min_length=2, max_length=32)

    @model_validator(mode="after")
    def causal_order_and_adapter_projection(self) -> "T1TrajectoryV11":
        if self.steps[0].kind != "user_input" or self.steps[0].seq != 0:
            raise ValueError("trajectory begins with exact initial user input at sequence zero")
        if self.steps[0].text != self.original_input_text:
            raise ValueError("root original_input_text must equal the initial user submission")
        if [step.seq for step in self.steps] != list(range(len(self.steps))):
            raise ValueError("trajectory sequence numbers must be contiguous and causal")
        if any(item.source_turn_id != self.synthetic_private_turn_id for item in self.synthetic_private_bound_references):
            raise ValueError("synthetic private sidecar references must belong to this exact Turn")

        emitted_queries: list[QueryEvidenceObservation] = []
        emitted_results: list[v1.ModelReadResult] = []
        pending_read: ReadDecision | None = None
        last_decision: ModelDecisionStep | None = None
        current_user_text = self.original_input_text
        expected_recent = list(self.recent_messages)
        generation = self.initial_generation
        previous_model_step: ModelDecisionStep | None = None

        for step in self.steps[1:]:
            if pending_read is not None and step.kind != "tool_observation":
                raise ValueError("a read decision must be followed immediately by its typed tool observation")

            if step.kind == "user_input":
                raise ValueError("trace contains exactly one initial user_input step")

            if step.kind == "user_clarification":
                if (
                    previous_model_step is None
                    or previous_model_step.decision.kind != "clarify"
                    or step.responds_to_seq != previous_model_step.seq
                ):
                    raise ValueError("resumed user input must answer the immediately preceding clarify decision")
                if step.generation != generation + 1:
                    raise ValueError("each accepted clarification must increment generation exactly once")
                expected_recent = (expected_recent + [v1.PriorMessage(role="user", text=current_user_text)])[-19:]
                current_user_text = step.text
                generation = step.generation
                previous_model_step = None
                continue

            if step.kind == "tool_observation":
                if pending_read is None:
                    raise ValueError("tool observation requires a preceding read decision")
                if not step.result.simulation or step.query.source.value != "synthetic_simulation":
                    raise ValueError("this offline trajectory schema accepts synthetic observations only")
                if (
                    step.query.operation != pending_read.operation
                    or step.query.criteria != pending_read.criteria
                    or step.query.result_ref != step.result.result_ref
                    or step.query.operation != step.result.operation
                    or step.query.context_version != step.result.context_version
                    or step.query.observed_at != step.result.observed_at
                    or step.query.simulation != step.result.simulation
                ):
                    raise ValueError("tool observation must match the immediately preceding read request/result")
                if step.query.normalized_criteria != normalized_criteria(step.query.operation, step.query.criteria):
                    raise ValueError("trace query criteria must use the canonical normalized representation")
                if step.query.backend_criteria != backend_criteria_for(step.query.criteria):
                    raise ValueError("trace backend stage cannot drop or invent query criteria")
                if step.query.post_filter != post_filter_for(step.query.criteria):
                    raise ValueError("trace post-filter stage cannot drop or invent query criteria")
                if step.query.returned_count != len(step.result.body.items):
                    raise ValueError("trace returned_count must match the complete typed result body")
                if step.query.body_digest != body_digest(step.result.body):
                    raise ValueError("trace result body digest must match the typed body")
                matched = [fact for fact in step.result.body.items if _fact_matches(fact, step.query.criteria)]
                if (
                    step.query.matched_count != len(matched)
                    or step.query.matching_fact_citations != [fact.evidence_ref for fact in matched]
                ):
                    raise ValueError("trace matches must be recalculated from the full typed result body")
                if step.query.page.complete and step.query.page.expected_total != len(step.result.body.items):
                    raise ValueError("a complete trace query must cover the exact full result total")
                emitted_queries.append(step.query)
                emitted_results.append(step.result)
                pending_read = None
                previous_model_step = None
                continue

            context = step.context
            if context.input_text != current_user_text:
                raise ValueError("each model context input_text must equal the latest accepted user submission verbatim")
            if context.recent_messages != expected_recent:
                raise ValueError("recent_messages must contain only prior accepted user inputs in order")
            if context.query_observations != emitted_queries:
                raise ValueError("a model step must contain the exact full query objects emitted earlier in this trace")
            if context.read_results != emitted_results:
                raise ValueError("a model step must contain exact full read-result bodies emitted earlier in this trace")
            if step.decision.kind == "read":
                validate_decision(
                    step.decision,
                    context,
                    trusted_bound_references=self.synthetic_private_bound_references,
                    current_turn_id=self.synthetic_private_turn_id,
                )
                pending_read = step.decision
            else:
                validate_synthetic_trace_decision(step.decision, context)
            last_decision = step
            previous_model_step = step

        if pending_read is not None:
            raise ValueError("trajectory cannot end before its requested read observation")
        if last_decision is None or last_decision is not self.steps[-1] or last_decision.decision.kind == "read":
            raise ValueError("trajectory must end with a non-read model decision consuming the prior trace")
        return self


def _trace_render_query_answer(context: ModelContext, selected_refs: list[QueryEvidenceRef]) -> str:
    observations = {item.query_ref: item for item in context.query_observations}
    results = {item.result_ref: item for item in context.read_results}
    lines: list[str] = []
    for ref in selected_refs:
        query = observations[ref]
        result = results[query.result_ref]
        facts = [fact for fact in result.body.items if _fact_matches(fact, query.criteria)]
        noun = {"activities": "activities", "expenses": "expenses", "debts": "debts"}[query.criteria.kind]
        if not query.page.complete:
            lines.append(f"Partial {noun} query: {len(facts)} matched among {len(result.body.items)} returned; more data may exist.")
            lines.extend(_render_fact(fact) for fact in facts)
        elif not facts:
            if not result.body.items:
                lines.append(f"No {noun} matched; the complete backend result contained 0 items.")
            else:
                lines.append(f"No {noun} matched the post-filter; all {len(result.body.items)} backend items were checked.")
        else:
            lines.append(f"Found {len(facts)} matching {noun}:")
            lines.extend(_render_fact(fact) for fact in facts)
    return "\n".join(lines)


def validate_synthetic_trace_decision(decision: SemanticDecision, context: ModelContext) -> None:
    """Structural/casual check for examples only; never an authorization for live queries."""
    if decision.kind != "answer":
        validate_decision(decision, context)
        return
    facts = {fact.evidence_ref for result in context.read_results for fact in result.body.items}
    policies = {item.evidence_ref for item in context.policy_evidence}
    queries = {item.query_ref for item in context.query_observations}
    results = {item.result_ref: item for item in context.read_results}
    citations = set(decision.citations)
    if not citations.issubset(facts | policies | queries):
        raise ValueError("synthetic trace answer cites only facts/policy/query evidence already emitted")
    if decision.basis == "grounded" and not citations:
        raise ValueError("grounded trace answers require typed evidence")
    if decision.basis == "conversation":
        if citations:
            raise ValueError("conversation-only answer cannot claim typed evidence")
        if context.intent_classification == "business":
            if decision.text != CLOSED_CAPABILITY_ACKNOWLEDGEMENT:
                raise ValueError("business-context conversation requires the explicit closed-capability acknowledgement")
        elif context.read_results or context.query_observations or context.available_permissions:
            raise ValueError("non-business trace context cannot carry business query results or capabilities")
        return

    query_cites = [citation for citation in decision.citations if citation in queries]
    fact_cites = citations.intersection(facts)
    if query_cites:
        if fact_cites or citations.intersection(policies):
            raise ValueError("synthetic query renderer answers cannot mix query citations with other claims")
        rendered = _trace_render_query_answer(context, query_cites)
        if decision.text != rendered or decision.citations != query_cites:
            raise ValueError("synthetic query citations require the exact deterministic trace renderer output")
    elif fact_cites:
        matches = {
            citation
            for query in context.query_observations
            for citation in query.matching_fact_citations
        }
        if not fact_cites.issubset(matches):
            raise ValueError("synthetic trace fact citations must come from an earlier typed query match set")
        if fact_cites != citations:
            raise ValueError("synthetic fact-renderer answer cannot mix fact citations with query/policy claims")
        facts_by_ref = {
            fact.evidence_ref: fact
            for query in context.query_observations
            for fact in results[query.result_ref].body.items
            if fact.evidence_ref in query.matching_fact_citations
        }
        ordered = [
            fact.evidence_ref
            for query in context.query_observations
            for fact in results[query.result_ref].body.items
            if fact.evidence_ref in fact_cites
        ]
        expected = "Current matching facts:\n" + "\n".join(_render_fact(facts_by_ref[ref]) for ref in ordered)
        if decision.text != expected or decision.citations != ordered:
            raise ValueError("synthetic fact citation only authorizes exact deterministic typed-fact rendering")
    elif citations:
        if not citations.issubset(policies):
            raise ValueError("synthetic trace answer citation class is invalid")
        rendered_policy = render_policy_answer(
            context,
            [citation for citation in decision.citations if citation in policies],
        )
        if decision.text != rendered_policy.text or decision.citations != rendered_policy.citations:
            raise ValueError("synthetic policy citations require exact deterministic static-policy rendering")


class AdaptationEnvelope(v1.ContractModel):
    source_profile: v1.ShortText
    target_profile: Literal["t1-offline-canonical"]
    explicit_conversion: Literal[True]
    preserve_original_input: Literal[True]
    preserve_recent_messages: Literal[True]
    query_evidence_adapter: Literal["not_applicable", "trusted_adapter_required"]
    source_freeze_sha256: v1.Sha256Hex
    new_source_freeze_required: Literal[True]
    replay_and_review_required: Literal[True]
    new_split_required: Literal[True]


def build_trajectory_schema() -> dict:
    schema = T1TrajectoryV11.model_json_schema(mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://shared-ledger.invalid/schemas/t1-trajectory-1.1.0.json"
    return schema


def build_adaptation_schema() -> dict:
    schema = AdaptationEnvelope.model_json_schema(mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://shared-ledger.invalid/schemas/t1-adaptation-1.1.0.json"
    return schema
