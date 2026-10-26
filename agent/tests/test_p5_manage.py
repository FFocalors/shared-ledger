from __future__ import annotations

"""P5.8a Activity / Participant management: preview, execute, reconcile."""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlsplit

import pytest

from agent.app import contracts as c
from agent.app.p5_write import LiveExpenseGateway, LiveWriteConfig, LiveWriteError
from agent.app.ports import Principal
from agent.app.store import SQLiteAgentStore
from test_p5_live_write import ACTIVITY, FakeReadBackend, P1, P2
from test_sqlite_persistence import OWNER, _session, _submit, _wait_with_proposal


NEW_ACTIVITY = uuid.UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
NEW_PARTICIPANT = uuid.UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")


def _activity_row(activity_id=ACTIVITY, name="Trip", *, archived=False, deleted=False,
                  locked=False, join_code="12345678", created_by=OWNER,
                  activity_type="normal", currency="CNY", multi=False) -> dict:
    return {
        "id": str(activity_id),
        "name": name,
        "type": activity_type,
        "base_currency": currency,
        "multi_currency_enabled": multi,
        "created_by": str(created_by),
        "archived_at": "2026-10-01T00:00:00+00:00" if archived else None,
        "is_deleted": deleted,
        "participants_locked_at": "2026-10-01T00:00:00+00:00" if locked else None,
        "join_code": join_code,
    }


def _participant_row(participant_id=P1, name="Ann", *, activity_id=ACTIVITY, order=0,
                     deleted=False) -> dict:
    return {
        "id": str(participant_id),
        "activity_id": str(activity_id),
        "name": name,
        "participant_order": order,
        "is_deleted": deleted,
    }


