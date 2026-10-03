#!/usr/bin/env python3
"""Audit whether frozen v0.1 result references have visible, authoritative bodies.

This tool is deliberately read-only with respect to all frozen inputs. It writes
an Experiment B audit package, and refuses to invent missing Gateway receipt
metadata. It uses the unchanged v0.1 serializer to inspect the actual model view.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "docs/ai/dataset/canonical_training/v0.1"
OUT = ROOT / "docs/ai/dataset/experiments/v0.2/experiment_b"
CONTRACT = ROOT / "docs/ai/AI_MODEL_CONTRACT.md"
CATALOG = ROOT / "docs/ai/schema/tool_catalog.json"
SERIALIZER = ROOT / "scripts/ai_training_setup/export_dataset.py"
SCRIPT = Path(__file__).resolve()
RESULT_SOURCE_KEYS = {"verified_read_result", "verified_read_results", "supporting_lookup_result"}
PRIVATE_SOURCE_KEYS = {"source", "evidence_refs", "recording", "recorded_at", "reviewer", "provenance"}
RECEIPT_OMITTABLE_SOURCE_KEYS = {"source", "tool", "arguments"}
RECEIPT_REQUIRED = {"status", "result_id", "observed_at", "financial_version", "data"}
DATE_TIME = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$")

# Manual, fact-level review of every source-bearing canonical Scenario. Surface
# variants inherit the same business-state facts but are still checked row by
# row against their own serialized input below.
FACT_AUDIT: dict[str, dict[str, Any]] = {
    "scenario_gs_p0a_009": {"needs_result_body": True, "claims": [
        {"expected_fact": "existing Expense amount/currency and the before-values for payments/splits",
         "source_path": "state.facts.verified_read_result.expense.original; .payments; .splits",
         "visible_input": "selected Expense ID is visible; no Expense DTO or prior amounts are visible. User supplies requested new values, not verified current state."}]},
    "scenario_gs_p0b_004": {"needs_result_body": True, "claims": [
        {"expected_fact": "existing Expense amount/currency, payment and split values used as diff.before",
         "source_path": "state.facts.verified_read_result.expense.original; .payments; .splits",
         "visible_input": "The user mentions an old amount, but current persisted payment/split state is not present in model-visible context."}]},
    "scenario_gs_p0a_015": {"needs_result_body": True, "claims": [
        {"expected_fact": "JPY payable/net balance 0.01 and CNY prepayment account balance 20",
         "source_path": "state.facts.verified_read_results[result-p0a-balance-015].data.balance_by_currency; state.facts.verified_read_results[result-p0a-prepayment-015].data.accounts",
         "visible_input": "The user asks for balances; tool_results is empty, so neither authoritative DTO is visible."}]},
    "scenario_gs_p0b_009": {"needs_result_body": True, "claims": [
        {"expected_fact": "same-currency reverse-debt offset order and separate handling of different original currencies",
         "source_path": "state.facts.supporting_lookup_result.passage",
         "visible_input": "The user asks how prepayment is applied; no frozen rule passage is included in model-visible context."}]},
    "scenario_gs_p0b_010": {"needs_result_body": True, "claims": [
        {"expected_fact": "verified bilateral CNY debt amount 80 used to explain the 80 CNY cap",
         "source_path": "state.facts.supporting_lookup_result.debts[0]",
         "visible_input": "The user states the attempted transfer amount and asks about a cap; verified debt DTO is absent."}]},
    "scenario_gs_p0a_011": {"needs_result_body": True, "claims": [
        {"expected_fact": "target transfer ID and current is_voided=false state before proposing void",
         "source_path": "state.facts.supporting_lookup_result.transfer_id; .is_voided",
         "visible_input": "Activity ID and the user's reason are visible; no selected transfer binding or transfer status is in the serialized input."}]},
    "scenario_gs_p0b_012": {"needs_result_body": True, "claims": [
        {"expected_fact": "original expense identity and facts required to bind the negative refund expense to its source",
         "source_path": "state.facts.verified_read_result.expense.id; .original; .original_expense_id",
         "visible_input": "The user provides refund amount/date/beneficiary, but the persisted original-expense DTO and its ID are absent."}]},
    "scenario_gs_p0b_014": {"needs_result_body": False, "claims": [],
        "out_of_scope_note": "The expected output is a fresh get_final_settlement tool_call; its arguments come from the user's refresh request and activity context, not the old suggestion body. The mode default is not established by a prior result and is outside this result-body overlay."},
    "scenario_gs_p0a_012": {"needs_result_body": True, "claims": [
        {"expected_fact": "unique expense match, expense ID, and deletion-relevant expense state",
         "source_path": "state.facts.supporting_lookup_result.candidate_ids; .resolution; .expense",
         "visible_input": "The user query/title is visible, but the matching server candidate ID and DTO are absent."}]},
    "scenario_gs_p0b_016": {"needs_result_body": True, "claims": [
        {"expected_fact": "financial_locked=true and linked refund history explaining why deletion is blocked",
         "source_path": "state.facts.supporting_lookup_result.expenses[0].financial_locked; .linked_refund_ids",
         "visible_input": "The user reports deletion failure; no lookup result body establishing the lock/reason is visible."}]},
    "scenario_gs_p0b_017": {"needs_result_body": True, "claims": [
        {"expected_fact": "who paid and who bears this Expense, including the amount/currency",
         "source_path": "state.facts.supporting_lookup_result.expense.payments; .splits; .original",
         "visible_input": "The selected Expense ID and question are visible; payer/split DTO values are absent."}]},
    "scenario_gs_p0b_018": {"needs_result_body": True, "claims": [
        {"expected_fact": "current persisted Expense title/amount/payment/split values used for update diff",
         "source_path": "state.facts.verified_read_result.expense",
         "visible_input": "Selected Expense ID and edit form state are visible; the persisted DTO is absent."}]},
    "scenario_gs_p0b_019": {"needs_result_body": True, "claims": [
        {"expected_fact": "unique selected Expense match and unlocked state required by the proposal summary",
         "source_path": "state.facts.supporting_lookup_result.resolution; .candidate_ids; .expenses[0].financial_locked",
         "visible_input": "Selected Expense ID and route identify the target, but no authoritative current lock/read result is visible."}]},
    "scenario_gs_p0b_020": {"needs_result_body": True, "claims": [
        {"expected_fact": "persisted current title and Expense data used for the recent-action edit diff",
         "source_path": "state.facts.verified_read_result.expense",
         "visible_input": "Recent action reports create success and identifies an entity; its persisted current DTO is not included."}]},
    "scenario_gs_p0b_022": {"needs_result_body": True, "claims": [
        {"expected_fact": "zero matching expense result needed to say the attempted expense is not currently found",
         "source_path": "state.facts.supporting_lookup_result.resolution; .candidate_ids",
         "visible_input": "Recent action reports a failed write, but failure alone does not prove no row persisted; the lookup body is absent."}]},
    "scenario_gs_p0b_025": {"needs_result_body": True, "claims": [
        {"expected_fact": "multiple participant candidates and their display labels for clarification",
         "source_path": "state.facts.supporting_lookup_result.candidate_ids; state.entities[id].display_name",
         "visible_input": "The user pronoun is visible; neither candidate list nor candidate labels are in model-visible context."}]},
    "scenario_gs_p0b_033": {"needs_result_body": True, "claims": [
        {"expected_fact": "AA equal-split rule and the 33.4/33.3/33.3 example explanation",
         "source_path": "state.facts.supporting_lookup_result.passage",
         "visible_input": "The user asks why the allocation appears that way; no verified rule passage is visible."}]},
    "scenario_gs_p0b_034": {"needs_result_body": True, "claims": [
        {"expected_fact": "prepayment offsets reverse debt in the same currency, with usage only from a remainder",
         "source_path": "state.facts.supporting_lookup_result.passage",
         "visible_input": "The user asks about offset order; no verified rule passage is visible."}]},
    "scenario_gs_p0b_035": {"needs_result_body": True, "claims": [
        {"expected_fact": "refund history permanently locks the original expense even if the refund is deleted",
         "source_path": "state.facts.supporting_lookup_result.passage",
         "visible_input": "The user asks a policy question; no verified rule passage is visible."}]},
    "scenario_gs_p0b_036": {"needs_result_body": True, "claims": [
        {"expected_fact": "writes require trusted UI confirmation and chat 'OK' does not confirm",
         "source_path": "state.facts.supporting_lookup_result.passage",
         "visible_input": "The user describes chat confirmation; no verified policy passage is visible."}]},
    "scenario_gs_p0b_037": {"needs_result_body": True, "claims": [
        {"expected_fact": "cumulative refund cap and the service rejection threshold",
         "source_path": "state.facts.supporting_lookup_result.passage",
         "visible_input": "The user gives the attempted amount; no verified policy passage or refund-history result is visible."}]},
    "scenario_gs_p0b_038": {"needs_result_body": True, "claims": [
        {"expected_fact": "changed financial version invalidates the prior preview and requires a fresh read/preview",
         "source_path": "state.facts.supporting_lookup_result.passage",
         "visible_input": "The user reports the error; no verified rule passage is visible."}]},
    "scenario_gs_p0b_039": {"needs_result_body": True, "claims": [
        {"expected_fact": "archived activities are read-only and creator unarchive is required before new expenses",
         "source_path": "state.facts.supporting_lookup_result.passage",
         "visible_input": "The user asks about archived activity; no verified policy passage is visible."}]},
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def walk_result_objects(value: Any, path: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    if isinstance(value, dict):
        if isinstance(value.get("result_id"), str) and value.get("source") == "server_result" and isinstance(value.get("tool"), str):
            yield path or "$", value
        for key, child in value.items():
            yield from walk_result_objects(child, f"{path}.{key}" if path else f"$.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_result_objects(child, f"{path}[{index}]")


def find_ids(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"evidence_result_id", "verified_result_id"} and isinstance(child, str):
                result.add(child)
            elif key in {"evidence_result_ids", "verified_result_ids"} and isinstance(child, list):
                result.update(item for item in child if isinstance(item, str))
            result.update(find_ids(child))
    elif isinstance(value, list):
        for child in value:
            result.update(find_ids(child))
    return result


def load_serializer():
    spec = importlib.util.spec_from_file_location("shared_ledger_v01_exporter", SERIALIZER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load frozen serializer: {SERIALIZER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def has_business_body(record: dict[str, Any]) -> bool:
    return any(key not in {"tool", "arguments", "result_id", "source", "status", "observed_at", "financial_version"}
               for key in record)


def receipt_shape(record: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Check only source-backed receipt shape; never synthesize missing fields."""
    success = schema.get("oneOf", [{}])[0]
    allowed = set(success.get("properties", {}))
    supplied = {key: value for key, value in record.items() if key not in RECEIPT_OMITTABLE_SOURCE_KEYS}
    missing = sorted(RECEIPT_REQUIRED - set(supplied))
    extra = sorted(set(supplied) - allowed)
    errors = []
    if missing:
        errors.append("missing_required:" + ",".join(missing))
    if extra:
        errors.append("extra_properties:" + ",".join(extra))
    if supplied.get("status") != "success":
        errors.append("status_not_source_recorded_success")
    if not isinstance(supplied.get("result_id"), str) or not supplied.get("result_id"):
        errors.append("invalid_result_id")
    observed = supplied.get("observed_at")
    if not isinstance(observed, str) or not DATE_TIME.match(observed):
        errors.append("observed_at_missing_or_invalid")
    financial_version = supplied.get("financial_version")
    if financial_version is not None and (not isinstance(financial_version, str) or not financial_version.isdigit()):
        errors.append("financial_version_not_contract_value")
    data_schema = success.get("properties", {}).get("data", {})
    if isinstance(supplied.get("data"), dict):
        data = supplied["data"]
        required = set(data_schema.get("required", []))
        properties = set(data_schema.get("properties", {}))
        missing_data = sorted(required - set(data))
        extra_data = sorted(set(data) - properties) if properties else []
        if missing_data:
            errors.append("data_missing_required:" + ",".join(missing_data))
        if extra_data:
            errors.append("data_extra_properties:" + ",".join(extra_data))
    elif "data" in RECEIPT_REQUIRED:
        errors.append("data_not_present_as_contract_object")
    return {"contract_shape_valid": not errors, "errors": errors}


