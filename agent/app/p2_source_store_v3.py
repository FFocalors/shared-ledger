"""Private SQLite state for the disabled P2 v3 candidate Store slice.

This module is not imported by Runtime/API. It stores immutable profile pins,
durable budget/lifecycle metadata and cost-only HTTP wire captures on the
existing Store connection. It does not accept source facts or establish source
truth; strict parsing/projection remains a later integration slice.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import time
import uuid
import dataclasses
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timezone
from typing import Any, Literal, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit

from pydantic import BaseModel

from .contracts import ApiActionKind, TurnState, UiEntityType
from .p2_v3_execution_cohort import (
    P2V3ExecutionManifestError,
    P2V3VerifiedExecutionCohort,
    is_verified_execution_cohort,
)
from .p2_read_contracts_v3 import (
    P2ReadQueryRequest,
    P2Scope,
    P2_V3_CANDIDATE_PROFILE_ID as CONTRACT_P2_V3_PROFILE_ID,
    P2_V3_VERSIONS as CONTRACT_P2_V3_VERSIONS,
    p2_criteria_digest as _public_criteria_digest,
)


P2_V3_CANDIDATE_PROFILE_ID = CONTRACT_P2_V3_PROFILE_ID
P2_V3_VERSIONS = CONTRACT_P2_V3_VERSIONS.model_dump(mode="json")

P2_V3_MAX_MODEL_CALLS = 6
P2_V3_MAX_REPAIRS = 1
P2_V3_MAX_LOGICAL_READS = 4
P2_V3_MAX_ACTIVE_US = 240_000_000
P2_V3_MAX_BACKEND_US = 20_000_000
P2_V3_MAX_GETS = 48
P2_V3_MAX_GET_RESPONSE_BYTES = 1_048_576
P2_V3_MAX_RESPONSE_BYTES = 4_194_304

P2_V3_OPERATIONS = frozenset({
    "read.activities", "read.expenses", "read.debts", "read.refund_events",
    "read.prepayment_accounts", "read.prepayment_usages", "read.prepayment_return_events",
})
P2_V3_SOURCE_ROLES = frozenset({
    "activity", "membership", "participant", "ledger_unit", "expense", "debt",
    "refund_parent", "prepayment_account", "prepayment_usage", "prepayment_return",
    "financial_version", "actor", "scope_label",
})
P2_V3_SOURCE_TABLE_ROLES = {
    "activities": frozenset({"activity", "financial_version", "scope_label"}),
    "activity_members": frozenset({"membership"}),
    "ledger_units": frozenset({"ledger_unit", "scope_label"}),
    "participants": frozenset({"participant", "scope_label"}),
    "sub_activity_participants": frozenset({"ledger_unit"}),
    "participant_claims": frozenset({"actor"}),
    "expenses": frozenset({"expense", "refund_parent"}),
    "payments": frozenset({"expense"}),
    "splits": frozenset({"expense"}),
    "expense_debts": frozenset({"debt"}),
    "prepayment_accounts": frozenset({"prepayment_account"}),
    "prepayment_usages": frozenset({"prepayment_usage"}),
    "transfers": frozenset({"prepayment_return"}),
    "transfer_components": frozenset({"prepayment_return"}),
}
P2_V3_METADATA_TABLE_ROLES = {
    "activities": frozenset({"activity", "financial_version", "scope_label"}),
    "activity_members": frozenset({"membership"}),
    "participants": frozenset({"participant", "scope_label"}),
    "ledger_units": frozenset({"ledger_unit", "scope_label"}),
    "sub_activity_participants": frozenset({"ledger_unit"}),
    "participant_claims": frozenset({"actor"}),
}
P2_V3_MAX_SOURCE_PAGES_PER_TABLE = 4
P2_V3_MAX_SOURCE_PAGES_PER_CAPTURE_CHAIN = 32
# Full source-pin verification and Store acceptance bookkeeping share this local cap;
# Turn-wide active and backend limits remain enforced independently.
P2_V3_METADATA_ACCEPTANCE_CAP_US = 2_000_000
P2_V3_OPERATION_SOURCE_ROLES = {
    "read.activities": frozenset({"activity", "membership", "participant", "scope_label", "actor", "financial_version"}),
    "read.expenses": frozenset({"activity", "membership", "participant", "ledger_unit", "expense", "actor", "scope_label", "financial_version"}),
    "read.debts": frozenset({"activity", "membership", "participant", "ledger_unit", "expense", "debt", "financial_version"}),
    "read.refund_events": frozenset({"activity", "membership", "expense", "refund_parent", "financial_version"}),
    "read.prepayment_accounts": frozenset({"activity", "membership", "prepayment_account", "financial_version"}),
    "read.prepayment_usages": frozenset({"activity", "membership", "participant", "ledger_unit", "expense", "debt", "prepayment_account", "prepayment_usage", "financial_version"}),
    "read.prepayment_return_events": frozenset({"activity", "membership", "prepayment_account", "prepayment_return", "financial_version"}),
}
P2_V3_CHARGE_STAGES = frozenset({
    "model", "repair", "backend_get", "backend_processing", "local_processing",
})


class P2V3StoreConflict(RuntimeError):
    """A candidate compare-and-swap or immutable binding no longer matches."""


class P2V3StoreNotFound(LookupError):
    """A candidate resource is not available under the supplied owner/Turn."""


class P2V3UnsupportedProfile(RuntimeError):
    """An immutable v3 Turn pin belongs to a different reviewed source cohort."""


@dataclass(frozen=True, slots=True)
class P2V3AcceptedAdmissionMetadata:
    """Metadata projection returned only after Store source-proof commit."""

    projection: Any = dataclass_field(repr=False)
    metadata_proofs: tuple[Any, ...] = dataclass_field(default=(), repr=False)
    source_receipt_ids: tuple[str, ...] = dataclass_field(default=(), repr=False)


@dataclass(frozen=True, slots=True)
class P2V3AcceptedReadPage:
    """Store-accepted historical page awaiting a post-commit live projection.

    ``historical`` is display-safe but has no consumable next-page capability.
    The private registry/identity fields are process-local issuer state and are
    deliberately omitted from repr; they are never restored from SQLite.
    """

    accepted_page_id: str = dataclass_field(repr=False)
    historical: Any = dataclass_field(repr=False)
    query_result_receipt_id: str = dataclass_field(repr=False)
    _logical_query_id: str = dataclass_field(repr=False)
    _query_attempt_id: str = dataclass_field(repr=False)
    _attempt_seq: int = dataclass_field(repr=False)
    _admission_id: str = dataclass_field(repr=False)
    _page_index: int = dataclass_field(repr=False)
    _store: Any = dataclass_field(repr=False, compare=False)
    _registry: Any = dataclass_field(repr=False, compare=False)
    _identity: Any = dataclass_field(repr=False, compare=False)
    _claim_token: str = dataclass_field(repr=False, compare=False)
    _seal: object = dataclass_field(repr=False, compare=False)
    _issue_state: dict[str, bool] = dataclass_field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class P2V3ProtectedOutputCommit:
    """Private arguments for the same-transaction canonical/output commit."""

    accepted_page: P2V3AcceptedReadPage = dataclass_field(repr=False)
    historical_output: Any = dataclass_field(repr=False)
    gate: Any = dataclass_field(repr=False)


@dataclass(frozen=True, slots=True)
class P2V3StoredProtectedOutput:
    """Strict sidecar and private scope IDs for one committed candidate event."""

    profile_id: str
    event_seq: int
    historical: Any = dataclass_field(repr=False)
    activity_ids: tuple[uuid.UUID, ...] = dataclass_field(repr=False)


_P2_V3_ACCEPTED_READ_PAGE_SEAL = object()
_P2_V3_METADATA_PERMIT_SEAL = object()


class _P2V3MetadataPublicationPermit:
    """Single-use, process-local evidence that metadata passed the A/B/C gate."""

    __slots__ = ("_store", "_registry_nonce", "identity", "admission_id", "acceptance_id", "_seal", "_consumed")

    def __init__(
        self, *, store: Any, registry_nonce: object, identity: Any,
        admission_id: str, acceptance_id: str, seal: object,
    ) -> None:
        if seal is not _P2_V3_METADATA_PERMIT_SEAL:
            raise ValueError("metadata publication permits are Store-issued")
        self._store = store
        self._registry_nonce = registry_nonce
        self.identity = identity
        self.admission_id = admission_id
        self.acceptance_id = acceptance_id
        self._seal = seal
        self._consumed = False

    def __repr__(self) -> str:
        return "<P2V3MetadataPublicationPermit private>"


_P2_V3_REFERENCE_REGISTRY_SEAL = object()


class P2V3RequestReferenceRegistry:
    """Short-lived Store-issued opaque references for one current request.

    Before source acceptance, refs live only in this object. ``bind_entity``
    never persists a locator; acceptance must prove the corresponding captured
    row before it writes an immutable ``p2_v3_entity_locators`` record.
    """

    def __init__(
        self, store: Any, *, identity: Any, admission_id: str,
        principal_user_id: uuid.UUID, claim_token: str, cohort_sha256: str, seal: object,
    ) -> None:
        if seal is not _P2_V3_REFERENCE_REGISTRY_SEAL:
            raise ValueError("reference registry must be issued by the Store")
        self._store = store
        self.identity = identity
        self.admission_id = admission_id
        self.principal_user_id = principal_user_id
        self._claim_token = claim_token
        if type(cohort_sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", cohort_sha256) is None:
            raise ValueError("reference registry requires a verified immutable execution cohort")
        self._cohort_sha256 = cohort_sha256
        self._seal = seal
        self._entity_by_key: dict[tuple[str, uuid.UUID, uuid.UUID | None, uuid.UUID | None], str] = {}
        self._entity_by_ref: dict[str, tuple[str, uuid.UUID, uuid.UUID | None, uuid.UUID | None]] = {}
        self._capture_by_id: dict[str, str] = {}
        self._capture_by_ref: dict[str, str] = {}
        self._principal_ref = self._new_ref()
        self._owner_turn_ref = self._new_ref()
        self._query_refs: dict[str, str] = {}
        self._query_ids: dict[str, str] = {}
        self._source_refs: dict[tuple[str, str], str] = {}
        self._evidence_refs: dict[tuple[str, str, int], str] = {}
        self._result_refs: dict[tuple[str, str, int], str] = {}
        self._criteria_refs: dict[str, str] = {}
        self._descriptors: dict[str, Any] = {}
        self._continuation_proofs: dict[tuple[str, str], Any] = {}
        self._continuation_attempts: dict[tuple[str, str], int] = {}
        self._continuation_issued_queries: set[str] = set()
        self._consumed_continuations: set[tuple[str, str]] = set()
        self._requested_scope: dict[str, str] | None = None
        self._requested_scope_digest: str | None = None
        self._public_scope_digest: str | None = None
        self._configured_source_origin: tuple[str, str] | None = None
        self._accepted_receipt_by_capture_ref: dict[str, str] = {}
        self._accepted_metadata_proofs: tuple[Any, ...] = ()
        self._accepted_metadata_projection: Any = None
        self._accepted_snapshot_digest: str | None = None
        self._accepted_acceptance_id: str | None = None
        self._permit_nonce = object()

    @staticmethod
    def _new_ref() -> str:
        return "ref_" + secrets.token_urlsafe(24)

    def bind_entity(
        self, kind: str, entity_id: uuid.UUID, *, activity_id: uuid.UUID,
        ledger_unit_id: uuid.UUID | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> str:
        if (
            type(kind) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", kind)
            or type(entity_id) is not uuid.UUID or type(activity_id) is not uuid.UUID
            or (ledger_unit_id is not None and type(ledger_unit_id) is not uuid.UUID)
        ):
            raise P2V3StoreConflict("invalid private entity binding")
        key = (kind, entity_id, activity_id, ledger_unit_id)
        existing = self._entity_by_key.get(key)
        if existing is not None:
            if self._entity_by_ref.get(existing) != key:
                raise P2V3StoreConflict("request-local entity reference registry is inconsistent")
            return existing

        def lookup(db: sqlite3.Connection) -> str | None:
            identity_rows = db.execute(
                """SELECT * FROM p2_v3_entity_locators
                   WHERE owner_user_id=? AND turn_id=? AND entity_kind=?
                     AND private_entity_id=? AND private_activity_id IS ?
                     AND private_ledger_unit_id IS ? ORDER BY locator_id""",
                (
                    str(self.identity.owner_user_id), str(self.identity.turn_id), kind,
                    str(entity_id), str(activity_id),
                    str(ledger_unit_id) if ledger_unit_id is not None else None,
                ),
            ).fetchall()
            if len(identity_rows) > 1:
                raise P2V3StoreConflict("private entity identity has ambiguous persisted opaque locators")
            if identity_rows:
                row = identity_rows[0]
                if row["cohort_sha256"] != self._cohort_sha256:
                    raise P2V3StoreConflict("persisted entity locator belongs to another execution cohort")
                token = row["entity_ref"]
                if type(token) is not str or re.fullmatch(r"ref_[A-Za-z0-9_-]{22,64}", token) is None:
                    raise P2V3StoreConflict("persisted entity locator has an invalid opaque reference")
                token_rows = db.execute(
                    "SELECT * FROM p2_v3_entity_locators WHERE entity_ref=? ORDER BY owner_user_id,turn_id,entity_kind",
                    (token,),
                ).fetchall()
                if len(token_rows) != 1 or token_rows[0]["locator_id"] != row["locator_id"]:
                    raise P2V3StoreConflict("persisted opaque reference is ambiguous across owner, Turn, or entity kind")
                return token
            token = self._new_ref()
            if type(token) is not str or re.fullmatch(r"ref_[A-Za-z0-9_-]{22,64}", token) is None:
                raise P2V3StoreConflict("opaque entity reference generator returned an invalid token")
            collision = db.execute(
                "SELECT 1 FROM p2_v3_entity_locators WHERE entity_ref=? LIMIT 1", (token,),
            ).fetchone()
            if collision is not None:
                raise P2V3StoreConflict("generated opaque entity reference collides with a persisted locator")
            return token

        if connection is None:
            with self._store._connection() as db:
                token = lookup(db)
        else:
            token = lookup(connection)
        assert token is not None
        # A token may be reused only for the exact same private identity and
        # immutable cohort. No old receipt/proof is activated by this mapping.
        token_binding = self._entity_by_ref.get(token)
        if token_binding is not None and token_binding != key:
            raise P2V3StoreConflict("opaque entity reference is already bound to a different request identity")
        other_ref = self._entity_by_key.get(key)
        if other_ref is not None and other_ref != token:
            raise P2V3StoreConflict("private entity identity maps to multiple opaque references")
        self._entity_by_key[key] = token
        self._entity_by_ref[token] = key
        return token

    def _set_requested_scope(self, scope: dict[str, str], scope_digest: str, public_scope_digest: str) -> None:
        if self._requested_scope is not None:
            raise P2V3StoreConflict("request scope was already initialized")
        self._requested_scope = dict(scope)
        self._requested_scope_digest = scope_digest
        self._public_scope_digest = public_scope_digest

    def bind_configured_source_origin(self, project_url: str) -> None:
        """Pin the trusted adapter's configured HTTPS origin before any GET.

        This is a request-local consistency check. The production execution
        cohort must separately bind the server's configured project origin.
        """
        if type(project_url) is not str or len(project_url) > 2048:
            raise P2V3StoreConflict("invalid configured source origin")
        from urllib.parse import urlsplit

        parts = urlsplit(project_url)
        if (
            parts.scheme != "https" or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.query or parts.fragment
            or parts.path not in ("", "/")
        ):
            raise P2V3StoreConflict("configured source origin must be an HTTPS project URL")
        origin = (parts.scheme, parts.netloc.lower())
        if self._configured_source_origin is not None and self._configured_source_origin != origin:
            raise P2V3StoreConflict("request registry source origin cannot be rebound")
        self._configured_source_origin = origin

    def _record_metadata_acceptance(
        self, *, receipt_by_capture_ref: dict[str, str], proofs: tuple[Any, ...],
        projection: Any, snapshot_digest: str, public_scope_digest: str,
        permit: _P2V3MetadataPublicationPermit,
    ) -> None:
        if self._accepted_snapshot_digest is not None:
            raise P2V3StoreConflict("source admission metadata was already accepted")
        if (
            not receipt_by_capture_ref
            or any(ref not in self._capture_by_ref for ref in receipt_by_capture_ref)
            or getattr(projection, "reference_registry", None) is not self
            or getattr(projection, "snapshot_digest", None) != snapshot_digest
            or public_scope_digest != self._public_scope_digest
            or re.fullmatch(r"[0-9a-f]{64}", snapshot_digest) is None
            or not isinstance(permit, _P2V3MetadataPublicationPermit)
            or permit._seal is not _P2_V3_METADATA_PERMIT_SEAL
            or permit._store is not self._store
            or permit._registry_nonce is not self._permit_nonce
            or permit.identity != self.identity
            or permit.admission_id != self.admission_id
            or type(permit.acceptance_id) is not str or not permit.acceptance_id
            or permit._consumed
        ):
            raise P2V3StoreConflict("accepted metadata does not match this request registry")
        permit._consumed = True
        self._accepted_receipt_by_capture_ref = dict(receipt_by_capture_ref)
        self._accepted_metadata_proofs = tuple(proofs)
        self._accepted_metadata_projection = projection
        self._accepted_snapshot_digest = snapshot_digest
        self._accepted_acceptance_id = permit.acceptance_id

    def _revoke_metadata_acceptance(self, *, identity: Any, admission_id: str) -> None:
        """Best-effort rollback of request-local publication after a caller failure."""
        if identity != self.identity or admission_id != self.admission_id:
            return
        self._accepted_receipt_by_capture_ref = {}
        self._accepted_metadata_proofs = ()
        self._accepted_metadata_projection = None
        self._accepted_snapshot_digest = None
        self._accepted_acceptance_id = None

    def require_metadata_accepted(self, *, identity: Any, admission_id: str) -> None:
        if (
            self._seal is not _P2_V3_REFERENCE_REGISTRY_SEAL
            or identity != self.identity or admission_id != self.admission_id
            or self._accepted_snapshot_digest is None
        ):
            raise P2V3StoreConflict("source admission metadata has not been Store-accepted")

    def accepted_receipt_id(self, capture_ref: str, *, identity: Any, admission_id: str) -> str:
        self.require_metadata_accepted(identity=identity, admission_id=admission_id)
        try:
            return self._accepted_receipt_by_capture_ref[capture_ref]
        except KeyError:
            raise P2V3StoreNotFound("accepted source receipt reference is unavailable") from None

    def accepted_metadata_proofs(self, *, identity: Any, admission_id: str) -> tuple[Any, ...]:
        self.require_metadata_accepted(identity=identity, admission_id=admission_id)
        return self._accepted_metadata_proofs

    def accepted_metadata_projection_or_none(self, *, identity: Any, admission_id: str) -> Any | None:
        if (
            self._seal is not _P2_V3_REFERENCE_REGISTRY_SEAL
            or identity != self.identity or admission_id != self.admission_id
        ):
            raise P2V3StoreConflict("metadata projection lookup identity mismatch")
        if self._accepted_acceptance_id is None:
            if (
                self._accepted_snapshot_digest is not None or self._accepted_metadata_projection is not None
                or self._accepted_metadata_proofs
            ):
                raise P2V3StoreConflict("unaccepted metadata projection state is inconsistent")
            return None
        self.require_metadata_accepted(identity=identity, admission_id=admission_id)
        projection = self._accepted_metadata_projection
        if getattr(projection, "reference_registry", None) is not self:
            raise P2V3StoreConflict("accepted metadata projection lost its request registry")
        return projection

    def binding_for_ref(self, opaque_ref: str) -> tuple[str, uuid.UUID, uuid.UUID | None, uuid.UUID | None]:
        """Return a private prospective binding only to this in-process Store path."""
        found = self._entity_by_ref.get(opaque_ref)
        if found is not None:
            return found
        if type(opaque_ref) is not str:
            raise P2V3StoreConflict("invalid opaque entity reference")
        with self._store._connection() as connection:
            rows = connection.execute(
                """SELECT entity_kind,private_entity_id,private_activity_id,private_ledger_unit_id,cohort_sha256
                   FROM p2_v3_entity_locators WHERE owner_user_id=? AND turn_id=? AND entity_ref=?
                   ORDER BY entity_kind""",
                (str(self.identity.owner_user_id), str(self.identity.turn_id), opaque_ref),
            ).fetchall()
        if not rows:
            raise P2V3StoreNotFound("opaque entity reference is not bound to this owner and Turn")
        if len(rows) != 1 or rows[0]["cohort_sha256"] != self._cohort_sha256:
            raise P2V3StoreConflict("persisted opaque reference is ambiguous or belongs to another cohort")
        row = rows[0]
        found = (
            str(row["entity_kind"]), uuid.UUID(row["private_entity_id"]),
            uuid.UUID(row["private_activity_id"]) if row["private_activity_id"] else None,
            uuid.UUID(row["private_ledger_unit_id"]) if row["private_ledger_unit_id"] else None,
        )
        self._entity_by_ref[opaque_ref] = found
        self._entity_by_key[found] = opaque_ref
        return found

    def _restore_unaccepted_ui_expense_ref(
        self, opaque_ref: str, *, expense_id: uuid.UUID, activity_id: uuid.UUID,
    ) -> None:
        """Rebind a query's private UI selection locally after an unaccepted GET.

        The ref must come from the immutable query descriptor and the IDs from
        the same current owner's persisted UI selection. This creates no
        locator row or source authority; a fresh accepted source read remains
        necessary before facts can be used.
        """
        if (
            self._seal is not _P2_V3_REFERENCE_REGISTRY_SEAL
            or type(opaque_ref) is not str
            or re.fullmatch(r"ref_[A-Za-z0-9_-]{22,64}", opaque_ref) is None
            or type(expense_id) is not uuid.UUID
            or type(activity_id) is not uuid.UUID
        ):
            raise P2V3StoreConflict("restored UI expense reference is invalid")
        key = ("expense", expense_id, activity_id, None)
        existing_key = self._entity_by_ref.get(opaque_ref)
        existing_ref = self._entity_by_key.get(key)
        if existing_key is not None and existing_key != key:
            raise P2V3StoreConflict("restored UI expense reference is already bound to another entity")
        if existing_ref is not None and existing_ref != opaque_ref:
            raise P2V3StoreConflict("restored UI expense identity already has another opaque reference")
        with self._store._connection() as connection:
            token_rows = connection.execute(
                """SELECT * FROM p2_v3_entity_locators
                   WHERE owner_user_id=? AND turn_id=? AND entity_ref=? ORDER BY locator_id""",
                (str(self.identity.owner_user_id), str(self.identity.turn_id), opaque_ref),
            ).fetchall()
            identity_rows = connection.execute(
                """SELECT * FROM p2_v3_entity_locators
                   WHERE owner_user_id=? AND turn_id=? AND entity_kind='expense'
                     AND private_entity_id=? AND private_activity_id=?
                     AND private_ledger_unit_id IS NULL ORDER BY locator_id""",
                (str(self.identity.owner_user_id), str(self.identity.turn_id), str(expense_id), str(activity_id)),
            ).fetchall()
        if len(token_rows) > 1 or len(identity_rows) > 1:
            raise P2V3StoreConflict("restored UI expense locator is ambiguous")
        if token_rows:
            row = token_rows[0]
            if (
                row["entity_kind"] != "expense"
                or row["private_entity_id"] != str(expense_id)
                or row["private_activity_id"] != str(activity_id)
                or row["private_ledger_unit_id"] is not None
                or row["cohort_sha256"] != self._cohort_sha256
            ):
                raise P2V3StoreConflict("restored UI expense ref conflicts with its persisted locator")
        elif identity_rows:
            raise P2V3StoreConflict("restored UI expense identity already has a different persisted ref")
        self._entity_by_ref[opaque_ref] = key
        self._entity_by_key[key] = opaque_ref

    def resolve_entity(self, opaque_ref: str, kind: str, *, activity_id: uuid.UUID) -> uuid.UUID:
        if type(opaque_ref) is not str or type(activity_id) is not uuid.UUID:
            raise P2V3StoreConflict("invalid opaque entity lookup")
        found = self._entity_by_ref.get(opaque_ref)
        if found is not None:
            if found[0] != kind or found[2] != activity_id:
                raise P2V3StoreConflict("opaque entity reference is outside its binding")
            return found[1]
        with self._store._connection() as connection:
            rows = connection.execute(
                """SELECT private_entity_id,private_activity_id,private_ledger_unit_id,cohort_sha256
                   FROM p2_v3_entity_locators WHERE owner_user_id=? AND turn_id=?
                     AND entity_ref=? AND entity_kind=? ORDER BY locator_id""",
                (str(self.identity.owner_user_id), str(self.identity.turn_id), opaque_ref, kind),
            ).fetchall()
        if not rows or rows[0]["private_activity_id"] != str(activity_id):
            raise P2V3StoreNotFound("opaque entity reference is not in this owner/Turn scope")
        if len(rows) != 1 or rows[0]["cohort_sha256"] != self._cohort_sha256:
            raise P2V3StoreConflict("persisted opaque reference is ambiguous or belongs to another cohort")
        row = rows[0]
        entity_id = uuid.UUID(row["private_entity_id"])
        ledger_id = uuid.UUID(row["private_ledger_unit_id"]) if row["private_ledger_unit_id"] else None
        key = (kind, entity_id, activity_id, ledger_id)
        self._entity_by_key[key] = opaque_ref
        self._entity_by_ref[opaque_ref] = key
        return entity_id

    def bind_capture(self, capture_id: str, *, identity: Any) -> str:
        if identity != self.identity or type(capture_id) is not str or not capture_id:
            raise P2V3StoreConflict("capture reference identity mismatch")
        if capture_id not in self._capture_by_id:
            token = self._new_ref()
            self._capture_by_id[capture_id] = token
            self._capture_by_ref[token] = capture_id
        return self._capture_by_id[capture_id]

    def resolve_principal(self, principal_ref: str) -> uuid.UUID:
        if principal_ref != self._principal_ref:
            raise P2V3StoreConflict("principal reference mismatch")
        return self.principal_user_id

    def principal_ref(self) -> str:
        return self._principal_ref

    def owner_turn_ref(self, *, identity: Any) -> str:
        if identity != self.identity:
            raise P2V3StoreConflict("owner/Turn reference identity mismatch")
        return self._owner_turn_ref

    def resolve_activity_ref(self, activity_ref: str) -> uuid.UUID:
        kind, entity_id, activity_id, ledger_unit_id = self.binding_for_ref(activity_ref)
        if kind != "activity" or entity_id != activity_id or ledger_unit_id is not None:
            raise P2V3StoreConflict("activity reference is outside its exact activity binding")
        return entity_id

    def _activity_id(self) -> uuid.UUID:
        values = [key[1] for key in self._entity_by_key if key[0] == "activity"]
        if len(set(values)) != 1:
            raise P2V3StoreConflict("activity reference is not uniquely bound in this request")
        return values[0]

    def bind_capture_lookup(self, opaque_ref: str) -> str:
        try:
            return self._capture_by_ref[opaque_ref]
        except KeyError:
            raise P2V3StoreNotFound("capture reference is not in this request") from None

    # The methods below are request-local identity conveniences used by the
    # adapter. Continuation issuance remains Store-acceptance-only.
    def query_ref(self, logical_query_id: str, *, identity: Any) -> str:
        if identity != self.identity or type(logical_query_id) is not str or not logical_query_id:
            raise P2V3StoreConflict("query reference identity mismatch")
        query_ref = self._query_refs.get(logical_query_id)
        if query_ref is None:
            query_ref = self._new_ref()
            self._query_refs[logical_query_id] = query_ref
            self._query_ids[query_ref] = logical_query_id
        elif self._query_ids.get(query_ref) != logical_query_id:
            raise P2V3StoreConflict("request-local query reference registry is inconsistent")
        return query_ref

    def source_ref(self, logical_query_id: str, *, identity: Any, source_kind: str) -> str:
        if identity != self.identity:
            raise P2V3StoreConflict("source reference identity mismatch")
        return self._source_refs.setdefault((logical_query_id, source_kind), self._new_ref())

    def query_evidence_ref(self, logical_query_id: str, attempt_id: str, *, identity: Any, page_index: int) -> str:
        if identity != self.identity:
            raise P2V3StoreConflict("evidence reference identity mismatch")
        key = (logical_query_id, attempt_id, page_index)
        return self._evidence_refs.setdefault(key, "qev_" + secrets.token_urlsafe(20))

    def result_ref(self, logical_query_id: str, attempt_id: str, *, identity: Any, page_index: int) -> str:
        if identity != self.identity:
            raise P2V3StoreConflict("result reference identity mismatch")
        return self._result_refs.setdefault((logical_query_id, attempt_id, page_index), self._new_ref())

    def criteria_ref(self, criteria_digest: str, *, identity: Any) -> str:
        if identity != self.identity:
            raise P2V3StoreConflict("criteria reference identity mismatch")
        return self._criteria_refs.setdefault(criteria_digest, self._new_ref())

    def load_query_descriptor(self, query_ref: str, *, identity: Any) -> Any:
        if identity != self.identity or query_ref not in self._descriptors:
            raise P2V3StoreNotFound("query descriptor is unavailable in this request")
        return self._descriptors[query_ref]

    def _register_query_descriptor(self, logical_query_id: str, descriptor: Any, *, identity: Any) -> str:
        if identity != self.identity or type(logical_query_id) is not str or not logical_query_id:
            raise P2V3StoreConflict("query descriptor identity mismatch")
        from . import p2_source_codec_v3 as codec3
        if not isinstance(descriptor, codec3.V3QueryDescriptor):
            raise P2V3StoreConflict("query descriptor must use the strict source codec type")
        query_ref = self.query_ref(logical_query_id, identity=identity)
        previous = self._descriptors.get(query_ref)
        if previous is not None and previous != descriptor:
            raise P2V3StoreConflict("request-local query descriptor cannot be rebound")
        self._descriptors[query_ref] = descriptor
        return query_ref

    @staticmethod
    def _continuation_proof_sha256(proof: Any) -> str:
        from . import p2_source_codec_v3 as codec3

        if not isinstance(proof, codec3.V3ContinuationProof):
            raise P2V3StoreConflict("continuation proof must use the strict source codec type")
        return codec3.stable_digest({
            "logical_query_id": proof.logical_query_id,
            "query_attempt_id": proof.query_attempt_id,
            "page_index": proof.page_index,
            "query_evidence_ref": proof.query_evidence_ref,
            "query_digest": proof.query_digest,
            "body_digest": proof.body_digest,
            "projection_digest": proof.projection_digest,
            "normalized_criteria_digest": proof.normalized_criteria_digest,
            "source_total": proof.source_total,
            "financial_versions_digest": proof.financial_versions_digest,
            "source_query_complete": proof.source_query_complete,
        })

    def issue_continuation(
        self,
        *,
        logical_query_id: str,
        query_attempt_id: str,
        attempt_seq: int,
        page_index: int,
        source_proof: Any,
        projection_sha256: str,
        expires_at: datetime,
        identity: Any,
    ) -> str:
        from . import p2_source_codec_v3 as codec3

        if (
            identity != self.identity
            or type(logical_query_id) is not str or not logical_query_id
            or type(query_attempt_id) is not str or not query_attempt_id
            or type(attempt_seq) is not int or attempt_seq < 1
            or page_index != 0
            or not isinstance(source_proof, codec3.V3ContinuationProof)
            or source_proof.logical_query_id != logical_query_id
            or source_proof.query_attempt_id != query_attempt_id
            or source_proof.page_index != page_index
            or source_proof.projection_digest != projection_sha256
            or type(expires_at) is not datetime
            or expires_at.tzinfo is None or expires_at.utcoffset() is None
        ):
            raise P2V3StoreConflict("continuation issuance is outside its accepted page-zero binding")
        query_ref = self.query_ref(logical_query_id, identity=identity)
        if query_ref in self._continuation_issued_queries:
            raise P2V3StoreConflict("this source query already issued its one continuation")
        raw_ref = self._new_ref()
        self._store._issue_p2_v3_continuation_token(
            self.identity.owner_user_id, self.identity.turn_id,
            claim_token=self._claim_token,
            logical_query_id=logical_query_id,
            raw_next_page_ref=raw_ref,
            admission_id=self.admission_id,
            attempt_seq=attempt_seq,
            issuer_page_index=page_index,
            source_proof_sha256=self._continuation_proof_sha256(source_proof),
            projection_sha256=projection_sha256,
            expires_at=expires_at,
        )
        key = (query_ref, raw_ref)
        self._continuation_proofs[key] = source_proof
        self._continuation_attempts[key] = attempt_seq
        self._continuation_issued_queries.add(query_ref)
        return raw_ref

    def load_continuation_proof(self, *, query_ref: str, next_page_ref: str, identity: Any) -> Any:
        if identity != self.identity or self._query_ids.get(query_ref) is None:
            raise P2V3StoreConflict("continuation identity mismatch")
        try:
            return self._continuation_proofs[(query_ref, next_page_ref)]
        except KeyError:
            raise P2V3StoreNotFound("continuation is unavailable") from None

    def consume_continuation(self, *, query_ref: str, next_page_ref: str, turn_id: uuid.UUID) -> Any:
        from . import p2_source_codec_v3 as codec3

        if turn_id != self.identity.turn_id:
            raise P2V3StoreConflict("continuation belongs to another Turn")
        logical_query_id = self._query_ids.get(query_ref)
        key = (query_ref, next_page_ref)
        proof = self._continuation_proofs.get(key)
        attempt_seq = self._continuation_attempts.get(key)
        if (
            logical_query_id is None
            or proof is None
            or not isinstance(proof, codec3.V3ContinuationProof)
            or proof.logical_query_id != logical_query_id
            or attempt_seq is None
            or proof.page_index != 0
            or key in self._consumed_continuations
        ):
            raise P2V3StoreConflict("continuation is unavailable, stale, or already consumed")
        attempt_id, page_index, consumed_seq = self._store.consume_p2_v3_continuation(
            self.identity.owner_user_id, self.identity.turn_id,
            claim_token=self._claim_token,
            logical_query_id=logical_query_id,
            raw_next_page_ref=next_page_ref,
            admission_id=self.admission_id,
            attempt_seq=attempt_seq,
            page_index=proof.page_index + 1,
            source_proof_sha256=self._continuation_proof_sha256(proof),
            projection_sha256=proof.projection_digest,
        )
        if consumed_seq != attempt_seq:
            raise P2V3StoreConflict("continuation attempt sequence changed during consumption")
        self._consumed_continuations.add(key)
        return codec3.QueryAttemptBinding(
            identity=self.identity,
            logical_query_id=logical_query_id,
            query_attempt_id=attempt_id,
            page_index=page_index,
            claim_token=self._claim_token,
        )

    def _assert_store_issued(self, store: Any, *, identity: Any, admission_id: str, claim_token: str) -> None:
        if (
            self._seal is not _P2_V3_REFERENCE_REGISTRY_SEAL
            or self._store is not store
            or self.identity != identity
            or self.admission_id != admission_id
            or self._claim_token != claim_token
        ):
            raise P2V3StoreConflict("request-local reference registry binding does not match this admission")


@dataclass(frozen=True)
class P2V3TurnSnapshot:
    owner_user_id: str
    turn_id: str
    profile_id: str
    versions: tuple[str, str, str, str]
    schema_bundle_sha256: str
    source_manifest_sha256: str
    contract_source_sha256: str
    generation: int
    input_seq: int
    input_digest: str
    context_revision: int
    state_revision: int
    claim_epoch: int
    authority_epoch: int
    lifecycle: str
    revision: int
    model_calls: int
    model_reserved_calls: int
    repair_calls: int
    repair_reserved_calls: int
    logical_read_calls: int
    active_used_us: int
    active_reserved_us: int
    backend_used_us: int
    backend_reserved_us: int
    get_attempts: int
    get_reserved: int
    response_bytes: int
    bytes_reserved: int
    historical_unknown_consumption: bool


@dataclass(frozen=True)
class P2V3QuerySnapshot:
    logical_query_id: str
    owner_user_id: str
    turn_id: str
    operation: str
    generation: int
    input_seq: int
    input_digest: str
    authority_epoch: int
    criteria_json: str
    criteria_digest: str
    scope_json: str
    scope_digest: str
    admission_id: str


@dataclass(frozen=True)
class P2V3ResumeQueryDescriptor:
    """Strict immutable query data for restarting the current input without replanning."""

    logical_query_id: str
    operation: str
    criteria_json: str
    scope_json: str
    private_selection_refs: tuple[str, ...]
    generation: int
    input_seq: int
    input_digest: str
    cohort_sha256: str


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: Any, *, max_bytes: int) -> tuple[str, str]:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    encoded = raw.encode("utf-8")
    if len(encoded) > max_bytes:
        raise ValueError("candidate descriptor exceeds its private storage bound")
    return raw, _digest(encoded)


def _private_scope_descriptor(value: Any) -> dict[str, Optional[str] | str]:
    """Accept only bounded private scope locators; never retain a raw request/body."""
    if not isinstance(value, dict) or set(value) not in (
        {"scope_kind"}, {"scope_kind", "activity_id"},
        {"scope_kind", "activity_id", "ledger_unit_id"},
    ):
        raise ValueError("private scope descriptor has an unsupported shape")
    kind = value.get("scope_kind")
    if kind == "none":
        if set(value) != {"scope_kind"}:
            raise ValueError("no-scope descriptor cannot include entity locators")
        return {"scope_kind": "none"}
    if kind not in {"activity", "ledger_unit"}:
        raise ValueError("private scope kind is not allowlisted")
    if "activity_id" not in value or (
        kind == "activity"
        and (
            set(value) not in (
                {"scope_kind", "activity_id"},
                {"scope_kind", "activity_id", "ledger_unit_id"},
            )
            or value.get("ledger_unit_id") is not None
        )
    ) or (
        kind == "ledger_unit" and set(value) != {"scope_kind", "activity_id", "ledger_unit_id"}
    ):
        raise ValueError("private scope locator fields do not match its kind")
    try:
        activity_id = str(uuid.UUID(value["activity_id"]))
        ledger_unit_id = str(uuid.UUID(value["ledger_unit_id"])) if kind == "ledger_unit" else None
    except (TypeError, ValueError, AttributeError):
        raise ValueError("private scope entity locators must be UUIDs") from None
    return {"scope_kind": kind, "activity_id": activity_id, "ledger_unit_id": ledger_unit_id}


def _safe_ui_hint(value: Any) -> Optional[dict[str, str]]:
    if value is None:
        return None
    allowed = {"activity_id", "expense_id", "ledger_unit_id", "participant_id"}
    if not isinstance(value, dict) or not value or set(value) - allowed:
        raise ValueError("UI context hint contains unsupported fields")
    output: dict[str, str] = {}
    for key, raw in value.items():
        try:
            output[key] = str(uuid.UUID(raw))
        except (TypeError, ValueError, AttributeError):
            raise ValueError("UI context hint fields must be UUID locators") from None
    return output


def _wire_query_descriptor(operation: str, criteria: Any, scope: Any) -> tuple[str, str, str, str]:
    if isinstance(criteria, BaseModel):
        # Preserve strict Python values such as datetime.date through the
        # Pydantic strict validation boundary. JSON-mode dump stringifies date
        # values, and strict validation correctly refuses those strings.
        criteria_value = criteria.model_dump(mode="python", exclude_none=False)
    else:
        criteria_value = criteria
    if isinstance(scope, P2Scope):
        scope_value = scope.model_dump(mode="python", exclude_none=False)
    else:
        scope_value = scope
    try:
        request = P2ReadQueryRequest.model_validate({
            "kind": "read",
            "message_type": "query_request",
            "profile_id": CONTRACT_P2_V3_PROFILE_ID,
            "versions": CONTRACT_P2_V3_VERSIONS.model_dump(mode="json"),
            "operation": operation,
            "criteria": criteria_value,
            "scope": scope_value,
        }, strict=True)
    except Exception:
        raise ValueError("logical read criteria or scope failed the reviewed strict v3 contract") from None
    criteria_json, _ = _canonical_json(
        request.criteria.model_dump(mode="json", exclude_none=False), max_bytes=32768,
    )
    # The immutable query descriptor preserves optional defaults explicitly,
    # while the grant/QEV criteria digest follows the public contract's
    # exclude_none=True definition. Keep the audit JSON and public digest as
    # separate bindings.
    criteria_digest = _public_criteria_digest(request.criteria)
    scope_json, scope_digest = _canonical_json(
        request.scope.model_dump(mode="json", exclude_none=False) if request.scope is not None else None,
        max_bytes=32768,
    )
    return criteria_json, criteria_digest, scope_json, scope_digest


def _normalized_criteria_digest(criteria_json: str, ui_expense_refs: Sequence[str]) -> str:
    """Hash the reviewed public criteria projection, separately from Store audit metadata."""
    try:
        criteria_value = json.loads(criteria_json)
    except (TypeError, ValueError):
        raise ValueError("strict criteria JSON cannot be normalized") from None
    _, digest = _canonical_json({
        "criteria": criteria_value,
        "ui_expense_refs": sorted(ui_expense_refs),
    }, max_bytes=32768)
    return digest


def _private_query_descriptor_json(
    *,
    owner_user_id: str,
    turn_id: str,
    logical_query_id: str,
    operation: str,
    criteria_json: str,
    criteria_digest: str,
    scope_json: str,
    scope_digest: str,
    selected_refs_json: str,
    selected_refs_digest: str,
    normalized_criteria_digest: str,
    admission_id: str,
    generation: int,
    input_seq: int,
    input_digest: str,
    authority_epoch: int,
    context_revision: int,
    cohort_sha256: str,
) -> tuple[str, str]:
    """Private audit binding; deliberately distinct from the public criteria digest."""
    return _canonical_json({
        "owner_user_id": owner_user_id,
        "turn_id": turn_id,
        "logical_query_id": logical_query_id,
        "operation": operation,
        "criteria_json": criteria_json,
        "criteria_digest": criteria_digest,
        "scope_json": scope_json,
        "scope_digest": scope_digest,
        "selected_refs_json": selected_refs_json,
        "selected_refs_digest": selected_refs_digest,
        "normalized_criteria_digest": normalized_criteria_digest,
        "admission_id": admission_id,
        "generation": generation,
        "input_seq": input_seq,
        "input_digest": input_digest,
        "authority_epoch": authority_epoch,
        "context_revision": context_revision,
        "cohort_sha256": cohort_sha256,
    }, max_bytes=49152)


def _strict_nonnegative_int(value: int, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def _strict_positive_int(value: int, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _check_sha256(value: Optional[str], name: str, *, required: bool = False) -> Optional[str]:
    if value is None and not required:
        return None
    if type(value) is not str or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
    return value


def _stamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("candidate timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise RuntimeError("stored P2 v3 timestamp is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RuntimeError("stored P2 v3 timestamp has no timezone")
    return parsed.astimezone(timezone.utc)


def _now(value: Optional[datetime]) -> datetime:
    instant = value if value is not None else datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("candidate timestamps must be timezone-aware")
    return instant.astimezone(timezone.utc)


def _p2_v3_metadata_request_pairs(
    table: str, activity_id: uuid.UUID, principal_user_id: uuid.UUID, offset: int,
) -> list[tuple[str, str]]:
    """Exact bounded bootstrap GET plan; caller filters cannot select rows."""
    from . import p2_source_codec_v3 as codec3

    plans: dict[str, tuple[list[tuple[str, str]], str]] = {
        "activities": ([ ("id", f"eq.{activity_id}"), ("is_deleted", "eq.false") ], "id.asc"),
        "activity_members": ([ ("activity_id", f"eq.{activity_id}"), ("user_id", f"eq.{principal_user_id}") ], "activity_id.asc"),
        "ledger_units": ([ ("activity_id", f"eq.{activity_id}") ], "id.asc"),
        "participants": ([ ("activity_id", f"eq.{activity_id}") ], "participant_order.asc,id.asc"),
        "sub_activity_participants": ([ ("activity_id", f"eq.{activity_id}") ], "ledger_unit_id.asc,participant_id.asc"),
        "participant_claims": ([ ("activity_id", f"eq.{activity_id}"), ("user_id", f"eq.{principal_user_id}") ], "id.asc"),
    }
    if table not in plans or type(offset) is not int or offset < 0:
        raise P2V3StoreConflict("metadata source table or offset is unsupported")
    filters, order = plans[table]
    return [
        ("select", ",".join(codec3._SOURCE_COLUMNS[table])), *filters,
        ("order", order), ("limit", str(codec3.MAX_ROWS_PER_PAGE)), ("offset", str(offset)),
    ]


class P2V3StoreMixin:
    """Helpers that participate in SQLiteAgentStore's existing connection/txn."""

    @staticmethod
    def _cohort_metadata_values(cohort: P2V3VerifiedExecutionCohort) -> tuple[Any, ...]:
        return (
            cohort.manifest_sha256,
            cohort.manifest_kind,
            cohort.profile_id,
            cohort.versions[0], cohort.versions[1], cohort.versions[2], cohort.versions[3],
            cohort.schema_bundle_sha256, cohort.source_manifest_sha256,
            cohort.contract_source_sha256, cohort.safe_config_sha256, len(cohort.components),
        )

    def _persist_p2_v3_execution_pin(
        self,
        connection: sqlite3.Connection,
        *,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        cohort: P2V3VerifiedExecutionCohort,
        now: datetime,
    ) -> None:
        """Persist the verifier result and the exact new-Turn pin in the caller transaction."""
        allow_synthetic = bool(getattr(self, "_test_only_allow_synthetic_p2_v3_cohort", False))
        if not is_verified_execution_cohort(cohort) or (cohort.is_synthetic and not allow_synthetic):
            raise P2V3UnsupportedProfile("only a verified enabled execution cohort may pin a candidate Turn")
        cohort = cohort.verify_unchanged()
        values = self._cohort_metadata_values(cohort)
        stored = connection.execute(
            "SELECT * FROM p2_v3_execution_cohorts WHERE cohort_sha256=?", (cohort.manifest_sha256,),
        ).fetchone()
        if stored is None:
            connection.execute(
                """INSERT INTO p2_v3_execution_cohorts (
                    cohort_sha256,manifest_kind,profile_id,api_version,semantic_version,
                    operations_version,trajectory_version,schema_bundle_sha256,
                    source_manifest_sha256,contract_source_sha256,safe_config_sha256,
                    component_count,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (*values, _stamp(now)),
            )
            connection.executemany(
                """INSERT INTO p2_v3_execution_cohort_components (
                    cohort_sha256,component_path,component_role,byte_count,component_sha256
                ) VALUES (?,?,?,?,?)""",
                [
                    (cohort.manifest_sha256, item.path, item.role, item.byte_count, item.sha256)
                    for item in cohort.components
                ],
            )
        else:
            stored_values = (
                stored["cohort_sha256"], stored["manifest_kind"], stored["profile_id"],
                stored["api_version"], stored["semantic_version"], stored["operations_version"],
                stored["trajectory_version"], stored["schema_bundle_sha256"],
                stored["source_manifest_sha256"], stored["contract_source_sha256"],
                stored["safe_config_sha256"], int(stored["component_count"]),
            )
            if stored_values != values:
                raise P2V3UnsupportedProfile("stored execution cohort conflicts with the verifier result")
            stored_components = [
                (row["component_path"], row["component_role"], int(row["byte_count"]), row["component_sha256"])
                for row in connection.execute(
                    "SELECT * FROM p2_v3_execution_cohort_components WHERE cohort_sha256=? ORDER BY component_path",
                    (cohort.manifest_sha256,),
                )
            ]
            expected_components = sorted(
                (item.path, item.role, item.byte_count, item.sha256) for item in cohort.components
            )
            if stored_components != expected_components:
                raise P2V3UnsupportedProfile("stored execution cohort components conflict with the verifier result")

        row = connection.execute(
            "SELECT * FROM p2_v3_turns WHERE turn_id=? AND owner_user_id=?",
            (str(turn_id), str(owner_user_id)),
        ).fetchone()
        if row is None:
            raise P2V3StoreConflict("v3 assignment row must exist before the immutable cohort pin")
        pin_exists = connection.execute(
            "SELECT 1 FROM p2_v3_turn_execution_pins WHERE turn_id=? AND owner_user_id=?",
            (str(turn_id), str(owner_user_id)),
        ).fetchone()
        if pin_exists is not None:
            raise P2V3StoreConflict("an immutable P2 v3 execution pin already exists")
        connection.execute(
            """INSERT INTO p2_v3_turn_execution_pins (
                turn_id,owner_user_id,cohort_sha256,manifest_sha256,profile_id,
                api_version,semantic_version,operations_version,trajectory_version,
                schema_bundle_sha256,source_manifest_sha256,contract_source_sha256,
                safe_config_sha256,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                str(turn_id), str(owner_user_id), cohort.manifest_sha256, cohort.manifest_sha256,
                cohort.profile_id, *cohort.versions, cohort.schema_bundle_sha256,
                cohort.source_manifest_sha256, cohort.contract_source_sha256,
                cohort.safe_config_sha256, _stamp(now),
            ),
        )

    @staticmethod
    def _component_projection_digest(rows: list[sqlite3.Row]) -> str:
        value = [
            {"path": row["component_path"], "role": row["component_role"],
             "bytes": int(row["byte_count"]), "sha256": row["component_sha256"]}
            for row in sorted(rows, key=lambda item: (item["component_path"], item["component_role"]))
        ]
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
        return _digest(raw)

    def _verify_p2_v3_execution_pin_rows(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> tuple[bool, Optional[sqlite3.Row]]:
        """Verify persisted pin/cohort consistency without reinterpreting old unpinned rows."""
        owner_id, turn_id = row["owner_user_id"], row["turn_id"]
        pin = connection.execute(
            "SELECT * FROM p2_v3_turn_execution_pins WHERE turn_id=? AND owner_user_id=?",
            (turn_id, owner_id),
        ).fetchone()
        if pin is None:
            return False, None
        cohort = connection.execute(
            "SELECT * FROM p2_v3_execution_cohorts WHERE cohort_sha256=?", (pin["cohort_sha256"],),
        ).fetchone()
        if cohort is None:
            raise RuntimeError("P2 v3 immutable Turn pin has no stored execution cohort")
        component_rows = connection.execute(
            "SELECT * FROM p2_v3_execution_cohort_components WHERE cohort_sha256=? ORDER BY component_path",
            (pin["cohort_sha256"],),
        ).fetchall()
        if len(component_rows) != int(cohort["component_count"]):
            raise RuntimeError("P2 v3 execution cohort component set is incomplete")
        source_digest = self._component_projection_digest(component_rows)
        schema_rows = [item for item in component_rows if item["component_role"] == "schema_bundle"]
        schema_digest = schema_rows[0]["component_sha256"] if len(schema_rows) == 1 else (
            hashlib.sha256(b"synthetic-test-schema-bundle").hexdigest()
            if cohort["manifest_kind"] == "synthetic_test" else ""
        )
        contract_rows = [item for item in component_rows if item["component_role"] == "read_contracts"]
        contract_digest = contract_rows[0]["component_sha256"] if len(contract_rows) == 1 else (
            hashlib.sha256(b"synthetic-test-contract-snapshot").hexdigest()
            if cohort["manifest_kind"] == "synthetic_test" else ""
        )
        expected_cohort = (
            row["profile_id"], row["api_version"], row["semantic_version"],
            row["operations_version"], row["trajectory_version"],
            row["schema_bundle_sha256"], row["source_manifest_sha256"], row["contract_source_sha256"],
        )
        pin_cohort = (
            pin["profile_id"], pin["api_version"], pin["semantic_version"],
            pin["operations_version"], pin["trajectory_version"],
            pin["schema_bundle_sha256"], pin["source_manifest_sha256"], pin["contract_source_sha256"],
        )
        stored_cohort = (
            cohort["profile_id"], cohort["api_version"], cohort["semantic_version"],
            cohort["operations_version"], cohort["trajectory_version"],
            cohort["schema_bundle_sha256"], cohort["source_manifest_sha256"], cohort["contract_source_sha256"],
        )
        if (
            pin["manifest_sha256"] != pin["cohort_sha256"]
            or pin["manifest_sha256"] != cohort["cohort_sha256"]
            or pin["safe_config_sha256"] != cohort["safe_config_sha256"]
            or expected_cohort != pin_cohort or pin_cohort != stored_cohort
            or source_digest != cohort["source_manifest_sha256"]
            or schema_digest != cohort["schema_bundle_sha256"]
            or contract_digest != cohort["contract_source_sha256"]
        ):
            raise RuntimeError("P2 v3 execution pin, cohort or component digests disagree")
        return True, pin

    def _require_current_p2_v3_pin(self, connection: sqlite3.Connection, row: sqlite3.Row) -> None:
        pinned, pin = self._verify_p2_v3_execution_pin_rows(connection, row)
        cohort = getattr(self, "_p2_v3_execution_cohort", None)
        if not pinned or pin is None or cohort is None or not is_verified_execution_cohort(cohort):
            raise P2V3UnsupportedProfile("P2 v3 Turn has no current verified execution cohort pin")
        if cohort.is_synthetic and not getattr(self, "_test_only_allow_synthetic_p2_v3_cohort", False):
            raise P2V3UnsupportedProfile("synthetic execution cohort cannot authorize P2 v3 work")
        if (
            pin["manifest_sha256"] != cohort.manifest_sha256
            or pin["profile_id"] != cohort.profile_id
            or (pin["api_version"], pin["semantic_version"], pin["operations_version"], pin["trajectory_version"]) != cohort.versions
            or pin["schema_bundle_sha256"] != cohort.schema_bundle_sha256
            or pin["source_manifest_sha256"] != cohort.source_manifest_sha256
            or pin["contract_source_sha256"] != cohort.contract_source_sha256
            or pin["safe_config_sha256"] != cohort.safe_config_sha256
        ):
            raise P2V3UnsupportedProfile("P2 v3 Turn belongs to an unsupported immutable execution cohort")
        try:
            cohort = cohort.verify_unchanged()
            self._p2_v3_execution_cohort = cohort
        except (OSError, P2V3ExecutionManifestError, ValueError):
            raise P2V3UnsupportedProfile("P2 v3 current execution cohort changed after verification") from None

    def _insert_p2_v3_turn(
        self,
        connection: sqlite3.Connection,
        *,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        generation: int,
        input_seq: int,
        input_digest: str,
        context_revision: int,
        state_revision: int,
        lifecycle: str,
        execution_cohort: P2V3VerifiedExecutionCohort,
        now: datetime,
    ) -> None:
        if lifecycle not in {"queued", "active", "waiting", "terminal", "invalidated"}:
            raise ValueError("invalid v3 lifecycle")
        _check_sha256(input_digest, "input_digest", required=True)
        allow_synthetic = bool(getattr(self, "_test_only_allow_synthetic_p2_v3_cohort", False))
        if not is_verified_execution_cohort(execution_cohort) or (
            execution_cohort.is_synthetic and not allow_synthetic
        ):
            raise P2V3UnsupportedProfile("new P2 v3 assignment requires an enabled verifier-issued cohort")
        execution_cohort = execution_cohort.verify_unchanged()
        connection.execute(
            """INSERT INTO p2_v3_turns (
                turn_id, owner_user_id, profile_id, api_version, semantic_version,
                operations_version, trajectory_version, schema_bundle_sha256,
                source_manifest_sha256, contract_source_sha256, generation, input_seq,
                input_digest, context_revision, turn_state_revision, claim_epoch,
                authority_epoch, lifecycle, revision, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, 1, ?, ?)""",
            (
                str(turn_id), str(owner_user_id), P2_V3_CANDIDATE_PROFILE_ID,
                P2_V3_VERSIONS["api"], P2_V3_VERSIONS["semantic"],
                P2_V3_VERSIONS["operations"], P2_V3_VERSIONS["trajectory"],
                execution_cohort.schema_bundle_sha256, execution_cohort.source_manifest_sha256,
                execution_cohort.contract_source_sha256, generation, input_seq, input_digest,
                context_revision, state_revision, lifecycle,
                _stamp(now), _stamp(now),
            ),
        )

    @staticmethod
    def _p2_v3_snapshot(row: sqlite3.Row) -> P2V3TurnSnapshot:
        versions = (
            row["api_version"], row["semantic_version"],
            row["operations_version"], row["trajectory_version"],
        )
        if (
            row["profile_id"] != P2_V3_CANDIDATE_PROFILE_ID
            or versions != tuple(P2_V3_VERSIONS[key] for key in ("api", "semantic", "operations", "trajectory"))
            or any(
                type(row[field]) is not str or re.fullmatch(r"[0-9a-f]{64}", row[field]) is None
                for field in ("schema_bundle_sha256", "source_manifest_sha256", "contract_source_sha256")
            )
        ):
            raise P2V3UnsupportedProfile("stored P2 v3 profile or version tuple is not supported")
        return P2V3TurnSnapshot(
            owner_user_id=row["owner_user_id"], turn_id=row["turn_id"],
            profile_id=row["profile_id"], versions=versions,
            schema_bundle_sha256=row["schema_bundle_sha256"],
            source_manifest_sha256=row["source_manifest_sha256"],
            contract_source_sha256=row["contract_source_sha256"],
            generation=int(row["generation"]), input_seq=int(row["input_seq"]),
            input_digest=row["input_digest"], context_revision=int(row["context_revision"]),
            state_revision=int(row["turn_state_revision"]), claim_epoch=int(row["claim_epoch"]),
            authority_epoch=int(row["authority_epoch"]), lifecycle=row["lifecycle"],
            revision=int(row["revision"]), model_calls=int(row["model_calls"]),
            model_reserved_calls=int(row["model_reserved_calls"]),
            repair_calls=int(row["repair_calls"]),
            repair_reserved_calls=int(row["repair_reserved_calls"]),
            logical_read_calls=int(row["logical_read_calls"]),
            active_used_us=int(row["active_used_us"]), active_reserved_us=int(row["active_reserved_us"]),
            backend_used_us=int(row["backend_used_us"]), backend_reserved_us=int(row["backend_reserved_us"]),
            get_attempts=int(row["get_attempts"]), get_reserved=int(row["get_reserved"]),
            response_bytes=int(row["response_bytes"]), bytes_reserved=int(row["bytes_reserved"]),
            historical_unknown_consumption=bool(row["historical_unknown_consumption"]),
        )

    @staticmethod
    def _p2_v3_overrun_totals(
        connection: sqlite3.Connection,
        owner_user_id: str,
        turn_id: str,
    ) -> tuple[int, int, int]:
        """Return append-only measured overrun not represented by capped turn counters.

        The summary columns deliberately remain within the frozen 003 CHECK limits.
        Therefore reservation admission must add terminal-event overruns in the same
        IMMEDIATE transaction before deciding whether any work remains.
        """
        rows = connection.execute(
            """SELECT reservation_id,overrun_active_us,overrun_backend_us,overrun_response_bytes
               FROM p2_v3_charge_events
               WHERE owner_user_id=? AND turn_id=?
                 AND event_kind IN ('settled','known_no_dispatch','unknown')""",
            (owner_user_id, turn_id),
        ).fetchall()
        by_reservation: dict[str, list[int]] = {}
        for row in rows:
            reservation_id = str(row["reservation_id"])
            values = by_reservation.setdefault(reservation_id, [0, 0, 0])
            for index, column in enumerate(("overrun_active_us", "overrun_backend_us", "overrun_response_bytes")):
                value = row[column]
                if type(value) is not int or value < 0:
                    raise RuntimeError("P2 v3 terminal overrun ledger is malformed")
                values[index] = max(values[index], value)
        # V005 observations refine the same processing reservation. Use the
        # maximum across its 003 terminal and V005 append-only observations,
        # then sum across distinct reservations; never double-charge a copied
        # terminal overrun.
        metadata_rows = connection.execute(
            """SELECT b.processing_reservation_id,
                      MAX(e.overrun_active_us) AS overrun_active_us,
                      MAX(e.overrun_backend_us) AS overrun_backend_us
               FROM p2_v3_metadata_acceptance_batches b
               JOIN p2_v3_metadata_acceptance_events e ON e.acceptance_id=b.acceptance_id
               WHERE b.owner_user_id=? AND b.turn_id=?
               GROUP BY b.processing_reservation_id""",
            (owner_user_id, turn_id),
        ).fetchall()
        for row in metadata_rows:
            reservation_id = str(row["processing_reservation_id"])
            values = by_reservation.setdefault(reservation_id, [0, 0, 0])
            for index, column in enumerate(("overrun_active_us", "overrun_backend_us")):
                value = row[column]
                if type(value) is not int or value < 0:
                    raise RuntimeError("P2 v3 metadata overrun ledger is malformed")
                values[index] = max(values[index], value)
        return tuple(sum(values[index] for values in by_reservation.values()) for index in range(3))

    def _p2_v3_current_claim(
        self,
        connection: sqlite3.Connection,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        *,
        claim_token: str,
        now: datetime,
    ) -> tuple[sqlite3.Row, P2V3TurnSnapshot, Any]:
        turn_row = self._owned_turn(connection, owner_user_id, turn_id)
        aggregate = self._turn_aggregate(turn_row)
        self._check_claim(aggregate, claim_token, now)
        if aggregate.record.turn.state != TurnState.RUNNING:
            raise P2V3StoreConflict("v3 candidate work requires the current RUNNING Turn")
        candidate = connection.execute(
            "SELECT * FROM p2_v3_turns WHERE turn_id = ? AND owner_user_id = ?",
            (str(turn_id), str(owner_user_id)),
        ).fetchone()
        if candidate is None:
            raise P2V3StoreNotFound("v3 candidate Turn is not available to this owner")
        snapshot = self._p2_v3_snapshot(candidate)
        input_seq, input_digest = self._p2_input_binding(aggregate.checkpoint)
        if (
            snapshot.generation != aggregate.checkpoint.generation
            or snapshot.input_seq != input_seq
            or snapshot.input_digest != input_digest
            or snapshot.context_revision != aggregate.checkpoint_revision
            or snapshot.state_revision != aggregate.record.turn.state_revision
            or snapshot.lifecycle != "active"
        ):
            raise P2V3StoreConflict("v3 candidate input, claim or revision binding changed")
        self._require_current_p2_v3_pin(connection, candidate)
        return candidate, snapshot, aggregate

    def _verify_p2_v3_rows(self, connection: sqlite3.Connection) -> None:
        """Fail closed on malformed v3 pins, ledgers, or derived budget summaries."""
        overlap = connection.execute(
            "SELECT 1 FROM p2_v3_turns v3 JOIN p2_candidate_turns v2 USING(turn_id) LIMIT 1"
        ).fetchone()
        if overlap is not None:
            raise RuntimeError("Turn is assigned to more than one candidate Store family")
        required_triggers = {
            "p2_v3_turn_identity_immutable", "p2_v3_turn_no_delete",
            "p2_v3_excludes_v2_family", "p2_v2_excludes_v3_family",
            "p2_v3_charge_events_append_only_update", "p2_v3_charge_events_append_only_delete",
            "p2_v3_admissions_append_only_update", "p2_v3_admissions_append_only_delete",
            "p2_v3_queries_append_only_update", "p2_v3_queries_append_only_delete",
            "p2_v3_attempts_append_only_update", "p2_v3_attempts_append_only_delete",
            "p2_v3_captures_append_only_update", "p2_v3_captures_append_only_delete",
            "p2_v3_nonce_uses_append_only_update", "p2_v3_nonce_uses_append_only_delete",
            "p2_v3_nonce_issues_append_only_update", "p2_v3_nonce_issues_append_only_delete",
        }
        actual_triggers = {
            str(row[0]) for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND (name LIKE 'p2_v3_%' OR name='p2_v2_excludes_v3_family')"
            )
        }
        if not required_triggers.issubset(actual_triggers):
            raise RuntimeError("P2 v3 append-only or family-exclusion trigger is missing")
        for row in connection.execute("SELECT * FROM p2_v3_turns ORDER BY turn_id"):
            try:
                snapshot = self._p2_v3_snapshot(row)
            except P2V3UnsupportedProfile:
                # Preserve old immutable pins and keep canonical/v2 Store startup usable.
                # Candidate access/claim will reject this Turn under the current cohort.
                continue
            self._verify_p2_v3_execution_pin_rows(connection, row)
            turn = connection.execute(
                "SELECT * FROM turns WHERE turn_id=? AND owner_user_id=?",
                (snapshot.turn_id, snapshot.owner_user_id),
            ).fetchone()
            if turn is None:
                raise RuntimeError("P2 v3 assignment has no matching durable Turn")
            checkpoint = self._turn_aggregate(turn).checkpoint
            input_seq, input_digest = self._p2_input_binding(checkpoint)
            if (
                snapshot.generation != checkpoint.generation or snapshot.input_seq != input_seq
                or snapshot.input_digest != input_digest or snapshot.context_revision != int(turn["checkpoint_revision"])
                or snapshot.state_revision != int(turn["state_revision"])
            ):
                raise RuntimeError("P2 v3 assignment pin no longer matches its durable Turn")
            reservations = connection.execute(
                "SELECT * FROM p2_v3_charge_events WHERE owner_user_id=? AND turn_id=? AND event_kind='reserved'",
                (snapshot.owner_user_id, snapshot.turn_id),
            ).fetchall()
            derived = {
                "active_used_us": 0, "active_reserved_us": 0,
                "backend_used_us": 0, "backend_reserved_us": 0,
                "response_bytes": 0, "bytes_reserved": 0,
                "model_calls": 0, "model_reserved_calls": 0,
                "repair_calls": 0, "repair_reserved_calls": 0,
                "get_attempts": 0, "get_reserved": 0,
            }
            for reservation in reservations:
                events = connection.execute(
                    "SELECT * FROM p2_v3_charge_events WHERE reservation_id=? AND owner_user_id=? AND turn_id=? "
                    "ORDER BY occurred_at,CASE event_kind "
                    "WHEN 'reserved' THEN 0 WHEN 'dispatch_started' THEN 1 "
                    "WHEN 'settled' THEN 2 WHEN 'known_no_dispatch' THEN 2 "
                    "WHEN 'unknown' THEN 2 ELSE 3 END,event_id",
                    (reservation["reservation_id"], snapshot.owner_user_id, snapshot.turn_id),
                ).fetchall()
                kinds = [event["event_kind"] for event in events]
                if not kinds or kinds[0] != "reserved" or kinds.count("reserved") != 1:
                    raise RuntimeError("P2 v3 reservation history is malformed")
                if kinds.count("dispatch_started") > 1 or sum(kind in {"settled", "known_no_dispatch", "unknown"} for kind in kinds) > 1:
                    raise RuntimeError("P2 v3 reservation has duplicate dispatch or settlement")
                started = "dispatch_started" in kinds
                terminal = next((event for event in events if event["event_kind"] in {"settled", "known_no_dispatch", "unknown"}), None)
                stage = reservation["stage"]
                model = int(stage in {"model", "repair"})
                repair = int(stage == "repair")
                get = int(stage == "backend_get")
                if started:
                    derived["model_calls"] += model
                    derived["repair_calls"] += repair
                    derived["get_attempts"] += get
                if terminal is None:
                    derived["active_reserved_us"] += int(reservation["active_limit_us"])
                    derived["backend_reserved_us"] += int(reservation["backend_limit_us"])
                    derived["bytes_reserved"] += int(reservation["response_bytes_limit"])
                    if not started:
                        derived["model_reserved_calls"] += model
                        derived["repair_reserved_calls"] += repair
                        derived["get_reserved"] += get
                else:
                    derived["active_used_us"] += int(terminal["actual_active_us"] or 0)
                    derived["backend_used_us"] += int(terminal["actual_backend_us"] or 0)
                    derived["response_bytes"] += int(terminal["actual_response_bytes"] or 0)
            derived["logical_read_calls"] = int(connection.execute(
                "SELECT COUNT(*) FROM p2_v3_queries WHERE owner_user_id=? AND turn_id=?",
                (snapshot.owner_user_id, snapshot.turn_id),
            ).fetchone()[0])
            for field, expected in derived.items():
                if int(getattr(snapshot, field)) != expected:
                    raise RuntimeError(f"P2 v3 stored {field} disagrees with append-only charge history")
        self._verify_p2_v3_metadata_acceptance_rows(connection)
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise RuntimeError("P2 v3 candidate Store foreign-key integrity failed")

    @staticmethod
    def _verify_p2_v3_metadata_acceptance_rows(connection: sqlite3.Connection) -> None:
        """Check V005 proof sets and terminal-charge links on every Store open."""
        from . import p2_source_codec_v3 as codec3

        for batch in connection.execute(
            "SELECT * FROM p2_v3_metadata_acceptance_batches ORDER BY created_at,acceptance_id"
        ):
            links = connection.execute(
                "SELECT * FROM p2_v3_metadata_acceptance_proofs WHERE acceptance_id=? ORDER BY ordinal",
                (batch["acceptance_id"],),
            ).fetchall()
            if len(links) != int(batch["proof_count"]) or [int(row["ordinal"]) for row in links] != list(range(len(links))):
                raise RuntimeError("P2 v3 metadata proof set is not contiguous or has the wrong size")
            proof_material = [
                {"ordinal": int(row["ordinal"]), "metadata_proof_id": row["metadata_proof_id"],
                 "source_receipt_id": row["source_receipt_id"]}
                for row in links
            ]
            if codec3.stable_digest(proof_material) != batch["proof_set_sha256"]:
                raise RuntimeError("P2 v3 metadata proof-set digest does not match its immutable links")
            events = connection.execute(
                "SELECT * FROM p2_v3_metadata_acceptance_events WHERE acceptance_id=? ORDER BY event_seq",
                (batch["acceptance_id"],),
            ).fetchall()
            if not events or events[0]["event_seq"] != 1 or events[0]["event_kind"] != "proof_committed":
                raise RuntimeError("P2 v3 metadata acceptance is missing its proof-commit event")
            if [int(row["event_seq"]) for row in events] != list(range(1, len(events) + 1)):
                raise RuntimeError("P2 v3 metadata acceptance event sequence is not contiguous")
            terminal = next((row for row in events if row["event_seq"] == 2), None)
            charge = connection.execute(
                "SELECT * FROM p2_v3_charge_events WHERE reservation_id=? AND owner_user_id=? AND turn_id=? AND event_kind IN('settled','unknown')",
                (batch["processing_reservation_id"], batch["owner_user_id"], batch["turn_id"]),
            ).fetchone()
            if terminal is None:
                # An actively executing worker may be between A and B. A
                # terminal 003 charge without its V005 event is an orphan and
                # must be recovered before Store verification succeeds.
                if charge is not None:
                    raise RuntimeError("P2 v3 metadata terminal charge lacks its V005 terminal event")
                continue
            if charge is None or (
                terminal["reservation_id"] != batch["processing_reservation_id"]
                or terminal["terminal_event_id"] != charge["event_id"]
                or terminal["terminal_charge_kind"] != charge["event_kind"]
                or int(terminal["charged_active_us"]) != int(charge["actual_active_us"])
                or int(terminal["charged_backend_us"]) != int(charge["actual_backend_us"])
                or int(terminal["overrun_active_us"]) != int(charge["overrun_active_us"])
                or int(terminal["overrun_backend_us"]) != int(charge["overrun_backend_us"])
            ):
                raise RuntimeError("P2 v3 metadata terminal event does not match its one 003 charge")
            if len(events) > 2 and terminal["event_kind"] not in {"finalized", "unknown"}:
                raise RuntimeError("P2 v3 metadata observations have no terminal event")

    def _recover_p2_v3_pending_reservations(
        self,
        connection: sqlite3.Connection,
        *,
        owner_user_id: str,
        turn_id: str,
        now: datetime,
    ) -> bool:
        """Conservatively settle orphan reservations once; return whether any were settled."""
        pending = connection.execute(
            """SELECT reserved.* FROM p2_v3_charge_events AS reserved
                WHERE reserved.owner_user_id=? AND reserved.turn_id=? AND reserved.event_kind='reserved'
                  AND NOT EXISTS (SELECT 1 FROM p2_v3_charge_events e
                    WHERE e.reservation_id=reserved.reservation_id AND e.event_kind IN ('settled','known_no_dispatch','unknown'))
                ORDER BY reserved.occurred_at,reserved.reservation_id""",
            (owner_user_id, turn_id),
        ).fetchall()
        changed_any = False
        for reserved in pending:
            started = connection.execute(
                "SELECT 1 FROM p2_v3_charge_events WHERE reservation_id=? AND event_kind='dispatch_started'",
                (reserved["reservation_id"],),
            ).fetchone() is not None
            if started:
                self._insert_p2_v3_charge_event(
                    connection, reserved, event_kind="unknown", now=now,
                    actual_active_us=int(reserved["active_limit_us"]),
                    actual_backend_us=int(reserved["backend_limit_us"]),
                    actual_response_bytes=int(reserved["response_bytes_limit"]),
                )
                unknown = 1
            else:
                self._insert_p2_v3_charge_event(
                    connection, reserved, event_kind="known_no_dispatch", now=now,
                    actual_active_us=int(reserved["active_limit_us"]), actual_backend_us=0,
                    actual_response_bytes=0,
                )
                unknown = 0
            root = connection.execute(
                "SELECT * FROM p2_v3_turns WHERE owner_user_id=? AND turn_id=?",
                (owner_user_id, turn_id),
            ).fetchone()
            if root is None:
                raise RuntimeError("P2 v3 reservation parent disappeared during conservative recovery")
            snapshot = self._p2_v3_snapshot(root)
            stage = reserved["stage"]
            # mark_p2_v3_dispatch_started already committed these logical slots;
            # recovery must never count them a second time.
            started_call = 0
            started_repair = 0
            started_get = 0
            release_call = int(not started and stage in {"model", "repair"})
            release_repair = int(not started and stage == "repair")
            release_get = int(not started and stage == "backend_get")
            changed = connection.execute(
                """UPDATE p2_v3_turns SET active_reserved_us=active_reserved_us-?,
                    active_used_us=active_used_us+?,backend_reserved_us=backend_reserved_us-?,
                    backend_used_us=backend_used_us+?,bytes_reserved=bytes_reserved-?,
                    response_bytes=response_bytes+?,model_reserved_calls=model_reserved_calls-?,
                    model_calls=model_calls+?,repair_reserved_calls=repair_reserved_calls-?,
                    repair_calls=repair_calls+?,get_reserved=get_reserved-?,get_attempts=get_attempts+?,
                    historical_unknown_consumption=MAX(historical_unknown_consumption,?),
                    revision=revision+1,updated_at=? WHERE owner_user_id=? AND turn_id=? AND revision=?
                    AND active_reserved_us>=? AND backend_reserved_us>=? AND bytes_reserved>=?
                    AND model_reserved_calls>=? AND repair_reserved_calls>=? AND get_reserved>=?""",
                (
                    int(reserved["active_limit_us"]), int(reserved["active_limit_us"]),
                    int(reserved["backend_limit_us"]), int(reserved["backend_limit_us"] if started else 0),
                    int(reserved["response_bytes_limit"]), int(reserved["response_bytes_limit"] if started else 0),
                    release_call, started_call, release_repair, started_repair, release_get, started_get,
                    unknown, _stamp(now), owner_user_id, turn_id, snapshot.revision,
                    int(reserved["active_limit_us"]), int(reserved["backend_limit_us"]),
                    int(reserved["response_bytes_limit"]), release_call, release_repair, release_get,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("P2 v3 conservative recovery lost its Store CAS")
            changed_any = True

        # A process may have stopped after Phase A committed its proof batch
        # but before Phase B wrote the V005 terminal event. The 003 reservation
        # recovery above charges that dispatch once as unknown; mirror that
        # same charge into the V005 batch exactly once so it can never be
        # mistaken for publishable metadata after restart.
        orphan_batches = connection.execute(
            """SELECT b.* FROM p2_v3_metadata_acceptance_batches b
               JOIN p2_v3_metadata_acceptance_events proof ON proof.acceptance_id=b.acceptance_id
                    AND proof.event_seq=1 AND proof.event_kind='proof_committed'
               WHERE b.owner_user_id=? AND b.turn_id=?
                 AND NOT EXISTS(SELECT 1 FROM p2_v3_metadata_acceptance_events terminal
                    WHERE terminal.acceptance_id=b.acceptance_id AND terminal.event_seq=2
                      AND terminal.event_kind IN('finalized','unknown'))
               ORDER BY b.created_at,b.acceptance_id""",
            (owner_user_id, turn_id),
        ).fetchall()
        for batch in orphan_batches:
            charge = connection.execute(
                "SELECT * FROM p2_v3_charge_events WHERE reservation_id=? AND owner_user_id=? AND turn_id=? AND event_kind IN('settled','unknown')",
                (batch["processing_reservation_id"], owner_user_id, turn_id),
            ).fetchone()
            if charge is None or charge["event_kind"] != "unknown":
                raise RuntimeError("orphan metadata proof batch lacks a conservatively recovered unknown charge")
            connection.execute(
                """INSERT INTO p2_v3_metadata_acceptance_events (
                       acceptance_id,event_seq,event_kind,owner_user_id,turn_id,reservation_id,
                       terminal_event_id,terminal_charge_kind,cost_basis,measured_active_us,
                       measured_backend_us,charged_active_us,charged_backend_us,observation_outcome,
                       overrun_active_us,overrun_backend_us,occurred_at
                   ) VALUES (?,2,'unknown',?,?,?,?, 'unknown','unknown_cap',NULL,NULL,?,?,NULL,?,?,?)""",
                (
                    batch["acceptance_id"], owner_user_id, turn_id,
                    batch["processing_reservation_id"], charge["event_id"],
                    int(charge["actual_active_us"]), int(charge["actual_backend_us"]),
                    int(charge["overrun_active_us"]), int(charge["overrun_backend_us"]), _stamp(now),
                ),
            )
            changed_any = True
        return changed_any

    def _recover_p2_v3_process_start(self, connection: sqlite3.Connection, *, instant: datetime) -> None:
        """Invalidate only expired/missing claims; a second Store cannot steal a live lease."""
        rows = connection.execute("SELECT * FROM p2_v3_turns ORDER BY turn_id").fetchall()
        for row in rows:
            try:
                snapshot = self._p2_v3_snapshot(row)
                self._require_current_p2_v3_pin(connection, row)
            except P2V3UnsupportedProfile:
                continue
            turn = connection.execute(
                "SELECT state,state_revision,checkpoint_revision,claim_token,claim_until FROM turns WHERE turn_id=? AND owner_user_id=?",
                (snapshot.turn_id, snapshot.owner_user_id),
            ).fetchone()
            if turn is None:
                raise RuntimeError("P2 v3 assignment has no owner-scoped Turn")
            until = _parse_datetime(turn["claim_until"]) if turn["claim_until"] else None
            if turn["claim_token"] is not None and until is not None and until > instant:
                continue
            self._recover_p2_v3_pending_reservations(
                connection, owner_user_id=snapshot.owner_user_id, turn_id=snapshot.turn_id, now=instant,
            )
            current = connection.execute(
                "SELECT * FROM p2_v3_turns WHERE turn_id=? AND owner_user_id=?",
                (snapshot.turn_id, snapshot.owner_user_id),
            ).fetchone()
            current_snapshot = self._p2_v3_snapshot(current)
            changed = connection.execute(
                """UPDATE p2_v3_turns SET claim_epoch=claim_epoch+1,authority_epoch=authority_epoch+1,
                    lifecycle=?,context_revision=?,turn_state_revision=?,revision=revision+1,updated_at=?
                    WHERE turn_id=? AND owner_user_id=? AND revision=? AND claim_epoch=? AND authority_epoch=?""",
                (
                    self._p2_v3_lifecycle_for_state(TurnState(turn["state"])),
                    int(turn["checkpoint_revision"]), int(turn["state_revision"]), _stamp(instant),
                    snapshot.turn_id, snapshot.owner_user_id, current_snapshot.revision,
                    current_snapshot.claim_epoch, current_snapshot.authority_epoch,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("P2 v3 Store startup invalidation lost its CAS")

    def _claim_p2_v3_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        now: datetime,
    ) -> None:
        row = connection.execute(
            "SELECT * FROM p2_v3_turns WHERE turn_id=? AND owner_user_id=?",
            (str(turn_id), str(owner_user_id)),
        ).fetchone()
        if row is None:
            raise P2V3StoreNotFound("v3 candidate scheduler claim requires its immutable profile pin")
        self._require_current_p2_v3_pin(connection, row)
        snapshot = self._p2_v3_snapshot(row)
        turn = connection.execute(
            "SELECT state_revision,checkpoint_revision FROM turns WHERE turn_id=? AND owner_user_id=?",
            (str(turn_id), str(owner_user_id)),
        ).fetchone()
        if turn is None:
            raise RuntimeError("v3 candidate Turn disappeared during claim")
        self._recover_p2_v3_pending_reservations(
            connection, owner_user_id=str(owner_user_id), turn_id=str(turn_id), now=now,
        )
        current = connection.execute(
            "SELECT * FROM p2_v3_turns WHERE turn_id=? AND owner_user_id=?",
            (str(turn_id), str(owner_user_id)),
        ).fetchone()
        current_snapshot = self._p2_v3_snapshot(current)
        changed = connection.execute(
            """UPDATE p2_v3_turns SET claim_epoch=claim_epoch+1,authority_epoch=authority_epoch+1,
                lifecycle='active',context_revision=?,turn_state_revision=?,revision=revision+1,updated_at=?
                WHERE turn_id=? AND owner_user_id=? AND revision=? AND claim_epoch=? AND authority_epoch=?""",
            (
                int(turn["checkpoint_revision"]), int(turn["state_revision"]), _stamp(now),
                str(turn_id), str(owner_user_id), current_snapshot.revision,
                current_snapshot.claim_epoch, current_snapshot.authority_epoch,
            ),
        ).rowcount
        if changed != 1:
            raise P2V3StoreConflict("v3 scheduler claim invalidation lost its Store CAS")

    @staticmethod
    def _p2_v3_lifecycle_for_state(state: TurnState) -> str:
        if state in (TurnState.QUEUED, TurnState.RECOVERING):
            return "queued"
        if state in (TurnState.RUNNING, TurnState.EXECUTING):
            return "active"
        if state in (TurnState.COMPLETED, TurnState.CANCELLED, TurnState.FAILED):
            return "terminal"
        return "waiting"

    def _insert_p2_v3_charge_event(
        self,
        connection: sqlite3.Connection,
        reservation: sqlite3.Row,
        *,
        event_kind: str,
        now: datetime,
        actual_active_us: Optional[int] = None,
        actual_backend_us: Optional[int] = None,
        actual_response_bytes: Optional[int] = None,
        overrun_active_us: int = 0,
        overrun_backend_us: int = 0,
        overrun_response_bytes: int = 0,
        raw_body_sha256: Optional[str] = None,
        prepared_request_sha256: Optional[str] = None,
        selected_model_key: Optional[str] = None,
        validated_measurement_sha256: Optional[str] = None,
    ) -> str:
        if event_kind not in {"dispatch_started", "settled", "known_no_dispatch", "unknown"}:
            raise ValueError("invalid v3 charge event kind")
        event_id = str(uuid.uuid4())
        connection.execute(
            """INSERT INTO p2_v3_charge_events (
                event_id,reservation_id,event_kind,owner_user_id,turn_id,profile_id,stage,
                generation,claim_epoch,authority_epoch,context_revision,logical_query_id,
                query_attempt_id,admission_id,source_role,active_limit_us,backend_limit_us,
                response_bytes_limit,request_digest,prepared_request_sha256,selected_model_key,
                validated_measurement_sha256,actual_active_us,actual_backend_us,
                actual_response_bytes,overrun_active_us,overrun_backend_us,overrun_response_bytes,
                raw_body_sha256,occurred_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                event_id, reservation["reservation_id"], event_kind,
                reservation["owner_user_id"], reservation["turn_id"], reservation["profile_id"],
                reservation["stage"], reservation["generation"], reservation["claim_epoch"],
                reservation["authority_epoch"], reservation["context_revision"],
                reservation["logical_query_id"], reservation["query_attempt_id"],
                reservation["admission_id"], reservation["source_role"],
                reservation["active_limit_us"], reservation["backend_limit_us"],
                reservation["response_bytes_limit"], reservation["request_digest"],
                prepared_request_sha256, selected_model_key, validated_measurement_sha256,
                actual_active_us, actual_backend_us, actual_response_bytes,
                overrun_active_us, overrun_backend_us, overrun_response_bytes,
                raw_body_sha256, _stamp(now),
            ),
        )
        return event_id

    def get_p2_v3_snapshot(self, owner_user_id: uuid.UUID, turn_id: uuid.UUID) -> P2V3TurnSnapshot:
        self._require_started()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM p2_v3_turns WHERE turn_id = ? AND owner_user_id = ?",
                (str(turn_id), str(owner_user_id)),
            ).fetchone()
            if row is None:
                raise P2V3StoreNotFound("v3 candidate Turn is not available to this owner")
            self._require_current_p2_v3_pin(connection, row)
            return self._p2_v3_snapshot(row)

    def get_p2_v3_resume_query_descriptor(
        self, owner_user_id: uuid.UUID, turn_id: uuid.UUID, *, claim_token: str,
    ) -> P2V3ResumeQueryDescriptor | None:
        """Return the sole valid query for this exact generation/input, if one exists.

        A descriptor with a damaged claim, cohort, owner, or projection must fail
        closed. Returning ``None`` is reserved for the actual no-query case so
        Runtime cannot mistake a corrupt prior query for fresh planning.
        """
        self._require_started()
        with self._connection() as connection:
            _, current, _ = self._p2_v3_current_claim(
                connection, owner_user_id, turn_id, claim_token=claim_token,
                now=datetime.now(timezone.utc),
            )
            rows = connection.execute(
                """SELECT * FROM p2_v3_queries
                   WHERE owner_user_id=? AND turn_id=? AND generation=? AND input_seq=?
                   ORDER BY logical_query_id""",
                (str(owner_user_id), str(turn_id), current.generation, current.input_seq),
            ).fetchall()
            if not rows:
                return None
            if len(rows) != 1:
                raise P2V3StoreConflict("current input has multiple immutable logical queries")
            query = rows[0]
            if (
                query["profile_id"] != P2_V3_CANDIDATE_PROFILE_ID
                or query["input_digest"] != current.input_digest
                or query["generation"] != current.generation
                or query["input_seq"] != current.input_seq
                or query["operation"] not in P2_V3_OPERATIONS
            ):
                raise P2V3StoreConflict("current input query identity or execution profile changed")

            descriptor = connection.execute(
                """SELECT * FROM p2_v3_query_descriptor_bindings
                   WHERE logical_query_id=? AND owner_user_id=? AND turn_id=?""",
                (query["logical_query_id"], str(owner_user_id), str(turn_id)),
            ).fetchone()
            if descriptor is None:
                raise P2V3StoreConflict("current input logical query has no immutable descriptor")
            admission = connection.execute(
                """SELECT * FROM p2_v3_source_admissions
                   WHERE admission_id=? AND owner_user_id=? AND turn_id=?""",
                (descriptor["admission_id"], str(owner_user_id), str(turn_id)),
            ).fetchone()
            pin = connection.execute(
                "SELECT cohort_sha256 FROM p2_v3_turn_execution_pins WHERE turn_id=? AND owner_user_id=?",
                (str(turn_id), str(owner_user_id)),
            ).fetchone()
            if admission is None or pin is None:
                raise P2V3StoreConflict("current input query admission or execution cohort is unavailable")
            exact_fields_match = (
                descriptor["logical_query_id"] == query["logical_query_id"]
                and descriptor["owner_user_id"] == str(owner_user_id)
                and descriptor["turn_id"] == str(turn_id)
                and descriptor["generation"] == current.generation
                and descriptor["input_seq"] == current.input_seq
                and descriptor["input_digest"] == current.input_digest
                and descriptor["authority_epoch"] == query["authority_epoch"]
                and descriptor["criteria_json"] == query["criteria_json"]
                and descriptor["criteria_digest"] == query["criteria_digest"]
                and descriptor["scope_json"] == query["scope_json"]
                and descriptor["scope_digest"] == query["scope_digest"]
                and descriptor["context_revision"] == query["created_context_revision"]
                and descriptor["admission_id"] == query["admission_id"]
                and descriptor["cohort_sha256"] == pin["cohort_sha256"]
                and admission["generation"] == descriptor["generation"]
                and admission["input_seq"] == descriptor["input_seq"]
                and admission["input_digest"] == descriptor["input_digest"]
                and admission["authority_epoch"] == descriptor["authority_epoch"]
                and admission["context_revision"] == descriptor["context_revision"]
            )
            if not exact_fields_match:
                raise P2V3StoreConflict("current input query descriptor does not match its immutable admission")

            try:
                stored_criteria = json.loads(descriptor["criteria_json"])
                stored_scope = json.loads(descriptor["scope_json"])
                stored_refs = json.loads(descriptor["selected_refs_json"])
                if (
                    type(stored_criteria) is not dict
                    or (stored_scope is not None and type(stored_scope) is not dict)
                    or type(stored_refs) is not list
                    or len(stored_refs) > 32
                    or any(
                        type(item) is not str
                        or re.fullmatch(r"ref_[A-Za-z0-9_-]{22,64}", item) is None
                        for item in stored_refs
                    )
                    or stored_refs != sorted(set(stored_refs))
                ):
                    raise ValueError("invalid descriptor shape")
                request_json = json.dumps({
                    "kind": "read",
                    "message_type": "query_request",
                    "profile_id": P2_V3_CANDIDATE_PROFILE_ID,
                    "versions": P2_V3_VERSIONS,
                    "operation": query["operation"],
                    "criteria": stored_criteria,
                    "scope": stored_scope,
                }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                request = P2ReadQueryRequest.model_validate_json(request_json, strict=True)
                criteria_json, criteria_digest, scope_json, scope_digest = _wire_query_descriptor(
                    request.operation.value, request.criteria, request.scope,
                )
                recomputed_criteria_digest = _normalized_criteria_digest(
                    criteria_json, stored_refs,
                )
                expected_json, expected_sha = _private_query_descriptor_json(
                    owner_user_id=str(owner_user_id), turn_id=str(turn_id),
                    logical_query_id=query["logical_query_id"], operation=query["operation"],
                    criteria_json=descriptor["criteria_json"],
                    criteria_digest=descriptor["criteria_digest"],
                    scope_json=descriptor["scope_json"], scope_digest=descriptor["scope_digest"],
                    selected_refs_json=descriptor["selected_refs_json"],
                    selected_refs_digest=descriptor["selected_refs_digest"],
                    normalized_criteria_digest=descriptor["normalized_criteria_digest"],
                    admission_id=descriptor["admission_id"],
                    generation=int(descriptor["generation"]),
                    input_seq=int(descriptor["input_seq"]),
                    input_digest=descriptor["input_digest"],
                    authority_epoch=int(descriptor["authority_epoch"]),
                    context_revision=int(descriptor["context_revision"]),
                    cohort_sha256=descriptor["cohort_sha256"],
                )
            except Exception:
                raise P2V3StoreConflict("current input query descriptor failed strict integrity validation") from None

            if (
                request.operation.value != query["operation"]
                or criteria_json != descriptor["criteria_json"]
                or criteria_digest != descriptor["criteria_digest"]
                or scope_json != descriptor["scope_json"]
                or scope_digest != descriptor["scope_digest"]
                or recomputed_criteria_digest != descriptor["normalized_criteria_digest"]
                or _digest(descriptor["selected_refs_json"].encode("utf-8")) != descriptor["selected_refs_digest"]
                or descriptor["normalized_descriptor_json"] != expected_json
                or descriptor["normalized_descriptor_sha256"] != expected_sha
            ):
                raise P2V3StoreConflict("current input query descriptor failed its exact projection check")
            return P2V3ResumeQueryDescriptor(
                logical_query_id=str(query["logical_query_id"]),
                operation=str(query["operation"]),
                criteria_json=str(descriptor["criteria_json"]),
                scope_json=str(descriptor["scope_json"]),
                private_selection_refs=tuple(stored_refs),
                generation=current.generation,
                input_seq=current.input_seq,
                input_digest=current.input_digest,
                cohort_sha256=str(descriptor["cohort_sha256"]),
            )

    def create_p2_v3_source_admission(
        self,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        *,
        claim_token: str,
        requested_scope: Any,
        public_scope: Any = None,
        ui_hint: Any = None,
        now: Optional[datetime] = None,
    ) -> str:
        """Persist a private scope-bootstrap descriptor; it is not a read result."""
        self._require_started()
        instant = _now(now)
        private_scope = _private_scope_descriptor(requested_scope)
        scope_json, scope_digest = _canonical_json(private_scope, max_bytes=8192)
        safe_hint = _safe_ui_hint(ui_hint)
        _, ui_hint_digest = _canonical_json(safe_hint, max_bytes=2048) if safe_hint is not None else (None, None)
        if public_scope is None:
            _, public_scope_digest = _canonical_json(None, max_bytes=2048)
        else:
            try:
                normalized_scope = P2Scope.model_validate(public_scope, strict=True)
            except Exception:
                raise ValueError("source admission public scope must be a reviewed strict v3 scope") from None
            _, public_scope_digest = _canonical_json(
                normalized_scope.model_dump(mode="json", exclude_none=False), max_bytes=2048,
            )
        admission_id = str(uuid.uuid4())
        with self._transaction() as connection:
            _, snapshot, _ = self._p2_v3_current_claim(
                connection, owner_user_id, turn_id, claim_token=claim_token, now=instant,
            )
            connection.execute(
                """INSERT INTO p2_v3_source_admissions (
                    admission_id,owner_user_id,turn_id,generation,input_seq,input_digest,
                    claim_epoch,authority_epoch,context_revision,ui_hint_digest,
                    requested_scope_json,requested_scope_digest,public_scope_digest,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    admission_id, str(owner_user_id), str(turn_id), snapshot.generation,
                    snapshot.input_seq, snapshot.input_digest, snapshot.claim_epoch,
                    snapshot.authority_epoch, snapshot.context_revision, ui_hint_digest,
                    scope_json, scope_digest, public_scope_digest, _stamp(instant),
                ),
            )
        return admission_id

    def create_p2_v3_request_admission(
        self,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        *,
        claim_token: str,
        principal_user_id: uuid.UUID,
        activity_id_hint: uuid.UUID | None,
        ledger_unit_id_hint: uuid.UUID | None = None,
        ui_hint: Any = None,
        now: Optional[datetime] = None,
    ) -> tuple[Any, P2Scope | None]:
        """Atomically create an admission and its request-local prospective refs.

        The returned refs are identifiers only. They do not authorize source
        access and must not be exposed to a model until metadata acceptance.
        """
        self._require_started()
        if type(owner_user_id) is not uuid.UUID or type(turn_id) is not uuid.UUID:
            raise ValueError("source admission requires UUID owner and Turn")
        if type(principal_user_id) is not uuid.UUID:
            raise ValueError("source admission requires the verified principal UUID")
        if principal_user_id != owner_user_id:
            raise P2V3StoreConflict("verified principal must own the candidate Turn")
        if activity_id_hint is not None and type(activity_id_hint) is not uuid.UUID:
            raise ValueError("Activity hint must be a UUID or null")
        if ledger_unit_id_hint is not None and type(ledger_unit_id_hint) is not uuid.UUID:
            raise ValueError("ledger-unit hint must be a UUID or null")
        if activity_id_hint is None and ledger_unit_id_hint is not None:
            raise ValueError("ledger-unit hint requires an Activity hint")

        from . import p2_source_codec_v3 as codec3

        instant = _now(now)
        admission_id = str(uuid.uuid4())
        private_scope = (
            {"scope_kind": "none"}
            if activity_id_hint is None
            else {
                "scope_kind": "ledger_unit" if ledger_unit_id_hint is not None else "activity",
                "activity_id": str(activity_id_hint),
                **({"ledger_unit_id": str(ledger_unit_id_hint)} if ledger_unit_id_hint is not None else {}),
            }
        )
        # Store the same closed shape that acceptance revalidates. In
        # particular, an Activity scope carries ledger_unit_id=None so its
        # persisted digest and the request-local registry digest agree.
        private_scope = _private_scope_descriptor(private_scope)
        scope_json, scope_digest = _canonical_json(private_scope, max_bytes=8192)
        if ui_hint is None and activity_id_hint is not None:
            ui_hint = {"activity_id": str(activity_id_hint)}
            if ledger_unit_id_hint is not None:
                ui_hint["ledger_unit_id"] = str(ledger_unit_id_hint)
        safe_hint = _safe_ui_hint(ui_hint)
        _, ui_hint_digest = _canonical_json(safe_hint, max_bytes=2048) if safe_hint is not None else (None, None)

        with self._transaction() as connection:
            _, snapshot, _ = self._p2_v3_current_claim(
                connection, owner_user_id, turn_id, claim_token=claim_token, now=instant,
            )
            turn_row = connection.execute(
                "SELECT * FROM p2_v3_turns WHERE owner_user_id=? AND turn_id=?",
                (str(owner_user_id), str(turn_id)),
            ).fetchone()
            if turn_row is None:
                raise P2V3StoreNotFound("source admission Turn is unavailable")
            self._require_current_p2_v3_pin(connection, turn_row)
            pinned, pin = self._verify_p2_v3_execution_pin_rows(connection, turn_row)
            if not pinned or pin is None:
                raise P2V3UnsupportedProfile("source admission requires the current immutable cohort pin")
            identity = codec3.V3ExecutionIdentity(
                owner_user_id=owner_user_id, turn_id=turn_id,
                generation=snapshot.generation, input_seq=snapshot.input_seq,
                input_digest=snapshot.input_digest, claim_epoch=snapshot.claim_epoch,
                authority_epoch=snapshot.authority_epoch,
                context_revision=snapshot.context_revision,
            )
            registry = P2V3RequestReferenceRegistry(
                self, identity=identity, admission_id=admission_id,
                principal_user_id=principal_user_id, claim_token=claim_token,
                cohort_sha256=pin["cohort_sha256"],
                seal=_P2_V3_REFERENCE_REGISTRY_SEAL,
            )
            public_scope: P2Scope | None = None
            public_scope_digest = _canonical_json(None, max_bytes=2048)[1]
            if activity_id_hint is not None:
                activity_ref = registry.bind_entity(
                    "activity", activity_id_hint, activity_id=activity_id_hint,
                    connection=connection,
                )
                if ledger_unit_id_hint is None:
                    public_scope = P2Scope(
                        scope_kind="activity", scope_ref=activity_ref,
                        activity_ref=activity_ref, ledger_unit_ref=None,
                    )
                else:
                    ledger_ref = registry.bind_entity(
                        "ledger_unit", ledger_unit_id_hint, activity_id=activity_id_hint,
                        ledger_unit_id=ledger_unit_id_hint,
                        connection=connection,
                    )
                    public_scope = P2Scope(
                        scope_kind="ledger_unit", scope_ref=ledger_ref,
                        activity_ref=activity_ref, ledger_unit_ref=ledger_ref,
                    )
                _, public_scope_digest = _canonical_json(
                    public_scope.model_dump(mode="json", exclude_none=False), max_bytes=2048,
                )
            registry._set_requested_scope(private_scope, scope_digest, public_scope_digest)
            connection.execute(
                """INSERT INTO p2_v3_source_admissions (
                    admission_id,owner_user_id,turn_id,generation,input_seq,input_digest,
                    claim_epoch,authority_epoch,context_revision,ui_hint_digest,
                    requested_scope_json,requested_scope_digest,public_scope_digest,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    admission_id, str(owner_user_id), str(turn_id), snapshot.generation,
                    snapshot.input_seq, snapshot.input_digest, snapshot.claim_epoch,
                    snapshot.authority_epoch, snapshot.context_revision, ui_hint_digest,
                    scope_json, scope_digest, public_scope_digest, _stamp(instant),
                ),
            )
        binding = codec3.AdmissionOnlyBinding(
            identity=identity, admission_id=admission_id, claim_token=claim_token,
            reference_registry=registry,
        )
        return binding, public_scope

    def create_p2_v3_logical_query(
        self,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        *,
        claim_token: str,
        admission_id: str,
        operation: str,
        criteria: Any,
        scope: Any,
        expected_revision: int,
        private_selection_refs: Sequence[str] = (),
        logical_query_id: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> str:
        """Create one immutable guarded logical read after admission/shape checks."""
        self._require_started()
        if operation not in P2_V3_OPERATIONS:
            raise ValueError("operation is not in the v3 read allowlist")
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("expected revision must be a positive integer")
        criteria_json, criteria_digest, scope_json, scope_digest = _wire_query_descriptor(operation, criteria, scope)
        if not isinstance(private_selection_refs, (list, tuple)) or len(private_selection_refs) > 32:
            raise ValueError("private selection refs must be a bounded list of opaque references")
        if any(
            type(item) is not str or re.fullmatch(r"ref_[A-Za-z0-9_-]{22,64}", item) is None
            for item in private_selection_refs
        ):
            raise ValueError("private selection entries must be opaque reference tokens")
        if len(set(private_selection_refs)) != len(private_selection_refs):
            raise ValueError("private selection refs must be unique")
        selected_refs_json, selected_refs_digest = _canonical_json(
            sorted(private_selection_refs), max_bytes=4096,
        )
        normalized_criteria_digest = _normalized_criteria_digest(criteria_json, private_selection_refs)
        query_id = str(uuid.uuid4()) if logical_query_id is None else logical_query_id
        instant = _now(now)
        with self._transaction() as connection:
            _, snapshot, _ = self._p2_v3_current_claim(
                connection, owner_user_id, turn_id, claim_token=claim_token, now=instant,
            )
            if snapshot.revision != expected_revision:
                raise P2V3StoreConflict("v3 Store revision changed before logical read creation")
            admission = connection.execute(
                "SELECT * FROM p2_v3_source_admissions WHERE admission_id = ? AND owner_user_id = ? AND turn_id = ?",
                (admission_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            if admission is None:
                raise P2V3StoreNotFound("source admission is unavailable to this owner and Turn")
            if any(admission[key] != value for key, value in (
                ("generation", snapshot.generation), ("input_seq", snapshot.input_seq),
                ("input_digest", snapshot.input_digest), ("claim_epoch", snapshot.claim_epoch),
                ("authority_epoch", snapshot.authority_epoch), ("context_revision", snapshot.context_revision),
            )):
                raise P2V3StoreConflict("source admission is stale for the current Turn claim")
            if scope_digest != admission["public_scope_digest"]:
                raise P2V3StoreConflict("logical query scope does not match the source-authorized admission")
            pin = connection.execute(
                "SELECT cohort_sha256 FROM p2_v3_turn_execution_pins WHERE turn_id=? AND owner_user_id=?",
                (str(turn_id), str(owner_user_id)),
            ).fetchone()
            if pin is None:
                raise P2V3UnsupportedProfile("logical query requires the immutable current execution pin")
            cohort_sha256 = pin["cohort_sha256"]
            if logical_query_id is not None:
                existing = connection.execute(
                    "SELECT * FROM p2_v3_queries WHERE logical_query_id=? AND owner_user_id=? AND turn_id=?",
                    (logical_query_id, str(owner_user_id), str(turn_id)),
                ).fetchone()
                if existing is None:
                    raise P2V3StoreNotFound("logical query descriptor is unavailable to this owner and Turn")
                if (
                    existing["profile_id"] != P2_V3_CANDIDATE_PROFILE_ID
                    or existing["operation"] != operation
                    or existing["criteria_digest"] != criteria_digest
                    or existing["scope_digest"] != scope_digest
                ):
                    raise P2V3StoreConflict("resumed logical query cannot change operation, criteria, or scope")
                descriptor = connection.execute(
                    "SELECT * FROM p2_v3_query_descriptor_bindings WHERE logical_query_id=? AND owner_user_id=? AND turn_id=?",
                    (logical_query_id, str(owner_user_id), str(turn_id)),
                ).fetchone()
                if descriptor is None or (
                    descriptor["criteria_json"] != criteria_json
                    or descriptor["criteria_digest"] != criteria_digest
                    or descriptor["scope_json"] != scope_json
                    or descriptor["scope_digest"] != scope_digest
                    or descriptor["selected_refs_json"] != selected_refs_json
                    or descriptor["selected_refs_digest"] != selected_refs_digest
                    or descriptor["normalized_criteria_digest"] != normalized_criteria_digest
                    or descriptor["context_revision"] != existing["created_context_revision"]
                    or descriptor["cohort_sha256"] != cohort_sha256
                ):
                    raise P2V3StoreConflict("resumed logical query descriptor is missing, stale or changed")
                try:
                    expected_json, expected_sha = _private_query_descriptor_json(
                        owner_user_id=str(owner_user_id), turn_id=str(turn_id), logical_query_id=query_id,
                        operation=existing["operation"], criteria_json=descriptor["criteria_json"],
                        criteria_digest=descriptor["criteria_digest"], scope_json=descriptor["scope_json"],
                        scope_digest=descriptor["scope_digest"], selected_refs_json=descriptor["selected_refs_json"],
                        selected_refs_digest=descriptor["selected_refs_digest"],
                        normalized_criteria_digest=descriptor["normalized_criteria_digest"],
                        admission_id=descriptor["admission_id"], generation=int(descriptor["generation"]),
                        input_seq=int(descriptor["input_seq"]), input_digest=descriptor["input_digest"],
                        authority_epoch=int(descriptor["authority_epoch"]),
                        context_revision=int(descriptor["context_revision"]), cohort_sha256=descriptor["cohort_sha256"],
                    )
                    stored_criteria = json.loads(descriptor["criteria_json"])
                    stored_refs = json.loads(descriptor["selected_refs_json"])
                    recomputed_criteria_digest = _normalized_criteria_digest(
                        descriptor["criteria_json"], stored_refs,
                    )
                except (TypeError, ValueError, json.JSONDecodeError):
                    raise P2V3StoreConflict("stored logical query audit descriptor is invalid") from None
                if (
                    existing["generation"] != descriptor["generation"]
                    or existing["input_seq"] != descriptor["input_seq"]
                    or existing["input_digest"] != descriptor["input_digest"]
                    or existing["authority_epoch"] != descriptor["authority_epoch"]
                    or existing["criteria_json"] != descriptor["criteria_json"]
                    or existing["criteria_digest"] != descriptor["criteria_digest"]
                    or existing["scope_json"] != descriptor["scope_json"]
                    or existing["scope_digest"] != descriptor["scope_digest"]
                    or existing["admission_id"] != descriptor["admission_id"]
                    or stored_criteria is None
                    or type(stored_refs) is not list
                    or recomputed_criteria_digest != descriptor["normalized_criteria_digest"]
                    or descriptor["normalized_descriptor_json"] != expected_json
                    or descriptor["normalized_descriptor_sha256"] != expected_sha
                ):
                    raise P2V3StoreConflict("stored logical query audit binding failed its exact projection check")
                return query_id
            if snapshot.logical_read_calls >= P2_V3_MAX_LOGICAL_READS:
                raise P2V3StoreConflict("v3 logical read budget is exhausted")
            normalized_descriptor_json, normalized_descriptor_sha256 = _private_query_descriptor_json(
                owner_user_id=str(owner_user_id), turn_id=str(turn_id), logical_query_id=query_id,
                operation=operation, criteria_json=criteria_json, criteria_digest=criteria_digest,
                scope_json=scope_json, scope_digest=scope_digest, selected_refs_json=selected_refs_json,
                selected_refs_digest=selected_refs_digest, normalized_criteria_digest=normalized_criteria_digest,
                admission_id=admission_id, generation=snapshot.generation, input_seq=snapshot.input_seq,
                input_digest=snapshot.input_digest, authority_epoch=snapshot.authority_epoch,
                context_revision=snapshot.context_revision, cohort_sha256=cohort_sha256,
            )
            connection.execute(
                """INSERT INTO p2_v3_queries (
                    logical_query_id,owner_user_id,turn_id,profile_id,operation,generation,
                    input_seq,input_digest,authority_epoch,criteria_json,criteria_digest,
                    scope_json,scope_digest,created_context_revision,admission_id,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    query_id, str(owner_user_id), str(turn_id), P2_V3_CANDIDATE_PROFILE_ID,
                    operation, snapshot.generation, snapshot.input_seq, snapshot.input_digest,
                    snapshot.authority_epoch, criteria_json, criteria_digest, scope_json,
                    scope_digest, snapshot.context_revision, admission_id, _stamp(instant),
                ),
            )
            connection.execute(
                """INSERT INTO p2_v3_query_descriptor_bindings (
                    logical_query_id,owner_user_id,turn_id,admission_id,generation,input_seq,
                    input_digest,authority_epoch,criteria_json,criteria_digest,scope_json,scope_digest,
                    selected_refs_json,selected_refs_digest,normalized_descriptor_json,
                    normalized_criteria_digest,context_revision,cohort_sha256,
                    normalized_descriptor_sha256,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    query_id, str(owner_user_id), str(turn_id), admission_id, snapshot.generation,
                    snapshot.input_seq, snapshot.input_digest, snapshot.authority_epoch,
                    criteria_json, criteria_digest, scope_json, scope_digest,
                    selected_refs_json, selected_refs_digest, normalized_descriptor_json,
                    normalized_criteria_digest, snapshot.context_revision, cohort_sha256,
                    normalized_descriptor_sha256, _stamp(instant),
                ),
            )
            changed = connection.execute(
                "UPDATE p2_v3_turns SET logical_read_calls = logical_read_calls + 1, revision = revision + 1, updated_at = ? "
                "WHERE turn_id = ? AND owner_user_id = ? AND revision = ? AND logical_read_calls < ?",
                (_stamp(instant), str(turn_id), str(owner_user_id), snapshot.revision, P2_V3_MAX_LOGICAL_READS),
            ).rowcount
            if changed != 1:
                raise P2V3StoreConflict("v3 logical read reservation lost its Store CAS")
        return query_id

    @staticmethod
    def _p2_v3_continuation_proof_from_receipt(receipt: Any) -> Any:
        import hashlib
        from . import p2_event_contracts_v3 as pe3
        from . import p2_source_codec_v3 as codec3

        try:
            if hashlib.sha256(receipt["historical_payload_json"].encode("utf-8")).hexdigest() != receipt["historical_payload_sha256"]:
                raise ValueError("receipt payload hash does not match")
            historical = pe3.P2V3HistoricalReadPayload.model_validate_json(
                receipt["historical_payload_json"], strict=True,
            )
            evidence = historical.query_evidence
            if (
                int(receipt["page_index"]) != 0
                or historical.page.page_index != 0
                or not historical.page.has_more
                or not evidence.source_query_complete
                or evidence.model_projection_complete
                or evidence.projection_digest != receipt["projection_sha256"]
                or str(evidence.query_evidence_ref) != receipt["query_evidence_ref"]
                or evidence.normalized_criteria_digest != receipt["normalized_criteria_digest"]
                or evidence.source_total != receipt["source_total"]
                or evidence.matched_count <= codec3.MAX_FACTS_PER_PAGE
                or evidence.matched_count > codec3.MAX_FACTS_PER_PAGE * 2
                or receipt["query_attempt_id"] is None
                or evidence.query_digest == ""
            ):
                raise ValueError("receipt is not an accepted, complete page-zero continuation source")
            versions_digest = codec3.stable_digest(tuple(
                (str(item.activity_ref), item.financial_version)
                for item in evidence.financial_versions
            ))
            return codec3.V3ContinuationProof(
                logical_query_id=receipt["logical_query_id"],
                query_attempt_id=receipt["query_attempt_id"],
                page_index=0,
                query_evidence_ref=receipt["query_evidence_ref"],
                query_digest=evidence.query_digest,
                body_digest=evidence.body_digest,
                projection_digest=evidence.projection_digest,
                normalized_criteria_digest=receipt["normalized_criteria_digest"],
                source_total=receipt["source_total"],
                financial_versions_digest=versions_digest,
                source_query_complete=True,
            )
        except Exception as exc:
            raise P2V3StoreConflict("accepted page-zero continuation receipt failed strict readback") from exc

    def _issue_p2_v3_continuation_token(
        self,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        *,
        claim_token: str,
        logical_query_id: str,
        raw_next_page_ref: str,
        admission_id: str,
        attempt_seq: int,
        issuer_page_index: int,
        source_proof_sha256: str,
        projection_sha256: str,
        expires_at: datetime,
        now: Optional[datetime] = None,
    ) -> None:
        """Private seam for a future source-proof owner; cost-only captures cannot call it."""
        if type(raw_next_page_ref) is not str or re.fullmatch(r"ref_[A-Za-z0-9_-]{22,64}", raw_next_page_ref) is None:
            raise ValueError("continuation reference is invalid")
        _strict_positive_int(attempt_seq, "attempt_seq")
        _strict_nonnegative_int(issuer_page_index, "issuer_page_index")
        if issuer_page_index != 0:
            raise P2V3StoreConflict("only the accepted page-zero receipt can issue one continuation")
        source_proof_sha256 = _check_sha256(source_proof_sha256, "source_proof_sha256", required=True)
        projection_sha256 = _check_sha256(projection_sha256, "projection_sha256", required=True)
        instant = _now(now)
        expiration = _now(expires_at)
        nonce_digest = _digest(raw_next_page_ref.encode("utf-8"))
        self._require_started()
        with self._transaction() as connection:
            _, snapshot, aggregate = self._p2_v3_current_claim(
                connection, owner_user_id, turn_id, claim_token=claim_token, now=instant,
            )
            if expiration <= instant:
                raise ValueError("continuation expiry must be in the future")
            claim_until = aggregate.claim_until
            if claim_until is None or expiration > claim_until:
                raise ValueError("continuation cannot outlive its current Store claim")
            query = connection.execute(
                "SELECT * FROM p2_v3_queries WHERE logical_query_id=? AND owner_user_id=? AND turn_id=?",
                (logical_query_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            admission = connection.execute(
                "SELECT * FROM p2_v3_source_admissions WHERE admission_id=? AND owner_user_id=? AND turn_id=?",
                (admission_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            descriptor = connection.execute(
                "SELECT * FROM p2_v3_query_descriptor_bindings WHERE logical_query_id=? AND owner_user_id=? AND turn_id=?",
                (logical_query_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            attempt = connection.execute(
                "SELECT * FROM p2_v3_query_attempts WHERE logical_query_id=? AND attempt_seq=? AND page_index=? AND owner_user_id=? AND turn_id=?",
                (logical_query_id, attempt_seq, issuer_page_index, str(owner_user_id), str(turn_id)),
            ).fetchone()
            receipt = connection.execute(
                "SELECT * FROM p2_v3_query_result_receipts WHERE logical_query_id=? AND query_attempt_id=? AND page_index=? AND owner_user_id=? AND turn_id=?",
                (logical_query_id, attempt["attempt_id"] if attempt is not None else "", issuer_page_index,
                 str(owner_user_id), str(turn_id)),
            ).fetchone()
            if query is None or admission is None or descriptor is None or attempt is None or receipt is None:
                raise P2V3StoreNotFound("continuation issuer is unavailable to this owner and Turn")
            proof = self._p2_v3_continuation_proof_from_receipt(receipt)
            expected_source_proof_sha256 = P2V3RequestReferenceRegistry._continuation_proof_sha256(proof)
            if (
                admission["generation"] != snapshot.generation
                or admission["input_seq"] != snapshot.input_seq
                or admission["input_digest"] != snapshot.input_digest
                or admission["claim_epoch"] != snapshot.claim_epoch
                or admission["authority_epoch"] != snapshot.authority_epoch
                or admission["context_revision"] != snapshot.context_revision
                or admission["public_scope_digest"] != query["scope_digest"]
                or descriptor["admission_id"] != admission_id
                or descriptor["cohort_sha256"] != receipt["cohort_sha256"]
                or descriptor["context_revision"] != snapshot.context_revision
                or attempt["generation"] != snapshot.generation
                or attempt["authority_epoch"] != snapshot.authority_epoch
                or attempt["admission_id"] != admission_id
                or attempt["criteria_digest"] != query["criteria_digest"]
                or attempt["scope_digest"] != query["scope_digest"]
                or attempt["attempt_state"] != "started"
                or proof.logical_query_id != logical_query_id
                or proof.query_attempt_id != attempt["attempt_id"]
                or receipt["criteria_digest"] != query["criteria_digest"]
                or receipt["scope_digest"] != query["scope_digest"]
                or receipt["has_more"] != 1
                or receipt["source_query_complete"] != 1
                or receipt["model_projection_complete"] != 0
                or expected_source_proof_sha256 != source_proof_sha256
                or receipt["projection_sha256"] != projection_sha256
                or not proof.source_query_complete
            ):
                raise P2V3StoreConflict("continuation issuer no longer matches current authorization and query")
            latest = connection.execute(
                "SELECT attempt_seq,MAX(page_index) AS page_index FROM p2_v3_query_attempts WHERE logical_query_id=? GROUP BY attempt_seq ORDER BY attempt_seq DESC LIMIT 1",
                (logical_query_id,),
            ).fetchone()
            if latest is None or int(latest["attempt_seq"]) != attempt_seq or int(latest["page_index"]) != issuer_page_index:
                raise P2V3StoreConflict("continuation can only be issued from the latest page attempt")
            connection.execute(
                """INSERT INTO p2_v3_continuation_nonce_issues (
                    nonce_sha256,logical_query_id,owner_user_id,turn_id,generation,authority_epoch,
                    attempt_seq,page_index,criteria_digest,scope_digest,source_proof_sha256,
                    projection_sha256,issued_at,expires_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    nonce_digest, logical_query_id, str(owner_user_id), str(turn_id), snapshot.generation,
                    snapshot.authority_epoch, attempt_seq, issuer_page_index, query["criteria_digest"],
                    query["scope_digest"], source_proof_sha256, projection_sha256,
                    _stamp(instant), _stamp(expiration),
                ),
            )

    def begin_p2_v3_query_attempt(
        self,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        *,
        claim_token: str,
        logical_query_id: str,
        admission_id: str,
        page_index: int = 0,
        attempt_seq: Optional[int] = None,
        now: Optional[datetime] = None,
    ) -> tuple[str, int]:
        """Record a private page attempt; no source completeness is implied."""
        self._require_started()
        _strict_nonnegative_int(page_index, "page_index")
        if page_index != 0:
            raise P2V3StoreConflict("continuation pages must atomically consume their opaque token")
        if attempt_seq is not None:
            _strict_positive_int(attempt_seq, "attempt_seq")
        instant = _now(now)
        attempt_id = str(uuid.uuid4())
        with self._transaction() as connection:
            _, snapshot, _ = self._p2_v3_current_claim(
                connection, owner_user_id, turn_id, claim_token=claim_token, now=instant,
            )
            query = connection.execute(
                "SELECT * FROM p2_v3_queries WHERE logical_query_id=? AND owner_user_id=? AND turn_id=?",
                (logical_query_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            admission = connection.execute(
                "SELECT * FROM p2_v3_source_admissions WHERE admission_id=? AND owner_user_id=? AND turn_id=?",
                (admission_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            if query is None or admission is None:
                raise P2V3StoreNotFound("query or source admission is unavailable to this owner and Turn")
            if (
                admission["generation"] != snapshot.generation or admission["input_seq"] != snapshot.input_seq
                or admission["input_digest"] != snapshot.input_digest
                or admission["claim_epoch"] != snapshot.claim_epoch
                or admission["authority_epoch"] != snapshot.authority_epoch
                or admission["context_revision"] != snapshot.context_revision
                or query["scope_digest"] != admission["public_scope_digest"]
            ):
                raise P2V3StoreConflict("query or admission is stale or outside the requested scope")
            previous = connection.execute(
                "SELECT COALESCE(MAX(attempt_seq),0) AS value FROM p2_v3_query_attempts WHERE logical_query_id=?",
                (logical_query_id,),
            ).fetchone()
            max_attempt = int(previous["value"])
            if page_index == 0:
                selected_seq = max_attempt + 1 if attempt_seq is None else attempt_seq
                if selected_seq != max_attempt + 1:
                    raise P2V3StoreConflict("page-zero reread must use the next private attempt sequence")
            else:  # page_index is constrained to zero above.
                raise P2V3StoreConflict("continuation pages must use consume_p2_v3_continuation")
            connection.execute(
                """INSERT INTO p2_v3_query_attempts (
                    attempt_id,logical_query_id,owner_user_id,turn_id,generation,authority_epoch,
                    attempt_seq,page_index,criteria_digest,scope_digest,admission_id,attempt_state,observed_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,'started',?)""",
                (
                    attempt_id, logical_query_id, str(owner_user_id), str(turn_id), snapshot.generation,
                    snapshot.authority_epoch, selected_seq, page_index, query["criteria_digest"],
                    query["scope_digest"], admission_id, _stamp(instant),
                ),
            )
        return attempt_id, selected_seq

    def bind_p2_v3_query_descriptor(
        self,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        *,
        claim_token: str,
        admission: Any,
        request: Any,
        logical_query_id: str,
        private_selection_refs: tuple[str, ...] = (),
        now: Optional[datetime] = None,
    ) -> str:
        """Bind a strict public request to its persisted query in one request-local registry.

        This does not create authority or a source receipt.  It only allows the
        source adapter to read the exact server-persisted descriptor instead
        of accepting a Runtime-created locator/cache entry.
        """
        from . import p2_read_contracts_v3 as pc3
        from . import p2_source_codec_v3 as codec3

        self._require_started()
        if type(owner_user_id) is not uuid.UUID or type(turn_id) is not uuid.UUID:
            raise P2V3StoreConflict("query descriptor requires an owner and Turn UUID")
        if not isinstance(admission, codec3.AdmissionOnlyBinding):
            raise P2V3StoreConflict("query descriptor requires a Store-issued admission")
        if not isinstance(request, pc3.P2ReadQueryRequest):
            raise P2V3StoreConflict("query descriptor requires a strict P2 read request")
        if (
            admission.identity.owner_user_id != owner_user_id
            or admission.identity.turn_id != turn_id
            or admission.claim_token != claim_token
            or type(logical_query_id) is not str or not logical_query_id
            or type(private_selection_refs) is not tuple
            or len(private_selection_refs) > codec3.MAX_UI_EXPENSE_SELECTION
            or any(type(item) is not str for item in private_selection_refs)
            or len(set(private_selection_refs)) != len(private_selection_refs)
        ):
            raise P2V3StoreConflict("query descriptor admission or selection binding is invalid")
        registry = admission.reference_registry
        if not isinstance(registry, P2V3RequestReferenceRegistry):
            raise P2V3StoreConflict("query descriptor requires the Store-issued request registry")
        registry._assert_store_issued(
            self, identity=admission.identity, admission_id=admission.admission_id,
            claim_token=claim_token,
        )
        operation = request.operation.value
        criteria_json, criteria_digest, scope_json, scope_digest = _wire_query_descriptor(
            operation, request.criteria, request.scope,
        )
        if request.profile_id != P2_V3_CANDIDATE_PROFILE_ID or request.versions.model_dump(mode="json") != P2_V3_VERSIONS:
            raise P2V3StoreConflict("query request has an unsupported candidate profile or version tuple")
        if private_selection_refs and operation != "read.expenses":
            raise P2V3StoreConflict("opaque UI expense selections are supported only for expense reads")
        instant = _now(now)
        with self._connection() as connection:
            _, current, current_aggregate = self._p2_v3_current_claim(
                connection, owner_user_id, turn_id, claim_token=claim_token, now=instant,
            )
            admission_row = connection.execute(
                "SELECT * FROM p2_v3_source_admissions WHERE admission_id=? AND owner_user_id=? AND turn_id=?",
                (admission.admission_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            query_row = connection.execute(
                "SELECT * FROM p2_v3_queries WHERE logical_query_id=? AND owner_user_id=? AND turn_id=?",
                (logical_query_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            descriptor_row = connection.execute(
                "SELECT * FROM p2_v3_query_descriptor_bindings WHERE logical_query_id=? AND owner_user_id=? AND turn_id=?",
                (logical_query_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            if admission_row is None or query_row is None or descriptor_row is None:
                raise P2V3StoreNotFound("persisted source admission or query descriptor is unavailable")
            if (
                admission_row["generation"] != current.generation
                or admission_row["input_seq"] != current.input_seq
                or admission_row["input_digest"] != current.input_digest
                or admission_row["claim_epoch"] != current.claim_epoch
                or admission_row["authority_epoch"] != current.authority_epoch
                or admission_row["context_revision"] != current.context_revision
                or admission_row["public_scope_digest"] != scope_digest
                or query_row["operation"] != operation
                or query_row["criteria_json"] != criteria_json
                or query_row["criteria_digest"] != criteria_digest
                or query_row["scope_json"] != scope_json
                or query_row["scope_digest"] != scope_digest
                or query_row["profile_id"] != P2_V3_CANDIDATE_PROFILE_ID
                or query_row["generation"] != current.generation
                or query_row["input_seq"] != current.input_seq
                or query_row["input_digest"] != current.input_digest
                or query_row["authority_epoch"] != descriptor_row["authority_epoch"]
                or descriptor_row["criteria_json"] != criteria_json
                or descriptor_row["criteria_digest"] != criteria_digest
                or descriptor_row["scope_json"] != scope_json
                or descriptor_row["scope_digest"] != scope_digest
                or descriptor_row["normalized_criteria_digest"] != _normalized_criteria_digest(
                    criteria_json, private_selection_refs,
                )
                or descriptor_row["selected_refs_json"] != _canonical_json(
                    sorted(private_selection_refs), max_bytes=4096,
                )[0]
                or descriptor_row["cohort_sha256"] != registry._cohort_sha256
                or descriptor_row["context_revision"] != query_row["created_context_revision"]
                or query_row["created_context_revision"] > current.context_revision
            ):
                raise P2V3StoreConflict("Runtime request differs from the persisted owner/Turn query descriptor")

        # UI opaque selections are resolved only through this Store registry.
        selected_private_ids: list[uuid.UUID] = []
        for selected_ref in private_selection_refs:
            try:
                kind, private_id, activity_id, _ledger_unit_id = registry.binding_for_ref(selected_ref)
            except P2V3StoreNotFound:
                ui = current_aggregate.record.ui_context_snapshot
                if (
                    len(private_selection_refs) != 1
                    or operation != "read.expenses"
                    or ui is None
                    or ui.selected_entity is None
                    or ui.selected_entity.entity_type != UiEntityType.EXPENSE
                    or request.scope is None
                ):
                    raise P2V3StoreConflict(
                        "unaccepted private selection cannot be rebuilt from this Turn's UI context",
                    ) from None
                activity_id = registry.resolve_activity_ref(str(request.scope.activity_ref))
                registry._restore_unaccepted_ui_expense_ref(
                    selected_ref, expense_id=ui.selected_entity.entity_id,
                    activity_id=activity_id,
                )
                kind, private_id, activity_id, _ledger_unit_id = registry.binding_for_ref(selected_ref)
            if kind != "expense" or (request.scope is not None and activity_id != registry.resolve_activity_ref(str(request.scope.activity_ref))):
                raise P2V3StoreConflict("selected opaque expense reference is outside the authorized request scope")
            selected_private_ids.append(private_id)
        descriptor = codec3.V3QueryDescriptor(
            request=request,
            ui_expense_ids=tuple(sorted(selected_private_ids, key=str)),
            ui_expense_refs=tuple(sorted(private_selection_refs)),
            public_request_digest=_canonical_json(request.model_dump(mode="json", exclude_none=False), max_bytes=16_384)[1],
            normalized_selection_digest=_normalized_criteria_digest(criteria_json, private_selection_refs),
        )
        return registry._register_query_descriptor(logical_query_id, descriptor, identity=admission.identity)

    def consume_p2_v3_continuation(
        self,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        *,
        claim_token: str,
        logical_query_id: str,
        raw_next_page_ref: str,
        admission_id: str,
        attempt_seq: int,
        page_index: int,
        source_proof_sha256: str,
        projection_sha256: str,
        now: Optional[datetime] = None,
    ) -> tuple[str, int, int]:
        """Consume one opaque continuation digest and create its next page attempt atomically."""
        if type(raw_next_page_ref) is not str or re.fullmatch(r"ref_[A-Za-z0-9_-]{22,64}", raw_next_page_ref) is None:
            raise ValueError("continuation reference is invalid")
        _strict_positive_int(attempt_seq, "attempt_seq")
        _strict_positive_int(page_index, "page_index")
        if page_index != 1:
            raise P2V3StoreConflict("the candidate currently allows one continuation page")
        source_proof_sha256 = _check_sha256(source_proof_sha256, "source_proof_sha256", required=True)
        projection_sha256 = _check_sha256(projection_sha256, "projection_sha256", required=True)
        nonce_digest = _digest(raw_next_page_ref.encode("utf-8"))
        self._require_started()
        instant = _now(now)
        attempt_id = str(uuid.uuid4())
        with self._transaction() as connection:
            _, snapshot, _ = self._p2_v3_current_claim(
                connection, owner_user_id, turn_id, claim_token=claim_token, now=instant,
            )
            query = connection.execute(
                "SELECT * FROM p2_v3_queries WHERE logical_query_id=? AND owner_user_id=? AND turn_id=?",
                (logical_query_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            admission = connection.execute(
                "SELECT * FROM p2_v3_source_admissions WHERE admission_id=? AND owner_user_id=? AND turn_id=?",
                (admission_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            if query is None or admission is None:
                raise P2V3StoreNotFound("query or source admission is unavailable to this owner and Turn")
            if (
                admission["generation"] != snapshot.generation or admission["input_seq"] != snapshot.input_seq
                or admission["input_digest"] != snapshot.input_digest
                or admission["claim_epoch"] != snapshot.claim_epoch
                or admission["authority_epoch"] != snapshot.authority_epoch
                or admission["context_revision"] != snapshot.context_revision
                or query["scope_digest"] != admission["public_scope_digest"]
            ):
                raise P2V3StoreConflict("continuation query/admission is stale or outside the requested scope")
            issue = connection.execute(
                "SELECT * FROM p2_v3_continuation_nonce_issues WHERE nonce_sha256=? AND logical_query_id=? AND owner_user_id=? AND turn_id=?",
                (nonce_digest, logical_query_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            if issue is None:
                raise P2V3StoreConflict("continuation token was not issued by a bound source page")
            issuer_receipt = connection.execute(
                "SELECT * FROM p2_v3_query_result_receipts WHERE logical_query_id=? AND query_attempt_id=(SELECT attempt_id FROM p2_v3_query_attempts WHERE logical_query_id=? AND attempt_seq=? AND page_index=0 AND owner_user_id=? AND turn_id=?) AND page_index=0 AND owner_user_id=? AND turn_id=?",
                (logical_query_id, logical_query_id, attempt_seq, str(owner_user_id), str(turn_id), str(owner_user_id), str(turn_id)),
            ).fetchone()
            if issuer_receipt is None:
                raise P2V3StoreConflict("continuation source page receipt is unavailable")
            proof = self._p2_v3_continuation_proof_from_receipt(issuer_receipt)
            expected_source_proof_sha256 = P2V3RequestReferenceRegistry._continuation_proof_sha256(proof)
            if (
                issue["generation"] != snapshot.generation
                or issue["authority_epoch"] != snapshot.authority_epoch
                or issue["attempt_seq"] != attempt_seq or issue["page_index"] != page_index - 1
                or issue["criteria_digest"] != query["criteria_digest"]
                or issue["scope_digest"] != query["scope_digest"]
                or issue["source_proof_sha256"] != source_proof_sha256
                or issue["projection_sha256"] != projection_sha256
                or issue["source_proof_sha256"] != expected_source_proof_sha256
                or issue["projection_sha256"] != issuer_receipt["projection_sha256"]
                or issue["page_index"] != 0
                or issuer_receipt["has_more"] != 1
                or _parse_datetime(issue["expires_at"]) <= instant
            ):
                raise P2V3StoreConflict("continuation issuer is expired or no longer matches this query epoch")
            latest = connection.execute(
                "SELECT attempt_seq,MAX(page_index) AS page_index FROM p2_v3_query_attempts WHERE logical_query_id=? GROUP BY attempt_seq ORDER BY attempt_seq DESC LIMIT 1",
                (logical_query_id,),
            ).fetchone()
            if latest is None or int(latest["attempt_seq"]) != attempt_seq or int(latest["page_index"]) != page_index - 1:
                raise P2V3StoreConflict("continuation is not the latest contiguous page for this query")
            if connection.execute(
                "SELECT 1 FROM p2_v3_continuation_nonce_uses WHERE nonce_sha256=?",
                (nonce_digest,),
            ).fetchone() is not None:
                raise P2V3StoreConflict("continuation token was already consumed")
            connection.execute(
                """INSERT INTO p2_v3_continuation_nonce_uses (
                    nonce_sha256,logical_query_id,owner_user_id,turn_id,generation,
                    authority_epoch,attempt_seq,page_index,consumed_at
                ) VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    nonce_digest, logical_query_id, str(owner_user_id), str(turn_id), snapshot.generation,
                    snapshot.authority_epoch, attempt_seq, page_index, _stamp(instant),
                ),
            )
            connection.execute(
                """INSERT INTO p2_v3_query_attempts (
                    attempt_id,logical_query_id,owner_user_id,turn_id,generation,authority_epoch,
                    attempt_seq,page_index,criteria_digest,scope_digest,admission_id,attempt_state,observed_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,'started',?)""",
                (
                    attempt_id, logical_query_id, str(owner_user_id), str(turn_id), snapshot.generation,
                    snapshot.authority_epoch, attempt_seq, page_index, query["criteria_digest"],
                    query["scope_digest"], admission_id, _stamp(instant),
                ),
            )
        return attempt_id, page_index, attempt_seq

    def _p2_v3_capture_chain_plan(
        self,
        connection: sqlite3.Connection,
        *,
        owner_user_id: str,
        turn_id: str,
        snapshot: P2V3TurnSnapshot,
        reservation_id: str,
        source_role: str,
        source_table: str,
        reservation_query: Optional[sqlite3.Row],
        reservation_attempt: Optional[sqlite3.Row],
        reservation_admission_id: Optional[str],
        capture_chain_logical_query_id: Optional[str],
        capture_chain_attempt_id: Optional[str],
        requested_table_ordinal: Optional[int],
    ) -> dict[str, Any]:
        """Validate a reserved GET's immutable chain/table link inside its charge transaction."""
        if source_role not in P2_V3_SOURCE_ROLES:
            raise ValueError("GET source role is not allowlisted")
        if source_role not in P2_V3_SOURCE_TABLE_ROLES[source_table]:
            raise ValueError("GET source role does not match its exact source table")
        # Before a logical operation exists, only the fixed scope/member/label
        # bootstrap reads are legal. Those same admission-bound GETs may be
        # attributed to a newly created query attempt for pre/post fencing,
        # but they do not become financial reads and do not inherit that
        # operation's narrower data-role allowlist.
        if reservation_query is None:
            if source_table not in P2_V3_METADATA_TABLE_ROLES or source_role not in P2_V3_METADATA_TABLE_ROLES[source_table]:
                raise ValueError("admission-bound GET is outside the fixed scope metadata allowlist")
        else:
            allowed_roles = P2_V3_OPERATION_SOURCE_ROLES[reservation_query["operation"]]
            if source_table in P2_V3_METADATA_TABLE_ROLES:
                allowed_roles = allowed_roles | P2_V3_METADATA_TABLE_ROLES[source_table]
            if source_role not in allowed_roles:
                raise ValueError("query-bound GET source role is not valid for its logical operation")

        chain_query = reservation_query
        chain_attempt = reservation_attempt
        if reservation_query is not None:
            if (
                capture_chain_logical_query_id not in (None, reservation_query["logical_query_id"])
                or capture_chain_attempt_id not in (None, reservation_attempt["attempt_id"])
            ):
                raise P2V3StoreConflict("query GET cannot be attributed to another query attempt")
        elif capture_chain_logical_query_id is not None:
            if reservation_admission_id is None:
                raise P2V3StoreConflict("metadata chain requires an authenticated source admission")
            chain_query = connection.execute(
                "SELECT * FROM p2_v3_queries WHERE logical_query_id=? AND owner_user_id=? AND turn_id=?",
                (capture_chain_logical_query_id, owner_user_id, turn_id),
            ).fetchone()
            chain_attempt = connection.execute(
                "SELECT * FROM p2_v3_query_attempts WHERE attempt_id=? AND logical_query_id=? "
                "AND owner_user_id=? AND turn_id=?",
                (capture_chain_attempt_id, capture_chain_logical_query_id, owner_user_id, turn_id),
            ).fetchone()
            if chain_query is None or chain_attempt is None:
                raise P2V3StoreNotFound("metadata capture chain is not available to this owner and Turn")

        if chain_query is None:
            if reservation_admission_id is None:
                raise P2V3StoreConflict("every bootstrap GET requires its verified admission identity")
            chain_kind = "admission"
            chain_id = reservation_admission_id
            chain_query_id = None
            chain_attempt_id = None
            chain_admission_id = reservation_admission_id
            page_index = None
        else:
            if chain_attempt is None or reservation_admission_id is None:
                raise P2V3StoreConflict("query capture chain is missing its current attempt/admission binding")
            if (
                chain_attempt["logical_query_id"] != chain_query["logical_query_id"]
                or chain_attempt["owner_user_id"] != owner_user_id
                or chain_attempt["turn_id"] != turn_id
                or chain_attempt["generation"] != snapshot.generation
                or chain_attempt["authority_epoch"] != snapshot.authority_epoch
                or chain_attempt["criteria_digest"] != chain_query["criteria_digest"]
                or chain_attempt["scope_digest"] != chain_query["scope_digest"]
                or chain_attempt["admission_id"] != reservation_admission_id
                or chain_attempt["attempt_state"] != "started"
            ):
                raise P2V3StoreConflict("capture chain attempt is stale or does not match its immutable query")
            latest = connection.execute(
                "SELECT MAX(attempt_seq) FROM p2_v3_query_attempts WHERE logical_query_id=? AND owner_user_id=? AND turn_id=?",
                (chain_query["logical_query_id"], owner_user_id, turn_id),
            ).fetchone()[0]
            if int(latest or 0) != int(chain_attempt["attempt_seq"]):
                raise P2V3StoreConflict("capture chain attempt is not the latest query attempt")
            admission = connection.execute(
                "SELECT * FROM p2_v3_source_admissions WHERE admission_id=? AND owner_user_id=? AND turn_id=?",
                (reservation_admission_id, owner_user_id, turn_id),
            ).fetchone()
            if admission is None or admission["public_scope_digest"] != chain_query["scope_digest"]:
                raise P2V3StoreConflict("capture chain query does not match its current admitted scope")
            chain_kind = "query_attempt"
            chain_id = chain_attempt["attempt_id"]
            chain_query_id = chain_query["logical_query_id"]
            chain_attempt_id = chain_attempt["attempt_id"]
            chain_admission_id = None

        charged_clause = """
            AND NOT EXISTS (
                SELECT 1 FROM p2_v3_charge_events terminal
                WHERE terminal.reservation_id=r.reservation_id
                  AND terminal.event_kind='known_no_dispatch'
            )
        """
        chain_count = int(connection.execute(
            "SELECT COUNT(*) FROM p2_v3_capture_chain_reservations r "
            "JOIN p2_v3_charge_events reserved ON reserved.reservation_id=r.reservation_id "
            "AND reserved.event_kind='reserved' WHERE r.owner_user_id=? AND r.turn_id=? "
            "AND r.capture_chain_kind=? AND r.capture_chain_id=? " + charged_clause,
            (owner_user_id, turn_id, chain_kind, chain_id),
        ).fetchone()[0])
        if chain_count >= P2_V3_MAX_SOURCE_PAGES_PER_CAPTURE_CHAIN:
            raise P2V3StoreConflict("P2 v3 source capture chain page budget is exhausted")
        table_count = int(connection.execute(
            "SELECT COUNT(*) FROM p2_v3_capture_chain_reservations r "
            "JOIN p2_v3_charge_events reserved ON reserved.reservation_id=r.reservation_id "
            "AND reserved.event_kind='reserved' WHERE r.owner_user_id=? AND r.turn_id=? "
            "AND r.capture_chain_kind=? AND r.capture_chain_id=? AND r.source_table=? " + charged_clause,
            (owner_user_id, turn_id, chain_kind, chain_id, source_table),
        ).fetchone()[0])
        if table_count >= P2_V3_MAX_SOURCE_PAGES_PER_TABLE:
            raise P2V3StoreConflict("P2 v3 source table page budget is exhausted")
        if requested_table_ordinal is not None and requested_table_ordinal != table_count:
            raise P2V3StoreConflict("capture-chain source-table GET ordinal is not the next available slot")
        in_flight = connection.execute(
            "SELECT 1 FROM p2_v3_capture_chain_reservations r "
            "WHERE r.owner_user_id=? AND r.turn_id=? AND r.capture_chain_kind=? "
            "AND r.capture_chain_id=? AND r.source_table=? AND NOT EXISTS ("
            "SELECT 1 FROM p2_v3_charge_events terminal WHERE terminal.reservation_id=r.reservation_id "
            "AND terminal.event_kind IN ('settled','known_no_dispatch','unknown')) LIMIT 1",
            (owner_user_id, turn_id, chain_kind, chain_id, source_table),
        ).fetchone()
        if in_flight is not None:
            raise P2V3StoreConflict("a source page for this table is already pending in the capture chain")
        sequence = connection.execute(
            "SELECT COALESCE(MAX(chain_sequence),-1)+1 FROM p2_v3_capture_chain_reservations "
            "WHERE owner_user_id=? AND turn_id=? AND capture_chain_kind=? AND capture_chain_id=?",
            (owner_user_id, turn_id, chain_kind, chain_id),
        ).fetchone()[0]
        if type(sequence) is not int or sequence < 0 or sequence > 9_223_372_036_854_775_807:
            raise P2V3StoreConflict("capture chain audit sequence is exhausted")
        return {
            "reservation_id": reservation_id,
            "owner_user_id": owner_user_id,
            "turn_id": turn_id,
            "chain_kind": chain_kind,
            "chain_id": chain_id,
            "chain_query_id": chain_query_id,
            "chain_attempt_id": chain_attempt_id,
            "chain_admission_id": chain_admission_id,
            "table_get_ordinal": table_count,
            "sequence": sequence,
            "source_role": source_role,
            "source_table": source_table,
            "generation": snapshot.generation,
            "input_seq": snapshot.input_seq,
            "input_digest": snapshot.input_digest,
            "claim_epoch": snapshot.claim_epoch,
            "authority_epoch": snapshot.authority_epoch,
            "context_revision": snapshot.context_revision,
        }

    def reserve_p2_v3_stage(
        self,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        *,
        claim_token: str,
        stage: str,
        active_limit_us: int,
        backend_limit_us: int = 0,
        response_bytes_limit: int = 0,
        logical_query_id: Optional[str] = None,
        query_attempt_id: Optional[str] = None,
        admission_id: Optional[str] = None,
        source_role: Optional[str] = None,
        source_table: Optional[str] = None,
        capture_chain_logical_query_id: Optional[str] = None,
        capture_chain_attempt_id: Optional[str] = None,
        capture_chain_table_ordinal: Optional[int] = None,
        request_digest: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> str:
        """Atomically reserve one execution stage against the Turn-wide budget."""
        self._require_started()
        if stage not in P2_V3_CHARGE_STAGES:
            raise ValueError("candidate charge stage is not allowlisted")
        _strict_positive_int(active_limit_us, "active_limit_us")
        _strict_nonnegative_int(backend_limit_us, "backend_limit_us")
        _strict_nonnegative_int(response_bytes_limit, "response_bytes_limit")
        if active_limit_us > P2_V3_MAX_ACTIVE_US or backend_limit_us > P2_V3_MAX_BACKEND_US:
            raise ValueError("candidate charge reservation exceeds a stage maximum")
        if backend_limit_us > active_limit_us:
            raise ValueError("backend charge must be an active-time subset")
        request_digest = _check_sha256(request_digest, "request_digest", required=stage == "backend_get")
        if stage == "backend_get":
            default_table_by_role = {
                "activity": "activities", "membership": "activity_members",
                "participant": "participants", "ledger_unit": "ledger_units",
                "expense": "expenses", "debt": "expense_debts",
                "refund_parent": "expenses", "prepayment_account": "prepayment_accounts",
                "prepayment_usage": "prepayment_usages", "prepayment_return": "transfers",
                "financial_version": "activities", "actor": "participant_claims",
                "scope_label": "activities",
            }
            source_table = source_table or default_table_by_role.get(source_role or "")
            if type(source_table) is not str or source_table not in P2_V3_SOURCE_TABLE_ROLES:
                raise ValueError("GET source table is not in the exact v3 table allowlist")
            if source_role not in P2_V3_SOURCE_TABLE_ROLES[source_table]:
                raise ValueError("GET source role does not match its exact source table")
            chain_fields = (
                capture_chain_logical_query_id,
                capture_chain_attempt_id,
            )
            if logical_query_id is not None:
                if any(value is not None for value in chain_fields) and chain_fields != (
                    logical_query_id, query_attempt_id,
                ):
                    raise ValueError("query GET capture chain must be its exact reserved query attempt")
            elif any(value is not None for value in chain_fields) and not all(
                value is not None for value in chain_fields
            ):
                raise ValueError("metadata capture chain requires both a logical query and its attempt")
            if capture_chain_table_ordinal is not None:
                _strict_nonnegative_int(capture_chain_table_ordinal, "capture_chain_table_ordinal")
                if capture_chain_table_ordinal >= P2_V3_MAX_SOURCE_PAGES_PER_TABLE:
                    raise ValueError("capture-chain table GET ordinal exceeds its four-request bound")
        elif any(value is not None for value in (
            source_table, capture_chain_logical_query_id, capture_chain_attempt_id,
            capture_chain_table_ordinal,
        )):
            raise ValueError("non-GET reservations cannot carry source capture-chain metadata")
        if stage in {"model", "repair"}:
            if (backend_limit_us, response_bytes_limit, logical_query_id, query_attempt_id,
                    admission_id, source_role, request_digest) != (0, 0, None, None, None, None, None):
                raise ValueError("model reservations cannot carry source GET metadata")
        elif stage == "backend_get":
            if backend_limit_us <= 0 or response_bytes_limit <= 0:
                raise ValueError("GET reservations require backend time and response-byte bounds")
            if response_bytes_limit > P2_V3_MAX_GET_RESPONSE_BYTES:
                raise ValueError("GET reservation exceeds the 1 MiB per-GET response cap")
            if (logical_query_id is None) == (admission_id is None):
                raise ValueError("GET must bind exactly one logical query or pre-query admission")
            if logical_query_id is not None and query_attempt_id is None:
                raise ValueError("query GET must bind the active private page attempt")
            if logical_query_id is None and query_attempt_id is not None:
                raise ValueError("admission GET cannot bind a logical query attempt")
            if source_role not in P2_V3_SOURCE_ROLES:
                raise ValueError("GET source role is not allowlisted")
        elif stage == "backend_processing":
            if backend_limit_us <= 0 or response_bytes_limit != 0 or any(
                item is not None for item in (logical_query_id, query_attempt_id, admission_id, source_role, request_digest)
            ):
                raise ValueError("backend processing reservations carry only active/backend timing")
        elif stage == "local_processing":
            if backend_limit_us != 0 or response_bytes_limit != 0 or any(
                item is not None for item in (logical_query_id, query_attempt_id, admission_id, source_role, request_digest)
            ):
                raise ValueError("local processing reservations cannot carry backend/source metadata")
        reservation_id = str(uuid.uuid4())
        instant = _now(now)
        with self._transaction() as connection:
            root, snapshot, _ = self._p2_v3_current_claim(
                connection, owner_user_id, turn_id, claim_token=claim_token, now=instant,
            )
            overrun_active_us, overrun_backend_us, overrun_response_bytes = self._p2_v3_overrun_totals(
                connection, str(owner_user_id), str(turn_id),
            )
            if (
                snapshot.active_used_us + snapshot.active_reserved_us + overrun_active_us + active_limit_us > P2_V3_MAX_ACTIVE_US
                or snapshot.backend_used_us + snapshot.backend_reserved_us + overrun_backend_us + backend_limit_us > P2_V3_MAX_BACKEND_US
                or snapshot.response_bytes + snapshot.bytes_reserved + overrun_response_bytes + response_bytes_limit > P2_V3_MAX_RESPONSE_BYTES
                or snapshot.get_attempts + snapshot.get_reserved + int(stage == "backend_get") > P2_V3_MAX_GETS
            ):
                raise P2V3StoreConflict("candidate physical-work budget is exhausted")
            if stage in {"model", "repair"} and snapshot.model_calls + snapshot.model_reserved_calls >= P2_V3_MAX_MODEL_CALLS:
                raise P2V3StoreConflict("candidate model-call budget is exhausted")
            if stage == "repair" and snapshot.repair_calls + snapshot.repair_reserved_calls >= 1:
                raise P2V3StoreConflict("candidate repair-call budget is exhausted")
            query = None
            attempt = None
            admission = None
            admission_lookup_id = admission_id
            event_admission_id = admission_id
            if logical_query_id is not None:
                query = connection.execute(
                    "SELECT * FROM p2_v3_queries WHERE logical_query_id=? AND owner_user_id=? AND turn_id=?",
                    (logical_query_id, str(owner_user_id), str(turn_id)),
                ).fetchone()
                attempt = connection.execute(
                    "SELECT * FROM p2_v3_query_attempts WHERE attempt_id=? AND logical_query_id=? "
                    "AND owner_user_id=? AND turn_id=?",
                    (query_attempt_id, logical_query_id, str(owner_user_id), str(turn_id)),
                ).fetchone()
                if query is None or attempt is None:
                    raise P2V3StoreNotFound("query or page attempt is unavailable to this owner and Turn")
                if (
                    attempt["generation"] != snapshot.generation
                    or attempt["authority_epoch"] != snapshot.authority_epoch
                    or attempt["criteria_digest"] != query["criteria_digest"]
                    or attempt["scope_digest"] != query["scope_digest"]
                    or attempt["attempt_state"] != "started"
                ):
                    raise P2V3StoreConflict("query page attempt is stale or mismatched")
                if source_role is None:
                    raise ValueError("query GET requires a source role")
                allowed_roles = P2_V3_OPERATION_SOURCE_ROLES[query["operation"]]
                if source_table in P2_V3_METADATA_TABLE_ROLES:
                    allowed_roles = allowed_roles | P2_V3_METADATA_TABLE_ROLES[source_table]
                if source_role not in allowed_roles:
                    raise ValueError("GET source role is not valid for this logical operation")
                admission_lookup_id = attempt["admission_id"]
                # Query-bound ledger entries point through the attempt FK. Keep
                # admission only as a validation dependency; the SQL shape
                # deliberately makes query and bootstrap admission exclusive.
                event_admission_id = None
            if admission_lookup_id is not None:
                admission = connection.execute(
                    "SELECT * FROM p2_v3_source_admissions WHERE admission_id=? AND owner_user_id=? AND turn_id=?",
                    (admission_lookup_id, str(owner_user_id), str(turn_id)),
                ).fetchone()
                if admission is None:
                    raise P2V3StoreNotFound("source admission is unavailable to this owner and Turn")
                if (
                    admission["generation"] != snapshot.generation
                    or admission["input_seq"] != snapshot.input_seq
                    or admission["input_digest"] != snapshot.input_digest
                    or admission["claim_epoch"] != snapshot.claim_epoch
                    or admission["authority_epoch"] != snapshot.authority_epoch
                    or admission["context_revision"] != snapshot.context_revision
                ):
                    raise P2V3StoreConflict("source admission is stale for the current claim")
            capture_chain_plan = None
            if stage == "backend_get":
                capture_chain_plan = self._p2_v3_capture_chain_plan(
                    connection,
                    owner_user_id=str(owner_user_id),
                    turn_id=str(turn_id),
                    snapshot=snapshot,
                    reservation_id=reservation_id,
                    source_role=str(source_role),
                    source_table=str(source_table),
                    reservation_query=query,
                    reservation_attempt=attempt,
                    reservation_admission_id=admission_lookup_id,
                    capture_chain_logical_query_id=capture_chain_logical_query_id,
                    capture_chain_attempt_id=capture_chain_attempt_id,
                    requested_table_ordinal=capture_chain_table_ordinal,
                )
            connection.execute(
                """INSERT INTO p2_v3_charge_events (
                    event_id,reservation_id,event_kind,owner_user_id,turn_id,profile_id,stage,
                    generation,claim_epoch,authority_epoch,context_revision,logical_query_id,
                    query_attempt_id,admission_id,source_role,active_limit_us,backend_limit_us,
                    response_bytes_limit,request_digest,occurred_at
                ) VALUES (?,?,'reserved',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()), reservation_id, str(owner_user_id), str(turn_id),
                    P2_V3_CANDIDATE_PROFILE_ID, stage, snapshot.generation, snapshot.claim_epoch,
                    snapshot.authority_epoch, snapshot.context_revision, logical_query_id,
                    query_attempt_id, event_admission_id, source_role, active_limit_us,
                    backend_limit_us, response_bytes_limit, request_digest, _stamp(instant),
                ),
            )
            if capture_chain_plan is not None:
                pin = connection.execute(
                    "SELECT cohort_sha256 FROM p2_v3_turn_execution_pins WHERE turn_id=? AND owner_user_id=?",
                    (str(turn_id), str(owner_user_id)),
                ).fetchone()
                if pin is None:
                    raise P2V3UnsupportedProfile("capture-chain reservation requires the immutable execution pin")
                connection.execute(
                    """INSERT INTO p2_v3_capture_chain_reservations (
                        reservation_id,owner_user_id,turn_id,cohort_sha256,
                        reservation_binding_kind,reservation_admission_id,
                        reservation_logical_query_id,reservation_query_attempt_id,
                        capture_chain_kind,capture_chain_id,capture_chain_logical_query_id,
                        capture_chain_attempt_id,table_get_ordinal,chain_sequence,source_role,source_table,
                        generation,input_seq,input_digest,claim_epoch,authority_epoch,context_revision,reserved_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        capture_chain_plan["reservation_id"], capture_chain_plan["owner_user_id"],
                        capture_chain_plan["turn_id"], pin["cohort_sha256"],
                        "query_attempt" if logical_query_id is not None else "admission",
                        admission_lookup_id if logical_query_id is None else None,
                        logical_query_id,
                        query_attempt_id if logical_query_id is not None else None,
                        capture_chain_plan["chain_kind"], capture_chain_plan["chain_id"],
                        capture_chain_plan["chain_query_id"], capture_chain_plan["chain_attempt_id"],
                        capture_chain_plan["table_get_ordinal"], capture_chain_plan["sequence"],
                        capture_chain_plan["source_role"], capture_chain_plan["source_table"],
                        capture_chain_plan["generation"], capture_chain_plan["input_seq"],
                        capture_chain_plan["input_digest"], capture_chain_plan["claim_epoch"],
                        capture_chain_plan["authority_epoch"], capture_chain_plan["context_revision"],
                        _stamp(instant),
                    ),
                )
            changed = connection.execute(
                """UPDATE p2_v3_turns SET active_reserved_us=active_reserved_us+?,
                    backend_reserved_us=backend_reserved_us+?,bytes_reserved=bytes_reserved+?,
                    model_reserved_calls=model_reserved_calls+?,repair_reserved_calls=repair_reserved_calls+?,
                    get_reserved=get_reserved+?,revision=revision+1,updated_at=?
                    WHERE turn_id=? AND owner_user_id=? AND revision=?
                      AND active_used_us+active_reserved_us+?<=?
                      AND backend_used_us+backend_reserved_us+?<=?
                      AND response_bytes+bytes_reserved+?<=?
                      AND get_attempts+get_reserved+?<=? AND model_calls+model_reserved_calls+?<=?
                      AND repair_calls+repair_reserved_calls+?<=1""",
                (
                    active_limit_us, backend_limit_us, response_bytes_limit,
                    int(stage in {"model", "repair"}), int(stage == "repair"), int(stage == "backend_get"),
                    _stamp(instant), str(turn_id), str(owner_user_id), snapshot.revision,
                    active_limit_us, P2_V3_MAX_ACTIVE_US, backend_limit_us, P2_V3_MAX_BACKEND_US,
                    response_bytes_limit, P2_V3_MAX_RESPONSE_BYTES, int(stage == "backend_get"),
                    P2_V3_MAX_GETS, int(stage in {"model", "repair"}), P2_V3_MAX_MODEL_CALLS,
                    int(stage == "repair"),
                ),
            ).rowcount
            if changed != 1:
                raise P2V3StoreConflict("candidate budget reservation lost its Store CAS")
        return reservation_id

    def mark_p2_v3_dispatch_started(
        self,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        reservation_id: str,
        *,
        claim_token: str,
        prepared_request_sha256: Optional[str] = None,
        selected_model_key: Optional[str] = None,
        validated_measurement_sha256: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> None:
        """Persist irreversible-dispatch intent before invoking the external stage."""
        self._require_started()
        instant = _now(now)
        with self._transaction() as connection:
            _, snapshot, _ = self._p2_v3_current_claim(
                connection, owner_user_id, turn_id, claim_token=claim_token, now=instant,
            )
            reserved = connection.execute(
                "SELECT * FROM p2_v3_charge_events WHERE reservation_id=? AND owner_user_id=? AND turn_id=? AND event_kind='reserved'",
                (reservation_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            if reserved is None:
                raise P2V3StoreNotFound("candidate charge reservation is unavailable to this owner and Turn")
            if (
                reserved["generation"] != snapshot.generation
                or reserved["claim_epoch"] != snapshot.claim_epoch
                or reserved["authority_epoch"] != snapshot.authority_epoch
                or reserved["context_revision"] != snapshot.context_revision
            ):
                raise P2V3StoreConflict("candidate charge reservation is stale")
            stage = reserved["stage"]
            model_stage = stage in {"model", "repair"}
            prepared_request_sha256 = _check_sha256(
                prepared_request_sha256, "prepared_request_sha256", required=model_stage,
            )
            validated_measurement_sha256 = _check_sha256(
                validated_measurement_sha256, "validated_measurement_sha256", required=model_stage,
            )
            if model_stage:
                if type(selected_model_key) is not str or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", selected_model_key) is None:
                    raise ValueError("selected model key must be a bounded configured key")
            elif any(item is not None for item in (
                prepared_request_sha256, selected_model_key, validated_measurement_sha256,
            )):
                raise ValueError("non-model dispatch cannot carry model preparation metadata")
            existing = connection.execute(
                "SELECT * FROM p2_v3_charge_events WHERE reservation_id=? AND event_kind='dispatch_started'",
                (reservation_id,),
            ).fetchone()
            if existing is not None:
                observed = (
                    existing["prepared_request_sha256"], existing["selected_model_key"],
                    existing["validated_measurement_sha256"],
                )
                expected = (prepared_request_sha256, selected_model_key, validated_measurement_sha256)
                if observed == expected:
                    return
                raise P2V3StoreConflict("candidate dispatch metadata conflicts with the persisted preparation")
            if connection.execute(
                "SELECT 1 FROM p2_v3_charge_events WHERE reservation_id=? AND event_kind IN ('settled','known_no_dispatch','unknown')",
                (reservation_id,),
            ).fetchone() is not None:
                raise P2V3StoreConflict("candidate charge reservation was already settled")
            self._insert_p2_v3_charge_event(
                connection, reserved, event_kind="dispatch_started", now=instant,
                prepared_request_sha256=prepared_request_sha256,
                selected_model_key=selected_model_key,
                validated_measurement_sha256=validated_measurement_sha256,
            )
            repair_stage = stage == "repair"
            get_stage = stage == "backend_get"
            changed = connection.execute(
                """UPDATE p2_v3_turns SET model_reserved_calls=model_reserved_calls-?,
                    model_calls=model_calls+?,
                    repair_reserved_calls=repair_reserved_calls-?,repair_calls=repair_calls+?,
                    get_reserved=get_reserved-?,get_attempts=get_attempts+?,revision=revision+1,updated_at=?
                    WHERE turn_id=? AND owner_user_id=? AND revision=?
                      AND model_reserved_calls>=? AND repair_reserved_calls>=? AND get_reserved>=?""",
                (
                    int(model_stage), int(model_stage), int(repair_stage), int(repair_stage),
                    int(get_stage), int(get_stage), _stamp(instant), str(turn_id), str(owner_user_id),
                    snapshot.revision, int(model_stage), int(repair_stage), int(get_stage),
                ),
            ).rowcount
            if changed != 1:
                raise P2V3StoreConflict("candidate dispatch accounting lost its Store CAS")

    def settle_p2_v3_stage(
        self,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        reservation_id: str,
        *,
        outcome: Literal["actual", "known_no_dispatch", "unknown"],
        actual_active_us: Optional[int] = None,
        actual_backend_us: Optional[int] = None,
        actual_response_bytes: Optional[int] = None,
        raw_body_sha256: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> P2V3TurnSnapshot:
        """Settle measured or conservative costs exactly once, even for a late cancelled worker."""
        self._require_started()
        if outcome not in {"actual", "known_no_dispatch", "unknown"}:
            raise ValueError("invalid candidate stage settlement outcome")
        has_actual_measurements = not (
            outcome == "unknown"
            and actual_active_us is None
            and actual_backend_us is None
            and actual_response_bytes is None
        )
        if has_actual_measurements:
            actual_active_us = _strict_nonnegative_int(actual_active_us, "actual_active_us")
            actual_backend_us = _strict_nonnegative_int(actual_backend_us if actual_backend_us is not None else 0, "actual_backend_us")
            actual_response_bytes = _strict_nonnegative_int(actual_response_bytes if actual_response_bytes is not None else 0, "actual_response_bytes")
        if has_actual_measurements and actual_backend_us > actual_active_us:
            raise ValueError("backend work must be a subset of active work")
        raw_body_sha256 = _check_sha256(raw_body_sha256, "raw_body_sha256")
        instant = _now(now)
        with self._transaction() as connection:
            root = connection.execute(
                "SELECT * FROM p2_v3_turns WHERE turn_id=? AND owner_user_id=?",
                (str(turn_id), str(owner_user_id)),
            ).fetchone()
            if root is None:
                raise P2V3StoreNotFound("v3 candidate Turn is not available to this owner")
            snapshot = self._p2_v3_snapshot(root)
            reserved = connection.execute(
                "SELECT * FROM p2_v3_charge_events WHERE reservation_id=? AND owner_user_id=? AND turn_id=? AND event_kind='reserved'",
                (reservation_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            if reserved is None:
                raise P2V3StoreNotFound("candidate charge reservation is unavailable to this owner and Turn")
            started = connection.execute(
                "SELECT 1 FROM p2_v3_charge_events WHERE reservation_id=? AND event_kind='dispatch_started'",
                (reservation_id,),
            ).fetchone() is not None
            terminal = connection.execute(
                "SELECT 1 FROM p2_v3_charge_events WHERE reservation_id=? AND event_kind IN ('settled','known_no_dispatch','unknown')",
                (reservation_id,),
            ).fetchone()
            if terminal is not None:
                raise P2V3StoreConflict("candidate charge reservation was already settled")
            if outcome == "actual" and not started:
                raise P2V3StoreConflict("actual settlement requires a persisted dispatch marker")
            if outcome == "known_no_dispatch" and started:
                raise P2V3StoreConflict("a dispatched reservation cannot be released as pre-dispatch")
            if outcome == "unknown" and not started:
                raise P2V3StoreConflict("unknown outcome requires a persisted dispatch marker")
            active_limit = int(reserved["active_limit_us"])
            backend_limit = int(reserved["backend_limit_us"])
            bytes_limit = int(reserved["response_bytes_limit"])
            if outcome == "unknown":
                charged_active, charged_backend, charged_bytes = active_limit, backend_limit, bytes_limit
                event_kind = "unknown"
                raw_body_sha256 = None
            elif outcome == "known_no_dispatch":
                if actual_backend_us != 0 or actual_response_bytes != 0 or raw_body_sha256 is not None:
                    raise ValueError("known pre-dispatch work cannot charge HTTP time, bytes or body digest")
                charged_active = min(actual_active_us, active_limit)
                charged_backend, charged_bytes = 0, 0
                event_kind = "known_no_dispatch"
                raw_body_sha256 = None
            else:
                overrun = (
                    actual_active_us > active_limit or actual_backend_us > backend_limit
                    or actual_response_bytes > bytes_limit
                )
                event_kind = "unknown" if overrun else "settled"
                if overrun:
                    charged_active, charged_backend, charged_bytes = active_limit, backend_limit, bytes_limit
                else:
                    charged_active, charged_backend, charged_bytes = (
                        actual_active_us, actual_backend_us, actual_response_bytes,
                    )
                if overrun:
                    raw_body_sha256 = None
            if has_actual_measurements:
                overrun_active = max(0, actual_active_us - active_limit)
                overrun_backend = max(0, actual_backend_us - backend_limit)
                overrun_bytes = max(0, actual_response_bytes - bytes_limit)
            else:
                overrun_active = overrun_backend = overrun_bytes = 0
            if event_kind == "unknown":
                raw_body_sha256 = None
            if reserved["stage"] != "backend_get" and raw_body_sha256 is not None:
                raise ValueError("only a GET charge may bind a response body digest")
            self._insert_p2_v3_charge_event(
                connection, reserved, event_kind=event_kind, now=instant,
                actual_active_us=charged_active, actual_backend_us=charged_backend,
                actual_response_bytes=charged_bytes, overrun_active_us=overrun_active,
                overrun_backend_us=overrun_backend, overrun_response_bytes=overrun_bytes,
                raw_body_sha256=raw_body_sha256,
            )
            stage = reserved["stage"]
            model_stage = stage in {"model", "repair"}
            repair_stage = stage == "repair"
            get_stage = stage == "backend_get"
            release_model = int(model_stage and not started)
            release_repair = int(repair_stage and not started)
            release_get = int(get_stage and not started)
            changed = connection.execute(
                """UPDATE p2_v3_turns SET active_reserved_us=active_reserved_us-?,
                    active_used_us=active_used_us+?,backend_reserved_us=backend_reserved_us-?,
                    backend_used_us=backend_used_us+?,bytes_reserved=bytes_reserved-?,
                    response_bytes=response_bytes+?,model_reserved_calls=model_reserved_calls-?,
                    repair_reserved_calls=repair_reserved_calls-?,get_reserved=get_reserved-?,
                    historical_unknown_consumption=MAX(historical_unknown_consumption,?),
                    revision=revision+1,updated_at=? WHERE turn_id=? AND owner_user_id=? AND revision=?
                      AND active_reserved_us>=? AND backend_reserved_us>=? AND bytes_reserved>=?
                      AND model_reserved_calls>=? AND repair_reserved_calls>=? AND get_reserved>=?""",
                (
                    active_limit, charged_active, backend_limit, charged_backend, bytes_limit, charged_bytes,
                    release_model, release_repair, release_get, int(event_kind == "unknown"), _stamp(instant),
                    str(turn_id), str(owner_user_id), snapshot.revision, active_limit, backend_limit,
                    bytes_limit, release_model, release_repair, release_get,
                ),
            ).rowcount
            if changed != 1:
                raise P2V3StoreConflict("candidate settlement lost its Store CAS")
            updated = connection.execute(
                "SELECT * FROM p2_v3_turns WHERE turn_id=? AND owner_user_id=?",
                (str(turn_id), str(owner_user_id)),
            ).fetchone()
            return self._p2_v3_snapshot(updated)

    def record_p2_v3_wire_capture_cost_only(
        self,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        reservation_id: str,
        *,
        http_status: int,
        content_range: Optional[str],
        returned_count: int,
        response_bytes: int,
        raw_body_sha256: str,
        observed_at: datetime,
    ) -> str:
        """Link a real settled GET capture without granting source-fact authority."""
        self._require_started()
        _strict_nonnegative_int(returned_count, "returned_count")
        _strict_nonnegative_int(response_bytes, "response_bytes")
        if type(http_status) is not int or not 100 <= http_status <= 599:
            raise ValueError("HTTP status must be an integer status code")
        if content_range is not None and (type(content_range) is not str or len(content_range) > 512):
            raise ValueError("Content-Range is outside the capture bound")
        digest = _check_sha256(raw_body_sha256, "raw_body_sha256", required=True)
        instant = _now(observed_at)
        capture_id = str(uuid.uuid4())
        with self._transaction() as connection:
            settled = connection.execute(
                """SELECT reserved.*,terminal.raw_body_sha256 AS settled_raw_body_sha256,
                          terminal.actual_response_bytes AS settled_response_bytes,
                          terminal.event_kind AS terminal_kind
                    FROM p2_v3_charge_events AS reserved
                    JOIN p2_v3_charge_events AS terminal USING(reservation_id,owner_user_id,turn_id)
                    WHERE reserved.reservation_id=? AND reserved.owner_user_id=? AND reserved.turn_id=?
                      AND reserved.event_kind='reserved' AND terminal.event_kind='settled'""",
                (reservation_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            if settled is None:
                raise P2V3StoreConflict("wire capture requires a settled GET reservation")
            if (
                settled["stage"] != "backend_get" or settled["settled_raw_body_sha256"] != digest
                or int(settled["settled_response_bytes"]) != response_bytes
            ):
                raise P2V3StoreConflict("wire capture differs from its settled GET cost record")
            if settled["logical_query_id"] is not None:
                attempt = connection.execute(
                    "SELECT * FROM p2_v3_query_attempts WHERE attempt_id=? AND logical_query_id=? "
                    "AND owner_user_id=? AND turn_id=?",
                    (settled["query_attempt_id"], settled["logical_query_id"], str(owner_user_id), str(turn_id)),
                ).fetchone()
                if attempt is None:
                    raise P2V3StoreConflict("wire capture page attempt is unavailable")
                page_index = int(attempt["page_index"])
                if attempt["attempt_state"] != "started":
                    raise P2V3StoreConflict("wire capture cannot bind a closed page attempt")
            else:
                attempt = None
                page_index = None
            connection.execute(
                """INSERT INTO p2_v3_wire_captures (
                    capture_id,reservation_id,reservation_event_kind,owner_user_id,turn_id,
                    query_attempt_id,logical_query_id,admission_id,source_role,page_index,
                    generation,claim_epoch,authority_epoch,context_revision,request_digest,
                    raw_body_sha256,http_status,content_range,returned_count,response_bytes,
                    observed_at,capture_state
                ) VALUES (?,?,'settled',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'cost_only')""",
                (
                    capture_id, reservation_id, str(owner_user_id), str(turn_id),
                    settled["query_attempt_id"], settled["logical_query_id"], settled["admission_id"],
                    settled["source_role"], page_index, settled["generation"], settled["claim_epoch"],
                    settled["authority_epoch"], settled["context_revision"], settled["request_digest"],
                    digest, http_status, content_range, returned_count, response_bytes, _stamp(instant),
                ),
            )
        return capture_id

    def _p2_v3_settle_processing_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        claim_token: str,
        reservation_id: str,
        actual_us: int,
        now: datetime,
    ) -> None:
        """Settle acceptance CPU in the same transaction as accepted proof rows."""
        actual_us = _strict_nonnegative_int(actual_us, "actual_us")
        _, snapshot, _ = self._p2_v3_current_claim(
            connection, owner_user_id, turn_id, claim_token=claim_token, now=now,
        )
        reserved = connection.execute(
            "SELECT * FROM p2_v3_charge_events WHERE reservation_id=? AND owner_user_id=? AND turn_id=? AND event_kind='reserved'",
            (reservation_id, str(owner_user_id), str(turn_id)),
        ).fetchone()
        started = connection.execute(
            "SELECT 1 FROM p2_v3_charge_events WHERE reservation_id=? AND owner_user_id=? AND turn_id=? AND event_kind='dispatch_started'",
            (reservation_id, str(owner_user_id), str(turn_id)),
        ).fetchone()
        terminal = connection.execute(
            "SELECT 1 FROM p2_v3_charge_events WHERE reservation_id=? AND owner_user_id=? AND turn_id=? AND event_kind IN ('settled','known_no_dispatch','unknown')",
            (reservation_id, str(owner_user_id), str(turn_id)),
        ).fetchone()
        if (
            reserved is None or reserved["stage"] != "backend_processing" or started is None
            or terminal is not None or int(reserved["active_limit_us"]) < actual_us
            or int(reserved["backend_limit_us"]) < actual_us
        ):
            raise P2V3StoreConflict("metadata acceptance processing reservation is unavailable or exceeded")
        self._insert_p2_v3_charge_event(
            connection, reserved, event_kind="settled", now=now,
            actual_active_us=actual_us, actual_backend_us=actual_us,
            actual_response_bytes=0,
        )
        changed = connection.execute(
            """UPDATE p2_v3_turns SET active_reserved_us=active_reserved_us-?,
                   active_used_us=active_used_us+?,backend_reserved_us=backend_reserved_us-?,
                   backend_used_us=backend_used_us+?,revision=revision+1,updated_at=?
               WHERE turn_id=? AND owner_user_id=? AND revision=?
                 AND active_reserved_us>=? AND backend_reserved_us>=?""",
            (
                int(reserved["active_limit_us"]), actual_us,
                int(reserved["backend_limit_us"]), actual_us, _stamp(now),
                str(turn_id), str(owner_user_id), snapshot.revision,
                int(reserved["active_limit_us"]), int(reserved["backend_limit_us"]),
            ),
        ).rowcount
        if changed != 1:
            raise P2V3StoreConflict("metadata acceptance processing settlement lost Store CAS")

    def accept_p2_v3_admission_metadata(
        self,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        *,
        binding: Any,
        projection: Any,
        now: Optional[datetime] = None,
    ) -> P2V3AcceptedAdmissionMetadata:
        """Independently reparse and atomically accept scoped bootstrap metadata.

        The input projection is only a transient capture bundle. This method
        re-hashes and decodes every exact response body, checks the fixed GET
        plan and Store cost/capture chain, rebuilds the scope projection with
        the Store-issued ref registry, and persists receipts, locators and
        field proofs in one IMMEDIATE transaction. The registry is activated
        only after commit succeeds.
        """
        from . import p2_source_codec_v3 as codec3
        from .p2_event_contracts_v3 import P2V3PrivateMetadataProofBinding

        self._require_started()
        if (
            not isinstance(binding, codec3.AdmissionOnlyBinding)
            or not isinstance(projection, codec3.P2V3ScopeMetadataProjection)
            or type(owner_user_id) is not uuid.UUID or type(turn_id) is not uuid.UUID
        ):
            raise P2V3StoreConflict("metadata acceptance requires a scoped Store admission projection")
        registry = binding.reference_registry
        if not isinstance(registry, P2V3RequestReferenceRegistry):
            raise P2V3StoreConflict("metadata acceptance requires the Store-issued request registry")
        registry._assert_store_issued(
            self, identity=binding.identity, admission_id=binding.admission_id,
            claim_token=binding.claim_token,
        )
        if (
            registry is not projection.reference_registry
            or binding.identity.owner_user_id != owner_user_id
            or binding.identity.turn_id != turn_id
                or registry.principal_user_id != owner_user_id
        ):
            raise P2V3StoreConflict("metadata projection is outside its Store admission identity")

        instant = _now(now)
        with self._connection() as connection:
            _, initial, _ = self._p2_v3_current_claim(
                connection, owner_user_id, turn_id, claim_token=binding.claim_token, now=instant,
            )
            overrun_active, overrun_backend, _ = self._p2_v3_overrun_totals(
                connection, str(owner_user_id), str(turn_id),
            )
            active_remaining = P2_V3_MAX_ACTIVE_US - initial.active_used_us - initial.active_reserved_us - overrun_active
            backend_remaining = P2_V3_MAX_BACKEND_US - initial.backend_used_us - initial.backend_reserved_us - overrun_backend
        processing_limit = P2_V3_METADATA_ACCEPTANCE_CAP_US
        if active_remaining < processing_limit or backend_remaining < processing_limit:
            raise P2V3StoreConflict("metadata acceptance lacks its fixed processing budget")
        processing_id = self.reserve_p2_v3_stage(
            owner_user_id, turn_id, claim_token=binding.claim_token,
            stage="backend_processing", active_limit_us=processing_limit,
            backend_limit_us=processing_limit, now=instant,
        )
        dispatched = False
        started_ns = time.monotonic_ns()
        try:
            self.mark_p2_v3_dispatch_started(
                owner_user_id, turn_id, processing_id, claim_token=binding.claim_token, now=instant,
            )
            # Fault boundary models a caller observing an exception after the
            # irreversible marker COMMIT. Cleanup must consult the durable
            # marker rather than treating the local flag as proof of no work.
            self._fault("p2_v3.metadata_acceptance.dispatch.after_commit")
            dispatched = True
            phase_a = self._accept_p2_v3_admission_metadata_transaction(
                owner_user_id, turn_id, binding=binding, projection=projection,
                processing_reservation_id=processing_id, now=_now(None),
            )
            self._fault("p2_v3.metadata_acceptance.a.after_commit")
            phase_b = self._finish_p2_v3_metadata_acceptance(
                owner_user_id, turn_id, binding=binding,
                acceptance_id=phase_a["acceptance_id"],
                actual_us=max(0, (time.monotonic_ns() - started_ns) // 1000),
                force_unknown=False, now=_now(None),
            )
            self._fault("p2_v3.metadata_acceptance.b.after_commit")
            if not phase_b["finalized"]:
                raise P2V3StoreConflict("metadata processing could not be finalized under the current claim")

            c_elapsed = max(0, (time.monotonic_ns() - started_ns) // 1000)
            c_outcome = "overrun" if c_elapsed > processing_limit else "within_cap"
            phase_c = self._append_p2_v3_metadata_observation(
                owner_user_id, turn_id, acceptance_id=phase_a["acceptance_id"],
                outcome=c_outcome, actual_us=c_elapsed, now=_now(None),
            )
            self._fault("p2_v3.metadata_acceptance.c.after_commit")

            # C's commit duration and the independent current-worker recheck
            # are included in the final monotonic fence. A permit is never
            # restored from the durable finalized event.
            still_current = self._p2_v3_metadata_claim_is_current(
                owner_user_id, turn_id, binding=binding, now=_now(None),
            )
            # The final claim/pin read is part of the processing interval. Take
            # the monotonic sample after it returns so a slow recheck cannot
            # publish a permit beyond the fixed cap.
            final_elapsed = max(0, (time.monotonic_ns() - started_ns) // 1000)
            if final_elapsed > processing_limit:
                self._append_p2_v3_metadata_observation(
                    owner_user_id, turn_id, acceptance_id=phase_a["acceptance_id"],
                    outcome="overrun", actual_us=final_elapsed, now=_now(None),
                )
                raise P2V3StoreConflict("metadata acceptance exceeded its processing cap after commit")
            if not still_current:
                self._append_p2_v3_metadata_observation(
                    owner_user_id, turn_id, acceptance_id=phase_a["acceptance_id"],
                    outcome="unknown", actual_us=final_elapsed, now=_now(None),
                )
                raise P2V3StoreConflict("metadata acceptance lost its claim before publication")
            if phase_c["outcome"] != "within_cap":
                raise P2V3StoreConflict("metadata acceptance has no within-cap postcommit observation")

            permit = _P2V3MetadataPublicationPermit(
                store=self, registry_nonce=registry._permit_nonce, identity=binding.identity,
                admission_id=binding.admission_id, acceptance_id=phase_a["acceptance_id"],
                seal=_P2_V3_METADATA_PERMIT_SEAL,
            )
            result = P2V3AcceptedAdmissionMetadata(
                projection=phase_a["projection"], metadata_proofs=phase_a["metadata_proofs"],
                source_receipt_ids=tuple(phase_a["receipt_ids"]),
            )
            try:
                registry._record_metadata_acceptance(
                    receipt_by_capture_ref=phase_a["receipt_by_capture_ref"],
                    proofs=phase_a["metadata_proofs"],
                    projection=phase_a["projection"],
                    snapshot_digest=phase_a["projection"].snapshot_digest,
                    public_scope_digest=phase_a["public_scope_digest"], permit=permit,
                )
            except BaseException:
                registry._revoke_metadata_acceptance(
                    identity=binding.identity, admission_id=binding.admission_id,
                )
                raise
            return result
        except BaseException as original:
            registry._revoke_metadata_acceptance(identity=binding.identity, admission_id=binding.admission_id)
            try:
                self._fail_closed_p2_v3_metadata_acceptance(
                    owner_user_id, turn_id, binding=binding,
                    processing_reservation_id=processing_id, started_ns=started_ns,
                    dispatched=dispatched,
                )
            except BaseException as cleanup_error:
                if not isinstance(original, Exception):
                    raise original
                raise P2V3StoreConflict(
                    "metadata acceptance did not obtain a publication permit and cost finalization is uncertain"
                ) from cleanup_error
            raise

    def _finish_p2_v3_metadata_acceptance(
        self,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        *,
        binding: Any,
        acceptance_id: str,
        actual_us: int,
        force_unknown: bool,
        now: datetime,
    ) -> dict[str, Any]:
        """B: commit one conservative-cap charge and its terminal V005 event."""
        actual_us = _strict_nonnegative_int(actual_us, "actual_us")
        with self._transaction() as connection:
            batch = connection.execute(
                "SELECT * FROM p2_v3_metadata_acceptance_batches WHERE acceptance_id=? AND owner_user_id=? AND turn_id=?",
                (acceptance_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            if batch is None:
                raise P2V3StoreNotFound("metadata acceptance batch is unavailable to this owner and Turn")
            events = connection.execute(
                "SELECT * FROM p2_v3_metadata_acceptance_events WHERE acceptance_id=? ORDER BY event_seq",
                (acceptance_id,),
            ).fetchall()
            if len(events) != 1 or events[0]["event_seq"] != 1 or events[0]["event_kind"] != "proof_committed":
                raise P2V3StoreConflict("metadata batch is not awaiting its one terminal event")
            reserved = connection.execute(
                "SELECT * FROM p2_v3_charge_events WHERE reservation_id=? AND owner_user_id=? AND turn_id=? AND event_kind='reserved'",
                (batch["processing_reservation_id"], str(owner_user_id), str(turn_id)),
            ).fetchone()
            started = connection.execute(
                "SELECT 1 FROM p2_v3_charge_events WHERE reservation_id=? AND owner_user_id=? AND turn_id=? AND event_kind='dispatch_started'",
                (batch["processing_reservation_id"], str(owner_user_id), str(turn_id)),
            ).fetchone()
            if reserved is None or started is None or int(reserved["active_limit_us"]) != P2_V3_METADATA_ACCEPTANCE_CAP_US or int(reserved["backend_limit_us"]) != P2_V3_METADATA_ACCEPTANCE_CAP_US:
                raise P2V3StoreConflict("metadata processing reservation is missing or differs from the fixed cap")
            turn_row = connection.execute(
                "SELECT * FROM p2_v3_turns WHERE owner_user_id=? AND turn_id=?",
                (str(owner_user_id), str(turn_id)),
            ).fetchone()
            if turn_row is None:
                raise P2V3StoreNotFound("metadata acceptance Turn is unavailable")
            snapshot = self._p2_v3_snapshot(turn_row)
            fresh = False
            if not force_unknown:
                try:
                    candidate, checked, _ = self._p2_v3_current_claim(
                        connection, owner_user_id, turn_id,
                        claim_token=binding.claim_token, now=now,
                    )
                    fresh = (
                        checked.owner_user_id == str(owner_user_id)
                        and checked.turn_id == str(turn_id)
                        and checked.generation == batch["generation"]
                        and checked.input_seq == batch["input_seq"]
                        and checked.input_digest == batch["input_digest"]
                        and checked.claim_epoch == batch["claim_epoch"]
                        and checked.authority_epoch == batch["authority_epoch"]
                        and checked.context_revision == batch["context_revision"]
                        and candidate["lifecycle"] == "active"
                    )
                    if fresh:
                        snapshot = checked
                except (P2V3StoreConflict, P2V3StoreNotFound, P2V3UnsupportedProfile):
                    fresh = False
            cap = P2_V3_METADATA_ACCEPTANCE_CAP_US
            finalized = bool(fresh and actual_us <= cap and not force_unknown)
            terminal_kind = "settled" if finalized else "unknown"
            overrun = max(0, actual_us - cap)
            terminal_event_id = self._insert_p2_v3_charge_event(
                connection, reserved, event_kind=terminal_kind, now=now,
                actual_active_us=cap, actual_backend_us=cap, actual_response_bytes=0,
                overrun_active_us=overrun, overrun_backend_us=overrun,
            )
            changed = connection.execute(
                """UPDATE p2_v3_turns SET active_reserved_us=active_reserved_us-?,
                       active_used_us=active_used_us+?,backend_reserved_us=backend_reserved_us-?,
                       backend_used_us=backend_used_us+?,historical_unknown_consumption=MAX(historical_unknown_consumption,?),
                       revision=revision+1,updated_at=?
                   WHERE turn_id=? AND owner_user_id=? AND revision=?
                     AND active_reserved_us>=? AND backend_reserved_us>=?""",
                (
                    cap, cap, cap, cap, int(not finalized), _stamp(now),
                    str(turn_id), str(owner_user_id), snapshot.revision, cap, cap,
                ),
            ).rowcount
            if changed != 1:
                raise P2V3StoreConflict("metadata terminal charge lost the Turn budget CAS")
            connection.execute(
                """INSERT INTO p2_v3_metadata_acceptance_events (
                       acceptance_id,event_seq,event_kind,owner_user_id,turn_id,reservation_id,
                       terminal_event_id,terminal_charge_kind,cost_basis,measured_active_us,
                       measured_backend_us,charged_active_us,charged_backend_us,observation_outcome,
                       overrun_active_us,overrun_backend_us,occurred_at
                   ) VALUES (?,2,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    acceptance_id, "finalized" if finalized else "unknown", str(owner_user_id), str(turn_id),
                    batch["processing_reservation_id"], terminal_event_id, terminal_kind,
                    "conservative_cap" if finalized else "unknown_cap",
                    actual_us if finalized else None, actual_us if finalized else None,
                    cap, cap, None, overrun, overrun, _stamp(now),
                ),
            )
            self._fault("p2_v3.metadata_acceptance.b.before_commit")
            return {"acceptance_id": acceptance_id, "finalized": finalized, "terminal_kind": terminal_kind}

    def _append_p2_v3_metadata_observation(
        self,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        *,
        acceptance_id: str,
        outcome: str,
        actual_us: int,
        now: datetime,
    ) -> dict[str, Any]:
        """C: append one postcommit measurement without reviving unknown/overrun work."""
        if outcome not in {"within_cap", "unknown", "overrun"}:
            raise ValueError("metadata observation outcome is not allowlisted")
        actual_us = _strict_nonnegative_int(actual_us, "actual_us")
        with self._transaction() as connection:
            batch = connection.execute(
                "SELECT * FROM p2_v3_metadata_acceptance_batches WHERE acceptance_id=? AND owner_user_id=? AND turn_id=?",
                (acceptance_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            if batch is None:
                raise P2V3StoreNotFound("metadata acceptance batch is unavailable to this owner and Turn")
            terminal = connection.execute(
                "SELECT * FROM p2_v3_metadata_acceptance_events WHERE acceptance_id=? AND event_seq=2",
                (acceptance_id,),
            ).fetchone()
            reserved = connection.execute(
                "SELECT * FROM p2_v3_charge_events WHERE reservation_id=? AND owner_user_id=? AND turn_id=? AND event_kind='reserved'",
                (batch["processing_reservation_id"], str(owner_user_id), str(turn_id)),
            ).fetchone()
            charge = connection.execute(
                "SELECT * FROM p2_v3_charge_events WHERE reservation_id=? AND owner_user_id=? AND turn_id=? AND event_kind=?",
                (batch["processing_reservation_id"], str(owner_user_id), str(turn_id), terminal["terminal_charge_kind"] if terminal else ""),
            ).fetchone()
            previous = connection.execute(
                "SELECT * FROM p2_v3_metadata_acceptance_events WHERE acceptance_id=? AND event_kind='postcommit_observation' ORDER BY event_seq",
                (acceptance_id,),
            ).fetchall()
            if terminal is None or reserved is None or charge is None:
                raise P2V3StoreConflict("postcommit observation lacks the accepted terminal charge")
            previous_active = max(
                [int(terminal["measured_active_us"] or 0)]
                + [int(row["measured_active_us"] or 0) for row in previous]
            )
            previous_backend = max(
                [int(terminal["measured_backend_us"] or 0)]
                + [int(row["measured_backend_us"] or 0) for row in previous]
            )
            if actual_us < max(previous_active, previous_backend):
                raise P2V3StoreConflict("postcommit observation regressed the measured processing prefix")
            cap = int(reserved["active_limit_us"])
            if actual_us > cap and outcome != "overrun":
                raise P2V3StoreConflict("postcommit processing exceeded cap without an overrun observation")
            if actual_us <= cap and outcome == "overrun":
                raise P2V3StoreConflict("within-cap processing cannot be recorded as an overrun")
            if terminal["event_kind"] == "unknown" and outcome == "within_cap":
                raise P2V3StoreConflict("unknown metadata acceptance cannot be revived")
            prior_active_overrun = max(
                [int(terminal["overrun_active_us"] or 0)]
                + [int(row["overrun_active_us"] or 0) for row in previous]
            )
            prior_backend_overrun = max(
                [int(terminal["overrun_backend_us"] or 0)]
                + [int(row["overrun_backend_us"] or 0) for row in previous]
            )
            overrun_active = max(prior_active_overrun, max(0, actual_us - int(reserved["active_limit_us"])))
            overrun_backend = max(prior_backend_overrun, max(0, actual_us - int(reserved["backend_limit_us"])))
            terminal_charge_kind = terminal["terminal_charge_kind"]
            event_seq = 3 + len(previous)
            connection.execute(
                """INSERT INTO p2_v3_metadata_acceptance_events (
                       acceptance_id,event_seq,event_kind,owner_user_id,turn_id,reservation_id,
                       terminal_event_id,terminal_charge_kind,cost_basis,measured_active_us,
                       measured_backend_us,charged_active_us,charged_backend_us,observation_outcome,
                       overrun_active_us,overrun_backend_us,occurred_at
                   ) VALUES (?,?, 'postcommit_observation', ?,?,?,?, ?,NULL,?,?,NULL,NULL,?,?,?,?)""",
                (
                    acceptance_id, event_seq, str(owner_user_id), str(turn_id),
                    batch["processing_reservation_id"], terminal["terminal_event_id"], terminal_charge_kind,
                    actual_us, actual_us, outcome, overrun_active, overrun_backend, _stamp(now),
                ),
            )
            self._fault("p2_v3.metadata_acceptance.c.before_commit")
            return {"acceptance_id": acceptance_id, "event_seq": event_seq, "outcome": outcome}

    def _p2_v3_metadata_claim_is_current(
        self, owner_user_id: uuid.UUID, turn_id: uuid.UUID, *, binding: Any, now: datetime,
    ) -> bool:
        with self._connection() as connection:
            try:
                candidate, current, _ = self._p2_v3_current_claim(
                    connection, owner_user_id, turn_id, claim_token=binding.claim_token, now=now,
                )
            except (P2V3StoreConflict, P2V3StoreNotFound, P2V3UnsupportedProfile):
                return False
            identity = binding.identity
            return (
                current.generation == identity.generation
                and current.input_seq == identity.input_seq
                and current.input_digest == identity.input_digest
                and current.claim_epoch == identity.claim_epoch
                and current.authority_epoch == identity.authority_epoch
                and current.context_revision == identity.context_revision
                and candidate["lifecycle"] == "active"
            )

    def _fail_closed_p2_v3_metadata_acceptance(
        self,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        *,
        binding: Any,
        processing_reservation_id: str,
        started_ns: int,
        dispatched: bool,
    ) -> None:
        """Settle cost once and make an unpermitted committed batch non-publishable."""
        elapsed = max(0, (time.monotonic_ns() - started_ns) // 1000)
        with self._connection() as connection:
            batch = connection.execute(
                "SELECT acceptance_id FROM p2_v3_metadata_acceptance_batches WHERE processing_reservation_id=? AND owner_user_id=? AND turn_id=?",
                (processing_reservation_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            terminal = connection.execute(
                "SELECT event_kind FROM p2_v3_charge_events WHERE reservation_id=? AND owner_user_id=? AND turn_id=? AND event_kind IN('settled','known_no_dispatch','unknown')",
                (processing_reservation_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            batch_id = str(batch["acceptance_id"]) if batch is not None else None
        if batch_id is None:
            if terminal is None:
                # The dispatch marker is irreversible even if its caller saw
                # an exception after COMMIT and never set the local flag.
                # Consult the durable ledger before choosing the settlement.
                with self._connection() as connection:
                    dispatch_started = connection.execute(
                        "SELECT 1 FROM p2_v3_charge_events WHERE reservation_id=? AND owner_user_id=? AND turn_id=? AND event_kind='dispatch_started'",
                        (processing_reservation_id, str(owner_user_id), str(turn_id)),
                    ).fetchone() is not None
                effective_dispatched = dispatched or dispatch_started
                self.settle_p2_v3_stage(
                    owner_user_id, turn_id, processing_reservation_id,
                    outcome="unknown" if effective_dispatched else "known_no_dispatch",
                    actual_active_us=elapsed if effective_dispatched else 0,
                    actual_backend_us=elapsed if effective_dispatched else 0,
                    actual_response_bytes=0, now=_now(None),
                )
            return
        with self._connection() as connection:
            terminal_event = connection.execute(
                "SELECT * FROM p2_v3_metadata_acceptance_events WHERE acceptance_id=? AND event_seq=2",
                (batch_id,),
            ).fetchone()
            last_observation = connection.execute(
                "SELECT * FROM p2_v3_metadata_acceptance_events WHERE acceptance_id=? AND event_kind='postcommit_observation' ORDER BY event_seq DESC LIMIT 1",
                (batch_id,),
            ).fetchone()
        if terminal_event is None:
            self._finish_p2_v3_metadata_acceptance(
                owner_user_id, turn_id, binding=binding, acceptance_id=batch_id,
                actual_us=elapsed, force_unknown=True, now=_now(None),
            )
            return
        if terminal_event["event_kind"] == "finalized" and (
            last_observation is None or last_observation["observation_outcome"] == "within_cap"
        ):
            outcome = "overrun" if elapsed > P2_V3_METADATA_ACCEPTANCE_CAP_US else "unknown"
            self._append_p2_v3_metadata_observation(
                owner_user_id, turn_id, acceptance_id=batch_id,
                outcome=outcome, actual_us=elapsed, now=_now(None),
            )

    def _accept_p2_v3_admission_metadata_transaction(
        self,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        *,
        binding: Any,
        projection: Any,
        processing_reservation_id: str,
        now: datetime,
    ) -> dict[str, Any]:
        from . import p2_source_codec_v3 as codec3
        from .p2_event_contracts_v3 import P2V3PrivateMetadataProofBinding

        registry = binding.reference_registry
        identity = binding.identity
        expected_tables = (
            "activities", "activity_members", "ledger_units", "participants",
            "sub_activity_participants", "participant_claims",
        )
        source_role = {
            "activities": "activity", "activity_members": "membership",
            "ledger_units": "ledger_unit", "participants": "participant",
            "sub_activity_participants": "ledger_unit", "participant_claims": "actor",
        }

        def same_public(left: Any, right: Any) -> bool:
            if left is None or right is None:
                return left is right
            return left.model_dump(mode="json", exclude_none=False) == right.model_dump(mode="json", exclude_none=False)

        with self._transaction() as connection:
            _, current, _ = self._p2_v3_current_claim(
                connection, owner_user_id, turn_id, claim_token=binding.claim_token, now=now,
            )
            identity_values = (
                current.owner_user_id, current.turn_id, current.generation, current.input_seq,
                current.input_digest, current.claim_epoch, current.authority_epoch, current.context_revision,
            )
            expected_identity_values = (
                str(identity.owner_user_id), str(identity.turn_id), identity.generation, identity.input_seq,
                identity.input_digest, identity.claim_epoch, identity.authority_epoch, identity.context_revision,
            )
            if identity_values != expected_identity_values:
                raise P2V3StoreConflict("admission metadata belongs to a stale owner/Turn/input/claim")
            turn_row = connection.execute(
                "SELECT * FROM p2_v3_turns WHERE owner_user_id=? AND turn_id=?",
                (str(owner_user_id), str(turn_id)),
            ).fetchone()
            if turn_row is None:
                raise P2V3StoreNotFound("metadata admission Turn is unavailable")
            self._require_current_p2_v3_pin(connection, turn_row)
            admission_row = connection.execute(
                "SELECT * FROM p2_v3_source_admissions WHERE admission_id=? AND owner_user_id=? AND turn_id=?",
                (binding.admission_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            if admission_row is None:
                raise P2V3StoreNotFound("source admission is unavailable to this owner and Turn")
            if any(admission_row[key] != expected for key, expected in (
                ("generation", current.generation), ("input_seq", current.input_seq),
                ("input_digest", current.input_digest), ("claim_epoch", current.claim_epoch),
                ("authority_epoch", current.authority_epoch),
                ("context_revision", current.context_revision),
                ("generation", identity.generation), ("input_seq", identity.input_seq),
                ("input_digest", identity.input_digest), ("claim_epoch", identity.claim_epoch),
                ("authority_epoch", identity.authority_epoch),
                ("context_revision", identity.context_revision),
            )):
                raise P2V3StoreConflict("source admission belongs to a stale Turn input or claim epoch")
            private_scope = json.loads(admission_row["requested_scope_json"])
            private_scope, private_scope_digest = _canonical_json(
                _private_scope_descriptor(private_scope), max_bytes=8192,
            )
            private_scope_value = json.loads(private_scope)
            if (
                private_scope_digest != admission_row["requested_scope_digest"]
                or registry._requested_scope != private_scope_value
                or registry._requested_scope_digest != private_scope_digest
                or registry._public_scope_digest != admission_row["public_scope_digest"]
            ):
                raise P2V3StoreConflict("metadata source scope differs from the immutable Store admission")
            if private_scope_value.get("scope_kind") not in {"activity", "ledger_unit"}:
                raise P2V3StoreConflict("source metadata acceptance requires a concrete verified Activity scope")
            activity_id = uuid.UUID(private_scope_value["activity_id"])
            ledger_unit_id = (
                uuid.UUID(private_scope_value["ledger_unit_id"])
                if private_scope_value["scope_kind"] == "ledger_unit" else None
            )
            activity_ref = registry.bind_entity("activity", activity_id, activity_id=activity_id)
            if registry.resolve_activity_ref(activity_ref) != activity_id:
                raise P2V3StoreConflict("prospective Activity ref does not match the private admission scope")
            scope_kind = private_scope_value["scope_kind"]
            scope_ref = activity_ref
            if ledger_unit_id is not None:
                scope_ref = registry.bind_entity(
                    "ledger_unit", ledger_unit_id, activity_id=activity_id, ledger_unit_id=ledger_unit_id,
                )
                if registry.binding_for_ref(scope_ref) != ("ledger_unit", ledger_unit_id, activity_id, ledger_unit_id):
                    raise P2V3StoreConflict("prospective child ref does not match the private admission scope")

            supplied_snapshot = projection.snapshot
            supplied_pages = supplied_snapshot.witnesses
            if (
                not supplied_pages or len(supplied_pages) > 24
                or tuple(projection.captures) != tuple(page.witness for page in supplied_pages)
                or supplied_snapshot.activity_id != activity_id
                or supplied_snapshot.activity_ref != activity_ref
                or supplied_snapshot.scope_kind != scope_kind
                or supplied_snapshot.ledger_unit_id != ledger_unit_id
                or supplied_snapshot.scope_ref != scope_ref
            ):
                raise P2V3StoreConflict("metadata projection does not match its immutable admitted scope and capture list")

            expected_public_scope = P2Scope(
                scope_kind=scope_kind, scope_ref=scope_ref,
                activity_ref=activity_ref,
                ledger_unit_ref=scope_ref if ledger_unit_id is not None else None,
            )
            public_scope_digest = _canonical_json(
                expected_public_scope.model_dump(mode="json", exclude_none=False), max_bytes=2048,
            )[1]
            if public_scope_digest != admission_row["public_scope_digest"]:
                raise P2V3StoreConflict("opaque public scope digest differs from the precommitted admission")

            expected_order = {table: index for index, table in enumerate(expected_tables)}
            current_origin: tuple[str, str] | None = None
            pages_by_table: dict[str, list[Any]] = {table: [] for table in expected_tables}
            parsed_by_table: dict[str, list[Mapping[str, Any]]] = {table: [] for table in expected_tables}
            expected_offset_by_table = {table: 0 for table in expected_tables}
            receipts: list[dict[str, Any]] = []
            seen_group = -1
            closed_tables: set[str] = set()
            for page in supplied_pages:
                table = page.table
                if table not in expected_order or not isinstance(page.witness, codec3.CapturedPageWitness):
                    raise P2V3StoreConflict("metadata capture contains a non-allowlisted source table")
                group = expected_order[table]
                if group < seen_group or (table in closed_tables and pages_by_table[table]):
                    raise P2V3StoreConflict("metadata source pages are not in the fixed table/range sequence")
                if seen_group >= 0 and group != seen_group:
                    closed_tables.add(expected_tables[seen_group])
                seen_group = group
                witness = page.witness
                if (
                    witness.owner_user_id != owner_user_id or witness.turn_id != turn_id
                    or witness.generation != current.generation or witness.input_seq != current.input_seq
                    or witness.input_digest != current.input_digest or witness.claim_epoch != current.claim_epoch
                    or witness.authority_epoch != current.authority_epoch
                    or witness.context_revision != current.context_revision
                    or witness.binding_kind != "admission" or witness.admission_id != binding.admission_id
                    or witness.logical_query_id is not None or witness.query_attempt_id is not None
                    or witness.page_index is not None or witness.source_role != source_role[table]
                    or witness.reservation_id != page.reservation_id or witness.capture_id == ""
                    or witness.request_sha256 != page.request_sha256
                    or witness.response_sha256 != page.raw_body_sha256
                    or type(page.raw_body) is not bytes or len(page.raw_body) > P2_V3_MAX_GET_RESPONSE_BYTES
                    or witness.response_bytes != len(page.raw_body)
                    or _digest(page.raw_body) != witness.response_sha256
                    or witness.http_status not in (200, 206) or page.status != witness.http_status
                    or page.content_range != (witness.content_range or "")
                    or type(witness.elapsed_us) is not int or witness.elapsed_us < 0
                    or witness.observed_at.tzinfo is None or witness.observed_at.utcoffset() is None
                ):
                    raise P2V3StoreConflict("captured metadata witness is stale or differs from its raw response")
                offset = expected_offset_by_table[table]
                parts = urlsplit(page.request_url)
                if registry._configured_source_origin is None:
                    raise P2V3StoreConflict("metadata source origin was not pinned by the configured adapter")
                if (
                    parts.scheme != "https" or not parts.hostname or parts.username is not None
                    or parts.password is not None or parts.fragment or parts.query == ""
                    or parts.path != f"/rest/v1/{table}" or len(page.request_url) > 12_000
                ):
                    raise P2V3StoreConflict("metadata GET is outside the fixed HTTPS PostgREST path")
                origin = (parts.scheme, parts.netloc.lower())
                if origin != registry._configured_source_origin:
                    raise P2V3StoreConflict("metadata GET origin differs from the configured source origin")
                if current_origin is not None and current_origin != origin:
                    raise P2V3StoreConflict("metadata captures do not share one configured source origin")
                current_origin = origin
                expected_query = urlencode(_p2_v3_metadata_request_pairs(
                    table, activity_id, registry.principal_user_id, offset,
                ))
                request_digest = _digest((parts.path + "?" + parts.query).encode("utf-8"))
                if parts.query != expected_query or request_digest != witness.request_sha256:
                    raise P2V3StoreConflict("metadata GET query differs from the fixed owner/scope request plan")
                try:
                    raw_rows = codec3.parse_source_rows(page.raw_body, table)
                    parsed_range = codec3.parse_content_range(
                        witness.content_range, expected_offset=offset,
                        row_count=len(raw_rows), status=witness.http_status,
                    )
                except Exception as exc:
                    raise P2V3StoreConflict("metadata raw response failed independent strict decoding") from exc
                if (
                    codec3.stable_digest([dict(row) for row in raw_rows])
                    != codec3.stable_digest([dict(row) for row in page.rows])
                    or parsed_range != page.range or page.offset != offset
                ):
                    raise P2V3StoreConflict("metadata raw rows/range differ from the caller projection")
                page.witness.observed_at.astimezone(timezone.utc)
                pages_by_table[table].append(page)
                parsed_by_table[table].extend(raw_rows)
                expected_offset_by_table[table] += len(raw_rows)
                receipts.append({
                    "page": page, "rows": raw_rows, "table": table, "offset": offset,
                    "table_ordinal": len(pages_by_table[table]) - 1,
                })

            if tuple(table for table in expected_tables if pages_by_table[table]) != expected_tables:
                raise P2V3StoreConflict("all six complete scope/member/label source tables are required")
            source_tables: dict[str, Any] = {}
            all_pages: list[Any] = []
            for table in expected_tables:
                pages = pages_by_table[table]
                if not pages or len(pages) > codec3.MAX_PAGES_PER_TABLE:
                    raise P2V3StoreConflict("metadata source table has no complete bounded page chain")
                try:
                    source = codec3.source_table(parsed_by_table[table], pages, table=table)
                except Exception as exc:
                    raise P2V3StoreConflict("metadata source table failed independent range/uniqueness validation") from exc
                if not source.complete or not source.range_contiguous or not source.unique_items_verified:
                    raise P2V3StoreConflict("metadata source table is partial or has unstable totals")
                source_tables[table] = source
                all_pages.extend(pages)
            if len(all_pages) != len(receipts):
                raise P2V3StoreConflict("metadata capture chain is incomplete")

            admission_chain = connection.execute(
                """SELECT r.*,c.event_kind AS charge_event_kind,c.stage,t.event_kind AS terminal_kind,
                          t.actual_active_us,t.actual_backend_us,t.actual_response_bytes,t.raw_body_sha256 AS settled_body_sha
                   FROM p2_v3_capture_chain_reservations AS r
                   JOIN p2_v3_charge_events AS c ON c.reservation_id=r.reservation_id AND c.event_kind='reserved'
                   LEFT JOIN p2_v3_charge_events AS t ON t.reservation_id=r.reservation_id
                        AND t.event_kind IN ('settled','known_no_dispatch','unknown')
                   WHERE r.owner_user_id=? AND r.turn_id=? AND r.capture_chain_kind='admission'
                     AND r.capture_chain_id=? ORDER BY r.chain_sequence""",
                (str(owner_user_id), str(turn_id), binding.admission_id),
            ).fetchall()
            expected_reservations = [entry["page"].reservation_id for entry in receipts]
            if (
                [row["reservation_id"] for row in admission_chain] != expected_reservations
                or any(row["terminal_kind"] != "settled" or row["stage"] != "backend_get" for row in admission_chain)
            ):
                raise P2V3StoreConflict("metadata proof requires the exact complete settled admission capture chain")

            pin_ok, pin = self._verify_p2_v3_execution_pin_rows(connection, turn_row)
            if not pin_ok or pin is None:
                raise P2V3UnsupportedProfile("metadata proof requires the current immutable execution pin")
            if connection.execute(
                "SELECT 1 FROM p2_v3_admission_source_receipts WHERE admission_id=? LIMIT 1",
                (binding.admission_id,),
            ).fetchone() is not None:
                raise P2V3StoreConflict("admission metadata receipts are immutable and already accepted")

            # Rebuild the snapshot exclusively from strict raw-byte decodes.
            activity_rows = source_tables["activities"].rows
            if len(activity_rows) != 1 or uuid.UUID(activity_rows[0]["id"]) != activity_id:
                raise P2V3StoreConflict("requested Activity is not uniquely visible in the complete source result")
            if ledger_unit_id is not None:
                requested_units = [row for row in source_tables["ledger_units"].rows if row["id"] == str(ledger_unit_id)]
                if len(requested_units) != 1 or requested_units[0]["is_deleted"] is not False or requested_units[0]["type"] != "sub_activity":
                    raise P2V3StoreConflict("requested ledger unit is not an active same-Activity child scope")
            rebuilt_snapshot = codec3.SourceSnapshot(
                activity_id=activity_id, activity_ref=activity_ref,
                activity=activity_rows[0],
                ledger_units=source_tables["ledger_units"].rows,
                participants=source_tables["participants"].rows,
                child_rows=source_tables["sub_activity_participants"].rows,
                claims=source_tables["participant_claims"].rows,
                membership_rows=source_tables["activity_members"].rows,
                scope_ref=scope_ref, scope_kind=scope_kind,
                ledger_unit_id=ledger_unit_id, witnesses=tuple(all_pages),
            )
            try:
                rebuilt_projection = codec3.project_scope_metadata(
                    rebuilt_snapshot, registry.principal_user_id,
                    binder=registry, identity=identity,
                )
            except Exception as exc:
                raise P2V3StoreConflict("independently decoded source does not prove membership and scope") from exc
            if (
                rebuilt_projection.snapshot_digest != projection.snapshot_digest
                or rebuilt_projection.captures != projection.captures
                or not same_public(rebuilt_projection.current_actor, projection.current_actor)
                or tuple(item.model_dump(mode="json", exclude_none=False) for item in rebuilt_projection.source_labels)
                    != tuple(item.model_dump(mode="json", exclude_none=False) for item in projection.source_labels)
            ):
                raise P2V3StoreConflict("caller projection differs from Store-rebuilt source metadata")

            page_by_capture = {page.witness.capture_id: page for page in all_pages}
            receipt_id_by_capture: dict[str, str] = {}
            for ordinal, entry in enumerate(receipts):
                page, table = entry["page"], entry["table"]
                witness = page.witness
                stored_capture = connection.execute(
                    "SELECT * FROM p2_v3_wire_captures WHERE capture_id=? AND owner_user_id=? AND turn_id=?",
                    (witness.capture_id, str(owner_user_id), str(turn_id)),
                ).fetchone()
                chain_row = admission_chain[ordinal]
                reserved = connection.execute(
                    "SELECT * FROM p2_v3_charge_events WHERE reservation_id=? AND owner_user_id=? AND turn_id=? AND event_kind='reserved'",
                    (witness.reservation_id, str(owner_user_id), str(turn_id)),
                ).fetchone()
                terminal = connection.execute(
                    "SELECT * FROM p2_v3_charge_events WHERE reservation_id=? AND owner_user_id=? AND turn_id=? AND event_kind='settled'",
                    (witness.reservation_id, str(owner_user_id), str(turn_id)),
                ).fetchone()
                if stored_capture is None or reserved is None or terminal is None:
                    raise P2V3StoreConflict("metadata capture has no Store-settled wire and budget record")
                if (
                    stored_capture["capture_state"] != "cost_only"
                    or stored_capture["reservation_id"] != witness.reservation_id
                    or stored_capture["admission_id"] != binding.admission_id
                    or stored_capture["logical_query_id"] is not None
                    or stored_capture["query_attempt_id"] is not None
                    or stored_capture["generation"] != identity.generation
                    or stored_capture["claim_epoch"] != identity.claim_epoch
                    or stored_capture["authority_epoch"] != identity.authority_epoch
                    or stored_capture["context_revision"] != identity.context_revision
                    or stored_capture["source_role"] != source_role[table]
                    or stored_capture["request_digest"] != witness.request_sha256
                    or stored_capture["raw_body_sha256"] != witness.response_sha256
                    or int(stored_capture["response_bytes"]) != len(page.raw_body)
                    or int(stored_capture["http_status"]) != witness.http_status
                    or stored_capture["content_range"] != witness.content_range
                    or reserved["stage"] != "backend_get"
                    or reserved["admission_id"] != binding.admission_id
                    or reserved["source_role"] != source_role[table]
                    or reserved["request_digest"] != witness.request_sha256
                    or terminal["raw_body_sha256"] != witness.response_sha256
                    or int(terminal["actual_response_bytes"]) != len(page.raw_body)
                    or chain_row["source_table"] != table
                    or chain_row["source_role"] != source_role[table]
                    or chain_row["reservation_binding_kind"] != "admission"
                    or chain_row["reservation_admission_id"] != binding.admission_id
                    or chain_row["capture_chain_id"] != binding.admission_id
                    or int(chain_row["generation"]) != identity.generation
                    or int(chain_row["input_seq"]) != identity.input_seq
                    or chain_row["input_digest"] != identity.input_digest
                    or int(chain_row["claim_epoch"]) != identity.claim_epoch
                    or int(chain_row["authority_epoch"]) != identity.authority_epoch
                    or int(chain_row["context_revision"]) != identity.context_revision
                    or int(chain_row["table_get_ordinal"]) != entry["table_ordinal"]
                ):
                    raise P2V3StoreConflict("Store wire/cost/capture-chain facts do not match the raw source page")
                raw_rows = entry["rows"]
                source_rows_sha = codec3.stable_digest([dict(row) for row in raw_rows])
                typed_dto_sha = codec3.stable_digest({"table": table, "rows": [dict(row) for row in raw_rows]})
                receipt_id = str(uuid.uuid4())
                receipt_id_by_capture[witness.capture_id] = receipt_id
                connection.execute(
                    """INSERT INTO p2_v3_source_get_receipts (
                        source_receipt_id,capture_id,reservation_id,reservation_event_kind,
                        owner_user_id,turn_id,cohort_sha256,binding_kind,admission_id,
                        logical_query_id,query_attempt_id,page_index,source_role,source_table,
                        request_sha256,raw_body_sha256,typed_dto_sha256,source_rows_sha256,
                        http_status,content_range,range_start,returned_count,known_total,
                        response_bytes,observed_at,elapsed_us,accepted_at
                    ) VALUES (?,?,?,'settled',?,?,?,'admission',?,NULL,NULL,NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        receipt_id, witness.capture_id, witness.reservation_id,
                        str(owner_user_id), str(turn_id), pin["cohort_sha256"], binding.admission_id,
                        source_role[table], table, witness.request_sha256, witness.response_sha256,
                        typed_dto_sha, source_rows_sha, witness.http_status, witness.content_range,
                        page.range.offset, page.range.row_count, page.range.total,
                        len(page.raw_body), _stamp(witness.observed_at), witness.elapsed_us, _stamp(now),
                    ),
                )
                connection.execute(
                    """INSERT INTO p2_v3_admission_source_receipts (
                        admission_id,owner_user_id,turn_id,ordinal,source_receipt_id,
                        private_scope_sha256,source_role
                    ) VALUES (?,?,?,?,?,?,?)""",
                    (
                        binding.admission_id, str(owner_user_id), str(turn_id), ordinal,
                        receipt_id, private_scope_digest, source_role[table],
                    ),
                )

            rows_by_id: dict[tuple[str, str], Mapping[str, Any]] = {}
            for table in expected_tables:
                for row in source_tables[table].rows:
                    key_field = "activity_id" if table == "activity_members" else (
                        "ledger_unit_id|participant_id" if table == "sub_activity_participants" else "id"
                    )
                    if key_field == "id":
                        rows_by_id[(table, str(row["id"]))] = row
                    elif key_field == "activity_id":
                        rows_by_id[(table, str(registry.principal_user_id))] = row

            # Persist only public entity refs actually projected from these rows.
            entity_refs: set[str] = set()
            for label in rebuilt_projection.source_labels:
                entity_refs.add(str(label.entity_ref))
            if rebuilt_projection.current_actor is not None:
                entity_refs.add(str(rebuilt_projection.current_actor.participant_ref))
            locator_id_by_ref: dict[str, str] = {}
            source_row_by_ref: dict[str, tuple[str, Mapping[str, Any], str]] = {}
            for entity_ref in sorted(entity_refs):
                kind, entity_id, bound_activity, bound_unit = registry.binding_for_ref(entity_ref)
                if bound_activity != activity_id or kind not in {"activity", "ledger_unit", "participant"}:
                    raise P2V3StoreConflict("metadata ref registry contains a non-public or cross-Activity entity")
                table = {"activity": "activities", "ledger_unit": "ledger_units", "participant": "participants"}[kind]
                row = rows_by_id.get((table, str(entity_id)))
                if row is None:
                    raise P2V3StoreConflict("metadata entity locator has no independently decoded source row")
                capture_page = next((
                    item for item in pages_by_table[table]
                    if any(str(candidate.get("id")) == str(entity_id) for candidate in item.rows)
                ), None)
                if capture_page is None:
                    raise P2V3StoreConflict("metadata entity row has no exact source receipt")
                if kind == "ledger_unit" and (bound_unit != entity_id or row["type"] != "sub_activity" or row["is_deleted"] is not False):
                    raise P2V3StoreConflict("metadata ledger-unit ref is not an active child of this Activity")
                if kind == "participant" and (row["activity_id"] != str(activity_id) or row["is_deleted"] is not False):
                    raise P2V3StoreConflict("metadata participant ref is inactive or outside this Activity")
                identity_rows = connection.execute(
                    """SELECT * FROM p2_v3_entity_locators
                       WHERE owner_user_id=? AND turn_id=? AND entity_kind=?
                         AND private_entity_id=? AND private_activity_id IS ?
                         AND private_ledger_unit_id IS ? ORDER BY locator_id""",
                    (
                        str(owner_user_id), str(turn_id), kind, str(entity_id),
                        str(bound_activity) if bound_activity is not None else None,
                        str(bound_unit) if bound_unit is not None else None,
                    ),
                ).fetchall()
                token_rows = connection.execute(
                    "SELECT * FROM p2_v3_entity_locators WHERE entity_ref=? ORDER BY owner_user_id,turn_id,entity_kind",
                    (entity_ref,),
                ).fetchall()
                if len(identity_rows) > 1 or len(token_rows) > 1:
                    raise P2V3StoreConflict("metadata entity identity or opaque ref has ambiguous persisted locators")
                if identity_rows:
                    persisted = identity_rows[0]
                    if (
                        persisted["owner_user_id"] != str(owner_user_id)
                        or persisted["turn_id"] != str(turn_id)
                        or persisted["entity_ref"] != entity_ref
                        or persisted["entity_kind"] != kind
                        or persisted["private_entity_id"] != str(entity_id)
                        or persisted["private_activity_id"] != (str(bound_activity) if bound_activity is not None else None)
                        or persisted["private_ledger_unit_id"] != (str(bound_unit) if bound_unit is not None else None)
                        or persisted["cohort_sha256"] != pin["cohort_sha256"]
                        or len(token_rows) != 1
                        or token_rows[0]["locator_id"] != persisted["locator_id"]
                    ):
                        raise P2V3StoreConflict("persisted metadata locator does not exactly match this identity, ref, and cohort")
                    # The old locator is identity-only. Its receipt/proofs are not
                    # reused: metadata proofs below bind the new accepted receipt.
                    locator_id = persisted["locator_id"]
                else:
                    if token_rows:
                        raise P2V3StoreConflict("prospective metadata ref collides with a different persisted identity")
                    locator_id = str(uuid.uuid4())
                    connection.execute(
                        """INSERT INTO p2_v3_entity_locators (
                            locator_id,owner_user_id,turn_id,entity_ref,entity_kind,private_entity_id,
                            private_activity_id,private_ledger_unit_id,cohort_sha256,
                            created_from_receipt_id,created_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            locator_id, str(owner_user_id), str(turn_id), entity_ref, kind, str(entity_id),
                            str(bound_activity) if bound_activity is not None else None,
                            str(bound_unit) if bound_unit is not None else None,
                            pin["cohort_sha256"], receipt_id_by_capture[capture_page.witness.capture_id], _stamp(now),
                        ),
                    )
                locator_id_by_ref[entity_ref] = locator_id
                source_receipt_id = receipt_id_by_capture[capture_page.witness.capture_id]
                source_row_by_ref[entity_ref] = (table, row, source_receipt_id)

            scope_locator_id = locator_id_by_ref.get(scope_ref)
            if scope_locator_id is None:
                raise P2V3StoreConflict("accepted metadata scope has no persisted private locator")
            metadata_proofs: list[Any] = []
            proof_rows: list[tuple[Any, ...]] = []
            for label in rebuilt_projection.source_labels:
                source_ref = str(label.source_receipt_ref)
                capture_id = registry.bind_capture_lookup(source_ref)
                receipt_id = receipt_id_by_capture.get(capture_id)
                entity_ref = str(label.entity_ref)
                locator_id = locator_id_by_ref.get(entity_ref)
                source_record = source_row_by_ref.get(entity_ref)
                if receipt_id is None or locator_id is None or source_record is None:
                    raise P2V3StoreConflict("metadata label lacks a committed source-row/receipt locator")
                table, row, _ = source_record
                if table != label.source_kind:
                    raise P2V3StoreConflict("metadata label source kind differs from its source row")
                proof_id = str(uuid.uuid4())
                source_value_sha = codec3.stable_digest({
                    "entity_kind": label.entity_kind, "source_field_role": "display_name",
                    "value": label.display_name,
                })
                source_version = str(label.source_financial_version) if label.source_financial_version is not None else None
                source_updated = _stamp(label.source_row_updated_at) if label.source_row_updated_at is not None else None
                proof_rows.append((
                    proof_id, str(owner_user_id), str(turn_id), pin["cohort_sha256"], entity_ref,
                    label.entity_kind, str(label.scope_ref), locator_id, scope_locator_id,
                    "display_name", receipt_id, source_version, source_updated,
                    _stamp(label.observed_at), source_value_sha, _stamp(now),
                ))
                metadata_proofs.append(P2V3PrivateMetadataProofBinding(
                    entity_kind=label.entity_kind, entity_ref=label.entity_ref,
                    source_ref=label.entity_ref, scope_ref=label.scope_ref,
                    source_kind=label.source_kind, source_receipt_ref=label.source_receipt_ref,
                    private_source_row_id=uuid.UUID(str(row["id"])), private_proof_id=uuid.UUID(proof_id),
                ))
            actor = rebuilt_projection.current_actor
            if actor is not None:
                participant_ref = str(actor.participant_ref)
                actor_ref = str(actor.actor_ref)
                participant_locator_id = locator_id_by_ref.get(participant_ref)
                participant_binding = registry.binding_for_ref(participant_ref)
                actor_binding = registry.binding_for_ref(actor_ref)
                if (
                    participant_locator_id is None or actor_binding[0] != "actor"
                    or actor_binding[1] != registry.principal_user_id or actor_binding[2] != activity_id
                ):
                    raise P2V3StoreConflict("current actor is not bound to this verified principal/activity")
                source_table = source_tables["participant_claims"]
                claims = [
                    row for row in source_table.rows
                    if row["activity_id"] == str(activity_id)
                    and row["user_id"] == str(registry.principal_user_id)
                    and row["participant_id"] == str(participant_binding[1])
                ]
                if len(claims) != 1:
                    raise P2V3StoreConflict("current actor proof requires one exact current-user claim row")
                claim = claims[0]
                actor_capture = next((
                    page for page in pages_by_table["participant_claims"]
                    if any(candidate == claim for candidate in page.rows)
                ), None)
                receipt_id = receipt_id_by_capture.get(actor_capture.witness.capture_id) if actor_capture else None
                capture_ref = str(actor.source_receipt_ref)
                if receipt_id is None or registry.bind_capture_lookup(capture_ref) != actor_capture.witness.capture_id:
                    raise P2V3StoreConflict("current actor claim is not bound to its exact captured page")
                proof_id = str(uuid.uuid4())
                actor_scope_locator_id = locator_id_by_ref.get(str(actor.activity_ref))
                if actor_scope_locator_id is None:
                    raise P2V3StoreConflict("current actor Activity scope has no accepted Activity locator")
                proof_rows.append((
                    proof_id, str(owner_user_id), str(turn_id), pin["cohort_sha256"], actor_ref,
                    "current_actor", str(actor.activity_ref), participant_locator_id, actor_scope_locator_id,
                    "current_actor", receipt_id, None, _stamp(codec3._time(claim, "claimed_at")),
                    _stamp(actor.observed_at), codec3.stable_digest({
                        "source_field_role": "current_actor", "participant_ref": participant_ref,
                        "claimed_at": claim["claimed_at"],
                    }), _stamp(now),
                ))
                metadata_proofs.append(P2V3PrivateMetadataProofBinding(
                    entity_kind="current_actor", entity_ref=actor.actor_ref,
                    source_ref=actor.participant_ref, scope_ref=actor.activity_ref,
                    source_kind="participant_claims.current_auth_user",
                    source_receipt_ref=actor.source_receipt_ref,
                    private_source_row_id=uuid.UUID(str(claim["id"])),
                    private_proof_id=uuid.UUID(proof_id),
                ))

            connection.executemany(
                """INSERT INTO p2_v3_metadata_source_proofs (
                    metadata_proof_id,owner_user_id,turn_id,cohort_sha256,entity_ref,
                    entity_kind,scope_ref,private_entity_locator_id,private_scope_locator_id,
                    source_field_role,source_receipt_id,source_version,source_row_updated_at,
                    observed_at,source_value_sha256,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                proof_rows,
            )
            if not 1 <= len(metadata_proofs) <= 129:
                raise P2V3StoreConflict("metadata acceptance proof set is outside the bounded V005 shape")
            reserved = connection.execute(
                "SELECT * FROM p2_v3_charge_events WHERE reservation_id=? AND owner_user_id=? AND turn_id=? AND event_kind='reserved'",
                (processing_reservation_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            dispatch_started = connection.execute(
                "SELECT 1 FROM p2_v3_charge_events WHERE reservation_id=? AND owner_user_id=? AND turn_id=? AND event_kind='dispatch_started'",
                (processing_reservation_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            if (
                reserved is None or dispatch_started is None
                or reserved["stage"] != "backend_processing"
                or int(reserved["active_limit_us"]) != P2_V3_METADATA_ACCEPTANCE_CAP_US
                or int(reserved["backend_limit_us"]) != P2_V3_METADATA_ACCEPTANCE_CAP_US
                or int(reserved["response_bytes_limit"]) != 0
            ):
                raise P2V3StoreConflict("metadata A phase lacks the fixed started processing reservation")
            acceptance_id = str(uuid.uuid4())
            proof_links: list[tuple[Any, ...]] = []
            for ordinal, proof in enumerate(metadata_proofs):
                capture_id = registry.bind_capture_lookup(str(proof.source_receipt_ref))
                receipt_id = receipt_id_by_capture.get(capture_id)
                if receipt_id is None:
                    raise P2V3StoreConflict("metadata proof source receipt is outside this accepted capture set")
                proof_links.append((
                    acceptance_id, str(owner_user_id), str(turn_id), ordinal,
                    str(proof.private_proof_id), receipt_id,
                ))
            proof_set_digest = codec3.stable_digest([
                {"ordinal": row[3], "metadata_proof_id": row[4], "source_receipt_id": row[5]}
                for row in proof_links
            ])
            projection_digest = codec3.stable_digest(
                {
                    "current_actor": (
                        rebuilt_projection.current_actor.model_dump(mode="json", exclude_none=False)
                        if rebuilt_projection.current_actor is not None else None
                    ),
                    "source_labels": [
                        item.model_dump(mode="json", exclude_none=False)
                        for item in rebuilt_projection.source_labels
                    ],
                    "snapshot_digest": rebuilt_projection.snapshot_digest,
                    "scope_kind": rebuilt_projection.snapshot.scope_kind,
                    "scope_ref": rebuilt_projection.snapshot.scope_ref,
                }
            )
            connection.execute(
                """INSERT INTO p2_v3_metadata_acceptance_batches (
                       acceptance_id,owner_user_id,turn_id,cohort_sha256,admission_id,
                       processing_reservation_id,reserved_event_id,reserved_event_kind,
                       generation,input_seq,input_digest,claim_epoch,authority_epoch,context_revision,
                       projection_sha256,proof_set_sha256,proof_count,created_at
                   ) VALUES (?,?,?,?,?,?,?,'reserved',?,?,?,?,?,?,?,?,?,?)""",
                (
                    acceptance_id, str(owner_user_id), str(turn_id), pin["cohort_sha256"],
                    binding.admission_id, processing_reservation_id, reserved["event_id"],
                    current.generation, current.input_seq, current.input_digest,
                    current.claim_epoch, current.authority_epoch, current.context_revision,
                    projection_digest, proof_set_digest, len(proof_links), _stamp(now),
                ),
            )
            connection.executemany(
                """INSERT INTO p2_v3_metadata_acceptance_proofs (
                       acceptance_id,owner_user_id,turn_id,ordinal,metadata_proof_id,source_receipt_id
                   ) VALUES (?,?,?,?,?,?)""",
                proof_links,
            )
            connection.execute(
                """INSERT INTO p2_v3_metadata_acceptance_events (
                       acceptance_id,event_seq,event_kind,owner_user_id,turn_id,
                       overrun_active_us,overrun_backend_us,occurred_at
                   ) VALUES (?,1,'proof_committed',?,?,0,0,?)""",
                (acceptance_id, str(owner_user_id), str(turn_id), _stamp(now)),
            )
            self._fault("p2_v3.metadata_acceptance.a.before_commit")
            return {
                "acceptance_id": acceptance_id,
                "projection": rebuilt_projection,
                "metadata_proofs": tuple(metadata_proofs),
                "receipt_ids": tuple(receipt_id_by_capture.values()),
                "receipt_by_capture_ref": {
                    registry.bind_capture(page.witness.capture_id, identity=identity):
                    receipt_id_by_capture[page.witness.capture_id]
                    for page in all_pages
                },
                "public_scope_digest": public_scope_digest,
            }

    def _update_p2_v3_after_transition(
        self,
        connection: sqlite3.Connection,
        *,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        after: Any,
        checkpoint: Any,
        checkpoint_revision: int,
        expected_revision: int,
        now: datetime,
    ) -> None:
        current = connection.execute(
            "SELECT * FROM p2_v3_turns WHERE turn_id = ? AND owner_user_id = ?",
            (str(turn_id), str(owner_user_id)),
        ).fetchone()
        if current is None:
            raise P2V3StoreNotFound("v3 candidate assignment disappeared during Turn transition")
        snapshot = self._p2_v3_snapshot(current)
        if snapshot.revision != expected_revision:
            raise P2V3StoreConflict("v3 Store revision changed during Turn transition")
        leaving_active = after.state != TurnState.RUNNING
        if leaving_active and snapshot.active_reserved_us:
            raise P2V3StoreConflict("v3 stage reservations must settle before a waiting or terminal transition")
        input_seq, input_digest = self._p2_input_binding(checkpoint)
        generation_changed = checkpoint.generation != snapshot.generation
        if checkpoint.generation < snapshot.generation or (
            generation_changed and input_digest == snapshot.input_digest
        ):
            raise P2V3StoreConflict("v3 generation must advance with a new accepted input")
        invalidate = leaving_active or generation_changed
        changed = connection.execute(
            """UPDATE p2_v3_turns SET generation=?,input_seq=?,input_digest=?,context_revision=?,
                turn_state_revision=?,claim_epoch=claim_epoch+?,authority_epoch=authority_epoch+?,
                lifecycle=?,revision=revision+1,updated_at=?
                WHERE turn_id=? AND owner_user_id=? AND revision=? AND generation=?
                  AND claim_epoch=? AND authority_epoch=?""",
            (
                checkpoint.generation, input_seq, input_digest, checkpoint_revision,
                after.state_revision, int(invalidate), int(invalidate),
                self._p2_v3_lifecycle_for_state(after.state), _stamp(now),
                str(turn_id), str(owner_user_id), snapshot.revision, snapshot.generation,
                snapshot.claim_epoch, snapshot.authority_epoch,
            ),
        ).rowcount
        if changed != 1:
            raise P2V3StoreConflict("v3 Turn lifecycle update lost its Store CAS")

    def _update_p2_v3_after_action(
        self,
        connection: sqlite3.Connection,
        *,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        after: Any,
        checkpoint: Any,
        checkpoint_revision: int,
        expected_revision: int,
        now: datetime,
    ) -> None:
        current = connection.execute(
            "SELECT * FROM p2_v3_turns WHERE turn_id = ? AND owner_user_id = ?",
            (str(turn_id), str(owner_user_id)),
        ).fetchone()
        if current is None:
            raise P2V3StoreNotFound("v3 candidate assignment disappeared during accepted action")
        snapshot = self._p2_v3_snapshot(current)
        if snapshot.revision != expected_revision:
            raise P2V3StoreConflict("v3 Store revision changed during accepted action")
        if snapshot.active_reserved_us:
            if after.state not in (TurnState.COMPLETED, TurnState.CANCELLED, TurnState.FAILED):
                raise P2V3StoreConflict("v3 nonterminal action cannot abandon unsettled work reservations")
            self._recover_p2_v3_pending_reservations(
                connection, owner_user_id=str(owner_user_id), turn_id=str(turn_id), now=now,
            )
            current = connection.execute(
                "SELECT * FROM p2_v3_turns WHERE turn_id = ? AND owner_user_id = ?",
                (str(turn_id), str(owner_user_id)),
            ).fetchone()
            snapshot = self._p2_v3_snapshot(current)
            if snapshot.active_reserved_us:
                raise P2V3StoreConflict("v3 terminal action could not settle every pending work reservation")
        input_seq, input_digest = self._p2_input_binding(checkpoint)
        generation_changed = checkpoint.generation != snapshot.generation
        if checkpoint.generation < snapshot.generation or (
            generation_changed and input_digest == snapshot.input_digest
        ):
            raise P2V3StoreConflict("v3 generation must advance with a new accepted input")
        changed = connection.execute(
            """UPDATE p2_v3_turns SET generation=?,input_seq=?,input_digest=?,context_revision=?,
                turn_state_revision=?,claim_epoch=claim_epoch+1,authority_epoch=authority_epoch+1,
                lifecycle=?,revision=revision+1,updated_at=?
                WHERE turn_id=? AND owner_user_id=? AND revision=? AND generation=?
                  AND claim_epoch=? AND authority_epoch=?""",
            (
                checkpoint.generation, input_seq, input_digest, checkpoint_revision,
                after.state_revision, self._p2_v3_lifecycle_for_state(after.state), _stamp(now),
                str(turn_id), str(owner_user_id), snapshot.revision, snapshot.generation,
                snapshot.claim_epoch, snapshot.authority_epoch,
            ),
        ).rowcount
        if changed != 1:
            raise P2V3StoreConflict("v3 accepted-action invalidation lost its Store CAS")

    def _sync_p2_v3_checkpoint(
        self,
        connection: sqlite3.Connection,
        *,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        checkpoint_revision: int,
        state_revision: int,
        expected_revision: int,
        now: datetime,
    ) -> None:
        current = connection.execute(
            "SELECT * FROM p2_v3_turns WHERE turn_id = ? AND owner_user_id = ?",
            (str(turn_id), str(owner_user_id)),
        ).fetchone()
        if current is None:
            raise P2V3StoreNotFound("v3 candidate assignment disappeared while syncing checkpoint")
        snapshot = self._p2_v3_snapshot(current)
        if snapshot.revision != expected_revision:
            raise P2V3StoreConflict("v3 Store revision changed while syncing checkpoint")
        changed = connection.execute(
            """UPDATE p2_v3_turns SET context_revision=?,turn_state_revision=?,revision=revision+1,
                updated_at=? WHERE turn_id=? AND owner_user_id=? AND revision=?
                  AND generation=? AND claim_epoch=? AND authority_epoch=?""",
            (
                checkpoint_revision, state_revision, _stamp(now), str(turn_id), str(owner_user_id),
                snapshot.revision, snapshot.generation, snapshot.claim_epoch, snapshot.authority_epoch,
            ),
        ).rowcount
        if changed != 1:
            raise P2V3StoreConflict("v3 checkpoint synchronization lost its Store CAS")

    def _accept_p2_v3_scoped_query_attempt(
        self,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        *,
        claim_token: str,
        principal_user_id: uuid.UUID,
        pending: Any,
        now: Optional[datetime] = None,
    ) -> P2V3AcceptedReadPage:
        """Accept a scoped financial page after rebuilding it from captured GETs."""
        from . import p2_read_backend as backend3
        from . import p2_read_contracts_v3 as pc3
        from . import p2_source_codec_v3 as codec3
        from . import p2_event_contracts_v3 as pe3

        self._require_started()
        if type(owner_user_id) is not uuid.UUID or type(turn_id) is not uuid.UUID:
            raise P2V3StoreConflict("source acceptance requires an owner and Turn UUID")
        if type(principal_user_id) is not uuid.UUID or principal_user_id != owner_user_id:
            raise P2V3StoreConflict("verified principal does not own this source Turn")
        if not isinstance(pending, backend3.P2V3PendingSourceAttempt):
            raise P2V3StoreConflict("source acceptance requires the adapter's private pending attempt")
        binding, query_binding = pending.admission, pending.query_binding
        registry = binding.reference_registry
        if not isinstance(binding, codec3.AdmissionOnlyBinding) or not isinstance(query_binding, codec3.QueryAttemptBinding):
            raise P2V3StoreConflict("source acceptance has no exact admission/query binding")
        if not isinstance(registry, P2V3RequestReferenceRegistry):
            raise P2V3StoreConflict("source acceptance requires the Store-issued reference registry")
        registry._assert_store_issued(self, identity=binding.identity, admission_id=binding.admission_id, claim_token=claim_token)
        identity = binding.identity
        operation = pending.request.operation
        page_index = query_binding.page_index
        if (
            operation not in {
                pc3.P2ReadOperation.EXPENSES, pc3.P2ReadOperation.DEBTS,
                pc3.P2ReadOperation.REFUND_EVENTS, pc3.P2ReadOperation.PREPAYMENT_ACCOUNTS,
                pc3.P2ReadOperation.PREPAYMENT_USAGES, pc3.P2ReadOperation.PREPAYMENT_RETURN_EVENTS,
            }
            or pending.request.scope is None
            or identity.owner_user_id != owner_user_id or identity.turn_id != turn_id
            or query_binding.identity != identity or binding.claim_token != claim_token
            or registry.principal_user_id != principal_user_id
            or pending.admission_projection is None
            or page_index not in (0, 1)
            or (page_index == 0 and pending.previous_proof is not None)
            or (page_index == 1 and pending.previous_proof is None)
            or pending.projection.historical.operation is not operation
            or pending.projection.historical.page.page_index != page_index
            or (page_index == 1 and pending.projection.historical.page.has_more)
        ):
            raise P2V3StoreConflict("scoped source slice requires a bound first or terminal continuation page")
        if pending.context_version is None or not pending.context_version.strip():
            raise P2V3StoreConflict("scoped facts require a server context version")
        admission_projection = pending.admission_projection
        if (
            admission_projection.reference_registry is not registry
            or admission_projection.snapshot_digest != registry._accepted_snapshot_digest
            or admission_projection.snapshot.scope_ref != pending.request.scope.scope_ref
            or admission_projection.snapshot.activity_ref != pending.request.scope.activity_ref
        ):
            raise P2V3StoreConflict("scoped read does not use this Store's accepted admission snapshot")

        instant = _now(now)
        with self._connection() as connection:
            _initial, current, _ = self._p2_v3_current_claim(
                connection, owner_user_id, turn_id, claim_token=claim_token, now=instant,
            )
            turn_row = connection.execute(
                "SELECT * FROM p2_v3_turns WHERE turn_id=? AND owner_user_id=?",
                (str(turn_id), str(owner_user_id)),
            ).fetchone()
            admission_row = connection.execute(
                "SELECT * FROM p2_v3_source_admissions WHERE admission_id=? AND owner_user_id=? AND turn_id=?",
                (binding.admission_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            query_row = connection.execute(
                "SELECT * FROM p2_v3_queries WHERE logical_query_id=? AND owner_user_id=? AND turn_id=?",
                (query_binding.logical_query_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            attempt_row = connection.execute(
                "SELECT * FROM p2_v3_query_attempts WHERE attempt_id=? AND logical_query_id=? AND owner_user_id=? AND turn_id=?",
                (query_binding.query_attempt_id, query_binding.logical_query_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            descriptor_row = connection.execute(
                "SELECT * FROM p2_v3_query_descriptor_bindings WHERE logical_query_id=? AND owner_user_id=? AND turn_id=?",
                (query_binding.logical_query_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            if any(row is None for row in (turn_row, admission_row, query_row, attempt_row, descriptor_row)):
                raise P2V3StoreNotFound("current scoped admission, query, or attempt is unavailable")
            self._require_current_p2_v3_pin(connection, turn_row)
            pin_ok, pin = self._verify_p2_v3_execution_pin_rows(connection, turn_row)
            expected_identity = (
                owner_user_id, turn_id, current.generation, current.input_seq,
                current.input_digest, current.claim_epoch, current.authority_epoch, current.context_revision,
            )
            if (
                not pin_ok or pin is None
                or (identity.owner_user_id, identity.turn_id, identity.generation, identity.input_seq,
                    identity.input_digest, identity.claim_epoch, identity.authority_epoch, identity.context_revision) != expected_identity
                or admission_row["generation"] != current.generation
                or admission_row["input_seq"] != current.input_seq
                or admission_row["input_digest"] != current.input_digest
                or admission_row["claim_epoch"] != current.claim_epoch
                or admission_row["authority_epoch"] != current.authority_epoch
                or admission_row["context_revision"] != current.context_revision
                or admission_row["public_scope_digest"] != query_row["scope_digest"]
                or query_row["operation"] != operation.value
                or query_row["admission_id"] != descriptor_row["admission_id"]
                or query_row["generation"] != current.generation
                or query_row["input_seq"] != current.input_seq
                or query_row["input_digest"] != current.input_digest
                or query_row["authority_epoch"] != descriptor_row["authority_epoch"]
                or query_row["criteria_digest"] != attempt_row["criteria_digest"]
                or query_row["scope_digest"] != attempt_row["scope_digest"]
                or attempt_row["admission_id"] != binding.admission_id
                or attempt_row["generation"] != current.generation
                or attempt_row["authority_epoch"] != current.authority_epoch
                or attempt_row["page_index"] != page_index
                or attempt_row["attempt_state"] != "started"
                or descriptor_row["cohort_sha256"] != pin["cohort_sha256"]
                or descriptor_row["normalized_criteria_digest"] != pending.query_evidence.normalized_criteria_digest
            ):
                raise P2V3StoreConflict("pending scoped read is stale or differs from its immutable Store query")
            if page_index == 1:
                prior = pending.previous_proof
                if not isinstance(prior, codec3.V3ContinuationProof):
                    raise P2V3StoreConflict("continuation page has no strict Store-issued prior proof")
                prior_attempt = connection.execute(
                    "SELECT * FROM p2_v3_query_attempts WHERE attempt_id=? AND logical_query_id=? AND owner_user_id=? AND turn_id=?",
                    (prior.query_attempt_id, query_binding.logical_query_id, str(owner_user_id), str(turn_id)),
                ).fetchone()
                prior_receipt = connection.execute(
                    "SELECT * FROM p2_v3_query_result_receipts WHERE logical_query_id=? AND query_attempt_id=? AND page_index=0 AND owner_user_id=? AND turn_id=?",
                    (query_binding.logical_query_id, prior.query_attempt_id, str(owner_user_id), str(turn_id)),
                ).fetchone()
                prior_uses = connection.execute(
                    """SELECT u.*,i.source_proof_sha256,i.projection_sha256,i.page_index AS issuer_page_index
                       FROM p2_v3_continuation_nonce_uses u
                       JOIN p2_v3_continuation_nonce_issues i
                         ON i.nonce_sha256=u.nonce_sha256 AND i.logical_query_id=u.logical_query_id
                        AND i.owner_user_id=u.owner_user_id AND i.turn_id=u.turn_id
                       WHERE u.logical_query_id=? AND u.owner_user_id=? AND u.turn_id=?
                         AND u.attempt_seq=? AND u.page_index=1 ORDER BY u.consumed_at""",
                    (query_binding.logical_query_id, str(owner_user_id), str(turn_id), int(attempt_row["attempt_seq"])),
                ).fetchall()
                if (
                    prior_attempt is None or prior_receipt is None or len(prior_uses) != 1
                    or prior_attempt["attempt_seq"] != attempt_row["attempt_seq"]
                    or prior_attempt["page_index"] != 0
                    or prior_attempt["attempt_state"] != "started"
                    or prior_receipt["has_more"] != 1
                    or prior_receipt["criteria_digest"] != query_row["criteria_digest"]
                    or prior_receipt["scope_digest"] != query_row["scope_digest"]
                    or prior_receipt["cohort_sha256"] != pin["cohort_sha256"]
                    or self._p2_v3_continuation_proof_from_receipt(prior_receipt) != prior
                    or prior_uses[0]["issuer_page_index"] != 0
                    or prior_uses[0]["source_proof_sha256"] != P2V3RequestReferenceRegistry._continuation_proof_sha256(prior)
                    or prior_uses[0]["projection_sha256"] != prior.projection_digest
                ):
                    raise P2V3StoreConflict("continuation page no longer matches its one-use accepted page-zero proof")
            criteria_json, criteria_digest, scope_json, scope_digest = _wire_query_descriptor(
                query_row["operation"], pending.request.criteria, pending.request.scope,
            )
            if (
                criteria_json != query_row["criteria_json"] or criteria_digest != query_row["criteria_digest"]
                or scope_json != query_row["scope_json"] or scope_digest != query_row["scope_digest"]
                or pending.request.profile_id != P2_V3_CANDIDATE_PROFILE_ID
                or pending.request.versions.model_dump(mode="json") != P2_V3_VERSIONS
            ):
                raise P2V3StoreConflict("pending scoped request differs from the immutable query descriptor")
            if registry._configured_source_origin is None:
                raise P2V3StoreConflict("configured source origin was not pinned before the first GET")
            cohort_sha256 = pin["cohort_sha256"]

        processing_limit_us = P2_V3_METADATA_ACCEPTANCE_CAP_US
        processing_id = self.reserve_p2_v3_stage(
            owner_user_id, turn_id, claim_token=claim_token, stage="backend_processing",
            active_limit_us=processing_limit_us, backend_limit_us=processing_limit_us, now=instant,
        )
        self.mark_p2_v3_dispatch_started(owner_user_id, turn_id, processing_id, claim_token=claim_token, now=instant)
        processing_started_ns = time.monotonic_ns()

        def reject(message: str, cause: BaseException | None = None) -> P2V3StoreConflict:
            error = P2V3StoreConflict(message)
            if cause is not None:
                error.__cause__ = cause
            return error

        try:
            alias_to_capture_ids: dict[str, set[str]] = {}
            alias_template: dict[str, Any] = {}
            for alias, table in pending.query_tables:
                if alias == "ledger_units":
                    # The adapter's convenience alias is the end-snapshot
                    # ledger-unit table; the exact captures remain under the
                    # numbered scope aliases below.
                    continue
                alias_template[alias] = table
                alias_to_capture_ids[alias] = {item.witness.capture_id for item in table.pages}
            capture_to_alias: dict[str, str] = {}
            for alias, capture_ids in alias_to_capture_ids.items():
                for capture_id in capture_ids:
                    if capture_id in capture_to_alias:
                        raise reject("scoped source capture is aliased more than once")
                    capture_to_alias[capture_id] = alias
            if not pending.query_captures or len(pending.query_captures) > P2_V3_MAX_SOURCE_PAGES_PER_CAPTURE_CHAIN:
                raise reject("scoped query capture chain is empty or exceeds its bound")

            parsed_by_alias: dict[str, list[Mapping[str, Any]]] = {alias: [] for alias in alias_template}
            pages_by_alias: dict[str, list[Any]] = {alias: [] for alias in alias_template}
            filters_by_alias: dict[str, list[dict[str, str]]] = {alias: [] for alias in alias_template}
            scope_public = pending.request.scope
            activity_id = registry.resolve_activity_ref(str(scope_public.activity_ref))
            ledger_unit_id = (
                registry.resolve_entity(str(scope_public.ledger_unit_ref), "ledger_unit", activity_id=activity_id)
                if scope_public.scope_kind == "ledger_unit" else None
            )
            source_columns = codec3._SOURCE_COLUMNS
            for page in pending.query_captures:
                witness = page.witness
                alias = capture_to_alias.get(witness.capture_id)
                if alias is None:
                    raise reject("scoped GET is absent from the adapter's exact table alias set")
                expected_role = backend3.P2ReadBackendAdapter._V3_TABLE_ROLES.get(page.table)
                if (
                    expected_role is None or witness.source_role != expected_role
                    or witness.binding_kind != "query_attempt" or witness.admission_id is not None
                    or witness.logical_query_id != query_binding.logical_query_id
                    or witness.query_attempt_id != query_binding.query_attempt_id
                    or witness.page_index != query_binding.page_index
                    or witness.owner_user_id != owner_user_id or witness.turn_id != turn_id
                    or witness.generation != identity.generation or witness.input_seq != identity.input_seq
                    or witness.input_digest != identity.input_digest or witness.claim_epoch != identity.claim_epoch
                    or witness.authority_epoch != identity.authority_epoch
                    or witness.context_revision != identity.context_revision
                    or witness.capture_id == "" or witness.reservation_id != page.reservation_id
                    or type(page.raw_body) is not bytes or len(page.raw_body) > P2_V3_MAX_GET_RESPONSE_BYTES
                    or len(page.raw_body) != witness.response_bytes
                    or _digest(page.raw_body) != witness.response_sha256
                    or _digest(page.raw_body) != page.raw_body_sha256
                    or page.status != witness.http_status or page.content_range != witness.content_range
                    or page.observed_at.tzinfo is None or page.observed_at.utcoffset() is None
                ):
                    raise reject("scoped raw capture does not match its exact Store query-attempt witness")
                parts = urlsplit(page.request_url)
                if (
                    parts.scheme != "https" or not parts.hostname or parts.username is not None
                    or parts.password is not None or parts.fragment or not parts.query
                    or parts.netloc.lower() != registry._configured_source_origin[1]
                    or parts.path != f"/rest/v1/{page.table}" or len(page.request_url) > 12_000
                ):
                    raise reject("scoped source GET is outside the configured PostgREST origin")
                try:
                    pairs = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)
                    raw_rows = codec3.parse_source_rows(page.raw_body, page.table)
                    page_range = codec3.parse_content_range(
                        page.content_range, expected_offset=page.offset,
                        row_count=len(raw_rows), status=page.status,
                    )
                except Exception as exc:
                    raise reject("scoped raw source page failed strict JSON/range parsing", exc)
                keys = [key for key, _ in pairs]
                values_by_key: dict[str, list[str]] = {}
                for key, value in pairs:
                    values_by_key.setdefault(key, []).append(value)
                expected_order = sorted(backend3.P2ReadBackendAdapter._V3_ORDERS[page.table])[0]
                if (
                    any(len(values) != 1 for values in values_by_key.values())
                    or not keys or keys[0] != "select"
                    or values_by_key.get("select") != [",".join(source_columns[page.table])]
                    or values_by_key.get("order") != [expected_order]
                    or values_by_key.get("limit") != ["16"]
                    or values_by_key.get("offset") != [str(page.offset)]
                    or keys[-3:] != ["order", "limit", "offset"]
                    or any(key not in {"select", "order", "limit", "offset"} | backend3.P2ReadBackendAdapter._V3_FILTER_COLUMNS[page.table] for key in keys)
                    or page_range != page.range
                    or codec3.stable_digest([dict(row) for row in raw_rows]) != codec3.stable_digest([dict(row) for row in page.rows])
                ):
                    raise reject("scoped GET query or raw source rows differ from the fixed source contract")
                filters = {key: value for key, value in pairs if key not in {"select", "order", "limit", "offset"}}
                if "activity_id" in backend3.P2ReadBackendAdapter._V3_FILTER_COLUMNS[page.table] and filters.get("activity_id") != f"eq.{activity_id}":
                    raise reject("scoped GET does not carry the resolved Activity filter")
                if page.table == "activity_members" and (
                    filters.get("user_id") != f"eq.{principal_user_id}"
                    or filters.get("activity_id") != f"eq.{activity_id}"
                ):
                    raise reject("scope membership GET does not carry the verified principal filter")
                if page.table == "activities" and filters.get("id") != f"eq.{activity_id}":
                    raise reject("scope Activity GET does not carry the exact resolved ID filter")
                filters_by_alias[alias].append(filters)
                parsed_by_alias[alias].extend(raw_rows)
                pages_by_alias[alias].append(dataclasses.replace(page, rows=raw_rows, range=page_range))

            strict_tables: dict[str, Any] = {}
            for alias, template in alias_template.items():
                pages = pages_by_alias[alias]
                if pages:
                    try:
                        table = codec3.source_table(parsed_by_alias[alias], pages, table=pages[0].table)
                    except Exception as exc:
                        raise reject("scoped source pages are not a complete unique chain", exc)
                else:
                    table = backend3.P2ReadBackendAdapter._v3_empty_table(template.table)
                if not table.complete or not table.range_contiguous or not table.unique_items_verified:
                    raise reject("scoped source table is incomplete")
                if codec3.stable_digest([dict(row) for row in table.rows]) != codec3.stable_digest([dict(row) for row in template.rows]):
                    raise reject("scoped adapter table rows differ from strict raw-source decode")
                strict_tables[alias] = table

            scope_aliases = []
            for alias in strict_tables:
                matched = re.fullmatch(r"__scope_(\d+)_(activities|activity_members|ledger_units|participants|sub_activity_participants|participant_claims)", alias)
                if matched:
                    scope_aliases.append((int(matched.group(1)), matched.group(2), alias))
            scope_aliases.sort(key=lambda item: item[0])
            scope_groups: list[dict[str, str]] = []
            for position, (sequence, table_name, alias) in enumerate(scope_aliases):
                if position == 0 or sequence != scope_aliases[position - 1][0] + 1:
                    scope_groups.append({})
                scope_groups[-1][table_name] = alias
            if len(scope_groups) != 2:
                raise reject("scoped query lacks its two independent metadata snapshots")
            required_scope_tables = {"activities", "activity_members", "ledger_units", "participants", "sub_activity_participants", "participant_claims"}
            if any(set(group) != required_scope_tables for group in scope_groups):
                raise reject("scoped metadata snapshot table set is incomplete")

            def build_snapshot(group: Mapping[str, str]) -> Any:
                scoped = {table: strict_tables[alias] for table, alias in group.items()}
                activity_rows = scoped["activities"].rows
                if len(activity_rows) != 1:
                    raise reject("scoped metadata Activity snapshot is not unique")
                snapshot = codec3.SourceSnapshot(
                    activity_id=activity_id,
                    activity_ref=str(scope_public.activity_ref),
                    activity=activity_rows[0],
                    ledger_units=scoped["ledger_units"].rows,
                    participants=scoped["participants"].rows,
                    child_rows=scoped["sub_activity_participants"].rows,
                    claims=scoped["participant_claims"].rows,
                    membership_rows=scoped["activity_members"].rows,
                    scope_ref=str(scope_public.scope_ref),
                    scope_kind=scope_public.scope_kind,
                    ledger_unit_id=ledger_unit_id,
                    witnesses=tuple(
                        page for table in scoped.values() for page in table.pages
                    ),
                )
                return snapshot

            ordered_groups = scope_groups
            start_snapshot = build_snapshot(ordered_groups[0])
            end_snapshot = build_snapshot(ordered_groups[1])
            try:
                codec3.project_scope_metadata(start_snapshot, principal_user_id, binder=registry, identity=identity)
                codec3.project_scope_metadata(end_snapshot, principal_user_id, binder=registry, identity=identity)
            except Exception as exc:
                raise reject("scoped raw metadata failed independent principal and relation checks", exc)
            if (
                not codec3.scope_metadata_is_current(admission_projection.snapshot, start_snapshot)
                or not codec3.scope_metadata_is_current(start_snapshot, end_snapshot)
            ):
                raise reject("scope metadata changed between admission and the query's pre/post fences")
            if (
                start_snapshot.activity_id != activity_id
                or start_snapshot.scope_ref != scope_public.scope_ref
                or start_snapshot.scope_kind != scope_public.scope_kind
                or start_snapshot.ledger_unit_id != ledger_unit_id
            ):
                raise reject("query scope snapshot differs from the Store-accepted public scope")

            selected_units = (
                (ledger_unit_id,) if scope_public.scope_kind == "ledger_unit" and ledger_unit_id is not None
                else tuple(
                    uuid.UUID(row["id"]) for row in start_snapshot.ledger_units
                    if row.get("is_deleted") is False
                )
            )
            if not selected_units:
                raise reject("scoped query has no active ledger unit to bind its source filters")
            unit_column, unit_value = backend3.P2ReadBackendAdapter._v3_in_filter(
                "ledger_unit_id", selected_units,
            )
            activity_filter = f"eq.{activity_id}"

            def unique_ids(rows: Sequence[Mapping[str, Any]], field_name: str) -> tuple[uuid.UUID, ...]:
                return tuple(dict.fromkeys(uuid.UUID(row[field_name]) for row in rows))

            def in_filter(column: str, values: Sequence[uuid.UUID]) -> dict[str, str]:
                if not values:
                    return {}
                key, value = backend3.P2ReadBackendAdapter._v3_in_filter(column, values)
                return {key: value}

            expected_metadata_filters = {
                "activities": {"id": f"eq.{activity_id}", "is_deleted": "eq.false"},
                "activity_members": {"activity_id": activity_filter, "user_id": f"eq.{principal_user_id}"},
                "ledger_units": {"activity_id": activity_filter},
                "participants": {"activity_id": activity_filter},
                "sub_activity_participants": {"activity_id": activity_filter},
                "participant_claims": {"activity_id": activity_filter, "user_id": f"eq.{principal_user_id}"},
            }
            for group in ordered_groups:
                for table_name, alias in group.items():
                    expected_filters = expected_metadata_filters[table_name]
                    actual_filters = filters_by_alias.get(alias, ())
                    if not actual_filters or any(item != expected_filters for item in actual_filters):
                        raise reject("scope metadata GET does not use its exact activity and principal filters")

            operation_filters: dict[str, dict[str, str]] = {}
            operation_expenses = strict_tables.get("expenses")
            expense_rows = () if operation_expenses is None else operation_expenses.rows
            expense_ids = unique_ids(expense_rows, "id")
            debt_table = strict_tables.get("expense_debts")
            debt_rows = () if debt_table is None else debt_table.rows
            debt_ids = unique_ids(debt_rows, "id")
            usage_table = strict_tables.get("prepayment_usages")
            usage_rows = () if usage_table is None else usage_table.rows
            transfer_table = strict_tables.get("transfers")
            transfer_rows = () if transfer_table is None else transfer_table.rows
            transfer_ids = unique_ids(transfer_rows, "id")
            if operation is pc3.P2ReadOperation.EXPENSES:
                expected = {unit_column: unit_value, "is_deleted": "eq.false"}
                if pending.descriptor.ui_expense_ids:
                    expected.update(in_filter("id", pending.descriptor.ui_expense_ids))
                operation_filters["expenses"] = expected
                operation_filters["payments"] = in_filter("expense_id", expense_ids)
                operation_filters["splits"] = in_filter("expense_id", expense_ids)
            elif operation is pc3.P2ReadOperation.DEBTS:
                operation_filters["expense_debts"] = {"activity_id": activity_filter, unit_column: unit_value}
                operation_filters["expenses"] = in_filter("id", unique_ids(debt_rows, "expense_id"))
            elif operation is pc3.P2ReadOperation.REFUND_EVENTS:
                operation_filters["expenses"] = {unit_column: unit_value, "is_deleted": "eq.false"}
                operation_filters["refund_parents"] = in_filter(
                    "id", tuple(dict.fromkeys(
                        uuid.UUID(row["original_expense_id"])
                        for row in expense_rows if row.get("original_expense_id") is not None
                    )),
                )
            elif operation is pc3.P2ReadOperation.PREPAYMENT_ACCOUNTS:
                operation_filters["prepayment_accounts"] = {"activity_id": activity_filter}
            elif operation is pc3.P2ReadOperation.PREPAYMENT_USAGES:
                debt_filters = {"activity_id": activity_filter, unit_column: unit_value}
                if pending.request.criteria.expense_ref is not None:
                    expense_id = registry.resolve_entity(
                        str(pending.request.criteria.expense_ref), "expense", activity_id=activity_id,
                    )
                    debt_filters["expense_id"] = f"eq.{expense_id}"
                operation_filters["expense_debts"] = debt_filters
                if debt_ids:
                    operation_filters["prepayment_usages"] = {
                        "activity_id": activity_filter,
                        **in_filter("expense_debt_id", debt_ids),
                    }
                if usage_rows:
                    operation_filters["prepayment_accounts"] = {
                        "activity_id": activity_filter,
                        **in_filter("id", unique_ids(usage_rows, "account_id")),
                    }
                    related_expense_ids = tuple(
                        uuid.UUID(row["expense_id"]) for row in debt_rows
                        if uuid.UUID(row["id"]) in set(debt_ids)
                    )
                    if related_expense_ids:
                        operation_filters["expenses"] = in_filter("id", related_expense_ids)
            elif operation is pc3.P2ReadOperation.PREPAYMENT_RETURN_EVENTS:
                operation_filters["transfers"] = {
                    "activity_id": activity_filter,
                    "type": "eq.prepayment_return",
                    "is_voided": "eq.false",
                }
                if transfer_ids:
                    operation_filters["transfer_components"] = {
                        "activity_id": activity_filter,
                        **in_filter("transfer_id", transfer_ids),
                    }
            for alias, actual_filters in filters_by_alias.items():
                if alias.startswith("__scope_") or alias == "ledger_units":
                    continue
                expected_filters = operation_filters.get(alias)
                if expected_filters is None or not actual_filters or any(item != expected_filters for item in actual_filters):
                    raise reject("operation GET does not use its exact scoped and relationship filters")

            operation_tables = {
                alias: table for alias, table in strict_tables.items()
                if not alias.startswith("__scope_") and alias != "ledger_units"
            }
            if not operation_tables:
                raise reject("scoped read contains no operation source tables")
            try:
                facts = codec3.project_facts(
                    operation, operation_tables, start_snapshot, pending.request,
                    query_evidence_ref=registry.query_evidence_ref(
                        query_binding.logical_query_id, query_binding.query_attempt_id,
                        identity=identity, page_index=page_index,
                    ),
                    binder=registry, principal_user_id=principal_user_id,
                    context_version=pending.context_version,
                    authorized_expense_ids=frozenset(pending.descriptor.ui_expense_ids) if pending.descriptor.ui_expense_ids else None,
                )
            except Exception as exc:
                raise reject("scoped source facts failed independent relationship validation", exc)
            if len(facts) > codec3.MAX_FACTS_PER_PAGE * 2:
                raise reject("scoped fact projection exceeds the one-continuation source bound")
            page_start = page_index * codec3.MAX_FACTS_PER_PAGE
            page_facts = facts[page_start:page_start + codec3.MAX_FACTS_PER_PAGE]
            has_more = len(facts) > page_start + len(page_facts)
            if (page_index == 1 and has_more) or not page_facts and facts:
                raise reject("scoped fact projection exceeds the one-continuation page bound")
            if pending.projection.historical.page.has_more != has_more:
                raise reject("pending page continuation flag differs from the Store-rebuilt source projection")

            capture_state = backend3._V3QueryCaptureState(operation=operation, binding=query_binding)
            capture_state.tables.update(strict_tables)
            capture_state.tables.update(operation_tables)
            capture_state.captures.extend(page.witness for page in pending.query_captures)
            capture_state.source_pages = len(pending.query_captures)
            capture_state.table_pages.update({alias: len(table.pages) for alias, table in strict_tables.items()})
            capture_state.fence_complete = all(
                table.complete and table.range_contiguous and table.unique_items_verified
                for table in strict_tables.values()
            )

            query_ref = registry.query_ref(query_binding.logical_query_id, identity=identity)
            query_evidence_ref = registry.query_evidence_ref(
                query_binding.logical_query_id, query_binding.query_attempt_id, identity=identity, page_index=page_index,
            )
            result_ref = registry.result_ref(
                query_binding.logical_query_id, query_binding.query_attempt_id, identity=identity, page_index=page_index,
            )
            public_criteria_sha = pc3.p2_criteria_digest(pending.request.criteria)
            criteria_ref = registry.criteria_ref(public_criteria_sha, identity=identity)
            source_kind = operation.value.removeprefix("read.")
            source_ref = registry.source_ref(query_binding.logical_query_id, identity=identity, source_kind=source_kind)
            primary_table = {
                pc3.P2ReadOperation.EXPENSES: "expenses",
                pc3.P2ReadOperation.DEBTS: "expense_debts",
                pc3.P2ReadOperation.REFUND_EVENTS: "expenses",
                pc3.P2ReadOperation.PREPAYMENT_ACCOUNTS: "prepayment_accounts",
                pc3.P2ReadOperation.PREPAYMENT_USAGES: "prepayment_usages" if strict_tables.get("expense_debts") and strict_tables["expense_debts"].rows else "expense_debts",
                pc3.P2ReadOperation.PREPAYMENT_RETURN_EVENTS: "transfers",
            }[operation]
            builder = object.__new__(backend3.P2ReadBackendAdapter)
            builder._turn_state = None
            builder._v3_budget_port = object()
            builder._v3_locator_port = registry
            try:
                rebuilt = builder._v3_build_preaccept_projection(
                    operation, pending.request, pending.descriptor,
                    capture_state, operation_tables, primary_table=primary_table,
                    all_facts=facts, page_facts=page_facts, page_index=page_index, has_more=has_more,
                    query_ref=query_ref, result_ref=result_ref, evidence_ref=query_evidence_ref,
                    criteria_ref=criteria_ref, source_ref=source_ref,
                    criteria_sha=public_criteria_sha, source_version_fenced=True,
                )
            except Exception as exc:
                raise reject("Store could not rebuild the scoped QueryEvidence projection", exc)
            if rebuilt.historical.model_dump(mode="json", exclude_none=False) != pending.projection.historical.model_dump(mode="json", exclude_none=False):
                raise reject("scoped historical projection differs from Store-rebuilt source facts")
            if pending.query_evidence.query_digest != rebuilt.historical.query_evidence.query_digest:
                raise reject("scoped QueryEvidence digest does not bind the captured GET chain")

            acceptance_now = _now(None)
            result_receipt_id = str(uuid.uuid4())
            with self._transaction() as connection:
                _, latest, _ = self._p2_v3_current_claim(
                    connection, owner_user_id, turn_id, claim_token=claim_token, now=acceptance_now,
                )
                fresh_turn = connection.execute(
                    "SELECT * FROM p2_v3_turns WHERE turn_id=? AND owner_user_id=?",
                    (str(turn_id), str(owner_user_id)),
                ).fetchone()
                self._require_current_p2_v3_pin(connection, fresh_turn)
                fresh_pin_ok, fresh_pin = self._verify_p2_v3_execution_pin_rows(connection, fresh_turn)
                fresh_attempt = connection.execute(
                    "SELECT * FROM p2_v3_query_attempts WHERE attempt_id=? AND logical_query_id=? AND owner_user_id=? AND turn_id=?",
                    (query_binding.query_attempt_id, query_binding.logical_query_id, str(owner_user_id), str(turn_id)),
                ).fetchone()
                if (
                    not fresh_pin_ok or fresh_pin is None or fresh_pin["cohort_sha256"] != cohort_sha256
                    or latest.generation != identity.generation or latest.input_seq != identity.input_seq
                    or latest.input_digest != identity.input_digest or latest.claim_epoch != identity.claim_epoch
                    or latest.authority_epoch != identity.authority_epoch or latest.context_revision != identity.context_revision
                    or fresh_attempt is None or fresh_attempt["attempt_state"] != "started"
                    or fresh_attempt["admission_id"] != binding.admission_id
                ):
                    raise reject("scoped source acceptance lost its current claim, admission, or attempt")
                if connection.execute(
                    "SELECT 1 FROM p2_v3_query_result_receipts WHERE logical_query_id=? AND query_attempt_id=? AND page_index=?",
                    (query_binding.logical_query_id, query_binding.query_attempt_id, page_index),
                ).fetchone() is not None:
                    raise reject("scoped query result page already has an immutable receipt")
                chain_rows = connection.execute(
                    """SELECT r.*, c.stage, t.event_kind AS terminal_kind,
                              t.actual_response_bytes,t.raw_body_sha256 AS settled_body_sha
                       FROM p2_v3_capture_chain_reservations r
                       JOIN p2_v3_charge_events c ON c.reservation_id=r.reservation_id AND c.event_kind='reserved'
                       LEFT JOIN p2_v3_charge_events t ON t.reservation_id=r.reservation_id AND t.event_kind='settled'
                       WHERE r.owner_user_id=? AND r.turn_id=? AND r.capture_chain_kind='query_attempt'
                         AND r.capture_chain_id=? ORDER BY r.chain_sequence""",
                    (str(owner_user_id), str(turn_id), query_binding.query_attempt_id),
                ).fetchall()
                if [row["reservation_id"] for row in chain_rows] != [page.reservation_id for page in pending.query_captures]:
                    raise reject("scoped raw captures differ from the exact Store GET reservation chain")

                receipt_by_capture: dict[str, str] = {}
                raw_rows_by_capture: dict[str, tuple[Mapping[str, Any], ...]] = {}
                alias_by_capture = dict(capture_to_alias)
                for page, chain_row in zip(pending.query_captures, chain_rows, strict=True):
                    witness = page.witness
                    capture_row = connection.execute(
                        "SELECT * FROM p2_v3_wire_captures WHERE capture_id=? AND owner_user_id=? AND turn_id=?",
                        (witness.capture_id, str(owner_user_id), str(turn_id)),
                    ).fetchone()
                    reserved = connection.execute(
                        "SELECT * FROM p2_v3_charge_events WHERE reservation_id=? AND owner_user_id=? AND turn_id=? AND event_kind='reserved'",
                        (witness.reservation_id, str(owner_user_id), str(turn_id)),
                    ).fetchone()
                    terminal = connection.execute(
                        "SELECT * FROM p2_v3_charge_events WHERE reservation_id=? AND owner_user_id=? AND turn_id=? AND event_kind='settled'",
                        (witness.reservation_id, str(owner_user_id), str(turn_id)),
                    ).fetchone()
                    if capture_row is None or reserved is None or terminal is None or chain_row["terminal_kind"] != "settled":
                        raise reject("scoped GET lacks its Store-settled capture and budget records")
                    alias = alias_by_capture[witness.capture_id]
                    raw_rows = tuple(codec3.parse_source_rows(page.raw_body, page.table))
                    if (
                        capture_row["capture_state"] != "cost_only"
                        or capture_row["reservation_id"] != witness.reservation_id
                        or capture_row["query_attempt_id"] != query_binding.query_attempt_id
                        or capture_row["logical_query_id"] != query_binding.logical_query_id
                        or capture_row["admission_id"] is not None
                        or capture_row["page_index"] != page_index
                        or capture_row["generation"] != identity.generation
                        or capture_row["claim_epoch"] != identity.claim_epoch
                        or capture_row["authority_epoch"] != identity.authority_epoch
                        or capture_row["context_revision"] != identity.context_revision
                        or capture_row["source_role"] != witness.source_role
                        or capture_row["request_digest"] != witness.request_sha256
                        or capture_row["raw_body_sha256"] != witness.response_sha256
                        or int(capture_row["response_bytes"]) != len(page.raw_body)
                        or int(capture_row["http_status"]) != witness.http_status
                        or capture_row["content_range"] != witness.content_range
                        or reserved["stage"] != "backend_get"
                        or reserved["query_attempt_id"] != query_binding.query_attempt_id
                        or reserved["logical_query_id"] != query_binding.logical_query_id
                        or reserved["request_digest"] != witness.request_sha256
                        or terminal["raw_body_sha256"] != witness.response_sha256
                        or int(terminal["actual_response_bytes"]) != len(page.raw_body)
                        or chain_row["source_table"] != page.table
                        or chain_row["source_role"] != witness.source_role
                        or chain_row["reservation_binding_kind"] != "query_attempt"
                        or chain_row["reservation_query_attempt_id"] != query_binding.query_attempt_id
                        or chain_row["reservation_logical_query_id"] != query_binding.logical_query_id
                        or int(chain_row["generation"]) != identity.generation
                        or int(chain_row["input_seq"]) != identity.input_seq
                        or chain_row["input_digest"] != identity.input_digest
                        or int(chain_row["claim_epoch"]) != identity.claim_epoch
                        or int(chain_row["authority_epoch"]) != identity.authority_epoch
                        or int(chain_row["context_revision"]) != identity.context_revision
                    ):
                        raise reject("scoped raw GET differs from its immutable Store budget/capture rows")
                    source_receipt_id = str(uuid.uuid4())
                    receipt_by_capture[witness.capture_id] = source_receipt_id
                    raw_rows_by_capture[witness.capture_id] = raw_rows
                    table_dto_sha = codec3.stable_digest({"table": page.table, "rows": [dict(row) for row in raw_rows]})
                    source_rows_sha = codec3.stable_digest([dict(row) for row in raw_rows])
                    connection.execute(
                        """INSERT INTO p2_v3_source_get_receipts (
                            source_receipt_id,capture_id,reservation_id,reservation_event_kind,
                            owner_user_id,turn_id,cohort_sha256,binding_kind,admission_id,
                            logical_query_id,query_attempt_id,page_index,source_role,source_table,
                            request_sha256,raw_body_sha256,typed_dto_sha256,source_rows_sha256,
                            http_status,content_range,range_start,returned_count,known_total,
                            response_bytes,observed_at,elapsed_us,accepted_at
                        ) VALUES (?,?,?,'settled',?,?,?,'query_attempt',NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            source_receipt_id, witness.capture_id, witness.reservation_id,
                            str(owner_user_id), str(turn_id), cohort_sha256,
                            query_binding.logical_query_id, query_binding.query_attempt_id, page_index,
                            witness.source_role, page.table, witness.request_sha256,
                            witness.response_sha256, table_dto_sha, source_rows_sha,
                            witness.http_status, witness.content_range, page.range.offset,
                            page.range.row_count, page.range.total, len(page.raw_body),
                            _stamp(witness.observed_at), witness.elapsed_us, _stamp(acceptance_now),
                        ),
                    )

                historical = rebuilt.historical
                historical_json, historical_sha = _canonical_json(historical.model_dump(mode="json", exclude_none=False), max_bytes=262_144)
                versions_json, _ = _canonical_json(
                    [item.model_dump(mode="json", exclude_none=False) for item in historical.query_evidence.financial_versions],
                    max_bytes=8192,
                )
                qev = historical.query_evidence
                connection.execute(
                    """INSERT INTO p2_v3_query_result_receipts (
                        query_result_receipt_id,owner_user_id,turn_id,cohort_sha256,
                        logical_query_id,query_attempt_id,page_index,query_evidence_ref,query_ref,
                        criteria_digest,normalized_criteria_digest,scope_digest,
                        per_activity_financial_versions_json,historical_payload_json,
                        historical_payload_sha256,projection_sha256,source_query_complete,
                        model_projection_complete,has_more,zero_classification,source_total,
                        matched_total,page_count,observed_at,accepted_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        result_receipt_id, str(owner_user_id), str(turn_id), cohort_sha256,
                        query_binding.logical_query_id, query_binding.query_attempt_id, page_index,
                        str(qev.query_evidence_ref), str(qev.query_ref), query_row["criteria_digest"],
                        str(qev.normalized_criteria_digest), query_row["scope_digest"], versions_json,
                        historical_json, historical_sha, qev.projection_digest,
                        int(qev.source_query_complete), int(qev.model_projection_complete), int(qev.page.has_more),
                        {"nonzero": "not_zero"}.get(qev.query_zero_classification, qev.query_zero_classification),
                        qev.source_total, qev.matched_total, qev.page_count,
                        _stamp(qev.observed_at), _stamp(acceptance_now),
                    ),
                )
                for ordinal, page in enumerate(pending.query_captures):
                    connection.execute(
                        "INSERT INTO p2_v3_query_result_gets (query_result_receipt_id,owner_user_id,turn_id,ordinal,source_receipt_id) VALUES (?,?,?,?,?)",
                        (result_receipt_id, str(owner_user_id), str(turn_id), ordinal, receipt_by_capture[page.witness.capture_id]),
                    )

                def related_source_rows(fact: Any) -> list[tuple[str, list[Mapping[str, Any]]]]:
                    scope_activity = activity_id
                    kind = fact.fact_kind
                    needed: list[tuple[str, str, uuid.UUID]] = []
                    if kind == "expense":
                        expense_id = registry.resolve_entity(str(fact.expense_ref), "expense", activity_id=scope_activity)
                        needed.extend((("expenses", "id", expense_id), ("payments", "expense_id", expense_id), ("splits", "expense_id", expense_id)))
                    elif kind == "debt":
                        needed.extend((
                            ("expense_debts", "id", registry.resolve_entity(str(fact.debt_ref), "debt", activity_id=scope_activity)),
                            ("expenses", "id", registry.resolve_entity(str(fact.expense_ref), "expense", activity_id=scope_activity)),
                        ))
                    elif kind == "refund_event":
                        needed.append(("expenses", "id", registry.resolve_entity(str(fact.refund_ref), "refund", activity_id=scope_activity)))
                        if fact.parent_expense_ref is not None:
                            needed.append(("refund_parents", "id", registry.resolve_entity(str(fact.parent_expense_ref), "expense", activity_id=scope_activity)))
                    elif kind == "prepayment_account":
                        needed.append(("prepayment_accounts", "id", registry.resolve_entity(str(fact.account_ref), "prepayment_account", activity_id=scope_activity)))
                    elif kind == "prepayment_usage":
                        needed.extend((
                            ("prepayment_usages", "id", registry.resolve_entity(str(fact.usage_ref), "prepayment_usage", activity_id=scope_activity)),
                            ("prepayment_accounts", "id", registry.resolve_entity(str(fact.account_ref), "prepayment_account", activity_id=scope_activity)),
                            ("expense_debts", "id", registry.resolve_entity(str(fact.debt_ref), "debt", activity_id=scope_activity)),
                            ("expenses", "id", registry.resolve_entity(str(fact.expense_ref), "expense", activity_id=scope_activity)),
                        ))
                    elif kind == "prepayment_return_event":
                        needed.extend((
                            ("transfers", "id", registry.resolve_entity(str(fact.return_event_ref), "prepayment_return", activity_id=scope_activity)),
                            ("transfer_components", "transfer_id", registry.resolve_entity(str(fact.return_event_ref), "prepayment_return", activity_id=scope_activity)),
                        ))
                    else:
                        raise reject("scoped fact kind has no exact source relation mapping")
                    result: list[tuple[str, list[Mapping[str, Any]]]] = []
                    for alias, field_name, wanted_id in needed:
                        table = operation_tables.get(alias)
                        if table is None:
                            raise reject("scoped fact is missing one of its required joined source tables")
                        rows = [row for row in table.rows if row.get(field_name) == str(wanted_id)]
                        if not rows:
                            raise reject("scoped fact has no exact raw source row for its immutable relation")
                        result.append((alias, rows))
                    return result

                capture_position = {page.witness.capture_id: i for i, page in enumerate(pending.query_captures)}
                for ordinal, fact in enumerate(facts):
                    fact_ref = str(pe3._fact_public_ref(fact))
                    fact_json, fact_sha = _canonical_json(fact.model_dump(mode="json", exclude_none=False), max_bytes=32_768)
                    fact_proof_id = str(uuid.uuid4())
                    activity_ref = getattr(fact, "activity_ref", scope_public.activity_ref)
                    scope_ref = getattr(fact, "scope_ref", None)
                    financial_version = getattr(fact, "financial_version", None)
                    connection.execute(
                        """INSERT INTO p2_v3_query_fact_proofs (
                            fact_proof_id,query_result_receipt_id,owner_user_id,turn_id,
                            query_evidence_ref,fact_ref,fact_kind,activity_ref,scope_ref,
                            financial_version,exact_fact_json,exact_fact_sha256,created_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            fact_proof_id, result_receipt_id, str(owner_user_id), str(turn_id),
                            str(qev.query_evidence_ref), fact_ref, fact.fact_kind,
                            str(activity_ref) if activity_ref is not None else None,
                            str(scope_ref) if scope_ref is not None else None,
                            str(financial_version) if financial_version is not None else None,
                            fact_json, fact_sha, _stamp(acceptance_now),
                        ),
                    )
                    grouped_sources: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
                    for alias, source_rows in related_source_rows(fact):
                        matched_captures: list[str] = []
                        for page in pending.query_captures:
                            if capture_to_alias[page.witness.capture_id] != alias:
                                continue
                            page_rows = raw_rows_by_capture[page.witness.capture_id]
                            if any(row in page_rows for row in source_rows):
                                key = (page.witness.capture_id, page.witness.source_role)
                                grouped_sources.setdefault(key, [])
                                grouped_sources[key].extend(row for row in source_rows if row in page_rows)
                                matched_captures.append(page.witness.capture_id)
                        if not matched_captures:
                            raise reject("scoped fact source rows are detached from the query GET chain")
                    for source_ordinal, ((capture_id, role), source_rows) in enumerate(sorted(
                        grouped_sources.items(), key=lambda item: capture_position[item[0][0]],
                    )):
                        source_receipt_id = receipt_by_capture[capture_id]
                        connection.execute(
                            """INSERT INTO p2_v3_query_fact_sources (
                                fact_proof_id,owner_user_id,turn_id,ordinal,source_receipt_id,
                                source_role,source_row_sha256
                            ) VALUES (?,?,?,?,?,?,?)""",
                            (
                                fact_proof_id, str(owner_user_id), str(turn_id), source_ordinal,
                                source_receipt_id, role,
                                codec3.stable_digest([dict(row) for row in source_rows]),
                            ),
                        )
                    if not grouped_sources:
                        raise reject("scoped fact has no accepted raw source proof")
                    entity_kind, private_entity_id, private_activity_id, private_unit_id = registry.binding_for_ref(fact_ref)
                    locator_rows = connection.execute(
                        """SELECT * FROM p2_v3_entity_locators
                           WHERE owner_user_id=? AND turn_id=? AND entity_kind=? AND entity_ref=?""",
                        (str(owner_user_id), str(turn_id), entity_kind, fact_ref),
                    ).fetchall()
                    created_receipt = receipt_by_capture[next(iter(grouped_sources))[0]]
                    if len(locator_rows) > 1:
                        raise reject("scoped fact locator is ambiguous for this owner and Turn")
                    if locator_rows:
                        locator = locator_rows[0]
                        if (
                            locator["private_entity_id"] != str(private_entity_id)
                            or locator["private_activity_id"] != str(private_activity_id)
                            or locator["private_ledger_unit_id"] != (str(private_unit_id) if private_unit_id else None)
                            or locator["cohort_sha256"] != cohort_sha256
                        ):
                            raise reject("scoped fact opaque ref conflicts with its private locator")
                    else:
                        connection.execute(
                            """INSERT INTO p2_v3_entity_locators (
                                locator_id,owner_user_id,turn_id,entity_ref,entity_kind,
                                private_entity_id,private_activity_id,private_ledger_unit_id,
                                cohort_sha256,created_from_receipt_id,created_at
                            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                            (
                                str(uuid.uuid4()), str(owner_user_id), str(turn_id), fact_ref,
                                entity_kind, str(private_entity_id), str(private_activity_id),
                                str(private_unit_id) if private_unit_id else None, cohort_sha256,
                                created_receipt, _stamp(acceptance_now),
                            ),
                        )

                elapsed = max(0, (time.monotonic_ns() - processing_started_ns) // 1000)
                if elapsed > processing_limit_us:
                    raise reject("scoped Store source acceptance exceeded its processing budget")
                self._p2_v3_settle_processing_in_transaction(
                    connection, owner_user_id=owner_user_id, turn_id=turn_id,
                    claim_token=claim_token, reservation_id=processing_id,
                    actual_us=elapsed, now=_now(None),
                )
                self._fault("p2_v3.query_acceptance.before_commit")
            registry._accepted_receipt_by_capture_ref[str(rebuilt.historical.query_evidence.query_evidence_ref)] = result_receipt_id
            return P2V3AcceptedReadPage(
                accepted_page_id=str(uuid.uuid4()), historical=rebuilt.historical,
                query_result_receipt_id=result_receipt_id,
                _logical_query_id=query_binding.logical_query_id,
                _query_attempt_id=query_binding.query_attempt_id,
                _attempt_seq=int(attempt_row["attempt_seq"]),
                _admission_id=binding.admission_id, _page_index=page_index, _store=self,
                _registry=registry, _identity=identity, _claim_token=claim_token,
                _seal=_P2_V3_ACCEPTED_READ_PAGE_SEAL,
            )
        except BaseException as original:
            try:
                self.settle_p2_v3_stage(owner_user_id, turn_id, processing_id, outcome="unknown", now=_now(None))
            except BaseException:
                if not isinstance(original, Exception):
                    raise original
            raise

    def accept_p2_v3_query_attempt(
        self,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        *,
        claim_token: str,
        principal_user_id: uuid.UUID,
        pending: Any,
        now: Optional[datetime] = None,
    ) -> P2V3AcceptedReadPage:
        """Accept the first read-only Activities page after Store rechecks its raw GETs.

        The first runnable vertical slice intentionally accepts only an
        unscoped ``read.activities`` page.  No caller-provided fact projection
        or digest is trusted: the Store strictly decodes each captured body,
        reconstructs the facts and historical projection, then writes the
        source/result receipts and private proof links in one transaction.
        """
        from . import p2_read_backend as backend3
        from . import p2_read_contracts_v3 as pc3
        from . import p2_source_codec_v3 as codec3
        from . import p2_event_contracts_v3 as pe3

        self._require_started()
        if type(owner_user_id) is not uuid.UUID or type(turn_id) is not uuid.UUID:
            raise P2V3StoreConflict("source acceptance requires an owner and Turn UUID")
        if type(principal_user_id) is not uuid.UUID or principal_user_id != owner_user_id:
            raise P2V3StoreConflict("verified principal does not own this source Turn")
        if not isinstance(pending, backend3.P2V3PendingSourceAttempt):
            raise P2V3StoreConflict("source acceptance requires the adapter's private pending attempt")
        binding = pending.admission
        query_binding = pending.query_binding
        registry = binding.reference_registry
        if not isinstance(binding, codec3.AdmissionOnlyBinding) or not isinstance(query_binding, codec3.QueryAttemptBinding):
            raise P2V3StoreConflict("source acceptance has no exact admission/query binding")
        if not isinstance(registry, P2V3RequestReferenceRegistry):
            raise P2V3StoreConflict("source acceptance requires the Store-issued reference registry")
        registry._assert_store_issued(
            self, identity=binding.identity, admission_id=binding.admission_id,
            claim_token=claim_token,
        )
        identity = binding.identity
        if pending.request.operation is not pc3.P2ReadOperation.ACTIVITIES:
            return self._accept_p2_v3_scoped_query_attempt(
                owner_user_id, turn_id, claim_token=claim_token,
                principal_user_id=principal_user_id, pending=pending, now=now,
            )
        if (
            identity.owner_user_id != owner_user_id or identity.turn_id != turn_id
            or query_binding.identity != identity or binding.claim_token != claim_token
            or registry.principal_user_id != principal_user_id
            or pending.request.operation is not pc3.P2ReadOperation.ACTIVITIES
            or pending.request.scope is not None
            or pending.admission_projection is not None
            or pending.bootstrap_captures
            or pending.resolved_scope_ids
            or query_binding.page_index != 0
        ):
            raise P2V3StoreConflict("this Store slice only accepts unscoped first-page Activities reads")
        if pending.context_version is None or not pending.context_version.strip():
            raise P2V3StoreConflict("Activity facts require a server context version")
        if pending.projection.historical.operation is not pc3.P2ReadOperation.ACTIVITIES:
            raise P2V3StoreConflict("pending historical projection has another operation")
        if pending.projection.historical.page.has_more:
            raise P2V3StoreConflict("multi-page model projection is not yet accepted by this Store slice")

        instant = _now(now)
        with self._connection() as connection:
            initial, current, _ = self._p2_v3_current_claim(
                connection, owner_user_id, turn_id, claim_token=claim_token, now=instant,
            )
            turn_row = connection.execute(
                "SELECT * FROM p2_v3_turns WHERE turn_id=? AND owner_user_id=?",
                (str(turn_id), str(owner_user_id)),
            ).fetchone()
            admission_row = connection.execute(
                "SELECT * FROM p2_v3_source_admissions WHERE admission_id=? AND owner_user_id=? AND turn_id=?",
                (binding.admission_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            query_row = connection.execute(
                "SELECT * FROM p2_v3_queries WHERE logical_query_id=? AND owner_user_id=? AND turn_id=?",
                (query_binding.logical_query_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            attempt_row = connection.execute(
                "SELECT * FROM p2_v3_query_attempts WHERE attempt_id=? AND logical_query_id=? AND owner_user_id=? AND turn_id=?",
                (query_binding.query_attempt_id, query_binding.logical_query_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            descriptor_row = connection.execute(
                "SELECT * FROM p2_v3_query_descriptor_bindings WHERE logical_query_id=? AND owner_user_id=? AND turn_id=?",
                (query_binding.logical_query_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            if any(item is None for item in (turn_row, admission_row, query_row, attempt_row, descriptor_row)):
                raise P2V3StoreNotFound("current source admission, query, or attempt is unavailable")
            self._require_current_p2_v3_pin(connection, turn_row)
            pinned, pin = self._verify_p2_v3_execution_pin_rows(connection, turn_row)
            if not pinned or pin is None:
                raise P2V3UnsupportedProfile("source acceptance requires the current immutable execution pin")
            expected_identity = (
                owner_user_id, turn_id, current.generation, current.input_seq,
                current.input_digest, current.claim_epoch, current.authority_epoch,
                current.context_revision,
            )
            if (
                (identity.owner_user_id, identity.turn_id, identity.generation, identity.input_seq,
                 identity.input_digest, identity.claim_epoch, identity.authority_epoch, identity.context_revision)
                    != expected_identity
                or admission_row["generation"] != current.generation
                or admission_row["input_seq"] != current.input_seq
                or admission_row["input_digest"] != current.input_digest
                or admission_row["claim_epoch"] != current.claim_epoch
                or admission_row["authority_epoch"] != current.authority_epoch
                or admission_row["context_revision"] != current.context_revision
                or admission_row["public_scope_digest"] != query_row["scope_digest"]
                or query_row["operation"] != pc3.P2ReadOperation.ACTIVITIES.value
                or query_row["admission_id"] != descriptor_row["admission_id"]
                or query_row["generation"] != current.generation
                or query_row["input_seq"] != current.input_seq
                or query_row["input_digest"] != current.input_digest
                or query_row["authority_epoch"] != descriptor_row["authority_epoch"]
                or query_row["criteria_digest"] != attempt_row["criteria_digest"]
                or query_row["scope_digest"] != attempt_row["scope_digest"]
                or attempt_row["admission_id"] != binding.admission_id
                or attempt_row["generation"] != current.generation
                or attempt_row["authority_epoch"] != current.authority_epoch
                or attempt_row["page_index"] != 0
                or attempt_row["attempt_state"] != "started"
                or descriptor_row["cohort_sha256"] != pin["cohort_sha256"]
                or descriptor_row["normalized_criteria_digest"] != pending.query_evidence.normalized_criteria_digest
            ):
                raise P2V3StoreConflict("pending Activities read is stale or differs from its immutable Store query")
            criteria_json, criteria_digest, scope_json, scope_digest = _wire_query_descriptor(
                query_row["operation"], pending.request.criteria, pending.request.scope,
            )
            if (
                criteria_json != query_row["criteria_json"] or criteria_digest != query_row["criteria_digest"]
                or scope_json != query_row["scope_json"] or scope_digest != query_row["scope_digest"]
                or pending.request.profile_id != P2_V3_CANDIDATE_PROFILE_ID
                or pending.request.versions.model_dump(mode="json") != P2_V3_VERSIONS
            ):
                raise P2V3StoreConflict("pending Activities request differs from the immutable query descriptor")
            if registry._configured_source_origin is None:
                raise P2V3StoreConflict("configured source origin was not pinned before the first GET")
            cohort_sha256 = pin["cohort_sha256"]

        # Reserve acceptance CPU before reparsing. The fixed bound is charged
        # once with the accepted receipts; if the transaction fails, the
        # reservation is conservatively settled as unknown below.
        processing_limit_us = P2_V3_METADATA_ACCEPTANCE_CAP_US
        processing_id = self.reserve_p2_v3_stage(
            owner_user_id, turn_id, claim_token=claim_token, stage="backend_processing",
            active_limit_us=processing_limit_us, backend_limit_us=processing_limit_us, now=instant,
        )
        try:
            self.mark_p2_v3_dispatch_started(
                owner_user_id, turn_id, processing_id, claim_token=claim_token, now=instant,
            )
        except BaseException:
            # The durable marker may have committed before an exception.
            # Leave the reservation for the existing recovery path.
            raise
        processing_started_ns = time.monotonic_ns()

        def reject(message: str, cause: BaseException | None = None) -> P2V3StoreConflict:
            error = P2V3StoreConflict(message)
            if cause is not None:
                error.__cause__ = cause
            return error

        try:
            query_pages: dict[str, list[Any]] = {"activity_members": [], "activities": []}
            parsed_rows: dict[str, list[Mapping[str, Any]]] = {"activity_members": [], "activities": []}
            source_roles = {"activity_members": "membership", "activities": "activity"}
            if not pending.query_captures or len(pending.query_captures) > 32:
                raise reject("Activities query capture chain is empty or exceeds its bound")
            expected_tables = {"activity_members", "activities"}
            if any(page.table not in expected_tables for page in pending.query_captures):
                raise reject("Activities query contains a non-allowlisted source table")
            for page in pending.query_captures:
                witness = page.witness
                if (
                    witness.binding_kind != "query_attempt"
                    or witness.admission_id is not None
                    or witness.logical_query_id != query_binding.logical_query_id
                    or witness.query_attempt_id != query_binding.query_attempt_id
                    or witness.page_index != query_binding.page_index
                    or witness.owner_user_id != owner_user_id or witness.turn_id != turn_id
                    or witness.generation != identity.generation or witness.input_seq != identity.input_seq
                    or witness.input_digest != identity.input_digest or witness.claim_epoch != identity.claim_epoch
                    or witness.authority_epoch != identity.authority_epoch
                    or witness.context_revision != identity.context_revision
                    or witness.source_role != source_roles[page.table]
                    or witness.capture_id == "" or witness.reservation_id != page.reservation_id
                    or type(page.raw_body) is not bytes or len(page.raw_body) > P2_V3_MAX_GET_RESPONSE_BYTES
                    or len(page.raw_body) != witness.response_bytes
                    or _digest(page.raw_body) != witness.response_sha256
                    or _digest(page.raw_body) != page.raw_body_sha256
                    or page.status != witness.http_status or page.content_range != witness.content_range
                    or page.observed_at.tzinfo is None or page.observed_at.utcoffset() is None
                ):
                    raise reject("Activities raw capture does not match its exact query attempt witness")
                parts = urlsplit(page.request_url)
                if (
                    parts.scheme != "https" or not parts.hostname or parts.username is not None
                    or parts.password is not None or parts.fragment or not parts.query
                    or parts.netloc.lower() != registry._configured_source_origin[1]
                    or parts.path != f"/rest/v1/{page.table}" or len(page.request_url) > 12_000
                ):
                    raise reject("Activities source GET is outside the configured PostgREST origin")
                try:
                    raw_rows = codec3.parse_source_rows(page.raw_body, page.table)
                    query_pairs = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)
                    page_range = codec3.parse_content_range(
                        page.content_range, expected_offset=page.offset,
                        row_count=len(raw_rows), status=page.status,
                    )
                except Exception as exc:
                    raise reject("Activities raw source page failed strict JSON/range parsing", exc)
                if page_range != page.range or codec3.stable_digest([dict(row) for row in raw_rows]) != codec3.stable_digest([dict(row) for row in page.rows]):
                    raise reject("Activities raw source page differs from its adapter rows or parsed range")
                query_pages[page.table].append(dataclasses.replace(page, rows=raw_rows, range=page_range))
                parsed_rows[page.table].extend(raw_rows)

            def build_table(table: str) -> Any:
                pages = query_pages[table]
                if not pages:
                    if table == "activities" and not parsed_rows["activity_members"]:
                        return backend3.P2ReadBackendAdapter._v3_empty_table(table)
                    raise reject(f"Activities source is missing the required {table} GET")
                try:
                    result = codec3.source_table(parsed_rows[table], pages, table=table)
                except Exception as exc:
                    raise reject(f"Activities {table} pages are not a complete unique chain", exc)
                if not result.complete or not result.range_contiguous or not result.unique_items_verified:
                    raise reject(f"Activities {table} source is incomplete")
                return result

            memberships = build_table("activity_members")
            member_activity_ids = tuple(uuid.UUID(row["activity_id"]) for row in memberships.rows)
            if len(member_activity_ids) != len(set(member_activity_ids)) or any(
                uuid.UUID(row["user_id"]) != principal_user_id for row in memberships.rows
            ):
                raise reject("Activities membership rows do not all belong to the verified principal")
            if member_activity_ids and not query_pages["activities"]:
                raise reject("Activities rows were not fetched for the verified member set")
            activities = build_table("activities")
            activity_ids = tuple(uuid.UUID(row["id"]) for row in activities.rows)
            if set(activity_ids) != set(member_activity_ids) or len(activity_ids) != len(set(activity_ids)):
                raise reject("Activities rows do not exactly match the current verified membership set")

            order_by_table = {"activity_members": "activity_id.asc", "activities": "id.asc"}
            source_columns = codec3._SOURCE_COLUMNS
            for table in ("activity_members", "activities"):
                for page in query_pages[table]:
                    parts = urlsplit(page.request_url)
                    expected_filters = (
                        [("user_id", f"eq.{principal_user_id}")]
                        if table == "activity_members"
                        else [("id", "in.(" + ",".join(str(item) for item in member_activity_ids) + ")")]
                    )
                    expected_query = urlencode([
                        ("select", ",".join(source_columns[table])), *expected_filters,
                        ("order", order_by_table[table]), ("limit", "16"), ("offset", str(page.offset)),
                    ])
                    if parts.query != expected_query:
                        raise reject("Activities GET query does not match the fixed source plan")

            tables = {"activity_members": memberships, "activities": activities}
            order_captures = tuple(page.witness for page in pending.query_captures)
            input_tables = dict(pending.query_tables)
            if set(input_tables) != set(tables):
                raise reject("Activities adapter table set differs from the strict Store source set")
            for table in tables:
                if codec3.stable_digest([dict(row) for row in input_tables[table].rows]) != codec3.stable_digest([dict(row) for row in tables[table].rows]):
                    raise reject("Activities adapter table rows differ from strict raw-source decode")

            query_ref = registry.query_ref(query_binding.logical_query_id, identity=identity)
            source_ref = registry.source_ref(query_binding.logical_query_id, identity=identity, source_kind="activities")
            qev_ref = registry.query_evidence_ref(
                query_binding.logical_query_id, query_binding.query_attempt_id,
                identity=identity, page_index=0,
            )
            result_ref = registry.result_ref(
                query_binding.logical_query_id, query_binding.query_attempt_id,
                identity=identity, page_index=0,
            )
            # The persisted query row keeps the private descriptor digest
            # (exclude_none=False). Public QueryEvidence follows the reviewed
            # grant digest (exclude_none=True), so bind the ref to that exact
            # public value rather than aliasing the private audit digest.
            public_criteria_sha = pc3.p2_criteria_digest(pending.request.criteria)
            criteria_ref = registry.criteria_ref(public_criteria_sha, identity=identity)
            try:
                facts = codec3.project_facts(
                    pc3.P2ReadOperation.ACTIVITIES, tables, None, pending.request,
                    query_evidence_ref=qev_ref, binder=registry,
                    principal_user_id=principal_user_id, context_version=pending.context_version,
                )
            except Exception as exc:
                raise reject("Activities source facts failed independent relationship validation", exc)
            if len(facts) > codec3.MAX_FACTS_PER_PAGE:
                raise reject("Activities fact projection requires a page that this slice does not yet issue")

            capture_state = backend3._V3QueryCaptureState(
                operation=pc3.P2ReadOperation.ACTIVITIES, binding=query_binding,
            )
            capture_state.tables.update(tables)
            capture_state.captures.extend(order_captures)
            capture_state.source_pages = len(order_captures)
            capture_state.table_pages.update({table: len(query_pages[table]) for table in tables})
            builder = object.__new__(backend3.P2ReadBackendAdapter)
            builder._turn_state = None
            builder._v3_budget_port = object()
            builder._v3_locator_port = registry
            rebuilt_projection = builder._v3_build_preaccept_projection(
                pc3.P2ReadOperation.ACTIVITIES, pending.request, pending.descriptor,
                capture_state, tables, primary_table="activities" if member_activity_ids else "activity_members",
                all_facts=facts, page_facts=facts, page_index=0, has_more=False,
                query_ref=query_ref, result_ref=result_ref, evidence_ref=qev_ref,
                criteria_ref=criteria_ref, source_ref=source_ref,
                criteria_sha=public_criteria_sha, source_version_fenced=False,
            )
            rebuilt_dump = rebuilt_projection.historical.model_dump(mode="json", exclude_none=False)
            pending_dump = pending.projection.historical.model_dump(mode="json", exclude_none=False)
            if rebuilt_dump != pending_dump:
                changed_fields = sorted(
                    key for key in set(rebuilt_dump) | set(pending_dump)
                    if rebuilt_dump.get(key) != pending_dump.get(key)
                )
                if "query_evidence" in changed_fields:
                    rebuilt_qev = rebuilt_dump.get("query_evidence") or {}
                    pending_qev = pending_dump.get("query_evidence") or {}
                    qev_fields = sorted(
                        key for key in set(rebuilt_qev) | set(pending_qev)
                        if rebuilt_qev.get(key) != pending_qev.get(key)
                    )
                    changed_fields = ["query_evidence." + key for key in qev_fields]
                # Field names are static schema metadata; never put source values
                # or model text into this failure path.
                raise reject(
                    "Activities historical projection differs from Store-rebuilt source facts: "
                    + ",".join(changed_fields)
                )
            if pending.query_evidence.query_digest != rebuilt_projection.historical.query_evidence.query_digest:
                raise reject("Activities QueryEvidence digest does not bind the actual captured GET chain")

            source_receipt_ids: dict[str, str] = {}
            result_receipt_id = str(uuid.uuid4())
            collection_proof_id = str(uuid.uuid4())
            private_collection_locator_id = str(uuid.uuid4())
            fact_proof_by_ref: dict[str, str] = {}
            activity_locator_by_ref: dict[str, str] = {}
            acceptance_now = _now(None)
            with self._transaction() as connection:
                _, current, _ = self._p2_v3_current_claim(
                    connection, owner_user_id, turn_id, claim_token=claim_token, now=acceptance_now,
                )
                fresh_turn = connection.execute(
                    "SELECT * FROM p2_v3_turns WHERE turn_id=? AND owner_user_id=?",
                    (str(turn_id), str(owner_user_id)),
                ).fetchone()
                self._require_current_p2_v3_pin(connection, fresh_turn)
                fresh_pin_ok, fresh_pin = self._verify_p2_v3_execution_pin_rows(connection, fresh_turn)
                fresh_attempt = connection.execute(
                    "SELECT * FROM p2_v3_query_attempts WHERE attempt_id=? AND logical_query_id=? AND owner_user_id=? AND turn_id=?",
                    (query_binding.query_attempt_id, query_binding.logical_query_id, str(owner_user_id), str(turn_id)),
                ).fetchone()
                if (
                    not fresh_pin_ok or fresh_pin is None or fresh_pin["cohort_sha256"] != cohort_sha256
                    or current.generation != identity.generation or current.input_seq != identity.input_seq
                    or current.input_digest != identity.input_digest or current.claim_epoch != identity.claim_epoch
                    or current.authority_epoch != identity.authority_epoch or current.context_revision != identity.context_revision
                    or fresh_attempt is None or fresh_attempt["attempt_state"] != "started"
                    or fresh_attempt["admission_id"] != binding.admission_id
                ):
                    raise reject("Activities source acceptance lost its current claim, admission, or attempt")
                if connection.execute(
                    "SELECT 1 FROM p2_v3_query_result_receipts WHERE logical_query_id=? AND query_attempt_id=? AND page_index=0",
                    (query_binding.logical_query_id, query_binding.query_attempt_id),
                ).fetchone() is not None:
                    raise reject("Activities query page already has an immutable result receipt")

                chain_rows = connection.execute(
                    """SELECT r.*, c.stage, t.event_kind AS terminal_kind,
                              t.actual_active_us, t.actual_backend_us, t.actual_response_bytes,
                              t.raw_body_sha256 AS settled_body_sha
                       FROM p2_v3_capture_chain_reservations r
                       JOIN p2_v3_charge_events c ON c.reservation_id=r.reservation_id AND c.event_kind='reserved'
                       LEFT JOIN p2_v3_charge_events t ON t.reservation_id=r.reservation_id
                            AND t.event_kind IN ('settled','known_no_dispatch','unknown')
                       WHERE r.owner_user_id=? AND r.turn_id=? AND r.capture_chain_kind='query_attempt'
                         AND r.capture_chain_id=? ORDER BY r.chain_sequence""",
                    (str(owner_user_id), str(turn_id), query_binding.query_attempt_id),
                ).fetchall()
                if [row["reservation_id"] for row in chain_rows] != [page.reservation_id for page in pending.query_captures]:
                    raise reject("Activities source captures differ from the exact Store GET reservation chain")

                receipt_by_capture: dict[str, str] = {}
                page_by_capture: dict[str, Any] = {}
                row_receipt: dict[tuple[str, str], str] = {}
                for ordinal, (page, chain_row) in enumerate(zip(pending.query_captures, chain_rows, strict=True)):
                    witness = page.witness
                    stored_capture = connection.execute(
                        "SELECT * FROM p2_v3_wire_captures WHERE capture_id=? AND owner_user_id=? AND turn_id=?",
                        (witness.capture_id, str(owner_user_id), str(turn_id)),
                    ).fetchone()
                    reserved = connection.execute(
                        "SELECT * FROM p2_v3_charge_events WHERE reservation_id=? AND owner_user_id=? AND turn_id=? AND event_kind='reserved'",
                        (witness.reservation_id, str(owner_user_id), str(turn_id)),
                    ).fetchone()
                    terminal = connection.execute(
                        "SELECT * FROM p2_v3_charge_events WHERE reservation_id=? AND owner_user_id=? AND turn_id=? AND event_kind='settled'",
                        (witness.reservation_id, str(owner_user_id), str(turn_id)),
                    ).fetchone()
                    if stored_capture is None or reserved is None or terminal is None or chain_row["terminal_kind"] != "settled":
                        raise reject("Activities GET lacks its Store-settled capture and budget records")
                    if (
                        stored_capture["capture_state"] != "cost_only"
                        or stored_capture["reservation_id"] != witness.reservation_id
                        or stored_capture["query_attempt_id"] != query_binding.query_attempt_id
                        or stored_capture["logical_query_id"] != query_binding.logical_query_id
                        or stored_capture["admission_id"] is not None
                        or stored_capture["page_index"] != query_binding.page_index
                        or stored_capture["generation"] != identity.generation
                        or stored_capture["claim_epoch"] != identity.claim_epoch
                        or stored_capture["authority_epoch"] != identity.authority_epoch
                        or stored_capture["context_revision"] != identity.context_revision
                        or stored_capture["source_role"] != source_roles[page.table]
                        or stored_capture["request_digest"] != witness.request_sha256
                        or stored_capture["raw_body_sha256"] != witness.response_sha256
                        or int(stored_capture["response_bytes"]) != len(page.raw_body)
                        or int(stored_capture["http_status"]) != witness.http_status
                        or stored_capture["content_range"] != witness.content_range
                        or reserved["stage"] != "backend_get"
                        or reserved["query_attempt_id"] != query_binding.query_attempt_id
                        or reserved["logical_query_id"] != query_binding.logical_query_id
                        or chain_row["source_table"] != page.table
                        or chain_row["source_role"] != source_roles[page.table]
                        or reserved["request_digest"] != witness.request_sha256
                        or terminal["raw_body_sha256"] != witness.response_sha256
                        or int(terminal["actual_response_bytes"]) != len(page.raw_body)
                        or chain_row["source_table"] != page.table
                        or chain_row["source_role"] != source_roles[page.table]
                        or chain_row["reservation_binding_kind"] != "query_attempt"
                        or chain_row["reservation_query_attempt_id"] != query_binding.query_attempt_id
                        or chain_row["reservation_logical_query_id"] != query_binding.logical_query_id
                        or int(chain_row["generation"]) != identity.generation
                        or int(chain_row["input_seq"]) != identity.input_seq
                        or chain_row["input_digest"] != identity.input_digest
                        or int(chain_row["claim_epoch"]) != identity.claim_epoch
                        or int(chain_row["authority_epoch"]) != identity.authority_epoch
                        or int(chain_row["context_revision"]) != identity.context_revision
                    ):
                        raise reject("Activities raw GET does not match its immutable Store budget/capture records")
                    source_receipt_id = str(uuid.uuid4())
                    receipt_by_capture[witness.capture_id] = source_receipt_id
                    source_receipt_ids[witness.capture_id] = source_receipt_id
                    page_by_capture[witness.capture_id] = page
                    raw_rows = codec3.parse_source_rows(page.raw_body, page.table)
                    table_dto_sha = codec3.stable_digest({"table": page.table, "rows": [dict(row) for row in raw_rows]})
                    source_rows_sha = codec3.stable_digest([dict(row) for row in raw_rows])
                    connection.execute(
                        """INSERT INTO p2_v3_source_get_receipts (
                            source_receipt_id,capture_id,reservation_id,reservation_event_kind,
                            owner_user_id,turn_id,cohort_sha256,binding_kind,admission_id,
                            logical_query_id,query_attempt_id,page_index,source_role,source_table,
                            request_sha256,raw_body_sha256,typed_dto_sha256,source_rows_sha256,
                            http_status,content_range,range_start,returned_count,known_total,
                            response_bytes,observed_at,elapsed_us,accepted_at
                        ) VALUES (?,?,?,'settled',?,?,?,'query_attempt',NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            source_receipt_id, witness.capture_id, witness.reservation_id,
                            str(owner_user_id), str(turn_id), cohort_sha256,
                            query_binding.logical_query_id, query_binding.query_attempt_id, query_binding.page_index,
                            source_roles[page.table], page.table, witness.request_sha256,
                            witness.response_sha256, table_dto_sha, source_rows_sha,
                            witness.http_status, witness.content_range, page.range.offset,
                            page.range.row_count, page.range.total, len(page.raw_body),
                            _stamp(witness.observed_at), witness.elapsed_us, _stamp(acceptance_now),
                        ),
                    )
                    if page.table == "activities":
                        for row in raw_rows:
                            row_receipt[(page.table, str(row["id"]))] = source_receipt_id
                    else:
                        for row in raw_rows:
                            row_receipt[(page.table, str(row["activity_id"]))] = source_receipt_id

                historical = rebuilt_projection.historical
                historical_json, historical_sha = _canonical_json(
                    historical.model_dump(mode="json", exclude_none=False), max_bytes=262_144,
                )
                per_activity_versions_json, _ = _canonical_json(
                    [item.model_dump(mode="json", exclude_none=False) for item in historical.query_evidence.financial_versions],
                    max_bytes=8192,
                )
                qev = historical.query_evidence
                result_projection_sha = qev.projection_digest
                query_id = query_binding.logical_query_id
                connection.execute(
                    """INSERT INTO p2_v3_query_result_receipts (
                        query_result_receipt_id,owner_user_id,turn_id,cohort_sha256,
                        logical_query_id,query_attempt_id,page_index,query_evidence_ref,query_ref,
                        criteria_digest,normalized_criteria_digest,scope_digest,
                        per_activity_financial_versions_json,historical_payload_json,
                        historical_payload_sha256,projection_sha256,source_query_complete,
                        model_projection_complete,has_more,zero_classification,source_total,
                        matched_total,page_count,observed_at,accepted_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        result_receipt_id, str(owner_user_id), str(turn_id), cohort_sha256,
                        query_id, query_binding.query_attempt_id, 0, str(qev.query_evidence_ref),
                        str(qev.query_ref), query_row["criteria_digest"],
                        str(qev.normalized_criteria_digest), query_row["scope_digest"],
                        per_activity_versions_json, historical_json, historical_sha,
                        result_projection_sha, int(qev.source_query_complete),
                        int(qev.model_projection_complete), int(qev.page.has_more),
                        {"nonzero": "not_zero"}.get(qev.query_zero_classification, qev.query_zero_classification),
                        qev.source_total, qev.matched_total, qev.page_count,
                        _stamp(qev.observed_at), _stamp(acceptance_now),
                    ),
                )
                for ordinal, page in enumerate(pending.query_captures):
                    connection.execute(
                        "INSERT INTO p2_v3_query_result_gets (query_result_receipt_id,owner_user_id,turn_id,ordinal,source_receipt_id) VALUES (?,?,?,?,?)",
                        (result_receipt_id, str(owner_user_id), str(turn_id), ordinal, receipt_by_capture[page.witness.capture_id]),
                    )

                private_collection_query_id = str(uuid.UUID(query_id))
                collection_locator_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"p2-v3-collection:{owner_user_id}:{turn_id}:{query_id}"))
                complete_zero_kind = qev.query_zero_classification if qev.query_zero_classification in {"backend_zero", "post_filter_zero"} else None
                connection.execute(
                    """INSERT INTO p2_v3_activity_collection_qev_proofs (
                        collection_proof_id,query_result_receipt_id,owner_user_id,turn_id,
                        query_evidence_ref,private_collection_query_id,private_collection_locator_id,
                        criteria_digest,normalized_criteria_digest,complete_zero_kind,created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        collection_proof_id, result_receipt_id, str(owner_user_id), str(turn_id),
                        str(qev.query_evidence_ref), private_collection_query_id, collection_locator_id,
                        query_row["criteria_digest"], str(qev.normalized_criteria_digest),
                        complete_zero_kind, _stamp(acceptance_now),
                    ),
                )

                activity_capture_ids = {page.witness.capture_id for page in pending.query_captures if page.table == "activities"}
                membership_capture_ids = {page.witness.capture_id for page in pending.query_captures if page.table == "activity_members"}
                membership_receipt_by_id: dict[str, str] = {}
                for page in pending.query_captures:
                    if page.table == "activity_members":
                        for row in codec3.parse_source_rows(page.raw_body, page.table):
                            membership_receipt_by_id[str(row["activity_id"])] = receipt_by_capture[page.witness.capture_id]

                visible_refs = [str(item.activity_ref) for item in facts]
                if visible_refs != [str(item) for item in qev.matching_fact_refs]:
                    raise reject("Activities fact references differ from QueryEvidence membership")
                for ordinal, fact in enumerate(facts):
                    activity_ref = str(fact.activity_ref)
                    activity_id = registry.resolve_activity_ref(activity_ref)
                    activity_row = next((row for row in activities.rows if row["id"] == str(activity_id)), None)
                    membership_row = next((row for row in memberships.rows if row["activity_id"] == str(activity_id)), None)
                    if activity_row is None or membership_row is None:
                        raise reject("projected Activity has no exact current Activity and membership source rows")
                    activity_source_receipt = row_receipt.get(("activities", str(activity_id)))
                    membership_source_receipt = membership_receipt_by_id.get(str(activity_id))
                    if activity_source_receipt is None or membership_source_receipt is None:
                        raise reject("projected Activity source receipts are unavailable")

                    entity_rows = connection.execute(
                        "SELECT * FROM p2_v3_entity_locators WHERE owner_user_id=? AND turn_id=? AND entity_kind='activity' AND entity_ref=? ORDER BY locator_id",
                        (str(owner_user_id), str(turn_id), activity_ref),
                    ).fetchall()
                    if len(entity_rows) > 1:
                        raise reject("Activity locator is ambiguous for this owner and Turn")
                    if entity_rows:
                        locator_row = entity_rows[0]
                        if (
                            locator_row["private_entity_id"] != str(activity_id)
                            or locator_row["private_activity_id"] != str(activity_id)
                            or locator_row["private_ledger_unit_id"] is not None
                            or locator_row["cohort_sha256"] != cohort_sha256
                        ):
                            raise reject("Activity opaque ref conflicts with its private locator")
                        activity_locator_id = locator_row["locator_id"]
                    else:
                        activity_locator_id = str(uuid.uuid4())
                        connection.execute(
                            """INSERT INTO p2_v3_entity_locators (
                                locator_id,owner_user_id,turn_id,entity_ref,entity_kind,
                                private_entity_id,private_activity_id,private_ledger_unit_id,
                                cohort_sha256,created_from_receipt_id,created_at
                            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                            (
                                activity_locator_id, str(owner_user_id), str(turn_id), activity_ref,
                                "activity", str(activity_id), str(activity_id), None, cohort_sha256,
                                activity_source_receipt, _stamp(acceptance_now),
                            ),
                        )
                    activity_locator_by_ref[activity_ref] = activity_locator_id
                    fact_json, fact_sha = _canonical_json(fact.model_dump(mode="json", exclude_none=False), max_bytes=32768)
                    fact_proof_id = str(uuid.uuid4())
                    fact_proof_by_ref[activity_ref] = fact_proof_id
                    connection.execute(
                        """INSERT INTO p2_v3_query_fact_proofs (
                            fact_proof_id,query_result_receipt_id,owner_user_id,turn_id,
                            query_evidence_ref,fact_ref,fact_kind,activity_ref,scope_ref,
                            financial_version,exact_fact_json,exact_fact_sha256,created_at
                        ) VALUES (?,?,?,?,?,?,'activity',?,NULL,NULL,?,?,?)""",
                        (
                            fact_proof_id, result_receipt_id, str(owner_user_id), str(turn_id),
                            str(qev.query_evidence_ref), activity_ref, activity_ref,
                            fact_json, fact_sha, _stamp(acceptance_now),
                        ),
                    )
                    for source_ordinal, (source_receipt, role, source_row) in enumerate((
                        (activity_source_receipt, "activity", activity_row),
                        (membership_source_receipt, "membership", membership_row),
                    )):
                        connection.execute(
                            """INSERT INTO p2_v3_query_fact_sources (
                                fact_proof_id,owner_user_id,turn_id,ordinal,source_receipt_id,
                                source_role,source_row_sha256
                            ) VALUES (?,?,?,?,?,?,?)""",
                            (
                                fact_proof_id, str(owner_user_id), str(turn_id), source_ordinal,
                                source_receipt, role, codec3.stable_digest(dict(source_row)),
                            ),
                        )
                    membership_proof_id = str(uuid.uuid4())
                    connection.execute(
                        """INSERT INTO p2_v3_activity_collection_members (
                            collection_proof_id,owner_user_id,turn_id,ordinal,activity_ref,
                            private_activity_locator_id,private_membership_proof_id,
                            activity_source_receipt_id,membership_source_receipt_id
                        ) VALUES (?,?,?,?,?,?,?,?,?)""",
                        (
                            collection_proof_id, str(owner_user_id), str(turn_id), ordinal,
                            activity_ref, activity_locator_id, membership_proof_id,
                            activity_source_receipt, membership_source_receipt,
                        ),
                    )

                processing_actual_us = max(0, (time.monotonic_ns() - processing_started_ns) // 1000)
                if processing_actual_us > processing_limit_us:
                    raise reject("Activities Store source acceptance exceeded its processing budget")
                self._p2_v3_settle_processing_in_transaction(
                    connection, owner_user_id=owner_user_id, turn_id=turn_id,
                    claim_token=claim_token, reservation_id=processing_id,
                    actual_us=processing_actual_us, now=_now(None),
                )
                self._fault("p2_v3.query_acceptance.before_commit")

            # Only a successful durable receipt can activate this request-local
            # result handle. The registry never contains a grant or raw body.
            for evidence_ref in (str(rebuilt_projection.historical.query_evidence.query_evidence_ref),):
                registry._accepted_receipt_by_capture_ref[evidence_ref] = result_receipt_id
            return P2V3AcceptedReadPage(
                accepted_page_id=str(uuid.uuid4()), historical=rebuilt_projection.historical,
                query_result_receipt_id=result_receipt_id,
                _logical_query_id=query_binding.logical_query_id,
                _query_attempt_id=query_binding.query_attempt_id,
                _attempt_seq=int(attempt_row["attempt_seq"]),
                _admission_id=binding.admission_id, _page_index=0, _store=self,
                _registry=registry, _identity=identity, _claim_token=claim_token,
                _seal=_P2_V3_ACCEPTED_READ_PAGE_SEAL,
            )
        except BaseException as original:
            try:
                self.settle_p2_v3_stage(
                    owner_user_id, turn_id, processing_id, outcome="unknown",
                    now=_now(None),
                )
            except BaseException:
                if not isinstance(original, Exception):
                    raise original
            raise

    def issue_p2_v3_page(
        self,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        *,
        claim_token: str,
        accepted_page: P2V3AcceptedReadPage,
        now: Optional[datetime] = None,
    ) -> Any:
        """Create a live result only from a committed Store receipt, once per handle."""
        from . import p2_read_contracts_v3 as pc3
        from . import p2_event_contracts_v3 as pe3

        if (
            not isinstance(accepted_page, P2V3AcceptedReadPage)
            or accepted_page._seal is not _P2_V3_ACCEPTED_READ_PAGE_SEAL
            or accepted_page._store is not self
            or accepted_page._identity.owner_user_id != owner_user_id
            or accepted_page._identity.turn_id != turn_id
            or accepted_page._claim_token != claim_token
            or accepted_page._issue_state.get("issued", False)
        ):
            raise P2V3StoreConflict("page issue requires this Store's fresh accepted result handle")
        instant = _now(now)
        next_page_ref: str | None = None
        proof: Any = None
        claim_until: datetime | None = None
        with self._transaction() as connection:
            _, snapshot, aggregate = self._p2_v3_current_claim(
                connection, owner_user_id, turn_id, claim_token=claim_token, now=instant,
            )
            receipt = connection.execute(
                "SELECT * FROM p2_v3_query_result_receipts WHERE query_result_receipt_id=? AND owner_user_id=? AND turn_id=?",
                (accepted_page.query_result_receipt_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            query = connection.execute(
                "SELECT * FROM p2_v3_queries WHERE logical_query_id=? AND owner_user_id=? AND turn_id=?",
                (accepted_page._logical_query_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            attempt = connection.execute(
                "SELECT * FROM p2_v3_query_attempts WHERE attempt_id=? AND logical_query_id=? AND owner_user_id=? AND turn_id=?",
                (accepted_page._query_attempt_id, accepted_page._logical_query_id, str(owner_user_id), str(turn_id)),
            ).fetchone()
            if receipt is None or query is None or attempt is None:
                raise P2V3StoreNotFound("accepted result receipt is unavailable")
            if (
                receipt["page_index"] != accepted_page._page_index
                or receipt["cohort_sha256"] != accepted_page._registry._cohort_sha256
                or receipt["query_evidence_ref"] != str(accepted_page.historical.query_evidence.query_evidence_ref)
                or receipt["historical_payload_sha256"] != _canonical_json(
                    accepted_page.historical.model_dump(mode="json", exclude_none=False), max_bytes=262_144,
                )[1]
                or int(receipt["has_more"]) != int(accepted_page.historical.page.has_more)
                or attempt["attempt_seq"] != accepted_page._attempt_seq
                or attempt["page_index"] != accepted_page._page_index
                or attempt["attempt_state"] != "started"
                or query["criteria_digest"] != receipt["criteria_digest"]
                or query["scope_digest"] != receipt["scope_digest"]
                or snapshot.generation != accepted_page._identity.generation
                or snapshot.input_seq != accepted_page._identity.input_seq
                or snapshot.input_digest != accepted_page._identity.input_digest
                or snapshot.claim_epoch != accepted_page._identity.claim_epoch
                or snapshot.authority_epoch != accepted_page._identity.authority_epoch
                or snapshot.context_revision != accepted_page._identity.context_revision
            ):
                raise P2V3StoreConflict("accepted page no longer matches the current source/query/Turn receipt")
            get_links = connection.execute(
                "SELECT source_receipt_id FROM p2_v3_query_result_gets WHERE query_result_receipt_id=? AND owner_user_id=? AND turn_id=? ORDER BY ordinal",
                (accepted_page.query_result_receipt_id, str(owner_user_id), str(turn_id)),
            ).fetchall()
            if not get_links:
                raise P2V3StoreConflict("accepted page has no source GET receipt links")
            claim_until = aggregate.claim_until
            if accepted_page.historical.page.has_more:
                if (
                    accepted_page._page_index != 0
                    or accepted_page.historical.page.page_index != 0
                    or accepted_page.historical.query_evidence.matched_count <= 16
                    or accepted_page.historical.query_evidence.matched_count > 32
                    or not accepted_page.historical.query_evidence.source_query_complete
                    or accepted_page.historical.query_evidence.model_projection_complete
                    or claim_until is None
                ):
                    raise P2V3StoreConflict("only a complete bounded page-zero receipt can issue one continuation")
                proof = self._p2_v3_continuation_proof_from_receipt(receipt)
            elif accepted_page._page_index not in (0, 1):
                raise P2V3StoreConflict("accepted page index is outside the one-continuation bound")

        try:
            historical = pe3.P2V3HistoricalReadPayload.model_validate_json(
                receipt["historical_payload_json"], strict=True,
            )
        except Exception as exc:
            raise P2V3StoreConflict("accepted historical source result failed Store readback") from exc
        if historical.model_dump(mode="json", exclude_none=False) != accepted_page.historical.model_dump(mode="json", exclude_none=False):
            raise P2V3StoreConflict("accepted result handle differs from its immutable Store readback")
        if accepted_page.historical.page.has_more:
            assert proof is not None and claim_until is not None
            next_page_ref = accepted_page._registry.issue_continuation(
                logical_query_id=accepted_page._logical_query_id,
                query_attempt_id=accepted_page._query_attempt_id,
                attempt_seq=accepted_page._attempt_seq,
                page_index=accepted_page._page_index,
                source_proof=proof,
                projection_sha256=historical.query_evidence.projection_digest,
                expires_at=claim_until,
                identity=accepted_page._identity,
            )
        result = pc3.P2ReadBackendResult(
            operation=historical.operation,
            query_evidence=historical.query_evidence,
            page=pc3.P2PageProjection(
                items=historical.page.items, completeness=historical.page.completeness,
                has_more=historical.page.has_more, next_page_ref=next_page_ref,
                page_index=historical.page.page_index,
                range_contiguous=historical.page.range_contiguous,
                stable_total_verified=historical.page.stable_total_verified,
                source_version_fenced=historical.page.source_version_fenced,
                unique_items_verified=historical.page.unique_items_verified,
                expected_total=historical.page.expected_total,
            ),
        )
        accepted_page._issue_state["issued"] = True
        return result

    @staticmethod
    def _p2_v3_metadata_projection_digest(projection: Any) -> str:
        from . import p2_source_codec_v3 as codec3

        return codec3.stable_digest({
            "current_actor": (
                projection.current_actor.model_dump(mode="json", exclude_none=False)
                if projection.current_actor is not None else None
            ),
            "source_labels": [
                item.model_dump(mode="json", exclude_none=False)
                for item in projection.source_labels
            ],
            "snapshot_digest": projection.snapshot_digest,
            "scope_kind": projection.snapshot.scope_kind,
            "scope_ref": projection.snapshot.scope_ref,
        })

    @staticmethod
    def _p2_v3_metadata_output_digest(output: Any) -> str:
        _, digest = _canonical_json({
            "current_actor": (
                output.current_actor.model_dump(mode="json", exclude_none=False)
                if output.current_actor is not None else None
            ),
            "source_labels": [
                item.model_dump(mode="json", exclude_none=False)
                for item in output.source_labels
            ],
        }, max_bytes=65_536)
        return digest

    def _p2_v3_accepted_metadata_binding(
        self,
        connection: sqlite3.Connection,
        *,
        accepted_page: P2V3AcceptedReadPage,
        output: Any,
        identity: Any,
        pin: Any,
    ) -> Optional[dict[str, Any]]:
        """Bind public answer metadata to the Store-accepted admission receipt set."""
        registry = accepted_page._registry
        projection = registry.accepted_metadata_projection_or_none(
            identity=identity, admission_id=accepted_page._admission_id,
        )
        if projection is None:
            if output.source_labels or output.current_actor is not None:
                raise P2V3StoreConflict("protected answer metadata has no accepted admission projection")
            return None
        if (
            output.source_labels != tuple(projection.source_labels)
            or output.current_actor != projection.current_actor
        ):
            raise P2V3StoreConflict("protected answer metadata differs from the accepted admission projection")

        acceptance_id = registry._accepted_acceptance_id
        if type(acceptance_id) is not str or not acceptance_id:
            raise P2V3StoreConflict("accepted metadata projection has no durable acceptance identity")
        batch = connection.execute(
            """SELECT * FROM p2_v3_metadata_acceptance_batches
               WHERE acceptance_id=? AND owner_user_id=? AND turn_id=?""",
            (acceptance_id, str(identity.owner_user_id), str(identity.turn_id)),
        ).fetchone()
        if batch is None or (
            batch["admission_id"] != accepted_page._admission_id
            or batch["cohort_sha256"] != pin["cohort_sha256"]
            or int(batch["generation"]) != identity.generation
            or int(batch["input_seq"]) != identity.input_seq
            or batch["input_digest"] != identity.input_digest
            or int(batch["claim_epoch"]) != identity.claim_epoch
            or int(batch["authority_epoch"]) != identity.authority_epoch
            or int(batch["context_revision"]) != identity.context_revision
            or batch["projection_sha256"] != self._p2_v3_metadata_projection_digest(projection)
        ):
            raise P2V3StoreConflict("metadata acceptance batch differs from the accepted projection or Turn")

        accepted_proofs = registry.accepted_metadata_proofs(
            identity=identity, admission_id=accepted_page._admission_id,
        )
        if not 1 <= len(accepted_proofs) <= 128:
            raise P2V3StoreConflict("accepted metadata proof set is outside protected output bounds")
        expected_proofs = [
            {
                "ordinal": ordinal,
                "metadata_proof_id": str(proof.private_proof_id),
                "source_receipt_id": registry.accepted_receipt_id(
                    str(proof.source_receipt_ref), identity=identity,
                    admission_id=accepted_page._admission_id,
                ),
            }
            for ordinal, proof in enumerate(accepted_proofs)
        ]
        _, proof_set_sha = _canonical_json(expected_proofs, max_bytes=65_536)
        proof_rows = connection.execute(
            """SELECT ordinal,metadata_proof_id,source_receipt_id
               FROM p2_v3_metadata_acceptance_proofs WHERE acceptance_id=?
               ORDER BY ordinal""",
            (acceptance_id,),
        ).fetchall()
        stored_proofs = [
            {
                "ordinal": int(row["ordinal"]),
                "metadata_proof_id": row["metadata_proof_id"],
                "source_receipt_id": row["source_receipt_id"],
            }
            for row in proof_rows
        ]
        events = connection.execute(
            """SELECT event_seq,event_kind,observation_outcome
               FROM p2_v3_metadata_acceptance_events WHERE acceptance_id=?
               ORDER BY event_seq""",
            (acceptance_id,),
        ).fetchall()
        postcommit = [row for row in events if row["event_kind"] == "postcommit_observation"]
        if (
            stored_proofs != expected_proofs
            or len(stored_proofs) != int(batch["proof_count"])
            or proof_set_sha != batch["proof_set_sha256"]
            or not any(int(row["event_seq"]) == 2 and row["event_kind"] == "finalized" for row in events)
            or not postcommit or postcommit[-1]["observation_outcome"] != "within_cap"
        ):
            raise P2V3StoreConflict("metadata acceptance receipt set is incomplete or differs from its projection")
        return {
            "acceptance_id": acceptance_id,
            "projection_sha256": batch["projection_sha256"],
            "proof_set_sha256": batch["proof_set_sha256"],
            "output_metadata_sha256": self._p2_v3_metadata_output_digest(output),
            "proofs": expected_proofs,
        }

    def _p2_v3_readback_metadata_binding(
        self,
        connection: sqlite3.Connection,
        *,
        output_row: sqlite3.Row,
        historical_output: Any,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
    ) -> Optional[dict[str, Any]]:
        """Verify persisted output metadata links and return their hash material."""
        acceptance_rows = connection.execute(
            """SELECT oa.ordinal AS output_ordinal,oa.acceptance_id,b.*
               FROM p2_v3_output_metadata_acceptances oa
               JOIN p2_v3_metadata_acceptance_batches b
                 ON b.acceptance_id=oa.acceptance_id
                AND b.owner_user_id=oa.owner_user_id AND b.turn_id=oa.turn_id
               WHERE oa.protected_output_id=? AND oa.owner_user_id=? AND oa.turn_id=?
               ORDER BY oa.ordinal""",
            (output_row["protected_output_id"], str(owner_user_id), str(turn_id)),
        ).fetchall()
        output_links = connection.execute(
            """SELECT ordinal,metadata_proof_id FROM p2_v3_output_metadata_links
               WHERE protected_output_id=? AND owner_user_id=? AND turn_id=? ORDER BY ordinal""",
            (output_row["protected_output_id"], str(owner_user_id), str(turn_id)),
        ).fetchall()
        if not acceptance_rows:
            if output_links or historical_output.source_labels or historical_output.current_actor is not None:
                raise P2V3StoreConflict("protected output metadata is detached from an accepted admission")
            return None
        if len(acceptance_rows) != 1 or int(acceptance_rows[0]["output_ordinal"]) != 0:
            raise P2V3StoreConflict("protected output has an ambiguous accepted metadata binding")
        batch = acceptance_rows[0]
        if (
            batch["cohort_sha256"] != output_row["cohort_sha256"]
            or int(batch["generation"]) != int(output_row["generation"])
            or int(batch["input_seq"]) != int(output_row["input_seq"])
            or batch["input_digest"] != output_row["input_digest"]
            or int(batch["context_revision"]) != int(output_row["context_revision"])
            or re.fullmatch(r"[0-9a-f]{64}", batch["projection_sha256"] or "") is None
        ):
            raise P2V3StoreConflict("protected output metadata acceptance is stale for its output")
        proof_rows = connection.execute(
            """SELECT ap.ordinal,ap.metadata_proof_id,ap.source_receipt_id,
                      p.source_receipt_id AS proof_source_receipt_id,
                      r.binding_kind,r.admission_id,r.cohort_sha256 AS receipt_cohort_sha256
               FROM p2_v3_metadata_acceptance_proofs ap
               JOIN p2_v3_metadata_source_proofs p
                 ON p.metadata_proof_id=ap.metadata_proof_id
                AND p.owner_user_id=ap.owner_user_id AND p.turn_id=ap.turn_id
               JOIN p2_v3_source_get_receipts r
                 ON r.source_receipt_id=ap.source_receipt_id
                AND r.owner_user_id=ap.owner_user_id AND r.turn_id=ap.turn_id
               WHERE ap.acceptance_id=? AND ap.owner_user_id=? AND ap.turn_id=?
               ORDER BY ap.ordinal""",
            (batch["acceptance_id"], str(owner_user_id), str(turn_id)),
        ).fetchall()
        proofs = [
            {
                "ordinal": int(row["ordinal"]),
                "metadata_proof_id": row["metadata_proof_id"],
                "source_receipt_id": row["source_receipt_id"],
            }
            for row in proof_rows
        ]
        linked = [
            {"ordinal": int(row["ordinal"]), "metadata_proof_id": row["metadata_proof_id"]}
            for row in output_links
        ]
        _, acceptance_proof_sha = _canonical_json(proofs, max_bytes=65_536)
        events = connection.execute(
            """SELECT event_seq,event_kind,observation_outcome
               FROM p2_v3_metadata_acceptance_events WHERE acceptance_id=?
               ORDER BY event_seq""",
            (batch["acceptance_id"],),
        ).fetchall()
        postcommit = [row for row in events if row["event_kind"] == "postcommit_observation"]
        if (
            len(proofs) != int(batch["proof_count"])
            or [item["ordinal"] for item in proofs] != list(range(len(proofs)))
            or [
                {"ordinal": item["ordinal"], "metadata_proof_id": item["metadata_proof_id"]}
                for item in proofs
            ] != linked
            or acceptance_proof_sha != batch["proof_set_sha256"]
            or any(
                row["proof_source_receipt_id"] != row["source_receipt_id"]
                or row["binding_kind"] != "admission"
                or row["admission_id"] != batch["admission_id"]
                or row["receipt_cohort_sha256"] != batch["cohort_sha256"]
                for row in proof_rows
            )
            or not any(int(row["event_seq"]) == 2 and row["event_kind"] == "finalized" for row in events)
            or not postcommit or postcommit[-1]["observation_outcome"] != "within_cap"
        ):
            raise P2V3StoreConflict("protected output metadata links do not match finalized accepted receipts")
        return {
            "acceptance_id": batch["acceptance_id"],
            "projection_sha256": batch["projection_sha256"],
            "proof_set_sha256": batch["proof_set_sha256"],
            "output_metadata_sha256": self._p2_v3_metadata_output_digest(historical_output),
            "proofs": proofs,
        }

    def _persist_p2_v3_protected_output_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        owner_user_id: uuid.UUID,
        after: Any,
        checkpoint: Any,
        appended_events: Any,
        protected_output: P2V3ProtectedOutputCommit,
        claim_token: str,
        now: datetime,
    ) -> None:
        """Persist one Store-issued source-backed answer with its canonical events."""
        from . import p2_event_contracts_v3 as pe3
        from .contracts import EventType, TurnState, TurnStep

        accepted_page = protected_output.accepted_page
        output = protected_output.historical_output
        if (
            not isinstance(accepted_page, P2V3AcceptedReadPage)
            or accepted_page._seal is not _P2_V3_ACCEPTED_READ_PAGE_SEAL
            or accepted_page._store is not self
            or accepted_page._identity.owner_user_id != owner_user_id
            or accepted_page._identity.turn_id != after.turn_id
            or accepted_page._claim_token != claim_token
            or not accepted_page._issue_state.get("issued", False)
            or accepted_page._issue_state.get("protected_output_committed", False)
        ):
            raise P2V3StoreConflict("protected output requires this Store's fresh issued page handle")
        if type(output) is not pe3.P2V3HistoricalAnswer:
            raise P2V3StoreConflict("protected output requires the strict historical answer")
        if (
            after.owner_user_id != owner_user_id
            or after.turn_id != accepted_page._identity.turn_id
            or after.state is not TurnState.COMPLETED
            or after.step is not TurnStep.TERMINAL
            or checkpoint.generation != accepted_page._identity.generation
            or checkpoint.resume_step is not None
        ):
            raise P2V3StoreConflict("protected output is detached from its completing candidate Turn")

        _, current, _ = self._p2_v3_current_claim(
            connection, owner_user_id, after.turn_id, claim_token=claim_token, now=now,
        )
        identity = accepted_page._identity
        if (
            current.generation != identity.generation
            or current.input_seq != identity.input_seq
            or current.input_digest != identity.input_digest
            or current.claim_epoch != identity.claim_epoch
            or current.authority_epoch != identity.authority_epoch
            or current.context_revision != identity.context_revision
        ):
            raise P2V3StoreConflict("protected output page is stale for the current Turn claim")
        turn_row = connection.execute(
            "SELECT * FROM p2_v3_turns WHERE turn_id=? AND owner_user_id=?",
            (str(after.turn_id), str(owner_user_id)),
        ).fetchone()
        pin_ok, pin = self._verify_p2_v3_execution_pin_rows(connection, turn_row)
        if not pin_ok or pin is None or pin["cohort_sha256"] != accepted_page._registry._cohort_sha256:
            raise P2V3UnsupportedProfile("protected output has no matching current execution pin")
        metadata_binding = self._p2_v3_accepted_metadata_binding(
            connection, accepted_page=accepted_page, output=output,
            identity=identity, pin=pin,
        )

        receipt = connection.execute(
            """SELECT * FROM p2_v3_query_result_receipts
               WHERE query_result_receipt_id=? AND owner_user_id=? AND turn_id=?""",
            (accepted_page.query_result_receipt_id, str(owner_user_id), str(after.turn_id)),
        ).fetchone()
        query = connection.execute(
            """SELECT * FROM p2_v3_queries
               WHERE logical_query_id=? AND owner_user_id=? AND turn_id=?""",
            (accepted_page._logical_query_id, str(owner_user_id), str(after.turn_id)),
        ).fetchone()
        attempt = connection.execute(
            """SELECT * FROM p2_v3_query_attempts
               WHERE attempt_id=? AND logical_query_id=? AND owner_user_id=? AND turn_id=?""",
            (accepted_page._query_attempt_id, accepted_page._logical_query_id,
             str(owner_user_id), str(after.turn_id)),
        ).fetchone()
        if receipt is None or query is None or attempt is None:
            raise P2V3StoreNotFound("protected output source receipt is unavailable")
        historical_json, historical_sha = _canonical_json(
            accepted_page.historical.model_dump(mode="json", exclude_none=False), max_bytes=262_144,
        )
        if (
            receipt["page_index"] != accepted_page._page_index
            or receipt["cohort_sha256"] != pin["cohort_sha256"]
            or receipt["historical_payload_json"] != historical_json
            or receipt["historical_payload_sha256"] != historical_sha
            or receipt["query_evidence_ref"] != str(accepted_page.historical.query_evidence.query_evidence_ref)
            or receipt["has_more"] != 0
            or query["criteria_digest"] != receipt["criteria_digest"]
            or query["scope_digest"] != receipt["scope_digest"]
            or attempt["attempt_seq"] != accepted_page._attempt_seq
            or attempt["attempt_state"] != "started"
            or attempt["criteria_digest"] != receipt["criteria_digest"]
            or attempt["scope_digest"] != receipt["scope_digest"]
        ):
            raise P2V3StoreConflict("protected output source receipt no longer matches the accepted page")

        qev = accepted_page.historical.query_evidence
        output_fact_refs = tuple(str(pe3._fact_public_ref(item)) for item in output.fact_cards)
        complete_fact_refs = tuple(str(item) for item in qev.matching_fact_refs)
        if (
            output.basis != "fresh_read_receipts"
            or output.turn_ref != accepted_page._registry.owner_turn_ref(identity=identity)
            or output.generation != identity.generation
            or output.context_revision != identity.context_revision
            or output.simulation is not qev.simulation
            or output.query_evidence != (qev,)
            or output.citations != (qev.query_evidence_ref,)
            or output_fact_refs != complete_fact_refs
            or any(item.query_evidence_ref != qev.query_evidence_ref for item in output.fact_cards)
            or accepted_page._page_index not in (0, 1)
        ):
            raise P2V3StoreConflict("protected answer does not exactly bind the accepted source page")

        message_events = [item for item in appended_events if item.event.type == EventType.MESSAGE]
        if len(message_events) != 1:
            raise P2V3StoreConflict("protected answer requires one canonical message event")
        event_seq = int(message_events[0].seq)
        if event_seq < 1:
            raise P2V3StoreConflict("protected answer canonical event sequence is invalid")

        fact_links: list[tuple[int, str, str, str, str]] = []
        for ordinal, fact in enumerate(output.fact_cards):
            fact_ref = str(pe3._fact_public_ref(fact))
            proof = connection.execute(
                """SELECT fact_proof_id,exact_fact_json,exact_fact_sha256,fact_kind
                   FROM p2_v3_query_fact_proofs
                   WHERE query_result_receipt_id=? AND owner_user_id=? AND turn_id=? AND fact_ref=?""",
                (accepted_page.query_result_receipt_id, str(owner_user_id), str(after.turn_id), fact_ref),
            ).fetchone()
            card_json, card_sha = _canonical_json(
                fact.model_dump(mode="json", exclude_none=False), max_bytes=32_768,
            )
            if (
                proof is None
                or proof["fact_kind"] != fact.fact_kind
                or proof["exact_fact_json"] != card_json
                or proof["exact_fact_sha256"] != card_sha
            ):
                raise P2V3StoreConflict("protected answer contains a fact without its exact accepted proof")
            fact_links.append((ordinal, fact_ref, proof["fact_proof_id"], card_json, card_sha))

        _, proof_set_sha = _canonical_json({
            "query_receipts": [{
                "query_result_receipt_id": accepted_page.query_result_receipt_id,
                "query_evidence_ref": str(qev.query_evidence_ref),
            }],
            "facts": [{"fact_ref": fact_ref, "fact_proof_id": proof_id, "fact_sha256": fact_sha}
                      for _, fact_ref, proof_id, _, fact_sha in fact_links],
            "metadata": metadata_binding,
        }, max_bytes=65_536)
        output_json, output_sha = _canonical_json(
            output.model_dump(mode="json", exclude_none=False), max_bytes=262_144,
        )
        protected_output_id = str(uuid.uuid4())
        connection.execute(
            """INSERT INTO p2_v3_protected_outputs (
                protected_output_id,owner_user_id,turn_id,cohort_sha256,event_seq,
                output_kind,provenance_kind,historical_payload_json,historical_payload_sha256,
                generation,input_seq,input_digest,context_revision,proof_set_sha256,created_at
            ) VALUES (?,?,?,?,?,'answer','source_bearing',?,?,?,?,?,?,?,?)""",
            (
                protected_output_id, str(owner_user_id), str(after.turn_id), pin["cohort_sha256"],
                event_seq, output_json, output_sha, identity.generation,
                identity.input_seq, identity.input_digest, identity.context_revision,
                proof_set_sha, _stamp(now),
            ),
        )
        for ordinal, fact_ref, proof_id, card_json, card_sha in fact_links:
            connection.execute(
                """INSERT INTO p2_v3_output_fact_links (
                    protected_output_id,owner_user_id,turn_id,card_ordinal,fact_proof_id,
                    public_card_json,public_card_sha256
                ) VALUES (?,?,?,?,?,?,?)""",
                (protected_output_id, str(owner_user_id), str(after.turn_id), ordinal,
                 proof_id, card_json, card_sha),
            )
        connection.execute(
            """INSERT INTO p2_v3_output_query_links (
                protected_output_id,owner_user_id,turn_id,ordinal,query_result_receipt_id,query_evidence_ref
            ) VALUES (?,?,?,0,?,?)""",
            (protected_output_id, str(owner_user_id), str(after.turn_id),
             accepted_page.query_result_receipt_id, str(qev.query_evidence_ref)),
        )
        if metadata_binding is not None:
            connection.execute(
                """INSERT INTO p2_v3_output_metadata_acceptances (
                    protected_output_id,owner_user_id,turn_id,ordinal,acceptance_id
                ) VALUES (?,?,?,0,?)""",
                (protected_output_id, str(owner_user_id), str(after.turn_id),
                 metadata_binding["acceptance_id"]),
            )
            connection.executemany(
                """INSERT INTO p2_v3_output_metadata_links (
                    protected_output_id,owner_user_id,turn_id,ordinal,metadata_proof_id
                ) VALUES (?,?,?,?,?)""",
                [
                    (protected_output_id, str(owner_user_id), str(after.turn_id),
                     proof["ordinal"], proof["metadata_proof_id"])
                    for proof in metadata_binding["proofs"]
                ],
            )
        connection.execute(
            """INSERT INTO p2_v3_output_event_links (
                protected_output_id,owner_user_id,turn_id,event_seq
            ) VALUES (?,?,?,?)""",
            (protected_output_id, str(owner_user_id), str(after.turn_id), event_seq),
        )

    def commit_p2_v3_protected_output(
        self,
        owner_user_id: uuid.UUID,
        after: Any,
        *,
        expected_state_revision: int,
        expected_checkpoint_revision: int,
        claim_token: str,
        checkpoint: Any,
        events: Any,
        accepted_page: P2V3AcceptedReadPage,
        historical_output: Any,
        gate: Any,
        event_sources: Any = None,
        now: Optional[datetime] = None,
    ) -> Any:
        """Atomically complete the Turn and attach one source-backed answer."""
        from . import p2_event_contracts_v3 as pe3
        from .contracts import EventType, TurnState, TurnStep
        from .ports import AgentControlSnapshot

        if not isinstance(gate, AgentControlSnapshot) or gate.enabled is not True:
            raise P2V3StoreConflict("protected output requires a fresh enabled server control snapshot")
        if type(gate.disable_revision) is not int or gate.disable_revision < 0:
            raise P2V3StoreConflict("protected output control revision is invalid")
        if gate.source not in {"server_config", "simulation"}:
            raise P2V3StoreConflict("protected output control source is not trusted")
        if not isinstance(accepted_page, P2V3AcceptedReadPage):
            raise P2V3StoreConflict("protected output requires a Store-accepted page handle")
        if (
            accepted_page._seal is not _P2_V3_ACCEPTED_READ_PAGE_SEAL
            or accepted_page._store is not self
            or accepted_page._identity.owner_user_id != owner_user_id
            or accepted_page._identity.turn_id != after.turn_id
            or accepted_page._claim_token != claim_token
            or not accepted_page._issue_state.get("issued", False)
            or accepted_page._issue_state.get("protected_output_committed", False)
        ):
            raise P2V3StoreConflict("protected output requires this Turn's issued, unused page handle")
        if type(historical_output) is not pe3.P2V3HistoricalAnswer:
            raise P2V3StoreConflict("this output slice accepts only a strict historical answer")
        try:
            output = pe3.P2V3HistoricalAnswer.model_validate_json(
                historical_output.model_dump_json(), strict=True,
            )
        except Exception as exc:
            raise P2V3StoreConflict("historical answer failed strict Store revalidation") from exc
        if (
            output.basis != "fresh_read_receipts"
            or output.turn_ref != accepted_page._registry.owner_turn_ref(identity=accepted_page._identity)
            or output.generation != accepted_page._identity.generation
            or output.context_revision != accepted_page._identity.context_revision
            or output.simulation is not accepted_page.historical.query_evidence.simulation
            or output.query_evidence != (accepted_page.historical.query_evidence,)
            or output.citations != (accepted_page.historical.query_evidence.query_evidence_ref,)
            or tuple(str(pe3._fact_public_ref(item)) for item in output.fact_cards)
                != tuple(str(item) for item in accepted_page.historical.query_evidence.matching_fact_refs)
            or any(
                item.query_evidence_ref != accepted_page.historical.query_evidence.query_evidence_ref
                for item in output.fact_cards
            )
            or accepted_page.historical.page.has_more
        ):
            raise P2V3StoreConflict("historical answer does not exactly cite the issued source page")
        if (
            after.turn_id != accepted_page._identity.turn_id
            or after.owner_user_id != owner_user_id
            or after.state != TurnState.COMPLETED
            or after.step != TurnStep.TERMINAL
            or checkpoint.resume_step is not None
        ):
            raise P2V3StoreConflict("protected answer must complete its same candidate Turn and clear resume_step")
        try:
            if type(events) not in (list, tuple) or len(events) != 2:
                raise ValueError
            message_events = [item for item in events if item.type == EventType.MESSAGE]
            status_events = [item for item in events if item.type == EventType.STATUS]
            if len(message_events) != 1 or len(status_events) != 1:
                raise ValueError
            message = message_events[0]
            status = status_events[0]
            if (
                message.payload.text != output.text
                or message.payload.citations
                or message.simulation is not output.simulation
                or status.payload.state != TurnState.COMPLETED
                or status.payload.step != TurnStep.TERMINAL
                or status.payload.state_revision != after.state_revision
                or status.simulation is not output.simulation
            ):
                raise ValueError
        except (AttributeError, TypeError, ValueError):
            raise P2V3StoreConflict("canonical message/status events do not match the protected answer") from None

        commit = P2V3ProtectedOutputCommit(
            accepted_page=accepted_page, historical_output=output, gate=gate,
        )
        result = self.transition_turn(
            owner_user_id, after,
            expected_state_revision=expected_state_revision,
            expected_checkpoint_revision=expected_checkpoint_revision,
            events=events, event_sources=event_sources, checkpoint=checkpoint,
            claim_token=claim_token,
            candidate_profile_id=P2_V3_CANDIDATE_PROFILE_ID,
            p2_v3_protected_output=commit,
            now=now,
        )
        accepted_page._issue_state["protected_output_committed"] = True
        return result

    def get_p2_v3_protected_event_activity_ids(
        self,
        owner_user_id: uuid.UUID,
        turn_id: uuid.UUID,
        *,
        event_seq: int,
    ) -> Optional[P2V3StoredProtectedOutput]:
        """Read a committed candidate sidecar and its source-bound Activity IDs.

        ``None`` means the event sequence is not a protected candidate output;
        callers must then use their existing event path.  IDs are recovered
        only from immutable output/query/fact/member links and private
        locators.  This method does not authorize the current bearer; the API
        must recheck membership before returning the canonical event.
        """
        from . import p2_event_contracts_v3 as pe3
        from .contracts import AGENT_EVENT_ADAPTER, EventType

        if type(owner_user_id) is not uuid.UUID or type(turn_id) is not uuid.UUID:
            raise ValueError("protected event lookup requires owner and Turn UUIDs")
        if type(event_seq) is not int or event_seq < 1:
            raise ValueError("protected event lookup requires a positive event sequence")

        with self._connection() as connection:
            rows = connection.execute(
                """SELECT o.*, e.owner_user_id AS event_owner_user_id,
                          e.turn_id AS event_turn_id, e.seq AS stored_event_seq,
                          e.event_type, e.event_json
                   FROM p2_v3_output_event_links l
                   JOIN p2_v3_protected_outputs o
                     ON o.protected_output_id=l.protected_output_id
                    AND o.owner_user_id=l.owner_user_id AND o.turn_id=l.turn_id
                   JOIN events e ON e.turn_id=l.turn_id AND e.seq=l.event_seq
                   WHERE l.owner_user_id=? AND l.turn_id=? AND l.event_seq=?""",
                (str(owner_user_id), str(turn_id), event_seq),
            ).fetchall()
            if not rows:
                return None
            if len(rows) != 1:
                raise P2V3StoreConflict("protected event link is ambiguous")
            output_row = rows[0]
            if (
                output_row["event_owner_user_id"] != str(owner_user_id)
                or output_row["event_turn_id"] != str(turn_id)
                or int(output_row["stored_event_seq"]) != event_seq
                or output_row["event_type"] != EventType.MESSAGE.value
                or output_row["output_kind"] != "answer"
                or output_row["provenance_kind"] != "source_bearing"
            ):
                raise P2V3StoreConflict("protected event link is not a source-backed message answer")

            query_links = connection.execute(
                """SELECT l.*, r.* FROM p2_v3_output_query_links l
                   JOIN p2_v3_query_result_receipts r
                     ON r.query_result_receipt_id=l.query_result_receipt_id
                    AND r.owner_user_id=l.owner_user_id AND r.turn_id=l.turn_id
                   WHERE l.protected_output_id=? AND l.owner_user_id=? AND l.turn_id=?
                   ORDER BY l.ordinal""",
                (output_row["protected_output_id"], str(owner_user_id), str(turn_id)),
            ).fetchall()
            if len(query_links) != 1 or int(query_links[0]["ordinal"]) != 0:
                raise P2V3StoreConflict("protected event does not have its exact single accepted query receipt")
            query_link = query_links[0]
            linked_gets = connection.execute(
                """SELECT r.* FROM p2_v3_query_result_gets g
                   JOIN p2_v3_source_get_receipts r
                     ON r.source_receipt_id=g.source_receipt_id
                    AND r.owner_user_id=g.owner_user_id AND r.turn_id=g.turn_id
                   WHERE g.query_result_receipt_id=? AND g.owner_user_id=? AND g.turn_id=?
                   ORDER BY g.ordinal""",
                (query_link["query_result_receipt_id"], str(owner_user_id), str(turn_id)),
            ).fetchall()
            if not linked_gets:
                raise P2V3StoreConflict("protected event query receipt has no accepted source GETs")

            fact_links = connection.execute(
                """SELECT l.*, f.fact_ref, f.fact_kind, f.activity_ref, f.scope_ref,
                          f.query_result_receipt_id, f.query_evidence_ref,
                          f.exact_fact_json, f.exact_fact_sha256
                   FROM p2_v3_output_fact_links l
                   JOIN p2_v3_query_fact_proofs f
                     ON f.fact_proof_id=l.fact_proof_id
                    AND f.owner_user_id=l.owner_user_id AND f.turn_id=l.turn_id
                   WHERE l.protected_output_id=? AND l.owner_user_id=? AND l.turn_id=?
                   ORDER BY l.card_ordinal""",
                (output_row["protected_output_id"], str(owner_user_id), str(turn_id)),
            ).fetchall()
            collection = connection.execute(
                """SELECT * FROM p2_v3_activity_collection_qev_proofs
                   WHERE query_result_receipt_id=? AND owner_user_id=? AND turn_id=?""",
                (query_link["query_result_receipt_id"], str(owner_user_id), str(turn_id)),
            ).fetchone()
            members = []
            if collection is not None:
                members = connection.execute(
                    """SELECT * FROM p2_v3_activity_collection_members
                       WHERE collection_proof_id=? AND owner_user_id=? AND turn_id=?
                       ORDER BY ordinal""",
                    (collection["collection_proof_id"], str(owner_user_id), str(turn_id)),
                ).fetchall()

        output_json = output_row["historical_payload_json"]
        output_sha = hashlib.sha256(output_json.encode("utf-8")).hexdigest()
        if output_sha != output_row["historical_payload_sha256"]:
            raise P2V3StoreConflict("protected event sidecar hash does not match its immutable row")
        try:
            historical_output = pe3.P2V3HistoricalAnswer.model_validate_json(output_json, strict=True)
            source_result = pe3.P2V3HistoricalReadPayload.model_validate_json(
                query_link["historical_payload_json"], strict=True,
            )
            canonical_event = AGENT_EVENT_ADAPTER.validate_json(output_row["event_json"])
        except Exception as exc:
            raise P2V3StoreConflict("protected event sidecar, receipt, or canonical event failed strict parsing") from exc
        with self._connection() as connection:
            metadata_binding = self._p2_v3_readback_metadata_binding(
                connection, output_row=output_row, historical_output=historical_output,
                owner_user_id=owner_user_id, turn_id=turn_id,
            )
        output_fact_refs = tuple(str(pe3._fact_public_ref(item)) for item in historical_output.fact_cards)
        receipt_sha = hashlib.sha256(query_link["historical_payload_json"].encode("utf-8")).hexdigest()
        if (
            receipt_sha != query_link["historical_payload_sha256"]
            or int(output_row["event_seq"]) != event_seq
            or canonical_event.seq != event_seq
            or canonical_event.type != EventType.MESSAGE
            or canonical_event.payload.text != historical_output.text
            or canonical_event.payload.citations
            or canonical_event.simulation is not historical_output.simulation
            or historical_output.profile_id != P2_V3_CANDIDATE_PROFILE_ID
            or historical_output.kind != "answer"
            or historical_output.basis != "fresh_read_receipts"
            or len(historical_output.query_evidence) != 1
            or historical_output.query_evidence[0] != source_result.query_evidence
            or output_fact_refs != tuple(str(item) for item in source_result.query_evidence.matching_fact_refs)
            or any(
                item.query_evidence_ref != source_result.query_evidence.query_evidence_ref
                for item in historical_output.fact_cards
            )
            or historical_output.citations != (query_link["query_evidence_ref"],)
            or str(source_result.query_evidence.query_evidence_ref) != query_link["query_evidence_ref"]
            or str(source_result.query_evidence.query_evidence_ref) != query_link["query_evidence_ref"]
            or int(output_row["generation"]) != historical_output.generation
            or int(output_row["context_revision"]) != historical_output.context_revision
            or int(query_link["page_index"]) != source_result.page.page_index
            or int(query_link["has_more"]) != int(source_result.page.has_more)
        ):
            raise P2V3StoreConflict("protected event does not match its strict accepted source result")

        if len(fact_links) != len(historical_output.fact_cards):
            raise P2V3StoreConflict("protected event fact links do not match its accepted cards")
        fact_material: list[dict[str, Any]] = []
        linked_receipt_ids = {str(row["source_receipt_id"]) for row in linked_gets}
        if len(linked_receipt_ids) != len(linked_gets):
            raise P2V3StoreConflict("accepted query receipt contains duplicate source GET links")
        fact_rows_by_ref: dict[str, Any] = {}
        for ordinal, (row, card) in enumerate(zip(fact_links, historical_output.fact_cards, strict=True)):
            card_json, card_sha = _canonical_json(card.model_dump(mode="json", exclude_none=False), max_bytes=32_768)
            fact_ref = str(pe3._fact_public_ref(card))
            if (
                int(row["card_ordinal"]) != ordinal
                or row["query_result_receipt_id"] != query_link["query_result_receipt_id"]
                or row["query_evidence_ref"] != query_link["query_evidence_ref"]
                or row["fact_ref"] != fact_ref
                or row["fact_kind"] != card.fact_kind
                or row["exact_fact_json"] != card_json
                or row["exact_fact_sha256"] != card_sha
                or row["public_card_json"] != card_json
                or row["public_card_sha256"] != card_sha
            ):
                raise P2V3StoreConflict("protected event fact card differs from its immutable query proof")
            fact_rows_by_ref[fact_ref] = row
            fact_material.append({
                "fact_ref": fact_ref,
                "fact_proof_id": row["fact_proof_id"],
                "fact_sha256": card_sha,
            })

        _, expected_proof_set_sha = _canonical_json({
            "query_receipts": [{
                "query_result_receipt_id": query_link["query_result_receipt_id"],
                "query_evidence_ref": str(source_result.query_evidence.query_evidence_ref),
            }],
            "facts": fact_material,
            "metadata": metadata_binding,
        }, max_bytes=65_536)
        if expected_proof_set_sha != output_row["proof_set_sha256"]:
            raise P2V3StoreConflict("protected event proof-set digest does not bind its metadata and source proofs")

        if source_result.operation.value == "read.activities":
            expected_refs = [str(pe3._fact_public_ref(card)) for card in historical_output.fact_cards]
            if (
                collection is None
                or collection["query_evidence_ref"] != query_link["query_evidence_ref"]
                or [row["activity_ref"] for row in members] != expected_refs
                or any(row["fact_kind"] != "activity" for row in fact_links)
            ):
                raise P2V3StoreConflict("Activity output does not have its exact collection member proof")
            activity_ids: list[uuid.UUID] = []
            seen_refs: set[str] = set()
            for ordinal, member in enumerate(members):
                fact = fact_rows_by_ref.get(member["activity_ref"])
                if (
                    int(member["ordinal"]) != ordinal
                    or member["activity_ref"] in seen_refs
                    or fact is None
                    or fact["activity_ref"] != member["activity_ref"]
                    or member["activity_source_receipt_id"] not in linked_receipt_ids
                    or member["membership_source_receipt_id"] not in linked_receipt_ids
                ):
                    raise P2V3StoreConflict("Activity member is detached from its accepted fact or source receipts")
                seen_refs.add(member["activity_ref"])
                with self._connection() as connection:
                    locator = connection.execute(
                        """SELECT * FROM p2_v3_entity_locators
                           WHERE locator_id=? AND owner_user_id=? AND turn_id=?""",
                        (member["private_activity_locator_id"], str(owner_user_id), str(turn_id)),
                    ).fetchone()
                    activity_receipt = connection.execute(
                        """SELECT * FROM p2_v3_source_get_receipts
                           WHERE source_receipt_id=? AND owner_user_id=? AND turn_id=?""",
                        (member["activity_source_receipt_id"], str(owner_user_id), str(turn_id)),
                    ).fetchone()
                    membership_receipt = connection.execute(
                        """SELECT * FROM p2_v3_source_get_receipts
                           WHERE source_receipt_id=? AND owner_user_id=? AND turn_id=?""",
                        (member["membership_source_receipt_id"], str(owner_user_id), str(turn_id)),
                    ).fetchone()
                    source_facts = connection.execute(
                        """SELECT source_receipt_id,source_role FROM p2_v3_query_fact_sources
                           WHERE fact_proof_id=? AND owner_user_id=? AND turn_id=? ORDER BY ordinal""",
                        (fact["fact_proof_id"], str(owner_user_id), str(turn_id)),
                    ).fetchall()
                if (
                    locator is None or activity_receipt is None or membership_receipt is None
                    or locator["entity_ref"] != member["activity_ref"]
                    or locator["entity_kind"] != "activity"
                    or locator["private_entity_id"] != locator["private_activity_id"]
                    or locator["private_ledger_unit_id"] is not None
                    or locator["cohort_sha256"] != output_row["cohort_sha256"]
                    or locator["created_from_receipt_id"] != member["activity_source_receipt_id"]
                    or activity_receipt["source_table"] != "activities"
                    or activity_receipt["source_role"] != "activity"
                    or membership_receipt["source_table"] != "activity_members"
                    or membership_receipt["source_role"] != "membership"
                    or {(item["source_receipt_id"], item["source_role"]) for item in source_facts}
                        != {
                            (member["activity_source_receipt_id"], "activity"),
                            (member["membership_source_receipt_id"], "membership"),
                        }
                ):
                    raise P2V3StoreConflict("Activity member locator or source proof is invalid")
                try:
                    private_id = uuid.UUID(locator["private_activity_id"])
                except (TypeError, ValueError, AttributeError):
                    raise P2V3StoreConflict("Activity member locator has an invalid private ID") from None
                activity_ids.append(private_id)
        else:
            # Other operation types are accepted only after their own exact
            # scope and locator proofs are present. No caller-supplied scope is
            # used as a substitute for those links.
            activity_ids = []
            for fact in fact_links:
                activity_ref = fact["activity_ref"] or fact["scope_ref"]
                if activity_ref is None:
                    raise P2V3StoreConflict("protected source fact has no bound Activity scope")
                with self._connection() as connection:
                    locators = connection.execute(
                        """SELECT * FROM p2_v3_entity_locators
                           WHERE owner_user_id=? AND turn_id=? AND entity_kind='activity' AND entity_ref=?
                           ORDER BY locator_id""",
                        (str(owner_user_id), str(turn_id), activity_ref),
                    ).fetchall()
                if len(locators) != 1 or locators[0]["cohort_sha256"] != output_row["cohort_sha256"]:
                    raise P2V3StoreConflict("protected source fact has no unique current-cohort Activity locator")
                try:
                    private_id = uuid.UUID(locators[0]["private_activity_id"])
                except (TypeError, ValueError, AttributeError):
                    raise P2V3StoreConflict("protected source fact Activity locator has an invalid private ID") from None
                activity_ids.append(private_id)
            if not activity_ids and historical_output.fact_cards:
                raise P2V3StoreConflict("protected non-empty source output has no authorized Activity IDs")

        return P2V3StoredProtectedOutput(
            profile_id=P2_V3_CANDIDATE_PROFILE_ID,
            event_seq=event_seq,
            historical=historical_output,
            activity_ids=tuple(dict.fromkeys(activity_ids)),
        )



