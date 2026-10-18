from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from agent.app import contracts as c
from agent.app import p2_backend as v1
from agent.app import p2_read_backend as backend
from agent.app import p2_read_contracts_v3 as pc
from agent.app.p2_source_store_v3 import P2V3StoreConflict, P2V3StoreNotFound, P2_V3_CANDIDATE_PROFILE_ID
from agent.app import p2_source_store_v3 as source_store_v3
from agent.app.p2_v3_store_ports import P2V3StoreBudgetPort
from agent.app.store import EventDraft
from test_p2_source_codec_backend_v3 import P2, _datasets
from test_p2_v3_admission_metadata_acceptance import (
    OWNER, ACTIVITY, UNIT, SyntheticTransport, _adapter, _accepted_row_counts,
    _configured_store, _make_admission, _status,
)


def _create_running_turn_for_owner(store: Any, owner: uuid.UUID, *, now: datetime) -> tuple[uuid.UUID, str]:
    ui = c.UIContext(
        page_type=c.PageType.HOME, captured_at=now - timedelta(seconds=1),
        client_version="p2-v3-locator-reuse-cpu",
    )
    session = store.create_session(
        owner, c.CreateSessionRequest(client_request_id=uuid.uuid4(), title="locator collision CPU", ui_context=ui),
        now=now - timedelta(seconds=1),
    ).response_snapshot.session.session_id
    submitted = store.submit_turn(
        owner, session,
        c.SubmitTurnRequest(
            client_request_id=uuid.uuid4(), text="Read the current shared ledger", ui_context=ui,
        ),
        now=now - timedelta(seconds=1), candidate_profile_id=P2_V3_CANDIDATE_PROFILE_ID,
    )
    turn_id = submitted.response_snapshot.turn_id
    claimed = store.claim_runnable("p2v3-locator-other-owner", candidate_profile_id=P2_V3_CANDIDATE_PROFILE_ID, now=now)
    assert claimed is not None and claimed.turn.record.turn.turn_id == turn_id
    before = claimed.turn.record.turn
    after = before.model_copy(update={
        "state": c.TurnState.RUNNING, "state_revision": before.state_revision + 1,
        "step": c.TurnStep.BUILD_CONTEXT, "wait_reason": None, "resume_state": None,
    })
    store.transition_turn(
        owner, after, expected_state_revision=before.state_revision,
        expected_checkpoint_revision=claimed.turn.checkpoint_revision,
        events=[_status(after, now)], claim_token=claimed.claim_token,
        candidate_profile_id=P2_V3_CANDIDATE_PROFILE_ID, now=now,
    )
    return turn_id, claimed.claim_token


def _run_admission(
    store: Any, turn: uuid.UUID, claim: str, binding: Any, registry: Any,
    datasets: dict[str, list[dict[str, Any]]], *, now: datetime,
) -> tuple[Any, Any]:
    adapter = _adapter(store, OWNER, turn, claim, registry)
    adapter._transport.datasets = datasets
    verified = v1.VerifiedReadContext(
        owner_user_id=OWNER, turn_id=turn, principal_user_id=OWNER,
        access_token="synthetic.jwt.locator-reuse-cpu", expires_at=now + timedelta(minutes=5),
        refs_by_opaque_token={},
    )
    projection = asyncio.run(adapter.admit_scope_v3(
        verified, binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
    ))
    return projection, verified


def _locator_rows(store: Any, turn: uuid.UUID) -> list[dict[str, Any]]:
    with store._connection() as connection:
        return [dict(row) for row in connection.execute(
            "SELECT * FROM p2_v3_entity_locators WHERE owner_user_id=? AND turn_id=? ORDER BY entity_kind,private_entity_id",
            (str(OWNER), str(turn)),
        ).fetchall()]


def _proof_rows(store: Any, turn: uuid.UUID) -> list[dict[str, Any]]:
    with store._connection() as connection:
        return [dict(row) for row in connection.execute(
            "SELECT * FROM p2_v3_metadata_source_proofs WHERE owner_user_id=? AND turn_id=? ORDER BY metadata_proof_id",
            (str(OWNER), str(turn)),
        ).fetchall()]


def _receipt_ids(store: Any, admission_id: str) -> set[str]:
    with store._connection() as connection:
        return {str(row[0]) for row in connection.execute(
            "SELECT source_receipt_id FROM p2_v3_admission_source_receipts WHERE admission_id=?",
            (admission_id,),
        ).fetchall()}


