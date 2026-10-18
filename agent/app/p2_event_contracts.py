"""Disabled candidate DTOs for projecting P2 results into an event sidecar.

This module is deliberately not imported by the application. The DTOs validate
shape and internal consistency only; they do not authorize a read or establish
that a receipt came from an accepted source query.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, TypeAlias, Union

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, StringConstraints, TypeAdapter, model_validator

from .contracts import AGENT_EVENT_ADAPTER, API_VERSION, AgentEvent, StatusEvent, TurnPublicStatus
from .p2_read_contracts import (
    Digest,
    P2AnswerDecision,
    P2ClarifyDecision,
    P2Fact,
    P2FinancialVersion,
    P2ProtocolVersions,
    P2ProposalRecognition,
    P2ReadBackendResult,
    P2_VERSIONS,
    QueryEvidenceRef,
)


_FACT_ADAPTER = TypeAdapter(P2Fact)


def _strict_model_copy(model_type: type[BaseModel], value: BaseModel) -> BaseModel:
    if not isinstance(value, model_type):
        raise ValueError("nested candidate DTO has an unexpected type")
    try:
        return model_type.model_validate_json(value.model_dump_json(), strict=True)
    except Exception as exc:
        raise ValueError("nested candidate DTO failed strict revalidation") from exc


class P2EventWireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class P2EventPollQuery(P2EventWireModel):
    after_seq: Annotated[StrictInt, Field(ge=0)] = 0
    limit: Annotated[StrictInt, Field(ge=1, le=500)] = 100


class P2EventResultState(StrEnum):
    COMPLETE_EMPTY = "complete_empty"
    COMPLETE_NONEMPTY = "complete_nonempty"
    PARTIAL_OR_UNKNOWN = "partial_or_unknown"


def _derive_p2_result_state(
    *,
    returned_count: int,
    matched_count: int,
    source_total: int | None,
    matched_total: int | None,
    query_zero_classification: str,
    source_query_complete: bool,
    model_projection_complete: bool,
    has_more: bool,
    truncated: bool,
    range_contiguous: bool,
    stable_total_verified: bool,
    source_version_fenced: bool,
    unique_items_verified: bool,
) -> P2EventResultState:
    """Share one conservative completeness rule between projection and DTO validation."""
    if query_zero_classification == "backend_zero":
        if returned_count != 0 or source_total not in (None, 0):
            raise ValueError("backend_zero cannot report source rows or a nonzero source total")
    if query_zero_classification in {"backend_zero", "post_filter_zero"} and matched_count != 0:
        raise ValueError("zero classification cannot report matched facts")
    if query_zero_classification == "nonzero" and matched_count == 0:
        raise ValueError("nonzero classification requires matched facts")

    complete_coverage = (
        source_query_complete
        and model_projection_complete
        and not has_more
        and not truncated
        and range_contiguous
        and source_version_fenced
        and unique_items_verified
        # stable_total_verified qualifies a known source total. A matched
        # total is the post-filter count and does not stand in for source_total.
        and (source_total is None or stable_total_verified)
    )
    if (
        complete_coverage
        and matched_count == 0
        and query_zero_classification in {"backend_zero", "post_filter_zero"}
    ):
        if matched_total not in (None, 0):
            raise ValueError("complete_empty cannot report matched totals")
        return P2EventResultState.COMPLETE_EMPTY
    if complete_coverage and matched_count > 0 and query_zero_classification == "nonzero":
        return P2EventResultState.COMPLETE_NONEMPTY
    # In particular, unknown_or_partial never becomes a complete zero or
    # complete nonempty result solely because all coverage booleans are true.
    return P2EventResultState.PARTIAL_OR_UNKNOWN


class P2EventObservation(P2EventWireModel):
    """Historical summary of one accepted query, never a currentness claim."""

    query_evidence_ref: QueryEvidenceRef
    operation: Literal[
        "read.activities", "read.expenses", "read.debts", "read.refund_events",
        "read.prepayment_accounts", "read.prepayment_usages", "read.prepayment_return_events",
    ]
    source_kind: Literal[
        "activities", "expenses", "debts", "refund_events", "prepayment_accounts",
        "prepayment_usages", "prepayment_return_events",
    ]
    source_version: Annotated[StrictStr, StringConstraints(min_length=1, max_length=200)]
    observed_at: datetime
    returned_count: Annotated[StrictInt, Field(ge=0)]
    matched_count: Annotated[StrictInt, Field(ge=0)]
    source_total: Annotated[StrictInt, Field(ge=0)] | None
    matched_total: Annotated[StrictInt, Field(ge=0)] | None
    financial_versions: tuple[P2FinancialVersion, ...] = Field(max_length=64)
    page_count: Annotated[StrictInt, Field(ge=1, le=128)]
    has_more: StrictBool
    truncated: StrictBool
    source_query_complete: StrictBool
    model_projection_complete: StrictBool
    range_contiguous: StrictBool
    stable_total_verified: StrictBool
    source_version_fenced: StrictBool
    unique_items_verified: StrictBool
    query_zero_classification: Literal["backend_zero", "post_filter_zero", "nonzero", "unknown_or_partial"]
    query_digest: Digest
    body_digest: Digest
    projection_digest: Digest
    result_state: P2EventResultState

    @model_validator(mode="after")
    def historical_summary_is_consistent(self) -> "P2EventObservation":
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        if self.matched_count > self.returned_count:
            raise ValueError("matched_count cannot exceed returned_count")
        if self.source_total is not None and self.returned_count > self.source_total:
            raise ValueError("returned_count cannot exceed source_total")
        if self.matched_total is not None and self.matched_count > self.matched_total:
            raise ValueError("matched_count cannot exceed matched_total")
        source_kind = self.operation.removeprefix("read.")
        if self.source_kind != source_kind:
            raise ValueError("source_kind must match the read operation")
        for version in self.financial_versions:
            _strict_model_copy(P2FinancialVersion, version)
        expected_state = _derive_p2_result_state(
            returned_count=self.returned_count,
            matched_count=self.matched_count,
            source_total=self.source_total,
            matched_total=self.matched_total,
            query_zero_classification=self.query_zero_classification,
            source_query_complete=self.source_query_complete,
            model_projection_complete=self.model_projection_complete,
            has_more=self.has_more,
            truncated=self.truncated,
            range_contiguous=self.range_contiguous,
            stable_total_verified=self.stable_total_verified,
            source_version_fenced=self.source_version_fenced,
            unique_items_verified=self.unique_items_verified,
        )
        if self.result_state != expected_state:
            raise ValueError("result_state must match the explicit completeness and zero summary")
        return self


class P2FactCard(P2EventWireModel):
    """One source-typed fact bound to the qev that supplied it."""

    query_evidence_ref: QueryEvidenceRef
    fact: P2Fact

    @model_validator(mode="after")
    def fact_matches_qev(self) -> "P2FactCard":
        try:
            _FACT_ADAPTER.validate_json(self.fact.model_dump_json(), strict=True)
        except Exception as exc:
            raise ValueError("fact card must contain a strictly revalidated P2Fact") from exc
        if self.fact.query_evidence_ref != self.query_evidence_ref:
            raise ValueError("fact card qev must match the fact evidence ref")
        return self


class P2AnswerOutput(P2EventWireModel):
    kind: Literal["answer"]
    basis: Literal["fresh_read_receipts", "non_business_general"]
    text: Annotated[StrictStr, StringConstraints(min_length=1, max_length=4000)]
    citations: tuple[QueryEvidenceRef, ...] = Field(max_length=16)
    observations: tuple[P2EventObservation, ...] = Field(max_length=16)
    fact_cards: tuple[P2FactCard, ...] = Field(max_length=256)

    @model_validator(mode="after")
    def answer_sidecar_matches_citations(self) -> "P2AnswerOutput":
        for observation in self.observations:
            _strict_model_copy(P2EventObservation, observation)
        for card in self.fact_cards:
            _strict_model_copy(P2FactCard, card)
        if len(self.citations) != len(set(self.citations)):
            raise ValueError("answer citations must be unique")
        observation_refs = [item.query_evidence_ref for item in self.observations]
        if len(observation_refs) != len(set(observation_refs)):
            raise ValueError("answer observations must be unique")
        if self.basis == "non_business_general":
            if self.citations or self.observations or self.fact_cards:
                raise ValueError("source-free answers cannot carry citations or source sidecars")
            return self
        if not self.citations or set(observation_refs) != set(self.citations):
            raise ValueError("fresh-read observations must exactly match cited qevs")
        fact_identities: set[tuple[str, str]] = set()
        cited = set(self.citations)
        for card in self.fact_cards:
            if card.query_evidence_ref not in cited:
                raise ValueError("fact card must cite an answer qev")
            ref_field = {
                "activity": "activity_ref",
                "expense": "expense_ref",
                "debt": "debt_ref",
                "refund_event": "refund_ref",
                "prepayment_account": "account_ref",
                "prepayment_usage": "usage_ref",
                "prepayment_return_event": "return_event_ref",
            }[card.fact.fact_kind]
            identity = (card.fact.fact_kind, getattr(card.fact, ref_field))
            if identity in fact_identities:
                raise ValueError("answer fact cards must not duplicate a typed fact")
            fact_identities.add(identity)
        return self


class P2ClarificationOutput(P2EventWireModel):
    kind: Literal["clarify"]
    prompt: Annotated[StrictStr, StringConstraints(min_length=1, max_length=1200)]
    missing_slots: tuple[Annotated[StrictStr, StringConstraints(min_length=1, max_length=80)], ...] = Field(
        min_length=1, max_length=16
    )


class P2ProposalRecognitionOutput(P2EventWireModel):
    kind: Literal["propose"]
    operation: Literal["expense.create", "expense.update", "expense.presentation.update"]
    recognized_intent_text: Annotated[StrictStr, StringConstraints(min_length=1, max_length=200)]


P2CandidateOutput: TypeAlias = Annotated[
    Union[P2AnswerOutput, P2ClarificationOutput, P2ProposalRecognitionOutput],
    Field(discriminator="kind"),
]
_OUTPUT_ADAPTER = TypeAdapter(P2CandidateOutput)


class P2ProjectedEvent(P2EventWireModel):
    seq: Annotated[StrictInt, Field(ge=1)]
    created_at: datetime
    event: AgentEvent
    candidate_output: P2CandidateOutput | None = None

    @model_validator(mode="after")
    def event_row_and_sidecar_match(self) -> "P2ProjectedEvent":
        try:
            checked_event = AGENT_EVENT_ADAPTER.validate_json(self.event.model_dump_json(), strict=True)
        except Exception as exc:
            raise ValueError("canonical event must pass strict source contract revalidation") from exc
        if checked_event != self.event:
            raise ValueError("canonical event payload is not stable after strict revalidation")
        if self.candidate_output is not None:
            try:
                checked_output = _OUTPUT_ADAPTER.validate_json(self.candidate_output.model_dump_json(), strict=True)
            except Exception as exc:
                raise ValueError("candidate output must pass strict revalidation") from exc
            if checked_output != self.candidate_output:
                raise ValueError("candidate output is not stable after strict revalidation")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Store created_at must include a timezone")
        if self.event.seq != self.seq:
            raise ValueError("projected row sequence must match canonical AgentEvent.seq")
        if self.event.occurred_at.tzinfo is None or self.event.occurred_at.utcoffset() is None:
            raise ValueError("canonical event timestamp must include a timezone")
        if self.candidate_output is not None and not isinstance(self.event, StatusEvent):
            raise ValueError("candidate sidecar requires a harmless canonical status event")
        return self


class P2EventPollResponse(P2EventWireModel):
    api_version: Literal["1.0.0"] = API_VERSION
    versions: P2ProtocolVersions
    turn: TurnPublicStatus
    after_seq: Annotated[StrictInt, Field(ge=0)]
    events: tuple[P2ProjectedEvent, ...] = Field(max_length=500)
    next_after_seq: Annotated[StrictInt, Field(ge=0)]
    has_more: StrictBool

    @model_validator(mode="after")
    def cursor_and_candidate_versions_match(self) -> "P2EventPollResponse":
        _strict_model_copy(P2ProtocolVersions, self.versions)
        _strict_model_copy(TurnPublicStatus, self.turn)
        for item in self.events:
            _strict_model_copy(P2ProjectedEvent, item)
        if self.versions != P2_VERSIONS:
            raise ValueError("event projection requires the fixed candidate version tuple")
        seqs = [item.seq for item in self.events]
        if seqs != sorted(seqs) or len(seqs) != len(set(seqs)):
            raise ValueError("projected events must be in unique increasing sequence order")
        if any(seq <= self.after_seq for seq in seqs):
            raise ValueError("projected events must follow the supplied cursor")
        expected_cursor = seqs[-1] if seqs else self.after_seq
        if self.next_after_seq != expected_cursor:
            raise ValueError("next_after_seq must equal the last event or unchanged input cursor")
        if self.has_more and not self.events:
            raise ValueError("has_more requires progress past the input cursor")
        return self


def _revalidate_model(model_type: type[BaseModel], value: BaseModel) -> BaseModel:
    if not isinstance(value, model_type):
        raise ValueError("expected the declared candidate DTO type")
    try:
        return model_type.model_validate_json(value.model_dump_json(), strict=True)
    except Exception as exc:
        raise ValueError("candidate DTO failed strict revalidation") from exc


def _fact_ref(fact: P2Fact) -> str:
    return getattr(
        fact,
        {
            "activity": "activity_ref",
            "expense": "expense_ref",
            "debt": "debt_ref",
            "refund_event": "refund_ref",
            "prepayment_account": "account_ref",
            "prepayment_usage": "usage_ref",
            "prepayment_return_event": "return_event_ref",
        }[fact.fact_kind],
    )


def project_p2_backend_result(result: P2ReadBackendResult) -> tuple[P2EventObservation, tuple[P2FactCard, ...]]:
    """Deterministically project a typed result; does not establish authorization/currentness."""
    checked = _revalidate_model(P2ReadBackendResult, result)
    evidence = checked.query_evidence
    page = checked.page
    fact_refs = {_fact_ref(fact) for fact in page.items}
    if not fact_refs.issubset(set(evidence.matching_fact_refs)):
        raise ValueError("projected facts must appear in matching query evidence refs")
    summary = evidence.page
    result_state = _derive_p2_result_state(
        returned_count=evidence.returned_count,
        matched_count=evidence.matched_count,
        source_total=evidence.source_total,
        matched_total=evidence.matched_total,
        query_zero_classification=evidence.query_zero_classification,
        source_query_complete=evidence.source_query_complete,
        model_projection_complete=evidence.model_projection_complete,
        has_more=summary.has_more,
        truncated=summary.truncated,
        range_contiguous=summary.range_contiguous,
        stable_total_verified=summary.stable_total_verified,
        source_version_fenced=summary.source_version_fenced,
        unique_items_verified=summary.unique_items_verified,
    )
    observation = P2EventObservation(
        query_evidence_ref=evidence.query_evidence_ref,
        operation=evidence.operation.value,
        source_kind=evidence.source_kind,
        source_version=evidence.source_version,
        observed_at=evidence.observed_at,
        returned_count=evidence.returned_count,
        matched_count=evidence.matched_count,
        source_total=evidence.source_total,
        matched_total=evidence.matched_total,
        financial_versions=evidence.financial_versions,
        page_count=evidence.page_count,
        has_more=summary.has_more,
        truncated=summary.truncated,
        source_query_complete=evidence.source_query_complete,
        model_projection_complete=evidence.model_projection_complete,
        range_contiguous=summary.range_contiguous,
        stable_total_verified=summary.stable_total_verified,
        source_version_fenced=summary.source_version_fenced,
        unique_items_verified=summary.unique_items_verified,
        query_zero_classification=evidence.query_zero_classification,
        query_digest=evidence.query_digest,
        body_digest=evidence.body_digest,
        projection_digest=evidence.projection_digest,
        result_state=result_state,
    )
    cards = tuple(
        P2FactCard(query_evidence_ref=evidence.query_evidence_ref, fact=fact)
        for fact in page.items
    )
    return observation, cards


def build_p2_answer_output(
    decision: P2AnswerDecision,
    accepted_results: tuple[P2ReadBackendResult, ...] = (),
) -> P2AnswerOutput:
    """Build sidecars only from caller-supplied accepted typed results.

    The caller must prove receipt acceptance, current scope and actual source
    capture before calling this projection helper.
    """
    decision = _revalidate_model(P2AnswerDecision, decision)
    if decision.basis == "non_business_general":
        if accepted_results:
            raise ValueError("source-free answer cannot attach read results")
        return P2AnswerOutput(
            kind="answer", basis=decision.basis, text=decision.text, citations=(), observations=(), fact_cards=()
        )
    by_qev: dict[str, P2ReadBackendResult] = {}
    for result in accepted_results:
        checked = _revalidate_model(P2ReadBackendResult, result)
        qev = checked.query_evidence.query_evidence_ref
        if qev in by_qev:
            raise ValueError("accepted results must not duplicate qevs")
        by_qev[qev] = checked
    if set(decision.citations) != set(by_qev):
        raise ValueError("accepted result qevs must exactly match answer citations")
    observations: list[P2EventObservation] = []
    cards: list[P2FactCard] = []
    for qev in decision.citations:
        observation, qev_cards = project_p2_backend_result(by_qev[qev])
        observations.append(observation)
        cards.extend(qev_cards)
    return P2AnswerOutput(
        kind="answer",
        basis=decision.basis,
        text=decision.text,
        citations=decision.citations,
        observations=tuple(observations),
        fact_cards=tuple(cards),
    )


def build_p2_candidate_output(decision: P2AnswerDecision | P2ClarifyDecision | P2ProposalRecognition,
                              accepted_results: tuple[P2ReadBackendResult, ...] = ()) -> P2CandidateOutput:
    """Convert a parsed decision into the candidate sidecar without adding authority."""
    if isinstance(decision, P2AnswerDecision):
        return build_p2_answer_output(decision, accepted_results)
    if accepted_results:
        raise ValueError("only a factual answer can carry accepted read results")
    if isinstance(decision, P2ClarifyDecision):
        checked = _revalidate_model(P2ClarifyDecision, decision)
        return P2ClarificationOutput(kind="clarify", prompt=checked.prompt, missing_slots=checked.missing_slots)
    if isinstance(decision, P2ProposalRecognition):
        checked = _revalidate_model(P2ProposalRecognition, decision)
        return P2ProposalRecognitionOutput(
            kind="propose", operation=checked.operation.value, recognized_intent_text=checked.recognized_intent_text
        )
    raise ValueError("unsupported candidate decision for event projection")


def event_projection_json_schemas() -> dict[str, dict[str, object]]:
    """Return candidate-only schemas; callers must not replace the frozen OpenAPI export."""
    return {
        "P2EventPollQuery": P2EventPollQuery.model_json_schema(),
        "P2EventPollResponse": P2EventPollResponse.model_json_schema(),
        "P2CandidateOutput": _OUTPUT_ADAPTER.json_schema(),
    }
