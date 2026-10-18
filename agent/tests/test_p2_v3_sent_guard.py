from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest
from app import p2_read_contracts_v3 as c
from app.p2_read_prompt_v3 import P2V3PreparedRequest, P2V3PromptBuildConfig, build_p2_v3_request
from app.p2_v3_sent_guard import P2V3SentGuardError, validate_sent_p2_v3_decision


NOW = datetime.now(timezone.utc).replace(microsecond=0)
ACTIVITY = "ref_" + "A" * 22
EXPENSE = "ref_" + "B" * 22
QUERY = "ref_" + "C" * 22
RESULT = "ref_" + "D" * 22
CRITERIA = "ref_" + "E" * 22
SOURCE = "ref_" + "F" * 22
QEV = "qev_" + "G" * 22
NEXT = "ref_" + "H" * 22
PRINCIPAL = "ref_" + "I" * 22
TURN = "ref_" + "J" * 22
INPUT_DIGEST = "a" * 64


def ref(number: int) -> str:
    return "ref_" + f"{number:022d}"


def _scope() -> c.P2Scope:
    return c.P2Scope(
        scope_kind="activity", scope_ref=ACTIVITY, activity_ref=ACTIVITY, ledger_unit_ref=None,
    )


def _config() -> P2V3PromptBuildConfig:
    return P2V3PromptBuildConfig(
        model_id="sent-guard-cpu-fixture",
        endpoint_url="http://127.0.0.1:1234/v1/chat/completions",
    )


def _criteria() -> c.ExpenseCriteria:
    return c.ExpenseCriteria(kind="expenses", activity_ref=ACTIVITY)


def _debt_criteria() -> c.DebtCriteria:
    return c.DebtCriteria(kind="debts", activity_ref=ACTIVITY)


def _read_request() -> dict[str, object]:
    return {
        "kind": "read",
        "message_type": "query_request",
        "profile_id": c.P2_V3_CANDIDATE_PROFILE_ID,
        "versions": c.P2_V3_VERSIONS.model_dump(mode="json"),
        "operation": c.P2ReadOperation.EXPENSES.value,
        "criteria": {
            "kind": "expenses",
            "activity_ref": ACTIVITY,
            "from_date": None,
            "to_date": None,
            "participant_ref": None,
            "title_contains": None,
        },
        "scope": _scope().model_dump(mode="json"),
    }


def _public_context(
    *,
    classification: str = "factual_business",
    scope_status: str = "verified",
    allowed_kinds: tuple[str, ...] = ("read",),
    read_operations: tuple[c.P2ReadOperation, ...] = (c.P2ReadOperation.EXPENSES,),
    source_free: bool = False,
    fresh_refs: tuple[str, ...] = (),
    evidence: tuple[c.P2QueryEvidence, ...] = (),
    continuations: tuple[c.P2ContinuationHint, ...] = (),
    pending: tuple[c.P2PendingClarificationProjection, ...] = (),
    proposal_clarification_required: bool | None = None,
    proposal_operations: tuple[c.P2ProposalOperation, ...] = (),
    facts: tuple[c.P2Fact, ...] = (),
) -> c.P2ModelContext:
    scope = _scope() if scope_status == "verified" else None
    receipt_ref = "auth_" + "K" * 22 if scope is not None else None
    return c.P2ModelContext(
        profile_id=c.P2_V3_CANDIDATE_PROFILE_ID,
        versions=c.P2_V3_VERSIONS,
        context_version="synthetic-sent-guard-context-v1",
        generation=4,
        input_text="读取当前活动的支出。",
        trusted_intent=c.P2TrustedIntent(
            authority="server",
            classification=classification,
            requires_authoritative_evidence=classification in {"factual_business", "ambiguous"},
            source_input_seq=9,
            classifier_version="synthetic-policy-v1",
        ),
        scope_authorization=c.P2ScopeAuthorization(
            status=scope_status,
            scope=scope,
            authorization_receipt_ref=receipt_ref,
        ),
        guard=c.P2DecisionGuard(
            source_free_business_answer_allowed=source_free,
            allowed_decision_kinds=allowed_kinds,
            allowed_read_operations=read_operations,
            fresh_receipt_refs=fresh_refs,
            proposal_clarification_required=proposal_clarification_required,
            allowed_proposal_operations=proposal_operations,
        ),
        pending_clarifications=pending,
        query_evidence=evidence,
        continuations=continuations,
        facts=facts,
        recent_messages=(),
        current_actor=None,
        source_labels=(),
    )


