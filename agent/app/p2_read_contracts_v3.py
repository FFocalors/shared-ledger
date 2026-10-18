"""Disabled, unassembled P2 read-paged v3 candidate contracts.

This module is intentionally not imported by the application. It defines strict
DTOs only; scope authorization, source freshness, provenance, and causal
clarification remain runtime responsibilities.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import hashlib
import json
import math
import re
from typing import Annotated, Any, Generic, Literal, Mapping, TypeAlias, TypeVar, Union
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)


P2_V3_CANDIDATE_PROFILE_ID = "p2.read-paged-prepayment-refund.v3-candidate"
P2_DEBT_SOURCE_VARIANT = "expense_debt_line"
MAX_FINANCIAL_VERSION = 9_223_372_036_854_775_807


class P2V3ProtocolVersions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    api: Literal["3.0.0"]
    semantic: Literal["2.1.0"]
    operations: Literal["2.1.0"]
    trajectory: Literal["2.0.0"]


P2_V3_VERSIONS = P2V3ProtocolVersions(
    api="3.0.0", semantic="2.1.0", operations="2.1.0", trajectory="2.0.0"
)


class P2ReadOperation(StrEnum):
    ACTIVITIES = "read.activities"
    EXPENSES = "read.expenses"
    DEBTS = "read.debts"
    REFUND_EVENTS = "read.refund_events"
    PREPAYMENT_ACCOUNTS = "read.prepayment_accounts"
    PREPAYMENT_USAGES = "read.prepayment_usages"
    PREPAYMENT_RETURN_EVENTS = "read.prepayment_return_events"


def _read_operation_value(value: Any) -> Any:
    if isinstance(value, P2ReadOperation):
        return value
    if type(value) is str:
        try:
            return P2ReadOperation(value)
        except ValueError:
            return value
    return value


P2ReadOperationField = Annotated[P2ReadOperation, BeforeValidator(_read_operation_value)]


class P2ProposalOperation(StrEnum):
    EXPENSE_CREATE = "expense.create"
    EXPENSE_UPDATE = "expense.update"
    EXPENSE_PRESENTATION_UPDATE = "expense.presentation.update"


P2ClarificationSlot: TypeAlias = Literal[
    "activity_scope", "ledger_unit_scope", "expense_target", "participant_target", "currency",
    "date_range", "prepayment_account", "return_target", "proposal_target", "proposal_title",
    "proposal_amount", "proposal_currency", "proposal_participant", "proposal_occurred_at",
]
P2ClarificationReason: TypeAlias = Literal[
    "missing_required_scope", "multiple_scope_matches", "ambiguous_user_reference",
    "required_target_missing", "source_label_unavailable",
]


class P2WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


OpaqueRef = Annotated[
    StrictStr,
    StringConstraints(pattern=r"^ref_[A-Za-z0-9_-]{22,64}$", min_length=26, max_length=68),
]
QueryEvidenceRef = Annotated[
    StrictStr,
    StringConstraints(pattern=r"^qev_[A-Za-z0-9_-]{22,64}$", min_length=26, max_length=68),
]
Digest = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)]
CurrencyCode = Annotated[StrictStr, StringConstraints(pattern=r"^[A-Z]{3}$", min_length=3, max_length=3)]
ShortText = Annotated[StrictStr, StringConstraints(min_length=1, max_length=200)]
LongText = Annotated[StrictStr, StringConstraints(min_length=1, max_length=4000)]

# PostgreSQL numeric(p,s) text shapes: do not coerce floats, ints, bools, or
# strings with excess precision. Each source domain stays distinct.
Numeric20_4 = Annotated[
    StrictStr,
    StringConstraints(pattern=r"^-?(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,4})?$", max_length=22),
]
BaseNumeric20_1 = Annotated[
    StrictStr,
    StringConstraints(pattern=r"^(?:0|[1-9][0-9]{0,18})(?:\.[0-9])?$", max_length=21),
]
SignedBaseNumeric20_1 = Annotated[
    StrictStr,
    StringConstraints(pattern=r"^-?(?:0|[1-9][0-9]{0,18})(?:\.[0-9])?$", max_length=22),
]
FxRateNumeric20_10 = Annotated[
    StrictStr,
    StringConstraints(pattern=r"^(?:0|[1-9][0-9]{0,9})(?:\.[0-9]{1,10})?$", max_length=21),
]


def _decimal(value: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as exc:  # defensive; the lexical constraints run first
        raise ValueError("invalid decimal source lexeme") from exc


def _nonzero(value: str) -> str:
    if _decimal(value) == 0:
        raise ValueError("amount must be nonzero")
    return value


def _positive(value: str) -> str:
    if _decimal(value) <= 0:
        raise ValueError("amount must be positive")
    return value


def _nonnegative(value: str) -> str:
    if _decimal(value) < 0:
        raise ValueError("amount must be nonnegative")
    return value


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("source datetime must be timezone-aware")
    return value


class P2Scope(P2WireModel):
    scope_kind: Literal["activity", "ledger_unit"]
    scope_ref: OpaqueRef
    activity_ref: OpaqueRef | None = None
    ledger_unit_ref: OpaqueRef | None = None

    @model_validator(mode="after")
    def scope_links_are_consistent(self) -> "P2Scope":
        if self.scope_kind == "activity":
            if self.activity_ref != self.scope_ref or self.ledger_unit_ref is not None:
                raise ValueError("activity scope refs must identify the same Activity")
        elif self.ledger_unit_ref != self.scope_ref or self.activity_ref is None:
            raise ValueError("ledger-unit scope requires matching unit and parent Activity refs")
        return self


class ActivityCriteria(P2WireModel):
    kind: Literal["activities"]
    status: Literal["active", "archived", "any"] = "active"
    name_contains: ShortText | None = None


class ExpenseCriteria(P2WireModel):
    kind: Literal["expenses"]
    activity_ref: OpaqueRef
    from_date: date | None = None
    to_date: date | None = None
    participant_ref: OpaqueRef | None = None
    title_contains: ShortText | None = None

    @model_validator(mode="after")
    def dates_are_ordered(self) -> "ExpenseCriteria":
        if self.from_date is not None and self.to_date is not None and self.from_date > self.to_date:
            raise ValueError("from_date must not be after to_date")
        return self


class DebtCriteria(P2WireModel):
    kind: Literal["debts"]
    activity_ref: OpaqueRef
    participant_ref: OpaqueRef | None = None
    currency: CurrencyCode | None = None


class RefundEventCriteria(P2WireModel):
    kind: Literal["refund_events"]
    activity_ref: OpaqueRef
    from_date: date | None = None
    to_date: date | None = None

    @model_validator(mode="after")
    def dates_are_ordered(self) -> "RefundEventCriteria":
        if self.from_date is not None and self.to_date is not None and self.from_date > self.to_date:
            raise ValueError("from_date must not be after to_date")
        return self


class PrepaymentAccountsCriteria(P2WireModel):
    kind: Literal["prepayment_accounts"]
    activity_ref: OpaqueRef


class PrepaymentUsagesCriteria(P2WireModel):
    kind: Literal["prepayment_usages"]
    activity_ref: OpaqueRef
    expense_ref: OpaqueRef | None = None
    participant_ref: OpaqueRef | None = None


class PrepaymentReturnCriteria(P2WireModel):
    kind: Literal["prepayment_return_events"]
    activity_ref: OpaqueRef
    from_date: date | None = None
    to_date: date | None = None

    @model_validator(mode="after")
    def dates_are_ordered(self) -> "PrepaymentReturnCriteria":
        if self.from_date is not None and self.to_date is not None and self.from_date > self.to_date:
            raise ValueError("from_date must not be after to_date")
        return self


P2ReadCriteria: TypeAlias = Annotated[
    Union[
        ActivityCriteria,
        ExpenseCriteria,
        DebtCriteria,
        RefundEventCriteria,
        PrepaymentAccountsCriteria,
        PrepaymentUsagesCriteria,
        PrepaymentReturnCriteria,
    ],
    Field(discriminator="kind"),
]


class P2ReadQueryRequest(P2WireModel):
    kind: Literal["read"]
    message_type: Literal["query_request"]
    profile_id: Literal[P2_V3_CANDIDATE_PROFILE_ID]
    versions: P2V3ProtocolVersions
    operation: P2ReadOperationField
    criteria: P2ReadCriteria
    scope: P2Scope | None = None

    @model_validator(mode="after")
    def operation_and_scope_match(self) -> "P2ReadQueryRequest":
        if self.versions != P2_V3_VERSIONS:
            raise ValueError("unsupported or mixed candidate protocol version tuple")
        expected = {
            P2ReadOperation.ACTIVITIES: ActivityCriteria,
            P2ReadOperation.EXPENSES: ExpenseCriteria,
            P2ReadOperation.DEBTS: DebtCriteria,
            P2ReadOperation.REFUND_EVENTS: RefundEventCriteria,
            P2ReadOperation.PREPAYMENT_ACCOUNTS: PrepaymentAccountsCriteria,
            P2ReadOperation.PREPAYMENT_USAGES: PrepaymentUsagesCriteria,
            P2ReadOperation.PREPAYMENT_RETURN_EVENTS: PrepaymentReturnCriteria,
        }[self.operation]
        if not isinstance(self.criteria, expected):
            raise ValueError("operation and criteria kind do not match")
        if self.operation == P2ReadOperation.ACTIVITIES:
            if self.scope is not None and self.scope.scope_kind != "activity":
                raise ValueError("Activity discovery may only be bounded by an Activity scope")
        elif self.scope is None:
            raise ValueError("scoped read operations require an authorized scope")
        if self.scope is not None and hasattr(self.criteria, "activity_ref"):
            if getattr(self.criteria, "activity_ref") != self.scope.activity_ref:
                raise ValueError("criteria Activity and scope Activity must match")
        return self


class P2ReadContinueRequest(P2WireModel):
    kind: Literal["read"]
    message_type: Literal["continue_request"]
    profile_id: Literal[P2_V3_CANDIDATE_PROFILE_ID]
    versions: P2V3ProtocolVersions
    query_ref: OpaqueRef
    next_page_ref: OpaqueRef

    @model_validator(mode="after")
    def version_tuple_is_supported(self) -> "P2ReadContinueRequest":
        if self.versions != P2_V3_VERSIONS:
            raise ValueError("unsupported or mixed candidate protocol version tuple")
        return self


P2ReadRequest: TypeAlias = Annotated[
    Union[P2ReadQueryRequest, P2ReadContinueRequest], Field(discriminator="message_type")
]
_READ_REQUEST_ADAPTER = TypeAdapter(P2ReadRequest)


def parse_p2_read_request(payload: Any) -> P2ReadRequest:
    """Strictly parse one candidate request; no UUID-to-ref promotion occurs here."""
    decision = parse_p2_decision_shape(payload)
    if not isinstance(decision, P2ReadQueryRequest | P2ReadContinueRequest):
        raise ValueError("payload is not a read request")
    return decision


class P2UntrustedUIResolutionHints(P2WireModel):
    """Raw app hints accepted only by a server resolver, never model authority."""

    activity_ids: tuple[UUID, ...] = Field(default=(), max_length=16)
    expense_ids: tuple[UUID, ...] = Field(default=(), max_length=32)


class ParticipantAllocationFact(P2WireModel):
    participant_ref: OpaqueRef
    role: Literal["payer", "split"]
    signed_original_amount: Numeric20_4
    original_currency: CurrencyCode
    signed_base_amount: SignedBaseNumeric20_1
    base_currency: CurrencyCode

    _nonzero_original = field_validator("signed_original_amount")(_nonzero)


class ActivityFact(P2WireModel):
    fact_kind: Literal["activity"]
    activity_ref: OpaqueRef
    activity_kind: ShortText
    name: ShortText
    base_currency: CurrencyCode | None
    status: Literal["active", "archived", "unknown"]
    observed_at: datetime
    context_version: StrictStr
    query_evidence_ref: QueryEvidenceRef

    _observed_at_aware = field_validator("observed_at")(_aware_datetime)


class ExpenseFact(P2WireModel):
    fact_kind: Literal["expense"]
    expense_ref: OpaqueRef
    title: ShortText
    scope_ref: OpaqueRef
    occurred_at: datetime
    signed_original_amount: Numeric20_4
    original_currency: CurrencyCode
    signed_base_amount: SignedBaseNumeric20_1
    base_currency: CurrencyCode
    payer_split_lines: tuple[ParticipantAllocationFact, ...] = Field(min_length=1, max_length=128)
    expense_version: Annotated[StrictInt, Field(ge=0, le=MAX_FINANCIAL_VERSION)]
    financial_version: Annotated[StrictInt, Field(ge=0, le=MAX_FINANCIAL_VERSION)]
    query_evidence_ref: QueryEvidenceRef

    _nonzero_original = field_validator("signed_original_amount")(_nonzero)
    _occurred_at_aware = field_validator("occurred_at")(_aware_datetime)

    @field_validator("title")
    @classmethod
    def title_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source expense title must not be blank")
        return value


class DebtFact(P2WireModel):
    fact_kind: Literal["debt"]
    debt_source_variant: Literal["expense_debt_line"] = P2_DEBT_SOURCE_VARIANT
    debt_ref: OpaqueRef
    scope_ref: OpaqueRef
    activity_ref: OpaqueRef
    ledger_unit_ref: OpaqueRef
    expense_ref: OpaqueRef
    debtor_ref: OpaqueRef
    creditor_ref: OpaqueRef
    original_amount: Numeric20_4 | None
    original_currency: CurrencyCode | None
    base_amount: BaseNumeric20_1
    base_currency: CurrencyCode
    financial_version: Annotated[StrictInt, Field(ge=0, le=MAX_FINANCIAL_VERSION)]
    query_evidence_ref: QueryEvidenceRef

    _nonnegative_base = field_validator("base_amount")(_nonnegative)

    @model_validator(mode="after")
    def no_inferred_original_and_distinct_parties(self) -> "DebtFact":
        if self.debtor_ref == self.creditor_ref:
            raise ValueError("debt participants must differ")
        if self.original_amount is not None and _decimal(self.original_amount) <= 0:
            raise ValueError("persisted original debt amount must be positive when present")
        return self


class P2ExpenseDebtSourceAmounts(P2WireModel):
    """Raw source values only; this deliberately has no debt-row version field."""

    amount: BaseNumeric20_1
    original_amount: Numeric20_4 | None
    original_currency: CurrencyCode | None
    fx_rate: FxRateNumeric20_10 | None

    @field_validator("amount")
    @classmethod
    def base_amount_nonnegative(cls, value: str) -> str:
        return _nonnegative(value)

    @field_validator("fx_rate")
    @classmethod
    def rate_positive_when_present(cls, value: str | None) -> str | None:
        if value is not None and _decimal(value) <= 0:
            raise ValueError("FX rate must be positive when present")
        return value


def parse_expense_debt_source_amounts(row: Mapping[str, Any]) -> P2ExpenseDebtSourceAmounts:
    """Parse selected `expense_debts` source columns without filling nullable data."""
    if "financial_version" in row:
        raise ValueError("expense_debts has no row-level financial_version; bind the Activity fence separately")
    required = {"amount", "original_amount", "original_currency", "fx_rate"}
    if not required.issubset(row):
        raise ValueError("expense_debts amount projection is missing a source column")
    amount = parse_source_numeric_lexeme(row["amount"], precision=20, scale=1)
    original = row["original_amount"]
    if original is not None:
        original = parse_source_numeric_lexeme(original, precision=20, scale=4)
    fx_rate = row["fx_rate"]
    if fx_rate is not None:
        fx_rate = parse_source_numeric_lexeme(fx_rate, precision=20, scale=10)
    return P2ExpenseDebtSourceAmounts(
        amount=amount,
        original_amount=original,
        original_currency=row["original_currency"],
        fx_rate=fx_rate,
    )


class RefundEventFact(P2WireModel):
    fact_kind: Literal["refund_event"]
    refund_ref: OpaqueRef
    scope_ref: OpaqueRef
    signed_original_amount: Numeric20_4
    original_currency: CurrencyCode
    signed_base_amount: SignedBaseNumeric20_1
    base_currency: CurrencyCode
    occurred_at: datetime
    parent_expense_ref: OpaqueRef | None
    lineage_status: Literal["verified_same_activity_parent", "parent_unavailable", "unverified"]
    lineage_basis: Literal["public_parent_relationship"] | None = None
    refund_recipient_ref: OpaqueRef | None
    financial_version: Annotated[StrictInt, Field(ge=0, le=MAX_FINANCIAL_VERSION)]
    query_evidence_ref: QueryEvidenceRef

    _occurred_at_aware = field_validator("occurred_at")(_aware_datetime)

    @field_validator("signed_original_amount")
    @classmethod
    def linked_refund_is_negative_nonzero(cls, value: str) -> str:
        if _decimal(value) >= 0:
            raise ValueError("refund original amount must be negative and nonzero")
        return value

    @field_validator("signed_base_amount")
    @classmethod
    def refund_base_is_negative_or_zero(cls, value: str) -> str:
        if _decimal(value) > 0:
            raise ValueError("refund base amount must be negative or zero")
        return value

    @model_validator(mode="after")
    def public_lineage_only(self) -> "RefundEventFact":
        if self.lineage_status == "verified_same_activity_parent":
            if self.parent_expense_ref is None or self.lineage_basis != "public_parent_relationship":
                raise ValueError("verified lineage requires a public same-Activity parent relationship")
        elif self.lineage_basis is not None:
            raise ValueError("unverified lineage cannot carry a verification basis")
        return self


class PrepaymentAccountFact(P2WireModel):
    fact_kind: Literal["prepayment_account"]
    account_ref: OpaqueRef
    activity_ref: OpaqueRef
    owner_ref: OpaqueRef
    custodian_ref: OpaqueRef
    balance: Numeric20_4
    currency: CurrencyCode
    projection_updated_at: datetime
    financial_version: Annotated[StrictInt, Field(ge=0, le=MAX_FINANCIAL_VERSION)]
    query_evidence_ref: QueryEvidenceRef

    _nonnegative_balance = field_validator("balance")(_nonnegative)
    _projection_updated_at_aware = field_validator("projection_updated_at")(_aware_datetime)


class PrepaymentUsageFact(P2WireModel):
    fact_kind: Literal["prepayment_usage"]
    usage_ref: OpaqueRef
    account_ref: OpaqueRef
    expense_ref: OpaqueRef
    debt_ref: OpaqueRef
    activity_ref: OpaqueRef
    gross_amount: Numeric20_4
    amount: Numeric20_4
    prepayment_amount: Numeric20_4
    prepayment_currency: CurrencyCode
    debt_amount: Numeric20_4
    debt_currency: CurrencyCode
    base_amount: BaseNumeric20_1 | None
    base_currency: CurrencyCode | None
    bill_fx_rate: FxRateNumeric20_10 | None
    bill_occurred_at: datetime | None
    financial_version: Annotated[StrictInt, Field(ge=0, le=MAX_FINANCIAL_VERSION)]
    query_evidence_ref: QueryEvidenceRef

    @field_validator("bill_occurred_at")
    @classmethod
    def optional_bill_occurred_at_aware(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _aware_datetime(value)

    @field_validator("gross_amount", "amount", "prepayment_amount", "debt_amount")
    @classmethod
    def positive_usage_amounts(cls, value: str) -> str:
        return _positive(value)

    @field_validator("base_amount")
    @classmethod
    def nonnegative_optional_base(cls, value: str | None) -> str | None:
        return None if value is None else _nonnegative(value)

    @field_validator("bill_fx_rate")
    @classmethod
    def positive_optional_rate(cls, value: str | None) -> str | None:
        if value is not None and _decimal(value) <= 0:
            raise ValueError("FX rate must be positive when present")
        return value

    @model_validator(mode="after")
    def base_pair_is_independent(self) -> "PrepaymentUsageFact":
        if (self.base_amount is None) != (self.base_currency is None):
            raise ValueError("base amount and currency must be jointly present or absent")
        return self


class PrepaymentReturnEventFact(P2WireModel):
    fact_kind: Literal["prepayment_return_event"]
    return_event_ref: OpaqueRef
    activity_ref: OpaqueRef
    amount: Numeric20_4
    currency: CurrencyCode
    occurred_at: datetime
    from_ref: OpaqueRef
    from_role: Literal["owner", "custodian"]
    to_ref: OpaqueRef
    to_role: Literal["owner", "custodian"]
    transfer_component_match: StrictBool
    financial_version: Annotated[StrictInt, Field(ge=0, le=MAX_FINANCIAL_VERSION)]
    query_evidence_ref: QueryEvidenceRef

    _positive_return = field_validator("amount")(_positive)
    _occurred_at_aware = field_validator("occurred_at")(_aware_datetime)

    @model_validator(mode="after")
    def return_direction_is_nontrivial(self) -> "PrepaymentReturnEventFact":
        if self.from_ref == self.to_ref:
            raise ValueError("return sender and recipient must differ")
        return self


P2Fact: TypeAlias = Annotated[
    Union[
        ActivityFact,
        ExpenseFact,
        DebtFact,
        RefundEventFact,
        PrepaymentAccountFact,
        PrepaymentUsageFact,
        PrepaymentReturnEventFact,
    ],
    Field(discriminator="fact_kind"),
]


class P2EntityDisplayLabel(P2WireModel):
    """Exact bounded source label; its receipt is an audit pointer, never authority."""

    entity_ref: OpaqueRef
    entity_kind: Literal["activity", "ledger_unit", "participant"]
    scope_ref: OpaqueRef
    display_name: ShortText
    source_kind: Literal["activities", "ledger_units", "participants"]
    observed_at: datetime
    scope_financial_version: Annotated[StrictInt, Field(ge=0, le=MAX_FINANCIAL_VERSION)]
    source_financial_version: Annotated[StrictInt, Field(ge=0, le=MAX_FINANCIAL_VERSION)] | None
    source_row_updated_at: datetime | None
    source_receipt_ref: OpaqueRef

    @model_validator(mode="after")
    def source_identity_and_time_are_consistent(self) -> "P2EntityDisplayLabel":
        if not self.display_name.strip():
            raise ValueError("source display label must not be blank")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("label observation time must be timezone-aware")
        if self.entity_kind == "activity":
            if self.source_kind != "activities" or self.source_financial_version is None or self.source_row_updated_at is not None:
                raise ValueError("Activity labels require their Activity financial version")
            if self.source_financial_version != self.scope_financial_version:
                raise ValueError("Activity label version must equal its scope fence")
        else:
            expected_source = "ledger_units" if self.entity_kind == "ledger_unit" else "participants"
            if self.source_kind != expected_source or self.source_financial_version is not None or self.source_row_updated_at is None:
                raise ValueError("Participant and unit labels require their source row timestamp")
            if self.source_row_updated_at.tzinfo is None or self.source_row_updated_at.utcoffset() is None:
                raise ValueError("label source row timestamp must be timezone-aware")
        return self


class P2CurrentActorBinding(P2WireModel):
    """Opaque Auth-user-to-current-Participant projection; not a permission."""

    actor_ref: OpaqueRef
    activity_ref: OpaqueRef
    participant_ref: OpaqueRef
    source_kind: Literal["participant_claims.current_auth_user"]
    observed_at: datetime
    scope_financial_version: Annotated[StrictInt, Field(ge=0, le=MAX_FINANCIAL_VERSION)]
    source_receipt_ref: OpaqueRef

    @model_validator(mode="after")
    def observed_time_is_aware(self) -> "P2CurrentActorBinding":
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("current actor observation time must be timezone-aware")
        return self

FactT = TypeVar("FactT", bound=BaseModel)


class ModelProjectionCompleteness(StrEnum):
    """Completeness of the candidate's model-visible projection, not source coverage."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    INCOMPLETE = "incomplete"


