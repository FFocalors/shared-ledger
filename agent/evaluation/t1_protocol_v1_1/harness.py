"""Offline typed query binding, validation and deterministic query answer renderer."""
from __future__ import annotations

import uuid
import copy
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional

from pydantic import Field, TypeAdapter, model_validator

from . import v1_contracts as v1
from .contracts import (
    CLOSED_CAPABILITY_ACKNOWLEDGEMENT,
    QUERY_EVIDENCE_SCHEMA_VERSION,
    AnswerDecision,
    BackendCriteria,
    ModelContext,
    PostFilter,
    QueryEvidenceObservation,
    QueryEvidenceRef,
    QueryPageMetadata,
    QuerySource,
    ReadCriteriaV11,
    ReadDecision,
    SemanticDecision,
    _fact_matches,
    backend_criteria_for,
    body_digest,
    calculate_query_digest,
    canonical_hash,
    exact_hash,
    normalized_criteria,
    post_filter_for,
)


class PageReceipt(v1.ContractModel):
    """Private adapter receipt for one page; cursor material is represented only by digests."""

    page_index: Annotated[int, Field(strict=True, ge=0, le=127)]
    offset: Annotated[int, Field(strict=True, ge=0)]
    item_digests: list[Annotated[str, Field(pattern=v1.SHA256_PATTERN)]] = Field(max_length=16)
    row_identity_digests: list[Annotated[str, Field(pattern=v1.SHA256_PATTERN)]] = Field(max_length=16)
    source_version: v1.ShortText
    snapshot_fingerprint: Annotated[str, Field(pattern=v1.SHA256_PATTERN)]
    scope_fingerprint: Annotated[str, Field(pattern=v1.SHA256_PATTERN)]
    range_start: Annotated[int, Field(strict=True, ge=0)]
    range_end_exclusive: Annotated[int, Field(strict=True, ge=0)]
    total_count: Optional[Annotated[int, Field(strict=True, ge=0)]]
    cursor_in_digest: Optional[Annotated[str, Field(pattern=v1.SHA256_PATTERN)]] = None
    cursor_out_digest: Optional[Annotated[str, Field(pattern=v1.SHA256_PATTERN)]] = None


class FinancialVersionFence(v1.ContractModel):
    activity_ref: v1.ActivityRef
    private_activity_id: uuid.UUID
    financial_version: v1.FinancialVersion


class TrustedSourceSnapshot(v1.ContractModel):
    """Private, adapter-owned scope and financial-version fence for one source snapshot."""

    snapshot_id: uuid.UUID
    source_version: v1.ShortText
    observed_at: v1.WireDateTime
    scope_activity_id: Optional[uuid.UUID]
    financial_versions: list[FinancialVersionFence] = Field(max_length=16)
    membership_snapshot_id: Optional[uuid.UUID] = None

    @model_validator(mode="after")
    def snapshot_is_well_formed(self) -> "TrustedSourceSnapshot":
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("source snapshot observation time must be timezone-aware")
        refs = [item.activity_ref for item in self.financial_versions]
        ids = [item.private_activity_id for item in self.financial_versions]
        if len(refs) != len(set(refs)) or len(ids) != len(set(ids)):
            raise ValueError("source snapshot financial-version map must have unique refs and private IDs")
        return self


class BoundQueryEvidence(v1.ContractModel):
    """Private Harness/adapter state; never serialize this model into ModelContext."""

    query_ref: QueryEvidenceRef
    result_ref: v1.ReadResultRef
    result_id: uuid.UUID
    owner_id: uuid.UUID
    source_turn_id: uuid.UUID
    generation: Annotated[int, Field(strict=True, ge=1)]
    expected_revision: Annotated[int, Field(strict=True, ge=1)]
    freshness_epoch: Annotated[int, Field(strict=True, ge=1)]
    scope_activity_id: Optional[uuid.UUID]
    scope_ref: Optional[v1.ActivityRef]
    operation: v1.ReadOperation
    criteria: ReadCriteriaV11
    normalized_criteria: str
    backend_criteria: BackendCriteria
    post_filter: PostFilter
    observed_at: v1.WireDateTime
    context_version: Annotated[int, Field(strict=True, ge=1)]
    schema_version: Annotated[str, Field(pattern=r"^1\.1\.0$")]
    source: QuerySource
    source_version: v1.ShortText
    source_fingerprint: Annotated[str, Field(pattern=v1.SHA256_PATTERN)]
    source_snapshot: TrustedSourceSnapshot
    source_snapshot_fingerprint: Annotated[str, Field(pattern=v1.SHA256_PATTERN)]
    query_digest: Annotated[str, Field(pattern=v1.SHA256_PATTERN)]
    body_digest: Annotated[str, Field(pattern=v1.SHA256_PATTERN)]
    simulation: bool
    page: QueryPageMetadata
    page_receipts: list[PageReceipt] = Field(min_length=1, max_length=128)
    source_integrity: Literal["trusted_adapter"]
    source_error: Optional[v1.ShortText] = None
    capacity_overflow: bool = False

    @model_validator(mode="after")
    def source_and_page_receipts_are_consistent(self) -> "BoundQueryEvidence":
        if self.source_integrity != "trusted_adapter":
            raise ValueError("query source integrity must come from the trusted adapter boundary")
        if self.source_error is not None:
            raise ValueError("source errors cannot be represented as empty query evidence")
        if self.capacity_overflow:
            raise ValueError("capacity overflow cannot be represented as a query result")
        if self.simulation != (self.source == QuerySource.SYNTHETIC_SIMULATION):
            raise ValueError("simulation flag must match the closed source allowlist")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("private query observation time must be timezone-aware")
        _validate_page_receipts(
            self.page,
            self.page_receipts,
            expected_source_version=self.source_version,
            expected_scope_fingerprint=canonical_hash({"scope_activity_id": str(self.scope_activity_id) if self.scope_activity_id else None}),
            expected_snapshot_fingerprint=self.source_snapshot_fingerprint,
        )
        if self.source_snapshot_fingerprint != exact_hash(self.source_snapshot):
            raise ValueError("private source snapshot fingerprint must hash its exact source fence")
        if self.source_fingerprint != self.source_snapshot_fingerprint:
            raise ValueError("private source fingerprint must bind the complete source and financial snapshot")
        if (
            self.source_snapshot.source_version != self.source_version
            or self.source_snapshot.scope_activity_id != self.scope_activity_id
            or self.source_snapshot.observed_at != self.observed_at
        ):
            raise ValueError("private source snapshot must match the query scope, source version and observation time")
        return self


