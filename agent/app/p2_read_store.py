"""Private SQLite DTOs and validation for the default-off P2 candidate Store slice.

This module deliberately stores budgets, normalized query descriptors and hashes only.
It never persists bearer credentials, grants, model facts, raw source rows, or live page
capabilities. A stored receipt is historical provenance; the Runtime must reauthorize
and reread its source before using any facts after a claim change or process restart.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator


P2_CANDIDATE_PROFILE_ID = "p2.read-paged-prepayment-refund.v2-candidate"
P2_MAX_MODEL_CALLS = 6
P2_MAX_LOGICAL_READS = 4
P2_MAX_REPAIRS = 1
P2_MAX_ACTIVE_US = 240_000_000
P2_MAX_BACKEND_US = 20_000_000
P2_MAX_GETS = 48
P2_MAX_RESPONSE_BYTES = 4 * 1024 * 1024

P2ReadOperation = Literal[
    "read.activities",
    "read.expenses",
    "read.debts",
    "read.refund_events",
    "read.prepayment_accounts",
    "read.prepayment_usages",
    "read.prepayment_return_events",
]
P2ChargeStage = Literal["model", "repair", "backend_get", "backend_processing", "local_processing"]
P2Lifecycle = Literal["queued", "active", "waiting", "terminal", "invalidated"]
P2ChargeEventKind = Literal["reserved", "settled", "unknown"]

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_FORBIDDEN_DESCRIPTOR_KEYS = {
    "access_token", "accesstoken", "refresh_token", "refreshtoken", "authorization", "bearer",
    "apikey", "api_key", "service_role", "servicerole", "service_role_key", "grant",
    "grant_token", "granttoken", "capability", "continuation", "continuation_token",
    "next_page_ref", "claim_token", "claimtoken", "nonce", "secret", "password", "token",
}


class _StrictPrivateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


def _uuid_text(value: str) -> str:
    if not _UUID_RE.fullmatch(value):
        raise ValueError("identifier must be a lowercase canonical UUID")
    if str(uuid.UUID(value)) != value:
        raise ValueError("identifier must be a lowercase canonical UUID")
    return value


def _digest_text(value: str) -> str:
    if not _HASH_RE.fullmatch(value):
        raise ValueError("digest must be lowercase SHA-256 hex")
    return value


def canonical_private_json(value: object) -> str:
    """Return bounded canonical JSON and reject duplicate or credential-like keys."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    if len(text.encode("utf-8")) > 32 * 1024:
        raise ValueError("private query descriptor exceeds its size bound")
    decoded = json.loads(text, object_pairs_hook=_reject_duplicate_pairs)
    _validate_private_value(decoded)
    if not isinstance(decoded, dict):
        raise ValueError("private query descriptors must be JSON objects")
    return text


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate keys are not allowed in private query descriptors")
        result[key] = value
    return result


def _reject_sensitive_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("private query descriptor contains a non-text key")
            folded = key.casefold()
            normalized = re.sub(r"[^a-z0-9]", "", folded)
            if folded in _FORBIDDEN_DESCRIPTOR_KEYS or normalized in {
                "accesstoken", "refreshtoken", "authorization", "bearer", "apikey",
                "servicerole", "servicerolekey", "grant", "granttoken", "capability",
                "continuation", "continuationtoken", "nextpageref", "claimtoken", "nonce",
                "secret", "password", "token", "pagetoken", "referencetoken",
            }:
                raise ValueError("private query descriptor contains a forbidden field")


def _validate_private_value(value: object, *, depth: int = 0, nodes: list[int] | None = None) -> None:
    if nodes is None:
        nodes = [0]
    nodes[0] += 1
    if depth > 8 or nodes[0] > 512:
        raise ValueError("private query descriptor exceeds its structural bound")
    _reject_sensitive_keys(value)
    if isinstance(value, dict):
        for item in value.values():
            _validate_private_value(item, depth=depth + 1, nodes=nodes)
    elif isinstance(value, list):
        if len(value) > 128:
            raise ValueError("private query descriptor list exceeds its structural bound")
        for item in value:
            _validate_private_value(item, depth=depth + 1, nodes=nodes)
    elif isinstance(value, float):
        raise ValueError("private query descriptors use typed decimal strings, not floating-point values")
    elif value is not None and not isinstance(value, (str, int, bool)):
        raise ValueError("private query descriptor contains an unsupported JSON value")