# Kept as a type alias for the already-reviewed backend candidate draft. The
# public enum values remain unchanged; source coverage is reported separately.
ReadCompleteness = ModelProjectionCompleteness


class P2FinancialVersion(P2WireModel):
    activity_ref: OpaqueRef
    financial_version: Annotated[StrictInt, Field(ge=0, le=MAX_FINANCIAL_VERSION)]


class P2PageSummary(P2WireModel):
    """Query-wide source coverage and model-projection status are independent."""

    pages_seen: Annotated[StrictInt, Field(ge=1, le=128)]
    has_more: StrictBool
    truncated: StrictBool
    source_query_complete: StrictBool
    model_projection_complete: StrictBool
    range_contiguous: StrictBool
    stable_total_verified: StrictBool
    source_version_fenced: StrictBool
    unique_items_verified: StrictBool
    expected_total: Annotated[StrictInt, Field(ge=0)] | None

    @model_validator(mode="after")
    def known_total_is_stable(self) -> "P2PageSummary":
        if self.stable_total_verified and self.expected_total is None:
            raise ValueError("stable total requires an expected total")
        if self.has_more and self.model_projection_complete:
            raise ValueError("a projection with another model page cannot be complete")
        return self


class P2PageProjection(P2WireModel, Generic[FactT]):
    """One model-visible page; `completeness` never describes source query coverage."""

    items: tuple[FactT, ...] = Field(max_length=16)
    completeness: ReadCompleteness
    has_more: StrictBool
    next_page_ref: OpaqueRef | None
    page_index: Annotated[StrictInt, Field(ge=0)]
    range_contiguous: StrictBool
    stable_total_verified: StrictBool
    source_version_fenced: StrictBool
    unique_items_verified: StrictBool
    expected_total: Annotated[StrictInt, Field(ge=0)] | None

    @model_validator(mode="after")
    def continuation_and_completeness_align(self) -> "P2PageProjection[FactT]":
        if self.has_more != (self.next_page_ref is not None):
            raise ValueError("has_more and next_page_ref must agree")
        if self.completeness == ReadCompleteness.COMPLETE and self.has_more:
            raise ValueError("a complete model projection cannot have a continuation")
        return self


