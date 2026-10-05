"""Replay the frozen 15 conformance fixtures through the isolated prototype."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
from gateway import FakeAuthority, Gateway, GatewayError, digest, proposal_for  # noqa: E402

FIXTURE = ROOT / "docs/ai/training_analysis/v0.3_write_firewall_replay/controls_non_training/control_vectors.json"
OUT = ROOT / "docs/ai/training_analysis/v0.3_gateway_boundary_prototype"


def sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


ID_ROLE = Gateway.ID_FIELDS


def seed_operation_entities(authority: FakeAuthority, activity_id: str, args: dict[str, Any]):
    authority.seed_entity(activity_id, "activity", activity_id)
    for key, expected_type in ID_ROLE.items():
        if key == "activity_id":
            continue
        value = args.get(key)
        if isinstance(value, str):
            authority.seed_entity(value, expected_type, activity_id)
    for group in ("payments", "manual_splits"):
        for row in args.get(group, []) if isinstance(args.get(group), list) else []:
            participant = row.get("participant_id") if isinstance(row, dict) else None
            if isinstance(participant, str):
                authority.seed_entity(participant, "participant", activity_id)
    for participant in args.get("aa_participant_ids", []) if isinstance(args.get("aa_participant_ids"), list) else []:
        if isinstance(participant, str):
            authority.seed_entity(participant, "participant", activity_id)


def setup(control: dict[str, Any], command: dict[str, Any], runtime_enabled: list[str]):
    binding = copy.deepcopy(control.get("current_binding", {}))
    args = command.get("arguments", {})
    activity_id = args.get("activity_id") or binding.get("activity_id")
    snapshot = {**binding, "activity_id": binding.get("activity_id", activity_id),
                "conversation_id": binding.get("conversation_id"),
                "actor_id": binding.get("actor_id"),
                "financial_version": binding.get("financial_version"),
                "enabled_tools": runtime_enabled}
    authority = FakeAuthority()
    authority.seed_session("offline-fixture-session", snapshot)
    seed_operation_entities(authority, snapshot.get("activity_id"), args)
    authority.seed_canonical_plan("offline-fixture-session", copy.deepcopy(command))
    gateway = Gateway(authority)
    return gateway, authority


def run_one(control_id: str, gateway: Gateway, raw_output: str, *, model_origin=False,
            exact_ui_click=False, attempted_fixture_confirmation=None,
            post_issue_state_change=None, post_issue_plan_change=None, replay_phase=""):
    try:
        session = gateway.open_session("offline-fixture-session")
    except GatewayError as exc:
        return {"control_id": control_id, "replay_phase": replay_phase, "decision": "deny", "reason": str(exc), "rpc_invoked": False,
                "snapshot_digest": digest(gateway.authority.current_snapshot("offline-fixture-session"))}
    if model_origin:
        result = gateway.handle_model_output(raw_output, session)
        return {"control_id": control_id, "replay_phase": replay_phase, "decision": result["decision"], "reason": result.get("reason"),
                "rpc_invoked": False, "audit_events": len(gateway.audit),
                "snapshot_digest": digest(gateway.authority.current_snapshot("offline-fixture-session"))}
    try:
        handle = gateway.stage_proposal(raw_output, session)
    except GatewayError as exc:
        return {"control_id": control_id, "replay_phase": replay_phase, "decision": "deny", "reason": str(exc), "rpc_invoked": False,
                "audit_events": len(gateway.audit),
                "snapshot_digest": digest(gateway.authority.current_snapshot("offline-fixture-session"))}
    if exact_ui_click:
        card = gateway.fake_ui.display(handle)
        capability = gateway.fake_ui.confirm(card["proposal_handle"])
        if post_issue_state_change:
            gateway.authority.update_snapshot("offline-fixture-session", **post_issue_state_change)
        if post_issue_plan_change:
            plan = gateway.authority.plans[("offline-fixture-session", "void_transfer")]
            if post_issue_plan_change == "payload":
                plan["arguments"]["void_reason"] = "changed-after-ui-confirmation"
            elif post_issue_plan_change == "tool_intent":
                plan["intent_id"] = "create_expense"
                plan["tool"] = "create_expense"
        result = gateway.dispatch_confirmed(capability, session)
        return {"control_id": control_id, "replay_phase": replay_phase, "decision": result["decision"], "reason": result.get("reason"),
                "rpc_invoked": False, "operation_digest": card["operation_digest"], "audit_events": len(gateway.audit),
                "snapshot_digest": digest(gateway.authority.current_snapshot("offline-fixture-session")),
                "audit_example": copy.deepcopy(gateway.audit)}
    result = gateway.dispatch_confirmed(attempted_fixture_confirmation, session)
    return {"control_id": control_id, "replay_phase": replay_phase, "decision": result["decision"], "reason": result.get("reason"),
            "rpc_invoked": False, "audit_events": len(gateway.audit),
            "snapshot_digest": digest(gateway.authority.current_snapshot("offline-fixture-session"))}


def main():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source_paths = [FIXTURE, ROOT / "docs/ai/schema/model_output.schema.json", ROOT / "docs/ai/schema/tool_catalog.json",
                    ROOT / "docs/ai/schema/intent_catalog.json", ROOT / "docs/ai/AI_MODEL_CONTRACT.md",
                    ROOT / "docs/ai/AI_SCOPE_FREEZE_V0.1.md", ROOT / "scripts/ai_training_evaluation/evaluate_generation.py",
                    ROOT / "scripts/ai_write_firewall_replay/replay.py", ROOT / "scripts/ai_write_firewall_replay/test_replay.py",
                    ROOT / "docs/ai/training_analysis/v0.2_synthesis/ARCHITECTURE_REVIEW.md"]
    before = {str(p): sha(p) for p in source_paths}
    results = []
    for control in fixture["model_origin_controls"]:
        output = control["model_output"]
        gw, _ = setup({"current_binding": {"actor_id": "model-fixture-actor", "activity_id": output["arguments"]["activity_id"],
                                             "conversation_id": "model-fixture-conversation", "financial_version": "v1"}},
                      {"intent_id": output.get("intent_id"), "tool": output.get("tool"), "arguments": output.get("arguments", {})},
                      control.get("runtime_enabled_tools", []))
        results.append(run_one(control["control_id"], gw, canonical(output), model_origin=True))
    read_control = fixture["read_positive_controls"][0]
    read_output = read_control["model_output"]
    gw, _ = setup({"current_binding": {"actor_id": "read-fixture-actor", "activity_id": read_output["arguments"]["activity_id"],
                                         "conversation_id": "read-fixture-conversation", "financial_version": "v1"}},
                  {"intent_id": read_output["intent_id"], "tool": read_output["tool"], "arguments": read_output["arguments"]},
                  read_control["runtime_enabled_tools"])
    results.append(run_one(read_control["control_id"], gw, canonical(read_output), model_origin=True))

    for control in fixture["trusted_origin_controls"]:
        command = copy.deepcopy(control.get("simulator_registry_command", {
            "intent_id": control.get("intent_id"), "tool": control.get("tool"), "arguments": control.get("arguments", {})
        }))
        setup_control = copy.deepcopy(control)
        phase = ""
        state_change = None
        plan_change = None
        exact = control["control_id"] in {
            "trusted_l1_create_expense_exact_confirmation_current_binding",
            "trusted_l2_void_transfer_exact_confirmation_current_binding",
        }
        if control["control_id"] == "trusted_l2_void_transfer_stale_financial_version":
            setup_control["current_binding"]["financial_version"] = control["simulator_confirmation"]["financial_version"]
            state_change = {"financial_version": control["current_binding"]["financial_version"]}
            exact = True
            phase = "trusted_ui_cap_then_current_financial_version_changes"
        elif control["control_id"] == "trusted_l2_void_transfer_actor_activity_conversation_mismatch":
            state_change = {k: control["simulator_confirmation"][k] for k in ("actor_id", "activity_id", "conversation_id")}
            exact = True
            phase = "trusted_ui_cap_then_current_session_binding_changes"
        elif control["control_id"] == "trusted_l2_void_transfer_payload_entity_mismatch":
            phase = "fake_authority_entity_resolution_rejects_fixture_mismatch"
        elif control["control_id"] == "trusted_l2_void_transfer_payload_digest_mismatch":
            plan_change = "payload"
            exact = True
            phase = "trusted_ui_cap_then_server_plan_payload_changes"
        elif control["control_id"] == "trusted_l2_void_transfer_confirmation_tool_intent_substitution":
            plan_change = "tool_intent"
            exact = True
            phase = "trusted_ui_cap_then_server_plan_tool_intent_changes"
        elif control["control_id"] == "trusted_l2_void_transfer_missing_required_binding":
            phase = "server_session_setup_rejects_missing_binding"
        elif control["control_id"] == "trusted_d4_update_expense_even_with_exact_confirmation":
            phase = "frozen_d4_scope_rejects_before_confirmation"
        elif control["control_id"] == "trusted_l2_void_transfer_forged_confirmation":
            phase = "unregistered_legacy_confirmation_attempt_rejected"
        else:
            phase = "trusted_ui_exact_current_operation"
        gw, authority = setup(setup_control, command, control.get("runtime_enabled_tools", []))
        if control["control_id"] == "trusted_l2_void_transfer_payload_entity_mismatch":
            transfer_id = command["arguments"].get("transfer_id")
            authority.entities.pop(transfer_id, None)
            actual_entity = control["simulator_confirmation"].get("entity_id")
            if actual_entity:
                authority.seed_entity(actual_entity, "transfer", control["current_binding"]["activity_id"])
        model_candidate = proposal_for(command["intent_id"], command["tool"], command["arguments"])
        # Old simulator trust fields are used only as hostile fixture payloads here;
        # they seed scenario state or exercise rejection; only the private FakeTrustedUI callback can mint a capability.
        results.append(run_one(control["control_id"], gw, canonical(model_candidate), exact_ui_click=exact,
                               attempted_fixture_confirmation=control.get("simulator_confirmation"),
                               post_issue_state_change=state_change, post_issue_plan_change=plan_change,
                               replay_phase=phase))

    after = {str(p): sha(p) for p in source_paths}
    counts: dict[str, int] = {}
    for result in results:
        counts[result["decision"]] = counts.get(result["decision"], 0) + 1
    adapter_rpc_calls = 0
    report = {
        "status": "V0_3_AI_GATEWAY_BOUNDARY_PROTOTYPE_READY",
        "fixture_source_sha256": before[str(FIXTURE)],
        "source_hashes_before": before,
        "source_hashes_after": after,
        "frozen_and_prior_fixture_sources_unchanged": before == after,
        "old_control_fixture_count": len(results),
        "control_results": results,
        "decisions": counts,
        "trusted_ui_noop_write_positives": sum(x["decision"] == "noop_recorded" for x in results),
        "adapter_rpc_invocations": adapter_rpc_calls,
        "limits": [
            "No model inference, training, network, database, financial RPC, or Android integration was run.",
            "The old fixture confirmation booleans, trusted flags, and digests are never accepted as authorization inputs; only the private in-process UI callback creates capabilities.",
            "The fake authority/server-plan registry is deterministic test setup; arbitrary malicious code in the same Python process can inspect or alter process memory.",
            "No production authentication, cryptographic bearer token, real idempotency, TTL, or complete financial business validation is implemented.",
        ],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "control_replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "source_hashes.json").write_text(json.dumps({"before": before, "after": after, "unchanged": before == after}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    audit_example = next((x.get("audit_example") for x in results if x.get("audit_example")), [])
    (OUT / "audit_example.json").write_text(json.dumps({"classification": "synthetic_noop_audit_example", "events": audit_example}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "fixture_count": len(results), "decisions": counts,
                      "positive_ui_noop_writes": report["trusted_ui_noop_write_positives"],
                      "rpc_invocations": adapter_rpc_calls, "sources_unchanged": before == after}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
