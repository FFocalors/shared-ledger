"""Minimal offline Gateway boundary prototype. All adapters are no-op fakes."""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FROZEN_SCHEMA = ROOT / "docs/ai/schema/model_output.schema.json"
FROZEN_TOOLS = ROOT / "docs/ai/schema/tool_catalog.json"
FROZEN_INTENTS = ROOT / "docs/ai/schema/intent_catalog.json"
OLD_REPLAY = ROOT / "scripts/ai_write_firewall_replay/replay.py"
_MODULE_SPEC = importlib.util.spec_from_file_location("frozen_firewall_helpers", OLD_REPLAY)
_HELPERS = importlib.util.module_from_spec(_MODULE_SPEC)
sys.modules[_MODULE_SPEC.name] = _HELPERS
_MODULE_SPEC.loader.exec_module(_HELPERS)


class GatewayError(RuntimeError):
    pass


class _OpaqueHandle:
    __slots__ = ("_marker",)

    def __init__(self, marker: object):
        if marker is not _HANDLE_MARKER:
            raise TypeError("opaque handles are minted by Gateway only")
        self._marker = marker


_HANDLE_MARKER = object()


class SessionHandle(_OpaqueHandle):
    pass


class ProposalHandle(_OpaqueHandle):
    pass


class ConfirmationCapability(_OpaqueHandle):
    pass


def _token(cls):
    return cls(_HANDLE_MARKER)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    import hashlib
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_frozen_assets():
    evaluator = _HELPERS.load_frozen_evaluator()
    schema = json.loads(FROZEN_SCHEMA.read_text(encoding="utf-8"))
    tools = json.loads(FROZEN_TOOLS.read_text(encoding="utf-8"))
    intents = json.loads(FROZEN_INTENTS.read_text(encoding="utf-8"))
    return evaluator, schema, tools, intents


@dataclass(frozen=True)
class EntityRef:
    entity_id: str
    entity_type: str
    activity_id: str


class FakeAuthority:
    """Deterministic local authority fixture; never connects to a service."""

    def __init__(self):
        self.sessions: dict[str, dict[str, Any]] = {}
        self.entities: dict[str, EntityRef] = {}
        self.plans: dict[tuple[str, str], dict[str, Any]] = {}

    def seed_session(self, session_id: str, snapshot: dict[str, Any]):
        self.sessions[session_id] = copy.deepcopy(snapshot)

    def seed_entity(self, entity_id: str, entity_type: str, activity_id: str):
        self.entities[entity_id] = EntityRef(entity_id, entity_type, activity_id)

    def seed_canonical_plan(self, session_id: str, command: dict[str, Any]):
        """Test/bootstrap-only server-owned plan registration, never a Gateway API."""
        key = (session_id, command["intent_id"])
        if key in self.plans:
            raise GatewayError("duplicate_fake_server_plan")
        self.plans[key] = copy.deepcopy(command)

    def canonical_plan(self, session_id: str, intent_id: str):
        plan = self.plans.get((session_id, intent_id))
        return copy.deepcopy(plan) if plan is not None else None

    def current_snapshot(self, session_id: str) -> dict[str, Any]:
        if session_id not in self.sessions:
            raise GatewayError("unknown_server_session")
        return copy.deepcopy(self.sessions[session_id])

    def update_snapshot(self, session_id: str, **changes):
        if session_id not in self.sessions:
            raise GatewayError("unknown_server_session")
        self.sessions[session_id].update(copy.deepcopy(changes))

    def resolve(self, entity_id: Any, expected_type: str, activity_id: str) -> str:
        if not isinstance(entity_id, str) or not entity_id:
            raise GatewayError(f"entity_id_missing:{expected_type}")
        ref = self.entities.get(entity_id)
        if ref is None:
            raise GatewayError(f"entity_not_authoritative:{expected_type}")
        if ref.entity_type != expected_type:
            raise GatewayError(f"entity_type_mismatch:{expected_type}")
        if ref.activity_id != activity_id:
            raise GatewayError("entity_scope_mismatch")
        return ref.entity_id


