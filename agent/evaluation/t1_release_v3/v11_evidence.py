"""Attach frozen offline v1.1 typed query evidence to a candidate read row.

RBR01 requires that a *no-match* answer be backed by a citable query result
that binds query completeness (including pagination/truncation), the filters
actually applied, the scope, and the result/schema version -- an empty list
on its own proves nothing.

This module builds exactly that evidence for a read row, from the row's
**own** synthetic fixture and deterministic replay result (never from a
substitute fixture), using the frozen v1.1 issuer ``bind_trusted_query`` and
the frozen trusted renderer ``render_query_answer``.  Nothing here may be
hand-written: the observation, the digests, the page receipts and the
rendered answer all come from the frozen package.
"""
from __future__ import annotations

import importlib
import uuid
from types import SimpleNamespace
from typing import Any

from . import profile

SOURCE_VERSION = "synthetic-source-v1"
QUERY_REF = "query_1"
GENERATION = 1
EXPECTED_REVISION = 1
FRESHNESS_EPOCH = 1
CONTEXT_VERSION = 1
READ_OPERATIONS = ("read.activities", "read.expenses", "read.debts")


class EvidenceError(RuntimeError):
    pass


def api(v11_package: Any) -> SimpleNamespace:
    """The frozen v1.1 symbols used here, resolved from the pinned package.

    The v1.1 package carries its own copy of the v1 contracts.  Models built
    for the v1.1 ports must be instances of *those* classes, not of the
    baseline snapshot's identically named ones, so the copy is exposed here.
    """
    contracts = importlib.import_module("evaluation.t1_protocol_v1_1.contracts")
    harness = importlib.import_module("evaluation.t1_protocol_v1_1.harness")
    v1 = importlib.import_module("evaluation.t1_protocol_v1_1.v1_contracts")
    return SimpleNamespace(
        package=v11_package,
        contracts=contracts,
        harness=harness,
        V1=v1,
        QueryEvidenceRef=contracts.QueryEvidenceRef,
        QuerySource=contracts.QuerySource,
        QueryPageMetadata=contracts.QueryPageMetadata,
        ReadExpensesCriteria=contracts.ReadExpensesCriteria,
        ReadDecision=contracts.ReadDecision,
        ModelContext=contracts.ModelContext,
        FinancialVersionFence=harness.FinancialVersionFence,
        TrustedSourceSnapshot=harness.TrustedSourceSnapshot,
        CurrentQueryState=harness.CurrentQueryState,
        PageReceipt=harness.PageReceipt,
        bind_trusted_query=harness.bind_trusted_query,
        make_query_observation=harness.make_query_observation,
        validate_context_bindings=harness.validate_context_bindings,
        render_query_answer=harness.render_query_answer,
        canonical_hash=contracts.canonical_hash,
        exact_hash=contracts.exact_hash,
        row_identity_digest=harness.row_identity_digest,
    )


def _named(namespace: uuid.UUID, *parts: str) -> uuid.UUID:
    return uuid.uuid5(namespace, ":".join(parts))


def complete_page(v11: SimpleNamespace, *, returned: int) -> Any:
    """Full one-page coverage metadata: nothing hidden, nothing truncated."""
    return v11.QueryPageMetadata(
        pages_seen=1,
        expected_total=returned,
        has_more=False,
        truncated=False,
        complete=True,
        range_contiguous=True,
        stable_total_verified=True,
        source_version_fenced=True,
        unique_items_verified=True,
    )