class CurrentQueryState(v1.ContractModel):
    """Independent trusted currentness lookup keyed by query/result identity, not model metadata."""

    query_ref: QueryEvidenceRef
    result_id: uuid.UUID
    owner_id: uuid.UUID
    source_turn_id: uuid.UUID
    generation: Annotated[int, Field(strict=True, ge=1)]
    expected_revision: Annotated[int, Field(strict=True, ge=1)]
    freshness_epoch: Annotated[int, Field(strict=True, ge=1)]
    current_generation: Annotated[int, Field(strict=True, ge=1)]
    current_revision: Annotated[int, Field(strict=True, ge=1)]
    current_freshness_epoch: Annotated[int, Field(strict=True, ge=1)]
    status: Literal["current", "stale"]
    scope_activity_id: Optional[uuid.UUID]
    context_version: Annotated[int, Field(strict=True, ge=1)]
    source: QuerySource
    source_version: v1.ShortText
    source_fingerprint: Annotated[str, Field(pattern=v1.SHA256_PATTERN)]
    source_snapshot_fingerprint: Annotated[str, Field(pattern=v1.SHA256_PATTERN)]
    observed_at: v1.WireDateTime
    query_digest: Annotated[str, Field(pattern=v1.SHA256_PATTERN)]
    body_digest: Annotated[str, Field(pattern=v1.SHA256_PATTERN)]

    @model_validator(mode="after")
    def time_is_aware(self) -> "CurrentQueryState":
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("current query state observation time must be timezone-aware")
        return self


@dataclass(frozen=True)
class ValidatedQuery:
    observation: QueryEvidenceObservation
    result: v1.ModelReadResult
    matched_facts: tuple[Any, ...]
    complete: bool
    binding: BoundQueryEvidence
    binding_digest: str
    current_state: CurrentQueryState
    current_state_digest: str


@dataclass(frozen=True)
class ValidatedQuerySet:
    context: ModelContext
    queries: tuple[ValidatedQuery, ...]
    context_digest: str


def _validate_page_receipts(
    page: QueryPageMetadata,
    receipts: list[PageReceipt],
    *,
    expected_source_version: str,
    expected_scope_fingerprint: str,
    expected_snapshot_fingerprint: str,
) -> None:
    if len(receipts) != page.pages_seen:
        raise ValueError("private page receipt count must match visible pages_seen")
    expected_total = page.expected_total
    next_offset = 0
    previous_cursor_out: Optional[str] = None
    flat_item_digests: list[str] = []
    flat_row_identity_digests: list[str] = []
    stable_snapshot: Optional[str] = None
    for index, receipt in enumerate(receipts):
        if receipt.page_index != index:
            raise ValueError("page receipts must have consecutive zero-based indexes")
        if receipt.offset != next_offset:
            raise ValueError("page receipt ranges must be contiguous without gaps or overlap")
        if receipt.range_start != receipt.offset or receipt.range_end_exclusive != receipt.offset + len(receipt.item_digests):
            raise ValueError("private source page start/end fence must exactly cover the page body")
        if receipt.source_version != expected_source_version:
            raise ValueError("every page must be fenced to the exact trusted source version")
        if receipt.scope_fingerprint != expected_scope_fingerprint:
            raise ValueError("every page must be fenced to the exact private scope")
        if receipt.snapshot_fingerprint != expected_snapshot_fingerprint:
            raise ValueError("every page must be fenced to the exact trusted source snapshot")
        if stable_snapshot is None:
            stable_snapshot = receipt.snapshot_fingerprint
        elif receipt.snapshot_fingerprint != stable_snapshot:
            raise ValueError("all pages must belong to one stable source snapshot")
        if expected_total is not None and receipt.total_count != expected_total:
            raise ValueError("page receipt totals must remain stable across pages")
        if expected_total is None and receipt.total_count is not None:
            raise ValueError("unknown complete-source count must stay unknown in every private page receipt")
        if index == 0 and receipt.cursor_in_digest is not None:
            raise ValueError("first page cannot have an incoming cursor")
        if index > 0 and receipt.cursor_in_digest != previous_cursor_out:
            raise ValueError("page cursor digest chain must be continuous")
        if len(receipt.row_identity_digests) != len(receipt.item_digests):
            raise ValueError("each page item body digest needs one private stable-row identity digest")
        next_offset += len(receipt.item_digests)
        flat_item_digests.extend(receipt.item_digests)
        flat_row_identity_digests.extend(receipt.row_identity_digests)
        previous_cursor_out = receipt.cursor_out_digest
    if page.complete:
        if expected_total is None:
            raise ValueError("complete evidence requires exact source total metadata")
        if next_offset != expected_total:
            raise ValueError("complete page ranges must reach the stable expected_total")
        if previous_cursor_out is not None:
            raise ValueError("complete page ranges cannot leave an outgoing cursor")
    else:
        if not (page.has_more or page.truncated):
            raise ValueError("incomplete page ranges must report truncation or more data")
        if page.has_more and previous_cursor_out is None:
            raise ValueError("more pages require a private outgoing cursor digest")
    if expected_total is not None and next_offset > expected_total:
        raise ValueError("page ranges cannot exceed the stable expected_total")
    if len(flat_row_identity_digests) != len(set(flat_row_identity_digests)):
        raise ValueError("stable source row identities must be unique across every page")