def _private_context(
    *,
    classification: str = "factual_business",
    scope_status: str = "verified",
    scope_override: c.P2Scope | None = None,
    grant: c.P2SourceAuthorizationGrant | None = None,
    receipts: tuple[c.P2FreshQueryEvidenceRef, ...] = (),
    bindings: tuple[c.P2QueryAuthorizationBinding, ...] = (),
    pending: tuple[c.P2PendingClarification, ...] = (),
    proposal_target_resolved: bool = False,
) -> c.P2IntentContext:
    scope = (scope_override or _scope()) if scope_status == "verified" else None
    return c.P2IntentContext(
        profile_id=c.P2_V3_CANDIDATE_PROFILE_ID,
        versions=c.P2_V3_VERSIONS,
        classification=classification,
        principal_ref=PRINCIPAL,
        owner_turn_ref=TURN,
        generation=4,
        source_input_seq=9,
        input_digest=INPUT_DIGEST,
        scope_status=scope_status,
        scope=scope,
        source_authorization_grant=grant,
        fresh_receipt_refs=receipts,
        query_authorization_bindings=bindings,
        clarification_required=bool(pending),
        pending_clarifications=pending,
        proposal_target_resolved=proposal_target_resolved,
        classifier_source="server_policy",
        classifier_version="synthetic-policy-v1",
    )


def _metadata_pair(
    *,
    allowed_kinds: tuple[str, ...] = ("read",),
    read_operations: tuple[c.P2ReadOperation, ...] = (c.P2ReadOperation.EXPENSES,),
) -> tuple[c.P2ModelContext, c.P2IntentContext]:
    public = _public_context(allowed_kinds=allowed_kinds, read_operations=read_operations)
    private = _private_context()  # verified metadata context; no first-read grant or qev yet
    return public, private


def _evidence(
    *,
    has_more: bool = False,
    observed_at: datetime | None = None,
    operation: c.P2ReadOperation = c.P2ReadOperation.EXPENSES,
    criteria: c.ExpenseCriteria | c.DebtCriteria | None = None,
    criteria_digest: str | None = None,
    query_ref: str = QUERY,
) -> c.P2QueryEvidence:
    criteria_value = criteria or _criteria()
    digest = criteria_digest or c.p2_criteria_digest(criteria_value)
    item_count = 17 if has_more else 1
    model_complete = not has_more
    source_pages = 2 if has_more else 1
    fact_refs = (EXPENSE,) if operation == c.P2ReadOperation.EXPENSES else ()
    return c.P2QueryEvidence(
        profile_id=c.P2_V3_CANDIDATE_PROFILE_ID,
        versions=c.P2_V3_VERSIONS,
        query_evidence_ref=QEV,
        query_ref=query_ref,
        result_ref=RESULT,
        operation=operation,
        criteria_ref=CRITERIA,
        criteria_digest=digest,
        normalized_criteria_digest="b" * 64,
        backend_criteria_stage="scope_only",
        source_kind=operation.value.removeprefix("read."),
        source_ref=SOURCE,
        source_version="synthetic-source-v1",
        observed_at=observed_at or NOW - timedelta(seconds=20),
        simulation=True,
        returned_count=item_count,
        matched_count=item_count,
        source_total=item_count,
        matched_total=item_count,
        page_count=source_pages,
        query_zero_classification="nonzero",
        source_query_complete=True,
        model_projection_complete=model_complete,
        matching_fact_refs=fact_refs,
        financial_versions=(c.P2FinancialVersion(activity_ref=ACTIVITY, financial_version=12),),
        page=c.P2PageSummary(
            pages_seen=source_pages,
            has_more=has_more,
            truncated=False,
            source_query_complete=True,
            model_projection_complete=model_complete,
            range_contiguous=True,
            stable_total_verified=True,
            source_version_fenced=True,
            unique_items_verified=True,
            expected_total=item_count,
        ),
        query_digest="c" * 64,
        body_digest="d" * 64,
        projection_digest="e" * 64,
    )