def build_no_match_evidence(
    *,
    c: Any,
    v11: SimpleNamespace,
    namespace: uuid.UUID,
    sample_key: str,
    operation: str,
    criteria: Any,
    result: Any,
    scope_activity_id: uuid.UUID | None,
    observed_at: Any,
    bound_references: list[Any],
    turn_id: uuid.UUID,
    bound_evidence_references: list[Any] | None = None,
    row_entity_ids: dict[str, uuid.UUID] | None = None,
    context_version: int = CONTEXT_VERSION,
) -> dict[str, Any]:
    """Evidence bundle for one no-match read, derived from its own replay result.

    ``result`` is the row's own ``v1.ToolReadResult``.  Its ``body.items`` may
    be empty (complete backend zero) or non-empty while the typed post-filter
    matches nothing (post-filter zero); the two stay distinguishable because
    the frozen port carries typed ``backend_criteria`` and ``post_filter``.
    """
    if operation not in READ_OPERATIONS:
        raise EvidenceError(f"typed query evidence is defined for read operations only: {operation}")
    returned = len(result.body.items)

    query_ref = v11.QueryEvidenceRef.Q01
    if query_ref.value != QUERY_REF:
        raise EvidenceError("frozen query reference enum no longer starts at query_1")

    if criteria.kind == "activities":
        if scope_activity_id is not None:
            raise EvidenceError("activity-list queries must use a none backend scope")
        financial_versions: list[Any] = []
        membership_snapshot_id = _named(namespace, sample_key, "membership-snapshot")
    else:
        if scope_activity_id is None:
            raise EvidenceError("expense/debt queries require a verified private activity scope")
        financial_versions = [v11.FinancialVersionFence(
            activity_ref=criteria.activity_ref,
            private_activity_id=scope_activity_id,
            financial_version="1",
        )]
        membership_snapshot_id = None

    owner_id = _named(namespace, sample_key, "owner")
    source_snapshot = v11.TrustedSourceSnapshot(
        snapshot_id=_named(namespace, sample_key, "source-snapshot"),
        source_version=SOURCE_VERSION,
        observed_at=observed_at,
        scope_activity_id=scope_activity_id,
        financial_versions=financial_versions,
        membership_snapshot_id=membership_snapshot_id,
    )
    snapshot_fingerprint = v11.exact_hash(source_snapshot)

    # A page row identity must hash the persisted entity/derived-row key of the
    # fact's own typed evidence binding, so it is looked up, never invented.
    entity_ids = dict(row_entity_ids or {})
    row_digests = []
    for fact in result.body.items:
        entity_id = entity_ids.get(fact.evidence_ref.value)
        if entity_id is None:
            raise EvidenceError(f"no persisted entity id for replayed row {fact.evidence_ref.value}")
        row_digests.append(v11.row_identity_digest(fact.kind, entity_id))

    page_receipts = [v11.PageReceipt(
        page_index=0,
        offset=0,
        item_digests=[v11.canonical_hash(fact) for fact in result.body.items],
        row_identity_digests=row_digests,
        source_version=SOURCE_VERSION,
        snapshot_fingerprint=snapshot_fingerprint,
        scope_fingerprint=v11.canonical_hash(
            {"scope_activity_id": str(scope_activity_id) if scope_activity_id else None}
        ),
        range_start=0,
        range_end_exclusive=returned,
        total_count=returned,
        cursor_in_digest=None,
        cursor_out_digest=None,
    )]

    binding = v11.bind_trusted_query(
        query_ref=query_ref,
        owner_id=owner_id,
        turn_id=turn_id,
        generation=GENERATION,
        expected_revision=EXPECTED_REVISION,
        freshness_epoch=FRESHNESS_EPOCH,
        scope_activity_id=scope_activity_id,
        result=result,
        criteria=criteria,
        context_version=context_version,
        source=v11.QuerySource.SYNTHETIC_SIMULATION,
        source_version=SOURCE_VERSION,
        source_fingerprint=snapshot_fingerprint,
        source_snapshot=source_snapshot,
        page=complete_page(v11, returned=returned),
        page_receipts=page_receipts,
    )
    observation = v11.make_query_observation(binding, result)
    if observation.matched_count != 0:
        raise EvidenceError("typed query evidence is attached only to a no-match read")
    if observation.returned_count != returned:
        raise EvidenceError("returned_count does not match the replayed body")

    current_state = v11.CurrentQueryState(
        query_ref=query_ref,
        result_id=result.result_id,
        owner_id=owner_id,
        source_turn_id=turn_id,
        generation=GENERATION,
        expected_revision=EXPECTED_REVISION,
        freshness_epoch=FRESHNESS_EPOCH,
        current_generation=GENERATION,
        current_revision=EXPECTED_REVISION,
        current_freshness_epoch=FRESHNESS_EPOCH,
        status="current",
        scope_activity_id=scope_activity_id,
        context_version=context_version,
        source=v11.QuerySource.SYNTHETIC_SIMULATION,
        source_version=SOURCE_VERSION,
        source_fingerprint=snapshot_fingerprint,
        source_snapshot_fingerprint=snapshot_fingerprint,
        observed_at=observed_at,
        query_digest=binding.query_digest,
        body_digest=binding.body_digest,
    )
    model_result = v11.V1.ModelReadResult(
        result_ref=result.result_ref,
        operation=result.operation,
        observed_at=result.observed_at,
        context_version=result.context_version,
        simulation=result.simulation,
        body=result.body,
    )
    return {
        "binding": binding,
        "observation": observation,
        "model_result": model_result,
        "current_state": current_state,
        "bound_read_result": v11.V1.BoundReadResultReference(
            result_ref=result.result_ref,
            result_id=result.result_id,
            source_turn_id=turn_id,
            operation=result.operation,
            observed_at=result.observed_at,
            context_version=result.context_version,
        ),
        "bound_references": list(bound_references),
        "bound_evidence_references": list(bound_evidence_references or []),
        "actual_result": result,
    }


