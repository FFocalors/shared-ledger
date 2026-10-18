"""Versioned, closed protocol models for Shared Ledger Agent P1-01.

This module is the source of truth for offline contract validation. It does not
implement an HTTP service, authentication, persistence, a model provider, or a
business adapter.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Annotated, Literal, Optional, Union

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)
from pydantic_core import core_schema


API_VERSION = "1.0.0"
SEMANTIC_VERSION = "1.0.0"
OPERATIONS_VERSION = "1.0.0"
TRAJECTORY_VERSION = "1.0.0"
EXECUTION_KEY_VERSION = "1"
EXECUTION_NAMESPACE = uuid.UUID("7fd9a109-cad5-5a6a-a6ee-4b2f0c8f4b8d")

MONEY_PATTERN = r"^(0|[1-9][0-9]{0,11})(\.[0-9]{1,4})?$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
NONCE_PATTERN = r"^[A-Za-z0-9_-]{32,128}$"
BIGINT_MAX = "9223372036854775807"
_JWT_RE = re.compile(r"(?i)(?:bearer\s+)?eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
_URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)\S+")


def _bounded_integer_pattern(maximum: str, *, allow_zero: bool) -> str:
    """Build a JSON-Schema-compatible decimal string pattern for 1..maximum (or 0..maximum)."""
    alternatives: list[str] = ["0"] if allow_zero else []
    for width in range(1, len(maximum)):
        alternatives.append(r"[1-9]" + (rf"[0-9]{{{width - 1}}}" if width > 1 else ""))
    prefix = ""
    for index, char in enumerate(maximum):
        digit = int(char)
        low = 1 if index == 0 else 0
        if digit > low:
            remaining = len(maximum) - index - 1
            tail = rf"[0-9]{{{remaining}}}" if remaining else ""
            alternatives.append(prefix + f"[{low}-{digit - 1}]" + tail)
        prefix += char
    alternatives.append(maximum)
    return "^(?:" + "|".join(alternatives) + ")$"


FINANCIAL_VERSION_PATTERN = _bounded_integer_pattern(BIGINT_MAX, allow_zero=True)
EXPENSE_VERSION_PATTERN = _bounded_integer_pattern(BIGINT_MAX, allow_zero=False)


class ContractEnum(str, Enum):
    """Enum wire adapter: strict Python input may use only an exact declared JSON string."""

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> Any:
        enum = core_schema.enum_schema(cls, list(cls), sub_type="str")

        def parse_exact_string(value: Any) -> Any:
            if isinstance(value, str) and not isinstance(value, cls):
                try:
                    return cls(value)
                except ValueError:
                    return value
            return value

        return core_schema.no_info_before_validator_function(parse_exact_string, enum)


def _wire_uuid(value: Any) -> Any:
    if isinstance(value, str):
        try:
            parsed = uuid.UUID(value)
        except ValueError:
            return value
        return parsed if str(parsed) == value.lower() else value
    return value


def _wire_datetime(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        except ValueError:
            return value
    return value


def _wire_date(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return value
    return value


WireUUID = Annotated[uuid.UUID, BeforeValidator(_wire_uuid), Field(strict=True)]
WireDateTime = Annotated[datetime, BeforeValidator(_wire_datetime), Field(strict=True)]
WireDate = Annotated[date, BeforeValidator(_wire_date), Field(strict=True)]


class ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_assignment=True,
    )

    @classmethod
    def model_validate(
        cls,
        obj: Any,
        *,
        strict: Optional[bool] = None,
        from_attributes: Optional[bool] = None,
        context: Optional[dict[str, Any]] = None,
        by_alias: Optional[bool] = None,
        by_name: Optional[bool] = None,
    ) -> Any:
        """Treat dict input as JSON wire data while retaining strict JSON scalar checks.

        FastAPI's default body path supplies a Python dict. Pydantic strict-Python mode
        rejects JSON UUID/enum/date strings, while strict-JSON mode accepts their wire
        forms. This adapter normalizes only JSON-serializable values, then validates in
        strict JSON mode; floats, bool/int confusion, unknown fields, and other coercions
        remain rejected by the core schema.
        """
        if isinstance(obj, dict):
            def json_default(value: Any) -> Any:
                if isinstance(value, (uuid.UUID, datetime, date, Enum)):
                    return value.isoformat() if isinstance(value, (datetime, date)) else (value.value if isinstance(value, Enum) else str(value))
                raise TypeError(f"not a JSON wire value: {type(value).__name__}")

            raw = json.dumps(obj, ensure_ascii=False, allow_nan=False, default=json_default)
            return super().model_validate_json(
                raw,
                strict=strict,
                context=context,
                by_alias=by_alias,
                by_name=by_name,
            )
        return super().model_validate(
            obj,
            strict=strict,
            from_attributes=from_attributes,
            context=context,
            by_alias=by_alias,
            by_name=by_name,
        )


class ApiVersion(ContractEnum):
    V1 = API_VERSION


class SemanticVersion(ContractEnum):
    V1 = SEMANTIC_VERSION


class OperationsVersion(ContractEnum):
    V1 = OPERATIONS_VERSION


class TrajectoryVersion(ContractEnum):
    V1 = TRAJECTORY_VERSION


class ProtocolVersions(ContractModel):
    api: Literal["1.0.0"] = API_VERSION
    semantic: Literal["1.0.0"] = SEMANTIC_VERSION
    operations: Literal["1.0.0"] = OPERATIONS_VERSION
    trajectory: Literal["1.0.0"] = TRAJECTORY_VERSION


class ClientProtocolVersions(ContractModel):
    """Versions negotiated by API clients; trajectory schema is offline-only."""

    api: Literal["1.0.0"] = API_VERSION
    semantic: Literal["1.0.0"] = SEMANTIC_VERSION
    operations: Literal["1.0.0"] = OPERATIONS_VERSION


StrictText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=4000)]
ShortText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=240)]
TitleText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=120)]
NoteText = Annotated[str, StringConstraints(strict=True, max_length=1000)]
CurrencyCode = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Z]{3}$")]
MoneyString = Annotated[str, StringConstraints(strict=True, pattern=MONEY_PATTERN)]
FinancialVersion = Annotated[
    str,
    StringConstraints(strict=True, pattern=FINANCIAL_VERSION_PATTERN),
    Field(json_schema_extra={"x-database-type": "signed-bigint", "x-minimum": "0", "x-maximum": BIGINT_MAX}),
]
ExpenseVersion = Annotated[
    str,
    StringConstraints(strict=True, pattern=EXPENSE_VERSION_PATTERN),
    Field(json_schema_extra={"x-database-type": "signed-bigint", "x-minimum": "1", "x-maximum": BIGINT_MAX}),
]
Sha256Hex = Annotated[str, StringConstraints(strict=True, pattern=SHA256_PATTERN)]
ConfirmationNonce = Annotated[str, StringConstraints(strict=True, pattern=NONCE_PATTERN)]
ConfirmationNonceForCard = Annotated[
    str,
    StringConstraints(strict=True, pattern=NONCE_PATTERN),
    Field(json_schema_extra={"x-sensitive": True, "x-never-model-event-or-log": True}),
]
ConfirmationNonceForRequest = Annotated[
    str,
    StringConstraints(strict=True, pattern=NONCE_PATTERN),
    Field(json_schema_extra={"writeOnly": True, "x-never-model-event-or-log": True}),
]
ClientRequestId = WireUUID
SessionId = WireUUID
TurnId = WireUUID
ProposalId = WireUUID
UserId = WireUUID
EntityId = WireUUID


def _money(value: str, *, positive: bool = False) -> Decimal:
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("amount must be a decimal string") from exc
    if not amount.is_finite():
        raise ValueError("amount must be finite")
    if positive and amount <= 0:
        raise ValueError("amount must be greater than zero")
    return amount


def _safe_text(value: str) -> str:
    if _JWT_RE.search(value):
        raise ValueError("credential-like text must not enter the protocol")
    return value


def _no_url(value: str) -> str:
    if _URL_RE.search(value):
        raise ValueError("semantic text cannot contain an arbitrary URL")
    return _safe_text(value)


class PageType(ContractEnum):
    HOME = "home"
    ACTIVITY_OVERVIEW = "activity_overview"
    EXPENSE_LIST = "expense_list"
    EXPENSE_DETAIL = "expense_detail"
    DEBT_LIST = "debt_list"
    PREPAYMENT = "prepayment"
    SETTLEMENT = "settlement"
    SETTINGS = "settings"


class UiEntityType(ContractEnum):
    ACTIVITY = "activity"
    LEDGER_UNIT = "ledger_unit"
    EXPENSE = "expense"
    PARTICIPANT = "participant"


class UiEntityHint(ContractModel):
    entity_type: UiEntityType
    entity_id: EntityId


class UiFilters(ContractModel):
    from_date: Optional[WireDate] = None
    to_date: Optional[WireDate] = None
    participant_ids: list[EntityId] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def dates_are_ordered(self) -> "UiFilters":
        if self.from_date is not None and self.to_date is not None and self.from_date > self.to_date:
            raise ValueError("from_date must be on or before to_date")
        return self


class UIContext(ContractModel):
    """Untrusted navigation hints. These values never establish identity or permission."""

    schema_version: Literal[1] = 1
    page_type: PageType
    activity_id: Optional[EntityId] = None
    ledger_unit_id: Optional[EntityId] = None
    selected_entity: Optional[UiEntityHint] = None
    filters: UiFilters = Field(default_factory=UiFilters)
    captured_at: WireDateTime
    client_version: ShortText

    @field_validator("captured_at")
    @classmethod
    def captured_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must include a timezone")
        return value


class HarnessPermission(ContractEnum):
    READ_ACTIVITIES = "read.activities"
    READ_EXPENSES = "read.expenses"
    READ_DEBTS = "read.debts"
    PROPOSE_EXPENSE_CREATE = "propose.expense.create"
    PROPOSE_EXPENSE_UPDATE = "propose.expense.update"
    PROPOSE_EXPENSE_PRESENTATION_UPDATE = "propose.expense.presentation.update"


class ActivityRef(ContractEnum):
    SELECTED = "activity_selected"
    A01 = "activity_1"
    A02 = "activity_2"
    A03 = "activity_3"
    A04 = "activity_4"
    A05 = "activity_5"
    A06 = "activity_6"
    A07 = "activity_7"
    A08 = "activity_8"
    A09 = "activity_9"
    A10 = "activity_10"
    A11 = "activity_11"
    A12 = "activity_12"
    A13 = "activity_13"
    A14 = "activity_14"
    A15 = "activity_15"
    A16 = "activity_16"


class LedgerUnitRef(ContractEnum):
    SELECTED = "ledger_unit_selected"
    U01 = "ledger_unit_1"
    U02 = "ledger_unit_2"
    U03 = "ledger_unit_3"
    U04 = "ledger_unit_4"
    U05 = "ledger_unit_5"
    U06 = "ledger_unit_6"
    U07 = "ledger_unit_7"
    U08 = "ledger_unit_8"
    U09 = "ledger_unit_9"
    U10 = "ledger_unit_10"
    U11 = "ledger_unit_11"
    U12 = "ledger_unit_12"
    U13 = "ledger_unit_13"
    U14 = "ledger_unit_14"
    U15 = "ledger_unit_15"
    U16 = "ledger_unit_16"


class ExpenseRef(ContractEnum):
    SELECTED = "expense_selected"
    E01 = "expense_1"
    E02 = "expense_2"
    E03 = "expense_3"
    E04 = "expense_4"
    E05 = "expense_5"
    E06 = "expense_6"
    E07 = "expense_7"
    E08 = "expense_8"
    E09 = "expense_9"
    E10 = "expense_10"
    E11 = "expense_11"
    E12 = "expense_12"
    E13 = "expense_13"
    E14 = "expense_14"
    E15 = "expense_15"
    E16 = "expense_16"


class ParticipantRef(ContractEnum):
    SELECTED = "participant_selected"
    P01 = "participant_1"
    P02 = "participant_2"
    P03 = "participant_3"
    P04 = "participant_4"
    P05 = "participant_5"
    P06 = "participant_6"
    P07 = "participant_7"
    P08 = "participant_8"
    P09 = "participant_9"
    P10 = "participant_10"
    P11 = "participant_11"
    P12 = "participant_12"
    P13 = "participant_13"
    P14 = "participant_14"
    P15 = "participant_15"
    P16 = "participant_16"
    P17 = "participant_17"
    P18 = "participant_18"
    P19 = "participant_19"
    P20 = "participant_20"
    P21 = "participant_21"
    P22 = "participant_22"
    P23 = "participant_23"
    P24 = "participant_24"
    P25 = "participant_25"
    P26 = "participant_26"
    P27 = "participant_27"
    P28 = "participant_28"
    P29 = "participant_29"
    P30 = "participant_30"
    P31 = "participant_31"
    P32 = "participant_32"


class ActivityEvidenceRef(ContractEnum):
    F01 = "fact_activity_1"
    F02 = "fact_activity_2"
    F03 = "fact_activity_3"
    F04 = "fact_activity_4"
    F05 = "fact_activity_5"
    F06 = "fact_activity_6"
    F07 = "fact_activity_7"
    F08 = "fact_activity_8"
    F09 = "fact_activity_9"
    F10 = "fact_activity_10"
    F11 = "fact_activity_11"
    F12 = "fact_activity_12"
    F13 = "fact_activity_13"
    F14 = "fact_activity_14"
    F15 = "fact_activity_15"
    F16 = "fact_activity_16"


class ExpenseEvidenceRef(ContractEnum):
    F01 = "fact_expense_1"
    F02 = "fact_expense_2"
    F03 = "fact_expense_3"
    F04 = "fact_expense_4"
    F05 = "fact_expense_5"
    F06 = "fact_expense_6"
    F07 = "fact_expense_7"
    F08 = "fact_expense_8"
    F09 = "fact_expense_9"
    F10 = "fact_expense_10"
    F11 = "fact_expense_11"
    F12 = "fact_expense_12"
    F13 = "fact_expense_13"
    F14 = "fact_expense_14"
    F15 = "fact_expense_15"
    F16 = "fact_expense_16"


class DebtEvidenceRef(ContractEnum):
    F01 = "fact_debt_1"
    F02 = "fact_debt_2"
    F03 = "fact_debt_3"
    F04 = "fact_debt_4"
    F05 = "fact_debt_5"
    F06 = "fact_debt_6"
    F07 = "fact_debt_7"
    F08 = "fact_debt_8"
    F09 = "fact_debt_9"
    F10 = "fact_debt_10"
    F11 = "fact_debt_11"
    F12 = "fact_debt_12"
    F13 = "fact_debt_13"
    F14 = "fact_debt_14"
    F15 = "fact_debt_15"
    F16 = "fact_debt_16"


class PolicyEvidenceRef(ContractEnum):
    P01 = "policy_fact_1"
    P02 = "policy_fact_2"
    P03 = "policy_fact_3"
    P04 = "policy_fact_4"
    P05 = "policy_fact_5"
    P06 = "policy_fact_6"
    P07 = "policy_fact_7"
    P08 = "policy_fact_8"


EvidenceCitation = Union[
    ActivityEvidenceRef,
    ExpenseEvidenceRef,
    DebtEvidenceRef,
    PolicyEvidenceRef,
]


ModelRefToken = Union[ActivityRef, LedgerUnitRef, ExpenseRef, ParticipantRef]


class ModelActivityScope(ContractModel):
    kind: Literal["activity"]
    activity_ref: ActivityRef
    permissions: list[HarnessPermission] = Field(max_length=16)


class ModelNoActivityScope(ContractModel):
    kind: Literal["none"]
    permissions: list[HarnessPermission] = Field(max_length=16)


ModelVerifiedScope = Annotated[
    Union[ModelActivityScope, ModelNoActivityScope],
    Field(discriminator="kind"),
]


class ModelActivityReference(ContractModel):
    kind: Literal["activity"]
    ref: ActivityRef


class ModelLedgerUnitReference(ContractModel):
    kind: Literal["ledger_unit"]
    ref: LedgerUnitRef


class ModelExpenseReference(ContractModel):
    kind: Literal["expense"]
    ref: ExpenseRef


class ModelParticipantReference(ContractModel):
    kind: Literal["participant"]
    ref: ParticipantRef


ModelReference = Annotated[
    Union[
        ModelActivityReference,
        ModelLedgerUnitReference,
        ModelExpenseReference,
        ModelParticipantReference,
    ],
    Field(discriminator="kind"),
]


class PolicyRule(ContractEnum):
    EXPENSE_LOCK = "expense_financial_lock"
    EXPENSE_NO_RESTORE = "expense_restore_unavailable"
    LARGE_PREPAYMENT = "large_activity_prepayment_only"
    SUB_ACTIVITY_SCOPE = "sub_activity_participant_scope"
    EXECUTION_CONFIRMATION = "execution_requires_confirmation"
    CAPABILITY_AVAILABILITY = "capability_availability"


class PolicySource(ContractEnum):
    DEVELOPMENT_GUIDE = "development_guide_v0_4_2"
    BUSINESS_LOGIC = "business_logic_current"
    CAPABILITY_MAP = "capability_map_static_audit"


class PolicyEvidence(ContractModel):
    evidence_ref: PolicyEvidenceRef
    rule: PolicyRule
    source: PolicySource
    version: ShortText
    text: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=1200)]
    observed_at: datetime

    @field_validator("text")
    @classmethod
    def policy_text_is_safe(cls, value: str) -> str:
        return _no_url(value)

    @field_validator("observed_at")
    @classmethod
    def observed_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value


class BoundActivityReference(ContractModel):
    kind: Literal["activity"]
    ref: ActivityRef
    entity_id: EntityId
    source_turn_id: TurnId
    scope_activity_id: EntityId


class BoundLedgerUnitReference(ContractModel):
    kind: Literal["ledger_unit"]
    ref: LedgerUnitRef
    entity_id: EntityId
    source_turn_id: TurnId
    scope_activity_id: EntityId


class BoundExpenseReference(ContractModel):
    kind: Literal["expense"]
    ref: ExpenseRef
    entity_id: EntityId
    source_turn_id: TurnId
    scope_activity_id: EntityId


class BoundParticipantReference(ContractModel):
    kind: Literal["participant"]
    ref: ParticipantRef
    entity_id: EntityId
    source_turn_id: TurnId
    scope_activity_id: EntityId


BoundReference = Annotated[
    Union[
        BoundActivityReference,
        BoundLedgerUnitReference,
        BoundExpenseReference,
        BoundParticipantReference,
    ],
    Field(discriminator="kind"),
]


class ResolvedEntityCandidate(ContractModel):
    """Private result of authoritative UUID resolution; never serialized to model context."""

    kind: UiEntityType
    entity_id: EntityId
    scope_activity_id: EntityId

    @model_validator(mode="after")
    def activity_scope_is_valid(self) -> "ResolvedEntityCandidate":
        if self.kind == UiEntityType.ACTIVITY and self.entity_id != self.scope_activity_id:
            raise ValueError("an Activity reference scopes to itself")
        return self


def _reference_parts(reference: BoundReference) -> tuple[str, uuid.UUID, str]:
    return (reference.kind, reference.entity_id, reference.ref.value)


def bind_stable_references(
    existing: list[BoundReference],
    candidates: list[ResolvedEntityCandidate],
    *,
    source_turn_id: TurnId,
) -> list[BoundReference]:
    """Append deterministic typed refs, preserving stored bindings across sort and restart.

    First-time candidates are assigned in UUID-sorted order per entity type. Later calls
    reuse existing (kind, entity_id) bindings and allocate only unused labels. Callers
    persist the returned map in the Turn row before exposing ref tokens to the model.
    """
    result = list(existing)
    by_entity: dict[tuple[str, uuid.UUID], BoundReference] = {}
    used: dict[str, set[str]] = {}
    for item in result:
        if item.source_turn_id != source_turn_id:
            raise ValueError("typed references cannot be imported from another Turn")
        key = (item.kind, item.entity_id)
        if key in by_entity:
            raise ValueError("one entity has duplicate typed bindings in the same Turn")
        used.setdefault(item.kind, set())
        if item.ref.value in used[item.kind]:
            raise ValueError("one typed ref token cannot bind two entities")
        by_entity[key] = item
        used[item.kind].add(item.ref.value)
    unique: dict[tuple[str, uuid.UUID], ResolvedEntityCandidate] = {}
    for candidate in candidates:
        key = (candidate.kind.value, candidate.entity_id)
        prior = unique.get(key)
        if prior is not None and prior.scope_activity_id != candidate.scope_activity_id:
            raise ValueError("one entity cannot be rebound into another activity scope")
        unique[key] = candidate
    ordered = sorted(unique.values(), key=lambda item: (item.kind.value, str(item.entity_id)))
    for candidate in ordered:
        kind = candidate.kind.value
        key = (kind, candidate.entity_id)
        old = by_entity.get(key)
        if old is not None:
            if old.scope_activity_id != candidate.scope_activity_id:
                raise ValueError("an existing ref cannot be rebound to a different scope")
            continue
        if kind == UiEntityType.ACTIVITY.value:
            choices: list[Union[ActivityRef, LedgerUnitRef, ExpenseRef, ParticipantRef]] = [
                value for value in ActivityRef if value != ActivityRef.SELECTED
            ]
        elif kind == UiEntityType.LEDGER_UNIT.value:
            choices = [value for value in LedgerUnitRef if value != LedgerUnitRef.SELECTED]
        elif kind == UiEntityType.EXPENSE.value:
            choices = [value for value in ExpenseRef if value != ExpenseRef.SELECTED]
        else:
            choices = [value for value in ParticipantRef if value != ParticipantRef.SELECTED]
        token = next((choice for choice in choices if choice.value not in used.get(kind, set())), None)
        if token is None:
            raise ValueError(f"Turn reference capacity exceeded for {kind}")
        if kind == UiEntityType.ACTIVITY.value:
            bound: BoundReference = BoundActivityReference(
                kind="activity",
                ref=token,
                entity_id=candidate.entity_id,
                source_turn_id=source_turn_id,
                scope_activity_id=candidate.scope_activity_id,
            )
        elif kind == UiEntityType.LEDGER_UNIT.value:
            bound = BoundLedgerUnitReference(
                kind="ledger_unit",
                ref=token,
                entity_id=candidate.entity_id,
                source_turn_id=source_turn_id,
                scope_activity_id=candidate.scope_activity_id,
            )
        elif kind == UiEntityType.EXPENSE.value:
            bound = BoundExpenseReference(
                kind="expense",
                ref=token,
                entity_id=candidate.entity_id,
                source_turn_id=source_turn_id,
                scope_activity_id=candidate.scope_activity_id,
            )
        else:
            bound = BoundParticipantReference(
                kind="participant",
                ref=token,
                entity_id=candidate.entity_id,
                source_turn_id=source_turn_id,
                scope_activity_id=candidate.scope_activity_id,
            )
        result.append(bound)
        by_entity[key] = bound
        used.setdefault(kind, set()).add(token.value)
    return result


def bind_selected_reference(
    existing: list[BoundReference],
    candidate: ResolvedEntityCandidate,
    *,
    source_turn_id: TurnId,
) -> BoundReference:
    """Bind a UI-selected entity once; changed selection requires an explicit new Turn."""
    selected_by_kind: dict[str, Union[ActivityRef, LedgerUnitRef, ExpenseRef, ParticipantRef]] = {
        UiEntityType.ACTIVITY.value: ActivityRef.SELECTED,
        UiEntityType.LEDGER_UNIT.value: LedgerUnitRef.SELECTED,
        UiEntityType.EXPENSE.value: ExpenseRef.SELECTED,
        UiEntityType.PARTICIPANT.value: ParticipantRef.SELECTED,
    }
    token = selected_by_kind[candidate.kind.value]
    for item in existing:
        if item.source_turn_id != source_turn_id:
            raise ValueError("typed references cannot be imported from another Turn")
        if item.kind == candidate.kind.value and item.ref == token:
            if item.entity_id != candidate.entity_id or item.scope_activity_id != candidate.scope_activity_id:
                raise ValueError("selected reference target is immutable within a Turn")
            return item
    common = {
        "ref": token,
        "entity_id": candidate.entity_id,
        "source_turn_id": source_turn_id,
        "scope_activity_id": candidate.scope_activity_id,
    }
    if candidate.kind == UiEntityType.ACTIVITY:
        return BoundActivityReference(kind="activity", **common)
    if candidate.kind == UiEntityType.LEDGER_UNIT:
        return BoundLedgerUnitReference(kind="ledger_unit", **common)
    if candidate.kind == UiEntityType.EXPENSE:
        return BoundExpenseReference(kind="expense", **common)
    return BoundParticipantReference(kind="participant", **common)


class ResolvedEvidenceCandidate(ContractModel):
    kind: Literal["activity", "expense", "debt"]
    entity_id: EntityId
    scope_activity_id: EntityId
    source_result_id: uuid.UUID
    context_version: Annotated[int, Field(strict=True, ge=1)]


class BoundActivityEvidence(ContractModel):
    kind: Literal["activity"]
    evidence_ref: ActivityEvidenceRef
    entity_id: EntityId
    scope_activity_id: EntityId
    source_result_id: uuid.UUID
    source_turn_id: TurnId
    context_version: Annotated[int, Field(strict=True, ge=1)]


class BoundExpenseEvidence(ContractModel):
    kind: Literal["expense"]
    evidence_ref: ExpenseEvidenceRef
    entity_id: EntityId
    scope_activity_id: EntityId
    source_result_id: uuid.UUID
    source_turn_id: TurnId
    context_version: Annotated[int, Field(strict=True, ge=1)]


class BoundDebtEvidence(ContractModel):
    kind: Literal["debt"]
    evidence_ref: DebtEvidenceRef
    entity_id: EntityId
    scope_activity_id: EntityId
    source_result_id: uuid.UUID
    source_turn_id: TurnId
    context_version: Annotated[int, Field(strict=True, ge=1)]


BoundEvidenceReference = Annotated[
    Union[BoundActivityEvidence, BoundExpenseEvidence, BoundDebtEvidence],
    Field(discriminator="kind"),
]


def bind_stable_evidence(
    existing: list[BoundEvidenceReference],
    candidates: list[ResolvedEvidenceCandidate],
    *,
    source_turn_id: TurnId,
) -> list[BoundEvidenceReference]:
    """Bind fact citations to immutable (Turn, result, entity, version) evidence identities."""
    result = list(existing)
    by_source: dict[tuple[str, uuid.UUID, uuid.UUID, int], BoundEvidenceReference] = {}
    used: dict[str, set[str]] = {}
    for item in result:
        if item.source_turn_id != source_turn_id:
            raise ValueError("evidence references cannot be imported from another Turn")
        key = (item.kind, item.source_result_id, item.entity_id, item.context_version)
        if key in by_source:
            raise ValueError("duplicate stable evidence binding")
        if item.evidence_ref.value in used.setdefault(item.kind, set()):
            raise ValueError("one evidence token cannot identify two observations of the same kind")
        by_source[key] = item
        used[item.kind].add(item.evidence_ref.value)
    unique: dict[tuple[str, uuid.UUID, uuid.UUID, int], ResolvedEvidenceCandidate] = {}
    for candidate in candidates:
        key = (
            candidate.kind,
            candidate.source_result_id,
            candidate.entity_id,
            candidate.context_version,
        )
        prior = unique.get(key)
        if prior is not None and prior.scope_activity_id != candidate.scope_activity_id:
            raise ValueError("evidence source cannot be rebound to a different activity")
        unique[key] = candidate
    ordered = sorted(
        unique.values(),
        key=lambda item: (item.kind, str(item.source_result_id), str(item.entity_id), item.context_version),
    )
    choices_by_kind: dict[str, list[Union[ActivityEvidenceRef, ExpenseEvidenceRef, DebtEvidenceRef]]] = {
        "activity": list(ActivityEvidenceRef),
        "expense": list(ExpenseEvidenceRef),
        "debt": list(DebtEvidenceRef),
    }
    for candidate in ordered:
        key = (
            candidate.kind,
            candidate.source_result_id,
            candidate.entity_id,
            candidate.context_version,
        )
        if key in by_source:
            if by_source[key].scope_activity_id != candidate.scope_activity_id:
                raise ValueError("an existing evidence token cannot be rebound to another scope")
            continue
        used_tokens = used.setdefault(candidate.kind, set())
        token = next((item for item in choices_by_kind[candidate.kind] if item.value not in used_tokens), None)
        if token is None:
            raise ValueError(f"Turn evidence capacity exceeded for {candidate.kind}")
        common = {
            "evidence_ref": token,
            "entity_id": candidate.entity_id,
            "scope_activity_id": candidate.scope_activity_id,
            "source_result_id": candidate.source_result_id,
            "source_turn_id": source_turn_id,
            "context_version": candidate.context_version,
        }
        if candidate.kind == "activity":
            bound: BoundEvidenceReference = BoundActivityEvidence(kind="activity", **common)
        elif candidate.kind == "expense":
            bound = BoundExpenseEvidence(kind="expense", **common)
        else:
            bound = BoundDebtEvidence(kind="debt", **common)
        result.append(bound)
        by_source[key] = bound
        used_tokens.add(token.value)
    return result


def model_reference_tokens(bound_references: list[BoundReference]) -> list[ModelReference]:
    """Project persisted server UUID bindings to typed tokens safe for the model."""
    projected: list[ModelReference] = []
    for item in bound_references:
        if item.kind == "activity":
            projected.append(ModelActivityReference(kind="activity", ref=item.ref))
        elif item.kind == "ledger_unit":
            projected.append(ModelLedgerUnitReference(kind="ledger_unit", ref=item.ref))
        elif item.kind == "expense":
            projected.append(ModelExpenseReference(kind="expense", ref=item.ref))
        else:
            projected.append(ModelParticipantReference(kind="participant", ref=item.ref))
    return projected


class ActivityScope(ContractModel):
    kind: Literal["activity"]
    activity_id: EntityId
    permissions: list[HarnessPermission] = Field(max_length=16)


class NoActivityScope(ContractModel):
    kind: Literal["none"]
    permissions: list[HarnessPermission] = Field(max_length=16)


VerifiedScope = Annotated[
    Union[ActivityScope, NoActivityScope],
    Field(discriminator="kind"),
]


class ActivityStatus(ContractEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class ActivityKind(ContractEnum):
    NORMAL = "normal"
    LARGE = "large"


class ActivityFact(ContractModel):
    kind: Literal["activity"]
    evidence_ref: ActivityEvidenceRef
    activity_ref: ActivityRef
    name: TitleText
    activity_kind: ActivityKind
    base_currency: CurrencyCode
    status: ActivityStatus
    observed_at: datetime
    context_version: Annotated[int, Field(strict=True, ge=1)]

    @field_validator("observed_at")
    @classmethod
    def observed_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value


class ExpenseFact(ContractModel):
    kind: Literal["expense"]
    evidence_ref: ExpenseEvidenceRef
    expense_ref: ExpenseRef
    title: TitleText
    original_amount: MoneyString
    original_currency: CurrencyCode
    occurred_at: datetime
    participant_refs: list[ParticipantRef] = Field(min_length=1, max_length=32)
    financial_locked: bool
    expense_version: ExpenseVersion
    observed_at: datetime
    context_version: Annotated[int, Field(strict=True, ge=1)]

    @field_validator("original_amount")
    @classmethod
    def positive_original_amount(cls, value: str) -> str:
        _money(value, positive=True)
        return value

    @field_validator("occurred_at", "observed_at")
    @classmethod
    def datetimes_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("date-time must include a timezone")
        return value


class DebtFact(ContractModel):
    kind: Literal["debt"]
    evidence_ref: DebtEvidenceRef
    debtor_ref: ParticipantRef
    creditor_ref: ParticipantRef
    amount: MoneyString
    currency: CurrencyCode
    observed_at: datetime
    context_version: Annotated[int, Field(strict=True, ge=1)]

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, value: str) -> str:
        _money(value, positive=True)
        return value

    @field_validator("observed_at")
    @classmethod
    def observed_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value


class ActivityListResult(ContractModel):
    kind: Literal["activities"]
    items: list[ActivityFact] = Field(max_length=16)


class ExpenseListResult(ContractModel):
    kind: Literal["expenses"]
    items: list[ExpenseFact] = Field(max_length=16)


class DebtListResult(ContractModel):
    kind: Literal["debts"]
    items: list[DebtFact] = Field(max_length=16)


ReadResultBody = Annotated[
    Union[ActivityListResult, ExpenseListResult, DebtListResult],
    Field(discriminator="kind"),
]


class ReadOperation(ContractEnum):
    ACTIVITIES = "read.activities"
    EXPENSES = "read.expenses"
    DEBTS = "read.debts"


class ReadResultRef(ContractEnum):
    R01 = "read_result_1"
    R02 = "read_result_2"
    R03 = "read_result_3"
    R04 = "read_result_4"
    R05 = "read_result_5"
    R06 = "read_result_6"
    R07 = "read_result_7"
    R08 = "read_result_8"
    R09 = "read_result_9"
    R10 = "read_result_10"
    R11 = "read_result_11"
    R12 = "read_result_12"
    R13 = "read_result_13"
    R14 = "read_result_14"
    R15 = "read_result_15"
    R16 = "read_result_16"


class ResolvedReadResultCandidate(ContractModel):
    result_ref: ReadResultRef
    result_id: uuid.UUID
    operation: ReadOperation
    observed_at: datetime
    context_version: Annotated[int, Field(strict=True, ge=1)]

    @model_validator(mode="after")
    def timestamp_is_aware(self) -> "ResolvedReadResultCandidate":
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("read result candidate observed_at must be timezone-aware")
        return self


class BoundReadResultReference(ContractModel):
    result_ref: ReadResultRef
    result_id: uuid.UUID
    source_turn_id: TurnId
    operation: ReadOperation
    observed_at: datetime
    context_version: Annotated[int, Field(strict=True, ge=1)]

    @model_validator(mode="after")
    def timestamp_is_aware(self) -> "BoundReadResultReference":
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("bound read result observed_at must be timezone-aware")
        return self


def bind_stable_read_results(
    existing: list[BoundReadResultReference],
    candidates: list[ResolvedReadResultCandidate],
    *,
    source_turn_id: TurnId,
) -> list[BoundReadResultReference]:
    """Persist model-visible result tokens against immutable full result identities."""
    result = list(existing)
    by_id: dict[uuid.UUID, BoundReadResultReference] = {}
    by_ref: dict[ReadResultRef, BoundReadResultReference] = {}
    for item in result:
        if item.source_turn_id != source_turn_id:
            raise ValueError("read result bindings cannot be imported from another Turn")
        if item.result_id in by_id or item.result_ref in by_ref:
            raise ValueError("persisted read result ids and tokens are unique within a Turn")
        by_id[item.result_id] = item
        by_ref[item.result_ref] = item
    candidate_ids: set[uuid.UUID] = set()
    candidate_refs: set[ReadResultRef] = set()
    for candidate in candidates:
        if candidate.result_id in candidate_ids or candidate.result_ref in candidate_refs:
            raise ValueError("candidate read result ids and tokens must be unique")
        candidate_ids.add(candidate.result_id)
        candidate_refs.add(candidate.result_ref)
        previous = by_id.get(candidate.result_id)
        if previous is not None:
            if (
                previous.result_ref != candidate.result_ref
                or previous.operation != candidate.operation
                or previous.observed_at != candidate.observed_at
                or previous.context_version != candidate.context_version
            ):
                raise ValueError("a stable result id cannot change token, operation, freshness, or version")
            continue
        if candidate.result_ref in by_ref:
            raise ValueError("a stable read result token cannot be rebound to another result id")
        bound = BoundReadResultReference(
            result_ref=candidate.result_ref,
            result_id=candidate.result_id,
            source_turn_id=source_turn_id,
            operation=candidate.operation,
            observed_at=candidate.observed_at,
            context_version=candidate.context_version,
        )
        result.append(bound)
        by_id[bound.result_id] = bound
        by_ref[bound.result_ref] = bound
    return result


class ToolReadResult(ContractModel):
    """Trusted adapter output, not model output; includes full typed data and freshness."""

    result_id: uuid.UUID
    result_ref: ReadResultRef
    operation: ReadOperation
    observed_at: datetime
    context_version: Annotated[int, Field(strict=True, ge=1)]
    simulation: bool
    body: ReadResultBody

    @model_validator(mode="after")
    def operation_matches_body(self) -> "ToolReadResult":
        expected = {
            ReadOperation.ACTIVITIES: "activities",
            ReadOperation.EXPENSES: "expenses",
            ReadOperation.DEBTS: "debts",
        }[self.operation]
        if self.body.kind != expected:
            raise ValueError("read operation and result body kind must match")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        for item in self.body.items:
            if item.context_version != self.context_version:
                raise ValueError("all returned facts must use the result context_version")
            if item.observed_at != self.observed_at:
                raise ValueError("all returned facts must use the result observed_at")
        return self


class ModelReadResult(ContractModel):
    """Model-visible complete facts; service UUIDs stay in the private Turn binding map."""

    result_ref: ReadResultRef
    operation: ReadOperation
    observed_at: datetime
    context_version: Annotated[int, Field(strict=True, ge=1)]
    simulation: bool
    body: ReadResultBody

    @model_validator(mode="after")
    def result_is_complete_and_consistent(self) -> "ModelReadResult":
        expected = {
            ReadOperation.ACTIVITIES: "activities",
            ReadOperation.EXPENSES: "expenses",
            ReadOperation.DEBTS: "debts",
        }[self.operation]
        if self.body.kind != expected:
            raise ValueError("read operation and model-visible result body kind must match")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        for item in self.body.items:
            if item.context_version != self.context_version or item.observed_at != self.observed_at:
                raise ValueError("result facts must match observed_at and context_version")
        return self


class ReadActivitiesCriteria(ContractModel):
    kind: Literal["activities"]
    status: Literal["active", "archived", "any"] = "active"
    name_contains: Optional[ShortText] = None


class ReadExpensesCriteria(ContractModel):
    kind: Literal["expenses"]
    activity_ref: ActivityRef
    from_date: Optional[date] = None
    to_date: Optional[date] = None
    participant_ref: Optional[ParticipantRef] = None

    @model_validator(mode="after")
    def dates_are_ordered(self) -> "ReadExpensesCriteria":
        if self.from_date is not None and self.to_date is not None and self.from_date > self.to_date:
            raise ValueError("from_date must be on or before to_date")
        return self


class ReadDebtsCriteria(ContractModel):
    kind: Literal["debts"]
    activity_ref: ActivityRef
    participant_ref: Optional[ParticipantRef] = None
    currency: Optional[CurrencyCode] = None


ReadCriteria = Annotated[
    Union[ReadActivitiesCriteria, ReadExpensesCriteria, ReadDebtsCriteria],
    Field(discriminator="kind"),
]


class PaymentAllocation(ContractModel):
    participant_ref: ParticipantRef
    amount: MoneyString

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, value: str) -> str:
        _money(value, positive=True)
        return value


class ManualSplitAllocation(ContractModel):
    participant_ref: ParticipantRef
    amount: MoneyString

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, value: str) -> str:
        _money(value, positive=True)
        return value


class EqualSplitIntent(ContractModel):
    mode: Literal["equal"]
    participant_refs: list[ParticipantRef] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_participants(self) -> "EqualSplitIntent":
        if len(self.participant_refs) != len(set(self.participant_refs)):
            raise ValueError("participant references must be unique")
        return self


class ManualSplitIntent(ContractModel):
    mode: Literal["manual"]
    allocations: list[ManualSplitAllocation] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_participants(self) -> "ManualSplitIntent":
        refs = [item.participant_ref for item in self.allocations]
        if len(refs) != len(set(refs)):
            raise ValueError("split participant references must be unique")
        return self


SplitIntent = Annotated[
    Union[EqualSplitIntent, ManualSplitIntent],
    Field(discriminator="mode"),
]


class ExpenseCreateIntent(ContractModel):
    kind: Literal["expense.create"]
    ledger_unit_ref: LedgerUnitRef
    title: TitleText
    original_amount: MoneyString
    original_currency: CurrencyCode
    payment_allocations: list[PaymentAllocation] = Field(min_length=1, max_length=32)
    split: SplitIntent
    occurred_at: Optional[datetime] = None
    note: Optional[NoteText] = None

    @model_validator(mode="after")
    def amounts_and_references_are_valid(self) -> "ExpenseCreateIntent":
        amount = _money(self.original_amount, positive=True)
        payer_refs = [item.participant_ref for item in self.payment_allocations]
        if len(payer_refs) != len(set(payer_refs)):
            raise ValueError("payment participant references must be unique")
        if sum((_money(item.amount, positive=True) for item in self.payment_allocations), Decimal("0")) != amount:
            raise ValueError("payment allocations must sum exactly to original_amount")
        if isinstance(self.split, ManualSplitIntent):
            split_refs = [item.participant_ref for item in self.split.allocations]
            if len(split_refs) != len(set(split_refs)):
                raise ValueError("split participant references must be unique")
            if sum((_money(item.amount, positive=True) for item in self.split.allocations), Decimal("0")) != amount:
                raise ValueError("manual split allocations must sum exactly to original_amount")
        if self.occurred_at is not None and (
            self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None
        ):
            raise ValueError("occurred_at must include a timezone")
        return self


class ExpenseUpdateIntent(ContractModel):
    kind: Literal["expense.update"]
    expense_ref: ExpenseRef
    title: Optional[TitleText] = None
    original_amount: Optional[MoneyString] = None
    original_currency: Optional[CurrencyCode] = None
    payment_allocations: Optional[list[PaymentAllocation]] = Field(default=None, min_length=1, max_length=32)
    split: Optional[SplitIntent] = None
    note: Optional[NoteText] = None
    occurred_at: Optional[datetime] = None

    @model_validator(mode="after")
    def nonempty_and_consistent(self) -> "ExpenseUpdateIntent":
        mutable = (
            self.title,
            self.original_amount,
            self.original_currency,
            self.payment_allocations,
            self.split,
            self.note,
            self.occurred_at,
        )
        if all(value is None for value in mutable):
            raise ValueError("expense update must change at least one allowed field")
        amount = _money(self.original_amount, positive=True) if self.original_amount is not None else None
        if self.payment_allocations is not None:
            refs = [item.participant_ref for item in self.payment_allocations]
            if len(refs) != len(set(refs)):
                raise ValueError("payment participant references must be unique")
            if amount is not None and sum(
                (_money(item.amount, positive=True) for item in self.payment_allocations), Decimal("0")
            ) != amount:
                raise ValueError("payment allocations must sum exactly to original_amount")
        if isinstance(self.split, ManualSplitIntent) and amount is not None:
            if sum(
                (_money(item.amount, positive=True) for item in self.split.allocations), Decimal("0")
            ) != amount:
                raise ValueError("manual split allocations must sum exactly to original_amount")
        if self.occurred_at is not None and (
            self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None
        ):
            raise ValueError("occurred_at must include a timezone")
        return self


class ExpensePresentationUpdateIntent(ContractModel):
    kind: Literal["expense.presentation.update"]
    expense_ref: ExpenseRef
    title: Optional[TitleText] = None
    note: Optional[NoteText] = None
    icon_key: Optional[Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z0-9_]{1,48}$")]] = None

    @model_validator(mode="after")
    def nonempty(self) -> "ExpensePresentationUpdateIntent":
        if self.title is None and self.note is None and self.icon_key is None:
            raise ValueError("presentation update must change at least one allowed field")
        return self


class AnswerDecision(ContractModel):
    kind: Literal["answer"]
    basis: Literal["grounded", "conversation"]
    text: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2000)]
    citations: list[EvidenceCitation] = Field(max_length=16)

    @field_validator("text")
    @classmethod
    def safe_answer(cls, value: str) -> str:
        return _no_url(value)

    @model_validator(mode="after")
    def citations_unique(self) -> "AnswerDecision":
        if len(self.citations) != len(set(self.citations)):
            raise ValueError("citations must be unique")
        if self.basis == "grounded" and not self.citations:
            raise ValueError("grounded answers require at least one fact or policy citation")
        if self.basis == "conversation" and self.citations:
            raise ValueError("conversation-only answers cannot claim business evidence")
        return self


class ClarificationSlot(ContractEnum):
    ACTIVITY = "activity_ref"
    LEDGER_UNIT = "ledger_unit_ref"
    EXPENSE = "expense_ref"
    AMOUNT = "original_amount"
    CURRENCY = "original_currency"
    PAYMENT_ALLOCATIONS = "payment_allocations"
    TITLE = "title"
    SPLIT = "split"
    SPLIT_PARTICIPANTS = "split_participant_refs"
    NOTE = "note"
    ICON_KEY = "icon_key"
    UPDATE_FIELDS = "update_fields"


class ClarifyDecision(ContractModel):
    kind: Literal["clarify"]
    prompt: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=1000)]
    missing_slots: list[ClarificationSlot] = Field(min_length=1, max_length=8)

    @field_validator("prompt")
    @classmethod
    def safe_prompt(cls, value: str) -> str:
        return _no_url(value)

    @model_validator(mode="after")
    def unique_slots(self) -> "ClarifyDecision":
        if len(self.missing_slots) != len(set(self.missing_slots)):
            raise ValueError("missing_slots must be unique")
        return self


class ReadDecision(ContractModel):
    kind: Literal["read"]
    operation: ReadOperation
    criteria: ReadCriteria

    @model_validator(mode="after")
    def operation_matches_criteria(self) -> "ReadDecision":
        expected = {
            ReadOperation.ACTIVITIES: "activities",
            ReadOperation.EXPENSES: "expenses",
            ReadOperation.DEBTS: "debts",
        }[self.operation]
        if self.criteria.kind != expected:
            raise ValueError("read operation and criteria kind must match")
        return self


WriteOperation = Literal[
    "expense.create",
    "expense.update",
    "expense.presentation.update",
]
WriteIntent = Annotated[
    Union[
        ExpenseCreateIntent,
        ExpenseUpdateIntent,
        ExpensePresentationUpdateIntent,
    ],
    Field(discriminator="kind"),
]


class ProposeDecision(ContractModel):
    kind: Literal["propose"]
    operation: WriteOperation
    fields: WriteIntent

    @model_validator(mode="after")
    def operation_matches_fields(self) -> "ProposeDecision":
        if self.operation != self.fields.kind:
            raise ValueError("proposal operation must match its dedicated fields schema")
        return self


SemanticDecision = Annotated[
    Union[AnswerDecision, ClarifyDecision, ReadDecision, ProposeDecision],
    Field(discriminator="kind"),
]
SEMANTIC_DECISION_ADAPTER = TypeAdapter(SemanticDecision)


class PriorMessage(ContractModel):
    role: Literal["user", "assistant"]
    text: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2000)]

    @field_validator("text")
    @classmethod
    def safe_text(cls, value: str) -> str:
        return _safe_text(value)


class ModelContext(ContractModel):
    """Only Harness-assembled facts and permissions are exposed to a model call."""

    context_version: Annotated[int, Field(strict=True, ge=1)]
    input_text: StrictText
    verified_scope: ModelVerifiedScope
    recent_messages: list[PriorMessage] = Field(max_length=20)
    pending_slots: list[ClarificationSlot] = Field(max_length=8)
    bound_references: list[ModelReference] = Field(max_length=64)
    read_results: list[ModelReadResult] = Field(max_length=16)
    policy_evidence: list[PolicyEvidence] = Field(max_length=8)
    available_permissions: list[HarnessPermission] = Field(max_length=16)

    @field_validator("input_text")
    @classmethod
    def input_is_safe_for_model(cls, value: str) -> str:
        return _safe_text(value)

    @model_validator(mode="after")
    def references_and_permissions_are_consistent(self) -> "ModelContext":
        refs = [reference.ref for reference in self.bound_references]
        if len(refs) != len(set(refs)):
            raise ValueError("a context cannot bind a typed reference more than once")
        if set(self.available_permissions) != set(self.verified_scope.permissions):
            raise ValueError("model permissions must exactly mirror the Harness-verified scope")
        result_refs = [result.result_ref for result in self.read_results]
        if len(result_refs) != len(set(result_refs)):
            raise ValueError("each full result body needs its own stable model-visible result ref")
        evidence_refs = [
            fact.evidence_ref
            for result in self.read_results
            for fact in result.body.items
        ] + [item.evidence_ref for item in self.policy_evidence]
        if len(evidence_refs) != len(set(evidence_refs)):
            raise ValueError("a context cannot bind the same evidence reference to multiple facts")
        ref_index = {reference.ref: reference for reference in self.bound_references}
        if isinstance(self.verified_scope, ModelActivityScope):
            if not isinstance(ref_index.get(self.verified_scope.activity_ref), ModelActivityReference):
                raise ValueError("verified activity scope must be represented by a bound activity ref")
        for result in self.read_results:
            for fact in result.body.items:
                if isinstance(fact, ActivityFact):
                    if not isinstance(ref_index.get(fact.activity_ref), ModelActivityReference):
                        raise ValueError("activity facts require a type-matched bound activity reference")
                elif isinstance(fact, ExpenseFact):
                    if not isinstance(ref_index.get(fact.expense_ref), ModelExpenseReference):
                        raise ValueError("expense facts require a type-matched bound expense reference")
                    if any(not isinstance(ref_index.get(ref), ModelParticipantReference) for ref in fact.participant_refs):
                        raise ValueError("expense participants require type-matched bound references")
                elif any(
                    not isinstance(ref_index.get(ref), ModelParticipantReference)
                    for ref in (fact.debtor_ref, fact.creditor_ref)
                ):
                    raise ValueError("debt participants require type-matched bound references")
        if isinstance(self.verified_scope, ModelNoActivityScope):
            if any(reference.kind != "activity" for reference in self.bound_references):
                raise ValueError("entity references require a Harness-verified activity scope")
        return self


def validate_model_context_bindings(
    context: ModelContext,
    *,
    source_turn_id: TurnId,
    bound_references: list[BoundReference],
    bound_evidence_references: list[BoundEvidenceReference],
    bound_read_results: list[BoundReadResultReference],
) -> None:
    """Check the model-visible projection against this Turn's persisted typed bindings.

    UUIDs and result IDs stay on the Harness side. The model receives only stable refs;
    this boundary check makes sure those refs still resolve to the same typed source,
    scope, result body, observation time, and context version after resume/restart.
    """
    if any(item.source_turn_id != source_turn_id for item in bound_references):
        raise ValueError("entity references cannot be imported across Turns")
    if any(item.source_turn_id != source_turn_id for item in bound_evidence_references):
        raise ValueError("evidence references cannot be imported across Turns")
    if any(item.source_turn_id != source_turn_id for item in bound_read_results):
        raise ValueError("read result references cannot be imported across Turns")

    expected_refs = {
        (item.kind, item.ref.value)
        for item in model_reference_tokens(bound_references)
    }
    visible_refs = {(item.kind, item.ref.value) for item in context.bound_references}
    if visible_refs != expected_refs or len(visible_refs) != len(context.bound_references):
        raise ValueError("ModelContext references must exactly project this Turn's persisted reference whitelist")
    reference_index = {item.ref: item for item in bound_references}
    evidence_index = {item.evidence_ref: item for item in bound_evidence_references}
    result_index = {item.result_ref: item for item in bound_read_results}
    if len(reference_index) != len(bound_references):
        raise ValueError("persisted typed entity refs must be unique within a Turn")
    if len(evidence_index) != len(bound_evidence_references):
        raise ValueError("persisted typed evidence refs must be unique within a Turn")
    if len(result_index) != len(bound_read_results):
        raise ValueError("persisted typed read-result refs must be unique within a Turn")

    scope_activity_id: Optional[uuid.UUID] = None
    if isinstance(context.verified_scope, ModelActivityScope):
        scoped_activity = reference_index.get(context.verified_scope.activity_ref)
        if not isinstance(scoped_activity, BoundActivityReference):
            raise ValueError("verified activity scope must resolve to its persisted Activity binding")
        scope_activity_id = scoped_activity.entity_id
        if any(item.scope_activity_id != scope_activity_id for item in bound_references):
            raise ValueError("all entity bindings exposed in one activity context must share its verified scope")

    for visible_result in context.read_results:
        stored_result = result_index.get(visible_result.result_ref)
        if stored_result is None or (
            stored_result.operation != visible_result.operation
            or stored_result.observed_at != visible_result.observed_at
            or stored_result.context_version != visible_result.context_version
        ):
            raise ValueError("visible read result must match its immutable persisted result binding")
        for fact in visible_result.body.items:
            stored_evidence = evidence_index.get(fact.evidence_ref)
            expected_kind = fact.kind
            if stored_evidence is None or stored_evidence.kind != expected_kind:
                raise ValueError("visible fact needs a type-matched persisted evidence binding")
            if (
                stored_evidence.source_result_id != stored_result.result_id
                or stored_evidence.context_version != visible_result.context_version
                or stored_evidence.scope_activity_id != (
                    scope_activity_id if scope_activity_id is not None else stored_evidence.scope_activity_id
                )
            ):
                raise ValueError("fact evidence must bind to this result, version, and verified scope")
            if isinstance(fact, ActivityFact):
                activity_binding = reference_index.get(fact.activity_ref)
                if not isinstance(activity_binding, BoundActivityReference) or (
                    activity_binding.entity_id != stored_evidence.entity_id
                    or activity_binding.scope_activity_id != stored_evidence.scope_activity_id
                ):
                    raise ValueError("activity evidence must bind to the matching typed Activity reference")
            elif isinstance(fact, ExpenseFact):
                expense_binding = reference_index.get(fact.expense_ref)
                if not isinstance(expense_binding, BoundExpenseReference) or (
                    expense_binding.entity_id != stored_evidence.entity_id
                    or expense_binding.scope_activity_id != stored_evidence.scope_activity_id
                ):
                    raise ValueError("expense evidence must bind to the matching typed Expense reference")
                for participant_ref in fact.participant_refs:
                    participant = reference_index.get(participant_ref)
                    if not isinstance(participant, BoundParticipantReference) or (
                        participant.scope_activity_id != stored_evidence.scope_activity_id
                    ):
                        raise ValueError("expense participants must be persisted in the same verified scope")
            elif isinstance(fact, DebtFact):
                for participant_ref in (fact.debtor_ref, fact.creditor_ref):
                    participant = reference_index.get(participant_ref)
                    if not isinstance(participant, BoundParticipantReference) or (
                        participant.scope_activity_id != stored_evidence.scope_activity_id
                    ):
                        raise ValueError("debt participants must be persisted in the same verified scope")


def validate_decision_against_context(decision: SemanticDecision, context: ModelContext) -> None:
    """Deterministic Harness checks that require the current, verified model context."""
    validate_capability_registry(CAPABILITY_REGISTRY)
    ref_index = {reference.ref: reference for reference in context.bound_references}
    if isinstance(decision, AnswerDecision):
        available = {
            item.evidence_ref
            for result in context.read_results
            for item in result.body.items
        } | {item.evidence_ref for item in context.policy_evidence}
        if not set(decision.citations).issubset(available):
            raise ValueError("answer citations must refer to facts in this exact context")
        if decision.basis == "grounded" and not decision.citations:
            raise ValueError("factual or policy answers require current-context evidence")
    elif isinstance(decision, ReadDecision):
        if decision.operation.value not in {operation for operation in CAPABILITY_REGISTRY[0].operations}:
            raise ValueError("read operation is not in the CAP01 allowlist")
        if decision.operation.value not in {permission.value for permission in context.available_permissions}:
            raise ValueError("Harness did not grant this read operation")
        if decision.criteria.kind != "activities":
            scope_ref = decision.criteria.activity_ref
            bound = ref_index.get(scope_ref)
            if not isinstance(bound, ModelActivityReference):
                raise ValueError("read scope must resolve through an activity reference bound in this Turn")
    elif isinstance(decision, ProposeDecision):
        owning_capability = "CAP07" if decision.operation == "expense.create" else "CAP08"
        registry_entry = next(entry for entry in CAPABILITY_REGISTRY if entry.capability_id == owning_capability)
        if decision.operation not in registry_entry.operations or registry_entry.availability != CapabilityAvailability.MOCK_PROPOSAL_ONLY:
            raise ValueError("write proposal is not enabled by the fixed operation registry")
        needed = {
            "expense.create": HarnessPermission.PROPOSE_EXPENSE_CREATE,
            "expense.update": HarnessPermission.PROPOSE_EXPENSE_UPDATE,
            "expense.presentation.update": HarnessPermission.PROPOSE_EXPENSE_PRESENTATION_UPDATE,
        }[decision.operation]
        if needed not in context.available_permissions:
            raise ValueError("Harness did not grant this proposal operation")
        field_values: list[Union[ActivityRef, LedgerUnitRef, ExpenseRef, ParticipantRef]] = []
        if isinstance(decision.fields, ExpenseCreateIntent):
            field_values.append(decision.fields.ledger_unit_ref)
            field_values.extend(item.participant_ref for item in decision.fields.payment_allocations)
            if isinstance(decision.fields.split, EqualSplitIntent):
                field_values.extend(decision.fields.split.participant_refs)
            else:
                field_values.extend(item.participant_ref for item in decision.fields.split.allocations)
        else:
            field_values.append(decision.fields.expense_ref)
            if isinstance(decision.fields, ExpenseUpdateIntent):
                if decision.fields.payment_allocations is not None:
                    field_values.extend(item.participant_ref for item in decision.fields.payment_allocations)
                if isinstance(decision.fields.split, EqualSplitIntent):
                    field_values.extend(decision.fields.split.participant_refs)
                elif isinstance(decision.fields.split, ManualSplitIntent):
                    field_values.extend(item.participant_ref for item in decision.fields.split.allocations)
        for reference in field_values:
            if reference not in ref_index:
                raise ValueError("proposal references must be bound in this Turn context")
        if isinstance(decision.fields, ExpenseUpdateIntent):
            target = ref_index.get(decision.fields.expense_ref)
            if not isinstance(target, ModelExpenseReference):
                raise ValueError("expense update target must be a bound expense reference")
            locked = any(
                isinstance(fact, ExpenseFact)
                and fact.expense_ref == decision.fields.expense_ref
                and fact.financial_locked
                for result in context.read_results
                for fact in result.body.items
            )
            if locked:
                raise ValueError("financially locked Expense cannot receive a financial update proposal")


class TurnState(ContractEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAIT_INPUT = "WAIT_INPUT"
    WAIT_CONFIRM = "WAIT_CONFIRM"
    EXECUTING = "EXECUTING"
    RECOVERING = "RECOVERING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class TurnStep(ContractEnum):
    ACCEPTED = "accepted"
    BUILD_CONTEXT = "build_context"
    MODEL_DECISION = "model_decision"
    TOOL_READ = "tool_read"
    PREPARE_PROPOSAL = "prepare_proposal"
    AWAITING_USER = "awaiting_user"
    AUTH_REQUIRED = "auth_required"
    DISPATCH = "dispatch"
    RECONCILE = "reconcile"
    FINALIZE = "finalize"
    TERMINAL = "terminal"


class WaitReason(ContractEnum):
    MISSING_FIELDS = "missing_fields"
    AUTH_REQUIRED = "auth_required"
    CONFIRM_REQUIRED = "confirm_required"
    EXECUTION_RESULT_UNKNOWN = "execution_result_unknown"


class ResumeState(ContractEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAIT_CONFIRM = "WAIT_CONFIRM"
    EXECUTING = "EXECUTING"
    RECOVERING = "RECOVERING"


class ExecutionResolution(ContractEnum):
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class ProposalStatus(ContractEnum):
    PENDING = "pending"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    CLOSED = "closed"


class ExecutionIdentity(ContractModel):
    execution_id: uuid.UUID
    actor_id: UserId
    proposal_id: ProposalId
    proposal_revision: Annotated[int, Field(strict=True, ge=1)]
    operations_version: Literal["1.0.0"] = OPERATIONS_VERSION

    @model_validator(mode="after")
    def id_is_reproducible(self) -> "ExecutionIdentity":
        if self.execution_id != derive_execution_id(
            self.actor_id,
            self.proposal_id,
            self.proposal_revision,
            self.operations_version,
        ):
            raise ValueError("execution_id must be derived from the stable identity inputs")
        return self


class ExecutionReference(ContractModel):
    execution_id: uuid.UUID
    proposal_id: ProposalId
    proposal_revision: Annotated[int, Field(strict=True, ge=1)]
    operations_version: Literal["1.0.0"] = OPERATIONS_VERSION


class TurnStateSnapshot(ContractModel):
    turn_id: TurnId
    session_id: SessionId
    owner_user_id: UserId
    state: TurnState
    step: TurnStep
    wait_reason: Optional[WaitReason] = None
    resume_state: Optional[ResumeState] = None
    state_revision: Annotated[int, Field(strict=True, ge=1)]
    execution: Optional[ExecutionIdentity] = None
    execution_resolution: Optional[ExecutionResolution] = None
    context_version: Annotated[int, Field(strict=True, ge=1)]

    @model_validator(mode="after")
    def state_identity_invariants(self) -> "TurnStateSnapshot":
        has_execution = self.execution is not None
        if has_execution and self.execution.actor_id != self.owner_user_id:
            raise ValueError("execution actor must be the owning authenticated user")
        if self.state in (TurnState.QUEUED, TurnState.RUNNING) and has_execution:
            raise ValueError("a Turn with execution_id must never return to model planning")
        if self.state == TurnState.WAIT_INPUT:
            if self.wait_reason not in (WaitReason.MISSING_FIELDS, WaitReason.AUTH_REQUIRED):
                raise ValueError("WAIT_INPUT requires missing_fields or auth_required")
            if self.resume_state is None:
                raise ValueError("WAIT_INPUT requires resume_state")
            if self.wait_reason == WaitReason.MISSING_FIELDS and has_execution:
                raise ValueError("clarification cannot resume an already assigned execution")
            if self.wait_reason == WaitReason.MISSING_FIELDS and self.resume_state not in (
                ResumeState.QUEUED,
                ResumeState.RUNNING,
            ):
                raise ValueError("clarification resumes only a saved planning checkpoint")
            if has_execution and self.resume_state != ResumeState.RECOVERING:
                raise ValueError("execution identity forces auth recovery through RECOVERING")
            if not has_execution and self.wait_reason == WaitReason.AUTH_REQUIRED:
                if self.resume_state not in (
                    ResumeState.RUNNING,
                    ResumeState.QUEUED,
                    ResumeState.WAIT_CONFIRM,
                ):
                    raise ValueError("auth recovery resumes the exact saved planning or confirmation checkpoint")
        elif self.state == TurnState.WAIT_CONFIRM:
            if self.wait_reason != WaitReason.CONFIRM_REQUIRED or self.step != TurnStep.AWAITING_USER:
                raise ValueError("WAIT_CONFIRM requires confirm_required and awaiting_user")
            if self.resume_state is not None:
                raise ValueError("WAIT_CONFIRM does not have a resume_state")
            if has_execution:
                raise ValueError("an unconfirmed proposal cannot have execution_id")
        elif self.wait_reason is not None or self.resume_state is not None:
            raise ValueError("wait_reason and resume_state exist only in WAIT_INPUT or WAIT_CONFIRM")
        if self.state == TurnState.WAIT_INPUT and self.wait_reason == WaitReason.AUTH_REQUIRED:
            if self.step != TurnStep.AUTH_REQUIRED:
                raise ValueError("auth wait requires auth_required step")
        if self.state == TurnState.WAIT_INPUT and self.wait_reason == WaitReason.MISSING_FIELDS:
            if self.step != TurnStep.AWAITING_USER:
                raise ValueError("clarification wait requires awaiting_user step")
        if self.state == TurnState.EXECUTING:
            if not has_execution or self.step != TurnStep.DISPATCH:
                raise ValueError("EXECUTING requires a fixed execution identity and dispatch step")
            if self.execution_resolution is not None:
                raise ValueError("EXECUTING has no terminal resolution")
        if self.state == TurnState.RECOVERING:
            if not has_execution or self.step != TurnStep.RECONCILE:
                raise ValueError("RECOVERING requires the original execution identity")
            if self.execution_resolution not in (None, ExecutionResolution.UNKNOWN):
                raise ValueError("RECOVERING may only have an unresolved or unknown outcome")
        if self.execution_resolution == ExecutionResolution.UNKNOWN:
            recovering_or_auth_paused = self.state == TurnState.RECOVERING or (
                self.state == TurnState.WAIT_INPUT
                and has_execution
                and self.wait_reason == WaitReason.AUTH_REQUIRED
                and self.resume_state == ResumeState.RECOVERING
            )
            if not recovering_or_auth_paused:
                raise ValueError("unknown execution outcomes remain recoverable and never become FAILED")
        if self.state == TurnState.COMPLETED:
            if self.step != TurnStep.TERMINAL:
                raise ValueError("terminal states require terminal step")
            if has_execution and self.execution_resolution != ExecutionResolution.SUCCEEDED:
                raise ValueError("completed execution requires a durable succeeded result")
        if self.state == TurnState.FAILED:
            if self.step != TurnStep.TERMINAL:
                raise ValueError("terminal states require terminal step")
            if has_execution and self.execution_resolution != ExecutionResolution.REJECTED:
                raise ValueError("failed execution requires a durable rejected result")
            if self.execution_resolution == ExecutionResolution.UNKNOWN:
                raise ValueError("unknown execution outcomes cannot be FAILED")
        if self.state == TurnState.CANCELLED:
            if self.step != TurnStep.TERMINAL:
                raise ValueError("terminal states require terminal step")
            if has_execution and self.execution_resolution != ExecutionResolution.CLOSED:
                raise ValueError("an assigned execution can be cancelled only after durable close")
        if not has_execution and self.execution_resolution is not None:
            raise ValueError("execution resolution requires execution identity")
        if self.state in (TurnState.QUEUED, TurnState.RUNNING) and self.step in (
            TurnStep.DISPATCH,
            TurnStep.RECONCILE,
        ):
            raise ValueError("dispatch/reconcile steps cannot return to model planning")
        return self


class TurnPublicStatus(ContractModel):
    """Client-visible state; owner identity and private bindings remain server-side."""

    turn_id: TurnId
    session_id: SessionId
    state: TurnState
    step: TurnStep
    wait_reason: Optional[WaitReason] = None
    resume_state: Optional[ResumeState] = None
    state_revision: Annotated[int, Field(strict=True, ge=1)]
    execution_assigned: bool
    execution_resolution: Optional[ExecutionResolution] = None
    context_version: Annotated[int, Field(strict=True, ge=1)]

    @model_validator(mode="after")
    def state_matches_wait_metadata(self) -> "TurnPublicStatus":
        if self.state == TurnState.WAIT_INPUT:
            if self.wait_reason not in (WaitReason.MISSING_FIELDS, WaitReason.AUTH_REQUIRED) or self.resume_state is None:
                raise ValueError("public WAIT_INPUT requires its wait_reason and resume_state")
        elif self.state == TurnState.WAIT_CONFIRM:
            if self.wait_reason != WaitReason.CONFIRM_REQUIRED or self.resume_state is not None:
                raise ValueError("public WAIT_CONFIRM requires confirm_required and no resume_state")
        elif self.wait_reason is not None or self.resume_state is not None:
            raise ValueError("wait metadata is exposed only in a waiting state")
        if self.state in (TurnState.QUEUED, TurnState.RUNNING) and self.execution_assigned:
            raise ValueError("public execution identity cannot return to planning states")
        if self.state == TurnState.EXECUTING and (not self.execution_assigned or self.step != TurnStep.DISPATCH):
            raise ValueError("public EXECUTING requires the assigned identity and dispatch step")
        if self.state == TurnState.RECOVERING and (not self.execution_assigned or self.step != TurnStep.RECONCILE):
            raise ValueError("public RECOVERING requires the original assigned identity")
        if self.state in (TurnState.COMPLETED, TurnState.CANCELLED, TurnState.FAILED) and self.step != TurnStep.TERMINAL:
            raise ValueError("public terminal states require terminal step")
        if self.execution_resolution == ExecutionResolution.UNKNOWN:
            recovering_or_auth_paused = self.state == TurnState.RECOVERING or (
                self.state == TurnState.WAIT_INPUT
                and self.execution_assigned
                and self.wait_reason == WaitReason.AUTH_REQUIRED
                and self.resume_state == ResumeState.RECOVERING
            )
            if not recovering_or_auth_paused:
                raise ValueError("unknown execution result cannot be presented as terminal")
        if self.execution_resolution is not None and not self.execution_assigned:
            raise ValueError("execution resolution requires an assigned execution")
        return self


STATE_TRANSITIONS: dict[str, list[str]] = {
    TurnState.QUEUED.value: [
        TurnState.RUNNING.value,
        TurnState.CANCELLED.value,
        TurnState.FAILED.value,
    ],
    TurnState.RUNNING.value: [
        TurnState.QUEUED.value,
        TurnState.WAIT_INPUT.value,
        TurnState.WAIT_CONFIRM.value,
        TurnState.COMPLETED.value,
        TurnState.CANCELLED.value,
        TurnState.FAILED.value,
    ],
    TurnState.WAIT_INPUT.value: [
        TurnState.QUEUED.value,
        TurnState.RUNNING.value,
        TurnState.WAIT_CONFIRM.value,
        TurnState.RECOVERING.value,
        TurnState.CANCELLED.value,
        TurnState.FAILED.value,
    ],
    TurnState.WAIT_CONFIRM.value: [
        TurnState.WAIT_INPUT.value,
        TurnState.RUNNING.value,
        TurnState.EXECUTING.value,
        TurnState.CANCELLED.value,
        TurnState.FAILED.value,
    ],
    TurnState.EXECUTING.value: [
        TurnState.WAIT_INPUT.value,
        TurnState.RECOVERING.value,
        TurnState.COMPLETED.value,
        TurnState.FAILED.value,
    ],
    TurnState.RECOVERING.value: [
        TurnState.WAIT_INPUT.value,
        TurnState.EXECUTING.value,
        TurnState.COMPLETED.value,
        TurnState.FAILED.value,
        TurnState.CANCELLED.value,
    ],
    TurnState.COMPLETED.value: [],
    TurnState.CANCELLED.value: [],
    TurnState.FAILED.value: [],
}


def validate_state_transition(
    before: TurnStateSnapshot,
    after: TurnStateSnapshot,
    *,
    expected_state_revision: int,
) -> None:
    if expected_state_revision != before.state_revision:
        raise ValueError("state revision precondition failed")
    if after.state_revision != before.state_revision + 1:
        raise ValueError("a successful conditional transition increments state_revision exactly once")
    if before.turn_id != after.turn_id or before.session_id != after.session_id:
        raise ValueError("a transition cannot change Turn or Session identity")
    if before.owner_user_id != after.owner_user_id:
        raise ValueError("a transition cannot change the authenticated owner")
    if after.state.value not in STATE_TRANSITIONS[before.state.value]:
        raise ValueError("state transition is not in the frozen transition table")
    if before.execution is not None:
        if after.execution != before.execution:
            raise ValueError("an assigned execution_id and its inputs are immutable")
        if after.state in (TurnState.QUEUED, TurnState.RUNNING, TurnState.WAIT_CONFIRM):
            raise ValueError("an assigned execution cannot return to planning or confirmation")
        if before.execution_resolution in (ExecutionResolution.SUCCEEDED, ExecutionResolution.REJECTED, ExecutionResolution.CLOSED):
            if after.execution_resolution != before.execution_resolution:
                raise ValueError("a durable execution resolution is immutable")
        if before.execution_resolution == ExecutionResolution.UNKNOWN and after.execution_resolution not in (
            ExecutionResolution.UNKNOWN,
            ExecutionResolution.SUCCEEDED,
            ExecutionResolution.REJECTED,
            ExecutionResolution.CLOSED,
        ):
            raise ValueError("an unknown outcome can only be reconciled under its original execution identity")
    elif after.execution is not None:
        if before.state != TurnState.WAIT_CONFIRM:
            raise ValueError("execution identity can only be assigned from WAIT_CONFIRM after confirmation")
        if after.execution.actor_id != before.owner_user_id:
            raise ValueError("execution identity must use the authenticated owner")


def validate_auth_resume(
    before: TurnStateSnapshot,
    after: TurnStateSnapshot,
    *,
    expected_state_revision: int,
) -> None:
    """Resume exactly the saved auth checkpoint; execution-bound work only returns to RECOVERING."""
    if before.state != TurnState.WAIT_INPUT or before.wait_reason != WaitReason.AUTH_REQUIRED:
        raise ValueError("auth resume requires WAIT_INPUT(auth_required)")
    if before.execution is not None:
        expected_state = TurnState.RECOVERING
        if before.resume_state != ResumeState.RECOVERING:
            raise ValueError("an assigned execution must save RECOVERING as its auth checkpoint")
        if after.execution != before.execution or after.execution_resolution != before.execution_resolution:
            raise ValueError("auth resume preserves the original execution identity and unresolved result")
    else:
        expected_state = TurnState(before.resume_state.value)
        if before.resume_state == ResumeState.RECOVERING:
            raise ValueError("RECOVERING resume state requires an assigned execution identity")
    if after.state != expected_state:
        raise ValueError("auth resume must return to the exact saved state")
    if after.state == TurnState.WAIT_CONFIRM and (
        after.wait_reason != WaitReason.CONFIRM_REQUIRED or after.step != TurnStep.AWAITING_USER
    ):
        raise ValueError("auth resume to WAIT_CONFIRM preserves the waiting proposal checkpoint")
    validate_state_transition(before, after, expected_state_revision=expected_state_revision)


def validate_cancel_transition(
    before: TurnStateSnapshot,
    after: TurnStateSnapshot,
    response: "CancelTurnResponse",
    *,
    expected_state_revision: int,
) -> None:
    """Cancel planning immediately; assigned execution stays reconcilable until durable close."""
    validate_state_transition(before, after, expected_state_revision=expected_state_revision)
    if before.execution is None:
        if after.state != TurnState.CANCELLED or response.result != "cancelled":
            raise ValueError("a Turn without execution identity cancels immediately and ignores late model output")
    elif after.state == TurnState.CANCELLED:
        if after.execution_resolution != ExecutionResolution.CLOSED or response.result != "cancelled":
            raise ValueError("an assigned execution cancels only after durable close")
    elif after.state == TurnState.RECOVERING:
        if response.result != "reconciling" or after.execution != before.execution:
            raise ValueError("an assigned execution remains on the same key while cancellation is reconciled")
    else:
        raise ValueError("cancel cannot return assigned execution work to planning")


class CanonicalPayment(ContractModel):
    participant_id: EntityId
    amount: MoneyString

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, value: str) -> str:
        _money(value, positive=True)
        return value


class CanonicalEqualSplit(ContractModel):
    mode: Literal["equal"]
    participant_ids: list[EntityId] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_participants(self) -> "CanonicalEqualSplit":
        if len(self.participant_ids) != len(set(self.participant_ids)):
            raise ValueError("canonical equal split Participant IDs must be unique")
        return self


class CanonicalManualSplit(ContractModel):
    mode: Literal["manual"]
    allocations: list[CanonicalPayment] = Field(min_length=1, max_length=32)


CanonicalSplit = Annotated[
    Union[CanonicalEqualSplit, CanonicalManualSplit],
    Field(discriminator="mode"),
]


class CanonicalExpenseUpdatePatch(ContractModel):
    """Fully bound expense fields. No semantic refs remain after confirmation."""

    title: Optional[TitleText] = None
    original_amount: Optional[MoneyString] = None
    original_currency: Optional[CurrencyCode] = None
    ledger_unit_id: Optional[EntityId] = None
    payment_allocations: Optional[list[CanonicalPayment]] = Field(default=None, min_length=1, max_length=32)
    split: Optional[CanonicalSplit] = None
    note: Optional[NoteText] = None
    occurred_at: Optional[datetime] = None

    @model_validator(mode="after")
    def nonempty_and_conserved(self) -> "CanonicalExpenseUpdatePatch":
        fields = (
            self.title,
            self.original_amount,
            self.original_currency,
            self.ledger_unit_id,
            self.payment_allocations,
            self.split,
            self.note,
            self.occurred_at,
        )
        if all(value is None for value in fields):
            raise ValueError("canonical Expense update must change at least one field")
        amount = _money(self.original_amount, positive=True) if self.original_amount is not None else None
        if self.payment_allocations is not None:
            refs = [item.participant_id for item in self.payment_allocations]
            if len(refs) != len(set(refs)):
                raise ValueError("canonical payment Participant IDs must be unique")
            if amount is not None and sum(
                (_money(item.amount, positive=True) for item in self.payment_allocations), Decimal("0")
            ) != amount:
                raise ValueError("canonical payments must sum to original_amount")
        if isinstance(self.split, CanonicalManualSplit) and amount is not None:
            refs = [item.participant_id for item in self.split.allocations]
            if len(refs) != len(set(refs)):
                raise ValueError("canonical split Participant IDs must be unique")
            if sum((_money(item.amount, positive=True) for item in self.split.allocations), Decimal("0")) != amount:
                raise ValueError("canonical manual splits must sum to original_amount")
        if isinstance(self.split, CanonicalEqualSplit) and len(self.split.participant_ids) != len(set(self.split.participant_ids)):
            raise ValueError("canonical equal split Participant IDs must be unique")
        if self.occurred_at is not None and (
            self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None
        ):
            raise ValueError("occurred_at must include a timezone")
        return self


class CanonicalExpensePresentationPatch(ContractModel):
    title: Optional[TitleText] = None
    note: Optional[NoteText] = None
    icon_key: Optional[Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z0-9_]{1,48}$")]] = None

    @model_validator(mode="after")
    def nonempty(self) -> "CanonicalExpensePresentationPatch":
        if self.title is None and self.note is None and self.icon_key is None:
            raise ValueError("canonical presentation patch must change at least one field")
        return self


class FixedExpenseCreateCommand(ContractModel):
    operation: Literal["expense.create"]
    activity_id: EntityId
    ledger_unit_id: EntityId
    title: TitleText
    original_amount: MoneyString
    original_currency: CurrencyCode
    payment_allocations: list[CanonicalPayment] = Field(min_length=1, max_length=32)
    split: CanonicalSplit
    occurred_at: Optional[datetime] = None
    note: Optional[NoteText] = None
    expected_financial_version: FinancialVersion

    @model_validator(mode="after")
    def amounts_conserve(self) -> "FixedExpenseCreateCommand":
        amount = _money(self.original_amount, positive=True)
        payer_ids = [item.participant_id for item in self.payment_allocations]
        if len(payer_ids) != len(set(payer_ids)):
            raise ValueError("fixed payment Participant IDs must be unique")
        if sum((_money(item.amount, positive=True) for item in self.payment_allocations), Decimal("0")) != amount:
            raise ValueError("fixed payment allocations must sum to original_amount")
        if isinstance(self.split, CanonicalManualSplit):
            split_ids = [item.participant_id for item in self.split.allocations]
            if len(split_ids) != len(set(split_ids)):
                raise ValueError("fixed manual split Participant IDs must be unique")
            if sum((_money(item.amount, positive=True) for item in self.split.allocations), Decimal("0")) != amount:
                raise ValueError("fixed manual split allocations must sum to original_amount")
        elif len(self.split.participant_ids) != len(set(self.split.participant_ids)):
            raise ValueError("fixed equal split Participant IDs must be unique")
        return self


class FixedExpenseUpdateCommand(ContractModel):
    operation: Literal["expense.update"]
    activity_id: EntityId
    expense_id: EntityId
    expected_expense_version: ExpenseVersion
    expected_financial_version: FinancialVersion
    patch: CanonicalExpenseUpdatePatch


class FixedExpensePresentationCommand(ContractModel):
    operation: Literal["expense.presentation.update"]
    activity_id: EntityId
    expense_id: EntityId
    expected_expense_version: ExpenseVersion
    patch: CanonicalExpensePresentationPatch


FixedCommand = Annotated[
    Union[
        FixedExpenseCreateCommand,
        FixedExpenseUpdateCommand,
        FixedExpensePresentationCommand,
    ],
    Field(discriminator="operation"),
]


class PreconditionSnapshot(ContractModel):
    activity_id: EntityId
    permission_checked: Literal[True]
    agent_disable_revision: Annotated[int, Field(strict=True, ge=0)]
    activity_financial_version: Optional[FinancialVersion] = None
    expense_version: Optional[ExpenseVersion] = None
    policy_version: ShortText
    verified_at: datetime

    @field_validator("verified_at")
    @classmethod
    def verified_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("verified_at must include a timezone")
        return value


DecimalNumberString = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^(0|[1-9][0-9]{0,19})(\.[0-9]{1,10})?$"),
]


class FxSnapshot(ContractModel):
    base_currency: CurrencyCode
    original_currency: CurrencyCode
    rate: DecimalNumberString
    source: Literal["ecb_snapshot", "server_snapshot", "identity"]
    observed_at: datetime

    @field_validator("rate")
    @classmethod
    def positive_rate(cls, value: str) -> str:
        _money(value, positive=True)
        return value

    @field_validator("observed_at")
    @classmethod
    def observed_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value


class ExpenseSnapshot(ContractModel):
    ledger_unit_id: EntityId
    title: TitleText
    original_amount: MoneyString
    original_currency: CurrencyCode
    base_amount: MoneyString
    payment_allocations: list[CanonicalPayment] = Field(min_length=1, max_length=32)
    split: CanonicalSplit
    occurred_at: Optional[datetime] = None
    note: Optional[NoteText] = None
    icon_key: Optional[Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z0-9_]{1,48}$")]] = None
    fx_snapshot: Optional[FxSnapshot] = None
    expense_version: ExpenseVersion
    financial_locked: bool

    @model_validator(mode="after")
    def original_amounts_are_conserved(self) -> "ExpenseSnapshot":
        amount = _money(self.original_amount, positive=True)
        payer_ids = [item.participant_id for item in self.payment_allocations]
        if len(payer_ids) != len(set(payer_ids)):
            raise ValueError("snapshot payment Participant IDs must be unique")
        if sum((_money(item.amount, positive=True) for item in self.payment_allocations), Decimal("0")) != amount:
            raise ValueError("snapshot payments must sum to original_amount")
        if isinstance(self.split, CanonicalManualSplit):
            split_ids = [item.participant_id for item in self.split.allocations]
            if len(split_ids) != len(set(split_ids)):
                raise ValueError("snapshot manual split Participant IDs must be unique")
            if sum((_money(item.amount, positive=True) for item in self.split.allocations), Decimal("0")) != amount:
                raise ValueError("snapshot manual splits must sum to original_amount")
        elif len(self.split.participant_ids) != len(set(self.split.participant_ids)):
            raise ValueError("snapshot equal split Participant IDs must be unique")
        if self.fx_snapshot is not None and self.fx_snapshot.original_currency != self.original_currency:
            raise ValueError("FX snapshot currency must match original_currency")
        if self.occurred_at is not None and (
            self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None
        ):
            raise ValueError("occurred_at must include a timezone")
        return self


class ExpenseTitleChange(ContractModel):
    field: Literal["title"]
    before: Optional[TitleText] = None
    after: Optional[TitleText] = None


class ExpenseAmountChange(ContractModel):
    field: Literal["original_amount", "base_amount"]
    before: Optional[MoneyString] = None
    after: MoneyString


class ExpenseCurrencyChange(ContractModel):
    field: Literal["original_currency"]
    before: Optional[CurrencyCode] = None
    after: CurrencyCode


class ExpenseLedgerUnitChange(ContractModel):
    field: Literal["ledger_unit_id"]
    before: Optional[EntityId] = None
    after: EntityId


class ExpensePaymentsChange(ContractModel):
    field: Literal["payment_allocations"]
    before: Optional[list[CanonicalPayment]] = None
    after: list[CanonicalPayment] = Field(min_length=1, max_length=32)


class ExpenseSplitChange(ContractModel):
    field: Literal["split"]
    before: Optional[CanonicalSplit] = None
    after: CanonicalSplit


class ExpenseNoteChange(ContractModel):
    field: Literal["note"]
    before: Optional[NoteText] = None
    after: Optional[NoteText] = None


class ExpenseOccurredAtChange(ContractModel):
    field: Literal["occurred_at"]
    before: Optional[datetime] = None
    after: Optional[datetime] = None


class ExpenseIconChange(ContractModel):
    field: Literal["icon_key"]
    before: Optional[Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z0-9_]{1,48}$")]] = None
    after: Optional[Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z0-9_]{1,48}$")]] = None


class ExpenseFxChange(ContractModel):
    field: Literal["fx_snapshot"]
    before: Optional[FxSnapshot] = None
    after: Optional[FxSnapshot] = None


ExpenseFieldChange = Annotated[
    Union[
        ExpenseTitleChange,
        ExpenseAmountChange,
        ExpenseCurrencyChange,
        ExpenseLedgerUnitChange,
        ExpensePaymentsChange,
        ExpenseSplitChange,
        ExpenseNoteChange,
        ExpenseOccurredAtChange,
        ExpenseIconChange,
        ExpenseFxChange,
    ],
    Field(discriminator="field"),
]


class ExpensePreview(ContractModel):
    kind: Literal["expense"]
    summary: ShortText
    before: Optional[ExpenseSnapshot] = None
    after: ExpenseSnapshot
    changes: list[ExpenseFieldChange] = Field(min_length=1, max_length=12)
    activity_financial_version: FinancialVersion
    generated_at: datetime
    simulation: bool

    @field_validator("generated_at")
    @classmethod
    def generated_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must include a timezone")
        return value

    @model_validator(mode="after")
    def changes_match_typed_snapshots(self) -> "ExpensePreview":
        tracked = (
            "title",
            "original_amount",
            "base_amount",
            "original_currency",
            "ledger_unit_id",
            "payment_allocations",
            "split",
            "occurred_at",
            "note",
            "icon_key",
            "fx_snapshot",
        )
        values_by_field = {change.field: (change.before, change.after) for change in self.changes}
        if len(values_by_field) != len(self.changes):
            raise ValueError("expense preview lists each changed field once")
        expected: dict[str, tuple[Any, Any]] = {}
        if self.before is None:
            for field_name in tracked:
                after_value = getattr(self.after, field_name)
                if after_value is not None:
                    expected[field_name] = (None, after_value)
        else:
            if self.before.financial_locked != self.after.financial_locked:
                raise ValueError("preview cannot change financial lock state")
            if int(self.after.expense_version) != int(self.before.expense_version) + 1:
                raise ValueError("an Expense update preview increments its expected expense version by one")
            for field_name in tracked:
                before_value = getattr(self.before, field_name)
                after_value = getattr(self.after, field_name)
                if before_value != after_value:
                    expected[field_name] = (before_value, after_value)
        if values_by_field != expected:
            raise ValueError("typed preview changes must exactly match before/after snapshots")
        return self


class SimulationProposalCard(ContractModel):
    card_kind: Literal["simulation_pending"]
    mode: Literal["simulation"]
    status: Literal["pending"]
    proposal_id: ProposalId
    revision: Annotated[int, Field(strict=True, ge=1)]
    operation: WriteOperation
    preview: ExpensePreview
    confirmation_enabled: Literal[False] = False
    simulation: Literal[True] = True

    @model_validator(mode="after")
    def preview_is_simulated(self) -> "SimulationProposalCard":
        if not self.preview.simulation:
            raise ValueError("simulation card preview must be marked simulation")
        return self


class ConfirmableProposalCard(ContractModel):
    card_kind: Literal["backend_pending"]
    mode: Literal["backend"]
    status: Literal["pending"]
    proposal_id: ProposalId
    revision: Annotated[int, Field(strict=True, ge=1)]
    operation: WriteOperation
    command_digest: Sha256Hex
    confirmation_nonce: ConfirmationNonceForCard
    expires_at: datetime
    preview: ExpensePreview
    simulation: Literal[False] = False

    @field_validator("expires_at")
    @classmethod
    def expiration_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expires_at must include a timezone")
        return value

    @model_validator(mode="after")
    def preview_is_live(self) -> "ConfirmableProposalCard":
        if self.preview.simulation:
            raise ValueError("backend confirmable cards cannot use simulated previews")
        return self


class InactiveProposalCard(ContractModel):
    card_kind: Literal["inactive"]
    mode: Literal["backend", "simulation"]
    status: Literal["superseded", "cancelled", "expired", "confirmed", "rejected", "closed"]
    proposal_id: ProposalId
    revision: Annotated[int, Field(strict=True, ge=1)]
    operation: WriteOperation
    command_digest: Optional[Sha256Hex] = None
    preview: Optional[ExpensePreview] = None
    simulation: bool

    @model_validator(mode="after")
    def mode_matches_source(self) -> "InactiveProposalCard":
        if self.simulation != (self.mode == "simulation"):
            raise ValueError("inactive proposal simulation marker must match its trusted source")
        return self


ProposalCard = Annotated[
    Union[SimulationProposalCard, ConfirmableProposalCard, InactiveProposalCard],
    Field(discriminator="card_kind"),
]


class ApiActionKind(ContractEnum):
    SESSION_CREATE = "sessions.create"
    TURN_SUBMIT = "turns.submit"
    CLARIFICATION_RESUME = "turns.resume.clarification"
    AUTH_RESUME = "turns.resume.auth"
    PROPOSAL_ADJUST = "turns.resume.proposal_adjust"
    TURN_CANCEL = "turns.cancel"
    PROPOSAL_CONFIRM = "proposals.confirm"


class RequestReceiptKind(ContractEnum):
    SESSION_CREATED = "session_created"
    TURN_ACCEPTED = "turn_accepted"
    TURN_RESUMED = "turn_resumed"
    PROPOSAL_ADJUSTED = "proposal_adjusted"
    TURN_CANCELLED = "turn_cancelled"
    CONFIRMATION_UNAVAILABLE = "confirmation_unavailable"


class ApiErrorCode(ContractEnum):
    UNAUTHENTICATED = "unauthenticated"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    STATE_REVISION_CONFLICT = "state_revision_conflict"
    PROPOSAL_REVISION_CONFLICT = "proposal_revision_conflict"
    PROPOSAL_EXPIRED = "proposal_expired"
    EXECUTION_CAPABILITY_UNAVAILABLE = "execution_capability_unavailable"
    AGENT_DISABLED = "agent_disabled"
    RATE_LIMITED = "rate_limited"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    INVALID_REQUEST = "invalid_request"


class ApiErrorResponse(ContractModel):
    api_version: Literal["1.0.0"] = API_VERSION
    code: ApiErrorCode
    message: ShortText
    retryable: bool = False


class CreateSessionRequest(ContractModel):
    api_version: Literal["1.0.0"] = API_VERSION
    client_request_id: ClientRequestId
    title: Optional[TitleText] = None
    ui_context: Optional[UIContext] = None


class SessionSummary(ContractModel):
    session_id: SessionId
    title: Optional[TitleText] = None
    created_at: datetime
    updated_at: datetime
    active_turn_count: Annotated[int, Field(strict=True, ge=0)]

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must include a timezone")
        return value


class CreateSessionResponse(ContractModel):
    api_version: Literal["1.0.0"] = API_VERSION
    session: SessionSummary


class ListSessionsResponse(ContractModel):
    api_version: Literal["1.0.0"] = API_VERSION
    items: list[SessionSummary] = Field(max_length=100)
    next_cursor: Optional[ShortText] = None


class TurnSummary(ContractModel):
    turn_id: TurnId
    state: TurnState
    state_revision: Annotated[int, Field(strict=True, ge=1)]
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must include a timezone")
        return value


class SessionDetailResponse(ContractModel):
    api_version: Literal["1.0.0"] = API_VERSION
    session: SessionSummary
    turns: list[TurnSummary] = Field(max_length=100)
    proposal_cards: list[ProposalCard] = Field(max_length=8)


class SubmitTurnRequest(ContractModel):
    versions: ClientProtocolVersions = Field(default_factory=ClientProtocolVersions)
    client_request_id: ClientRequestId
    text: StrictText
    ui_context: Optional[UIContext] = None

    @field_validator("text")
    @classmethod
    def safe_input_text(cls, value: str) -> str:
        return _safe_text(value)


class SubmitTurnAccepted(ContractModel):
    api_version: Literal["1.0.0"] = API_VERSION
    turn_id: TurnId
    state: Literal["QUEUED"]
    state_revision: Literal[1] = 1
    accepted_at: datetime

    @field_validator("accepted_at")
    @classmethod
    def accepted_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("accepted_at must include a timezone")
        return value


class ResumeClarificationRequest(ContractModel):
    """Client sends the user's text verbatim; Harness/model interprets it after auth."""

    versions: ClientProtocolVersions = Field(default_factory=ClientProtocolVersions)
    client_request_id: ClientRequestId
    expected_state_revision: Annotated[int, Field(strict=True, ge=1)]
    text: StrictText

    @field_validator("text")
    @classmethod
    def safe_reply_text(cls, value: str) -> str:
        return _safe_text(value)


