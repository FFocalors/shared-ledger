from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app import contracts as c
from app.harness import ModelOutputError
from app.p2_harness import (
    P2ExpenseSupplement,
    P2FinancialVersion,
    P2Harness,
    P2PaymentLine,
    P2ReferenceLabel,
    P2ResultProvenance,
)


NOW = datetime(2026, 10, 11, 4, 0, tzinfo=timezone.utc)
VERSION = 7
HASH_A = "a" * 64
HASH_B = "b" * 64


def expense(
    *,
    ref: c.ExpenseRef = c.ExpenseRef.E01,
    evidence: c.ExpenseEvidenceRef = c.ExpenseEvidenceRef.F01,
    amount: str = "12.50",
    currency: str = "USD",
    participants: tuple[c.ParticipantRef, ...] = (c.ParticipantRef.P01,),
    observed_at: datetime = NOW,
    context_version: int = VERSION,
    expense_version: str = "1",
    title: str = "lunch",
) -> c.ExpenseFact:
    return c.ExpenseFact(
        kind="expense",
        evidence_ref=evidence,
        expense_ref=ref,
        title=title,
        original_amount=amount,
        original_currency=currency,
        occurred_at=NOW - timedelta(hours=1),
        participant_refs=list(participants),
        financial_locked=False,
        expense_version=expense_version,
        observed_at=observed_at,
        context_version=context_version,
    )


def debt(
    *,
    evidence: c.DebtEvidenceRef = c.DebtEvidenceRef.F01,
    debtor: c.ParticipantRef = c.ParticipantRef.P01,
    creditor: c.ParticipantRef = c.ParticipantRef.P02,
    amount: str = "35.00",
    currency: str = "CNY",
    observed_at: datetime = NOW,
    context_version: int = VERSION,
) -> c.DebtFact:
    return c.DebtFact(
        kind="debt",
        evidence_ref=evidence,
        debtor_ref=debtor,
        creditor_ref=creditor,
        amount=amount,
        currency=currency,
        observed_at=observed_at,
        context_version=context_version,
    )


def make_context(
    *,
    expenses: tuple[c.ExpenseFact, ...] = (),
    debts: tuple[c.DebtFact, ...] = (),
    simulation: bool = False,
    conversation_only: bool = False,
) -> c.ModelContext:
    references: list[c.ModelReference] = [] if conversation_only else [
        c.ModelActivityReference(kind="activity", ref=c.ActivityRef.A01),
    ]
    for fact in expenses:
        references.append(c.ModelExpenseReference(kind="expense", ref=fact.expense_ref))
    participants = {
        participant
        for fact in expenses
        for participant in fact.participant_refs
    } | {
        participant
        for fact in debts
        for participant in (fact.debtor_ref, fact.creditor_ref)
    }
    references.extend(
        c.ModelParticipantReference(kind="participant", ref=participant)
        for participant in sorted(participants, key=lambda item: item.value)
    )

    results: list[c.ModelReadResult] = []
    if expenses:
        results.append(c.ModelReadResult(
            result_ref=c.ReadResultRef.R01,
            operation=c.ReadOperation.EXPENSES,
            observed_at=expenses[0].observed_at,
            context_version=expenses[0].context_version,
            simulation=simulation,
            body={"kind": "expenses", "items": list(expenses)},
        ))
    if debts:
        results.append(c.ModelReadResult(
            result_ref=c.ReadResultRef.R02,
            operation=c.ReadOperation.DEBTS,
            observed_at=debts[0].observed_at,
            context_version=debts[0].context_version,
            simulation=simulation,
            body={"kind": "debts", "items": list(debts)},
        ))

    return c.ModelContext(
        context_version=VERSION,
        input_text="Summarize verified records.",
        verified_scope=(
            {"kind": "none", "permissions": []}
            if conversation_only
            else {"kind": "activity", "activity_ref": c.ActivityRef.A01, "permissions": []}
        ),
        recent_messages=[],
        pending_slots=[],
        bound_references=references,
        read_results=results,
        policy_evidence=[],
        available_permissions=[],
    )


def provenance_for(
    context: c.ModelContext,
    *,
    current: bool = True,
    financial_version: int = 9,
    **overrides: object,
) -> list[P2ResultProvenance]:
    values = []
    for result in context.read_results:
        item = {
            "result_ref": result.result_ref,
            "operation": result.operation,
            "source": "supabase_postgrest",
            "observed_at": result.observed_at,
            "context_version": result.context_version,
            "financial_versions": [
                P2FinancialVersion(
                    activity_ref=c.ActivityRef.A01,
                    financial_version=financial_version,
                    base_currency="CNY",
                ),
            ],
            "planning_generation": 3,
            "complete": True,
            "current": current,
            "page_index": 0,
            "has_more": False,
            "source_fingerprint": HASH_A,
            "query_fingerprint": HASH_B,
            "scope_fingerprint": HASH_A,
            "turn_binding_fingerprint": HASH_B,
            "criteria_fingerprint": HASH_A,
        }
        item.update(overrides)
        values.append(P2ResultProvenance(**item))
    return values