def render_no_match_answer(*, v11: SimpleNamespace, context: Any, evidence: dict[str, Any]) -> Any:
    """Render the canonical no-match answer through the frozen trusted renderer."""
    binding = evidence["binding"]
    validated = v11.validate_context_bindings(
        context,
        current_owner_id=binding.owner_id,
        current_turn_id=binding.source_turn_id,
        generation=binding.generation,
        expected_revision=binding.expected_revision,
        freshness_epoch=binding.freshness_epoch,
        current_context_version=context.context_version,
        current_query_states=[evidence["current_state"]],
        trusted_tool_results=[evidence["actual_result"]],
        bound_queries=[binding],
        bound_references=evidence["bound_references"],
        bound_evidence_references=evidence["bound_evidence_references"],
        bound_read_results=[evidence["bound_read_result"]],
    )
    return v11.render_query_answer(validated)


def summary(evidence: dict[str, Any]) -> dict[str, Any]:
    """The reviewer-facing facts of one converted no-match row."""
    observation = evidence["observation"]
    page = observation.page
    return {
        "query_ref": observation.query_ref.value,
        "operation": observation.operation.value,
        "backend_criteria": observation.backend_criteria.model_dump(mode="json"),
        "post_filter": observation.post_filter.model_dump(mode="json"),
        "normalized_criteria": observation.normalized_criteria,
        "returned_count": observation.returned_count,
        "matched_count": observation.matched_count,
        "source_total": page.expected_total,
        "page_complete": page.complete,
        "has_more": page.has_more,
        "truncated": page.truncated,
        "range_contiguous": page.range_contiguous,
        "stable_total_verified": page.stable_total_verified,
        "source_version_fenced": page.source_version_fenced,
        "unique_items_verified": page.unique_items_verified,
        "source": observation.source.value,
        "source_version": observation.source_version,
        "schema_version": observation.schema_version,
        "context_version": observation.context_version,
        "zero_class": "backend_zero" if observation.returned_count == 0 else "post_filter_zero",
    }


RBR01_BINDING_FIELDS = {
    "completeness_and_pagination": (
        "page.complete", "page.expected_total", "page.pages_seen", "page.has_more",
        "page.truncated", "page.range_contiguous", "page.stable_total_verified",
        "page.source_version_fenced", "page.unique_items_verified",
    ),
    "filters_applied": (
        "operation", "criteria", "normalized_criteria", "backend_criteria",
        "post_filter", "returned_count", "matched_count",
    ),
    "scope": ("criteria.activity_ref", "private scope_activity_id", "page scope fingerprint"),
    "result_and_schema_version": (
        "schema_version", "context_version", "source_version", "source",
        "query_digest", "body_digest",
    ),
    "profile": (profile.V11_PROFILE,),
}