def row_identity_digest(kind: str, entity_id: uuid.UUID) -> str:
    """Hash a trusted entity/derived-row key, never an amount/title-derived identity."""
    return canonical_hash({"kind": kind, "entity_id": str(entity_id)})


def _item_digests(result: v1.ToolReadResult) -> list[str]:
    return [canonical_hash(item) for item in result.body.items]


def _scope_ref(criteria: ReadCriteriaV11) -> Optional[v1.ActivityRef]:
    return None if criteria.kind == "activities" else criteria.activity_ref


def bind_trusted_query(
    *,
    query_ref: QueryEvidenceRef,
    owner_id: uuid.UUID,
    turn_id: uuid.UUID,
    generation: int,
    expected_revision: int,
    freshness_epoch: int,
    scope_activity_id: Optional[uuid.UUID],
    result: v1.ToolReadResult,
    criteria: ReadCriteriaV11,
    context_version: int,
    source: QuerySource,
    source_version: str,
    source_fingerprint: str,
    source_snapshot: TrustedSourceSnapshot,
    page: QueryPageMetadata,
    page_receipts: list[PageReceipt],
) -> BoundQueryEvidence:
    """Synthetic-only issuer for this offline package.

    A future P2 source label is part of the wire vocabulary only. It cannot be
    activated by a caller-controlled string or by hand-built ToolReadResult.
    A separately reviewed runtime adapter must replace this boundary before
    any non-synthetic result can be issued.
    """
    if source != QuerySource.SYNTHETIC_SIMULATION or not result.simulation:
        raise ValueError("offline v1.1 issuer accepts synthetic simulation results only")
    if source_snapshot.source_version != source_version or source_snapshot.observed_at != result.observed_at:
        raise ValueError("synthetic source snapshot must match result version and observation time")
    if source_snapshot.scope_activity_id != scope_activity_id:
        raise ValueError("synthetic source snapshot must match the private activity scope")
    snapshot_fingerprint = exact_hash(source_snapshot)
    if source_fingerprint != snapshot_fingerprint:
        raise ValueError("source fingerprint must bind the exact private source/financial snapshot")
    backend = backend_criteria_for(criteria)
    post_filter = post_filter_for(criteria)
    if criteria.kind == "activities" and scope_activity_id is not None:
        raise ValueError("activity-list queries use a none backend scope")
    if criteria.kind != "activities" and scope_activity_id is None:
        raise ValueError("expense/debt queries require a verified private activity scope")
    query_digest = calculate_query_digest(
        operation=result.operation,
        criteria=criteria,
        backend_criteria=backend,
        post_filter=post_filter,
        scope_activity_id=scope_activity_id,
        context_version=context_version,
        schema_version=QUERY_EVIDENCE_SCHEMA_VERSION,
        source=source,
        source_version=source_version,
    )
    return BoundQueryEvidence(
        query_ref=query_ref,
        result_ref=result.result_ref,
        result_id=result.result_id,
        owner_id=owner_id,
        source_turn_id=turn_id,
        generation=generation,
        expected_revision=expected_revision,
        freshness_epoch=freshness_epoch,
        scope_activity_id=scope_activity_id,
        scope_ref=_scope_ref(criteria),
        operation=result.operation,
        criteria=criteria,
        normalized_criteria=normalized_criteria(result.operation, criteria),
        backend_criteria=backend,
        post_filter=post_filter,
        observed_at=result.observed_at,
        context_version=context_version,
        schema_version=QUERY_EVIDENCE_SCHEMA_VERSION,
        source=source,
        source_version=source_version,
        source_fingerprint=source_fingerprint,
        source_snapshot=source_snapshot,
        source_snapshot_fingerprint=snapshot_fingerprint,
        query_digest=query_digest,
        body_digest=body_digest(result.body),
        simulation=result.simulation,
        page=page,
        page_receipts=page_receipts,
        source_integrity="trusted_adapter",
    )


def make_query_observation(binding: BoundQueryEvidence, result: v1.ToolReadResult) -> QueryEvidenceObservation:
    matched = [fact for fact in result.body.items if _fact_matches(fact, binding.criteria)]
    return QueryEvidenceObservation(
        query_ref=binding.query_ref,
        result_ref=binding.result_ref,
        operation=binding.operation,
        criteria=binding.criteria,
        normalized_criteria=binding.normalized_criteria,
        backend_criteria=binding.backend_criteria,
        post_filter=binding.post_filter,
        context_version=binding.context_version,
        schema_version=binding.schema_version,
        source=binding.source,
        source_version=binding.source_version,
        observed_at=binding.observed_at,
        simulation=binding.simulation,
        returned_count=len(result.body.items),
        matched_count=len(matched),
        matching_fact_citations=[fact.evidence_ref for fact in matched],
        page=binding.page,
        query_digest=binding.query_digest,
        body_digest=binding.body_digest,
    )