def test_second_admission_reuses_identity_refs_but_commits_fresh_metadata_proofs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, turn, claim, first_binding, first_registry, first_adapter, first_verified = _make_admission(tmp_path, monkeypatch)
    try:
        first_projection = asyncio.run(first_adapter.admit_scope_v3(
            first_verified, first_binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
        ))
        assert first_projection is not None
        first_receipts = _receipt_ids(store, first_binding.admission_id)
        assert len(first_receipts) == 6
        locators_before = _locator_rows(store, turn)
        proofs_before = _proof_rows(store, turn)
        assert locators_before and proofs_before
        first_activity_ref = first_projection.snapshot.activity_ref
        first_scope_ref = first_projection.snapshot.scope_ref

        now = datetime.now(timezone.utc)
        second_binding, second_scope = store.create_p2_v3_request_admission(
            OWNER, turn, claim_token=claim, principal_user_id=OWNER,
            activity_id_hint=ACTIVITY, ledger_unit_id_hint=UNIT, now=now,
        )
        second_registry = second_binding.reference_registry
        assert second_scope is not None
        assert second_scope.activity_ref == first_activity_ref
        assert second_scope.scope_ref == first_scope_ref
        assert second_registry.principal_ref() != first_registry.principal_ref()
        assert second_registry.owner_turn_ref(identity=second_binding.identity) != first_registry.owner_turn_ref(identity=first_binding.identity)
        assert second_registry._accepted_snapshot_digest is None

        data = _datasets()
        data["activity_members"][0]["user_id"] = str(OWNER)
        data["participant_claims"][0]["user_id"] = str(OWNER)
        data["activities"][0]["name"] = "refreshed activity label"
        data["ledger_units"][0]["name"] = "current child label"
        data["participants"] = [row for row in data["participants"] if row["id"] != str(P2)]
        data["sub_activity_participants"] = [
            row for row in data["sub_activity_participants"]
            if row["participant_id"] != str(P2)
        ]
        second_projection, _ = _run_admission(
            store, turn, claim, second_binding, second_registry, data, now=now,
        )
        assert second_projection.snapshot.activity_ref == first_activity_ref
        assert second_projection.snapshot.scope_ref == first_scope_ref
        labels = {label.entity_kind: label.display_name for label in second_projection.source_labels}
        assert labels["activity"] == "refreshed activity label"
        assert labels["ledger_unit"] == "current child label"
        second_refs = {str(label.entity_ref) for label in second_projection.source_labels}
        removed_ref = next(
            row["entity_ref"] for row in locators_before
            if row["entity_kind"] == "participant" and row["private_entity_id"] == str(P2)
        )
        assert removed_ref not in second_refs

        locators_after = _locator_rows(store, turn)
        assert locators_after == locators_before
        proofs_after = _proof_rows(store, turn)
        old_proof_by_id = {row["metadata_proof_id"]: row for row in proofs_after}
        assert all(old_proof_by_id[row["metadata_proof_id"]] == row for row in proofs_before)
        second_receipts = _receipt_ids(store, second_binding.admission_id)
        assert len(second_receipts) == 6 and first_receipts.isdisjoint(second_receipts)
        new_proofs = [row for row in proofs_after if row["source_receipt_id"] in second_receipts]
        assert new_proofs and all(row["source_receipt_id"] in second_receipts for row in new_proofs)
        assert any(row["source_receipt_id"] not in first_receipts for row in new_proofs)
        second_registry.require_metadata_accepted(identity=second_binding.identity, admission_id=second_binding.admission_id)
        first_registry.require_metadata_accepted(identity=first_binding.identity, admission_id=first_binding.admission_id)
    finally:
        store.close()