def _fact(qev: str = QEV) -> c.ExpenseFact:
    return c.ExpenseFact(
        fact_kind="expense",
        expense_ref=EXPENSE,
        title="早餐🍜 — café",
        scope_ref=ACTIVITY,
        occurred_at=NOW - timedelta(days=1),
        signed_original_amount="48.13",
        original_currency="CNY",
        signed_base_amount="48.1",
        base_currency="CNY",
        payer_split_lines=(c.ParticipantAllocationFact(
            participant_ref=PRINCIPAL,
            role="payer",
            signed_original_amount="48.13",
            original_currency="CNY",
            signed_base_amount="48.1",
            base_currency="CNY",
        ),),
        expense_version=5,
        financial_version=12,
        query_evidence_ref=qev,
    )


def _bound_pair(
    *,
    has_more: bool = False,
    guard_fresh: bool = True,
    receipt_operation: c.P2ReadOperation = c.P2ReadOperation.EXPENSES,
    receipt_query_ref: str = QUERY,
    receipt_criteria_digest: str | None = None,
    receipt_observed_at: datetime | None = None,
    receipt_next_page_ref: str | None = None,
    receipt_scope: c.P2Scope | None = None,
    expires_at: datetime | None = None,
    grant_expires_at: datetime | None = None,
    page_index: int = 0,
) -> tuple[c.P2ModelContext, c.P2IntentContext]:
    evidence = _evidence(has_more=has_more)
    digest = receipt_criteria_digest or evidence.criteria_digest
    observed = receipt_observed_at or evidence.observed_at
    expiry = expires_at or NOW + timedelta(hours=1)
    grant_expiry = grant_expires_at or NOW + timedelta(hours=1)
    next_page = (receipt_next_page_ref or NEXT) if has_more else None
    bound_scope = receipt_scope or _scope()
    receipt = c.P2FreshQueryEvidenceRef(
        query_evidence_ref=QEV,
        query_ref=receipt_query_ref,
        principal_ref=PRINCIPAL,
        owner_turn_ref=TURN,
        generation=4,
        source_input_seq=9,
        input_digest=INPUT_DIGEST,
        operation=receipt_operation,
        scope_ref=bound_scope.scope_ref,
        criteria_digest=digest,
        observed_at=observed,
        expires_at=expiry,
        next_page_ref=next_page,
        page_index=page_index,
    )
    grant = c.P2SourceAuthorizationGrant(
        principal_ref=PRINCIPAL,
        owner_turn_ref=TURN,
        generation=4,
        source_input_seq=9,
        input_digest=INPUT_DIGEST,
        operation=receipt_operation,
        scope=bound_scope,
        criteria_digest=digest,
        expires_at=grant_expiry,
        grant_ref=ref(50),
    )
    binding = c.P2QueryAuthorizationBinding(
        query_evidence_ref=QEV,
        receipt=receipt,
        grant=grant,
    )
    hints = (
        (c.P2ContinuationHint(query_evidence_ref=QEV, query_ref=QUERY, next_page_ref=NEXT),)
        if has_more else ()
    )
    public = _public_context(
        allowed_kinds=("read", "answer"),
        read_operations=(c.P2ReadOperation.EXPENSES,),
        fresh_refs=(QEV,) if guard_fresh else (),
        evidence=(evidence,),
        continuations=hints,
        facts=(_fact(),),
    )
    private = _private_context(
        scope_override=bound_scope,
        grant=grant,
        receipts=(receipt,),
        bindings=(binding,),
    )
    return public, private


def _prepared(public: c.P2ModelContext, private: c.P2IntentContext) -> P2V3PreparedRequest:
    return build_p2_v3_request(public, private, config=_config())


def _run(
    public: c.P2ModelContext,
    private: c.P2IntentContext,
    payload: object,
    *,
    prepared: P2V3PreparedRequest | None = None,
    now: datetime | None = None,
) -> c.P2Decision:
    return validate_sent_p2_v3_decision(
        prepared or _prepared(public, private), public, private, payload, now=now or NOW,
    )


def _read_grant(private: c.P2IntentContext) -> c.P2SourceAuthorizationGrant:
    request = c.parse_p2_decision_shape(_read_request())
    assert isinstance(request, c.P2ReadQueryRequest)
    return c.P2SourceAuthorizationGrant(
        principal_ref=PRINCIPAL,
        owner_turn_ref=TURN,
        generation=4,
        source_input_seq=9,
        input_digest=INPUT_DIGEST,
        operation=c.P2ReadOperation.EXPENSES,
        scope=_scope(),
        criteria_digest=c.p2_criteria_digest(request.criteria),
        expires_at=NOW + timedelta(hours=1),
        grant_ref=ref(60),
    )


