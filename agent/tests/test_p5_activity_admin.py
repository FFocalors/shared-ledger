from __future__ import annotations

"""P5.8c Creator-only administration: members, creator, archive, delete."""

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
from test_p5_live_write import ACTIVITY, FakeReadBackend, P1, P2
from test_sqlite_persistence import OWNER, _session, _submit, _wait_with_proposal


OTHER_USER = uuid.UUID("99999999-9999-4999-8999-999999999999")


def _activity_row(*, creator=OWNER, archived=False, deleted=False) -> dict:
    return {
        "id": str(ACTIVITY),
        "name": "Trip",
        "type": "large",
        "base_currency": "CNY",
        "multi_currency_enabled": False,
        "created_by": str(creator),
        "archived_at": "2026-10-01T00:00:00+00:00" if archived else None,
        "is_deleted": deleted,
        "participants_locked_at": None,
        "join_code": "12345678",
    }


def _participant_row(participant_id=P1, name="Ann") -> dict:
    return {
        "id": str(participant_id),
        "activity_id": str(ACTIVITY),
        "name": name,
        "participant_order": 0,
        "is_deleted": False,
    }


class FakeAdminTransport:
    def __init__(self) -> None:
        self.post_calls: list[dict] = []
        self.get_calls: list[str] = []
        self.mode = "success"
        self.activity = _activity_row()
        self.members = [OWNER, OTHER_USER]
        self.claims = [
            {
                "id": str(uuid.uuid4()), "activity_id": str(ACTIVITY),
                "participant_id": str(P1), "user_id": str(OTHER_USER),
            },
        ]
        self.participants = [_participant_row(P1, "Ann"), _participant_row(P2, "Ben")]
        self.status = {
            "activity_id": str(ACTIVITY),
            "total_debt": 12.5,
            "total_prepayment": 0.0,
            "has_unsettled_debt": True,
            "completed": False,
        }
        self.remove_changed = True
        self.transfer_new_creator = str(OTHER_USER)
        self.archive_changed = True
        self.archive_archived = True
        self.unarchive_changed = True
        self.unarchive_archived = False
        self.delete_changed = True

    def _error(self, code: str, message: str):
        return 400, json.dumps({"code": code, "message": message}).encode()

    def get_json(self, url, headers, *, timeout, max_response_bytes):  # noqa: ANN001
        self.get_calls.append(url)
        parsed = urlsplit(url)
        table = parsed.path.rsplit("/", 1)[-1]
        params = dict(parse_qsl(parsed.query))
        if table == "activities":
            return 200, json.dumps([self.activity]).encode()
        if table == "activity_members":
            return 200, json.dumps(
                [{"user_id": str(item)} for item in self.members],
            ).encode()
        if table == "participant_claims":
            return 200, json.dumps(self.claims).encode()
        if table == "participants":
            rows = self.participants
            if "id" in params:
                wanted = params["id"].removeprefix("eq.")
                rows = [row for row in rows if row["id"] == wanted]
            return 200, json.dumps(rows).encode()
        if table == "activity_financial_status":
            return 200, json.dumps([self.status]).encode()
        return 200, b"[]"

    def post_json(self, url, headers, payload, *, timeout, max_response_bytes):  # noqa: ANN001
        self.post_calls.append({"url": url, "payload": dict(payload)})
        if self.mode == "ambiguous":
            raise LiveWriteError("upstream_ambiguous", ambiguous=True)
        if self.mode == "creator":
            return self._error("42501", "creator permission required")
        if self.mode == "not_found":
            return self._error("P0002", "activity member was not found")
        if self.mode == "invalid":
            return self._error("22023", "creator cannot remove self")
        if self.mode == "archived_server":
            return self._error("55000", "archived activity is read-only")
        if url.endswith("/remove_activity_member"):
            return 200, json.dumps(self.remove_changed).encode()
        if url.endswith("/transfer_activity_creator"):
            return 200, json.dumps(self.transfer_new_creator).encode()
        if url.endswith("/archive_activity"):
            return 200, json.dumps([{
                "activity_id": str(ACTIVITY),
                "archived": self.archive_archived,
                "changed": self.archive_changed,
                "archived_at": "2026-10-26T00:00:00+00:00",
                "total_debt": 12.5,
                "total_prepayment": 0,
                "completed": False,
                "has_unsettled": True,
                "warning": "activity has unsettled debt or prepayment balance",
            }]).encode()
        if url.endswith("/unarchive_activity"):
            return 200, json.dumps([{
                "activity_id": str(ACTIVITY),
                "archived": self.unarchive_archived,
                "changed": self.unarchive_changed,
                "archived_at": None,
                "total_debt": 12.5,
                "total_prepayment": 0,
                "completed": False,
                "has_unsettled": True,
                "warning": "activity has unsettled debt or prepayment balance",
            }]).encode()
        if url.endswith("/delete_activity"):
            return 200, json.dumps(self.delete_changed).encode()
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