def grounded(*citations: c.EvidenceCitation, text: str = "Unsupported reply: debt is zero.") -> c.AnswerDecision:
    return c.AnswerDecision(
        kind="answer",
        basis="grounded",
        text=text,
        citations=list(citations),
    )


def labels_for_expense_context(*, include_bob: bool = False) -> list[P2ReferenceLabel]:
    labels = [P2ReferenceLabel(kind="participant", ref=c.ParticipantRef.P01, display_name="Alice")]
    if include_bob:
        labels.append(P2ReferenceLabel(kind="participant", ref=c.ParticipantRef.P02, display_name="Bob"))
    return labels


def supplement_for(
    fact: c.ExpenseFact,
    *,
    result_ref: c.ReadResultRef = c.ReadResultRef.R01,
    evidence_ref: c.ExpenseEvidenceRef | None = None,
    expense_ref: c.ExpenseRef | None = None,
    expense_version: str | None = None,
    original_currency: str | None = None,
    base_currency: str | None = "CNY",
    observed_at: datetime | None = None,
    context_version: int | None = None,
    financial_version: int = 9,
    source_fingerprint: str = HASH_A,
    payments: list[P2PaymentLine] | None = None,
    splits: list[P2PaymentLine] | None = None,
) -> P2ExpenseSupplement:
    return P2ExpenseSupplement(
        result_ref=result_ref,
        evidence_ref=evidence_ref or fact.evidence_ref,
        expense_ref=expense_ref or fact.expense_ref,
        activity_ref=c.ActivityRef.A01,
        expense_version=expense_version or fact.expense_version,
        original_currency=original_currency or fact.original_currency,
        base_currency=base_currency,
        observed_at=observed_at or fact.observed_at,
        context_version=context_version or fact.context_version,
        financial_version=financial_version,
        source_fingerprint=source_fingerprint,
        complete=True,
        payments=payments or [
            P2PaymentLine(
                participant_ref=c.ParticipantRef.P01,
                display_name="Alice",
                role="payer",
                amount="12.50",
                currency=fact.original_currency,
            ),
        ],
        splits=splits or [
            P2PaymentLine(
                participant_ref=c.ParticipantRef.P01,
                display_name="Alice",
                role="split_participant",
                amount="12.50",
                currency=fact.original_currency,
            ),
        ],
    )


def test_conversation_text_cannot_claim_money_debt_clearance_or_write_success() -> None:
    context = make_context(conversation_only=True)
    decision = c.AnswerDecision(
        kind="answer",
        basis="conversation",
        text="Paid 100 USD, debt settled, write succeeded.",
        citations=[],
    )

    rendered = P2Harness.render_answer(decision, context)

    assert rendered.text == "\u6211\u53ef\u4ee5\u5e2e\u52a9\u67e5\u8be2\u5df2\u9a8c\u8bc1\u7684\u6d3b\u52a8\u3001\u6d88\u8d39\u548c\u6b20\u6b3e\u4fe1\u606f\u3002"
    assert rendered.citations == []
    assert "100" not in rendered.text
    assert "settled" not in rendered.text
    assert "write succeeded" not in rendered.text


def test_conversation_basis_is_rejected_when_business_context_is_present() -> None:
    fact = expense()
    context = make_context(expenses=(fact,))
    decision = c.AnswerDecision(
        kind="answer",
        basis="conversation",
        text="Debt cleared.",
        citations=[],
    )

    with pytest.raises(ModelOutputError):
        P2Harness.render_answer(decision, context)


def test_grounded_answer_renders_each_fact_original_currency_direction_and_no_sum() -> None:
    first = expense(
        evidence=c.ExpenseEvidenceRef.F01,
        ref=c.ExpenseRef.E01,
        amount="12.50",
        currency="USD",
        title="lunch",
    )
    second = expense(
        evidence=c.ExpenseEvidenceRef.F02,
        ref=c.ExpenseRef.E02,
        amount="2000",
        currency="JPY",
        title="train",
        participants=(c.ParticipantRef.P02,),
    )
    balance = debt(amount="35.00", currency="CNY")
    context = make_context(expenses=(first, second), debts=(balance,))
    decision = grounded(
        c.ExpenseEvidenceRef.F01,
        c.ExpenseEvidenceRef.F02,
        c.DebtEvidenceRef.F01,
        text="The expenses total 2012.50 USD and debt is cleared.",
    )

    rendered = P2Harness.render_answer(
        decision,
        context,
        provenance=provenance_for(context),
        reference_labels=labels_for_expense_context(include_bob=True),
    )

    assert "\u6d88\u8d39\u8bb0\u5f55\uff1alunch \u2014 12.50 USD" in rendered.text
    assert "\u6d88\u8d39\u8bb0\u5f55\uff1atrain \u2014 2000 JPY" in rendered.text
    assert "\u503a\u52a1\u8bb0\u5f55\uff1aAlice \u2192 Bob\uff0c35.00 CNY" in rendered.text
    assert "2012.50 USD" not in rendered.text
    assert "debt is cleared" not in rendered.text


