import json
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
from gateway import (  # noqa: E402
    ConfirmationCapability, FakeAuthority, Gateway, GatewayError, ProposalHandle,
    SessionHandle, proposal_for,
)

VECTORS = json.loads((ROOT / "docs/ai/training_analysis/v0.3_write_firewall_replay/controls_non_training/control_vectors.json").read_text(encoding="utf-8"))


def setup_gateway(tool, intent, arguments, *, enabled=None, binding=None, version="7"):
    activity_id = arguments.get("activity_id")
    snapshot = {"actor_id": "actor-proto", "activity_id": activity_id,
                "conversation_id": "conversation-proto", "financial_version": version,
                "enabled_tools": enabled if enabled is not None else [tool]}
    if binding:
        snapshot.update(binding)
    authority = FakeAuthority()
    authority.seed_session("session", snapshot)
    authority.seed_entity(activity_id, "activity", activity_id)
    for key, kind in Gateway.ID_FIELDS.items():
        if key == "activity_id":
            continue
        value = arguments.get(key)
        if isinstance(value, str):
            authority.seed_entity(value, kind, activity_id)
    for collection in ("payments", "manual_splits"):
        for row in arguments.get(collection, []):
            value = row.get("participant_id")
            if value:
                authority.seed_entity(value, "participant", activity_id)
    for value in arguments.get("aa_participant_ids", []):
        authority.seed_entity(value, "participant", activity_id)
    authority.seed_canonical_plan("session", {"intent_id": intent, "tool": tool, "arguments": arguments})
    return Gateway(authority), authority


def open_handle(gateway):
    return gateway.open_session("session")