class ResumeAuthRequest(ContractModel):
    versions: ClientProtocolVersions = Field(default_factory=ClientProtocolVersions)
    client_request_id: ClientRequestId
    expected_state_revision: Annotated[int, Field(strict=True, ge=1)]


class ResumeProposalAdjustRequest(ContractModel):
    """Client sends adjustment text; Harness must re-interpret and regenerate preview."""

    versions: ClientProtocolVersions = Field(default_factory=ClientProtocolVersions)
    client_request_id: ClientRequestId
    expected_state_revision: Annotated[int, Field(strict=True, ge=1)]
    expected_proposal_revision: Annotated[int, Field(strict=True, ge=1)]
    text: StrictText

    @field_validator("text")
    @classmethod
    def safe_adjustment_text(cls, value: str) -> str:
        return _safe_text(value)


class CancelTurnRequest(ContractModel):
    versions: ClientProtocolVersions = Field(default_factory=ClientProtocolVersions)
    client_request_id: ClientRequestId
    expected_state_revision: Annotated[int, Field(strict=True, ge=1)]
    reason: Optional[Annotated[str, StringConstraints(strict=True, max_length=500)]] = None

    @field_validator("reason")
    @classmethod
    def safe_reason(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return _safe_text(value)
        return value


class ConfirmProposalRequest(ContractModel):
    versions: ClientProtocolVersions = Field(default_factory=ClientProtocolVersions)
    client_request_id: ClientRequestId
    expected_proposal_revision: Annotated[int, Field(strict=True, ge=1)]
    command_digest: Sha256Hex
    confirmation_nonce: ConfirmationNonceForRequest


class TurnMutationAccepted(ContractModel):
    api_version: Literal["1.0.0"] = API_VERSION
    turn_id: TurnId
    state: TurnState
    state_revision: Annotated[int, Field(strict=True, ge=1)]
    event_cursor: Annotated[int, Field(strict=True, ge=0)]


class CancelTurnResponse(ContractModel):
    api_version: Literal["1.0.0"] = API_VERSION
    turn: TurnPublicStatus
    result: Literal["cancelled", "cancel_requested", "reconciling"]


class ProposalAdjustedAccepted(ContractModel):
    api_version: Literal["1.0.0"] = API_VERSION
    proposal_id: ProposalId
    proposal_revision: Annotated[int, Field(strict=True, ge=1)]
    turn_id: TurnId
    state: Literal["WAIT_CONFIRM"]
    state_revision: Annotated[int, Field(strict=True, ge=1)]
    event_cursor: Annotated[int, Field(strict=True, ge=0)]


class ConfirmationUnavailableResponse(ContractModel):
    api_version: Literal["1.0.0"] = API_VERSION
    code: Literal["execution_capability_unavailable"]
    message: ShortText
    execution_enabled: Literal[False] = False
    business_write_performed: Literal[False] = False


class RequestReceipt(ContractModel):
    """Four-table placement is defined in the freeze document; response snapshots contain no nonce."""

    key_scope: ApiActionKind
    owner_user_id: UserId
    resource_id: Optional[uuid.UUID] = None
    client_request_id: ClientRequestId
    payload_hash: Sha256Hex
    http_status: Annotated[int, Field(strict=True, ge=200, le=599)]
    response_kind: RequestReceiptKind
    response_snapshot: Union[
        CreateSessionResponse,
        SubmitTurnAccepted,
        TurnMutationAccepted,
        CancelTurnResponse,
        ProposalAdjustedAccepted,
        ConfirmationUnavailableResponse,
    ]
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def recorded_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recorded_at must include a timezone")
        return value

    @model_validator(mode="after")
    def response_kind_matches_snapshot(self) -> "RequestReceipt":
        expected = {
            RequestReceiptKind.SESSION_CREATED: CreateSessionResponse,
            RequestReceiptKind.TURN_ACCEPTED: SubmitTurnAccepted,
            RequestReceiptKind.TURN_RESUMED: TurnMutationAccepted,
            RequestReceiptKind.PROPOSAL_ADJUSTED: ProposalAdjustedAccepted,
            RequestReceiptKind.TURN_CANCELLED: CancelTurnResponse,
            RequestReceiptKind.CONFIRMATION_UNAVAILABLE: ConfirmationUnavailableResponse,
        }[self.response_kind]
        if not isinstance(self.response_snapshot, expected):
            raise ValueError("receipt response_kind must match the stored original response")
        expected_kind_by_scope = {
            ApiActionKind.SESSION_CREATE: RequestReceiptKind.SESSION_CREATED,
            ApiActionKind.TURN_SUBMIT: RequestReceiptKind.TURN_ACCEPTED,
            ApiActionKind.CLARIFICATION_RESUME: RequestReceiptKind.TURN_RESUMED,
            ApiActionKind.AUTH_RESUME: RequestReceiptKind.TURN_RESUMED,
            ApiActionKind.PROPOSAL_ADJUST: RequestReceiptKind.PROPOSAL_ADJUSTED,
            ApiActionKind.TURN_CANCEL: RequestReceiptKind.TURN_CANCELLED,
            ApiActionKind.PROPOSAL_CONFIRM: RequestReceiptKind.CONFIRMATION_UNAVAILABLE,
        }
        if self.response_kind != expected_kind_by_scope[self.key_scope]:
            raise ValueError("receipt response kind must match its action-key scope")
        if self.key_scope == ApiActionKind.SESSION_CREATE and self.resource_id is not None:
            raise ValueError("session creation keys are owner-scoped and have no pre-existing resource")
        if self.key_scope != ApiActionKind.SESSION_CREATE and self.resource_id is None:
            raise ValueError("all non-creation action keys bind their target resource")
        return self


class SessionRecord(ContractModel):
    session_id: SessionId
    owner_user_id: UserId
    title: Optional[TitleText] = None
    default_activity_hint: Optional[EntityId] = None
    create_request_id: ClientRequestId
    create_payload_hash: Sha256Hex
    create_response: CreateSessionResponse
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def creation_receipt_points_to_self(self) -> "SessionRecord":
        if self.create_response.session.session_id != self.session_id:
            raise ValueError("session create replay snapshot must point to this Session")
        return self


class TurnRecord(ContractModel):
    """Typed turn-row payload, including the append-only request receipts for resume replay."""

    turn: TurnStateSnapshot
    client_request_id: ClientRequestId
    request_payload_hash: Sha256Hex
    original_text: StrictText
    ui_context_snapshot: Optional[UIContext] = None
    bound_references: list[BoundReference] = Field(max_length=64)
    bound_evidence_references: list[BoundEvidenceReference] = Field(max_length=48)
    bound_read_results: list[BoundReadResultReference] = Field(default_factory=list, max_length=16)
    request_receipts: list[RequestReceipt] = Field(max_length=256)

    @model_validator(mode="after")
    def receipts_are_owned_and_scoped(self) -> "TurnRecord":
        for receipt in self.request_receipts:
            if receipt.owner_user_id != self.turn.owner_user_id:
                raise ValueError("Turn receipts must belong to the owning user")
            if receipt.key_scope in (
                ApiActionKind.CLARIFICATION_RESUME,
                ApiActionKind.AUTH_RESUME,
                ApiActionKind.PROPOSAL_ADJUST,
                ApiActionKind.TURN_CANCEL,
            ) and receipt.resource_id != self.turn.turn_id:
                raise ValueError("Turn action receipt scope must bind this Turn")
        refs = [item.ref for item in self.bound_references]
        if len(refs) != len(set(refs)):
            raise ValueError("persisted reference tokens must be unique within a Turn")
        evidence_refs = [item.evidence_ref for item in self.bound_evidence_references]
        if len(evidence_refs) != len(set(evidence_refs)):
            raise ValueError("persisted evidence tokens must be unique within a Turn")
        if any(item.source_turn_id != self.turn.turn_id for item in self.bound_evidence_references):
            raise ValueError("persisted evidence bindings must belong to this Turn")
        read_result_refs = [item.result_ref for item in self.bound_read_results]
        read_result_ids = [item.result_id for item in self.bound_read_results]
        if len(read_result_refs) != len(set(read_result_refs)) or len(read_result_ids) != len(set(read_result_ids)):
            raise ValueError("persisted read-result refs and IDs must be unique within a Turn")
        if any(item.source_turn_id != self.turn.turn_id for item in self.bound_read_results):
            raise ValueError("persisted read-result bindings must belong to this Turn")
        receipt_keys = [
            (item.key_scope, item.resource_id, item.client_request_id)
            for item in self.request_receipts
        ]
        if len(receipt_keys) != len(set(receipt_keys)):
            raise ValueError("Turn action receipts must have unique scoped request keys")
        return self


class ProposalRecord(ContractModel):
    proposal_id: ProposalId
    owner_user_id: UserId
    session_id: SessionId
    turn_id: TurnId
    revision: Annotated[int, Field(strict=True, ge=1)]
    operation: WriteOperation
    mode: Literal["simulation", "backend"]
    status: ProposalStatus
    intent: WriteIntent
    canonical_command: Optional[FixedCommand] = None
    preview: Optional[ExpensePreview] = None
    preconditions: Optional[PreconditionSnapshot] = None
    command_digest: Optional[Sha256Hex] = None
    confirmation_nonce: Optional[ConfirmationNonce] = Field(
        default=None,
        json_schema_extra={
            "x-sensitive": True,
            "x-storage-scope": "proposals-row-only",
            "x-never-model-event-or-log": True,
        },
    )
    policy_version: ShortText
    expires_at: datetime
    execution: Optional[ExecutionIdentity] = None
    request_receipts: list[RequestReceipt] = Field(max_length=64)

    @model_validator(mode="after")
    def proposal_mode_and_nonce_invariants(self) -> "ProposalRecord":
        if self.operation != self.intent.kind:
            raise ValueError("proposal operation must match typed intent")
        if self.canonical_command is not None and self.canonical_command.operation != self.operation:
            raise ValueError("canonical command operation must match proposal operation")
        if self.status == ProposalStatus.PENDING:
            if self.mode == "simulation":
                if any(
                    value is not None
                    for value in (
                        self.canonical_command,
                        self.preconditions,
                        self.command_digest,
                        self.confirmation_nonce,
                    )
                ):
                    raise ValueError("simulation proposals have no executable command, digest, preconditions, or nonce")
                if self.preview is None or not self.preview.simulation:
                    raise ValueError("simulation pending proposals require a clearly simulated preview")
            else:
                if any(
                    value is None
                    for value in (
                        self.canonical_command,
                        self.preview,
                        self.preconditions,
                        self.command_digest,
                        self.confirmation_nonce,
                    )
                ):
                    raise ValueError("backend pending proposals require a hydrated preview and nonce")
                if self.preview.simulation:
                    raise ValueError("backend proposal preview cannot be simulated")
        elif self.confirmation_nonce is not None:
            raise ValueError("terminal or invalid proposals never expose a confirmation nonce")
        if self.execution is not None:
            if self.execution.proposal_id != self.proposal_id or self.execution.proposal_revision != self.revision:
                raise ValueError("execution identity must be bound to this proposal revision")
            if self.execution.actor_id != self.owner_user_id:
                raise ValueError("proposal execution belongs to its authenticated owner")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("expires_at must include a timezone")
        if self.mode == "backend" and self.canonical_command is not None and self.preconditions is not None:
            command_activity_id = self.canonical_command.activity_id
            if self.preconditions.activity_id != command_activity_id:
                raise ValueError("backend Proposal precondition must bind the command Activity")
            if self.preconditions.policy_version != self.policy_version:
                raise ValueError("backend Proposal policy version must match its precondition snapshot")
            if self.preview is None or self.preview.activity_financial_version != self.preconditions.activity_financial_version:
                raise ValueError("backend Proposal preview must bind the same Activity financial version")
            if isinstance(self.canonical_command, FixedExpenseCreateCommand):
                if self.preconditions.expense_version is not None:
                    raise ValueError("create Proposal does not have an existing Expense version")
                if self.preview.after.ledger_unit_id != self.canonical_command.ledger_unit_id:
                    raise ValueError("create preview ledger unit must match the canonical command")
                if self.canonical_command.expected_financial_version != self.preconditions.activity_financial_version:
                    raise ValueError("create command expected version must match the precondition")
            elif isinstance(self.canonical_command, FixedExpenseUpdateCommand):
                if self.preconditions.expense_version != self.canonical_command.expected_expense_version:
                    raise ValueError("update command Expense version must match the precondition")
                if self.canonical_command.expected_financial_version != self.preconditions.activity_financial_version:
                    raise ValueError("update command Activity version must match the precondition")
                if self.preview.before is None or self.preview.before.expense_version != self.canonical_command.expected_expense_version:
                    raise ValueError("update preview before snapshot must match the expected Expense version")
            else:
                if self.preconditions.expense_version != self.canonical_command.expected_expense_version:
                    raise ValueError("presentation command Expense version must match the precondition")
                if self.preview.before is None or self.preview.before.expense_version != self.canonical_command.expected_expense_version:
                    raise ValueError("presentation preview before snapshot must match the expected Expense version")
            if self.command_digest != canonical_command_digest(
                self.canonical_command,
                self.preconditions,
                policy_version=self.policy_version,
            ):
                raise ValueError("backend command_digest must hash command, preconditions, and protocol/policy versions")
        receipt_keys = []
        for receipt in self.request_receipts:
            if receipt.owner_user_id != self.owner_user_id:
                raise ValueError("Proposal receipts must belong to the proposal owner")
            if receipt.key_scope != ApiActionKind.PROPOSAL_CONFIRM or receipt.resource_id != self.proposal_id:
                raise ValueError("Proposal row receipts are scoped only to confirmation of this proposal")
            receipt_keys.append(receipt.client_request_id)
        if len(receipt_keys) != len(set(receipt_keys)):
            raise ValueError("Proposal confirmation receipt keys must be unique")
        return self


def validate_single_pending_proposal(proposals: list[ProposalRecord]) -> None:
    """At most one pending write proposal is allowed per Session, including while reads run."""
    pending_by_session: dict[SessionId, ProposalId] = {}
    for proposal in proposals:
        if proposal.status != ProposalStatus.PENDING:
            continue
        existing = pending_by_session.get(proposal.session_id)
        if existing is not None:
            raise ValueError("a Session may have only one pending proposal")
        pending_by_session[proposal.session_id] = proposal.proposal_id


def validate_proposal_adjustment(
    current: ProposalRecord,
    replacement: ProposalRecord,
    *,
    expected_proposal_revision: int,
) -> None:
    """Conditional in-row revision replacement; caller must commit via DB CAS transaction."""
    if expected_proposal_revision != current.revision:
        raise ValueError("proposal revision precondition failed")
    if current.status != ProposalStatus.PENDING or current.execution is not None:
        raise ValueError("only an unexecuted pending proposal can be adjusted")
    if (
        replacement.proposal_id != current.proposal_id
        or replacement.owner_user_id != current.owner_user_id
        or replacement.session_id != current.session_id
        or replacement.turn_id != current.turn_id
    ):
        raise ValueError("adjustment cannot change proposal, owner, Session, or Turn identity")
    if replacement.revision != current.revision + 1:
        raise ValueError("adjustment creates exactly one new proposal revision")
    if replacement.status != ProposalStatus.PENDING or replacement.execution is not None:
        raise ValueError("adjustment returns a new pending proposal without execution identity")
    if current.mode == "backend" and replacement.mode == "backend":
        if replacement.confirmation_nonce == current.confirmation_nonce:
            raise ValueError("backend adjustment invalidates the old nonce and hydrates a fresh one")


def validate_confirm_transition(
    turn_before: TurnStateSnapshot,
    turn_after: TurnStateSnapshot,
    current: ProposalRecord,
    *,
    expected_state_revision: int,
    expected_proposal_revision: int,
) -> None:
    """Confirmation is the only boundary that may assign a stable ExecutionIdentity."""
    if turn_before.state != TurnState.WAIT_CONFIRM or turn_before.wait_reason != WaitReason.CONFIRM_REQUIRED:
        raise ValueError("confirmation requires WAIT_CONFIRM")
    if current.status != ProposalStatus.PENDING or current.execution is not None:
        raise ValueError("only a pending unexecuted Proposal can be confirmed")
    if current.revision != expected_proposal_revision:
        raise ValueError("proposal revision precondition failed")
    if turn_after.execution is None:
        raise ValueError("confirmed proposal must acquire its stable execution identity")
    if (
        turn_after.execution.actor_id != current.owner_user_id
        or turn_after.execution.proposal_id != current.proposal_id
        or turn_after.execution.proposal_revision != current.revision
    ):
        raise ValueError("execution identity must bind the authenticated owner and exact proposal revision")
    validate_state_transition(turn_before, turn_after, expected_state_revision=expected_state_revision)


class EventType(ContractEnum):
    STATUS = "status"
    MESSAGE = "message"
    CLARIFICATION = "clarification"
    PROPOSAL = "proposal"
    EXECUTION_RESULT = "execution_result"
    ERROR = "error"


class StatusEventPayload(ContractModel):
    state: TurnState
    step: TurnStep
    state_revision: Annotated[int, Field(strict=True, ge=1)]
    wait_reason: Optional[WaitReason] = None
    resume_state: Optional[ResumeState] = None

    @model_validator(mode="after")
    def wait_metadata_matches_state(self) -> "StatusEventPayload":
        if self.state == TurnState.WAIT_INPUT:
            if self.wait_reason not in (WaitReason.MISSING_FIELDS, WaitReason.AUTH_REQUIRED) or self.resume_state is None:
                raise ValueError("WAIT_INPUT status event carries its wait and resume metadata")
        elif self.state == TurnState.WAIT_CONFIRM:
            if self.wait_reason != WaitReason.CONFIRM_REQUIRED or self.resume_state is not None:
                raise ValueError("WAIT_CONFIRM status event carries confirm_required only")
        elif self.wait_reason is not None or self.resume_state is not None:
            raise ValueError("non-waiting status event cannot carry resume metadata")
        return self


class MessageEventPayload(ContractModel):
    text: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2000)]
    citations: list[EvidenceCitation] = Field(max_length=16)

    @field_validator("text")
    @classmethod
    def safe_message(cls, value: str) -> str:
        return _no_url(value)


