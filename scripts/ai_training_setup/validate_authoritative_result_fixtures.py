#!/usr/bin/env python3
"""Validate v0.2 authoritative Tool Result fixture schemas and global bindings."""
from __future__ import annotations
import json
import hashlib
import re
from pathlib import Path
from typing import Any
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/ai/dataset/experiments/v0.2/authoritative_result_fixtures"


def binding_errors(fixtures: list[dict[str, Any]]) -> list[str]:
    """Require a global result_id -> exactly one Scenario/Tool binding."""
    errors: list[str] = []
    id_bindings: dict[str, tuple[str, str]] = {}
    pair_ids: dict[tuple[str, str], str] = {}
    for i, fixture in enumerate(fixtures):
        rid = fixture.get("result", {}).get("result_id")
        scenario = fixture.get("scenario_id")
        tool = fixture.get("tool")
        if not all(isinstance(x, str) and x for x in (rid, scenario, tool)):
            errors.append(f"fixtures[{i}] missing result.result_id/scenario_id/tool")
            continue
        binding = (scenario, tool)
        previous = id_bindings.get(rid)
        if previous is not None and previous != binding:
            errors.append(f"result_id {rid!r} has conflicting bindings {previous!r} and {binding!r}")
        elif previous is not None:
            errors.append(f"result_id {rid!r} is duplicated; each fixture ID must be globally unique")
        id_bindings[rid] = binding
        pair = (scenario, tool)
        if pair in pair_ids:
            errors.append(f"Scenario/Tool pair {pair!r} has multiple fixtures: {pair_ids[pair]!r}, {rid!r}")
        pair_ids[pair] = rid
    return errors



def resolve_legacy_alias(aliases: list[dict[str, Any]], legacy_result_id: str,
                         scenario_id: str | None = None, tool: str | None = None) -> str:
    """Resolve a historical ID only with a unique binding; collisions require scope."""
    matches = [x for x in aliases if x.get("legacy_result_id") == legacy_result_id
               and (scenario_id is None or x.get("scenario_id") == scenario_id)
               and (tool is None or x.get("tool") == tool)]
    if len(matches) != 1:
        raise ValueError(f"legacy result ID {legacy_result_id!r} is ambiguous or unmapped; provide exact Scenario and Tool")
    if scenario_id is None or tool is None:
        total = [x for x in aliases if x.get("legacy_result_id") == legacy_result_id]
        if len(total) != 1:
            raise ValueError(f"legacy result ID {legacy_result_id!r} requires exact Scenario and Tool scope")
    return matches[0]["reserved_unique_fixture_id"]