def validate_stable_query_bindings(
    existing: list[BoundQueryEvidence],
    candidates: list[BoundQueryEvidence],
    *,
    source_turn_id: uuid.UUID,
) -> list[BoundQueryEvidence]:
    """Preserve v1 immutable-reference behavior across resumes/revisions."""
    combined = list(existing)
    by_ref: dict[QueryEvidenceRef, BoundQueryEvidence] = {}
    by_id: dict[uuid.UUID, BoundQueryEvidence] = {}
    for item in combined:
        if item.source_turn_id != source_turn_id:
            raise ValueError("query evidence cannot be imported across Turns")
        if item.query_ref in by_ref or item.result_id in by_id:
            raise ValueError("query refs and actual result UUIDs are unique within one Turn")
        by_ref[item.query_ref] = item
        by_id[item.result_id] = item
    candidate_refs: set[QueryEvidenceRef] = set()
    candidate_ids: set[uuid.UUID] = set()
    for candidate in candidates:
        if candidate.source_turn_id != source_turn_id:
            raise ValueError("query evidence cannot be imported across Turns")
        if candidate.query_ref in candidate_refs or candidate.result_id in candidate_ids:
            raise ValueError("candidate query refs and result UUIDs must be unique")
        candidate_refs.add(candidate.query_ref)
        candidate_ids.add(candidate.result_id)
        old = by_id.get(candidate.result_id)
        if old is not None:
            if old != candidate:
                raise ValueError("a stable result UUID cannot change owner, Turn, scope, query, source or freshness")
            continue
        if candidate.query_ref in by_ref:
            raise ValueError("a stable query ref cannot be rebound to a different actual result")
        combined.append(candidate)
        by_ref[candidate.query_ref] = candidate
        by_id[candidate.result_id] = candidate
    return combined