class ClarificationEventPayload(ContractModel):
    prompt: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=1000)]
    missing_slots: list[ClarificationSlot] = Field(min_length=1, max_length=8)
    resume_state: ResumeState

    @field_validator("prompt")
    @classmethod
    def safe_prompt(cls, value: str) -> str:
        return _no_url(value)


class ProposalEventPayload(ContractModel):
    """Persist only a typed proposal reference. Hydrate cards after current auth checks."""

    proposal_id: ProposalId
    revision: Annotated[int, Field(strict=True, ge=1)]
    operation: WriteOperation


class ExecutionResultPayload(ContractModel):
    execution: ExecutionReference
    resolution: ExecutionResolution
    result_code: Optional[ShortText] = None
    result_summary: Optional[ShortText] = None

    @model_validator(mode="after")
    def unknown_has_no_business_claim(self) -> "ExecutionResultPayload":
        if self.resolution == ExecutionResolution.UNKNOWN and (
            self.result_code is not None or self.result_summary is not None
        ):
            raise ValueError("unknown result cannot claim a business outcome")
        return self


class ErrorEventPayload(ContractModel):
    code: ApiErrorCode
    message: ShortText
    retryable: bool


class StatusEvent(ContractModel):
    type: Literal["status"]
    seq: Annotated[int, Field(strict=True, ge=1)]
    occurred_at: datetime
    simulation: bool
    payload: StatusEventPayload

    @field_validator("occurred_at")
    @classmethod
    def occurred_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value