class FakeManagementTransport:
    def __init__(self) -> None:
        self.post_calls: list[dict] = []
        self.get_calls: list[str] = []
        self.mode = "success"
        self.activities: list[dict] = []
        self.participants: list[dict] = [_participant_row()]
        self.usage: dict[str, list[dict]] = {
            "participant_claims": [], "payments": [], "splits": [], "transfers": [],
        }
        self.created_activity_id = NEW_ACTIVITY
        self.created_join_code = "87654321"
        self.joined_activity_id = ACTIVITY
        self.join_is_new = True
        self.created_participant_id = NEW_PARTICIPANT
        self.created_participant_order = 3
        self.deleted_participant_id = P1
        self.delete_changed = True

    def _error(self, code: str, message: str):
        return 400, json.dumps({"code": code, "message": message}).encode()

    def get_json(self, url, headers, *, timeout, max_response_bytes):  # noqa: ANN001
        self.get_calls.append(url)
        parsed = urlsplit(url)
        table = parsed.path.rsplit("/", 1)[-1]
        params = dict(parse_qsl(parsed.query))
        if table == "activities":
            rows = self.activities
            if "id" in params:
                wanted = params["id"].removeprefix("eq.")
                rows = [row for row in rows if row["id"] == wanted]
            if "join_code" in params:
                wanted = params["join_code"].removeprefix("eq.")
                rows = [row for row in rows if row["join_code"] == wanted]
            if "name" in params:
                wanted = params["name"].removeprefix("eq.")
                rows = [row for row in rows if row["name"] == wanted]
            return 200, json.dumps(rows).encode()
        if table == "participants":
            rows = self.participants
            if "id" in params:
                wanted = params["id"].removeprefix("eq.")
                rows = [row for row in rows if row["id"] == wanted]
            if "activity_id" in params:
                wanted = params["activity_id"].removeprefix("eq.")
                rows = [row for row in rows if row["activity_id"] == wanted]
            return 200, json.dumps(rows).encode()
        if table in self.usage:
            return 200, json.dumps(self.usage[table]).encode()
        return 200, b"[]"

    def post_json(self, url, headers, payload, *, timeout, max_response_bytes):  # noqa: ANN001
        self.post_calls.append({"url": url, "payload": dict(payload)})
        if self.mode == "ambiguous":
            raise LiveWriteError("upstream_ambiguous", ambiguous=True)
        if self.mode == "invalid":
            return self._error("22023", "invalid management request")
        if self.mode == "locked":
            return self._error("55000", "participant list is locked")
        if self.mode == "used":
            return self._error("23514", "participant is claimed or used by financial facts")
        if self.mode == "archived":
            return self._error("55000", "archived activity is read-only")
        if self.mode == "not_found":
            return self._error("P0002", "activity not found")
        if self.mode == "forbidden":
            return self._error("42501", "caller is not an active activity member")
        if url.endswith("/create_activity"):
            return 200, json.dumps([{
                "activity_id": str(self.created_activity_id),
                "join_code": self.created_join_code,
                "activity_name": payload["name"],
                "activity_type": payload["type"],
                "activity_base_currency": payload["base_currency"],
                "activity_multi_currency_enabled": payload["multi_currency_enabled"],
            }]).encode()
        if url.endswith("/join_activity_by_code"):
            return 200, json.dumps([{
                "activity_id": str(self.joined_activity_id),
                "is_new": self.join_is_new,
            }]).encode()
        if url.endswith("/create_participant"):
            return 200, json.dumps([{
                "participant_id": str(self.created_participant_id),
                "participant_name": payload["name"],
                "participant_order": self.created_participant_order,
            }]).encode()
        if url.endswith("/delete_participant"):
            return 200, json.dumps([{
                "participant_id": str(self.deleted_participant_id),
                "deleted": self.delete_changed,
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
           activity_type: str = "large"):
    store = SQLiteAgentStore(tmp_path / f"{name}.sqlite3", admission_enabled=True)
    store.start()
    session = _session(store, OWNER)
    _, turn_id = _submit(store, session, OWNER)
    transport = transport or FakeManagementTransport()
    if builder in (
        "build_participant_create_preview", "build_participant_delete_preview",
    ) and not transport.activities:
        transport.activities = [_activity_row()]
    gateway = LiveExpenseGateway(
        LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
        store, FakeReadBackend(version=5, base_currency="CNY", activity_type=activity_type),
        transport,
    )
    kwargs: dict = {}
    if builder != "build_activity_create_preview" and builder != "build_activity_join_preview":
        kwargs["expires_at"] = datetime.now(timezone.utc) + timedelta(hours=1)
    proposal = asyncio.run(getattr(gateway, builder)(
        owner_user_id=OWNER,
        session_id=session,
        turn_id=turn_id,
        intent=intent,
        access_token="token-a",
        agent_disable_revision=0,
        now=datetime.now(timezone.utc),
        **kwargs,
    ))
    waiting = _wait_with_proposal(store, OWNER, turn_id, proposal)
    principal = Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1))
    return store, gateway, transport, proposal, waiting, principal, turn_id


def _activity_create_intent() -> c.ActivityCreateIntent:
    return c.ActivityCreateIntent(
        kind="activity.create", name="秋游", activity_type="large",
        base_currency="CNY", multi_currency_enabled=True,
    )


def _join_intent(code: str = "12345678") -> c.ActivityJoinIntent:
    return c.ActivityJoinIntent(kind="activity.join", join_code=code)


def _participant_create_intent(name: str = "Ben") -> c.ParticipantCreateIntent:
    return c.ParticipantCreateIntent(
        kind="participant.create", activity_id=ACTIVITY, name=name,
    )


def _participant_delete_intent(participant_id=P1) -> c.ParticipantDeleteIntent:
    return c.ParticipantDeleteIntent(
        kind="participant.delete", activity_id=ACTIVITY, participant_id=participant_id,
    )


# --------------------------------------------------------------- create activity


