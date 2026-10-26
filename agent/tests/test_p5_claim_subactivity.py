from __future__ import annotations

"""P5.8b Participant claims and sub-activity lifecycle."""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlsplit

import pytest
from pydantic import ValidationError

from agent.app import contracts as c
from agent.app.p5_write import LiveExpenseGateway, LiveWriteConfig, LiveWriteError
from agent.app.ports import Principal
from agent.app.store import SQLiteAgentStore
from test_p5_live_write import ACTIVITY, FakeReadBackend, P1, P2, UNIT
from test_sqlite_persistence import OWNER, _session, _submit, _wait_with_proposal


NEW_SUB = uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
OTHER_USER = uuid.UUID("99999999-9999-4999-8999-999999999999")


def _activity_row(*, archived=False, deleted=False, activity_type="large") -> dict:
    return {
        "id": str(ACTIVITY),
        "name": "Trip",
        "type": activity_type,
        "base_currency": "CNY",
        "multi_currency_enabled": False,
        "created_by": str(OWNER),
        "archived_at": "2026-10-01T00:00:00+00:00" if archived else None,
        "is_deleted": deleted,
        "participants_locked_at": None,
        "join_code": "12345678",
    }


def _participant_row(participant_id=P1, name="Ann", *, deleted=False) -> dict:
    return {
        "id": str(participant_id),
        "activity_id": str(ACTIVITY),
        "name": name,
        "participant_order": 0,
        "is_deleted": deleted,
    }


class FakeClaimTransport:
    def __init__(self) -> None:
        self.post_calls: list[dict] = []
        self.get_calls: list[str] = []
        self.mode = "success"
        self.activity = _activity_row()
        self.participants = [
            _participant_row(P1, "Ann"),
            _participant_row(P2, "Ben"),
        ]
        self.claims: list[dict] = []
        self.units = [
            {
                "id": str(UNIT), "activity_id": str(ACTIVITY), "name": "Main",
                "type": "root", "is_deleted": False,
            },
        ]
        self.claim_id = uuid.uuid4()
        self.claim_is_new = True
        self.unclaim_released = True
        self.new_unit_id = NEW_SUB
        self.delete_changed = True
        self.delete_is_deleted = True
        self.restore_changed = True
        self.restore_is_deleted = False
        self.financial_version_after = 6

    def _error(self, code: str, message: str):
        return 400, json.dumps({"code": code, "message": message}).encode()

    def get_json(self, url, headers, *, timeout, max_response_bytes):  # noqa: ANN001
        self.get_calls.append(url)
        parsed = urlsplit(url)
        table = parsed.path.rsplit("/", 1)[-1]
        params = dict(parse_qsl(parsed.query))
        if table == "activities":
            return 200, json.dumps([self.activity]).encode()
        if table == "participants":
            rows = self.participants
            if "id" in params:
                wanted = params["id"].removeprefix("eq.")
                rows = [row for row in rows if row["id"] == wanted]
            if "activity_id" in params:
                wanted = params["activity_id"].removeprefix("eq.")
                rows = [row for row in rows if row["activity_id"] == wanted]
            return 200, json.dumps(rows).encode()
        if table == "participant_claims":
            rows = self.claims
            if "activity_id" in params:
                wanted = params["activity_id"].removeprefix("eq.")
                rows = [row for row in rows if row["activity_id"] == wanted]
            return 200, json.dumps(rows).encode()
        if table == "ledger_units":
            rows = self.units
            if "id" in params:
                wanted = params["id"].removeprefix("eq.")
                rows = [row for row in rows if row["id"] == wanted]
            return 200, json.dumps(rows).encode()
        return 200, b"[]"

    def post_json(self, url, headers, payload, *, timeout, max_response_bytes):  # noqa: ANN001
        self.post_calls.append({"url": url, "payload": dict(payload)})
        if self.mode == "ambiguous":
            raise LiveWriteError("upstream_ambiguous", ambiguous=True)
        if self.mode == "invalid":
            return self._error("22023", "invalid request")
        if self.mode == "forbidden":
            return self._error("42501", "caller is not an activity member")
        if self.mode == "archived":
            return self._error("55000", "archived activity is read-only")
        if self.mode == "not_found":
            return self._error("P0002", "not found")
        if self.mode == "used":
            return self._error("23514", "a sub-activity requires at least one participant")
        if self.mode == "conflict":
            return self._error("23505", "user already claimed a participant")
        if self.mode == "root_missing":
            return self._error("P0001", "large activity root ledger unit is missing")
        if url.endswith("/claim_participant"):
            return 200, json.dumps([{
                "claim_id": str(self.claim_id),
                "claimed_participant_id": payload["participant_id"],
                "is_new": self.claim_is_new,
            }]).encode()
        if url.endswith("/unclaim_participant"):
            return 200, json.dumps(self.unclaim_released).encode()
        if url.endswith("/create_sub_activity"):
            return 200, json.dumps([{
                "parent_activity_id": str(ACTIVITY),
                "ledger_unit_id": str(self.new_unit_id),
                "created_name": payload["name"],
                "created_type": "sub_activity",
            }]).encode()
        if url.endswith("/delete_sub_activity"):
            return 200, json.dumps([{
                "sub_activity_id": payload["sub_activity_id"],
                "activity_id": str(ACTIVITY),
                "changed": self.delete_changed,
                "is_deleted": self.delete_is_deleted,
                "financial_version": self.financial_version_after,
            }]).encode()
        if url.endswith("/restore_sub_activity"):
            return 200, json.dumps([{
                "sub_activity_id": payload["sub_activity_id"],
                "activity_id": str(ACTIVITY),
                "changed": self.restore_changed,
                "is_deleted": self.restore_is_deleted,
                "financial_version": self.financial_version_after,
            }]).encode()
        return 200, b"[]"