def test_four_semantics_and_metadata_first_read_are_sent_guard_reachable() -> None:
    public, private = _metadata_pair()
    read = _run(public, private, _read_request())
    assert isinstance(read, c.P2ReadQueryRequest)
    assert private.source_authorization_grant is None
    with pytest.raises(ValueError, match="fresh source-authorized grant"):
        c.parse_p2_decision(_read_request(), private)
    authorized_private = _private_context(grant=_read_grant(private))
    assert isinstance(c.parse_p2_decision(_read_request(), authorized_private), c.P2ReadQueryRequest)

    nonbusiness_public = _public_context(
        classification="non_business",
        scope_status="absent",
        allowed_kinds=("answer",),
        read_operations=(),
        source_free=True,
    )
    nonbusiness_private = _private_context(classification="non_business", scope_status="absent")
    answer = {"kind": "answer", "basis": "non_business_general", "text": "一般说明。", "citations": []}
    assert isinstance(_run(nonbusiness_public, nonbusiness_private, answer), c.P2AnswerDecision)

    public_pending = c.P2PendingClarificationProjection(
        slot="activity_scope", reason="missing_required_scope", operation=None,
    )
    private_pending = c.P2PendingClarification(
        slot="activity_scope", reason="missing_required_scope", generation=4,
        source_input_seq=9, input_digest=INPUT_DIGEST, operation=None,
    )
    clarify_public = _public_context(
        classification="ambiguous", scope_status="unresolved", allowed_kinds=("clarify",),
        read_operations=(), pending=(public_pending,),
    )
    clarify_private = _private_context(
        classification="ambiguous", scope_status="unresolved", pending=(private_pending,),
    )
    clarify = {"kind": "clarify", "prompt": "请指定活动。", "missing_slots": ["activity_scope"]}
    assert isinstance(_run(clarify_public, clarify_private, clarify), c.P2ClarifyDecision)

    proposal_public = _public_context(
        classification="proposal_intent", scope_status="absent", allowed_kinds=("propose",),
        read_operations=(), proposal_clarification_required=False,
        proposal_operations=(c.P2ProposalOperation.EXPENSE_CREATE,),
    )
    proposal_private = _private_context(
        classification="proposal_intent", scope_status="absent", proposal_target_resolved=True,
    )
    proposal = {
        "kind": "propose", "operation": "expense.create", "recognized_intent_text": "新增支出意图",
    }
    assert isinstance(_run(proposal_public, proposal_private, proposal), c.P2ProposalRecognition)


def test_source_answer_requires_public_qev_and_private_current_binding() -> None:
    public, private = _bound_pair()
    decision = {"kind": "answer", "basis": "fresh_read_receipts", "text": "当前证据显示一笔支出。", "citations": [QEV]}
    assert isinstance(_run(public, private, decision), c.P2AnswerDecision)

    no_public_fresh = _public_context(
        allowed_kinds=("answer",), read_operations=(), fresh_refs=(),
        evidence=public.query_evidence, facts=public.facts,
    )
    assert isinstance(c.parse_p2_decision(decision, private), c.P2AnswerDecision)
    with pytest.raises(P2V3SentGuardError, match="sent public fresh receipt"):
        _run(no_public_fresh, private, decision)

    public_fresh_only = _public_context(
        allowed_kinds=("answer",), read_operations=(), fresh_refs=(QEV,),
        evidence=public.query_evidence, facts=public.facts,
    )
    private_without_binding = _private_context(grant=private.source_authorization_grant)
    with pytest.raises(P2V3SentGuardError, match="lacks one current private receipt and grant binding"):
        _run(public_fresh_only, private_without_binding, decision)


def test_first_read_public_kind_and_operation_are_checked_before_private_fullparse() -> None:
    _, metadata_private = _metadata_pair()
    grant = _read_grant(metadata_private)
    granted_private = _private_context(grant=grant)
    request = _read_request()

    kind_denied = _public_context(
        allowed_kinds=("answer",), read_operations=(), source_free=False,
    )
    assert isinstance(c.parse_p2_decision(request, granted_private), c.P2ReadQueryRequest)
    with pytest.raises(P2V3SentGuardError, match="decision kind"):
        _run(kind_denied, granted_private, request)

    # A guard that allowlists "read" must still allowlist at least one read operation for
    # the sent context to be renderable; EXPENSES stays absent so the sent operation is denied.
    operation_denied = _public_context(
        allowed_kinds=("read",), read_operations=(c.P2ReadOperation.DEBTS,), source_free=False,
    )
    assert isinstance(c.parse_p2_decision(request, granted_private), c.P2ReadQueryRequest)
    with pytest.raises(P2V3SentGuardError, match="read operation"):
        _run(operation_denied, granted_private, request)