def _setup(tmp_path, name: str, builder: str, intent, *, transport=None):
    store = SQLiteAgentStore(tmp_path / f"{name}.sqlite3", admission_enabled=True)
    store.start()
    session = _session(store, OWNER)
    _, turn_id = _submit(store, session, OWNER)
    transport = transport or FakeAdminTransport()
    gateway = LiveExpenseGateway(
        LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
        store, FakeReadBackend(version=5, base_currency="CNY", activity_type="large"),
        transport,
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
    return store, gateway, transport, proposal, waiting, principal, turn_id


def _remove_intent(user_id=OTHER_USER) -> c.ActivityMemberRemoveIntent:
    return c.ActivityMemberRemoveIntent(
        kind="activity.member.remove", activity_id=ACTIVITY, user_id=user_id,
    )


def _transfer_intent(user_id=OTHER_USER) -> c.ActivityCreatorTransferIntent:
    return c.ActivityCreatorTransferIntent(
        kind="activity.creator.transfer",
        activity_id=ACTIVITY, new_creator_user_id=user_id,
    )


def _archive_intent() -> c.ActivityArchiveIntent:
    return c.ActivityArchiveIntent(kind="activity.archive", activity_id=ACTIVITY)


def _unarchive_intent() -> c.ActivityUnarchiveIntent:
    return c.ActivityUnarchiveIntent(kind="activity.unarchive", activity_id=ACTIVITY)


def _delete_intent() -> c.ActivityDeleteIntent:
    return c.ActivityDeleteIntent(kind="activity.delete", activity_id=ACTIVITY)


def _preview_failure(tmp_path, name, builder, intent, transport):
    store = SQLiteAgentStore(tmp_path / f"{name}.sqlite3", admission_enabled=True)
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
            asyncio.run(getattr(gateway, builder)(
                owner_user_id=OWNER, session_id=session, turn_id=turn_id,
                intent=intent, access_token="token-a",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                agent_disable_revision=0, now=datetime.now(timezone.utc),
            ))
        assert transport.post_calls == []
        return excinfo.value.code
    finally:
        store.close()


# --------------------------------------------------------------- member removal


def test_member_remove_previews_and_executes(tmp_path) -> None:
    store, gateway, transport, proposal, waiting, principal, _ = _setup(
        tmp_path, "p58c-remove", "build_activity_member_remove_preview",
        _remove_intent(),
    )
    try:
        assert proposal.operation == "activity.member.remove"
        assert proposal.preview.operation == "activity.member.remove"
        assert proposal.preview.participant_name == "Ann"
        assert proposal.preview.target_user_ref is not None
        assert "撤销访问" in proposal.preview.summary
        assert transport.post_calls == []

        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "member_removed"
        call = transport.post_calls[0]
        assert call["url"].endswith("/rest/v1/rpc/remove_activity_member")
        # Only the membership goes; Participant rows and history are untouched.
        assert call["payload"] == {
            "activity_id": str(ACTIVITY), "user_id": str(OTHER_USER),
        }
    finally:
        store.close()


def test_member_remove_preview_rejections(tmp_path) -> None:
    transport = FakeAdminTransport()
    assert _preview_failure(
        tmp_path, "p58c-remove-self", "build_activity_member_remove_preview",
        _remove_intent(OWNER), transport,
    ) == "cannot_remove_self"

    transport = FakeAdminTransport()
    transport.members = [OWNER]
    assert _preview_failure(
        tmp_path, "p58c-remove-nonmember", "build_activity_member_remove_preview",
        _remove_intent(OTHER_USER), transport,
    ) == "member_not_found"

    transport = FakeAdminTransport()
    transport.activity["created_by"] = str(OTHER_USER)
    assert _preview_failure(
        tmp_path, "p58c-remove-noncreator", "build_activity_member_remove_preview",
        _remove_intent(OTHER_USER), transport,
    ) == "creator_permission_required"

    transport = FakeAdminTransport()
    transport.activity["archived_at"] = "2026-10-01T00:00:00+00:00"
    assert _preview_failure(
        tmp_path, "p58c-remove-archived", "build_activity_member_remove_preview",
        _remove_intent(OTHER_USER), transport,
    ) == "activity_archived"


def test_member_remove_cannot_target_the_creator() -> None:
    with pytest.raises(ValidationError):
        c.FixedActivityMemberRemoveCommand(
            operation="activity.member.remove",
            activity_id=ACTIVITY,
            user_id=OWNER,
            expected_creator_user_id=OWNER,
            expected_members_digest="a" * 64,
        )


# -------------------------------------------------------------------- transfer


def test_creator_transfer_previews_and_executes(tmp_path) -> None:
    store, gateway, transport, proposal, waiting, principal, _ = _setup(
        tmp_path, "p58c-transfer", "build_activity_creator_transfer_preview",
        _transfer_intent(),
    )
    try:
        assert proposal.operation == "activity.creator.transfer"
        assert proposal.preview.participant_name == "Ann"
        assert "当前创建者" in proposal.preview.summary

        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "creator_transferred"
        assert transport.post_calls[0]["payload"] == {
            "activity_id": str(ACTIVITY), "new_creator_user_id": str(OTHER_USER),
        }
    finally:
        store.close()


def test_creator_transfer_rejections(tmp_path) -> None:
    transport = FakeAdminTransport()
    assert _preview_failure(
        tmp_path, "p58c-transfer-self", "build_activity_creator_transfer_preview",
        _transfer_intent(OWNER), transport,
    ) == "cannot_transfer_to_self"

    transport = FakeAdminTransport()
    transport.members = [OWNER]
    assert _preview_failure(
        tmp_path, "p58c-transfer-nonmember", "build_activity_creator_transfer_preview",
        _transfer_intent(OTHER_USER), transport,
    ) == "new_creator_not_member"

    transport = FakeAdminTransport()
    transport.activity["created_by"] = str(OTHER_USER)
    assert _preview_failure(
        tmp_path, "p58c-transfer-noncreator", "build_activity_creator_transfer_preview",
        _transfer_intent(OTHER_USER), transport,
    ) == "creator_permission_required"


def test_creator_transfer_command_cannot_target_the_creator() -> None:
    with pytest.raises(ValidationError):
        c.FixedActivityCreatorTransferCommand(
            operation="activity.creator.transfer",
            activity_id=ACTIVITY,
            new_creator_user_id=OWNER,
            expected_creator_user_id=OWNER,
            expected_members_digest="a" * 64,
        )


# --------------------------------------------------------------------- archive


def test_archive_previews_with_the_unsettled_summary_and_executes(tmp_path) -> None:
    store, gateway, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p58c-archive", "build_activity_archive_preview", _archive_intent(),
    )
    try:
        assert proposal.operation == "activity.archive"
        assert proposal.preview.unsettled is True
        assert "债务 12.5" in proposal.preview.summary
        assert "未结清" in proposal.preview.summary
        assert transport.post_calls == []

        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "activity_archived"
        assert transport.post_calls[0]["payload"] == {"p_activity_id": str(ACTIVITY)}
        events = store.read_turn_view(OWNER, turn_id).events
        summaries = [
            item.event.payload.result_summary
            for item in events
            if item.event.type == "execution_result"
        ]
        assert any(
            "total_debt=12.5" in (value or "") and "has_unsettled=true" in (value or "")
            for value in summaries
        )
    finally:
        store.close()