def test_fresh_membership_revocation_refuses_new_admission_without_reusing_old_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, turn, claim, first_binding, first_registry, first_adapter, first_verified = _make_admission(tmp_path, monkeypatch)
    try:
        asyncio.run(first_adapter.admit_scope_v3(
            first_verified, first_binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
        ))
        old_locators = _locator_rows(store, turn)
        old_proofs = _proof_rows(store, turn)
        old_receipts = _receipt_ids(store, first_binding.admission_id)

        now = datetime.now(timezone.utc)
        binding, _ = store.create_p2_v3_request_admission(
            OWNER, turn, claim_token=claim, principal_user_id=OWNER,
            activity_id_hint=ACTIVITY, ledger_unit_id_hint=UNIT, now=now,
        )
        registry = binding.reference_registry
        data = _datasets()
        data["activity_members"] = []
        data["participant_claims"][0]["user_id"] = str(OWNER)
        adapter = _adapter(store, OWNER, turn, claim, registry)
        adapter._transport.datasets = data
        verified = v1.VerifiedReadContext(
            owner_user_id=OWNER, turn_id=turn, principal_user_id=OWNER,
            access_token="synthetic.jwt.revoked-membership-cpu", expires_at=now + timedelta(minutes=5),
            refs_by_opaque_token={},
        )
        with pytest.raises(backend.P2ReadBackendError):
            asyncio.run(adapter.admit_scope_v3(
                verified, binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
            ))
        with pytest.raises(P2V3StoreConflict):
            registry.require_metadata_accepted(identity=binding.identity, admission_id=binding.admission_id)
        assert _locator_rows(store, turn) == old_locators
        assert _proof_rows(store, turn) == old_proofs
        assert _receipt_ids(store, binding.admission_id) == set()
        assert _receipt_ids(store, first_binding.admission_id) == old_receipts
        assert _accepted_row_counts(store, binding.admission_id) == (0, len(old_proofs), len(old_locators), 6)
        first_registry.require_metadata_accepted(identity=first_binding.identity, admission_id=first_binding.admission_id)
    finally:
        store.close()


def test_different_private_identity_cannot_reuse_a_forced_existing_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _, _, binding, registry, adapter, verified = _make_admission(tmp_path, monkeypatch)
    try:
        asyncio.run(adapter.admit_scope_v3(
            verified, binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
        ))
        existing_unit_ref = next(
            ref for ref, key in registry._entity_by_ref.items() if key[0] == "ledger_unit"
        )
        monkeypatch.setattr(type(registry), "_new_ref", staticmethod(lambda: existing_unit_ref))
        other_unit = uuid.UUID("00000000-0000-4000-8000-000000000099")
        with pytest.raises(P2V3StoreConflict, match="collides"):
            registry.bind_entity("ledger_unit", other_unit, activity_id=ACTIVITY, ledger_unit_id=other_unit)
    finally:
        store.close()