class FakeNoopAdapter:
    """Captures requests locally and returns fake receipts; has no RPC client."""

    def __init__(self):
        self.reads: list[dict[str, Any]] = []
        self.writes: list[dict[str, Any]] = []

    def read(self, tool: str, arguments: dict[str, Any]):
        self.reads.append({"tool": tool, "arguments": copy.deepcopy(arguments)})
        return {"fake": True, "tool": tool, "rows": []}

    def write(self, command: dict[str, Any]):
        self.writes.append(copy.deepcopy(command))
        return {"fake": True, "status": "NOOP_RECORDED"}


class Gateway:
    REQUIRED_BINDINGS = ("actor_id", "activity_id", "conversation_id", "financial_version")
    ID_FIELDS = {
        "activity_id": "activity",
        "ledger_unit_id": "ledger_unit",
        "expense_id": "expense",
        "transfer_id": "transfer",
        "participant_id": "participant",
        "original_expense_id": "expense",
    }

    def __init__(self, authority: FakeAuthority, adapter: FakeNoopAdapter | None = None):
        self.authority = authority
        self.adapter = adapter or FakeNoopAdapter()
        self.evaluator, self.schema, self.tool_catalog, self.intent_catalog = load_frozen_assets()
        self.intent_map = {x["intent_id"]: x for x in self.intent_catalog["intents"]}
        self.tool_map = {x["tool_name"]: x for x in self.tool_catalog["tools"]}
        self._sessions: dict[int, tuple[SessionHandle, str]] = {}
        self._proposals: dict[int, tuple[ProposalHandle, dict[str, Any]]] = {}
        self._cards: set[int] = set()
        self._confirmed_proposals: set[int] = set()
        self._capabilities: dict[int, tuple[ConfirmationCapability, int, str, dict[str, Any], bool]] = {}
        self._capability_lock = threading.Lock()
        self._audit_lock = threading.Lock()
        self.audit: list[dict[str, Any]] = []
        self._ui_callback_key = object()
        self.fake_ui = FakeTrustedUI(self, self._ui_callback_key)

    def _event(self, event: str, decision: str, *, reason: str = "", source: str = "gateway", **fields):
        with self._audit_lock:
            record = {"seq": len(self.audit) + 1, "event": event, "decision": decision,
                      "reason": reason or None, "source": source, **fields}
            self.audit.append(record)
        return record

    def open_session(self, server_session_id: str) -> SessionHandle:
        snapshot = self.authority.current_snapshot(server_session_id)
        missing = [key for key in self.REQUIRED_BINDINGS if snapshot.get(key) in (None, "")]
        if missing:
            self._event("session_open", "deny", reason="missing_server_binding:" + ",".join(missing), source="gateway")
            raise GatewayError("missing_server_binding:" + ",".join(missing))
        handle = _token(SessionHandle)
        self._sessions[id(handle)] = (handle, server_session_id)
        self._event("session_open", "allow", source="server_session_registry", binding_digest=digest(self._binding(snapshot)))
        return handle

    def _session(self, handle: SessionHandle) -> tuple[str, dict[str, Any]]:
        entry = self._sessions.get(id(handle))
        if entry is None or entry[0] is not handle:
            raise GatewayError("unregistered_or_forged_session_handle")
        return entry[1], self.authority.current_snapshot(entry[1])

    def _binding(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        return {k: snapshot.get(k) for k in self.REQUIRED_BINDINGS}

    def _require_current_bindings(self, snapshot: dict[str, Any]):
        missing = [k for k in self.REQUIRED_BINDINGS if snapshot.get(k) in (None, "")]
        if missing:
            raise GatewayError("missing_current_binding:" + ",".join(missing))

    def _validate_output(self, raw_output: str):
        parsed, strict, extractable, _, duplicate_keys = self.evaluator.json_parse(raw_output)
        if not strict or not extractable or not isinstance(parsed, dict) or duplicate_keys:
            raise GatewayError("strict_json_parse_failed_or_duplicate_keys")
        errors = self.evaluator.validate_schema(parsed, self.schema, self.schema, self.tool_catalog)
        if errors:
            raise GatewayError("frozen_model_output_schema_invalid")
        return parsed

    def _public_check(self, intent_id: str, tool_name: str, snapshot: dict[str, Any]):
        enabled = set(snapshot.get("enabled_tools", [])) if isinstance(snapshot.get("enabled_tools"), list) else set()
        check = _HELPERS.tool_intent_public_check(intent_id, tool_name, enabled, self.intent_map, self.tool_map)
        if not check["pass"]:
            raise GatewayError("frozen_scope_or_allowlist_reject:" + ",".join(check["rejections"]))
        return check

    def handle_model_output(self, raw_output: str, session_handle: SessionHandle) -> dict[str, Any]:
        try:
            session_id, snapshot = self._session(session_handle)
            output = self._validate_output(raw_output)
            kind = output["type"]
            if kind == "tool_call":
                check = self._public_check(output["intent_id"], output["tool"], snapshot)
                if check["mode"] == "write":
                    raise GatewayError("model_origin_write_forbidden")
                args = self._canonicalize_arguments(output["tool"], output["arguments"], snapshot)
                result = self.adapter.read(output["tool"], args)
                self._event("model_tool_call", "read_noop", source="model_origin", intent_id=output["intent_id"],
                            tool=output["tool"], operation_digest=digest({"tool": output["tool"], "arguments": args}))
                return {"decision": "read_noop", "result": result}
            if kind == "proposal":
                proposal_handle = self.stage_proposal(raw_output, session_handle)
                return {"decision": "proposal_staged_unconfirmed", "proposal_handle": proposal_handle}
            self._event("model_output", "pass_through_noop", source="model_origin", output_type=kind)
            return {"decision": "pass_through_noop", "output_type": kind}
        except GatewayError as exc:
            reason = str(exc)
            self._event("model_output", "deny", reason=reason, source="model_origin")
            return {"decision": "deny", "reason": reason}

    def _canonicalize_arguments(self, tool_name: str, raw_args: dict[str, Any], snapshot: dict[str, Any]):
        if not isinstance(raw_args, dict):
            raise GatewayError("tool_arguments_not_object")
        tool = self.tool_map.get(tool_name)
        if not tool:
            raise GatewayError("unknown_tool")
        errors = self.evaluator.validate_schema(raw_args, tool["input_schema"], self.schema, self.tool_catalog)
        if errors:
            raise GatewayError("frozen_tool_argument_schema_invalid")
        activity_id = snapshot["activity_id"]
        args = copy.deepcopy(raw_args)
        if "activity_id" in args:
            args["activity_id"] = self.authority.resolve(args["activity_id"], "activity", activity_id)
            if args["activity_id"] != activity_id:
                raise GatewayError("activity_binding_mismatch")
        for key, expected_type in self.ID_FIELDS.items():
            if key == "activity_id" or key not in args or args[key] is None:
                continue
            args[key] = self.authority.resolve(args[key], expected_type, activity_id)
        for array_key in ("payments", "manual_splits"):
            if isinstance(args.get(array_key), list):
                for row in args[array_key]:
                    if isinstance(row, dict) and "participant_id" in row:
                        row["participant_id"] = self.authority.resolve(row["participant_id"], "participant", activity_id)
        if isinstance(args.get("aa_participant_ids"), list):
            args["aa_participant_ids"] = [self.authority.resolve(x, "participant", activity_id) for x in args["aa_participant_ids"]]
        return args

    def stage_proposal(self, raw_output: str, session_handle: SessionHandle) -> ProposalHandle:
        session_id, snapshot = self._session(session_handle)
        try:
            output = self._validate_output(raw_output)
            if output.get("type") != "proposal":
                raise GatewayError("proposal_output_required")
            operation = output["operation"]
            intent_id, tool_name = output["intent_id"], operation["tool"]
            self._public_check(intent_id, tool_name, snapshot)
            if output["execution_policy"].get("execution_allowed") is not True:
                raise GatewayError("frozen_execution_policy_denies_write")
            intent = self.intent_map.get(intent_id, {})
            tool = self.tool_map.get(tool_name, {})
            if tool.get("mode") != "write" or not tool.get("first_release_execution_allowed") or not intent.get("first_release_write_execution_allowed"):
                raise GatewayError("frozen_write_scope_denies_execution")
            if intent_id == "update_expense" or tool_name == "update_expense":
                raise GatewayError("d4_atomic_update_not_supported")
            canonical_args = self._canonicalize_arguments(tool_name, operation["arguments"], snapshot)
            authority_plan = self.authority.canonical_plan(session_id, intent_id)
            if not isinstance(authority_plan, dict) or authority_plan.get("tool") != tool_name:
                raise GatewayError("server_owned_canonical_proposal_missing")
            plan_args = self._canonicalize_arguments(tool_name, authority_plan.get("arguments"), snapshot)
            candidate = {"intent_id": intent_id, "tool": tool_name, "arguments": canonical_args}
            command = {"intent_id": intent_id, "tool": tool_name, "arguments": plan_args}
            if digest(candidate) != digest(command):
                raise GatewayError("proposal_does_not_match_server_owned_canonical_plan")
            binding = self._binding(snapshot)
            registry_record = {"command_json": canonical_json(command), "command_digest": digest(command),
                               "binding": binding, "binding_digest": digest(binding), "session_id": session_id}
            handle = _token(ProposalHandle)
            self._proposals[id(handle)] = (handle, registry_record)
            self._event("proposal_stage", "unconfirmed", source="gateway_registry", intent_id=intent_id,
                        tool=tool_name, operation_digest=registry_record["command_digest"], binding_digest=registry_record["binding_digest"])
            return handle
        except GatewayError as exc:
            self._event("proposal_stage", "deny", reason=str(exc), source="model_origin")
            raise

    def _proposal(self, proposal_handle: ProposalHandle):
        item = self._proposals.get(id(proposal_handle))
        if item is None or item[0] is not proposal_handle:
            raise GatewayError("unknown_or_forged_proposal_handle")
        return item[1]

    def _issue_ui_capability(self, key: object, proposal_handle: ProposalHandle) -> ConfirmationCapability:
        if key is not self._ui_callback_key:
            self._event("ui_confirmation", "deny", reason="untrusted_ui_callback", source="gateway")
            raise GatewayError("untrusted_ui_callback")
        proposal = self._proposal(proposal_handle)
        with self._capability_lock:
            if id(proposal_handle) in self._confirmed_proposals:
                raise GatewayError("proposal_confirmation_already_issued")
            snapshot = self.authority.current_snapshot(proposal["session_id"])
            self._require_current_bindings(snapshot)
            if self._binding(snapshot) != proposal["binding"]:
                self._event("ui_confirmation", "deny", reason="current_binding_changed", source="trusted_ui_callback")
                raise GatewayError("current_binding_changed")
            self._cards.add(id(proposal_handle))
            self._confirmed_proposals.add(id(proposal_handle))
            capability = _token(ConfirmationCapability)
            self._capabilities[id(capability)] = (capability, id(proposal_handle), proposal["command_digest"], proposal["binding"], False)
        self._event("ui_confirmation", "capability_issued", source="trusted_ui_callback",
                    operation_digest=proposal["command_digest"], binding_digest=proposal["binding_digest"])
        return capability

    def dispatch_confirmed(self, capability: ConfirmationCapability, session_handle: SessionHandle):
        try:
            request_session_id, _ = self._session(session_handle)
        except GatewayError as exc:
            self._event("write_dispatch", "deny", reason=str(exc), source="gateway")
            return {"decision": "deny", "reason": str(exc)}
        # Identity check, session binding, and one-time consumption are atomic.
        with self._capability_lock:
            entry = self._capabilities.get(id(capability))
            if entry is None or entry[0] is not capability:
                self._event("write_dispatch", "deny", reason="forged_or_cross_gateway_capability", source="gateway")
                return {"decision": "deny", "reason": "forged_or_cross_gateway_capability"}
            _, proposal_id, op_digest, binding, used = entry
            if used:
                self._event("write_dispatch", "deny", reason="capability_already_consumed", source="gateway")
                return {"decision": "deny", "reason": "capability_already_consumed"}
            proposal_pair = self._proposals.get(proposal_id)
            if proposal_pair is None:
                self._event("write_dispatch", "deny", reason="proposal_registry_missing", source="gateway")
                return {"decision": "deny", "reason": "proposal_registry_missing"}
            if proposal_pair[1]["session_id"] != request_session_id:
                self._event("write_dispatch", "deny", reason="capability_session_mismatch", source="gateway")
                return {"decision": "deny", "reason": "capability_session_mismatch"}
            # Consume before state revalidation and before any adapter invocation.
            self._capabilities[id(capability)] = (entry[0], proposal_id, op_digest, binding, True)
        proposal = proposal_pair[1]
        snapshot = self.authority.current_snapshot(proposal["session_id"])
        try:
            self._require_current_bindings(snapshot)
            if self._binding(snapshot) != binding or self._binding(snapshot) != proposal["binding"]:
                raise GatewayError("current_binding_changed")
            command = json.loads(proposal["command_json"])
            if digest(command) != op_digest or op_digest != proposal["command_digest"]:
                raise GatewayError("canonical_operation_binding_mismatch")
            public = self._public_check(command["intent_id"], command["tool"], snapshot)
            if public["mode"] != "write":
                raise GatewayError("command_is_not_write")
            canonical_args = self._canonicalize_arguments(command["tool"], command["arguments"], snapshot)
            rechecked = {"intent_id": command["intent_id"], "tool": command["tool"], "arguments": canonical_args}
            if digest(rechecked) != op_digest:
                raise GatewayError("canonical_operation_changed")
            current_plan = self.authority.canonical_plan(proposal["session_id"], command["intent_id"])
            if not isinstance(current_plan, dict) or current_plan.get("intent_id") != command["intent_id"] or current_plan.get("tool") != command["tool"]:
                raise GatewayError("server_owned_plan_changed")
            current_plan_args = self._canonicalize_arguments(command["tool"], current_plan.get("arguments"), snapshot)
            if digest({"intent_id": command["intent_id"], "tool": command["tool"], "arguments": current_plan_args}) != op_digest:
                raise GatewayError("server_owned_plan_changed")
        except GatewayError as exc:
            self._event("write_dispatch", "deny", reason=str(exc), source="gateway", operation_digest=op_digest)
            return {"decision": "deny", "reason": str(exc)}
        receipt = self.adapter.write(rechecked)
        self._event("write_dispatch", "noop_recorded", source="gateway_trusted_ui_capability",
                    intent_id=rechecked["intent_id"], tool=rechecked["tool"], operation_digest=op_digest,
                    binding_digest=digest(binding), rpc_invoked=False)
        return {"decision": "noop_recorded", "receipt": receipt, "command": rechecked}


class FakeTrustedUI:
    """A fixed in-process callback fixture, not a production auth mechanism."""

    def __init__(self, gateway: Gateway, callback_key: object):
        self._gateway = gateway
        self._callback_key = callback_key

    def display(self, proposal_handle: ProposalHandle):
        proposal = self._gateway._proposal(proposal_handle)
        self._gateway._cards.add(id(proposal_handle))
        command = json.loads(proposal["command_json"])
        return {"proposal_handle": proposal_handle, "intent_id": command["intent_id"],
                "tool": command["tool"], "canonical_command": copy.deepcopy(command),
                "operation_digest": proposal["command_digest"]}

    def confirm(self, proposal_handle: ProposalHandle) -> ConfirmationCapability:
        if id(proposal_handle) not in self._gateway._cards:
            raise GatewayError("proposal_not_displayed_by_trusted_ui")
        return self._gateway._issue_ui_capability(self._callback_key, proposal_handle)


def proposal_for(intent_id: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    level = 1 if intent_id in {"create_expense", "update_expense", "update_expense_presentation"} else 2
    execution_allowed = not (intent_id == "update_expense" or tool == "update_expense")
    reason = "confirmation_required" if execution_allowed else "d4_atomic_update_not_supported"
    kind = "create" if intent_id == "create_expense" else ("update" if "update" in intent_id else "financial")
    first_field = next(iter(arguments), "operation")
    return {"type": "proposal", "intent_id": intent_id,
            "operation": {"tool": tool, "arguments": copy.deepcopy(arguments)},
            "preview": {"kind": kind, "summary": "Offline proposal preview", "diff": [{"field": first_field, "after": arguments.get(first_field)}]},
            "confirmation": {"level": level, "required": True},
            "execution_policy": {"execution_allowed": execution_allowed, "reason": reason}}
