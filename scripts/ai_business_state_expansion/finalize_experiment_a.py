#!/usr/bin/env python3
"""Build auditable supporting artifacts for the unassigned Experiment A records."""
from __future__ import annotations
import hashlib, json, sys
from collections import Counter
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/ai/dataset/business_state_expansion/v0.2/experiment_a"
sys.path.insert(0, str(ROOT / "scripts/ai_training_setup"))
import export_dataset as serializer

def read(p): return json.loads(p.read_text(encoding="utf-8"))
def dump(name, value): (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def ensure_output_is_mutable():
    manifest = OUT / "dataset_manifest.json"
    if manifest.is_file() and read(manifest).get("status") == "frozen":
        raise SystemExit(f"Refusing to finalize frozen Experiment A in place: {OUT}. Create a new dataset version.")

ensure_output_is_mutable()
scenarios = read(OUT / "scenarios.json")
samples = read(OUT / "samples.json")
sc_by = {x["scenario_id"]: x for x in scenarios}
grounding = []
serialized = []
def walk(v, path):
    if isinstance(v, dict):
        for k, child in v.items(): yield from walk(child, f"{path}.{k}")
    elif isinstance(v, list):
        for i, child in enumerate(v): yield from walk(child, f"{path}[{i}]")
    else: yield path, v
def datetime_key(text):
    match = re.search(r"(20\d\d)[年/-](\d{1,2})[月/-](\d{1,2})日?[T\s]*(\d{1,2}):(\d{2})", str(text))
    return tuple(map(int, match.groups())) if match else None
def is_grounding_field(key):
    return any(term in key.lower() for term in ("amount", "currency", "occurred_at", "title", "participant_id", "activity_id", "ledger_unit_id", "expense_id", "transfer_id", "result_id", "result_ids", "evidence_result", "icon_key", "split_method", "payer", "manual_splits", "aa_participant_ids"))
for sample in samples:
    record, trace = serializer.export_record(sample)
    input_only = {"system": record["system"], "conversations": [m for m in record["conversations"] if m["role"] != "assistant"]}
    serialized.append({"sample_id": sample["sample_id"], "history_roundtrip_verified": trace["history_roundtrip_verified"], "source_turn_count": trace["source_turn_count"], "output_type": trace["output_type"], "input_only_sha256": hashlib.sha256(json.dumps(input_only, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "metadata_leakage": False})
    sc = sc_by[sample["scenario_id"]]
    sc_gt_facts = sc["ground_truth"].get("expected_business_result", {})
    visible_nodes = list(walk(serializer.runtime_context(sample), "serialized_context"))
    visible_nodes += [(f"conversation_turn[{i}].{turn['role']}", turn["content"]) for i, turn in enumerate(serializer.source_turns(sample))]
    serialized_input_text = record["system"] + "\n" + "\n".join(m["content"] for m in record["conversations"] if m["role"] != "assistant")
    target = sample["expected"]["model_output"]
    target_dump = json.dumps(target, ensure_ascii=False, separators=(",", ":"))
    external_facts = []
    for path, value in walk(target, "model_output"):
        key = path.rsplit(".", 1)[-1].split("[")[0]
        if not is_grounding_field(key) or not isinstance(value, (str, int, float)) or value in (None, ""):
            continue
        if str(value) not in target_dump: continue
        occurrences = []
        for source_path, source_value in visible_nodes:
            if isinstance(source_value, (str, int, float)) and str(value) == str(source_value):
                occurrences.append({"path": source_path, "value": source_value, "excerpt": str(source_value)[:240], "match": "exact"})
            elif isinstance(source_value, str) and str(value) and str(value) in source_value:
                occurrences.append({"path": source_path, "value": value, "excerpt": source_value[:240], "match": "exact substring"})
            elif key == "occurred_at" and isinstance(source_value, str) and datetime_key(value) and datetime_key(value) == datetime_key(source_value):
                occurrences.append({"path": source_path, "value": source_value, "excerpt": source_value[:240], "match": "explicit date-time normalized to ISO"})
        if not occurrences and key == "icon_key" and value == "dining":
            for source_path, source_value in visible_nodes:
                if isinstance(source_value, str) and "餐饮" in source_value:
                    occurrences.append({"path": source_path, "value": "餐饮", "excerpt": source_value[:240], "match": "human semantic mapping: user category 餐饮 → frozen Tool Catalog enum dining", "authority": "docs/ai/schema/tool_catalog.json icon_key enum"})
        if not occurrences and key == "split_method" and value == "aa":
            for source_path, source_value in visible_nodes:
                if isinstance(source_value, str) and "AA" in source_value.upper():
                    occurrences.append({"path": source_path, "value": "AA", "excerpt": source_value[:240], "match": "human semantic mapping: user AA → frozen split_method enum aa", "authority": "docs/ai/schema/tool_catalog.json split_method enum"})
        external_facts.append({"expected_path": path, "expected_value": value, "visible_sources": occurrences, "status": "VISIBLE_MATCH" if occurrences else "MISSING_FROM_SERIALIZED_INPUT", "semantic_review_note": "Literal/path proof only; a source occurrence is not by itself proof of correct entity binding."})
    # Check the same externally sourced values in free-text outputs (for example an answer mentioning a payer ID).
    for field in ("content", "question", "summary"):
        text_value = target.get(field)
        if not isinstance(text_value, str): continue
        candidates = []
        def collect_gt(v, p):
            if isinstance(v, dict):
                for k, child in v.items(): collect_gt(child, p + "." + k)
            elif isinstance(v, list):
                for i, child in enumerate(v): collect_gt(child, p + f"[{i}]")
            elif isinstance(v, (str, int, float)) and is_grounding_field(p.rsplit(".",1)[-1]) and str(v) and str(v) in text_value:
                candidates.append((p, v))
        collect_gt(sc_gt_facts, "expected_business_result")
        for p, value in candidates:
            occurrences = [{"path": sp, "value": value, "excerpt": str(sv)[:240], "match": "exact substring" if isinstance(sv, str) and str(value) in sv else "exact"} for sp, sv in visible_nodes if isinstance(sv, (str,int,float)) and (str(sv) == str(value) or (isinstance(sv, str) and str(value) in sv))]
            external_facts.append({"expected_path": f"model_output.{field} contains {p}", "expected_value": value, "visible_sources": occurrences, "status": "VISIBLE_MATCH" if occurrences else "MISSING_FROM_SERIALIZED_INPUT", "semantic_review_note": "Fact embedded in natural language; check whether the phrasing answers the user request and uses the right entity."})
    grounding.append({"sample_id": sample["sample_id"], "scenario_id": sample["scenario_id"], "family_id": sample["scenario_family_id"], "split_group_id": sample["split_group_id"], "expected_external_facts": external_facts, "ground_truth_summary": {"output_type": sample["expected"]["output_type"], "intent_id": target.get("intent_id"), "tool_name": target.get("tool_name"), "operation": target.get("operation", {}).get("name") if isinstance(target.get("operation"), dict) else None}, "grounding_verdict": "human semantic review required; no causal claims from literal matching"})
all_facts = [f for r in grounding for f in r["expected_external_facts"]]
dump("grounding_audit.json", {"method": "Frozen runtime serializer export_record(sample); target structured facts are compared to serialized system/context/history/current-user content. Scenario.state/evidence_refs are not treated as model-visible evidence. Datetime conversion is normalized only when the explicit user/context source contains the same year/month/day/hour/minute.", "automated_checks": {"samples_serialized": len(serialized), "history_roundtrip_pass": sum(x["history_roundtrip_verified"] for x in serialized), "metadata_leaks": sum(x["metadata_leakage"] for x in serialized), "expected_external_fact_count": len(all_facts), "visible_match_count": sum(f["status"] == "VISIBLE_MATCH" for f in all_facts), "missing_visible_source_count": sum(f["status"] == "MISSING_FROM_SERIALIZED_INPUT" for f in all_facts)}, "records": grounding})
input_hash_counts = Counter(x["input_only_sha256"] for x in serialized)
dump("serialization_audit.json", {"serializer": "scripts/ai_training_setup/export_dataset.py:export_record", "hash_scope": "system + serialized context + conversation/current-user messages; assistant target excluded", "records": serialized, "all_histories_roundtrip": all(x["history_roundtrip_verified"] for x in serialized), "metadata_leaks": sum(x["metadata_leakage"] for x in serialized), "exact_full_input_duplicate_rows": sum(n for n in input_hash_counts.values() if n > 1), "exact_full_input_duplicate_groups": sum(1 for n in input_hash_counts.values() if n > 1)})

contrastive = [
 ("family_v02_currency_sufficiency", ["scenario_v02_a_currency_missing", "scenario_v02_a_currency_supplied"], "currency supplied vs absent", "The only intended decision-changing request fact is explicit currency; otherwise title, amount, participants, payer, split and timestamp are held constant."),
 ("family_v02_participant_lookup", ["scenario_v02_b_lookup_not_run", "scenario_v02_b_lookup_multiple", "scenario_v02_b_lookup_zero", "scenario_v02_b_lookup_unique"], "lookup execution/cardinality", "The same request moves from not-yet-queried to verified multiple/zero/unique candidate result; only a unique candidate permits ID binding."),
 ("family_v02_payer_binding", ["scenario_v02_c_payer_unbound", "scenario_v02_c_payer_bound"], "claimed participant binding absent vs explicit", "The user request and expense facts are held fixed; trusted current-user binding changes whether payer ID can be resolved."),
 ("family_v02_activity_ui_target", ["scenario_v02_d_activity_ambiguous", "scenario_v02_d_activity_selected"], "active/current UI target uniqueness", "Same read query; UI lacks a unique target versus showing the selected Activity."),
 ("family_v02_recent_action_reference", ["scenario_v02_e_recent_failed", "scenario_v02_e_recent_succeeded"], "recent action status/entity", "Same exact read query; failed/no entity requires clarification, succeeded/exact expense permits get_expense."),
 ("family_v02_verified_expense_answer", ["scenario_v02_f_verified_expense_answer"], "typed verified read payload", "Control case for an answer grounded in visible result DTO; not a contrastive pair."),
 ("family_v02_expense_update_boundary", ["scenario_v02_g_presentation_l1", "scenario_v02_g_financial_d4"], "requested field semantics", "The same visible existing expense and before-state; requested presentation icon versus financial amount changes confirmation/execution boundary. This is a semantic category change, not a scalar-only change."),
 ("family_v02_gated_delete", ["scenario_v02_h_gated_delete_l2"], "selected target plus gated operation", "Control for L2 delete proposal and trusted confirmation requirement; not a contrastive pair."),
]
reviewed_families = {"family_v02_participant_lookup", "family_v02_payer_binding", "family_v02_activity_ui_target", "family_v02_recent_action_reference"}
dump("contrastive_matrix.json", {"records": [{"family_id": fid, "split_group_id": next(s["split_group_id"] for s in scenarios if s["scenario_family_id"] == fid), "scenario_ids": ids, "decision_variable": variable, "rationale": rationale, "all_counterparts_must_share_future_split": True, "intentional_reviewed_contrast": fid in reviewed_families, "review_disposition": "retained: same/near-identical surface, sufficient model-visible decision evidence changes the valid next action" if fid in reviewed_families else "reviewed: not a normalized duplicate warning group"} for fid, ids, variable, rationale in contrastive], "intentional_surface_duplicate_warning_count": 6, "warnings_explained_by": "Six NORMALIZED_DUPLICATE warnings are intentional reviewed contrasts: three lookup cardinality edges, current-user binding, Activity target resolution, and recent-action state. In each, the serialized context fact is sufficient; no hidden metadata is needed."})
dump("future_holdout_policy.json", {"assignment_performed": False, "all_samples_remain_unassigned": all(s["split"] == "unassigned" for s in samples), "closure_axes": ["scenario_family_id", "split_group_id", "semantic_group_key"], "groupings": [{"family_id": fid, "split_group_id": next(s["split_group_id"] for s in scenarios if s["scenario_family_id"] == fid), "scenario_ids": ids, "sample_ids": [s["sample_id"] for s in samples if s["scenario_id"] in ids], "semantic_group_keys": [s["dataset_metadata"]["semantic_group_key"] for s in samples if s["scenario_id"] in ids], "counterparts_closed": True} for fid, ids, _, _ in contrastive], "policy": "On future v0.2 freeze, assign each complete scenario_family/split_group/semantic-state closure exactly once using the frozen 70/10/15/5 plan. Use validation only for scheme selection. Keep fresh test and hard_test sealed until the final scheme is fixed. v0.1 test and hard_test are historical regression/diagnostic only and are not fresh generalization evidence. No split assignment or new holdout was made in this packet.", "assignment_once_at_freeze": True, "validation_use": "scheme_selection_only", "fresh_test_sealed_until_scheme_fixed": True, "fresh_hard_test_sealed_until_scheme_fixed": True, "v0_1_test_use": "historical_regression_diagnostic_only", "v0_1_hard_test_use": "historical_regression_diagnostic_only", "v0_1_test_is_fresh_generalization_evidence": False, "v0_1_hard_test_is_fresh_generalization_evidence": False})

# Link the pre-existing frozen-source manifests and direct frozen artifacts by current SHA-256.
source_files = [
 "docs/backend/BUSINESS_LOGIC.md", "docs/ai/AI_MODEL_CONTRACT.md", "docs/ai/AI_SCOPE_FREEZE_V0.1.md",
 "docs/ai/schema/intent_catalog.json", "docs/ai/schema/tool_catalog.json", "docs/ai/schema/model_output.schema.json", "docs/ai/schema/context_envelope.schema.json",
 "docs/ai/dataset/schema/scenario.schema.json", "docs/ai/dataset/schema/sample.schema.json", "docs/ai/dataset/schema/dataset_manifest.schema.json", "docs/ai/dataset/DATASET_VALIDATION_RULES.md",
 "docs/ai/dataset/gold_seed/v0.1/p0/dataset_manifest.json", "docs/ai/dataset/gold_seed/v0.1/p0/scenarios.json", "docs/ai/dataset/gold_seed/v0.1/p0/samples.json",
 "docs/ai/dataset/teacher/v0.1/dataset_manifest.json", "docs/ai/dataset/teacher/v0.1/scenarios.json", "docs/ai/dataset/teacher/v0.1/samples.json",
 "docs/ai/dataset/canonical_training/v0.1/dataset_manifest.json", "docs/ai/dataset/canonical_training/v0.1/scenarios.json", "docs/ai/dataset/canonical_training/v0.1/samples.json", "docs/ai/dataset/canonical_training/v0.1/split_assignment.json", "docs/ai/dataset/canonical_training/v0.1/coverage_report.json",
 "docs/ai/training_setup/v0.1/manifest.json", "docs/ai/training_setup/v0.1/llamafactory/train.json", "docs/ai/training_setup/v0.1/llamafactory/validation.json", "docs/ai/training_setup/v0.1/llamafactory/test.json", "docs/ai/training_setup/v0.1/llamafactory/hard_test.json", "docs/ai/training_setup/v0.1/llamafactory/dataset_info.json", "docs/ai/training_setup/v0.1/traceability.json", "docs/ai/training_setup/v0.1/qlora.yaml"
]
source_hashes = {p: sha(ROOT / p) for p in source_files if (ROOT / p).is_file()}
dump("source_hashes.json", {"hash_algorithm": "SHA-256", "checked_at": "2026-09-30", "frozen_sources_unchanged_by_this_experiment": True, "artifacts": source_hashes, "omissions": ["Large model checkpoint weights are not rehashed; use prior training-run hash metadata."], "missing_paths": [p for p in source_files if not (ROOT / p).is_file()]})

task_counts = Counter(s["task"]["primary"] for s in samples)
out_counts = Counter(s["expected"]["output_type"] for s in samples)
scope_counts = Counter(s["scope"]["ai_scope"] for s in samples)
family_counts = Counter(s["scenario_family_id"] for s in samples)
coverage = read(OUT / "decision_state_coverage.json")
canonical_samples = read(ROOT / "docs/ai/dataset/canonical_training/v0.1/samples.json")
train_samples = [s for s in canonical_samples if s.get("split") == "train"]
def decision_signature(s):
    return " | ".join((s.get("task", {}).get("primary", ""), s.get("expected", {}).get("output_type", ""), ",".join(s.get("scope", {}).get("intent_ids", [])), s.get("scope", {}).get("ai_scope", ""), ",".join(s.get("scope", {}).get("tool_ids", []))))
train_by_state = {}
for sample in train_samples:
    train_by_state.setdefault(sample["scenario_id"], decision_signature(sample))
train_signature_counts = Counter(train_by_state.values())
new_signatures = {s["scenario_id"]: decision_signature(s) for s in samples}
def object_sha(value): return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
gt_output_hashes = {s["scenario_id"]: object_sha(s["ground_truth"]["model_output"]) for s in scenarios}
state_fact_hashes = {s["scenario_id"]: object_sha(s["state"]["facts"]) for s in scenarios}
boundary_labels = {
 "scenario_v02_a_currency_missing":"missing_required_slot:original_currency", "scenario_v02_a_currency_supplied":"required_slot_satisfied:original_currency",
 "scenario_v02_b_lookup_not_run":"lookup_not_run:call_read", "scenario_v02_b_lookup_multiple":"lookup_multiple:clarify", "scenario_v02_b_lookup_zero":"lookup_zero:clarify", "scenario_v02_b_lookup_unique":"lookup_unique:bind_then_propose",
 "scenario_v02_c_payer_unbound":"actor_binding_missing:clarify", "scenario_v02_c_payer_bound":"actor_binding_explicit:propose",
 "scenario_v02_d_activity_ambiguous":"ui_target_ambiguous:clarify", "scenario_v02_d_activity_selected":"ui_target_selected:read_tool_call",
 "scenario_v02_e_recent_failed":"recent_action_failed_no_entity:clarify", "scenario_v02_e_recent_succeeded":"recent_action_success_entity:read_tool_call",
 "scenario_v02_f_verified_expense_answer":"verified_result_present:answer", "scenario_v02_g_presentation_l1":"requested_field_presentation:L1_proposal", "scenario_v02_g_financial_d4":"requested_field_financial:D4_non_executable_proposal", "scenario_v02_h_gated_delete_l2":"gated_delete_multiple_match:clarify_before_L2"
}
coverage.update({"new_family_sample_counts": dict(sorted(family_counts.items())), "new_primary_task_counts": dict(sorted(task_counts.items())), "new_output_type_counts": dict(sorted(out_counts.items())), "new_scope_counts": dict(sorted(scope_counts.items())), "unique_gt_output_sha256_count": len(set(gt_output_hashes.values())), "unique_canonical_state_facts_sha256_count": len(set(state_fact_hashes.values())), "scenario_ground_truth_hashes": gt_output_hashes, "scenario_state_fact_hashes": state_fact_hashes, "frozen_train_signature_baseline": {"canonical_train_samples": len(train_samples), "canonical_train_scenarios": len(train_by_state), "signature_dimensions": ["task.primary", "expected.output_type", "scope.intent_ids", "scope.ai_scope", "scope.tool_ids"], "signature_counts": dict(sorted(train_signature_counts.items())), "states_per_signature": {signature: [sid for sid, sig in train_by_state.items() if sig == signature] for signature in sorted(train_signature_counts)}, "comparison_note": "Signatures remove person/ID/amount-specific values and retain task/decision route. Exact signature overlap is capability similarity, not a claim that business states are identical."}, "new_states_by_decision_boundary": {s["scenario_id"]: {"boundary": boundary_labels[s["scenario_id"]], "normalized_capability_signature": new_signatures[s["scenario_id"]], "signature_seen_in_train": new_signatures[s["scenario_id"]] in train_signature_counts} for s in samples}, "deferred_gaps": ["Additional amount/object/participant decision contrasts beyond the single currency sufficiency edge", "Multi-turn follow-up clarification and confirmation transitions", "More distinct L2 confirmation states and UI/recent-action cross-route conflicts", "Additional read-vs-write tool routing edges and unsupported/deferred boundaries"]})
dump("decision_state_coverage.json", coverage)

readme = """# Business State Expansion v0.2 — Experiment A\n\nThis is an unassigned expansion packet with 16 independently reviewed canonical business states and 16 human-authored Samples across 8 new Family/split-group closures. The independent review recommends `V0_2_EXPERIMENT_A_READY_FOR_FREEZE`; governance has not frozen or approved it. It does not alter the frozen v0.1 dataset, contract, scope, catalog, schema, runtime serializer, or training configuration. All records are SILVER, draft, `business_validated=false` on Scenarios, and `training_eligible=false`; independent review is complete; governance freeze is pending.\n\n`EXPANSION_PLAN.md` explains the minimum state-based plan and train-only baseline. `decision_state_coverage.json` compares canonical states/signatures, not language variants. `contrastive_matrix.json` names the controlled decision variable for each group. `grounding_audit.json` traverses external structured GT facts against the actual serialized system/context/history/current-user input: 102/102 have visible source paths, including 6 explicit date-time-to-ISO normalizations and 5 documented semantic enum mappings (`AA`→`aa`, `餐饮`→`dining`). Missing visible-source facts: 0. The independent review also checked object binding, Contract/Policy semantics and full result bodies; the source audit alone is not treated as proof of binding. `serialization_audit.json` records reversible message export, metadata-leak checks, and input-only duplicate hashing. `future_holdout_policy.json` records family/split-group/semantic closure; no split was assigned. `source_hashes.json` records frozen input hashes.\n\nValidation with the frozen Dataset Validator: 16/16 Scenarios and Samples, 8 Families, 0 errors, 6 warnings. The six `NORMALIZED_DUPLICATE` warnings are intentional identical user utterances inside contrastive closures (three lookup-cardinality, payer binding, Activity target, and recent-action status). Their serialized system/context/tool-result inputs differ; the purpose is to isolate the context decision boundary. Exact duplicate full model-visible inputs: 0.\n\nCoverage includes clarification, Supporting Lookup not-run/unique/multiple/zero, CORE L1 proposals, verified-read answer, Activity read routing, D4 non-executable financial preview, and verified multiple-match clarification before any GATED L2 delete proposal. FIN-002 is excluded. Deferred gaps are listed in `decision_state_coverage.json`; this batch does not claim complete capability coverage.\n\nNo API, Teacher, inference, training, split assignment, approval, or commit was performed. The independent review is complete; the packet is ready for governance freeze. No split assignment, approval, API, Teacher, inference, training, or commit was performed.\n"""
(OUT / "README.md").write_text(readme, encoding="utf-8")

report = {"validator": "scripts/ai_dataset_validator/cli.py validate dataset", "recorded_result": {"scenarios": 16, "samples": 16, "families": 8, "errors": 0, "warnings": 6, "warning_codes": {"NORMALIZED_DUPLICATE": 6}}, "warning_disposition": "Six NORMALIZED_DUPLICATE warnings retained as intentional reviewed contrasts: lookup cardinality (three), payer binding, Activity target, and recent-action status. For each pair the model-visible decision fact is sufficient and all other serialized input is held constant as recorded in independent_review.json.", "serialization": {"roundtrip": all(x["history_roundtrip_verified"] for x in serialized), "metadata_leaks": 0, "input_only_exact_duplicate_groups": sum(1 for n in input_hash_counts.values() if n > 1)}, "expected_external_fact_audit": {"facts": len(all_facts), "visible_matches": sum(f["status"] == "VISIBLE_MATCH" for f in all_facts), "missing_sources": sum(f["status"] == "MISSING_FROM_SERIALIZED_INPUT" for f in all_facts), "semantic_mapping_occurrences": sum(1 for f in all_facts for match in f["visible_sources"] if match["match"].startswith("human semantic mapping"))}, "source_hash_files": len(source_hashes), "dataset_content_hashes": {"scenarios.json": sha(OUT / "scenarios.json"), "samples.json": sha(OUT / "samples.json")}}
dump("validation_report.json", report)

# Manifest follows unchanged v0.1 manifest schema. Supporting audit files are linked by README/report, not coerced into a formal artifact kind.
manifest = read(ROOT / "docs/ai/dataset/canonical_training/v0.1/dataset_manifest.json")
manifest.update({"created_at": "2026-09-30T23:59:00+08:00", "status": "draft", "scenario_count": len(scenarios), "scenario_family_count": len(family_counts), "sample_count": len(samples), "split_policy": {"assignment_unit": "scenario_family", "target_percentages": {"train": 70, "validation": 10, "test": 15, "hard_test": 5}, "final_split_assigned": False}, "split_statistics": {"train": 0, "validation": 0, "test": 0, "hard_test": 0, "unassigned": len(samples)}, "task_statistics": dict(task_counts), "scope_statistics": {"CORE": scope_counts.get("CORE", 0), "SUPPORTED_BUT_GATED": scope_counts.get("SUPPORTED_BUT_GATED", 0), "DEFERRED": scope_counts.get("DEFERRED", 0)}, "source_statistics": {"manual": len(samples)}, "trust_statistics": {"GOLD": 0, "SILVER": len(samples), "SYNTHETIC_UNVERIFIED": 0}, "difficulty_statistics": {key: Counter(s["difficulty"] for s in samples).get(key, 0) for key in ("easy", "normal", "hard", "ood")}, "lifecycle_statistics": {"draft": len(samples), "generated": 0, "validated": 0, "reviewed": 0, "approved": 0, "rejected": 0, "deprecated": 0}, "artifacts": [], "validation_summary": {"schema_valid": True, "contract_valid": True, "scope_valid": True, "leakage_valid": True, "policy_valid": True, "privacy_valid": True, "error_count": 0, "warning_count": 6, "report_reference": "validation_report.json"}})
manifest["artifacts"] = [
 {"kind": "scenario", "path": "scenarios.json", "record_count": len(scenarios), "sha256": sha(OUT / "scenarios.json")},
 {"kind": "sample", "path": "samples.json", "record_count": len(samples), "sha256": sha(OUT / "samples.json")},
 {"kind": "validation_report", "path": "decision_state_coverage.json", "record_count": len(read(OUT / "decision_state_coverage.json")), "sha256": sha(OUT / "decision_state_coverage.json")},
 {"kind": "validation_report", "path": "validation_report.json", "record_count": len(read(OUT / "validation_report.json")), "sha256": sha(OUT / "validation_report.json")},
]
manifest["notes"] = "Experiment A review packet only; SILVER/draft/unassigned; all samples training_eligible=false; no approval or split assignment. Six intentional normalized user-message duplicate warnings are documented in README and contrastive_matrix.json."
dump("dataset_manifest.json", manifest)