def _confirm_request(proposal: c.ProposalRecord, *, request_id: uuid.UUID | None = None):
    return c.ConfirmProposalRequest(
        client_request_id=request_id or uuid.uuid4(),
        expected_proposal_revision=proposal.revision,
        command_digest=proposal.command_digest,
        confirmation_nonce=proposal.confirmation_nonce,
    )


def _execute(gateway, principal, proposal, waiting):
    return asyncio.run(gateway.execute(
        principal=principal,
        proposal=proposal,
        request=_confirm_request(proposal),
        expected_state_revision=waiting.state_revision,
        access_token="token-a",
    ))


def _setup(tmp_path, name: str, builder: str, intent, *, transport=None,
           activity_type: str = "large", ledger_unit_type: str = "root"):
    store = SQLiteAgentStore(tmp_path / f"{name}.sqlite3", admission_enabled=True)
    store.start()
    session = _session(store, OWNER)
    _, turn_id = _submit(store, session, OWNER)
    transport = transport or FakeClaimTransport()
    read_backend = FakeReadBackend(
        version=5, base_currency="CNY",
        activity_type=activity_type, ledger_unit_type=ledger_unit_type,
    )
    gateway = LiveExpenseGateway(
        LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
        store, read_backend, transport,
    )
    proposal = asyncio.run(getattr(gateway, builder)(
        owner_user_id=OWNER,
        session_id=session,
        turn_id=turn_id,
        intent=intent,
        access_token="token-a",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        agent_disable_revision=0,
        now=datetime.now(timezone.utc),
    ))
    waiting = _wait_with_proposal(store, OWNER, turn_id, proposal)
    principal = Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1))
    return store, gateway, read_backend, transport, proposal, waiting, principal, turn_id


def _claim_intent(participant_id=P1) -> c.ParticipantClaimIntent:
    return c.ParticipantClaimIntent(
        kind="participant.claim", activity_id=ACTIVITY, participant_id=participant_id,
    )


def _unclaim_intent() -> c.ParticipantUnclaimIntent:
    return c.ParticipantUnclaimIntent(kind="participant.unclaim", activity_id=ACTIVITY)


def _sub_create_intent(name: str = "小组A", ids=None) -> c.SubActivityCreateIntent:
    return c.SubActivityCreateIntent(
        kind="subactivity.create", activity_id=ACTIVITY, name=name,
        participant_ids=ids or [P1, P2],
    )


def _sub_lifecycle_intent(*, is_restore: bool, sub_id=NEW_SUB):
    cls = c.SubActivityRestoreIntent if is_restore else c.SubActivityDeleteIntent
    return cls(
        kind="subactivity.restore" if is_restore else "subactivity.delete",
        activity_id=ACTIVITY, sub_activity_id=sub_id,
    )