def test_activity_create_previews_and_executes_without_a_creator_id(tmp_path) -> None:
    store, gateway, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p58-create", "build_activity_create_preview", _activity_create_intent(),
    )
    try:
        assert proposal.operation == "activity.create"
        assert isinstance(proposal.preview, c.ManagementPreview)
        assert proposal.preview.operation == "activity.create"
        assert proposal.preview.activity_name == "秋游"
        assert proposal.preconditions.activity_id is None
        assert transport.post_calls == []

        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "activity_created"
        assert len(transport.post_calls) == 1
        call = transport.post_calls[0]
        assert call["url"].endswith("/rest/v1/rpc/create_activity")
        assert call["payload"] == {
            "name": "秋游",
            "type": "large",
            "base_currency": "CNY",
            "multi_currency_enabled": True,
        }
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.COMPLETED
    finally:
        store.close()


def test_activity_create_refuses_a_duplicate_name(tmp_path) -> None:
    transport = FakeManagementTransport()
    transport.activities = [_activity_row(name="秋游")]
    store = SQLiteAgentStore(tmp_path / "p58-create-dup.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        gateway = LiveExpenseGateway(
            LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
            store, FakeReadBackend(version=5, base_currency="CNY"), transport,
        )
        with pytest.raises(LiveWriteError) as excinfo:
            asyncio.run(gateway.build_activity_create_preview(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=_activity_create_intent(), access_token="token-a",
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert excinfo.value.code == "activity_name_conflict"
        assert transport.post_calls == []
    finally:
        store.close()


# ----------------------------------------------------------------- join activity


def test_activity_join_previews_and_executes(tmp_path) -> None:
    store, gateway, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p58-join", "build_activity_join_preview", _join_intent(),
    )
    try:
        assert proposal.operation == "activity.join"
        assert proposal.preview.join_code == "12345678"
        assert "加入不等于认领参与人" in proposal.preview.summary
        assert proposal.preconditions.activity_id is None
        assert transport.post_calls == []

        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "activity_joined"
        assert transport.post_calls[0]["payload"] == {"join_code": "12345678"}
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.COMPLETED
    finally:
        store.close()


def test_activity_join_reports_an_existing_membership(tmp_path) -> None:
    transport = FakeManagementTransport()
    transport.join_is_new = False
    store, gateway, _, proposal, waiting, principal, _ = _setup(
        tmp_path, "p58-join-existing", "build_activity_join_preview", _join_intent(),
        transport=transport,
    )
    try:
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "activity_already_member"
    finally:
        store.close()


def test_activity_join_closes_on_an_archived_code(tmp_path) -> None:
    transport = FakeManagementTransport()
    transport.activities = [_activity_row(archived=True)]
    store, gateway, _, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p58-join-archived", "build_activity_join_preview", _join_intent(),
        transport=transport,
    )
    try:
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == "join_code_inactive"
        assert transport.post_calls == []
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.CANCELLED
    finally:
        store.close()


@pytest.mark.parametrize(
    ("server_mode", "code"),
    [("not_found", "activity_not_found"), ("archived", "activity_read_only")],
)
def test_activity_join_server_rejections(tmp_path, server_mode, code) -> None:
    store, gateway, transport, proposal, waiting, principal, _ = _setup(
        tmp_path, f"p58-join-{server_mode}", "build_activity_join_preview",
        _join_intent("99999999"),
    )
    try:
        transport.mode = server_mode
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.REJECTED
        assert outcome.code == code
    finally:
        store.close()


def test_activity_join_requires_eight_digits() -> None:
    with pytest.raises(Exception):
        c.ActivityJoinIntent(kind="activity.join", join_code="1234")


# ------------------------------------------------------------ create participant


def test_participant_create_previews_and_executes(tmp_path) -> None:
    store, gateway, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p58-participant-create", "build_participant_create_preview",
        _participant_create_intent(),
    )
    try:
        assert proposal.operation == "participant.create"
        assert proposal.preview.participant_name == "Ben"
        assert proposal.preview.participant_order is None
        assert "自动" in proposal.preview.summary
        assert transport.post_calls == []

        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "participant_created"
        call = transport.post_calls[0]
        assert call["url"].endswith("/rest/v1/rpc/create_participant")
        assert call["payload"] == {
            "activity_id": str(ACTIVITY), "name": "Ben", "participant_order": None,
        }
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.COMPLETED
    finally:
        store.close()