def test_continuation_requires_sent_hint_public_evidence_and_private_binding() -> None:
    public, private = _bound_pair(has_more=True, page_index=0)
    continuation = {
        "kind": "read", "message_type": "continue_request",
        "profile_id": c.P2_V3_CANDIDATE_PROFILE_ID,
        "versions": c.P2_V3_VERSIONS.model_dump(mode="json"),
        "query_ref": QUERY, "next_page_ref": NEXT,
    }
    assert isinstance(_run(public, private, continuation), c.P2ReadContinueRequest)
    # Public page_count is the source-page count, not a model-page ordinal.
    assert public.query_evidence[0].page_count == 2
    assert private.fresh_receipt_refs[0].page_index == 0

    private_without_public_hint = _private_context(
        grant=private.source_authorization_grant,
        receipts=private.fresh_receipt_refs,
        bindings=private.query_authorization_bindings,
    )
    no_hint_public = _public_context(
        allowed_kinds=("read",), read_operations=(c.P2ReadOperation.EXPENSES,),
        fresh_refs=(), evidence=public.query_evidence, continuations=(), facts=public.facts,
    )
    assert isinstance(c.parse_p2_decision(continuation, private_without_public_hint), c.P2ReadContinueRequest)
    with pytest.raises(P2V3SentGuardError, match="sent public context"):
        _run(no_hint_public, private_without_public_hint, continuation)


@pytest.mark.parametrize(
    ("variant", "expected"),
    [
        ("operation", "differs from its private query receipt"),
        ("query_ref", "differs from its private query receipt"),
        ("criteria", "differs from its private query receipt"),
        ("observed_at", "differs from its private query receipt"),
        ("receipt_expired", "expired or observed in the future"),
        ("grant_expired", "private query grant is expired"),
    ],
)
def test_citations_reject_public_private_receipt_drift_and_expiry(variant: str, expected: str) -> None:
    kwargs: dict[str, object] = {}
    if variant == "operation":
        kwargs["receipt_operation"] = c.P2ReadOperation.DEBTS
    elif variant == "query_ref":
        kwargs["receipt_query_ref"] = ref(77)
    elif variant == "criteria":
        kwargs["receipt_criteria_digest"] = "f" * 64
    elif variant == "observed_at":
        kwargs["receipt_observed_at"] = NOW - timedelta(minutes=4)
    elif variant == "receipt_expired":
        kwargs["expires_at"] = NOW - timedelta(seconds=1)
    elif variant == "grant_expired":
        kwargs["grant_expires_at"] = NOW - timedelta(seconds=1)
    public, private = _bound_pair(**kwargs)
    decision = {"kind": "answer", "basis": "fresh_read_receipts", "text": "有一笔支出。", "citations": [QEV]}
    with pytest.raises(P2V3SentGuardError, match=expected):
        _run(public, private, decision, now=NOW)


@pytest.mark.parametrize(
    ("variant", "expected"),
    [
        ("query_ref", "differs from its private query receipt"),
        ("criteria", "differs from its private query receipt"),
        ("observed_at", "differs from its private query receipt"),
        ("next_ref", "differ from its current private receipt"),
        ("operation", "differs from its private query receipt"),
        ("expiry", "expired or observed in the future"),
    ],
)
def test_continuation_rejects_mismatched_current_receipt(variant: str, expected: str) -> None:
    kwargs: dict[str, object] = {"has_more": True}
    if variant == "query_ref":
        kwargs["receipt_query_ref"] = ref(77)
    elif variant == "criteria":
        kwargs["receipt_criteria_digest"] = "f" * 64
    elif variant == "observed_at":
        kwargs["receipt_observed_at"] = NOW - timedelta(minutes=4)
    elif variant == "next_ref":
        # A current receipt with a different private nonce is valid DTO shape,
        # but it cannot authorize the public continuation hint.
        kwargs["receipt_next_page_ref"] = ref(78)
    elif variant == "operation":
        kwargs["receipt_operation"] = c.P2ReadOperation.DEBTS
    elif variant == "expiry":
        kwargs["expires_at"] = NOW - timedelta(seconds=1)
    public, private = _bound_pair(**kwargs)
    continuation = {
        "kind": "read", "message_type": "continue_request",
        "profile_id": c.P2_V3_CANDIDATE_PROFILE_ID,
        "versions": c.P2_V3_VERSIONS.model_dump(mode="json"),
        "query_ref": QUERY, "next_page_ref": NEXT,
    }
    with pytest.raises(P2V3SentGuardError, match=expected):
        _run(public, private, continuation, now=NOW)