def test_archive_is_idempotent(tmp_path) -> None:
    transport = FakeAdminTransport()
    transport.activity = _activity_row(archived=True)
    transport.archive_changed = False
    store, gateway, _, proposal, waiting, principal, _ = _setup(
        tmp_path, "p58c-archive-repeat", "build_activity_archive_preview",
        _archive_intent(), transport=transport,
    )
    try:
        assert proposal.canonical_command.expected_archived is True
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "activity_already_archived"
    finally:
        store.close()


def test_archive_rejects_a_non_creator(tmp_path) -> None:
    transport = FakeAdminTransport()
    transport.activity["created_by"] = str(OTHER_USER)
    assert _preview_failure(
        tmp_path, "p58c-archive-noncreator", "build_activity_archive_preview",
        _archive_intent(), transport,
    ) == "creator_permission_required"


# ------------------------------------------------------------------- unarchive


def test_unarchive_previews_and_executes(tmp_path) -> None:
    transport = FakeAdminTransport()
    transport.activity = _activity_row(archived=True)
    store, gateway, _, proposal, waiting, principal, _ = _setup(
        tmp_path, "p58c-unarchive", "build_activity_unarchive_preview",
        _unarchive_intent(), transport=transport,
    )
    try:
        assert proposal.canonical_command.expected_archived is True
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "activity_unarchived"
        assert transport.post_calls[0]["payload"] == {"p_activity_id": str(ACTIVITY)}
    finally:
        store.close()


