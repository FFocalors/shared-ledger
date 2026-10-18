"""Strict candidate DTOs for protected, display-only P2 v3 event history.

This module is intentionally not imported by application assembly. It validates
shape and same-snapshot linkage supplied by a future Store reader; it cannot
prove authentication, membership, source provenance, or current authorization.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Annotated, Any, Literal, Mapping, Sequence, TypeAlias, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, TypeAdapter, ValidationError, field_validator, model_validator

from .contracts import StatusEvent
from .p2_read_contracts_v3 import (
    Digest,
    LongText,
    OpaqueRef,
    P2ClarificationSlot,
    P2CurrentActorBinding,
    P2EntityDisplayLabel,
    P2Fact,
    P2ProposalOperation,
    P2QueryEvidence,
    P2ReadOperation,
    P2ReadOperationField,
    P2ReadBackendResult,
    ReadCompleteness,
    P2V3ProtocolVersions,
    P2_V3_CANDIDATE_PROFILE_ID,
    P2_V3_VERSIONS,
    QueryEvidenceRef,
    ShortText,
)


_POLL_LIMIT_MAX = 500
_OUTPUT_FACT_MAX = 256
_OUTPUT_QEV_MAX = 16
_OUTPUT_LABEL_MAX = 64


class P2V3EventContractError(ValueError):
    """Sanitized failure for malformed candidate DTOs or inconsistent page links."""


class _V3EventWireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class P2V3EventPollQuery(_V3EventWireModel):
    after_seq: Annotated[StrictInt, Field(ge=0)]
    limit: Annotated[StrictInt, Field(ge=1, le=_POLL_LIMIT_MAX)]


class _P2V3HistoricalBase(_V3EventWireModel):
    history_only: Literal[True]
    profile_id: Literal[P2_V3_CANDIDATE_PROFILE_ID]
    versions: P2V3ProtocolVersions
    turn_ref: OpaqueRef
    generation: Annotated[StrictInt, Field(ge=1)]
    read_epoch: Annotated[StrictInt, Field(ge=0)]
    context_ref: OpaqueRef
    context_digest: Digest
    context_revision: Annotated[StrictInt, Field(ge=0)]
    observed_at: datetime
    simulation: StrictBool

    @field_validator("observed_at")
    @classmethod
    def output_time_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("historical output observed_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def candidate_tuple_is_exact(self):
        if self.profile_id != P2_V3_CANDIDATE_PROFILE_ID or self.versions != P2_V3_VERSIONS:
            raise ValueError("historical output is not pinned to the reviewed v3 candidate")
        return self


def _check_evidence_bundle(
    *,
    versions: P2V3ProtocolVersions,
    observed_at: datetime,
    simulation: bool,
    evidence: tuple[P2QueryEvidence, ...],
    facts: tuple[P2Fact, ...],
    citation_refs: tuple[QueryEvidenceRef, ...] | None = None,
) -> set[str]:
    evidence_refs = [str(item.query_evidence_ref) for item in evidence]
    if len(evidence_refs) != len(set(evidence_refs)):
        raise ValueError("historical query evidence references must be unique")
    for item in evidence:
        if item.profile_id != P2_V3_CANDIDATE_PROFILE_ID or item.versions != versions:
            raise ValueError("historical query evidence has a mismatched profile or tuple")
        if item.simulation is not simulation:
            raise ValueError("historical query evidence simulation flag differs")
        if item.observed_at > observed_at:
            raise ValueError("historical output predates its source observation")
    refs = set(evidence_refs)
    fact_operation = {
        "activity": P2ReadOperation.ACTIVITIES,
        "expense": P2ReadOperation.EXPENSES,
        "debt": P2ReadOperation.DEBTS,
        "refund_event": P2ReadOperation.REFUND_EVENTS,
        "prepayment_account": P2ReadOperation.PREPAYMENT_ACCOUNTS,
        "prepayment_usage": P2ReadOperation.PREPAYMENT_USAGES,
        "prepayment_return_event": P2ReadOperation.PREPAYMENT_RETURN_EVENTS,
    }
    if citation_refs is not None:
        cited = [str(item) for item in citation_refs]
        if len(cited) != len(set(cited)):
            raise ValueError("historical citation references must be unique")
        if not set(cited).issubset(refs):
            raise ValueError("historical citation lacks an included query observation")
    for fact in facts:
        evidence_ref = str(fact.query_evidence_ref)
        if evidence_ref not in refs:
            raise ValueError("historical fact lacks an included query observation")
        matching_evidence = next(item for item in evidence if str(item.query_evidence_ref) == evidence_ref)
        if matching_evidence.operation != fact_operation.get(fact.fact_kind):
            raise ValueError("historical fact kind does not match its query operation")
        if _fact_public_ref(fact) not in matching_evidence.matching_fact_refs:
            raise ValueError("historical fact reference is absent from its query observation")
        if citation_refs is not None and str(fact.query_evidence_ref) not in {str(item) for item in citation_refs}:
            raise ValueError("historical answer fact is not covered by a cited query observation")
    return refs


def _check_metadata_projection(
    *,
    observed_at: datetime,
    labels: tuple[P2EntityDisplayLabel, ...],
    actor: P2CurrentActorBinding | None,
) -> None:
    label_keys = [(item.entity_kind, str(item.entity_ref), str(item.scope_ref)) for item in labels]
    if len(label_keys) != len(set(label_keys)):
        raise ValueError("historical source labels must be unique by entity and scope")
    if any(item.observed_at > observed_at for item in labels):
        raise ValueError("historical output predates a source label observation")
    if actor is not None and actor.observed_at > observed_at:
        raise ValueError("historical output predates its actor observation")


class P2V3HistoricalAnswer(_P2V3HistoricalBase):
    """Existing answer semantic; basis distinguishes source-backed and non-business answers."""

    kind: Literal["answer"]
    basis: Literal["fresh_read_receipts", "non_business_general"]
    text: LongText
    citations: tuple[QueryEvidenceRef, ...] = Field(max_length=_OUTPUT_QEV_MAX)
    query_evidence: tuple[P2QueryEvidence, ...] = Field(max_length=_OUTPUT_QEV_MAX)
    fact_cards: tuple[P2Fact, ...] = Field(max_length=_OUTPUT_FACT_MAX)
    source_labels: tuple[P2EntityDisplayLabel, ...] = Field(max_length=_OUTPUT_LABEL_MAX)
    current_actor: P2CurrentActorBinding | None

    @model_validator(mode="after")
    def answer_has_only_its_bound_evidence(self):
        if self.basis == "non_business_general":
            if self.citations or self.query_evidence or self.fact_cards or self.source_labels or self.current_actor is not None:
                raise ValueError("non-business historical answers cannot carry source projections")
            return self
        if not self.citations:
            raise ValueError("source-backed historical answers require citations")
        if self.read_epoch < 1:
            raise ValueError("source-backed historical answers require a read epoch")
        _check_evidence_bundle(
            versions=self.versions,
            observed_at=self.observed_at,
            simulation=self.simulation,
            evidence=self.query_evidence,
            facts=self.fact_cards,
            citation_refs=self.citations,
        )
        _check_metadata_projection(observed_at=self.observed_at, labels=self.source_labels, actor=self.current_actor)
        return self


class P2V3HistoricalClarification(_P2V3HistoricalBase):
    kind: Literal["clarify"]
    prompt: Annotated[str, Field(min_length=1, max_length=1200)]
    missing_slots: tuple[P2ClarificationSlot, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def slots_are_unique(self):
        if len(self.missing_slots) != len(set(self.missing_slots)):
            raise ValueError("historical clarification slots must be unique")
        return self


class P2V3HistoricalReadResult(_P2V3HistoricalBase):
    """Typed read output from the existing v3 backend result contract."""

    kind: Literal["read_result"]
    result: "P2V3HistoricalReadPayload"
    source_labels: tuple[P2EntityDisplayLabel, ...] = Field(max_length=_OUTPUT_LABEL_MAX)
    current_actor: P2CurrentActorBinding | None

    @model_validator(mode="after")
    def read_result_matches_historical_binding(self):
        if self.read_epoch < 1:
            raise ValueError("historical read results require a read epoch")
        evidence = self.result.query_evidence
        if self.result.operation != evidence.operation:
            raise ValueError("historical read operation must match its query evidence")
        expected_fact_kind = {
            P2ReadOperation.ACTIVITIES: "activity",
            P2ReadOperation.EXPENSES: "expense",
            P2ReadOperation.DEBTS: "debt",
            P2ReadOperation.REFUND_EVENTS: "refund_event",
            P2ReadOperation.PREPAYMENT_ACCOUNTS: "prepayment_account",
            P2ReadOperation.PREPAYMENT_USAGES: "prepayment_usage",
            P2ReadOperation.PREPAYMENT_RETURN_EVENTS: "prepayment_return_event",
        }[self.result.operation]
        if any(item.fact_kind != expected_fact_kind for item in self.result.page.items):
            raise ValueError("historical read facts must match the selected operation")
        if any(item.query_evidence_ref != evidence.query_evidence_ref for item in self.result.page.items):
            raise ValueError("historical read facts must bind to their query evidence")
        if (
            self.result.page.has_more != evidence.page.has_more
            or self.result.page.range_contiguous != evidence.page.range_contiguous
            or self.result.page.stable_total_verified != evidence.page.stable_total_verified
            or self.result.page.source_version_fenced != evidence.page.source_version_fenced
            or self.result.page.unique_items_verified != evidence.page.unique_items_verified
            or self.result.page.expected_total != evidence.page.expected_total
            or (self.result.page.completeness == ReadCompleteness.COMPLETE) != evidence.model_projection_complete
        ):
            raise ValueError("historical read page and query evidence disagree")
        _check_evidence_bundle(
            versions=self.versions,
            observed_at=self.observed_at,
            simulation=self.simulation,
            evidence=(evidence,),
            facts=tuple(self.result.page.items),
        )
        _check_metadata_projection(observed_at=self.observed_at, labels=self.source_labels, actor=self.current_actor)
        return self


class P2V3HistoricalReadPage(_V3EventWireModel):
    """Display-only page retaining coverage but deliberately excluding continuation caps."""

    items: tuple[P2Fact, ...] = Field(max_length=16)
    completeness: ReadCompleteness
    has_more: StrictBool
    page_index: Annotated[StrictInt, Field(ge=0)]
    range_contiguous: StrictBool
    stable_total_verified: StrictBool
    source_version_fenced: StrictBool
    unique_items_verified: StrictBool
    expected_total: Annotated[StrictInt, Field(ge=0)] | None

    @model_validator(mode="after")
    def no_false_completeness(self):
        if self.completeness == ReadCompleteness.COMPLETE and self.has_more:
            raise ValueError("a historical complete page cannot advertise another page")
        return self


class P2V3HistoricalReadPayload(_V3EventWireModel):
    operation: P2ReadOperationField
    query_evidence: P2QueryEvidence
    page: P2V3HistoricalReadPage


def project_live_p2_read_result_for_history(value: P2ReadBackendResult) -> P2V3HistoricalReadPayload:
    """Validate a live read result, then strip its consumable continuation capability.

    The historical page retains the actual `has_more` and coverage state while
    intentionally having no `next_page_ref` field at all. This does not create a
    new live result or imply that a later page was fetched.
    """
    if type(value) is not P2ReadBackendResult:
        raise P2V3EventContractError("history projection requires the exact live P2 read result DTO")
    try:
        live = P2ReadBackendResult.model_validate_json(value.model_dump_json(), strict=True)
        page = live.page
        historical = P2V3HistoricalReadPayload(
            operation=live.operation,
            query_evidence=live.query_evidence,
            page=P2V3HistoricalReadPage(
                items=tuple(page.items),
                completeness=page.completeness,
                has_more=page.has_more,
                page_index=page.page_index,
                range_contiguous=page.range_contiguous,
                stable_total_verified=page.stable_total_verified,
                source_version_fenced=page.source_version_fenced,
                unique_items_verified=page.unique_items_verified,
                expected_total=page.expected_total,
            ),
        )
        return P2V3HistoricalReadPayload.model_validate_json(historical.model_dump_json(), strict=True)
    except (ValidationError, TypeError, ValueError):
        raise P2V3EventContractError("invalid live read result for display-only history") from None


class P2V3HistoricalProposalIntent(_P2V3HistoricalBase):
    """Existing propose semantic stores recognition only; no preview or write authority."""

    kind: Literal["proposal_intent"]
    operation: P2ProposalOperation
    recognized_intent_text: ShortText


P2V3HistoricalOutput: TypeAlias = Annotated[
    Union[
        P2V3HistoricalAnswer,
        P2V3HistoricalClarification,
        P2V3HistoricalReadResult,
        P2V3HistoricalProposalIntent,
    ],
    Field(discriminator="kind"),
]
_HISTORICAL_OUTPUT_ADAPTER = TypeAdapter(P2V3HistoricalOutput)


class P2V3EventItem(_V3EventWireModel):
    status_event: StatusEvent
    historical_output: P2V3HistoricalOutput | None

    @model_validator(mode="after")
    def status_and_output_simulation_match(self):
        if self.historical_output is not None and self.status_event.simulation is not self.historical_output.simulation:
            raise ValueError("status and historical output simulation flags differ")
        return self


class P2V3EventPollResponse(_V3EventWireModel):
    api_version: Literal["1.0.0"]
    protocol_versions: P2V3ProtocolVersions
    turn_ref: OpaqueRef
    after_seq: Annotated[StrictInt, Field(ge=0)]
    events: tuple[P2V3EventItem, ...] = Field(max_length=_POLL_LIMIT_MAX)
    next_after_seq: Annotated[StrictInt, Field(ge=0)]
    has_more: StrictBool

    @model_validator(mode="after")
    def cursor_tracks_canonical_status_rows(self):
        seqs = [item.status_event.seq for item in self.events]
        if any(seq <= self.after_seq for seq in seqs):
            raise ValueError("event sequence must be strictly after the requested cursor")
        if seqs != sorted(seqs) or len(seqs) != len(set(seqs)):
            raise ValueError("canonical status events must be strictly ordered and unique")
        expected_cursor = seqs[-1] if seqs else self.after_seq
        if self.next_after_seq != expected_cursor:
            raise ValueError("next cursor must follow the canonical event page")
        if self.has_more and not seqs:
            raise ValueError("an empty canonical page cannot advertise more events")
        if self.protocol_versions != P2_V3_VERSIONS:
            raise ValueError("event response has an unsupported or mixed candidate tuple")
        return self


class P2V3PrivateTurnSnapshot(_V3EventWireModel):
    """Private same-snapshot identity; it is linkage input, not an auth proof."""

    owner_id: UUID
    turn_id: UUID
    turn_ref: OpaqueRef
    profile_id: Literal[P2_V3_CANDIDATE_PROFILE_ID]
    protocol_versions: P2V3ProtocolVersions

    @model_validator(mode="after")
    def exact_candidate_pin(self):
        if self.protocol_versions != P2_V3_VERSIONS:
            raise ValueError("private Turn snapshot has an unsupported or mixed tuple")
        return self


class P2V3PrivateScopeGateBinding(_V3EventWireModel):
    """Private locators needed for a later, fresh membership/scope check."""

    scope_ref: OpaqueRef
    activity_ref: OpaqueRef
    private_scope_locator_id: UUID
    private_activity_locator_id: UUID


class P2V3PrivateMetadataProofBinding(_V3EventWireModel):
    """Private source-row evidence for public labels or current-actor metadata."""

    entity_kind: Literal["activity", "expense", "ledger_unit", "participant", "current_actor"]
    entity_ref: OpaqueRef
    source_ref: OpaqueRef
    scope_ref: OpaqueRef
    source_kind: Literal[
        "activities", "expenses", "ledger_units", "participants", "participant_claims.current_auth_user"
    ]
    source_receipt_ref: OpaqueRef
    private_source_row_id: UUID
    private_proof_id: UUID

    @model_validator(mode="after")
    def metadata_source_kind_matches_entity(self):
        expected = {
            "activity": "activities",
            "expense": "expenses",
            "ledger_unit": "ledger_units",
            "participant": "participants",
            "current_actor": "participant_claims.current_auth_user",
        }[self.entity_kind]
        if self.source_kind != expected:
            raise ValueError("private metadata proof source does not match its entity kind")
        if self.entity_kind != "current_actor" and self.source_ref != self.entity_ref:
            raise ValueError("private metadata proof must bind the exact public entity reference")
        if self.entity_kind == "current_actor" and self.source_ref == self.entity_ref:
            raise ValueError("current actor proof must bind its participant separately from the actor reference")
        return self


class _P2V3PrivateQevProofIdentity(_V3EventWireModel):
    query_evidence_ref: QueryEvidenceRef
    query_ref: OpaqueRef
    result_ref: OpaqueRef
    source_kind: Literal[
        "activities", "expenses", "debts", "refund_events", "prepayment_accounts",
        "prepayment_usages", "prepayment_return_events",
    ]
    source_ref: OpaqueRef
    criteria_ref: OpaqueRef
    criteria_digest: Digest
    normalized_criteria_digest: Digest
    private_query_proof_id: UUID


class P2V3PrivateQevProofBinding(_P2V3PrivateQevProofIdentity):
    """Private proof for a query admitted under one exact Activity/scope binding."""

    binding_kind: Literal["scoped"] = "scoped"
    scope_ref: OpaqueRef
    fact_rows: tuple["P2V3PrivateFactRowBinding", ...] = Field(max_length=_OUTPUT_FACT_MAX)


class P2V3PrivateFactRowBinding(_V3EventWireModel):
    fact_ref: OpaqueRef
    private_source_row_id: UUID
    private_fact_proof_id: UUID


class P2V3PrivateActivityMembershipBinding(_V3EventWireModel):
    """Private locator/proof pair for a surfaced member of an Activities collection."""

    activity_ref: OpaqueRef
    private_activity_locator_id: UUID
    private_membership_proof_id: UUID


class P2V3PrivateActivityCollectionQevProofBinding(_P2V3PrivateQevProofIdentity):
    """Private authorization lineage for unscoped read.activities.

    The private collection/query IDs are Store lookup evidence, not a bearer
    grant. A later poll must reauthorize the current principal and recheck each
    Activity membership. No JWT or reusable credential is stored here.
    """

    binding_kind: Literal["activity_collection"]
    private_collection_query_id: UUID
    private_collection_locator_id: UUID
    activity_bindings: tuple[P2V3PrivateActivityMembershipBinding, ...] = Field(max_length=_OUTPUT_FACT_MAX)
    fact_rows: tuple[P2V3PrivateFactRowBinding, ...] = Field(max_length=_OUTPUT_FACT_MAX)

    @model_validator(mode="after")
    def activity_collection_refs_are_unique(self):
        refs = [str(item.activity_ref) for item in self.activity_bindings]
        locators = [str(item.private_activity_locator_id) for item in self.activity_bindings]
        proofs = [str(item.private_membership_proof_id) for item in self.activity_bindings]
        facts = [str(item.fact_ref) for item in self.fact_rows]
        if len(refs) != len(set(refs)) or len(locators) != len(set(locators)) or len(proofs) != len(set(proofs)):
            raise ValueError("private Activities collection membership bindings must be unique")
        if len(facts) != len(set(facts)):
            raise ValueError("private collection fact-row bindings must be unique")
        if self.source_kind != "activities":
            raise ValueError("collection query proof must bind the Activities source")
        return self


P2V3PrivateQevProof: TypeAlias = Annotated[
    Union[P2V3PrivateQevProofBinding, P2V3PrivateActivityCollectionQevProofBinding],
    Field(discriminator="binding_kind"),
]


class P2V3PrivateSourceFreeHistoryGate(_V3EventWireModel):
    """Explicit server-side context classification for outputs without source reads."""

    mode: Literal["source_free"]
    basis: Literal["non_business_general", "source_free_control_intent"]
    bound_context_ref: OpaqueRef
    bound_context_digest: Digest
    bound_text_digest: Digest | None
    bound_generation: Annotated[StrictInt, Field(ge=1)]
    bound_read_epoch: Annotated[StrictInt, Field(ge=0)]
    source_projection_empty: Literal[True]
    source_projection_kinds: tuple[()] = ()
    text_origin: Literal[
        "non_business_answer", "server_controlled_clarification", "original_user_intent"
    ]

    @model_validator(mode="after")
    def basis_matches_text_origin(self):
        if self.basis == "non_business_general" and self.text_origin != "non_business_answer":
            raise ValueError("non-business source-free gate must bind non-business answer text")
        if self.basis == "source_free_control_intent" and self.text_origin == "non_business_answer":
            raise ValueError("control/intent source-free gate needs a control or original-intent text origin")
        return self


class P2V3PrivateScopeGatedHistoryGate(_V3EventWireModel):
    """Private provenance needed to recheck every source-bearing historical output."""

    mode: Literal["scope_gated"]
    bound_context_ref: OpaqueRef
    bound_context_digest: Digest
    bound_text_digest: Digest | None
    bound_generation: Annotated[StrictInt, Field(ge=1)]
    # Metadata-only source projections can be gated before a financial read
    # epoch exists; scope proof, not an invented epoch, is the requirement.
    bound_read_epoch: Annotated[StrictInt, Field(ge=0)]
    source_projection_kinds: tuple[
        Literal[
            "financial_facts", "query_evidence", "current_actor", "display_labels",
            "expense_titles", "source_history", "source_text",
        ], ...
    ] = Field(min_length=1, max_length=7)
    scopes: tuple[P2V3PrivateScopeGateBinding, ...] = Field(default=(), max_length=64)
    metadata_proofs: tuple[P2V3PrivateMetadataProofBinding, ...] = Field(max_length=_OUTPUT_LABEL_MAX + 1)
    qev_proofs: tuple[P2V3PrivateQevProof, ...] = Field(max_length=_OUTPUT_QEV_MAX)
    text_scope_refs: tuple[OpaqueRef, ...] = Field(max_length=64)
    text_collection_query_refs: tuple[QueryEvidenceRef, ...] = Field(default=(), max_length=_OUTPUT_QEV_MAX)

    @model_validator(mode="after")
    def private_gate_bindings_are_unique_and_closed(self):
        scope_refs = [str(item.scope_ref) for item in self.scopes]
        if len(scope_refs) != len(set(scope_refs)):
            raise ValueError("private history scope bindings must be unique")
        activity_to_locator: dict[str, UUID] = {}
        locator_to_activity: dict[UUID, str] = {}
        scope_to_locator: dict[str, UUID] = {}
        locator_to_scope: dict[UUID, str] = {}
        for item in self.scopes:
            activity_key = str(item.activity_ref)
            previous_activity_locator = activity_to_locator.setdefault(activity_key, item.private_activity_locator_id)
            if previous_activity_locator != item.private_activity_locator_id:
                raise ValueError("one Activity reference cannot map to conflicting private Activity locators")
            previous_activity_ref = locator_to_activity.setdefault(item.private_activity_locator_id, activity_key)
            if previous_activity_ref != activity_key:
                raise ValueError("one private Activity locator cannot map to conflicting Activity references")
            scope_key = str(item.scope_ref)
            previous_scope_locator = scope_to_locator.setdefault(scope_key, item.private_scope_locator_id)
            if previous_scope_locator != item.private_scope_locator_id:
                raise ValueError("one scope reference cannot map to conflicting private scope locators")
            previous_scope_ref = locator_to_scope.setdefault(item.private_scope_locator_id, scope_key)
            if previous_scope_ref != scope_key:
                raise ValueError("one private scope locator cannot map to conflicting scope references")
        metadata_keys = [
            (item.entity_kind, str(item.entity_ref), str(item.scope_ref), str(item.source_receipt_ref))
            for item in self.metadata_proofs
        ]
        if len(metadata_keys) != len(set(metadata_keys)):
            raise ValueError("private metadata proof bindings must be unique")
        qev_refs = [str(item.query_evidence_ref) for item in self.qev_proofs]
        if len(qev_refs) != len(set(qev_refs)):
            raise ValueError("private QEV proof bindings must be unique")
        if len(self.source_projection_kinds) != len(set(self.source_projection_kinds)):
            raise ValueError("private source projection classifications must be unique")
        for proof in self.qev_proofs:
            fact_refs = [str(item.fact_ref) for item in proof.fact_rows]
            if len(fact_refs) != len(set(fact_refs)):
                raise ValueError("private fact row bindings must be unique within a QEV")
        known_scopes = set(scope_refs)
        if any(str(item.scope_ref) not in known_scopes for item in self.metadata_proofs):
            raise ValueError("private metadata proof references an unbound scope")
        for proof in self.qev_proofs:
            if isinstance(proof, P2V3PrivateQevProofBinding) and str(proof.scope_ref) not in known_scopes:
                raise ValueError("private QEV proof references an unbound scope")
        if not self.scopes and not any(isinstance(item, P2V3PrivateActivityCollectionQevProofBinding) for item in self.qev_proofs):
            raise ValueError("scope-gated history requires a real scope or Activities collection binding")
        text_scopes = [str(item) for item in self.text_scope_refs]
        if len(text_scopes) != len(set(text_scopes)):
            raise ValueError("private text scope references must be unique")
        if not set(text_scopes).issubset(known_scopes):
            raise ValueError("source-bearing text references an unbound scope")
        text_collection_refs = [str(item) for item in self.text_collection_query_refs]
        if len(text_collection_refs) != len(set(text_collection_refs)):
            raise ValueError("private text collection query references must be unique")
        collection_refs = {
            str(item.query_evidence_ref)
            for item in self.qev_proofs
            if isinstance(item, P2V3PrivateActivityCollectionQevProofBinding)
        }
        if not set(text_collection_refs).issubset(collection_refs):
            raise ValueError("source-bearing text references an unbound Activities collection query")
        return self


P2V3PrivateHistoryGate: TypeAlias = Annotated[
    Union[P2V3PrivateSourceFreeHistoryGate, P2V3PrivateScopeGatedHistoryGate],
    Field(discriminator="mode"),
]


class P2V3PrivateSidecarBinding(_V3EventWireModel):
    """Private same-owner/Turn/sequence linkage carried by a future Store snapshot."""

    owner_id: UUID
    turn_id: UUID
    turn_ref: OpaqueRef
    profile_id: Literal[P2_V3_CANDIDATE_PROFILE_ID]
    protocol_versions: P2V3ProtocolVersions
    canonical_seq: Annotated[StrictInt, Field(ge=1)]
    output: P2V3HistoricalOutput
    history_gate: P2V3PrivateHistoryGate

    @model_validator(mode="after")
    def gate_matches_output_and_private_proofs(self):
        output = self.output
        gate = self.history_gate
        if (
            gate.bound_context_ref != output.context_ref
            or gate.bound_context_digest != output.context_digest
            or gate.bound_text_digest != _historical_text_digest(output)
            or gate.bound_generation != output.generation
            or gate.bound_read_epoch != output.read_epoch
        ):
            raise ValueError("private history gate does not bind the exact historical context")

        if isinstance(gate, P2V3PrivateSourceFreeHistoryGate):
            if isinstance(output, P2V3HistoricalAnswer):
                if output.basis != "non_business_general" or gate.basis != "non_business_general":
                    raise ValueError("only an explicit non-business answer may use this source-free path")
            elif isinstance(output, P2V3HistoricalClarification):
                if gate.basis != "source_free_control_intent" or gate.text_origin != "server_controlled_clarification":
                    raise ValueError("source-free clarification must be server-controlled and source-free")
            elif isinstance(output, P2V3HistoricalProposalIntent):
                if gate.basis != "source_free_control_intent" or gate.text_origin != "original_user_intent":
                    raise ValueError("source-free proposal intent must bind original user intent")
            else:
                raise ValueError("read results require source-gated history")
            return self

        if isinstance(output, P2V3HistoricalAnswer) and output.basis != "fresh_read_receipts":
            raise ValueError("non-business answers cannot use a source-gated history path")
        if isinstance(output, (P2V3HistoricalAnswer, P2V3HistoricalClarification, P2V3HistoricalProposalIntent)):
            if not gate.text_scope_refs and not gate.text_collection_query_refs:
                raise ValueError("source-bearing text requires a private scope or collection-query binding")

        metadata_lookup = {
            (
                item.entity_kind,
                str(item.entity_ref),
                str(item.source_ref),
                str(item.scope_ref),
                str(item.source_kind),
                str(item.source_receipt_ref),
            )
            for item in gate.metadata_proofs
        }
        qev_lookup = {
            str(item.query_evidence_ref): item for item in gate.qev_proofs
        }
        public_qevs = _historical_query_evidence(output)
        public_qev_refs = {str(item.query_evidence_ref) for item in public_qevs}
        if set(qev_lookup) != public_qev_refs:
            raise ValueError("private QEV proof bindings must exactly cover public query evidence")
        scope_by_ref = {str(item.scope_ref): item for item in gate.scopes}
        for evidence in public_qevs:
            proof = qev_lookup[str(evidence.query_evidence_ref)]
            if not _private_qev_identity_matches(proof, evidence):
                raise ValueError("private QEV proof does not bind the exact public query descriptor")
            expected_fact_refs = {
                str(_fact_public_ref(item))
                for item in _historical_facts(output)
                if str(item.query_evidence_ref) == str(evidence.query_evidence_ref)
            }
            bound_fact_refs = {str(item.fact_ref) for item in proof.fact_rows}
            if bound_fact_refs != expected_fact_refs:
                raise ValueError("private QEV proof must exactly bind each included financial fact row")
            qev_facts = tuple(
                item for item in _historical_facts(output)
                if str(item.query_evidence_ref) == str(evidence.query_evidence_ref)
            )
            if any(_fact_public_ref(item) not in evidence.matching_fact_refs for item in qev_facts):
                raise ValueError("included fact reference is absent from its public QEV")
            if isinstance(proof, P2V3PrivateQevProofBinding):
                scope = scope_by_ref[str(proof.scope_ref)]
                _validate_scoped_qev_facts(evidence, scope, qev_facts)
                if evidence.operation == P2ReadOperation.ACTIVITIES:
                    row_by_ref = {str(item.fact_ref): item for item in proof.fact_rows}
                    if any(
                        row_by_ref[str(_fact_public_ref(fact))].private_source_row_id
                        != scope.private_activity_locator_id
                        for fact in qev_facts
                    ):
                        raise ValueError("scoped Activity row binding must match its private Activity locator")
            else:
                _validate_activity_collection_qev(evidence, proof, qev_facts)
        public_metadata = _historical_metadata(output)
        expected_metadata = {
            (
                entity_kind,
                str(entity_ref),
                str(source_ref),
                str(scope_ref),
                str(source_kind),
                str(receipt_ref),
            )
            for entity_kind, entity_ref, source_ref, scope_ref, source_kind, receipt_ref in public_metadata
        }
        if not expected_metadata.issubset(metadata_lookup):
            raise ValueError("public source metadata lacks an exact private source proof")
        for entity_kind, entity_ref, _source_ref, scope_ref, _source_kind, _receipt_ref in public_metadata:
            scope = scope_by_ref.get(str(scope_ref))
            if scope is None:
                raise ValueError("public source metadata has no private Activity scope locator")
            if entity_kind == "activity" and entity_ref != scope.activity_ref:
                raise ValueError("Activity display label does not match its private Activity locator")
            if entity_kind == "current_actor":
                actor = output.current_actor
                if actor is None or actor.activity_ref != scope.activity_ref:
                    raise ValueError("current actor metadata does not match its private Activity locator")
        for scope_ref in gate.text_scope_refs:
            scope_key = str(scope_ref)
            has_metadata = any(str(proof.scope_ref) == scope_key for proof in gate.metadata_proofs)
            has_qev = any(
                isinstance(proof, P2V3PrivateQevProofBinding) and str(proof.scope_ref) == scope_key
                for proof in gate.qev_proofs
            )
            if not (has_metadata or has_qev):
                raise ValueError("source-bearing text scope has no private metadata or query proof")
        if public_qevs and not gate.qev_proofs:
            raise ValueError("financial source history requires private query proofs")
        if public_qevs and "query_evidence" not in gate.source_projection_kinds:
            raise ValueError("source projection classification omits query evidence")
        if _historical_facts(output) and "financial_facts" not in gate.source_projection_kinds:
            raise ValueError("source projection classification omits financial facts")
        if public_metadata and not gate.metadata_proofs:
            raise ValueError("source labels and actor bindings require private metadata proofs")
        if "display_labels" in gate.source_projection_kinds and not any(
            item.entity_kind in {"activity", "ledger_unit", "participant"} for item in gate.metadata_proofs
        ):
            raise ValueError("display-label source projection requires private metadata proof")
        if "expense_titles" in gate.source_projection_kinds and not any(
            item.entity_kind == "expense" for item in gate.metadata_proofs
        ):
            raise ValueError("expense-title source projection requires private expense-row proof")
        for fact in _historical_facts(output):
            if fact.fact_kind == "expense":
                exact_expense_proof = any(
                    proof.entity_kind == "expense"
                    and proof.entity_ref == fact.expense_ref
                    and proof.source_ref == fact.expense_ref
                    and proof.scope_ref == fact.scope_ref
                    and proof.source_kind == "expenses"
                    for proof in gate.metadata_proofs
                )
                if not exact_expense_proof or "expense_titles" not in gate.source_projection_kinds:
                    raise ValueError("expense title must bind its exact private expense row and scope")
        for query_ref in gate.text_collection_query_refs:
            proof = qev_lookup.get(str(query_ref))
            if not isinstance(proof, P2V3PrivateActivityCollectionQevProofBinding):
                raise ValueError("source-bearing collection text must bind an Activities collection proof")
        if "current_actor" in gate.source_projection_kinds and not any(
            item.entity_kind == "current_actor" for item in gate.metadata_proofs
        ):
            raise ValueError("current-actor source projection requires private Auth mapping metadata proof")
        if any(row[0] == "current_actor" for row in public_metadata) and "current_actor" not in gate.source_projection_kinds:
            raise ValueError("source projection classification omits current actor metadata")
        if any(row[0] != "current_actor" for row in public_metadata) and "display_labels" not in gate.source_projection_kinds:
            raise ValueError("source projection classification omits display labels")
        if isinstance(output, P2V3HistoricalClarification) and not (
            {"source_text", "source_history", "display_labels", "expense_titles"} & set(gate.source_projection_kinds)
        ):
            raise ValueError("source-bearing clarification lacks a source-text or metadata classification")
        if isinstance(output, P2V3HistoricalProposalIntent) and not (
            {"source_text", "source_history", "display_labels", "expense_titles"} & set(gate.source_projection_kinds)
        ):
            raise ValueError("source-bearing proposal intent lacks a source-text or metadata classification")
        if not public_qevs and not public_metadata and not gate.metadata_proofs:
            raise ValueError("source-gated output requires explicit metadata provenance")
        return self


def _historical_query_evidence(output: P2V3HistoricalOutput) -> tuple[P2QueryEvidence, ...]:
    if isinstance(output, P2V3HistoricalAnswer):
        return output.query_evidence
    if isinstance(output, P2V3HistoricalReadResult):
        return (output.result.query_evidence,)
    return ()


def _historical_text_digest(output: P2V3HistoricalOutput) -> Digest | None:
    if isinstance(output, P2V3HistoricalAnswer):
        text = output.text
    elif isinstance(output, P2V3HistoricalClarification):
        text = output.prompt
    elif isinstance(output, P2V3HistoricalProposalIntent):
        text = output.recognized_intent_text
    else:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _historical_metadata(
    output: P2V3HistoricalOutput,
) -> tuple[tuple[str, OpaqueRef, OpaqueRef, OpaqueRef, str, OpaqueRef], ...]:
    if not isinstance(output, (P2V3HistoricalAnswer, P2V3HistoricalReadResult)):
        return ()
    rows: list[tuple[str, OpaqueRef, OpaqueRef, OpaqueRef, str, OpaqueRef]] = []
    for label in output.source_labels:
        rows.append((label.entity_kind, label.entity_ref, label.entity_ref, label.scope_ref, label.source_kind, label.source_receipt_ref))
    actor = output.current_actor
    if actor is not None:
        rows.append(("current_actor", actor.actor_ref, actor.participant_ref, actor.activity_ref, actor.source_kind, actor.source_receipt_ref))
    return tuple(rows)


def _historical_facts(output: P2V3HistoricalOutput) -> tuple[P2Fact, ...]:
    if isinstance(output, P2V3HistoricalAnswer):
        return output.fact_cards
    if isinstance(output, P2V3HistoricalReadResult):
        return tuple(output.result.page.items)
    return ()


def _private_qev_identity_matches(proof: P2V3PrivateQevProof, evidence: P2QueryEvidence) -> bool:
    return all(
        getattr(proof, name) == getattr(evidence, name)
        for name in (
            "query_evidence_ref",
            "query_ref",
            "result_ref",
            "source_kind",
            "source_ref",
            "criteria_ref",
            "criteria_digest",
            "normalized_criteria_digest",
        )
    )


def _validate_scoped_qev_facts(evidence: P2QueryEvidence, scope: P2V3PrivateScopeGateBinding, facts: tuple[P2Fact, ...]) -> None:
    if evidence.operation == P2ReadOperation.ACTIVITIES:
        if evidence.source_kind != "activities":
            raise ValueError("scoped Activities proof must bind the Activities source")
        # The backend fences every scoped read with the Activity snapshot and
        # includes that snapshot's financial version in QEV, even when the
        # operation itself is read.activities. ActivityFact.context_version is
        # a separate projection field and must never be used to infer or
        # replace this QEV proof.
        if len(evidence.financial_versions) > 1:
            raise ValueError("scoped Activity QEV cannot bind multiple financial versions")
        version = evidence.financial_versions[0] if evidence.financial_versions else None
        if version is not None and version.activity_ref != scope.activity_ref:
            raise ValueError("scoped Activity QEV financial version does not match its private Activity locator")
        if any(fact.fact_kind != "activity" or fact.activity_ref != scope.activity_ref for fact in facts):
            raise ValueError("scoped Activity query contains a fact outside its exact Activity locator")
        if any(ref != scope.activity_ref for ref in evidence.matching_fact_refs):
            raise ValueError("scoped Activity QEV references a different Activity")
        _validate_activity_zero_classification(evidence, facts)
        return
    if len(evidence.financial_versions) > 1:
        raise ValueError("scoped financial query cannot bind multiple Activity financial versions")
    version = evidence.financial_versions[0] if evidence.financial_versions else None
    if version is not None and version.activity_ref != scope.activity_ref:
        raise ValueError("scoped financial query Activity does not match its private scope locator")
    if facts and version is None:
        raise ValueError("financial fact rows require an exact QEV financial version")
    for fact in facts:
        fact_activity = getattr(fact, "activity_ref", None)
        fact_scope = getattr(fact, "scope_ref", None)
        if fact_activity is not None and fact_activity != scope.activity_ref:
            raise ValueError("included financial fact belongs to a different Activity")
        if fact_scope is not None and fact_scope != scope.scope_ref:
            raise ValueError("included financial fact belongs to a different private scope")
        fact_version = getattr(fact, "financial_version", None)
        if fact_version is not None and (version is None or fact_version != version.financial_version):
            raise ValueError("included financial fact version differs from the public QEV")


def _validate_activity_collection_qev(
    evidence: P2QueryEvidence,
    proof: P2V3PrivateActivityCollectionQevProofBinding,
    facts: tuple[P2Fact, ...],
) -> None:
    if evidence.operation != P2ReadOperation.ACTIVITIES or evidence.source_kind != "activities":
        raise ValueError("Activity collection proof must bind read.activities")
    membership = {str(item.activity_ref): item for item in proof.activity_bindings}
    if set(membership) != {str(item) for item in evidence.matching_fact_refs}:
        raise ValueError("Activity collection membership proof must exactly bind the public QEV references")
    if any(fact.fact_kind != "activity" for fact in facts):
        raise ValueError("Activity collection QEV can bind only Activity facts")
    row_by_ref = {str(item.fact_ref): item for item in proof.fact_rows}
    for fact in facts:
        ref = str(_fact_public_ref(fact))
        member = membership.get(ref)
        row = row_by_ref.get(ref)
        if member is None or row is None or row.private_source_row_id != member.private_activity_locator_id:
            raise ValueError("Activity collection fact row must match its private membership locator")

    _validate_activity_zero_classification(evidence, facts)


def _validate_activity_zero_classification(evidence: P2QueryEvidence, facts: tuple[P2Fact, ...]) -> None:
    page = evidence.page
    zero = evidence.query_zero_classification
    if zero == "backend_zero":
        valid_zero = (
            evidence.source_query_complete
            and evidence.model_projection_complete
            and not page.has_more
            and evidence.source_total == 0
            and evidence.returned_count == 0
            and evidence.matched_count == 0
            and evidence.matched_total == 0
            and not evidence.matching_fact_refs
            and not facts
        )
        if not valid_zero:
            raise ValueError("backend_zero requires complete source and projection evidence of a true zero collection")
    elif zero == "post_filter_zero":
        valid_zero = (
            evidence.source_query_complete
            and evidence.model_projection_complete
            and not page.has_more
            and evidence.source_total is not None
            and evidence.returned_count > 0
            and evidence.matched_count == 0
            and evidence.matched_total == 0
            and not evidence.matching_fact_refs
            and not facts
        )
        if not valid_zero:
            raise ValueError("post_filter_zero requires complete coverage with source rows and zero matching Activities")
    elif zero == "unknown_or_partial":
        if evidence.source_query_complete and evidence.model_projection_complete:
            raise ValueError("complete empty Activity coverage must use an explicit zero classification")
    elif zero == "nonzero":
        if not evidence.matching_fact_refs:
            raise ValueError("nonzero Activity evidence must identify at least one matching Activity")
    else:
        raise ValueError("unsupported Activity collection zero classification")


def _fact_public_ref(fact: P2Fact) -> OpaqueRef:
    ref_field = {
        "activity": "activity_ref",
        "expense": "expense_ref",
        "debt": "debt_ref",
        "refund_event": "refund_ref",
        "prepayment_account": "account_ref",
        "prepayment_usage": "usage_ref",
        "prepayment_return_event": "return_event_ref",
    }.get(fact.fact_kind)
    if ref_field is None:
        raise P2V3EventContractError("unknown v3 fact kind in protected history")
    value = getattr(fact, ref_field)
    return value


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(_: str) -> None:
    raise ValueError("non-finite JSON number is not allowed")


def _reject_json_float(_: str) -> None:
    # All source numeric values in the reviewed DTOs are exact lexeme strings.
    raise ValueError("floating JSON numbers are not accepted in protected history")


def _raw_json_and_tree(payload: Any) -> tuple[str, dict[str, Any]]:
    try:
        if type(payload) is str:
            raw = payload
        elif type(payload) in {bytes, bytearray}:
            raw = bytes(payload).decode("utf-8", errors="strict")
        elif isinstance(payload, BaseModel):
            raw = payload.model_dump_json()
        elif isinstance(payload, Mapping):
            raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        else:
            raise ValueError("unsupported payload type")
        tree = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_json_constant,
            parse_float=_reject_json_float,
        )
        if not isinstance(tree, dict):
            raise ValueError("payload root must be an object")
        return raw, tree
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, OverflowError):
        raise P2V3EventContractError("invalid protected v3 event JSON") from None


def _check_explicit_nullable_source_fields(tree: Any) -> None:
    if isinstance(tree, list):
        for item in tree:
            _check_explicit_nullable_source_fields(item)
        return
    if not isinstance(tree, dict):
        return
    # Existing DTOs permit None but default some nullable fields. A historical
    # projection must preserve explicit source/model values rather than filling
    # a missing key from a constructor default.
    if "source_kind" in tree and "query_evidence_ref" in tree:
        if "source_total" not in tree or "matched_total" not in tree:
            raise P2V3EventContractError("historical query totals must be explicit, including null")
    if tree.get("fact_kind") == "debt" and "debt_source_variant" not in tree:
        raise P2V3EventContractError("historical debt source variant must be explicit")
    if tree.get("fact_kind") == "refund_event" and "lineage_basis" not in tree:
        raise P2V3EventContractError("historical refund lineage basis must be explicit, including null")
    for item in tree.values():
        _check_explicit_nullable_source_fields(item)


def parse_p2_v3_event_poll_query(payload: Any) -> P2V3EventPollQuery:
    raw, _ = _raw_json_and_tree(payload)
    try:
        return P2V3EventPollQuery.model_validate_json(raw, strict=True)
    except (ValidationError, TypeError, ValueError):
        raise P2V3EventContractError("invalid protected v3 event poll query") from None


def parse_p2_v3_historical_output(payload: Any) -> P2V3HistoricalOutput:
    raw, tree = _raw_json_and_tree(payload)
    _check_explicit_nullable_source_fields(tree)
    try:
        return _HISTORICAL_OUTPUT_ADAPTER.validate_json(raw, strict=True)
    except (ValidationError, TypeError, ValueError):
        raise P2V3EventContractError("invalid protected v3 historical output") from None


def parse_p2_v3_event_poll_response(payload: Any) -> P2V3EventPollResponse:
    raw, tree = _raw_json_and_tree(payload)
    _check_explicit_nullable_source_fields(tree)
    try:
        return P2V3EventPollResponse.model_validate_json(raw, strict=True)
    except (ValidationError, TypeError, ValueError):
        raise P2V3EventContractError("invalid protected v3 event poll response") from None


def _revalidate_status_event(value: Any) -> StatusEvent:
    if type(value) is not StatusEvent:
        raise P2V3EventContractError("only canonical status events may enter the v3 poll projection")
    try:
        return StatusEvent.model_validate_json(value.model_dump_json(), strict=True)
    except (ValidationError, TypeError, ValueError):
        raise P2V3EventContractError("invalid canonical status event") from None


def _revalidate_private_snapshot(value: Any) -> P2V3PrivateTurnSnapshot:
    if type(value) is not P2V3PrivateTurnSnapshot:
        raise P2V3EventContractError("private Turn snapshot has an invalid DTO type")
    try:
        return P2V3PrivateTurnSnapshot.model_validate_json(value.model_dump_json(), strict=True)
    except (ValidationError, TypeError, ValueError):
        raise P2V3EventContractError("invalid private Turn snapshot binding") from None


def _revalidate_sidecar(value: Any) -> P2V3PrivateSidecarBinding:
    if type(value) is not P2V3PrivateSidecarBinding:
        raise P2V3EventContractError("private sidecar has an invalid DTO type")
    try:
        raw = value.model_dump_json()
        _raw_json_and_tree(raw)
        return P2V3PrivateSidecarBinding.model_validate_json(raw, strict=True)
    except (ValidationError, TypeError, ValueError):
        raise P2V3EventContractError("invalid private sidecar binding") from None


def project_p2_v3_event_page(
    *,
    snapshot: P2V3PrivateTurnSnapshot,
    query: P2V3EventPollQuery,
    canonical_status_events: Sequence[StatusEvent],
    sidecars: Sequence[P2V3PrivateSidecarBinding],
    has_more: bool,
) -> P2V3EventPollResponse:
    """Bind protected outputs to canonical status rows from one Store snapshot.

    This helper checks DTO/link consistency only. The caller must obtain the
    inputs from one owner-bound read transaction and separately verify current
    authentication and membership for each protected source output.
    """
    snapshot = _revalidate_private_snapshot(snapshot)
    query = parse_p2_v3_event_poll_query(query)
    if type(has_more) is not bool:
        raise P2V3EventContractError("page has_more must be a strict boolean")
    try:
        status_events = tuple(_revalidate_status_event(item) for item in canonical_status_events)
        private_sidecars = tuple(_revalidate_sidecar(item) for item in sidecars)
    except TypeError:
        raise P2V3EventContractError("event page rows must be finite sequences") from None
    if len(status_events) > query.limit:
        raise P2V3EventContractError("canonical event page exceeds the requested limit")
    seqs = [item.seq for item in status_events]
    if any(seq <= query.after_seq for seq in seqs) or seqs != sorted(seqs) or len(seqs) != len(set(seqs)):
        raise P2V3EventContractError("canonical status event page has an invalid cursor or order")
    if has_more and len(status_events) != query.limit:
        raise P2V3EventContractError("a page with more events must fill its requested canonical limit")
    event_by_seq = {item.seq: item for item in status_events}
    output_by_seq: dict[int, P2V3HistoricalOutput] = {}
    for sidecar in private_sidecars:
        if (
            sidecar.owner_id != snapshot.owner_id
            or sidecar.turn_id != snapshot.turn_id
            or sidecar.turn_ref != snapshot.turn_ref
            or sidecar.profile_id != snapshot.profile_id
            or sidecar.protocol_versions != snapshot.protocol_versions
        ):
            raise P2V3EventContractError("protected sidecar identity differs from the owner-bound Turn snapshot")
        if sidecar.canonical_seq in output_by_seq:
            raise P2V3EventContractError("duplicate protected sidecar sequence")
        event = event_by_seq.get(sidecar.canonical_seq)
        if event is None:
            raise P2V3EventContractError("protected sidecar has no matching status event in this page")
        output = parse_p2_v3_historical_output(sidecar.output)
        if (
            output.turn_ref != snapshot.turn_ref
            or output.profile_id != snapshot.profile_id
            or output.versions != snapshot.protocol_versions
        ):
            raise P2V3EventContractError("historical output identity differs from its private binding")
        if event.simulation is not output.simulation:
            raise P2V3EventContractError("status and historical output simulation flags differ")
        output_by_seq[sidecar.canonical_seq] = output
    items = tuple(
        P2V3EventItem(status_event=event, historical_output=output_by_seq.get(event.seq))
        for event in status_events
    )
    next_after_seq = status_events[-1].seq if status_events else query.after_seq
    try:
        return P2V3EventPollResponse(
            api_version="1.0.0",
            protocol_versions=snapshot.protocol_versions,
            turn_ref=snapshot.turn_ref,
            after_seq=query.after_seq,
            events=items,
            next_after_seq=next_after_seq,
            has_more=has_more,
        )
    except ValidationError:
        raise P2V3EventContractError("projected v3 event page failed cursor validation") from None


def export_p2_v3_event_json_schemas() -> dict[str, Any]:
    """Return schemas only for a separately reviewed, hidden candidate route."""
    return {
        "poll_query": P2V3EventPollQuery.model_json_schema(),
        "historical_output": _HISTORICAL_OUTPUT_ADAPTER.json_schema(),
        "event_poll_response": P2V3EventPollResponse.model_json_schema(),
    }