def _claim(participant_id, user_id, claim_id=None) -> dict:
    return {
        "id": str(claim_id or uuid.uuid4()),
        "activity_id": str(ACTIVITY),
        "participant_id": str(participant_id),
        "user_id": str(user_id),
    }


# ----------------------------------------------------------------------- claim


def test_claim_previews_and_executes(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p58b-claim", "build_participant_claim_preview", _claim_intent(),
    )
    try:
        assert proposal.operation == "participant.claim"
        assert proposal.preview.operation == "participant.claim"
        assert proposal.preview.participant_name == "Ann"
        assert "当前未认领" in proposal.preview.summary
        command = proposal.canonical_command
        assert isinstance(command, c.FixedParticipantClaimCommand)
        assert command.expected_claim_state == "none"
        assert transport.post_calls == []

        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "participant_claimed"
        call = transport.post_calls[0]
        assert call["url"].endswith("/rest/v1/rpc/claim_participant")
        assert call["payload"] == {
            "activity_id": str(ACTIVITY), "participant_id": str(P1),
        }
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.COMPLETED
    finally:
        store.close()


def test_repeat_claim_is_idempotent(tmp_path) -> None:
    transport = FakeClaimTransport()
    transport.claims = [_claim(P1, OWNER)]
    transport.claim_is_new = False
    store, gateway, _, _, proposal, waiting, principal, _ = _setup(
        tmp_path, "p58b-claim-repeat", "build_participant_claim_preview",
        _claim_intent(), transport=transport,
    )
    try:
        assert "本人已认领" in proposal.preview.summary
        assert proposal.canonical_command.expected_claim_state == "mine"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "participant_claim_already_exists"
    finally:
        store.close()


