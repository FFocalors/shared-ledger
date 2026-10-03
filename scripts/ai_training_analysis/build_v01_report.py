#!/usr/bin/env python3
"""Build the human-readable v0.1 training failure analysis from saved artifacts only."""
from __future__ import annotations

import json
import hashlib
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/ai/training_analysis/v0.1"
CANONICAL = ROOT / "docs/ai/dataset/canonical_training/v0.1"
RUN = Path(r"D:\AI\runs\shared-ledger\training_runs\qlora-v0.1\20260930-143013")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    samples = read(CANONICAL / "samples.json")
    by_id = {x["sample_id"]: x for x in samples}
    scenario_by_id = {x["scenario_id"]: x for x in read(CANONICAL / "scenarios.json")}
    fail = read(OUT / "failure_matrix.json")
    coverage = read(OUT / "train_heldout_coverage.json")
    trajectory = read(OUT / "checkpoint_trajectory.json")
    confusion = read(OUT / "output_routing_confusion.json")
    grounding = read(OUT / "grounding_field_trace.json")["fields"]
    complexity = read(OUT / "complexity_and_context.json")
    token_counts = read(OUT / "tokenizer_counts.json")
    baseline_hashes = read(RUN / "final_source_hash_check.json")["files"]
    integrity = [{"path": row["path"], "baseline_sha256": row["expected_sha256"],
                  "current_sha256": hashlib.sha256((ROOT / Path(row["path"])).read_bytes()).hexdigest(),
                  "matches_baseline": hashlib.sha256((ROOT / Path(row["path"])).read_bytes()).hexdigest() == row["expected_sha256"]}
                 for row in baseline_hashes]
    write(OUT / "source_integrity_check.json", {"baseline_report": "D:/AI/runs/shared-ledger/training_runs/qlora-v0.1/20260930-143013/final_source_hash_check.json",
          "checked_at": "2026-09-30", "files_checked": len(integrity), "unchanged": sum(x["matches_baseline"] for x in integrity),
          "changed": [x["path"] for x in integrity if not x["matches_baseline"]], "files": integrity})

    # Deterministic, source-backed semantic case review. No inference is performed.
    case_notes = {
        "sample_gs_p0_028": {
            "kind": "UI-bound read tool routing",
            "assessment": "The activity id and enabled get_debt tool are model-visible; the output preserves the activity id but emits the wrong intent and adds unsupported ledger_unit_id/participant_id arguments plus undeclared fields. This supports routing/contract mismatch, not missing-id evidence.",
            "confidence": "high for visible id and structural mismatch; no causal claim about attention",
        },
        "sample_gs_p0_027": {
            "kind": "UI-bound activity query",
            "assessment": "The activity id and enabled get_activity_context tool are visible and copied correctly. The output routes through query_recent_entries instead of query_activity and adds limit/order/reason fields. Source value is available; intent/tool argument compatibility is the observed failure.",
            "confidence": "high for visible id and structural mismatch; no causal claim about attention",
        },
        "sample_gs_p0_032": {
            "kind": "verified result IDs without result payload",
            "assessment": "The user asks for the debt/prepayment balances without stating amounts. verified_result_ids contains the balance and prepayment result identifiers, but tool_results is empty and the compact visible UI/context contains neither 0.01 JPY nor 20 CNY. Expected answer requires those amounts; model instead states 15.00 and 0.00. The concrete gap is that result identifiers are serialized without the result DTO values needed to answer.",
            "confidence": "high for absence of the expected amounts from the serialized sample input; this is a data representation gap, not a claim about general model behavior",
        },
        "sample_gs_p0_092": {
            "kind": "business rule result id without rule payload",
            "assessment": "The user asks whether an archived activity can receive expenses. lookup_business_rule and result-rule-008-verified are visible, but tool_results is empty and the archived-activity rule text is absent from model-visible context/messages. Expected answer requires the creator-only unarchive rule; actual output adds an unsupported admin create/recreate alternative. The scenario evidence reference is not part of the serialized model input.",
            "confidence": "high for visible fields and serialized payload absence; source policy itself is supported by the frozen expected contract/evidence and not inferred from an ID",
        },
        "sample_gs_p0_005": {
            "kind": "expense proposal versus stale clarification vocabulary",
            "assessment": "The user supplies the date/time, expense title, amount, self-payment and self-only allocation; the activity/ledger ids, claimed participant, and enabled create_expense tool are visible. Expected output binds the current participant and creates a manual-split proposal. Actual output asks for account_id, a field absent from this frozen operation contract. This points to output-vocabulary/routing mismatch rather than absent core input facts.",
            "confidence": "high for visible values and expected/actual structure; account ownership semantics are interpreted from this canonical scenario, not independently inferred",
        },
    }
    cases = []
    records = {x["sample_id"]: x for x in read_jsonl(RUN / "eval/checkpoint-22-validation/records.jsonl")}
    records.update({x["sample_id"]: x for x in read_jsonl(RUN / "eval/best-checkpoint-22-test-hard/records.jsonl")})
    for sid, note in case_notes.items():
        sample = by_id[sid]
        scenario = scenario_by_id[sample["scenario_id"]]
        rec = records[sid]
        inp = sample["input"]
        cases.append({
            "sample_id": sid, "scenario_id": sample["scenario_id"], "family_id": sample["scenario_family_id"],
            "split": sample["split"], "expected_type": sample["expected"]["output_type"],
            "user_message": sample["surface_form"].get("user_message"),
            "history": sample["surface_form"].get("conversation", []),
            "ui_context": inp.get("ui_context"), "claimed_participant_id": inp.get("user_context", {}).get("claimed_participant_id"),
            "enabled_tools": inp.get("server_context", {}).get("enabled_tools", []),
            "verified_result_ids": inp.get("server_context", {}).get("verified_result_ids", []),
            "tool_results": inp.get("server_context", {}).get("tool_results", []),
            "expected_model_output": sample["expected"]["model_output"], "actual_model_output": rec.get("parsed_output"),
            "evidence_refs_not_model_visible": scenario.get("evidence_refs", []),
            **note,
        })
    write(OUT / "grounding_case_reviews.json", {
        "method": "Manual semantic review of five saved best-checkpoint rows against the exact serialized runtime input, frozen expected output, and cited scenario evidence; no inference performed.",
        "limits": ["A literal substring is not proof of correct semantic binding.", "No literal match is not proof that a fact is absent: normalization, derivation, or implicit binding may apply.", "Scenario evidence_refs and hidden scenario.state are not assumed to be model-visible.", "No claim is made about attention or causal use of a visible field."],
        "cases": cases,
    })

    # Explicit evidence/hypothesis/change/validation matrix. Recommendations only;
    # this analysis does not modify frozen v0.1 data or model artifacts.
    root_causes = [
        {"area": "data / runtime evidence", "evidence": "sample_gs_p0_032 has verified result IDs but empty tool_results; expected amounts are absent from user/history/UI/context and answer amounts are wrong. sample_gs_p0_092 similarly has a verified policy result ID but no visible policy payload.", "hypothesis": "IDs alone do not expose enough numerical or policy content for grounded answers in these rows.", "proposed_change": "In a new dataset version, serialize a sanitized, authoritative verified-result payload (or explicitly route to a read tool before answering) and keep the result ID-to-payload binding deterministic.", "validation": "Hold contract/model/config fixed; validation-only tests must verify source payload visibility, correct citation, exact amount/policy fact, and zero invented alternatives.", "evidence_strength": "high for these two serialized rows; scope/generalization requires new cases"},
        {"area": "data / state diversity", "evidence": "Train has 171 rows but only 36 canonical scenarios, 36 exact GTs and 36 state hashes; 106 rows are Teacher surface variants preserving those exact GTs. Heldout has 73 rows/16 canonical states and family isolation gives zero same-family train rows by policy.", "hypothesis": "Surface variety improves wording exposure but cannot add new decision-state coverage; transfer relies on related capability peers.", "proposed_change": "Prioritize additional canonical business states for weak decisions (tool routing, required-field resolution, guarded proposal and rule/result grounding), not more same-GT paraphrases alone.", "validation": "Preserve family/split-group isolation; compare capability peers and newly sealed families using predeclared row-level safety and structured fact metrics.", "evidence_strength": "high for exact source counts; causal performance impact is unproven"},
        {"area": "representation / contract guidance", "evidence": "sample_gs_p0_028 and _027 show visible IDs/tools copied into actual calls, but wrong intent/extra args; sample_gs_p0_005 has required user values and create_expense enabled but asks for account_id absent from operation schema.", "hypothesis": "The current serialized examples/system guidance may not sufficiently distinguish allowed intent-tool-argument combinations and current-user entity binding from legacy vocabulary.", "proposed_change": "Test a concise schema-grounded serialization/system guidance revision in a new version, without changing frozen business semantics or output schema.", "validation": "One-factor prompt/representation ablation; score the same validation capability slices and require schema/tool mapping and entity correctness without worsening proposal safety.", "evidence_strength": "medium; observed errors are clear, cause is a hypothesis"},
        {"area": "training / capacity and optimization", "evidence": "Validation improves from ckpt11 to ckpt33; under the corrected row-level safety unit, unsafe rows are 24, 12, 11, while loss falls 1.8061, 1.6279, 1.6060. Structure stays 11/24 from ckpt22 to ckpt33; schema-valid rises 12 to 13.", "hypothesis": "Additional optimization might improve some metrics, but available checkpoints do not show broad structured convergence and do not isolate capacity, LR, data, or prompt effects.", "proposed_change": "Do not increase epochs/rank based on this run alone. After data and grounding fixes, test one training variable in a separately versioned, budget-capped validation run.", "validation": "Same data/serialization; vary only one optimizer/model parameter; select on validation with row-level safety first and report schema/type/field metrics. No test/hard retuning.", "evidence_strength": "high for saved metrics; causal diagnosis is unsupported"},
    ]
    write(OUT / "root_cause_matrix.json", {"status": "diagnostic hypotheses; no v0.1 source data changed", "items": root_causes})

    experiments = [
        {"id": "V02-A", "variable": "canonical business-state coverage", "change": "Add a small, pre-registered set of new canonical decision states (recommended initial budget: 12 states, one or two reviewed surface forms each) in weak capability areas; do not count paraphrases as new GT states.", "hold_fixed": "Contract/schema, serializer, prompt, optimizer, model, training budget, and existing family split policy.", "evaluation": "Validation-only on newly sealed families plus existing validation for comparability; no test/hard selection. Stratify tool routing, clarification, proposal binding, guarded operations and policy/read results.", "primary_metric": "unsafe validation rows (one row once), then expected branch/schema and key-fact accuracy", "gate": "No added dangerous proposal/tool call; every expected fact has model-visible evidence or the sample is excluded from answerable evaluation.", "budget": "12 new GT states; max 24 train surface records; one training run capped at the v0.1 optimizer-step budget", "priority": 1},
        {"id": "V02-B", "variable": "runtime verified-result payload serialization", "change": "For authoritative read results, compare ID-only context with a sanitized, bounded result payload containing the exact values/policy text keyed by the same result ID. Requires authoritative payloads; never synthesize them.", "hold_fixed": "Same canonical states/surface, expected output, contract, prompt, model, optimizer, and training-step budget; only runtime context serialization differs.", "evaluation": "Paired validation cases where source IDs and payloads are independently verified; new sealed scenario families; retain current heldout only as legacy diagnostic.", "primary_metric": "grounded amount/entity/policy facts, evidence ID correctness and hallucinated/contradictory natural-language facts", "gate": "No result payload without source provenance; zero cross-ID payload binding; no change to business rules.", "budget": "Up to 12 matched examples, one small run at the existing step budget", "priority": 2},
        {"id": "V02-C", "variable": "concise contract guidance in model-visible system prompt", "change": "A/B test a short, frozen-catalog-derived intent/tool/argument and current-user-binding reminder against the existing concise system prompt.", "hold_fixed": "Dataset content/splits, runtime context, model, optimizer, steps, and output contract.", "evaluation": "Validation only on new sealed or existing validation families; no test/hard tuning.", "primary_metric": "intent-tool mapping, argument/schema validity and clarification-versus-proposal routing, with safety as hard gate", "gate": "No scope expansion, no loosening write confirmation, and no worse unsafe-row count.", "budget": "One prompt variant and at most one capped training run; only after V02-A/B data gaps are addressed", "priority": 3},
    ]
    write(OUT / "v02_experiment_plan.json", {"status": "design only; no v0.2 samples or training created", "max_experiments": 3, "test_policy": "The v0.1 test and hard_test have been inspected and are legacy diagnostics only; future selection uses validation and newly sealed family-isolated evaluation.", "experiments": experiments})

    # Compact self-contained report with links to complete machine-readable tables.
    counts = fail["category_counts"]
    train_rows = [s for s in samples if s["split"] == "train"]
    state_counts = {"samples": len(train_rows), "families": len({s["scenario_family_id"] for s in train_rows}),
                    "scenarios": len({s["scenario_id"] for s in train_rows}),
                    "exact_gt": len({json.dumps(s["expected"]["model_output"], ensure_ascii=False, sort_keys=True) for s in train_rows}),
                    "gold": sum(s.get("source", {}).get("surface_form_type") != "teacher_generated" for s in train_rows),
                    "teacher": sum(s.get("source", {}).get("surface_form_type") == "teacher_generated" for s in train_rows)}
    best = trajectory["checkpoints"]
    paired = trajectory["paired_checkpoint_22_to_33_changes"]["metrics"]
    target = token_counts["grouped"]["output_type"]
    text = f'''# Training v0.1 Failure Analysis and Dataset Gap Analysis

This report analyzes saved QLoRA v0.1 outputs only. It does not run inference, train, or alter any frozen source, checkpoint, or training setup. The diagnostic artifacts live alongside this report and the source script is [analyze_v01.py](../../../../scripts/ai_training_analysis/analyze_v01.py); the semantic-case/report builder is [build_v01_report.py](../../../../scripts/ai_training_analysis/build_v01_report.py).

## Evaluation outcome

Best-checkpoint-22 held-out results: validation 24 rows (schema-valid {best['checkpoint_22']['schema_valid']}/24, type-correct {best['checkpoint_22']['type_correct']}/24, business-structure exact {best['checkpoint_22']['business_structure_match']}/24, unsafe {best['checkpoint_22']['unsafe_rows']}/24); test 37 rows (schema-valid 19/37, type-correct 21/37, structure 13/37, unsafe 18/37); hard_test 12 rows (schema-valid 6/12, type-correct 9/12, structure 6/12, unsafe 6/12). “Unsafe” counts each record once if any frozen contract-safety violation is present. These are offline output evaluations; no tool was executed.

The output-type confusion matrix is answer 31/33 predicted answer, clarification 12/18, proposal 0/14 (all 14 routed to clarification), and tool_call 7/8. Full matrix: [output_routing_confusion.json](output_routing_confusion.json). Best22’s aggregate manual factual review covered its 30 business-structure matches: 4 correct, 5 partial, 21 incorrect/unsupported. This is separate from `schema_valid` and structure metrics.

The 73-row failure matrix includes every held-out sample, expected/predicted type, source split, schema required/extra/type errors, GT leaf differences, safety flags, challenge tags, and human review when available: [failure_matrix.csv](failure_matrix.csv) and [failure_matrix.json](failure_matrix.json). Failure labels overlap and must not be summed as unique rows. Counts: field-value mismatch {counts.get('field_value_mismatch',0)}, entity-resolution mismatch {counts.get('entity_resolution',0)}, UI-context-related discrepancy {counts.get('ui_context_grounding',0)}, output-routing discrepancy {counts.get('output_type_routing',0)}, clarification-necessity discrepancy {counts.get('clarification_necessity',0)}, proposal-routing discrepancy {counts.get('proposal_routing',0)}, schema-formatting invalid {counts.get('schema_formatting',0)}, unexpected output fields {counts.get('unexpected_output_field',0)}. `hallucinated_fact` is restricted to human-reviewed contradictory/incorrect text cases; it is not inferred from a regex. `missing_fact` and `field_value_mismatch` are mechanical GT-path comparisons and do not independently prove a causal source gap.

## Training-to-held-out comparison

The training split has {state_counts['samples']} samples, {state_counts['families']} Families, {state_counts['scenarios']} canonical scenarios, {state_counts['exact_gt']} exact GT outputs, {state_counts['gold']} Gold and {state_counts['teacher']} Teacher surfaces. All 36 training scenarios have one exact business-state/GT anchor each; the 106 Teacher rows provide surface/context variation while preserving that anchor, not 106 new business decisions. The 73 held-out rows cover 16 Families and 16 canonical states (validation 5, test 8, hard_test 3). No held-out Family appears in train by design; that is family isolation, not leakage or a missing-family defect. Transfer is therefore assessed through shared intent/output/task capability peers in [train_heldout_coverage.json](train_heldout_coverage.json), not exact same-Family examples.

Train task counts are proposal_generation 31, clarification 45, result_explanation 25, tool_call 22, rule_qa 21, error_handling 18, parameter_extraction 17, interaction_context_reasoning 17, ui_context_reasoning 14, entity_resolution 14, conversation_context_reasoning 14, intent_classification 6, unsupported_detection 6. By expected output: proposal 46 samples/10 canonical states, clarification 51/11, tool_call 24/5, answer 44/9, unsupported 6/1. These are not independent unique states beyond the 36-scenario total.

## Expected-output complexity and visible context

Tokenizer-only counts use the frozen local tokenizer, the saved LLaMA-Factory `qwen3_5_nothink` template and setup serialization; no model weights were loaded. By expected type, target token mean/median/max are: answer {target['answer']['target_tokens']['mean']}/{target['answer']['target_tokens']['median']}/{target['answer']['target_tokens']['max']}, clarification {target['clarification']['target_tokens']['mean']}/{target['clarification']['target_tokens']['median']}/{target['clarification']['target_tokens']['max']}, proposal {target['proposal']['target_tokens']['mean']}/{target['proposal']['target_tokens']['median']}/{target['proposal']['target_tokens']['max']}, tool_call {target['tool_call']['target_tokens']['mean']}/{target['tool_call']['target_tokens']['median']}/{target['tool_call']['target_tokens']['max']}, unsupported {target['unsupported']['target_tokens']['mean']}/{target['unsupported']['target_tokens']['median']}/{target['unsupported']['target_tokens']['max']}. Proposal targets have a skewed distribution (mean below median) and the longest frozen target is 665 tokens. Proposal outputs also have the most required paths, leaves and nesting; see [complexity_and_context.json](complexity_and_context.json) and [tokenizer_counts.json](tokenizer_counts.json). Schema complexity counts active GT-branch recursive required paths, JSON depth/leaves and enum/const schema nodes; it does not claim a learned cognitive complexity score.

Across the 244 assigned serialized rows, runtime-context JSON is median 849 characters (mean 893.73, max 1515), median depth 3/max 5, mean 15.525 scalar leaves, with a mean 5.832 empty containers and 1.389 excess repeated scalar occurrences. This gives measurable evidence of some null/empty/repeated fields, but does not measure attention or prove context length caused errors.

For expected non-natural structured leaves in the 73 held-out cases, 605 paths were traced against the actual serialized input. On the sensitive key-path rule `id/amount/currency/payment/payer/participant`, 328 expected leaf occurrences split as 126 matched a relevant runtime-context path, 68 appeared literally in the current user turn, 50 had the same value somewhere else in context without a reliable semantic path, and 84 had no literal match. Literal presence does not prove semantic binding, and no literal match does not prove the fact was unavailable: normalization, derivation or implicit reference resolution can apply. Full row/path evidence: [grounding_field_trace.json](grounding_field_trace.json). `scenario.state` and `evidence_refs` are not treated as model-visible; the latter are not automatically inserted by the training serializer.

Semantic checks were performed on five saved rows and are recorded with actual inputs/outputs in [grounding_case_reviews.json](grounding_case_reviews.json). Two tool-call rows have visible IDs/tools but wrong intent/extra arguments (`sample_gs_p0_028`, `sample_gs_p0_027`). An expense proposal row has visible amount/title/date/self-payer/context but asks for an unsupported `account_id` (`sample_gs_p0_005`). Two answer rows demonstrate stronger data gaps: `sample_gs_p0_032` receives verified result IDs but no result DTO payload for the expected JPY/CNY amounts; `sample_gs_p0_092` receives a verified rule-result ID but no policy text needed for the creator-only unarchive rule. Their actual responses contain unsupported/contradictory content. These row findings support a missing serialized payload for these examples; they are not generalized from ID strings alone.

## Checkpoint and routing findings

Validation-only checkpoint trajectory, using one-unsafe-row-once: checkpoint11 24 unsafe/24, checkpoint22 12/24, checkpoint33 11/24. Corresponding eval losses are {best['checkpoint_11']['eval_loss']:.4f}, {best['checkpoint_22']['eval_loss']:.4f}, {best['checkpoint_33']['eval_loss']:.4f}; structure matches are 0, 11, 11 and schema-valid rows 0, 12, 13. Therefore the corrected diagnostic rank puts checkpoint33 before 22 before 11, while the historical run chose 22 under its prior flag-instance interpretation; the saved selection is preserved. Checkpoint33 has 11 unsafe rows but 23 overlapping flag instances versus checkpoint22’s 12 rows and 22 flags, so the row-count revision is explicit. Paired validation changes from checkpoint22 to checkpoint33: schema-valid {paired['schema_valid']['improved_rows']} improved / {paired['schema_valid']['regressed_rows']} regressed rows; type-correct {paired['type_correct']['improved_rows']} / {paired['type_correct']['regressed_rows']}; business-structure {paired['business_structure_match']['improved_rows']} / {paired['business_structure_match']['regressed_rows']}; safe-row status {paired['safe_row']['improved_rows']} / {paired['safe_row']['regressed_rows']}; field-fact correct-leaf counts improved in {paired['field_facts_correct']['improved_rows']} rows and regressed in {paired['field_facts_correct']['regressed_rows']}; key-fact counts improved in {paired['key_facts_correct']['improved_rows']} and regressed in {paired['key_facts_correct']['regressed_rows']}. For row-status metrics, improved means false-to-true; for fact counts, increased/decreased correct fields. This modest safety gain does not establish broad business correctness, and no test/hard data was used for ranking. See [checkpoint_trajectory.json](checkpoint_trajectory.json).

## Evidence-led gaps and proposed v0.2 work

The [root_cause_matrix.json](root_cause_matrix.json) separates measured evidence from causal hypotheses. The strongest supported representation gap is ID-only verified results without the business DTO/policy payload in the serialized input for the two inspected answer cases. Train coverage shows many Teacher surface variants but only one canonical state per training Scenario. The output errors also include correct-looking entity values with wrong intent or non-contract fields, so explicit schema/intent-tool guidance is a testable hypothesis, not a proven cause. Checkpoint loss decreases do not justify more epochs or rank changes on their own.

The [v02_experiment_plan.json](v02_experiment_plan.json) proposes at most three one-variable experiments: (A) add a small set of canonical decision states; (B) test authoritative verified-result payload serialization; (C) test concise contract guidance. It defines controlled factors, validation-only metrics, data safety gates and budgets. These are plans only. The v0.1 test/hard_test have been inspected and are legacy diagnostics, not future tuning sets; new evaluation families must remain family-isolated and sealed.

## Reproducibility and source integrity

The analysis script consumes saved generation records, canonical files and LLaMA-Factory export rows. It checks 73 unique held-out rows, maps all 244 assigned exported rows to traceability, and requires conversation round-trip verification. [analysis_manifest.json](analysis_manifest.json) records SHA-256 for frozen Canonical/Training Setup/Contract/Scope/Schema/Catalog sources and saved checkpoint artifacts, and output hashes for analysis artifacts. The training-run baseline source snapshot check confirms {sum(x['matches_baseline'] for x in integrity)}/{len(integrity)} files unchanged in [source_integrity_check.json](source_integrity_check.json). No frozen source, checkpoint, prompt or setup was changed by this analysis. The report does not authorize Teacher generation, dataset changes, test-set tuning or another training run.
'''
    (OUT / "FINAL_REPORT.md").write_text(text, encoding="utf-8")
    manifest_path = OUT / "analysis_manifest.json"
    manifest = read(manifest_path)
    manifest["artifacts_sha256"] = {
        p.name: __import__("hashlib").sha256(p.read_bytes()).hexdigest()
        for p in OUT.iterdir() if p.is_file() and p.name != manifest_path.name
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