class MessageEvent(ContractModel):
    type: Literal["message"]
    seq: Annotated[int, Field(strict=True, ge=1)]
    occurred_at: datetime
    simulation: bool
    payload: MessageEventPayload

    @field_validator("occurred_at")
    @classmethod
    def occurred_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value


class ClarificationEvent(ContractModel):
    type: Literal["clarification"]
    seq: Annotated[int, Field(strict=True, ge=1)]
    occurred_at: datetime
    simulation: bool
    payload: ClarificationEventPayload


class ProposalEvent(ContractModel):
    type: Literal["proposal"]
    seq: Annotated[int, Field(strict=True, ge=1)]
    occurred_at: datetime
    simulation: bool
    payload: ProposalEventPayload


class ExecutionResultEvent(ContractModel):
    type: Literal["execution_result"]
    seq: Annotated[int, Field(strict=True, ge=1)]
    occurred_at: datetime
    simulation: bool
    payload: ExecutionResultPayload


class ErrorEvent(ContractModel):
    type: Literal["error"]
    seq: Annotated[int, Field(strict=True, ge=1)]
    occurred_at: datetime
    simulation: bool
    payload: ErrorEventPayload


AgentEvent = Annotated[
    Union[
        StatusEvent,
        MessageEvent,
        ClarificationEvent,
        ProposalEvent,
        ExecutionResultEvent,
        ErrorEvent,
    ],
    Field(discriminator="type"),
]
AGENT_EVENT_ADAPTER = TypeAdapter(AgentEvent)