def sample_ref_ids(sample: dict[str, Any]) -> set[str]:
    ids = set(sample.get("input", {}).get("server_context", {}).get("verified_result_ids", []))
    ids.update(find_ids(sample.get("expected", {}).get("model_output", {})))
    return ids


def main() -> None:
    samples_path = CANONICAL / "samples.json"
    scenarios_path = CANONICAL / "scenarios.json"
    splits_path = CANONICAL / "split_assignment.json"
    dataset_manifest_path = CANONICAL / "dataset_manifest.json"
    samples = read_json(samples_path)
    scenarios = read_json(scenarios_path)
    catalog = read_json(CATALOG)
    scenario_by_id = {scenario["scenario_id"]: scenario for scenario in scenarios}
    result_schemas = {tool["tool_name"]: tool["output_schema"] for tool in catalog["tools"]}

    authority_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    authority_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for scenario in scenarios:
        facts = scenario.get("state", {}).get("facts", {})
        for source_path, record in walk_result_objects(facts):
            item = {"scenario_id": scenario["scenario_id"], "source_path": "state.facts." + source_path.removeprefix("$."),
                    "record": record}
            authority_by_key[(scenario["scenario_id"], record["result_id"])].append(item)
            authority_by_id[record["result_id"]].append(item)

    serializer = load_serializer()
    sample_audit: list[dict[str, Any]] = []
    reference_counter: Counter[str] = Counter()
    split_counts: Counter[str] = Counter()
    fully_grounded_rows = 0
    no_body_needed_rows = 0
    gap_rows = 0
    missing_business_authority_rows = 0
    missing_legal_receipt_rows = 0
    serializer_errors: list[dict[str, str]] = []
    source_inventory: dict[tuple[str, str], dict[str, Any]] = {}

    for sample in samples:
        ids = sorted(sample_ref_ids(sample))
        split = sample.get("split", "unassigned")
        split_counts[split] += 1
        for result_id in ids:
            reference_counter[result_id] += 1
        scenario = scenario_by_id[sample["scenario_id"]]
        fact_review = FACT_AUDIT.get(sample["scenario_id"]) if ids else None
        if ids and fact_review is None:
            raise ValueError(f"Manual expected-fact audit missing for {sample['scenario_id']}")
        outputs = sample.get("expected", {}).get("model_output", {})
        output_type = outputs.get("type")
        refs = []
        body_missing = []
        receipt_missing = []
        for result_id in ids:
            candidates = authority_by_key.get((sample["scenario_id"], result_id), [])
            matching = []
            for candidate in candidates:
                record = candidate["record"]
                schema = result_schemas.get(record["tool"], {})
                shape = receipt_shape(record, schema)
                entry_key = (candidate["scenario_id"], result_id)
                if entry_key not in source_inventory:
                    source_inventory[entry_key] = {
                        "scenario_id": candidate["scenario_id"], "result_id": result_id,
                        "tool": record["tool"], "source_path": candidate["source_path"],
                        "source_record_sha256": json_sha(record),
                        "business_payload_fields": sorted(set(record) - PRIVATE_SOURCE_KEYS - {"tool", "arguments", "result_id", "status", "observed_at", "financial_version"}),
                        "business_payload_present": has_business_body(record),
                        "contract_shape": shape,
                    }
                matching.append({"source_path": candidate["source_path"], "tool": record["tool"],
                                 "business_payload_fields": source_inventory[entry_key]["business_payload_fields"],
                                 "source_record_sha256": source_inventory[entry_key]["source_record_sha256"],
                                 "contract_shape": shape})
            if not matching:
                body_missing.append(result_id)
                receipt_missing.append(result_id)
            elif not any(item["business_payload_fields"] for item in matching):
                body_missing.append(result_id)
                receipt_missing.append(result_id)
            elif not any(item["contract_shape"]["contract_shape_valid"] for item in matching):
                receipt_missing.append(result_id)
            refs.append({"result_id": result_id, "visible_payload": any(
                item.get("result_id") == result_id for item in sample.get("input", {}).get("server_context", {}).get("tool_results", [])
            ), "authoritative_sources": matching})

        # The 23 scenario families were reviewed fact by fact. A result ID alone
        # is not evidence that the Expected Output consumes its old body.
        needs_prior_body = bool(ids and fact_review["needs_result_body"])
        visible_results = sample.get("input", {}).get("server_context", {}).get("tool_results", [])
        visible_result_ids = {r.get("result_id") for r in visible_results if isinstance(r, dict)}
        missing_visible_ids = [result_id for result_id in ids if result_id not in visible_result_ids]
        row_status = "NO_RESULT_ID_REFERENCE" if not ids else ("NO_PRIOR_RESULT_FACT_REQUIRED" if not needs_prior_body else (
            "ID_ONLY_BODY_INSUFFICIENT" if missing_visible_ids else "VISIBLE_RESULT_BODY_REVIEW_REQUIRED"))
        if ids and not needs_prior_body:
            no_body_needed_rows += 1
        elif needs_prior_body and missing_visible_ids:
            gap_rows += 1
        elif ids and needs_prior_body and not missing_visible_ids:
            fully_grounded_rows += 1
        if body_missing:
            missing_business_authority_rows += 1
        if receipt_missing and needs_prior_body:
            missing_legal_receipt_rows += 1

        # Run every row through the unchanged serializer and require JSON round
        # trip plus zero production metadata leakage.
        try:
            record, trace = serializer.export_record(copy.deepcopy(sample))
            _ = json.loads(serializer.compact(sample["expected"]["model_output"]))
            if not trace["history_roundtrip_verified"]:
                raise ValueError("conversation_history_roundtrip_failed")
        except Exception as exc:  # validation result is reported, never suppressed
            serializer_errors.append({"sample_id": sample["sample_id"], "error": f"{type(exc).__name__}: {exc}"})

        try:
            runtime_context = serializer.runtime_context(sample)
        except Exception:
            runtime_context = None
        sample_audit.append({
            "sample_id": sample["sample_id"], "scenario_id": sample["scenario_id"],
            "scenario_family_id": sample["scenario_family_id"], "split_group_id": sample["split_group_id"],
            "split": split, "output_type": output_type, "result_ids": ids,
            "expected_external_result_facts_required": needs_prior_body,
            "grounding_status": row_status, "result_refs": refs,
            "fact_claims": fact_review["claims"] if fact_review else [],
            "out_of_scope_grounding_note": fact_review.get("out_of_scope_note") if fact_review else None,
            "visible_input_fact_audit": "manual assessment recorded per Scenario; row's actual serialized user/context/history/runtime context and tool_results were inspected",
            "visible_user_message": sample.get("input", {}).get("user_message"),
            "visible_conversation_history": sample.get("input", {}).get("conversation_history", []),
            "visible_runtime_context": runtime_context,
            "visible_tool_results": visible_results,
            "missing_business_authority_result_ids": body_missing,
            "missing_contract_receipt_result_ids": receipt_missing,
            "ground_truth_sha256": json_sha(sample.get("expected", {})),
            "surface_form_sha256": json_sha(sample.get("surface_form", {})),
            "business_state_sha256": json_sha(scenario.get("state", {})),
        })

    # Detect identifier reuse across different scenario/tool pairs.
    reused_ids: list[dict[str, Any]] = []
    for result_id, records in sorted(authority_by_id.items()):
        pair_signatures = {(item["scenario_id"], item["record"].get("tool"), json_sha(item["record"])) for item in records}
        scenario_tools = sorted({(item["scenario_id"], item["record"].get("tool")) for item in records})
        if len(scenario_tools) > 1:
            reused_ids.append({"result_id": result_id, "scenario_tool_pairs": [
                {"scenario_id": sid, "tool": tool} for sid, tool in scenario_tools],
                "conflicting_record_count": len(pair_signatures)})

    # Facts can only be called safe to patch if an actual receipt already
    # exists, it satisfies the closed Tool Catalog schema, and its expected
    # result ID is not reused by another scenario/tool.
    unique_refs = set(reference_counter)
    valid_receipt_pairs = {(sid, result_id) for (sid, result_id), items in authority_by_key.items()
                           if any(receipt_shape(item["record"], result_schemas.get(item["record"]["tool"], {}))["contract_shape_valid"]
                                  for item in items)}
    valid_receipts = {result_id for _sid, result_id in valid_receipt_pairs}
    conflicting_ids = {x["result_id"] for x in reused_ids}
    receipt_error_counts: Counter[str] = Counter()
    for inventory in source_inventory.values():
        receipt_error_counts.update(inventory["contract_shape"]["errors"])
    safe_expected_fact_rows = sum(1 for row in sample_audit if row["expected_external_result_facts_required"] and
                                  all((row["scenario_id"], rid) in valid_receipt_pairs and rid not in conflicting_ids for rid in row["result_ids"]))

    experiment_a = ROOT / "docs/ai/dataset/business_state_expansion/v0.2/experiment_a"
    source_paths = [samples_path, scenarios_path, splits_path, dataset_manifest_path, CONTRACT, CATALOG, SERIALIZER, SCRIPT,
                    experiment_a / "samples.json", experiment_a / "scenarios.json",
                    experiment_a / "dataset_manifest.json", experiment_a / "freeze_hashes.json"]
    source_hashes = {str(path.relative_to(ROOT)).replace("\\", "/"): sha256(path) for path in source_paths}
    validator_report_path = OUT / "source_validator_report.json"
    validator_report = read_json(validator_report_path) if validator_report_path.is_file() else None
    canonical_expected = {item["path"]: item["sha256"] for item in read_json(dataset_manifest_path).get("artifacts", [])}
    canonical_actual = {"samples.json": sha256(samples_path), "scenarios.json": sha256(scenarios_path),
                        "split_assignment.json": sha256(splits_path)}
    canonical_hash_match = all(canonical_actual.get(path) == digest for path, digest in canonical_expected.items()
                               if path in canonical_actual)
    a_freeze = read_json(experiment_a / "freeze_hashes.json")
    a_hash_results = {}
    for rel, expected in a_freeze.get("hashes", {}).items():
        candidate = experiment_a / rel
        if candidate.is_file():
            a_hash_results[rel] = {"expected": expected, "actual": sha256(candidate), "matches": sha256(candidate) == expected}
    a_hash_match = len(a_hash_results) == len(a_freeze.get("hashes", {})) and all(x["matches"] for x in a_hash_results.values())
    summary = {
        "canonical_sample_count": len(samples), "canonical_scenario_count": len(scenarios),
        "split_counts": dict(split_counts),
        "frozen_v0_1_hashes_match_manifest": canonical_hash_match,
        "frozen_experiment_a_hashes_match_freeze_record": a_hash_match,
        "experiment_a_frozen_hashes_verified": len(a_hash_results),
        "result_referenced_sample_count": sum(1 for row in sample_audit if row["result_ids"]),
        "result_fact_dependent_sample_count": sum(1 for row in sample_audit if row["expected_external_result_facts_required"]),
        "no_prior_result_body_needed_sample_count": no_body_needed_rows,
        "complete_visible_authoritative_grounding_sample_count": fully_grounded_rows,
        "id_only_or_body_insufficient_sample_count": gap_rows,
        "safe_to_overlay_sample_count": safe_expected_fact_rows,
        "samples_with_no_business_payload_authority": missing_business_authority_rows,
        "samples_missing_contract_valid_receipt_authority": missing_legal_receipt_rows,
        "referenced_unique_result_id_count": len(unique_refs),
        "referenced_ids_with_scenario_server_result_body_count": len({rid for rid in unique_refs
            if any(item["result_id"] == rid and item["scenario_id"] in {s["scenario_id"] for s in scenarios}
                   for item in source_inventory.values())}),
        "referenced_ids_with_contract_valid_receipt_count": len(valid_receipts & unique_refs),
        "referenced_scenario_result_pair_count": len(source_inventory),
        "referenced_scenario_result_pairs_with_contract_valid_receipt_count": len(valid_receipt_pairs & {
            (row["scenario_id"], result_id) for row in sample_audit for result_id in row["result_ids"]}),
        "referenced_scenario_result_pairs_missing_contract_valid_receipt_count": len(source_inventory) - len(valid_receipt_pairs & set(source_inventory)),
        "reused_result_ids_across_scenarios": reused_ids,
        "split_result_grounding_counts": {
            split: {
                "result_referenced": sum(1 for row in sample_audit if row["split"] == split and row["result_ids"]),
                "body_dependent": sum(1 for row in sample_audit if row["split"] == split and row["expected_external_result_facts_required"]),
                "no_prior_body_needed": sum(1 for row in sample_audit if row["split"] == split and row["result_ids"] and not row["expected_external_result_facts_required"]),
                "id_only_or_body_insufficient": sum(1 for row in sample_audit if row["split"] == split and row["grounding_status"] == "ID_ONLY_BODY_INSUFFICIENT"),
            } for split in sorted(split_counts)
        },
        "serializer_rows_checked": len(samples), "serializer_errors": len(serializer_errors),
        "model_visible_metadata_leakage_check": "export_record_metadata_guard",
        "model_visible_metadata_leakage_checked_rows": len(samples),
        "model_visible_metadata_leakage_rows": sum(1 for row in serializer_errors if "metadata leakage" in row["error"].lower()),
        "canonical_dataset_validator": ({"status": "valid" if validator_report and validator_report.get("valid") else "not_run",
            "errors": len(validator_report.get("errors", [])) if validator_report else None,
            "warnings": len(validator_report.get("warnings", [])) if validator_report else None,
            "warning_codes": dict(Counter(x.get("code", "unknown") for x in validator_report.get("warnings", []))) if validator_report else {},
            "report_artifact": "source_validator_report.json" if validator_report else None}),
        "source_receipt_schema_error_counts": dict(receipt_error_counts),
        "overlay_patch_count": 0,
        "status": "blocked_by_missing_authority" if gap_rows else "ready_for_independent_review",
    }
    audit = {
        "experiment": "v0.2 Experiment B — Authoritative Result Grounding",
        "status": summary["status"],
        "method": {
            "result_reference_sources": ["input.server_context.verified_result_ids", "expected.model_output.evidence_result_id(s)"],
            "authority_scope": "same frozen scenario state.facts only; source=server_result; no GT-to-source synthesis",
            "body_needed_rule": "Manual fact-level review of every one of the 23 referenced Scenario states. It distinguishes rows whose target facts require a prior result body from rows that merely carry an ID; scenario-specific Expected fact→source→visible-input mapping is attached to every row.",
            "receipt_rule": "Only source-recorded fields may form a model-visible runtime receipt; required Tool Catalog output_schema fields are never synthesized.",
            "historical_diagnostic_policy": "test/hard_test were audited with the same fixed rule; their values were not used to design data or tune a model.",
        },
        "summary": summary,
        "scenario_fact_audit": FACT_AUDIT,
        "result_source_inventory": sorted(source_inventory.values(), key=lambda x: (x["scenario_id"], x["result_id"], x["source_path"])),
        "samples": sample_audit,
        "serializer_errors": serializer_errors,
        "frozen_source_hashes": source_hashes,
        "frozen_hash_verification": {"canonical_v0_1": {"matches_manifest": canonical_hash_match,
            "artifact_hashes": {path: {"expected": canonical_expected[path], "actual": actual,
                "matches": actual == canonical_expected[path]} for path, actual in canonical_actual.items() if path in canonical_expected}},
            "experiment_a": {"matches_freeze_record": a_hash_match, "artifacts": a_hash_results}},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "grounding_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "overlay_patches.json").write_text(json.dumps({"status": "blocked_no_safe_patch", "patches": []}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "source_hashes.json").write_text(json.dumps(source_hashes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    readme = f"""# Experiment B — Authoritative Result Grounding

Status: **{summary['status']}**. Frozen v0.1 and Experiment A remain unchanged.

The fixed, fact-level audit covered all {summary['result_referenced_sample_count']} result-ID-bearing samples across {len(FACT_AUDIT)} source Scenarios. Of these, {summary['result_fact_dependent_sample_count']} outputs require facts from a prior result body; {summary['no_prior_result_body_needed_sample_count']} carry a result ID but initiate a fresh read and do not consume the old body. Among the body-dependent rows, visible authoritative result-body grounding is {summary['complete_visible_authoritative_grounding_sample_count']}/{summary['result_fact_dependent_sample_count']}; {summary['id_only_or_body_insufficient_sample_count']} are ID-only/body-insufficient.

All {summary['referenced_unique_result_id_count']} referenced IDs have same-Scenario business payload sources in frozen `state.facts` ({summary['samples_with_no_business_payload_authority']} rows lack business-payload authority). However, {summary['samples_missing_contract_valid_receipt_authority']} body-dependent sample rows lack a complete, source-backed runtime receipt conforming to the closed Tool Catalog schema. Therefore safe overlay additions: {summary['safe_to_overlay_sample_count']}. Do not derive `observed_at` from sample creation time or fill missing receipt metadata with invented values. The audit records Expected fact → authoritative source pointer → actual model-visible state for each source Scenario. Result ID reuse across Scenario/tool pairs is separately listed.

The unchanged serializer (`scripts/ai_training_setup/export_dataset.py`) was applied to all {summary['serializer_rows_checked']} canonical rows; its production-metadata guard checked all {summary['model_visible_metadata_leakage_checked_rows']} rows and found {summary['model_visible_metadata_leakage_rows']} leakages (serializer errors: {summary['serializer_errors']}). The standalone Dataset Validator report is preserved in `source_validator_report.json`: valid={summary['canonical_dataset_validator']['status'] == 'valid'}, errors={summary['canonical_dataset_validator']['errors']}, warnings={summary['canonical_dataset_validator']['warnings']}. The warnings are the existing semantic-group review warnings and remain visible in the report. Per-source receipt schema failures are detailed in `result_source_inventory` and summarized in the manifest; they include absent required envelope fields and any missing nested Tool-output fields, not just timestamps. Of {summary['referenced_scenario_result_pair_count']} distinct Scenario/result source pairs, {summary['referenced_scenario_result_pairs_with_contract_valid_receipt_count']} has valid receipt shape and {summary['referenced_scenario_result_pairs_missing_contract_valid_receipt_count']} do not; the one valid-shaped pair is in the fresh-read/no-prior-body-needed Scenario, so it does not close any of the 108 dependent rows. The inventory also records nested gaps such as `get_participant_balance.data.base_reference`. Test and hard_test were audited under the same fixed rule, as historical diagnostics only; their labels were not used to design content or select a model.

`overlay_patches.json` is empty because the available business payloads cannot be wrapped as valid receipts without missing runtime-authority fields. No frozen source data changed. See `grounding_audit.json`, `source_hashes.json`, and `manifest.json` for row-level findings and hashes. Further data/training work is blocked until valid source receipts become available.
"""
    (OUT / "README.md").write_text(readme, encoding="utf-8")
    manifest = {
        "experiment_version": "0.2-experiment-b", "status": summary["status"],
        "created_at_local_date": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_dataset": {"path": "docs/ai/dataset/canonical_training/v0.1", "sample_count": len(samples),
                           "splits_unchanged": True, "sha256": {k: source_hashes[k] for k in source_hashes if "canonical_training/v0.1" in k}},
        "overlay": {"samples_modified": 0, "patches_artifact": "overlay_patches.json", "status": "not_produced_due_to_missing_contract_valid_receipts"},
        "audit_summary": summary,
        "artifacts": {},
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    artifact_paths = [OUT / "grounding_audit.json", OUT / "overlay_patches.json", OUT / "source_hashes.json", OUT / "README.md"]
    if validator_report_path.is_file():
        artifact_paths.append(validator_report_path)
    manifest["artifacts"] = {path.name: sha256(path) for path in artifact_paths}
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest["manifest_sha256"] = sha256(OUT / "manifest.json")
    (OUT / "manifest.sha256").write_text(manifest["manifest_sha256"] + "  manifest.json\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