class P2QueryEvidence(P2WireModel):
    profile_id: Literal[P2_V3_CANDIDATE_PROFILE_ID]
    versions: P2V3ProtocolVersions
    query_evidence_ref: QueryEvidenceRef
    query_ref: OpaqueRef
    result_ref: OpaqueRef
    operation: P2ReadOperationField
    criteria_ref: OpaqueRef
    criteria_digest: Digest
    normalized_criteria_digest: Digest
    backend_criteria_stage: Literal["scope_only"]
    source_kind: Literal[
        "activities", "expenses", "debts", "refund_events", "prepayment_accounts",
        "prepayment_usages", "prepayment_return_events",
    ]
    source_ref: OpaqueRef
    source_version: ShortText
    observed_at: datetime
    simulation: StrictBool
    returned_count: Annotated[StrictInt, Field(ge=0)]
    matched_count: Annotated[StrictInt, Field(ge=0)]
    source_total: Annotated[StrictInt, Field(ge=0)] | None = None
    matched_total: Annotated[StrictInt, Field(ge=0)] | None = None
    page_count: Annotated[StrictInt, Field(ge=1, le=128)]
    query_zero_classification: Literal["backend_zero", "post_filter_zero", "nonzero", "unknown_or_partial"]
    source_query_complete: StrictBool
    model_projection_complete: StrictBool
    matching_fact_refs: tuple[OpaqueRef, ...] = Field(max_length=256)
    financial_versions: tuple[P2FinancialVersion, ...] = Field(max_length=64)
    page: P2PageSummary
    query_digest: Digest
    body_digest: Digest
    projection_digest: Digest

    _observed_at_aware = field_validator("observed_at")(_aware_datetime)

    @model_validator(mode="after")
    def evidence_is_candidate_bound(self) -> "P2QueryEvidence":
        if self.versions != P2_V3_VERSIONS:
            raise ValueError("evidence version tuple does not match this candidate")
        if self.matched_count > self.returned_count:
            raise ValueError("matched_count cannot exceed returned_count")
        if self.source_total is not None and self.returned_count > self.source_total:
            raise ValueError("returned_count cannot exceed source_total")
        if self.matched_total is not None and self.matched_count > self.matched_total:
            raise ValueError("matched_count cannot exceed matched_total")
        if len(self.matching_fact_refs) != len(set(self.matching_fact_refs)):
            raise ValueError("matching_fact_refs must be unique")
        if len(self.financial_versions) != len({item.activity_ref for item in self.financial_versions}):
            raise ValueError("financial versions must have one entry per Activity")
        if self.page.pages_seen != self.page_count:
            raise ValueError("page summary count does not match the evidence page_count")
        if self.page.source_query_complete != self.source_query_complete:
            raise ValueError("page summary and evidence disagree on source completeness")
        if self.page.model_projection_complete != self.model_projection_complete:
            raise ValueError("page summary and evidence disagree on projection completeness")
        expected_source_kind = self.operation.value.removeprefix("read.")
        if self.source_kind != expected_source_kind:
            raise ValueError("source_kind does not match the selected operation")
        return self


class P2ReadBackendResult(P2WireModel):
    operation: P2ReadOperationField
    query_evidence: P2QueryEvidence
    page: P2PageProjection[P2Fact]

    @model_validator(mode="after")
    def operation_and_evidence_match(self) -> "P2ReadBackendResult":
        if self.operation != self.query_evidence.operation:
            raise ValueError("result operation must match its query evidence")
        expected_kind = {
            P2ReadOperation.ACTIVITIES: ActivityFact,
            P2ReadOperation.EXPENSES: ExpenseFact,
            P2ReadOperation.DEBTS: DebtFact,
            P2ReadOperation.REFUND_EVENTS: RefundEventFact,
            P2ReadOperation.PREPAYMENT_ACCOUNTS: PrepaymentAccountFact,
            P2ReadOperation.PREPAYMENT_USAGES: PrepaymentUsageFact,
            P2ReadOperation.PREPAYMENT_RETURN_EVENTS: PrepaymentReturnEventFact,
        }[self.operation]
        if any(not isinstance(item, expected_kind) for item in self.page.items):
            raise ValueError("page facts must match the selected operation")
        if any(item.query_evidence_ref != self.query_evidence.query_evidence_ref for item in self.page.items):
            raise ValueError("every fact must bind to the enclosing query evidence")
        if (
            self.page.has_more != self.query_evidence.page.has_more
            or self.page.range_contiguous != self.query_evidence.page.range_contiguous
            or self.page.source_version_fenced != self.query_evidence.page.source_version_fenced
            or self.page.unique_items_verified != self.query_evidence.page.unique_items_verified
        ):
            raise ValueError("page projection and evidence summary disagree")
        if (self.page.completeness == ModelProjectionCompleteness.COMPLETE) != self.query_evidence.model_projection_complete:
            raise ValueError("page projection completeness must match model_projection_complete evidence")
        return self