def json_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class CandidateTurnSnapshot(_StrictPrivateModel):
    profile_id: Literal["p2.read-paged-prepayment-refund.v2-candidate"]
    owner_user_id: StrictStr
    turn_id: StrictStr
    generation: Annotated[StrictInt, Field(ge=1)]
    input_seq: Annotated[StrictInt, Field(ge=1)]
    input_digest: StrictStr
    context_revision: Annotated[StrictInt, Field(ge=1)]
    state_revision: Annotated[StrictInt, Field(ge=1)]
    claim_epoch: Annotated[StrictInt, Field(ge=0)] = 0
    read_epoch: Annotated[StrictInt, Field(ge=0)] = 0
    lifecycle: P2Lifecycle = "queued"
    revision: Annotated[StrictInt, Field(ge=1)] = 1
    model_calls: Annotated[StrictInt, Field(ge=0, le=P2_MAX_MODEL_CALLS)] = 0
    logical_read_calls: Annotated[StrictInt, Field(ge=0, le=P2_MAX_LOGICAL_READS)] = 0
    repair_calls: Annotated[StrictInt, Field(ge=0, le=P2_MAX_REPAIRS)] = 0
    active_used_us: Annotated[StrictInt, Field(ge=0, le=P2_MAX_ACTIVE_US)] = 0
    active_reserved_us: Annotated[StrictInt, Field(ge=0, le=P2_MAX_ACTIVE_US)] = 0
    backend_used_us: Annotated[StrictInt, Field(ge=0, le=P2_MAX_BACKEND_US)] = 0
    backend_reserved_us: Annotated[StrictInt, Field(ge=0, le=P2_MAX_BACKEND_US)] = 0
    get_attempts: Annotated[StrictInt, Field(ge=0, le=P2_MAX_GETS)] = 0
    response_bytes: Annotated[StrictInt, Field(ge=0, le=P2_MAX_RESPONSE_BYTES)] = 0
    bytes_reserved: Annotated[StrictInt, Field(ge=0, le=P2_MAX_RESPONSE_BYTES)] = 0
    unknown_consumption: StrictBool = False

    @field_validator("owner_user_id", "turn_id")
    @classmethod
    def canonical_ids(cls, value: str) -> str:
        return _uuid_text(value)

    @field_validator("input_digest")
    @classmethod
    def input_hash(cls, value: str) -> str:
        return _digest_text(value)