def validate_context_bindings(
    context: ModelContext,
    *,
    current_owner_id: uuid.UUID,
    current_turn_id: uuid.UUID,
    generation: int,
    expected_revision: int,
    freshness_epoch: int,
    current_context_version: int,
    current_query_states: list[CurrentQueryState],
    trusted_tool_results: list[v1.ToolReadResult],
    bound_queries: list[BoundQueryEvidence],
    bound_references: list[v1.BoundReference],
    bound_evidence_references: list[v1.BoundEvidenceReference],
    bound_read_results: list[v1.BoundReadResultReference],
) -> ValidatedQuerySet:
    """Reconcile visible evidence with trusted actual results and independent live private state."""
    # Pydantic does not rerun validators when an already-created model instance is
    # passed to model_validate. These private objects can contain nested mutable
    # values, so reparse their wire projections at the trust boundary.
    context = ModelContext.model_validate(context.model_dump(mode="python"))
    bound_queries = [BoundQueryEvidence.model_validate(item.model_dump(mode="python")) for item in bound_queries]
    current_query_states = [CurrentQueryState.model_validate(item.model_dump(mode="python")) for item in current_query_states]
    trusted_tool_results = [v1.ToolReadResult.model_validate(item.model_dump(mode="python")) for item in trusted_tool_results]
    bound_references = [TypeAdapter(v1.BoundReference).validate_python(item.model_dump(mode="python")) for item in bound_references]
    bound_evidence_references = [
        TypeAdapter(v1.BoundEvidenceReference).validate_python(item.model_dump(mode="python"))
        for item in bound_evidence_references
    ]
    bound_read_results = [
        v1.BoundReadResultReference.model_validate(item.model_dump(mode="python"))
        for item in bound_read_results
    ]
    base = v1.ModelContext.model_validate(context.model_dump(mode="json", exclude={"query_observations", "intent_classification"}))
    v1.validate_model_context_bindings(
        base,
        source_turn_id=current_turn_id,
        bound_references=bound_references,
        bound_evidence_references=bound_evidence_references,
        bound_read_results=bound_read_results,
    )
    if context.context_version != current_context_version:
        raise ValueError("ModelContext context_version is stale")
    visible_by_ref = {item.query_ref: item for item in context.query_observations}
    private_by_ref = {item.query_ref: item for item in bound_queries}
    current_by_ref = {item.query_ref: item for item in current_query_states}
    actual_by_id = {item.result_id: item for item in trusted_tool_results}
    if len(actual_by_id) != len(trusted_tool_results):
        raise ValueError("trusted actual ToolReadResult IDs must be unique")
    persisted_results = {item.result_ref: item for item in bound_read_results}
    visible_results = {item.result_ref: item for item in context.read_results}
    if set(private_by_ref) != set(visible_by_ref) or len(private_by_ref) != len(bound_queries):
        raise ValueError("every visible query token must resolve to private owner/Turn state")
    if set(current_by_ref) != set(visible_by_ref) or len(current_by_ref) != len(current_query_states):
        raise ValueError("every visible query token must have an independent current-state binding")
    if set(actual_by_id) != {item.result_id for item in bound_queries}:
        raise ValueError("trusted actual results and private query bindings must correspond exactly")
    if set(visible_results) != {item.result_ref for item in bound_queries}:
        raise ValueError("all visible results must have a private query binding")
    activity_bindings = {item.ref: item for item in bound_references if isinstance(item, v1.BoundActivityReference)}
    if not isinstance(context.verified_scope, (v1.ModelActivityScope, v1.ModelNoActivityScope)):
        raise ValueError("query grounding requires a typed current scope")
    validated: list[ValidatedQuery] = []
    for query_ref, visible in visible_by_ref.items():
        private = private_by_ref[query_ref]
        current = current_by_ref[query_ref]
        if (
            private.owner_id != current_owner_id
            or private.source_turn_id != current_turn_id
            or private.generation > generation
            or private.expected_revision > expected_revision
            or private.freshness_epoch > freshness_epoch
        ):
            raise ValueError("query cannot come from a future owner/Turn/generation/CAS revision/freshness epoch")
        if private.source != QuerySource.SYNTHETIC_SIMULATION or not private.simulation:
            raise ValueError("offline harness accepts synthetic query evidence only; future adapter labels are not authority")
        if (
            current.owner_id != private.owner_id
            or current.source_turn_id != private.source_turn_id
            or current.generation != private.generation
            or current.expected_revision != private.expected_revision
            or current.freshness_epoch != private.freshness_epoch
            or current.current_generation != generation
            or current.current_revision != expected_revision
            or current.current_freshness_epoch != freshness_epoch
            or current.result_id != private.result_id
            or current.scope_activity_id != private.scope_activity_id
            or current.context_version != private.context_version
            or current.source != private.source
            or current.source_version != private.source_version
            or current.source_fingerprint != private.source_fingerprint
            or current.source_snapshot_fingerprint != private.source_snapshot_fingerprint
            or current.observed_at != private.observed_at
            or current.query_digest != private.query_digest
            or current.body_digest != private.body_digest
        ):
            raise ValueError("per-query state does not confirm issuance identity and current owner/Turn checkpoint")
        # Issuance values remain immutable and may be older than the current CAS
        # checkpoint. The independent per-query state above binds that issuance to
        # the current checkpoint and explicitly says whether it is still current.
        if private.source_integrity != "trusted_adapter" or private.source_error is not None or private.capacity_overflow:
            raise ValueError("query requires trusted source integrity without error or overflow")
        if (
            visible.operation != private.operation
            or visible.criteria != private.criteria
            or visible.normalized_criteria != private.normalized_criteria
            or visible.backend_criteria != private.backend_criteria
            or visible.post_filter != private.post_filter
            or visible.result_ref != private.result_ref
            or visible.query_digest != private.query_digest
            or visible.body_digest != private.body_digest
            or visible.page != private.page
            or visible.source != private.source
            or visible.source_version != private.source_version
            or visible.schema_version != private.schema_version
            or visible.observed_at != private.observed_at
            or visible.context_version != private.context_version
            or visible.simulation != private.simulation
        ):
            raise ValueError("visible typed query must match its immutable private binding")
        if private.normalized_criteria != normalized_criteria(private.operation, private.criteria):
            raise ValueError("private normalized criteria are not canonical")
        if private.backend_criteria != backend_criteria_for(private.criteria) or private.post_filter != post_filter_for(private.criteria):
            raise ValueError("private backend/post-filter stages must preserve the full typed query")
        expected_query_digest = calculate_query_digest(
            operation=private.operation,
            criteria=private.criteria,
            backend_criteria=private.backend_criteria,
            post_filter=private.post_filter,
            scope_activity_id=private.scope_activity_id,
            context_version=private.context_version,
            schema_version=private.schema_version,
            source=private.source,
            source_version=private.source_version,
        )
        if visible.query_digest != expected_query_digest:
            raise ValueError("query digest must bind criteria, post-filter, scope and versions")
        expected_scope_ref = None if private.criteria.kind == "activities" else private.criteria.activity_ref
        if private.scope_ref != expected_scope_ref:
            raise ValueError("private scope token does not match the explicit query")
        expected_permission = {
            "activities": v1.HarnessPermission.READ_ACTIVITIES,
            "expenses": v1.HarnessPermission.READ_EXPENSES,
            "debts": v1.HarnessPermission.READ_DEBTS,
        }[private.criteria.kind]
        if expected_permission not in context.available_permissions or expected_permission not in context.verified_scope.permissions:
            raise ValueError("typed query requires a granted capability in current ModelContext and verified scope")
        if private.criteria.kind == "activities":
            if not isinstance(context.verified_scope, v1.ModelNoActivityScope) or private.scope_activity_id is not None:
                raise ValueError("global activity query must use ModelNoActivityScope, never a selected activity scope")
        else:
            if (
                not isinstance(context.verified_scope, v1.ModelActivityScope)
                or context.verified_scope.activity_ref != private.criteria.activity_ref
            ):
                raise ValueError("expense/debt query must use the exact selected activity scope")
            activity = activity_bindings.get(private.criteria.activity_ref)
            if activity is None or activity.entity_id != private.scope_activity_id:
                raise ValueError("query scope token must bind to the same immutable Activity UUID")
            participant_ref = private.criteria.participant_ref
            if participant_ref is not None:
                participant = next(
                    (
                        item for item in bound_references
                        if isinstance(item, v1.BoundParticipantReference) and item.ref == participant_ref
                    ),
                    None,
                )
                if (
                    participant is None
                    or participant.source_turn_id != current_turn_id
                    or participant.scope_activity_id != private.scope_activity_id
                ):
                    raise ValueError("participant query filter must resolve to a same-Turn participant in the selected activity")
        actual = actual_by_id.get(private.result_id)
        if actual is None or (
            actual.result_id != private.result_id
            or actual.result_ref != private.result_ref
            or actual.operation != private.operation
            or actual.observed_at != private.observed_at
            or actual.context_version != private.context_version
            or actual.simulation != private.simulation
            or body_digest(actual.body) != private.body_digest
        ):
            raise ValueError("trusted actual ToolReadResult does not match the bound result identity/body")
        visible_result = visible_results.get(private.result_ref)
        if visible_result is None or (
            visible_result.operation != actual.operation
            or visible_result.observed_at != actual.observed_at
            or visible_result.context_version != actual.context_version
            or visible_result.simulation != actual.simulation
            or visible_result.body != actual.body
            or body_digest(visible_result.body) != private.body_digest
        ):
            raise ValueError("visible v1 result must exactly project the trusted typed ToolReadResult")
        persisted = persisted_results.get(private.result_ref)
        if persisted is None or (
            persisted.result_id != private.result_id
            or persisted.source_turn_id != current_turn_id
            or persisted.operation != actual.operation
            or persisted.observed_at != actual.observed_at
            or persisted.context_version != private.context_version
        ):
            raise ValueError("result must match its immutable per-result v1 issuance binding")
        if len(actual.body.items) != visible.returned_count:
            raise ValueError("returned_count must match the complete typed result body")
        _validate_page_receipts(
            private.page,
            private.page_receipts,
            expected_source_version=private.source_version,
            expected_scope_fingerprint=canonical_hash({"scope_activity_id": str(private.scope_activity_id) if private.scope_activity_id else None}),
            expected_snapshot_fingerprint=private.source_snapshot_fingerprint,
        )
        page_digests = [digest for page in private.page_receipts for digest in page.item_digests]
        if page_digests != [canonical_hash(fact) for fact in actual.body.items]:
            raise ValueError("private page ranges and cursor chain must reconstruct the actual result body")
        evidence_for_result = {
            item.evidence_ref: item
            for item in bound_evidence_references
            if item.source_result_id == private.result_id
            and item.source_turn_id == current_turn_id
            and item.context_version == private.context_version
        }
        row_digests: list[str] = []
        for fact in actual.body.items:
            bound_evidence = evidence_for_result.get(fact.evidence_ref)
            if bound_evidence is None or bound_evidence.kind != fact.kind:
                raise ValueError("every result row needs an immutable typed evidence-to-entity binding")
            row_digests.append(row_identity_digest(fact.kind, bound_evidence.entity_id))
        page_row_digests = [digest for page in private.page_receipts for digest in page.row_identity_digests]
        if page_row_digests != row_digests or len(page_row_digests) != len(set(page_row_digests)):
            raise ValueError("private page row identities must exactly match unique bound entity/derived-row identities")
        snapshot_by_ref = {item.activity_ref: item for item in private.source_snapshot.financial_versions}
        if private.criteria.kind == "activities":
            if private.source_snapshot.membership_snapshot_id is None:
                raise ValueError("activity query, including an empty result, requires a trusted membership snapshot ID")
            activity_bindings_by_ref = {
                item.ref: item
                for item in bound_references
                if isinstance(item, v1.BoundActivityReference)
            }
            for fact in actual.body.items:
                activity = activity_bindings_by_ref.get(fact.activity_ref)
                version_fence = snapshot_by_ref.get(fact.activity_ref)
                if (
                    activity is None
                    or version_fence is None
                    or version_fence.private_activity_id != activity.entity_id
                ):
                    raise ValueError("every activity row must map to its trusted financial-version snapshot and private entity ID")
            if set(snapshot_by_ref) != {fact.activity_ref for fact in actual.body.items}:
                raise ValueError("activity membership snapshot and per-activity financial versions must exactly cover the full backend body")
        else:
            scope_fence = snapshot_by_ref.get(private.criteria.activity_ref)
            if (
                scope_fence is None
                or scope_fence.private_activity_id != private.scope_activity_id
                or len(private.source_snapshot.financial_versions) != 1
            ):
                raise ValueError("expense/debt query requires exactly one current financial-version fence for its private activity scope")
        matched = [fact for fact in actual.body.items if _fact_matches(fact, private.criteria)]
        matched_citations = [fact.evidence_ref for fact in matched]
        if visible.matched_count != len(matched) or visible.matching_fact_citations != matched_citations:
            raise ValueError("matched facts must be recalculated from the full body and exact post-filter")
        if visible.operation.value not in set(v1.CAPABILITY_REGISTRY[0].operations):
            raise ValueError("query operation is outside the unchanged v1 CAP allowlist")
        if visible.operation not in context.available_permissions:
            raise ValueError("Harness did not grant the query operation")
        if current.status == "stale":
            continue
        validated.append(ValidatedQuery(
            observation=visible,
            result=visible_result,
            matched_facts=tuple(matched),
            complete=visible.page.complete,
            binding=private,
            binding_digest=canonical_hash(private),
            current_state=current,
            current_state_digest=canonical_hash(current),
        ))
    # Detach the validated state from caller-owned mutable Pydantic objects. The renderer
    # hashes and recalculates it again to close the validation/render TOCTOU gap.
    frozen_context = copy.deepcopy(context)
    frozen_queries = tuple(
        ValidatedQuery(
            observation=copy.deepcopy(item.observation),
            result=copy.deepcopy(item.result),
            matched_facts=tuple(copy.deepcopy(item.matched_facts)),
            complete=item.complete,
            binding=copy.deepcopy(item.binding),
            binding_digest=exact_hash(item.binding),
            current_state=copy.deepcopy(current_by_ref[item.observation.query_ref]),
            current_state_digest=exact_hash(current_by_ref[item.observation.query_ref]),
        )
        for item in validated
    )
    return ValidatedQuerySet(
        context=frozen_context,
        queries=frozen_queries,
        context_digest=exact_hash(frozen_context),
    )