class P2SourceAuthorizationGrant(P2WireModel):
    """Source-authorized grant needed to begin a read; not a result receipt."""

    principal_ref: OpaqueRef
    owner_turn_ref: OpaqueRef
    generation: Annotated[StrictInt, Field(ge=1)]
    source_input_seq: Annotated[StrictInt, Field(ge=0)]
    input_digest: Digest
    operation: P2ReadOperationField
    scope: P2Scope | None
    criteria_digest: Digest
    expires_at: datetime
    grant_ref: OpaqueRef

    @model_validator(mode="after")
    def no_scope_grants_are_discovery_only(self) -> "P2SourceAuthorizationGrant":
        if self.scope is None and self.operation != P2ReadOperation.ACTIVITIES:
            raise ValueError("only Activity discovery grants may be unscoped")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("source authorization grant expiry must be timezone-aware")
        return self


class P2FreshQueryEvidenceRef(P2WireModel):
    """A post-read receipt reference required for factual answers."""

    query_evidence_ref: QueryEvidenceRef
    query_ref: OpaqueRef
    principal_ref: OpaqueRef
    owner_turn_ref: OpaqueRef
    generation: Annotated[StrictInt, Field(ge=1)]
    source_input_seq: Annotated[StrictInt, Field(ge=0)]
    input_digest: Digest
    operation: P2ReadOperationField
    scope_ref: OpaqueRef | None
    criteria_digest: Digest
    observed_at: datetime
    expires_at: datetime
    next_page_ref: OpaqueRef | None = None
    page_index: Annotated[StrictInt, Field(ge=0)] = 0

    _observed_at_aware = field_validator("observed_at")(_aware_datetime)
    _expires_at_aware = field_validator("expires_at")(_aware_datetime)

    @model_validator(mode="after")
    def no_scope_is_activity_discovery_only(self) -> "P2FreshQueryEvidenceRef":
        if self.scope_ref is None and self.operation != P2ReadOperation.ACTIVITIES:
            raise ValueError("only Activity discovery evidence may be unscoped")
        return self


class P2QueryAuthorizationBinding(P2WireModel):
    """Private per-query grant/receipt pair; its shape is not proof of Auth."""

    query_evidence_ref: QueryEvidenceRef
    receipt: P2FreshQueryEvidenceRef
    grant: P2SourceAuthorizationGrant

    @model_validator(mode="after")
    def receipt_and_grant_match(self) -> "P2QueryAuthorizationBinding":
        if self.query_evidence_ref != self.receipt.query_evidence_ref:
            raise ValueError("per-query binding must name its receipt qev")
        if (
            self.grant.principal_ref != self.receipt.principal_ref
            or self.grant.owner_turn_ref != self.receipt.owner_turn_ref
            or self.grant.generation != self.receipt.generation
            or self.grant.source_input_seq != self.receipt.source_input_seq
            or self.grant.input_digest != self.receipt.input_digest
            or self.grant.operation != self.receipt.operation
            or self.grant.criteria_digest != self.receipt.criteria_digest
        ):
            raise ValueError("per-query grant and receipt identities/criteria must match")
        grant_scope_ref = self.grant.scope.scope_ref if self.grant.scope is not None else None
        if grant_scope_ref != self.receipt.scope_ref:
            raise ValueError("per-query grant and receipt scopes must match")
        if self.grant.expires_at.tzinfo is None or self.grant.expires_at.utcoffset() is None:
            raise ValueError("per-query grant expiry must be timezone-aware")
        if self.receipt.expires_at.tzinfo is None or self.receipt.expires_at.utcoffset() is None:
            raise ValueError("per-query receipt expiry must be timezone-aware")
        if self.receipt.observed_at.tzinfo is None or self.receipt.observed_at.utcoffset() is None:
            raise ValueError("per-query receipt observation time must be timezone-aware")
        return self


class P2PendingClarification(P2WireModel):
    """Server-derived current-turn slot/reason binding; never model-authored authority."""

    slot: P2ClarificationSlot
    reason: P2ClarificationReason
    generation: Annotated[StrictInt, Field(ge=1)]
    source_input_seq: Annotated[StrictInt, Field(ge=0)]
    input_digest: Digest
    operation: P2ReadOperation | P2ProposalOperation | None = None

    @model_validator(mode="after")
    def slot_operation_and_reason_are_coherent(self) -> "P2PendingClarification":
        read_ops_by_slot = {
            "activity_scope": set(P2ReadOperation),
            "ledger_unit_scope": set(P2ReadOperation) - {P2ReadOperation.ACTIVITIES},
            "expense_target": {
                P2ReadOperation.EXPENSES, P2ReadOperation.DEBTS, P2ReadOperation.REFUND_EVENTS,
                P2ReadOperation.PREPAYMENT_USAGES,
            },
            "participant_target": {
                P2ReadOperation.EXPENSES, P2ReadOperation.DEBTS, P2ReadOperation.PREPAYMENT_USAGES,
            },
            "currency": {P2ReadOperation.DEBTS},
            "date_range": {
                P2ReadOperation.EXPENSES, P2ReadOperation.REFUND_EVENTS,
                P2ReadOperation.PREPAYMENT_RETURN_EVENTS,
            },
            "prepayment_account": {
                P2ReadOperation.PREPAYMENT_ACCOUNTS, P2ReadOperation.PREPAYMENT_USAGES,
                P2ReadOperation.PREPAYMENT_RETURN_EVENTS,
            },
            "return_target": {P2ReadOperation.PREPAYMENT_RETURN_EVENTS},
        }
        proposal_ops_by_slot = {
            "proposal_target": set(P2ProposalOperation),
            "proposal_title": set(P2ProposalOperation),
            "proposal_amount": {P2ProposalOperation.EXPENSE_CREATE, P2ProposalOperation.EXPENSE_UPDATE},
            "proposal_currency": {P2ProposalOperation.EXPENSE_CREATE, P2ProposalOperation.EXPENSE_UPDATE},
            "proposal_participant": {P2ProposalOperation.EXPENSE_CREATE, P2ProposalOperation.EXPENSE_UPDATE},
            "proposal_occurred_at": {P2ProposalOperation.EXPENSE_CREATE, P2ProposalOperation.EXPENSE_UPDATE},
        }
        if self.slot in proposal_ops_by_slot:
            if not isinstance(self.operation, P2ProposalOperation):
                raise ValueError("proposal clarification must bind a proposal operation")
            if self.operation not in proposal_ops_by_slot[self.slot]:
                raise ValueError("proposal clarification slot does not apply to its proposal operation")
        elif isinstance(self.operation, P2ProposalOperation):
            raise ValueError("read clarification slots cannot bind a proposal operation")
        elif isinstance(self.operation, P2ReadOperation) and self.operation not in read_ops_by_slot[self.slot]:
            raise ValueError("clarification slot does not apply to its read operation")
        elif self.operation is None and self.slot not in {"activity_scope", "ledger_unit_scope"}:
            raise ValueError("non-scope clarification requires its exact read operation")

        allowed_reasons = {
            "activity_scope": {"missing_required_scope", "multiple_scope_matches", "ambiguous_user_reference"},
            "ledger_unit_scope": {"missing_required_scope", "multiple_scope_matches", "ambiguous_user_reference"},
            "expense_target": {"multiple_scope_matches", "ambiguous_user_reference", "required_target_missing", "source_label_unavailable"},
            "participant_target": {"multiple_scope_matches", "ambiguous_user_reference", "required_target_missing", "source_label_unavailable"},
            "currency": {"ambiguous_user_reference", "required_target_missing"},
            "date_range": {"ambiguous_user_reference", "required_target_missing"},
            "prepayment_account": {"multiple_scope_matches", "ambiguous_user_reference", "required_target_missing", "source_label_unavailable"},
            "return_target": {"multiple_scope_matches", "ambiguous_user_reference", "required_target_missing", "source_label_unavailable"},
            "proposal_target": {"multiple_scope_matches", "ambiguous_user_reference", "required_target_missing", "source_label_unavailable"},
            "proposal_title": {"ambiguous_user_reference", "required_target_missing"},
            "proposal_amount": {"ambiguous_user_reference", "required_target_missing"},
            "proposal_currency": {"ambiguous_user_reference", "required_target_missing"},
            "proposal_participant": {"multiple_scope_matches", "ambiguous_user_reference", "required_target_missing", "source_label_unavailable"},
            "proposal_occurred_at": {"ambiguous_user_reference", "required_target_missing"},
        }
        if self.reason not in allowed_reasons[self.slot]:
            raise ValueError("clarification reason does not explain the selected slot")
        return self

class P2PendingClarificationProjection(P2WireModel):
    """Safe model-visible route hint; contains no private authority binding."""

    slot: P2ClarificationSlot
    reason: P2ClarificationReason
    operation: P2ReadOperation | P2ProposalOperation | None = None

    @model_validator(mode="after")
    def slot_operation_and_reason_are_coherent(self) -> "P2PendingClarificationProjection":
        # Reuse the private DTO's closed slot/reason/operation rules. Sentinel
        # bindings are local validation inputs only and are never serialized.
        P2PendingClarification.model_validate({
            "slot": self.slot,
            "reason": self.reason,
            "generation": 1,
            "source_input_seq": 0,
            "input_digest": "0" * 64,
            "operation": self.operation,
        })
        return self


_PROPOSAL_PENDING_SLOTS = frozenset({
    "proposal_target", "proposal_title", "proposal_amount", "proposal_currency",
    "proposal_participant", "proposal_occurred_at",
})
_SHARED_SCOPE_PENDING_SLOTS = frozenset({"activity_scope", "ledger_unit_scope"})


