"""Read-only, offline validation for Dataset Schema v0.1 records."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote
import uuid


BASELINE_SHA = "55fb28a7c0660462e5842e2eb5c71cfa763e5801"
VERSIONS = {"business_logic": "1.2", "ai_contract": "0.1.2", "ai_scope": "0.1", "dataset": "0.1"}
SPLITS = {"train", "validation", "test", "hard_test", "unassigned"}
LIFECYCLE = {"draft", "generated", "validated", "reviewed", "approved", "rejected", "deprecated"}


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    file: str
    record_id: str | None
    json_path: str
    message: str


@dataclass
class ValidationReport:
    valid: bool
    errors: list[Issue]
    warnings: list[Issue]
    info: list[Issue]
    statistics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": [asdict(item) for item in self.errors],
            "warnings": [asdict(item) for item in self.warnings],
            "info": [asdict(item) for item in self.info],
            "statistics": self.statistics,
        }


class DatasetValidator:
    """Validate individual records or a complete Dataset without writing input files."""

    def __init__(self, repo_root: str | Path):
        self.root = Path(repo_root).resolve()
        ai = self.root / "docs" / "ai"
        self.schema_paths = {
            "scenario": ai / "dataset/schema/scenario.schema.json",
            "sample": ai / "dataset/schema/sample.schema.json",
            "manifest": ai / "dataset/schema/dataset_manifest.schema.json",
            "context": ai / "schema/context_envelope.schema.json",
            "model": ai / "schema/model_output.schema.json",
            "tool_catalog": ai / "schema/tool_catalog.json",
            "intent_catalog": ai / "schema/intent_catalog.json",
        }
        self.schemas = {key: self._read_json(path) for key, path in self.schema_paths.items()}
        self.family_titles = self._read_family_titles(ai / "dataset/GOLD_SEED_COVERAGE_MATRIX_V0.1.md")
        self.intents = {item["intent_id"]: item for item in self.schemas["intent_catalog"]["intents"]}
        self.tools = {item["tool_name"]: item for item in self.schemas["tool_catalog"]["tools"]}
        self.external = {
            self.schemas["context"]["$id"]: self.schemas["context"],
            self.schemas["model"]["$id"]: self.schemas["model"],
            self.schemas["tool_catalog"]["$id"]: self.schemas["tool_catalog"],
            "tool_catalog.json": self.schemas["tool_catalog"],
        }
        self.jsonschema_validators = {}
        try:
            from jsonschema import Draft202012Validator, FormatChecker
            from referencing import Registry, Resource
            from referencing.jsonschema import DRAFT202012

            resources = []
            for key in ("scenario", "sample", "manifest", "context", "model", "tool_catalog"):
                document = self.schemas[key]
                resource = Resource.from_contents(document, default_specification=DRAFT202012)
                uri = document.get("$id")
                if uri:
                    resources.append((uri, resource))
            resources.append(("https://shared-ledger.invalid/ai/dataset/v0.1/tool_catalog.json", Resource.from_contents(self.schemas["tool_catalog"], default_specification=DRAFT202012)))
            registry = Registry().with_resources(resources)
            for key in ("scenario", "sample", "manifest", "context", "model"):
                document = self.schemas[key]
                Draft202012Validator.check_schema(document)
                self.jsonschema_validators[id(document)] = Draft202012Validator(document, registry=registry, format_checker=FormatChecker())
        except ImportError:
            raise RuntimeError("Install the declared Draft 2020-12 dependency with: python -m pip install -r scripts/ai_dataset_validator/requirements.txt") from None
        self._issues: list[Issue] = []

    @staticmethod
    def _read_json(path: Path) -> Any:
        with path.open("r", encoding="utf-8-sig") as stream:
            return json.load(stream)

    @staticmethod
    def _read_family_titles(path: Path) -> dict[str, str]:
        titles: dict[str, str] = {}
        if not path.is_file():
            return titles
        pattern = re.compile(r"^\|\s*`([A-Z][A-Z0-9-]+)`\s*\|\s*([^|]+?)\s*\|")
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            match = pattern.match(line)
            if match:
                titles[match.group(1)] = match.group(2).strip().strip("`")
        return titles

    def _add(self, severity: str, code: str, file: str, record_id: str | None, path: str, message: str) -> None:
        self._issues.append(Issue(severity, code, file, record_id, path or "$", message))

    def _schema_errors(self, value: Any, schema: dict[str, Any], file: str, record_id: str | None, path: str) -> None:
        validator = self.jsonschema_validators.get(id(schema))
        if validator is None:
            raise RuntimeError("A compiled Draft 2020-12 validator is unavailable.")
        for error in validator.iter_errors(value):
            pointer = "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in error.absolute_path)
            self._add("ERROR", "SCHEMA_INVALID", file, record_id, path + pointer, error.message)
    def _validate_versions(self, obj: dict[str, Any], field: str, file: str, rid: str) -> None:
        versions = obj.get(field, {})
        for key, expected in VERSIONS.items():
            if versions.get(key) != expected:
                self._add("ERROR", "VERSION_MISMATCH", file, rid, f"/{field}/{key}", f"Expected {key} version {expected}.")
        if versions.get("frozen_reference_sha") != BASELINE_SHA:
            self._add("ERROR", "VERSION_MISMATCH", file, rid, f"/{field}/frozen_reference_sha", "Frozen business logic SHA does not match v1.2 baseline.")

    def _evidence_references(self, scenario: dict[str, Any], file: str, rid: str | None) -> None:
        """Resolve repository files and explicit line / JSON Pointer locators."""
        refs = scenario.get("trust", {}).get("evidence_refs", [])
        for index, reference in enumerate(refs):
            if not isinstance(reference, str) or not reference:
                self._add("ERROR", "EVIDENCE_REF_UNRESOLVED", file, rid, f"/trust/evidence_refs/{index}", "Evidence reference must be a non-empty repository-relative path.")
                continue
            path_text, marker, fragment = reference.partition("#")
            target = (self.root / path_text).resolve()
            if not target.is_relative_to(self.root) or not target.is_file():
                self._add("ERROR", "EVIDENCE_REF_UNRESOLVED", file, rid, f"/trust/evidence_refs/{index}", "Evidence file must resolve to a file inside the repository.")
                continue
            if marker and re.fullmatch(r"L[1-9][0-9]*", fragment):
                line_number = int(fragment[1:])
                try:
                    with target.open("r", encoding="utf-8-sig") as stream:
                        line_count = sum(1 for _ in stream)
                except (OSError, UnicodeError):
                    line_count = 0
                if line_number > line_count:
                    self._add("ERROR", "EVIDENCE_REF_UNRESOLVED", file, rid, f"/trust/evidence_refs/{index}", f"Evidence line {line_number} does not exist in {path_text}.")
            elif marker and fragment.startswith("/") and target.suffix.lower() == ".json":
                try:
                    value: Any = self._read_json(target)
                    for part in fragment[1:].split("/"):
                        key = unquote(part).replace("~1", "/").replace("~0", "~")
                        value = value[int(key)] if isinstance(value, list) else value[key]
                except (OSError, UnicodeError, ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError):
                    self._add("ERROR", "EVIDENCE_REF_UNRESOLVED", file, rid, f"/trust/evidence_refs/{index}", f"JSON Pointer {fragment} does not resolve in {path_text}.")

    def _tool_role(self, intent_id: str, tool_id: str) -> str | None:
        intent = self.intents.get(intent_id, {})
        if tool_id in intent.get("possible_tools", []):
            return "PRIMARY"
        if tool_id in intent.get("supporting_lookup_tools", []):
            return "SUPPORTING_LOOKUP"
        return None

    def _scope_record(self, obj: dict[str, Any], file: str, rid: str, is_sample: bool) -> None:
        scope = obj.get("scope", {})
        intents = scope.get("intent_ids", [])
        tools = scope.get("tool_ids", [])
        expected_scopes = set()
        allowed_tools: dict[str, set[str]] = defaultdict(set)
        for iid in intents:
            intent = self.intents.get(iid)
            if not intent:
                self._add("ERROR", "INTENT_UNKNOWN", file, rid, "/scope/intent_ids", f"Unknown intent_id: {iid}.")
                continue
            expected_scopes.add(intent.get("ai_scope_v0_1"))
            allowed_tools[iid].update(intent.get("possible_tools", []))
            allowed_tools[iid].update(intent.get("supporting_lookup_tools", []))
        declared = scope.get("ai_scope")
        if expected_scopes:
            rank = {"CORE": 0, "SUPPORTED_BUT_GATED": 1, "DEFERRED": 2}
            required_scope = max(expected_scopes, key=lambda value: rank.get(value, -1))
            if declared != required_scope:
                self._add("ERROR", "SCOPE_MISMATCH", file, rid, "/scope/ai_scope", f"Declared scope must preserve the most restrictive listed Intent scope: {required_scope}.")
        for tid in tools:
            if tid not in self.tools:
                self._add("ERROR", "TOOL_UNKNOWN", file, rid, "/scope/tool_ids", f"Unknown tool_id: {tid}.")
            elif intents and not any(tid in allowed_tools[i] for i in intents if i in self.intents):
                self._add("ERROR", "INTENT_TOOL_MISMATCH", file, rid, "/scope/tool_ids", f"Tool {tid} is not mapped from the listed Intent(s).")
            elif intents:
                for iid in intents:
                    if self._tool_role(iid, tid) == "SUPPORTING_LOOKUP":
                        tool = self.tools[tid]
                        if tool.get("mode") != "read":
                            self._add("ERROR", "SUPPORTING_LOOKUP_WRITE", file, rid, "/scope/tool_ids", f"Supporting Lookup {tid} must be read-only.")
                        if tool.get("confirmation_level") != 0:
                            self._add("ERROR", "SUPPORTING_LOOKUP_CONFIRMATION", file, rid, "/scope/tool_ids", f"Supporting Lookup {tid} must use confirmation level L0.")
        policy = obj.get("policy_status")
        split = obj.get("split")
        execution = obj.get("expected", {}).get("execution", {}) if is_sample else obj.get("ground_truth", {}).get("execution_policy", {})
        if policy in {"pending", "excluded_pending_policy"}:
            if split != "unassigned":
                self._add("ERROR", "PENDING_IN_SPLIT", file, rid, "/split", "Pending-policy records must remain unassigned.")
            if execution.get("execution_allowed") is not False or execution.get("successful_execution_label_allowed") is not False:
                self._add("ERROR", "PENDING_EXECUTION", file, rid, "/expected/execution", "Pending-policy records cannot carry execution or success labels.")
        if declared == "DEFERRED" and (execution.get("execution_allowed") is not False or execution.get("successful_execution_label_allowed") is not False):
            self._add("ERROR", "DEFERRED_EXECUTION", file, rid, "/expected/execution", "DEFERRED records cannot carry execution or success labels.")
        lifecycle = obj.get("dataset_metadata", {}).get("lifecycle_status") if is_sample else obj.get("lifecycle", {}).get("status")
        trust = obj.get("trust", {}).get("level")
        if lifecycle not in LIFECYCLE:
            self._add("ERROR", "LIFECYCLE_INVALID", file, rid, "/lifecycle", "Lifecycle status is not in the frozen state list.")
        if lifecycle == "approved" and not is_sample and not obj.get("lifecycle", {}).get("deprecated_by_version") is None:
            self._add("ERROR", "LIFECYCLE_INVALID", file, rid, "/lifecycle/deprecated_by_version", "Deprecated records cannot remain approved.")
        if trust == "SYNTHETIC_UNVERIFIED" and (lifecycle not in {"draft", "generated", "rejected"} or split != "unassigned"):
            self._add("ERROR", "UNVERIFIED_TRUST", file, rid, "/lifecycle", "SYNTHETIC_UNVERIFIED records must be unassigned and draft/generated/rejected.")
        if is_sample:
            meta = obj.get("dataset_metadata", {})
            if meta.get("deprecated_by_version") and lifecycle == "approved":
                self._add("ERROR", "DEPRECATED_APPROVED", file, rid, "/dataset_metadata/lifecycle_status", "Deprecated sample cannot remain approved.")
            if obj.get("source", {}).get("surface_form_type") == "teacher_generated":
                teacher = obj.get("source", {}).get("teacher")
                required = ("provider", "model", "generation_run_id", "prompt_version", "generated_at", "temperature")
                if not isinstance(teacher, dict) or any(k not in teacher or teacher[k] is None for k in required):
                    self._add("ERROR", "TEACHER_PROVENANCE_MISSING", file, rid, "/source/teacher", "Teacher source requires provider, model, generation_run_id, prompt_version, generated_at, and temperature.")
                elif teacher.get("seed") is not None and not isinstance(teacher["seed"], (str, int)):
                    self._add("ERROR", "TEACHER_PROVENANCE_INVALID", file, rid, "/source/teacher/seed", "Teacher seed must be a string, integer, or null.")
                elif lifecycle == "approved" and (
                    obj.get("trust", {}).get("surface_form_reviewed") is not True
                    or not obj.get("trust", {}).get("validation_evidence")
                ):
                    self._add("ERROR", "TEACHER_APPROVAL_EVIDENCE", file, rid, "/dataset_metadata/lifecycle_status", "Teacher data requires validation evidence and human surface review before approval.")
            elif obj.get("source", {}).get("teacher") is not None:
                self._add("ERROR", "TEACHER_PROVENANCE_SPOOFED", file, rid, "/source/teacher", "Non-teacher sources must not include Teacher provenance.")
        privacy = obj.get("privacy", {}) if not is_sample else obj.get("dataset_metadata", {})
        for flag in ("contains_production_data", "contains_real_personal_data"):
            if privacy.get(flag) is not False:
                self._add("ERROR", "PRIVACY_FLAG", file, rid, f"/{'dataset_metadata' if is_sample else 'privacy'}/{flag}", f"{flag} must be false.")

    def _validate_output(self, output: Any, scope: dict[str, Any], input_context: dict[str, Any] | None, execution: dict[str, Any], file: str, rid: str, path: str, expected_diff: Any = None) -> None:
        if not isinstance(output, dict):
            return
        self._schema_errors(output, self.schemas["model"], file, rid, path)
        typ = output.get("type")
        intents = scope.get("intent_ids", [])
        if typ in {"proposal", "tool_call"}:
            iid = output.get("intent_id")
            tool = output.get("operation", {}).get("tool") if typ == "proposal" else output.get("tool")
            if iid not in self.intents:
                self._add("ERROR", "INTENT_UNKNOWN", file, rid, path + "/intent_id", f"Unknown intent_id: {iid}.")
            elif self._tool_role(iid, tool) is None:
                self._add("ERROR", "INTENT_TOOL_MISMATCH", file, rid, path, f"Intent {iid} does not map to Tool {tool}.")
            elif self._tool_role(iid, tool) == "SUPPORTING_LOOKUP":
                catalog_lookup = self.tools.get(tool) or {}
                if typ != "tool_call":
                    self._add("ERROR", "SUPPORTING_LOOKUP_ROLE", file, rid, path, "Supporting Lookup is a read-only intermediate tool_call, not a proposal.")
                if catalog_lookup.get("mode") != "read":
                    self._add("ERROR", "SUPPORTING_LOOKUP_WRITE", file, rid, path, f"Supporting Lookup {tool} must be read-only.")
                if catalog_lookup.get("confirmation_level") != 0:
                    self._add("ERROR", "SUPPORTING_LOOKUP_CONFIRMATION", file, rid, path, f"Supporting Lookup {tool} must use confirmation level L0.")
                if execution.get("execution_allowed") is not False:
                    self._add("ERROR", "SUPPORTING_LOOKUP_EXECUTION", file, rid, path, "A Supporting Lookup cannot carry an execution-allowed label.")
                if execution.get("successful_execution_label_allowed") is not False:
                    self._add("ERROR", "SUPPORTING_LOOKUP_SUCCESS_LABEL", file, rid, path, "Supporting Lookup cannot carry a successful business-write label.")
            if iid and iid not in intents:
                self._add("ERROR", "INTENT_MISMATCH", file, rid, path + "/intent_id", "Output intent is not declared in record scope.")
            catalog_tool = self.tools.get(tool)
            if tool and catalog_tool is None:
                self._add("ERROR", "TOOL_UNKNOWN", file, rid, path, f"Unknown tool_id: {tool}.")
            elif tool and tool not in scope.get("tool_ids", []):
                self._add("ERROR", "SCOPE_TOOL_MISMATCH", file, rid, path, f"Output Tool {tool} is not declared in scope.tool_ids.")
            level = (self.intents.get(iid) or {}).get("confirmation_level", 0)
            level = (self.tools.get(tool) or {}).get("confirmation_level_by_intent", {}).get(iid, level)
            if self._tool_role(iid or "", tool or "") == "SUPPORTING_LOOKUP":
                level = 0
            if typ == "tool_call" and (catalog_tool or {}).get("mode") == "write":
                self._add("ERROR", "WRITE_TOOL_CALL", file, rid, path, "Write operations must be represented as proposals.")
            if typ == "proposal":
                conf = output.get("confirmation", {})
                policy = output.get("execution_policy", {})
                if conf.get("level") != level:
                    self._add("ERROR", "CONFIRMATION_LEVEL", file, rid, path + "/confirmation/level", f"Catalog requires confirmation level {level}.")
                required = level > 0
                if conf.get("required") is not required or execution.get("confirmation_required") is not required:
                    self._add("ERROR", "CONFIRMATION_REQUIRED", file, rid, path + "/confirmation/required", "Confirmation declaration does not match the frozen intent policy.")
                if execution.get("confirmation_level") != level:
                    self._add("ERROR", "CONFIRMATION_LEVEL", file, rid, "/expected/execution/confirmation_level", f"Dataset execution metadata must use level {level}.")
                if required and execution.get("final_authorization") != "trusted_ui_event_required":
                    self._add("ERROR", "CONFIRMATION_AUTHORIZATION", file, rid, "/expected/execution/final_authorization", "Write proposals require a trusted UI confirmation event.")
                if policy.get("execution_allowed") != execution.get("execution_allowed"):
                    self._add("ERROR", "EXECUTION_POLICY_MISMATCH", file, rid, path + "/execution_policy/execution_allowed", "Proposal and Dataset execution flags differ.")
                if expected_diff is not None and output.get("preview", {}).get("diff") != expected_diff:
                    self._add("ERROR", "EXPECTED_DIFF_MISMATCH", file, rid, path + "/preview/diff", "Proposal preview diff must deeply equal expected_diff.")
            scopes = {(self.intents.get(i) or {}).get("ai_scope_v0_1") for i in [iid] if i}
            if "DEFERRED" in scopes and (typ not in {"answer", "unsupported"}):
                self._add("ERROR", "DEFERRED_OUTPUT", file, rid, path, "DEFERRED intents may only produce answer or unsupported.")
            if "DEFERRED" in scopes and execution.get("execution_allowed") is not False:
                self._add("ERROR", "DEFERRED_EXECUTION", file, rid, "/expected/execution/execution_allowed", "DEFERRED execution must remain disabled.")
            if iid in {"update_expense", "update_refund"}:
                if typ != "proposal":
                    self._add("ERROR", "D4_OUTPUT_TYPE", file, rid, path + "/type", "D4 financial edits require a preview-only proposal.")
                else:
                    if policy.get("execution_allowed") is not False or policy.get("reason") != "d4_atomic_update_not_supported":
                        self._add("ERROR", "D4_EXECUTION", file, rid, path + "/execution_policy", "D4 proposal must be disabled with reason d4_atomic_update_not_supported.")
                    if execution.get("execution_allowed") is not False or execution.get("successful_execution_label_allowed") is not False:
                        self._add("ERROR", "D4_EXECUTION", file, rid, "/expected/execution", "D4 execution and success labels must both be false.")
                    if expected_diff is None or output.get("preview", {}).get("diff") != expected_diff:
                        expected_diff_path = "/expected/expected_diff" if path.startswith("/expected/") else "/ground_truth/expected_business_result/expected_diff"
                        self._add("ERROR", "D4_DIFF", file, rid, expected_diff_path, "D4 expected_diff is required and must equal proposal diff.")
                    if input_context and "update_expense" in input_context.get("server_context", {}).get("enabled_tools", []):
                        self._add("ERROR", "D4_TOOL_EXPOSED", file, rid, "/input/server_context/enabled_tools", "D4 update Tool must not be enabled.")
            if input_context:
                enabled = input_context.get("server_context", {}).get("enabled_tools", [])
                if typ == "tool_call" and tool not in enabled:
                    self._add("ERROR", "TOOL_NOT_ENABLED", file, rid, path + "/tool", "Called Tool is not enabled in this ContextEnvelope.")
        if typ == "clarification":
            annotation = None
            if path.startswith("/expected"):
                # Caller compares this with the sample annotation after output validation.
                pass
            if "missing_fields" not in output or not isinstance(output.get("missing_fields"), list):
                self._add("ERROR", "CLARIFICATION_FIELDS", file, rid, path + "/missing_fields", "Clarification must enumerate missing fields.")
        if input_context:
            enabled = input_context.get("server_context", {}).get("enabled_tools", [])
            for i, tool in enumerate(enabled):
                record_scope = [self.intents[x].get("ai_scope_v0_1") for x in intents if x in self.intents]
                if tool not in self.tools:
                    self._add("ERROR", "TOOL_UNKNOWN", file, rid, f"/input/server_context/enabled_tools/{i}", f"Unknown enabled tool: {tool}.")
                elif (self.tools[tool].get("ai_scope_v0_1") == "DEFERRED" or (set(intents) & {"update_expense", "update_refund"} and tool == "update_expense")):
                    self._add("ERROR", "SCOPE_TOOL_EXPOSED", file, rid, f"/input/server_context/enabled_tools/{i}", f"Tool {tool} is forbidden by Scope/D4.")
            if typ == "answer" and output.get("evidence_result_ids"):
                known = set(input_context.get("server_context", {}).get("verified_result_ids", []))
                for evidence in output["evidence_result_ids"]:
                    if evidence not in known:
                        self._add("ERROR", "UNVERIFIED_EVIDENCE", file, rid, path + "/evidence_result_ids", f"Evidence {evidence} is not listed as verified by the server.")
            if typ in {"proposal", "tool_call"} and output.get("intent_id") in self.intents:
                lvl = self.intents[output["intent_id"]].get("confirmation_level", 0)
                tool_name = output.get("operation", {}).get("tool") if typ == "proposal" else output.get("tool")
                lvl = (self.tools.get(tool_name) or {}).get("confirmation_level_by_intent", {}).get(output["intent_id"], lvl)
                if lvl == 2 and typ == "tool_call" and re.search(r"确定|执行吧|可以", input_context.get("user_message", "")):
                    self._add("ERROR", "CHAT_CONFIRMATION_BYPASS", file, rid, path, "Chat text cannot authorize a financial write; require a proposal and trusted UI event.")

    def validate_scenario(self, obj: dict[str, Any], file: str = "<scenario>") -> ValidationReport:
        self._issues = []
        rid = obj.get("scenario_id") if isinstance(obj, dict) else None
        if not isinstance(obj, dict):
            self._add("ERROR", "JSON_TYPE", file, None, "$", "Scenario must be a JSON object.")
        else:
            self._schema_errors(obj, self.schemas["scenario"], file, rid, "$")
            self._validate_versions(obj, "versions", file, rid or "")
            self._evidence_references(obj, file, rid)
            self._scope_record(obj, file, rid or "", False)
            self._validate_scenario_state_integrity(obj, file)
            if obj.get("source", {}).get("type") == "business_logic":
                self._validate_scenario_authenticity(obj, file)
            gt = obj.get("ground_truth", {})
            model = gt.get("model_output")
            expected_business_result = gt.get("expected_business_result", {})
            expected_diff = expected_business_result.get("expected_diff") if isinstance(expected_business_result, dict) else None
            if expected_diff is None and obj.get("source", {}).get("type") != "business_logic" and isinstance(model, dict):
                expected_diff = model.get("preview", {}).get("diff")
            if model:
                self._validate_output(model, obj.get("scope", {}), None, gt.get("execution_policy", {}), file, rid or "", "/ground_truth/model_output", expected_diff)
                if gt.get("expected_output_type") != model.get("type"):
                    self._add("ERROR", "OUTPUT_TYPE_MISMATCH", file, rid, "/ground_truth/expected_output_type", "Ground truth output type must match model_output.type.")
                if obj.get("source", {}).get("type") == "business_logic":
                    self._validate_scenario_d4_read_diff(obj, file)
            self._proposal_success_language(model, file, rid)
        return self._report({"scenarios": 1, "samples": 0, "families": 1 if isinstance(obj, dict) and obj.get("scenario_family_id") else 0})

    def _proposal_success_language(self, model: Any, file: str, rid: str | None) -> None:
        if not isinstance(model, dict):
            return
        text_values: list[str] = []
        def visit(node: Any) -> None:
            if isinstance(node, dict):
                for value in node.values(): visit(value)
            elif isinstance(node, list):
                for value in node: visit(value)
            elif isinstance(node, str): text_values.append(node)
        visit(model)
        if model.get("type") == "proposal" and re.search(r"已修改成功|已更新成功|执行成功|已转账|已创建成功|已经完成", " ".join(text_values)):
            self._add("ERROR", "FALSE_SUCCESS_CLAIM", file, rid, "/ground_truth/model_output", "Proposal wording must not claim the operation already succeeded.")

    def validate_sample(self, obj: dict[str, Any], scenarios: dict[str, dict[str, Any]] | None = None, file: str = "<sample>") -> ValidationReport:
        self._issues = []
        rid = obj.get("sample_id") if isinstance(obj, dict) else None
        if not isinstance(obj, dict):
            self._add("ERROR", "JSON_TYPE", file, None, "$", "Sample must be a JSON object.")
        else:
            self._schema_errors(obj, self.schemas["sample"], file, rid, "$")
            if obj.get("dataset_version") != VERSIONS["dataset"]:
                self._add("ERROR", "VERSION_MISMATCH", file, rid, "/dataset_version", "Expected Dataset version 0.1.")
            self._scope_record(obj, file, rid or "", True)
            self._surface_and_context(obj, file, rid)
            output = obj.get("expected", {}).get("model_output")
            execution = obj.get("expected", {}).get("execution", {})
            self._validate_output(output, obj.get("scope", {}), obj.get("input"), execution, file, rid or "", "/expected/model_output", obj.get("expected", {}).get("expected_diff"))
            if output and obj.get("expected", {}).get("output_type") != output.get("type"):
                self._add("ERROR", "OUTPUT_TYPE_MISMATCH", file, rid, "/expected/output_type", "expected.output_type must equal model_output.type.")
            self._clarification_and_entities(obj, file, rid)
            self._proposal_success_language(output, file, rid)
            if scenarios is not None:
                self._cross_record(obj, scenarios, file, rid)
        return self._report({"scenarios": 0, "samples": 1, "families": 1 if isinstance(obj, dict) and obj.get("scenario_family_id") else 0})

    def _surface_and_context(self, sample: dict[str, Any], file: str, rid: str | None) -> None:
        surface = sample.get("surface_form", {})
        context = sample.get("input", {})
        if surface.get("user_message") != context.get("user_message"):
            self._add("ERROR", "SURFACE_CONTEXT_MISMATCH", file, rid, "/surface_form/user_message", "Surface user_message must exactly equal ContextEnvelope user_message.")
        conversation = surface.get("conversation", [])
        if surface.get("context_turn_count") != len(conversation):
            self._add("ERROR", "CONTEXT_TURN_COUNT", file, rid, "/surface_form/context_turn_count", "context_turn_count must equal surface conversation length.")
        messages = context.get("conversation_context", {}).get("messages", [])
        compact_messages = [{key: row.get(key) for key in ("turn_id", "role", "content")} for row in messages]
        if conversation and conversation != compact_messages:
            self._add("ERROR", "CONVERSATION_MISMATCH", file, rid, "/input/conversation_context/messages", "Conversation history differs from surface_form conversation.")
        selected = context.get("ui_context", {}).get("selected_entity")
        visible = context.get("page_state", {}).get("visible_entities", [])
        visible_ids = {x.get("id") for x in visible if isinstance(x, dict)}
        if isinstance(selected, dict) and selected.get("id") and visible and selected["id"] not in visible_ids:
            self._add("ERROR", "SELECTED_ENTITY_MISSING", file, rid, "/input/ui_context/selected_entity/id", "Selected entity must exist in visible_entities.")
        if context.get("server_context", {}).get("baseline_commit") != BASELINE_SHA:
            self._add("ERROR", "VERSION_MISMATCH", file, rid, "/input/server_context/baseline_commit", "Context baseline_commit must match the frozen business logic SHA.")

    def _clarification_and_entities(self, sample: dict[str, Any], file: str, rid: str | None) -> None:
        expected = sample.get("expected", {})
        model = expected.get("model_output", {})
        annotation = expected.get("clarification_annotation")
        if model.get("type") == "clarification":
            if not isinstance(annotation, dict):
                self._add("ERROR", "CLARIFICATION_ANNOTATION_MISSING", file, rid, "/expected/clarification_annotation", "Clarification output requires an annotation.")
            else:
                for field in ("reason", "missing_fields", "question"):
                    if annotation.get(field) != model.get(field):
                        self._add("ERROR", "CLARIFICATION_ANNOTATION_MISMATCH", file, rid, f"/expected/clarification_annotation/{field}", f"Annotation {field} must exactly match Model Output.")
                candidate_ids = self._output_candidate_ids(model.get("candidates", []))
                if set(annotation.get("candidate_entity_ids", [])) != candidate_ids:
                    self._add("ERROR", "CLARIFICATION_CANDIDATES", file, rid, "/expected/clarification_annotation/candidate_entity_ids", "Candidate annotation must match Model Output candidates.")
        entity_resolution = expected.get("entity_resolution", [])
        for index, entity in enumerate(entity_resolution):
            path = f"/expected/entity_resolution/{index}"
            candidates = entity.get("candidate_ids", [])
            status = entity.get("resolution_status")
            chosen = entity.get("expected_entity_id")
            if not entity.get("mention") or not candidates or not entity.get("evidence_source"):
                self._add("ERROR", "ENTITY_RESOLUTION_INCOMPLETE", file, rid, path, "Entity mention, candidate_ids, and evidence_source are required.")
            if status == "resolved" and (not chosen or chosen not in candidates):
                self._add("ERROR", "ENTITY_RESOLUTION_INVALID", file, rid, path + "/expected_entity_id", "Resolved entity must be one of the candidate IDs.")
            if len(set(candidates)) > 1 and status == "resolved":
                self._add("ERROR", "ENTITY_AMBIGUOUS_SELECTED", file, rid, path, "Multiple candidates without unique evidence must require clarification.")
            if len(set(candidates)) > 1 and chosen:
                self._add("ERROR", "ENTITY_AMBIGUOUS_SELECTED", file, rid, path + "/expected_entity_id", "Do not select an entity from an ambiguous candidate set.")

    @staticmethod
    def _output_candidate_ids(candidates: list[Any]) -> set[str]:
        result: set[str] = set()
        for candidate in candidates:
            entity = candidate.get("entity", {}) if isinstance(candidate, dict) else {}
            if entity.get("id"):
                result.add(entity["id"])
        return result

    def _cross_record(self, sample: dict[str, Any], scenarios: dict[str, dict[str, Any]], file: str, rid: str | None) -> None:
        scenario = scenarios.get(sample.get("scenario_id"))
        if scenario is None:
            self._add("ERROR", "SCENARIO_MISSING", file, rid, "/scenario_id", f"Scenario {sample.get('scenario_id')} does not exist.")
            return
        for field in ("scenario_family_id", "split_group_id", "split"):
            if sample.get(field) != scenario.get(field):
                self._add("ERROR", "SCENARIO_SAMPLE_MISMATCH", file, rid, f"/{field}", f"Sample {field} must match its Scenario.")
        if sample.get("scope") != scenario.get("scope"):
            # scope may be narrowed to sample intents; its declared scope still must agree.
            if sample.get("scope", {}).get("ai_scope") != scenario.get("scope", {}).get("ai_scope"):
                self._add("ERROR", "SCENARIO_SAMPLE_MISMATCH", file, rid, "/scope/ai_scope", "Sample scope must match the Scenario scope.")
        if sample.get("policy_status") != scenario.get("policy_status"):
            self._add("ERROR", "SCENARIO_SAMPLE_MISMATCH", file, rid, "/policy_status", "Sample policy status must match the Scenario.")
        if sample.get("expected", {}).get("ground_truth_pointer") != f"{sample.get('scenario_id')}#/ground_truth":
            self._add("ERROR", "GROUND_TRUTH_POINTER", file, rid, "/expected/ground_truth_pointer", "Ground truth pointer must target the associated Scenario.")
        if sample.get("dataset_version") != scenario.get("versions", {}).get("dataset"):
            self._add("ERROR", "VERSION_MISMATCH", file, rid, "/dataset_version", "Sample Dataset version must match Scenario version.")
        sample_execution = sample.get("expected", {}).get("execution", {})
        scenario_execution = scenario.get("ground_truth", {}).get("execution_policy", {})
        for field in ("execution_allowed", "confirmation_level", "confirmation_required", "final_authorization", "successful_execution_label_allowed"):
            if sample_execution.get(field) != scenario_execution.get(field):
                self._add("ERROR", "GROUND_TRUTH_CONFLICT", file, rid, f"/expected/execution/{field}", f"Sample changes canonical Scenario execution policy {field}.")
        truth = scenario.get("ground_truth", {}).get("model_output", {})
        expected = sample.get("expected", {}).get("model_output", {})
        self._compare_business_truth(truth, expected, file, rid)

    def _compare_business_truth(self, truth: dict[str, Any], sample: dict[str, Any], file: str, rid: str | None) -> None:
        if not truth or not sample:
            return
        fields = ["type", "intent_id"]
        for key in fields:
            if truth.get(key) != sample.get(key):
                self._add("ERROR", "GROUND_TRUTH_CONFLICT", file, rid, f"/expected/model_output/{key}", f"Sample changes canonical Ground Truth {key}.")
        for field in ("operation", "tool", "arguments"):
            a, b = truth.get(field), sample.get(field)
            if a != b:
                self._add("ERROR", "GROUND_TRUTH_CONFLICT", file, rid, f"/expected/model_output/{field}", f"Sample changes canonical Ground Truth {field}.")
        if truth.get("type") == "proposal" and sample.get("type") == "proposal":
            for field in ("confirmation", "execution_policy"):
                if truth.get(field) != sample.get(field):
                    self._add("ERROR", "GROUND_TRUTH_CONFLICT", file, rid, f"/expected/model_output/{field}", f"Sample changes canonical Ground Truth {field}.")
            if truth.get("preview", {}).get("diff") != sample.get("preview", {}).get("diff"):
                self._add("ERROR", "GROUND_TRUTH_CONFLICT", file, rid, "/expected/model_output/preview/diff", "Sample changes canonical business diff.")

    def validate_dataset(self, scenarios: list[dict[str, Any]], samples: list[dict[str, Any]], manifest: dict[str, Any] | None = None, dataset_root: str | Path | None = None, files: dict[str, str] | None = None) -> ValidationReport:
        self._issues = []
        files = files or {}
        authenticity_scenarios = [scenario for scenario in scenarios if scenario.get("source", {}).get("type") == "business_logic"]
        self._validate_scenario_batch_authenticity(authenticity_scenarios, files.get("scenarios", "scenarios.json"))
        scenario_ids: dict[str, dict[str, Any]] = {}
        sample_ids: dict[str, dict[str, Any]] = {}
        for index, scenario in enumerate(scenarios):
            rid = scenario.get("scenario_id")
            self._schema_errors(scenario, self.schemas["scenario"], files.get("scenarios", "scenarios.json"), rid, f"$[{index}]")
            self._validate_versions(scenario, "versions", files.get("scenarios", "scenarios.json"), rid or "")
            self._evidence_references(scenario, files.get("scenarios", "scenarios.json"), rid)
            self._scope_record(scenario, files.get("scenarios", "scenarios.json"), rid or "", False)
            self._validate_scenario_output(scenario, files.get("scenarios", "scenarios.json"))
            if scenario.get("source", {}).get("type") == "business_logic":
                self._validate_scenario_authenticity(scenario, files.get("scenarios", "scenarios.json"))
            if rid in scenario_ids:
                self._add("ERROR", "DUPLICATE_SCENARIO_ID", files.get("scenarios", "scenarios.json"), rid, f"$[{index}]/scenario_id", "Scenario ID is duplicated.")
            scenario_ids[rid] = scenario
        for index, sample in enumerate(samples):
            rid = sample.get("sample_id")
            file = files.get("samples", "samples.json")
            self._schema_errors(sample, self.schemas["sample"], file, rid, f"$[{index}]")
            if sample.get("dataset_version") != VERSIONS["dataset"]:
                self._add("ERROR", "VERSION_MISMATCH", file, rid, f"$[{index}]/dataset_version", "Expected Dataset version 0.1.")
            self._scope_record(sample, file, rid or "", True)
            self._surface_and_context(sample, file, rid)
            self._validate_output(sample.get("expected", {}).get("model_output"), sample.get("scope", {}), sample.get("input"), sample.get("expected", {}).get("execution", {}), file, rid or "", f"$[{index}]/expected/model_output", sample.get("expected", {}).get("expected_diff"))
            output = sample.get("expected", {}).get("model_output", {})
            if output and sample.get("expected", {}).get("output_type") != output.get("type"):
                self._add("ERROR", "OUTPUT_TYPE_MISMATCH", file, rid, f"$[{index}]/expected/output_type", "expected.output_type must equal model_output.type.")
            self._clarification_and_entities(sample, file, rid)
            self._proposal_success_language(output, file, rid)
            self._cross_record(sample, scenario_ids, file, rid)
            if rid in sample_ids:
                self._add("ERROR", "DUPLICATE_SAMPLE_ID", file, rid, f"$[{index}]/sample_id", "Sample ID is duplicated.")
            sample_ids[rid] = sample
        self._leakage(scenarios, samples)
        self._deduplicate(samples)
        if manifest:
            self._validate_manifest(manifest, scenarios, samples, dataset_root, files.get("manifest", "dataset_manifest.json"))
        stats = self._statistics(scenarios, samples)
        return self._report(stats)

    def _validate_scenario_output(self, scenario: dict[str, Any], file: str) -> None:
        rid = scenario.get("scenario_id")
        truth = scenario.get("ground_truth", {})
        output = truth.get("model_output")
        expected_business_result = truth.get("expected_business_result", {})
        expected_diff = expected_business_result.get("expected_diff") if isinstance(expected_business_result, dict) else None
        if expected_diff is None and scenario.get("source", {}).get("type") != "business_logic" and isinstance(output, dict):
            expected_diff = output.get("preview", {}).get("diff")
        self._validate_output(output, scenario.get("scope", {}), None, truth.get("execution_policy", {}), file, rid or "", "/ground_truth/model_output", expected_diff)
        if output and truth.get("expected_output_type") != output.get("type"):
            self._add("ERROR", "OUTPUT_TYPE_MISMATCH", file, rid, "/ground_truth/expected_output_type", "Ground truth output type must match model_output.type.")
        self._validate_scenario_state_integrity(scenario, file)
        if output and scenario.get("source", {}).get("type") == "business_logic":
            self._validate_scenario_d4_read_diff(scenario, file)

    def _validate_scenario_state_integrity(self, scenario: dict[str, Any], file: str) -> None:
        """Check generic canonical-state consistency without Family/ID special cases."""
        rid = scenario.get("scenario_id", "")
        facts = scenario.get("state", {}).get("facts", {})
        entities = scenario.get("state", {}).get("entities", [])
        declared = {entity.get("id") for entity in entities if entity.get("id")}
        if len(declared) != sum(bool(entity.get("id")) for entity in entities):
            self._add("ERROR", "SCENARIO_ENTITY_ID_DUPLICATE", file, rid, "/state/entities", "Entity IDs must be unique within a Scenario.")
        facts_ui = facts.get("ui_context")
        if isinstance(facts_ui, dict):
            context_ui_schema = self.schemas["context"].get("properties", {}).get("ui_context", {}).get("properties", {})
            allowed_pages = context_ui_schema.get("page_type", {}).get("enum", [])
            form_schema = context_ui_schema.get("form_mode", {}).get("anyOf", [{}])[0]
            allowed_forms = form_schema.get("enum", [])
            if facts_ui.get("page_type") not in allowed_pages:
                self._add("ERROR", "SCENARIO_UI_ENUM", file, rid, "/state/facts/ui_context/page_type", "page_type must use the frozen Context Envelope enum.")
            if facts_ui.get("form_mode") is not None and facts_ui.get("form_mode") not in allowed_forms:
                self._add("ERROR", "SCENARIO_UI_ENUM", file, rid, "/state/facts/ui_context/form_mode", "form_mode must use the frozen Context Envelope enum or null.")
        operation = scenario.get("operation", {})
        model = scenario.get("ground_truth", {}).get("model_output", {})
        operation_args = operation.get("arguments")
        state_args = facts.get("operation_arguments")
        if "operation_arguments" in facts and operation_args != state_args:
            self._add("ERROR", "SCENARIO_OPERATION_ARGUMENTS_MISMATCH", file, rid, "/operation/arguments", "Operation arguments must match the recorded state operation_arguments.")
        model_operation = model.get("operation", {})
        if operation.get("tool_id") and model_operation.get("tool") == operation.get("tool_id") and model_operation.get("arguments") != operation_args:
            self._add("ERROR", "SCENARIO_MODEL_ARGUMENTS_MISMATCH", file, rid, "/ground_truth/model_output/operation/arguments", "Model output arguments must match the declared operation arguments.")
        records = facts.get("recorded_facts", [])
        allowed_sources = {"user_input", "user_selected", "ui_context", "conversation_confirmed", "persisted_entity", "server_result", "missing", "stale_context"}
        seen = set()
        for index, record in enumerate(records if isinstance(records, list) else []):
            if not isinstance(record, dict) or set(record) != {"field", "value", "source"}:
                self._add("ERROR", "SCENARIO_RECORDED_FACT_SHAPE", file, rid, f"/state/facts/recorded_facts/{index}", "Each recorded fact must contain exactly field, value, and source.")
                continue
            key = json.dumps(record, ensure_ascii=False, sort_keys=True)
            if key in seen:
                self._add("ERROR", "SCENARIO_RECORDED_FACT_DUPLICATE", file, rid, f"/state/facts/recorded_facts/{index}", "Recorded facts must not be exact duplicates.")
            seen.add(key)
            if record.get("source") not in allowed_sources:
                self._add("ERROR", "SCENARIO_RECORDED_FACT_SOURCE", file, rid, f"/state/facts/recorded_facts/{index}/source", "Recorded fact source is outside the frozen vocabulary.")
        if scenario.get("source", {}).get("type") == "business_logic" and not any(
            isinstance(row, dict) and row.get("field") == "user_message" and isinstance(row.get("value"), str) and row["value"].strip()
            for row in records if isinstance(records, list)
        ):
            self._add("ERROR", "SCENARIO_USER_MESSAGE_MISSING", file, rid, "/state/facts/recorded_facts", "Canonical business scenarios must record the actual user_message and its source.")
        # Validate formal entity-reference fields in arguments and lookup results.
        reference_keys = {"activity_id", "ledger_unit_id", "participant_id", "owner_participant_id", "custodian_participant_id", "payer_participant_id", "expense_id", "original_expense_id", "transfer_id", "counterparty_id", "from_participant_id", "to_participant_id"}
        def walk(value: Any, path: str) -> None:
            if isinstance(value, dict):
                if value.get("type") in {"activity", "ledger_unit", "user", "participant", "expense", "transfer", "prepayment_account"} and isinstance(value.get("id"), str) and value["id"] not in declared:
                    self._add("ERROR", "SCENARIO_ENTITY_REFERENCE_UNDECLARED", file, rid, f"{path}/id", f"Entity ID {value['id']} is not declared in state.entities.")
                if "status" in value and "transfer_id" in value and "is_voided" not in value:
                    self._add("ERROR", "SCENARIO_FROZEN_VOCABULARY", file, rid, path + "/status", "Transfer state must use the frozen is_voided field, not a generic status alias.")
                for key, child in value.items():
                    child_path = f"{path}/{key}"
                    if key in reference_keys and isinstance(child, str) and child not in declared:
                        self._add("ERROR", "SCENARIO_ENTITY_REFERENCE_UNDECLARED", file, rid, child_path, f"Referenced entity ID {child} is not declared in state.entities.")
                    elif key == "candidate_ids" and isinstance(child, list):
                        for idx, candidate in enumerate(child):
                            if candidate not in declared:
                                self._add("ERROR", "SCENARIO_ENTITY_REFERENCE_UNDECLARED", file, rid, f"{child_path}/{idx}", f"Candidate ID {candidate} is not declared in state.entities.")
                    else:
                        walk(child, child_path)
            elif isinstance(value, list):
                for idx, child in enumerate(value):
                    walk(child, f"{path}/{idx}")
        walk(operation_args or {}, "/operation/arguments")
        walk(facts.get("supporting_lookup_result", {}), "/state/facts/supporting_lookup_result")
        walk(model, "/ground_truth/model_output")
        lookup = facts.get("supporting_lookup_result", {})
        if isinstance(lookup, dict) and lookup.get("resolution") in {"unique", "multiple", "zero"}:
            count = len(lookup.get("candidate_ids", []))
            expected = {"unique": 1, "multiple": 2, "zero": 0}[lookup["resolution"]]
            if (lookup["resolution"] == "unique" and count != 1) or (lookup["resolution"] == "multiple" and count < 2) or (lookup["resolution"] == "zero" and count != 0):
                self._add("ERROR", "SCENARIO_LOOKUP_RESOLUTION_COUNT", file, rid, "/state/facts/supporting_lookup_result", f"Lookup resolution {lookup['resolution']} is inconsistent with {count} candidate IDs (expected {expected if lookup['resolution'] != 'multiple' else 'at least 2'}).")

    def _validate_scenario_authenticity(self, scenario: dict[str, Any], file: str) -> None:
        """Reject deterministic training/meta leakage; semantic authenticity stays a human review."""
        rid = scenario.get("scenario_id", "")
        facts = scenario.get("state", {}).get("facts", {})
        output = scenario.get("ground_truth", {}).get("model_output", {})
        expected_business_result = scenario.get("ground_truth", {}).get("expected_business_result", {})
        family_ids = [value for value in (scenario.get("source", {}).get("source_id", ""), scenario.get("scenario_family_id", "")) if value]
        family_code = scenario.get("source", {}).get("source_id", "")
        matrix_title = self.family_titles.get(family_code, "")
        title = scenario.get("title", "")
        user_message = next((row.get("value") for row in facts.get("recorded_facts", [])
                             if isinstance(row, dict) and row.get("field") == "user_message"), "")
        normalized = lambda value: re.sub(r"[\s，。！？、：:；;（）()\[\]{}\"'`]+", "", str(value)).casefold()
        if normalized(user_message) in {normalized(value) for value in [*family_ids, title, matrix_title] if value}:
            self._add("ERROR", "SCENARIO_CONTENT_FAMILY_TEXT", file, rid, "/state/facts/recorded_facts", "User message must be a business utterance, not a family ID or scenario title.")
        output_strings: list[tuple[str, str]] = []
        def visit(value: Any, path: str) -> None:
            if isinstance(value, dict):
                for key, child in value.items(): visit(child, path + "/" + key)
            elif isinstance(value, list):
                for index, child in enumerate(value): visit(child, f"{path}/{index}")
            elif isinstance(value, str): output_strings.append((value, path))
        visit(output, "/ground_truth/model_output")
        for value, path in output_strings:
            low = value.casefold()
            user_facing = path.endswith(("/content", "/question", "/summary"))
            family_leak = any(re.search(r"(?<![A-Za-z0-9_])" + re.escape(code) + r"(?![A-Za-z0-9_])", value, re.I) for code in family_ids)
            title_leak = bool(matrix_title and normalized(matrix_title) in normalized(value))
            if user_facing and (family_leak or title_leak or any(term in low for term in ("coverage matrix", "canonical scenario", "ground truth", "family_id", "training example", "proposal"))):
                self._add("ERROR", "SCENARIO_OUTPUT_META_TEXT", file, rid, path, "User-facing model output must not expose family or dataset-production metadata.")
        if isinstance(expected_business_result, dict):
            expected_strings: list[tuple[str, str]] = []
            def visit_expected(value: Any, path: str) -> None:
                if isinstance(value, dict):
                    for key, child in value.items(): visit_expected(child, path + "/" + key)
                elif isinstance(value, list):
                    for index, child in enumerate(value): visit_expected(child, f"{path}/{index}")
                elif isinstance(value, str): expected_strings.append((value, path))
            visit_expected(expected_business_result, "/ground_truth/expected_business_result")
            for value, path in expected_strings:
                if path.endswith("/blocked_by") or path.endswith("/result_id"):
                    continue
                if any(re.search(r"(?<![A-Za-z0-9_])" + re.escape(code) + r"(?![A-Za-z0-9_])", value, re.I) for code in family_ids):
                    self._add("ERROR", "SCENARIO_EXPECTED_RESULT_FAMILY_TEXT", file, rid, path, "Expected business annotations must not contain Family IDs.")
                if matrix_title and normalized(matrix_title) in normalized(value):
                    self._add("ERROR", "SCENARIO_EXPECTED_RESULT_FAMILY_TEXT", file, rid, path, "Expected business annotations must not contain Coverage Matrix titles.")
                if re.search(r"coverage\s+matrix|canonical scenario|ground truth|family_id", value, re.I):
                    self._add("ERROR", "SCENARIO_EXPECTED_RESULT_META_TEXT", file, rid, path, "Expected business annotations must not contain production metadata or stale synthetic result identifiers.")
            expected_lookup = expected_business_result.get("supporting_lookup", None)
            state_lookup = facts.get("supporting_lookup_result", None)
            if expected_lookup is not None and expected_lookup != (state_lookup if state_lookup is not None else {}):
                self._add("ERROR", "SCENARIO_EXPECTED_LOOKUP_MISMATCH", file, rid, "/ground_truth/expected_business_result/supporting_lookup", "Expected supporting_lookup must deeply equal the recorded supporting_lookup_result.")
            known_result_ids: set[str] = set()
            def collect_result_ids(value: Any) -> None:
                if isinstance(value, dict):
                    for key, child in value.items():
                        if key == "result_id" and isinstance(child, str): known_result_ids.add(child)
                        elif key in {"result_ids", "evidence_result_ids"} and isinstance(child, list): known_result_ids.update(x for x in child if isinstance(x, str))
                        else: collect_result_ids(child)
                elif isinstance(value, list):
                    for child in value: collect_result_ids(child)
            collect_result_ids(facts)
            def check_result_refs(value: Any, path: str) -> None:
                if isinstance(value, dict):
                    for key, child in value.items():
                        child_path = path + "/" + key
                        if key == "result_id" and isinstance(child, str) and child not in known_result_ids:
                            self._add("ERROR", "SCENARIO_EXPECTED_RESULT_REFERENCE", file, rid, child_path, "Expected result identifier must resolve to a recorded result.")
                        elif key in {"result_ids", "evidence_result_ids"} and isinstance(child, list):
                            for index, result_id in enumerate(child):
                                if isinstance(result_id, str) and result_id not in known_result_ids:
                                    self._add("ERROR", "SCENARIO_EXPECTED_RESULT_REFERENCE", file, rid, f"{child_path}/{index}", "Expected result identifier must resolve to a recorded result.")
                        else: check_result_refs(child, child_path)
                elif isinstance(value, list):
                    for index, child in enumerate(value): check_result_refs(child, f"{path}/{index}")
            check_result_refs(expected_business_result, "/ground_truth/expected_business_result")
        business_text = [scenario.get("title", ""), facts.get("operation_arguments", {}).get("title", ""), facts.get("operation_arguments", {}).get("query", "")]
        for index, value in enumerate(business_text):
            if not isinstance(value, str): continue
            if re.search(r"(?:^|[^A-Za-z0-9])(?:L1|L2|D4)(?:$|[^A-Za-z0-9])|proposal|coverage\s+matrix|→|⇒", value, re.I):
                self._add("ERROR", "SCENARIO_BUSINESS_META_TEXT", file, rid, f"/business_text/{index}", "Business titles and queries must not contain workflow or training labels.")
            if matrix_title and normalized(value) == normalized(matrix_title):
                self._add("ERROR", "SCENARIO_BUSINESS_META_TEXT", file, rid, f"/business_text/{index}", "Business titles and queries must describe the request, not repeat the Matrix family title.")
        # A line citation must point to substantive content, not a Markdown heading or JSON root marker.
        for index, reference in enumerate(scenario.get("trust", {}).get("evidence_refs", [])):
            if not isinstance(reference, str): continue
            path_text, marker, fragment = reference.partition("#")
            if marker and re.fullmatch(r"L[1-9][0-9]*", fragment):
                try:
                    line = (self.root / path_text).read_text(encoding="utf-8-sig").splitlines()[int(fragment[1:]) - 1].strip()
                except (OSError, UnicodeError, IndexError):
                    continue
                if re.fullmatch(r"(?:#{1,6}\s*.*|\{+[, ]*|\[+[, ]*|\}+[\], ]*)", line) or len(line) < 18:
                    self._add("ERROR", "EVIDENCE_REF_LOW_QUALITY", file, rid, f"/trust/evidence_refs/{index}", "Evidence line must contain substantive rule or source content, not only a heading or JSON delimiter.")
        # Every declared entity must support an actual fact, argument, result, or output reference.
        serialized = json.dumps({key: value for key, value in scenario.items() if key != "state"}, ensure_ascii=False)
        serialized += json.dumps(scenario.get("state", {}).get("facts", {}), ensure_ascii=False)
        for index, entity in enumerate(scenario.get("state", {}).get("entities", [])):
            entity_id = entity.get("id")
            if entity_id and entity_id not in serialized:
                self._add("ERROR", "SCENARIO_ENTITY_UNUSED", file, rid, f"/state/entities/{index}", "Declared entity must be referenced by the recorded business state or Ground Truth.")
        tags = set(scenario.get("rule_tags", []))
        output_type = output.get("type")
        if ("clarification" in tags) != (output_type == "clarification"):
            self._add("ERROR", "SCENARIO_RULE_TAG_OUTPUT_MISMATCH", file, rid, "/rule_tags", "The clarification tag must agree with the actual output type.")
        if "d4_preview_only" in tags:
            policy = output.get("execution_policy", {})
            if output_type != "proposal" or policy.get("execution_allowed") is not False or policy.get("reason") != "d4_atomic_update_not_supported":
                self._add("ERROR", "SCENARIO_RULE_TAG_OUTPUT_MISMATCH", file, rid, "/rule_tags", "d4_preview_only requires a disabled D4 proposal.")
        context_facts = facts
        required_context = {
            "ui_context": ("ui_context",),
            "interaction_context": ("interaction_context", "recent_actions"),
            "conversation_context": ("conversation_context",),
        }
        for tag, fact_names in required_context.items():
            if tag not in tags:
                continue
            if not any(context_facts.get(name) for name in fact_names):
                self._add("ERROR", "SCENARIO_CONTEXT_TAG_STATE_MISMATCH", file, rid, "/rule_tags", f"{tag} requires a corresponding non-empty recorded state fact.")

    def _validate_scenario_d4_read_diff(self, scenario: dict[str, Any], file: str) -> None:
        """Ensure D4 before-values are anchored to the recorded server read."""
        rid = scenario.get("scenario_id", "")
        output = scenario.get("ground_truth", {}).get("model_output", {})
        if output.get("intent_id") not in {"update_expense", "update_refund"}:
            return
        facts = scenario.get("state", {}).get("facts", {})
        read = facts.get("verified_read_result", {})
        expense = read.get("expense", {}) if isinstance(read, dict) else {}
        if read.get("source") != "server_result" or not expense:
            self._add("ERROR", "D4_READ_SOURCE_MISSING", file, rid, "/state/facts/verified_read_result", "D4 before-values require a recorded server read of the current Expense.")
            return
        original = expense.get("original", {})
        field_sources = {
            "title": expense.get("title"),
            "original_amount": original.get("amount"),
            "original_currency": original.get("currency"),
            "payments": expense.get("payments"),
            "manual_splits": expense.get("splits"),
            "occurred_at": expense.get("occurred_at"),
            "note": expense.get("note"),
            "icon_key": expense.get("icon_key"),
        }
        for index, item in enumerate(output.get("preview", {}).get("diff", [])):
            field = item.get("field") if isinstance(item, dict) else None
            if field in field_sources and field_sources[field] is not None and item.get("before") != field_sources[field]:
                self._add("ERROR", "D4_BEFORE_READ_MISMATCH", file, rid, f"/ground_truth/model_output/preview/diff/{index}/before", f"D4 before-value for {field} must equal the verified server read.")

    def _validate_scenario_batch_authenticity(self, scenarios: list[dict[str, Any]], file: str) -> None:
        seen: dict[str, str] = {}
        for scenario in scenarios:
            rid = scenario.get("scenario_id", "")
            assertions = scenario.get("ground_truth", {}).get("deterministic_assertions", [])
            family_id = scenario.get("source", {}).get("source_id", "")
            title = scenario.get("title", "")
            matrix_title = self.family_titles.get(family_id, "")
            known_result_ids: set[str] = set()
            def collect_result_ids(value: Any) -> None:
                if isinstance(value, dict):
                    for key, child in value.items():
                        if key == "result_id" and isinstance(child, str): known_result_ids.add(child)
                        else: collect_result_ids(child)
                elif isinstance(value, list):
                    for child in value: collect_result_ids(child)
            collect_result_ids(scenario.get("state", {}).get("facts", {}))
            for index, assertion in enumerate(assertions):
                value = str(assertion)
                family_check_value = value
                for result_id in known_result_ids:
                    family_check_value = family_check_value.replace(result_id, "")
                if family_id and family_id.casefold() in family_check_value.casefold():
                    self._add("ERROR", "SCENARIO_ASSERTION_FAMILY_TEXT", file, rid, f"/ground_truth/deterministic_assertions/{index}", "Assertions must state checkable business facts without using the family ID as their differentiator.")
                key = re.sub(r"[\W_]+", "", value.casefold())
                # Family/title substitutions are not permitted to make a shared assertion appear unique.
                key = key.replace(re.sub(r"[\W_]+", "", title.casefold()), "")
                if matrix_title:
                    key = key.replace(re.sub(r"[\W_]+", "", matrix_title.casefold()), "")
                if key in seen:
                    self._add("ERROR", "SCENARIO_ASSERTION_DUPLICATE", file, rid, f"/ground_truth/deterministic_assertions/{index}", f"Assertion duplicates a batch assertion in {seen[key]} after title normalization.")
                else:
                    seen[key] = rid
                if re.search(r"本轮用户原话为[“\"「『].+?[”\"」』].{0,12}(?:回答|输出)不得增加这句话未提供的", value):
                    self._add("ERROR", "SCENARIO_ASSERTION_BOILERPLATE", file, rid, f"/ground_truth/deterministic_assertions/{index}", "Replace the generic user-quote guardrail with a scenario-specific, checkable business assertion.")
    def _leakage(self, scenarios: list[dict[str, Any]], samples: list[dict[str, Any]]) -> None:
        family: dict[str, str] = {}
        group: dict[str, str] = {}
        locations: dict[str, str] = {}
        rows = [(x, "scenario", x.get("scenario_id")) for x in scenarios] + [(x, "sample", x.get("sample_id")) for x in samples]
        for obj, kind, rid in rows:
            split = obj.get("split", "unassigned")
            for keyname, seen in (("scenario_family_id", family), ("split_group_id", group)):
                key = obj.get(keyname)
                if key in seen and seen[key] != split:
                    self._add("ERROR", "SPLIT_LEAKAGE", kind + "s.json", rid, f"/{keyname}", f"{keyname} {key} occurs in split {seen[key]} and {split}.")
                else:
                    seen[key] = split

    def _deduplicate(self, samples: list[dict[str, Any]]) -> None:
        exact: dict[str, str] = {}
        normalized: dict[str, str] = {}
        semantic: dict[str, dict[str, Any]] = {}
        for sample in samples:
            rid = sample.get("sample_id")
            reduced = copy.deepcopy(sample)
            reduced.pop("sample_id", None)
            metadata = reduced.get("dataset_metadata", {})
            for key in ("normalization_key", "dedup_key", "semantic_group_key", "review_notes"):
                metadata.pop(key, None)
            token = json.dumps(reduced, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
            if digest in exact:
                self._add("ERROR", "EXACT_DUPLICATE", "samples.json", rid, "/", f"Exact duplicate of sample {exact[digest]}.")
            else:
                exact[digest] = rid or ""
            text = sample.get("input", {}).get("user_message", "")
            normalized_text = self._normalize(text)
            if normalized_text in normalized:
                prior = next((x for x in samples if x.get("sample_id") == normalized[normalized_text]), {})
                if sample.get("split") != prior.get("split"):
                    self._add("ERROR", "NORMALIZED_DUPLICATE_CROSS_SPLIT", "samples.json", rid, "/input/user_message", f"Normalized surface duplicate crosses split with {normalized[normalized_text]}.")
                else:
                    self._add("WARNING", "NORMALIZED_DUPLICATE", "samples.json", rid, "/input/user_message", f"Normalized surface duplicate of sample {normalized[normalized_text]}.")
            else:
                normalized[normalized_text] = rid or ""
            group_key = sample.get("dataset_metadata", {}).get("semantic_group_key")
            if group_key:
                prior = semantic.get(group_key)
                if prior:
                    if sample.get("split") != prior.get("split"):
                        self._add("ERROR", "SEMANTIC_GROUP_CROSS_SPLIT", "samples.json", rid, "/dataset_metadata/semantic_group_key", f"Semantic group {group_key} crosses split with {prior.get('sample_id')}.")
                    else:
                        self._add("WARNING", "SEMANTIC_GROUP_REVIEW", "samples.json", rid, "/dataset_metadata/semantic_group_key", f"Semantic group repeats within a split; review family-level deduplication against {prior.get('sample_id')}.")
                else:
                    semantic[group_key] = sample

    @staticmethod
    def _normalize(text: str) -> str:
        text = unicodedata.normalize("NFKC", text).casefold()
        return "".join(ch for ch in text if ch.isalnum())

    def _statistics(self, scenarios: list[dict[str, Any]], samples: list[dict[str, Any]]) -> dict[str, Any]:
        lookup_resolutions = Counter(
            x.get("state", {}).get("facts", {}).get("supporting_lookup_result", {}).get("resolution")
            for x in scenarios
            if x.get("state", {}).get("facts", {}).get("supporting_lookup_result", {}).get("resolution") in {"unique", "multiple", "zero"}
        )
        return {
            "scenarios": len(scenarios),
            "samples": len(samples),
            "families": len({x.get("scenario_family_id") for x in scenarios if x.get("scenario_family_id")}),
            "splits": dict(Counter(x.get("split", "unassigned") for x in samples)),
            "tasks": dict(Counter(x.get("task", {}).get("primary", "unknown") for x in samples)),
            "scopes": dict(Counter(x.get("scope", {}).get("ai_scope", "unknown") for x in samples)),
            "sources": dict(Counter("manual" if x.get("source", {}).get("surface_form_type") == "human_authored" else x.get("source", {}).get("surface_form_type", "unknown") for x in samples)),
            "trust": {key: sum(x.get("trust", {}).get("level") == key for x in samples) for key in ("GOLD", "SILVER", "SYNTHETIC_UNVERIFIED")},
            "difficulty": {key: sum(x.get("difficulty") == key for x in samples) for key in ("easy", "normal", "hard", "ood")},
            "lifecycle": {key: sum(x.get("dataset_metadata", {}).get("lifecycle_status") == key for x in samples) for key in ("draft", "generated", "validated", "reviewed", "approved", "rejected", "deprecated")},
            "supporting_lookup_resolutions": {key: lookup_resolutions.get(key, 0) for key in ("unique", "multiple", "zero")},
        }

    def _validate_manifest(self, manifest: dict[str, Any], scenarios: list[dict[str, Any]], samples: list[dict[str, Any]], dataset_root: str | Path | None, file: str) -> None:
        rid = "manifest"
        self._schema_errors(manifest, self.schemas["manifest"], file, rid, "$")
        for key, expected in (("dataset_version", "0.1"), ("business_logic_version", "1.2"), ("ai_contract_version", "0.1.2"), ("ai_scope_version", "0.1"), ("frozen_reference_sha", BASELINE_SHA)):
            if manifest.get(key) != expected:
                self._add("ERROR", "MANIFEST_VERSION", file, rid, f"/{key}", f"Expected {key}={expected}.")
        stats = self._statistics(scenarios, samples)
        expected_values = {
            "scenario_count": len(scenarios), "scenario_family_count": stats["families"], "sample_count": len(samples),
            "split_statistics": {key: stats["splits"].get(key, 0) for key in ["train", "validation", "test", "hard_test", "unassigned"]},
            "task_statistics": stats["tasks"], "scope_statistics": stats["scopes"], "source_statistics": stats["sources"],
            "trust_statistics": stats["trust"], "difficulty_statistics": stats["difficulty"], "lifecycle_statistics": stats["lifecycle"],
        }
        for key, expected in expected_values.items():
            if manifest.get(key) != expected:
                self._add("ERROR", "MANIFEST_STATISTICS", file, rid, f"/{key}", f"Manifest declaration differs from recomputed value {expected!r}.")
        policy = manifest.get("split_policy", {})
        if policy.get("assignment_unit") != "scenario_family":
            self._add("ERROR", "MANIFEST_SPLIT_POLICY", file, rid, "/split_policy/assignment_unit", "Split assignment unit must be scenario_family.")
        targets = policy.get("target_percentages", {})
        if sum(targets.values()) != 100:
            self._add("ERROR", "MANIFEST_SPLIT_POLICY", file, rid, "/split_policy/target_percentages", "Split target percentages must sum to 100.")
        if dataset_root:
            root = Path(dataset_root).resolve()
            for index, artifact in enumerate(manifest.get("artifacts", [])):
                artifact_path = (root / artifact.get("path", "")).resolve()
                if not artifact_path.is_relative_to(root) or not artifact_path.is_file():
                    self._add("ERROR", "MANIFEST_ARTIFACT_MISSING", file, rid, f"/artifacts/{index}/path", "Manifest artifact path is missing or escapes the Dataset root.")
                    continue
                digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
                if artifact.get("sha256") != digest:
                    self._add("ERROR", "MANIFEST_ARTIFACT_HASH", file, rid, f"/artifacts/{index}/sha256", "Artifact SHA-256 does not match file content.")
                count = len(self._read_json(artifact_path))
                if artifact.get("record_count") != count:
                    self._add("ERROR", "MANIFEST_ARTIFACT_COUNT", file, rid, f"/artifacts/{index}/record_count", f"Artifact record_count must be {count}.")
        declared_errors = manifest.get("validation_summary", {}).get("error_count")
        actual_errors = sum(issue.severity == "ERROR" for issue in self._issues)
        if declared_errors != actual_errors:
            self._add("ERROR", "MANIFEST_VALIDATION_COUNT", file, rid, "/validation_summary/error_count", f"Manifest error_count must reflect the {actual_errors} errors found before Manifest summary validation.")

    def _report(self, statistics: dict[str, Any]) -> ValidationReport:
        errors = [x for x in self._issues if x.severity == "ERROR"]
        warnings = [x for x in self._issues if x.severity == "WARNING"]
        info = [x for x in self._issues if x.severity == "INFO"]
        return ValidationReport(not errors, errors, warnings, info, statistics)

    def load_dataset(self, path: str | Path) -> ValidationReport:
        target = Path(path).resolve()
        if target.is_file():
            if target.name == "dataset_manifest.json":
                base = target.parent.parent if target.parent.name == "examples" else target.parent
                manifest_path = target
            else:
                raise ValueError("Dataset validation needs a directory or dataset_manifest.json path.")
        else:
            base = target.parent if target.name == "examples" else target
            manifest_path = (target / "dataset_manifest.json") if target.name == "examples" else target / "manifest.json"
            if not manifest_path.exists() and (target / "dataset_manifest.json").exists():
                manifest_path = target / "dataset_manifest.json"
        scenario_path = base / "examples/scenarios.json" if base.name == "dataset" and not (base / "scenarios.json").exists() else base / "scenarios.json"
        sample_path = base / "examples/samples.json" if base.name == "dataset" and not (base / "samples.json").exists() else base / "samples.json"
        if target.name == "examples":
            scenario_path, sample_path = target / "scenarios.json", target / "samples.json"
        scenarios = self._read_json(scenario_path)
        samples = self._read_json(sample_path)
        manifest = self._read_json(manifest_path) if manifest_path.exists() else None
        root = base
        return self.validate_dataset(scenarios, samples, manifest, root, {"scenarios": str(scenario_path), "samples": str(sample_path), "manifest": str(manifest_path)})

    def validate_file(self, kind: str, path: str | Path) -> ValidationReport:
        target = Path(path).resolve()
        value = self._read_json(target)
        if kind == "scenario":
            if not isinstance(value, dict):
                raise ValueError("Scenario input must be one JSON object.")
            return self.validate_scenario(value, str(target))
        if kind == "sample":
            if not isinstance(value, dict):
                raise ValueError("Sample input must be one JSON object.")
            return self.validate_sample(value, file=str(target))
        if kind == "manifest":
            if not isinstance(value, dict):
                raise ValueError("Manifest input must be one JSON object.")
            dataset_root = target.parent.parent if target.parent.name == "examples" else target.parent
            artifact_files = {entry.get("kind"): entry.get("path") for entry in value.get("artifacts", [])}

            def load_records(kind_name: str, fallback: str) -> list[dict[str, Any]]:
                candidates = []
                if artifact_files.get(kind_name):
                    candidates.append(dataset_root / artifact_files[kind_name])
                candidates.extend([dataset_root / fallback, target.parent / Path(fallback).name])
                for candidate in candidates:
                    if candidate.is_file():
                        return self._read_json(candidate)
                return []

            scenarios = load_records("scenario", "scenarios.json")
            samples = load_records("sample", "samples.json")
            return self.validate_dataset(scenarios, samples, value, dataset_root, {"manifest": str(target)})
        raise ValueError(f"Unsupported record kind: {kind}")
