"""Isolated T1 semantic/operations/trajectory 1.1 protocol over an immutable v1 snapshot.

This package has no dependency on the mutable application package or P2 runtime.
"""
from __future__ import annotations

import hashlib
import json
import uuid
import unicodedata
from datetime import date, datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import Field, StringConstraints, TypeAdapter, model_validator

from . import v1_contracts as v1

API_VERSION = "1.0.0"
SEMANTIC_VERSION = "1.1.0"
OPERATIONS_VERSION = "1.1.0"
TRAJECTORY_VERSION = "1.1.0"
EXECUTION_KEY_VERSION = "1"
PROTOCOL_PROFILE = "t1-offline-canonical"
QUERY_EVIDENCE_SCHEMA_VERSION = "1.1.0"
VENDOR_SOURCE_SHA256 = "9fd214d9d8eb43c6f5b03b1d7e95b2bef274dbf9e8be495f536f495b48a5bf2d"


class QueryEvidenceRef(v1.ContractEnum):
    Q01 = "query_1"
    Q02 = "query_2"
    Q03 = "query_3"
    Q04 = "query_4"
    Q05 = "query_5"
    Q06 = "query_6"
    Q07 = "query_7"
    Q08 = "query_8"
    Q09 = "query_9"
    Q10 = "query_10"
    Q11 = "query_11"
    Q12 = "query_12"
    Q13 = "query_13"
    Q14 = "query_14"
    Q15 = "query_15"
    Q16 = "query_16"


class QuerySource(v1.ContractEnum):
    SYNTHETIC_SIMULATION = "synthetic_simulation"
    P2_T1_ADAPTER = "p2_t1_adapter"


class ReadExpensesCriteria(v1.ReadExpensesCriteria):
    """v1 expense criteria plus one explicit NFC/casefold literal title filter."""

    from_date: Optional[v1.WireDate] = None
    to_date: Optional[v1.WireDate] = None
    title_contains: Optional[v1.ShortText] = None


ReadCriteriaV11 = Annotated[
    Union[v1.ReadActivitiesCriteria, ReadExpensesCriteria, v1.ReadDebtsCriteria],
    Field(discriminator="kind"),
]


class ReadDecision(v1.ContractModel):
    kind: Literal["read"]
    operation: v1.ReadOperation
    criteria: ReadCriteriaV11

    @model_validator(mode="after")
    def operation_matches_criteria(self) -> "ReadDecision":
        expected = {
            v1.ReadOperation.ACTIVITIES: "activities",
            v1.ReadOperation.EXPENSES: "expenses",
            v1.ReadOperation.DEBTS: "debts",
        }[self.operation]
        if self.criteria.kind != expected:
            raise ValueError("read operation and criteria kind must match")
        return self


class BackendActivitiesCriteria(v1.ContractModel):
    kind: Literal["activities"]
    scope_ref: None = None


class BackendExpensesCriteria(v1.ContractModel):
    kind: Literal["expenses"]
    scope_ref: v1.ActivityRef


class BackendDebtsCriteria(v1.ContractModel):
    kind: Literal["debts"]
    scope_ref: v1.ActivityRef


BackendCriteria = Annotated[
    Union[BackendActivitiesCriteria, BackendExpensesCriteria, BackendDebtsCriteria],
    Field(discriminator="kind"),
]


class ActivityPostFilter(v1.ContractModel):
    kind: Literal["activities"]
    status: Literal["active", "archived", "any"] = "active"
    name_contains: Optional[v1.ShortText] = None


class ExpensePostFilter(v1.ContractModel):
    kind: Literal["expenses"]
    from_date: Optional[v1.WireDate] = None
    to_date: Optional[v1.WireDate] = None
    participant_ref: Optional[v1.ParticipantRef] = None
    title_contains: Optional[v1.ShortText] = None


class DebtPostFilter(v1.ContractModel):
    kind: Literal["debts"]
    participant_ref: Optional[v1.ParticipantRef] = None
    currency: Optional[v1.CurrencyCode] = None


PostFilter = Annotated[
    Union[ActivityPostFilter, ExpensePostFilter, DebtPostFilter],
    Field(discriminator="kind"),
]