def test_missing_or_stale_provenance_and_unknown_citations_fail_closed() -> None:
    fact = expense()
    context = make_context(expenses=(fact,))
    decision = grounded(c.ExpenseEvidenceRef.F01)

    with pytest.raises(ModelOutputError):
        P2Harness.render_answer(decision, context, provenance=[])

    with pytest.raises(ModelOutputError):
        P2Harness.render_answer(decision, context, provenance=provenance_for(context, current=False))

    with pytest.raises(ModelOutputError):
        P2Harness.render_answer(
            grounded(c.ExpenseEvidenceRef.F02),
            context,
            provenance=provenance_for(context),
        )


def test_unknown_or_mismatched_provenance_metadata_is_rejected() -> None:
    fact = expense()
    context = make_context(expenses=(fact,))
    with pytest.raises(ModelOutputError):
        P2Harness.build_envelope(
            context,
            provenance=provenance_for(context) + [
                P2ResultProvenance(
                    **{
                        **provenance_for(context)[0].model_dump(),
                        "result_ref": c.ReadResultRef.R03,
                    }
                )
            ],
        )

    for changed in (
        {"operation": c.ReadOperation.DEBTS},
        {"observed_at": NOW + timedelta(seconds=1)},
        {"context_version": VERSION + 1},
    ):
        with pytest.raises(ModelOutputError):
            P2Harness.build_envelope(
                context,
                provenance=provenance_for(context, **changed),
            )

    with pytest.raises(ValidationError):
        provenance_for(context, complete=False)
    with pytest.raises(ValidationError):
        provenance_for(context, has_more=True)


def test_render_answer_revalidates_explicit_provenance_against_the_current_result() -> None:
    fact = expense()
    context = make_context(expenses=(fact,))
    with pytest.raises(ModelOutputError):
        P2Harness.render_answer(
            grounded(fact.evidence_ref),
            context,
            provenance=provenance_for(context, context_version=VERSION + 1),
        )


def test_duplicate_activity_financial_versions_are_rejected() -> None:
    fact = expense()
    context = make_context(expenses=(fact,))
    base = provenance_for(context)[0]
    values = base.model_dump()
    values["financial_versions"] = [
        P2FinancialVersion(activity_ref=c.ActivityRef.A01, financial_version=9),
        P2FinancialVersion(activity_ref=c.ActivityRef.A01, financial_version=10),
    ]

    with pytest.raises((ValidationError, ModelOutputError)):
        duplicate = P2ResultProvenance(**values)
        P2Harness.build_envelope(context, provenance=[duplicate])


def test_financial_version_accepts_zero_and_rejects_negative_values() -> None:
    assert P2FinancialVersion(activity_ref=c.ActivityRef.A01, financial_version=0).financial_version == 0
    with pytest.raises(ValidationError):
        P2FinancialVersion(activity_ref=c.ActivityRef.A01, financial_version=-1)


def test_current_provenance_cannot_promote_a_simulated_or_unknown_result() -> None:
    fact = expense()
    simulated = make_context(expenses=(fact,), simulation=True)

    with pytest.raises(ModelOutputError):
        P2Harness.build_envelope(simulated, provenance=provenance_for(simulated))

    with pytest.raises(ModelOutputError):
        P2Harness.build_envelope(
            make_context(expenses=(fact,)),
            provenance=provenance_for(make_context(expenses=(fact,))) + [
                P2ResultProvenance(
                    **{
                        **provenance_for(make_context(expenses=(fact,)))[0].model_dump(),
                        "result_ref": c.ReadResultRef.R03,
                    }
                )
            ],
        )