def test_unarchive_reports_a_live_activity(tmp_path) -> None:
    transport = FakeAdminTransport()
    transport.unarchive_changed = False
    store, gateway, _, proposal, waiting, principal, _ = _setup(
        tmp_path, "p58c-unarchive-noop", "build_activity_unarchive_preview",
        _unarchive_intent(), transport=transport,
    )
    try:
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "activity_not_archived"
    finally:
        store.close()


def test_unarchive_rejects_a_non_creator(tmp_path) -> None:
    transport = FakeAdminTransport()
    transport.activity = _activity_row(archived=True, creator=OTHER_USER)
    assert _preview_failure(
        tmp_path, "p58c-unarchive-noncreator", "build_activity_unarchive_preview",
        _unarchive_intent(), transport,
    ) == "creator_permission_required"


# ---------------------------------------------------------------------- delete


def test_delete_previews_and_executes(tmp_path) -> None:
    store, gateway, transport, proposal, waiting, principal, _ = _setup(
        tmp_path, "p58c-delete", "build_activity_delete_preview", _delete_intent(),
    )
    try:
        assert proposal.operation == "activity.delete"
        assert "无法恢复" in proposal.preview.summary
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.SUCCEEDED
        assert outcome.code == "activity_deleted"
        assert transport.post_calls[0]["payload"] == {"activity_id": str(ACTIVITY)}
    finally:
        store.close()


def test_delete_refuses_an_archived_activity_before_any_rpc(tmp_path) -> None:
    transport = FakeAdminTransport()
    transport.activity["archived_at"] = "2026-10-01T00:00:00+00:00"
    assert _preview_failure(
        tmp_path, "p58c-delete-archived", "build_activity_delete_preview",
        _delete_intent(), transport,
    ) == "activity_archived"


def test_delete_refuses_a_non_creator(tmp_path) -> None:
    transport = FakeAdminTransport()
    transport.activity["created_by"] = str(OTHER_USER)
    assert _preview_failure(
        tmp_path, "p58c-delete-noncreator", "build_activity_delete_preview",
        _delete_intent(), transport,
    ) == "creator_permission_required"


def test_delete_server_rejection_is_reported(tmp_path) -> None:
    store, gateway, transport, proposal, waiting, principal, _ = _setup(
        tmp_path, "p58c-delete-rejected", "build_activity_delete_preview",
        _delete_intent(),
    )
    try:
        transport.mode = "creator"
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.REJECTED
        assert outcome.code == "creator_permission_required"
    finally:
        store.close()


# ------------------------------------------------------- idempotency & versions