def test_continuation_checks_current_scope_and_strict_private_page_index() -> None:
    foreign_scope = c.P2Scope(
        scope_kind="activity", scope_ref=ref(88), activity_ref=ref(88), ledger_unit_ref=None,
    )
    public, valid_private = _bound_pair(has_more=True)
    prepared = _prepared(public, valid_private)
    continuation = {
        "kind": "read", "message_type": "continue_request",
        "profile_id": c.P2_V3_CANDIDATE_PROFILE_ID,
        "versions": c.P2_V3_VERSIONS.model_dump(mode="json"),
        "query_ref": QUERY, "next_page_ref": NEXT,
    }
    _, foreign_private = _bound_pair(has_more=True, receipt_scope=foreign_scope)
    with pytest.raises(P2V3SentGuardError, match="projection binding"):
        _run(public, foreign_private, continuation, prepared=prepared)

    current_public, current_private = _bound_pair(has_more=True, page_index=1)
    current_prepared = _prepared(current_public, current_private)
    invalid_receipt = current_private.fresh_receipt_refs[0].model_copy(update={"page_index": -1})
    invalid_binding = current_private.query_authorization_bindings[0].model_copy(update={"receipt": invalid_receipt})
    invalid_private = current_private.model_copy(update={
        "fresh_receipt_refs": (invalid_receipt,),
        "query_authorization_bindings": (invalid_binding,),
    })
    with pytest.raises(P2V3SentGuardError, match="private intent context failed strict revalidation"):
        _run(current_public, invalid_private, continuation, prepared=current_prepared)


def test_continuation_operation_is_checked_against_sent_read_allowlist() -> None:
    criteria = _debt_criteria()
    digest = c.p2_criteria_digest(criteria)
    evidence = _evidence(
        has_more=True, operation=c.P2ReadOperation.DEBTS, criteria=criteria,
        criteria_digest=digest,
    )
    receipt = c.P2FreshQueryEvidenceRef(
        query_evidence_ref=QEV,
        query_ref=QUERY,
        principal_ref=PRINCIPAL,
        owner_turn_ref=TURN,
        generation=4,
        source_input_seq=9,
        input_digest=INPUT_DIGEST,
        operation=c.P2ReadOperation.DEBTS,
        scope_ref=ACTIVITY,
        criteria_digest=digest,
        observed_at=evidence.observed_at,
        expires_at=NOW + timedelta(hours=1),
        next_page_ref=NEXT,
        page_index=1,
    )
    grant = c.P2SourceAuthorizationGrant(
        principal_ref=PRINCIPAL,
        owner_turn_ref=TURN,
        generation=4,
        source_input_seq=9,
        input_digest=INPUT_DIGEST,
        operation=c.P2ReadOperation.DEBTS,
        scope=_scope(),
        criteria_digest=digest,
        expires_at=NOW + timedelta(hours=1),
        grant_ref=ref(59),
    )
    binding = c.P2QueryAuthorizationBinding(query_evidence_ref=QEV, receipt=receipt, grant=grant)
    public = _public_context(
        allowed_kinds=("read",),
        read_operations=(c.P2ReadOperation.EXPENSES,),
        fresh_refs=(QEV,),
        evidence=(evidence,),
        continuations=(c.P2ContinuationHint(query_evidence_ref=QEV, query_ref=QUERY, next_page_ref=NEXT),),
    )
    private = _private_context(grant=grant, receipts=(receipt,), bindings=(binding,))
    prepared = _prepared(public, private)
    continuation = {
        "kind": "read", "message_type": "continue_request",
        "profile_id": c.P2_V3_CANDIDATE_PROFILE_ID,
        "versions": c.P2_V3_VERSIONS.model_dump(mode="json"),
        "query_ref": QUERY, "next_page_ref": NEXT,
    }
    with pytest.raises(P2V3SentGuardError, match="original query operation is absent"):
        _run(public, private, continuation, prepared=prepared)