def test_participant_create_refuses_duplicate_names_and_lock(tmp_path) -> None:
    for label, mutate, code in (
        ("name", lambda t: t.participants.append(_participant_row(P2, "Ben", order=1)),
         "participant_name_conflict"),
        ("locked", lambda t: t.activities.__setitem__(0, _activity_row(locked=True)),
         "participant_list_locked"),
    ):
        transport = FakeManagementTransport()
        transport.activities = [_activity_row()]
        mutate(transport)
        store = SQLiteAgentStore(tmp_path / f"p58-pc-{label}.sqlite3", admission_enabled=True)
        store.start()
        try:
            session = _session(store, OWNER)
            _, turn_id = _submit(store, session, OWNER)
            gateway = LiveExpenseGateway(
                LiveWriteConfig(
                    project_url="https://example.supabase.co", publishable_key="anon-key",
                ),
                store, FakeReadBackend(version=5, base_currency="CNY"), transport,
            )
            with pytest.raises(LiveWriteError) as excinfo:
                asyncio.run(gateway.build_participant_create_preview(
                    owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                    intent=_participant_create_intent(), access_token="token-a",
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                    agent_disable_revision=0, now=datetime.now(timezone.utc),
                ))
            assert excinfo.value.code == code
            assert transport.post_calls == []
        finally:
            store.close()


# ------------------------------------------------------------ delete participant


def test_participant_delete_previews_and_executes(tmp_path) -> None:
    store, gateway, transport, proposal, waiting, principal, _ = _setup(
        tmp_path, "p58-participant-delete", "build_participant_delete_preview",
        _participant_delete_intent(),
    )
    try:
        assert proposal.operation == "participant.delete"
        assert proposal.preview.participant_name == "Ann"
        assert proposal.preview.participant_id == P1
        assert transport.post_calls == []

        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "participant_deleted"
        assert transport.post_calls[0]["payload"] == {"participant_id": str(P1)}
    finally:
        store.close()


def test_participant_delete_of_an_already_deleted_row_is_idempotent(tmp_path) -> None:
    store, gateway, transport, proposal, waiting, principal, _ = _setup(
        tmp_path, "p58-participant-already", "build_participant_delete_preview",
        _participant_delete_intent(),
    )
    try:
        transport.delete_changed = False
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "participant_already_deleted"
    finally:
        store.close()