def _validate_pending_classification(
    classification: str,
    pending: tuple[P2PendingClarification | P2PendingClarificationProjection, ...],
) -> None:
    """Keep pending slot semantics aligned with the trusted intent branch."""
    for item in pending:
        is_proposal_slot = item.slot in _PROPOSAL_PENDING_SLOTS
        is_proposal_operation = isinstance(item.operation, P2ProposalOperation)
        is_read_operation = isinstance(item.operation, P2ReadOperation)
        if classification == "proposal_intent":
            if is_read_operation:
                raise ValueError("proposal intent cannot carry a read-operation clarification")
            if is_proposal_slot:
                if not is_proposal_operation:
                    raise ValueError("proposal clarification must bind a proposal operation")
            elif item.slot in _SHARED_SCOPE_PENDING_SLOTS:
                if item.operation is not None:
                    raise ValueError("proposal intent may use only operation-neutral shared scope clarification")
            else:
                raise ValueError("proposal intent cannot carry a read-detail clarification")
        elif classification in {"factual_business", "ambiguous"}:
            if is_proposal_slot or is_proposal_operation:
                raise ValueError("business read intent cannot carry proposal-specific clarification")
        elif classification == "non_business" and pending:
            raise ValueError("non-business context cannot carry business clarification slots")



class P2TrustedIntent(P2WireModel):
    authority: Literal["server"]
    classification: Literal["factual_business", "non_business", "ambiguous", "proposal_intent"]
    requires_authoritative_evidence: StrictBool
    source_input_seq: Annotated[StrictInt, Field(ge=0)]
    classifier_version: Annotated[StrictStr, StringConstraints(min_length=1, max_length=120)]


class P2ScopeAuthorization(P2WireModel):
    status: Literal["verified", "absent", "unresolved", "not_authorized"]
    scope: P2Scope | None
    authorization_receipt_ref: Annotated[
        StrictStr, StringConstraints(pattern=r"^auth_[A-Za-z0-9_-]{22,64}$", min_length=27, max_length=68)
    ] | None

    @model_validator(mode="after")
    def verified_scope_requires_receipt(self) -> "P2ScopeAuthorization":
        if self.status == "verified":
            if self.scope is None or self.authorization_receipt_ref is None:
                raise ValueError("verified scope requires scope and authorization receipt")
        elif self.scope is not None or self.authorization_receipt_ref is not None:
            raise ValueError("unverified scope status cannot carry authorized scope data")
        return self


class P2DecisionGuard(P2WireModel):
    source_free_business_answer_allowed: StrictBool
    allowed_decision_kinds: tuple[Literal["answer", "clarify", "read", "propose"], ...] = Field(
        min_length=1, max_length=4
    )
    allowed_read_operations: tuple[P2ReadOperationField, ...] = Field(max_length=7)
    fresh_receipt_refs: tuple[QueryEvidenceRef, ...] = Field(max_length=16)
    proposal_clarification_required: StrictBool | None = None
    allowed_proposal_operations: tuple[P2ProposalOperation, ...] = Field(default=(), max_length=3)

    @model_validator(mode="after")
    def allowlists_are_unique(self) -> "P2DecisionGuard":
        if len(self.allowed_decision_kinds) != len(set(self.allowed_decision_kinds)):
            raise ValueError("decision allowlist must be unique")
        if len(self.allowed_read_operations) != len(set(self.allowed_read_operations)):
            raise ValueError("read operation allowlist must be unique")
        if len(self.allowed_proposal_operations) != len(set(self.allowed_proposal_operations)):
            raise ValueError("proposal operation allowlist must be unique")
        return self


class P2RecentMessage(P2WireModel):
    seq: Annotated[StrictInt, Field(ge=0)]
    role: Literal["user", "assistant"]
    text: Annotated[StrictStr, StringConstraints(min_length=1, max_length=4000)]
    generation: Annotated[StrictInt, Field(ge=1)]


class P2ContinuationHint(P2WireModel):
    """Public opaque page handle bound to fresh query evidence, not a grant."""

    query_evidence_ref: QueryEvidenceRef
    query_ref: OpaqueRef
    next_page_ref: OpaqueRef