def test_duplicate_confirmation_sends_one_rpc(tmp_path) -> None:
    store, gateway, transport, proposal, waiting, principal, turn_id = _setup(
        tmp_path, "p58c-duplicate", "build_activity_delete_preview", _delete_intent(),
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
        ("build_activity_member_remove_preview", _remove_intent, "members",
         "members_changed"),
        ("build_activity_creator_transfer_preview", _transfer_intent, "members",
         "members_changed"),
        ("build_activity_creator_transfer_preview", _transfer_intent, "creator",
         "creator_changed"),
        ("build_activity_archive_preview", _archive_intent, "archived",
         "activity_state_changed"),
        ("build_activity_delete_preview", _delete_intent, "creator",
         "creator_changed"),
    ],
)
def test_preview_changes_close_without_an_rpc(
    tmp_path, builder, intent_factory, change, code,
) -> None:
    transport = FakeAdminTransport()
    store, gateway, _, proposal, waiting, principal, turn_id = _setup(
        tmp_path, f"p58c-change-{change}-{builder}", builder, intent_factory(),
        transport=transport,
    )
    try:
        if change == "members":
            transport.members = [OWNER, OTHER_USER, uuid.uuid4()]
        elif change == "creator":
            transport.activity["created_by"] = str(uuid.uuid4())
        else:
            transport.activity["archived_at"] = "2026-10-02T00:00:00+00:00"
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
    ("builder", "intent_factory", "changed", "code"),
    [
        ("build_activity_member_remove_preview", _remove_intent, True,
         "member_removed_elsewhere"),
        ("build_activity_member_remove_preview", _remove_intent, False,
         "member_remove_not_applied"),
        ("build_activity_creator_transfer_preview", _transfer_intent, True,
         "creator_transferred_elsewhere"),
        ("build_activity_creator_transfer_preview", _transfer_intent, False,
         "creator_transfer_not_applied"),
        ("build_activity_archive_preview", _archive_intent, True, "archived_elsewhere"),
        ("build_activity_archive_preview", _archive_intent, False, "archive_not_applied"),
        ("build_activity_unarchive_preview", _unarchive_intent, False,
         "unarchived_elsewhere"),
        ("build_activity_unarchive_preview", _unarchive_intent, True,
         "unarchive_not_applied"),
        ("build_activity_delete_preview", _delete_intent, True,
         "activity_deleted_elsewhere"),
        ("build_activity_delete_preview", _delete_intent, False,
         "delete_activity_not_applied"),
    ],
)
def test_unknown_administration_outcomes_always_close(
    tmp_path, builder, intent_factory, changed, code,
) -> None:
    transport = FakeAdminTransport()
    archived_builder = builder in (
        "build_activity_unarchive_preview",
    )
    if archived_builder:
        transport.activity = _activity_row(archived=True)
    store, gateway, _, proposal, waiting, principal, turn_id = _setup(
        tmp_path, f"p58c-unknown-{code}-{builder}", builder, intent_factory(),
        transport=transport,
    )
    try:
        transport.mode = "ambiguous"
        assert _execute(gateway, principal, proposal, waiting).resolution is c.ExecutionResolution.UNKNOWN

        if builder == "build_activity_member_remove_preview":
            transport.members = [OWNER] if changed else [OWNER, OTHER_USER]
        elif builder == "build_activity_creator_transfer_preview":
            transport.activity["created_by"] = (
                str(OTHER_USER) if changed else str(OWNER)
            )
        elif builder == "build_activity_archive_preview":
            transport.activity["archived_at"] = (
                "2026-10-02T00:00:00+00:00" if changed else None
            )
        elif builder == "build_activity_unarchive_preview":
            transport.activity["archived_at"] = (
                None if not changed else "2026-10-02T00:00:00+00:00"
            )
        else:
            transport.activity["is_deleted"] = changed

        stored = store.get_proposal(OWNER, proposal.proposal_id)
        outcome = asyncio.run(gateway.reconcile(principal, stored, "token-a"))
        assert outcome.resolution is c.ExecutionResolution.CLOSED
        assert outcome.code == code
        assert len(transport.post_calls) == 1
        assert store.get_turn(OWNER, turn_id).record.turn.state is c.TurnState.CANCELLED
    finally:
        store.close()


def test_archived_activity_management_write_is_rejected_by_the_server(tmp_path) -> None:
    # After archiving, the server is read-only: a management write is dispatched
    # (the preview captured archived=true) and comes back rejected, never closed
    # as a success or a silent no-op.
    transport = FakeAdminTransport()
    transport.activity["archived_at"] = "2026-10-26T00:00:00+00:00"
    transport.mode = "archived_server"
    store = SQLiteAgentStore(tmp_path / "p58c-archived-write.sqlite3", admission_enabled=True)
    store.start()
    try:
        session = _session(store, OWNER)
        _, turn_id = _submit(store, session, OWNER)
        gateway = LiveExpenseGateway(
            LiveWriteConfig(project_url="https://example.supabase.co", publishable_key="anon-key"),
            store, FakeReadBackend(version=5, base_currency="CNY", activity_type="large"),
            transport,
        )
        proposal = asyncio.run(gateway.build_participant_create_preview(
            owner_user_id=OWNER, session_id=session, turn_id=turn_id,
            intent=c.ParticipantCreateIntent(
                kind="participant.create", activity_id=ACTIVITY, name="Zoe",
            ),
            access_token="token-a",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            agent_disable_revision=0, now=datetime.now(timezone.utc),
        ))
        waiting = _wait_with_proposal(store, OWNER, turn_id, proposal)
        principal = Principal(OWNER, datetime.now(timezone.utc) + timedelta(hours=1))
        outcome = _execute(gateway, principal, proposal, waiting)
        assert outcome.resolution is c.ExecutionResolution.REJECTED
        assert outcome.code == "activity_read_only"
        assert len(transport.post_calls) == 1
    finally:
        store.close()