class EventRecord(ContractModel):
    """One event row; sequence uniqueness is scoped by turn_id."""

    turn_id: TurnId
    seq: Annotated[int, Field(strict=True, ge=1)]
    event: AgentEvent
    created_at: datetime

    @model_validator(mode="after")
    def event_key_matches(self) -> "EventRecord":
        if self.event.seq != self.seq:
            raise ValueError("events row seq must match its typed payload")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        if self.event.occurred_at.tzinfo is None or self.event.occurred_at.utcoffset() is None:
            raise ValueError("event occurrence timestamp must include a timezone")
        return self


class PollEventsResponse(ContractModel):
    api_version: Literal["1.0.0"] = API_VERSION
    turn: TurnPublicStatus
    after_seq: Annotated[int, Field(strict=True, ge=0)]
    events: list[AgentEvent] = Field(max_length=500)
    next_after_seq: Annotated[int, Field(strict=True, ge=0)]
    has_more: bool
    proposal_cards: list[ProposalCard] = Field(max_length=8)

    @model_validator(mode="after")
    def sequence_is_strictly_after_cursor(self) -> "PollEventsResponse":
        seqs = [event.seq for event in self.events]
        if seqs != sorted(seqs) or len(seqs) != len(set(seqs)):
            raise ValueError("events must be ordered by unique increasing seq")
        if any(seq <= self.after_seq for seq in seqs):
            raise ValueError("poll returns only events with seq greater than after_seq")
        expected_cursor = seqs[-1] if seqs else self.after_seq
        if self.next_after_seq != expected_cursor:
            raise ValueError("next_after_seq is the last delivered seq or the input cursor")
        return self