class P2ModelContext(P2WireModel):
    """Candidate model-context DTO matching the separately reviewed schema shape."""

    profile_id: Literal[P2_V3_CANDIDATE_PROFILE_ID]
    versions: P2V3ProtocolVersions
    context_version: Annotated[StrictStr, StringConstraints(min_length=1, max_length=240)]
    generation: Annotated[StrictInt, Field(ge=1)]
    input_text: Annotated[StrictStr, StringConstraints(min_length=1, max_length=4000)]
    trusted_intent: P2TrustedIntent
    scope_authorization: P2ScopeAuthorization
    guard: P2DecisionGuard
    pending_clarifications: tuple[P2PendingClarificationProjection, ...] = Field(max_length=16)
    query_evidence: tuple[P2QueryEvidence, ...] = Field(max_length=16)
    continuations: tuple[P2ContinuationHint, ...] = Field(default=(), max_length=16)
    facts: tuple[P2Fact, ...] = Field(max_length=256)
    recent_messages: tuple[P2RecentMessage, ...] = Field(max_length=32)
    current_actor: P2CurrentActorBinding | None
    source_labels: tuple[P2EntityDisplayLabel, ...] = Field(max_length=128)

    @model_validator(mode="after")
    def model_context_guard_is_fail_closed(self) -> "P2ModelContext":
        if self.versions != P2_V3_VERSIONS:
            raise ValueError("model context version tuple does not match this candidate")
        scope_status = self.scope_authorization.status
        labels = self.source_labels
        label_refs = tuple(label.entity_ref for label in labels)
        if len(label_refs) != len(set(label_refs)):
            raise ValueError("source labels must be unique per opaque entity ref")
        label_versions = {label.scope_financial_version for label in labels}
        if scope_status == "verified" and len(label_versions) > 1:
            raise ValueError("source labels must share one Activity financial-version fence")
        if scope_status == "verified":
            scope = self.scope_authorization.scope
            if scope is None:
                raise ValueError("verified context requires its scoped DTO")
            for label in labels:
                if label.scope_ref != scope.scope_ref:
                    raise ValueError("source labels must bind the current authorized scope")
                if label.entity_kind == "activity" and label.entity_ref != scope.activity_ref:
                    raise ValueError("Activity label must bind the scoped parent Activity")
                if (
                    label.entity_kind == "ledger_unit"
                    and scope.scope_kind == "ledger_unit"
                    and label.entity_ref != scope.ledger_unit_ref
                ):
                    raise ValueError("ledger-unit label must bind the selected child scope")
            if self.current_actor is not None:
                actor = self.current_actor
                if actor.activity_ref != scope.activity_ref:
                    raise ValueError("current actor must bind the scoped parent Activity")
                if label_versions and actor.scope_financial_version not in label_versions:
                    raise ValueError("current actor and labels must share the current Activity version")
                matching_participant_labels = [
                    label for label in labels
                    if label.entity_kind == "participant" and label.entity_ref == actor.participant_ref
                ]
                if len(matching_participant_labels) != 1:
                    raise ValueError("current actor must have one matching Participant label")
                if matching_participant_labels[0].scope_ref != scope.scope_ref:
                    raise ValueError("current actor Participant label must bind the current scope")
                if matching_participant_labels[0].scope_financial_version != actor.scope_financial_version:
                    raise ValueError("current actor and Participant label must share the Activity version")
        elif scope_status == "absent":
            if self.current_actor is not None:
                raise ValueError("no-scope discovery cannot claim a current Participant actor")
            if any(
                label.entity_kind != "activity" or label.scope_ref != label.entity_ref
                for label in labels
            ):
                raise ValueError("no-scope discovery may expose only self-scoped Activity labels")
            if any(item.operation != P2ReadOperation.ACTIVITIES for item in self.query_evidence):
                raise ValueError("no-scope discovery cannot carry financial query evidence")
            if any(not isinstance(fact, ActivityFact) for fact in self.facts):
                raise ValueError("no-scope discovery cannot carry financial fact DTOs")
        else:
            if self.current_actor is not None or labels:
                raise ValueError("unresolved or unauthorized scope cannot expose source metadata")
            if self.query_evidence or self.continuations or self.facts or self.guard.fresh_receipt_refs:
                raise ValueError("unresolved or unauthorized scope cannot carry prior source facts")
        classification = self.trusted_intent.classification
        guard = self.guard
        kinds = set(guard.allowed_decision_kinds)
        reads = set(guard.allowed_read_operations)
        proposals = set(guard.allowed_proposal_operations)
        pending_slots = tuple(item.slot for item in self.pending_clarifications)
        if len(pending_slots) != len(set(pending_slots)):
            raise ValueError("public pending clarification slots must be unique")
        _validate_pending_classification(classification, self.pending_clarifications)
        if self.pending_clarifications:
            if kinds != {"clarify"}:
                raise ValueError("pending clarification must be the only allowed decision kind")
        elif "clarify" in kinds:
            raise ValueError("clarify cannot be advertised without a current pending slot")
        if "read" not in kinds and reads:
            raise ValueError("read operations require read to be allowlisted")
        if "propose" not in kinds and proposals:
            raise ValueError("proposal operations require propose to be allowlisted")

        if classification == "factual_business":
            if not self.trusted_intent.requires_authoritative_evidence or guard.source_free_business_answer_allowed:
                raise ValueError("factual business context must require authoritative evidence")
            if "propose" in kinds:
                raise ValueError("factual business context cannot enable proposals")
        elif classification == "ambiguous":
            if not self.trusted_intent.requires_authoritative_evidence or guard.source_free_business_answer_allowed:
                raise ValueError("ambiguous context must default-deny source-free answers")
            if "answer" in kinds or "propose" in kinds:
                raise ValueError("ambiguous context may only clarify or request a read")
        elif classification == "proposal_intent":
            if self.trusted_intent.requires_authoritative_evidence or guard.source_free_business_answer_allowed:
                raise ValueError("proposal intent cannot authorize factual answers")
            if guard.proposal_clarification_required is None:
                raise ValueError("proposal context must state whether clarification is required")
            if "read" in kinds or "answer" in kinds:
                raise ValueError("proposal intent cannot enable reads or answers")
            if self.pending_clarifications:
                if not guard.proposal_clarification_required or proposals:
                    raise ValueError("pending proposal details require clarification only")
            else:
                if guard.proposal_clarification_required or not proposals or kinds != {"propose"}:
                    raise ValueError("resolved proposal context requires recognize-only proposal")
        else:
            if self.pending_clarifications:
                raise ValueError("non-business context cannot carry business clarification slots")
            if self.trusted_intent.requires_authoritative_evidence:
                raise ValueError("non-business context is not a business-fact query")
            if guard.source_free_business_answer_allowed and "answer" not in kinds:
                raise ValueError("source-free general answer must be allowlisted")
            if "read" in kinds or reads or "propose" in kinds or proposals:
                raise ValueError("non-business context cannot enable business operations")

        if self.scope_authorization.status != "verified":
            if self.scope_authorization.status in {"absent", "unresolved", "not_authorized"}:
                if reads - {P2ReadOperation.ACTIVITIES}:
                    raise ValueError("unverified scope may only allow Activity discovery")
                if self.scope_authorization.status != "absent" and "answer" in kinds:
                    raise ValueError("unresolved or unauthorized scope cannot allow an answer")
        evidence_ref_sequence = tuple(item.query_evidence_ref for item in self.query_evidence)
        if len(evidence_ref_sequence) != len(set(evidence_ref_sequence)):
            raise ValueError("query evidence refs must be unique")
        evidence_refs = set(evidence_ref_sequence)
        if not set(guard.fresh_receipt_refs).issubset(evidence_refs):
            raise ValueError("fresh receipt refs must bind to query evidence in this context")
        evidence_by_ref = {item.query_evidence_ref: item for item in self.query_evidence}

        # Compare only numeric Activity fences that the supplied typed DTOs
        # actually assert. ActivityFact intentionally has no financial_version
        # field; its context_version is a different source value and is never
        # interpreted as a numeric fence here.
        activity_versions: dict[OpaqueRef, tuple[int, str]] = {}

        def bind_activity_version(activity_ref: OpaqueRef, version: int, source: str) -> None:
            previous = activity_versions.get(activity_ref)
            if previous is not None and previous[0] != version:
                raise ValueError(
                    f"Activity financial-version fence conflicts for {activity_ref}: "
                    f"{previous[1]} says {previous[0]}, {source} says {version}"
                )
            activity_versions[activity_ref] = (version, source)

        if scope_status == "verified":
            assert self.scope_authorization.scope is not None
            parent_activity_ref = self.scope_authorization.scope.activity_ref
            for label in labels:
                bind_activity_version(parent_activity_ref, label.scope_financial_version, "source label")
            if self.current_actor is not None:
                bind_activity_version(
                    self.current_actor.activity_ref,
                    self.current_actor.scope_financial_version,
                    "current actor",
                )
        elif scope_status == "absent":
            for label in labels:
                # No-scope discovery labels are already constrained to Activity
                # rows whose scope_ref equals entity_ref.
                bind_activity_version(label.entity_ref, label.scope_financial_version, "Activity label")

        query_fences_by_ref: dict[QueryEvidenceRef, dict[OpaqueRef, int]] = {}
        for evidence in self.query_evidence:
            fences = {
                item.activity_ref: item.financial_version
                for item in evidence.financial_versions
            }
            query_fences_by_ref[evidence.query_evidence_ref] = fences
            for activity_ref, version in fences.items():
                bind_activity_version(activity_ref, version, "query evidence")
            if scope_status == "verified" and evidence.operation != P2ReadOperation.ACTIVITIES:
                assert self.scope_authorization.scope is not None
                parent_activity_ref = self.scope_authorization.scope.activity_ref
                if set(fences) != {parent_activity_ref}:
                    raise ValueError(
                        "financial query evidence must carry exactly the current parent Activity financial-version fence"
                    )

        continuation_evidence_refs = tuple(item.query_evidence_ref for item in self.continuations)
        continuation_query_refs = tuple(item.query_ref for item in self.continuations)
        continuation_page_refs = tuple(item.next_page_ref for item in self.continuations)
        if (
            len(continuation_evidence_refs) != len(set(continuation_evidence_refs))
            or len(continuation_query_refs) != len(set(continuation_query_refs))
            or len(continuation_page_refs) != len(set(continuation_page_refs))
        ):
            raise ValueError("continuation hint evidence, query, and page refs must each be unique")
        if self.continuations and "read" not in kinds:
            raise ValueError("continuation hints require read to be allowlisted")
        hints_by_evidence = {item.query_evidence_ref: item for item in self.continuations}
        for hint in self.continuations:
            evidence = evidence_by_ref.get(hint.query_evidence_ref)
            if hint.query_evidence_ref not in guard.fresh_receipt_refs:
                raise ValueError("continuation hint must bind to a fresh receipt ref")
            if evidence is None or evidence.query_ref != hint.query_ref:
                raise ValueError("continuation hint query ref must match its query evidence")
            if not evidence.page.has_more:
                raise ValueError("continuation hint requires query evidence with another page")
        if "read" in kinds:
            for receipt_ref in guard.fresh_receipt_refs:
                evidence = evidence_by_ref[receipt_ref]
                if evidence.page.has_more and receipt_ref not in hints_by_evidence:
                    raise ValueError("fresh query evidence with another page requires a continuation hint")
        fact_operation = {
            ActivityFact: P2ReadOperation.ACTIVITIES,
            ExpenseFact: P2ReadOperation.EXPENSES,
            DebtFact: P2ReadOperation.DEBTS,
            RefundEventFact: P2ReadOperation.REFUND_EVENTS,
            PrepaymentAccountFact: P2ReadOperation.PREPAYMENT_ACCOUNTS,
            PrepaymentUsageFact: P2ReadOperation.PREPAYMENT_USAGES,
            PrepaymentReturnEventFact: P2ReadOperation.PREPAYMENT_RETURN_EVENTS,
        }
        fact_ref_field = {
            ActivityFact: "activity_ref",
            ExpenseFact: "expense_ref",
            DebtFact: "debt_ref",
            RefundEventFact: "refund_ref",
            PrepaymentAccountFact: "account_ref",
            PrepaymentUsageFact: "usage_ref",
            PrepaymentReturnEventFact: "return_event_ref",
        }
        for fact in self.facts:
            evidence = evidence_by_ref.get(fact.query_evidence_ref)
            fact_type = type(fact)
            if evidence is None or evidence.operation != fact_operation[fact_type]:
                raise ValueError("every fact must cite matching operation evidence in this context")
            scope = self.scope_authorization.scope
            if scope is not None:
                if isinstance(fact, ActivityFact) and fact.activity_ref != scope.activity_ref:
                    raise ValueError("Activity fact must match the current scoped parent")
                if isinstance(fact, (ExpenseFact, RefundEventFact)) and fact.scope_ref != scope.scope_ref:
                    raise ValueError("fact scope ref must match the current authorized scope")
                if isinstance(fact, DebtFact):
                    if fact.scope_ref != scope.scope_ref or fact.activity_ref != scope.activity_ref:
                        raise ValueError("debt fact must match the current authorized scope")
                    if scope.scope_kind == "ledger_unit" and fact.ledger_unit_ref != scope.ledger_unit_ref:
                        raise ValueError("debt fact must match the selected child unit")
                if isinstance(fact, (PrepaymentAccountFact, PrepaymentUsageFact, PrepaymentReturnEventFact)):
                    if fact.activity_ref != scope.activity_ref:
                        raise ValueError("prepayment fact must match the scoped parent Activity")
            fact_ref = getattr(fact, fact_ref_field[fact_type])
            if fact_ref not in evidence.matching_fact_refs:
                raise ValueError("fact is absent from its query evidence matching refs")
            if not isinstance(fact, ActivityFact):
                if hasattr(fact, "activity_ref"):
                    fact_activity_ref = fact.activity_ref
                elif scope is not None:
                    # Expense/refund DTOs carry the authorized scope ref. For a
                    # child-scope query, the trusted scope DTO supplies the
                    # parent Activity; no Activity id is inferred from text.
                    fact_activity_ref = scope.activity_ref
                else:
                    raise ValueError("financial fact has no bound parent Activity")
                query_version = query_fences_by_ref[fact.query_evidence_ref].get(fact_activity_ref)
                if query_version is None:
                    raise ValueError("financial query evidence is missing the fact's Activity financial-version fence")
                if fact.financial_version != query_version:
                    raise ValueError("fact financial_version does not match its query evidence Activity fence")
                bind_activity_version(fact_activity_ref, fact.financial_version, "financial fact")
        return self


_MODEL_CONTEXT_ADAPTER = TypeAdapter(P2ModelContext)