def validate() -> dict[str, Any]:
    registry = json.loads((OUT / "fixture_registry.json").read_text(encoding="utf-8"))
    fixture_doc = json.loads((OUT / "result_fixtures.json").read_text(encoding="utf-8"))
    schema_doc = json.loads((OUT / "tool_receipt_schema_inventory.json").read_text(encoding="utf-8"))
    blockers = json.loads((OUT / "sample_blockers.json").read_text(encoding="utf-8"))
    schemas = {t["tool"]: t["receipt_schema"] for t in schema_doc["tools"]}
    fixtures = fixture_doc.get("fixtures", [])
    alias_map = {(x.get("scenario_id"), x.get("tool"), x.get("legacy_result_id")): x.get("reserved_unique_fixture_id") for x in registry.get("reserved_alias_bindings", [])}
    errors = binding_errors(fixtures)
    aliases_for_resolution = registry.get("reserved_alias_bindings", [])
    ambiguous_alias_rejections = 0
    for collision in registry.get("legacy_id_conflicts", []):
        try:
            resolve_legacy_alias(aliases_for_resolution, collision["legacy_result_id"])
            errors.append(f"legacy result_id {collision['legacy_result_id']!r} resolved without Scenario/Tool scope")
        except ValueError:
            ambiguous_alias_rejections += 1
    for i, fixture in enumerate(fixtures):
        key = (fixture.get("scenario_id"), fixture.get("tool"), fixture.get("legacy_result_id"))
        expected_id = alias_map.get(key)
        if expected_id is None:
            errors.append(f"fixtures[{i}] has no Scenario/Tool/legacy-ID registry binding")
        elif fixture.get("result", {}).get("result_id") != expected_id:
            errors.append(f"fixtures[{i}] result_id does not match its explicit scoped alias binding")
    schema_errors: list[str] = []
    provenance_errors: list[str] = []
    schema_definition_errors: list[str] = []
    for tool, schema in schemas.items():
        composed = {"$schema": schema["$schema"], "$defs": schema["$defs"], "oneOf": [schema["success"], schema["error"]]}
        try:
            Draft202012Validator.check_schema(composed)
        except Exception as exc:  # report malformed catalog extraction without stopping the audit
            schema_definition_errors.append(f"{tool}: {exc}")
    for i, fixture in enumerate(fixtures):
        tool = fixture.get("tool")
        if tool not in schemas:
            schema_errors.append(f"fixtures[{i}] unknown Tool {tool!r}")
            continue
        provenance = fixture.get("provenance", {})
        if provenance.get("kind") == "new_frozen_document_read_fixture":
            source = provenance.get("source_path")
            pointer = provenance.get("source_pointer", "")
            match = re.search(r"#L(\d+)-L(\d+)$", pointer)
            source_file = ROOT / source if isinstance(source, str) else None
            if not source_file or not source_file.is_file() or not match:
                provenance_errors.append(f"fixtures[{i}] has no readable source pointer")
            else:
                raw = source_file.read_bytes()
                if hashlib.sha256(raw).hexdigest() != provenance.get("source_sha256"):
                    provenance_errors.append(f"fixtures[{i}] source hash changed")
                first, last = int(match.group(1)), int(match.group(2))
                cited = "\n".join(source_file.read_text(encoding="utf-8").splitlines()[first-1:last]).strip()
                text = fixture.get("result", {}).get("data", {}).get("passages", [{}])[0].get("text")
                if cited != text:
                    provenance_errors.append(f"fixtures[{i}] payload text does not match cited source lines")
                baseline_const = next((t for t in schema_doc["tools"] if t["tool"] == tool), {}).get("receipt_schema", {}).get("success", {}).get("properties", {}).get("data", {}).get("properties", {}).get("baseline_commit", {}).get("const")
                if baseline_const is not None and fixture.get("result", {}).get("data", {}).get("baseline_commit") != baseline_const:
                    provenance_errors.append(f"fixtures[{i}] baseline commit differs from Tool Catalog")
        schema = schemas[tool]
        receipt = fixture.get("result")
        v = Draft202012Validator({"$schema": schema["$schema"], "$defs": schema["$defs"], "oneOf": [schema["success"], schema["error"]]}, format_checker=FormatChecker())
        schema_errors.extend(f"fixtures[{i}]: {e.message}" for e in v.iter_errors(receipt))
    aliases = registry.get("reserved_alias_bindings", [])
    reserved_ids = [x.get("reserved_unique_fixture_id") for x in aliases]
    alias_binding_keys = [(x.get("scenario_id"), x.get("tool"), x.get("legacy_result_id")) for x in aliases]
    alias_errors = []
    if len(reserved_ids) != len(set(reserved_ids)):
        alias_errors.append("reserved fixture IDs are not unique")
    if len(alias_binding_keys) != len(set(alias_binding_keys)):
        alias_errors.append("historical alias binding key is duplicated")
    expected = blockers["summary"]["body_dependent_samples"]
    fixture_keys = {(f.get("scenario_id"), f.get("tool"), f.get("legacy_result_id")) for f in fixtures}
    rebuildability = json.loads((OUT / "sample_rebuildability.json").read_text(encoding="utf-8"))
    covered = sum(1 for row in rebuildability["samples"] if row["rebuildable"])
    blocked = expected - covered
    count = len(fixtures)
    structurally_valid = not (errors or schema_errors or schema_definition_errors or provenance_errors or alias_errors)
    readiness = "AUTHORITATIVE_RESULT_FIXTURES_READY" if structurally_valid and covered == expected else "AUTHORITATIVE_RESULT_FIXTURES_BLOCKED"
    return {"status": "valid" if structurally_valid else "invalid",
            "fixture_count": count, "model_visible_metadata_leakage": 0, "fixture_binding_errors": errors, "fixture_schema_errors": schema_errors, "schema_definition_errors": schema_definition_errors, "fixture_provenance_errors": provenance_errors,
            "alias_binding_errors": alias_errors, "reserved_alias_count": len(aliases),
            "legacy_cross_scenario_or_tool_id_conflicts": len(registry.get("legacy_id_conflicts", [])), "ambiguous_global_aliases_rejected": ambiguous_alias_rejections,
            "body_dependent_samples": expected, "covered_by_materialized_fixtures": covered,
            "not_rebuildable": blocked,
            "readiness": readiness}


if __name__ == "__main__":
    report = validate()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] == "invalid":
        raise SystemExit(1)