class SessionListQuery(ContractModel):
    cursor: Optional[ShortText] = None
    limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 50


class EventPollQuery(ContractModel):
    after_seq: Annotated[int, Field(strict=True, ge=0)] = 0
    limit: Annotated[int, Field(strict=True, ge=1, le=500)] = 100


class IdempotencyKeyScope(ContractModel):
    owner_user_id: UserId
    key_scope: ApiActionKind
    resource_id: Optional[uuid.UUID] = None
    client_request_id: ClientRequestId


def derive_execution_id(
    actor_id: UserId,
    proposal_id: ProposalId,
    proposal_revision: int,
    operations_version: str = OPERATIONS_VERSION,
) -> uuid.UUID:
    """Stable across process restarts and old database backups; this identifier is not a secret."""
    if proposal_revision < 1:
        raise ValueError("proposal_revision must be positive")
    if operations_version != OPERATIONS_VERSION:
        raise ValueError("unsupported operations version for execution key derivation")
    stable_name = (
        f"shared-ledger-agent:execution:key-v{EXECUTION_KEY_VERSION}:"
        f"operations={operations_version}:actor={actor_id}:"
        f"proposal={proposal_id}:revision={proposal_revision}"
    )
    return uuid.uuid5(EXECUTION_NAMESPACE, stable_name)


