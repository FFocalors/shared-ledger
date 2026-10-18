"""CPU-only decision gate bound to the exact prepared V3 public context.

This module checks the public guard that was serialized into a prepared request
and its projection against the private intent snapshot. It does not authenticate
the source, issue grants, create queries, or call a backend. A successful result
must still pass ``parse_p2_decision`` after Runtime has obtained fresh Auth and
minted any operation/criteria/scope-bound grant.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any

from . import p2_read_contracts_v3 as contracts
from . import p2_read_prompt_v3 as prompt


class P2V3SentGuardError(ValueError):
    """The decision is not permitted by the exact prepared public context."""


def validate_sent_p2_v3_decision(
    prepared_request: prompt.P2V3PreparedRequest,
    public_context: contracts.P2ModelContext,
    private_intent: contracts.P2IntentContext,
    payload: Any,
    *,
    now: datetime | None = None,
) -> contracts.P2Decision:
    """Strictly validate a decision against the public guard in prepared bytes.

    This helper intentionally allows a metadata-only first read whose private
    intent has no operation grant yet. Runtime must then fresh-authorize the
    selected request, mint a narrow grant, and call ``parse_p2_decision`` before
    any query or backend operation. For continuation, the public QEV has no
    model-page ordinal: ``page_count``/``pages_seen`` count source pages, while
    ``P2FreshQueryEvidenceRef.page_index`` is private. This helper checks that
    the private ordinal is strict and travels with its exact receipt/binding;
    only Runtime/Store can compare it to the authoritative current attempt.
    """

    public = _strict_public_context(public_context)
    private = _strict_private_intent(private_intent)
    prepared = _strict_prepared_request(prepared_request)
    _bind_prepared_to_public(prepared, public, private)
    decision = contracts.parse_p2_decision_shape(payload)
    clock = _utc_now(now)

    guard = public.guard
    if decision.kind not in guard.allowed_decision_kinds:
        raise P2V3SentGuardError("decision kind is absent from the sent public guard")

    if isinstance(decision, contracts.P2ReadQueryRequest):
        _check_first_read(public, private, guard, decision)
    elif isinstance(decision, contracts.P2ReadContinueRequest):
        _check_continuation(public, private, guard, decision, clock)
    elif isinstance(decision, contracts.P2AnswerDecision):
        _check_answer(public, private, guard, decision, clock)
    elif isinstance(decision, contracts.P2ProposalRecognition):
        if public.trusted_intent.classification != "proposal_intent":
            raise P2V3SentGuardError("proposal decision requires sent proposal intent")
        if private.clarification_required or not private.proposal_target_resolved:
            raise P2V3SentGuardError("proposal target is unresolved in current private intent")
        if guard.proposal_clarification_required is not False:
            raise P2V3SentGuardError("sent guard does not mark proposal target resolved")
        if decision.operation not in guard.allowed_proposal_operations:
            raise P2V3SentGuardError("proposal operation is absent from the sent public guard")
    elif isinstance(decision, contracts.P2ClarifyDecision):
        if public.trusted_intent.classification == "non_business":
            raise P2V3SentGuardError("non-business context cannot emit a business clarification")
        public_slots = {item.slot for item in public.pending_clarifications}
        private_slots = {item.slot for item in private.pending_clarifications}
        if not decision.missing_slots or not set(decision.missing_slots).issubset(public_slots & private_slots):
            raise P2V3SentGuardError("clarification slots are not a subset of current public and private pending slots")
    else:  # pragma: no cover - closed decision union, retained as a fail-closed boundary
        raise P2V3SentGuardError("unsupported candidate decision type")

    return decision


def _strict_public_context(value: Any) -> contracts.P2ModelContext:
    if type(value) is not contracts.P2ModelContext:
        raise P2V3SentGuardError("exact v3 public model context is required")
    try:
        return contracts.parse_p2_model_context(
            value.model_dump_json(by_alias=True, exclude_none=False)
        )
    except Exception as exc:
        raise P2V3SentGuardError("public model context failed strict revalidation") from exc


def _strict_private_intent(value: Any) -> contracts.P2IntentContext:
    if type(value) is not contracts.P2IntentContext:
        raise P2V3SentGuardError("exact v3 private intent context is required")
    try:
        return contracts.P2IntentContext.model_validate_json(
            value.model_dump_json(by_alias=True, exclude_none=False), strict=True
        )
    except Exception as exc:
        raise P2V3SentGuardError("private intent context failed strict revalidation") from exc


def _strict_prepared_request(value: Any) -> prompt.P2V3PreparedRequest:
    if type(value) is not prompt.P2V3PreparedRequest:
        raise P2V3SentGuardError("exact v3 prepared request is required")
    try:
        return prompt.P2V3PreparedRequest.model_validate_json(
            value.model_dump_json(by_alias=True, exclude_none=False), strict=True
        )
    except Exception as exc:
        raise P2V3SentGuardError("prepared request failed strict binding revalidation") from exc


def _bind_prepared_to_public(
    prepared: prompt.P2V3PreparedRequest,
    public: contracts.P2ModelContext,
    private: contracts.P2IntentContext,
) -> None:
    try:
        contracts.validate_p2_clarification_projection(public, private)
        rebuilt = prompt.build_p2_v3_request(
            public,
            private,
            config=prepared.config,
            repair_feedback=prepared.repair_feedback,
        )
    except Exception as exc:
        raise P2V3SentGuardError("prepared request and public/private context failed projection binding") from exc

    public_json = json.dumps(
        public.model_dump(mode="json", by_alias=True, exclude_none=False),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    public_digest = sha256(public_json.encode("utf-8")).hexdigest()
    if prepared.context_sha256 != public_digest or rebuilt.context_sha256 != public_digest:
        raise P2V3SentGuardError("prepared context digest does not bind the supplied public DTO")
    if prepared != rebuilt:
        raise P2V3SentGuardError("prepared bytes/config/fingerprint differ from the supplied public DTO")

    try:
        body = json.loads(prepared.body_bytes)
        messages = body["messages"]
        content = messages[-1]["content"]
    except Exception as exc:
        raise P2V3SentGuardError("prepared body has no canonical public-context message") from exc
    prefix = prompt.P2_V3_CONTEXT_MESSAGE_PREFIX
    if type(content) is not str or not content.startswith(prefix) or content[len(prefix):] != public_json:
        raise P2V3SentGuardError("body context differs from the supplied public DTO")


def _check_first_read(
    public: contracts.P2ModelContext,
    private: contracts.P2IntentContext,
    guard: contracts.P2DecisionGuard,
    decision: contracts.P2ReadQueryRequest,
) -> None:
    if public.trusted_intent.classification not in {"factual_business", "ambiguous"}:
        raise P2V3SentGuardError("first read is unavailable for this sent classification")
    if private.clarification_required:
        raise P2V3SentGuardError("current private intent requires clarification before a read")
    if decision.operation not in guard.allowed_read_operations:
        raise P2V3SentGuardError("read operation is absent from the sent public guard")

    scope_status = public.scope_authorization.status
    current_scope = public.scope_authorization.scope
    if decision.scope is None:
        if (
            decision.operation != contracts.P2ReadOperation.ACTIVITIES
            or scope_status != "absent"
            or private.scope_status != "absent"
        ):
            raise P2V3SentGuardError("only no-scope Activity discovery is allowed without a verified scope")
    elif scope_status != "verified" or decision.scope != current_scope:
        raise P2V3SentGuardError("read scope does not match the sent verified scope")


def _check_continuation(
    public: contracts.P2ModelContext,
    private: contracts.P2IntentContext,
    guard: contracts.P2DecisionGuard,
    decision: contracts.P2ReadContinueRequest,
    now: datetime,
) -> None:
    if public.trusted_intent.classification not in {"factual_business", "ambiguous"}:
        raise P2V3SentGuardError("continuation is unavailable for this sent classification")
    if private.clarification_required:
        raise P2V3SentGuardError("current private intent requires clarification before a continuation")

    hints = [
        hint for hint in public.continuations
        if hint.query_ref == decision.query_ref and hint.next_page_ref == decision.next_page_ref
    ]
    if len(hints) != 1:
        raise P2V3SentGuardError("continuation refs are absent or ambiguous in the sent public context")
    hint = hints[0]
    if hint.query_evidence_ref not in guard.fresh_receipt_refs:
        raise P2V3SentGuardError("continuation evidence is absent from sent fresh receipt refs")

    evidence = _public_evidence(public, hint.query_evidence_ref)
    if evidence.query_ref != decision.query_ref or not evidence.page.has_more:
        raise P2V3SentGuardError("continuation does not match public query evidence with another page")
    receipt, grant = _matching_private_binding(private, hint.query_evidence_ref)
    _check_qev_receipt_binding(public, evidence, receipt, grant, now)
    if receipt.query_ref != decision.query_ref or receipt.next_page_ref != decision.next_page_ref:
        raise P2V3SentGuardError("continuation refs differ from its current private receipt")
    if type(receipt.page_index) is not int or receipt.page_index < 0:
        raise P2V3SentGuardError("private continuation receipt has an invalid page index")
    if receipt.operation not in guard.allowed_read_operations:
        raise P2V3SentGuardError("original query operation is absent from the sent public read allowlist")
    _check_receipt_scope(public, receipt)


def _check_answer(
    public: contracts.P2ModelContext,
    private: contracts.P2IntentContext,
    guard: contracts.P2DecisionGuard,
    decision: contracts.P2AnswerDecision,
    now: datetime,
) -> None:
    classification = public.trusted_intent.classification
    if decision.basis == "non_business_general":
        if not guard.source_free_business_answer_allowed:
            raise P2V3SentGuardError("sent guard does not permit source-free general answers")
        if classification != "non_business" or private.classification != "non_business":
            raise P2V3SentGuardError("source-free answer requires current non-business classification")
        if decision.citations:
            raise P2V3SentGuardError("source-free answer cannot cite source receipts")
        return

    if classification != "factual_business" or private.classification != "factual_business":
        raise P2V3SentGuardError("source-backed answer requires current factual business classification")
    if not decision.citations or len(decision.citations) != len(set(decision.citations)):
        raise P2V3SentGuardError("source-backed answer requires unique query evidence citations")
    if not set(decision.citations).issubset(set(guard.fresh_receipt_refs)):
        raise P2V3SentGuardError("answer citation is absent from the sent public fresh receipt allowlist")

    for qev_ref in decision.citations:
        evidence = _public_evidence(public, qev_ref)
        receipt, grant = _matching_private_binding(private, qev_ref)
        _check_qev_receipt_binding(public, evidence, receipt, grant, now)
        _check_receipt_scope(public, receipt)


def _public_evidence(
    public: contracts.P2ModelContext,
    qev_ref: str,
) -> contracts.P2QueryEvidence:
    matches = [item for item in public.query_evidence if item.query_evidence_ref == qev_ref]
    if len(matches) != 1:
        raise P2V3SentGuardError("query evidence ref is absent or ambiguous in the sent public context")
    return matches[0]


def _matching_private_binding(
    private: contracts.P2IntentContext,
    qev_ref: str,
) -> tuple[contracts.P2FreshQueryEvidenceRef, contracts.P2SourceAuthorizationGrant]:
    receipts = [item for item in private.fresh_receipt_refs if item.query_evidence_ref == qev_ref]
    bindings = [item for item in private.query_authorization_bindings if item.query_evidence_ref == qev_ref]
    if len(receipts) != 1 or len(bindings) != 1:
        raise P2V3SentGuardError("cited query evidence lacks one current private receipt and grant binding")
    binding = bindings[0]
    if binding.receipt != receipts[0]:
        raise P2V3SentGuardError("private query authorization binding differs from its current receipt")
    return receipts[0], binding.grant


def _check_qev_receipt_binding(
    public: contracts.P2ModelContext,
    evidence: contracts.P2QueryEvidence,
    receipt: contracts.P2FreshQueryEvidenceRef,
    grant: contracts.P2SourceAuthorizationGrant,
    now: datetime,
) -> None:
    if evidence.query_evidence_ref != receipt.query_evidence_ref:
        raise P2V3SentGuardError("public query evidence and private receipt refs differ")
    if (
        evidence.query_ref != receipt.query_ref
        or evidence.operation != receipt.operation
        or evidence.criteria_digest != receipt.criteria_digest
        or evidence.observed_at != receipt.observed_at
    ):
        raise P2V3SentGuardError("public query evidence differs from its private query receipt")
    if (
        grant.operation != receipt.operation
        or grant.criteria_digest != receipt.criteria_digest
        or (grant.scope.scope_ref if grant.scope is not None else None) != receipt.scope_ref
    ):
        raise P2V3SentGuardError("private query grant does not match the receipt operation/criteria/scope")
    if receipt.generation != public.generation:
        # The private intent validator binds receipt input identity; the
        # public/private projection check binds their shared generation.
        raise P2V3SentGuardError("private receipt generation differs from the sent public context")
    if receipt.source_input_seq != public.trusted_intent.source_input_seq:
        raise P2V3SentGuardError("private receipt input sequence differs from the sent public context")
    if receipt.expires_at <= now or receipt.observed_at > now:
        raise P2V3SentGuardError("private query receipt is expired or observed in the future")
    if grant.expires_at <= now:
        raise P2V3SentGuardError("private query grant is expired")


def _check_receipt_scope(
    public: contracts.P2ModelContext,
    receipt: contracts.P2FreshQueryEvidenceRef,
) -> None:
    scope_auth = public.scope_authorization
    if scope_auth.status == "verified" and scope_auth.scope is not None:
        expected_scope_ref = scope_auth.scope.scope_ref
    elif scope_auth.status == "absent" and receipt.operation == contracts.P2ReadOperation.ACTIVITIES:
        expected_scope_ref = None
    else:
        raise P2V3SentGuardError("source receipt requires the current verified scope or Activity discovery")
    if receipt.scope_ref != expected_scope_ref:
        raise P2V3SentGuardError("private receipt scope differs from the sent public scope")


def _utc_now(value: datetime | None) -> datetime:
    current = datetime.now(timezone.utc) if value is None else value
    if type(current) is not datetime or current.tzinfo is None or current.utcoffset() is None:
        raise P2V3SentGuardError("current time must be timezone-aware")
    return current.astimezone(timezone.utc)