def test_claim_refuses_a_participant_claimed_by_someone_else(tmp_path) -> None:
    transport = FakeClaimTransport()
    transport.claims = [_claim(P1, OTHER_USER)]
    store = SQLiteAgentStore(tmp_path / "p58b-claim-other.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        gateway = LiveExpenseGateway(
            LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
            store, FakeReadBackend(version=5, base_currency="CNY", activity_type="large"),
            transport,
        )
        with pytest.raises(LiveWriteError) as excinfo:
            asyncio.run(gateway.build_participant_claim_preview(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=_claim_intent(), access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert excinfo.value.code == "participant_claimed_by_other"
        assert transport.post_calls == []
    finally:
        store.close()


def test_claim_refuses_when_the_caller_already_claimed_another(tmp_path) -> None:
    transport = FakeClaimTransport()
    transport.claims = [_claim(P2, OWNER)]
    store = SQLiteAgentStore(tmp_path / "p58b-claim-second.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        gateway = LiveExpenseGateway(
            LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
            store, FakeReadBackend(version=5, base_currency="CNY", activity_type="large"),
            transport,
        )
        with pytest.raises(LiveWriteError) as excinfo:
            asyncio.run(gateway.build_participant_claim_preview(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=_claim_intent(P1), access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert excinfo.value.code == "actor_already_claimed_other"
        assert transport.post_calls == []
    finally:
        store.close()


def test_claim_rejects_a_deleted_participant(tmp_path) -> None:
    transport = FakeClaimTransport()
    transport.participants = [_participant_row(P1, "Ann", deleted=True)]
    store = SQLiteAgentStore(tmp_path / "p58b-claim-deleted.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        gateway = LiveExpenseGateway(
            LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
            store, FakeReadBackend(version=5, base_currency="CNY", activity_type="large"),
            transport,
        )
        with pytest.raises(LiveWriteError) as excinfo:
            asyncio.run(gateway.build_participant_claim_preview(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=_claim_intent(), access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert excinfo.value.code == "participant_not_found"
        assert transport.post_calls == []
    finally:
        store.close()


# --------------------------------------------------------------------- unclaim


def test_unclaim_previews_and_executes(tmp_path) -> None:
    transport = FakeClaimTransport()
    transport.claims = [_claim(P1, OWNER)]
    store, gateway, _, _, proposal, waiting, principal, _ = _setup(
        tmp_path, "p58b-unclaim", "build_participant_unclaim_preview",
        _unclaim_intent(), transport=transport,
    )
    try:
        assert proposal.operation == "participant.unclaim"
        assert proposal.preview.participant_name == "Ann"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "claim_released"
        assert transport.post_calls[0]["url"].endswith("/rest/v1/rpc/unclaim_participant")
        assert transport.post_calls[0]["payload"] == {"activity_id": str(ACTIVITY)}
    finally:
        store.close()


def test_unclaim_without_a_claim_is_refused(tmp_path) -> None:
    transport = FakeClaimTransport()
    transport.claims = [_claim(P1, OTHER_USER)]
    store = SQLiteAgentStore(tmp_path / "p58b-unclaim-none.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        gateway = LiveExpenseGateway(
            LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
            store, FakeReadBackend(version=5, base_currency="CNY", activity_type="large"),
            transport,
        )
        with pytest.raises(LiveWriteError) as excinfo:
            asyncio.run(gateway.build_participant_unclaim_preview(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=_unclaim_intent(), access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert excinfo.value.code == "claim_not_found"
        assert transport.post_calls == []
        # Somebody else's claim is untouched by this refusal.
        assert transport.claims[0]["user_id"] == str(OTHER_USER)
    finally:
        store.close()


def test_unclaim_reports_an_already_released_claim(tmp_path) -> None:
    transport = FakeClaimTransport()
    transport.claims = [_claim(P1, OWNER)]
    transport.unclaim_released = False
    store, gateway, _, _, proposal, waiting, principal, _ = _setup(
        tmp_path, "p58b-unclaim-noop", "build_participant_unclaim_preview",
        _unclaim_intent(), transport=transport,
    )
    try:
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "claim_already_released"
    finally:
        store.close()


# ------------------------------------------------------------ sub-activity create


def test_sub_activity_create_previews_and_executes(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, _ = _setup(
        tmp_path, "p58b-sub-create", "build_sub_activity_create_preview",
        _sub_create_intent(),
    )
    try:
        assert proposal.operation == "subactivity.create"
        assert proposal.preview.sub_activity_name == "小组A"
        assert proposal.preview.participant_names == ["Ann", "Ben"]
        assert transport.post_calls == []

        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "sub_activity_created"
        call = transport.post_calls[0]
        assert call["url"].endswith("/rest/v1/rpc/create_sub_activity")
        # The three-argument entry only; no scope-configuration field is ever sent.
        assert call["payload"] == {
            "activity_id": str(ACTIVITY),
            "name": "小组A",
            "participant_ids": [str(P1), str(P2)],
        }
        assert all(
            item["url"].startswith("https://example.supabase.co/rest/v1/rpc/")
            for item in transport.post_calls
        )
    finally:
        store.close()


@pytest.mark.parametrize("ids", [[P1, P1]])
def test_sub_activity_intent_rejects_duplicate_ids(tmp_path, ids) -> None:
    with pytest.raises(ValidationError):
        _sub_create_intent(ids=ids)


def test_sub_activity_intent_rejects_an_empty_selection() -> None:
    with pytest.raises(ValidationError):
        c.SubActivityCreateIntent(
            kind="subactivity.create", activity_id=ACTIVITY, name="小组A",
            participant_ids=[],
        )


@pytest.mark.parametrize(
    ("mutate", "read_backend_kwargs", "code"),
    [
        (lambda t: None, {"activity_type": "normal"}, "sub_activity_requires_large"),
        (lambda t: None,
         {"activity_type": "large", "ledger_unit_type": "main"},
         "sub_activity_root_missing"),
        (lambda t: None,
         {"activity_type": "large", "ledger_unit_type": "root",
          "ledger_unit_name": "小组A"},
         "sub_activity_name_conflict"),
    ],
)
def test_sub_activity_create_preview_rejections(
    tmp_path, mutate, read_backend_kwargs, code,
) -> None:
    transport = FakeClaimTransport()
    mutate(transport)
    store = SQLiteAgentStore(tmp_path / f"p58b-sub-{code}.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        gateway = LiveExpenseGateway(
            LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
            store,
            FakeReadBackend(version=5, base_currency="CNY", **read_backend_kwargs),
            transport,
        )
        with pytest.raises(LiveWriteError) as excinfo:
            asyncio.run(gateway.build_sub_activity_create_preview(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=_sub_create_intent(), access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert excinfo.value.code == code
        assert transport.post_calls == []
    finally:
        store.close()


def test_sub_activity_create_rejects_participants_outside_the_roster(tmp_path) -> None:
    store = SQLiteAgentStore(tmp_path / "p58b-sub-roster.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        transport = FakeClaimTransport()
        gateway = LiveExpenseGateway(
            LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
            store,
            FakeReadBackend(
                version=5, base_currency="CNY", activity_type="large",
                ledger_unit_type="root",
            ),
            transport,
        )
        with pytest.raises(LiveWriteError) as excinfo:
            asyncio.run(gateway.build_sub_activity_create_preview(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=_sub_create_intent(ids=[P1, OTHER_USER]), access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert excinfo.value.code == "sub_activity_participant_invalid"
        assert transport.post_calls == []
    finally:
        store.close()


# --------------------------------------------------- sub-activity delete/restore


def test_sub_activity_delete_and_repeat(tmp_path) -> None:
    transport = FakeClaimTransport()
    transport.units.append({
        "id": str(NEW_SUB), "activity_id": str(ACTIVITY), "name": "小组A",
        "type": "sub_activity", "is_deleted": False,
    })
    store, gateway, _, _, proposal, waiting, principal, _ = _setup(
        tmp_path, "p58b-sub-delete", "build_sub_activity_delete_preview",
        _sub_lifecycle_intent(is_restore=False), transport=transport,
    )
    try:
        assert proposal.preview.sub_activity_id == NEW_SUB
        assert "未删除" in proposal.preview.summary
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "sub_activity_deleted"
        assert transport.post_calls[0]["payload"] == {"sub_activity_id": str(NEW_SUB)}
    finally:
        store.close()

    repeated = FakeClaimTransport()
    repeated.units.append({
        "id": str(NEW_SUB), "activity_id": str(ACTIVITY), "name": "小组A",
        "type": "sub_activity", "is_deleted": True,
    })
    repeated.delete_changed = False
    store, gateway, _, _, proposal, waiting, principal, _ = _setup(
        tmp_path / "again", "p58b-sub-delete-repeat",
        "build_sub_activity_delete_preview",
        _sub_lifecycle_intent(is_restore=False), transport=repeated,
    )
    try:
        assert "已删除" in proposal.preview.summary
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "sub_activity_already_deleted"
    finally:
        store.close()


def test_sub_activity_restore_advances_the_financial_version(tmp_path) -> None:
    transport = FakeClaimTransport()
    transport.units.append({
        "id": str(NEW_SUB), "activity_id": str(ACTIVITY), "name": "小组A",
        "type": "sub_activity", "is_deleted": True,
    })
    store, gateway, _, _, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p58b-sub-restore", "build_sub_activity_restore_preview",
        _sub_lifecycle_intent(is_restore=True), transport=transport,
    )
    try:
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "sub_activity_restored"
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.execution_resolution is c.ExecutionResolution.SUCCEEDED
        # financial_version comes from the server result, not a local guess.
        events = store.read_turn_view(OWNER, turn_id).events
        summaries = [
            item.event.payload.result_summary
            for item in events
            if item.event.type == "execution_result"
        ]
        assert any("financial_version=6" in (value or "") for value in summaries)
    finally:
        store.close()


def test_sub_activity_restore_of_a_live_unit_is_idempotent(tmp_path) -> None:
    transport = FakeClaimTransport()
    transport.units.append({
        "id": str(NEW_SUB), "activity_id": str(ACTIVITY), "name": "小组A",
        "type": "sub_activity", "is_deleted": False,
    })
    transport.restore_changed = False
    transport.restore_is_deleted = False
    store, gateway, _, _, proposal, waiting, principal, _ = _setup(
        tmp_path, "p58b-sub-restore-noop", "build_sub_activity_restore_preview",
        _sub_lifecycle_intent(is_restore=True), transport=transport,
    )
    try:
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "sub_activity_not_deleted"
    finally:
        store.close()


@pytest.mark.parametrize(
    ("builder", "intent_factory"),
    [
        ("build_sub_activity_delete_preview", lambda: _sub_lifecycle_intent(is_restore=False)),
        ("build_sub_activity_restore_preview", lambda: _sub_lifecycle_intent(is_restore=True)),
    ],
)
def test_sub_activity_lifecycle_rejects_non_members(tmp_path, builder, intent_factory) -> None:
    transport = FakeClaimTransport()
    transport.units.append({
        "id": str(NEW_SUB), "activity_id": str(ACTIVITY), "name": "小组A",
        "type": "sub_activity", "is_deleted": False,
    })
    store, gateway, _, _, proposal, waiting, principal, _ = _setup(
        tmp_path, f"p58b-sub-member-{builder}", builder, intent_factory(),
        transport=transport,
    )
    try:
        transport.mode = "forbidden"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.REJECTED
        assert outcome.code == "actor_not_permitted"
    finally:
        store.close()


def test_sub_activity_lifecycle_rejects_a_sibling_unit_kind(tmp_path) -> None:
    transport = FakeClaimTransport()
    store = SQLiteAgentStore(tmp_path / "p58b-sub-kind.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        gateway = LiveExpenseGateway(
            LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
            store, FakeReadBackend(version=5, base_currency="CNY", activity_type="large"),
            transport,
        )
        with pytest.raises(LiveWriteError) as excinfo:
            asyncio.run(gateway.build_sub_activity_delete_preview(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=_sub_lifecycle_intent(is_restore=False, sub_id=UNIT),
                access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert excinfo.value.code == "not_a_sub_activity"
        assert transport.post_calls == []
    finally:
        store.close()


# ------------------------------------------------------- idempotency & versions


def test_duplicate_confirmation_sends_one_rpc(tmp_path) -> None:
    store, gateway, _, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p58b-duplicate", "build_participant_claim_preview", _claim_intent(),
    )
    try:
        assert _execute(gateway, principal, proposal, waiting).resolution is c.ExecutionResolution.SUCCEEDED
        execution_id = store.get_turn(OWNER, turn_id).record.turn.execution.execution_id
        stored = store.get_proposal(OWNER, proposal.proposal_id)
        again = asyncio.run(gateway.execute(
            principal=principal,
            proposal=stored,
            request=_confirm_request(proposal),
            expected_state_revision=store.get_turn(OWNER, turn_id).record.turn.state_revision,
            access_token="token-a",
        ))
        assert again.resolution is c.ExecutionResolution.SUCCEEDED
        assert len(transport.post_calls) == 1
        assert store.get_turn(OWNER, turn_id).record.turn.execution.execution_id == execution_id
    finally:
        store.close()


@pytest.mark.parametrize(
    ("builder", "intent_factory", "change", "code"),
    [
        ("build_participant_claim_preview", _claim_intent, "archived",
         "management_state_changed"),
        ("build_participant_claim_preview", _claim_intent, "version",
         "data_changed_during_read"),
        ("build_participant_claim_preview", _claim_intent, "claim",
         "claim_state_changed"),
        ("build_sub_activity_create_preview", _sub_create_intent, "version",
         "data_changed_during_read"),
        ("build_sub_activity_create_preview", _sub_create_intent, "archived",
         "sub_activity_state_changed"),
        ("build_sub_activity_delete_preview",
         lambda: _sub_lifecycle_intent(is_restore=False), "unit",
         "sub_activity_state_changed"),
        ("build_sub_activity_delete_preview",
         lambda: _sub_lifecycle_intent(is_restore=False), "version",
         "data_changed_during_read"),
    ],
)
def test_preview_changes_close_without_an_rpc(
    tmp_path, builder, intent_factory, change, code,
) -> None:
    transport = FakeClaimTransport()
    transport.units.append({
        "id": str(NEW_SUB), "activity_id": str(ACTIVITY), "name": "小组A",
        "type": "sub_activity", "is_deleted": False,
    })
    store, gateway, read_backend, _, proposal, waiting, principal, turn_id = _setup(
        tmp_path, f"p58b-change-{change}-{builder}", builder, intent_factory(),
        transport=transport,
    )
    try:
        if change == "archived":
            transport.activity["archived_at"] = "2026-10-02T00:00:00+00:00"
        elif change == "version":
            read_backend.version = 6
        elif change == "claim":
            transport.claims.append(_claim(P1, OWNER))
        else:
            transport.units[-1]["is_deleted"] = True
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == code
        assert transport.post_calls == []
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.CANCELLED
        assert turn.execution is None
    finally:
        store.close()


@pytest.mark.parametrize(
    ("builder", "intent_factory", "exists", "code"),
    [
        ("build_participant_claim_preview", _claim_intent, True, "claimed_elsewhere"),
        ("build_participant_claim_preview", _claim_intent, False, "claim_not_applied"),
        ("build_participant_unclaim_preview", _unclaim_intent, True, "unclaim_not_applied"),
        ("build_participant_unclaim_preview", _unclaim_intent, False, "released_elsewhere"),
        ("build_sub_activity_create_preview", _sub_create_intent, True,
         "sub_activity_created_elsewhere"),
        ("build_sub_activity_create_preview", _sub_create_intent, False,
         "sub_activity_not_created"),
        ("build_sub_activity_delete_preview",
         lambda: _sub_lifecycle_intent(is_restore=False), True,
         "sub_activity_deleted_elsewhere"),
        ("build_sub_activity_delete_preview",
         lambda: _sub_lifecycle_intent(is_restore=False), False,
         "sub_activity_delete_not_applied"),
        ("build_sub_activity_restore_preview",
         lambda: _sub_lifecycle_intent(is_restore=True), True,
         "sub_activity_restore_not_applied"),
        ("build_sub_activity_restore_preview",
         lambda: _sub_lifecycle_intent(is_restore=True), False,
         "sub_activity_restored_elsewhere"),
    ],
)
def test_unknown_outcomes_always_close(tmp_path, builder, intent_factory, exists, code) -> None:
    transport = FakeClaimTransport()
    transport.units.append({
        "id": str(NEW_SUB), "activity_id": str(ACTIVITY), "name": "小组A",
        "type": "sub_activity", "is_deleted": True,
    })
    if builder == "build_participant_unclaim_preview":
        transport.claims = [_claim(P1, OWNER)]
    store, gateway, _, _, proposal, waiting, principal, turn_id = _setup(
        tmp_path, f"p58b-unknown-{code}-{builder}", builder, intent_factory(),
        transport=transport,
    )
    try:
        transport.mode = "ambiguous"
        assert _execute(gateway, principal, proposal, waiting).resolution is c.ExecutionResolution.UNKNOWN
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.RECOVERING
        assert turn.execution_resolution is c.ExecutionResolution.UNKNOWN

        if builder == "build_participant_claim_preview":
            transport.claims = [_claim(P1, OWNER)] if exists else []
        elif builder == "build_participant_unclaim_preview":
            transport.claims = [_claim(P1, OWNER)] if exists else []
        elif builder == "build_sub_activity_create_preview":
            transport.units = [
                unit for unit in transport.units
                if unit["id"] != str(NEW_SUB)
            ]
            if exists:
                transport.units.append({
                    "id": str(NEW_SUB), "activity_id": str(ACTIVITY), "name": "小组A",
                    "type": "sub_activity", "is_deleted": False,
                })
        else:
            transport.units[-1]["is_deleted"] = exists

        stored = store.get_proposal(OWNER, proposal.proposal_id)
        outcome = asyncio.run(gateway.reconcile(principal, stored, "token-a"))
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == code
        assert len(transport.post_calls) == 1
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.CANCELLED
    finally:
        store.close()


def test_legacy_sub_activities_are_never_backfilled_by_a_dispatch(tmp_path) -> None:
    # The Agent only calls the three-argument RPC; it never writes scope rows or
    # the configuration flag, so pre-migration children stay legacy-unscoped.
    store, gateway, _, transport, proposal, waiting, principal, _ = _setup(
        tmp_path, "p58b-legacy", "build_sub_activity_create_preview",
        _sub_create_intent(),
    )
    try:
        assert _execute(gateway, principal, proposal, waiting).resolution is c.ExecutionResolution.SUCCEEDED
        assert len(transport.post_calls) == 1
        payload = transport.post_calls[0]["payload"]
        assert set(payload) == {"activity_id", "name", "participant_ids"}
        assert "participant_scope_configured" not in json.dumps(payload)
    finally:
        store.close()