def raw(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def fixture_proposal(control):
    cmd = control["simulator_registry_command"]
    return proposal_for(cmd["intent_id"], cmd["tool"], cmd["arguments"])


class GatewayBoundaryTests(unittest.TestCase):
    def test_model_write_denied_and_read_allowed(self):
        write = next(x for x in VECTORS["model_origin_controls"] if x["control_id"] == "model_l1_create_expense_valid_with_user_claim")
        args = write["model_output"]["arguments"]
        gw, _ = setup_gateway("create_expense", "create_expense", args, enabled=write["runtime_enabled_tools"])
        result = gw.handle_model_output(raw(write["model_output"]), open_handle(gw))
        self.assertEqual(result["decision"], "deny")
        self.assertEqual(result["reason"], "model_origin_write_forbidden")
        self.assertEqual(gw.adapter.writes, [])

        read = VECTORS["read_positive_controls"][0]
        read_args = read["model_output"]["arguments"]
        rgw, _ = setup_gateway("get_debt", "query_debt", read_args, enabled=read["runtime_enabled_tools"])
        read_result = rgw.handle_model_output(raw(read["model_output"]), open_handle(rgw))
        self.assertEqual(read_result["decision"], "read_noop")
        self.assertEqual(len(rgw.adapter.reads), 1)
        self.assertEqual(rgw.adapter.writes, [])

    def test_model_cannot_spoof_origin_or_confirmation(self):
        control = next(x for x in VECTORS["model_origin_controls"] if x["control_id"] == "model_output_extra_origin_confirmed_fields_common_reject")
        args = control["model_output"]["arguments"]
        gw, _ = setup_gateway("void_transfer", "void_transfer", args, enabled=control["runtime_enabled_tools"])
        result = gw.handle_model_output(raw(control["model_output"]), open_handle(gw))
        self.assertEqual(result["decision"], "deny")
        self.assertIn("schema", result["reason"])
        self.assertEqual(gw.adapter.writes, [])

    def test_exact_ui_click_dispatches_gateway_built_command_once(self):
        control = next(x for x in VECTORS["trusted_origin_controls"] if x["control_id"] == "trusted_l1_create_expense_exact_confirmation_current_binding")
        gw, _ = setup_gateway("create_expense", "create_expense", control["arguments"], binding=control["current_binding"], enabled=control["runtime_enabled_tools"])
        session = open_handle(gw)
        model_obj = fixture_proposal(control)
        original_amount = model_obj["operation"]["arguments"]["original_amount"]
        handle = gw.stage_proposal(raw(model_obj), session)
        model_obj["operation"]["arguments"]["original_amount"] = "99999"
        card = gw.fake_ui.display(handle)
        self.assertEqual(card["canonical_command"]["arguments"]["original_amount"], original_amount)
        card["canonical_command"]["arguments"]["original_amount"] = "88888"
        card["operation_digest"] = "user-edited-digest"
        with self.assertRaises(TypeError):
            gw.fake_ui.confirm(handle, arguments={"original_amount": "99999"})
        capability = gw.fake_ui.confirm(handle)
        result = gw.dispatch_confirmed(capability, session)
        self.assertEqual(result["decision"], "noop_recorded")
        self.assertEqual(result["command"]["arguments"]["original_amount"], original_amount)
        self.assertEqual(len(gw.adapter.writes), 1)
        self.assertEqual(gw.dispatch_confirmed(capability, session)["reason"], "capability_already_consumed")
        self.assertEqual(len(gw.adapter.writes), 1)

    def test_model_proposal_only_stages_and_requires_ui_callback(self):
        control = next(x for x in VECTORS["trusted_origin_controls"] if x["control_id"] == "trusted_l1_create_expense_exact_confirmation_current_binding")
        gw, _ = setup_gateway("create_expense", "create_expense", control["arguments"], binding=control["current_binding"], enabled=control["runtime_enabled_tools"])
        result = gw.handle_model_output(raw(fixture_proposal(control)), open_handle(gw))
        self.assertEqual(result["decision"], "proposal_staged_unconfirmed")
        self.assertEqual(gw.adapter.writes, [])
        self.assertEqual(len(gw._proposals), 1)
        self.assertEqual(gw._capabilities, {})

    def test_model_proposal_d4_never_stages(self):
        control = next(x for x in VECTORS["trusted_origin_controls"] if x["control_id"] == "trusted_d4_update_expense_even_with_exact_confirmation")
        args = control["arguments"]
        gw, _ = setup_gateway("update_expense", "update_expense", args, enabled=[])
        with self.assertRaises(GatewayError):
            gw.stage_proposal(raw(fixture_proposal(control)), open_handle(gw))
        self.assertEqual(gw.adapter.writes, [])

    def test_forged_and_cross_gateway_handles_fail(self):
        control = next(x for x in VECTORS["trusted_origin_controls"] if x["control_id"] == "trusted_l2_void_transfer_exact_confirmation_current_binding")
        gw1, _ = setup_gateway("void_transfer", "void_transfer", control["arguments"], binding=control["current_binding"], enabled=control["runtime_enabled_tools"])
        gw2, _ = setup_gateway("void_transfer", "void_transfer", control["arguments"], binding=control["current_binding"], enabled=control["runtime_enabled_tools"])
        h1 = open_handle(gw1)
        h2 = open_handle(gw2)
        self.assertEqual(gw1.handle_model_output("{}", h2)["decision"], "deny")
        proposal = gw1.stage_proposal(raw(fixture_proposal(control)), h1)
        cap = gw1.fake_ui.confirm(gw1.fake_ui.display(proposal)["proposal_handle"])
        self.assertEqual(gw2.dispatch_confirmed(cap, h2)["decision"], "deny")
        self.assertEqual(gw1.dispatch_confirmed({"trusted": True}, h1)["decision"], "deny")
        with self.assertRaises(TypeError):
            SessionHandle(object())
        with self.assertRaises(TypeError):
            ConfirmationCapability(object())
        with self.assertRaises(TypeError):
            ProposalHandle(object())

    def test_binding_change_after_ui_click_fails_closed_for_each_field(self):
        control = next(x for x in VECTORS["trusted_origin_controls"] if x["control_id"] == "trusted_l2_void_transfer_exact_confirmation_current_binding")
        for field, changed in (("actor_id", "actor-other"), ("activity_id", "00000000-0000-4000-8000-000000000088"),
                               ("conversation_id", "conversation-other"), ("financial_version", "10")):
            with self.subTest(field=field):
                gw, authority = setup_gateway("void_transfer", "void_transfer", control["arguments"], binding=control["current_binding"], enabled=control["runtime_enabled_tools"])
                session = open_handle(gw)
                proposal = gw.stage_proposal(raw(fixture_proposal(control)), session)
                capability = gw.fake_ui.confirm(gw.fake_ui.display(proposal)["proposal_handle"])
                authority.update_snapshot("session", **{field: changed})
                result = gw.dispatch_confirmed(capability, session)
                self.assertEqual(result["decision"], "deny")
                self.assertEqual(result["reason"], "current_binding_changed")
                self.assertEqual(gw.adapter.writes, [])

    def test_missing_required_session_binding_fails_closed(self):
        args = {"activity_id": "00000000-0000-4000-8000-000000000001"}
        for field in Gateway.REQUIRED_BINDINGS:
            with self.subTest(field=field):
                gw, authority = setup_gateway("get_debt", "query_debt", args)
                authority.update_snapshot("session", **{field: None})
                with self.assertRaises(GatewayError):
                    gw.open_session("session")

    def test_result_id_never_substitutes_for_transfer_id_even_if_uuid_shaped(self):
        control = next(x for x in VECTORS["trusted_origin_controls"] if x["control_id"] == "trusted_l2_void_transfer_exact_confirmation_current_binding")
        args = dict(control["arguments"])
        result_id = "00000000-0000-4000-8000-000000000099"
        args["transfer_id"] = result_id
        gw, authority = setup_gateway("void_transfer", "void_transfer", args, binding=control["current_binding"], enabled=control["runtime_enabled_tools"])
        authority.seed_entity(result_id, "tool_result", control["current_binding"]["activity_id"])
        with self.assertRaisesRegex(GatewayError, "entity_type_mismatch:transfer"):
            gw.stage_proposal(raw(proposal_for("void_transfer", "void_transfer", args)), open_handle(gw))

    def test_same_id_wrong_scope_rejects(self):
        control = next(x for x in VECTORS["trusted_origin_controls"] if x["control_id"] == "trusted_l2_void_transfer_exact_confirmation_current_binding")
        gw, authority = setup_gateway("void_transfer", "void_transfer", control["arguments"], binding=control["current_binding"], enabled=control["runtime_enabled_tools"])
        transfer_id = control["arguments"]["transfer_id"]
        authority.seed_entity(transfer_id, "transfer", "another-activity")
        with self.assertRaisesRegex(GatewayError, "entity_scope_mismatch"):
            gw.stage_proposal(raw(fixture_proposal(control)), open_handle(gw))

    def test_unknown_disabled_tool_and_intent_reject(self):
        control = VECTORS["read_positive_controls"][0]
        obj = copy_json(control["model_output"])
        obj["tool"] = "get_transfer"
        obj["intent_id"] = "void_transfer"
        args = {"activity_id": control["model_output"]["arguments"]["activity_id"], "transfer_id": "00000000-0000-4000-8000-000000000042"}
        obj["arguments"] = args
        gw, _ = setup_gateway("get_debt", "query_debt", control["model_output"]["arguments"], enabled=[])
        result = gw.handle_model_output(raw(obj), open_handle(gw))
        self.assertEqual(result["decision"], "deny")
        self.assertEqual(gw.adapter.reads, [])

    def test_capability_is_bound_to_session_and_audit_has_no_bearer_or_session_id(self):
        control = next(x for x in VECTORS["trusted_origin_controls"] if x["control_id"] == "trusted_l2_void_transfer_exact_confirmation_current_binding")
        gw, authority = setup_gateway("void_transfer", "void_transfer", control["arguments"], binding=control["current_binding"], enabled=control["runtime_enabled_tools"])
        session = open_handle(gw)
        authority.seed_session("other", authority.current_snapshot("session"))
        other_session = gw.open_session("other")
        proposal = gw.stage_proposal(raw(fixture_proposal(control)), session)
        capability = gw.fake_ui.confirm(gw.fake_ui.display(proposal)["proposal_handle"])
        self.assertEqual(gw.dispatch_confirmed(capability, other_session)["reason"], "capability_session_mismatch")
        self.assertEqual(gw.dispatch_confirmed(capability, session)["decision"], "noop_recorded")
        audit_text = json.dumps(gw.audit, ensure_ascii=False).lower()
        self.assertNotIn("session_id", audit_text)
        self.assertNotIn("bearer", audit_text)
        self.assertNotIn("token", audit_text)
        for record in gw.audit:
            self.assertFalse({"session_id", "capability", "confirmation_capability", "bearer_token"} & set(record))

    def test_capability_consumption_is_atomic_under_concurrent_dispatch(self):
        control = next(x for x in VECTORS["trusted_origin_controls"] if x["control_id"] == "trusted_l1_create_expense_exact_confirmation_current_binding")
        gw, _ = setup_gateway("create_expense", "create_expense", control["arguments"], binding=control["current_binding"], enabled=control["runtime_enabled_tools"])
        session = open_handle(gw)
        proposal = gw.stage_proposal(raw(fixture_proposal(control)), session)
        capability = gw.fake_ui.confirm(gw.fake_ui.display(proposal)["proposal_handle"])
        outputs = []
        threads = [threading.Thread(target=lambda: outputs.append(gw.dispatch_confirmed(capability, session))) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(x["decision"] == "noop_recorded" for x in outputs), 1)
        self.assertEqual(len(gw.adapter.writes), 1)

    def test_model_plan_cannot_change_server_owned_amount(self):
        control = next(x for x in VECTORS["trusted_origin_controls"] if x["control_id"] == "trusted_l1_create_expense_exact_confirmation_current_binding")
        gw, _ = setup_gateway("create_expense", "create_expense", control["arguments"], binding=control["current_binding"], enabled=control["runtime_enabled_tools"])
        proposal = fixture_proposal(control)
        proposal["operation"]["arguments"]["original_amount"] = "99999"
        with self.assertRaisesRegex(GatewayError, "does_not_match_server_owned_canonical_plan"):
            gw.stage_proposal(raw(proposal), open_handle(gw))
        self.assertEqual(gw.adapter.writes, [])

    def test_post_confirmation_server_plan_tool_intent_or_payload_change_is_rejected(self):
        control = next(x for x in VECTORS["trusted_origin_controls"] if x["control_id"] == "trusted_l2_void_transfer_exact_confirmation_current_binding")
        for change in ("payload", "tool_intent"):
            with self.subTest(change=change):
                gw, authority = setup_gateway("void_transfer", "void_transfer", control["arguments"], binding=control["current_binding"], enabled=control["runtime_enabled_tools"])
                session = open_handle(gw)
                proposal = gw.stage_proposal(raw(fixture_proposal(control)), session)
                cap = gw.fake_ui.confirm(gw.fake_ui.display(proposal)["proposal_handle"])
                plan = authority.plans[("session", "void_transfer")]
                if change == "payload":
                    plan["arguments"]["void_reason"] = "changed-after-confirmation"
                else:
                    plan["intent_id"] = "create_expense"
                    plan["tool"] = "create_expense"
                result = gw.dispatch_confirmed(cap, session)
                self.assertEqual(result["decision"], "deny")
                self.assertEqual(result["reason"], "server_owned_plan_changed")
                self.assertEqual(gw.adapter.writes, [])

    def test_required_binding_removed_after_confirmation_fails_closed(self):
        control = next(x for x in VECTORS["trusted_origin_controls"] if x["control_id"] == "trusted_l2_void_transfer_exact_confirmation_current_binding")
        gw, authority = setup_gateway("void_transfer", "void_transfer", control["arguments"], binding=control["current_binding"], enabled=control["runtime_enabled_tools"])
        session = open_handle(gw)
        proposal = gw.stage_proposal(raw(fixture_proposal(control)), session)
        cap = gw.fake_ui.confirm(gw.fake_ui.display(proposal)["proposal_handle"])
        authority.update_snapshot("session", financial_version=None)
        result = gw.dispatch_confirmed(cap, session)
        self.assertEqual(result["decision"], "deny")
        self.assertEqual(result["reason"], "missing_current_binding:financial_version")
        self.assertEqual(gw.adapter.writes, [])


def copy_json(obj):
    return json.loads(json.dumps(obj))


if __name__ == "__main__":
    unittest.main()