def validate_decision(
    decision: SemanticDecision,
    context: ModelContext,
    *,
    validated_queries: Optional[ValidatedQuerySet] = None,
    allow_closed_capability_ack: bool = False,
    trusted_bound_references: Optional[list[v1.BoundReference]] = None,
    current_turn_id: Optional[uuid.UUID] = None,
) -> None:
    """Keep v1 financial/permission rules; query citations require exact renderer output."""
    v1.validate_capability_registry(v1.CAPABILITY_REGISTRY)
    if isinstance(decision, AnswerDecision):
        facts_and_policy = {
            fact.evidence_ref
            for result in context.read_results
            for fact in result.body.items
        } | {item.evidence_ref for item in context.policy_evidence}
        query_refs = {item.query_ref for item in context.query_observations}
        citations = set(decision.citations)
        if any(citation not in facts_and_policy and citation not in query_refs for citation in citations):
            raise ValueError("citations must resolve to facts, policy or query refs in this exact context")
        if decision.basis == "grounded" and not citations:
            raise ValueError("grounded answers require typed current-context evidence")
        if decision.basis == "conversation":
            if citations:
                raise ValueError("conversation-only answers cannot claim typed evidence")
            if context.intent_classification == "business":
                if not allow_closed_capability_ack or decision.text != CLOSED_CAPABILITY_ACKNOWLEDGEMENT:
                    raise ValueError("business context cannot fall back to conversation except through the explicit closed-capability acknowledgement")
            elif context.read_results or context.query_observations or context.available_permissions:
                raise ValueError("non-business conversation context cannot carry business query results or capabilities")
        fact_refs = {
            fact.evidence_ref
            for result in context.read_results
            for fact in result.body.items
        }
        if citations.intersection(fact_refs):
            if validated_queries is None:
                raise ValueError("fact citations from read results require current trusted query validation")
            _assert_validated_query_set(validated_queries, expected_context=context)
            current_matches = {
                fact.evidence_ref
                for query in validated_queries.queries
                for fact in query.matched_facts
            }
            if not citations.intersection(fact_refs).issubset(current_matches):
                raise ValueError("fact citations must come from the current post-filter match set")
            if citations.intersection(fact_refs) != citations or query_refs.intersection(citations) or citations.intersection({item.evidence_ref for item in context.policy_evidence}):
                raise ValueError("fact-grounded answers cannot mix financial facts with query/policy claims")
            rendered_facts = render_fact_answer(
                validated_queries,
                [citation for citation in decision.citations if citation in fact_refs],
                expected_context=context,
            )
            if decision.text != rendered_facts.text or decision.citations != rendered_facts.citations:
                raise ValueError("fact citations only authorize exact trusted typed-fact rendering")
        if query_refs.intersection(citations):
            if validated_queries is None:
                raise ValueError("query citation requires a validated trusted query set")
            _assert_validated_query_set(validated_queries, expected_context=context)
            rendered = render_query_answer(validated_queries, [c for c in decision.citations if c in query_refs])
            if decision.text != rendered.text or decision.citations != rendered.citations:
                raise ValueError("query citations only authorize the exact deterministic query renderer output")
        policy_refs = {item.evidence_ref for item in context.policy_evidence}
        if citations.intersection(policy_refs):
            if citations != citations.intersection(policy_refs):
                raise ValueError("policy citations cannot be mixed with query or financial facts")
            rendered_policy = render_policy_answer(
                context,
                [citation for citation in decision.citations if citation in policy_refs],
            )
            if decision.text != rendered_policy.text or decision.citations != rendered_policy.citations:
                raise ValueError("policy citations only authorize exact deterministic static-policy rendering")
        return
    if isinstance(decision, v1.ClarifyDecision):
        return
    if isinstance(decision, ReadDecision):
        if decision.criteria.kind != "activities" and (
            not isinstance(context.verified_scope, v1.ModelActivityScope)
            or context.verified_scope.activity_ref != decision.criteria.activity_ref
        ):
            raise ValueError("expense/debt ReadDecision criteria must use the exact verified selected activity")
        criteria_json = decision.criteria.model_dump(mode="json", exclude={"title_contains"}, exclude_none=True)
        v1_criteria = TypeAdapter(v1.ReadCriteria).validate_json(
            json.dumps(criteria_json, ensure_ascii=False, separators=(",", ":"))
        )
        old_decision = v1.ReadDecision(kind="read", operation=decision.operation, criteria=v1_criteria)
        base = v1.ModelContext.model_validate(context.model_dump(mode="json", exclude={"query_observations", "intent_classification"}))
        # Reuse the complete frozen v1 scope, permission and typed-reference checks.
        v1.validate_decision_against_context(old_decision, base)
        if decision.criteria.kind != "activities" and decision.criteria.participant_ref is not None:
            if trusted_bound_references is None or current_turn_id is None:
                raise ValueError("participant-filtered ReadDecision requires its private same-Turn binding map")
            activity = next(
                (item for item in trusted_bound_references if isinstance(item, v1.BoundActivityReference) and item.ref == decision.criteria.activity_ref),
                None,
            )
            participant = next(
                (item for item in trusted_bound_references if isinstance(item, v1.BoundParticipantReference) and item.ref == decision.criteria.participant_ref),
                None,
            )
            if (
                activity is None or participant is None
                or activity.source_turn_id != current_turn_id or participant.source_turn_id != current_turn_id
                or activity.entity_id != participant.scope_activity_id
                or v1.ModelParticipantReference(kind="participant", ref=participant.ref) not in context.bound_references
            ):
                raise ValueError("participant filter must bind to this Turn and selected activity UUID")
        return
    if isinstance(decision, v1.ProposeDecision):
        base = v1.ModelContext.model_validate(context.model_dump(mode="json", exclude={"query_observations", "intent_classification"}))
        v1.validate_decision_against_context(decision, base)
        return
    raise ValueError("unknown semantic decision kind")