class CandidateQueryDescriptor(_StrictPrivateModel):
    logical_query_id: StrictStr
    profile_id: Literal["p2.read-paged-prepayment-refund.v2-candidate"]
    owner_user_id: StrictStr
    turn_id: StrictStr
    operation: P2ReadOperation
    generation: Annotated[StrictInt, Field(ge=1)]
    input_seq: Annotated[StrictInt, Field(ge=1)]
    input_digest: StrictStr
    criteria_json: StrictStr
    criteria_digest: StrictStr
    scope_json: StrictStr
    scope_digest: StrictStr
    created_context_revision: Annotated[StrictInt, Field(ge=1)]
    created_at: datetime

    @field_validator("logical_query_id", "owner_user_id", "turn_id")
    @classmethod
    def canonical_ids(cls, value: str) -> str:
        return _uuid_text(value)

    @field_validator("input_digest", "criteria_digest", "scope_digest")
    @classmethod
    def hash_fields(cls, value: str) -> str:
        return _digest_text(value)

    @field_validator("criteria_json", "scope_json")
    @classmethod
    def canonical_descriptor(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 32 * 1024:
            raise ValueError("private query descriptor exceeds its size bound")
        decoded = json.loads(value, object_pairs_hook=_reject_duplicate_pairs)
        _validate_private_value(decoded)
        if not isinstance(decoded, dict):
            raise ValueError("private query descriptors must be JSON objects")
        normalized = json.dumps(decoded, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        if normalized != value:
            raise ValueError("private query descriptor is not canonical JSON")
        return value

    @model_validator(mode="after")
    def descriptors_bind_their_hashes(self) -> "CandidateQueryDescriptor":
        if json_sha256(self.criteria_json) != self.criteria_digest:
            raise ValueError("criteria digest does not bind its normalized descriptor")
        if json_sha256(self.scope_json) != self.scope_digest:
            raise ValueError("scope digest does not bind its normalized descriptor")
        if self.operation != "read.activities" and self.scope_json == "{}":
            raise ValueError("only activity discovery may have an empty scope descriptor")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("query timestamp must include a timezone")
        return self


class CandidateChargeReservation(_StrictPrivateModel):
    reservation_id: StrictStr
    profile_id: Literal["p2.read-paged-prepayment-refund.v2-candidate"]
    owner_user_id: StrictStr
    turn_id: StrictStr
    stage: P2ChargeStage
    generation: Annotated[StrictInt, Field(ge=1)]
    claim_epoch: Annotated[StrictInt, Field(ge=0)]
    read_epoch: Annotated[StrictInt, Field(ge=1)]
    context_revision: Annotated[StrictInt, Field(ge=1)]
    active_limit_us: Annotated[StrictInt, Field(ge=0, le=P2_MAX_ACTIVE_US)]
    backend_limit_us: Annotated[StrictInt, Field(ge=0, le=P2_MAX_BACKEND_US)] = 0
    response_bytes_limit: Annotated[StrictInt, Field(ge=0, le=P2_MAX_RESPONSE_BYTES)] = 0
    logical_query_id: StrictStr | None = None
    request_digest: StrictStr | None = None
    created_at: datetime

    @field_validator("reservation_id", "owner_user_id", "turn_id")
    @classmethod
    def canonical_ids(cls, value: str) -> str:
        return _uuid_text(value)

    @field_validator("logical_query_id")
    @classmethod
    def query_id(cls, value: str | None) -> str | None:
        return _uuid_text(value) if value is not None else value

    @field_validator("request_digest")
    @classmethod
    def request_hash(cls, value: str | None) -> str | None:
        return _digest_text(value) if value is not None else value

    @model_validator(mode="after")
    def stage_shape(self) -> "CandidateChargeReservation":
        if self.active_limit_us <= 0:
            raise ValueError("every admitted execution stage needs a positive active-time reservation")
        if self.backend_limit_us > self.active_limit_us:
            raise ValueError("backend time is a subset of the active-time reservation")
        if self.stage == "backend_get":
            if self.backend_limit_us <= 0 or self.response_bytes_limit <= 0 or self.request_digest is None or self.logical_query_id is None:
                raise ValueError("GET reservation must bind a query, request digest, backend time and byte ceiling")
        elif self.stage == "backend_processing":
            if self.backend_limit_us <= 0 or self.response_bytes_limit or self.request_digest is not None or self.logical_query_id is not None:
                raise ValueError("backend processing must reserve backend time without GET-only fields")
        elif self.backend_limit_us or self.response_bytes_limit or self.request_digest is not None or self.logical_query_id is not None:
            raise ValueError("only GET or backend-processing reservations may include backend time")
        if self.stage == "repair" and self.logical_query_id is not None:
            raise ValueError("repair reservations do not bind a source query")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("reservation timestamp must include a timezone")
        return self


class CandidateChargeSettlement(_StrictPrivateModel):
    reservation_id: StrictStr
    outcome: Literal["actual", "unknown"]
    actual_active_us: Annotated[StrictInt, Field(ge=0, le=P2_MAX_ACTIVE_US)]
    actual_backend_us: Annotated[StrictInt, Field(ge=0, le=P2_MAX_BACKEND_US)] = 0
    actual_response_bytes: Annotated[StrictInt, Field(ge=0, le=P2_MAX_RESPONSE_BYTES)] = 0
    overrun_active_us: Annotated[StrictInt, Field(ge=0, le=9_223_372_036_854_775_807)] = 0
    overrun_backend_us: Annotated[StrictInt, Field(ge=0, le=9_223_372_036_854_775_807)] = 0
    overrun_response_bytes: Annotated[StrictInt, Field(ge=0, le=9_223_372_036_854_775_807)] = 0
    raw_body_digest: StrictStr | None = None
    settled_at: datetime

    @field_validator("reservation_id")
    @classmethod
    def canonical_id(cls, value: str) -> str:
        return _uuid_text(value)

    @field_validator("raw_body_digest")
    @classmethod
    def body_hash(cls, value: str | None) -> str | None:
        return _digest_text(value) if value is not None else value

    @model_validator(mode="after")
    def settlement_shape(self) -> "CandidateChargeSettlement":
        if self.actual_backend_us > self.actual_active_us:
            raise ValueError("backend time cannot exceed active execution time")
        if self.outcome == "unknown":
            if self.raw_body_digest is not None:
                raise ValueError("unknown consumption cannot claim a captured response body")
        elif self.actual_response_bytes and self.raw_body_digest is None:
            raise ValueError("received response bytes require their actual body digest")
        if self.outcome == "actual" and any((self.overrun_active_us, self.overrun_backend_us, self.overrun_response_bytes)):
            raise ValueError("actual settlements cannot carry overrun diagnostics")
        if self.settled_at.tzinfo is None or self.settled_at.utcoffset() is None:
            raise ValueError("settlement timestamp must include a timezone")
        return self


class CandidatePageReceiptDraft(_StrictPrivateModel):
    receipt_id: StrictStr
    logical_query_id: StrictStr
    owner_user_id: StrictStr
    turn_id: StrictStr
    generation: Annotated[StrictInt, Field(ge=1)]
    input_seq: Annotated[StrictInt, Field(ge=1)]
    input_digest: StrictStr
    claim_epoch: Annotated[StrictInt, Field(ge=0)]
    read_epoch: Annotated[StrictInt, Field(ge=1)]
    context_revision: Annotated[StrictInt, Field(ge=1)]
    page_index: Annotated[StrictInt, Field(ge=0, le=63)]
    criteria_digest: StrictStr
    scope_digest: StrictStr
    raw_body_digest: StrictStr
    validated_dto_digest: StrictStr
    projection_digest: StrictStr
    source_version_digest: StrictStr
    observed_at: datetime
    source_query_complete: StrictBool
    model_page_has_more: StrictBool
    next_page_ref_digest: StrictStr | None = None

    @field_validator("receipt_id", "logical_query_id", "owner_user_id", "turn_id")
    @classmethod
    def canonical_ids(cls, value: str) -> str:
        return _uuid_text(value)

    @field_validator(
        "input_digest", "criteria_digest", "scope_digest", "raw_body_digest",
        "validated_dto_digest", "projection_digest", "source_version_digest", "next_page_ref_digest",
    )
    @classmethod
    def hash_fields(cls, value: str | None) -> str | None:
        return _digest_text(value) if value is not None else value

    @model_validator(mode="after")
    def receipt_shape(self) -> "CandidatePageReceiptDraft":
        if self.model_page_has_more != (self.next_page_ref_digest is not None):
            raise ValueError("a continuing model page must bind only the hash of its opaque next-page ref")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("source observation time must include a timezone")
        return self


def revalidate_model(model_type: type[BaseModel], value: BaseModel) -> BaseModel:
    """Re-run strict validation after dumping, defeating model_construct/model_copy bypasses."""
    if not isinstance(value, model_type):
        raise ValueError("candidate DTO has the wrong model type")
    return model_type.model_validate(value.model_dump(mode="python", round_trip=True), strict=True)


def receipt_digest(draft: CandidatePageReceiptDraft, source_get_chain_digest: str) -> str:
    payload = draft.model_dump(mode="json", exclude={"receipt_id"})
    payload["source_get_chain_digest"] = _digest_text(source_get_chain_digest)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