def parse_p2_model_context(payload: Any) -> P2ModelContext:
    """Strictly parse/revalidate the public v3 context; this does not authorize sources."""
    if isinstance(payload, P2ModelContext):
        raw: str | bytes = payload.model_dump_json()
    elif type(payload) in {str, bytes, bytearray}:
        raw = bytes(payload) if type(payload) is bytearray else payload
    elif isinstance(payload, Mapping):
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    else:
        raise ValueError("P2 v3 context must be JSON or a typed candidate DTO")
    try:
        tree = json.loads(raw, object_pairs_hook=_reject_duplicate_pairs, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("invalid P2 v3 context JSON") from exc
    if not isinstance(tree, dict):
        raise ValueError("P2 v3 context JSON must be an object")

    def require_finite_numbers(value: Any) -> None:
        if type(value) is float and not math.isfinite(value):
            raise ValueError("non-finite JSON numbers are not allowed")
        if isinstance(value, list):
            for item in value:
                require_finite_numbers(item)
        elif isinstance(value, dict):
            for item in value.values():
                require_finite_numbers(item)

    require_finite_numbers(tree)
    return _MODEL_CONTEXT_ADAPTER.validate_json(raw, strict=True)


class P2IntentContext(P2WireModel):
    """Internal server guard snapshot; this is not the serialized model-context DTO."""

    profile_id: Literal[P2_V3_CANDIDATE_PROFILE_ID]
    versions: P2V3ProtocolVersions
    classification: Literal["non_business", "proposal_intent", "factual_business", "ambiguous"] = "ambiguous"
    principal_ref: OpaqueRef
    owner_turn_ref: OpaqueRef
    generation: Annotated[StrictInt, Field(ge=1)]
    source_input_seq: Annotated[StrictInt, Field(ge=0)]
    input_digest: Digest
    scope_status: Literal["absent", "unresolved", "not_authorized", "verified"] = "absent"
    scope: P2Scope | None = None
    source_authorization_grant: P2SourceAuthorizationGrant | None = None
    fresh_receipt_refs: tuple[P2FreshQueryEvidenceRef, ...] = ()
    query_authorization_bindings: tuple[P2QueryAuthorizationBinding, ...] = Field(default=(), max_length=16)
    clarification_required: StrictBool = False
    pending_clarifications: tuple[P2PendingClarification, ...] = Field(default=(), max_length=16)
    proposal_target_resolved: StrictBool = False
    # This must be populated from server-side classifier provenance. Pydantic
    # validates shape only and cannot authenticate that provenance.
    classifier_source: Literal["server_policy"] | None = None
    classifier_version: ShortText | None = None

    @model_validator(mode="after")
    def trusted_branch_guard(self) -> "P2IntentContext":
        if self.versions != P2_V3_VERSIONS:
            raise ValueError("trusted intent version tuple does not match this candidate")
        pending_slots = tuple(item.slot for item in self.pending_clarifications)
        if self.clarification_required != bool(self.pending_clarifications):
            raise ValueError("clarification flag must match the server-bound pending slots")
        if len(pending_slots) != len(set(pending_slots)):
            raise ValueError("pending clarification slots must be unique")
        _validate_pending_classification(self.classification, self.pending_clarifications)
        for pending in self.pending_clarifications:
            if (
                pending.generation != self.generation
                or pending.source_input_seq != self.source_input_seq
                or pending.input_digest != self.input_digest
            ):
                raise ValueError("pending clarification must bind the current input and generation")
        if self.classification == "non_business" and self.pending_clarifications:
            raise ValueError("non-business input cannot carry a business clarification slot")
        current_proposal_slots = set(pending_slots) & _PROPOSAL_PENDING_SLOTS
        if self.classification == "proposal_intent":
            if not self.proposal_target_resolved:
                if not self.clarification_required or "proposal_target" not in current_proposal_slots:
                    raise ValueError("unresolved proposal intent requires a bound proposal_target clarification")
            elif "proposal_target" in current_proposal_slots:
                raise ValueError("resolved proposal target cannot remain pending")
        elif current_proposal_slots:
            raise ValueError("proposal-specific slots require server-classified proposal intent")

        if self.scope_status == "verified":
            if self.scope is None:
                raise ValueError("verified scope requires its scope DTO")
            if self.source_authorization_grant is None:
                if self.fresh_receipt_refs or self.query_authorization_bindings:
                    raise ValueError("pre-read metadata context cannot carry query receipts or authorization bindings")
            elif self.source_authorization_grant.scope != self.scope:
                raise ValueError("authorized grant must bind the verified scope")
        elif self.scope is not None:
            raise ValueError("unverified context cannot carry a verified scope")
        elif self.source_authorization_grant is not None:
            grant = self.source_authorization_grant
            if (
                self.scope_status != "absent"
                or grant.operation != P2ReadOperation.ACTIVITIES
                or grant.scope is not None
            ):
                raise ValueError("only an explicit no-scope Activity discovery grant is allowed")

        if self.source_authorization_grant is not None:
            grant = self.source_authorization_grant
            if (
                grant.principal_ref != self.principal_ref
                or grant.owner_turn_ref != self.owner_turn_ref
                or grant.generation != self.generation
                or grant.source_input_seq != self.source_input_seq
                or grant.input_digest != self.input_digest
            ):
                raise ValueError("source grant is not bound to the current owner Turn/input generation")
        for receipt in self.fresh_receipt_refs:
            if (
                receipt.principal_ref != self.principal_ref
                or receipt.owner_turn_ref != self.owner_turn_ref
                or receipt.generation != self.generation
                or receipt.source_input_seq != self.source_input_seq
                or receipt.input_digest != self.input_digest
            ):
                raise ValueError("fresh receipt is not bound to the current owner Turn/input generation")
        receipt_by_qev = {receipt.query_evidence_ref: receipt for receipt in self.fresh_receipt_refs}
        if len(receipt_by_qev) != len(self.fresh_receipt_refs):
            raise ValueError("fresh query evidence refs must be unique")
        binding_qevs = [binding.query_evidence_ref for binding in self.query_authorization_bindings]
        if len(binding_qevs) != len(set(binding_qevs)):
            raise ValueError("per-query authorization bindings must be unique")
        for binding in self.query_authorization_bindings:
            if receipt_by_qev.get(binding.query_evidence_ref) != binding.receipt:
                raise ValueError("per-query binding must match a current context receipt")
            for bound in (binding.receipt,):
                if (
                    bound.principal_ref != self.principal_ref
                    or bound.owner_turn_ref != self.owner_turn_ref
                    or bound.generation != self.generation
                    or bound.source_input_seq != self.source_input_seq
                    or bound.input_digest != self.input_digest
                ):
                    raise ValueError("per-query binding is not bound to this owner Turn/input generation")
            grant = binding.grant
            if (
                grant.principal_ref != self.principal_ref
                or grant.owner_turn_ref != self.owner_turn_ref
                or grant.generation != self.generation
                or grant.source_input_seq != self.source_input_seq
                or grant.input_digest != self.input_digest
            ):
                raise ValueError("per-query grant is not bound to this owner Turn/input generation")
            if self.scope_status == "verified":
                if self.scope is None or grant.scope != self.scope:
                    raise ValueError("per-query grant must bind this current verified scope")
            elif not (
                self.scope_status == "absent"
                and self.scope is None
                and grant.scope is None
                and grant.operation == P2ReadOperation.ACTIVITIES
            ):
                raise ValueError("only no-scope Activity discovery may be unscoped")
        if self.query_authorization_bindings and not any(
            self.source_authorization_grant == binding.grant for binding in self.query_authorization_bindings
        ):
            raise ValueError("primary source grant must be one of the bound per-query grants")

        if self.classification in {"factual_business", "proposal_intent", "non_business"}:
            if self.classifier_source != "server_policy" or self.classifier_version is None:
                raise ValueError("classified intent requires server classifier provenance")

        # Ambiguous/default-unknown is fail-closed for facts even if stale or
        # fabricated evidence refs happen to be present.
        if self.classification == "ambiguous":
            return self

        return self


def _pending_projection_key(item: P2PendingClarification | P2PendingClarificationProjection) -> tuple[str, str, str | None]:
    operation = item.operation.value if isinstance(item.operation, StrEnum) else item.operation
    return item.slot, item.reason, operation


def validate_p2_clarification_projection(
    model_context: P2ModelContext,
    intent_context: P2IntentContext,
) -> P2ModelContext:
    """Strictly revalidate and pair public routing hints with private current intent.

    Returns only the revalidated public DTO. This is a consistency guard, not
    source authorization; callers must retain and separately enforce the private
    intent context when parsing model decisions.
    """
    if not isinstance(model_context, P2ModelContext) or not isinstance(intent_context, P2IntentContext):
        raise ValueError("typed public model context and private intent context are required")
    try:
        public = parse_p2_model_context(model_context)
        private = P2IntentContext.model_validate_json(intent_context.model_dump_json(), strict=True)
    except Exception as exc:
        raise ValueError("public/private clarification contexts failed strict revalidation") from exc

    if public.profile_id != private.profile_id or public.versions != private.versions or public.versions != P2_V3_VERSIONS:
        raise ValueError("public/private clarification contexts must use one exact v3 candidate tuple")
    if public.generation != private.generation:
        raise ValueError("public model-context generation does not match private intent")
    if public.trusted_intent.source_input_seq != private.source_input_seq:
        raise ValueError("public trusted-intent input sequence does not match private intent")
    if public.trusted_intent.classification != private.classification:
        raise ValueError("public trusted intent classification does not match private intent")
    if (
        private.classifier_version is not None
        and public.trusted_intent.classifier_version != private.classifier_version
    ):
        raise ValueError("public trusted-intent classifier version does not match private provenance")
    expected_evidence_requirement = private.classification in {"factual_business", "ambiguous"}
    if public.trusted_intent.requires_authoritative_evidence is not expected_evidence_requirement:
        raise ValueError("public trusted-intent evidence requirement does not match private classification")
    if public.scope_authorization.status != private.scope_status or public.scope_authorization.scope != private.scope:
        raise ValueError("public scope projection does not match the private current scope binding")
    _validate_pending_classification(public.trusted_intent.classification, public.pending_clarifications)
    _validate_pending_classification(private.classification, private.pending_clarifications)
    if private.classification == "proposal_intent":
        if public.guard.proposal_clarification_required is not private.clarification_required:
            raise ValueError("public proposal clarification flag does not match private pending state")
    elif public.guard.proposal_clarification_required is not None:
        raise ValueError("proposal clarification flag is only valid for proposal intent")

    public_pending = tuple(sorted(_pending_projection_key(item) for item in public.pending_clarifications))
    private_pending = tuple(sorted(_pending_projection_key(item) for item in private.pending_clarifications))
    if public_pending != private_pending:
        raise ValueError("public pending clarification projection does not match private current slots")
    return public


class P2AnswerDecision(P2WireModel):
    kind: Literal["answer"]
    basis: Literal["fresh_read_receipts", "non_business_general"]
    text: LongText
    citations: tuple[QueryEvidenceRef, ...] = Field(max_length=16)

    @model_validator(mode="after")
    def basis_and_citations_match(self) -> "P2AnswerDecision":
        if self.basis == "fresh_read_receipts" and not self.citations:
            raise ValueError("fresh-read answers require citations")
        if self.basis == "non_business_general" and self.citations:
            raise ValueError("source-free answers cannot include citations")
        return self


class P2ClarifyDecision(P2WireModel):
    kind: Literal["clarify"]
    prompt: Annotated[StrictStr, StringConstraints(min_length=1, max_length=1200)]
    missing_slots: tuple[P2ClarificationSlot, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def missing_slots_are_unique(self) -> "P2ClarifyDecision":
        if len(self.missing_slots) != len(set(self.missing_slots)):
            raise ValueError("clarification slots must be unique")
        return self


class P2ProposalRecognition(P2WireModel):
    kind: Literal["propose"]
    operation: P2ProposalOperation
    recognized_intent_text: ShortText


P2Decision: TypeAlias = Union[
    P2AnswerDecision, P2ClarifyDecision, P2ReadQueryRequest, P2ReadContinueRequest, P2ProposalRecognition
]


def parse_p2_decision(payload: Any, context: P2IntentContext) -> P2Decision:
    """Parse and guard one model decision using separately supplied trusted context."""
    decision = parse_p2_decision_shape(payload)
    if not isinstance(context, P2IntentContext):
        raise ValueError("trusted P2 intent context is required")
    try:
        # Revalidate to catch model_copy/model_construct updates at the trust boundary.
        context = P2IntentContext.model_validate_json(context.model_dump_json(), strict=True)
    except Exception as exc:
        raise ValueError("trusted P2 intent context failed revalidation") from exc
    if context.clarification_required and not isinstance(decision, P2ClarifyDecision):
        raise ValueError("clarification-required context permits clarification only")
    if isinstance(decision, P2AnswerDecision):
        if context.classification == "non_business":
            if decision.basis != "non_business_general" or decision.citations:
                raise ValueError("non-business answers must be source-free and citation-free")
        else:
            if context.classification != "factual_business":
                raise ValueError("factual answer requires explicit server-classified business intent")
            if context.source_authorization_grant is None or not context.fresh_receipt_refs:
                raise ValueError("factual answer requires a source grant and fresh query evidence")
            if decision.basis != "fresh_read_receipts" or not decision.citations:
                raise ValueError("factual answer must cite fresh query evidence")
            if len(decision.citations) != len(set(decision.citations)):
                raise ValueError("answer citations must be unique")
            permitted = {item.query_evidence_ref for item in context.fresh_receipt_refs}
            if not set(decision.citations).issubset(permitted):
                raise ValueError("answer citation is not bound to a fresh receipt")
            now = datetime.now(timezone.utc)
            grant = context.source_authorization_grant
            bindings_by_qev = {
                binding.query_evidence_ref: binding for binding in context.query_authorization_bindings
            }
            if not set(decision.citations).issubset(bindings_by_qev):
                raise ValueError("answer citation lacks a per-query authorization binding")
            if context.scope_status == "verified":
                if context.scope is None or grant.scope != context.scope:
                    raise ValueError("factual answer requires a matching verified scope")
                eligible_scope_ref = context.scope.scope_ref
            elif (
                context.scope_status == "absent"
                and grant.operation == P2ReadOperation.ACTIVITIES
                and grant.scope is None
            ):
                eligible_scope_ref = None
            else:
                raise ValueError("factual answer requires verified scope or authorized Activity discovery")
            receipts_by_qev = {receipt.query_evidence_ref: receipt for receipt in context.fresh_receipt_refs}
            if not any(
                grant == binding.grant for binding in context.query_authorization_bindings
            ):
                raise ValueError("primary source grant must be represented in per-query bindings")
            for cited_qev in decision.citations:
                receipt = receipts_by_qev[cited_qev]
                query_grant = bindings_by_qev[cited_qev].grant
                if receipt.expires_at.tzinfo is None or receipt.observed_at.tzinfo is None:
                    raise ValueError("fresh query evidence timestamps must be timezone-aware")
                if receipt.expires_at <= now or receipt.observed_at > now:
                    raise ValueError("answer receipt is expired or from the future")
                if receipt.scope_ref != eligible_scope_ref:
                    raise ValueError("answer receipt scope does not match the authorized scope")
                if eligible_scope_ref is None and receipt.operation != P2ReadOperation.ACTIVITIES:
                    raise ValueError("no-scope factual answers may cite only Activity discovery")
                if query_grant.expires_at.tzinfo is None or query_grant.expires_at <= now:
                    raise ValueError("answer source grant is expired or lacks timezone")
                if receipt.operation != query_grant.operation or receipt.criteria_digest != query_grant.criteria_digest:
                    raise ValueError("answer receipt does not match its source-authorized operation and criteria")
    elif isinstance(decision, (P2ReadQueryRequest, P2ReadContinueRequest)):
        if context.classification not in {"factual_business", "ambiguous"}:
            raise ValueError("read is unavailable for non-business or proposal-only intent")
        if context.clarification_required:
            raise ValueError("clarification-required context cannot start a read")
        if isinstance(decision, P2ReadQueryRequest):
            grant = context.source_authorization_grant
            if grant is None or grant.operation != decision.operation:
                raise ValueError("first read requires a matching fresh source-authorized grant")
            if grant.expires_at.tzinfo is None or grant.expires_at <= datetime.now(timezone.utc):
                raise ValueError("source authorization grant is expired or lacks timezone")
            if grant.criteria_digest != p2_criteria_digest(decision.criteria):
                raise ValueError("source authorization grant does not bind these criteria")
            if decision.scope is None:
                if (
                    decision.operation != P2ReadOperation.ACTIVITIES
                    or grant.scope is not None
                    or context.scope_status != "absent"
                ):
                    raise ValueError("only Activity discovery may use a no-scope grant")
            elif (
                context.scope_status != "verified"
                or context.scope != decision.scope
                or grant.scope != decision.scope
            ):
                raise ValueError("scoped read requires a matching verified scope and grant")
        else:
            grant = context.source_authorization_grant
            if grant is None:
                raise ValueError("continuation requires the source grant for its original query")
            now = datetime.now(timezone.utc)
            if grant.expires_at.tzinfo is None or grant.expires_at <= now:
                raise ValueError("continuation source grant is expired or lacks timezone")
            if context.scope_status == "verified":
                expected_scope_ref = context.scope.scope_ref if context.scope is not None else None
            elif (
                context.scope_status == "absent"
                and grant.operation == P2ReadOperation.ACTIVITIES
                and grant.scope is None
            ):
                expected_scope_ref = None
            else:
                raise ValueError("continuation requires a verified scope or authorized Activity discovery")
            if not any(
                receipt.query_ref == decision.query_ref
                and receipt.next_page_ref == decision.next_page_ref
                and receipt.operation == grant.operation
                and receipt.criteria_digest == grant.criteria_digest
                and receipt.scope_ref == expected_scope_ref
                and receipt.expires_at.tzinfo is not None
                and receipt.expires_at > now
                for receipt in context.fresh_receipt_refs
            ):
                raise ValueError("continuation must bind to a prior query receipt")
    elif isinstance(decision, P2ProposalRecognition):
        if context.classification != "proposal_intent":
            raise ValueError("proposal recognition requires server-classified proposal intent")
        if context.clarification_required or not context.proposal_target_resolved:
            raise ValueError("unresolved proposal targets must be clarified")
    elif isinstance(decision, P2ClarifyDecision):
        if context.classification == "non_business":
            raise ValueError("non-business branch does not emit business clarification")
        pending_slots = {item.slot for item in context.pending_clarifications}
        if not pending_slots:
            raise ValueError("clarification requires server-bound pending slots for this input")
        if not set(decision.missing_slots).issubset(pending_slots):
            raise ValueError("clarification may name only currently pending server slots")
    return decision


_DECISION_ADAPTER = TypeAdapter(P2Decision)
_KNOWN_DECISION_TYPES = (
    P2AnswerDecision,
    P2ClarifyDecision,
    P2ReadQueryRequest,
    P2ReadContinueRequest,
    P2ProposalRecognition,
)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def parse_p2_decision_shape(payload: Any) -> P2Decision:
    """Strictly parse candidate JSON shape only; never authorizes a source read or answer."""
    if isinstance(payload, _KNOWN_DECISION_TYPES):
        raw: str | bytes = payload.model_dump_json()
    elif type(payload) in {str, bytes, bytearray}:
        raw = bytes(payload) if type(payload) is bytearray else payload
    elif isinstance(payload, Mapping):
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    else:
        raise ValueError("decision must be JSON or a typed candidate DTO")
    try:
        tree = json.loads(raw, object_pairs_hook=_reject_duplicate_pairs, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("invalid candidate decision JSON") from exc
    if not isinstance(tree, dict):
        raise ValueError("decision JSON must be an object")
    def require_finite_numbers(value: Any) -> None:
        if type(value) is float and not math.isfinite(value):
            raise ValueError("non-finite JSON numbers are not allowed")
        if isinstance(value, list):
            for item in value:
                require_finite_numbers(item)
        elif isinstance(value, dict):
            for item in value.values():
                require_finite_numbers(item)

    require_finite_numbers(tree)
    try:
        return _DECISION_ADAPTER.validate_json(raw, strict=True)
    except ValidationError:
        raise


def export_p2_v3_json_schemas() -> dict[str, Any]:
    """Return isolated candidate schemas; never invokes the canonical exporter."""
    return {
        "protocol_versions": P2V3ProtocolVersions.model_json_schema(),
        "read_request": _READ_REQUEST_ADAPTER.json_schema(),
        "model_context": P2ModelContext.model_json_schema(),
        "decision": _DECISION_ADAPTER.json_schema(),
        "query_evidence": P2QueryEvidence.model_json_schema(),
        "fact": TypeAdapter(P2Fact).json_schema(),
        "current_actor": P2CurrentActorBinding.model_json_schema(),
        "entity_display_label": P2EntityDisplayLabel.model_json_schema(),
    }


def parse_source_numeric_lexeme(value: Any, *, precision: int, scale: int) -> str:
    """Validate exact decimal text from a source DTO without float/int coercion."""
    if type(value) is not str:
        raise ValueError("numeric source value must be an exact string lexeme")
    integer_digits = precision - scale
    pattern = rf"^-?(?:0|[1-9][0-9]{{0,{integer_digits - 1}}})(?:\.[0-9]{{1,{scale}}})?$"
    if re.fullmatch(pattern, value) is None:
        raise ValueError("numeric source lexeme exceeds its numeric precision/scale")
    _decimal(value)
    return value


def p2_criteria_digest(criteria: P2ReadCriteria) -> str:
    """Stable digest used by a server-issued grant to bind exact read criteria."""
    canonical = json.dumps(
        criteria.model_dump(mode="json", exclude_none=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def parse_financial_version(value: Any) -> int:
    """Accept only a JSON/Python integer, rejecting bool, float, and strings."""
    if type(value) is not int or value < 0 or value > MAX_FINANCIAL_VERSION:
        raise ValueError("financial_version must be a strict nonnegative int64")
    return value


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def parse_json_source_object(raw: str) -> dict[str, Any]:
    """Parse raw source JSON while retaining decimals as text and rejecting duplicates."""
    if type(raw) is not str:
        raise ValueError("raw JSON must be text")
    try:
        value = json.loads(raw, parse_float=str, parse_int=int, object_pairs_hook=_reject_duplicate_pairs)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("invalid source JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("source JSON root must be an object")
    return value