def _render_fact(fact: Any) -> str:
    if isinstance(fact, v1.ExpenseFact):
        safe_title = json.dumps(v1._no_url(fact.title), ensure_ascii=True)
        return f"- {fact.expense_ref.value} | {safe_title} | {fact.original_amount} {fact.original_currency}"
    if isinstance(fact, v1.ActivityFact):
        safe_name = json.dumps(v1._no_url(fact.name), ensure_ascii=True)
        return f"- {fact.activity_ref.value} | {safe_name} | {fact.status.value}"
    if isinstance(fact, v1.DebtFact):
        return f"- debtor {fact.debtor_ref.value} owes creditor {fact.creditor_ref.value}: {fact.amount} {fact.currency}"
    raise ValueError("query renderer supports only v1 typed facts")


def _assert_validated_query_set(
    validated: ValidatedQuerySet,
    *,
    expected_context: Optional[ModelContext] = None,
) -> None:
    if exact_hash(validated.context) != validated.context_digest:
        raise ValueError("validated ModelContext changed after trusted query validation")
    if expected_context is not None and (
        exact_hash(expected_context) != validated.context_digest
        or expected_context != validated.context
    ):
        raise ValueError("validated query set belongs to a different exact ModelContext")
    observations = {item.query_ref: item for item in validated.context.query_observations}
    results = {item.result_ref: item for item in validated.context.read_results}
    for query in validated.queries:
        if exact_hash(query.binding) != query.binding_digest:
            raise ValueError("private query binding changed after validation")
        if exact_hash(query.current_state) != query.current_state_digest:
            raise ValueError("independent current-query state changed after validation")
        if query.current_state.status != "current":
            raise ValueError("stale query cannot remain in a validated answerable query set")
        if (
            query.current_state.query_ref != query.binding.query_ref
            or query.current_state.result_id != query.binding.result_id
            or query.current_state.owner_id != query.binding.owner_id
            or query.current_state.source_turn_id != query.binding.source_turn_id
            or query.current_state.generation != query.binding.generation
            or query.current_state.expected_revision != query.binding.expected_revision
            or query.current_state.freshness_epoch != query.binding.freshness_epoch
            or query.current_state.scope_activity_id != query.binding.scope_activity_id
            or query.current_state.context_version != query.binding.context_version
            or query.current_state.source != query.binding.source
            or query.current_state.source_version != query.binding.source_version
            or query.current_state.source_fingerprint != query.binding.source_fingerprint
            or query.current_state.source_snapshot_fingerprint != query.binding.source_snapshot_fingerprint
            or query.current_state.observed_at != query.binding.observed_at
            or query.current_state.query_digest != query.binding.query_digest
            or query.current_state.body_digest != query.binding.body_digest
        ):
            raise ValueError("current-query state no longer confirms its private query binding")
        observation = observations.get(query.observation.query_ref)
        result = results.get(query.result.result_ref)
        if observation is None or result is None or observation != query.observation or result != query.result:
            raise ValueError("validated query no longer belongs to this exact context")
        if (
            query.binding.query_ref != observation.query_ref
            or query.binding.result_ref != result.result_ref
            or query.binding.body_digest != observation.body_digest
            or body_digest(result.body) != observation.body_digest
            or query.binding.query_digest != observation.query_digest
            or query.binding.context_version != observation.context_version
            or query.binding.context_version != result.context_version
        ):
            raise ValueError("validated query result/body/version changed after validation")
        recomputed = tuple(fact for fact in result.body.items if _fact_matches(fact, observation.criteria))
        if (
            [fact.evidence_ref for fact in recomputed] != observation.matching_fact_citations
            or len(recomputed) != observation.matched_count
            or exact_hash(recomputed) != exact_hash(query.matched_facts)
            or query.complete != observation.page.complete
        ):
            raise ValueError("validated matching fact set changed after validation")