@pytest.mark.parametrize("used_by", ["participant_claims", "payments", "splits", "transfers"])
def test_participant_delete_refuses_a_claimed_or_used_row(tmp_path, used_by) -> None:
    transport = FakeManagementTransport()
    transport.activities = [_activity_row()]
    transport.usage[used_by] = [{"id": str(uuid.uuid4())}]
    store = SQLiteAgentStore(tmp_path / f"p58-used-{used_by}.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        gateway = LiveExpenseGateway(
            LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
            store, FakeReadBackend(version=5, base_currency="CNY"), transport,
        )
        with pytest.raises(LiveWriteError) as excinfo:
            asyncio.run(gateway.build_participant_delete_preview(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=_participant_delete_intent(), access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert excinfo.value.code == "participant_claimed_or_used"
        assert transport.post_calls == []
    finally:
        store.close()


def test_participant_delete_refuses_a_locked_list(tmp_path) -> None:
    transport = FakeManagementTransport()
    transport.activities = [_activity_row(locked=True)]
    store = SQLiteAgentStore(tmp_path / "p58-pd-locked.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        gateway = LiveExpenseGateway(
            LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
            store, FakeReadBackend(version=5, base_currency="CNY"), transport,
        )
        with pytest.raises(LiveWriteError) as excinfo:
            asyncio.run(gateway.build_participant_delete_preview(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=_participant_delete_intent(), access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert excinfo.value.code == "participant_list_locked"
        assert transport.post_calls == []
    finally:
        store.close()


# ------------------------------------------------------- idempotency & versions


def test_duplicate_confirmation_sends_one_rpc(tmp_path) -> None:
    store, gateway, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p58-duplicate", "build_participant_create_preview",
        _participant_create_intent(),
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
    ("builder", "intent_factory", "mutate", "code"),
    [
        ("build_participant_create_preview", _participant_create_intent,
         lambda t: t.activities.__setitem__(0, _activity_row(locked=True)),
         "management_state_changed"),
        ("build_participant_create_preview", _participant_create_intent,
         lambda t: t.participants.append(_participant_row(P2, "Ben", order=1)),
         "participant_name_conflict"),
        ("build_participant_delete_preview", _participant_delete_intent,
         lambda t: t.participants.__setitem__(0, _participant_row(deleted=True)),
         "management_state_changed"),
        ("build_participant_delete_preview", _participant_delete_intent,
         lambda t: t.usage["payments"].append({"id": str(uuid.uuid4())}),
         "participant_claimed_or_used"),
    ],
)
def test_preview_state_changes_close_without_an_rpc(
    tmp_path, builder, intent_factory, mutate, code,
) -> None:
    transport = FakeManagementTransport()
    transport.activities = [_activity_row()]
    store, gateway, _, proposal, waiting, principal, turn_id = _setup(
        tmp_path, f"p58-change-{code}-{builder}", builder, intent_factory(),
        transport=transport,
    )
    try:
        mutate(transport)
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
        ("build_activity_create_preview", _activity_create_intent, True,
         "activity_created_elsewhere"),
        ("build_activity_create_preview", _activity_create_intent, False,
         "activity_not_created"),
        ("build_activity_join_preview", _join_intent, True, "joined_elsewhere"),
        ("build_activity_join_preview", _join_intent, False, "join_not_applied"),
        ("build_participant_create_preview", _participant_create_intent, True,
         "participant_created_elsewhere"),
        ("build_participant_create_preview", _participant_create_intent, False,
         "participant_not_created"),
        ("build_participant_delete_preview", _participant_delete_intent, True,
         "deleted_elsewhere"),
        ("build_participant_delete_preview", _participant_delete_intent, False,
         "delete_not_applied"),
    ],
)
def test_unknown_management_outcomes_always_close(
    tmp_path, builder, intent_factory, exists, code,
) -> None:
    transport = FakeManagementTransport()
    transport.activities = [_activity_row()]
    store, gateway, _, proposal, waiting, principal, turn_id = _setup(
        tmp_path, f"p58-unknown-{code}-{builder}", builder, intent_factory(),
        transport=transport,
    )
    try:
        transport.mode = "ambiguous"
        assert _execute(gateway, principal, proposal, waiting).resolution is c.ExecutionResolution.UNKNOWN
        turn = store.get_turn(OWNER, turn_id).record.turn
        assert turn.state is c.TurnState.RECOVERING
        assert turn.execution_resolution is c.ExecutionResolution.UNKNOWN

        if builder == "build_activity_create_preview":
            transport.activities = [_activity_row(NEW_ACTIVITY, "秋游",
                                                  currency="CNY", multi=True,
                                                  activity_type="large")] if exists else []
        elif builder == "build_activity_join_preview":
            transport.activities = [_activity_row()] if exists else []
        elif builder == "build_participant_create_preview":
            transport.participants = [_participant_row(), _participant_row(P2, "Ben", order=1)] \
                if exists else [_participant_row()]
        else:
            transport.participants = [_participant_row(deleted=True)] if exists else []

        stored = store.get_proposal(OWNER, proposal.proposal_id)
        outcome = asyncio.run(gateway.reconcile(principal, stored, "token-a"))
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == code
        assert len(transport.post_calls) == 1
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.CANCELLED
    finally:
        store.close()