def test_owner_turn_and_cohort_collisions_and_ambiguous_old_locators_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, turn, claim, binding, registry, adapter, verified = _make_admission(tmp_path, monkeypatch)
    try:
        asyncio.run(adapter.admit_scope_v3(
            verified, binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
        ))
        activity_ref = next(ref for ref, key in registry._entity_by_ref.items() if key[0] == "activity")

        # A fresh current registry may reuse a unique locator only while its
        # immutable cohort matches. A changed cohort must fail before binding.
        now = datetime.now(timezone.utc)
        same_binding, _ = store.create_p2_v3_request_admission(
            OWNER, turn, claim_token=claim, principal_user_id=OWNER,
            activity_id_hint=ACTIVITY, ledger_unit_id_hint=UNIT, now=now,
        )
        same_registry = same_binding.reference_registry
        activity_key = next(key for key in same_registry._entity_by_key if key[0] == "activity")
        old_ref = same_registry._entity_by_key.pop(activity_key)
        same_registry._entity_by_ref.pop(old_ref)
        same_registry._cohort_sha256 = "a" * 64
        with pytest.raises(P2V3StoreConflict, match="cohort"):
            same_registry.bind_entity("activity", ACTIVITY, activity_id=ACTIVITY)

        # A forced random token collision across owners/Turns is rejected. The
        # second owner's real candidate Turn has no matching locator.
        original_new_ref = type(registry)._new_ref
        other_owner = uuid.UUID("a1000000-0000-4000-8000-000000000099")
        other_turn, other_claim = _create_running_turn_for_owner(store, other_owner, now=now + timedelta(seconds=1))
        generated = iter(("ref_" + "A" * 24, "ref_" + "B" * 24, activity_ref))
        monkeypatch.setattr(type(registry), "_new_ref", staticmethod(lambda: next(generated)))
        before_admissions = None
        with store._connection() as connection:
            before_admissions = int(connection.execute(
                "SELECT COUNT(*) FROM p2_v3_source_admissions WHERE owner_user_id=? AND turn_id=?",
                (str(other_owner), str(other_turn)),
            ).fetchone()[0])
        with pytest.raises(P2V3StoreConflict, match="collides"):
            store.create_p2_v3_request_admission(
                other_owner, other_turn, claim_token=other_claim, principal_user_id=other_owner,
                activity_id_hint=ACTIVITY, now=now + timedelta(seconds=1),
            )
        with store._connection() as connection:
            after_admissions = int(connection.execute(
                "SELECT COUNT(*) FROM p2_v3_source_admissions WHERE owner_user_id=? AND turn_id=?",
                (str(other_owner), str(other_turn)),
            ).fetchone()[0])
        assert after_admissions == before_admissions

        monkeypatch.setattr(type(registry), "_new_ref", staticmethod(original_new_ref))
        other_turn_registry = source_store_v3.P2V3RequestReferenceRegistry(
            store, identity=replace(binding.identity, turn_id=uuid.uuid4()),
            admission_id=str(uuid.uuid4()), principal_user_id=OWNER,
            claim_token="synthetic-unclaimed-turn", cohort_sha256=registry._cohort_sha256,
            seal=source_store_v3._P2_V3_REFERENCE_REGISTRY_SEAL,
        )
        monkeypatch.setattr(type(registry), "_new_ref", staticmethod(lambda: activity_ref))
        with pytest.raises(P2V3StoreConflict, match="collides"):
            other_turn_registry.bind_entity("activity", ACTIVITY, activity_id=ACTIVITY)
        monkeypatch.setattr(type(registry), "_new_ref", staticmethod(original_new_ref))

        # Persisted duplicate refs for the same identity are ambiguous and may
        # never be resolved by picking an arbitrary row.
        locator = next(row for row in _locator_rows(store, turn) if row["entity_ref"] == activity_ref)
        with store._connection() as connection:
            connection.execute(
                """INSERT INTO p2_v3_entity_locators (
                    locator_id,owner_user_id,turn_id,entity_ref,entity_kind,private_entity_id,
                    private_activity_id,private_ledger_unit_id,cohort_sha256,created_from_receipt_id,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()), locator["owner_user_id"], locator["turn_id"],
                    "ref_" + "C" * 24, locator["entity_kind"], locator["private_entity_id"],
                    locator["private_activity_id"], locator["private_ledger_unit_id"], locator["cohort_sha256"],
                    locator["created_from_receipt_id"], locator["created_at"],
                ),
            )
        with pytest.raises(P2V3StoreConflict, match="ambiguous"):
            store.create_p2_v3_request_admission(
                OWNER, turn, claim_token=claim, principal_user_id=OWNER,
                activity_id_hint=ACTIVITY, ledger_unit_id_hint=UNIT, now=now + timedelta(seconds=3),
            )
    finally:
        store.close()


def test_new_scope_without_fresh_source_row_does_not_reuse_previous_child_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, turn, claim, first_binding, first_registry, first_adapter, first_verified = _make_admission(tmp_path, monkeypatch)
    try:
        asyncio.run(first_adapter.admit_scope_v3(
            first_verified, first_binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=UNIT,
        ))
        old_locators = _locator_rows(store, turn)
        old_proofs = _proof_rows(store, turn)
        other_unit = uuid.UUID("00000000-0000-4000-8000-000000000099")
        now = datetime.now(timezone.utc)
        binding, scope = store.create_p2_v3_request_admission(
            OWNER, turn, claim_token=claim, principal_user_id=OWNER,
            activity_id_hint=ACTIVITY, ledger_unit_id_hint=other_unit, now=now,
        )
        registry = binding.reference_registry
        assert scope is not None and scope.activity_ref == first_registry._entity_by_key[("activity", ACTIVITY, ACTIVITY, None)]
        assert scope.ledger_unit_ref != first_registry._entity_by_key[("ledger_unit", UNIT, ACTIVITY, UNIT)]
        data = _datasets()
        data["activity_members"][0]["user_id"] = str(OWNER)
        data["participant_claims"][0]["user_id"] = str(OWNER)
        adapter = _adapter(store, OWNER, turn, claim, registry)
        adapter._transport.datasets = data
        verified = v1.VerifiedReadContext(
            owner_user_id=OWNER, turn_id=turn, principal_user_id=OWNER,
            access_token="synthetic.jwt.scope-transition-cpu", expires_at=now + timedelta(minutes=5),
            refs_by_opaque_token={},
        )
        with pytest.raises(backend.P2ReadBackendError):
            asyncio.run(adapter.admit_scope_v3(
                verified, binding, ui_activity_id_hint=ACTIVITY, ui_ledger_unit_id_hint=other_unit,
            ))
        with pytest.raises(P2V3StoreConflict):
            registry.require_metadata_accepted(identity=binding.identity, admission_id=binding.admission_id)
        assert _locator_rows(store, turn) == old_locators
        assert _proof_rows(store, turn) == old_proofs
        assert _receipt_ids(store, binding.admission_id) == set()
    finally:
        store.close()