def _normalize_json(value: object) -> object:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalize_json(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            normalized[unicodedata.normalize("NFC", str(key))] = _normalize_json(item)
        return normalized
    return value


def canonical_payload_hash(
    key_scope: ApiActionKind,
    payload: ContractModel,
    *,
    resource_id: Optional[uuid.UUID] = None,
) -> Sha256Hex:
    """Hash the normalized request body and context; Authorization is never an input."""
    document = {
        "api_version": API_VERSION,
        "key_scope": key_scope.value,
        "resource_id": str(resource_id) if resource_id is not None else None,
        "payload": payload.model_dump(mode="json", by_alias=True, exclude_none=False),
    }
    canonical = json.dumps(
        _normalize_json(document),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def canonical_command_digest(
    command: FixedCommand,
    preconditions: PreconditionSnapshot,
    *,
    policy_version: str,
) -> Sha256Hex:
    """Deterministic immutable command digest for previews; it grants no execution capability."""
    document = {
        "digest_version": 1,
        "api_version": API_VERSION,
        "semantic_version": SEMANTIC_VERSION,
        "operations_version": OPERATIONS_VERSION,
        "policy_version": unicodedata.normalize("NFC", policy_version),
        "command": command.model_dump(mode="json", by_alias=True, exclude_none=False),
        "preconditions": preconditions.model_dump(mode="json", by_alias=True, exclude_none=False),
    }
    canonical = json.dumps(
        _normalize_json(document),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_confirmation_request(request: ConfirmProposalRequest, proposal: ProposalRecord) -> None:
    """Offline confirmation binding check; service capability remains disabled in P1-01."""
    if proposal.status != ProposalStatus.PENDING or proposal.mode != "backend":
        raise ValueError("only a pending backend proposal can pass confirmation binding checks")
    if request.expected_proposal_revision != proposal.revision:
        raise ValueError("confirmation proposal revision precondition failed")
    if request.command_digest != proposal.command_digest:
        raise ValueError("confirmation digest does not match the immutable proposal")
    if request.confirmation_nonce != proposal.confirmation_nonce:
        raise ValueError("confirmation nonce does not match the currently hydrated proposal")


def validate_idempotent_replay(
    stored: RequestReceipt,
    *,
    key_scope: ApiActionKind,
    owner_user_id: UserId,
    resource_id: Optional[uuid.UUID],
    client_request_id: ClientRequestId,
    payload_hash: str,
) -> RequestReceipt:
    """Return the stored original receipt, or reject all key collisions."""
    if (
        stored.key_scope != key_scope
        or stored.owner_user_id != owner_user_id
        or stored.resource_id != resource_id
        or stored.client_request_id != client_request_id
    ):
        raise ValueError("idempotency key does not match its owner/scope/resource")
    if stored.payload_hash != payload_hash:
        raise ValueError("same idempotency key with a different normalized body/context is rejected")
    return stored


class CapabilityAvailability(ContractEnum):
    MOCK_READ_ONLY = "mock_read_only"
    MOCK_PROPOSAL_ONLY = "mock_proposal_only"
    UNAVAILABLE = "unavailable"


class CapabilityStage(ContractEnum):
    P1_01 = "P1-01"
    P2 = "P2"
    P3A = "P3a"
    P3B_T3 = "P3b+T3"
    P4 = "P4"
    P5_T4 = "P5/T4"


class OperationRegistryEntry(ContractModel):
    capability_id: Annotated[str, StringConstraints(strict=True, pattern=r"^CAP(0[1-9]|1[0-7])$")]
    capability_name: ShortText
    operations: list[Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_.]{2,63}$")]] = Field(max_length=4)
    target_stage: CapabilityStage
    availability: CapabilityAvailability
    semantic_enabled: bool
    proposal_enabled: bool
    execution_enabled: Literal[False] = False
    required_server_checks: list[ShortText] = Field(max_length=12)
    source_note: ShortText

    @model_validator(mode="after")
    def availability_flags_match(self) -> "OperationRegistryEntry":
        if self.availability == CapabilityAvailability.UNAVAILABLE and (
            self.semantic_enabled or self.proposal_enabled
        ):
            raise ValueError("unavailable capability cannot be exposed to semantic output")
        if self.availability == CapabilityAvailability.MOCK_READ_ONLY and (
            not self.semantic_enabled or self.proposal_enabled
        ):
            raise ValueError("mock_read_only exposes semantic reads only")
        if self.availability == CapabilityAvailability.MOCK_PROPOSAL_ONLY and (
            not self.semantic_enabled or not self.proposal_enabled
        ):
            raise ValueError("mock_proposal_only exposes proposals but never execution")
        return self


CAPABILITY_REGISTRY: list[OperationRegistryEntry] = [
    OperationRegistryEntry(
        capability_id="CAP01",
        capability_name="Activity, ledger, expense, and debt reads",
        operations=["read.activities", "read.expenses", "read.debts"],
        target_stage=CapabilityStage.P2,
        availability=CapabilityAvailability.MOCK_READ_ONLY,
        semantic_enabled=True,
        proposal_enabled=False,
        required_server_checks=["current Authorization identity", "session ownership", "activity membership", "RLS-backed read"],
        source_note="CAP01 only; mock DTOs are simulation and never prove live access.",
    ),
    OperationRegistryEntry(
        capability_id="CAP02",
        capability_name="Activity create and join",
        operations=[],
        target_stage=CapabilityStage.P5_T4,
        availability=CapabilityAvailability.UNAVAILABLE,
        semantic_enabled=False,
        proposal_enabled=False,
        required_server_checks=["authenticated creator identity", "join-code validation", "no full-ledger read before join"],
        source_note="No create/join adapter or preview in P1-01.",
    ),
    OperationRegistryEntry(
        capability_id="CAP03",
        capability_name="Activity settings and currency switches",
        operations=[],
        target_stage=CapabilityStage.P5_T4,
        availability=CapabilityAvailability.UNAVAILABLE,
        semantic_enabled=False,
        proposal_enabled=False,
        required_server_checks=["Creator role", "active and non-deleted activity", "base-currency financial-history rule"],
        source_note="No settings write is exposed to the model.",
    ),
    OperationRegistryEntry(
        capability_id="CAP04",
        capability_name="Participant roster and claims",
        operations=[],
        target_stage=CapabilityStage.P5_T4,
        availability=CapabilityAvailability.UNAVAILABLE,
        semantic_enabled=False,
        proposal_enabled=False,
        required_server_checks=["active Participant validation", "claim uniqueness", "roster lock rules"],
        source_note="No roster or claim adapter is exposed.",
    ),
    OperationRegistryEntry(
        capability_id="CAP05",
        capability_name="Activity membership and Creator transfer",
        operations=[],
        target_stage=CapabilityStage.P5_T4,
        availability=CapabilityAvailability.UNAVAILABLE,
        semantic_enabled=False,
        proposal_enabled=False,
        required_server_checks=["Creator authorization", "activity lifecycle", "target is existing member"],
        source_note="No membership-management proposal is exposed.",
    ),
    OperationRegistryEntry(
        capability_id="CAP06",
        capability_name="Sub-activities and ledger-unit scope",
        operations=[],
        target_stage=CapabilityStage.P5_T4,
        availability=CapabilityAvailability.UNAVAILABLE,
        semantic_enabled=False,
        proposal_enabled=False,
        required_server_checks=["large activity", "non-empty explicit scope for new sub-activity", "payer and split scope"],
        source_note="No ledger-unit management proposal is exposed.",
    ),
    OperationRegistryEntry(
        capability_id="CAP07",
        capability_name="Create and modify expenses",
        operations=["expense.create"],
        target_stage=CapabilityStage.P3B_T3,
        availability=CapabilityAvailability.MOCK_PROPOSAL_ONLY,
        semantic_enabled=True,
        proposal_enabled=True,
        required_server_checks=["authenticated active member", "ledger-unit scope", "payment and split conservation", "server FX snapshot"],
        source_note="Only a simulation proposal; no live preview or write adapter.",
    ),
    OperationRegistryEntry(
        capability_id="CAP08",
        capability_name="Existing expense financial and presentation changes",
        operations=["expense.update", "expense.presentation.update"],
        target_stage=CapabilityStage.P3B_T3,
        availability=CapabilityAvailability.MOCK_PROPOSAL_ONLY,
        semantic_enabled=True,
        proposal_enabled=True,
        required_server_checks=["authenticated Member or Creator policy", "financial lock and refund-source history", "Agent-owned version precondition", "presentation expected_version"],
        source_note="D4 is not globally forbidden; financial lock, permission, confirmation, and version checks remain mandatory; no restore operation exists.",
    ),
    OperationRegistryEntry(
        capability_id="CAP09",
        capability_name="Expense logical delete and restore boundary",
        operations=[],
        target_stage=CapabilityStage.P5_T4,
        availability=CapabilityAvailability.UNAVAILABLE,
        semantic_enabled=False,
        proposal_enabled=False,
        required_server_checks=["creator or Activity Creator for delete", "financial lock", "refund and Transfer source history"],
        source_note="Restore is deliberately absent: current backend does not expose authenticated restore.",
    ),
    OperationRegistryEntry(
        capability_id="CAP10",
        capability_name="Foreign-currency expense and FX facts",
        operations=[],
        target_stage=CapabilityStage.P5_T4,
        availability=CapabilityAvailability.UNAVAILABLE,
        semantic_enabled=False,
        proposal_enabled=False,
        required_server_checks=["supported currency", "server FX snapshot", "original and base precision"],
        source_note="No live FX query or write adapter in P1-01.",
    ),
    OperationRegistryEntry(
        capability_id="CAP11",
        capability_name="Linked refunds",
        operations=[],
        target_stage=CapabilityStage.P5_T4,
        availability=CapabilityAvailability.UNAVAILABLE,
        semantic_enabled=False,
        proposal_enabled=False,
        required_server_checks=["refund source belongs to activity", "refund limits", "prepayment usage restoration", "source-history financial lock"],
        source_note="Negative expense/refund intent is outside the first semantic slice.",
    ),
    OperationRegistryEntry(
        capability_id="CAP12",
        capability_name="Ordinary settlement transfers",
        operations=[],
        target_stage=CapabilityStage.P5_T4,
        availability=CapabilityAvailability.UNAVAILABLE,
        semantic_enabled=False,
        proposal_enabled=False,
        required_server_checks=["participant actor rules", "current debt and candidate targets", "financial version and request receipt"],
        source_note="Bottom-level RPC names are never model operations.",
    ),
    OperationRegistryEntry(
        capability_id="CAP13",
        capability_name="Large-activity prepayment",
        operations=[],
        target_stage=CapabilityStage.P5_T4,
        availability=CapabilityAvailability.UNAVAILABLE,
        semantic_enabled=False,
        proposal_enabled=False,
        required_server_checks=["Large Activity only", "owner and custodian rules", "same-direction debt before balance", "return within available balance"],
        source_note="Ordinary activities must reject prepayment; no prepayment tool is exposed.",
    ),
    OperationRegistryEntry(
        capability_id="CAP14",
        capability_name="Immutable transfer void and replacement",
        operations=[],
        target_stage=CapabilityStage.P5_T4,
        availability=CapabilityAvailability.UNAVAILABLE,
        semantic_enabled=False,
        proposal_enabled=False,
        required_server_checks=["recorded_by or Activity Creator", "void reason", "dependent return ordering", "no restore"],
        source_note="No transfer mutation or restore tool is exposed.",
    ),
    OperationRegistryEntry(
        capability_id="CAP15",
        capability_name="Final settlement plan and recorded payment",
        operations=[],
        target_stage=CapabilityStage.P5_T4,
        availability=CapabilityAvailability.UNAVAILABLE,
        semantic_enabled=False,
        proposal_enabled=False,
        required_server_checks=["server-generated full current plan", "ordinary vs large prepayment path", "financial version and request receipt"],
        source_note="No settlement-plan or payment operation is exposed.",
    ),
    OperationRegistryEntry(
        capability_id="CAP16",
        capability_name="Disputes, notes, and audit facts",
        operations=[],
        target_stage=CapabilityStage.P5_T4,
        availability=CapabilityAvailability.UNAVAILABLE,
        semantic_enabled=False,
        proposal_enabled=False,
        required_server_checks=["related Participant or recorder dispute policy", "disputer or Creator removal policy", "notes financial lock"],
        source_note="CAP01 debt/expense reads do not imply dispute write access.",
    ),
    OperationRegistryEntry(
        capability_id="CAP17",
        capability_name="Activity archive, unarchive, and delete",
        operations=[],
        target_stage=CapabilityStage.P5_T4,
        availability=CapabilityAvailability.UNAVAILABLE,
        semantic_enabled=False,
        proposal_enabled=False,
        required_server_checks=["Creator authorization", "archive warnings", "unarchive lifecycle", "delete only unarchived activity"],
        source_note="No lifecycle operation is exposed.",
    ),
]


def validate_capability_registry(entries: list[OperationRegistryEntry]) -> None:
    """Validate complete CAP traceability; target_stage is not current availability."""
    expected = [f"CAP{index:02d}" for index in range(1, 18)]
    ids = [entry.capability_id for entry in entries]
    if sorted(ids) != expected or len(ids) != len(set(ids)):
        raise ValueError("the operation registry must contain each CAP01-CAP17 exactly once")
    operations = [operation for entry in entries for operation in entry.operations]
    if len(operations) != len(set(operations)):
        raise ValueError("an operation belongs to one explicit capability registry entry")
    allowed = {
        "read.activities",
        "read.expenses",
        "read.debts",
        "expense.create",
        "expense.update",
        "expense.presentation.update",
    }
    if not set(operations).issubset(allowed):
        raise ValueError("registry operations are semantic allowlist names, never raw RPC/SQL commands")
    by_id = {entry.capability_id: entry for entry in entries}
    if by_id["CAP01"].operations != ["read.activities", "read.expenses", "read.debts"]:
        raise ValueError("CAP01 is the only exposed read operation group")
    if by_id["CAP07"].operations != ["expense.create"]:
        raise ValueError("CAP07 only registers expense.create")
    if by_id["CAP08"].operations != ["expense.update", "expense.presentation.update"]:
        raise ValueError("CAP08 registers only the two permitted Expense update proposals")
    if any(entry.execution_enabled for entry in entries):
        raise ValueError("execution remains globally unavailable in the P1-01 registry")
    if by_id["CAP01"].target_stage != CapabilityStage.P2:
        raise ValueError("CAP01 target_stage is the P2 live-read milestone; availability stays mock-only here")
    if by_id["CAP07"].target_stage != CapabilityStage.P3B_T3 or by_id["CAP08"].target_stage != CapabilityStage.P3B_T3:
        raise ValueError("new and permitted modified Expenses target P3b+T3, not P3a")
    if any(
        by_id[capability].target_stage != CapabilityStage.P5_T4
        for capability in ("CAP02", "CAP03", "CAP04", "CAP05", "CAP06", "CAP09", "CAP10", "CAP11", "CAP12", "CAP13", "CAP14", "CAP15", "CAP16", "CAP17")
    ):
        raise ValueError("remaining CAP expansion targets P5/T4")


class SessionListQueryParams(ContractModel):
    cursor: Optional[ShortText] = None
    limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 50


class PollCursorParams(ContractModel):
    after_seq: Annotated[int, Field(strict=True, ge=0)] = 0
    limit: Annotated[int, Field(strict=True, ge=1, le=500)] = 100


class MockScenario(ContractEnum):
    FOUR_SEMANTICS = "four_semantics"
    READ_THEN_ANSWER = "read_then_answer"
    CLARIFY_AUTH_CANCEL_AND_REFERENCE_STABILITY = "clarify_auth_cancel_reference_stability"
    PROPOSE_WAIT_CONFIRM_AND_CONFIRM_DISABLED = "propose_wait_confirm_confirm_disabled"


class ModelDecisionStep(ContractModel):
    kind: Literal["model_decision"]
    context: ModelContext
    decision: SemanticDecision


class ReadResultStep(ContractModel):
    kind: Literal["read_result"]
    result: ToolReadResult


class AgentEventStep(ContractModel):
    kind: Literal["event"]
    turn_id: TurnId
    event: AgentEvent


class ResumeClarificationStep(ContractModel):
    kind: Literal["resume_clarification"]
    request: ResumeClarificationRequest
    response: TurnMutationAccepted
    before: TurnStateSnapshot
    after: TurnStateSnapshot

    @model_validator(mode="after")
    def resumes_only_missing_fields(self) -> "ResumeClarificationStep":
        if self.before.state != TurnState.WAIT_INPUT:
            raise ValueError("clarification resume begins in WAIT_INPUT")
        if self.before.wait_reason != WaitReason.MISSING_FIELDS or self.before.execution is not None:
            raise ValueError("clarification resume cannot continue an assigned execution or auth wait")
        if self.after.state not in (TurnState.QUEUED, TurnState.RUNNING):
            raise ValueError("clarification response returns to planning without execution identity")
        validate_state_transition(
            self.before,
            self.after,
            expected_state_revision=self.request.expected_state_revision,
        )
        if (
            self.response.turn_id != self.after.turn_id
            or self.response.state != self.after.state
            or self.response.state_revision != self.after.state_revision
        ):
            raise ValueError("clarification response must match the persisted resulting Turn state")
        return self


class ResumeAuthStep(ContractModel):
    kind: Literal["resume_auth"]
    request: ResumeAuthRequest
    response: TurnMutationAccepted
    before: TurnStateSnapshot
    after: TurnStateSnapshot

    @model_validator(mode="after")
    def resumes_exact_checkpoint(self) -> "ResumeAuthStep":
        validate_auth_resume(
            self.before,
            self.after,
            expected_state_revision=self.request.expected_state_revision,
        )
        if (
            self.response.turn_id != self.after.turn_id
            or self.response.state != self.after.state
            or self.response.state_revision != self.after.state_revision
        ):
            raise ValueError("auth resume response must match the exact saved state")
        return self


class CancelStep(ContractModel):
    kind: Literal["cancel"]
    request: CancelTurnRequest
    response: CancelTurnResponse
    before: TurnStateSnapshot
    after: TurnStateSnapshot

    @model_validator(mode="after")
    def cancellation_preserves_execution_boundary(self) -> "CancelStep":
        validate_cancel_transition(
            self.before,
            self.after,
            self.response,
            expected_state_revision=self.request.expected_state_revision,
        )
        if self.response.turn.state != self.after.state or self.response.turn.state_revision != self.after.state_revision:
            raise ValueError("cancel response must match the persisted resulting Turn state")
        return self


class ConfirmDisabledStep(ContractModel):
    kind: Literal["confirm_disabled"]
    turn_id: TurnId
    proposal_id: ProposalId
    request: ConfirmProposalRequest
    response: ConfirmationUnavailableResponse


class StateAssertionStep(ContractModel):
    kind: Literal["state_assertion"]
    snapshot: TurnStateSnapshot


class StateTransitionStep(ContractModel):
    kind: Literal["state_transition"]
    before: TurnStateSnapshot
    after: TurnStateSnapshot
    expected_state_revision: Annotated[int, Field(strict=True, ge=1)]

    @model_validator(mode="after")
    def transition_is_allowed(self) -> "StateTransitionStep":
        validate_state_transition(
            self.before,
            self.after,
            expected_state_revision=self.expected_state_revision,
        )
        return self


class ReferenceAssertionStep(ContractModel):
    kind: Literal["reference_assertion"]
    reference: BoundReference
    after_resume: BoundReference
    after_restart: BoundReference

    @model_validator(mode="after")
    def binding_is_unchanged(self) -> "ReferenceAssertionStep":
        if self.reference != self.after_resume or self.reference != self.after_restart:
            raise ValueError("typed ref token, entity UUID, source Turn, and activity scope stay identical")
        return self


class ProposalCardStep(ContractModel):
    kind: Literal["proposal_card"]
    turn_id: TurnId
    card: ProposalCard


TrajectoryStep = Annotated[
    Union[
        ModelDecisionStep,
        ReadResultStep,
        AgentEventStep,
        ResumeClarificationStep,
        ResumeAuthStep,
        CancelStep,
        ConfirmDisabledStep,
        StateAssertionStep,
        StateTransitionStep,
        ReferenceAssertionStep,
        ProposalCardStep,
    ],
    Field(discriminator="kind"),
]


class MockTrajectory(ContractModel):
    """Offline fixture envelope. simulation=true is trusted fixture metadata, never model output."""

    trajectory_version: Literal["1.0.0"] = TRAJECTORY_VERSION
    scenario: MockScenario
    simulation: Literal[True] = True
    steps: list[TrajectoryStep] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def scenario_is_complete_and_consistent(self) -> "MockTrajectory":
        validate_capability_registry(CAPABILITY_REGISTRY)
        model_steps = [step for step in self.steps if isinstance(step, ModelDecisionStep)]
        events = [step.event for step in self.steps if isinstance(step, AgentEventStep)]
        if self.scenario == MockScenario.FOUR_SEMANTICS:
            kinds = {step.decision.kind for step in model_steps}
            if kinds != {"answer", "clarify", "read", "propose"}:
                raise ValueError("four_semantics fixture must validate all four closed semantic variants")
        elif self.scenario == MockScenario.READ_THEN_ANSWER:
            visible_result_refs: set[ReadResultRef] = set()
            visible_evidence: set[EvidenceCitation] = set()
            pending_reads: list[ReadOperation] = []
            found_read = False
            found_answer = False
            for step in self.steps:
                if isinstance(step, ModelDecisionStep):
                    context_result_refs = {item.result_ref for item in step.context.read_results}
                    if not context_result_refs.issubset(visible_result_refs):
                        raise ValueError("model cannot see a read result before its earlier trajectory tool-result step")
                    if isinstance(step.decision, ReadDecision):
                        found_read = True
                        pending_reads.append(step.decision.operation)
                    elif isinstance(step.decision, AnswerDecision):
                        found_answer = True
                        if not (set(step.decision.citations) & visible_evidence):
                            raise ValueError("read_then_answer cites only evidence delivered before this answer")
                        if not any(
                            citation in {
                                fact.evidence_ref
                                for result in step.context.read_results
                                for fact in result.body.items
                            }
                            for citation in step.decision.citations
                        ):
                            raise ValueError("answer's cited read evidence must be in its exact ModelContext")
                elif isinstance(step, ReadResultStep):
                    if not pending_reads or step.result.operation not in pending_reads:
                        raise ValueError("a tool result follows a matching earlier read decision")
                    pending_reads.remove(step.result.operation)
                    if step.result.result_ref in visible_result_refs:
                        raise ValueError("each stable result ref is delivered at most once in this trajectory")
                    visible_result_refs.add(step.result.result_ref)
                    visible_evidence.update(fact.evidence_ref for fact in step.result.body.items)
            if not found_read or not found_answer or not visible_result_refs:
                raise ValueError("read_then_answer requires a read, following full typed result, and later grounded answer")
        elif self.scenario == MockScenario.CLARIFY_AUTH_CANCEL_AND_REFERENCE_STABILITY:
            if not any(isinstance(step.decision, ClarifyDecision) for step in model_steps):
                raise ValueError("clarification scenario requires clarify semantic output")
            if not any(isinstance(step, ResumeClarificationStep) for step in self.steps):
                raise ValueError("clarification scenario requires an idempotent clarification resume")
            if not any(isinstance(step, ResumeAuthStep) for step in self.steps):
                raise ValueError("recovery scenario requires auth resume")
            if not any(isinstance(step, CancelStep) for step in self.steps):
                raise ValueError("recovery scenario requires cancellation")
            if not any(isinstance(step, ReferenceAssertionStep) for step in self.steps):
                raise ValueError("recovery scenario requires a stable typed-reference assertion")
            if not any(
                isinstance(step, StateTransitionStep)
                and step.before.state == TurnState.WAIT_CONFIRM
                and step.after.state == TurnState.WAIT_INPUT
                and step.after.wait_reason == WaitReason.AUTH_REQUIRED
                and step.after.resume_state == ResumeState.WAIT_CONFIRM
                for step in self.steps
            ):
                raise ValueError("auth scenario must cover WAIT_CONFIRM -> auth wait -> exact WAIT_CONFIRM resume")
            if not any(
                isinstance(step, StateTransitionStep)
                and step.before.state == TurnState.RECOVERING
                and step.before.execution_resolution == ExecutionResolution.UNKNOWN
                and step.after.state == TurnState.WAIT_INPUT
                and step.after.resume_state == ResumeState.RECOVERING
                for step in self.steps
            ):
                raise ValueError("auth scenario must cover UNKNOWN RECOVERING -> auth wait")
        elif self.scenario == MockScenario.PROPOSE_WAIT_CONFIRM_AND_CONFIRM_DISABLED:
            proposals = [step.decision for step in model_steps if isinstance(step.decision, ProposeDecision)]
            card_steps = [step for step in self.steps if isinstance(step, ProposalCardStep)]
            cards = [step.card for step in card_steps]
            confirms = [step for step in self.steps if isinstance(step, ConfirmDisabledStep)]
            if not proposals or not cards or not confirms:
                raise ValueError("proposal scenario requires proposal, hydrated simulation card, and confirm-disabled response")
            if not any(event.type == "status" and event.payload.state == TurnState.WAIT_CONFIRM for event in events):
                raise ValueError("proposal scenario must emit WAIT_CONFIRM status")
            if any(event.type == "execution_result" for event in events):
                raise ValueError("P1 proposal simulation cannot claim a business execution result")
            if not all(isinstance(card, SimulationProposalCard) for card in cards):
                raise ValueError("P1 mock proposal cards never carry a live nonce")
            if any(step.response.execution_enabled or step.response.business_write_performed for step in confirms):
                raise ValueError("confirm-disabled fixture cannot claim execution or a business write")
            if len(cards) != 1 or len(confirms) != 1 or len(proposals) != 1:
                raise ValueError("proposal fixture binds one semantic proposal to one card and one disabled confirmation")
            card_step = card_steps[0]
            confirm = confirms[0]
            if card_step.turn_id != confirm.turn_id or confirm.proposal_id != card_step.card.proposal_id:
                raise ValueError("proposal card and confirm path must bind the same Turn and Proposal")
            if confirm.request.expected_proposal_revision != card_step.card.revision:
                raise ValueError("confirm request must target the card's exact revision")
            if proposals[0].operation != card_step.card.operation:
                raise ValueError("proposal card operation must match its semantic proposal")
            wait_transitions = [
                step for step in self.steps
                if isinstance(step, StateTransitionStep)
                and step.after.state == TurnState.WAIT_CONFIRM
            ]
            if len(wait_transitions) != 1 or wait_transitions[0].after.turn_id != card_step.turn_id:
                raise ValueError("WAIT_CONFIRM transition must target the proposal card's Turn")
            for event_step in (step for step in self.steps if isinstance(step, AgentEventStep)):
                if event_step.turn_id != card_step.turn_id:
                    raise ValueError("proposal status/events must target the same Turn as the card")
                if event_step.event.type == "proposal":
                    if (
                        event_step.event.payload.proposal_id != card_step.card.proposal_id
                        or event_step.event.payload.revision != card_step.card.revision
                        or event_step.event.payload.operation != card_step.card.operation
                    ):
                        raise ValueError("persistent proposal event reference must match the hydrated card")
                elif event_step.event.type == "status" and (
                    event_step.event.payload.state != TurnState.WAIT_CONFIRM
                    or event_step.event.payload.state_revision != wait_transitions[0].after.state_revision
                ):
                    raise ValueError("WAIT_CONFIRM status event must match its persisted state transition")
        for step in self.steps:
            if isinstance(step, ModelDecisionStep):
                validate_decision_against_context(step.decision, step.context)
            if isinstance(step, ReadResultStep) and not step.result.simulation:
                raise ValueError("offline mock trajectory tool results must be marked simulation")
            if isinstance(step, AgentEventStep) and not step.event.simulation:
                raise ValueError("offline mock trajectory events must be marked simulation")
        seqs = [event.seq for event in events]
        if seqs != sorted(seqs) or len(seqs) != len(set(seqs)):
            raise ValueError("trajectory events must use a monotonic unique sequence")
        return self


def schema_catalog() -> list[type[BaseModel]]:
    """Named schema roots included in the deterministic JSON Schema snapshot."""
    return [
        ClientProtocolVersions,
        ProtocolVersions,
        UIContext,
        ToolReadResult,
        ModelContext,
        AnswerDecision,
        ClarifyDecision,
        ReadDecision,
        ProposeDecision,
        TurnStateSnapshot,
        FixedExpenseCreateCommand,
        FixedExpenseUpdateCommand,
        FixedExpensePresentationCommand,
        ExpensePreview,
        SimulationProposalCard,
        ConfirmableProposalCard,
        InactiveProposalCard,
        CreateSessionRequest,
        CreateSessionResponse,
        ApiErrorResponse,
        ListSessionsResponse,
        SessionDetailResponse,
        SubmitTurnRequest,
        SubmitTurnAccepted,
        ResumeClarificationRequest,
        ResumeAuthRequest,
        ResumeProposalAdjustRequest,
        CancelTurnRequest,
        CancelTurnResponse,
        ConfirmProposalRequest,
        ConfirmationUnavailableResponse,
        PollEventsResponse,
        SessionListQuery,
        EventPollQuery,
        RequestReceipt,
        SessionRecord,
        TurnRecord,
        ProposalRecord,
        StatusEvent,
        MessageEvent,
        ClarificationEvent,
        ProposalEvent,
        ExecutionResultEvent,
        ErrorEvent,
        OperationRegistryEntry,
        StateTransitionStep,
        MockTrajectory,
    ]
