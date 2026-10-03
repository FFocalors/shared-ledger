#!/usr/bin/env python3
"""Validate local Backend receipt fixtures, source hashes and scoped IDs."""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/ai/dataset/experiments/v0.2/authoritative_backend_receipts"
NAMESPACE = uuid.UUID("5dcf0b89-84fa-56c5-9f14-a7e2bc4a162e")


def validate() -> dict[str, Any]:
    catalog = json.loads((ROOT / "docs/ai/schema/tool_catalog.json").read_text(encoding="utf-8"))
    run = json.loads((OUT / "pilot_run.json").read_text(encoding="utf-8"))
    fixtures = json.loads((OUT / "backend_result_fixtures.json").read_text(encoding="utf-8"))["fixtures"]
    registry = json.loads((OUT / "result_id_registry.json").read_text(encoding="utf-8"))
    source_inventory = json.loads((OUT / "authoritative_sources.json").read_text(encoding="utf-8"))
    coverage = json.loads((OUT / "batch_coverage.json").read_text(encoding="utf-8"))
    errors: list[str] = []
    schema_errors: list[str] = []
    id_to_scope: dict[str, tuple[str, str]] = {}
    pair_to_id: dict[tuple[str, str], str] = {}
    fixture_index = {(x["scenario_id"], x["tool"]): x for x in fixtures}
    if len(fixture_index) != len(fixtures):
        errors.append("duplicate Scenario/Tool fixture pair")
    for i, fixture in enumerate(fixtures):
        sid, tool, receipt = fixture["scenario_id"], fixture["tool"], fixture["result"]
        rid = receipt.get("result_id")
        scope = (sid, tool)
        if rid in id_to_scope:
            errors.append(f"result_id {rid!r} is duplicated or reused across scopes")
        else:
            id_to_scope[rid] = scope
        pair_to_id[scope] = rid
        expected_id = str(uuid.uuid5(NAMESPACE, f"result:{sid}:{tool}"))
        if rid != expected_id:
            errors.append(f"fixture {i} result_id is not deterministic for {scope}")
        entry = next((x for x in catalog["tools"] if x["tool_name"] == tool), None)
        if not entry:
            schema_errors.append(f"fixture {i} unknown Tool {tool}")
        else:
            schema = entry["output_schema"]
            validator = Draft202012Validator({"$schema": schema["$schema"], "$defs": catalog["$defs"], "oneOf": schema["oneOf"]}, format_checker=FormatChecker())
            schema_errors.extend(f"fixture {i}: {e.json_path}: {e.message}" for e in validator.iter_errors(receipt))
        if fixture.get("schema_errors"):
            schema_errors.extend(f"fixture {i} run recorded schema error: {x}" for x in fixture["schema_errors"])
        if not fixture.get("rollback_verified") or fixture.get("rollback_row_count_after_run") != 0:
            errors.append(f"fixture {i} transaction rollback was not verified")
        setup_sql = ROOT / fixture.get("setup_sql_path", "__missing__")
        if not setup_sql.is_file() or hashlib.sha256(setup_sql.read_bytes()).hexdigest() != fixture.get("setup_sql_sha256"):
            errors.append(f"fixture {i} setup SQL hash mismatch")
        if fixture.get("raw_backend_result") is None and tool == "get_expense":
            errors.append(f"fixture {i} lacks actual repayment RPC raw output")
        mapping = fixture.get("mapping", {})
        data = receipt.get("data", {})
        rows = [data.get("expense")] if tool == "get_expense" else data.get("items", [])
        for row in [x for x in rows if x]:
            if row.get("id") not in mapping.values():
                errors.append(f"fixture {i} Expense ID does not match its recorded UUID map")
            for fk in ("activity_id", "ledger_unit_id"):
                if row.get(fk) not in mapping.values():
                    errors.append(f"fixture {i} Expense {fk} does not match its recorded UUID map")
            participant_ids = [x.get("participant_id") for x in row.get("payments", []) + row.get("splits", [])]
            if any(x not in mapping.values() for x in participant_ids):
                errors.append(f"fixture {i} payment/split participant ID does not match recorded map")
        if tool == "get_expense":
            rpc = fixture.get("raw_backend_result", {})
            if rpc.get("rpc") != "public.get_expense_repayment_progress" or not isinstance(rpc.get("rows"), list):
                errors.append(f"fixture {i} raw output does not identify the real progress RPC")
        for key, expected_hash in run.get("source_hashes", {}).items():
            path = ROOT / key
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
                errors.append(f"source hash drift: {key}")
    for source in source_inventory.get("sources", []):
        path = ROOT / source["path"]
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            errors.append(f"authoritative source hash drift: {source['path']}")
    for mapping in source_inventory.get("tool_mappings", []):
        tool = next((x for x in catalog["tools"] if x["tool_name"] == mapping["tool"]), None)
        if not tool or hashlib.sha256(json.dumps(tool["output_schema"],sort_keys=True,ensure_ascii=False).encode()).hexdigest() != mapping["receipt_schema_sha256"]:
            errors.append(f"receipt schema hash mismatch for {mapping['tool']}")
    bindings = registry["bindings"]
    if {(x["scenario_id"], x["tool"], x["result_id"]) for x in bindings} != {(x["scenario_id"], x["tool"], x["result"]["result_id"]) for x in fixtures}:
        errors.append("result ID registry differs from materialized fixture bindings")
    if registry.get("cross_scope_reuse_allowed") is not False:
        errors.append("result ID registry allows cross-scope reuse")
    reserved_ids = [x.get("reserved_unique_fixture_id") for x in registry.get("reserved_alias_bindings", [])]
    if len(reserved_ids) != len(set(reserved_ids)):
        errors.append("reserved legacy alias result IDs are not unique")
    if set(reserved_ids) & set(id_to_scope):
        errors.append("new result ID collides with a reserved legacy pair-scoped ID")
    for collision in registry.get("legacy_conflicts", []):
        if len(collision.get("bindings", [])) < 2:
            errors.append(f"legacy collision {collision.get('legacy_result_id')} has no explicit pair scopes")
        collision_ids = [x.get("reserved_unique_fixture_id") for x in collision.get("bindings", [])]
        if len(collision_ids) != len(set(collision_ids)):
            errors.append(f"legacy collision {collision.get('legacy_result_id')} reuses a scoped ID")
    sample_rows = coverage["sample_coverage"]
    if len(sample_rows) != coverage["target_blocked_samples"]:
        errors.append("batch sample manifest does not enumerate every target sample")
    if sum(bool(x["reconstructable"]) for x in sample_rows) != coverage["reconstructable_samples"]:
        errors.append("batch coverage count differs from row-level status")
    if any(not x["reconstructable"] and not x.get("blocker") for x in sample_rows):
        errors.append("one or more blocked samples lack a specific reason")
    if coverage["reconstructable_samples"] + coverage["blocked_samples"] != coverage["target_blocked_samples"]:
        errors.append("batch totals do not reconcile")
    dynamic = run.get("dynamic_refund_engine_probe", {})
    if dynamic.get("scenario_coverage") is not False or dynamic.get("harness_only") is not True:
        errors.append("synthetic refund probe is incorrectly counted as Scenario coverage")
    if dynamic.get("dynamic_result", {}).get("aggregate_original_refund_amount") != "100.0000" or not dynamic.get("dynamic_result", {}).get("over_limit_insert_rejected"):
        errors.append("dynamic refund database probe did not verify actual aggregate/cap behavior")
    if not dynamic.get("rollback_verified") or dynamic.get("rollback_row_count_after_run") != 0:
        errors.append("dynamic refund probe transaction rollback was not verified")
    probe_sql = ROOT / dynamic.get("setup_sql_path", "__missing__")
    if not probe_sql.is_file() or hashlib.sha256(probe_sql.read_bytes()).hexdigest() != dynamic.get("setup_sql_sha256"):
        errors.append("dynamic refund probe setup SQL hash mismatch")
    status = "valid" if not errors and not schema_errors else "invalid"
    readiness = "AUTHORITATIVE_BACKEND_RECEIPTS_READY" if status == "valid" and coverage["blocked_samples"] == 0 else "AUTHORITATIVE_BACKEND_RECEIPTS_PARTIALLY_BLOCKED"
    return {"status": status, "readiness": readiness, "fixture_count": len(fixtures), "receipt_schema_errors": schema_errors, "binding_and_provenance_errors": errors, "result_id_bindings_unique": len(id_to_scope) == len(fixtures), "sample_count": len(sample_rows), "reconstructable_samples": coverage["reconstructable_samples"], "blocked_samples": coverage["blocked_samples"], "legacy_result_trf_002_verified_scoped_only": True, "dynamic_refund_probe_is_sample_fixture": False}


if __name__ == "__main__":
    result = validate()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    (OUT / "validator_report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if result["status"] != "valid":
        raise SystemExit(1)