def render_query_answer(
    validated: ValidatedQuerySet,
    query_refs: Optional[list[QueryEvidenceRef]] = None,
    *,
    expected_context: Optional[ModelContext] = None,
) -> AnswerDecision:
    """Render only validated matching facts; never sum, net, convert or infer money."""
    _assert_validated_query_set(validated, expected_context=expected_context)
    selected = set(query_refs or [query.observation.query_ref for query in validated.queries])
    if not selected or not selected.issubset({query.observation.query_ref for query in validated.queries}):
        raise ValueError("query renderer requires validated query refs")
    lines: list[str] = []
    chosen: list[QueryEvidenceRef] = []
    for query in validated.queries:
        observation = query.observation
        if observation.query_ref not in selected:
            continue
        chosen.append(observation.query_ref)
        noun = {"activities": "activities", "expenses": "expenses", "debts": "debts"}[observation.criteria.kind]
        if not query.complete:
            lines.append(
                f"Partial {noun} query: {observation.matched_count} matched among {observation.returned_count} returned; more data may exist."
            )
            lines.extend(_render_fact(fact) for fact in query.matched_facts)
        elif not query.matched_facts:
            if observation.returned_count == 0:
                lines.append(f"No {noun} matched; the complete backend result contained 0 items.")
            else:
                lines.append(
                    f"No {noun} matched the post-filter; all {observation.returned_count} backend items were checked."
                )
        else:
            lines.append(f"Found {observation.matched_count} matching {noun}:")
            lines.extend(_render_fact(fact) for fact in query.matched_facts)
    return AnswerDecision(kind="answer", basis="grounded", text="\n".join(lines), citations=chosen)


def render_fact_answer(
    validated: ValidatedQuerySet,
    evidence_refs: list[Any],
    *,
    expected_context: Optional[ModelContext] = None,
) -> AnswerDecision:
    """Render selected current matched facts exactly; never accept model arithmetic or prose."""
    _assert_validated_query_set(validated, expected_context=expected_context)
    requested = set(evidence_refs)
    if not requested or len(requested) != len(evidence_refs):
        raise ValueError("fact renderer requires a nonempty unique selection")
    matched = {
        fact.evidence_ref: fact
        for query in validated.queries
        for fact in query.matched_facts
    }
    if not requested.issubset(matched):
        raise ValueError("fact renderer only accepts facts from current validated query match sets")
    ordered_refs = [
        fact.evidence_ref
        for query in validated.queries
        for fact in query.matched_facts
        if fact.evidence_ref in requested
    ]
    lines = ["Current matching facts:"]
    lines.extend(_render_fact(matched[ref]) for ref in ordered_refs)
    return AnswerDecision(kind="answer", basis="grounded", text="\n".join(lines), citations=ordered_refs)


def render_policy_answer(
    context: ModelContext,
    evidence_refs: list[Any],
) -> AnswerDecision:
    """Render only cited static policy text; policy cannot assert account/query facts."""
    requested = set(evidence_refs)
    if not requested or len(requested) != len(evidence_refs):
        raise ValueError("policy renderer requires a nonempty unique selection")
    evidence = {item.evidence_ref: item for item in context.policy_evidence}
    if not requested.issubset(evidence):
        raise ValueError("policy renderer only accepts exact policy evidence in this context")
    ordered = [item for item in context.policy_evidence if item.evidence_ref in requested]
    lines = ["Trusted policy statements:"]
    lines.extend(
        f"- {item.evidence_ref.value} | {item.rule.value} | {item.source.value} v{item.version} | {json.dumps(item.text, ensure_ascii=True)}"
        for item in ordered
    )
    return AnswerDecision(
        kind="answer",
        basis="grounded",
        text="\n".join(lines),
        citations=[item.evidence_ref for item in ordered],
    )