class QueryPageMetadata(v1.ContractModel):
    """Model-visible pagination summary; raw cursors and cursor digests stay private."""

    pages_seen: int = Field(strict=True, ge=1, le=128)
    expected_total: Optional[int] = Field(default=None, strict=True, ge=0)
    has_more: bool
    truncated: bool
    complete: bool
    range_contiguous: bool
    stable_total_verified: bool
    source_version_fenced: bool
    unique_items_verified: bool

    @model_validator(mode="after")
    def completeness_is_never_inferred_from_empty(self) -> "QueryPageMetadata":
        if self.complete:
            if (
                self.expected_total is None
                or self.has_more
                or self.truncated
                or not self.range_contiguous
                or not self.stable_total_verified
                or not self.source_version_fenced
                or not self.unique_items_verified
            ):
                raise ValueError("complete evidence requires an exact stable total and verified full page/version fences")
        elif not (self.has_more or self.truncated):
            raise ValueError("an incomplete query must explicitly report more data or truncation")
        return self


def _normalize_json(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _normalize_json(value.model_dump(mode="json", exclude_none=True))
    if isinstance(value, Enum):
        return _normalize_json(value.value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, (list, tuple)):
        return [_normalize_json(item) for item in value]
    if isinstance(value, dict):
        return {unicodedata.normalize("NFC", str(key)): _normalize_json(item) for key, item in value.items()}
    return str(value) if value.__class__.__name__ == "UUID" else value


def canonical_json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", exclude_none=True)
    return json.dumps(_normalize_json(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def exact_hash(value: Any) -> str:
    """Hash typed wire data without NFC rewriting; useful for verbatim-text seals."""
    def project(item: Any) -> Any:
        if hasattr(item, "model_dump"):
            return project(item.model_dump(mode="json", exclude_none=True))
        if isinstance(item, Enum):
            return item.value
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        if isinstance(item, uuid.UUID):
            return str(item)
        if isinstance(item, dict):
            return {str(key): project(child) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [project(child) for child in item]
        return item

    value = project(value)
    serialized = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def body_digest(body: Any) -> str:
    return exact_hash(body)


def normalized_criteria(operation: v1.ReadOperation, criteria: ReadCriteriaV11) -> str:
    return canonical_json({
        "operation": operation.value,
        "criteria": criteria.model_dump(mode="json", exclude_none=True),
    })


def backend_criteria_for(criteria: ReadCriteriaV11) -> BackendCriteria:
    if criteria.kind == "activities":
        return BackendActivitiesCriteria(kind="activities", scope_ref=None)
    if criteria.kind == "expenses":
        return BackendExpensesCriteria(kind="expenses", scope_ref=criteria.activity_ref)
    return BackendDebtsCriteria(kind="debts", scope_ref=criteria.activity_ref)


def post_filter_for(criteria: ReadCriteriaV11) -> PostFilter:
    if criteria.kind == "activities":
        return ActivityPostFilter(kind="activities", status=criteria.status, name_contains=criteria.name_contains)
    if criteria.kind == "expenses":
        return ExpensePostFilter(
            kind="expenses",
            from_date=criteria.from_date,
            to_date=criteria.to_date,
            participant_ref=criteria.participant_ref,
            title_contains=criteria.title_contains,
        )
    return DebtPostFilter(kind="debts", participant_ref=criteria.participant_ref, currency=criteria.currency)


def calculate_query_digest(
    *,
    operation: v1.ReadOperation,
    criteria: ReadCriteriaV11,
    backend_criteria: BackendCriteria,
    post_filter: PostFilter,
    scope_activity_id: Optional[Any],
    context_version: int,
    schema_version: str,
    source: QuerySource,
    source_version: str,
) -> str:
    return canonical_hash({
        "operation": operation.value,
        "normalized_criteria": normalized_criteria(operation, criteria),
        "backend_criteria": backend_criteria,
        "post_filter": post_filter,
        "scope_activity_id": str(scope_activity_id) if scope_activity_id else None,
        "context_version": context_version,
        "schema_version": schema_version,
        "source": source.value,
        "source_version": source_version,
    })


def _fact_matches(fact: Any, criteria: ReadCriteriaV11) -> bool:
    if criteria.kind == "activities":
        if criteria.status != "any" and fact.status.value != criteria.status:
            return False
        if criteria.name_contains is not None:
            needle = unicodedata.normalize("NFC", criteria.name_contains).casefold()
            if needle not in unicodedata.normalize("NFC", fact.name).casefold():
                return False
        return True
    if criteria.kind == "expenses":
        # P2 dates are UTC calendar windows: from_date is inclusive at 00:00Z and
        # to_date is exclusive at the following midnight. Comparing UTC dates is
        # equivalent without constructing to_date + 1 day (which overflows at date.max).
        try:
            occurred = fact.occurred_at.astimezone(timezone.utc).date()
        except OverflowError as exc:
            raise ValueError("expense timestamp cannot be represented in the UTC query calendar") from exc
        if criteria.from_date is not None and occurred < criteria.from_date:
            return False
        if criteria.to_date is not None and occurred > criteria.to_date:
            return False
        if criteria.participant_ref is not None and criteria.participant_ref not in fact.participant_refs:
            return False
        if criteria.title_contains is not None:
            needle = unicodedata.normalize("NFC", criteria.title_contains).casefold()
            if needle not in unicodedata.normalize("NFC", fact.title).casefold():
                return False
        return True
    if criteria.participant_ref is not None and criteria.participant_ref not in {fact.debtor_ref, fact.creditor_ref}:
        return False
    if criteria.currency is not None and fact.currency != criteria.currency:
        return False
    return True


class QueryEvidenceObservation(v1.ContractModel):
    """Typed query summary shown beside v1 facts; it is not trusted on its own."""

    query_ref: QueryEvidenceRef
    result_ref: v1.ReadResultRef
    operation: v1.ReadOperation
    criteria: ReadCriteriaV11
    normalized_criteria: Annotated[str, StringConstraints(strict=True, min_length=2, max_length=2000)]
    backend_criteria: BackendCriteria
    post_filter: PostFilter
    context_version: Annotated[int, Field(strict=True, ge=1)]
    schema_version: Literal["1.1.0"] = "1.1.0"
    source: QuerySource
    source_version: v1.ShortText
    observed_at: v1.WireDateTime
    simulation: bool
    returned_count: Annotated[int, Field(strict=True, ge=0, le=16)]
    matched_count: Annotated[int, Field(strict=True, ge=0, le=16)]
    matching_fact_citations: list[Union[v1.ActivityEvidenceRef, v1.ExpenseEvidenceRef, v1.DebtEvidenceRef]] = Field(max_length=16)
    page: QueryPageMetadata
    query_digest: Annotated[str, Field(pattern=v1.SHA256_PATTERN)]
    body_digest: Annotated[str, Field(pattern=v1.SHA256_PATTERN)]

    @model_validator(mode="after")
    def typed_query_is_self_consistent(self) -> "QueryEvidenceObservation":
        expected_operation = {
            "activities": v1.ReadOperation.ACTIVITIES,
            "expenses": v1.ReadOperation.EXPENSES,
            "debts": v1.ReadOperation.DEBTS,
        }[self.criteria.kind]
        if self.operation != expected_operation:
            raise ValueError("query operation and criteria kind must match")
        if self.backend_criteria.kind != self.criteria.kind or self.post_filter.kind != self.criteria.kind:
            raise ValueError("backend criteria and post-filter stages must match the typed query")
        if self.normalized_criteria != normalized_criteria(self.operation, self.criteria):
            raise ValueError("normalized criteria must be the canonical typed projection")
        if self.backend_criteria != backend_criteria_for(self.criteria) or self.post_filter != post_filter_for(self.criteria):
            raise ValueError("backend and post-filter stages must preserve every explicit criterion")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("query observed_at must be timezone-aware")
        if self.matched_count != len(self.matching_fact_citations):
            raise ValueError("matched_count must equal the matching fact citation count")
        if len(self.matching_fact_citations) != len(set(self.matching_fact_citations)):
            raise ValueError("matching fact citations must be unique")
        if self.page.complete and self.page.expected_total != self.returned_count:
            raise ValueError("complete query total must equal returned_count")
        if self.simulation != (self.source == QuerySource.SYNTHETIC_SIMULATION):
            raise ValueError("simulation flag must match the closed source allowlist")
        return self


class ModelContext(v1.ModelContext):
    """v1 fields stay unchanged; typed query observations are carried separately."""

    intent_classification: Literal["business", "non_business"]
    query_observations: list[QueryEvidenceObservation] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def query_results_are_separate_and_exact(self) -> "ModelContext":
        if self.intent_classification == "non_business" and (
            self.read_results
            or self.query_observations
            or self.available_permissions
            or self.bound_references
            or isinstance(self.verified_scope, v1.ModelActivityScope)
        ):
            raise ValueError("non-business intent is a trusted no-business-data route and cannot carry account scope/results")
        query_refs = [item.query_ref for item in self.query_observations]
        query_results = [item.result_ref for item in self.query_observations]
        visible_results = [item.result_ref for item in self.read_results]
        if len(query_refs) != len(set(query_refs)):
            raise ValueError("query evidence refs must be unique within one context")
        if len(query_results) != len(set(query_results)):
            raise ValueError("one query observation may bind each result only once")
        if set(query_results) != set(visible_results) or len(query_results) != len(visible_results):
            raise ValueError("every v1 read result must have exactly one separate query observation")
        result_index = {result.result_ref: result for result in self.read_results}
        for query in self.query_observations:
            result = result_index[query.result_ref]
            if (
                result.operation != query.operation
                or result.observed_at != query.observed_at
                or result.context_version != query.context_version
                or result.simulation != query.simulation
            ):
                raise ValueError("query observation must match its visible v1 result envelope")
            if query.returned_count != len(result.body.items):
                raise ValueError("returned_count must equal the full visible result body")
            evidence = {fact.evidence_ref for fact in result.body.items}
            if not set(query.matching_fact_citations).issubset(evidence):
                raise ValueError("query matches must cite facts in its bound result body")
        return self


EvidenceCitationV11 = Union[v1.EvidenceCitation, QueryEvidenceRef]


class AnswerDecision(v1.AnswerDecision):
    citations: list[EvidenceCitationV11] = Field(max_length=16)


SemanticDecision = Annotated[
    Union[AnswerDecision, v1.ClarifyDecision, ReadDecision, v1.ProposeDecision],
    Field(discriminator="kind"),
]
SEMANTIC_DECISION_ADAPTER = TypeAdapter(SemanticDecision)


class DecisionEnvelopeV11(v1.ContractModel):
    """Complete explicit profile negotiation paired with one of the four typed decisions."""

    versions: NegotiatedVersions
    decision: SemanticDecision


class NegotiatedVersions(v1.ContractModel):
    api_version: Literal["1.0.0"]
    semantic_version: Literal["1.1.0"]
    operations_version: Literal["1.1.0"]
    trajectory_version: Literal["1.1.0"]
    execution_key_version: Literal["1"]


class ProtocolVersionTuple(v1.ContractModel):
    """Complete tuple required before either the old or new parser is selected."""

    api_version: v1.ShortText
    semantic_version: v1.ShortText
    operations_version: v1.ShortText
    trajectory_version: v1.ShortText
    execution_key_version: v1.ShortText

    @model_validator(mode="after")
    def supported_complete_profile(self) -> "ProtocolVersionTuple":
        value = self.model_dump(mode="json")
        legacy = {
            "api_version": v1.API_VERSION,
            "semantic_version": v1.SEMANTIC_VERSION,
            "operations_version": v1.OPERATIONS_VERSION,
            "trajectory_version": v1.TRAJECTORY_VERSION,
            "execution_key_version": v1.EXECUTION_KEY_VERSION,
        }
        current = {
            "api_version": API_VERSION,
            "semantic_version": SEMANTIC_VERSION,
            "operations_version": OPERATIONS_VERSION,
            "trajectory_version": TRAJECTORY_VERSION,
            "execution_key_version": EXECUTION_KEY_VERSION,
        }
        if value not in (legacy, current):
            raise ValueError("only complete explicitly supported legacy-v1 or offline-v1.1 tuples are accepted")
        return self


CLOSED_CAPABILITY_ACKNOWLEDGEMENT = "This capability is unavailable in the current protocol."


def parse_decision(raw: Any, *, negotiated_versions: Any) -> Any:
    """Require the full version tuple; never select a parser from semantic alone."""
    if isinstance(raw, (str, bytes, bytearray)):
        wire_json = raw
    else:
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump(mode="json")

        def wire_default(value: Any) -> Any:
            if isinstance(value, Enum):
                return value.value
            if isinstance(value, (date, datetime)):
                return value.isoformat()
            raise TypeError(f"unsupported JSON protocol value: {type(value).__name__}")

        wire_json = json.dumps(raw, ensure_ascii=False, allow_nan=False, default=wire_default)
    try:
        versions = ProtocolVersionTuple.model_validate(negotiated_versions)
    except Exception as exc:
        raise ValueError("complete explicit version negotiation is required") from exc
    if versions.semantic_version == v1.SEMANTIC_VERSION:
        return v1.SEMANTIC_DECISION_ADAPTER.validate_json(wire_json)
    return SEMANTIC_DECISION_ADAPTER.validate_json(wire_json)


def semantic_schema_roots() -> list[type]:
    return [
        NegotiatedVersions,
        ProtocolVersionTuple,
        QueryEvidenceRef,
        QuerySource,
        ReadExpensesCriteria,
        ReadDecision,
        BackendActivitiesCriteria,
        BackendExpensesCriteria,
        BackendDebtsCriteria,
        ActivityPostFilter,
        ExpensePostFilter,
        DebtPostFilter,
        QueryPageMetadata,
        QueryEvidenceObservation,
        ModelContext,
        AnswerDecision,
        v1.ClarifyDecision,
        v1.ProposeDecision,
        DecisionEnvelopeV11,
    ]


def build_semantic_decision_schema() -> dict:
    schema = SEMANTIC_DECISION_ADAPTER.json_schema(mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://shared-ledger.invalid/schemas/t1-semantic-decision-1.1.0.json"
    return schema