def test_fingerprints_are_closed_sha256_metadata_not_freeform_identity() -> None:
    fact = expense()
    context = make_context(expenses=(fact,))
    values = provenance_for(context)[0].model_dump()
    values["query_fingerprint"] = "not-a-sha"
    with pytest.raises(ValidationError):
        P2ResultProvenance(**values)

    for forbidden_field in ("user_id", "owner_user_id", "turn_id", "activity_id", "expense_id"):
        values = provenance_for(context)[0].model_dump()
        values[forbidden_field] = "private-identity"
        with pytest.raises(ValidationError):
            P2ResultProvenance(**values)

    for fingerprint_field in (
        "source_fingerprint",
        "query_fingerprint",
        "scope_fingerprint",
        "turn_binding_fingerprint",
        "criteria_fingerprint",
    ):
        values = provenance_for(context)[0].model_dump()
        values[fingerprint_field] = "00000000-0000-0000-0000-000000000000"
        with pytest.raises(ValidationError):
            P2ResultProvenance(**values)


@pytest.mark.parametrize(
    "label",
    [
        P2ReferenceLabel(kind="expense", ref=c.ExpenseRef.E02, display_name="Unknown"),
        P2ReferenceLabel(kind="participant", ref=c.ExpenseRef.E01, display_name="Wrong kind"),
    ],
)
def test_unknown_or_wrong_kind_reference_labels_are_rejected(label: P2ReferenceLabel) -> None:
    fact = expense()
    context = make_context(expenses=(fact,))
    with pytest.raises(ModelOutputError):
        P2Harness.build_envelope(context, reference_labels=[label])


def test_valid_supplement_renders_trusted_participant_amounts_without_aggregation() -> None:
    fact = expense(amount="12.50", currency="USD")
    context = make_context(expenses=(fact,))
    supplement = supplement_for(fact)
    rendered = P2Harness.render_answer(
        grounded(fact.evidence_ref, text="Alice paid 12.50 USD; total is 12.50 USD."),
        context,
        provenance=provenance_for(context),
        expense_supplements=[supplement],
        reference_labels=labels_for_expense_context(),
    )

    assert "\u6d88\u8d39\u8bb0\u5f55\uff1alunch \u2014 12.50 USD" in rendered.text
    assert "\u4ed8\u6b3e Alice\uff1a12.50 USD" in rendered.text
    assert "\u5206\u644a Alice\uff1a12.50 USD" in rendered.text
    assert "the total is" not in rendered.text


def test_duplicate_expense_supplements_for_one_evidence_ref_are_rejected() -> None:
    fact = expense()
    context = make_context(expenses=(fact,))
    supplement = supplement_for(fact)

    with pytest.raises(ModelOutputError):
        P2Harness.render_answer(
            grounded(fact.evidence_ref),
            context,
            provenance=provenance_for(context),
            expense_supplements=[supplement, supplement],
            reference_labels=labels_for_expense_context(),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"result_ref": c.ReadResultRef.R02},
        {"evidence_ref": c.ExpenseEvidenceRef.F02},
        {"expense_ref": c.ExpenseRef.E02},
        {"expense_version": "2"},
        {"original_currency": "EUR"},
        {"observed_at": NOW + timedelta(seconds=1)},
        {"context_version": VERSION + 1},
        {"financial_version": 10},
        {"source_fingerprint": HASH_B},
        {
            "payments": [
                P2PaymentLine(
                    participant_ref=c.ParticipantRef.P02,
                    display_name="Bob",
                    role="payer",
                    amount="12.50",
                    currency="USD",
                )
            ],
        },
        {
            "payments": [
                P2PaymentLine(
                    participant_ref=c.ParticipantRef.P01,
                    display_name="Mallory",
                    role="payer",
                    amount="12.50",
                    currency="USD",
                )
            ],
        },
        {
            "payments": [
                P2PaymentLine(
                    participant_ref=c.ParticipantRef.P01,
                    display_name="Alice",
                    role="payer",
                    amount="12.50",
                    currency="EUR",
                )
            ],
        },
    ],
)
def test_cross_bound_or_untrusted_expense_supplement_is_rejected(changes: dict[str, object]) -> None:
    fact = expense()
    context = make_context(expenses=(fact,))
    supplement = supplement_for(fact, **changes)

    with pytest.raises(ModelOutputError):
        P2Harness.render_answer(
            grounded(fact.evidence_ref),
            context,
            provenance=provenance_for(context),
            expense_supplements=[supplement],
            reference_labels=labels_for_expense_context(),
        )


def test_expense_supplement_cannot_cross_bind_a_result_with_wrong_operation_or_fingerprint() -> None:
    fact = expense()
    context = make_context(expenses=(fact,))
    wrong_operation = provenance_for(context, operation=c.ReadOperation.DEBTS)
    wrong_source = provenance_for(context, source_fingerprint=HASH_B)
    supplement = supplement_for(fact)

    for provenance in (wrong_operation, wrong_source):
        with pytest.raises(ModelOutputError):
            P2Harness.render_answer(
                grounded(fact.evidence_ref),
                context,
                provenance=provenance,
                expense_supplements=[supplement],
                reference_labels=labels_for_expense_context(),
            )