def test_proposal_operation_and_nonbusiness_answer_flag_are_sent_guarded() -> None:
    proposal_public = _public_context(
        classification="proposal_intent", scope_status="absent", allowed_kinds=("propose",),
        read_operations=(), proposal_clarification_required=False,
        proposal_operations=(c.P2ProposalOperation.EXPENSE_CREATE,),
    )
    proposal_private = _private_context(
        classification="proposal_intent", scope_status="absent", proposal_target_resolved=True,
    )
    wrong_proposal = {
        "kind": "propose", "operation": "expense.update", "recognized_intent_text": "更新支出意图",
    }
    assert isinstance(c.parse_p2_decision(wrong_proposal, proposal_private), c.P2ProposalRecognition)
    with pytest.raises(P2V3SentGuardError, match="proposal operation"):
        _run(proposal_public, proposal_private, wrong_proposal)

    public = _public_context(
        classification="non_business", scope_status="absent", allowed_kinds=("answer",),
        read_operations=(), source_free=False,
    )
    private = _private_context(classification="non_business", scope_status="absent")
    general = {"kind": "answer", "basis": "non_business_general", "text": "一般说明。", "citations": []}
    with pytest.raises(P2V3SentGuardError, match="does not permit source-free"):
        _run(public, private, general)


def test_sent_body_hash_and_strict_revalidation_reject_context_or_prepared_bypasses() -> None:
    public, private = _metadata_pair()
    prepared = _prepared(public, private)
    read = _read_request()

    tampered_prepared = prepared.model_copy(update={"context_sha256": "0" * 64})
    with pytest.raises(P2V3SentGuardError, match="prepared request failed"):
        _run(public, private, read, prepared=tampered_prepared)

    constructed = P2V3PreparedRequest.model_construct(
        **{
            **prepared.model_dump(),
            "versions": prepared.versions,
            "config": prepared.config,
            "prepared_fingerprint_sha256": "0" * 64,
        }
    )
    with pytest.raises(P2V3SentGuardError, match="prepared request failed"):
        _run(public, private, read, prepared=constructed)

    changed_public = public.model_copy(update={"input_text": "换成另一条用户输入。"})
    with pytest.raises(P2V3SentGuardError, match="does not bind the supplied public DTO"):
        _run(changed_public, private, read, prepared=prepared)

    constructed_public = c.P2ModelContext.model_construct(
        **{
            **public.model_dump(),
            "versions": public.versions,
            "trusted_intent": public.trusted_intent,
            "scope_authorization": public.scope_authorization,
            "guard": public.guard,
            "continuations": public.continuations,
            "query_evidence": public.query_evidence,
            "facts": public.facts,
            "generation": "4",
        }
    )
    with pytest.raises(P2V3SentGuardError, match="public model context failed"):
        _run(constructed_public, private, read, prepared=prepared)


def test_private_model_copy_that_changes_classification_is_rejected() -> None:
    public, private = _metadata_pair()
    prepared = _prepared(public, private)
    bypass = private.model_copy(update={"classification": "non_business"})
    with pytest.raises(P2V3SentGuardError, match="projection binding"):
        _run(public, bypass, _read_request(), prepared=prepared)


def test_continuation_has_more_false_shape_cannot_bypass_public_revalidation() -> None:
    public, private = _bound_pair(has_more=True)
    prepared = _prepared(public, private)
    bad_evidence = public.query_evidence[0].model_copy(update={
        "page": public.query_evidence[0].page.model_copy(update={"has_more": False}),
    })
    bad_public = c.P2ModelContext.model_construct(
        **{
            **public.model_dump(),
            "versions": public.versions,
            "trusted_intent": public.trusted_intent,
            "scope_authorization": public.scope_authorization,
            "guard": public.guard,
            "continuations": public.continuations,
            "query_evidence": (bad_evidence,),
            "facts": public.facts,
        }
    )
    continuation = {
        "kind": "read", "message_type": "continue_request",
        "profile_id": c.P2_V3_CANDIDATE_PROFILE_ID,
        "versions": c.P2_V3_VERSIONS.model_dump(mode="json"),
        "query_ref": QUERY, "next_page_ref": NEXT,
    }
    with pytest.raises(P2V3SentGuardError, match="public model context failed"):
        _run(bad_public, private, continuation, prepared=prepared)

