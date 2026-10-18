"""P2 Harness envelope and conservative answer rendering.

The frozen v1 semantic context remains authoritative. P2 metadata is typed,
internal-only, and contains no service UUIDs or credentials.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from typing_extensions import Annotated

from . import contracts as c
from .harness import ModelOutputError, ModelPrompt, parse_model_output


Fingerprint = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]


class P2FinancialVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    activity_ref: c.ActivityRef
    financial_version: int = Field(ge=0)
    base_currency: c.CurrencyCode | None = None


class P2ResultProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    result_ref: c.ReadResultRef
    operation: c.ReadOperation
    source: Literal["supabase_postgrest"]
    observed_at: datetime
    context_version: int = Field(ge=1)
    financial_versions: list[P2FinancialVersion] = Field(max_length=16)
    planning_generation: int = Field(ge=1)
    complete: Literal[True] = True
    current: bool
    page_index: int = Field(ge=0, le=15)
    has_more: Literal[False] = False
    source_fingerprint: Fingerprint
    query_fingerprint: Fingerprint
    scope_fingerprint: Fingerprint
    turn_binding_fingerprint: Fingerprint
    criteria_fingerprint: Fingerprint


class P2ReferenceLabel(BaseModel):
    """Harness-verified human label for one opaque v1 reference."""

    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["activity", "ledger_unit", "expense", "participant"]
    ref: c.ModelRefToken
    display_name: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=160)]
    evidence_ref: c.EvidenceCitation | None = None


class P2PaymentLine(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    participant_ref: c.ParticipantRef
    display_name: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=160)] | None = None
    role: Literal["payer", "split_participant"]
    amount: c.MoneyString
    currency: c.CurrencyCode
    base_amount: c.MoneyString | None = None
    base_currency: c.CurrencyCode | None = None


class P2ExpenseSupplement(BaseModel):
    """Trusted exact backend detail linked to an existing v1 expense evidence token."""

    model_config = ConfigDict(extra="forbid", strict=True)

    result_ref: c.ReadResultRef
    evidence_ref: c.ExpenseEvidenceRef
    expense_ref: c.ExpenseRef
    activity_ref: c.ActivityRef
    expense_version: c.ExpenseVersion
    original_currency: c.CurrencyCode
    base_currency: c.CurrencyCode | None = None
    observed_at: datetime
    context_version: int = Field(ge=1)
    financial_version: int = Field(ge=0)
    source_fingerprint: Fingerprint
    complete: Literal[True] = True
    payments: list[P2PaymentLine] = Field(max_length=32)
    splits: list[P2PaymentLine] = Field(max_length=32)


class P2PromptEnvelope(ModelPrompt):
    """Typed provider input; only safe opaque refs and trusted display facts are added."""

    provenance: list[P2ResultProvenance] = Field(max_length=16)
    reference_labels: list[P2ReferenceLabel] = Field(max_length=64)
    expense_supplements: list[P2ExpenseSupplement] = Field(max_length=16)


_MONEY_TOKEN = re.compile(
    r"(?i)(?:[$€£¥￥]\s*[-+]?\d[\d,]*(?:\.\d+)?|"
    r"[-+]?\d[\d,]*(?:\.\d+)?\s*(?:元|圆|人民币|美元|欧元|英镑|日元|CNY|RMB|USD|EUR|GBP|JPY))"
)
_CHINESE_MONEY_TOKEN = re.compile(r"[零〇一二两三四五六七八九十百千万亿]+\s*(?:元|圆|人民币)")


class P2Harness:
    """Build safe provider envelopes and render only trusted grounded facts."""

    @staticmethod
    def build_envelope(
        context: c.ModelContext,
        *,
        repair_feedback: str | None = None,
        expense_supplements: list[P2ExpenseSupplement] | None = None,
        reference_labels: list[P2ReferenceLabel] | None = None,
        provenance: list[P2ResultProvenance] | None = None,
    ) -> P2PromptEnvelope:
        # Missing provenance (including after restart) is deliberately stale.
        by_ref = P2Harness._validated_provenance(context, provenance or [])
        ordered_provenance = [by_ref[item.result_ref] for item in context.read_results if item.result_ref in by_ref]
        labels_by_ref = {item.ref: item for item in P2Harness._reference_labels(context)}
        supplied_labels = reference_labels or []
        supplied_refs = [item.ref for item in supplied_labels]
        if len(supplied_refs) != len(set(supplied_refs)):
            raise ModelOutputError("trusted reference label is duplicated")
        for item in supplied_labels:
            existing = labels_by_ref.get(item.ref)
            if existing is not None and (
                existing.kind != item.kind or existing.display_name != item.display_name
            ):
                raise ModelOutputError("trusted reference label conflicts with a persisted fact label")
            labels_by_ref[item.ref] = item
        bound_by_ref = {item.ref: item for item in context.bound_references}
        for label in labels_by_ref.values():
            bound = bound_by_ref.get(label.ref)
            if bound is None or bound.kind != label.kind:
                raise ModelOutputError("trusted reference label does not match a bound model reference")
        labels = [labels_by_ref[key] for key in sorted(labels_by_ref, key=lambda item: item.value)]
        supplements = P2Harness._validated_supplements(
            context, by_ref, expense_supplements or [], labels_by_ref,
        )
        return P2PromptEnvelope(
            context=context,
            repair_feedback=repair_feedback,
            provenance=ordered_provenance,
            reference_labels=labels,
            expense_supplements=list(supplements.values()),
        )

    @staticmethod
    def parse(raw: str, context: c.ModelContext) -> c.SemanticDecision:
        return parse_model_output(raw, context)

    @staticmethod
    def render_answer(
        decision: c.AnswerDecision,
        context: c.ModelContext,
        *,
        provenance: list[P2ResultProvenance] | None = None,
        expense_supplements: list[P2ExpenseSupplement] | None = None,
        reference_labels: list[P2ReferenceLabel] | None = None,
    ) -> c.AnswerDecision:
        if decision.basis == "conversation":
            if context.read_results or context.policy_evidence or context.bound_references:
                raise ModelOutputError("business context requires a grounded answer with current citations")
            return decision.model_copy(update={
                "text": "我可以帮助查询已验证的活动、消费和欠款信息。",
                "citations": [],
            })

        trusted_provenance = provenance if provenance is not None else P2Harness.build_envelope(context).provenance
        provenance_by_ref = P2Harness._validated_provenance(context, trusted_provenance)
        current_refs = {
            item.result_ref
            for item in provenance_by_ref.values()
            if item.complete and item.current
        }
        current_citations: set[c.EvidenceCitation] = set()
        for result in context.read_results:
            if result.result_ref not in current_refs:
                continue
            current_citations.update(item.evidence_ref for item in result.body.items)
        current_citations.update(item.evidence_ref for item in context.policy_evidence)
        if any(citation not in current_citations for citation in decision.citations):
            raise ModelOutputError("grounded answer cited stale or unverified evidence")

        facts_by_evidence: dict[c.EvidenceCitation, object] = {
            fact.evidence_ref: fact
            for result in context.read_results
            if result.result_ref in current_refs
            for fact in result.body.items
        }
        result_by_evidence = {
            fact.evidence_ref: result.result_ref
            for result in context.read_results
            if result.result_ref in current_refs
            for fact in result.body.items
        }
        policies = {item.evidence_ref: item for item in context.policy_evidence}
        labels_by_ref = {item.ref: item for item in (reference_labels or P2Harness._reference_labels(context))}
        valid_refs = {item.ref for item in context.bound_references}
        for label in labels_by_ref.values():
            if label.ref not in valid_refs:
                raise ModelOutputError("trusted label references an unbound model ref")
            binding = next(item for item in context.bound_references if item.ref == label.ref)
            if label.kind != binding.kind:
                raise ModelOutputError("trusted label kind does not match its bound reference")
        supplements = P2Harness._validated_supplements(
            context, provenance_by_ref, expense_supplements or [], labels_by_ref,
        )
        labels = {item.ref: item.display_name for item in labels_by_ref.values()}
        lines: list[str] = []
        for citation in decision.citations:
            fact = facts_by_evidence.get(citation)
            if isinstance(fact, c.ActivityFact):
                lines.append(f"活动：{fact.name}（{fact.base_currency}）")
            elif isinstance(fact, c.ExpenseFact):
                lines.append(f"消费记录：{fact.title} — {fact.original_amount} {fact.original_currency}")
                supplement = supplements.get(citation)
                if supplement is not None:
                    for payment in supplement.payments:
                        label = labels_by_ref[payment.participant_ref].display_name
                        lines.append(f"付款 {label}：{payment.amount} {payment.currency}")
                    for split in supplement.splits:
                        label = labels_by_ref[split.participant_ref].display_name
                        lines.append(f"分摊 {label}：{split.amount} {split.currency}")
            elif isinstance(fact, c.DebtFact):
                lines.append(
                    f"债务记录：{labels.get(fact.debtor_ref, fact.debtor_ref.value)} → "
                    f"{labels.get(fact.creditor_ref, fact.creditor_ref.value)}，"
                    f"{fact.amount} {fact.currency}"
                )
            else:
                policy = policies.get(citation)
                if policy is not None:
                    lines.append(policy.text)
        if not lines:
            raise ModelOutputError("grounded answer has no current trusted facts")
        rendered = "根据当前可信记录：\n" + "\n".join(lines)
        if len(rendered) > 2000:
            raise ModelOutputError("trusted fact rendering exceeds the answer limit; narrow the query")
        return decision.model_copy(update={"text": rendered})

    @staticmethod
    def proposal_acknowledgement() -> c.AnswerDecision:
        return c.AnswerDecision(
            kind="answer",
            basis="conversation",
            text="我已识别到一项提议意图；本阶段不会创建预览、确认卡或执行写入。",
            citations=[],
        )

    @staticmethod
    def _reference_labels(context: c.ModelContext) -> list[P2ReferenceLabel]:
        names: dict[c.ModelRefToken, tuple[Literal["activity", "expense"], str, c.EvidenceCitation | None]] = {}
        for result in context.read_results:
            for fact in result.body.items:
                if isinstance(fact, c.ActivityFact):
                    names[fact.activity_ref] = ("activity", fact.name, fact.evidence_ref)
                elif isinstance(fact, c.ExpenseFact):
                    names[fact.expense_ref] = ("expense", fact.title, fact.evidence_ref)
        labels: list[P2ReferenceLabel] = []
        for item in context.bound_references:
            found = names.get(item.ref)
            if found is None:
                continue
            labels.append(P2ReferenceLabel(
                kind=found[0],
                ref=item.ref,
                display_name=found[1],
                evidence_ref=found[2],
            ))
        return labels

    @staticmethod
    def _validated_provenance(
        context: c.ModelContext,
        provenance: list[P2ResultProvenance],
    ) -> dict[c.ReadResultRef, P2ResultProvenance]:
        by_ref = {item.result_ref: item for item in provenance}
        if len(by_ref) != len(provenance):
            raise ModelOutputError("trusted result provenance is duplicated")
        results = {item.result_ref: item for item in context.read_results}
        if set(by_ref) - set(results):
            raise ModelOutputError("trusted result provenance has no durable result")
        for result_ref, item in by_ref.items():
            result = results[result_ref]
            financial_refs = [version.activity_ref for version in item.financial_versions]
            if len(financial_refs) != len(set(financial_refs)):
                raise ModelOutputError("trusted financial version metadata is duplicated")
            if item.operation in (c.ReadOperation.EXPENSES, c.ReadOperation.DEBTS):
                if not isinstance(context.verified_scope, c.ModelActivityScope):
                    if item.current:
                        raise ModelOutputError("activity read provenance requires a verified activity scope")
                elif item.current and context.verified_scope.activity_ref not in financial_refs:
                    raise ModelOutputError("current activity read has no matching financial version")
            if (
                item.operation != result.operation
                or item.observed_at != result.observed_at
                or item.context_version != result.context_version
                or item.planning_generation < 1
                or item.current and result.simulation
                or item.complete is not True
                or item.has_more is not False
            ):
                raise ModelOutputError("trusted result provenance does not match durable result")
        return by_ref

    @staticmethod
    def _validated_supplements(
        context: c.ModelContext,
        provenance_by_ref: dict[c.ReadResultRef, P2ResultProvenance],
        supplements: list[P2ExpenseSupplement],
        labels_by_ref: dict[c.ModelRefToken, P2ReferenceLabel],
    ) -> dict[c.ExpenseEvidenceRef, P2ExpenseSupplement]:
        results = {result.result_ref: result for result in context.read_results}
        facts = {
            fact.evidence_ref: (result, fact)
            for result in context.read_results
            for fact in result.body.items
        }
        references = {reference.ref: reference for reference in context.bound_references}
        by_evidence: dict[c.ExpenseEvidenceRef, P2ExpenseSupplement] = {}
        for supplement in supplements:
            if supplement.evidence_ref in by_evidence:
                raise ModelOutputError("expense supplement evidence is duplicated")
            result = results.get(supplement.result_ref)
            provenance = provenance_by_ref.get(supplement.result_ref)
            fact_pair = facts.get(supplement.evidence_ref)
            if result is None or provenance is None or fact_pair is None:
                raise ModelOutputError("expense supplement does not match a trusted result")
            stored_result, fact = fact_pair
            version = next((
                item for item in provenance.financial_versions
                if item.activity_ref == supplement.activity_ref
            ), None)
            if not isinstance(fact, c.ExpenseFact) or (
                not supplement.complete
                or not provenance.complete
                or not provenance.current
                or provenance.operation != c.ReadOperation.EXPENSES
                or result.operation != c.ReadOperation.EXPENSES
                or provenance.source != "supabase_postgrest"
                or supplement.source_fingerprint != provenance.source_fingerprint
                or supplement.financial_version != (version.financial_version if version else None)
                or supplement.base_currency != (version.base_currency if version else None)
                or stored_result.result_ref != supplement.result_ref
                or result.observed_at != supplement.observed_at
                or result.context_version != supplement.context_version
                or provenance.observed_at != supplement.observed_at
                or provenance.context_version != supplement.context_version
                or fact.evidence_ref != supplement.evidence_ref
                or fact.expense_ref != supplement.expense_ref
                or fact.expense_version != supplement.expense_version
                or fact.original_currency != supplement.original_currency
                or fact.observed_at != supplement.observed_at
                or fact.context_version != supplement.context_version
                or not isinstance(context.verified_scope, c.ModelActivityScope)
                or context.verified_scope.activity_ref != supplement.activity_ref
            ):
                raise ModelOutputError("expense supplement does not match its current trusted fact")
            expense_binding = references.get(supplement.expense_ref)
            if expense_binding is None or expense_binding.kind != "expense":
                raise ModelOutputError("expense supplement references an unbound expense")
            participant_refs = set(fact.participant_refs)
            if any(line.role != "payer" for line in supplement.payments):
                raise ModelOutputError("payment line role does not match its source list")
            if any(line.role != "split_participant" for line in supplement.splits):
                raise ModelOutputError("split line role does not match its source list")
            for line in (*supplement.payments, *supplement.splits):
                participant_binding = references.get(line.participant_ref)
                if (
                    participant_binding is None
                    or participant_binding.kind != "participant"
                    or line.participant_ref not in participant_refs
                ):
                    raise ModelOutputError("expense supplement contains an unbound participant")
                allowed_currencies = {supplement.original_currency}
                if supplement.base_currency is not None:
                    allowed_currencies.add(supplement.base_currency)
                if line.currency not in allowed_currencies:
                    raise ModelOutputError("expense supplement currency is not a trusted source currency")
                label = labels_by_ref.get(line.participant_ref)
                if label is None or label.kind != "participant" or label.display_name != line.display_name:
                    raise ModelOutputError("expense supplement participant label kind is invalid")
            by_evidence[supplement.evidence_ref] = supplement
        return by_evidence

    @staticmethod
    def _contains_financial_claim(value: str) -> bool:
        return bool(_MONEY_TOKEN.search(value) or _CHINESE_MONEY_TOKEN.search(value))

    @staticmethod
    def _fingerprint(value: object) -> str:
        canonical = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

