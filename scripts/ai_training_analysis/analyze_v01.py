#!/usr/bin/env python3
"""Read-only failure and dataset-gap analysis for the frozen QLoRA v0.1 run."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
DEFAULT_RUN = Path(r"D:\AI\runs\shared-ledger\training_runs\qlora-v0.1\20260930-143013")
CANONICAL = ROOT / "docs/ai/dataset/canonical_training/v0.1"
SETUP = ROOT / "docs/ai/training_setup/v0.1"
SCHEMA_PATH = ROOT / "docs/ai/schema/model_output.schema.json"
CATALOG_PATH = ROOT / "docs/ai/schema/tool_catalog.json"
CONTRACT = ROOT / "docs/ai/AI_MODEL_CONTRACT.md"
SCOPE = ROOT / "docs/ai/AI_SCOPE_FREEZE_V0.1.md"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def compact(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(x: Any) -> str:
    return hashlib.sha256(compact(x).encode("utf-8")).hexdigest()


def leaves(value: Any, path: str = "$") -> list[tuple[str, Any]]:
    if isinstance(value, dict):
        return [z for k, v in value.items() for z in leaves(v, f"{path}.{k}")]
    if isinstance(value, list):
        return [z for i, v in enumerate(value) for z in leaves(v, f"{path}[{i}]")]
    return [(path, value)]


def deep_diffs(expected: Any, actual: Any, path: str = "$") -> tuple[list[str], list[str]]:
    missing: list[str] = []
    extra: list[str] = []
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [path], []
        for k, v in expected.items():
            if k not in actual:
                missing.extend(z[0] for z in leaves(v, f"{path}.{k}"))
            else:
                a, b = deep_diffs(v, actual[k], f"{path}.{k}")
                missing.extend(a); extra.extend(b)
        for k, v in actual.items():
            if k not in expected:
                extra.extend(z[0] for z in leaves(v, f"{path}.{k}"))
    elif isinstance(expected, list):
        if not isinstance(actual, list):
            return [path], []
        for i, v in enumerate(expected):
            if i >= len(actual):
                missing.extend(z[0] for z in leaves(v, f"{path}[{i}]"))
            else:
                a, b = deep_diffs(v, actual[i], f"{path}[{i}]")
                missing.extend(a); extra.extend(b)
        for i in range(len(expected), len(actual)):
            extra.extend(z[0] for z in leaves(actual[i], f"{path}[{i}]"))
    elif expected != actual:
        missing.append(path)
    return missing, extra


def leaf_comparison(expected: Any, actual: Any) -> tuple[list[str], list[str], list[str]]:
    """Return absent expected leaves, differing shared leaves, and extra actual leaves."""
    exp = dict(leaves(expected))
    act = dict(leaves(actual)) if actual is not None else {}
    missing = sorted(set(exp) - set(act))
    extra = sorted(set(act) - set(exp))
    mismatch = sorted(p for p in set(exp) & set(act) if exp[p] != act[p])
    return missing, mismatch, extra


def runtime_context(sample: dict[str, Any]) -> dict[str, Any]:
    inp = sample["input"]
    client, ui = inp.get("client_context", {}), inp.get("ui_context", {})
    user, page = inp.get("user_context", {}), inp.get("page_state", {})
    conv, server = inp.get("conversation_context", {}), inp.get("server_context", {})
    return {
        "platform": client.get("platform"), "app_version": client.get("app_version"),
        "locale": client.get("locale"), "timezone": client.get("timezone"),
        "ui": {"route": ui.get("route"), "page_type": ui.get("page_type"),
               "activity_id": ui.get("activity_id"), "ledger_unit_id": ui.get("ledger_unit_id"),
               "selected_entity": ui.get("selected_entity"), "form_mode": ui.get("form_mode"),
               "focused_field": ui.get("focused_field")},
        "user": {"claimed_participant_id": user.get("claimed_participant_id"), "role_hint": user.get("role_hint")},
        "page_state": {"load_state": page.get("load_state"),
                       "financial_version_hint": page.get("financial_version_hint"),
                       "entity_version_hint": page.get("entity_version_hint"), "filters": page.get("filters"),
                       "visible_entities": page.get("visible_entities"), "draft": page.get("draft"),
                       "write_state": page.get("write_state")},
        "recent_actions": inp.get("recent_actions", []),
        "conversation_state": {"confirmed_bindings": conv.get("confirmed_bindings", []),
                               "pending_clarification": conv.get("pending_clarification")},
        "runtime_policy": {"enabled_tools": server.get("enabled_tools", []),
                           "verified_result_ids": server.get("verified_result_ids", []),
                           "confirmation_policy": server.get("confirmation_policy"),
                           "tool_results": server.get("tool_results", [])},
    }


def nested_depth(x: Any) -> int:
    if isinstance(x, dict): return 1 + max((nested_depth(v) for v in x.values()), default=0)
    if isinstance(x, list): return 1 + max((nested_depth(v) for v in x), default=0)
    return 0


def count_empty_containers(x: Any) -> int:
    if isinstance(x, dict):
        return int(not x) + sum(count_empty_containers(v) for v in x.values())
    if isinstance(x, list):
        return int(not x) + sum(count_empty_containers(v) for v in x)
    return 0


def count_schema_keywords(branch: dict[str, Any], catalog: dict[str, Any], root_schema: dict[str, Any]) -> dict[str, int]:
    from scripts.ai_training_evaluation.evaluate_generation import resolve_ref
    counts = Counter()
    seen_refs: set[str] = set()
    def walk(node: Any, base_path: str = "") -> None:
        if isinstance(node, list):
            for item in node: walk(item, base_path)
        elif isinstance(node, dict):
            if "$ref" in node:
                ref = node["$ref"]
                if ref not in seen_refs:
                    seen_refs.add(ref)
                    walk(resolve_ref(ref, root_schema.get("$id", ""), root_schema, catalog), ref)
            for key in ("const", "enum"):
                if key in node: counts[key] += 1
            for key, value in node.items():
                if key != "$ref": walk(value, base_path)
    walk(branch)
    return {"const_schema_nodes": counts["const"], "enum_schema_nodes": counts["enum"]}


def expected_branch(expected: dict[str, Any], schema: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any] | None:
    from scripts.ai_training_evaluation.evaluate_generation import validate_schema
    matches = [b for b in schema["oneOf"] if not validate_schema(expected, b, schema, catalog)]
    return matches[0] if len(matches) == 1 else None


def field_source_hits(value: Any, key: str, ctx: dict[str, Any], turns: list[dict[str, str]]) -> dict[str, Any]:
    context_hits = []
    for path, v in leaves(ctx):
        if v == value and value is not None:
            context_hits.append(path)
    current_hits, history_hits = [], []
    sval = str(value) if value is not None and not isinstance(value, (dict, list, bool)) else None
    if sval and len(sval) >= 2:
        for i, turn in enumerate(turns):
            if sval in turn["content"]:
                (history_hits if i < len(turns) - 1 else current_hits).append(i)
    key_l = key.lower()
    hints = []
    if "activity" in key_l: hints += ["$.ui.activity_id", "$.ui.route", "$.conversation_state.active_activity_id"]
    if "ledger" in key_l or "unit" in key_l: hints += ["$.ui.ledger_unit_id"]
    if "participant" in key_l or "payer" in key_l or "owner" in key_l or "actor" in key_l: hints += ["$.user.claimed_participant_id", "$.page_state.visible_entities", "$.runtime_policy.tool_results", "$.conversation_state.confirmed_bindings"]
    if "expense" in key_l or "transfer" in key_l or "prepayment" in key_l or "result" in key_l: hints += ["$.page_state.visible_entities", "$.page_state.draft", "$.recent_actions", "$.runtime_policy.verified_result_ids", "$.runtime_policy.tool_results"]
    matching_hints = [p for p in context_hits if any(p.startswith(h) for h in hints)]
    if matching_hints: status = "matched_relevant_runtime_context_path"
    elif context_hits: status = "same_value_in_context_other_path_or_unscoped"
    elif current_hits: status = "literal_in_current_user_turn_not_semantic_binding_proof"
    elif history_hits: status = "literal_in_history_not_semantic_binding_proof"
    else: status = "no_literal_match_semantic_or_normalization_possible"
    return {"status": status, "context_paths": context_hits[:10], "current_user_turn_indexes": current_hits,
            "history_turn_indexes": history_hits, "relevant_key_hints": hints}


def family_summaries(samples: list[dict[str, Any]], scenarios: dict[str, dict[str, Any]], traces: dict[str, dict[str, Any]]) -> dict[str, Any]:
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in samples: by_family[s["scenario_family_id"]].append(s)
    result = {}
    for fam, rows in sorted(by_family.items()):
        gt_sig = {canonical_hash(s["expected"]["model_output"]) for s in rows}
        decision_sigs = set()
        state_sigs = set()
        contexts = set(); surfaces = set()
        scenario_ids = set()
        src = Counter()
        for s in rows:
            gt = json.loads(json.dumps(s["expected"]["model_output"], ensure_ascii=False))
            def strip_natural(x: Any, parent: str = "") -> Any:
                if isinstance(x, dict): return {k: strip_natural(v, k) for k, v in x.items() if k not in {"content", "question", "summary"}}
                if isinstance(x, list): return [strip_natural(v, parent) for v in x]
                return x
            decision_sigs.add(canonical_hash(strip_natural(gt)))
            scenario = scenarios[s["scenario_id"]]
            state_sigs.add(canonical_hash(scenario.get("state", {})))
            contexts.add(canonical_hash(runtime_context(s)))
            surfaces.add(canonical_hash({"user_message": s["surface_form"].get("user_message"), "conversation": s["surface_form"].get("conversation", [])}))
            scenario_ids.add(s["scenario_id"])
            source_type = s.get("source", {}).get("surface_form_type", "unknown")
            src["Teacher" if source_type == "teacher_generated" else "Gold/human"] += 1
        sample = rows[0]; scenario = scenarios[sample["scenario_id"]]
        result[fam] = {"family_id": fam, "scenario_ids": sorted(scenario_ids), "canonical_scenario_count": len(scenario_ids),
                       "sample_count": len(rows), "gold_sample_count": src["Gold/human"], "teacher_sample_count": src["Teacher"],
                       "unique_exact_ground_truth_count": len(gt_sig), "unique_decision_signature_count": len(decision_sigs),
                       "unique_business_state_count": len(state_sigs), "unique_runtime_context_state_count": len(contexts),
                       "unique_surface_variant_count": len(surfaces), "output_type": sample["expected"]["output_type"],
                       "intent_ids": scenario.get("ground_truth", {}).get("intent_ids", []),
                       "task_primary": sample.get("task", {}).get("primary"),
                       "rule_tags": scenario.get("rule_tags", []), "ai_scope": sample.get("scope", {}).get("ai_scope"),
                       "business_state_ids": sorted({v for path, v in leaves(scenario.get("state", {})) if "id" in path.lower() and isinstance(v, str)})}
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=DEFAULT_RUN)
    ap.add_argument("--out", type=Path, default=ROOT / "docs/ai/training_analysis/v0.1")
    args = ap.parse_args()
    out = args.out; out.mkdir(parents=True, exist_ok=True)
    samples = read_json(CANONICAL / "samples.json")
    scenarios_list = read_json(CANONICAL / "scenarios.json")
    scenarios = {x["scenario_id"]: x for x in scenarios_list}
    train_samples = {x["sample_id"]: x for x in samples}
    traces = {x["sample_id"]: x for x in read_json(SETUP / "traceability.json")}
    schema = read_json(SCHEMA_PATH); catalog = read_json(CATALOG_PATH)
    contract_diag = read_json(args.run / "contract_field_diagnostics.json")
    diag_rows = {k: {x["sample_id"]: x for x in contract_diag[k]["rows"]} for k in ("baseline", "best_checkpoint_22")}
    manual_doc = read_json(args.run / "manual_content_review.json")
    manual = {x["sample_id"]: x for x in manual_doc["records"]}
    fail_index = read_json(args.run / "failure_case_index.json")
    old_fail = {x["sample_id"]: x for x in fail_index["records"]}
    eval_dirs = {
        "baseline": args.run / "baseline/records.jsonl",
        "checkpoint_11": args.run / "eval/checkpoint-11-validation/records.jsonl",
        "checkpoint_22": args.run / "eval/checkpoint-22-validation/records.jsonl",
        "checkpoint_33": args.run / "eval/checkpoint-33-validation/records.jsonl",
        "best22_heldout": args.run / "eval/best-checkpoint-22-test-hard/records.jsonl",
    }
    record_sets = {k: read_jsonl(v) for k, v in eval_dirs.items()}
    best73 = record_sets["checkpoint_22"] + record_sets["best22_heldout"]
    assert len(best73) == 73 and len({r["sample_id"] for r in best73}) == 73
    assert all(r["sample_id"] in train_samples for r in best73)
    assert all(r["sample_id"] in traces and traces[r["sample_id"]]["history_roundtrip_verified"] for r in best73)
    # Use the actual serialized training lines to inspect what the model could see.
    train_lines: dict[str, dict[str, Any]] = {}
    for split in ("train", "validation", "test", "hard_test"):
        path = SETUP / f"llamafactory/{split}.json"
        rows = read_json(path)
        expected_ids = [sid for sid, t in traces.items() if t["split"] == split]
        target_hash_to_id: dict[str, list[str]] = defaultdict(list)
        for sid in expected_ids: target_hash_to_id[traces[sid]["canonical_expected_sha256"]].append(sid)
        seen = set()
        for row in rows:
            target = row["conversations"][-1]["content"]
            h = hashlib.sha256(target.encode("utf-8")).hexdigest()
            candidates = [sid for sid in target_hash_to_id.get(h, []) if sid not in seen]
            if not candidates: continue
            sid = candidates[0]; seen.add(sid); train_lines[sid] = row
        assert len(seen) == len(rows), f"training export target mapping incomplete for {split}: {len(seen)}/{len(rows)}"
    # Expected branch and schema diagnostics are reused, not re-scored.
    from scripts.ai_training_evaluation.evaluate_generation import validate_schema
    matrix = []
    field_traces = []
    category_count = Counter()
    category_defs = ["output_type_routing", "clarification_necessity", "clarification_slot", "proposal_routing",
                     "proposal_diff", "tool_selection", "tool_arguments", "entity_resolution", "pronoun_or_me_binding",
                     "amount_or_currency", "evidence_or_result_id", "ui_context_grounding", "conversation_history",
                     "confirmation_policy", "execution_allowed", "hallucinated_fact", "missing_fact", "unsupported_fact", "schema_formatting"]
    category_defs.extend(["field_value_mismatch", "unexpected_output_field"])
    for rec in best73:
        sid=rec["sample_id"]; src=train_samples[sid]; scenario=scenarios[src["scenario_id"]]
        exp=rec["expected_output"]; actual=rec.get("parsed_output"); typ=exp.get("type"); pred=actual.get("type") if isinstance(actual,dict) else None
        drow=diag_rows["best_checkpoint_22"][sid]
        diff_missing,diff_values,diff_extra=leaf_comparison(exp,actual)
        changed_paths=diff_missing+diff_values+diff_extra
        tags=[]; evidence=[]
        if pred != typ: tags.append("output_type_routing"); evidence.append("expected/output type differ")
        if typ=="clarification" and pred!="clarification" or typ!="clarification" and pred=="clarification": tags.append("clarification_necessity")
        if typ=="clarification" and pred=="clarification":
            fields=("intent_id","reason","missing_fields","candidates")
            if any(not isinstance(actual,dict) or actual.get(k)!=exp.get(k) for k in fields): tags.append("clarification_slot")
        if typ=="proposal" and pred!="proposal": tags.append("proposal_routing")
        actual_preview=actual.get("preview") if isinstance(actual,dict) else None
        actual_preview=actual_preview if isinstance(actual_preview,dict) else {}
        if typ=="proposal" and pred=="proposal" and (actual.get("operation")!=exp.get("operation") or actual_preview.get("diff")!=exp.get("preview",{}).get("diff")):
            tags.append("proposal_diff")
        if typ=="tool_call" and pred=="tool_call":
            if actual.get("tool")!=exp.get("tool") or actual.get("intent_id")!=exp.get("intent_id"): tags.append("tool_selection")
            if actual.get("arguments")!=exp.get("arguments"): tags.append("tool_arguments")
        if any(re.search(r"(^|\.)([^.]*_id|[^.]*_ids)$",p) for p in changed_paths): tags.append("entity_resolution")
        msg=src["surface_form"].get("user_message",""); history=src["surface_form"].get("conversation",[])
        pronoun=any(w in msg for w in ("我","自己","我的","我们")) or any(w in compact(history) for w in ("我","自己","我的","我们"))
        if pronoun and "entity_resolution" in tags: tags.append("pronoun_or_me_binding")
        if any(re.search(r"amount|currency|payment|split|rate|total",p,re.I) for p in changed_paths): tags.append("amount_or_currency")
        if any(re.search(r"evidence_result_ids|result_id",p,re.I) for p in changed_paths): tags.append("evidence_or_result_id")
        if src["input"].get("ui_context") and any(re.search(r"activity_id|ledger_unit_id|selected_entity|expense_id|participant_id",p,re.I) for p in changed_paths): tags.append("ui_context_grounding")
        if history and (pred!=typ or changed_paths): tags.append("conversation_history")
        if typ=="proposal" and pred=="proposal" and actual.get("confirmation")!=exp.get("confirmation"): tags.append("confirmation_policy")
        if typ=="proposal" and pred=="proposal" and actual.get("execution_policy")!=exp.get("execution_policy"): tags.append("execution_allowed")
        if diff_missing: tags.append("missing_fact")
        if diff_values: tags.append("field_value_mismatch")
        review=manual.get(sid)
        if review and review.get("human_factual_review") in ("incorrect","unsupported","contradictory"):
            tags.append("hallucinated_fact")
        if review and review.get("human_factual_review") == "partial": tags.append("missing_fact")
        if review and "unsupported" in review.get("review_note","").lower(): tags.append("unsupported_fact")
        if diff_extra: tags.append("unexpected_output_field")
        if not rec["evaluation"].get("schema_valid"): tags.append("schema_formatting")
        categories=sorted(set(tags))
        category_count.update(categories)
        # Human-factual review only exists for projection-match rows; do not infer it for unreviewed rows.
        actual_schema_errors=drow.get("invalid_schema_errors",[])
        row={"sample_id":sid,"scenario_id":src["scenario_id"],"family_id":src["scenario_family_id"],"split":src["split"],
             "expected_type":typ,"difficulty":src["difficulty"],"challenge_tags":src["challenge_tags"],
             "source":src["source"].get("surface_form_type"),"predicted_type":pred,
             "raw_json_valid":rec.get("raw_json_parse_ok"),"extractable_json_valid":rec.get("extractable_json_parse_ok"),
             "schema_valid":rec["evaluation"].get("schema_valid"),"required_missing_paths":drow.get("missing_required_paths",[]),
             "unexpected_field_paths":drow.get("unexpected_field_paths",[]),"invalid_value_type_schema_errors":actual_schema_errors,
             "business_structure_match":rec["evaluation"].get("normalized_business_structure_match"),
             "key_facts_correct":rec["evaluation"].get("key_facts_correct"),"key_facts_total":rec["evaluation"].get("key_facts_total"),
             "safety_violations":rec["evaluation"].get("contract_safety_violations",[]),"missing_target_leaf_paths":diff_missing,
             "mismatched_target_leaf_paths":diff_values,"extra_target_leaf_paths":diff_extra,"failure_categories":categories,
             "evidence_status":"mechanical path/value comparison; semantic cause requires source review",
             "human_text_review":review.get("human_factual_review") if review else "not_reviewed",
             "human_review_note":review.get("review_note") if review else None,
             "old_failure_case":old_fail.get(sid,{}).get("error_category")}
        matrix.append(row)
        # Trace every non-natural target leaf to only model-visible context/messages.
        line=train_lines[sid]; visible_context={}
        marker="運行時上下文（JSON）："
        if marker in line["system"]:
            text=line["system"].split(marker,1)[1]
            try: visible_context=json.JSONDecoder().raw_decode(text)[0]
            except Exception: visible_context=runtime_context(src)
        else: visible_context=runtime_context(src)
        conversations=line["conversations"][:-1]
        turns=[]
        for m in conversations:
            content=m["content"]
            group_marker="<|shared_ledger_turn_block_v1|>"
            if content.startswith(group_marker):
                turns.extend(json.loads(content[len(group_marker):]))
            else: turns.append(m)
        for path,value in leaves(exp):
            key=path.rsplit(".",1)[-1].split("[")[0]
            if key in {"content","question","summary"}: continue
            hit=field_source_hits(value,key,visible_context,turns)
            field_traces.append({"sample_id":sid,"scenario_id":src["scenario_id"],"family_id":src["scenario_family_id"],
                                 "expected_type":typ,"field_path":path,"expected_value":value,
                                 "actual_value":value_at(actual,path),"matches_actual":value_at(actual,path)==value,
                                 "visible_source":hit})
    # Route prediction confusion matrix; include null output explicitly.
    expected_classes=sorted({r["expected_type"] for r in matrix})
    predicted_classes=sorted({r["predicted_type"] or "<unparsed>" for r in matrix}|set(expected_classes))
    confusion={e:{p:0 for p in predicted_classes} for e in expected_classes}
    for r in matrix: confusion[r["expected_type"]][r["predicted_type"] or "<unparsed>"]+=1
    # Group source examples and failure families.
    family_stats=family_summaries(samples,scenarios,traces)
    failure_families=sorted({r["family_id"] for r in matrix if not r["business_structure_match"] or not r["schema_valid"]})
    train_by_family=defaultdict(list)
    for s in samples:
        if s["split"]=="train": train_by_family[s["scenario_family_id"]].append(s)
    coverage=[]
    for fam in failure_families:
        held=family_stats[fam]
        intents=set(held["intent_ids"]); task=held["task_primary"]; outtype=held["output_type"]
        train_candidates=[s for s in samples if s["split"]=="train"]
        same_intent=[s for s in train_candidates if intents.intersection(s.get("scope",{}).get("intent_ids",[]))]
        same_output=[s for s in train_candidates if s["expected"]["output_type"]==outtype]
        same_task=[s for s in train_candidates if s.get("task",{}).get("primary")==task]
        same_output_intent=[s for s in same_intent if s["expected"]["output_type"]==outtype]
        same_task_intent=[s for s in same_intent if s.get("task",{}).get("primary")==task]
        same_output_task=[s for s in train_candidates if s["expected"]["output_type"]==outtype and s.get("task",{}).get("primary")==task]
        peers=[s for s in same_output_task if intents.intersection(s.get("scope",{}).get("intent_ids",[]))]
        peer_families=defaultdict(list)
        for s in peers: peer_families[s["scenario_family_id"]].append(s)
        def peer_profile(rows):
            return {"samples":len(rows),"families":len({s["scenario_family_id"] for s in rows}),
                    "scenarios":len({s["scenario_id"] for s in rows}),
                    "exact_ground_truths":len({canonical_hash(s["expected"]["model_output"]) for s in rows})}
        coverage.append({**held,"heldout_failure_sample_count":sum(r["family_id"]==fam for r in matrix),
                         "heldout_failure_categories":dict(Counter(c for r in matrix if r["family_id"]==fam for c in r["failure_categories"])),
                         "same_family_train_samples":len(train_by_family.get(fam,[])),"same_family_train_canonical_scenarios":len({s["scenario_id"] for s in train_by_family.get(fam,[])}),
                         "train_peer_samples_same_output_task_and_intent":len(peers),"train_peer_families":len(peer_families),
                         "train_peer_distinct_gt":len({canonical_hash(s["expected"]["model_output"]) for s in peers}),
                         "train_capability_peers":{"shared_intent":peer_profile(same_intent),"shared_output_type":peer_profile(same_output),
                             "shared_task":peer_profile(same_task),"shared_output_and_intent":peer_profile(same_output_intent),
                             "shared_task_and_intent":peer_profile(same_task_intent),"shared_output_and_task":peer_profile(same_output_task),
                             "shared_output_task_and_intent":peer_profile(peers)},
                         "interpretation":"same-family zero is intentional family isolation; peer counts show transfer opportunity, not exact scenario-state equivalence"})
    # Dataset profile and business state/context/surface diversity by capability slice.
    all_stats=family_summaries(samples,scenarios,traces)
    slice_stats={}
    for label,pred in [
        ("clarification",lambda s:s["expected"]["output_type"]=="clarification"),
        ("proposal",lambda s:s["expected"]["output_type"]=="proposal"),
        ("tool_call",lambda s:s["expected"]["output_type"]=="tool_call"),
        ("context_heavy",lambda s:bool(set(s.get("challenge_tags",[]))&{"ui_reference","recent_action_reference","multi_turn","ellipsis","pronoun","stale_context","cross_activity_reference"})),
        ("entity_ambiguity",lambda s:bool(set(s.get("challenge_tags",[]))&{"multiple_candidates","pronoun","same_name_entity","missing_participants","missing_payer"})),
        ("financial_risk",lambda s:bool(set(s.get("challenge_tags",[]))&{"financial_risk","multi_currency","manual_split","missing_currency","missing_payer","missing_split_method"})),
        ("gated",lambda s:s.get("scope",{}).get("ai_scope")=="SUPPORTED_BUT_GATED"),
    ]:
        rr=[s for s in samples if pred(s) and s["split"]!="unassigned"]
        slice_stats[label]={"samples":len(rr),"train_samples":sum(s["split"]=="train" for s in rr),"heldout_samples":sum(s["split"]!="train" for s in rr),
                            "families":len({s["scenario_family_id"] for s in rr}),"canonical_scenarios":len({s["scenario_id"] for s in rr}),
                            "unique_gt":len({canonical_hash(s["expected"]["model_output"]) for s in rr}),
                            "gold":sum(s.get("source",{}).get("surface_form_type")!="teacher_generated" for s in rr),
                            "teacher":sum(s.get("source",{}).get("surface_form_type")=="teacher_generated" for s in rr)}
    # Context size, depth, emptiness and duplicate-value proxies from actual serialized rows.
    ctx_stats=[]
    for sid,line in train_lines.items():
        sm=train_samples[sid]; m="運行時上下文（JSON）："; text=line["system"].split(m,1)[1] if m in line["system"] else "{}"
        try:ctx=json.JSONDecoder().raw_decode(text)[0]
        except Exception:ctx=runtime_context(sm)
        vals=[v for _,v in leaves(ctx) if v is not None and not isinstance(v,(dict,list))]
        freq=Counter(compact(v) for v in vals)
        ctx_stats.append({"sample_id":sid,"split":sm["split"],"output_type":sm["expected"]["output_type"],"chars":len(compact(ctx)),"depth":nested_depth(ctx),
                          "scalar_leaf_count":len(vals),"null_leaf_count":sum(v is None for _,v in leaves(ctx)),
                          "empty_container_count":count_empty_containers(ctx),"repeated_value_groups":sum(n>1 for n in freq.values()),
                          "repeated_value_excess_occurrences":sum(n-1 for n in freq.values() if n>1),"top_repeated_values":[{"value":v,"count":n} for v,n in freq.most_common(5) if n>1]})
    # Complexity per active sample based on output branch validated by the frozen GT.
    from scripts.ai_training_evaluation.evaluate_generation import resolve_ref
    def req_count(value,sch,path="$",out=None):
        out=out or set()
        if "$ref" in sch: return req_count(value,resolve_ref(sch["$ref"],schema.get("$id",""),schema,catalog),path,out)
        for sub in sch.get("allOf",[]):req_count(value,sub,path,out)
        if isinstance(value,dict):
            for k in sch.get("required",[]):out.add(path+"."+k)
            for k,ps in sch.get("properties",{}).items():
                if k in value:req_count(value[k],ps,path+"."+k,out)
        elif isinstance(value,list) and "items" in sch:
            for i,v in enumerate(value):req_count(v,sch["items"],f"{path}[{i}]",out)
        for comb in ("oneOf","anyOf"):
            if comb in sch:
                matches=[x for x in sch[comb] if not validate_schema(value,x,schema,catalog)]
                if len(matches)==1:req_count(value,matches[0],path,out)
        return out
    complexity_by_type=defaultdict(list)
    for sm in samples:
        if sm["split"]=="unassigned":continue
        exp=sm["expected"]["model_output"]; branch=expected_branch(exp,schema,catalog)
        if branch is None: continue
        reqs=req_count(exp,branch)
        es,ex=deep_diffs(exp,exp)
        lf=leaves(exp)
        bound=[(p,v) for p,v in lf if any(tok in p.lower() for tok in ("_id","amount","currency","participant","payer","occurred_at","date","time","evidence"))]
        complexity_by_type[exp["type"]].append({"sample_id":sm["sample_id"],"family_id":sm["scenario_family_id"],"split":sm["split"],"target_chars":len(compact(exp)),
            "required_path_count":len(reqs),"json_depth":nested_depth(exp),"id_amount_entity_leaf_count":len(bound),"leaf_count":len(lf),
            "schema_constraints":count_schema_keywords(branch,catalog,schema),"gt_sha256":canonical_hash(exp)})
    # Routing matrix and checkpoint validation trajectory.
    trajectory={}
    for cp in ("checkpoint_11","checkpoint_22","checkpoint_33"):
        rs=record_sets[cp]; unsafe=sum(bool(r["evaluation"].get("contract_safety_violations")) for r in rs)
        trajectory[cp]={"records":len(rs),"raw_json":sum(bool(r.get("raw_json_parse_ok")) for r in rs),"extractable_json":sum(bool(r.get("extractable_json_parse_ok")) for r in rs),
            "schema_valid":sum(bool(r["evaluation"].get("schema_valid")) for r in rs),"type_correct":sum(bool(r["evaluation"].get("type_correct")) for r in rs),
            "business_structure_match":sum(bool(r["evaluation"].get("normalized_business_structure_match")) for r in rs),"unsafe_rows":unsafe,
            "violation_flag_counts":dict(Counter(flag for r in rs for flag in r["evaluation"].get("contract_safety_violations",[]))),
            "field_fact_correct":sum(r["evaluation"].get("field_facts_correct",0) for r in rs),"field_fact_total":sum(r["evaluation"].get("field_facts_total",0) for r in rs),
            "key_fact_correct":sum(r["evaluation"].get("key_facts_correct",0) for r in rs),"key_fact_total":sum(r["evaluation"].get("key_facts_total",0) for r in rs),
            "eval_loss":read_json(args.run/f"train/checkpoints/checkpoint-{cp[-2:]}/trainer_state.json").get("log_history",[])[-1].get("eval_loss") if (args.run/f"train/checkpoints/checkpoint-{cp[-2:]}/trainer_state.json").exists() else None,
            "type_confusion":dict(Counter(f"{r['expected_output'].get('type')}→{r['evaluation'].get('actual_type') or '<unparsed>'}" for r in rs))}
    # Full baseline->best output routing matrix (expected by v0.1 best22).
    route_matrix=confusion
    # Validate frozen GT coverage and input artifacts before writing.
    assert len(matrix)==73 and {r["sample_id"] for r in matrix}=={r["sample_id"] for r in best73}
    assert len(train_lines)==244
    # Save fine-grained diagnostics.
    write_json=lambda name,obj:(out/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    write_json("failure_matrix.json",{"basis":"Saved best22 raw outputs, frozen training export rows, expected contract branch; manual review only where available.","records":matrix,"category_counts":dict(category_count),"zero_categories":{c:category_count[c] for c in category_defs}})
    with (out/"failure_matrix.csv").open("w",encoding="utf-8-sig",newline="") as f:
        fields=["sample_id","scenario_id","family_id","split","expected_type","predicted_type","difficulty","challenge_tags","source","raw_json_valid","schema_valid","missing_required_count","unexpected_field_count","invalid_value_type_count","business_structure_match","key_facts_correct","key_facts_total","safety_violations","failure_categories","human_text_review","human_review_note"]
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for r in matrix:
            z=dict(r); z["challenge_tags"]=compact(z["challenge_tags"]);z["safety_violations"]=compact(z["safety_violations"]);z["failure_categories"]=compact(z["failure_categories"])
            z["missing_required_count"]=len(r["required_missing_paths"]);z["unexpected_field_count"]=len(r["unexpected_field_paths"]);z["invalid_value_type_count"]=len(r["invalid_value_type_schema_errors"])
            w.writerow({k:z.get(k) for k in fields})
    write_json("grounding_field_trace.json",{"basis":"Expected structured leaves compared against actual LLaMA-Factory serialized runtime JSON and reversible conversation turns, not hidden scenario state.","fields":field_traces})
    write_json("train_heldout_coverage.json",{"family_isolation_policy":"scenario_family_id and split_group closure; same-family train zero is intentional, inspect shared output+task+intent analogues.","failure_families":coverage,"capability_slices":slice_stats,"all_family_profile":family_stats})
    write_json("output_routing_confusion.json",{"rows":"expected output_type","columns":"predicted type; <unparsed> when no JSON object","matrix":route_matrix,"counts":{k:sum(v.values()) for k,v in route_matrix.items()}})
    write_json("complexity_and_context.json",{"target_complexity_by_expected_type":{k:v for k,v in complexity_by_type.items()},"runtime_context_profiles":ctx_stats,"context_profile_summary":summarize_numeric(ctx_stats,["chars","depth","scalar_leaf_count","null_leaf_count","empty_container_count","repeated_value_groups","repeated_value_excess_occurrences"]),"visible_grounding_status_counts":dict(Counter(f["visible_source"]["status"] for f in field_traces)),"visible_grounding_by_target_field":grounding_by_key(field_traces),"token_length_reference":read_json(SETUP/"validation_report.json")["target_tokens_by_output_type"],"token_length_note":"Existing LLaMA-Factory template token distributions are taken from frozen setup validation. The current report will add per-type arithmetic mean from tokenizer-only counts if available; no model weights are loaded."})
    ranked = sorted(
        trajectory,
        key=lambda x: (
            trajectory[x]["unsafe_rows"],
            -trajectory[x]["business_structure_match"],
            -safe_div(trajectory[x]["key_fact_correct"], trajectory[x]["key_fact_total"]),
            -trajectory[x]["schema_valid"],
            trajectory[x]["eval_loss"] or 999999,
            int(x.rsplit("_", 1)[1]),
        ),
    )
    write_json("checkpoint_trajectory.json", {
        "source": "saved validation records only", "checkpoints": trajectory,
        "paired_checkpoint_22_to_33_changes": paired_changes(record_sets["checkpoint_22"], record_sets["checkpoint_33"]),
        "selection_metric_revision": {
            "unit": "unsafe validation rows; each row counted once if any safety violation",
            "historical_best": "checkpoint-22; retained unchanged in original run artifacts",
            "diagnostic_rank": "recomputed below using row count first, then normalized business structure, key facts, schema-valid, eval loss, lower step",
            "ranked_checkpoints": ranked, "test_or_hard_used_for_rank": False,
        },
    })
    source_files=[CANONICAL/n for n in ["samples.json","scenarios.json","split_assignment.json","coverage_report.json","dataset_manifest.json"]]+[SETUP/n for n in ["traceability.json","manifest.json","validation_report.json","qlora.yaml"]]+[SCHEMA_PATH,CATALOG_PATH,CONTRACT,SCOPE]
    source_hashes={str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p):sha(p) for p in source_files if p.exists()}
    checkpoint_hashes={}
    for cp in (11,22,33):
        p=args.run/f"train/checkpoints/checkpoint-{cp}"
        if p.exists():
            checkpoint_hashes[str(p)]=[{"file":str(x.relative_to(args.run)),"sha256":sha(x),"bytes":x.stat().st_size} for x in p.rglob("*") if x.is_file() and x.suffix.lower() in {".safetensors",".bin",".json"}]
    write_json("analysis_manifest.json",{"analysis_version":"0.1","run_id":args.run.name,"dataset":{"samples":len(samples),"assigned_samples":244,"heldout_rows":73},"frozen_source_hashes_sha256":source_hashes,"checkpoint_file_hashes_sha256":checkpoint_hashes,"artifacts_sha256":{},"no_model_loaded":True,"no_inference_training_or_source_mutation":True})
    manifest_path=out/"analysis_manifest.json"; m=read_json(manifest_path)
    m["artifacts_sha256"]={p.name:sha(p) for p in out.iterdir() if p.is_file() and p.name!="analysis_manifest.json"}
    manifest_path.write_text(json.dumps(m,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def value_at(value: Any, path: str) -> Any:
    # Paths are produced by leaves() and contain only simple JSON property names / array indexes.
    try:
        parts=re.findall(r"\.([^.[\]]+)|\[(\d+)\]",path[1:])
        cur=value
        for key,index in parts:
            cur=cur[int(index)] if index else cur[key]
        return cur
    except Exception: return None


def safe_div(a: int, b: int) -> float:
    return a/b if b else 0.0


def summarize_numeric(rows: list[dict[str, Any]], keys: list[str]) -> dict[str, Any]:
    ret={}
    for key in keys:
        vals=sorted(r[key] for r in rows)
        if vals:
            ret[key]={"count":len(vals),"min":vals[0],"mean":round(statistics.mean(vals),3),"median":statistics.median(vals),"p90_indexed":vals[min(len(vals)-1,int(.9*(len(vals)-1)))],"max":vals[-1]}
    return ret


def grounding_by_key(fields: list[dict[str, Any]]) -> dict[str, Any]:
    out={}
    for f in fields:
        key=f["field_path"].rsplit(".",1)[-1].split("[")[0]
        x=out.setdefault(key,{"expected_occurrences":0,"actual_matches":0,"source_statuses":Counter()})
        x["expected_occurrences"]+=1;x["actual_matches"]+=bool(f["matches_actual"]);x["source_statuses"][f["visible_source"]["status"]]+=1
    return {k:{"expected_occurrences":v["expected_occurrences"],"actual_matches":v["actual_matches"],"source_statuses":dict(v["source_statuses"])} for k,v in out.items()}


def paired_changes(before_rows: list[dict[str, Any]], after_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Paired changes across the same saved validation rows; no new generation."""
    before = {x["sample_id"]: x for x in before_rows}
    after = {x["sample_id"]: x for x in after_rows}
    assert set(before) == set(after)
    metrics = {
        "schema_valid": lambda r: int(bool(r["evaluation"].get("schema_valid"))),
        "type_correct": lambda r: int(bool(r["evaluation"].get("type_correct"))),
        "business_structure_match": lambda r: int(bool(r["evaluation"].get("normalized_business_structure_match"))),
        "safe_row": lambda r: int(not bool(r["evaluation"].get("contract_safety_violations"))),
        "field_facts_correct": lambda r: int(r["evaluation"].get("field_facts_correct", 0)),
        "key_facts_correct": lambda r: int(r["evaluation"].get("key_facts_correct", 0)),
    }
    out = {"paired_records": len(before), "comparison": "checkpoint-22 validation to checkpoint-33 validation; saved records only",
           "metrics": {}}
    for name, fn in metrics.items():
        improved = regressed = unchanged = 0
        deltas = []
        for sid in before:
            delta = fn(after[sid]) - fn(before[sid]); deltas.append(delta)
            if delta > 0: improved += 1
            elif delta < 0: regressed += 1
            else: unchanged += 1
        out["metrics"][name] = {"improved_rows": improved, "unchanged_rows": unchanged,
                                "regressed_rows": regressed, "net_count_change": sum(deltas)}
    return out


if __name__ == "__main__":
    main()
